**What the E. coli reports add beyond target detection**

The clearest difference in this pilot is that DeepSeek V4.1 Flash delivers
more consistent coding-region descriptions and several stronger protein-family
assignments. GLM-5.3-Flash sometimes finds additional neighbouring genes, but
its execution failures and missing or malformed reports reduce its usefulness.
Both models can turn genuine sequence observations into unsupported biological
stories. These are observations about this fixed experiment, not a general
ranking of the models.

This exploration uses all 144 saved records and transcripts, the existing Kimi
claims, and the cached genome annotation. It makes no new agent or judge calls
and does not alter the original target scores. The numerical analysis is
reproducible with `python src/explore_ecoli.py`; its outputs are
[exploration_metrics.json](exploration_metrics.json) and
[exploration_metrics.csv](exploration_metrics.csv). The original benchmark
results remain in [comparison.md](comparison.md).

**A comparison beyond the binary target score**

There are 63 corresponding runs where both models produced a nonempty report.
For those runs, an exploratory coordinate check compares gene-type claims with
annotated coding sequences. A match must cover at least 80% of both the claimed
interval and the annotation visible in the window. Short edge fragments with
less than 150 visible bases and pseudogenes are excluded. Each annotated coding
interval counts once per report, even when multiple nested claims match it.

| Measure | DeepSeek V4.1 Flash | GLM-5.3-Flash |
|---|---|---|
| Annotated coding intervals matched, on the same 63 reports | 136/193 (70.5%) | 97/193 (50.3%) |
| Matches with a looser 50% overlap requirement | 149/193 (77.2%) | 116/193 (60.1%) |
| 80% matches, also accepting explicitly described ORFs extracted as `other` | 136/193 | 99/193 |
| Reports containing a gene-type claim, on those pairs | 63/63 | 52/63 |
| Runs with Python failure diagnostics, all 72 runs | 31/72 | 66/72 |
| Python tool outputs containing failure diagnostics | 42/1,204 calls (3.5%) | 197/1,124 calls (17.5%) |
| Empty reports | 1/72 | 9/72 |
| Nonempty report with a separate delivery problem | 1 repetitive output | 1 tool-call payload |
| Median report length, nonempty reports | 616 words | 592 words |
| Median elapsed time, all runs | 242 seconds | 274 seconds |
| Agent output tokens, all runs | 2.57 million | 1.51 million |

The coordinate denominator repeats the same genes across conditions and
repetitions: the dataset has 38 eligible coding intervals in 12 distinct
windows, 17 of them clipped by a window boundary. It does not contain 193
independent genes. This check does not validate strand, exact start codons,
protein sequence, gene name, or function. An unmatched ORF is not automatically
false, and an overlapping gene claim is not a correct functional annotation.

DeepSeek matches more annotated intervals in 28 of the 63 paired reports, GLM
in 11, and they tie in 24. Removing both pairs with the identified nonempty
delivery problems gives 128/185 (69.2%) for DeepSeek and 94/185 (50.8%) for GLM;
the pattern remains. These are checks on the robustness of a post hoc metric,
not a significance test or a preregistered endpoint.

The following table uses the same nonempty pairs within each window. Names are
the reference annotation, not names successfully recovered by the models.

| Window | Eligible annotated genes | Paired reports | DeepSeek coordinate matches | GLM coordinate matches |
|---|---|---|---|---|
| region_001 | pdxY, tyrS, pdxH, mliC | 6 | 16/24 | 12/24 |
| region_002 | ygcE, queE | 6 | 11/12 | 5/12 |
| region_003 | ydcL, insQ, ydcO | 5 | 10/15 | 10/15 |
| region_004 | mgtA | 6 | 6/6 | 6/6 |
| region_005 | insD4, insC4, ygeQ | 6 | 9/18 | 7/18 |
| region_006 | lysS, prfB, recJ | 4 | 7/12 | 4/12 |
| region_007 | fadR, nhaB, dsbB | 6 | 13/18 | 9/18 |
| region_008 | glnH, glnP, glnQ, ybiO | 4 | 16/16 | 8/16 |
| region_009 | yigI, rarD, yigG, yigF, corA | 3 | 11/15 | 4/15 |
| region_010 | cas2, iap, cysD | 5 | 7/15 | 5/15 |
| region_011 | yhcF, insH10, yhcD | 6 | 11/18 | 14/18 |
| region_012 | fepE, fepC, fepG, fepD | 6 | 19/24 | 13/24 |

