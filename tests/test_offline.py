"""Checks that need no API access. Run with: python tests/test_offline.py"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import analyze  # noqa: E402
import harness  # noqa: E402
import make_loci  # noqa: E402
import transcripts  # noqa: E402
from tools import Workspace, longest_nt_run, seen_positions, to_intervals  # noqa: E402


def test_longest_nt_run():
    assert longest_nt_run("no sequence here, just a cat and a tag") == 0
    assert longest_nt_run("x " + "ACGT" * 10 + " y") == 40
    # FASTA line breaks do not split a run, a header does
    assert longest_nt_run(">h\n" + "A" * 70 + "\n" + "C" * 30 + "\n") == 100
    assert longest_nt_run("GC content: 0.5, length 3000") == 0


def test_loci_are_reproducible_and_truthful():
    import random

    seq, truth = make_loci.make_positive(random.Random(1), 3000, 0.5)
    seq2, _ = make_loci.make_positive(random.Random(1), 3000, 0.5)
    assert seq == seq2 and len(seq) == 3000
    array = seq[truth["start"] - 1 : truth["end"]]
    if truth["mutation_rate"] == 0:
        assert array.count(truth["unit"]) == truth["copies"]
    assert len(array) >= truth["unit_len"] * truth["copies"]


def test_seen_positions():
    seq = "ACGTTGCAAGGCTTAGCCATGCAATTGGCCAAGTCAGTCA" * 3
    assert to_intervals(seen_positions("x " + seq[10:40] + " y", seq[:60] + "T" * 60)) == [[11, 40]]
    # wrapped lines join; a short fragment is ignored
    assert to_intervals(seen_positions(seq[:25] + "\n" + seq[25:50] + "\nACGT", seq[:60] + "T" * 60)) == [[1, 50]]
    # a word glued on by a line break must not hide the sequence line after it
    assert to_intervals(seen_positions("data\n" + seq[:30] + "\n", seq[:60] + "T" * 60)) == [[1, 30]]
    assert seen_positions("GC content 0.5", seq) == set()
    # a fragment that occurs twice cannot be placed, so it is not counted
    assert seen_positions(seq[:30], seq) == set()


def test_route_from_transcript():
    unit = "GATTACAGGCTTAACCGGTTAGC"
    array = unit * 5
    kmers = transcripts.repeat_kmers(array)
    assert unit[:12] in kmers

    def openai_turn(reasoning, code=None):
        calls = [{"function": {"name": "run_python", "arguments": json.dumps({"code": code})}}] if code else []
        return {"role": "assistant", "content": "", "reasoning_content": reasoning, "tool_calls": calls}

    by_eye = [openai_turn("reading the file"), openai_turn(f"I can see {unit[3:20]} again and again", "find_tandem_repeats()")]
    turns = transcripts.assistant_turns(by_eye)
    assert transcripts.first_notice(turns, kmers) == (1, True)

    by_script = [openai_turn("no idea yet", "count kmers and find repeats"), openai_turn(f"the script reports {unit}")]
    assert transcripts.first_notice(transcripts.assistant_turns(by_script), kmers) == (1, False)

    never = [openai_turn("GC looks flat", "print(gc_content)")]
    assert transcripts.first_notice(transcripts.assistant_turns(never), kmers) == (None, None)

    anthropic = [{"role": "assistant", "content": [
        {"type": "thinking", "thinking": f"there is {unit[:15]} repeated"},
        {"type": "tool_use", "input": {"code": "translate orfs"}},
    ]}]
    turns = transcripts.assistant_turns(anthropic)
    assert transcripts.first_notice(turns, kmers) == (0, True) and transcripts.script_kinds(turns[0]["scripts"][0]) == ["orf"]
    assert transcripts.script_kinds("x = 1") == ["other"]


def test_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "region.fasta").write_text(">x\n" + "ACGT" * 100 + "\n")
        ws = Workspace(tmp, read_default=50)
        out, err = ws.call("read_file", {"path": "region.fasta"})
        assert not err and out.startswith(">x\nACGT") and "[characters 0-50 of" in out
        out, err = ws.call("read_file", {"path": "../../etc/passwd"})
        assert err and "outside" in out
        out, err = ws.call("run_python", {"code": "print(len(open('region.fasta').read()))"})
        assert not err and out.strip() == "404"
        out, err = ws.call("list_files", {})
        assert "region.fasta" in out
        out, err = ws.call("nope", {})
        assert err


class ScriptedClient:
    """Stands in for the API client and replays fixed responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def response(stop_reason, content):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        content=content,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        _request_id="req_test",
    )


