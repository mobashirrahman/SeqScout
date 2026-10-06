"""The agent's tools, plus the measurement of how much raw sequence it saw."""
import re

from isolation import IsolatedWorkspace

OUTPUT_CAP = 20_000
MIN_NT_RUN = 20  # shorter runs are mostly ordinary words such as "tag" or "cat"

TOOL_DEFS = [
    {
        "name": "list_files",
        "description": "List the supplied files and scratch directory with their sizes in bytes.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "read_file",
        "description": (
            "Read text from a file in the working directory. Returns up to `length` "
            "characters starting at character `offset`. Use it to look at file contents directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File name relative to the working directory."},
                "offset": {"type": "integer", "description": "0-based character offset. Default 0."},
                "length": {"type": "integer", "description": "Number of characters to return."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_python",
        "description": (
            "Run a Python 3 script in the working directory and return its stdout and stderr. "
            "Only Python's standard library and supplied inputs are available. Each call starts "
            "a fresh interpreter. Network sockets and subprocesses are blocked. Inputs are "
            "read-only; save any generated files under scratch/. Resource limits are enforced."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "The script source."}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
]

_NT_RUN = re.compile(r"(?:[ACGTN]+\n?)+", re.IGNORECASE)


def longest_nt_run(text):
    """Longest stretch of nucleotide letters in `text`, joined across line breaks."""
    longest = 0
    for m in _NT_RUN.finditer(text):
        n = len(m.group().replace("\n", ""))
        longest = max(longest, n)
    return longest if longest >= MIN_NT_RUN else 0


class Workspace(IsolatedWorkspace):
    """All agent tools execute under the configured Landlock/seccomp policy.

    Setup failures raise IsolationError. There is no unrestricted fallback.
    """


def read_fasta_sequence(text):
    return "".join(line.strip() for line in text.splitlines() if not line.startswith(">")).upper()


def seen_positions(text, seq):
    """0-based positions of `seq` shown in `text` as runs of at least MIN_NT_RUN bases.

    Sequence printed in short space-separated blocks is not counted. Neither is
    a fragment that occurs more than once in `seq` (a lone copy of a repeat
    unit, say), because there is no telling which occurrence was shown.
    """
    seen = set()
    for m in _NT_RUN.finditer(text):
        whole = m.group().replace("\n", "").upper()
        # A word ending in a/c/g/t just before the sequence would spoil the whole run,
        # so fall back to its separate lines.
        pieces = [whole] if whole in seq else m.group().upper().split("\n")
        for piece in pieces:
            if len(piece) < MIN_NT_RUN:
                continue
            at = seq.find(piece)
            if at != -1 and seq.find(piece, at + 1) == -1:
                seen.update(range(at, at + len(piece)))
    return seen


def to_intervals(positions):
    """Sorted 0-based positions as merged [start, end] pairs, 1-based inclusive."""
    intervals = []
    for pos in sorted(positions):
        if intervals and pos == intervals[-1][1]:
            intervals[-1][1] = pos + 1
        else:
            intervals.append([pos + 1, pos + 1])
    return intervals
