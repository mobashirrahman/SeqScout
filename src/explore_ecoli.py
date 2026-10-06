"""Explore saved E. coli reports without rerunning agents or judges.

Gene matching is an exploratory coordinate check, separate from target scores:
both the reported interval and the clipped annotated coding interval must be
at least 80% covered by their intersection. Strand and function are not scored.
"""
import csv
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median

from fetch_ecoli import overlaps, parse_feature_table
from summarize_ecoli import MODELS
from tools import read_fasta_sequence
from transcripts import assistant_turns, python_error_outputs, script_kinds

ROOT = Path(__file__).resolve().parent.parent
REPORT_TOPICS = {
    "shuffle_or_randomisation": r"shuffl|permut|monte.car|randomi[sz]",
    "hydropathy_or_membrane": r"hydropath|hydrophob|transmembrane|membrane",
    "regulatory_signals": r"shine|dalgarno|promoter|terminator|ribosome.binding",
    "cas": r"\bcas\w*\b",
}


def local_cds(truth, features):
    source = truth["source"]
    genes = []
    for feature in features:
        if feature["key"] != "CDS" or "pseudo" in feature["quals"]:
            continue
        if not overlaps(feature, source["start"], source["end"]):
            continue
        start = max(feature["start"], source["start"]) - source["start"] + 1
        end = min(feature["end"], source["end"]) - source["start"] + 1
        strand = feature["strand"]
        if source["strand"] == "-":
            start, end = truth["length"] - end + 1, truth["length"] - start + 1
            strand = "+" if strand == "-" else "-"
        if end - start + 1 < 150:
            continue
        name = next((g["name"] for g in truth["annotated"]
                     if g["key"] == "gene" and not g["pseudo"]
                     and g["start"] == start and g["end"] == end), feature["quals"].get("locus_tag"))
        genes.append({"name": name, "start": start, "end": end, "strand": strand,
                      "product": feature["quals"].get("product"),
                      "clipped": feature["start"] < source["start"] or feature["end"] > source["end"],
                      "ribosomal_slippage": "ribosomal_slippage" in feature["quals"]})
    return sorted(genes, key=lambda g: g["start"])


def matches(claim, gene, threshold):
    if claim.get("start") is None or claim.get("end") is None:
        return False
    start, end = sorted((claim["start"], claim["end"]))
    intersection = max(0, min(end, gene["end"]) - max(start, gene["start"]) + 1)
    return (intersection >= threshold * (end - start + 1)
            and intersection >= threshold * (gene["end"] - gene["start"] + 1))


def repeated_paragraphs(report):
    # Exact paragraph repetition is a narrow indicator of output degeneration.
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", report)]
    counts = Counter(p for p in paragraphs if len(p) >= 60)
    return max(counts.values(), default=0), sum((n - 1) * len(p) for p, n in counts.items())


def gc_statements(report, actual_gc):
    # Only direct 'GC content: N%' / 'N% GC' expressions. This intentionally
    # collects local values too: discrepancies require human scope review.
    patterns = (r"(?:GC(?:\s+content)?|G\s*\+\s*C)\s*(?:is|of|=|:)?\s*[\s*~≈]*([0-9]+(?:\.[0-9]+)?)\s*%",
                r"([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:G\s*\+\s*C|GC)\b")
    values = sorted(set(float(m.group(1)) for pattern in patterns for m in re.finditer(pattern, report, re.I)))
    return [{"value": value, "whole_window_error_pp": round(value - actual_gc, 3)} for value in values]


