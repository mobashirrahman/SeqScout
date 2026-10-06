#!/usr/bin/env bash
# Small sandboxed pilot: four E. coli windows, both conditions, one repetition per model.
#
#   region_004  control (mgtL, mgtA)
#   region_006  prfB programmed frameshift
#   region_010  CRISPR repeat-spacer array
#   region_011  insertion sequence IS5
#
# Usage:  src/pilot_ecoli.sh            run agents, judge, analyse
#         src/pilot_ecoli.sh --dry-run  list the runs without calling any model
#         MODELS="hy3 glm-5.2" src/pilot_ecoli.sh
#         MODELS=space-bunny-free EFFORT=max MAX_TURNS=60 MAX_OUT=64000 OUT=results/sandbox_pilot src/pilot_ecoli.sh
#
# longcat-2.5-preview-free and omen-alpha are free on the Go plan, so they cost
# nothing to add. The Zen free models are not an option: they reject any client
# other than OpenCode itself, and the Go client policy asks us to send our own
# user agent rather than name ourselves as OpenCode.
set -euo pipefail
cd "$(dirname "$0")/.."

MODELS=${MODELS:-"glm-5.3-flash hy3 glm-5.2 deepseek-v4.1-flash longcat-2.5-preview-free omen-alpha"}
JUDGE=${JUDGE:-kimi-k2.7-code}
WINDOWS=region_004,region_006,region_010,region_011
OUT=${OUT:-results/sandbox_pilot}
LOGS=logs
MAX_TURNS=${MAX_TURNS:-30}
MAX_OUT=${MAX_OUT:-32000}
WORKERS=${WORKERS:-4}
EFFORT=${EFFORT:-}   # empty leaves each model on its own default reasoning level
PY=.venv/bin/python

agent() {
    $PY -u src/harness.py --provider opencode-go --model "$1" --loci data/ecoli/loci --only "$WINDOWS" \
        --out "$OUT/$1" --reps 1 --max-turns "$MAX_TURNS" --max-output-tokens "$MAX_OUT" \
        ${EFFORT:+--effort "$EFFORT"} --workers "$WORKERS" "${@:2}"
}

if [[ "${1:-}" == "--dry-run" ]]; then
    for model in $MODELS; do agent "$model" --dry-run; done
    exit
fi

set -a; . ./.env; set +a
mkdir -p "$OUT" "$LOGS"
for model in $MODELS; do
    agent "$model" > "$LOGS/sandbox_pilot_$model.log" 2>&1 &   # each model has its own allowance, so run them side by side
done
wait
for model in $MODELS; do
    echo "===== $model"
    tail -n 9 "$LOGS/sandbox_pilot_$model.log"
    $PY src/judge.py --provider opencode-go --model "$JUDGE" --runs "$OUT/$model" | tail -n 1
    $PY src/analyze.py --runs "$OUT/$model" --truth data/ecoli/truth --loci data/ecoli/loci
done
