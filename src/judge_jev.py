"""Judge reports with Jev, a structured-decision model that answers typed questions.

Jev cannot extract numbers, so coordinates are recovered by asking, for each
feature type and each stretch of the region, whether the report places such a
feature there. Like judge.py, the judge sees only the report text: not the
condition, the locus or the ground truth. The answers are written in the same
"claims" format judge.py produces, so analyze.py reads either.

Compared with judge.py this gives positions only to the nearest bin, and no
unit length, copy number, gene list or names.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backends import GO_KEY_ENV, USER_AGENT
from judge import REPORT_FIELDS

ENDPOINT = "https://opencode.ai/zen/v1/systemone"
YES = 0.5
ABSENT = " A statement that none was found does not count."
TYPES = {
    "repeat_array": (
        "a repeat array: a sequence unit occurring several times in a row, back to back or "
        "separated by spacers (tandem repeats, satellites, CRISPR-like arrays). A single "
        "duplicated motif, a homopolymer run or one hairpin does not count"
    ),
    "mobile_element": (
        "an insertion sequence, transposon or other transposable element, including a "
        "transposase gene or an element bounded by inverted terminal repeats"
    ),
    "frameshift": (
        "a gene that is split across two reading frames, read through a programmed ribosomal "
        "frameshift, or interrupted by a frameshift or premature stop"
    ),
}


def build_questions(length, bin_size):
    questions = {}
    for kind, text in TYPES.items():
        questions[kind] = {
            "type": "noul",
            "instructions": f"Does the report state that the region contains {text}?{ABSENT}",
        }
        for start in range(1, length + 1, bin_size):
            end = min(start + bin_size - 1, length)
            questions[f"{kind}@{start}-{end}"] = {
                "type": "noul",
                "instructions": (
                    f"Does the report place {text.split(':')[0].split(',')[0]} at coordinates that "
                    f"overlap positions {start} to {end} of the region? Answer no if the report "
                    "claims no such feature or gives it no coordinates."
                ),
            }
    questions["other"] = {
        "type": "noul",
        "instructions": (
            "Apart from ordinary genes or open reading frames, repeat arrays, mobile elements and "
            "frameshifts, does the report present any other feature of the region as notable, "
            "unusual or possibly functional? Features it examined and dismissed do not count."
        ),
    }
    questions["named"] = {
        "type": "noul",
        "instructions": "Does the report identify the region or a feature in it by an organism name, a gene name or a locus name?",
    }
    return questions


def call_jev(model, report, questions, key):
    body = json.dumps({"model": model, "state": report, "questions": questions}).encode()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT}
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(ENDPOINT, body, headers), timeout=120) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503):
                raise SystemExit(f"Jev refused the request: {error.code} {error.read().decode()[:300]}")
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(5 * (attempt + 1))
    return None


def to_claims(answers):
    """Jev's probabilities as a judge.py-style claims record."""
    p = {name: answer["noul"] for name, answer in answers.items()}
    features = []
    for kind in TYPES:
        if p[kind] < YES:
            continue
        spans = []  # merged runs of adjacent bins the report was said to cover
        for name in (n for n in p if n.startswith(f"{kind}@")):
            start, end = (int(x) for x in name.split("@")[1].split("-"))
            if p[name] < YES:
                continue
            if spans and start == spans[-1][1] + 1:
                spans[-1][1] = end
            else:
                spans.append([start, end])
        for start, end in spans or [[None, None]]:
            features.append({"type": kind, "start": start, "end": end, "description": "position from Jev bins"})
    if p["other"] >= YES:
        features.append({"type": "other", "start": None, "end": None, "description": "other notable feature"})
    return {
        "features": features,
        "named_identity": ["(named; Jev does not extract the name)"] if p["named"] >= YES else [],
        "coarse_positions": True,
        "jev": {name: round(value, 3) for name, value in p.items()},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, required=True, help="a directory of run records")
    p.add_argument("--model", default="jev-1.13-free")
    p.add_argument("--length", type=int, default=3000, help="length of the regions the reports describe")
    p.add_argument("--bin", type=int, default=500, help="resolution of the recovered positions")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    key = os.environ.get(GO_KEY_ENV) or p.error(f"set {GO_KEY_ENV}")
    questions = build_questions(args.length, args.bin)

    def pending(record):
        return [(text, claims) for text, claims in REPORT_FIELDS if record.get(text) and record.get(claims) is None]

    todo = [path for path in sorted(args.runs.glob("*.json")) if pending(json.loads(path.read_text()))]

    def work(path):
        record = json.loads(path.read_text())
        for text, claims in pending(record):
            reply = call_jev(args.model, record[text], questions, key)
            record[claims] = to_claims(reply["answers"]) if reply else None
        record["judge_model"] = args.model
        path.write_text(json.dumps(record, indent=2) + "\n")
        return path.stem, record["claims"]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for stem, claims in pool.map(work, todo):
            summary = [f"{f['type']} {f['start']}-{f['end']}" for f in claims["features"]] if claims else None
            print(f"{stem}: {summary}")
    failed = sum(bool(pending(json.loads(path.read_text()))) for path in args.runs.glob("*.json"))
    print(f"judged {len(todo)}; {failed} reports still without a usable judgement")


if __name__ == "__main__":
    main()
