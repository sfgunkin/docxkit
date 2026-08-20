"""renumber.shift — exhibit numbers move everywhere or nowhere.

The traps pinned here: single-pass shifting (5,6 -> 6,7 without the
double-shift a sequential replace produces), digits hidden by run
fragmentation, inflected prose labels, and the range mentions that must
be REFUSED rather than half-shifted.
"""
from __future__ import annotations

import pytest
from conftest import NS, note, notes, para, run

from docxkit._xml import visible_text
from docxkit.errors import AnchorError
from docxkit.renumber import (
    audit,
    footnotes,
    numbers_in_order,
    remap,
    remap_parts,
    shift,
)
from docxkit.tables import read_all


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def caption(n: int, label: str = "Table") -> str:
    return para(run(f"{label} {n}. Something about it"))


def text_of_doc(xml: str) -> str:
    import re

    from docxkit._xml import visible_text
    return " | ".join(visible_text(m.group(0)) for m in
                      re.finditer(r"<w:p\b.*?</w:p>", xml, re.DOTALL))


def test_audit_catches_captions_out_of_document_order():
    """THE DSI SHAPE. Two tables numbered one past the highest so far went
    into a section that PRECEDES the one already holding those numbers, so the
    captions read 1, 2, 11, 12, 9, 10 — every number unique, every reference
    resolving, and the sequence backwards where the sections meet. Uniqueness
    is what a build asserts; order is what a reader sees."""
    xml = doc("".join(caption(n) for n in (1, 2, 11, 12, 9, 10)))
    assert numbers_in_order(xml, "Table") == [1, 2, 11, 12, 9, 10]
    problems = audit(xml, "Table")
    assert any("not in document order" in p for p in problems)
    assert any("not 1..6" in p for p in problems)


def test_audit_catches_a_DUPLICATE_number():
    """`sorted(nums) != list(range(1, n + 1))`, not `>`: a duplicate
    sorts BELOW the run it should be — [1, 1, 2] against [1, 2, 3] — so
    an order comparison reports the gaps and misses the repeats. Two
    captions numbered 1 is what a copied section leaves, and every
    reference to "Table 1" then resolves to whichever comes first."""
    xml = doc("".join(caption(n) for n in (1, 1, 2)))

    problems = audit(xml, "Table")

    assert any("not 1..3" in p for p in problems), problems


def test_a_two_digit_exhibit_is_not_a_suffixed_scheme():
    """`\\w` includes digits, so the suffix class used to match the second
    digit of its own number: `\\d+` gave one back and "Table 11" read as
    "Table 1" with a suffix. Every exhibit from 10 upwards was then reported
    as a numbering scheme the module refuses to touch — in every paper long
    enough to have ten of them."""
    xml = doc("".join(caption(n) for n in (10, 11, 12))
              + para(run("See Table 11 and also Table 12.")))
    out, report = shift(xml, "Table", frm=10, by=3)
    assert not report.flagged
    assert numbers_in_order(out, "Table") == [13, 14, 15]


@pytest.mark.parametrize("phrase", [
    "See Table 1A for the detail.",
    "See Table 1.1 for the detail.",
    "See Tables 5–7 for the detail.",
    "See Tables 5 and 6 for the detail.",
])
def test_schemes_and_ranges_are_still_flagged(phrase):
    xml = doc(caption(1) + caption(5) + para(run(phrase)))
    _out, report = shift(xml, "Table", frm=1, by=10)
    assert report.flagged, phrase


def test_audit_is_silent_on_sound_numbering():
    xml = doc("".join(caption(n) for n in (1, 2, 3))
              + para(run("As Table 2 shows.")))
    assert audit(xml, "Table") == []


def test_audit_reports_a_mention_no_caption_defines():
    xml = doc(caption(1) + para(run("But see Table 4 for the detail.")))
    assert any("mentions 4" in p for p in audit(xml, "Table"))


