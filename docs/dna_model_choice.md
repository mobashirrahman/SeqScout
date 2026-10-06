# Choosing a DNA model for the supervisor tool

Literature and hardware analysis for the open question in
[`future_tests.md`](future_tests.md) plan 2b: *which DNA model, it must cover
bacterial sequence and fit an 8 GB GPU*. Written 2026-10-06. No model has been
downloaded or run; everything below is from published specifications and
benchmarks plus arithmetic on this machine's limits.

## What the tool has to do

Plan 2b gives the supervisor three narrow calls on 3,000-base *E. coli* K-12
windows:

1. a surprise profile for a coordinate range against a shuffled baseline,
2. a comparison of the original region with an edited version,
3. similarity between two regions.

Calls 1 and 2 need a per-position likelihood; call 3 needs embeddings. The
targets the models missed are `prfB` (a programmed frameshift, a frame change
over roughly 20 bases) and IS5 (terminal inverted repeats plus a transposase
ORF). So the useful resolution is single-nucleotide for `prfB` and
hundreds of bases for IS5, on bacterial sequence, within one 3 kb window.

## The hardware is the binding constraint

| | This machine |
|---|---|
| GPU | GeForce RTX 2060 SUPER, 8 GB |
| Architecture | Turing, compute capability 7.5 |
| Precision | FP32, FP16, INT8 — **no BF16, no FP8** |
| Kernels | FlashAttention-2 and most fused SSM kernels target compute capability 8.0+ |
| Host | 31 GB RAM, 16 cores, 1.2 TB free on `/scratch` |
| Installed | NumPy only; no PyTorch, no CUDA toolkit in `.venv` |

Turing's missing BF16 and FP8 paths matter more than the 8 GB. Weight memory
alone is `parameters × 2` bytes in FP16, so a 500M model is about 1 GB and the
8 GB limit rules out far less than the precision support does.

## Evo 2 does not fit, for two independent reasons

Evo 2 is the obvious candidate — single-nucleotide resolution, prokaryotic
training data, autoregressive likelihoods — and it is unusable here.

- **Memory.** The 7B checkpoint needs about 14 GB in BF16 before KV cache and
  activations. NVIDIA's own support matrix lists H100, H200, RTX 6000 Ada and
  L40S for 7B; the February 2026 20B release is described as fitting *a single
  H100*. None of this is an 8 GB consumer card.
- **Precision.** Evo 2 requires FP8 support, "older GPUs not currently
  supported". The 1B checkpoint is the worse case rather than the escape hatch:
  it is documented as sensitive to FP8 state in training *and* inference
  because it was trained that way, while the 7B checkpoint is robust to FP8
  being off. A 1B model is only ~2 GB of weights, so it is the precision
  requirement and the StripedHyena-2 kernels, not the capacity, that exclude it.

Evo 1 (7B, 131k context) is excluded on the same memory grounds and depends on
FlashAttention. GenomeOcean-4B is ~8.5 GB of FP16 weights, over budget before
any activations; the published FP8 variant is of no use on Turing. Int4
quantisation would fit numerically but distorts the exact quantity — the
likelihood — the tool is supposed to measure, so it is not a sound workaround
for calls 1 and 2.

Treat "we could not use Evo 2" as a stated scope limit of plan 2b, not a gap to
apologise for; see the next section for why the literature supports that.

## What the literature says about using a smaller model instead

- **Scale buys little here.** GENEB probes 40 genomic foundation models over
  100 tasks under one protocol and reports that "scale provides only modest and
  inconsistent gains, and architectural and pretraining alignment frequently
  outweigh parameter count", with rankings that "vary sharply across task
  categories". Aggregate leaderboards are unstable, so a 10–500M model
  pretrained on prokaryotic genomes is a defensible choice rather than a
  consolation prize.
- **Frozen features are task-dependent.** A unified frozen-probing analysis of
  DNABERT-2, Nucleotide Transformer, HyenaDNA, GENERATOR-v2 and Omni-DNA finds
  frozen probes recovering 95–100% of fine-tuned performance on promoter tasks
  but only 60–88% on splice sites, concluding that local biological signal is
  "partially present in frozen representations, but is not always accessible
  through final pooled embeddings". For call 3 this argues for per-position or
  layer-wise comparison rather than one pooled embedding per region.
- **Do not read mechanism into a likelihood.** The 2026 analysis of Evo 2
  generation reports domain-agnostic generative behaviour, collapsed repeat
  structure (direct repeats depleted ~10-fold) and distorted regulatory
  architecture; a companion mechanistic-invariance study reports that genomic
  language models fail to learn positional regulatory logic. Neither paper
  evaluates per-position surprisal as an evaluation metric, so the surprise
  profile in call 1 is an unvalidated readout even for the largest models.
