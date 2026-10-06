"""Summarise the E. coli comparison without treating missing reports as misses.

The saved truth and claim definitions remain unchanged. --allow-partial is for
progress snapshots; a final report requires every planned run and judgement.
"""
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from analyze import SPECIAL, named_identities, score
from fetch_ecoli import NOT_ORDINARY, overlaps, parse_feature_table, revcomp
from tools import read_fasta_sequence
from transcripts import python_error_outputs

MODELS = ("deepseek-v4.1-flash", "glm-5.3-flash")
CONDITIONS = ("file", "inline")


def validate_source(data, raw):
    sequence = read_fasta_sequence((raw / "U00096.3.fasta").read_text())
    features = parse_feature_table((raw / "U00096.3.ft").read_text())
    audit = []
    for path in sorted((data / "truth").glob("*.json")):
        truth = json.loads(path.read_text())
        source = truth["source"]
        window = sequence[source["start"] - 1:source["end"]]
        if source["strand"] == "-":
            window = revcomp(window)
        fasta = data / "loci" / f"{path.stem}.fasta"
        assert window == read_fasta_sequence(fasta.read_text()), f"source mismatch: {path.stem}"
        assert len(window) == truth["length"], f"length mismatch: {path.stem}"
        target = truth["target"]
        entry = {"locus": path.stem, "source": source, "fasta_sha256": hashlib.sha256(fasta.read_bytes()).hexdigest()}
        if target:
            assert 1 <= target["start"] <= target["end"] <= len(window)
            if source["strand"] == "-":
                start, end = source["end"] - target["end"] + 1, source["end"] - target["start"] + 1
            else:
                start, end = source["start"] + target["start"] - 1, source["start"] + target["end"] - 1
            if target["type"] == "mobile_element":
                assert any(f["key"] == "mobile_element" and f["start"] == start and f["end"] == end and
                           f["quals"].get("mobile_element_type") == f"insertion sequence:{target['name']}" for f in features)
            elif target["type"] == "frameshift":
                assert any(f["key"] == "CDS" and "ribosomal_slippage" in f["quals"] and
                           f["start"] == start and f["end"] == end for f in features)
                assert any(f["key"] == "gene" and f["start"] == start and f["end"] == end and
                           f["quals"].get("gene") == target["name"] for f in features)
            else:
                # Diagnostic motif scan, not replacement truth or exact boundaries.
                core = window[target["start"] - 1:target["end"]]
                motif = Counter(core[i:i + 29] for i in range(len(core) - 28)).most_common(1)[0][0]
                starts = [i + 1 for i in range(len(window) - 28)
                          if sum(a != b for a, b in zip(window[i:i + 29], motif)) <= 4]
                entry["repeat_diagnostic"] = {"motif": motif, "max_mismatches": 4, "starts": starts,
                                              "note": "Approximate conserved-core truth; scan is not an independently curated array annotation."}
        else:
            assert not any(overlaps(f, source["start"], source["end"]) and
                           (f["key"] in NOT_ORDINARY or "pseudo" in f["quals"] or "ribosomal_slippage" in f["quals"])
                           for f in features), f"special annotation in control: {path.stem}"
        audit.append(entry)
    return audit


