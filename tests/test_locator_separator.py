r"""`refstyle` audits everything around the locator, so its silence read
as approval.

An author edit turned one entry's `6(1):` into `6(1);` and the audit
reported the file clean: **74 entries, 74 cited, one finding, and that
one about Doepke's position in the list.** Counting the paper's own
practice, 41 of its 42 `volume(issue)` entries use a colon and exactly
this one uses a semicolon (Parental_style, 2026-09-01).

The rule is the paper's own MAJORITY rather than a hard-coded character,
because journals differ and a paper consistently writing `40(2), 355` is
following its journal, not making an error. Both bounds on that majority
were measured over 300 manuscripts, and the tests here pin the cases
that set them — a list too short to have a practice, and a list holding
two conventions at once.
"""
from __future__ import annotations

import pytest

from docxkit._cite_grammar import Reference
from docxkit.refstyle import _locator_findings


def entries(*locators: str, start: int = 10) -> list[Reference]:
    """A reference list whose entries differ only in their locator."""
    return [Reference(text=(f"Author{i}, A. (20{10 + i % 80}). “A title "
                            f"about something.” A Journal, {loc}"),
                      surname=f"Author{i}", year=str(2010 + i % 80),
                      index=start + i)
            for i, loc in enumerate(locators)]


COLON = ["12(3): 45–67"] * 20
COMMA = ["12(3), 45–67"] * 20


# ------------------------------------------------ the case that was missed


def test_the_semicolon_that_74_entries_hid():
    """Parental_style's own entry, and the shape of its list."""
    found = _locator_findings(entries(*(["6(1): 157–189"] * 41),
                                      "6(1); 157–189"))

    assert len(found) == 1
    assert found[0].code == "locator-sep"
    assert '41 of 42' in found[0].message
    assert '";"' in found[0].message
    assert found[0].where == "¶52"    # index 10 + 41, one-based


def test_the_snippet_shows_the_LOCATOR_not_the_authors():
    """Every other snippet here is the entry's first 60 characters, which
    for this finding is the part that is right."""
    found = _locator_findings(entries(*COLON, "12(3), 45–67"))

    assert "12(3)" in found[0].snippet
    assert "Author0" not in found[0].snippet


# ------------------------------------------------------ what it stays quiet on


def test_a_list_that_agrees_reports_nothing():
    assert _locator_findings(entries(*COLON)) == []
    assert _locator_findings(entries(*COMMA)) == []


def test_a_COMMA_paper_is_not_told_to_use_a_colon():
    """The reason the rule is a majority and not a character. Half these
    papers' journals set `40(2), 355`, and a module preferring the colon
    would report a house style as an error in every one of them."""
    assert _locator_findings(entries(*COMMA, "12(3), 45–67")) == []


def test_a_list_too_SHORT_to_have_a_practice_is_left_alone():
    """Measured: half the mixed lists in the corpus have a "majority" of
    one or two entries (`ACC1.docx`, "1 of 2 agree"). A convention of one
    entry is not a convention."""
    assert _locator_findings(entries("12(3): 45–67", "12(3), 45–67")) == []
    assert _locator_findings(
        entries(*(["12(3): 45–67"] * 5), "12(3), 45–67")) == []


def test_a_list_holding_TWO_conventions_is_described_not_reported():
    """A hand-assembled review running 31 one way and 8 the other. Naming
    the 8 tells the author their document has variety, which they know."""
    both = entries(*(["12(3): 45–67"] * 31), *(["12(3), 45–67"] * 8))

    assert _locator_findings(both) == []


def test_an_entry_with_NO_locator_is_not_a_dissenter():
    """A book, a working paper, a URL — most reference lists are half
    made of entries with no volume at all, and they must not count
    toward or against the majority."""
    books = [Reference(text="Sen, A. (1999). Development as Freedom. Knopf.",
                       surname="Sen", year="1999", index=99)] * 30

    assert _locator_findings(entries(*COLON) + books) == []


@pytest.mark.parametrize("locator", [
    "12 (3): 45–67",          # a space before the issue — Clim. Change
    "150(3):227–260",         # no space after, BibTeX's shape
    "101(910): 251-272",      # a four-digit issue
    "6(1): 157",              # a single page, not a range
    "40(2): 355 – 372",       # spaced en-dash
])
def test_the_shapes_a_real_list_actually_holds(locator):
    """Each of these appears in the corpus. A locator the pattern cannot
    see is a dissenter it cannot report — and worse, one that silently
    shrinks the majority it is judging the others against."""
    found = _locator_findings(entries(*COLON, locator))

    assert found == [], f"{locator!r} read as a departure"


def test_a_colon_INSIDE_the_journal_name_is_not_the_locator():
    """`International Review of the Red Cross: 101(910), 251-272` — the
    colon before the volume is punctuation in the title. The separator
    this rule judges is the one after the ISSUE."""
    odd = [Reference(
        text=("Drozdzewski, D. (2019). “Cultural memory and identity.” "
              "International Review of the Red Cross: 101(910), 251-272"),
        surname="Drozdzewski", year="2019", index=80)]

    found = _locator_findings(entries(*COLON) + odd)

    assert len(found) == 1
    assert '","' in found[0].message


def test_it_rides_the_whole_audit():
    """Wired into `audit`, not merely importable."""
    from conftest import make_parts, para, run

    from docxkit.refstyle import audit

    body = para(run("References")) + "".join(
        para(run(f"Author{i}, A. (20{10 + i}). “A title.” A Journal, "
                 f"{20 + i}(1){';' if i == 5 else ':'} 5–6."))
        for i in range(12))

    codes = [i for i in audit(make_parts(body)).issues
             if i.code == "locator-sep"]

    assert len(codes) == 1
    assert codes[0].where == "¶7"      # the heading is ¶1
