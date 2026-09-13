"""`_cite_audit`'s edges: the survivors of the 2026-09-12 fresh sweep.

199 mutants survived a three-file harness. Most sat in rules judged by a
THRESHOLD or a PLACE, the majority a back-link finding waits for or the
paragraph or gap a bookmark is filed under, and no fixture had put a number
on the boundary. The rest were loop exits nobody reached twice, guards
nobody tripped, and message excerpts nobody quoted.
"""
from __future__ import annotations

import pytest

from docxkit._cite_audit import (
    _audit_findings,
    _doubled_links,
    _Finding,
    _foreign_owner,
    _name_runs,
    _no_backlink,
    _off_link,
    _reached,
    _span_findings,
    balanced_span,
    unbalanced_span,
)
from docxkit._cite_grammar import Reference
from docxkit._xml import PARA_RE


def _where(i: int) -> str:
    return {-1: "body", -2: "fn", -3: "en"}.get(i) or f"¶{i + 1}"


# --- _no_backlink: the majority it waits for --------------------------------


def _home(n: int, linked: int) -> tuple[dict[str, int],
                                        dict[str, list[tuple[int, str]]]]:
    """`n` entries at paragraphs 300 and up; the first `linked` link home
    from their own paragraph. The indices are rebuilt through `int(str())`,
    so an identity test cannot pass where equality does."""
    ref_marks = {f"K{j:02d}2001": 300 + j for j in range(n)}
    links = {f"{key}txt": [(int(str(at)), "Back")]
             for j, (key, at) in enumerate(ref_marks.items()) if j < linked}
    return ref_marks, links


@pytest.mark.parametrize(("n", "linked", "report"), [
    (4, 3, True),       # at the floor of three
    (4, 2, False),      # one below it
    (9, 5, True),       # at (9 + 1) // 2
    (9, 4, False),      # one below
    (9, 6, True),       # above it
    (10, 5, True),      # (10 + 1) // 2 is 5, where a true half is 5.5
])
def test_REF_WITHOUT_BACKLINK_waits_for_the_lists_own_majority(
        n, linked, report):
    ref_marks, links = _home(n, linked)

    found = _no_backlink(ref_marks, links, _where, skip=lambda k: False)

    assert [f.subject for f in found] == (
        sorted(ref_marks)[linked:] if report else [])


def test_a_back_link_counts_only_from_the_ENTRYS_OWN_paragraph():
    """Links to `K032001txt` from paragraphs 290 and 310 are somebody's
    prose, not the entry at 303 linking home."""
    ref_marks, links = _home(4, 3)
    links["K032001txt"] = [(290, "x"), (310, "y")]

    found = _no_backlink(ref_marks, links, _where, skip=lambda k: False)

    assert [f.subject for f in found] == ["K032001"]


# --- _reached: the PLACE a bookmark is filed under ---------------------------


def _bm(name: str, bid: int) -> str:
    return (f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
            f'<w:bookmarkEnd w:id="{bid}"/>')


def test_reach_is_shared_within_one_PLACE_and_never_across_places():
    """V before the first paragraph and X in the next gap stand alone. Y
    shares a paragraph, and Z a gap, with a linked `_Ref`, so only those
    are reached, however paragraph and gap keys are spelled. After W's
    paragraph comes a gap whose linked `_Ref4` starts a step past the
    paragraph's end: W is reached only if it is filed under that gap."""
    doc = ("<w:body>" + _bm("V", 1)
           + "<w:p>" + _bm("_Ref1", 2) + "<w:r><w:t>one</w:t></w:r></w:p>"
           + _bm("X", 3)
           + "<w:p>" + _bm("Y", 4) + _bm("_Ref2", 5)
           + "<w:r><w:t>two</w:t></w:r></w:p>"
           + _bm("Z", 6) + _bm("_Ref3", 7)
           + "<w:p>" + _bm("W", 8) + "<w:r><w:t>three</w:t></w:r></w:p>"
           + '<w:bookmarkEnd w:id="99"/>' + _bm("_Ref4", 9)
           + "</w:body>")
    paras = list(PARA_RE.finditer(doc))
    links = {"_Ref1": [(0, "a")], "_Ref2": [(1, "b")], "_Ref3": [(2, "c")],
             "_Ref4": [(2, "d")]}

    assert (_reached(doc, paras, links)
            == {"_Ref1", "Y", "_Ref2", "Z", "_Ref3", "_Ref4"})