def test_remap_swaps_two_pairs_in_one_pass():
    """A reorder needs a permutation, and no sequence of shifts expresses one.
    Done as sequential replacements, 9->11 would then be caught by 11->9 and
    come back; every replacement here is computed from the ORIGINAL number."""
    xml = doc("".join(caption(n) for n in (9, 10, 11, 12))
              + para(run("Table 11 first, then Table 9.")))
    out, report = remap(xml, "Table", {9: 11, 10: 12, 11: 9, 12: 10})
    assert numbers_in_order(out, "Table") == [11, 12, 9, 10]
    assert "Table 9 first, then Table 11." in text_of_doc(out)
    assert report.mentions == 6


def test_remap_moves_bookmarks_and_anchors_with_the_number():
    xml = doc(
        '<w:p><w:bookmarkStart w:id="1" w:name="Table9"/>'
        f'{run("Table 9. Dispersion")}</w:p>'
        '<w:p><w:hyperlink w:anchor="Table9">'
        f'{run("Table 9")}</w:hyperlink></w:p>')
    out, report = remap(xml, "Table", {9: 11})
    assert 'w:name="Table11"' in out and 'w:anchor="Table11"' in out
    assert 'w:name="Table9"' not in out and 'w:anchor="Table9"' not in out
    assert report.bookmarks == 1 and report.anchors == 1


def test_remap_moves_hyperlink_field_links_too():
    """crossrefs.link writes internal links as HYPERLINK FIELDS, not w:anchor
    attributes. Renaming the bookmarks without the fields leaves every link
    pointing at whichever exhibit now holds the old name — and under a
    permutation the set of names is unchanged, so nothing dangles, no audit
    reports a broken anchor, and the reader is simply sent to the wrong
    table."""
    xml = doc(
        '<w:p><w:bookmarkStart w:id="1" w:name="Table9txt"/>'
        f'{run("As Table 9 shows")}</w:p>'
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText>HYPERLINK \\l "Table9txt" \\h</w:instrText></w:r>'
        f'{run("Table 9")}'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        f'{run(". Dispersion")}</w:p>')
    out, report = remap(xml, "Table", {9: 11})
    assert 'HYPERLINK \\l "Table11txt"' in out
    assert 'Table9txt' not in out
    assert report.fields == 1 and report.bookmarks == 1


def test_remap_parts_renumbers_the_footnotes_too():
    """A mention lives wherever prose does. Renumbering document.xml alone left
    DSI's footnote 7 saying «в таблице 9» after that table had become 11 — and
    nothing dangled, because 9 still existed elsewhere. A wrong-but-valid
    reference is exactly what no dangling-reference check can see."""
    from docxkit.renumber import audit_parts, remap_parts
    body = doc(caption(1) + caption(2))
    foot = (f"<w:footnotes {NS}><w:footnote w:id=\"7\">"
            f"{para(run('as Table 1 shows'))}</w:footnote></w:footnotes>")
    parts = {"word/document.xml": body.encode("utf-8"),
             "word/footnotes.xml": foot.encode("utf-8")}
    report = remap_parts(parts, "Table", {1: 2, 2: 1})
    assert "Table 2 shows" in parts["word/footnotes.xml"].decode("utf-8")
    assert report.mentions == 3
    assert audit_parts(parts, "Table") == [
        "Table: captions are not in document order: [2, 1]"]


def test_audit_parts_sees_a_footnote_mention_with_no_caption():
    from docxkit.renumber import audit_parts
    body = doc(caption(1))
    foot = (f"<w:footnotes {NS}><w:footnote w:id=\"7\">"
            f"{para(run('but see Table 9'))}</w:footnote></w:footnotes>")
    parts = {"word/document.xml": body.encode("utf-8"),
             "word/footnotes.xml": foot.encode("utf-8")}
    assert any("footnotes.xml mentions 9" in p
               for p in audit_parts(parts, "Table"))


def test_remap_refuses_a_mapping_that_collides():
    xml = doc(caption(9) + caption(10))
    with pytest.raises(AnchorError):
        remap(xml, "Table", {9: 10})


def test_captions_and_mentions_from_frm_shift_once():
    xml = doc(caption(5) + caption(6)
              + para(run("As Table 5 shows, and Table 6 confirms, "
                         "Table 4 stays.")))
    out, report = shift(xml, "Table", frm=5)
    text = text_of_doc(out)
    assert "Table 6. " in text and "Table 7. " in text
    assert "As Table 6 shows, and Table 7 confirms, Table 4 stays." in text
    assert report.mentions == 4
    assert not report.flagged


