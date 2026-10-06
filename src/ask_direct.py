"""Ask the agent a direct yes/no question about a region, instead of "report anything notable".

This separates two reasons an open-ended run can miss a feature: the model
cannot recognise it even when asked, or it can but never thinks to look.
Each question is put to windows that do and do not contain the feature, so
a model that says yes to everything is visible.

The agent has the same tools and sandbox as in harness.py. Its reply must end
with fixed ANSWER and COORDINATES lines, which are read by code: no judge model.
"""
import argparse
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from analyze import target_of, wilson
from backends import PROVIDERS, api_errors, chat_class, make_client
from harness import REGION_FILE, run_once

# question name -> (target type in the truth files, wording)
QUESTIONS = {
    "insertion_sequence": (
        "mobile_element",
        "Does this region contain an insertion sequence (a bacterial transposable element)?",
    ),
    "frameshift": (
        "frameshift",
        "Does this region contain a gene whose protein is made through a programmed ribosomal "
        "frameshift, so that its coding sequence continues in a different reading frame?",
    ),
}
TASK = (
    f"The file {REGION_FILE} in your working directory holds a DNA region. {{question}} "
    "Investigate with your tools, then end your reply with exactly these two lines:\n"
    "ANSWER: yes or no\n"
    "COORDINATES: start-end of the feature, or none"
)


def parse_answer(report):
    """(True/False/None, (start, end) or None) from the reply's closing lines."""
    answers = re.findall(r"ANSWER:\W*(yes|no)\b", report, re.IGNORECASE)
    spans = re.findall(r"COORDINATES:\D*(\d[\d,]*)\s*(?:-|–|to|\.\.)\s*(\d[\d,]*)", report, re.IGNORECASE)
    answer = answers[-1].lower() == "yes" if answers else None
    span = tuple(int(x.replace(",", "")) for x in spans[-1]) if spans and answer else None
    return answer, span


def covers(span, target):
    """True when the answer's span holds at least half of the feature. Touching its edge is not enough."""
    if not span:
        return False
    shared = min(span[1], target["end"]) - max(span[0], target["start"]) + 1
    return shared >= 0.5 * (target["end"] - target["start"] + 1)


def summarize(out_dir, truth_dir):
    cells = defaultdict(list)  # (question, locus) -> records
    for path in sorted(out_dir.glob("*/*.json")):
        record = json.loads(path.read_text())
        cells[record["question"], record["locus"]].append(record)
    if not cells:
        return
    print("\n| question | region | holds the feature | said yes | placed it on the feature | no usable answer |")
    print("|---|---|---|---|---|---|")
    totals = defaultdict(lambda: [0, 0])  # (question, positive?) -> [yes, answered]
    for (question, locus), records in sorted(cells.items()):
        target = target_of(json.loads((truth_dir / f"{locus}.json").read_text()))
        positive = bool(target) and target["type"] == QUESTIONS[question][0]
        answered = [r for r in records if r["answer"] is not None]
        yes = [r for r in answered if r["answer"]]
        placed = sum(covers(r["answer_span"], target) for r in yes) if positive else None
        totals[question, positive][0] += len(yes)
        totals[question, positive][1] += len(answered)
        label = f"{target['kind']}: {target['name']}" if target else "control"
        print(f"| {question} | {locus} ({label}) | {'yes' if positive else 'no'} | {len(yes)}/{len(answered)} "
              f"| {'n/a' if placed is None else f'{placed}/{len(yes)}'} | {len(records) - len(answered)} |")
    print()
    for (question, positive), (yes, n) in sorted(totals.items()):
        lo, hi = wilson(yes, n)
        kind = "feature present" if positive else "feature absent "
        print(f"{question:18} {kind}: said yes {yes}/{n} (95% CI {100 * lo:.0f}-{100 * hi:.0f}%)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", default="opencode-go", choices=PROVIDERS)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", help="reasoning effort, if the model takes one")
    p.add_argument("--questions", default=",".join(QUESTIONS))
    p.add_argument("--loci", type=Path, default=Path("data/ecoli/loci"))
    p.add_argument("--truth", type=Path, default=Path("data/ecoli/truth"))
    p.add_argument("--only", default="region_001,region_004,region_006,region_011", help="comma-separated region names")
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--max-turns", type=int, default=15)
    p.add_argument("--out", type=Path, help="default results/direct_questions/<turn limit>_turns/<model>")
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--summary", action="store_true", help="print the results table for saved runs and exit")
    args = p.parse_args()

    out_dir = args.out or Path("results/direct_questions") / f"{args.max_turns}_turns" / args.model
    if args.summary:
        return summarize(out_dir, args.truth)
    questions = args.questions.split(",")
    if unknown := set(questions) - set(QUESTIONS):
        p.error(f"unknown question: {', '.join(sorted(unknown))}")
    wanted = set(args.only.split(","))
    loci = [locus for locus in sorted(args.loci.glob("*.fasta")) if locus.stem in wanted]
    if missing := wanted - {locus.stem for locus in loci}:
        p.error(f"not in {args.loci}: {', '.join(sorted(missing))}")

    jobs = []
    for question in questions:
        for locus in loci:
            for rep in range(args.reps):
                out = out_dir / question / f"{locus.stem}__file__{rep}.json"
                if not out.exists():
                    jobs.append((question, locus, rep, out))
    print(f"{len(jobs)} runs to do in {out_dir} ({len(questions) * len(loci) * args.reps - len(jobs)} already saved)")
    if args.dry_run or not jobs:
        return summarize(out_dir, args.truth)

    client = make_client(args.provider)
    auth_error, other_errors = api_errors(args.provider)

    def work(job):
        question, locus, rep, out = job
        record = run_once(
            client,
            locus,
            "file",
            model=args.model,
            effort=args.effort or ("medium" if args.provider == "anthropic" else None),
            read_default=2000,
            max_turns=args.max_turns,
            chat_cls=chat_class(args.provider),
            task=TASK.format(question=QUESTIONS[question][1]),
        )
        answer, span = parse_answer(record["report"])
        record.update(provider=args.provider, rep=rep, question=question, answer=answer, answer_span=span)
        (out.parent / "transcripts").mkdir(parents=True, exist_ok=True)
        (out.parent / "transcripts" / out.name).write_text(json.dumps(record.pop("transcript"), indent=2) + "\n")
        out.write_text(json.dumps(record, indent=2) + "\n")
        return record

    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, job): job for job in jobs}
        for future in as_completed(futures):
            question, locus, rep, _ = futures[future]
            label = f"{question} {locus.stem} #{rep}"
            try:
                record = future.result()
            except auth_error:
                raise SystemExit("authentication failed: check your API key")
            except other_errors as e:
                failed += 1
                print(f"{label}: {type(e).__name__}: {e}; rerun to resume")
            else:
                answer = {True: "yes", False: "no", None: "NO USABLE ANSWER"}[record["answer"]]
                print(f"{label}: {answer} {record['answer_span'] or ''} ({len(record['tool_calls'])} tool calls)")
    print(f"done: {len(jobs) - failed} saved, {failed} failed")
    summarize(out_dir, args.truth)


if __name__ == "__main__":
    main()