# --- the bracket rules -------------------------------------------------------


def test_unbalanced_span_reads_the_WHOLE_label_before_it_answers():
    assert unbalanced_span("((x)") == "("


@pytest.mark.parametrize(("text", "at", "end", "want"), [
    ("see ((x) today", 4, 8, "(x)"),            # an extra "(" at the start
    ("a (a))b ok", 2, 7, None),                 # a ")" it cannot place
    ("(a))b) tail", 0, 5, None),                # ...with a ")" after it too
    ("Modigliani (1986x", 0, 16, None),         # nothing to extend over
    ("xModigliani (1986) says", 1, 17, "Modigliani (1986)"),   # an odd end
])
def test_balanced_span_on_the_shapes_it_can_and_cannot_repair(
        text, at, end, want):
    assert balanced_span(text, at, end) == want


# --- _off_link: a marker meeting its link at an edge -------------------------


@pytest.mark.parametrize(("text", "marker", "label", "how"), [
    ("Adams (2001); Brown (2002) wrote", (12, 26), (0, 12),
     "runs 14 characters past its link, over '; Brown (2002)'"),
    ("As argued by Adams (2001)", (0, 13), (13, 25),
     "starts 13 characters early, over 'As argued by '"),
    ("Earlier words here. Then Adams (2001).", (5, 5), (25, 37),
     "sits 20 characters before its link"),
])
def test_off_link_reads_a_marker_that_meets_its_link_at_an_EDGE(
        text, marker, label, how):
    assert _off_link(text, *marker, *label) == how


def test_off_link_quotes_40_characters_of_what_the_marker_covers():
    before, after = "a" * 50, "b" * 50
    text = before + "Adams (2001)" + after

    assert (_off_link(text, 0, 62, 50, 62)
            == f"starts 50 characters early, over {before[:40]!r}")
    assert (_off_link(text, 50, 112, 50, 62)
            == f"runs 50 characters past its link, over {after[:40]!r}")


# --- small readers -----------------------------------------------------------


def test_doubled_links_tolerates_a_field_or_link_CLOSED_from_elsewhere():
    """A field begun in the paragraph before ends in this one, and a stray
    `</w:hyperlink>` can outlive its opening. Nothing is open to close,
    and a scan past the bottom of the stack raised."""
    assert _doubled_links(
        '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>') == []
    assert _doubled_links("<w:p></w:hyperlink></w:p>") == []


def test_name_runs_start_AFRESH_after_the_year():
    assert "worldbank" in _name_runs("ref_2020_world_bank")


def test_foreign_owner_is_NOBODY_when_two_entries_answer():
    entries = [Reference(text="Smith, A. (2020).", surname="Smith",
                         year="2020", index=5),
               Reference(text="Jones, B. (2020).", surname="Jones",
                         year="2020", index=6)]

    assert _foreign_owner("ref_smith_jones_2020", entries) is None


# --- _span_findings ----------------------------------------------------------


def test_span_findings_reads_on_past_a_BROKEN_and_a_BALANCED_link():
    """Called without texts too, which is the default."""
    links = {"Aaa2001": [(0, "Aaa (2001")],
             "Bbb2002": [(1, "Bbb (2002)"), (2, "Bbb (2002")]}

    found = _span_findings(links, {"Bbb2002": 3}, _where)

    assert [f.subject for f in found] == ["Bbb2002"]