def test_a_fragmented_mention_still_shifts():
    # "Table 12" stored as three runs, the digits split across two
    body = ("<w:p><w:r><w:t>see Table </w:t></w:r>"
            "<w:r><w:t>1</w:t></w:r><w:r><w:t>2</w:t></w:r>"
            "<w:r><w:t> here</w:t></w:r></w:p>")
    out, report = shift(doc(body), "Table", frm=3)
    assert "see Table 13 here" in text_of_doc(out)
    assert report.mentions == 1


def test_ten_is_not_one():
    xml = doc(para(run("Table 1 and also Table 10.")))
    out, _ = shift(xml, "Table", frm=10)
    assert "Table 1 and also Table 11." in text_of_doc(out)


def test_inflected_russian_prose_keeps_its_case_ending():
    xml = doc(para(run("Таблица 4. Итоги"))
              + para(run("как показано в таблице 4 выше")))
    out, report = shift(xml, "Таблица", frm=4)
    text = text_of_doc(out)
    assert "Таблица 5. " in text
    assert "в таблице 5 выше" in text
    assert report.mentions == 2


def test_bookmarks_anchors_and_ref_fields_follow():
    body = (
        '<w:p><w:bookmarkStart w:id="1" w:name="Table5"/>'
        + run("Table 5. Cap") + '<w:bookmarkEnd w:id="1"/></w:p>'
        + '<w:p><w:bookmarkStart w:id="2" w:name="Table5txt"/>'
          '<w:hyperlink w:anchor="Table5">' + run("Table 5")
        + "</w:hyperlink>"
          '<w:bookmarkEnd w:id="2"/>'
          '<w:r><w:instrText xml:space="preserve"> REF Table5 \\h '
          "</w:instrText></w:r></w:p>")
    out, report = shift(doc(body), "Table", frm=5)
    assert 'w:name="Table6"' in out and 'w:name="Table6txt"' in out
    assert 'w:anchor="Table6"' in out
    assert " REF Table6 \\h " in out
    assert "Table5" not in out
    assert (report.bookmarks, report.anchors, report.fields) == (2, 1, 1)


def test_appendix_prefix_shifts_its_own_sequence_only():
    xml = doc(caption(2) + para(run("Table A2. Extra"))
              + para(run("see Table A2 and Table 2")))
    out, _ = shift(xml, "Table", frm=2, prefix="A")
    text = text_of_doc(out)
    assert "Table A3. Extra" in text
    assert "see Table A3 and Table 2" in text
    assert "Table 2. " in text                    # main sequence untouched


def test_ranges_are_flagged_not_half_shifted():
    xml = doc(para(run("Tables 5–7 report the results.")))
    out, report = shift(xml, "Table", frm=5)
    assert "Tables 5–7 report" in text_of_doc(out)     # untouched
    assert report.mentions == 0
    assert report.flagged and "5–7" in report.flagged[0]


def test_lists_are_flagged_not_half_shifted():
    xml = doc(para(run("Tables 5 and 6 agree.")))
    out, report = shift(xml, "Table", frm=5)
    text = text_of_doc(out)
    assert "Tables 5 and 6 agree." in text
    assert report.mentions == 0
    assert report.flagged


def test_negative_shift_closes_a_gap():
    xml = doc(caption(4) + caption(5) + para(run("see Table 4 and then "
                                                 "read Table 5")))
    out, _ = shift(xml, "Table", frm=4, by=-1)
    text = text_of_doc(out)
    assert "Table 3. " in text and "Table 4. " in text
    assert "see Table 3 and then read Table 4" in text


def test_a_shift_that_collides_captions_refuses():
    xml = doc(caption(3) + caption(4))
    with pytest.raises(AnchorError, match="collide"):
        shift(xml, "Table", frm=4, by=-1)


def test_by_zero_refuses():
    with pytest.raises(AnchorError, match="by=0"):
        shift(doc(caption(1)), "Table", frm=1, by=0)


