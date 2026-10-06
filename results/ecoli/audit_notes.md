# E. coli scoring audit

These are concrete examples checked against the cached sequence, annotation
and transcripts. They are a qualitative audit, not an estimated error rate.
The saved reports, judge claims and target truth remain unchanged.

## Numeric error carried into a biological interpretation

[GLM, region_002, inline, repetition 0](glm-5.3-flash/region_002__inline__0.json)
reports GC content of 66.1% and suggests Firmicutes, including
Streptococcus/Staphylococcus. Counting the supplied FASTA gives G=661,
C=648 and length=3000: GC is **43.633%**. The source record identifies the
sequence as E. coli K-12 MG1655.

Its [transcript](glm-5.3-flash/transcripts/region_002__inline__0.json)
contains this computation:

```python
print(len(seq), seq.count('G') + seq.count('C') / len(seq))
```

The output is `3000 661.216`. Missing parentheses cause the calculation to
divide only the C count, and the report then treats that output as 66.1%.
The report nevertheless detects the CRISPR core. A detection success does
not establish that the rest of the interpretation is correct.

## Reverse-strand coordinates reported in the wrong coordinate system

[GLM, region_001, file, repetition 0](glm-5.3-flash/region_001__file__0.json)
places its main reverse-strand ORF at 1050–2336. Its
[script](glm-5.3-flash/transcripts/region_001__file__0.json) reports
positions in the reverse-complement string without converting them back
to the supplied sequence. For a 3000-base window, that interval maps to
**665–1951** in the original coordinates:

```text
start = 3000 - 2336 + 1 = 665
end   = 3000 - 1050 + 1 = 1951
```

The judge correctly records what the report says. It does not verify the
sequence or repair the report's coordinates.

## A fuller array can disagree with approximate truth

[DeepSeek, region_010, inline, repetition 0](deepseek-v4.1-flash/region_010__inline__0.json)
reports an array at 331–1093 with 13 copies. The saved target truth is the
conserved core at 331–910 with 10 copies. An independent local 29-base
motif scan finds those ten exact copies and three variants at 943, 1004
and 1065, with 2, 1 and 3 mismatches respectively to the core motif.

The target still overlaps correctly. Treating the extra three copies or
extended boundary as an error against full-array truth would be unjustified.
The truth interval is a repeat-search seed, not a curated complete array.

The same report suggests the two downstream ORFs are candidate Cas
proteins. The source annotation assigns these intervals to `iap` and
`cysD`. Finding an array and assigning nearby gene functions are separate
claims and need separate checks.

## Metrics that need careful interpretation

- Three control flags illustrate why the raw tally is not a false-alarm
  rate. DeepSeek region_009 file repetition 1 correctly reports `AAG` ×4
  at 2785–2796. GLM region_001 file repetition 2 correctly reports
  `ATCACC` ×2 at 2381–2392, but explicitly says it is not biologically
  interesting; extracting it as a finding violates the judge's exclusion
  instructions. GLM region_009 inline repetition 0 claims `CGTCGT` ×3
  at 2795–2810; that 16-base interval actually contains
  `AGGAGTGAATATGCAG`, and cannot contain three six-base copies. This last
  claim is a concrete factual error. These cases are preserved in the
  raw metrics and are not pooled into an over-claiming estimate.
- [GLM region_001 inline repetition 1](glm-5.3-flash/transcripts/region_001__inline__1.json)
  submitted EBI BLAST jobs and retrieved an output identifying PdxH
  matches, including Shigella and E. coli. These names are external
  information, not evidence of memorisation. Network access is possible
  through the standard library despite the lack of dedicated database tools.
- [GLM region_004 inline repetition 2](glm-5.3-flash/transcripts/region_004__inline__2.json)
  successfully ran `pip install biopython`, also installing NumPy in the
  shared virtual environment, and opened a UniProt URL. Temporary working
  directories do not isolate interpreter dependencies. A future strictly
  sequence-only batch must enforce both network and dependency isolation.
- The original `tool_errors` counters record wrapper failures. A Python
  process can print a traceback while the wrapper returns `is_error=False`.
  The comparison therefore also counts diagnostic outputs from transcripts.
- The judge sometimes includes `region.fasta`, `region_001`, `ORF1`,
  `gene A` or similar labels as named identities. Analysis excludes these
  placeholders and retains the raw identity list in a separate CSV column.
- A special feature claimed on a control is not automatically false. Very
  short duplicated motifs can also be extracted as repeat arrays despite
  the judge instruction to exclude single duplicated motifs. Review the
  specific claims before using that tally as an over-claiming rate.
- The transcript route measure checks whether the agent quoted a repeat
  fragment before a script tagged by repeat-search keywords. It does not
  prove conscious recognition, successful script execution or absence of
  sequence recall.

## Next experiment

Keep this batch as a fixed pilot. First enforce execution isolation, curate full CRISPR boundaries and
repeat copies, review special-feature extraction on controls, and measure
factual and functional over-claiming explicitly. A later batch can vary the
turn cap and use more independent loci. The synthetic transcript rerun,
full GLM-5.3 run, and human/yeast additions remain separate deferred work.
