r"""No raw control character anywhere in the tree — the heredoc's damage.

The agent harness's shell layer halves the backslashes in a `python -
<<'PY'` heredoc, so a patch script written the obvious way arrives with
`\\n` as `\n` and — the quiet half — `\b` as U+0008 BACKSPACE. That is
invisible in grep, in a diff and in a terminal: a regex written
`w:footnoteReference\b[^>]*` landed in `_xml.py` as
`w:footnoteReference<BS>[^>]*`, which also matches
`<w:footnoteReferenceX`, and sat there committed and green (backlog S3,
2026-08-20/21).

ruff is a backstop for three of the four places it can land — PLE2510
fires on a stray control character in a raw string, a plain string, an
f-string and a docstring alike. It does not fire on a COMMENT, and
nothing lints `.md` at all, which is exactly where the two that got
through that session landed. So the sweep the backlog entry recommends
running after a heredoc session is a gate instead: it costs
milliseconds, and "remember to run the sweep" is not a gate.

Tab, newline and carriage return are the three a text file legitimately
holds. Everything else below U+0020 (and DEL) is damage — no source file
here has ever wanted one, and a test fixture that needs `\x00` writes
the ESCAPE, which is four ordinary characters in the file.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: everything below U+0020 except tab, newline and carriage return, and DEL
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SKIP = {".git", "__pycache__", ".venv", "venv", ".mypy_cache",
        ".ruff_cache", ".pytest_cache", "build", "dist", ".eggs"}
SUFFIXES = {".py", ".md", ".toml", ".cfg", ".yml", ".yaml"}

SOURCES = sorted(
    p for p in ROOT.rglob("*")
    if p.is_file() and p.suffix in SUFFIXES
    and not SKIP & set(p.relative_to(ROOT).parts))


def test_the_sweep_finds_files_to_read():
    """A path bug that skips everything passes the test below silently —
    which is the shape of failure this whole file exists to refuse."""
    assert len(SOURCES) > 50
    assert any(p.suffix == ".md" for p in SOURCES)
    assert any(p.name == "_xml.py" for p in SOURCES)


def test_the_pattern_catches_what_the_heredoc_makes():
    """The gate has nothing to find in a clean tree, so the only proof
    it can still fail is the pattern itself. chr(8) is what `\\b`
    becomes; chr(92) + "b" is what it should have stayed."""
    assert CONTROL_RE.search("w:footnoteReference" + chr(8) + "[^>]*")
    assert CONTROL_RE.search(chr(127))
    assert not CONTROL_RE.search("w:footnoteReference" + chr(92) + "b")
    assert not CONTROL_RE.search("tab\tnewline\r\n")


def test_no_raw_control_character():
    """One test over the whole tree, and it reports EVERY hit.

    Not one case per file: a sweep that stops at the first answer sends
    its reader round the loop once per character, and these arrive in
    batches — one heredoc session damaged two files.
    """
    hits: list[str] = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        for m in CONTROL_RE.finditer(text):
            ch, at = m.group(0), m.start()
            hits.append(
                f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, at) + 1}"
                f" holds a raw {unicodedata.name(ch, '')} "
                f"(U+{ord(ch):04X}) in {text[max(0, at - 40):at + 40]!r}")
    assert not hits, (
        "a backslash escape was eaten on its way through a heredoc — "
        "write the payload with the Write tool, or compose the backslash "
        "(B = chr(92)):\n" + "\n".join(hits))
