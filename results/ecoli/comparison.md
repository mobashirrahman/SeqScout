# Final E. coli comparison

Generated 2026-10-06T00:59:22.847584+00:00.

12 windows × 2 conditions × 3 repetitions = 72 runs per model. Both models use the same prompts, tools, 20-turn limit and Kimi K2.7 Code judge. All saved runs have transcripts.

| Model | Condition | Saved | Found / scored positives | Located / scored positives | Special claims / scored controls | Forced / saved | Not scored |
|---|---|---|---|---|---|---|---|
| deepseek-v4.1-flash | file | 36/36 | 6/18 | 6/18 | 1/18 | 21/36 | 0 |
| deepseek-v4.1-flash | inline | 36/36 | 6/18 | 6/18 | 1/17 | 21/36 | 1 |
| glm-5.3-flash | file | 36/36 | 6/17 | 6/17 | 1/15 | 20/36 | 4 |
| glm-5.3-flash | inline | 36/36 | 5/15 | 5/15 | 1/16 | 21/36 | 5 |

## Individual targets

Each cell is located / found / scored, followed by any unscored runs. Repetitions share the same window; the independent sequence sample is two CRISPR windows, three insertion sequences and one frameshift window.

| Locus | Target | DeepSeek file | DeepSeek inline | GLM file | GLM inline |
|---|---|---|---|---|---|
| region_002 | CRISPR repeat-spacer array: array at 2904014 | 3 / 3 / 3 | 3 / 3 / 3 | 3 / 3 / 3 | 3 / 3 / 3 |
| region_003 | insertion sequence: IS609 | 0 / 0 / 3 | 0 / 0 / 3 | 0 / 0 / 3 | 0 / 0 / 2 (+1 unscored) |
| region_005 | insertion sequence: IS2H | 0 / 0 / 3 | 0 / 0 / 3 | 0 / 0 / 3 | 0 / 0 / 3 |
| region_006 | programmed ribosomal frameshift: prfB | 0 / 0 / 3 | 0 / 0 / 3 | 0 / 0 / 2 (+1 unscored) | 0 / 0 / 2 (+1 unscored) |
| region_010 | CRISPR repeat-spacer array: array at 2877884 | 3 / 3 / 3 | 3 / 3 / 3 | 3 / 3 / 3 | 2 / 2 / 2 (+1 unscored) |
| region_011 | insertion sequence: IS5R | 0 / 0 / 3 | 0 / 0 / 3 | 0 / 0 / 3 | 0 / 0 / 3 |

## Effort and failures

| Model | Median seconds | Input (cached subset) | Output tokens | Wrapper errors | Python diagnostic outputs (runs) | Identity claims / scored |
|---|---|---|---|---|---|---|
| deepseek-v4.1-flash | 242.2 | 23,664,024 (19,003,072) | 2,568,616 | 0 | 42 (31) | 23/71 |
| glm-5.3-flash | 274.0 | 13,698,218 (8,948,992) | 1,514,924 | 3 | 197 (66) | 12/63 |

Python failures are inferred from traceback, exception and timeout text in tool outputs. The original wrapper counters omit subprocess failures. Token totals cover agent calls; judge usage was not saved, so these are not total billed usage.

## External access and environment changes

The harness does not enforce the tool description's standard-library-only constraint or disable networking. GLM region_001 inline repetition 1 successfully retrieved an EBI BLAST result; GLM region_004 inline repetition 2 installed Biopython and NumPy in the shared virtual environment and opened a UniProt URL. This is a material limitation of a sequence-only interpretation. The current batch is retained unchanged.

- `results/ecoli/glm-5.3-flash/region_001__inline__1.json`: network-related code on turns [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]; installation code on turns [] (zero-based; keyword flags require transcript review).
- `results/ecoli/glm-5.3-flash/region_004__inline__2.json`: network-related code on turns [18]; installation code on turns [17] (zero-based; keyword flags require transcript review).

## Interpretation limits

- Found means the judge extracted the target's feature type somewhere in the report. Located additionally requires any coordinate overlap; descending coordinate pairs are normalised. These metrics do not establish exact boundaries or correct biological interpretation.
- Controls exclude selected special annotations, pseudogenes and annotated ribosomal slippage. Additional claims are not automatically false. Other notable features on real DNA do not measure over-claiming.
- CRISPR truth comes from a repeat search, not a curated annotation. In region_010, the conserved core is 331–910 with 10 exact copies, while a diagnostic motif scan also finds three variant copies at 943, 1004 and 1065. Boundary and copy-number errors against this core should not be interpreted as accuracy on the full array.
- Identity claims exclude supplied filenames and generic ORF labels. They include incorrect guesses and functional names; they do not prove memorisation.
- Empty reports remain unscored, including in the CSV. Detection denominators include only judged reports; effort and forced-report denominators include every saved run.
- Wilson intervals in individual analysis files describe repeated runs and do not account for correlation within a locus. This pilot does not establish a reliable advantage of either presentation condition.

## Unscored reports

- `results/ecoli/deepseek-v4.1-flash/region_008__inline__1.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_003__inline__1.json`: end_turn; empty report
- `results/ecoli/glm-5.3-flash/region_006__file__0.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_006__inline__1.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_008__inline__1.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_008__inline__2.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_009__file__0.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_009__file__1.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_009__file__2.json`: max_tokens; empty report
- `results/ecoli/glm-5.3-flash/region_010__inline__0.json`: max_tokens; empty report

Concrete factual, coordinate and boundary examples are documented in [audit_notes.md](audit_notes.md).
