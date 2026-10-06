# Harness and budget lessons for our DNA benchmark

Read on 2026-10-06. This note compares published methods with our runner and
proposes experiments. No runner code was changed and no model API calls were made.
The user now prioritizes discovery. The rollout below uses discovery cases;
the claim and validation contract is in
[`discovery_benchmark.md`](discovery_benchmark.md).

## Sources and interpretation

Pablo Romero's September 28 research write-up,
[Does the harness matter when running Cyber Benchmarks?](https://generality.org/blog/posts/exploitbench-harnesses/),
compares our exact models on ten ExploitBench tasks across seven harness
configurations. Extended configurations use 250 million tokens per task;
the original uses a 300-turn limit without compaction. Claude Code performs
best for DeepSeek but worst for GLM in that experiment. The authors acknowledge
the small sample and do not establish why the rankings differ.

They suggest a handoff-style compaction prompt helps agents continue, after
observing repetitive submissions. That explanation is a hypothesis. They also
disclose a ReAct configuration error causing compaction at 100K tokens.
The comparison changes bundled harness behavior, rather than isolating summary
wording. The chart JSON was inaccessible through the web tool; this note does
not reconstruct numerical scores from chart images.

The preceding [September 8 GLM budget experiment](https://generality.org/blog/posts/glm-flash-exploitbench/)
uses up to one billion tokens per vulnerability and continues until full success
or the budget limit. It argues for measuring capability against spending as
well as tokens. Its cost comparison uses discounted GLM evaluation prices and
historical reference-model prices. Errors are handled by carrying forward the
last observed score. This is a capability-scaling experiment with a different
stopping rule from our final-claim-submission benchmark. Its headline cost ratio
should not be transplanted into our study.

The linked [METR research note](https://metr.org/notes/2026-02-13-measuring-time-horizon-using-claude-code-and-codex/)
finds no statistically significant advantage for the tested vendor harnesses
over its default scaffolds on its models/tasks. It adds remaining-token
messages and timeout retries, manually reviews large performance discrepancies,
and plots success against token use. A larger-budget check makes little
difference for one tested configuration. These findings motivate testing
harness effects on our tasks; they do not identify a universally best harness.

## What our runner already measures

The [harness](../src/harness.py) uses a shared agent loop, three explicit tools and
a fresh restricted workspace per run. It preserves transcripts, per-turn
input/output/cache usage and inference timing, requested and served model IDs,
prompt/code hashes, and structured tool execution records. Keep the
[offline policy](isolation.md) fixed across proposed conditions.

| Area | Current behavior | Proposed change before scoring the suite |
|---|---|---|
| Run budget | Turn cap; 16,000-token maximum per API response | Cumulative token limits, total run deadline and distinct stop reasons |
| Budget awareness | Final-turn warning only | Neutral remaining-resource messages, identical for both models |
| Context | Full conversation replayed; no compaction | Record context growth; test compaction separately if needed |
| Delivery | Last allowed turn forbids tools; response exhaustion can end a run sooner | Reserve finalization and measure remaining empty/malformed answers |
| Failure persistence | Whole records saved at completion; API failures printed for resume | Assignment manifest, partial checkpoints and durable failure records |
| Settings | Go adapter does not pass reasoning effort or temperature | Record request settings, visible defaults and unknown gateway settings |
| Usage coverage | Agent tokens; historical judge usage missing | Separate agent, finalization, compaction, retry and judge usage |

The adapters expose different provider usage fields. Verify their meanings and
normalize them before enforcing a common budget; identical field names do not
establish equivalent accounting. SDK retries currently happen inside the client,
so saved successful responses do not describe every API attempt.

## Evidence from our historical pilot

Recomputed from all 72 saved E. coli records per model. These are historical
unrestricted runs, not results from the offline worker or SeqQA. See the
[pilot comparison](../results/ecoli/comparison.md).

| Measure | DeepSeek V4.1 Flash | GLM-5.3-Flash |
|---|---:|---:|
| Runs at the forced final turn | 42/72 | 41/72 |
| Median recorded turns | 20 | 20 |
| Median cumulative input + output tokens | 347,823 | 195,013 |
| Median cumulative output tokens | 33,581 | 17,308.5 |
| Empty reports ending at the response token limit | 1 | 8 |
| Other empty reports | 0 | 1 |

For these Go records, cached input is a reported subset of input. Cumulative
input includes repeatedly submitted conversation history; it is not the length
of one context window. Equal turns did not produce equal token use. Arrival at
the forced final turn does not prove that a longer run would solve the task.
An empty report at the response cap is a delivery outcome, not evidence by
itself of a biological reasoning failure.

## Proposed budget comparison

Separate two questions:

1. **Controlled resources:** same task, tools, presentation, cumulative
   generated-token allowance and safety limits for both models. Count reasoning
   within that allowance when the provider includes it in completion tokens;
   verify the convention first and mark missing breakdowns as unknown. Add a
   cumulative input-plus-output cap and run deadline to bound runaway work.
   Cached input counts once in this processing total, despite its lower price.
2. **Practical efficiency:** validated finding yield and claim outcomes against
   measured tokens, cost and elapsed
   time. An optional equal-spending experiment needs its own condition label.
   Freeze provider, pricing date, rates and cache treatment. Separate estimates
   from confirmed charges; tokens are not identical physical compute across models.

Calibrate one shared baseline allowance **B** on development examples, then
compare **B** with **3B** on matched questions. Their enormous allowances are
not targets for our study. Freeze B before the held-out evaluation; increasing
only the losing model's budget after seeing scores would change the comparison.

Set turn and input safeguards high enough that they do not silently become the
main constraint in the generated-budget experiment, and report when each binds.
For inline/file comparisons, presentation can itself increase input use. Keep
that efficiency difference visible in token and cost reporting.

Tell the agent its remaining resources without hinting at target features.
Derive each response limit from the remaining allowance and reserve a
finalization call. Summaries and final answers count toward the run total.
A reservation alone cannot guarantee text delivery if reasoning consumes the
final response; provider controls and final-answer formatting need validation.

## Compaction and tools

Keep the simple loop for the first batch. Short sequence tasks may never need
compaction. Response limits, finalization and usage accounting deserve attention
first. Do not adopt a whole CLI harness because it ranked well on cyber tasks;
that would change prompts, tools, continuation and context handling together.

If compaction becomes necessary, test one structured handoff policy against
the ordinary loop with all other settings fixed. Preserve:

- The question, input-file paths and sequence identity.
- Findings with coordinates, strand, units and supporting evidence paths.
- Saved scripts, successful checks and failed approaches.
- Remaining uncertainty, the next concrete operation and resource budget.
- Whether a final answer has already been submitted.

Keep the full transcript outside model context. Inputs and scratch files remain
available after compaction. Save summaries, triggers, token usage and retained
message IDs. Review a sample for invented facts, lost coordinates and dropped
uncertainty. A summary is agent-generated state, not ground truth for scoring.

Where ordinary runs fit in context, use a separately labelled stress subset
to investigate compaction. If testing an artificially low trigger, say so.
Compare against an uncompacted reference that still fits the model's context;
an overflowing reference would confound memory management with task solving.

Our file tools already support bounded reads; Python can analyse a permitted
file without printing its whole sequence. Preserve this design. Tool descriptions
should make scratch persistence, fresh interpreters, indexing, limits and
truncation clear. Wording changes apply equally to both models and both
presentations, with a new recorded prompt hash. Avoid feature-specific hints.

## Submission, curves and failure rules

Freeze one ranked claim-and-evidence submission per discovery run, then stop.
The agent may test and revise many hypotheses internally before submitting.
Do not resume merely to spend the remaining budget, or feed hidden-grader
feedback into the run.
Continuing after rejection would measure feedback-assisted search and requires
a separate protocol.

Fresh runs at B and 3B give the clearest comparison. A single 3B run can also
show when its final submission arrived; unfinished runs count as unsuccessful at
earlier checkpoints. That curve does not predict what a budget-aware agent
would submit when actually capped at B. Confirmation and novelty checks happen
after claims are frozen. Intermediate drafts are not additional benchmark
submissions, and provider usage arrives in response-sized increments.

Keep every assigned case in the validated-finding yield denominator. Separately
report delivery, API, isolation, tool-limit, parsing and answer errors. Fix any
infrastructure retry policy in advance, retain original failures and observable
extra usage, and apply it equally. Do not silently retain only successful attempts.

Check coordinates, quantities and controlled hidden relationships in code.
Evaluate other claims through independent evidence and documented review;
an LLM judge alone does not establish biological truth or novelty. Record judge
versions and tokens when one is used. Flag repeated calls and repeated output
for analysis before introducing a new loop-based stopping policy.

## Development experiment and rollout

1. Review 24 development discovery cases across hidden structures, blinded
   real data, open exploration and matched controls. Keep calibration keys and
   confirmation material private, and validate the claim-review contract.
2. Calibrate B with a small development batch. Then compare both models at B
   and 3B using one presentation and the shared isolated loop:
   **24 cases × 2 models × 2 budgets = 96 runs**, before repetitions and
   excluding the calibration batch. This is a proposal; no batch was launched.
3. Inspect limits, delivery, errors, context growth and a stratified sample of
   verified, refuted and unresolved claims. Finalize the protocol on development
   data.
4. If warranted, test eight development stress cases with two models, the
   ordinary loop and one compaction policy, and two repetitions at a fixed
   budget: **64 additional runs**. Choose inputs where both context policies fit.
5. Freeze one main protocol. A 500-case suite requires 1,000 runs for one
   presentation, or 2,000 with inline/file, before repetitions.

These are our proposals, not methods validated on DNA by the cyber study.
Choose development cases before inspecting which model wins. Keep related
sequences, loci and generation templates grouped in held-out selection. We
lack the cross-model calibration needed to copy their IRT-based task selection.

Report paired model differences on the same cases, discovery-quality profiles,
delivery rate, budget-exhaustion rate and median/tail usage. Group uncertainty
by independent locus/template where appropriate; repetitions do not create
independent biological examples. Keep held-out cases out of prompt, budget
and harness selection. Public question-answering accuracy remains an optional
separate competency check.

The portfolio result can remain brief: what each model solves under documented
access and resource limits, how often it fails to deliver, and what its
transcripts reveal about those failures.
