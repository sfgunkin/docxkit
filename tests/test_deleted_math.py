r"""`math --check` reported a redline's DELETED maths as a stranded display.

Measured on Aging_Well R78, 2026-09-01. A batch built with `--keep-math`
deletes a body paragraph carrying two inline equations. On the accepted
view `math --check` exits 0 with 15 displays; on the promoted PROPOSAL
it exits 1:

    16 display equation(s), 1 still in INLINE mode
       ¶64    'cijfj'
       -> equations.display(para) wraps them in m:oMathPara

¶64 is the deleted paragraph: its prose all `w:delText`, the equations'
runs inside tracked deletions. `visible_text` drops the `w:delText` and
keeps the `m:t`, so the paragraph reads as maths-only — the exact
signature of a stranded display — and the check could not tell a
paragraph with nothing live from one that IS an equation. The remedy it
printed would have wrapped an equation on its way OUT of the document.

Reproduced independently before the fix: over 600 manuscripts, exactly
one other document carries the shape — `Missing Market 12082019.docx`
¶78, 17 `w:delText` runs and one `m:oMath` inside a deletion with a
stray "G. " live — and it was reported as a stranded display too. Its
count went 10 -> 9 with the fix in, the nine being real.
"""
from __future__ import annotations

import pytest

from docxkit.equations import (
    _accepted_side,
    display_equations,
    inline_display,
    is_display,
)

WHEN = 'w:author="R" w:date="2026-09-01T00:00:00Z"'
MATHS = ("<m:oMath><m:r><m:t>c</m:t></m:r><m:sSub><m:e><m:r>"
         "<m:t>ij</m:t></m:r></m:e></m:sSub></m:oMath>")


def run(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def struck(text: str) -> str:
    return (f'<w:del w:id="7" {WHEN}><w:r>'
            f"<w:delText>{text}</w:delText></w:r></w:del>")


def struck_maths() -> str:
    return f'<w:del w:id="8" {WHEN}>{MATHS}</w:del>'


def para(*bits: str) -> str:
    return "<w:p>" + "".join(bits) + "</w:p>"


def body(*paras: str) -> str:
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
          '2006/main" xmlns:m="http://schemas.openxmlformats.org/'
          'officeDocument/2006/math"')
    return f"<w:document {ns}><w:body>{''.join(paras)}</w:body></w:document>"


# ------------------------------------------------------- the false finding


def test_a_paragraph_on_its_way_OUT_is_not_a_stranded_display():
    """The R78 shape: prose in `w:delText`, the maths inside a `w:del`."""
    going = para(struck("The capability set is "), struck_maths(),
                 struck(" for each individual."))

    assert is_display(going) is False
    assert inline_display(body(going)) == []


def test_a_deletion_whose_NAME_ends_another_way_is_still_resolved():
    """The accepted side was taken only when the paragraph held the
    string `<w:del `. A deletion written `<w:del\\n…` — legal XML, though
    no corpus package writes one — was left in, and its maths read as a
    stranded display."""
    going = para(struck("The capability set is ").replace("<w:del ",
                                                          "<w:del\n"),
                 struck_maths().replace("<w:del ", "<w:del\n"))

    assert is_display(going) is False


def test_the_remedy_it_printed_would_have_edited_a_DELETION():
    """Which is why this is worth a gate rather than a note: the report
    named `equations.display(para)`, and applying it to a paragraph
    being deleted wraps an equation on its way out of the document."""
    going = para(struck("text "), struck_maths())

    assert display_equations(body(going)) == []


def test_the_DELETED_PROSE_was_half_the_illusion():
    """`visible_text` drops `w:delText` and keeps `m:t`, so a paragraph
    losing its words already read as maths-only. Resolving to the
    accepted side fixes both halves in one pass — which is why it is the
    general answer rather than "skip a paragraph whose maths is deleted"."""
    losing_words = para(struck("The capability set is "), MATHS,
                        struck(" for each individual."))

    # the maths is LIVE, so in the accepted view this really is one
    assert is_display(losing_words) is True


# ------------------------------------------------- what still reports


def test_a_LIVE_stranded_display_still_reports():
    assert is_display(para(MATHS)) is True
    assert len(inline_display(body(para(MATHS)))) == 1


def test_a_clean_document_is_unchanged_by_the_resolution():
    doc = body(para(run("Prose about it.")), para(MATHS))

    assert len(inline_display(doc)) == 1


def test_maths_beside_LIVE_prose_is_not_a_display_either_way():
    """It was not one before and is not one now; the resolution must not
    turn an inline equation in a sentence into a finding."""
    inline = para(run("We write "), MATHS, run(" for the capability set."))

    assert is_display(inline) is False


def test_a_paragraph_whose_prose_is_INSERTED_is_live():
    """`w:ins` text is live and `visible_text` keeps it, so an inserted
    sentence around an equation is prose. Only the deletion side moves."""
    added = para(f'<w:ins w:id="9" {WHEN}>{run("We write ")}</w:ins>',
                 MATHS,
                 f'<w:ins w:id="10" {WHEN}>{run(" for it.")}</w:ins>')

    assert is_display(added) is False


# ------------------------------------------------------ accepted_side


def test_accepted_side_leaves_an_untracked_paragraph_alone():
    """Identity, not a reserialisation: this runs per paragraph over
    every document the check reads."""
    clean = para(run("Ordinary prose."), MATHS)

    assert _accepted_side(clean) is clean


def test_accepted_side_removes_the_whole_del_element():
    p = para(run("kept "), struck("gone"), run(" kept"))

    got = _accepted_side(p)

    assert "gone" not in got
    assert "<w:del" not in got
    assert got.count("<w:r>") == 2


# --------------------------------------------------------- the report


def run_cli(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["docxkit", *argv])
    with pytest.raises(SystemExit) as exc:
        from docxkit.cli import main
        main()
    return 0 if exc.value.code is None else int(exc.value.code)


def test_the_command_SAYS_it_read_the_accepted_side(monkeypatch, tmp_path,
                                                    capsys):
    """A count that silently answers about a different view of the file
    than the one named on the command line is the shape this backlog
    keeps finding — so the resolution is announced, not assumed."""
    from conftest import make_parts

    from docxkit.package import write_docx

    path = tmp_path / "redline.docx"
    write_docx(path, make_parts(
        para(struck("The capability set is "), struck_maths())
        + para(MATHS)))

    code = run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "1 display equation(s), 1 still in INLINE mode" in out
    assert "ACCEPTED side" in out


def test_a_CLEAN_document_is_not_told_about_a_side(monkeypatch, tmp_path,
                                                   capsys):
    """The note is for a reader looking at a redline. On a clean file it
    would be noise about a distinction the file does not have."""
    from conftest import make_parts

    from docxkit.package import write_docx

    path = tmp_path / "clean.docx"
    write_docx(path, make_parts(para(MATHS)))

    run_cli(monkeypatch, "math", str(path))

    assert "ACCEPTED side" not in capsys.readouterr().out


@pytest.mark.parametrize("prose", ["", " ", "(3)", " , (A2)"])
def test_the_equation_NUMBER_rules_are_unchanged_by_it(prose):
    """`is_display` counts a number and closing punctuation as not-prose,
    and three of one manuscript's seven equations were invisible before
    that was true. The resolution must not disturb it."""
    assert is_display(para(MATHS, run(prose))) is True
