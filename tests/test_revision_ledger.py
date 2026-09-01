r"""The round's record — written this release, read the next.

`revision`'s state is inferred from artifacts: which files are in
`build/` and what they hash to. Two of the last three S2 defects were
inference bugs of that shape — `verdict` could not tell a batch the
author REJECTED from one never promoted (both leave the manuscript
identical, `39fe472`), and `build` is silent on a pending working file
because "adjudication pending" and "clean" look the same from the files.

A record of the transitions is what neither could ask. But a reader that
trusted it TODAY would trust a ledger no paper has: nine manuscripts are
mid-round with nothing written, so every reader would meet an absent
record on its first real question. Hence the staging the 2026-09-01
review asked for — **write it for a release, read it in the next** — and
`test_nothing_READS_the_ledger_yet` below is what holds the promise.

That test is the interesting one. The rest pin the format so that a
reader written next release has something stable to read.
"""
from __future__ import annotations

import ast
import json
import pathlib
import shutil

import pytest
from conftest import make_parts, para, run, write

from docxkit import revision
from docxkit.revision import _ledger

SRC = pathlib.Path(revision.__file__).parent


def _paper(tmp_path):
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "src.docx",
                make_parts(para(run("The index rose."))))
    return revision.init(tmp_path / "proj", src, name="Test Paper",
                         author="Agent", attic=tmp_path / "attic")


def _lines(paper) -> list[dict[str, object]]:
    path = _ledger.ledger_path(paper)
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ------------------------------------------------- the staging promise


def test_nothing_READS_the_ledger_yet():
    """The whole of the staging, as a test rather than a comment.

    A ledger is only worth reading once real rounds have written one,
    and today none has. So the three writers may import it and nothing
    else may — and when a reader IS written next release, this test is
    what it has to argue with, deliberately, rather than a promise
    nobody remembers making.
    """
    writers = {"_build.py", "_promote.py", "_baseline.py", "_ledger.py"}
    readers = []
    for path in sorted(SRC.glob("*.py")):
        if path.name in writers:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            # `from ._ledger import x` and `from . import _ledger`
            names = {a.name for a in node.names}
            if node.module == "_ledger" or (node.level and "_ledger" in names):
                readers.append(path.name)

    assert not readers, (
        f"{sorted(set(readers))} imports the ledger, which nothing may "
        f"read until a release of real rounds has written one — see this "
        f"file's docstring before deleting this test")


def test_the_facade_does_not_export_it_either():
    """`revision/__init__.py` re-exports all 93 names behind it. The
    ledger stays off that list while it is write-only: an exported name
    is a name a paper can call, and a paper calling a reader that does
    not exist yet is the failure this staging is avoiding."""
    assert "_ledger" not in revision.__all__
    assert "record" not in revision.__all__


# --------------------------------------------------------- the writers


def test_a_promote_records_that_the_batch_REACHED_the_manuscript(tmp_path):
    """The event the whole ledger exists for. `verdict` infers this
    today from the redline copy `promote` happens to keep."""
    paper = _paper(tmp_path)
    write(paper.batch, make_parts(para(run("The index rose to 0.37."))))
    # `promote` refuses unless the live file still matches the baseline
    # the batch was built on — a byte copy is what that means.
    shutil.copyfile(paper.working, paper.prev)

    revision.promote(paper)

    (entry,) = [ln for ln in _lines(paper) if ln["event"] == "promoted"]
    assert entry["batch"] == "batch.docx"
    assert entry["batch_sha256"] and entry["base_sha256"]
    assert str(entry["redline"]).endswith(".docx")
    assert str(entry["at"]).startswith("20")


def test_a_baseline_records_the_verdict_it_wrote_to_the_log(tmp_path):
    paper = _paper(tmp_path)

    revision.baseline(paper, note="R1")

    (entry,) = [ln for ln in _lines(paper) if ln["event"] == "baselined"]
    assert entry["note"] == "R1"
    assert entry["truth_sha256"]
    assert "outcome" in entry, "the sentence log.md got, beside its inputs"


def test_every_event_is_APPENDED_and_none_rewritten(tmp_path):
    """One line per event, in the order they happened. A ledger that
    rewrote would be a second thing to trust, and the reason to have one
    is that the files already disagree with each other."""
    paper = _paper(tmp_path)

    revision.baseline(paper, note="one")
    revision.baseline(paper, note="two")

    notes = [ln.get("note") for ln in _lines(paper)]
    assert notes == ["one", "two"]


def test_it_lives_under_build_with_the_rest_of_the_machinery(tmp_path):
    paper = _paper(tmp_path)
    revision.baseline(paper)

    assert _ledger.ledger_path(paper).parent == paper.build_dir
    assert _ledger.ledger_path(paper).name == "ledger.jsonl"


# ---------------------------------------------------------- the format


def test_an_event_it_does_not_know_is_refused(tmp_path):
    """The vocabulary is three words and a writer cannot mint a fourth
    by misspelling one — a reader next release has to be able to switch
    on the set."""
    paper = _paper(tmp_path)

    with pytest.raises(ValueError, match="not a ledger event"):
        _ledger.record(paper, "promotedd")


def test_a_file_that_is_not_there_records_as_null_not_a_refusal(tmp_path):
    """A hash for a file that does not exist is `null`. Refusing would
    make the ledger fragile exactly where the protocol is: half these
    events happen while a file is being replaced."""
    paper = _paper(tmp_path)

    assert _ledger.sha256_of(paper.build_dir / "nope.docx") is None

    _ledger.record(paper, _ledger.BUILT, batch_sha256=None)
    assert _lines(paper)[-1]["batch_sha256"] is None


def test_the_lines_are_json_one_per_line(tmp_path):
    """`.jsonl`, so a half-written last line costs one event and not the
    file — the same reason `log.md` is appended to rather than parsed
    and rewritten."""
    paper = _paper(tmp_path)
    _ledger.record(paper, _ledger.BUILT, batch="a.docx")
    _ledger.record(paper, _ledger.PROMOTED, batch="a.docx")

    text = _ledger.ledger_path(paper).read_text(encoding="utf-8")

    assert text.count("\n") == 2
    for line in text.splitlines():
        assert json.loads(line)["event"] in ("built", "promoted")