def test_tables_content_is_untouched():
    tbl = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>5</w:t></w:r></w:p>"
           "</w:tc></w:tr></w:tbl>")
    xml = doc(caption(5) + tbl)
    out, _ = shift(xml, "Table", frm=5)
    assert read_all(out)[0].rows == [["5"]]       # a bare cell "5" is data


# ------------------------------------ shift's guards, stated as values ----
#
# The first mutation run on this module (2026-08-17) left 11 survivors in
# `shift`. The tests above drive what it DOES; these are the refusals and
# the edges, which nothing had asked about.

def _captions(*lines: str) -> str:
    return doc("".join(para(run(line)) for line in lines))


def test_shifting_down_to_ONE_is_allowed():
    """The guard refuses numbers below 1, and 1 is a number. Table 2
    becoming Table 1 is the ordinary case for removing Table 1, and a
    guard written `<= 1` refuses exactly it."""
    xml = _captions("Table 2. Second.", "Table 3. Third.")

    out, _report = shift(xml, "Table", frm=2, by=-1)

    assert "Table 1. Second." in text_of_doc(out)
    assert "Table 2. Third." in text_of_doc(out)


def test_shifting_to_ZERO_is_refused():
    with pytest.raises(AnchorError, match="below 1"):
        shift(_captions("Table 1. First."), "Table", frm=1, by=-1)


def test_shift_options_are_KEYWORD_only():
    """`frm` and `by` decide which exhibits move and in which direction.
    Passed by position they read as bare numbers at the call site, and
    the two are trivially swappable."""
    with pytest.raises(TypeError):
        shift(_captions("Table 1. First."), "Table", 1)  # type: ignore[call-arg]


def test_a_MAIN_sequence_caption_before_an_appendix_one_is_skipped():
    """With `prefix="A"` the main sequence is not this shift's business,
    and the scan has to walk PAST it rather than stop: a paper numbers
    its main tables before its appendix ones, so the first caption it
    meets is always the wrong one.
    """
    xml = _captions("Table 1. Main.", "Table A2. Appendix.",
                    "Table A3. More.")

    out, _report = shift(xml, "Table", frm=2, prefix="A")

    text = text_of_doc(out)
    assert "Table 1. Main." in text, "the main sequence moved"
    assert "Table A3. Appendix." in text and "Table A4. More." in text, text


def test_a_collision_names_both_sets_of_numbers():
    """Removing a caption's number without removing the caption puts two
    exhibits on one number, and the refusal has to say which."""
    xml = _captions("Table 1. First.", "Table 2. Second.")

    with pytest.raises(AnchorError, match="collide"):
        shift(xml, "Table", frm=2, by=-1)


def test_a_RANGE_mention_does_not_stop_the_scan_of_its_paragraph():
    """"Tables 5–7" is flagged for the author rather than half-shifted,
    and the scan carries on: a sentence that mentions a range usually
    mentions single exhibits too, and stopping there leaves them at
    their old numbers with nothing to say so."""
    xml = doc(para(run("See Tables 5-7 and also Table 9 for detail.")))

    out, report = shift(xml, "Table", frm=5)

    assert "Table 10" in text_of_doc(out), text_of_doc(out)
    assert "Tables 5-7" in text_of_doc(out), "the range was rewritten"
    assert report.flagged, "the range should be flagged for the author"


def test_TWO_mentions_in_one_paragraph_both_widen_correctly():
    """Runs are rewritten bottom-up. Each rewrite changes the length of
    the paragraph, so the offsets of every run after it go stale —
    applied top-down the second splice lands inside the wrong run, and
    9 -> 10 is the case that grows rather than merely swapping a digit.
    """
    xml = doc(para(run("See Table 9 "), run("and Table 9 again.")))

    out, _report = shift(xml, "Table", frm=9)

    assert text_of_doc(out) == "See Table 10 and Table 10 again."


def test_an_APPENDIX_collision_is_refused_like_any_other():
    """The collision check reads the same prefix filter the shift does,
    and it has to walk past the main sequence to find the appendix
    captions at all. Skipping the wrong ones — or stopping at the first
    — leaves the check with nothing to compare, so it passes and the
    shift puts two appendix tables on one number.
    """
    xml = _captions("Table 1. Main.", "Table A1. First.", "Table A2. Second.")

    with pytest.raises(AnchorError, match="collide"):
        shift(xml, "Table", frm=2, by=-1, prefix="A")


