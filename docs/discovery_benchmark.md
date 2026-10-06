# An offline benchmark for discovery

Direction updated on 2026-10-06 following the user's clarification: discovery
is the main objective. The models should choose what to investigate, form
hypotheses and produce evidence. Public question-answering sets remain optional
competency checks. This is a proposal; no new dataset, adapter or paid run exists.

## What one case looks like

The unit is a **discovery case**: a blinded sequence, a small panel of related
sequences, or sequences plus necessary measurement metadata. It can support
several valid findings. A broad scientific objective gives the agent a reason
to investigate without naming a target feature or supplying a conclusion.

Draft prompt:

> Investigate the supplied sequences and metadata. Choose up to three findings
> worth further investigation. For each, give a precise claim, supporting
> evidence, a test of a competing explanation, and a prediction or follow-up
> test that could disprove it. Save reproducible analysis code and state what
> the available data cannot establish. Reporting no supported finding is valid.

This prompt deliberately asks for scientific checks; report that scaffolding
rather than claiming the model performed them spontaneously. The model can
explore and reject many ideas internally. Its final submission freezes a small,
ranked set of claims and their evidence before independent validation.

Use neutral filenames and preserve scientifically necessary schema, units and
conditions. Exclude source-paper conclusions, answer-bearing annotation fields,
generator internals and grader files. Strip accidental hints without making
the data uninterpretable. Keep every permitted input and its checksum in a
manifest; the agent sees no internet or unapproved tooling.

## Four kinds of discovery case

| Case type | Agent task | What it can establish |
|---|---|---|
| Fresh hidden structure | Explore generated sequence panels with an undisclosed rule or relationship | Discovery of a previously unseen instance, with exact validation |
| Blinded real sequence | Explore curated E. coli data with selected conclusions hidden | Recovery of a real observation; useful calibration of discovery skills |
| Open real-data exploration | Choose and test a finding where no expected answer is fixed | A candidate new observation or hypothesis, subject to independent review |
| Matched controls | Explore background data with the tested relationship removed or absent by construction | Calibration of claims and appropriate abstention |

The first two assess discovery behavior with checkable references. They do
not establish new biological knowledge. The third is where genuine research
novelty can emerge. Keep their results separate instead of pooling them into
a claim that the model discovered new biology.

Start with E. coli-based cases and generated sequences, consistent with the
existing scope. Panels provide comparisons that a lone 3,000-base window may
not support. Any broader organism scope needs a deliberate later extension.

Example case ideas, not alleged discoveries or prompts revealing the answer:

- A blinded panel with an unusual relationship between motif spacing and
  candidate coding boundaries. The agent chooses the relationship and tests
  whether it persists in other panels.
- Related windows containing a structural regularity that survives sequence
  divergence. Evidence must distinguish the pattern from composition or sampling
  artifacts; a mechanistic interpretation remains a separate hypothesis.
- Real sequence panels where the model identifies an unanticipated recurring
  pattern or challenges a supplied measurement's consistency. Independent
  checks decide whether it is a valid observation and whether it is already known.
- Matched background panels that can tempt a convincing story. Correctly
  measured incidental patterns remain valid observations; the control is not
  proof that every interesting statement must be false.

Fresh random seeds alone are a weak novelty test. Hold out combinations of
rules, sequence regimes and source loci where practical; document exactly what
was withheld. Generated patterns can be novel to the evaluation without being
biologically plausible or unknown to science.

## Validate observations, then assess novelty

The [verification procedure](verification.md) maps claim types to checks and
provides a [review template](claim_review_template.md). It is proposed work;
the existing claim extractor does not perform this validation.

Separate three statuses:

1. **Verified observation:** reproducible evidence supports the stated,
   appropriately bounded claim about supplied data.
2. **Candidate discovery:** the observation supports a specific new hypothesis
   or relationship that merits independent confirmation.
3. **Confirmed research contribution:** evidence and a documented external
   novelty review support the claimed addition to biological knowledge.

For comparative claims, withhold independent sequences or samples during
exploration. After submission, freeze the pattern definition, thresholds,
predictions and analysis code before evaluating that held-out material. Use
separate loci or sample groups, not near-duplicate overlapping windows. Reusing
the discovery data after searching many hypotheses is not independent confirmation.

For a claim about a unique sequence, verification may instead require an
independent reconstruction, measurement or annotation review. Structural
evidence alone does not establish a biological function or causal mechanism.
Report proposed experimental follow-up as a proposal, not a completed validation.

Assess research novelty outside the agent environment, after freezing claims.
Use a documented literature/annotation snapshot, search date and expert review
for shortlisted findings. This does not give the agent live lookup. Model
confidence, unfamiliar wording, or a missing search hit cannot establish novelty.
If confirmation or the prior-art review is incomplete, label novelty unresolved.

