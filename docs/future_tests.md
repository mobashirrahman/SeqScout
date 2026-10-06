# Future tests

Experiment plans and their status. Updated 2026-10-06.

## Where we are

The first batch (DeepSeek V4.1 Flash, 60 runs, synthetic regions) hit a ceiling:
the planted repeat array was found and located in 15/15 positive runs in both
the `file` and `inline` conditions, with 0/15 false alarms on controls. The
agent always read the file and routinely ran a repeat search, and a near-exact
tandem repeat in random background cannot hide from that. In 8 of 30 control
runs the report presented some other feature of random sequence as notable.

So the next test has to be harder. Results are in `results/synthetic/deepseek-v4.1-flash/`.

The agreed scope is the E. coli-only pilot before adding human or yeast
features. Both 72-run batches are complete: `deepseek-v4.1-flash` and
`glm-5.3-flash`, with transcripts, the same 20-turn cap and one fixed
`kimi-k2.7-code` judge. All 134 nonempty reports have been judged; DeepSeek
has one empty report and GLM has nine. DeepSeek found and located the CRISPR
target in 12/12 scored CRISPR runs, and GLM in 11/11. Neither model identified
the insertion-sequence or frameshift targets in any scored run. Final results
are in [`results/ecoli/comparison.md`](../results/ecoli/comparison.md), with concrete
errors and interpretation limits in [`audit_notes.md`](../results/ecoli/audit_notes.md).

## Plan 1: isolated discovery benchmark

Recorded from the portfolio discussion on 2026-10-06. The
[isolated runner](isolation.md) is implemented and tested with Landlock,
seccomp, explicit input/tool lists and resource limits. No isolated model batch
has been run yet. The user clarified that discovery is the main objective:
models should choose what to investigate, propose findings and substantiate
them. The current plan is a 24-case discovery pilot, then expansion toward
about 500 cases if the task and validation work. Details are in
[`docs/discovery_benchmark.md`](discovery_benchmark.md).

The [Anthropic ART workflow note](anthropic_workflow.md) maps the motivating
study to an offline adaptation: small comparative panels, skeptical review,
bounded follow-ups and an auditable candidate funnel. It distinguishes our
current fixed-input recognition tests from a full discovery campaign and records
the paper's validation limits.

Public-benchmark research is recorded in
[`docs/benchmark_reuse.md`](benchmark_reuse.md). LAB-Bench SeqQA provides
600 released questions; SeqQA2 provides 400 open-answer tasks with file/inline
modes, and GenomeQA provides 5,200 raw-DNA inference records. Access, licensing,
missing-reference and scoring differences matter. These are optional competency
checks; they do not define the main discovery task. Closer method references
include StatefulDiscovery, TruthInsightBench and DiscoveryBench, discussed in
the discovery plan. No public-benchmark adapter or model run has been implemented.

Harness and budget design lessons from the Generality Labs study and its linked
METR note are recorded in [`docs/harness_study.md`](harness_study.md).
The proposed comparison keeps our shared isolated loop, adds cumulative budgets
and delivery/failure accounting, and tests a baseline allowance against three
times that allowance on development cases. Compaction is a separate
experiment if context growth requires it. These changes remain proposals:
the current runner still has a turn cap and no cumulative token cap or compaction.

The idea is to measure what an agent discovers from supplied data and its own
code, preserving how it selected, tested and revised hypotheses. Several
findings can be valid within one case. Score observation validity, independent
confirmation, novelty status and report delivery separately. Fresh generated
cases and blinded known features calibrate discovery skills; real open-data
cases permit candidate new findings without a predetermined answer.

**Execution environment.** Give every run a fresh, disposable worker with no
network access and only Python's standard library. Exclude BLAST, HMMER,
Biopython, NumPy and package installers. Agents may write their own algorithms.
Expose the supplied sequence read-only, provide a temporary writable workspace,
and keep answer keys, API credentials and host files outside the worker. Enforce
network, filesystem, dependency and resource limits at the operating-system
level; prompt instructions are insufficient.

The model API client stays outside the offline worker. It forwards only the
allowed file and Python operations and receives their outputs; generated code
always executes inside the worker. This permits hosted model inference without
giving the agent's analysis code internet access. Verify isolation with tests
for network attempts, unavailable packages, host-file access and state leaking
between runs before using the runner for scored experiments.
The implemented runner controls file contents but leaves basic host path
metadata visible; full namespace isolation would require a host that permits
container namespaces. Keep this boundary explicit in published results.

