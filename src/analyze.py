"""Compare judged runs with the ground truth and summarise by condition.

Writes one row per run to a CSV and prints summary tables. Columns that need
a saved transcript or a newer run record are left empty where those are missing.
"""
import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import median

from tools import read_fasta_sequence
from transcripts import assistant_turns, first_notice, python_error_outputs, repeat_kmers, script_kinds

# A file-condition run counts as having "looked" once a single tool result
# showed it at least this many contiguous nucleotides.
LOOKED_NT = 200


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denom = 1 + z * z / n
    return (max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom))


# Feature types that would be a finding. On a control, claiming one counts as a false alarm.
SPECIAL = ("repeat_array", "mobile_element", "frameshift")


def target_of(truth):
    """The feature a run should find, or None for a control. Accepts both truth formats."""
    if "target" in truth:
        return truth["target"]
    if not truth.get("has_array"):
        return None
    return {
        "type": "repeat_array",
        "kind": "planted array",
        "name": f"{truth['copies']} x {truth['unit_len']} nt",
        "start": truth["start"],
        "end": truth["end"],
        "unit_len": truth["unit_len"],
        "copies": truth["copies"],
    }


def claimed_features(claims):
    """The judge's feature list. Accepts the first judge format, which only knew repeat arrays."""
    if "features" in claims:
        return claims["features"]
    features = [{"type": "other", "start": None, "end": None} for _ in claims.get("other_notable_features") or []]
    if claims["claims_repeat_array"]:
        array = {k: claims.get(k) for k in ("start", "end", "unit_length", "copy_number")}
        features.append({"type": "repeat_array", **array})
    return features


def named_identities(claims):
    """Exclude supplied filenames and analyst-created ORF labels from recognition flags."""
    placeholder = r"(?i)^(?:(?:region|locus)[_ -]?\d+|orf[_ -]?[a-z0-9]+|gene[_ -]+[a-z0-9]+|g\d+[a-z]?|\S+\.(?:fasta|fa|fna))$"
    return [name for name in claims.get("named_identity") or [] if not re.fullmatch(placeholder, name.strip())]


def _overlaps(feature, target):
    start, end = feature.get("start"), feature.get("end")
    if start is None or end is None:
        return False
    start, end = sorted((start, end))  # reports may give reverse-strand coordinates in descending order
    return start <= target["end"] and end >= target["start"]


def score(record, truth):
    """Classify one run. Returns None when the run produced no judged report."""
    claims = record.get("claims")
    if claims is None:
        return None
    features = claimed_features(claims)
    target = target_of(truth)
    if target is None:
        return {"positive": False, "claimed": any(f["type"] in SPECIAL for f in features), "localized": False}
    matches = [f for f in features if f["type"] == target["type"]]
    return {
        "positive": True,
        "claimed": bool(matches),
        "localized": any(_overlaps(f, target) for f in matches),
    }


def accuracy(record, truth):
    """Signed errors of the reported target against the true one (reported minus true)."""
    target = target_of(truth)
    empty = {"unit_len_err": None, "copies_err": None, "start_err": None, "end_err": None}
    if target is None:
        return empty
    matches = [f for f in claimed_features(record["claims"]) if f["type"] == target["type"]]
    if not matches:
        return empty
    best = next((f for f in matches if _overlaps(f, target)), matches[0])
    if best.get("start") is not None and best.get("end") is not None:
        start, end = sorted((best["start"], best["end"]))
        best = {**best, "start": start, "end": end}

    def err(claimed_key, truth_key):
        value = best.get(claimed_key)
        return None if value is None or target.get(truth_key) is None else value - target[truth_key]

    return {
        "unit_len_err": err("unit_length", "unit_len"),
        "copies_err": err("copy_number", "copies"),
        "start_err": err("start", "start"),
        "end_err": err("end", "end"),
    }


def target_seen(record, truth):
    """Fraction of the target that tool results showed the agent."""
    target = target_of(truth)
    if target is None or "seen_intervals" not in record:
        return None
    if record["condition"] == "inline":
        return 1.0  # the whole region is in the prompt
    shown = sum(
        max(0, min(end, target["end"]) - max(start, target["start"]) + 1)
        for start, end in record["seen_intervals"]
    )
    return round(shown / (target["end"] - target["start"] + 1), 3)


def route(transcript, truth, sequence):
    """What the transcript says about how the agent worked."""
    turns = assistant_turns(transcript)
    kinds = [kind for turn in turns for script in turn["scripts"] for kind in script_kinds(script)]
    out = {"ran_repeat_script": "repeat" in kinds, "notice_turn": None, "noticed_by_reading": None}
    target = target_of(truth)
    if target and target["type"] == "repeat_array":
        array = sequence[target["start"] - 1 : target["end"]]
        out["notice_turn"], out["noticed_by_reading"] = first_notice(turns, repeat_kmers(array))
    return out