- **Nothing published covers our two targets.** The closest bacterial work
  (GeneLM, a fine-tuned DNABERT) reaches 89.7% on verified translation
  initiation sites against Prodigal's 37.3%, and 96.7% versus 44.0% on
  *E. coli* — but it classifies annotated genes and explicitly does not address
  frameshifts, mobile elements or unannotated features. Zero-shot prokaryotic
  results for Evo are reported for gene essentiality and mutation effect, not
  for locating an insertion sequence or a frameshift. This supports the note
  already in `future_tests.md`: classical repeat finders, profile searches and
  gene callers remain the stronger baseline for `prfB` and IS5.

## Candidates that do fit

All FP16 weight figures are `parameters × 2` bytes; all four run inside 2 GB on
this card, so the choice is about resolution, pretraining match and dependency
risk, not capacity.

| Model | Params | Resolution | Context | Pretraining | Licence | Risk |
|---|---:|---|---:|---|---|---|
| seqLens v2 Micro 16K | 10.3M | single nt | 16,384 nt | 113,379 GTDB r220 prokaryote representatives (OpenGenome2) | Apache-2.0 | needs `mamba-ssm` 2.2.4; BF16-trained |
| ProkBERT-mini-c | 24.9M | single nt (1-mer) | 1,022 nt | 206.65 Gnt prokaryotic | CC-BY-NC-4.0 | 3 kb needs tiling |
| GenomeOcean-500M | 500M | BPE, ~5 nt/token | 1,024 tokens (~5 kb) | microbial (GTDB-based corpus) | BSD | coarse resolution |
| NT v2 500M multi-species | 498M | 6-mer | 2,048 tokens (12 kb) | 850 genomes incl. bacteria, + 3,200 human | — | mostly eukaryotic |

Notes on each:

- **seqLens v2 Micro 16K** is the best match on paper: single-nucleotide
  tokenisation, prokaryote-only pretraining, a 16k context that holds a whole
  3 kb window with room for the shuffled control, Apache-2.0, and it exposes
  both `get_embeddings()` and masked-LM logits, which maps onto all three
  calls. Reported frozen linear probes: 0.911 coding/non-coding accuracy, 0.798
  genus accuracy on 50 held-out genera. The risk is the stack, not the science:
  it is BiMamba2 with two sliding-window attention layers and wants
  `mamba-ssm` 2.2.4 on Turing, where fused selective-scan kernels are
  Ampere-oriented and the weights were trained in BF16. At 10M parameters a
  CPU or FP32 fallback on 16 cores is a realistic plan B if the kernels refuse
  to build.
- **ProkBERT-mini-c** is the one that is near-certain to run: a plain BERT
  encoder in stock `transformers`, no custom kernels, 1-mer tokens, prokaryotic
  pretraining, and masked-token probabilities straight from a fill-mask head.
  Its 1,022 nt context forces three to four overlapping tiles per window, which
  adds a seam artefact to control for in the surprise profile. Licence is
  non-commercial, which is fine for thesis work and worth stating in any
  publication.
- **GenomeOcean-500M** is the only fitting candidate that is autoregressive,
  so it yields a true next-token log-likelihood rather than a masked
  pseudo-likelihood — the cleaner object for calls 1 and 2 — on a microbial
  corpus, under BSD, in a Mistral-style architecture that runs in stock
  `transformers` with eager attention. Its BPE tokens average ~5 bases, so the
  profile is blurred exactly where `prfB` needs sharpness, but ~5 kb of context
  covers the window and the resolution is adequate for IS5-scale boundaries.
- **NT v2 500M multi-species** earns a place only as the well-characterised
  comparator: it appears in GENEB, BEND and the frozen-representation study, so
  its behaviour is documented, and 6-mer tokens put a 3 kb window in 500 tokens.
  Its corpus is dominated by human and other eukaryotic genomes, so it is the
  distribution-mismatch control, not the primary tool.

Excluded on pretraining grounds rather than size: HyenaDNA (0.4–6.6M) and
Caduceus (8M each) are single-nucleotide and tiny, but pretrained on the human
reference genome, which is the wrong distribution for *E. coli*. DNABERT-2
(117M, BPE) fits and is widely benchmarked, but is human/multispecies and is
the model GENEB-style critiques are aimed at.

## Recommendation

1. **seqLens v2 Micro 16K as the primary tool**, with **ProkBERT-mini-c** as
   the guaranteed-to-run single-nucleotide twin. Both are prokaryotic and
   single-nucleotide; if the Mamba kernels will not build on Turing, the
   experiment still has a per-nucleotide profile.
