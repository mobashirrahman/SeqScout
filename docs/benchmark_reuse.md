# Public benchmarks we can reuse

Research checked on 2026-10-06 against papers, author repositories, dataset
cards and unauthenticated downloads. This is a selection proposal, not a new
model evaluation. No paid inference was run and no benchmark has been integrated
into the harness yet.

**Updated direction:** the user prioritizes open-ended discovery. The main
proposal is now [`discovery_benchmark.md`](discovery_benchmark.md), where models
choose and test their own findings. SeqQA's 600 questions remain an optional
competency baseline. The question-answering proposals below are retained as
research options, rather than the main rollout.

## Closest matches

| Benchmark | Released material | Fit for our offline worker | Reuse status |
|---|---|---|---|
| [LAB-Bench SeqQA](https://huggingface.co/datasets/futurehouse/lab-bench) | 600 multiple-choice questions; 15 subtasks | Strong fit for sequence calculation and manipulation; some questions also need background knowledge | Download verified without authentication; CC BY-SA 4.0 |
| [LABBench2 SeqQA2](https://github.com/EdisonScientific/labbench2) | 400 sequence tasks with open answers; file, inject and retrieve modes | Its file/inject modes closely match our presentation experiment | [Dataset](https://huggingface.co/datasets/EdisonScientific/labbench2) is gated; unauthenticated file download returned 401; CC BY-SA 4.0 |
| [GenomeQA, Long et al.](https://github.com/ai4nucleome/GenomeQA) | 5,200 binary/multiple-choice records across six DNA inference families | Strong fit for general LLMs receiving raw DNA; predictive labels differ from exact sequence calculations | All 12 JSONL files fetched and counted; no repository licence found |

SeqQA tests ORFs, translation, GC content, restriction fragments and primer
selection. Its question/answer data are small enough to prepare outside the
worker and expose as plain text or JSON. The published question-and-choice
format can be scored in code without an LLM judge. The original public release
is a usable reference; enabling our Python tools creates a particular evaluation
protocol that must be reported. The original paper's scores combine public and
private questions and use models without tools; our public-only Python-assisted
run would not reproduce those scores directly.
[Dataset](https://huggingface.co/datasets/futurehouse/lab-bench),
[original evaluation protocol](https://arxiv.org/html/2407.10362v1#A4).

SeqQA2 replaces multiple-choice questions with open answers and provides
necessary context inline or in local files as an alternative to retrieval. We
would stage those files before execution and omit retrieve mode. The authors'
runner offers web tools, so importing the data into our controlled runner is
preferable to using its default tool setup. [Author announcement](https://edisonscientific.com/news/labbench2-an-improved-benchmark),
[evaluation harness](https://github.com/EdisonScientific/labbench2).

A September 29, 2026 independent audit reports resource-budget effects,
underspecified prompts and validator problems in SeqQA2. This is the audit
authors' finding, not a result we reproduced; their analysis also uses fallible
LLM transcript scanners. It is a reason to verify a small sample before treating
every failed answer as a model limitation. [Original audit](https://generality.org/blog/posts/labbench2-seqqa2-saturated/).

GenomeQA covers promoter/enhancer classification, splice sites, broad taxonomy,
histone marks, TF binding and TF motifs, using sequences of 6–1,000 bp. The
accepted ACL paper links to the released data; the earlier arXiv version did
not provide that link. Histone and regulatory labels are prediction targets
derived from biological data, not facts uniquely determined by a short string.
Keep these scores separate from arithmetic and exact coordinate tasks.
[ACL paper](https://aclanthology.org/2026.acl-long.1655.pdf).

GenomeQA's source records include `answer` and metadata fields such as
`true_label`, `truth` and `target`. Passing complete rows would leak answers.
Only approved question/input/option fields belong in the worker. IDs also repeat
across files; use the filename plus ID. No licence file or GitHub-recognised
licence was present at the checked revision, so do not assume redistribution
permission from public visibility. [Repository](https://github.com/ai4nucleome/GenomeQA),
[GitHub's licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

## What the released SeqQA data actually contain

I fetched all 600 records through the public dataset API and checked the pinned
Parquet file's availability. Every subtask has 40 records. A few details matter
for interpreting the experiment:

- **It mixes supplied-sequence work with background knowledge.** Three
  categories name an E. coli gene and pUC19 without supplying the gene/vector
  sequences in the question. Another supplies primers while naming the vector.
  Running these offline tests knowledge and inference together. Adding frozen
  references would make a useful adapted task, but changes the original protocol.
- **Question text alone is not an input identifier.** There are 558 distinct
  question texts, but all 600 question-plus-choice sets are distinct. In one
  category the candidate RNA sequences are themselves inputs. Repeated wording
  with different choices is therefore not evidence of a broken answer key.
- **Choice counts vary.** There are 560 records with four candidates and 40 with
  five. Six records contain repeated candidate strings. Audit those cases and
  define how equivalent answers are scored before shuffling options. In each
  of those six, the correct answer string appears twice; accepting only one
  of the two corresponding labels would incorrectly reject an equivalent answer.
- **About 360 records are candidates for a computation-focused subset.** These
  span the three direct ORF categories, three template/amplicon categories, GC
  content and two restriction-fragment categories. This is a preliminary
  inclusion screen, not validation of every reference answer. Restriction
  tasks still require enzyme recognition rules; record whether those are supplied
  as a frozen reference table or recalled by the model.

The release is labelled `train` on Hugging Face; that storage label does not
make it a development set for our evaluation. Preserve source IDs, canary text,
revision and licence information in the private source cache. Keep answer keys
and audit metadata outside agent-visible files. [Public dataset](https://huggingface.co/datasets/futurehouse/lab-bench).

## Other useful resources

| Resource | What it supplies | Why it is a later extension |
|---|---|---|
| [BioCoder](https://github.com/gersteinlab/BioCoder) | Bioinformatics code generation; reported 1,026 Python functions, 1,243 Java methods and 253 Rosalind problems | A Python/Rosalind subset could test algorithms with hidden cases. Many tasks have dependencies; the original evaluator uses Docker/AWS. No root licence was identified, and source-code terms need checking. |
| [BixBench](https://huggingface.co/datasets/futurehouse/BixBench) | Current v1.5: 205 questions across 59 biological analysis capsules; Apache-2.0 dataset card | Real multistep data analysis, including tasks specifying R/DESeq2 and other packages. Its intended workflow exceeds our standard-library policy. Useful for a separate offline environment with fixed scientific tools. |
| [GeneBench-Pro public package](https://huggingface.co/datasets/openai/genebench-pro-public-package) | Ten MIT-licensed case studies with staged data, schemas, tolerances and reference answers | The full benchmark has 129 problems; only ten are in this public package. These test statistical judgment rather than short DNA analysis. The package explicitly targets reproducibility, not a hidden-answer leaderboard. |
| [BioAgent Bench](https://github.com/bioagent-bench/bioagent-bench) | End-to-end bioinformatics tasks with downloadable inputs, references and expected results | Often requires alignment/variant calling/R workflows. Repository contents are CC BY 4.0; third-party data retain their own terms. The authors caution that some expected outputs are pipeline-specific rather than definitive truth. |
| [BEND](https://github.com/frederikkemarin/BEND) | Human genomic tasks, including gene finding, regulatory annotation and variant effects | Designed around DNA-model embeddings and downstream training, rather than conversational agents. Exporting selected sequences/labels would create an adapted evaluation. BSD-3-Clause code; check original dataset terms. |
| [Genomic Benchmarks](https://github.com/ML-Bioinfo-CEITEC/genomic_benchmarks) | Labelled sequence classification datasets with train/test splits | Useful inputs for a later prediction track. Training-based published scores are not directly comparable to our general LLMs with Python. Apache-2.0 repository; preserve underlying data provenance. |
| [DART-Eval](https://github.com/kundajelab/DART-Eval) | Regulatory DNA tasks and processed HDF5 data on Synapse | Another specialised DNA-model benchmark, with zero-shot, probe and fine-tuning protocols. Needs host-side conversion and source/access-term checks before reuse. |
| [BioPAWS-2](https://huggingface.co/datasets/dnagpt/biopaws-2) | A broad chat-format training/evaluation mixture, including reused biological datasets | Potentially convenient, but not a new independent test set. Check its per-record source, split and licence; avoid double-counting upstream benchmarks. The dataset viewer currently reports a schema-conversion error. |

There is also a different [ClawBio project called GenomeQA](https://genomeqa.clawbio.ai/).
Its page describes v0.1 as in development and a proposed 100-question set.
It is not the released 5,200-record ACL benchmark above.

## Existing results for our exact models

Checked on 2026-10-06 for **DeepSeek V4.1 Flash** and **GLM-5.3-Flash**.
The user wrote "T6, P411"; the working interpretation is DeepSeek V4.1 from
the preceding conversation. Literal-name searches did not identify a relevant
additional model. Searches included exact names and spelling variants paired
with SeqQA, SeqQA2, LAB-Bench, LABBench2, GenomeQA and BixBench.

**No public result for either exact model version was found on these four
biology benchmarks in the checked sources.** This is a search finding, not
proof that nobody has run them or that our evaluation would be the first.

| Benchmark | Results actually located | Exact-model status |
|---|---|---|
| [LAB-Bench SeqQA](https://arxiv.org/html/2407.10362v1) | Original paper tests GPT-4o, GPT-4-Turbo, Claude 3/3.5, Gemini 1.5 Pro and Llama 3 70B | Neither exact model appears in the original evaluation; no matching later public run found |
| [SeqQA2 official leaderboard](https://advances.edisonscientific.com/benchmarks/labbench2/seqqa2/) | 33 entries under seven model labels, covering GPT-5.2, Gemini 3 Pro and Claude Opus 4.5/4.6 variants and retry labels | No DeepSeek or GLM entry; published report filenames also contain neither |
| [GenomeQA](https://aclanthology.org/2026.acl-long.1655.pdf) | Claude Sonnet 4.5, GPT-5.1, Gemini 3 Pro, Grok 4.1, Llama 4 and Qwen3-Max, plus task-specific baselines | Neither exact model appears in the paper; no matching later public run found |
| [BixBench](https://github.com/Future-House/BixBench) | Original paper and released baseline files evaluate GPT-4o and Claude 3.5 Sonnet | No matching exact-model run found; this is not an inventory of every subsequent third-party evaluation |

The September SeqQA2 audit's listed models are GPT-5 Mini, Gemini 3.7 Flash and
GPT-5.6 Luna/Terra/Sol, rather than our pair.
[Audit and model list](https://generality.org/blog/posts/labbench2-seqqa2-saturated/).
Aggregate search pages mention our models beside biology audit titles because
those pages list multiple separate articles; that is not evidence of a biology
evaluation of the models.

There **is** a direct comparison of our exact two models on another domain:
Generality Labs' September 28 study evaluates them on ten ExploitBench tasks
across seven harness configurations. The large-budget configurations use
250 million tokens per task; the original configuration instead has a 300-turn
cap. Results differ substantially by harness, and the authors acknowledge the
small sample. These are cybersecurity results, not DNA benchmark scores.
They support controlling harness and budgets in our experiment, without
establishing which model is better at biology.
[Original study](https://generality.org/blog/posts/exploitbench-harnesses/).

Our closer reading, current-runner comparison and proposed budget/compaction
experiments are in [`harness_study.md`](harness_study.md).

The useful portfolio claim remains a reproducible comparison under documented
offline access controls, with transcripts and error analysis. Do not claim
"first-ever" evaluation based on missing search results. Cross-study scores
also need matching dataset revisions, subsets, tools, budgets and graders.

## Optional question-answering route

This earlier proposal is retained for a competency baseline. The main discovery
rollout now starts with 24 cases in
[`discovery_benchmark.md`](discovery_benchmark.md).

Start with **50 questions from the supplied-sequence SeqQA categories**, reviewed
before scoring. Validate ORF conventions, strands, stop-codon handling, restriction
rules, rounding and acceptable equivalent outputs. Run both agent models with
the same presentation, tool policy and budget. This establishes cost and whether
the tasks discriminate between our models.

Then choose one of two routes:

1. **Public reference run:** use the released 600 SeqQA questions with their
   choices. Report the mixed knowledge/calculation scope and scores by subtask.
   Keep the wording unchanged for this track. There is no scientific need to
   force its natural size down to 500.
2. **A sequence-only set of about 500:** provisionally use 300 audited SeqQA
   calculation questions, 100 newly generated cases with exact answers, and
   100 independently checked E. coli feature/control questions. The extra cases
   can target strand changes, clipped ORFs, degenerate repeats, insertion
   sequences and claims that the available evidence cannot support. Treat this
   as our adapted suite and publish the selection rules and attribution.

These allocations are proposals, not frozen selections. Preserve a development
set and group overlapping sequences/loci before choosing held-out questions.
Do not pad the total with repeated questions and present them as independent
biological examples. Human and yeast examples remain later extensions; adopting
GenomeQA's regulatory tasks would deliberately broaden that scope.
Public questions may have appeared in model training. Offline execution blocks
live lookup, but it cannot establish that a model has never seen an example.
Fresh generated cases provide a complementary check, rather than proof that
every biological pattern is unfamiliar.

Keep the current neutral discovery task as a separate track. Multiple-choice
accuracy does not measure whether an agent volunteers unsupported biological
stories in a free report. Combining the two scores would conceal that difference.

For the direct-question track, grade final choices, numbers, strings and
coordinates in code. Report accuracy over all assigned questions, including
empty/failed submissions, alongside delivery and execution failures. Use an LLM
claim extractor only for free reports and validate those claims independently.

Two models on 500 questions require 1,000 runs for one condition. Testing both
inline and file presentation makes 2,000, before repetitions or a Python-tool
ablation. Start with one fixed presentation; add those factors separately after
the validation batch.

## What importing would involve

The runner's isolation is ready, but its current task is a neutral DNA report.
A question benchmark needs a small adapter rather than just pointing `--loci`
at a downloaded dataset:

1. Pin the upstream revision; save the licence, source IDs and checksums in a
   host-side cache. Downloads and format conversion happen before the worker starts.
2. Separate the public question/inputs from private keys, label-bearing metadata,
   reference solutions and grader files. Stage only permitted inputs.
3. Freeze option order deterministically, retain equivalent-answer rules, and
   require a clear final answer format. Avoid judging correctness from arbitrary
   occurrences of an answer letter in the explanation.
4. For an inline/file ablation, move only the same sequence data between the
   prompt and supplied files; keep task wording, choices and budgets equivalent.
   Include sequences contained in answer choices when relevant.
5. Run deterministic scoring in the parent process; keep transcripts, scripts,
   execution records and source IDs. Label changes to upstream wording, inputs
   or scoring as adaptations.

Our useful contribution would be a reproducible comparison of DeepSeek and GLM
under explicit access controls, plus an audit of answer reliability and
unsupported claims. Reusing an established question set strengthens that work;
it does not require claiming the question set as our invention.

The checked revisions and compact audit counts are in
[`benchmark_sources.json`](benchmark_sources.json).