def test_span_findings_says_WHICH_WAY_off_a_label_it_can_find_once():
    trim = "see (Klimaviciute and Pestieau 2023) here"
    twice = "Modigliani (1986) and then Modigliani (1986 again"
    long = "Organisation for Economic Co-operation and Development (2019"
    links = {"Pes2023": [(0, "Pestieau 2023)")],
             "Mod1986": [(1, "Modigliani (1986")],
             "Oecd2019": [(2, long)]}
    texts = [trim, twice, "see " + long + " today"]
    marks = {"Pes2023": 9, "Mod1986": 9, "Oecd2019": 9}

    found = {f.subject: f for f in _span_findings(links, marks, _where,
                                                  texts)}

    assert "reached past its mention" in found["Pes2023"].message
    assert found["Pes2023"].extra == "Pestieau 2023"
    assert "reached past its mention" in found["Mod1986"].message
    assert found["Mod1986"].extra == ""
    assert f'"{long[:48]}"' in found["Oecd2019"].message


# --- the whole audit, where a rule reads the document ------------------------


def P(inner: str) -> str:
    return f"<w:p>{inner}</w:p>"


def R(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def _link(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}"><w:r>'
            f'<w:t xml:space="preserve">{label}</w:t></w:r></w:hyperlink>')


def _mark(name: str, bid: int, inner: str = "") -> str:
    from docxkit.citations import bookmark
    return bookmark(name, bid, inner)


def _field(anchor: str, label: str) -> str:
    from docxkit.citations import hyperlink_field
    return hyperlink_field(anchor, label)


FILLER = "".join(P(R(f"Filler {i}.")) for i in range(5))


def _entry(key: str, bid: int, extra: str = "") -> str:
    """A reference entry wrapped in its own bookmark, `Adams2001`."""
    return P(_mark(key, bid, R(f"{key[:-4]}, A. ({key[-4:]}). A title."))
             + extra)


def _parts(body: str, *, footnotes: str = "",
           endnotes: str = "") -> dict[str, bytes]:
    parts = {"word/document.xml": ("<w:document><w:body>" + body
                                   + "</w:body></w:document>").encode()}
    if footnotes:
        parts["word/footnotes.xml"] = ('<w:footnotes><w:footnote w:id="1">'
                                       + footnotes
                                       + "</w:footnote></w:footnotes>"
                                       ).encode()
    if endnotes:
        parts["word/endnotes.xml"] = ('<w:endnotes><w:endnote w:id="1">'
                                      + endnotes
                                      + "</w:endnote></w:endnotes>").encode()
    return parts


def _audit(parts: dict[str, bytes]) -> tuple[list[_Finding], dict[str, int]]:
    return _audit_findings(parts)


def _kinds(parts: dict[str, bytes], kind: str) -> list[_Finding]:
    return [f for f in _audit(parts)[0] if f.kind == kind]


def test_REF_WITHOUT_BACKLINK_skips_the_UNCITED_and_counts_the_REACHED():
    """A to D are cited and A to C link home. D does not, though a linked
    `_Ref` beside its entry reaches it; E is cited by nobody. D is the
    finding, and E is left out, an entry with a reason for no link."""
    cites = "".join(P(R("see ") + _mark(f"{k}txt", 10 + n, _link(k, k)))
                    for n, k in enumerate(("Adams2001", "Brown2002",
                                           "Cole2003", "Dean2004")))
    body = (FILLER + cites + P(R("as ") + _link("_Ref7", "above"))
            + P(R("References"))
            + _entry("Adams2001", 20, _field("Adams2001txt", " back"))
            + _entry("Brown2002", 21, _field("Brown2002txt", " back"))
            + _entry("Cole2003", 22, _field("Cole2003txt", " back"))
            + _entry("Dean2004", 23, _mark("_Ref7", 30))
            + _entry("Evans2005", 24))

    found = _kinds(_parts(body), "REF WITHOUT BACKLINK")

    assert [f.subject for f in found] == ["Dean2004"]


# --- code review, 2026-09-13 -------------------------------------------------