def test_run_once_records_what_was_read():
    with tempfile.TemporaryDirectory() as tmp:
        locus = Path(tmp) / "locus_001.fasta"
        import random

        make_loci.write_fasta(locus, "locus_001", make_loci.rand_seq(random.Random(3), 3000, 0.5))
        read = SimpleNamespace(type="tool_use", id="t1", name="read_file", input={"path": "region.fasta", "length": 500})
        final = SimpleNamespace(type="text", text="Nothing notable.")
        opts = dict(model="m", effort="low", read_default=2000, max_turns=5)

        client = ScriptedClient([response("tool_use", [read]), response("end_turn", [final])])
        record = harness.run_once(client, locus, "file", **opts)
        assert record["status"] == "end_turn" and record["report"] == "Nothing notable."
        roles = [m["role"] for m in record["transcript"]]
        assert roles == ["user", "assistant", "user", "assistant"]
        json.dumps(record["transcript"])  # must be serialisable
        # 500 characters minus the 11-character header line and 6 line breaks
        assert record["nt_run_from_tools"] == 500 - len(">locus_001\n") - 6
        assert record["seen_intervals"] == [[1, 483]] and record["tool_calls"][0]["turn"] == 0
        assert len(record["turns"]) == 2 and record["prompt_hash"] == harness.PROMPT_HASH
        assert record["input_tokens"] == 20
        assert "<file>" not in client.requests[0]["messages"][0]["content"]

        client = ScriptedClient([response("end_turn", [final])])
        record = harness.run_once(client, locus, "inline", **opts)
        assert locus.read_text() in client.requests[0]["messages"][0]["content"]
        assert record["nt_run_from_tools"] == 0

        # still calling tools at the limit: one reserved call asks for the report
        client = ScriptedClient([response("tool_use", [read])] * 3)
        record = harness.run_once(client, locus, "file", **{**opts, "max_turns": 2})
        assert record["status"] == "max_turns" and record["rescue"] == "tool_calls_at_limit" and record["report"] == ""
        assert len(client.requests) == 3 and client.requests[2]["tool_choice"] == {"type": "none"}

        # output cap spent before any report text: the reserved call recovers the report
        client = ScriptedClient([response("max_tokens", []), response("end_turn", [final])])
        record = harness.run_once(client, locus, "file", **{**opts, "max_output_tokens": 777})
        assert record["status"] == "end_turn" and record["report"] == "Nothing notable."
        assert record["rescue"] == "empty_after_max_tokens" and record["forced_report"] is False
        assert client.requests[0]["max_tokens"] == 777 and record["max_output_tokens"] == 777
        assert client.requests[1]["messages"][-2]["content"][-1]["text"] == harness.RESCUE_NOTE
        assert [t["status"] for t in record["turns"]] == ["max_tokens", "end_turn"]

        # a tool call written out as text is not a report
        stray = SimpleNamespace(type="text", text='{"name": "run_python", "arguments": {"code": "print(1)"}}')
        client = ScriptedClient([response("end_turn", [stray]), response("end_turn", [final])])
        record = harness.run_once(client, locus, "file", **opts)
        assert record["rescue"] == "empty_after_end_turn" and record["report"] == "Nothing notable."
        assert harness.has_report("## Report\nNothing.") and not harness.has_report("  \n")
        assert harness.has_report("{braces} can start a real report")

        # at the limit the agent is told to stop and the last request forbids tools
        client = ScriptedClient([response("tool_use", [read]), response("end_turn", [final])])
        record = harness.run_once(client, locus, "file", **{**opts, "max_turns": 2})
        assert record["status"] == "end_turn" and record["forced_report"] is True
        assert client.requests[0]["tool_choice"] == {"type": "auto"}
        assert client.requests[1]["tool_choice"] == {"type": "none"}
        assert client.requests[1]["messages"][-2]["content"][-1]["text"] == harness.LIMIT_NOTE