def test_remap_parts_treats_the_BODY_and_the_NOTES_differently():
    """Captions live in the body; a footnote holds mentions only. So
    the body goes through `remap` (captions, mentions and bookmarks)
    and every other part through `_apply` (mentions and names), and the
    branch that decides is `name == DOCUMENT`.

    Mutated to `>=` the footnotes take the body path — "word/footnotes"
    sorts above "word/document" — and their mentions are then read as
    captions. Mutated to `!=` the two swap outright. Either way the
    document still LOOKS renumbered, because the mentions move; what
    moves wrongly is the caption, and only in one part.
    """
    body = doc(para(run("Table 1. First.")) + para(run("Table 2. Second."))
               + para(run("As Table 2 shows.")))
    foot = notes("footnotes", note("But see Table 2 as well.", 2))
    parts = {"word/document.xml": body.encode("utf-8"),
             "word/footnotes.xml": foot.encode("utf-8")}

    report = remap_parts(parts, "Table", {2: 3})

    text = text_of_doc(parts["word/document.xml"].decode("utf-8"))
    assert "Table 3. Second." in text, text
    assert "Table 1. First." in text, text
    assert "As Table 3 shows." in text, text
    assert "But see Table 3 as well." in \
        visible_text(parts["word/footnotes.xml"].decode("utf-8"))
    assert report.mentions == 3, report.format()


def test_remap_parts_options_are_KEYWORD_only():
    parts = {"word/document.xml": doc(para(run("Table 1. First."))).encode()}

    with pytest.raises(TypeError):
        remap_parts(parts, "Table", {1: 2}, "A")   # type: ignore[call-arg]


# --- the run of 2026-08-20: 5.3 % ---------------------------------------

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _package(body: str, defs: str) -> dict[str, bytes]:
    return {
        "word/document.xml":
            f"<w:document {_NS}><w:body>{body}</w:body></w:document>".encode(),
        "word/footnotes.xml":
            f"<w:footnotes {_NS}>{defs}</w:footnotes>".encode(),
    }


def test_a_shift_counts_only_what_it_CHANGED():
    """Four counters, and every one of them was only ever asserted after
    something had incremented it — so the report could have started at 1
    and no test would have said otherwise.

    The zero cases are the ones a reader acts on: an anchor and a REF
    field pointing at an exhibit BELOW the shift are not rewritten, and a
    report that counts them says the pass touched links it never
    touched. Two of the three mutants that survived here made exactly
    that claim, by comparing the new number against a group that is None
    or against an object that is never the same one."""
    xml = ("<w:body>"
           '<w:p><w:bookmarkStart w:id="1" w:name="Table2"/>'
           "<w:r><w:t>Table 2. The earlier one</w:t></w:r>"
           '<w:bookmarkEnd w:id="1"/></w:p>'
           '<w:p><w:bookmarkStart w:id="2" w:name="Table3"/>'
           "<w:r><w:t>Table 3. The later one</w:t></w:r>"
           '<w:bookmarkEnd w:id="2"/></w:p>'
           '<w:p><w:r><w:t>as </w:t></w:r>'
           '<w:hyperlink w:anchor="Table2"><w:r><w:t>Table 2</w:t></w:r>'
           "</w:hyperlink><w:r><w:t> shows</w:t></w:r></w:p>"
           '<w:p><w:r><w:instrText> REF Table2 \\h </w:instrText></w:r>'
           "</w:p></w:body>")

    out, report = shift(xml, "Table", frm=3)

    assert (report.mentions, report.bookmarks) == (1, 1), report.format()
    assert (report.anchors, report.fields) == (0, 0), report.format()
    assert 'w:name="Table4"' in out and 'w:anchor="Table2"' in out
    assert "REF Table2" in out


