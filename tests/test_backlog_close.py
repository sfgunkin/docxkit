"""`tools/backlog_close.py` — the move every session hand-rolled.

Three copies in two days (`close_entry.py`, `close_s1.py`,
`close_entries.py`), one of which wrote CRLF. What is pinned here is what
a hand-rolled move gets wrong: the entry's end (the 2026-08-24 helper cut
"to the next `### `" and carried `## Fixed` along), the status gate on
the RESULT, and bytes that stay LF.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import backlog_close as bc  # noqa: E402  # pyright: ignore[reportMissingImports]

BACKLOG = """# docxkit backlog

## Open

### S2 — the first thing
<!-- status: open -->

Body of the first.

### S4 — the second thing
<!-- status: open -->

Body of the second.

### ~~S1 — a retraction~~ — RETRACTED 04.09
<!-- status: withdrawn -->

Kept on purpose.

## Where the fixed entries are

A pointer.
"""

ARCHIVE = """# archive

## Fixed

### ~~S3 — older~~ — FIXED 01.09, `abc1234`

<!-- status: fixed -->

Old body.
"""


def test_the_entry_moves_to_the_TOP_of_Fixed_struck_and_stamped():
    backlog, archive = bc.close(BACKLOG, ARCHIVE, "S4 — the second",
                                commit="def5678", note="**Fixed.**",
                                stamp="FIXED 25.09")

    assert "the second thing" not in backlog
    assert "S2 — the first thing" in backlog
    head = archive.index("## Fixed\n") + len("## Fixed\n\n")
    assert archive[head:].startswith(
        "### ~~S4 — the second thing~~ — FIXED 25.09, `def5678`\n\n"
        "<!-- status: fixed -->\n\nBody of the second.\n\n**Fixed.**\n")
    assert archive.index("the second thing") < archive.index("older")


def test_the_LAST_open_entry_stops_at_the_next_SECTION():
    """The 2026-08-24 incident: cut to the next `### ` and the section
    heading between goes with the entry."""
    retraction_first = BACKLOG.replace(
        "### ~~S1 — a retraction~~ — RETRACTED 04.09\n"
        "<!-- status: withdrawn -->\n\nKept on purpose.\n\n", "")

    backlog, archive = bc.close(retraction_first, ARCHIVE, "S4",
                                commit="def5678", note="n", stamp="FIXED")

    assert "## Where the fixed entries are" in backlog
    assert "Where the fixed" not in archive


@pytest.mark.parametrize("heading, said", [
    ("S", "2 entries"),
    ("S9 — nothing", "0 entries"),
])
def test_it_needs_EXACTLY_one_entry(heading, said):
    with pytest.raises(bc.CloseError, match=said):
        bc.close(BACKLOG, ARCHIVE, heading, commit="x", note="n",
                 stamp="FIXED")


def test_only_an_OPEN_entry_is_closed():
    with pytest.raises(bc.CloseError, match="not `open`"):
        bc.close(BACKLOG, ARCHIVE, "~~S1 — a retraction", commit="x",
                 note="n", stamp="FIXED")


def test_main_writes_LF_and_refuses_an_unknown_commit(tmp_path,
                                                      monkeypatch):
    (tmp_path / "BACKLOG.md").write_bytes(BACKLOG.encode())
    (tmp_path / "BACKLOG-ARCHIVE.md").write_bytes(ARCHIVE.encode())

    monkeypatch.setattr(bc, "_commit_exists", lambda root, c: False)
    assert bc.main(["S2", "--commit", "nope", "--note", "n"],
                   root=tmp_path) == 2
    assert (tmp_path / "BACKLOG.md").read_bytes() == BACKLOG.encode()

    monkeypatch.setattr(bc, "_commit_exists", lambda root, c: True)
    assert bc.main(["S2", "--commit", "abc", "--note", "n", "--dry-run"],
                   root=tmp_path) == 0
    assert (tmp_path / "BACKLOG.md").read_bytes() == BACKLOG.encode()

    assert bc.main(["S2", "--commit", "abc", "--note", "done"],
                   root=tmp_path) == 0
    written = (tmp_path / "BACKLOG-ARCHIVE.md").read_bytes()
    assert b"\r" not in written and b"S2 \xe2\x80\x94 the first" in written
    assert b"first thing" not in (tmp_path / "BACKLOG.md").read_bytes()
