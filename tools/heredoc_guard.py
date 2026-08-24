#!/usr/bin/env python
r"""Refuse a shell heredoc whose body contains a backslash.

A `PreToolUse` hook for the Bash tool. Reads the tool call on stdin as
JSON and exits 2 — the blocking status — when the command carries a
heredoc whose BODY has a backslash in it.

**Why a gate rather than a rule.** The rule has been written down three
times and walked into seven. The backlog entry this closes records six
occurrences across two agents sharing one tree; the seventh happened
while reading that entry, and put a no-op `out.replace("\\n", " ")` into
a committed test.

**What actually happens, measured 2026-08-24 rather than inherited.**
The heredoc was `<<'PY'` — POSIX-QUOTED, which is specified to pass its
body through untouched — and it did not:

    written      Python received
    \\n          a newline
    \\\\         one backslash
    \t           a TAB          (unchanged)
    \\t          a TAB

So the transformation is precise: **a doubled backslash is halved; a
single `\x` passes through.** That is unquoted-heredoc behaviour applied
to a quoted one, so the quoting is being lost before the shell sees it,
and no amount of quoting inside the heredoc can help.

It also explains why the trap is so hard to learn from: `"\n"` in a
payload is fine, and `"\\n"` — the spelling you reach for the moment you
want a LITERAL backslash-n, which is exactly when a patch script is
rewriting escapes — is silently wrong. The failure is invisible when the
mangled search string happens to match nothing, which is how the seventh
one shipped.

Single backslashes are refused too. The rule the entry settles on is
about the payload and not about care: there is no safe way to put a
backslash through this path, and a guard that permits the "safe" half is
a guard nobody can remember the shape of.

**Windows paths are not heredoc bodies.** `python "C:\Users\..."` is the
most common command in this environment and must not be blocked, so only
text between a heredoc's delimiters is examined.
"""
from __future__ import annotations

import json
import re
import sys

#: `<<` or `<<-`, then an optionally quoted delimiter word. `<<-` strips
#: leading TABS from the body, which changes nothing here: the body is
#: still delivered through the same mangling path.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

#: ASCII on purpose. This writes to stderr through whatever pipe the
#: harness gives it, and a cp1252 console cannot encode an em dash: the
#: refusal would then be a UnicodeEncodeError traceback instead of a
#: sentence, on the one code path whose whole job is to be readable.
#: The same trap is recorded for `cosmic-ray` and for `gates.py`.
REFUSAL = """A heredoc body must not contain a backslash.

Measured: `<<'DELIM'` is POSIX-quoted and STILL halves doubled
backslashes on this path (\\\\n arrives as a newline, \\\\\\\\ as one
backslash). Seven occurrences, one of which rewrote 387 real newlines in
a file a second session was editing.

Write the payload with the Write tool and execute the file, or use an
Edit call for a few lines. Neither touches the shell."""


def bodies(command: str) -> list[str]:
    """The text between each heredoc's delimiters.

    A command can carry several, and a delimiter ENDS at a line that is
    the word alone — `PY` closes, `PYTHON` does not, and neither does a
    `PY` with anything after it.
    """
    out: list[str] = []
    lines = command.splitlines()
    i = 0
    while i < len(lines):
        found = _HEREDOC.search(lines[i])
        if not found:
            i += 1
            continue
        delimiter = found.group(2)
        body: list[str] = []
        i += 1
        while i < len(lines) and lines[i].strip() != delimiter:
            body.append(lines[i])
            i += 1
        i += 1                       # step over the closing delimiter
        out.append("\n".join(body))
    return out


def offending(command: str) -> str | None:
    """The first heredoc body carrying a backslash, or None."""
    return next((b for b in bodies(command) if "\\" in b), None)


def main() -> int:
    try:
        call = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0                     # not something to judge; stay out
    if call.get("tool_name") != "Bash":
        return 0
    command = call.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return 0

    body = offending(command)
    if body is None:
        return 0

    line = next((ln for ln in body.splitlines() if "\\" in ln), "")
    said = f"{REFUSAL}\n\nThe backslash is here:\n    {line.strip()[:120]}"
    # The offending LINE is the caller's text and can be anything at
    # all, so the ascii() fallback covers the case the ASCII refusal
    # above cannot: a payload that is itself non-encodable.
    try:
        print(said, file=sys.stderr)
    except UnicodeEncodeError:
        print(ascii(said), file=sys.stderr)
    return 2                         # PreToolUse: block, and tell the model


if __name__ == "__main__":
    raise SystemExit(main())
