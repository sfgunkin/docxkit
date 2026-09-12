"""How an entry gets its bookmark NAME, stated as values.

Nineteen survivors across `_named`, `_mint_name` and `_dedup_name` on
2026-08-16 — the trio that decides what every hyperlink in the document
points at. The S1 already fixed here says what is at stake: two entries
that shared one name meant every link to it landed on whichever Word
found first, and the report said "linked 1, back-links added 2" while
it happened.

The names have two hard constraints and they pull against each other:

* **Word's cap.** A bookmark name over :data:`WORD_BOOKMARK_LIMIT` is
  truncated ON SAVE, and Word does not retarget the hyperlinks that
  pointed at the full name — every anchor silently orphaned, the
  document still opening, and only an audit able to find it;
* **uniqueness.** A collision mis-targets a link, which is worse than
  breaking one, so where both cannot hold the cap gives way.

Both were asserted only through their consequences. Nothing said what a
name IS.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run

from docxkit._cite_build import (
    _NAME_BUDGET,
    WORD_BOOKMARK_LIMIT,
    _dedup_name,
    _mint_name,
)
from docxkit._cite_grammar import Reference
from docxkit._xml import BOOKMARK_NAME_RE
from docxkit.citations import link_all


def _names(parts: dict[str, bytes]) -> set[str]:
    return set(BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8")))


def _entry(text: str) -> Reference:
    from docxkit.citations import references
    refs = references(["References", text], heading=("References",))
    assert refs, f"not parsed as an entry: {text!r}"
    return refs[0]


# ------------------------------------------------------ the paper's name --

def _fixed(name: str):
    """A naming convention that always proposes `name`."""
    return lambda surname, year: name


def test_a_convention_name_AT_the_budget_is_used():
    """The budget is the last length that FITS, not the first that does
    not: the in-text twin adds "txt", and `_NAME_BUDGET` already has
    that subtracted. A name of exactly this length saves intact.
    """
    proposed = "K" * _NAME_BUDGET
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal.")))

    report = link_all(parts, naming=_fixed(proposed))

    assert proposed in _names(parts), sorted(_names(parts))
    assert not report.skipped, report.format()
    assert len(proposed + "txt") <= WORD_BOOKMARK_LIMIT


def test_a_convention_name_ONE_over_the_budget_is_minted_instead():
    proposed = "K" * (_NAME_BUDGET + 1)
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal.")))

    report = link_all(parts, naming=_fixed(proposed))

    assert proposed not in _names(parts)
    assert "Kanbur2007" in _names(parts), sorted(_names(parts))
    assert any("characters" in note for note in report.skipped), \
        report.format()


def test_a_convention_name_ALREADY_taken_is_minted_instead():
    """A collision mis-targets a link, and the paper's convention is not
    worth that. Reported, because the author chose the convention."""
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + '<w:p><w:bookmarkStart w:id="9" w:name="Ref1"/>'
        + run("An earlier scheme left this.")
        + '<w:bookmarkEnd w:id="9"/></w:p>'
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal.")))

    report = link_all(parts, naming=_fixed("Ref1"))

    assert "Kanbur2007" in _names(parts), sorted(_names(parts))
    assert any("already taken" in note for note in report.skipped), \
        report.format()


# ------------------------------------------------- the minted name, exact --

def test_a_minted_name_is_the_surname_and_the_year():
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal.")))

    link_all(parts)

    assert {"Kanbur2007", "Kanbur2007txt"} <= _names(parts), \
        sorted(_names(parts))


def test_a_LONG_institutional_name_is_cut_to_fit_the_cap():
    """Parental Style, 2026-08-05: four entries over the cap, eight dead
    anchors, found only when the author saved in Word. Only the alpha
    part is cut, so the name keeps the <alpha><year> shape the key
    check needs.
    """
    r = _entry("State Committee of the Republic of Uzbekistan on Statistics "
               "and United Nations Children's Fund (UNICEF). (2021). "
               "Multiple indicator cluster survey.")

    name = _mint_name(r, set())

    assert len(name) == _NAME_BUDGET, name
    assert len(name + "txt") <= WORD_BOOKMARK_LIMIT
    assert name.endswith("2021")
    assert name.startswith("StateCommitteeoftheRepublic")


# ------------------------------------------------------------ uniqueness --

def test_a_fresh_name_is_handed_back_unchanged():
    assert _dedup_name("Kanbur2007", set()) == "Kanbur2007"


def test_a_name_whose_TXT_TWIN_is_taken_is_still_a_collision():
    """The pair is the unit. Taking `Kanbur2007` when `Kanbur2007txt`
    already exists points this entry's in-text end at the other one's."""
    assert _dedup_name("Kanbur2007", {"Kanbur2007txt"}) == "Kanbur2007_2"


def test_the_suffixes_run_2_then_3():
    """`_2` because the unsuffixed name is the first, and then one at a
    time — a step of two would leave gaps that read as missing entries."""
    assert _dedup_name("Kanbur2007", {"Kanbur2007"}) == "Kanbur2007_2"
    assert _dedup_name("Kanbur2007",
                       {"Kanbur2007", "Kanbur2007_2"}) == "Kanbur2007_3"
    assert _dedup_name("Kanbur2007", {"Kanbur2007", "Kanbur2007_2",
                                      "Kanbur2007_3"}) == "Kanbur2007_4"


def test_three_entries_under_one_key_get_three_distinct_names():
    parts = make_parts(
        para(run("All three (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal."))
        + para(run("Kanbur, A. (2007). Distribution. Another Journal."))
        + para(run("Kanbur, S. (2007). A third. A Third Journal.")))

    link_all(parts)

    minted = sorted(n for n in _names(parts) if n.startswith("Kanbur"))
    assert minted == ["Kanbur2007", "Kanbur2007_2", "Kanbur2007_3"], minted


def test_UNIQUENESS_beats_the_cap_when_every_candidate_is_taken():
    """The pathological fallback, which nothing had run. Ninety-nine
    truncated candidates all taken, and the answer is a name that is too
    long rather than one that collides: an over-long name breaks its own
    link, a colliding one silently re-points somebody else's.
    """
    r = _entry("International Institute for Applied Systems Analysis. "
               "(2020). Global population projections.")
    every = {_mint_name(r, set())}
    for n in range(2, 100):
        keep = _NAME_BUDGET - len(r.year) - len(f"_{n}")
        every.add(f"{_ascii(r)[:keep]}{r.year}_{n}")
    # and the untruncated form as well, so the fallback has to dedup too
    every.add(_ascii(r) + r.year)

    name = _mint_name(r, every)

    assert name not in every, name
    assert len(name) > _NAME_BUDGET, "the cap should have given way"
    assert name == _ascii(r) + "2020_2", name


def _ascii(r: Reference) -> str:
    from docxkit._cite_build import _ascii_stem
    return _ascii_stem(r.surname)


# `suffix = "" if n == 1 else ...` mutated to `n <= 1` is EQUIVALENT: the
# loop starts at 1 and never goes below it.
#
# `if keep < 1: break` is UNREACHABLE, and its two mutants are permanent
# residue. `_NAME_BUDGET` is 37, a year is 4 characters (5 with a letter
# suffix) and the widest `_N` is 3, so `keep` is never below 29. The
# guard is kept because it protects `alpha[:keep]` from a future change
# to WORD_BOOKMARK_LIMIT, which is the only thing that could make it
# matter — recorded here so the next survivor report is not read as a
# gap.
@pytest.mark.parametrize("year", ["2007", "2007a"])
def test_the_truncation_budget_never_goes_negative(year):
    """The arithmetic behind that unreachable guard, stated instead."""
    for n in range(1, 100):
        suffix = "" if n == 1 else f"_{n}"
        assert _NAME_BUDGET - len(year) - len(suffix) >= 29


def test_a_document_whose_bookmark_IDS_are_already_high_still_links():
    """`range(bid, bid + 4096)`, the pool of ids the pass hands out. It
    starts above every id already in the document, and the width is
    added to that start — `bid | 4096` is the same number for every
    small `bid` and an EMPTY range the moment the document's own ids
    reach 4096, which Word's do in a manuscript that has been edited for
    a year (each save mints fresh ids for the fields it rewrites).

    An empty pool is not a wrong name: it is `StopIteration` out of the
    middle of a linking pass, with the document half rewritten."""
    import re

    high = ('<w:p><w:bookmarkStart w:id="5000" w:name="_Toc5000"/>'
            + run("Introduction") + '<w:bookmarkEnd w:id="5000"/></w:p>')
    parts = make_parts(
        high + para(run("Poverty fell (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    report = link_all(parts)

    assert report.linked == ["Kanbur2007 @ ¶2"], report.linked
    ids = re.findall(r'<w:bookmarkStart w:id="(\d+)"',
                     parts["word/document.xml"].decode("utf-8"))
    assert "5000" in ids and len(set(ids)) == len(ids), ids


# `for n in range(1, 100)` mutated to `range(1, 99)` is the same
# residue as the `keep < 1` guard above: it would take 98 names of one
# shape already in the document to reach the last turn, and the
# `_dedup_name` fallback answers the case beyond it either way.


# --- the grammar's edges: the 2026-09-12 replay of `_cite_grammar` --------
#
# 67 mutants survived a six-file harness. Each test below puts a number on
# a boundary nothing had measured; the rest are argued in equivalents.toml.


@pytest.mark.parametrize(("text", "years"), [
    ("Sen (2000, 2100).", ["2000", "2100"]),       # the last plausible year
    ("Sen (2000, 2101).", ["2000"]),               # ...and a page after it
    ("Acemoglu and Robinson (2012, 1215, 2019).", ["2012"]),   # a page ENDS
    ("Sen (1985, 1992, 1215).", ["1985", "1992"]),  # two works, then a page
])
def test_a_four_digit_LOCATOR_closes_a_list_of_years(text, years):
    from docxkit._cite_grammar import find_citations

    assert [c.year for c in find_citations(text)] == years


def test_three_years_under_one_author_TILE_the_group():
    from docxkit._cite_grammar import find_citations

    text = "Sen (1985, 1992, 1999) argues."

    assert ([text[c.start:c.end] for c in find_citations(text)]
            == ["Sen (1985", "1992", "1999)"])


def test_a_parenthetical_group_of_years_is_cut_at_its_OWN_offsets():
    """The group opens at 12 and its years at 16: offsets where `+`, `^`,
    `|` and the other operators all give different answers."""
    from docxkit._cite_grammar import find_citations

    text = "As argued, (Sen 1985, 1992)."

    assert ([(c.start, c.end) for c in find_citations(text)]
            == [(12, 20), (22, 26)])


def test_a_ONE_word_name_never_widens_even_over_an_echo_of_itself():
    from docxkit._cite_grammar import Citation, extend_to_name

    text = "by UNICEF UNICEF (2020)."
    c = Citation(authors="UNICEF", year="2020", start=10, end=23,
                 narrative=True)

    assert extend_to_name(text, c, "UNICEF") is c


@pytest.mark.parametrize("pad", [0, 300])
def test_a_BLOCKED_wide_span_falls_back_to_the_grammars_own(pad):
    """The wide span a known surname gives is taken when clear; when its
    first words are already linked, the narrower one is, if that is clear.
    Padded past 256 too, where two equal offsets are two int objects."""
    from docxkit._cite_grammar import citations_clear_of

    lead = "x" * pad + "see "
    text = lead + "de São José et al. (2019) today."
    at = len(lead)
    masked = text[:at] + "\x00" * len("de São ") + text[at + 7:]

    found = citations_clear_of(text, masked, ("de São José",))

    assert ([(c.start - pad, c.end - pad, c.year) for c in found]
            == [(11, 29, "2019")])


def test_add_style_styles_ONCE_a_run_carrying_a_format_change():
    """A tracked formatting change keeps the OLD properties in a second
    `<w:rPr>`, inside `w:rPrChange`. Styling that one as well would write
    the Hyperlink style into Word's record of what the run used to be."""
    from docxkit._cite_grammar import _add_style

    run = ('<w:r><w:rPr><w:b/><w:rPrChange w:id="1" w:author="A">'
           "<w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr><w:t>x</w:t></w:r>")

    out = _add_style(run, "Hyperlink")

    assert out.count('<w:rStyle w:val="Hyperlink"/>') == 1
    assert out.startswith('<w:r><w:rPr><w:rStyle w:val="Hyperlink"/><w:b/>')
