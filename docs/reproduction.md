# Reproducing the experiments

Run these commands from the repository root.

The current harness requires the [controlled execution environment](isolation.md).
Commands below create fresh isolated batches. The saved pilot results used the
earlier unrestricted runner and remain in `results/synthetic/` and `results/ecoli/`.

A small experiment on agent harness design. The same model gets the same DNA
region and the same neutral task ("describe anything notable") under two
conditions:

| condition | what differs |
|---|---|
| `inline` | the raw sequence is pasted into the prompt |
| `file` | the sequence is only in `region.fasta`; the agent must open it |

Tools, system prompt and workspace are identical in both. Some regions contain a
planted repeat array, some are random controls. We measure how often the final
report mentions the array, and how many contiguous nucleotides the agent pulled
into its context through tools.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

.venv/bin/python tests/test_offline.py     # no API calls
.venv/bin/python tests/test_isolation.py   # actual kernel enforcement; no API calls
.venv/bin/python src/isolation.py              # checks this host's restrictions
.venv/bin/python src/make_loci.py              # 5 positives + 5 controls -> data/
.venv/bin/python src/harness.py --out results/isolated/claude-opus-5-5 --dry-run
.venv/bin/python src/harness.py --out results/isolated/claude-opus-5-5 --reps 3
.venv/bin/python src/judge.py --runs results/isolated/claude-opus-5-5
.venv/bin/python src/analyze.py --runs results/isolated/claude-opus-5-5
```

`harness.py` saves one JSON per run in `results/synthetic/<model>/` and skips runs that
already exist, so it can be interrupted and resumed. `--out` overrides this
default. Resume refuses mixed execution policies or code versions, including
historical unrestricted runs. Start with `--reps 1` to check the cost before
scaling up.

### Other models through OpenCode Go

```bash
export OPENCODE_API_KEY=...
M=glm-5.3-flash
.venv/bin/python src/harness.py --provider opencode-go --model "$M" \
  --out "results/isolated/$M" --reps 1
.venv/bin/python src/judge.py --provider opencode-go --model kimi-k2.7-code --runs "results/isolated/$M"
.venv/bin/python src/analyze.py --runs "results/isolated/$M"
```

This provider uses the OpenAI-compatible `/chat/completions` endpoint. Use one fixed judge model for every
agent model you compare, so the scoring does not change between them.

### E. coli pilot

The second batch uses 12 fixed 3,000-base windows from *E. coli* K-12 MG1655
(`U00096.3`): two CRISPR cores, three insertion sequences, one `prfB`
frameshift region and six annotation-selected controls. The FASTA files and
truth are in `data/ecoli/`; the source sequence and feature table are cached
in `data/raw/`. `fetch_ecoli.py` reproduces the set from that cache.

The historical pilot has 72 completed runs per agent model. The following
commands start new isolated batches in separate directories. Resuming skips
saved runs with matching execution policies and code; wait for a harness or
judge on the same directory to finish before resuming it.

```bash
set -a
. ./.env
set +a
for M in deepseek-v4.1-flash glm-5.3-flash; do
  .venv/bin/python src/harness.py --provider opencode-go --model "$M" \
    --loci data/ecoli/loci --out "results/isolated/ecoli/$M" --reps 3 --workers 6
  .venv/bin/python src/judge.py --provider opencode-go --model kimi-k2.7-code \
    --runs "results/isolated/ecoli/$M"
  .venv/bin/python src/analyze.py --runs "results/isolated/ecoli/$M" \
    --truth data/ecoli/truth --loci data/ecoli/loci > "results/isolated/ecoli/$M/analysis.txt"
done
.venv/bin/python src/summarize_ecoli.py --runs results/isolated/ecoli
```

`summarize_ecoli.py` writes `comparison.md` and `summary.json` under `--runs`,
validates every window against the source record, and checks that model,
prompt, code, turn limit and judge match across the comparison. It rejects
an unfinished batch unless passed `--allow-partial`.

The broader report comparison is in
[`results/ecoli/exploration.md`](../results/ecoli/exploration.md). Run
`.venv/bin/python src/explore_ecoli.py` to reproduce its gene-coordinate coverage,
tool diagnostics, report-topic counts and output-quality flags. This analysis
uses the saved reports and annotation and makes no API calls; its exploratory
metrics are separate from the original target scores.

The CSV retains empty and unjudged reports with blank scores. Detection
denominators use judged reports; effort includes every saved run. The
transcript-derived Python diagnostic count includes failures omitted by the
original tool wrapper counters. Recognition flags exclude filenames and
generic ORF labels; biological names can still be incorrect guesses.

CRISPR truth describes approximate conserved cores found by a local repeat
search, rather than independently curated array boundaries. Additional
degenerate copies can lie outside these cores. Special-feature claims on
real controls and other notable features require review before calling them
false alarms or over-claiming. Repetitions share windows, so the run-level
Wilson intervals do not represent uncertainty across independent loci.

The historical pilot is **not strictly offline**: GLM used `urllib` to retrieve
an EBI BLAST result and used `pip` to install Biopython/NumPy in the shared
virtual environment. These runs are flagged in the comparison and its JSON.
The original tool description's standard-library-only constraint was not
enforced. The current runner blocks sockets, package access and subprocesses;
the historical results do not establish performance under those controls.

## Design choices worth knowing

- **Truth formats.** Synthetic ground truth is exact. Its files use `has_array`,
  `length` and, for positives, `start`, `end`, `unit_len` and `copies` (1-based
  coordinates). Real-sequence files can instead use `target` (null for controls)
  with a feature `type`, `kind`, `name`, `start` and `end`, plus source and
  annotation metadata. Supply matching `--loci` and `--truth` directories.
- **Blind judge.** `judge.py` sees only the report text and extracts what it
  claims. The comparison with the truth happens in code in `analyze.py`.
- **Refusals are an outcome, not an error.** No fallback model is configured,
  because a silent model swap would confound the comparison. Refused runs are
  counted in the "not scored" column.
- **`--read-default`** sets how many characters `read_file` returns when the
  agent gives no length. It is a harness parameter that may itself change the
  result, so it is recorded in every run.
- **Worker policy.** All tools use Landlock and seccomp, with read-only inputs,
  writable per-run scratch and resource limits. Configuration is in
  `sandbox_policy.json`, or supply `--sandbox-policy` with a custom file.
  Unsupported hosts stop before model API calls; no unrestricted fallback
  exists. Basic host filesystem metadata remains visible. See
  [the exact execution boundary](isolation.md).

## Limits

- Synthetic repeat arrays in random background are easy targets. Real genomes
  have their own repeats and low-complexity stretches; extra findings need
  verification before they can be counted as false alarms.
- Small numbers give wide intervals. The tables print 95% Wilson intervals
  across runs; repetitions on the same window are correlated.
- "Found" means the report claims the target feature type; "located" additionally
  requires coordinate overlap. These scores do not validate function or exact
  boundaries.