GLM's advantage in region_011 and the tie in region_003 matter: its reports
occasionally add useful neighbouring coding intervals that DeepSeek dismisses
or omits. DeepSeek's advantage is a pattern across the pilot, not superiority
in every report.

**Useful functional information that target scores miss**

The most convincing example is **mgtA in region_004**, a control window. Both
models locate its long coding region in all six runs. DeepSeek identifies a
P-type ATPase in all six reports, matching the source annotation's
Mg-importing P-type ATPase. It gives a concrete motif argument: `TGES`,
`DKTGTLT`, and `GDGIND`, in the expected order. For
[file repetition 0](deepseek-v4.1-flash/region_004__file__0.json), the reported
motif intervals at 794–805, 1274–1294, and 2075–2104 contain the corresponding
coding DNA in the supplied sequence.

GLM does not identify the ATPase family in any of those six reports. Its
[file repetition 0](glm-5.3-flash/region_004__file__0.json) instead suggests a
mostly soluble scaffold, and
[inline repetition 2](glm-5.3-flash/region_004__inline__2.json) confidently calls
an RND efflux transporter. The latter also reports a TGA stop at 2849–2851;
the supplied bases there are `CAA`, and the actual stop is `TAA` at 2852–2854.
Correctly locating the ORF therefore hides a substantial difference in the
reports' usefulness.

DeepSeek also gives useful **ABC transport-system interpretations** in
regions_008 and _012. For example,
[region_008 file repetition 2](deepseek-v4.1-flash/region_008__file__2.json)
identifies an ATP-binding cassette next to a membrane protein, consistent with
the annotated glutamine transporter subunits `glnQ` and `glnP`. GLM often
recognises membrane proteins too, and
[region_012 inline repetition 0](glm-5.3-flash/region_012__inline__0.json)
recognises the nucleotide-binding motif in the annotated `fepC` region. Its
assignment is broader—an NTPase—than DeepSeek's ABC ATPase interpretation.
Neither model establishes the transport substrate from these observations.

GLM supplies a different kind of useful evidence in
[region_001 inline repetition 1](glm-5.3-flash/region_001__inline__1.json):
external BLAST identifies PdxH, consistent with the annotated gene and
function. It then infers *Shigella flexneri* origin from the database hit,
although the supplied fragment comes from E. coli K-12. A correct protein match
does not establish a unique species of origin. This run shows both the value
of external homology and the risk of overinterpreting it; it cannot establish
sequence recognition from model training.

**Why both models still miss the harder targets**

The insertion-sequence failures are often failures of interpretation after
finding coding structure. Both
[DeepSeek](deepseek-v4.1-flash/region_003__file__0.json) and
[GLM](glm-5.3-flash/region_003__file__0.json) locate the main coding intervals in
the IS609 window, yet describe an ordinary two-gene segment and dismiss mobile
element origin. In the IS5 window,
[DeepSeek file repetition 0](deepseek-v4.1-flash/region_011__file__0.json)
explicitly lists 12-base inverted-repeat arms at 1129–1140 and 2312–2323 but
calls them chance-level. Those intervals are at the annotated element's ends,
and their supplied sequences are exact reverse complements. The report then
states that there are no terminal inverted repeats. This is a concrete case
of relevant evidence being found and then dismissed, rather than never searched
for. It does not imply every short inverted repeat is a mobile element.

For **prfB**, DeepSeek's gene-type claims overlap at least 80% of the annotated
CDS span in five of its six reports, but none recognises the programmed
frameshift. Some reports describe fragments or opposite-strand ORFs rather
than assembling the annotated feature. Finding coding potential and explaining
the translation mechanism are separate capabilities.

**The over-claiming lead is stronger at the level of function and explanation**

There are concrete examples for both models, even on reports with successful
coordinate matches:

- [DeepSeek region_006 inline repetition 1](deepseek-v4.1-flash/region_006__inline__1.json)
  assigns a reverse-transcriptase/polymerase interpretation from a short
  `YxxDD` motif and proposes a retron or diversity-generating retroelement.
  The corresponding source annotation is `prfB`, peptide chain release factor
  RF2. Its proposed mobile-element explanation is explicitly speculative;
  it is not a validated discovery.
- [DeepSeek region_006 file repetition 0](deepseek-v4.1-flash/region_006__file__0.json)
  treats long opposite-strand ORFs as evidence of dual coding and suggests
  an engineered sequence. The supplied source is a normal E. coli genome
  slice. In particular, probabilities for the two complementary readings
  cannot simply be multiplied as if they were independent sequences.
