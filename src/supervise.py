"""Send an agent back to its own report with a nudge, and see what the second look finds.

Each run is an ordinary harness run followed by one review round. Both
reports are kept, so every run gives a before/after pair on the same region.
The nudges form a ladder, from no information to a hint about feature classes:

  again       "take another look" - the control for simply having a second pass
  reflect     revisit what you set aside or could not explain
  supervisor  a second model reads the report (never the sequence or the answer)
              and asks about its loose ends
  checklist   names classes of genomic feature to check - the only nudge that
              carries biological hints, so it is an upper bound, not a fair test

The supervisor has no tools and sees only the report.
"""
import argparse
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backends import PROVIDERS, api_errors, chat_class, make_client
from harness import CODE_HASH, run_once

CLOSING = (
    " Use your tools as needed, then write a complete revised report with coordinates. "
    "Keep earlier findings that still stand. It is fine to conclude that nothing changes."
)
NUDGES = {
    "again": "Take another look at the region before your report is final.",
    "reflect": (
        "Before your report is final, go back over your own work. List every observation you "
        "noted but set aside, explained away as chance, or could not explain. For each one, "
        "state the strongest alternative explanation under which it would be meaningful, and "
        "run one analysis that could tell the explanations apart."
    ),
    "checklist": (
        "Before your report is final, check explicitly for features beyond ordinary genes: "
        "repeat arrays, mobile elements bounded by inverted repeats, genes split across two "
        "reading frames, overlapping genes, RNA genes and regulatory structures. For each "
        "class, report the evidence for or against it in this region."
    ),
}
SUPERVISOR_SYSTEM = (
    "You supervise a junior analyst who was given a DNA region of unknown function and asked "
    "to report anything notable. You see only their report. You do not have the sequence and "
    "you do not know what, if anything, the region contains."
)
SUPERVISOR_PROMPT = """Read the report below and find its loose ends: observations that are \
reported but not explained, features dismissed without a decisive test, and things that do \
not fit together (unexplained gaps, odd boundaries, inconsistent numbers).

Write up to three questions for the analyst. Make each one specific to something in the \
report, and name a concrete analysis they can run with Python's standard library on the \
sequence alone. Do not tell them what you expect the answer to be, and do not ask for \
databases or other outside resources. If the report has no loose ends, reply with exactly \
NONE.

<report>
{report}
</report>"""
SUPERVISOR_FRAME = "A reviewer read your report and raised these points:\n\n{questions}\n\n"
MODES = (*NUDGES, "supervisor")


def ask(client, provider, model, system, prompt, effort=None):
    """One plain question to a model. Returns (text, input tokens, output tokens)."""
    if provider == "anthropic":
        r = client.messages.create(
            model=model, max_tokens=16000, system=system, messages=[{"role": "user", "content": prompt}]
        )
        text = "\n".join(b.text for b in r.content if b.type == "text")
        return text, r.usage.input_tokens, r.usage.output_tokens
    r = client.chat.completions.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        extra_headers={"x-opencode-session": str(uuid.uuid4())},
        **({"reasoning_effort": effort} if effort else {}),
    )
    return r.choices[0].message.content or "", r.usage.prompt_tokens, r.usage.completion_tokens


