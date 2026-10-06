"""Before/after comparison for reviewed runs written by supervise.py (judge them first)."""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from analyze import score, target_of


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, required=True, help="e.g. results/supervised/deepseek-v4.1-flash")
    p.add_argument("--truth", type=Path, default=Path("data/ecoli/truth"))
    args = p.parse_args()

    # (mode, region) -> list of (before, after) outcomes; an outcome is "located", "found", "no" or None (unscored)
    cells = defaultdict(list)
    extra = defaultdict(lambda: [0, 0, 0])  # mode -> runs, runs revised, tool calls after the nudge
    labels = {}
    for path in sorted(args.runs.glob("*/*.json")):
        record = json.loads(path.read_text())
        mode = record.get("review_mode", path.parent.name)
        truth = json.loads((args.truth / f"{record['locus']}.json").read_text())
        target = target_of(truth)
        labels[record["locus"]] = f"{target['kind']}: {target['name']}" if target else "control"

        def outcome(claims):
            s = score({"claims": claims}, truth) if claims is not None else None
            if s is None:
                return None
            return "located" if s["localized"] else "found" if s["claimed"] else "no"

        after = outcome(record.get("claims"))
        # Without a nudge there is one report, which counts as both.
        before = outcome(record["first_claims"]) if "first_report" in record else after
        cells[mode, record["locus"]].append((before, after))
        review = record.get("review") or {}
        extra[mode][0] += 1
        extra[mode][1] += bool(review.get("revised"))
        extra[mode][2] += review.get("tool_calls", 0)

    if not cells:
        raise SystemExit(f"no runs in {args.runs}")
    modes = sorted({mode for mode, _ in cells})
    print("Target claimed, before -> after the nudge (runs with a claim of the target type / scored runs).")
    print("For controls the count is runs claiming a repeat array, mobile element or frameshift.\n")
    print("| region | " + " | ".join(modes) + " |")
    print("|---|" + "---|" * len(modes))
    for locus in sorted(labels):
        row = []
        for mode in modes:
            pairs = [pair for pair in cells.get((mode, locus), []) if None not in pair]
            hit = lambda value: value in ("found", "located")
            row.append(f"{sum(hit(b) for b, _ in pairs)} -> {sum(hit(a) for _, a in pairs)} of {len(pairs)}" if pairs else "n/a")
        print(f"| {locus} ({labels[locus]}) | " + " | ".join(row) + " |")
    print("\n| mode | runs | revised report written | mean tool calls after the nudge |")
    print("|---|---|---|---|")
    for mode in modes:
        runs, revised, calls = extra[mode]
        print(f"| {mode} | {runs} | {revised} | {calls / runs:.1f} |")


if __name__ == "__main__":
    main()