def test_an_entry_whose_marker_Word_HOISTED_still_links_home():
    """Word moves a marker at a paragraph's head out to body level, where
    the audit files it at -1, and no link sits in paragraph -1: every such
    entry read as REF WITHOUT BACKLINK with its link home right there. The
    marker is the paragraph BELOW it, as `_reached` and MISPLACED MARKER
    already read it."""
    cites = "".join(P(R("see ") + _mark(f"{k}txt", 10 + n, _link(k, k)))
                    for n, k in enumerate(("Adams2001", "Brown2002",
                                           "Cole2003", "Dean2004")))
    hoisted = _mark("Dean2004", 23) + P(R("Dean, A. (2004). A title.")
                                        + _field("Dean2004txt", " back"))
    body = (FILLER + cites + P(R("References"))
            + _entry("Adams2001", 20, _field("Adams2001txt", " back"))
            + _entry("Brown2002", 21, _field("Brown2002txt", " back"))
            + _entry("Cole2003", 22, _field("Cole2003txt", " back"))
            + hoisted)

    assert _kinds(_parts(body), "REF WITHOUT BACKLINK") == []


def test_off_link_reads_what_a_marker_APART_from_its_link_covers():
    """One space from the link and over another citation: only the gap was
    read, and a space is no words."""
    text = "Jones (2019) Smith (2020) argue"

    assert (_off_link(text, 0, 12, 13, 25)
            == "covers 'Jones (2019)', 1 characters before its link")
    assert (_off_link(text, 26, 31, 13, 25)
            == "covers 'argue', 1 characters after its link")
    assert _off_link(text, 12, 12, 13, 25) is None, "empty, beside it"


def test_an_entry_REACHED_through_a_Word_anchor_is_not_an_orphan():
    body = (FILLER + P(R("see ") + _mark("Adams2001txt", 10,
                                         _link("Adams2001", "Adams")))
            + P(R("as ") + _link("_Ref9", "below"))
            + P(R("References"))
            + _entry("Adams2001", 20)
            + _entry("Brown2002", 21, _mark("_Ref9", 31)))

    assert _kinds(_parts(body), "ORPHAN REF") == []


def test_the_bookmark_findings_come_in_DOCUMENT_order_and_all_of_them():
    """`Zzz1999` names a year no entry carries and sits before the list;
    `Adams2001` is cited by its marker and linked by nothing. Sorted by
    name the orphan would come first, and stopping at the stale one would
    drop it."""
    body = (FILLER + P(R("see ") + _mark("Adams2001txt", 10, R("Adams")))
            + P(R("References")) + _mark("Zzz1999", 40)
            + _entry("Adams2001", 20))

    found = [(f.kind, f.subject) for f in _audit(_parts(body))[0]
             if f.kind in ("STALE BOOKMARK", "ORPHAN REF")]

    assert found == [("STALE BOOKMARK", "Zzz1999"),
                     ("ORPHAN REF", "Adams2001")]


def test_with_NO_reference_list_nothing_is_stale():
    body = FILLER + P(_mark("Adams2001", 20, R("Adams, A. (2001).")))

    assert _kinds(_parts(body), "STALE BOOKMARK") == []


def test_the_MENTION_counts_add_up_and_later_mentions_stay_QUIET():
    """Seven mentions: four linked, one later mention of a linked work, and
    two of works linked nowhere. 7 - 2 - 1 is 4, where + 2 gives 8."""
    keys = ("Adams2001", "Brown2002", "Cole2003", "Dean2004")
    body = (FILLER
            + "".join(P(R("Work pays (") + _link(k, f"{k[:-4]} {k[-4:]}")
                        + R(").")) for k in keys)
            + P(R("Again (Adams 2001).")) + P(R("Also (Evans 2005)."))
            + P(R("And (Fox 2006).")) + P(R("References"))
            + "".join(_entry(k, 20 + n) for n, k in enumerate(
                (*keys, "Evans2005", "Fox2006"))))

    findings, stats = _audit(_parts(body))

    assert (stats["mentions"], stats["unlinked"], stats["later_unlinked"],
            stats["mentions_linked"]) == (7, 2, 1, 4)
    assert not [f for f in findings if f.kind == "LATER-MENTION UNLINKED"]


def test_a_PLAIN_mention_after_a_linked_one_in_one_group_is_counted():
    body = (FILLER + P(R("(") + _link("Adams2001", "Adams 2001")
                       + R("; Evans 2005)."))
            + P(R("References"))
            + _entry("Adams2001", 20) + _entry("Evans2005", 21))

    assert _audit(_parts(body))[1]["unlinked"] == 1


