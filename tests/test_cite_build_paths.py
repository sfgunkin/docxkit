"""The citation builder's unrun paths, and its unasserted values.

Mutation testing `_cite_build.py` on 2026-08-15: 996 mutants, 41.1 %
real survival — the least-pinned module measured, against 17.3 % for
`edit.py` and 7.3 % for `revisions.py`. The survivors split almost
exactly in half:

* **169 (48 %) on lines the tests never run** — the FOOTNOTE citation
  path, the back-link undo, `unlink_by_anchor`'s refusals. The tell is
  that arithmetic mutations survive there: swapping `+` for `*` in a
  string concatenation would raise `TypeError` the moment anything
  reached it, so surviving proves the line is dead under those tests;
* **185 (52 %) on lines that DO run** — `_entry_keys` builds the keys an
  entry can be found by and `scan` decides which mention is the FIRST
  one, and nothing asserted on either value.

This file is the entry's suggested fixes in its own order: the footnote
case first, because it reaches most of the first column and is the path
LI7 uses.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run

from docxkit._xml import BOOKMARK_NAME_RE, internal_links
from docxkit.citations import link_all, unlink_by_anchor


def _anchors(parts: dict[str, bytes], part: str) -> list[str]:
    return [a for a, _ in internal_links(parts[part].decode("utf-8"))]


def _names(parts: dict[str, bytes], part: str) -> set[str]:
    return set(BOOKMARK_NAME_RE.findall(parts[part].decode("utf-8")))


REFERENCES = (
    para(run("References"))
    + para(run("Kanbur, R. (2007). Poverty and distribution. Journal of "
               "Development Economics."))
    + para(run("Ravallion, M. (2016). The Economics of Poverty. Oxford "
               "University Press.")))


def _footnote(text: str, nid: int = 2) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main">'
            f'<w:footnote w:id="{nid}">{para(run(text))}</w:footnote>'
            "</w:footnotes>")


# ------------------------------------------- the footnote citation path --

def test_a_work_cited_ONLY_in_a_footnote_is_linked_there():
    """The path the tests never ran. A footnote is where a paper puts
    the citation it does not want in the sentence, so "no work is cited
    only in a footnote" was never a safe assumption."""
    parts = make_parts(
        para(run("Loneliness rises with age.")) + REFERENCES,
        footnotes=_footnote("The gradient is steeper still (Kanbur 2007)."))

    report = link_all(parts)

    assert _anchors(parts, "word/footnotes.xml"), report.format()
    assert "Kanbur2007txt" in _names(parts, "word/footnotes.xml"), \
        "the in-text end of the pair belongs where the mention is"
    assert "Kanbur2007" in _names(parts, "word/document.xml"), \
        "the entry keeps its own bookmark in the body"


def test_the_body_mention_wins_when_a_work_is_cited_in_both():
    """First mention, and the body comes first: a footnote mention is a
    later one, so it stays unlinked under the papers' convention."""
    parts = make_parts(
        para(run("Loneliness rises with age (Kanbur 2007).")) + REFERENCES,
        footnotes=_footnote("See also Kanbur (2007) on distribution."))

    link_all(parts)

    assert "Kanbur2007txt" in _names(parts, "word/document.xml")
    assert not _anchors(parts, "word/footnotes.xml"), \
        "the footnote's later mention was linked as well"


def test_the_footnote_splice_leaves_the_note_readable():
    """The `foot[m.end():]` splice is where the arithmetic mutants
    survived, which is only possible if nothing ran it."""
    from docxkit._xml import visible_text

    text = "The gradient is steeper still (Kanbur 2007), notably in ECA."
    parts = make_parts(para(run("Loneliness rises.")) + REFERENCES,
                       footnotes=_footnote(text))
    link_all(parts)

    assert visible_text(parts["word/footnotes.xml"].decode("utf-8")) == text


# ------------------------------------------------ _entry_keys, by value --

@pytest.mark.parametrize("entry,expected", [
    ("World Bank Group. (2024). World Development Report.",
     {"worldbankgroup_2024", "world_2024", "bank_2024", "group_2024",
      "worldbank_2024", "bankgroup_2024", "wbg_2024"}),
    ("Health Promotion Board (HPB). (2023). Annual review.",
     {"hpb_2023"}),
    ("United Nations. (2024). World Population Prospects.",
     {"unitednations_2024", "un_2024", "united_2024", "nations_2024"}),
])
def test_entry_keys_names_every_form_the_entry_answers_to(entry, expected):
    """The keys an entry can be FOUND by, stated rather than implied.
    A citation grammar that refuses free capitalised adjacency captures
    "World Bank (2025a)" as "Bank (2025a)", so the entry filed under
    "World Bank Group" has to answer to the word runs as well as to its
    initialism."""
    from docxkit._cite_build import _entry_keys
    from docxkit.citations import references

    refs = references([entry], heading=("References",))  # no heading: direct
    if not refs:                      # references() wants a section
        refs = references(["References", entry], heading=("References",))
    keys = _entry_keys(refs[0])
    assert expected <= keys, f"missing {sorted(expected - keys)}"


def _keys_for(entry: str) -> set[str]:
    from docxkit._cite_build import _entry_keys
    from docxkit.citations import references

    refs = references(["References", entry], heading=("References",))
    assert refs, f"not parsed as an entry: {entry!r}"
    return _entry_keys(refs[0])