def test_review_round():
    import supervise

    with tempfile.TemporaryDirectory() as tmp:
        import random

        locus = Path(tmp) / "locus_001.fasta"
        make_loci.write_fasta(locus, "locus_001", make_loci.rand_seq(random.Random(3), 3000, 0.5))
        read = SimpleNamespace(type="tool_use", id="t1", name="read_file", input={"path": "region.fasta"})
        text = lambda t: SimpleNamespace(type="text", text=t)
        opts = dict(model="m", effort="low", read_default=2000, max_turns=5, review_turns=3)

        # nudged: works again, then revises
        client = ScriptedClient([response("end_turn", [text("First.")]), response("tool_use", [read]), response("end_turn", [text("Revised.")])])
        record = harness.run_once(client, locus, "file", reviewer=supervise.make_reviewer("reflect"), **opts)
        assert (record["first_report"], record["report"]) == ("First.", "Revised.")
        assert record["review"]["mode"] == "reflect" and record["review"]["revised"] and record["review"]["tool_calls"] == 1
        assert client.requests[1]["messages"][2]["content"][0]["text"].startswith(supervise.NUDGES["reflect"])
        assert record["tool_calls"][0]["turn"] == 1 and record["forced_report"] is False

        # a revision that comes back empty keeps the first report
        client = ScriptedClient([response("end_turn", [text("First.")]), response("max_tokens", []), response("max_tokens", [])])
        record = harness.run_once(client, locus, "file", reviewer=supervise.make_reviewer("again"), **opts)
        assert record["report"] == "First." and record["review"]["revised"] is False

        # supervisor with nothing to ask sends no nudge; with questions, they reach the agent
        ask = supervise.ask
        try:
            supervise.ask = lambda *a: ("NONE", 5, 1)
            client = ScriptedClient([response("end_turn", [text("First.")])])
            record = harness.run_once(client, locus, "file", reviewer=supervise.make_reviewer("supervisor", None, "x", "big"), **opts)
            assert record["review"]["nudge"] is None and "first_report" not in record and len(client.requests) == 1
            supervise.ask = lambda *a: ("1. Why is the gap at 100-200 unexplained?", 5, 9)
            client = ScriptedClient([response("end_turn", [text("First.")]), response("end_turn", [text("Revised.")])])
            record = harness.run_once(client, locus, "file", reviewer=supervise.make_reviewer("supervisor", None, "x", "big"), **opts)
            assert "gap at 100-200" in record["review"]["nudge"] and record["review"]["supervisor_model"] == "big"
        finally:
            supervise.ask = ask


def test_direct_question_answers():
    import ask_direct

    parse = ask_direct.parse_answer
    assert parse("...\nANSWER: yes\nCOORDINATES: 1,129-2323") == (True, (1129, 2323))
    assert parse("**ANSWER:** Yes\n**COORDINATES:** 295 to 1393") == (True, (295, 1393))
    assert parse("ANSWER: no\nCOORDINATES: none") == (False, None)
    assert parse("ANSWER: no\nCOORDINATES: 5-9") == (False, None)  # a span only counts with a yes
    assert parse("first ANSWER: yes ... on reflection\nANSWER: no\nCOORDINATES: none") == (False, None)
    assert parse("I could not decide.") == (None, None)
    prfb = {"start": 295, "end": 1393}
    assert ask_direct.covers((295, 1393), prfb) and ask_direct.covers((1, 900), prfb)
    assert not ask_direct.covers((1374, 2934), prfb) and not ask_direct.covers(None, prfb)
    assert "region.fasta" in ask_direct.TASK.format(question="Q?") and harness.build_prompt("file", "x", "T") == "T"


def test_openai_compatible_backend():
    from backends import OpenAIChat, extract_json

    def completion(finish, content=None, tool_calls=None):
        message = SimpleNamespace(content=content, tool_calls=tool_calls)
        message.model_dump = lambda exclude_none: {"role": "assistant", "content": content}
        return SimpleNamespace(
            id="chatcmpl_test",
            choices=[SimpleNamespace(finish_reason=finish, message=message)],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        )

    def call(i, arguments):
        return SimpleNamespace(id=i, function=SimpleNamespace(name="read_file", arguments=arguments))

    class Client:
        def __init__(self, responses):
            self.responses, self.requests = list(responses), []
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            self.requests.append(kwargs)
            return self.responses.pop(0)

    with tempfile.TemporaryDirectory() as tmp:
        locus = Path(tmp) / "locus_001.fasta"
        make_loci.write_fasta(locus, "locus_001", "ACGT" * 750)
        client = Client(
            [
                completion("tool_calls", tool_calls=[call("a", '{"path": "region.fasta"}'), call("b", "{not json")]),
                completion("stop", content="Report."),
            ]
        )
        record = harness.run_once(
            client, locus, "file", model="m", effort=None, read_default=2000, max_turns=5, chat_cls=OpenAIChat
        )
        assert record["status"] == "end_turn" and record["report"] == "Report."
        assert [c["is_error"] for c in record["tool_calls"]] == [False, True]
        assert record["nt_run_from_tools"] > 1900 and record["input_tokens"] == 14
        first, second = client.requests
        assert first["tools"][0]["type"] == "function" and "reasoning_effort" not in first
        assert OpenAIChat(client, "m", "s", "p", effort="max").extra == {"reasoning_effort": "max"}
        assert first["extra_headers"] == second["extra_headers"]  # one session id per conversation
        # the request holds the live history, which has since gained the final reply
        assert [m["role"] for m in second["messages"]][:5] == ["system", "user", "assistant", "tool", "tool"]

    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json("no json") is None


