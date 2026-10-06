"""Run the same agent on the same DNA regions under two conditions.

  inline  the raw sequence is pasted into the prompt
  file    the sequence is only in a file the agent has to choose to open

Tools, system prompt, task wording and workspace are identical in both. The
only difference is whether the raw sequence is already in the model's context.
Each run is saved as one JSON file, so the script can be stopped and resumed.
"""
import argparse
import hashlib
import json
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backends import MAX_TOKENS, PROVIDERS, AnthropicChat, api_errors, chat_class, make_client
from isolation import DEFAULT_POLICY, IsolationError, load_policy, policy_hash
from tools import TOOL_DEFS, Workspace, longest_nt_run, read_fasta_sequence, seen_positions, to_intervals

CONDITIONS = ("inline", "file")
REGION_FILE = "region.fasta"

SYSTEM = "You are a genomics analyst working in a directory that holds sequence data."

# Deliberately says nothing about repeats or any other specific feature.
TASK = (
    f"The file {REGION_FILE} in your working directory holds a DNA region of unknown "
    "function. Investigate it and write a short report describing anything notable "
    "about the sequence. If nothing stands out, say so. Give coordinates for any "
    "feature you describe."
)
LIMIT_NOTE = "You have reached the limit on tool calls. Write your final report now from what you have found."
RESCUE_NOTE = "Your last message contained no report. Write your final report now from what you have found. Do not call any tools."
INLINE_SUFFIX = "\n\nFor convenience, here is the content of the file:\n\n<file>\n{fasta}</file>"


def _digest(*parts):
    return hashlib.sha256(b"\0".join(parts)).hexdigest()[:12]


# Changes whenever the wording the agent sees changes, so runs from different prompts are never pooled by accident.
PROMPT_HASH = _digest(json.dumps([SYSTEM, TASK, INLINE_SUFFIX, LIMIT_NOTE, RESCUE_NOTE, TOOL_DEFS], sort_keys=True).encode())
# Changes whenever the harness code changes.
CODE_HASH = _digest(*(Path(__file__).with_name(n).read_bytes() for n in
                      ("harness.py", "backends.py", "tools.py", "isolation.py", "sandbox_worker.py", "sandbox_policy.json")))


def build_prompt(condition, fasta, task=TASK):
    return task + (INLINE_SUFFIX.format(fasta=fasta) if condition == "inline" else "")


_TOOL_CALL_TEXT = re.compile(r'\s*(<\|?tool_call|\{\s*"(name|tool|function|tool_calls)"\s*:)')


def has_report(text):
    """False for an empty message, and for one that is only a tool call written out as text."""
    return bool(text.strip()) and not _TOOL_CALL_TEXT.match(text)