def totals(rows):
    scored = [r for r in rows if r["scored"]]
    return {
        "saved": len(rows), "scored": len(scored),
        "median_report_words": median(r["report_words"] for r in scored) if scored else None,
        "reports_with_gene_claims": sum(r["gene_claims"] > 0 for r in scored),
        "gene_claims": sum(r["gene_claims"] for r in scored),
        "coordinate_gene_claims": sum(r["coordinate_gene_claims"] for r in scored),
        "gene_claims_matching_80": sum(r["gene_claims_matching_80"] for r in scored),
        "gene_claims_matching_50": sum(r["gene_claims_matching_50"] for r in scored),
        "annotated_cds_opportunities": sum(r["annotated_cds"] for r in scored),
        "cds_recovered_80": sum(r["cds_recovered_80"] for r in scored),
        "cds_recovered_50": sum(r["cds_recovered_50"] for r in scored),
        "cds_recovered_80_including_other_orfs": sum(r["cds_recovered_80_including_other_orfs"] for r in scored),
        "all_cds_opportunities": sum(r["annotated_cds"] for r in rows),
        "median_seconds": median(r["seconds"] for r in rows),
        "python_calls": sum(r["python_calls"] for r in rows),
        "python_diagnostic_outputs": sum(r["python_diagnostic_outputs"] for r in rows),
        "diagnostic_types": dict(sum((Counter(r["diagnostic_types"]) for r in rows), Counter())),
        "runs_with_python_diagnostics": sum(r["python_diagnostic_outputs"] > 0 for r in rows),
        "forced_reports": sum(r["forced_report"] for r in rows),
        "empty_reports": sum(r["report_words"] == 0 for r in rows),
        "tool_markup_reports": sum(r["tool_markup_report"] for r in rows),
        "repetitive_reports": sum(r["max_identical_paragraph_count"] >= 4 for r in rows),
        "reported_topics": {topic: sum(r["reported_topics"][topic] for r in scored) for topic in REPORT_TOPICS},
        "script_categories": dict(sum((Counter(r["script_categories"]) for r in rows), Counter())),
        "runs_with_shuffle_code": sum(r["shuffle_code"] for r in rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
    }


def main():
    truth = {p.stem: json.loads(p.read_text()) for p in (ROOT / "data/ecoli/truth").glob("*.json")}
    features = parse_feature_table((ROOT / "data/raw/U00096.3.ft").read_text())
    annotation = {locus: local_cds(t, features) for locus, t in truth.items()}
    assert all(g["name"] for genes in annotation.values() for g in genes)
    records = []
    for model in MODELS:
        for path in sorted((ROOT / "results/ecoli" / model).glob("*.json")):
            run = json.loads(path.read_text())
            sequence = read_fasta_sequence((ROOT / "data/ecoli/loci" / f"{run['locus']}.fasta").read_text())
            transcript = json.loads((path.parent / "transcripts" / path.name).read_text())
            genes = annotation[run["locus"]]
            claims = run.get("claims")
            gene_claims = [f for f in claims["features"] if f["type"] == "gene"] if claims else []
            report = run["report"]
            scripts = [s for turn in assistant_turns(transcript) for s in turn["scripts"]]
            diagnostics = Counter()
            for message in transcript:
                if message.get("role") != "tool" or not isinstance(message.get("content"), str):
                    continue
                output = message["content"]
                for error in set(re.findall(r"(?m)^((?:\w+\.)?\w*(?:Error|Exception)|re\.error|StopIteration)(?::|$)", output)):
                    diagnostics[error] += 1
                if re.search(r"(?m)^error: script exceeded \d+s", output):
                    diagnostics["timeout"] += 1
            repeat_max, repeated_chars = repeated_paragraphs(report)
            record = {
                "model": model, "run": path.stem, "locus": run["locus"],
                "condition": run["condition"], "rep": run["rep"], "scored": claims is not None,
                "report_words": len(report.split()), "report_chars": len(report),
                "status": run["status"], "seconds": run["seconds"], "forced_report": run["forced_report"],
                "gene_claims": len(gene_claims),
                "coordinate_gene_claims": sum(f.get("start") is not None and f.get("end") is not None for f in gene_claims),
                "annotated_cds": len(genes),
                "python_calls": sum(c["name"] == "run_python" for c in run["tool_calls"]),
                "python_diagnostic_outputs": python_error_outputs(transcript), "diagnostic_types": dict(diagnostics),
                "script_categories": {kind: int(any(kind in script_kinds(s) for s in scripts))
                                      for kind in ("repeat", "composition", "orf", "motif")},
                "shuffle_code": any(re.search(r"shuffl|permut", s, re.I) for s in scripts),
                "reported_topics": {name: bool(re.search(pattern, report, re.I)) for name, pattern in REPORT_TOPICS.items()},
                "max_identical_paragraph_count": repeat_max, "repeated_paragraph_chars": repeated_chars,
                "tool_markup_report": report.lstrip().startswith("<tool_call>"),
                "gc_scan": gc_statements(report, 100 * (sequence.count("G") + sequence.count("C")) / len(sequence)),
            }
            for threshold, tag in ((0.8, "80"), (0.5, "50")):
                record[f"genes_recovered_{tag}"] = [g["name"] for g in genes if any(matches(c, g, threshold) for c in gene_claims)]
                record[f"cds_recovered_{tag}"] = len(record[f"genes_recovered_{tag}"])
                record[f"gene_claims_matching_{tag}"] = sum(any(matches(c, g, threshold) for g in genes) for c in gene_claims)
            record["unmatched_gene_claims_80"] = [c for c in gene_claims if not any(matches(c, g, .8) for g in genes)]
            candidates = [f for f in claims["features"] if f["type"] == "gene" or
                          (f["type"] == "other" and re.search(r"\borf\b|open reading frame|stop.free (?:stretch|run|region)",
                                                               f["description"], re.I))] if claims else []
            record["cds_recovered_80_including_other_orfs"] = sum(any(matches(c, g, .8) for c in candidates) for g in genes)
            records.append(record)
    assert len(records) == 144
    paired_keys = set.intersection(*(set(r["run"] for r in records if r["model"] == m and r["scored"]) for m in MODELS))
    flagged_keys = {r["run"] for r in records if r["tool_markup_report"] or r["max_identical_paragraph_count"] >= 4}
    clean_pairs = paired_keys - flagged_keys
    summary = {
        "method": "Non-pseudo CDS spans with >=150 visible bases; clipped at window edges. Matching requires >=80% of both intervals covered, with a 50% sensitivity check. Gene-type claims only; no strand or function scoring. Counts reuse loci across runs, so they are descriptive, not independent samples. Unmatched claims are not automatically false.",
        "gc_scan_note": "Candidate statements include local GC values. whole_window_error_pp is a comparison with the whole window, not a validated error; scope needs manual review.",
        "annotation": annotation, "paired_nonempty_runs": len(paired_keys), "paired_runs_without_output_flags": len(clean_pairs),
        "models": {m: {"all_runs": totals([r for r in records if r["model"] == m]),
                       "paired_nonempty": totals([r for r in records if r["model"] == m and r["run"] in paired_keys]),
                       "paired_without_output_flags": totals([r for r in records if r["model"] == m and r["run"] in clean_pairs]),
                       "conditions": {c: totals([r for r in records if r["model"] == m and r["condition"] == c]) for c in ("file", "inline")},
                       "loci": {locus: totals([r for r in records if r["model"] == m and r["locus"] == locus]) for locus in sorted(truth)}}
                   for m in MODELS},
        "records": records,
    }
    out = ROOT / "results/ecoli"
    (out / "exploration_metrics.json").write_text(json.dumps(summary, indent=2) + "\n")
    flat_keys = [k for k, v in records[0].items() if not isinstance(v, (list, dict))]
    with (out / "exploration_metrics.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=flat_keys)
        writer.writeheader()
        writer.writerows({k: r[k] for k in flat_keys} for r in records)
    for model, model_summary in summary["models"].items():
        print(model, json.dumps(model_summary["all_runs"]))
        print("PAIRED", json.dumps(model_summary["paired_nonempty"]))
    print(f"Wrote exploratory metrics for {len(records)} runs, {len(paired_keys)} nonempty matched pairs.")


if __name__ == "__main__":
    main()