**Discovery cases.** Freeze the broad prompt, supplied inputs, private calibration
references and validation rules before comparing models. Start with generated
sequences and E. coli examples; human and yeast remain later extensions. The
provisional development pilot is:

| Cases | Setting | What it tests |
|---:|---|---|
| 6 | Fresh hidden structures or relationships | Choosing and verifying an unannounced pattern |
| 6 | Blinded real sequence cases | Recovery of independently checked observations |
| 6 | Open real-data exploration | Candidate findings without an expected answer |
| 6 | Matched controls | Supported claims and appropriate abstention |

Use generated examples where exact truth is available and independently
reviewed real annotations elsewhere. Curate complete CRISPR boundaries rather
than reuse approximate core intervals as exact truth. Mark the evidence needed
to support functional claims explicitly; the source annotation alone does
not make every function inferable from sequence. Group splits by source locus
or generation template so overlapping windows and near-duplicates cannot leak
between development and evaluation sets. Five hundred cases need not mean
500 independent biological examples; report both counts.

**Main task.** Give a broad investigation objective without naming the target
feature. The model submits up to three ranked claims, evidence and runnable
analyses; it can report no supported finding. It may explore and reject many
hypotheses internally. One final submission freezes claims before independent
validation, with no feedback from the hidden grader. Public direct-question
accuracy is an optional separate result. Retain inline/file as a controlled
factor rather than silently mixing presentations.

**Scoring and records.** Validate measurable claims in code where possible.
The proposed [verification procedure](verification.md) distinguishes
sequence facts, statistical relationships, biological roles and novelty, with
a [claim review template](claim_review_template.md) for evidence and verdicts.
Accept independently supported findings beyond the private calibration targets.
Classify claims as verified, refuted or unresolved. For comparative findings,
freeze predictions and analysis before testing withheld samples. Genuine
biological novelty requires a documented external prior-art and validation
review after submission; that review does not give agents internet access.
Distinguish detection, coordinates, functional assignment, factual errors,
unsupported explanations and justified uncertainty. Record empty, malformed
and repetitive reports as delivery outcomes. Keep one fixed, blinded claim
extractor where needed; validate claims separately against sequence or curated
evidence, with manual review of a stratified sample. Save prompts, transcripts,
scripts, stdout, stderr, exit codes, truncation flags, timing, tokens, model
versions and worker configuration. This makes execution failures observable
instead of inferring them only from traceback text.

**Rollout.** Validate discovery and review on the 24 development cases first.
Two models require 48 runs at one budget, or 96 for a B-versus-3B comparison,
excluding calibration and repetitions. Freeze the protocol before expanding
toward 500 cases, which requires 1,000 runs for one condition. Estimate the
budget from the smaller batch, keep equal tool and token limits,
and test a higher turn cap as a separate experiment. Isolation prevents live
lookup; it does not rule out sequence memorisation from model training.

## Test 1: real sequence with annotated features

Give the agent windows cut from a real, well-annotated genome and score whether
it finds the annotated feature.

### What changes with real sequence

- The background is no longer random. Real DNA has genes, biased composition
  and its own small repeats, so a routine repeat search no longer gives a clean
  answer. This is the main source of extra difficulty.
- The model may recognise the sequence from training data. Keep neutral file
  names, optionally reverse-complement the window, and record whether the agent
  names the organism or gene.
- Ground truth is incomplete. "Found the annotated feature" can be scored, but
  an extra claim is not automatically a false alarm.
- The original pilot did not enforce the intended sequence-only restriction.
  GLM retrieved an external BLAST result via `urllib` and installed
  Biopython/NumPy with `pip`. The current runner blocks those actions; a new
  isolated batch is needed before drawing offline conclusions. Isolation
  alone cannot establish whether a model memorised the sequence.

### Candidate features

Stay with well-annotated, harmless lab organisms.

| Difficulty | Feature | Source | Why |
|---|---|---|---|
| Moderate | CRISPR repeat-spacer array | *E. coli* K-12 | Closest real analogue of the synthetic task: short repeats with unique spacers, in real background |
| Moderate | Insertion sequence with inverted terminal repeats | *E. coli* K-12 | Needs an inverted-repeat search plus noticing an ORF between the ends |
| Moderate | CpG island | Human | Found by composition statistics, not repeats |
| Moderate | Centromere (short conserved elements around a very AT-rich core) | Yeast | A compositional signature about 125 bases long, easy to overlook |
| Hard | Degenerate tandem repeat (alpha satellite, monomers about 70-80% identical) | Human | Natural hard version of the first batch; exact-match searches fail |
| Hard | Programmed frameshift (one gene split across two reading frames) | *E. coli* K-12 `prfB` | Requires noticing that two adjacent ORFs belong together |
| Hard | Non-standard genetic code | Yeast mitochondrial DNA | ORFs look broken until the agent questions its own assumption |