def make_reviewer(mode, client=None, provider=None, supervisor_model=None, supervisor_effort=None):
    """A function for run_once: report text -> (nudge or None, details to record)."""
    if mode in NUDGES:
        return lambda report: (NUDGES[mode] + CLOSING, {"mode": mode})

    def supervisor(report):
        text, tokens_in, tokens_out = ask(
            client, provider, supervisor_model, SUPERVISOR_SYSTEM, SUPERVISOR_PROMPT.format(report=report),
            supervisor_effort,
        )
        meta = {
            "mode": mode,
            "supervisor_model": supervisor_model,
            "supervisor_reply": text,
            "supervisor_input_tokens": tokens_in,
            "supervisor_output_tokens": tokens_out,
        }
        questions = text.strip()
        # An empty reply is a failed call (typically the output cap spent on reasoning), not a "no questions".
        meta["supervisor_failed"] = not questions
        if not questions or questions.upper().startswith("NONE"):
            return None, meta
        return SUPERVISOR_FRAME.format(questions=questions) + CLOSING.strip(), meta

    return supervisor


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", default="opencode-go", choices=PROVIDERS)
    p.add_argument("--model", required=True, help="the agent that investigates")
    p.add_argument("--supervisor-model", help="required for the supervisor mode")
    p.add_argument("--supervisor-effort", help="reasoning effort for the supervisor, e.g. low")
    p.add_argument("--modes", default=",".join(MODES), help=f"comma-separated, from: {', '.join(MODES)}")
    p.add_argument("--loci", type=Path, default=Path("data/ecoli/loci"))
    p.add_argument("--only", help="comma-separated region names")
    p.add_argument("--condition", default="file", choices=["file", "inline"])
    p.add_argument("--reps", type=int, default=2)
    p.add_argument("--max-turns", type=int, default=30, help="turns before the first report")
    p.add_argument("--review-turns", type=int, default=15, help="turns after the nudge")
    p.add_argument("--out", type=Path, help="default results/supervised/<model>")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    modes = args.modes.split(",")
    if unknown := set(modes) - set(MODES):
        p.error(f"unknown mode: {', '.join(sorted(unknown))}")
    if "supervisor" in modes and not args.supervisor_model:
        p.error("--supervisor-model is required for the supervisor mode")
    loci = sorted(args.loci.glob("*.fasta"))
    if args.only:
        wanted = set(args.only.split(","))
        if missing := wanted - {locus.stem for locus in loci}:
            p.error(f"not in {args.loci}: {', '.join(sorted(missing))}")
        loci = [locus for locus in loci if locus.stem in wanted]
    out_dir = args.out or Path("results/supervised") / args.model

    jobs = []
    for mode in modes:
        for locus in loci:
            for rep in range(args.reps):
                out = out_dir / mode / f"{locus.stem}__{args.condition}__{rep}.json"
                if not out.exists():
                    jobs.append((mode, locus, rep, out))
    total = len(modes) * len(loci) * args.reps
    print(f"{len(jobs)} runs to do in {out_dir} ({total - len(jobs)} already saved)")
    if args.dry_run or not jobs:
        return

    client = make_client(args.provider)
    auth_error, other_errors = api_errors(args.provider)

    def work(job):
        mode, locus, rep, out = job
        record = run_once(
            client,
            locus,
            args.condition,
            model=args.model,
            effort=None if args.provider != "anthropic" else "medium",
            read_default=2000,
            max_turns=args.max_turns,
            chat_cls=chat_class(args.provider),
            reviewer=make_reviewer(mode, client, args.provider, args.supervisor_model, args.supervisor_effort),
            review_turns=args.review_turns,
        )
        record.update(provider=args.provider, rep=rep, review_mode=mode, code_hash=CODE_HASH)
        (out.parent / "transcripts").mkdir(parents=True, exist_ok=True)
        (out.parent / "transcripts" / out.name).write_text(json.dumps(record.pop("transcript"), indent=2) + "\n")
        out.write_text(json.dumps(record, indent=2) + "\n")
        return record

    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, job): job for job in jobs}
        for future in as_completed(futures):
            mode, locus, rep, _ = futures[future]
            label = f"{mode} {locus.stem} #{rep}"
            try:
                record = future.result()
            except auth_error:
                raise SystemExit("authentication failed: check your API key")
            except other_errors as e:
                failed += 1
                print(f"{label}: {type(e).__name__}: {e}; rerun to resume")
            else:
                review = record["review"] or {}
                outcome = (
                    "revised" if review.get("revised") else "not revised" if review.get("nudge")
                    else "SUPERVISOR RETURNED NOTHING" if review.get("supervisor_failed") else "no nudge sent"
                )
                print(f"{label}: {outcome}, {review.get('tool_calls', 0)} tool calls after the nudge")
    print(f"done: {len(jobs) - failed} saved, {failed} failed")


if __name__ == "__main__":
    main()
