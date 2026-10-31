"""`tools/view_oracle.py` — the accept/reject views' old-vs-new oracle.

It exists because a hand-rolled probe measured nothing: `_simulate_clean`
is cached on the XML, so a monkeypatched re-run was served the unpatched
view (2026-10-31). What is pinned here: the profile Word is compared on
counts what it claims, the diff and the verdict are key by key, and the
end-to-end run compares a real base against the working tree in their
own interpreters.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from conftest import document, para, run

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import view_oracle as vo  # noqa: E402  # pyright: ignore[reportMissingImports]


def _mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def _math(*inner: str) -> str:
    return (f'<w:p xmlns:m="http://schemas.openxmlformats.org/officeDocument'
            f'/2006/math"><m:oMath>{"".join(inner)}</m:oMath></w:p>')


def test_profile_counts_objects_SHELLS_glyphs_and_bookmarks():
    """Three fractions, one of them empty; five delimiters, two empty."""
    full_f = f"<m:f><m:num>{_mr('a')}</m:num><m:den>{_mr('b')}</m:den></m:f>"
    empty_f = "<m:f><m:num/><m:den/></m:f>"
    full_d = f"<m:d><m:e>{_mr('x')}</m:e></m:d>"
    empty_d = "<m:d><m:e><m:r><m:t/></m:r></m:e></m:d>"
    xml = document(
        '<w:bookmarkStart w:id="1" w:name="eq1"/>'
        + _math(full_f, full_f, empty_f) + '<w:bookmarkEnd w:id="1"/>'
        + _math(full_d, full_d, full_d, empty_d, empty_d)
        + para(run("Prose.")))

    got = vo.profile_xml(xml)

    assert got["objects"] == {"d": 5, "f": 3, "oMath": 2}
    assert got["shells"] == {"d": 2, "f": 1, "r": 2}   # runs: shells only
    assert got["equations"] == "ababxxx"
    assert got["bookmarks"] == ["eq1"]
    assert got["text"] == vo.profile_xml(
        document(para(run("Prose."))))["text"]


def test_diff_is_view_by_view_and_sees_a_view_on_one_side_only():
    base = {"a.docx": {"p|accept": ["1", None], "p|reject": ["2", None]}}
    head = {"a.docx": {"p|accept": ["1", None], "p|reject": ["3", None],
                       "q|accept": ["4", None]}}

    assert vo.diff(base, head) == [("a.docx", "p|reject"),
                                   ("a.docx", "q|accept")]


def test_judge_names_the_side_word_agrees_with_per_field():
    word = {"objects": {"f": 3}, "shells": {"d": 5}, "text": "t"}
    base = {"objects": {"f": 7}, "shells": {"d": 5}, "text": "u"}
    head = {"objects": {"f": 3}, "shells": {}, "text": "v"}

    assert vo.judge(base, head, word) == {
        "objects": "head", "shells": "base", "text": "neither"}
    assert vo.judge(word, word, word) == dict.fromkeys(word, "both")


def test_no_corpus_is_SKIPPED(monkeypatch):
    monkeypatch.delenv("DOCXKIT_CORPUS", raising=False)

    assert vo.main([]) == vo.SKIPPED


def test_end_to_end_against_HEAD_on_a_tiny_corpus(tmp_path, capsys):
    """git archive + two interpreters: the working tree against HEAD.
    Three redlines, one an exact copy, and a document with no revision
    at all: two redlines, four views each side, none differ."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, body in (
            ("a.docx", para('<w:ins w:id="1" w:author="A">'
                            + run("new") + "</w:ins>" + run(" old"))),
            ("b.docx", para('<w:del w:id="2" w:author="B">'
                            '<w:r><w:delText>gone</w:delText></w:r></w:del>'
                            + run(" kept"))),
            ("c.docx", para(run("no revision")))):
        with zipfile.ZipFile(corpus / name, "w") as z:
            z.writestr("word/document.xml", document(body))
    (corpus / "copy.docx").write_bytes((corpus / "a.docx").read_bytes())

    code = vo.main([str(corpus), "--base", "HEAD", "--expect-same"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "2 redlines of 3 distinct documents, 4 views" in out
    assert "reject: 0 views differ" in out