Controls: windows from the same genome that hold only ordinary genes.

### Recommended first set

About 12 windows from *E. coli* K-12 (one genome, one annotation file):

- 2 CRISPR array windows
- 3 insertion-sequence windows
- 1 `prfB` frameshift window
- 6 gene-only control windows

Implemented in `fetch_ecoli.py` and `data/ecoli/`. Insertion-sequence and
`prfB` coordinates come from the genome annotation. The CRISPR arrays are
not annotated in that record: their truth intervals were found by a repeat
search near `cas2` and cover approximate conserved cores. They must not be
treated as exact full-array boundaries or copy counts. In region_010,
three additional variant copies extend beyond the ten-copy conserved core.
If the agent identifies the organism often, test a less familiar genome;
names and guesses alone do not establish memorisation.

### Harness changes needed

These changes have been implemented for the pilot:

- A fetch script that downloads a genome record, cuts windows and writes the
  truth files from its annotation, except the approximate CRISPR cores found
  by repeat search.
- A broader judge that lists every claimed feature with a type from a fixed
  vocabulary and coordinates. Analysis matches those claims against the
  saved targets.
- A recognition check that flags runs where the agent names the organism or
  locus.

### Cautions

- Earlier downloads in this project were stopped by a safety classifier when
  they touched the phage material from the Yoon et al. preprint. *E. coli* K-12
  and yeast should be unproblematic, but this is untested.
- Longer or richer windows cost more tokens per run. The first batch used about
  140,000 input tokens per run on 3,000-base windows.

## Test 2: harder synthetic regions

Cheaper alternative or complement to Test 1, with exact ground truth:

- more mutation between copies (10-30%)
- fewer copies (2-3)
- longer and more variable spacers
- a tighter tool budget (lower `--max-turns`) or a smaller `--read-default`
- scoring that accepts "unit plus spacer" as the unit length for spaced arrays

## Test 3: rerun DeepSeek with transcripts

The first batch has no transcripts, so the "noticed by reading versus found by
script" analysis exists for one pilot run only. A rerun of the same 60 runs
would supply it. The harness now saves transcripts automatically.
This rerun remains deferred; the E. coli batches are separate experiments,
not a transcript rerun of the original synthetic batch.

## Test 4: GLM-5.3 (deferred)

Stronger model, about ten times the price of DeepSeek V4.1 Flash, with a $15
monthly limit on the Go plan. Run it on a task that does not hit the ceiling,
with fewer repeats or a lower turn limit so it fits the allowance.
The current E. coli comparison uses `glm-5.3-flash`, a different model; it
does not complete this deferred full GLM-5.3 experiment.

## Other leads

- Possible over-claiming on controls is relevant to the thesis theme of agents
  challenging their own hypotheses. In the first batch, 8/30 control reports
  (27%) presented another feature as notable; that is a claim tally, not yet
  an independently validated over-claiming rate.
- On real DNA, distinguish extra correct findings from unsupported claims.
  Audit factual errors and unjustified functional assignments separately;
  the fraction of reports with an `other` feature is not an over-claiming rate.
- Record Python execution failures from transcripts. The existing run
  records count wrapper errors but omit subprocess tracebacks and timeouts.
- The pilot's turn cap frequently forces a report. A follow-up should vary
  that cap as a separate experiment and retain the current batch unchanged.

## Plan 2: worker and supervisor experiments

Recorded 2026-10-06 for later. None has produced a result yet.

Why: across six models on four sandboxed E. coli windows (48 runs), every
model found the CRISPR array and none found the `prfB` frameshift or the IS5
insertion sequence. Model size, price and reasoning budget made no difference.
The misses were interpretation failures: models found the transposase ORF, the
terminal inverted repeats or the phase break at the frameshift site, and did
not draw the conclusion. A reviewer might.

Before any of these: the direct-question experiment (`ask_direct.py`) shows
whether a model recognises the feature when asked. If it does, review has
something to unlock. If it does not, review alone will not help and 2b becomes
the better bet.

### 2a. Basic worker and supervisor loop (design only)

