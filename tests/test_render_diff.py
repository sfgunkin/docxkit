"""`pages.compare_renders` / `docxkit render-diff` — two renders, sheet
by sheet.

The missing half of "verify a rebuild that should change nothing": on
2026-11-09 `compare` reported no difference on any layer for a change
that kept a theme `tblStyle` the old build removed, because it does not
read table properties, and only a render could say whether a page moved.
That took a hand-rolled 20-line PyMuPDF script (BACKLOG S4).

The PDFs here are drawn with PyMuPDF, so no Word is needed; the one test
through Word is marked `word`.
"""
from __future__ import annotations

import pytest

from docxkit.cli import main
from docxkit.pages import compare_renders

pymupdf = pytest.importorskip("pymupdf",
                              reason="the render layer needs docxkit[pdf]")


def _pdf(tmp_path, name: str, *sheets: str):
    """One sheet per string, its text at the same place on each."""
    doc = pymupdf.open()
    for body in sheets:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 200), body, fontsize=11)
    out = tmp_path / name
    doc.save(str(out))
    doc.close()
    return out


SHEETS: tuple[str, ...] = ("The first sheet.", "The second sheet.",
                           "The third sheet.", "The fourth sheet.",
                           "The fifth sheet.")


def test_identical_renders_are_SAME(tmp_path):
    a = _pdf(tmp_path, "a.pdf", *SHEETS)
    b = _pdf(tmp_path, "b.pdf", *SHEETS)

    diff = compare_renders(a, b)

    assert diff.same and diff.differing == [] and diff.pages_a == 5
    assert diff.format() == "SAME: 5 sheet(s), every one identical"


def test_the_sheets_that_MOVED_are_named_and_written_both_sides(tmp_path):
    """Sheets 2 and 4 of 5 change; 1, 3 and 5 do not."""
    moved = list(SHEETS)
    moved[1] = "The second sheet, rewrapped."
    moved[3] = "The fourth sheet moved down a line."
    a = _pdf(tmp_path, "a.pdf", *SHEETS)
    b = _pdf(tmp_path, "b.pdf", *moved)

    diff = compare_renders(a, b, out=tmp_path / "diff")

    assert not diff.same
    assert diff.differing == [2, 4]
    assert all(0 < diff.share[n] < 1 for n in (2, 4))
    assert sorted(p.name for p in diff.images) == [
        "sheet-002-a.png", "sheet-002-b.png",
        "sheet-004-a.png", "sheet-004-b.png"]
    assert all(p.is_file() for p in diff.images)
    assert "2 sheet(s) differ" in diff.format()


def test_a_sheet_GAINED_is_a_difference_even_when_every_shared_one_matches(
        tmp_path):
    a = _pdf(tmp_path, "a.pdf", *SHEETS[:3])
    b = _pdf(tmp_path, "b.pdf", *SHEETS[:3], "A caption spilled over.")

    diff = compare_renders(a, b)

    assert not diff.same and diff.differing == []
    assert "DIFFERENT sheet counts: 3 -> 4" in diff.format()


def test_the_command_exits_0_only_when_every_sheet_matches(
        tmp_path, monkeypatch, capsys):
    a = _pdf(tmp_path, "a.pdf", *SHEETS)
    same = _pdf(tmp_path, "same.pdf", *SHEETS)
    other = _pdf(tmp_path, "other.pdf", *SHEETS[:4], "Changed.")

    def run(*argv: str) -> int:
        monkeypatch.setattr("sys.argv", ["docxkit", *argv])
        try:
            main()
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0

    assert run("render-diff", str(a), str(same), "--pdfs") == 0
    assert run("render-diff", str(a), str(other), "--pdfs") == 1
    assert "sheet 5:" in capsys.readouterr().out


def test_without_PDFS_the_command_renders_both_through_Word(
        tmp_path, monkeypatch, capsys):
    """The ordinary form: two .docx, each rendered, then compared. Word
    is stubbed here; the test below is the real render."""
    from docxkit import pages
    from docxkit.pages import RenderDiff

    seen: list[tuple[str, str, int]] = []

    def fake(a, b, *, dpi, out):
        seen.append((a, b, dpi))
        return RenderDiff(3, 4)
    monkeypatch.setattr(pages, "render_diff", fake)
    monkeypatch.setattr("sys.argv", ["docxkit", "render-diff", "a.docx",
                                     "b.docx", "--dpi", "72"])
    with pytest.raises(SystemExit) as stopped:
        main()

    assert stopped.value.code == 1
    assert seen == [("a.docx", "b.docx", 72)]
    assert "DIFFERENT sheet counts: 3 -> 4" in capsys.readouterr().out


@pytest.mark.word
def test_WORD_renders_a_document_against_itself_as_SAME(tmp_path):
    """Through Word, both sides the same file: the determinism the
    comparison stands on. A render that differed from itself would make
    every rebuild look like it moved something."""
    import pathlib

    from docxkit.pages import render_diff

    paper = next((p for p in pathlib.Path(r"F:\OneDrive\__Documents")
                  .glob("*.docx") if not p.name.startswith("~$")), None)
    if paper is None:
        pytest.skip("no manuscript to render")
    diff = render_diff(paper, paper)
    assert diff.same, diff.format()


def test_a_sheet_turned_LANDSCAPE_is_a_whole_sheet_change(tmp_path):
    """Portrait 300 x 400 and landscape 400 x 300 hold the same number of
    samples, and comparing the buffers byte by byte gave a meaningless
    overlap for what is a different sheet (review, 2026-11-15)."""
    def sheets(name: str, *sizes: tuple[int, int]):
        doc = pymupdf.open()
        for w, h in sizes:
            doc.new_page(width=w, height=h).insert_text((20, 40), "Same.")
        doc.save(str(tmp_path / name))
        doc.close()
        return tmp_path / name

    a = sheets("a.pdf", (300, 400), (300, 400), (300, 400))
    b = sheets("b.pdf", (300, 400), (400, 300), (300, 400))

    diff = compare_renders(a, b)

    assert diff.differing == [2]
    assert diff.share == {2: 1.0}
