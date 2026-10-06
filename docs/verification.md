# Verifying an open-ended finding

Proposed procedure, recorded on 2026-10-06. This describes the validation layer
for the [discovery benchmark](discovery_benchmark.md); it is not an implemented
grader and does not change the historical results.

Verify each claim at the level its evidence supports. A correct observation,
a biological explanation and a claim of novelty can receive different verdicts.
The agent stays offline. A separate evaluator can inspect private references,
use scientific tools and review public literature after submissions are frozen.
These resources and their results are not returned to the agent during a run.

## Match the check to the claim

| Submitted claim | Independent check | What remains unestablished |
|---|---|---|
| A specified motif occurs at specified positions | Recompute matches from the original sequence with a trusted implementation; check strand, mismatches and coordinates | Biological function or relevance |
| A region contains a long open reading frame | Independently translate the stated frame using the appropriate genetic code; compare start/stop positions | Expression, protein function or whether the ORF is a real gene |
| A pattern is enriched or associated with a condition | Test a frozen definition on withheld samples with appropriate backgrounds, effect sizes, uncertainty and multiple-test handling | A causal mechanism |
| A sequence feature has a particular biological role | Review the supporting annotation's evidence and relevant independent functional measurements | A new function supported only by sequence resemblance |
| The finding adds new biological knowledge | Document prior-art searches and domain review after validating the observation | Universal absence from the literature or certainty based on a missing search hit |

For example, a hypothetical report saying “this repeat occurs eight times and
is a new regulatory mechanism” contains at least three claims: the occurrence
count, the regulatory role and the novelty. The count may be verified while
the role and novelty remain unresolved. This example is not a result of our runs.

## Review procedure

1. **Freeze an explicit submission.** Preserve the report, transcript, input
   checksums, analysis code and outputs. Extract up to three ranked findings
   without strengthening their wording. Split compound statements into atomic
   claims, preserving confidence, qualifications and dependencies. Require
   sequence identifiers, units and a coordinate convention. A reviewer must
   resolve ambiguous statements before choosing a test, without feedback that
   lets the agent rewrite its original submission after seeing validation data.

2. **Check reproducibility and correctness separately.** Rerun submitted code
   in the isolated worker on the permitted inputs. Confirm that the cited
   artifacts exist and reproduce the reported calculation. Then verify the
   central measurement through independently written code or an appropriately
   checked reference. Reproducing the same script can reproduce the same bug.
   Agreement between two language models does not replace this evidence.

3. **Check alternative explanations.** Use controls suited to the claim:
   sequence length and composition for motif enrichment, relevant local
   background for spacing, and source/sample grouping for comparisons. A
   shuffled sequence is useful only when its preserved properties match the
   proposed null explanation. Related or overlapping windows must not be
   counted as independent biological observations. Record completed checks,
   including failures; suggested checks earn no completed-validation credit.

4. **Confirm general claims on withheld material.** Reserve suitable data before
   exploration. Freeze the motif definition, thresholds, predicted direction,
   exclusions, test and analysis-code hash before opening that material. For
   genome panels, split by locus or appropriate biological group rather than
   overlapping windows. Record effect sizes and uncertainty. Specify the family
   of confirmatory tests and its multiple-test procedure before evaluation;
   submitting only the best exploratory result does not remove selection bias.
   Report every planned confirmation result. Any revision after seeing the
   holdout becomes a new exploratory hypothesis requiring fresh confirmation.

5. **Review interpretation and novelty.** For biological roles, record whether
   support is experimental, computational or merely an author statement, and
   whether it concerns the same gene, organism and condition. A proposed new
   mechanism may need independent functional data or a bench experiment.
   Search relevant annotations and literature for the exact observation and
   close equivalents; save search terms, dates, versions and prior-art links.
   Have a domain reviewer assess shortlisted contributions with model identity
   hidden. Use a second reviewer for consequential or disputed judgments and
   retain disagreements. Describe incomplete searches as incomplete.

The separation of exploration and confirmation follows the
[Center for Open Science guidance](https://www.cos.io/initiatives/prereg),
including its discussion of withheld data and selective reporting. Here the
proposed minimum is a timestamped, frozen local analysis manifest; no public
registration has been performed. This principle applies to statistical
generalization after an adaptive search. An exact statement about the supplied
sequence can be checked directly on that same sequence.

The [Gene Ontology evidence guide](https://geneontology.org/docs/guide-go-evidence-codes/)
distinguishes experimental support from computational inference and other
annotation evidence. We should retain those distinctions when reviewing a
functional interpretation rather than treating every database entry as an
experiment. The review dimensions in
[TruthInsightBench](https://arxiv.org/html/2609.05079v2) also motivate tracking
auditability, controls, robustness and falsifiability; those dimensions do not
make an LLM judgment an independent biological verification.

## Record bounded verdicts

- **Verified:** the specified check supports the claim within a stated scope.
  Say whether this establishes an exact sequence fact, a statistical relationship
  or a functional conclusion, and preserve its uncertainty.
- **Refuted:** a valid check supplies evidence contradicting the specific claim,
  such as incorrect counts or coordinates. Explain the contradiction.
- **Unresolved:** evidence is insufficient, the claim is ambiguous, or the
  necessary confirmation cannot be performed. A nonsignificant result alone
  does not prove that a relationship is absent.

Record novelty separately: **already known**, **candidate contribution after
documented review**, or **unresolved**. Rediscovering an annotated feature can
be a correct observation without being a new contribution. An absent annotation
does not establish novelty or falsity. Unexpected claims can be accepted even
if they differ from a private calibration target.

Each verdict needs a reason and links to its evidence. Use the
[claim review template](claim_review_template.md). Keep all submitted claims in
the denominator, including unresolved claims and duplicate discoveries across
models. Report duplicate scientific findings separately from model-level
successful submissions. Preserve missing reports as delivery failures rather
than treating them as evidence-backed abstention.

## What to build first

For the proposed 24-case development pilot, independently check measurable
claims and review every proposed new interpretation. Calibrate the checkers on
hidden generated structures, independently curated known cases and appropriate
controls. A control lacking the selected target may still contain other valid
observations. Audit a sample of rejected claims as well as accepted ones.
Freeze the review contract only after checking reviewer consistency; any larger
comparison needs a separate held-out suite.

The current [judge](../src/judge.py) extracts features and named identities from
reports. The current [analysis](../src/analyze.py) compares selected feature types
and locations with private targets; its overlap check is a localization proxy.
Neither verifies all report statements, novel biological functions or prior
art. Building independent claim checkers and confirmation-data handling is
still planned work. The historical pilot remains an annotation-recovery study.