def test_a_citation_in_a_FOOTNOTE_is_a_mention():
    body = (FILLER + P(R("Body.")) + P(R("References"))
            + _entry("Evans2005", 20))

    stats = _audit(_parts(body, footnotes=P(R("See (Evans 2005)."))))[1]

    assert stats["mentions"] == 1


def test_ENDNOTES_are_read_when_there_are_no_footnotes():
    parts = _parts(FILLER + P(R("Body.")),
                   endnotes=P(R("See ") + _link("Nowhere2020", "Nowhere")))

    assert [f.subject for f in _kinds(parts, "BROKEN LINK")] == [
        "Nowhere2020"]


def test_MISPLACED_MARKER_when_the_list_OPENS_the_document():
    """The entries start at paragraph 1. Counting two back from there
    wraps to the last paragraph and puts every marker in the prose."""
    body = (P(R("References"))
            + P(_mark("Brown2002", 20, R("Adams, A. (2001). A title.")))
            + P(_mark("Adams2001", 21, R("Brown, B. (2002). A title."))))

    found = _kinds(_parts(body), "MISPLACED MARKER")

    assert sorted(f.subject for f in found) == ["Adams2001", "Brown2002"]


def test_MISPLACED_MARKER_reads_on_past_a_marker_in_the_PROSE():
    body = (P(R("see ") + _mark("Cole2003", 30, R("Cole (2003)")))
            + P(R("References"))
            + P(_mark("Brown2002", 20, R("Adams, A. (2001). A title.")))
            + P(_mark("Adams2001", 21, R("Brown, B. (2002). A title.")))
            + P(R("Cole, C. (2003). A title.")))

    found = _kinds(_parts(body), "MISPLACED MARKER")

    assert sorted(f.subject for f in found) == ["Adams2001", "Brown2002"]


def test_MARKER_OFF_LINK_skips_a_REPEATED_anchor_and_reads_past_the_rest():
    """A paragraph linking Adams twice cannot say which link owns the
    marker. One that links a table first, then Brown with its marker in
    place, still reaches Cole's marker left at the paragraph's end."""
    repeated = P(_link("Adams2001", "Adams (2001)") + R(" and ")
                 + _link("Adams2001", "Adams (2001)")
                 + R(" again, later on.") + _mark("Adams2001txt", 10))
    onward = P(_link("Other", "a table") + R(", ")
               + _mark("Brown2002txt", 11, _link("Brown2002", "Brown (2002)"))
               + R(", ") + _link("Cole2003", "Cole (2003)")
               + R(" shows, and the paragraph runs on.")
               + _mark("Cole2003txt", 12))

    assert _kinds(_parts(FILLER + repeated), "MARKER OFF LINK") == []
    assert [f.subject for f in _kinds(_parts(FILLER + onward),
                                      "MARKER OFF LINK")] == ["Cole2003txt"]


def test_MARKER_OFF_LINK_in_a_FOOTNOTE_says_fn():
    note = P(_link("Adams2001", "Adams (2001)") + R(" shows, and runs on.")
             + _mark("Adams2001txt", 10))

    (found,) = _kinds(_parts(FILLER, footnotes=note), "MARKER OFF LINK")

    assert "(fn)" in found.message


def test_SELF_LINK_names_its_PARAGRAPH_or_its_note():
    body = (P(R("one")) + P(R("two")) + P(R("three"))
            + P(_mark("Brown2002", 13, R("Brown. ")
                      + _field("Brown2002", "back")))
            + P(_mark("Brown2002txt", 14, R("B."))))
    note = P(_mark("Cole2003", 16, R("C. ") + _field("Cole2003", "back")))

    (body_link,) = _kinds(_parts(body), "SELF LINK")
    (note_link,) = _kinds(_parts(P(_mark("Cole2003txt", 15, R("C."))),
                                 footnotes=note), "SELF LINK")

    assert "(¶4)" in body_link.message
    assert "no bookmark carries yet" not in body_link.message
    assert "(fn)" in note_link.message