def test_an_ALL_CAPS_lead_token_is_a_key_of_its_own():
    """"UNDP (United Nations Development Programme). (2025)." is cited
    "(UNDP 2025)". The parenthesised-acronym rule cannot supply that
    one — the parentheses here hold the expansion, not the acronym — so
    the lead token is its own rule, and the entry is unfindable without
    it.
    """
    keys = _keys_for("UNDP (United Nations Development Programme). (2025). "
                     "Human development report.")
    assert "undp_2025" in keys, sorted(keys)


def test_a_TWO_word_institution_answers_to_each_of_its_words():
    """The word-run rule has to start at two words, not three: the
    citation grammar refuses free capitalised adjacency, so "World Bank
    (2024)" is captured as "Bank (2024)" and the entry filed under
    "World Bank" has to answer to "Bank" alone.
    """
    keys = _keys_for("World Bank. (2024). World development report.")
    assert {"world_2024", "bank_2024", "worldbank_2024"} <= keys, sorted(keys)


# `if len(words) > 1:` mutated to `>= 1` is EQUIVALENT and left alive: a
# one-word surname entering the loop yields i=0, j=1, whose key is the
# surname's own — already there as `r.key` — and an initialism of one
# letter, which the `len(initials) >= 2` guard drops. Nothing changes.


def test_every_key_NAMES_something():
    """A key is a name and a year. One with an empty name answers to a
    citation with no author, which is not a thing — and it is what an
    off-by-one in the word-run bounds produces, silently, because the
    real keys are all still there beside it.
    """
    for entry in ("World Bank Group. (2024). World development report.",
                  "Kanbur, R. (2007). Poverty and distribution. Journal.",
                  "United Nations. (2024). World population prospects."):
        for key in _keys_for(entry):
            assert key.rsplit("_", 1)[0], f"{key!r} names nobody ({entry})"


# --------------------------------------------- unlink_by_anchor refusals --

LEGACY = (
    '<w:p><w:hyperlink w:anchor="id.abc123">'
    '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
    "<w:t>Kanbur (2007)</w:t></w:r></w:hyperlink>"
    '<w:r><w:t xml:space="preserve"> and others</w:t></w:r></w:p>'
    '<w:p><w:bookmarkStart w:id="9" w:name="id.abc123"/>'
    "<w:r><w:t>Kanbur, R. (2007).</w:t></w:r>"
    '<w:bookmarkEnd w:id="9"/></w:p>')


def test_unlink_by_anchor_unwraps_the_link_and_keeps_the_words():
    from docxkit._xml import visible_text

    out, links, marks = unlink_by_anchor(LEGACY, r"^id\.")

    assert (links, marks) == (1, 1)
    assert visible_text(out) == visible_text(LEGACY)
    assert "<w:hyperlink" not in out
    assert 'w:name="id.abc123"' not in out


def test_unlink_by_anchor_leaves_a_NON_matching_anchor_alone():
    out, links, marks = unlink_by_anchor(LEGACY, r"^ref_")
    assert (links, marks) == (0, 0)
    assert out == LEGACY


def test_unlink_by_anchor_handles_the_FIELD_form_too():
    """A Google export writes some links as fldChar HYPERLINK fields,
    and an element-only pass leaves those in place — where they
    silently veto link_all's entry back-links."""
    from docxkit._xml import visible_text

    field = (
        "<w:p>"
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l "id.abc123" '
        "</w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
        "<w:t>Kanbur (2007)</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')

    out, links, _ = unlink_by_anchor(field, r"^id\.")

    assert links == 1
    assert visible_text(out) == "Kanbur (2007)"
    assert "fldChar" not in out and "instrText" not in out


# ------------------------------------------- the collision and the undo --

def test_two_entries_with_the_SAME_surname_and_year_get_distinct_names():
    """`_dedup_name`'s path, which nothing ran. A collision does not
    merely look untidy: two entries sharing one bookmark means every
    link to it lands on whichever Word finds first."""
    parts = make_parts(
        para(run("Both agree (Kanbur 2007) and (Ravallion 2016)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal of Development."))
        + para(run("Kanbur, R. (2007). Distribution. Another Journal.")))

    link_all(parts)

    entries = sorted(n for n in _names(parts, "word/document.xml")
                     if n.startswith("Kanbur") and not n.endswith("txt"))
    assert len(entries) == 2, (
        f"the two entries share one bookmark: {entries}")
    assert entries[1].startswith(entries[0]), (
        f"the second should be a suffixed form of the first: {entries}")


def test_a_back_link_whose_target_never_appeared_is_UNDONE():
    """The undo path, never run before. A citation occurring twice in
    ONE paragraph is ambiguous, so the in-text wrap refuses — and
    shipping the entry's back-link anyway leaves `Kanbur2007txt`
    pointing at nothing. Silent: the anchor resolves nowhere, the words
    read correctly, and only an audit finds it."""
    parts = make_parts(
        para(run("As Kanbur (2007) says, and again Kanbur (2007) says."))
        + REFERENCES)

    report = link_all(parts)

    names = _names(parts, "word/document.xml")
    assert "Kanbur2007" in names, "the entry keeps its own bookmark"
    assert "Kanbur2007txt" not in names, "the in-text end was never wrapped"
    assert not _anchors(parts, "word/document.xml"), (
        "a link survived, pointing at a bookmark that does not exist")
    assert any("back-link removed" in n for n in report.skipped), (
        f"the undo was not reported: {report.skipped}")
    assert "Kanbur2007" not in report.backlinked