- [DeepSeek region_010 inline repetition 0](deepseek-v4.1-flash/region_010__inline__0.json)
  correctly finds the CRISPR array but suggests downstream candidate Cas
  proteins where the annotation is `iap` and `cysD`.
- [GLM region_011 file repetition 0](glm-5.3-flash/region_011__file__0.json)
  turns a list of nested in-frame starts and a GC-rich coding block into a
  horizontally acquired island story. It does not identify the annotated IS5
  transposase. Listing alternative starts is not evidence that each is an
  independently expressed nested gene; the specific island explanation is
  not established by this report.
- [GLM region_012 file repetition 1](glm-5.3-flash/region_012__file__1.json)
  reports no credible coding regions and builds its interpretation around
  compositional asymmetry, despite the four annotated coding intervals.
- [GLM region_002 inline repetition 0](glm-5.3-flash/region_002__inline__0.json)
  propagates a calculation error into a high-GC/Firmicutes interpretation:
  reported GC is 66.1%, while the supplied sequence is 43.633% GC.

These examples are a qualitative audit, not an estimated model error rate.
The existing judge extracts claims; it does not validate motif positions,
arithmetic, function, or causal explanations. More features, names, or confident
language therefore cannot serve as an accuracy score. Existing checks on
short-repeat control flags and reverse-strand coordinates are in
[audit_notes.md](audit_notes.md).

**Execution quality and output quality affect the comparison**

Both models usually perform composition, ORF, repeat, and motif scans. Keyword
tags identify attempted ORF-related code in 72 DeepSeek and 71 GLM runs, and
repeat-related code in 72 and 61 respectively. Shuffle/permutation code appears
in 18 DeepSeek and 8 GLM runs; the reports mention randomisation in 15/71 and
8/63 nonempty reports. These tags do not establish that a calculation executed
successfully or that its statistical interpretation was sound.

GLM has substantially more Python diagnostics. The most common categories are
59 NameErrors, 37 SyntaxErrors and 36 KeyErrors, compared with 7, 6 and 14 for
DeepSeek. Undefined imports, functions and variables occur despite the tool
description stating that each call starts a fresh interpreter. Tool outputs
were saved without subprocess exit codes, so the diagnostic tally is a textual
check, not complete execution telemetry.

DeepSeek's advantage in report delivery also needs qualification.
[region_008 file repetition 0](deepseek-v4.1-flash/region_008__file__0.json)
hits the output limit after repeatedly emitting the same paragraphs; one
paragraph occurs 20 times. Its gene coordinates can still score, but it is not
a usable finished report. Conversely,
[GLM region_008 file repetition 1](glm-5.3-flash/region_008__file__1.json)
ends with a literal `<tool_call>` payload containing Python code, not a
biological report. The original nonempty/empty distinction misses both cases.

DeepSeek emits about 70% more agent output tokens despite similar median report
length. Token accounting also includes intermediate output, so this is not
evidence of 70% more useful content or of a particular reasoning process. GLM
is lighter in tokens, but the median saved run takes longer here. Exact billed
cost is not recoverable from these files, especially because judge usage was
not saved.

The harness allowed external networking and modifications to the shared Python
environment. GLM retrieved BLAST results in one run and installed Biopython and
NumPy in another. These modifications may also affect subsequent concurrent
runs, so absence of installation code in a DeepSeek transcript does not prove
dependency isolation. This pilot cannot cleanly establish model memorisation
or strictly offline performance. The 20-turn cap forces reports in 42/72
DeepSeek and 41/72 GLM runs; it cannot explain the model difference by itself,
and the experiment does not measure whether a higher cap would help.

**What this suggests testing next**

The strongest next analysis target is factual and functional calibration:
whether a model distinguishes an observed motif or ORF from a supported family
assignment and from a speculative origin story. A follow-up can score those
layers separately, validate arithmetic and coordinate conversions, and retain
delivery failures explicitly. It should first enforce network and dependency
isolation, then vary the turn cap on a separate fixed batch. That would test
whether GLM's weakness here is mainly execution overhead and whether either
model can improve on mobile-element and frameshift interpretation without
simply adding more hypotheses.

Validation: all 144 exploratory CSV rows are retained; paired denominators are
identical; coordinate matching is checked for reverse-complement windows,
clipped genes, broad overlapping claims and missing coordinates. The offline
suite passes 12 checks. Functional examples above were reviewed against the
cached sequence or annotation; a complete annotation of all biological claims
remains outside this exploratory audit.
