"""`rebuild`, and the three lines that say what could NOT be linked.

Every one of `rebuild`'s fifteen survivors on 2026-08-16 sat on a
`report.skipped` line or on the `except` above one. Nothing asserted
what a refusal says — only that linking worked when it worked.

That is the wrong half to leave unpinned. A citation that WAS linked is
visible in the document; a citation that was not is visible only in this
report, so the report is the entire output for that case. And the
paragraph number is most of it: an author goes to the paragraph named,
and a number one out sends them to the sentence before, with nothing to
suggest they are in the wrong place.

Paragraph indices here are 3 and 5. `¶{i + 1}` mutates to eleven
arithmetic operators and several agree with the original at any given
index — 0 agrees with `|`, 1 with `<<`, 2 with `|` — so the fixtures
have to put the reported paragraph at an index that separates all of
them. Odd indices from 3 up do.
"""
from __future__ import annotations

from conftest import make_parts, para, run

from docxkit.citations import link_all

LEAD = (para(run("Ageing raises the risk of isolation."))
        + para(run("The gradient is steeper in the eastern countries."))
        + para(run("Two mechanisms have been proposed for it.")))


def _note(text: str, nid: int = 2) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main">'
            f'<w:footnote w:id="{nid}">{para(run(text))}</w:footnote>'
            "</w:footnotes>")


def test_a_citation_that_cannot_be_WRAPPED_is_reported_with_its_paragraph():
    """A work cited twice in ONE paragraph is ambiguous — the wrap
    refuses rather than pick an occurrence. That refusal is the only
    trace: the sentence reads normally and the entry is still there.
    """
    parts = make_parts(
        LEAD
        + para(run("As Kanbur (2007) says, and again Kanbur (2007) says."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    report = link_all(parts)

    assert report.skipped[0].startswith("'Kanbur (2007)' ¶4: "), report.skipped
    assert "occurs twice" in report.skipped[0]


def test_the_same_refusal_in_a_FOOTNOTE_says_so():
    """Body and footnote paragraphs are numbered separately, so a line
    naming ¶2 when it means the footnote's second paragraph sends the
    author to the wrong part of the document entirely."""
    parts = make_parts(
        LEAD + para(run("A point on poverty."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")),
        footnotes=_note("See Kanbur (2007), and again Kanbur (2007)."))

    report = link_all(parts)

    assert any(s.startswith("'Kanbur (2007)' fn¶1: ")
               for s in report.skipped), report.format()


def test_a_BACK_LINK_that_cannot_be_placed_is_reported_with_its_paragraph():
    """The entry's own head is wrapped to point back at the mention. An
    entry that repeats its head — a duplicated line in the list — makes
    that anchor ambiguous too, and the back-link is dropped rather than
    aimed at a guess.

    This also pins the `except AnchorError` above it: catch a different
    class and the error leaves `link_all` instead of becoming a line.
    """
    parts = make_parts(
        LEAD + para(run("A point (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Kanbur, R. (2007). Poverty. "
                   "Journal.")))

    report = link_all(parts)

    assert any(s.startswith("back-link ¶6: ") for s in report.skipped), \
        report.format()
    assert "occurs twice" in " ".join(report.skipped)
    assert not report.backlinked


def test_an_entry_with_no_recognisable_HEAD_is_reported():
    """The head is everything up to the year and its terminator. An
    entry that parses as a reference but offers no head gets no
    back-link, and the line is the only sign of it.

    The fixture is an entry with a space before the period after the
    year — `_REF_YEAR_RE` allows that space and `_HEAD_RE` does not, so
    the two disagree about where a head ends. That disagreement is
    filed separately; what is pinned here is that the disagreement is
    REPORTED rather than swallowed.
    """
    parts = make_parts(
        LEAD + para(run("A point (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007) . Poverty and distribution. "
                   "Journal.")))

    report = link_all(parts)

    assert report.skipped == ["no head on entry ¶6"], report.skipped
    assert not report.backlinked
    assert report.linked, "the in-text mention should still be linked"