def run_once(client, locus_path, condition, *, model, effort, read_default, max_turns, chat_cls=AnthropicChat,
             policy_path=None, max_output_tokens=MAX_TOKENS, reviewer=None, review_turns=15, task=TASK):
    """Run one agent to completion and return its record.

    `reviewer`, if given, is called with the agent's report and returns
    (nudge text or None, details to record). A nudge sends the agent back to
    work for up to `review_turns` more turns and a revised report.
    """
    fasta = Path(locus_path).read_text()
    sequence = read_fasta_sequence(fasta)
    seen = set()
    started = time.monotonic()
    record = {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_hash": PROMPT_HASH,
        "code_hash": CODE_HASH,
        "locus": Path(locus_path).stem,
        "condition": condition,
        "model": model,
        "effort": effort,
        "read_default": read_default,
        "max_turns": max_turns,
        "max_output_tokens": max_output_tokens,
        "tool_calls": [],
        "turns": [],
        "request_ids": [],
        "served_models": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
    }
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(locus_path, Path(tmp) / REGION_FILE)
        workspace = Workspace(tmp, read_default=read_default, policy=policy_path)
        definitions = [t for t in TOOL_DEFS if t["name"] in workspace.policy["allowed_tools"]]
        record["isolation"] = workspace.metadata
        record["prompt_hash"] = _digest(json.dumps([SYSTEM, task, INLINE_SUFFIX, LIMIT_NOTE, RESCUE_NOTE, definitions], sort_keys=True).encode())
        chat = chat_cls(client, model, SYSTEM, build_prompt(condition, fasta, task), effort=effort, tool_defs=definitions,
                        max_tokens=max_output_tokens)

        def take_turn(final):
            turn_started = time.monotonic()
            turn = chat.step(final=final)
            record["request_ids"].append(turn.request_id)
            if turn.served_model and turn.served_model not in record["served_models"]:
                record["served_models"].append(turn.served_model)
            record["input_tokens"] += turn.input_tokens
            record["output_tokens"] += turn.output_tokens
            record["cached_tokens"] += turn.cached_tokens
            record["turns"].append(
                {
                    "status": turn.status,
                    "input_tokens": turn.input_tokens,
                    "output_tokens": turn.output_tokens,
                    "cached_tokens": turn.cached_tokens,
                    "tool_calls": len(turn.tool_calls),
                    "seconds": round(time.monotonic() - turn_started, 1),
                }
            )
            return turn

        turns_done = 0

        def investigate(budget):
            """Let the agent work for up to `budget` turns. Returns (last turn, hit the limit, rescue reason)."""
            nonlocal turns_done
            # The last turn forbids tools, so a run that is still exploring at the
            # limit hands in a report instead of being lost.
            turn = None
            for i in range(budget):
                last = i == budget - 1
                turn = take_turn(final=last)
                if turn.status != "tool_use":
                    break

                results = []
                for call_id, name, args in turn.tool_calls:
                    if args is None:
                        output, is_error = "error: tool arguments were not a valid JSON object", True
                    else:
                        output, is_error = workspace.call(name, args)
                    seen.update(seen_positions(output, sequence))
                    record["tool_calls"].append(
                        {
                            "turn": turns_done + i,
                            "name": name,
                            "input": args,
                            "is_error": is_error,
                            "output_chars": len(output),
                            "nt_run": longest_nt_run(output),
                            "execution": workspace.last_execution if args is not None else None,
                        }
                    )
                    results.append((call_id, output, is_error))
                chat.add_results(results, note=LIMIT_NOTE if i == budget - 2 else None)
            turns_done += i + 1

            # One reserved call. A phase that ends without report text (the output cap spent on
            # reasoning, or a tool call made at the limit) is asked once more for its report.
            rescue = None
            if turn.status != "refusal" and not has_report(turn.text):
                rescue = "tool_calls_at_limit" if turn.status == "tool_use" else f"empty_after_{turn.status}"
                chat.add_results([], note=RESCUE_NOTE)
                turn = take_turn(final=True)
            return turn, last, rescue

        turn, last, record["rescue"] = investigate(max_turns)

        # Optional review: the reviewer reads the report and may send the agent back to work once.
        record["review"] = None
        if reviewer and has_report(turn.text):
            first = turn
            nudge, meta = reviewer(first.text)
            record["review"] = {**meta, "nudge": nudge}
            if nudge:
                record["first_report"] = first.text
                calls_before = len(record["tool_calls"])
                chat.add_results([], note=nudge)
                turn, hit_limit, rescue = investigate(review_turns)
                record["review"].update(
                    forced_report=hit_limit,
                    rescue=rescue,
                    tool_calls=len(record["tool_calls"]) - calls_before,
                    revised=has_report(turn.text),
                )
                if not has_report(turn.text):
                    turn = first  # a failed revision must not cost the run its first report

    # No fallback model on refusal: a silent model swap would confound the comparison.
    # A refusal is recorded as its own outcome instead.
    record["status"] = "max_turns" if turn.status == "tool_use" else turn.status
    record["forced_report"] = last
    record["refusal_category"] = turn.refusal_category
    record["report"] = turn.text if has_report(turn.text) else ""
    record["nt_run_from_tools"] = max((c["nt_run"] for c in record["tool_calls"]), default=0)
    # Which parts of the region tool results actually showed the agent, as 1-based intervals.
    record["seen_intervals"] = to_intervals(seen)
    record["tool_errors"] = sum(c["is_error"] for c in record["tool_calls"])
    record["seconds"] = round(time.monotonic() - started, 1)
    record["transcript"] = chat.transcript()
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider", default="anthropic", choices=PROVIDERS)
    p.add_argument("--model", help="default claude-opus-5-5 for anthropic; required for the opencode providers")
    p.add_argument("--loci", type=Path, default=Path("data/synthetic/loci"))
    p.add_argument("--out", type=Path, help="default results/synthetic/<model>")
    p.add_argument("--reps", type=int, default=3, help="runs per locus per condition")
    p.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="reasoning effort; default medium for anthropic, the model's own default otherwise",
    )
    p.add_argument("--read-default", type=int, default=2000, help="characters read_file returns by default")
    p.add_argument("--max-turns", type=int, default=20)
    p.add_argument("--max-output-tokens", type=int, default=MAX_TOKENS, help="cap on each model response")
    p.add_argument("--only", help="comma-separated region names to run, e.g. region_004,region_006")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--dry-run", action="store_true", help="list the runs that would be made and exit")
    p.add_argument("--sandbox-policy", type=Path, default=DEFAULT_POLICY,
                   help="allowed tools and worker resource limits; isolated execution is mandatory")
    args = p.parse_args()
    if args.max_turns < 1 or args.workers < 1 or args.reps < 1 or args.read_default < 1:
        p.error("turns, workers, repetitions and read-default must be positive")
    try:
        policy = load_policy(args.sandbox_policy)
    except (OSError, ValueError) as error:
        p.error(str(error))
    if REGION_FILE not in policy["input_files"]:
        p.error(f"input_files must include {REGION_FILE} for this DNA harness")

    if args.model is None:
        if args.provider != "anthropic":
            p.error(f"--model is required with --provider {args.provider} (e.g. glm-5.3, kimi-k3, deepseek-v4-pro)")
        args.model = "claude-opus-5-5"
    effort = args.effort or ("medium" if args.provider == "anthropic" else None)
    out_dir = args.out or Path("results/synthetic") / args.model

    loci = sorted(args.loci.glob("*.fasta"))
    if args.only:
        wanted = set(args.only.split(","))
        missing = wanted - {locus.stem for locus in loci}
        if missing:
            p.error(f"not in {args.loci}: {', '.join(sorted(missing))}")
        loci = [locus for locus in loci if locus.stem in wanted]
    if not loci:
        raise SystemExit(f"no .fasta files in {args.loci}; run make_loci.py first")
    (out_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    # Historical unrestricted runs must never be silently mixed with this batch.
    for saved in out_dir.glob("*.json"):
        existing = json.loads(saved.read_text())
        isolation = existing.get("isolation", {})
        if (not isolation.get("setup_verified") or isolation.get("policy_hash") != policy_hash(policy)
                or existing.get("code_hash") != CODE_HASH):
            p.error(f"{saved} has a different execution policy/code; choose a fresh --out directory")

    jobs = []
    for locus in loci:
        for condition in CONDITIONS:
            for rep in range(args.reps):
                out = out_dir / f"{locus.stem}__{condition}__{rep}.json"
                if not out.exists():
                    jobs.append((locus, condition, rep, out))
    total = len(loci) * len(CONDITIONS) * args.reps
    print(f"{len(jobs)} runs to do in {out_dir} ({total - len(jobs)} already saved)")
    if args.dry_run or not jobs:
        return

    # Verify kernel enforcement before constructing a client or making API calls.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            Workspace(tmp, read_default=args.read_default, policy=policy)
    except (IsolationError, OSError) as error:
        p.error(str(error))
    client = make_client(args.provider)
    auth_error, other_errors = api_errors(args.provider)

    def work(job):
        locus, condition, rep, out = job
        record = run_once(
            client,
            locus,
            condition,
            model=args.model,
            effort=effort,
            read_default=args.read_default,
            max_turns=args.max_turns,
            max_output_tokens=args.max_output_tokens,
            chat_cls=chat_class(args.provider),
            policy_path=policy,
        )
        record["provider"] = args.provider
        record["rep"] = rep
        # Kept apart from the run record: it is large and holds every tool output.
        transcript = record.pop("transcript")
        (out_dir / "transcripts" / out.name).write_text(json.dumps(transcript, indent=2) + "\n")
        out.write_text(json.dumps(record, indent=2) + "\n")
        return record

    tokens_in = tokens_out = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, job): job for job in jobs}
        for future in as_completed(futures):
            locus, condition, rep, _ = futures[future]
            label = f"{locus.stem} {condition} #{rep}"
            try:
                record = future.result()
            except auth_error:
                raise SystemExit("authentication failed: check your API key")
            except other_errors as e:
                failed += 1
                print(f"{label}: {type(e).__name__}: {e}; rerun to resume")
            else:
                tokens_in += record["input_tokens"]
                tokens_out += record["output_tokens"]
                notes = "".join(
                    f", {text}" for flag, text in (
                        (record["forced_report"], "hit turn limit"),
                        (record["rescue"], f"rescued ({record['rescue']})"),
                        (not record["report"], "NO REPORT"),
                    ) if flag
                )
                print(f"{label}: {record['status']}, {len(record['tool_calls'])} tool calls{notes}")
    print(f"done: {len(jobs) - failed} saved, {failed} failed; {tokens_in} input / {tokens_out} output tokens")


if __name__ == "__main__":
    main()