def test_a_caption_OUTSIDE_the_prefix_is_skipped_not_final():
    """`continue`, and a `break` there reads the appendix series as
    empty whenever a main-sequence caption comes first — which is the
    order every paper has them in."""
    xml = ("<w:body>"
           "<w:p><w:r><w:t>Table 1. Main sequence</w:t></w:r></w:p>"
           "<w:p><w:r><w:t>Table A1. Appendix one</w:t></w:r></w:p>"
           "<w:p><w:r><w:t>Table A2. Appendix two</w:t></w:r></w:p>"
           "</w:body>")

    assert numbers_in_order(xml, "Table", prefix="A") == [1, 2]
    assert numbers_in_order(xml, "Table") == [1]


def test_the_notes_are_rebuilt_from_the_FIRST_element_on():
    """`notes[:elements[0].start()]` is everything before the first note
    — the part element and its namespaces. Taken to the SECOND element
    the head swallows the separator note, which is then written twice:
    once in the head and once in the reordered body, and Word opens the
    document with a repair warning."""
    body = ('<w:p><w:r><w:footnoteReference w:id="2"/></w:r></w:p>'
            '<w:p><w:r><w:footnoteReference w:id="1"/></w:r></w:p>')
    defs = ('<w:footnote w:id="-1"><w:p><w:r><w:t>sep</w:t></w:r></w:p>'
            "</w:footnote>"
            '<w:footnote w:id="1"><w:p><w:r><w:t>first note</w:t></w:r></w:p>'
            "</w:footnote>"
            '<w:footnote w:id="2"><w:p><w:r><w:t>second note</w:t></w:r>'
            "</w:p></w:footnote>")
    parts = _package(body, defs)

    assert footnotes(parts) == {2: 1, 1: 2}

    out = parts["word/footnotes.xml"].decode("utf-8")
    assert out.count("<w:footnote ") == 3, out
    assert out.count("sep") == 1, out
    assert out.index("second note") < out.index("first note")


def test_a_document_with_MORE_THAN_256_notes_in_order_moves_nothing():
    """`old != new` over footnote ids, written `is not`. CPython hands
    out one object per integer below 257 and a fresh one above, so the
    two readings agree on every fixture in this file and part company on
    the 257th note — which reports itself as MOVED while sitting exactly
    where it was.

    Three hundred notes is a long paper, not an impossible one, and the
    report is what a round acts on: "44 notes moved" sends a reader
    looking for a renumbering that did not happen."""
    body = "".join(
        f'<w:p><w:r><w:footnoteReference w:id="{i}"/></w:r></w:p>'
        for i in range(1, 301))
    defs = "".join(
        f'<w:footnote w:id="{i}"><w:p><w:r><w:t>n{i}</w:t></w:r></w:p>'
        "</w:footnote>" for i in range(1, 301))

    assert footnotes(_package(body, defs)) == {}


# Argued rather than pinned, from the same run:
#
# * the four counters' DEFAULTS in `ShiftReport`. `shift` assigns all
#   four before anyone reads them — `report.bookmarks, report.anchors,
#   report.fields = names, anchors, refs` — so the value in the
#   dataclass is only ever seen by a caller who builds one by hand,
#   which nothing in this package does. (The test above still pins the
#   ZEROES, which is what the two counting mutants below needed.)
# * `if remap_fn(n) == n` written `is`, and the two `is not`s in
#   `_check_permutation`: exhibit numbers and their counts, all below
#   the 257 CPython caches.
# * `m.group(1).startswith("w:name")` written `m.group(0)`. Group 1 is
#   the attribute name and the quote after it, and group 0 begins at the
#   same character.
# * `if nums != sorted(nums)` written `>`, in `audit` and in
#   `footnote_audit`. A sorted list is the smallest arrangement of its
#   own elements, so an unsorted one is strictly greater — the two
#   comparisons agree on every list there is.
# * `len(set(mapping.values())) != len(mapping)` written `<`: a set of a
#   dict's values cannot be bigger than the dict.
# * `set(stored_after) - set(after)` written `^`. A reference with no
#   note has already raised above, so the references are a subset of the
#   notes and the two operations agree.
# * the five mutants on `if after != sorted(after) or stored_after !=
#   after` — the backstop that says the renumbering did not settle.
#   Every one of them differs only in a state this function has just
#   finished ruling out, and `is`/`is not` on two lists built here can
#   only be False.