- The worker ends with a structured list of claims: observation, evidence,
  interpretation, and a test that could disprove it.
- The supervisor sees only those claims, never the worker's chat, the sequence
  or the answer. It has two duties:
  - sceptic: name the strongest competing explanation and a concrete test for
    each claim, then mark it accepted, rejected or unresolved;
  - rescuer: review what the worker dismissed and ask whether the dismissal
    was justified.
- Use a different model as supervisor so the two do not share blind spots,
  cap at two rounds, and count supervisor tokens in the run's budget.
- Score both failure directions: unsupported claims removed, and true
  findings lost.

### 2b. Supervisor with a DNA-model tool (design only)

Give a DNA language model to the supervisor, not the worker, so discovery
stays unassisted and validation is an explicit, logged step. The tool would
run outside the sandbox and offer three narrow calls: a surprise profile for a
coordinate range against a shuffled baseline, a comparison of the original
region with an edited version, and similarity between two regions.

| | No DNA tool | With DNA tool |
|---|---|---|
| Solo agent | baseline | does the tool help or inflate claims? |
| Worker + supervisor | does review cut unsupported claims? | full workflow |

Score target found, unsupported claims, true evidence wrongly dismissed and
total tokens. Open points: whether its per-position scores are informative on
3,000-base windows, and that *E. coli* K-12 is almost certainly in its
training data. Classical tools (repeat finders, profile searches, gene
callers) are the stronger baseline for these particular targets.

Model choice is analysed in [`dna_model_choice.md`](dna_model_choice.md).
Evo 2 is unusable on this GPU: it requires FP8, which Turing does not have, and
the 7B checkpoint needs about 14 GB. The proposal is seqLens v2 Micro 16K
(10M, single-nucleotide, prokaryote-only, 16k context) with ProkBERT-mini-c as
a stock-`transformers` fallback and GenomeOcean-500M as an autoregressive
cross-check. Published work does not evaluate any of these on frameshifts or
insertion sequences, so the calibration gate comes first: if the surprise
profile does not mark the CRISPR array that every model already finds, drop 2b
rather than run it. Nothing is downloaded and no model has been run.

### 2c. Nudge ladder (built, not yet run)

After its first report the worker gets one nudge, works again and writes a
revised report. Both reports are kept and judged, so each run is a
before-and-after pair. Code: `supervise.py`, `summarize_supervision.py`.

| Nudge | What it tests |
|---|---|
| `again` | control: does a second pass alone help? |
| `reflect` | does self-review recover dismissed evidence? |
| `supervisor` | questions from a bigger model that read only the report |
| `checklist` | upper bound; names feature classes, so it gives hints |

- Full pilot: 4 windows x 4 nudges x 2 repetitions = 32 runs.
- Lean pilot: `prfB`, IS5 and one control x `again`, `reflect`, `supervisor`
  x 1 repetition = 9 runs, Hy3 as worker, 20 turns before and 8 after the
  nudge.
- Blocker cleared 2026-10-06: `--supervisor-model glm-5.2 --supervisor-effort low`
  returns usable questions. Checked on the saved `hy3` `region_006` report:
  915 input, 1,224 output tokens, three sequence-only questions, one of which
  caught an off-by-one in the reported ORF length and one of which asked why
  the ORF's truncation point and the GC swing do not coincide. Without the
  effort setting the earlier call burned its whole 16,000-token output
  allowance on reasoning and returned nothing, so keep the setting explicit.
- Expectation, stated in advance: `again` changes nothing; `reflect` and
  `supervisor` rarely reach the right name; IS5 is the likelier recovery;
  false alarms on the control rise slightly.

### 2d. Related ideas

- Shared notebook: a second run reads the first run's notes and continues.
  Do leads accumulate across attempts, or get dismissed again each time?
- Jev as a gate: a near-free yes/no check (`jev-1.13-free` on the
  `/zen/v1/systemone` endpoint) on whether a report has loose ends worth a
  supervisor call, and whether the supervisor's reply is usable.
- Rarity: run the open-ended task 30-50 times on one hard window to learn
  whether spontaneous discovery is never or merely rare.
- Calibration: ask for a confidence level on every claim and check whether it
  tracks correctness.

## Models

- Agents in the E. coli pilot: `deepseek-v4.1-flash` and `glm-5.3-flash`.
- Judge: `kimi-k2.7-code` (already $60 tier, different family from both agent
  models). `glm-5.2` is the other sensible $60 choice. Keep one judge fixed
  across everything that is compared.