def test_score_and_wilson():
    truth = {"has_array": True, "start": 500, "end": 900, "unit_len": 40, "copies": 10}
    hit = {"claims": {"claims_repeat_array": True, "start": 480, "end": 700}}
    assert analyze.score(hit, truth) == {"positive": True, "claimed": True, "localized": True}
    off = {"claims": {"claims_repeat_array": True, "start": 1000, "end": 1200}}
    assert analyze.score(off, truth)["localized"] is False
    vague = {"claims": {"claims_repeat_array": True, "start": None, "end": None}}
    assert analyze.score(vague, truth)["localized"] is False
    false_alarm = analyze.score(hit, {"has_array": False})
    assert false_alarm == {"positive": False, "claimed": True, "localized": False}
    assert analyze.score({"claims": None}, truth) is None

    # second truth and judge format: any target type, a list of claimed features
    is_truth = {"target": {"type": "mobile_element", "kind": "insertion sequence", "name": "IS5", "start": 1000, "end": 2200}}
    feats = lambda *f: {"claims": {"features": [dict(zip(("type", "start", "end"), x)) for x in f], "named_identity": []}}
    assert analyze.score(feats(("gene", 1100, 2000), ("mobile_element", 900, 2300)), is_truth)["localized"] is True
    assert analyze.score(feats(("repeat_array", 1100, 1200)), is_truth)["claimed"] is False
    assert analyze.score(feats(("gene", 1, 500), ("other", None, None)), {"target": None})["claimed"] is False
    assert analyze.score(feats(("frameshift", 1, 500)), {"target": None})["claimed"] is True
    assert analyze.accuracy(feats(("mobile_element", 990, 2210)), is_truth)["start_err"] == -10
    assert analyze.score(feats(("mobile_element", 2300, 900)), is_truth)["localized"] is True
    assert analyze.accuracy(feats(("mobile_element", 2210, 990)), is_truth)["start_err"] == -10
    import judge

    hedged = judge.Claims.model_validate_json(
        '{"features": [{"type": "CRISPR-like", "start": "1,828", "end": null, "unit_length": 33.0,'
        ' "copy_number": "~10", "description": "x"}], "named_identity": []}'
    ).features[0]
    assert (hedged.type, hedged.copy_number, hedged.start, hedged.end, hedged.unit_length) == ("other", 10, 1828, None, 33)
    assert analyze.wilson(0, 15)[0] == 0.0
    lo, hi = analyze.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77