2. **GenomeOcean-500M as the autoregressive cross-check** for calls 1 and 2, so
   the surprise profile does not rest on a masked pseudo-likelihood alone.
3. **Report agreement between them.** Two architectures agreeing on where a
   window is surprising is weak evidence, and our own `docs/verification.md`
   already states that agreement between two language models does not replace
   evidence — but disagreement is a cheap, informative negative.

**Calibration gate before any scored run.** Point the tool at the CRISPR
windows, which every model in the six-model batch already found. If the
surprise profile does not mark the repeat array against its shuffled baseline,
the tool cannot be expected to mark `prfB` or IS5 either, and plan 2b should be
dropped in favour of the classical-tool baseline rather than run. Also check
the profile on a gene-only control window, so "surprising" is not simply
"low-complexity".

Two caveats carried over from the plan and unchanged by this analysis: the DNA
tool runs outside the sandbox, so its use must be logged as an explicit
validation step rather than given to the worker; and *E. coli* K-12 is almost
certainly in the pretraining corpus of every candidate above — GTDB
representatives for the prokaryotic models — so a low surprisal may reflect
memorisation rather than biology. Isolation does not address this, and neither
does model choice.

## Setup cost

Nothing is installed: `.venv` has NumPy but no PyTorch and no CUDA toolkit. A
CUDA 12.x PyTorch wheel for compute capability 7.5 plus the three checkpoints is
a few GB of download against 1.2 TB free. Keep this in a separate environment
from the harness venv, since the harness deliberately runs standard-library
Python only.

## Sources

- [Evo 2 NIM prerequisites and support matrix](https://docs.nvidia.com/nim/bionemo/evo2/2.0.0/prerequisites.html) ·
  [Evo 2 fine-tuning tutorial](https://docs.nvidia.com/bionemo-framework/2.7.1/main/examples/bionemo-evo2/fine-tuning-tutorial/) ·
  [arcinstitute/evo2](https://github.com/arcinstitute/evo2) ·
  [Evo 2 in Nature](https://www.nature.com/articles/s41586-026-10176-5) ·
  [Evo (AI) overview](https://en.wikipedia.org/wiki/Evo_(AI))
- [Fundamental limitations of genomic language models for realistic sequence generation](https://www.biorxiv.org/content/10.64898/2026.01.17.700093v1.full) ·
  [The Mechanistic Invariance Test](https://arxiv.org/pdf/2604.06549)
- [GENEB: Why Genomic Models Are Hard to Compare](https://arxiv.org/abs/2606.04525) ·
  [Frozen but Not Always Accessible](https://arxiv.org/abs/2608.05329) ·
  [BEND](https://arxiv.org/pdf/2311.12570) ·
  [A bioinformatician's guide to choosing genomic foundation models](https://rewirebio.io/blog/a-bioinformaticians-guide-to-choosing-genomic-foundation-models/)
- [seqLens v2 Micro 16K](https://huggingface.co/seqSight/seqlens-v2-micro-16k) ·
  [ProkBERT-mini-c](https://huggingface.co/neuralbioinfo/prokbert-mini-c) ·
  [ProkBERT family preprint](https://www.biorxiv.org/content/10.1101/2023.11.09.566411.full.pdf) ·
  [GenomeOcean-500M](https://huggingface.co/pGenomeOcean/GenomeOcean-500M) ·
  [GenomeOcean-4B](https://huggingface.co/pGenomeOcean/GenomeOcean-4B) ·
  [GenomeOcean-4B v1.2](https://huggingface.co/DOEJGI/GenomeOcean-4B-v1.2) ·
  [NT v2 500M multi-species](https://huggingface.co/InstaDeepAI/nucleotide-transformer-v2-500m-multi-species) ·
  [Nucleotide Transformer paper](https://people.stat.sc.edu/hoyen/STAT718/Papers/Nucleotide_Transformer.pdf) ·
  [Caduceus](https://arxiv.org/pdf/2403.03234)
- [gLMs decode bacterial genomes for gene prediction and TIS identification](https://pmc.ncbi.nlm.nih.gov/articles/PMC12222049/) ·
  [Evo at Arc Institute](https://arcinstitute.org/tools/evo)
- [RTX 2060 SUPER precision support](https://getdeploying.com/gpus/nvidia-rtx-2060-super-vs-nvidia-rtx-3060-ti) ·
  [CUDA compute capabilities](https://cvw.cac.cornell.edu/gpu-architecture/gpu-characteristics/computecap)
