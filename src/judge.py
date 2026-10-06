"""Extract what each report claims, without showing the judge the answer.

The judge sees only the report text: not the condition, not the locus, not the
ground truth. It turns the report into a few structured fields, and analyze.py
compares those fields with the truth in code.
"""
import argparse
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ValidationError, field_validator

from backends import PROVIDERS, extract_json, make_client

FEATURE_TYPES = ("repeat_array", "mobile_element", "frameshift", "gene", "other")

INSTRUCTIONS = """Below is a report an analyst wrote about a DNA region. Record what the report claims.

List every feature the report presents as present in the region. Leave out features \
the report examined and dismissed as absent, ordinary or expected by chance. Give each \
feature one type:

- repeat_array: a sequence unit occurring several times in a row, back to back or \
separated by spacers (tandem repeats, satellites, CRISPR-like repeat-spacer arrays). \
Not a single duplicated motif, a homopolymer run or one hairpin.
- mobile_element: an insertion sequence, transposon or other transposable element, \
including a transposase gene or an element bounded by inverted terminal repeats.
- frameshift: a gene the report says is split across two reading frames, read through \
a programmed ribosomal frameshift, or interrupted by a frameshift or premature stop.
- gene: an ordinary open reading frame or gene.
- other: anything else presented as notable.

Use the report's own coordinates for start and end, and null where it gives none. For \
a repeat_array also give unit_length and copy_number if the report states them. Do not \
infer or compute values the report does not state.

named_identity lists any organism, gene or locus names by which the report identifies \
the region or its features (for example a species name or a gene symbol). Use an empty \
list if it names none.

<report>
{report}
</report>"""


# A reviewed run holds two reports: the final one and the one written before the review.
REPORT_FIELDS = (("report", "claims"), ("first_report", "first_claims"))


class Feature(BaseModel):
    type: str
    start: Optional[int]
    end: Optional[int]
    unit_length: Optional[int] = None
    copy_number: Optional[int] = None
    description: str

    @field_validator("type", mode="before")
    @classmethod
    def _known_type(cls, value):
        return value if value in FEATURE_TYPES else "other"

    @field_validator("start", "end", "unit_length", "copy_number", mode="before")
    @classmethod
    def _number_from_text(cls, value):
        # Judges sometimes echo the report's hedged wording, e.g. "~10" or 8.2.
        if isinstance(value, float):
            return round(value)
        if isinstance(value, str):
            digits = re.search(r"\d+", value.replace(",", ""))
            return int(digits.group()) if digits else None
        return value


class Claims(BaseModel):
    features: list[Feature]
    named_identity: list[str]


JSON_SUFFIX = """

Reply with one JSON object and nothing else, with exactly two keys. "features" is an \
array of objects with keys type (one of repeat_array, mobile_element, frameshift, gene, \
other), start, end, unit_length, copy_number (integer or null) and description (a few \
words). "named_identity" is an array of strings."""


def judge_report_openai(client, report, model):
    response = client.chat.completions.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": INSTRUCTIONS.format(report=report) + JSON_SUFFIX}],
        extra_headers={"x-opencode-session": str(uuid.uuid4())},
    )
    raw = extract_json(response.choices[0].message.content or "")
    try:
        return Claims.model_validate_json(raw).model_dump() if raw else None
    except ValidationError:
        return None


def judge_report(client, report, model):
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": INSTRUCTIONS.format(report=report)}],
        output_format=Claims,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return None
    return response.parsed_output.model_dump()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, required=True, help="a directory written by harness.py")
    p.add_argument("--provider", default="anthropic", choices=PROVIDERS)
    p.add_argument("--model", help="judge model; default claude-opus-5-5 for anthropic")
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()
    if args.model is None:
        if args.provider != "anthropic":
            p.error(f"--model is required with --provider {args.provider}")
        args.model = "claude-opus-5-5"

    client = make_client(args.provider)
    judge = judge_report if args.provider == "anthropic" else judge_report_openai
    def pending(record):
        """(report field, claims field) pairs still to judge. A failed judgement (None) is tried again."""
        return [(text, claims) for text, claims in REPORT_FIELDS if record.get(text) and record.get(claims) is None]

    todo, skipped = [], 0
    for path in sorted(args.runs.glob("*.json")):
        if pending(json.loads(path.read_text())):
            todo.append(path)
        else:
            skipped += 1

    def work(path):
        record = json.loads(path.read_text())
        for text, claims in pending(record):
            record[claims] = judge(client, record[text], args.model)
        record["judge_model"] = args.model
        path.write_text(json.dumps(record, indent=2) + "\n")
        return path.stem, record["claims"]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for stem, claims in pool.map(work, todo):
            summary = [f"{f['type']} {f['start']}-{f['end']}" for f in claims["features"]] if claims else None
            print(f"{stem}: {summary}")
    judged = len(todo)
    failed = sum(json.loads(p.read_text()).get("claims", 0) is None for p in args.runs.glob("*.json"))
    print(f"judged {judged}, skipped {skipped} (already judged or no report); {failed} reports still without a usable judgement")


if __name__ == "__main__":
    main()