def tally(records):
    scored = [r for r in records if r["score"] is not None]
    positive = [r for r in scored if r["score"]["positive"]]
    control = [r for r in scored if not r["score"]["positive"]]
    return {
        "saved": len(records), "scored": len(scored), "positive_scored": len(positive),
        "target_found": sum(r["score"]["claimed"] for r in positive),
        "target_located": sum(r["score"]["localized"] for r in positive),
        "control_scored": len(control), "control_special_claims": sum(r["score"]["claimed"] for r in control),
        "forced_reports": sum(r["forced_report"] for r in records),
        "empty_reports": sum(not r["report"] for r in records),
        "not_scored": len(records) - len(scored),
        "median_seconds": median(r["seconds"] for r in records) if records else None,
        "wrapper_errors": sum(r["tool_errors"] for r in records),
        "python_error_outputs": sum(r["python_error_outputs"] for r in records),
        "runs_with_python_errors": sum(r["python_error_outputs"] > 0 for r in records),
        "reports_naming_identity": sum(bool(named_identities(r["claims"])) for r in scored),
        "runs_with_network_code": sum(bool(r["network_code_turns"]) for r in records),
        "runs_with_install_code": sum(bool(r["install_code_turns"]) for r in records),
        **{key: sum(r[key] for r in records) for key in ("input_tokens", "cached_tokens", "output_tokens")},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=Path("results/ecoli"))
    parser.add_argument("--data", type=Path, default=Path("data/ecoli"))
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    truth = {p.stem: json.loads(p.read_text()) for p in (args.data / "truth").glob("*.json")}
    expected = {(locus, condition, rep) for locus in truth for condition in CONDITIONS for rep in range(args.reps)}
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "expected_per_model": len(expected),
               "source_audit": validate_source(args.data, args.raw), "models": {}}
    all_records = []
    for model in MODELS:
        records = []
        for path in sorted((args.runs / model).glob("*.json")):
            record = json.loads(path.read_text())
            assert record["model"] == model and record["served_models"] == [model], f"model mismatch: {path}"
            transcript = args.runs / model / "transcripts" / path.name
            assert transcript.exists(), f"missing transcript: {path}"
            record["score"] = score(record, truth[record["locus"]])
            record["python_error_outputs"] = python_error_outputs(json.loads(transcript.read_text()))
            record["path"] = str(path)
            scripts = [(c["turn"], (c.get("input") or {}).get("code", "")) for c in record["tool_calls"]]
            record["network_code_turns"] = sorted({turn for turn, code in scripts if re.search(r"urllib|https?://|socket\.|urlopen|urlretrieve", code)})
            record["install_code_turns"] = sorted({turn for turn, code in scripts if re.search(r"['\"]pip['\"]\s*,\s*['\"]install['\"]|pip\s+install", code)})
            records.append(record)
        keys = {(r["locus"], r["condition"], r["rep"]) for r in records}
        assert keys <= expected and len(keys) == len(records), f"unexpected/duplicate runs: {model}"
        missing = sorted(expected - keys)
        pending = [r["path"] for r in records if r["report"] and r.get("claims") is None]
        if (missing or pending) and not args.allow_partial:
            raise SystemExit(f"{model}: {len(missing)} missing runs, {len(pending)} pending judgements; use --allow-partial for a snapshot")
        summary["models"][model] = {
            "total": tally(records), "missing_runs": missing, "pending_judgements": pending,
            "conditions": {c: tally([r for r in records if r["condition"] == c]) for c in CONDITIONS},
            "targets": {locus: {c: tally([r for r in records if r["locus"] == locus and r["condition"] == c])
                                for c in CONDITIONS} for locus in sorted(truth) if truth[locus]["target"]},
            "unscored_runs": [{"path": r["path"], "status": r["status"], "empty_report": not r["report"]}
                              for r in records if r["score"] is None],
            "control_claims": [{"path": r["path"], "features": [f for f in r["claims"]["features"] if f["type"] in SPECIAL]}
                               for r in records if r["score"] and not r["score"]["positive"] and r["score"]["claimed"]],
            "protocol_flags": [{"path": r["path"], "network_code_turns": r["network_code_turns"], "install_code_turns": r["install_code_turns"]}
                               for r in records if r["network_code_turns"] or r["install_code_turns"]],
        }
        all_records.extend(records)
    for key in ("prompt_hash", "code_hash", "max_turns", "read_default", "provider"):
        values = {r[key] for r in all_records}
        assert len(values) == 1, f"mixed experimental setting {key}: {values}"
        summary[key] = next(iter(values))
    judges = {r["judge_model"] for r in all_records if r.get("claims") is not None}
    assert judges == {"kimi-k2.7-code"}, f"unexpected judge models: {judges}"
    summary["judge_model"] = "kimi-k2.7-code"
    summary["complete"] = all(not m["missing_runs"] and not m["pending_judgements"] for m in summary["models"].values())
    label = "Final" if summary["complete"] else "Partial"
    lines = [f"# {label} E. coli comparison", "", f"Generated {summary['generated_at']}.", "",
             "12 windows × 2 conditions × 3 repetitions = 72 runs per model. Both models use the same prompts, tools, 20-turn limit and Kimi K2.7 Code judge. All saved runs have transcripts.", "",
             "| Model | Condition | Saved | Found / scored positives | Located / scored positives | Special claims / scored controls | Forced / saved | Not scored |",
             "|---|---|---|---|---|---|---|---|"]
    for model, result in summary["models"].items():
        for condition, cell in result["conditions"].items():
            lines.append(f"| {model} | {condition} | {cell['saved']}/36 | {cell['target_found']}/{cell['positive_scored']} | {cell['target_located']}/{cell['positive_scored']} | {cell['control_special_claims']}/{cell['control_scored']} | {cell['forced_reports']}/{cell['saved']} | {cell['not_scored']} |")
    lines += ["", "## Individual targets", "", "Each cell is located / found / scored, followed by any unscored runs. Repetitions share the same window; the independent sequence sample is two CRISPR windows, three insertion sequences and one frameshift window.", "",
              "| Locus | Target | DeepSeek file | DeepSeek inline | GLM file | GLM inline |", "|---|---|---|---|---|---|"]
    for locus in sorted(truth):
        target = truth[locus]["target"]
        if not target:
            continue
        cells = []
        for model in MODELS:
            for condition in CONDITIONS:
                cell = summary["models"][model]["targets"][locus][condition]
                cells.append(f"{cell['target_located']} / {cell['target_found']} / {cell['positive_scored']}" +
                             (f" (+{cell['not_scored']} unscored)" if cell["not_scored"] else ""))
        lines.append(f"| {locus} | {target['kind']}: {target['name']} | " + " | ".join(cells) + " |")
    lines += ["", "## Effort and failures", "", "| Model | Median seconds | Input (cached subset) | Output tokens | Wrapper errors | Python diagnostic outputs (runs) | Identity claims / scored |", "|---|---|---|---|---|---|---|"]
    for model, result in summary["models"].items():
        cell = result["total"]
        lines.append(f"| {model} | {cell['median_seconds']:.1f} | {cell['input_tokens']:,} ({cell['cached_tokens']:,}) | {cell['output_tokens']:,} | {cell['wrapper_errors']} | {cell['python_error_outputs']} ({cell['runs_with_python_errors']}) | {cell['reports_naming_identity']}/{cell['scored']} |")
    lines += ["", "Python failures are inferred from traceback, exception and timeout text in tool outputs. The original wrapper counters omit subprocess failures. Token totals cover agent calls; judge usage was not saved, so these are not total billed usage.", "",
              "## External access and environment changes", "",
              "The harness does not enforce the tool description's standard-library-only constraint or disable networking. GLM region_001 inline repetition 1 successfully retrieved an EBI BLAST result; GLM region_004 inline repetition 2 installed Biopython and NumPy in the shared virtual environment and opened a UniProt URL. This is a material limitation of a sequence-only interpretation. The current batch is retained unchanged.", ""]
    for model, result in summary["models"].items():
        for record in result["protocol_flags"]:
            lines.append(f"- `{record['path']}`: network-related code on turns {record['network_code_turns']}; installation code on turns {record['install_code_turns']} (zero-based; keyword flags require transcript review).")
    lines += ["", "## Interpretation limits", "", "- Found means the judge extracted the target's feature type somewhere in the report. Located additionally requires any coordinate overlap; descending coordinate pairs are normalised. These metrics do not establish exact boundaries or correct biological interpretation.",
              "- Controls exclude selected special annotations, pseudogenes and annotated ribosomal slippage. Additional claims are not automatically false. Other notable features on real DNA do not measure over-claiming.",
              "- CRISPR truth comes from a repeat search, not a curated annotation. In region_010, the conserved core is 331–910 with 10 exact copies, while a diagnostic motif scan also finds three variant copies at 943, 1004 and 1065. Boundary and copy-number errors against this core should not be interpreted as accuracy on the full array.",
              "- Identity claims exclude supplied filenames and generic ORF labels. They include incorrect guesses and functional names; they do not prove memorisation.",
              "- Empty reports remain unscored, including in the CSV. Detection denominators include only judged reports; effort and forced-report denominators include every saved run.",
              "- Wilson intervals in individual analysis files describe repeated runs and do not account for correlation within a locus. This pilot does not establish a reliable advantage of either presentation condition.", "", "## Unscored reports", ""]
    for model, result in summary["models"].items():
        for record in result["unscored_runs"]:
            lines.append(f"- `{record['path']}`: {record['status']}; " + ("empty report" if record["empty_report"] else "pending/failed judgement"))
    lines += ["", "Concrete factual, coordinate and boundary examples are documented in [audit_notes.md](audit_notes.md)."]
    (args.runs / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.runs / "comparison.md").write_text("\n".join(lines) + "\n")
    print(f"{label.lower()} comparison written to {args.runs / 'comparison.md'}")


if __name__ == "__main__":
    main()
