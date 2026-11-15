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


def _package(body: str) -> dict[str, bytes]:
    return {"word/document.xml": document(body).encode("utf-8")}


_ITALIC_TABLE = (
    para(run("Table 1. Estimates"))
    + "<w:tbl><w:tr><w:tc><w:p><w:pPr><w:jc w:val=\"right\"/></w:pPr>"
    "<w:r><w:rPr><w:i/></w:rPr><w:t>Pupils</w:t></w:r></w:p></w:tc>"
    "</w:tr></w:tbl>")


def test_house_probe_counts_what_the_pass_must_keep():
    answers = wo.probe_house(_package(_ITALIC_TABLE))

    (key, answer), = answers.items()
    assert key == "table 0"
    assert answer.startswith(
        "text same; italic 1->1 bold 0->1 jc 1->1 keepNext 0->0 "
        "vertAlign 0->0; sha "), answer      # row 0 is the header: bold


def test_crossrefs_probe_answers_per_caption_and_per_audit_bucket():
    body = (para(run("As Table 1 shows, it fell."))
            + para(run("Table 1. Estimates")))

    answers = wo.probe_crossrefs(_package(body))

    assert set(answers) == {"caption Table1"} | {
        f"audit {side} {b}" for side in ("before", "after")
        for b in wo._XREF_BUCKETS}
    assert answers["audit before unlinked"] == "1"
    assert answers["audit after linked"] == "1"
    assert answers["audit after misplaced_anchor"] == "0"


def test_link_all_probe_has_one_key_per_mention():
    body = (para(run("Lokshin (2026) shows it; Lokshin (2026) again."))
            + para(run("References"))
            + para(run("Lokshin, M. (2026). Inflows. Journal.")))

    answers = wo.probe_link_all(_package(body))

    assert answers.pop("body")
    assert answers == {
        "linked Lokshin2026 @ ¶1 (the first of 2 in the paragraph)": "yes",
        "back-linked Lokshin2026": "yes"}


def test_link_rest_probe_names_the_LATER_mention_it_links():
    body = (para(run("Lokshin (2026) shows it."))
            + para(run("Later, Lokshin (2026) again."))
            + para(run("References"))
            + para(run("Lokshin, M. (2026). Inflows. Journal.")))

    answers = wo.probe_link_rest(_package(body))

    assert answers.pop("body")
    assert answers == {"linked Lokshin2026 @ ¶2": "yes"}, answers


def test_link_more_probe_answers_both_ways_and_LINTS_the_result():
    """The default re-homes a marker and `rehome=False` holds it; the held
    run answers only where holding changed something, so a base without
    the switch is not a difference. The lint keys are where a link
    written inside a `w:ins` would show; here there is none."""
    ins = '<w:ins w:id="7" w:author="A" w:date="2026-11-01T00:00:00Z">'
    marked = ('<w:bookmarkStart w:id="5" w:name="Figure2txt"/>'
              '<w:hyperlink w:anchor="Figure2"><w:r><w:t>Figure 2</w:t>'
              '</w:r></w:hyperlink><w:bookmarkEnd w:id="5"/>')
    body = (para(run("Figure 2 shows it."))
            + para(ins + run("Intervening.") + "</w:ins>")
            + para(marked)
            + para('<w:bookmarkStart w:id="1" w:name="Figure2"/>'
                   '<w:bookmarkEnd w:id="1"/>'
                   + run("Figure 2. The framework")))

    answers = wo.probe_link_more(_package(body))

    assert answers.pop("body") and answers.pop("held body")
    assert answers == {"count Figure2": "1", "count Figure2txt moved": "1",
                       "held Figure2txt not moved: placed": "1"}, answers


