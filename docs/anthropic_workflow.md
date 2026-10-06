# Adapting Anthropic's ART discovery workflow

Research note, 2026-10-06. This connects the proposed
[discovery benchmark](discovery_benchmark.md) to the study that motivated the
project. It records a plan; no additional agents, data acquisition, model calls
or scientific-tool permissions have been added.

Primary sources:

- Anthropic's [23 September 2026 announcement](https://www.anthropic.com/news/claude-discovers-novel-enzyme-system).
- Yoon et al., [Autonomous AI agents discover reverse transcriptases with tandem repeat arrays](https://www-cdn.anthropic.com/22573675ada52a8ca8a97a1a4b4326b2f208a071.pdf),
  especially pp. 3–10, Fig. 4, and Methods pp. 28–31 and 38–39. The PDF was
  retrieved and its workflow, validation and benchmark methods read directly.
  This is a preprint; describe its conclusions as the authors' reported findings.

## What the study establishes

The authors describe array-associated reverse transcriptases (ART): an RT
family, upstream non-coding repeat arrays and associated partner genes. The
underlying RT had appeared in earlier work. Their follow-up combines family
analysis, published RNA-sequencing data and new expression experiments showing
short array-derived RNAs. The Discussion explicitly leaves RT activity, RNA
substrate use, partner interaction and biological function unestablished.
Programmable gene editing is therefore not a demonstrated outcome.

The discovery path matters: an initially nominated partner association was
rejected, but a follow-up investigated the RT lineage and nearby DNA. A worker
noticed repeats, measured them and examined possible prior descriptions. The
harness used worker, supervisor, curator and editor sessions, recorded decisions,
and permitted follow-up tasks. Its campaign used 949 sessions across 119 tasks.

The authors report no array rediscovery in ten further campaigns. Their audit
searched identifiers from the original campaign and acknowledges that other
contigs could escape that search. In a separate fixed-input study, providing DNA
in context aided recognition; file runs sometimes failed to read enough DNA.
These results motivate testing reliability and data exposure separately.

## What our current experiment measures

Our inline-versus-file sequence tests most closely resemble the paper's
fixed-input analysis, where a candidate is already supplied. They measure parts
of recognizing and characterizing a feature. They do not yet measure selecting
a candidate from a collection, pursuing an unexpected lead, or completing
experimental validation. The E. coli results remain annotation-recovery results.

The paper's research environment included web/literature access, database
connectors, scientific packages, specialist sequence tools and remote structure
jobs. Its offline fixed-input level also included specialist tools. Our
standard-library worker is a more restricted experimental condition. A sandbox
does not by itself mean internet-free or tool-free; those are explicit choices
in our adaptation. We can study the same reasoning stages while documenting
the different resources and scope.

## Workflow to borrow

| Element | Proposed implementation under our restrictions |
|---|---|
| Broad research brief | Give a family or neighborhood investigation objective without naming the hidden feature or preferred conclusion. |
| Comparison across loci | Stage a small local panel of related loci, gene coordinates and necessary metadata. Keep source conclusions and evaluator data hidden. |
| Direct inspection of primary data | Log which sequence intervals actually enter model context and whether recognition precedes or follows code-based detection. |
| Plan, execution and skeptical review | Have a worker produce code and claims; a separate reviewer session inspects actual artifacts and challenges unsupported interpretations. |
| Follow-ups after rejection | Allow a bounded task queue with reasons for opening, rejecting or completing each task. Preserve incidental observations that can justify another investigation. |
| Shared research record | Save hypotheses, tests, results, revisions and rejected explanations in a run-local notebook. Later sessions can read it; other model runs cannot. |
| Candidate funnel | Rank final candidates with explicit evidence and objections; retain rejected candidates and reasons. Allow a campaign to yield none. |
| Confirmation | Freeze the final package, then apply independent checks and suitable withheld-data tests outside the agent's exploratory loop. |

The reviewer should see the same allowed research inputs and completed worker
artifacts, not the private calibration answer or confirmation results. Its
feedback is part of the discovery workflow, not hidden-grader feedback.
Reviewers can request revisions within the campaign before the final freeze.
They cannot certify truth simply by approving a report. The
[verification procedure](verification.md) remains the authority for evidence
checks and bounded verdicts.

For an offline analogue of literature checking, we can optionally stage a
documented, dated collection of reference material. Give both models the same
collection and identify this as added context. Final external prior-art review
still happens after submission. Reference documents must not leak the hidden
case conclusion. We have not assembled or enabled such a collection.

## A useful development experiment

Use the proposed 24-case development set to check whether small local campaigns
produce auditable findings. Give each case enough comparative context to make
its claims testable. Preserve generated and blinded-known cases for calibration,
and open real-data cases for unexpected findings. E. coli-based data remain the
starting scope; using the study's phage material is not required to test these
workflow components.

Compare a single investigator with a worker-plus-reviewer workflow as a
separately labelled harness experiment. Both conditions receive the same total
token allowance, inputs, permitted tools and final submission rules. Count all
reviewer, notebook and follow-up overhead. Start with one reviewer pass and a
small fixed follow-up allowance rather than copying the original campaign's
scale. This is an optional new factor; it does not silently enlarge the existing
two-budget proposal or authorize paid runs.

Report intermediate behavior as well as final outcomes: relevant DNA exposure,
correct structural observations, justified hypothesis revisions, candidates
surviving independent validation, unsupported functional/novelty claims, and
variation across repeats. An association between reading more DNA and success
is observational. To test a causal effect, assign presentation conditions with
matched inputs and budgets. The paper's five information levels also change
tools and input volume, so their score differences are not a pure tooling effect.

Distinguish capability when a candidate is supplied from reliability when the
agent must find and select it. A model can succeed at characterization while
rarely reaching that candidate during exploration. Avoid counting repeated
recognition of one locus as multiple independent discoveries.

Token accounting needs particular care: the paper's 215.6-million campaign
figure sums uncached input, cache writes and output, excluding cache reads
(Methods p. 30). Our provider records use other conventions. Preserve raw token
categories, normalize them explicitly, and compare measured costs separately;
that headline is not a directly comparable total or a budget recommendation.

The paper's internal-signal analysis requires checkpoint-level access that our
hosted APIs do not expose. We can reproduce behavioral tests of sequence exposure
and pattern recognition; we cannot claim to reproduce its internal mechanism.

## Intended contribution

The research question becomes: **under controlled access and a fixed budget,
can inexpensive models notice an unexpected sequence feature, pursue it,
challenge their explanation, and deliver an independently supported candidate?**

This is a study of discovery behavior and harness design. Confirming a new
enzyme's function would require additional scientific evidence. Expansion
toward 500 cases should depend on whether this smaller workflow and its
independent validation work consistently.
