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


def test_add_style_fills_an_EMPTY_rPr_instead_of_adding_a_second():
    """`<w:rPr/>` is a run's properties, empty — 18,172 of them in 248 of
    2,954 corpus packages. Asked for the exact string `<w:rPr>`, the
    styler found none and put a second `w:rPr` in front of it, which
    CT_R does not allow."""
    from docxkit._cite_grammar import _add_style

    out = _add_style("<w:r><w:rPr/><w:t>x</w:t></w:r>", "Hyperlink")

    assert out == ('<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                   "<w:t>x</w:t></w:r>")


def test_add_style_reads_the_LIVE_style_not_the_one_a_change_recorded():
    """A style only in the `w:rPrChange` snapshot is what the run USED to
    wear; read as present, the live run was left unstyled."""
    from docxkit._cite_grammar import _add_style

    run = ('<w:r><w:rPr><w:rPrChange w:id="1" w:author="A"><w:rPr>'
           '<w:rStyle w:val="Emphasis"/></w:rPr></w:rPrChange></w:rPr>'
           "<w:t>x</w:t></w:r>")

    out = _add_style(run, "Hyperlink")

    assert out.startswith('<w:r><w:rPr><w:rStyle w:val="Hyperlink"/>'
                          "<w:rPrChange"), out


# --- the whole sweep of 2026-09-15 ------------------------------------


def test_the_CAP_is_forty_characters_with_the_TWIN_counted():
    """Word's limit is 40, and the in-text twin meets it first: a
    38-character name fits on the entry and is 41 on the mention, where
    Word cuts it ON SAVE and orphans the link. Every other test here
    reads the cap back through `_NAME_BUDGET`, so a limit of 41 moved
    the budget with it and nothing noticed. This one states the number.
    """
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal.")))

    report = link_all(parts, naming=_fixed("K" * 38))

    assert sorted(_names(parts)) == ["Kanbur2007", "Kanbur2007txt"]
    assert any("would pass Word's 40-character cap" in note
               for note in report.skipped), report.format()


def test_the_NINETY_NINTH_candidate_is_still_cut_to_the_cap():
    """`range(1, 100)` tries the suffixes `_2` to `_99` before the
    fallback lets uniqueness beat the cap. With the first ninety-eight
    taken, the ninety-ninth still fits; giving up one turn early hands
    back the whole name, 51 characters, which Word truncates on save.

    The surname is LONG on purpose. A short one fits whole, and the
    fallback then counts its own way up to the same `_99`.
    """
    r = _entry("International Institute for Applied Systems Analysis. "
               "(2020). Global population projections.")
    taken = set()
    for n in range(1, 99):
        suffix = "" if n == 1 else f"_{n}"
        keep = _NAME_BUDGET - len(r.year) - len(suffix)
        taken.add(f"{_ascii(r)[:keep]}{r.year}{suffix}")

    name = _mint_name(r, taken)

    assert name == "InternationalInstituteforAppli2020_99", name


@pytest.mark.parametrize("stray", ["Kanbur2005txt", "Smith2007txt"])
def test_a_stray_TXT_bookmark_names_this_work_by_surname_AND_year(stray):
    """An in-text bookmark with no entry marker beside it is evidence of
    this work's scheme only when it names THIS work. A draft that cut
    its citation of Kanbur (2005), or of Smith (2007), leaves the `txt`
    bookmark behind, and read by one half of the rule alone it is
    adopted: the entry is named `Kanbur2005` or `Smith2007`, the
    mention of Kanbur (2007) links there, and the report says "linked 1".

    One stray per half: the right surname in another year, and the
    right year under another surname.
    """
    from docxkit._xml import internal_links

    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(f'<w:bookmarkStart w:id="5" w:name="{stray}"/>'
               '<w:bookmarkEnd w:id="5"/>'
               + run("A sentence an earlier draft cited from."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal.")))

    report = link_all(parts)

    assert report.linked == ["Kanbur2007 @ ¶1"], report.format()
    assert [a for a, _ in internal_links(
        parts["word/document.xml"].decode("utf-8"))] == [
            "Kanbur2007", "Kanbur2007txt"]


@pytest.mark.parametrize(("entry", "twin", "rule"), [
    pytest.param("Kanbur2007", "Kanbur2007txt", ("", ""), id="suffix"),
    pytest.param("ref_noone_2018", "cite_noone_2018", ("ref", "cite"),
                 id="prefix"),
    # 16 and 17 characters over a tail of 13, where `^` and `-` differ
    pytest.param("ref_maestas_2023", "cite_maestas_2023", ("ref", "cite"),
                 id="maestas"),
    # prefixes LONGER than the tail, where `%` and `-` differ
    pytest.param("reference_ho_2019", "citation_ho_2019",
                 ("reference", "citation"), id="long-prefixes"),
    # where the two names part, the entry's letter sorts first
    pytest.param("bib_noone_2018", "cite_noone_2018", ("bib", "cite"),
                 id="b-sorts-before-e"),
    # a letter outside Latin-1: equal, and a fresh object each read
    pytest.param("ref_miłosz_2018", "cite_miłosz_2018", ("ref", "cite"),
                 id="outside-latin-1"),
    # exactly FOUR shared, a letter among them
    pytest.param("refWu19", "citeWu19", ("ref", "cite"), id="four"),
    # the shorter name is the WHOLE tail, and the character before it in
    # the longer name is the one it ends with
    pytest.param("kanbur_2007_", "ref_kanbur_2007_", ("", "ref_"),
                 id="whole-tail"),
    pytest.param("x" * 300 + "kanbur_2007_",
                 "ref_" + "x" * 300 + "kanbur_2007_", ("", "ref_"),
                 id="whole-tail-past-256"),
])
def test_a_PAIR_RULE_is_the_two_prefixes_over_the_LONGEST_shared_tail(
        entry, twin, rule):
    """How `link_all` learns a document's naming, by majority over the
    pairs still whole. Only its two ordinary shapes had been asked, and
    seventeen mutants lived in it; each case is a pair where a slip
    answers differently.

    The tail is walked one character at a time from the END, comparing
    by value, and stops at the shorter name's first character. One step
    further reads index -1, which wraps round to that name's LAST
    character, so the whole-tail cases end both names with the
    character that stands before the shorter one in the longer — and
    one of them is padded past 256, where the step count and the length
    are equal ints and two objects. What is left in front of the tail is
    the rule, which `%` and `^` reproduce only while a prefix is shorter
    than the tail. Four shared characters with a letter among them is
    the least that counts as a convention.
    """
    from docxkit._cite_build import _pair_rule

    assert _pair_rule(entry, twin) == rule


@pytest.mark.parametrize(("entry", "twin"), [
    pytest.param("ref_2018", "cite_2018", id="the-year-alone"),
    pytest.param("Kanbur2007txt", "Ravallion2016txt", id="three"),
    pytest.param("ref_noone_2018a", "cite_noone_2018b", id="last-differs"),
])
def test_too_LITTLE_shared_is_NOT_a_convention(entry, twin):
    """None, and the pass keeps the suffix rule. A shared year is five
    characters with no letter in them; two in-text names share their
    "txt" and nothing more; and two names whose LAST characters differ
    share no tail at all, however alike the rest — a walk that began one
    character in would find `_noone_2018` and learn ("ref", "cite") from
    the names of two different works.
    """
    from docxkit._cite_build import _pair_rule

    assert _pair_rule(entry, twin) is None


def test_the_SUFFIX_rule_is_recognised_by_VALUE():
    """`("", "")` stands for this module's own shape, and `_twin_of`
    answers `<name>txt` for it. The rule a document teaches is not the
    literal `_twin_of` compares against, though: for an entry whose own
    link points at its own marker, `_pair_rule` BUILDS it from slices,
    equal to the literal and a different object. Read by identity, or
    by an ordering that nothing sorts below, the suffix rule turns into
    a swap of one empty prefix for another, and the twin it names is the
    entry's own name: two bookmarks called `Ravallion2016`.
    """
    from docxkit._cite_build import _pair_rule, _twin_of

    built = _pair_rule("Kanbur2007", "Kanbur2007")

    assert _twin_of("Ravallion2016", ("", "")) == "Ravallion2016txt"
    assert _twin_of("Ravallion2016", built) == "Ravallion2016txt"
