"""`tools/pair_oracle.py` — `compare`'s old-vs-new oracle over version pairs.

Filed as backlog S4 (2026-11-19): a change to a layer that compares TWO
documents could only be measured with scratch scripts. Pinned here: which
files pair, the stride, the multiset diff, the skip, and an end-to-end run
of the working tree against HEAD.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

from conftest import document, para, run

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import pair_oracle as po  # noqa: E402  # pyright: ignore[reportMissingImports]

NOTHING = re.compile(r"(?!)")


def _docx(path: Path, text: str, mtime: int) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document(para(run(text))))
    os.utime(path, (mtime, mtime))
    return path


def test_versions_pair_in_TIME_order_and_only_with_their_own_name(tmp_path):
    a = _docx(tmp_path / "Paper_0911.docx", "one", 3)
    b = _docx(tmp_path / "Paper_0915.docx", "two", 5)
    c = _docx(tmp_path / "Paper_0920.docx", "three", 7)
    _docx(tmp_path / "Letter to the editor.docx", "x", 4)
    _docx(tmp_path / "Paper_redline.docx", "y", 6)

    pairs = po.version_pairs([str(tmp_path)], skip=NOTHING)

    # the letter sits between them in time and breaks no pair; it pairs
    # with nothing, and the redline is not a version at all
    assert pairs == [(str(a), str(b)), (str(b), str(c))]


def test_stride_spreads_the_sample_and_keeps_a_short_list_whole():
    pairs = [(str(k), str(k + 1)) for k in range(10)]

    assert po.stride(pairs, 5) == pairs[::2]
    assert po.stride(pairs, 50) == pairs
    assert po.stride(pairs, 0) == pairs


def test_diff_is_a_MULTISET_per_pair_and_bucket():
    """One entry gained beside an identical one kept is one gained."""
    base = {"a -> b": {"format": ["x"], "text": ["t"]}}
    head = {"a -> b": {"format": ["x", "x", "y"], "text": []},
            "c -> d": "error: OSError: gone"}

    assert po.diff(base, head) == {
        "(error)": [("c -> d", ["error: OSError: gone"], ["{}"])],
        "format": [("a -> b", ["x", "y"], [])],
        "text": [("a -> b", [], ["t"])]}


def test_no_corpus_is_SKIPPED(monkeypatch):
    monkeypatch.delenv("DOCXKIT_CORPUS", raising=False)

    assert po.main([]) == po.SKIPPED


def test_end_to_end_against_HEAD_on_a_tiny_corpus(tmp_path, capsys):
    """git archive + two interpreters, the working tree against HEAD, on
    one pair the two sides compare alike."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _docx(corpus / "Paper_v1.docx", "The first version.", 3)
    _docx(corpus / "Paper_v2.docx", "The second version.", 5)

    code = po.main([str(corpus), "--base", "HEAD", "--expect-same",
                    "--jobs", "1"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith("1 of 1 version pairs"), out
    assert "no bucket differs" in out