def test_the_house_apply_probe_reads_the_IMAGES_the_figure_rule_needs(
        tmp_path):
    """Read as XML only, every picture's own size was unknown, so the
    probe skipped every figure on both sides and a broken resize printed
    "0 differ" (review, 2026-11-15). PNG and JPEG travel; an EMF, which
    nothing reads, does not."""
    import struct
    png = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
           + struct.pack(">II", 1500, 1000) + b"\x08\x02\x00\x00\x00")
    ns = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
          'wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/'
          'drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
          'officeDocument/2006/relationships"')
    cx, cy = 5 * 914400, round(3.33 * 914400)
    fig = (f'<w:p><w:r><w:drawing><wp:inline {ns}>'
           f'<wp:extent cx="{cx}" cy="{cy}"/><a:graphic><a:graphicData>'
           f'<a:blip r:embed="rId7"/><a:xfrm><a:ext cx="{cx}" cy="{cy}"/>'
           "</a:xfrm></a:graphicData></a:graphic></wp:inline></w:drawing>"
           "</w:r></w:p>")
    path = tmp_path / "fig.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document(fig))
        z.writestr("word/_rels/document.xml.rels",
                   '<Relationships><Relationship Id="rId7" Type="image" '
                   'Target="media/image1.png"/></Relationships>')
        z.writestr("word/media/image1.png", png)
        z.writestr("word/media/image2.emf", b"\x01\x00\x00\x00")

    parts = wo._read_package(str(path))

    assert "word/media/image1.png" in parts
    assert "word/media/image2.emf" not in parts
    assert wo.probe_house_apply(parts)["figures resized"] == "1"


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
    for probe in ("insert_before", "house", "crossrefs", "link_all"):
        assert f"  {probe}: " in out, out


def test_an_UNSET_limit_samples_forty_and_the_paths_travel_in_a_FILE(
        tmp_path, capsys, monkeypatch):
    """`get(LIMIT_ENV, "0") or 40` never reached the 40 ("0" is truthy),
    so the whole corpus went to the worker on its command line — 1,813
    paths, which Windows refused with WinError 206 before a probe ran."""
    monkeypatch.delenv("DOCXKIT_CORPUS_LIMIT", raising=False)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for k in range(45):
        with zipfile.ZipFile(corpus / f"m{k:02}.docx", "w") as z:
            z.writestr("word/document.xml", document(para(run("x"))))
    argvs: list[list[str]] = []
    real = wo.subprocess.run

    def spy(cmd, **kw):
        argvs.append(cmd)
        return real(cmd, **kw)
    monkeypatch.setattr(wo.subprocess, "run", spy)

    code = wo.main([str(corpus), "--probe", "set_cell"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith("40 of 45 documents"), out
    workers = [a for a in argvs if "--worker" in a]
    assert len(workers) == 2 and all(len(a) == 7 for a in workers), workers


#: The commit before e84596f: `tables.house` replaced cell properties
#: wholesale, and `link_all` skipped a citation repeated in its paragraph.
BEFORE_THE_FIXES = "c9b2081"


def test_the_oracle_SEES_the_writer_fixes_it_used_to_miss(tmp_path, capsys):
    """The case that filed the entry: a batch changed `house` and
    `link_all`, and this tool's two probes could not see either."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    with zipfile.ZipFile(corpus / "m.docx", "w") as z:
        z.writestr("word/document.xml", document(
            _ITALIC_TABLE
            + para(run("Lokshin (2026) shows it; Lokshin (2026) again."))
            + para(run("References"))
            + para(run("Lokshin, M. (2026). Inflows. Journal."))))

    code = wo.main([str(corpus), "--base", BEFORE_THE_FIXES,
                    "--probe", "house", "--probe", "link_all",
                    "--expect-same", "--show", "9"])

    out = capsys.readouterr().out
    assert code == 1, out
    assert "house: 1 answers, 1 differ" in out, out
    assert "italic 1->0" in out and "italic 1->1" in out, out
    assert "link_all:" in out and "0 differ" not in out.split(
        "link_all:")[1].splitlines()[0], out
