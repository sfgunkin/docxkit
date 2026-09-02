r"""Nothing in docxkit could see prose that RENDERS superscript.

Footnote 5 of Parental_style rendered entirely in superscript for 20
days. Its prose run carried `<w:rStyle w:val="FootnoteReference"/>` and
no `w:vertAlign` of its own; `styles.xml` gives that style
`vertAlign=superscript`, so the raising was inherited. Every gate in the
paper's list passed it on every round:

    footnotes --check   reads SIZE only — "9 footnote(s), house size
                        10pt, 0 disagreeing"
    lint/citations/     content-blind to run properties
      refstyle/math
    compare FORMAT      the note's text was REPLACED wholesale in the
                        same batch, so there was no text-matched pair
                        to compare formatting on

The author found it by reading the page (2026-09-01).

**A grep for `w:vertAlign` reports such a file clean.** That is the trap
worth recording, and it is why this check lives in `styles`: the
character style has to be resolved through `styles.xml` before the
question can even be asked.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, notes, write

from docxkit.cli import main
from docxkit.styles import raised_prose

#: `FootnoteReference` as every one of these manuscripts defines it.
STYLES = (
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
    'wordprocessingml/2006/main">'
    '<w:style w:type="character" w:styleId="FootnoteReference">'
    '<w:name w:val="footnote reference"/>'
    '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>'
    '<w:style w:type="character" w:styleId="Emphasis">'
    "<w:name w:val=\"Emphasis\"/><w:rPr><w:i/></w:rPr></w:style>"
    "</w:styles>")

MARK = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
        "<w:footnoteRef/></w:r>")


def styled(text: str, style: str = "FootnoteReference") -> str:
    return (f'<w:r><w:rPr><w:rStyle w:val="{style}"/></w:rPr>'
            f"<w:t>{text}</w:t></w:r>")


def note(runs: str, nid: int = 5, kind: str = "footnote") -> str:
    return (f'<w:{kind} w:id="{nid}"><w:p><w:pPr>'
            f'<w:pStyle w:val="FootnoteText"/></w:pPr>{runs}'
            f"</w:p></w:{kind}>")


def parts(footnotes_body: str, doc_body: str = "",
          styles: str | None = STYLES) -> dict[str, bytes]:
    made = make_parts(doc_body or "<w:p><w:r><w:t>Body.</w:t></w:r></w:p>",
                      footnotes=notes("footnote", footnotes_body))
    if styles is not None:
        made["word/styles.xml"] = styles.encode("utf-8")
    return made


PROSE = "Table A1 reports the first stage of the main specification."


# ------------------------------------------------------- the defect itself


def test_the_footnote_that_sat_wrong_for_20_days():
    found = raised_prose(parts(note(MARK + styled(PROSE))))

    assert len(found) == 1
    assert found[0].where == "fn 5"
    assert found[0].style == "FootnoteReference"
    assert found[0].value == "superscript"
    assert found[0].text == PROSE
    assert found[0].part == "word/footnotes.xml"


def test_a_grep_for_vertAlign_finds_NOTHING_in_that_file():
    """The trap. The run states no `w:vertAlign`; the style supplies it,
    so the check has to resolve the cascade before it can ask."""
    made = parts(note(MARK + styled(PROSE)))

    assert b"vertAlign" not in made["word/footnotes.xml"]
    assert raised_prose(made)


def run_cli(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["docxkit", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    return 0 if exc.value.code is None else int(exc.value.code)


def test_it_rides_docxkit_lint_as_an_ADVISORY_finding(
        tmp_path, capsys, monkeypatch):
    """Word opens the file and the toolkit has no command that clears
    this — it is a formatting mistake for a person to fix, which is the
    tier `lint`'s advisory half exists for.

    Joined in the COMMAND rather than in `lint.audit_parts`, where it
    reads: `lint` and `styles` are siblings in the layering and may not
    import each other, and `test_layering` said so the first time this
    was wired the obvious way.
    """
    docx = write(tmp_path / "raised.docx",
                 parts(note(MARK + styled(PROSE))))

    code = run_cli(monkeypatch, "lint", str(docx))
    out = capsys.readouterr().out

    assert code == 0, "advisory findings do not fail the command"
    assert "advisory" in out
    assert "fn 5: prose renders superscript" in out
    assert "FootnoteReference" in out
    assert run_cli(monkeypatch, "lint", "--strict",
                   str(docx)) == 1


def test_the_BODY_is_read_too():
    """The same class appeared in the body — a run of prose wearing a
    raising style. A check over the notes alone would be half of one."""
    body = "<w:p>" + styled("an ordinary sentence") + "</w:p>"

    found = raised_prose(parts(note(MARK + "<w:r><w:t>fine.</w:t></w:r>"),
                               doc_body=body))

    assert [(r.part, r.where) for r in found] == [
        ("word/document.xml", "¶1")]


def test_an_ENDNOTE_is_read_too():
    made = make_parts("<w:p><w:r><w:t>Body.</w:t></w:r></w:p>")
    made["word/styles.xml"] = STYLES.encode("utf-8")
    made["word/endnotes.xml"] = notes(
        "endnote", note(MARK.replace("footnoteRef", "endnoteRef")
                        + styled(PROSE), kind="endnote")).encode("utf-8")

    found = raised_prose(made)

    assert [(r.part, r.where) for r in found] == [
        ("word/endnotes.xml", "en 5")]


# --------------------------------------------------- what it stays quiet on


def test_the_note_MARK_is_not_a_finding():
    """Its whole job is to be raised."""
    assert raised_prose(parts(note(
        MARK + "<w:r><w:t>An ordinary note.</w:t></w:r>"))) == []


def test_a_CUSTOM_note_mark_is_not_a_finding():
    """A footnote marked `*` rather than numbered carries the asterisk as
    literal TEXT in the first run, wearing `FootnoteReference` on
    purpose. Measured: 22 of 26 raw findings over 300 manuscripts are
    exactly this, and it is what the exemption is for."""
    custom = note(styled("*") + "<w:r><w:t> A starred note.</w:t></w:r>")

    assert raised_prose(parts(custom)) == []


def test_the_exemption_is_POSITION_not_LENGTH():
    """A raised full stop at the END of a note was found by this rule in
    an unrelated redline, and a "too short to be prose" cut-off would
    have thrown it away. Run 0 of a note with no auto mark IS the mark;
    everything after it is prose, however short."""
    custom = note(styled("*") + "<w:r><w:t> A starred note</w:t></w:r>"
                  + styled("."))

    found = raised_prose(parts(custom))

    assert [r.text for r in found] == ["."]


def test_a_run_stating_its_OWN_vertAlign_is_deliberate():
    """Including `baseline`, which is how a caller says "not raised" on a
    run that wears a raising style for its other properties."""
    grounded = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
                '<w:vertAlign w:val="baseline"/></w:rPr>'
                f"<w:t>{PROSE}</w:t></w:r>")

    assert raised_prose(parts(note(MARK + grounded))) == []


def test_a_style_that_does_not_RAISE_is_not_a_finding():
    assert raised_prose(parts(note(
        MARK + styled(PROSE, "Emphasis")))) == []


def test_a_DELETED_run_is_going_away():
    """Its typography is not a defect. A redline holds the author's
    deletions, and reporting them is reporting text nobody will read."""
    struck = (f'<w:del w:id="9" w:author="R" w:date="2026-01-01T00:00:00Z">'
              f'<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
              f"<w:delText>{PROSE}</w:delText></w:r></w:del>")

    assert raised_prose(parts(note(MARK + struck))) == []


def test_a_redlines_SUPERSEDED_properties_are_not_scored():
    """`w:rPrChange` holds what the formatting WAS. Reading it would
    score the change a revision is proposing to undo."""
    proposed = ('<w:r><w:rPr><w:rPrChange w:id="4" w:author="R" '
                'w:date="2026-01-01T00:00:00Z"><w:rPr>'
                '<w:rStyle w:val="FootnoteReference"/></w:rPr>'
                f"</w:rPrChange></w:rPr><w:t>{PROSE}</w:t></w:r>")

    assert raised_prose(parts(note(MARK + proposed))) == []


def test_no_styles_part_answers_NOTHING_rather_than_guessing():
    """With no `word/styles.xml` there is nothing to inherit FROM, and a
    run's own properties are the whole story — which this check is not
    about."""
    assert raised_prose(parts(note(MARK + styled(PROSE)),
                              styles=None)) == []


def test_an_empty_run_is_not_prose():
    assert raised_prose(parts(note(MARK + styled("   ")))) == []