def fmt(k, n):
    if n == 0:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%, CI {100 * lo:.0f}-{100 * hi:.0f}%)"


def count(rows, key):
    return sum(bool(r[key]) for r in rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, required=True, help="a directory written by harness.py")
    p.add_argument("--truth", type=Path, default=Path("data/synthetic/truth"))
    p.add_argument("--loci", type=Path, default=Path("data/synthetic/loci"))
    p.add_argument("--csv", type=Path, help="default <runs>/results.csv")
    args = p.parse_args()
    args.csv = args.csv or args.runs / "results.csv"

    rows = []
    unscored = defaultdict(lambda: defaultdict(int))
    annotation_controls = False
    for path in sorted(args.runs.glob("*.json")):
        record = json.loads(path.read_text())
        truth = json.loads((args.truth / f"{record['locus']}.json").read_text())
        s = score(record, truth)
        target = target_of(truth)
        annotation_controls |= "annotated" in truth
        judged = s is not None
        if s is None:
            reason = "empty report" if not record.get("report") else "no usable judgement"
            unscored[record["condition"]][reason] += 1
        row = {
            "locus": record["locus"],
            "condition": record["condition"],
            "rep": record.get("rep"),
            "model": record.get("model"),
            "provider": record.get("provider"),
            "judge_model": record.get("judge_model"),
            "scored": judged,
            "report_chars": len(record.get("report") or ""),
            "status": record["status"],
            "forced_report": record.get("forced_report"),
            "rescue": record.get("rescue"),
            "max_turns": record.get("max_turns"),
            "turns": len(record.get("turns") or []),
            **(s or {"positive": target is not None, "claimed": None, "localized": None}),
            **(accuracy(record, truth) if judged else dict.fromkeys(("unit_len_err", "copies_err", "start_err", "end_err"))),
            "other_claims": sum(f["type"] == "other" for f in claimed_features(record["claims"])) if judged else None,
            "named_identity": "|".join(named_identities(record["claims"])) if judged else None,
            "named_identity_raw": "|".join(record["claims"].get("named_identity") or []) if judged else None,
            "target_type": target["type"] if target else None,
            "target": f"{target['kind']}: {target['name']}" if target else None,
            "tool_calls": len(record["tool_calls"]),
            "tool_errors": sum(c["is_error"] for c in record["tool_calls"]),
            "nt_run_from_tools": record["nt_run_from_tools"],
            "target_seen": target_seen(record, truth),
            "ran_repeat_script": None,
            "notice_turn": None,
            "noticed_by_reading": None,
            "input_tokens": record["input_tokens"],
            "output_tokens": record["output_tokens"],
            "cached_tokens": record.get("cached_tokens"),
            "seconds": record.get("seconds"),
            "started_at": record.get("started_at"),
            "prompt_hash": record.get("prompt_hash"),
            "code_hash": record.get("code_hash"),
            "served_models": "|".join(record.get("served_models") or []),
            "has_transcript": False,
            "python_error_outputs": None,
        }
        transcript_path = args.runs / "transcripts" / path.name
        if transcript_path.exists():
            sequence = read_fasta_sequence((args.loci / f"{record['locus']}.fasta").read_text())
            transcript = json.loads(transcript_path.read_text())
            row.update(route(transcript, truth, sequence), has_transcript=True, python_error_outputs=python_error_outputs(transcript))
        rows.append(row)
    if not rows and not unscored:
        raise SystemExit(f"no runs in {args.runs}")

    with args.csv.open("w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    conditions = sorted({r["condition"] for r in rows} | set(unscored))
    hashes = {r["prompt_hash"] for r in rows}
    if len(hashes) > 1:
        print(f"WARNING: runs made with {len(hashes)} different prompt versions are pooled here: {sorted(map(str, hashes))}\n")

    alarm_label = "special-feature claim (controls)" if annotation_controls else "false alarm (controls)"
    print(f"| condition | target found (positives) | target located (positives) | {alarm_label} | forced reports | not scored |")
    print("|---|---|---|---|---|---|")
    for condition in conditions:
        sub = [r for r in rows if r["condition"] == condition]
        pos = [r for r in sub if r["scored"] and r["positive"]]
        neg = [r for r in sub if r["scored"] and not r["positive"]]
        skipped = ", ".join(f"{n} {status}" for status, n in sorted(unscored[condition].items())) or "0"
        print(
            f"| {condition} | {fmt(count(pos, 'claimed'), len(pos))} | {fmt(count(pos, 'localized'), len(pos))} "
            f"| {fmt(count(neg, 'claimed'), len(neg))} | {count(sub, 'forced_report')}/{len(sub)} | {skipped} |"
        )
    if annotation_controls:
        print("\nOn annotation-selected controls, a special-feature claim means a claimed repeat array, mobile element or frameshift; it is not proof that the claim is false. 'Found' matches feature type; 'located' additionally requires any coordinate overlap with the target.")
    print("Intervals describe scored runs, not independent loci; repeated runs on the same window are correlated.")

    print("\nPositives by region (located / found / runs):")
    print("| region | target | " + " | ".join(conditions) + " |")
    print("|---|---|" + "---|" * len(conditions))
    for locus in sorted({r["locus"] for r in rows if r["positive"]}):
        sub = [r for r in rows if r["locus"] == locus]
        cells = []
        for condition in conditions:
            c = [r for r in sub if r["condition"] == condition]
            scored = [r for r in c if r["scored"]]
            missing = len(c) - len(scored)
            cells.append(f"{count(scored, 'localized')} / {count(scored, 'claimed')} / {len(scored)}" + (f" (+{missing} not scored)" if missing else ""))
        print(f"| {locus} | {sub[0]['target']} | " + " | ".join(cells) + " |")

    print("\nEffort per run (median):")
    print("| condition | tool calls | longest nt run from tools | input tokens | seconds |")
    print("|---|---|---|---|---|")
    for condition in conditions:
        sub = [r for r in rows if r["condition"] == condition]
        if not sub:
            continue
        secs = [r["seconds"] for r in sub if r["seconds"] is not None]
        print(
            f"| {condition} | {median(r['tool_calls'] for r in sub)} | {median(r['nt_run_from_tools'] for r in sub)} "
            f"| {median(r['input_tokens'] for r in sub):,.0f} | {median(secs) if secs else 'n/a'} |"
        )

    with_transcript = [r for r in rows if r["has_transcript"]]
    if with_transcript:
        print(f"\nHow the array was found ({len(with_transcript)} of {len(rows)} runs have transcripts; keyword-based, see transcripts.py):")
        print("| condition | ran a repeat-search script (all runs) | wrote part of the unit (repeat-array targets) | of those, before any repeat-search script | median fraction of target shown by tools |")
        print("|---|---|---|---|---|")
        for condition in conditions:
            sub = [r for r in with_transcript if r["condition"] == condition]
            pos = [r for r in sub if r["target_type"] == "repeat_array"]
            noticed = [r for r in pos if r["notice_turn"] is not None]
            shown = [r["target_seen"] for r in sub if r["target_seen"] is not None]
            print(
                f"| {condition} | {fmt(count(sub, 'ran_repeat_script'), len(sub))} | {fmt(len(noticed), len(pos))} "
                f"| {fmt(count(noticed, 'noticed_by_reading'), len(noticed))} | {median(shown) if shown else 'n/a'} |"
            )

    neg = [r for r in rows if r["scored"] and not r["positive"]]
    if neg:
        print(f"\nControls where the report presented some other feature as notable: {fmt(sum(r['other_claims'] > 0 for r in neg), len(neg))}")
    named = [r for r in rows if r["named_identity"]]
    if named:
        names = defaultdict(int)
        for r in named:
            for name in r["named_identity"].split("|"):
                names[name] += 1
        top = ", ".join(f"{name} ({n})" for name, n in sorted(names.items(), key=lambda x: -x[1])[:12])
        print(f"\nReports that named an organism, gene or locus: {fmt(len(named), sum(r['scored'] for r in rows))}\n  most frequent: {top}")
        print("  supplied filenames and generic ORF labels excluded; a name is not proof of correct identification or memorisation")

    file_pos = [r for r in rows if r["scored"] and r["condition"] == "file" and r["positive"]]
    if file_pos:
        looked = [r for r in file_pos if r["nt_run_from_tools"] >= LOOKED_NT]
        blind = [r for r in file_pos if r["nt_run_from_tools"] < LOOKED_NT]
        print(f"\nFile condition, positives, split by whether a tool result showed >= {LOOKED_NT} contiguous nt:")
        print(f"  looked:       found {fmt(count(looked, 'claimed'), len(looked))}")
        print(f"  did not look: found {fmt(count(blind, 'claimed'), len(blind))}")
    print(f"\nper-run rows written to {args.csv}")


if __name__ == "__main__":
    main()
