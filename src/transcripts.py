"""Read saved transcripts: what the agent wrote, what its scripts did, when it noticed the array.

Everything here is computed after the fact from files on disk, so the rules
can be changed without rerunning any agent.
"""
import json
import re
from collections import Counter

QUOTE_K = 12  # an agent has "written part of the unit" once it writes this many matching bases

# Keyword rules, deliberately crude. They tag what a script looks for, not whether it worked.
SCRIPT_KINDS = {
    "repeat": r"repeat|tandem|k-?mer|period|dot.?plot|self.?compar|autocorr|satellite",
    "composition": r"\bgc\b|gc_|composition|skew|dinuc",
    "orf": r"orf|codon|translat|stop",
    "motif": r"motif|promoter|tata|shine|restriction|palindrom|hairpin|inverted",
}


def script_kinds(code):
    kinds = sorted(k for k, pattern in SCRIPT_KINDS.items() if re.search(pattern, code, re.IGNORECASE))
    return kinds or ["other"]


def python_error_outputs(transcript):
    """Count tool outputs with Python failure diagnostics, which old run records omitted.

    This is a transcript heuristic: subprocess exit codes were not saved.
    Merely writing to stderr (e.g. a warning) does not count.
    """
    outputs = []
    for message in transcript:
        if message.get("role") == "tool":
            outputs.append(message.get("content") or "")
        if isinstance(message.get("content"), list):
            outputs.extend(block.get("content") or "" for block in message["content"] if block.get("type") == "tool_result")
    diagnostic = r"(?m)^(?:Traceback \(most recent call last\):|\w*(?:Error|Exception):|error: script exceeded \d+s)"
    return sum(bool(re.search(diagnostic, output)) for output in outputs if isinstance(output, str))


def assistant_turns(transcript):
    """One entry per assistant message: everything it wrote, and the scripts it asked to run."""
    turns = []
    for m in transcript:
        if m.get("role") != "assistant":
            continue
        texts, scripts = [], []
        content = m.get("content")
        if isinstance(content, str):
            texts.append(content)
        for block in content if isinstance(content, list) else []:  # Anthropic content blocks
            if block.get("type") == "text":
                texts.append(block.get("text") or "")
            elif block.get("type") == "thinking":
                texts.append(block.get("thinking") or "")
            elif block.get("type") == "tool_use" and (block.get("input") or {}).get("code"):
                scripts.append(block["input"]["code"])
        for key in ("reasoning_content", "reasoning"):  # OpenAI-compatible providers
            if isinstance(m.get(key), str):
                texts.append(m[key])
        for call in m.get("tool_calls") or []:
            try:
                args = json.loads(call["function"]["arguments"])
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(args, dict) and args.get("code"):
                scripts.append(args["code"])
        turns.append({"text": "\n".join(texts), "scripts": scripts})
    return turns


def repeat_kmers(array, k=QUOTE_K):
    """k-mers that occur at least twice in the planted array, i.e. that come from the repeated unit."""
    counts = Counter(array[i : i + k] for i in range(len(array) - k + 1))
    return {kmer for kmer, n in counts.items() if n >= 2}


def _quotes(text, kmers, k=QUOTE_K):
    for token in re.findall(rf"[ACGT]{{{k},}}", text.upper()):
        if any(token[i : i + k] in kmers for i in range(len(token) - k + 1)):
            return True
    return False


def first_notice(turns, kmers):
    """When the agent first wrote part of the repeated unit, and by which route.

    Returns (turn index, by_reading). by_reading is True when no repeat-search
    script had returned before that turn, so the agent can only have got the
    unit from looking at sequence. Returns (None, None) if it never wrote it.
    """
    repeat_script_returned = False
    for i, turn in enumerate(turns):
        if _quotes(turn["text"] + "\n" + "\n".join(turn["scripts"]), kmers):
            return i, not repeat_script_returned
        if any("repeat" in script_kinds(s) for s in turn["scripts"]):
            repeat_script_returned = True
    return None, None