def test_pipeline_end_to_end():
    """make_loci -> hand-written run records -> analyze, all in a temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        py = sys.executable
        subprocess.run([py, ROOT / "src" / "make_loci.py", "--positives", "2", "--negatives", "2", "--out", tmp / "data"], check=True, capture_output=True)
        runs = tmp / "runs"
        runs.mkdir()
        opts = ["--runs", runs, "--truth", tmp / "data/truth", "--loci", tmp / "data/loci", "--csv", tmp / "r.csv"]
        for truth_path in sorted((tmp / "data/truth").glob("*.json")):
            truth = json.loads(truth_path.read_text())
            for condition in harness.CONDITIONS:
                found = truth["has_array"] and condition == "inline"
                record = {
                    "locus": truth_path.stem, "condition": condition, "rep": 0, "status": "end_turn",
                    "tool_calls": [], "nt_run_from_tools": 0, "report": "r", "input_tokens": 1, "output_tokens": 1,
                    "claims": {"claims_repeat_array": found, "start": truth.get("start") if found else None,
                               "end": truth.get("end") if found else None},
                }
                (runs / f"{truth_path.stem}__{condition}__0.json").write_text(json.dumps(record))
        out = subprocess.run(
            [py, ROOT / "src" / "analyze.py", *opts],
            check=True, capture_output=True, text=True,
        ).stdout
        assert "| inline | 2/2 (100%" in out and "| file | 0/2 (0%" in out, out
        assert len((tmp / "r.csv").read_text().splitlines()) == 9
        assert "How the array was found" not in out  # no transcripts saved

        # with a transcript in which the agent writes the unit before any script
        (runs / "transcripts").mkdir()
        positive = next(p for p in sorted((tmp / "data/truth").glob("*.json")) if json.loads(p.read_text())["has_array"])
        unit = json.loads(positive.read_text())["unit"]
        transcript = [{"role": "assistant", "content": f"I see {unit} repeated"}]
        (runs / "transcripts" / f"{positive.stem}__inline__0.json").write_text(json.dumps(transcript))
        out = subprocess.run([py, ROOT / "src" / "analyze.py", *opts], check=True, capture_output=True, text=True).stdout
        assert "How the array was found (1 of 8 runs" in out and "| inline | 0/1 (0%" in out and "| 1/1 (100%" in out, out


def test_analysis_keeps_unscored_runs():
    """Empty and unjudged reports remain in CSV and in the effort denominators."""
    import csv

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        runs, truth = tmp / "runs", tmp / "truth"
        runs.mkdir()
        truth.mkdir()
        (truth / "region_001.json").write_text(json.dumps({"target": None, "annotated": []}))
        base = {
            "locus": "region_001", "condition": "file", "status": "end_turn",
            "tool_calls": [], "nt_run_from_tools": 0, "input_tokens": 10, "output_tokens": 5,
        }
        cases = [
            {"report": "An ordinary gene", "claims": {"features": [], "named_identity": []}, "forced_report": False},
            {"report": "", "forced_report": True, "status": "max_tokens"},
            {"report": "Awaiting judgement", "claims": None, "forced_report": True},
        ]
        for rep, case in enumerate(cases):
            (runs / f"region_001__file__{rep}.json").write_text(json.dumps({**base, **case, "rep": rep}))
        result = subprocess.run(
            [sys.executable, ROOT / "src" / "analyze.py", "--runs", runs, "--truth", truth],
            check=True, capture_output=True, text=True,
        ).stdout
        rows = list(csv.DictReader((runs / "results.csv").open()))
        assert len(rows) == 3 and [r["scored"] for r in rows] == ["True", "False", "False"]
        assert rows[1]["claimed"] == rows[1]["localized"] == rows[1]["other_claims"] == ""
        assert "| 2/3 | 1 empty report, 1 no usable judgement |" in result, result
        assert "not proof that the claim is false" in result


def test_transcript_failures_and_identity_labels():
    assert transcripts.python_error_outputs([
        {"role": "tool", "content": "\n[stderr]\nTraceback (most recent call last):\nValueError: bad"},
        {"role": "tool", "content": "\n[stderr]\nSyntaxError: unmatched ')'"},
        {"role": "tool", "content": "\n[stderr]\nUserWarning: a warning"},
        {"role": "tool", "content": "error: script exceeded 30s"},
        {"role": "assistant", "content": "ValueError: I saw an earlier failure"},
    ]) == 3
    assert transcripts.python_error_outputs([
        {"role": "user", "content": [{"type": "tool_result", "content": "NameError: seq"}]},
    ]) == 1
    assert analyze.named_identities({"named_identity": [
        "region_001", "region.fasta", "ORF1", "gene A", "G3p", "OrfE", "prfB", "TyrRS", "Escherichia coli",
    ]}) == ["prfB", "TyrRS", "Escherichia coli"]


def test_exploratory_gene_coordinates():
    """Reverse-complement and edge clipping must preserve the scoring intervals."""
    from explore_ecoli import local_cds, matches

    truth = {"length": 300, "source": {"start": 1001, "end": 1300, "strand": "-"},
             "annotated": [{"key": "gene", "name": "middle", "start": 51, "end": 250, "pseudo": False},
                           {"key": "gene", "name": "edge", "start": 151, "end": 300, "pseudo": False}]}
    features = [
        {"key": "CDS", "start": 1051, "end": 1250, "strand": "+", "quals": {}},
        {"key": "CDS", "start": 900, "end": 1150, "strand": "-", "quals": {}},
        {"key": "CDS", "start": 1051, "end": 1250, "strand": "+", "quals": {"pseudo": ""}},
        {"key": "CDS", "start": 1201, "end": 1300, "strand": "+", "quals": {}},
    ]
    genes = local_cds(truth, features)
    assert [(g["name"], g["start"], g["end"], g["strand"], g["clipped"]) for g in genes] == [
        ("middle", 51, 250, "-", False), ("edge", 151, 300, "+", True),
    ]
    gene = {"start": 101, "end": 200}
    assert matches({"start": 200, "end": 101}, gene, .8)
    assert not matches({"start": 1, "end": 1000}, gene, .8)
    assert not matches({"start": 130, "end": 229}, gene, .8)
    assert matches({"start": 130, "end": 229}, gene, .5)
    assert not matches({"start": None, "end": 200}, gene, .8)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
