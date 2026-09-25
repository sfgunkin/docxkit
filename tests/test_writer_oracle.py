"""`tools/writer_oracle.py` — the writers' old-vs-new oracle.

Its first run found a regression committed the same hour (e08262a grew
a run in an EQUATION cell and printed the formula again as prose), which
is the argument for it. What is pinned here: the two probes answer what
they claim on shapes that broke, the diff is key by key, and the
end-to-end run compares a real base against the working tree.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from conftest import document, para, run

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import writer_oracle as wo  # noqa: E402  # pyright: ignore[reportMissingImports]


def _table(*cells: str) -> str:
    tcs = "".join(f"<w:tc>{c}</w:tc>" for c in cells)
    return (para(run("Table 1. Estimates"))
            + f"<w:tbl><w:tr>{tcs}</w:tr></w:tbl>")


def test_set_cell_probe_answers_each_cells_runs():
    sup = ('<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
           "<w:t>**</w:t></w:r>")
    xml = document(_table(para(run("0.012"), sup), para(run("Age"))))

    answers = wo.probe_set_cell(xml)

    assert answers == {
        "table 0 row 0 cell 0": '[[["0.012", false, false], '
                                '["**", true, false]]]',
        "table 0 row 0 cell 1": '[[["Age", false, false]]]'}


def test_insert_before_probe_names_what_is_STRANDED():
    """A collapsed head pair before an entry — kept by today's writer,
    which is the answer a regression would change."""
    xml = document(para(run("Allen (2001). A first entry."))
                   + '<w:bookmarkStart w:id="5" w:name="Baker2002"/>'
                   '<w:bookmarkEnd w:id="5"/>'
                   + para(run("Baker (2002). A second entry.")))

    assert wo.probe_insert_before(xml) == {
        "before 'Baker (2002). A second entry.'": "kept"}


def test_diff_is_key_by_key_and_sees_a_key_on_one_side_only():
    base = {"a.docx": {"set_cell": {"k1": "x", "k2": "y"}}}
    head = {"a.docx": {"set_cell": {"k1": "x", "k2": "z", "k3": "w"}}}

    assert wo.diff(base, head) == {"set_cell": [
        ("a.docx", "k2", "y", "z"), ("a.docx", "k3", None, "w")]}


def test_no_corpus_is_SKIPPED(monkeypatch):
    monkeypatch.delenv("DOCXKIT_CORPUS", raising=False)

    assert wo.main([]) == wo.SKIPPED


def test_end_to_end_against_HEAD_on_a_tiny_corpus(tmp_path, capsys):
    """git archive + two interpreters: the working tree against HEAD. A
    corpus of one document the two sides answer alike."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    with zipfile.ZipFile(corpus / "m.docx", "w") as z:
        z.writestr("word/document.xml",
                   document(_table(para(run("0.5")), para(run("Age")))))

    code = wo.main([str(corpus), "--base", "HEAD", "--expect-same"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "set_cell: 2 answers, 0 differ" in out