## Score the claim the agent actually makes

Known references calibrate scoring; they are not the only acceptable findings.
Accept an unexpected claim when an independent check supports it. A claim that
differs from the planted or annotated target is not automatically wrong.

Use a fixed blinded extractor to identify claims and cited artifacts if needed.
Validate the evidence in code where possible, then use documented domain review
for biological interpretation and novelty. An LLM rubric can help route review,
but cannot certify biological truth or new scientific knowledge by itself.

Report a profile rather than a single novelty score:

| Measure | Evidence required |
|---|---|
| Validated finding yield | Assigned cases with at least one specific, nontrivial, independently supported finding |
| Claim outcomes | Submitted claims classified as verified, refuted or unresolved; report all three counts |
| Independent confirmation | Frozen claims/predictions tested on suitable withheld material, with scope and denominator stated |
| Robustness and controls | Completed checks of sensitivity, background expectations and competing explanations |
| Novelty status | Calibration rediscovery, prior knowledge, candidate contribution or unresolved prior art |
| Delivery and efficiency | Usable submission, failures, binding limits, tokens, time and measured/estimated cost |

Define nontriviality by case class before evaluation. A routine GC calculation
can support a discovery claim but should not earn novelty credit on its own.
For real open cases, report reviewer criteria and disagreements explicitly.
Null cases may earn abstention/calibration credit; they do not earn discovery
yield merely because the report is empty. An empty failed submission is not
an evidence-backed conclusion that there is no finding.

Ranked claim limits reduce rewards for dumping dozens of guesses. Do not force
three findings, or treat many suggestions as many discoveries. Freeze judgment
rules and blind model identities before reviewing their outputs.

## Relevant methods we can borrow

- The [Anthropic ART workflow note](anthropic_workflow.md) connects this plan
  to the motivating Yoon et al. study: candidate selection, skeptical review,
  follow-up tasks, direct DNA inspection and independent confirmation. Our
  standard-library environment is a restricted adaptation of its resources.
- [StatefulDiscovery](https://github.com/SUSTech-GenAI/StatefulDiscovery)
  explicitly converts existing datasets into open exploration by hiding
  task-specific questions and answers. It also externalizes evolving discovery
  state. Borrow that preprocessing and state-management idea; do not assume
  its full tool environment matches our sandbox or that adapted scores equal
  original benchmark scores.
- [TruthInsightBench](https://arxiv.org/html/2609.05079v2) evaluates agents'
  own claims on blind data along evidence auditability, robustness, controls,
  cross-dataset generalization, novelty and falsifiability. Its evaluator uses
  an LLM judge, so we should borrow the dimensions while independently checking
  artifacts and shortlisted claims. Its
  [repository](https://github.com/TruthInsight-stack/TruthInsightBench) distinguishes
  Apache-2.0 authored materials from third-party data with separate terms.
- [DiscoveryBench](https://arxiv.org/abs/2407.01725) supplies datasets and
  discovery goals for hypothesis search and verification. Its
  [public repository](https://github.com/allenai/discoverybench) is a potential
  source of data, but removing target-directed questions creates an adapted
  task with a new evaluation contract.
- [DiscoveryWorld](https://proceedings.neurips.cc/paper_files/paper/2024/file/13836f251823945316ae067350a5c366-Paper-Datasets_and_Benchmarks_Track.pdf)
  evaluates cycles of hypothesis formation, experimentation and explanation
  in simulated worlds. It is inspiration for a future controlled experiment
  interface; discoveries there concern simulated scenarios.

These method sources were read, not installed or run. Before importing any
tasks, check source-data terms, remove endpoint/answer leaks, and convert only
suitable small inputs into our explicitly allowed formats.

## Pilot before scaling

Start with **24 development cases**: six fresh hidden structures, six blinded
real cases, six open real-data cases and six matched controls. This is a
provisional allocation, not a frozen selection. Group related cases for splits
and uncertainty; 24 cases need not be 24 independent biological examples.

Both models get the same isolated tools, neutral discovery prompt, inputs and
submission contract. One presentation at one budget requires **48 runs**.
After budget calibration, testing B and 3B requires **96 runs**, excluding
calibration and repeats. Treat the structured prompt as part of the harness;
an optional neutral-prompt ablation is a separately labelled experiment.

Use the pilot to check whether models produce testable findings and whether
independent reviewers can validate them consistently. Refine task coverage,
input size, evidence requirements and scoring before choosing a held-out suite.
The current runner needs staging for sequence panels/metadata, a structured
claim submission, cumulative budgets and independent validation; these are
planned changes, not implemented features.

If the pilot works, expand toward **about 500 discovery cases**. Do not pad the
suite with repeated questions or relabel existing annotation recovery as new
science. A smaller collection of well-supported candidate discoveries is a
useful result even if it does not justify a 500-case release.
