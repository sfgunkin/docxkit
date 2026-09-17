"""A manuscript frozen as text, and a protocol's anchors resolved on it.

Every protocol round on DSI wrote the same two scripts again —
`snapshot_t6.py` / `anchor_index_t6.py` on 2026-09-07 and
`snapshot_unfpa.py` / `anchor_index_unfpa.py` on 2026-09-16 (BACKLOG S4).
These tests hold the general version to what those scripts were FOR: a
dump a text diff can read, a structure record a count gate can read, and
an anchor that resolves exactly once, in the paragraph the protocol names.
"""
from __future__ import annotations

import dataclasses
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    dele,
    field,
    ins,
    make_parts,
    note,
    notes,
    para,
    row,
    run,
    table,
    write,
)

from docxkit import snapshot as snap
from docxkit.cli import main
from docxkit.errors import AnchorError

#: Word's separator notes, in every notes part.
SEPARATORS = ('<w:footnote w:id="-1" w:type="continuationSeparator"><w:p>'
              '<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
              '<w:footnote w:id="0" w:type="separator"><w:p><w:r>'
              "<w:separator/></w:r></w:p></w:footnote>")
LINK_RUN = ('<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            "<w:t>{}</w:t></w:r>")
MATH = "<m:oMath><m:r><m:t>{}</m:t></m:r></m:oMath>"


def hyperlink_field(anchor: str, label: str, *, split: bool = False) -> str:
    """A field-form internal link, its label styled as Word styles one."""
    instr = (f'<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l '
             f'</w:instrText></w:r><w:r><w:instrText>"{anchor}" '
             f"</w:instrText></w:r>" if split else
             f'<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l '
             f'"{anchor}" </w:instrText></w:r>')
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + instr
            + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + LINK_RUN.format(label)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def element_link(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}">{LINK_RUN.format(label)}'
            "</w:hyperlink>")


def paper_parts() -> dict[str, bytes]:
    """Five numbered paragraphs, one empty one, a table, notes of both kinds.

    ¶2 carries a field-form citation link and a footnote marker; ¶3 two
    equations; ¶4 a tab character AND a tab stop in its properties; ¶5 an
    element-form link and the bookmark its caption's back-link would name.
    """
    body = (
        para(run("Intro paragraph."))
        + para(run("A claim ("), hyperlink_field("Sen1999", "Sen 1999"),
               run(")."), '<w:r><w:footnoteReference w:id="2"/></w:r>')
        + '<w:p w14:paraId="0000AAAA" w14:textId="0000AAAA"/>'
        + para(run("Where "), MATH.format("x"), run(" and "),
               MATH.format("y"), run(" are outputs."))
        + table(row("Country", "AFI"), row("Poland", "0.31"))
        + para('<w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs>'
               "</w:pPr><w:r><w:t>Left</w:t><w:tab/><w:t>Right</w:t></w:r>")
        + para('<w:bookmarkStart w:id="7" w:name="Table1txt"/>',
               element_link("Table1", "Table 1"),
               '<w:bookmarkEnd w:id="7"/>', run(" shows it. ")))
    footnotes = notes(
        "footnotes", SEPARATORS,
        '<w:footnote w:id="2">'
        + para("<w:r><w:footnoteRef/></w:r>", run(" A note, see "),
               field("REF _Ref123 \\h", "Table 1"), run("."))
        + "</w:footnote>",
        '<w:footnote w:id="5">' + para("<w:r><w:footnoteRef/></w:r>")
        + "</w:footnote>")
    endnotes = notes("endnotes", note("An endnote.", nid=3, kind="endnote"))
    return make_parts(body, footnotes=footnotes,
                      extra={"word/endnotes.xml": endnotes})


# ================================================================ the dump


def test_the_dump_numbers_paragraphs_and_cells_in_DOCUMENT_order():
    """`[P<n>]` for a body paragraph, `[T<k>]` and `[T<k>:r,c]` for a table,
    one `⟦MATH⟧` per equation, and a tab CHARACTER as `\\t` — while the tab
    STOP in ¶4's properties, which is also spelled `<w:tab …/>`, is not
    a character on the page."""
    got = snap.snapshot(paper_parts())

    assert got.lines == (
        "[P1] Intro paragraph.",
        "[P2] A claim (Sen 1999).",
        f"[P3] Where {snap.MATH} and {snap.MATH} are outputs.",
        "[T1]",
        "[T1:1,1] Country",
        "[T1:1,2] AFI",
        "[T1:2,1] Poland",
        "[T1:2,2] 0.31",
        "[P4] Left\tRight",
        "[P5] Table 1 shows it. ",
    )


def test_the_dump_prints_ONLY_the_tab_of_the_printing_children():
    """A protocol copies anchors out of the dump and they are matched
    against `visible_text`, which holds no no-break hyphen and no line
    break. Printed here, `trade‑offs` would be an anchor nothing finds."""
    parts = make_parts(para("<w:r><w:t>trade</w:t><w:noBreakHyphen/>"
                            "<w:t>offs</w:t><w:br/><w:t>a</w:t><w:tab/>"
                            "<w:t>b</w:t></w:r>"))

    assert snap.snapshot(parts).lines == ("[P1] tradeoffsa\tb",)


def test_an_EMPTY_self_closing_paragraph_is_counted_and_not_numbered():
    """The package numbers ¶ the way `find.body_elements` walks them, which
    every report it prints shares. Word writes an empty paragraph as
    `<w:p …/>`, which that walk does not see, so the count a reader
    reconciles with Word's is recorded beside the numbering instead of
    silently disagreeing with it."""
    body = snap.snapshot(paper_parts()).structure["body"]

    assert (body["paragraphs"], body["empty_paragraphs"], body["tables"]) \
        == (5, 1, 1)


def test_a_cell_with_several_paragraphs_and_a_NESTED_table():
    inner = table(row("inner"))
    cell = ("<w:tc>" + para(run("first")) + para(run("second")) + inner
            + "</w:tc>")
    parts = make_parts(f"<w:tbl><w:tr>{cell}</w:tr></w:tbl>")

    got = snap.snapshot(parts)

    assert got.lines == ("[T1]", f"[T1:1,1] first | second | {snap.TABLE}")
    assert got.structure["body"]["tables"] == 1


def test_a_SECOND_table_is_T2_numbered_among_the_tables_alone():
    """`T<k>` is the k-th top-level table, whatever paragraphs stand
    between. A first table alone cannot tell `index + 1` from `index | 1`
    or `index ^ 1` — all three give 1 at index 0 — so the fixture holds
    the second one, where they give 2, 1 and 0."""
    parts = make_parts(table(row("a")) + para(run("between"))
                       + table(row("b", "c")))

    got = snap.snapshot(parts)

    assert got.lines == ("[T1]", "[T1:1,1] a", "[P1] between",
                         "[T2]", "[T2:1,1] b", "[T2:1,2] c")
    assert got.structure["body"]["tables"] == 2


def test_the_notes_are_named_by_KIND_and_id_and_the_shells_are_left_out():
    """Footnotes AND endnotes — which store a journal uses is house style —
    with Word's separators and an empty definition skipped, as DSI's dump
    skipped them."""
    got = snap.snapshot(paper_parts())

    assert got.notes == ("[FN2] A note, see Table 1.", "[EN3] An endnote.")


def test_a_note_of_several_paragraphs_keeps_its_paragraph_boundary():
    footnotes = notes("footnotes", '<w:footnote w:id="4">'
                      + para(run("One.")) + para(MATH.format("z"))
                      + "</w:footnote>")
    got = snap.snapshot(make_parts(para(run("x")), footnotes=footnotes))

    assert got.notes == (f"[FN4] One. | {snap.MATH}",)


# ============================================================ the structure


def test_the_structure_records_links_in_EVERY_form_per_part():
    """Word turns a field-form link into an element when the author saves
    — form churn — so a before/after record has to say which form each
    target is in. A REF cross-reference is the third form a reader
    clicks, and a footnote's links are not the body's."""
    s = snap.snapshot(paper_parts()).structure

    assert s["body"]["hyperlink_fields"] == {"Sen1999": 1}
    assert s["body"]["hyperlink_elements"] == {"Table1": 1}
    assert s["body"]["ref_fields"] == {}
    assert s["body"]["bookmarks"] == ["Table1txt"]
    assert s["body"]["oMath"] == 2
    assert s["footnotes"]["ref_fields"] == {"_Ref123": 1}
    assert s["footnotes"]["hyperlink_fields"] == {}
    assert (s["footnotes"]["notes"], s["endnotes"]["notes"]) == (1, 1)


def test_a_part_the_package_does_not_have_is_recorded_EMPTY_not_absent():
    """Stable keys, so a structure diff between two generations never
    reads a missing endnotes part as a change of shape."""
    s = snap.snapshot(make_parts(para(run("x")))).structure

    assert s["endnotes"] == {"notes": 0, "oMath": 0, "bookmarks": [],
                             "hyperlink_fields": {}, "hyperlink_elements": {},
                             "ref_fields": {}}


def test_an_instruction_SPLIT_across_runs_is_read_whole():
    """Word splits an instruction at rsid boundaries; the anchor sits in
    the second run here, and a per-run read finds no target at all."""
    parts = make_parts(para(hyperlink_field("Split1", "label", split=True)))

    body = snap.snapshot(parts).structure["body"]

    assert body["hyperlink_fields"] == {"Split1": 1}


def test_a_NESTED_field_keeps_its_own_target_and_its_parent_its_own():
    """Fields nest — Word writes a HYPERLINK inside a REF's result. Joining
    every instruction between a begin and the next end reads the outer
    field as `REF _Ref9 \\h HYPERLINK \\l "Inner"` and loses one of the
    two targets."""
    nested = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText xml:space="preserve"> REF _Ref9 \\h '
              "</w:instrText></w:r>"
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              + hyperlink_field("Inner", "inner")
              + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    body = snap.snapshot(make_parts(para(nested))).structure["body"]

    assert body["ref_fields"] == {"_Ref9": 1}
    assert body["hyperlink_fields"] == {"Inner": 1}


def test_a_field_nested_in_a_RESULT_keeps_its_SPLIT_instruction_whole():
    """An instruction belongs to the INNERMOST open field: here the outer
    REF is past its separator and the inner HYPERLINK is not. Asking the
    OUTERMOST field instead reads each half of the split inner instruction
    on its own, and neither half names a target. The test above cannot
    tell: its inner instruction is one run, a target read either way."""
    nested = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText xml:space="preserve"> REF _Ref9 \\h '
              "</w:instrText></w:r>"
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              + hyperlink_field("Inner", "inner", split=True)
              + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    body = snap.snapshot(make_parts(para(nested))).structure["body"]

    assert body["hyperlink_fields"] == {"Inner": 1}
    assert body["ref_fields"] == {"_Ref9": 1}


def test_an_instruction_in_a_field_RESULT_is_not_joined_to_its_own():
    """A REF whose result holds a HYPERLINK instruction an edit cut the
    `begin` off. Past its separator the REF collects nothing more: joined,
    it reads `REF _Ref9 \\h  HYPERLINK \\l "Orphan"`, the HYPERLINK
    pattern claims that first, and the cross-reference drops out of the
    record. The orphan fixtures above hold no instruction BEFORE their
    separator, so joining and not joining read the same there."""
    cut = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText xml:space="preserve"> REF _Ref9 \\h '
           "</w:instrText></w:r>"
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:r><w:instrText> HYPERLINK \\l "Orphan" </w:instrText></w:r>'
           + run("label")
           + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    body = snap.snapshot(make_parts(para(cut))).structure["body"]

    assert body["ref_fields"] == {"_Ref9": 1}
    assert body["hyperlink_fields"] == {"Orphan": 1}


def test_an_OUTER_instruction_resumes_after_a_field_nested_INSIDE_it():
    """Word nests a field in another's INSTRUCTION half too, and when the
    inner one ends the words after it are the outer instruction again —
    that is the stack's pop. An `end` that only marks its field done, or
    a `separate` / `end` taken for a new field, leaves `"Outer"` to be
    read on its own and the target is lost. The name comes AFTER the
    nested field on purpose: before it, the outer instruction would hold
    the whole target whichever frame the rest went to."""
    inner = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText>'
             "</w:r>"
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             + run("4")
             + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    outer = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l '
             "</w:instrText></w:r>"
             + inner
             + '<w:r><w:instrText>"Outer" </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             + LINK_RUN.format("label")
             + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    body = snap.snapshot(make_parts(para(outer))).structure["body"]

    assert body["hyperlink_fields"] == {"Outer": 1}


def test_a_field_that_is_not_a_link_and_one_left_OPEN_are_read_as_they_are():
    """A PAGE field targets nothing; a field an edit truncated — no `end`
    — still names the bookmark it depends on, as `field_anchors` reads
    an orphaned instruction."""
    open_field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                  '<w:r><w:instrText> HYPERLINK \\l "Cut" </w:instrText>'
                  "</w:r>")
    parts = make_parts(para(field("PAGE", "4")) + para(open_field))

    body = snap.snapshot(parts).structure["body"]

    assert body["hyperlink_fields"] == {"Cut": 1}
    assert body["ref_fields"] == {}


@pytest.mark.parametrize("stray", [
    pytest.param('<w:r><w:instrText> HYPERLINK \\l "Orphan" </w:instrText>'
                 "</w:r>", id="no_begin"),
    pytest.param('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                 '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                 '<w:r><w:instrText> HYPERLINK \\l "Orphan" </w:instrText>'
                 '</w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>',
                 id="after_its_separator"),
])
def test_an_instruction_NO_open_field_owns_is_read_on_its_own(stray):
    """The `begin` an edit cut off, or an instruction written into the
    result half: either way it belongs to no instruction being collected,
    and it still names the bookmark it depends on."""
    body = snap.snapshot(make_parts(para(stray))).structure["body"]

    assert body["hyperlink_fields"] == {"Orphan": 1}


def test_a_STRAY_separator_or_end_with_no_field_open_is_ignored():
    stray = ('<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    body = snap.snapshot(make_parts(para(stray, run("x")))).structure["body"]

    assert (body["hyperlink_fields"], body["ref_fields"]) == ({}, {})


def test_an_EXTERNAL_hyperlink_element_is_not_an_internal_target():
    ext = ('<w:hyperlink r:id="rId5">' + LINK_RUN.format("web")
           + "</w:hyperlink>")
    body = snap.snapshot(make_parts(para(ext))).structure["body"]

    assert body["hyperlink_elements"] == {}


# ============================================================ the views


def _tracked_parts() -> dict[str, bytes]:
    return make_parts(
        para(run("Kept "), ins("new"), dele("old"))
        + table(row("Country", "AFI"), row("Gone", "1", revision="del"),
                row("Added", "2", revision="ins")))


def test_the_STORED_view_is_the_markup_as_it_stands():
    """Inserted text is there and deleted text is not — `visible_text`'s
    reading — and a row flagged deleted is still a row in the file."""
    got = snap.snapshot(_tracked_parts())

    assert got.lines[0] == "[P1] Kept new"
    assert "[T1:2,1] Gone" in got.lines
    assert got.structure["view"] == "stored"


def test_ACCEPTED_is_the_view_the_tracked_gates_simulate():
    got = snap.snapshot(_tracked_parts(), accepted=True)

    assert "[T1:2,1] Added" in got.lines
    assert not any("Gone" in line for line in got.lines)
    assert got.structure["view"] == "accepted"


def test_ACCEPTED_prunes_the_shell_a_deleted_footnote_leaves():
    """A deleted note is a deleted reference AND a definition of
    `w:delText`; accepting part by part leaves the definition behind as
    an empty shell, which the dump would then count."""
    footnotes = notes("footnotes", SEPARATORS, '<w:footnote w:id="2">'
                      + para("<w:r><w:footnoteRef/></w:r>", dele(" Gone."))
                      + "</w:footnote>")
    body = para(run("Claim."), '<w:del w:id="9" w:author="A" '
                'w:date="2026-09-17T00:00:00Z"><w:r><w:footnoteReference '
                'w:id="2"/></w:r></w:del>')
    parts = make_parts(body, footnotes=footnotes)

    accepted = snap.snapshot(parts, accepted=True)

    assert accepted.notes == ()
    assert b'w:id="2"' in parts["word/footnotes.xml"], \
        "the caller's parts are not the simulation's"


# ======================================================== baseline labels


@pytest.mark.parametrize("insertions,labels", [
    pytest.param((), ["P1", "P2", "P3", "P4", "P5"], id="none"),
    pytest.param((2,), ["P1", "P2", "P2a", "P3", "P4"], id="one"),
    pytest.param((2, 2), ["P1", "P2", "P2a", "P2b", "P3"], id="repeated"),
    pytest.param((3, 1), ["P1", "P1a", "P2", "P3", "P3a"], id="any_order"),
    pytest.param((0,), ["P0a", "P1", "P2", "P3", "P4"], id="before_the_first"),
    pytest.param((4,), ["P1", "P2", "P3", "P4", "P4a"], id="after_the_last"),
])
def test_INSERTIONS_label_new_paragraphs_in_BASELINE_numbering(insertions,
                                                               labels):
    """`31,98` says: one paragraph inserted after baseline ¶31, one after
    ¶98. The inserted ones are `P31a`, `P98a`; a number given twice is two
    inserted there, `a` then `b`. Everything else keeps its BASELINE
    number, so a dump of the edited file diffs line for line against the
    dump of the one it grew out of."""
    body = "".join(para(run(f"p{i}")) for i in range(1, 6))

    got = snap.snapshot(make_parts(body), insertions=insertions)

    assert [line.split("]")[0][1:] for line in got.lines] == labels
    assert got.structure["insertions"] == sorted(insertions)


def test_the_letters_run_past_z():
    assert [snap._letters(i) for i in (0, 25, 26, 27, 701, 702)] == [
        "a", "z", "aa", "ab", "zz", "aaa"]


def test_INSERTIONS_the_document_cannot_hold_are_refused():
    """A baseline number past the end is a list written for another file,
    and labelling what there is would print a dump that silently numbers
    nothing the way the list meant."""
    body = "".join(para(run(f"p{i}")) for i in range(1, 4))

    with pytest.raises(AnchorError, match=r"after baseline ¶9"):
        snap.snapshot(make_parts(body), insertions=(9,))


@pytest.mark.parametrize("count,insertions,said", [
    pytest.param(4, (1, 3), "after baseline ¶3, and this document runs out "
                 "at baseline ¶3 with 4 paragraphs", id="owed_at_the_last"),
    pytest.param(3, (4, 9), "after baseline ¶9, and this document runs out "
                 "at baseline ¶3 with 3 paragraphs", id="the_latest_named"),
])
def test_INSERTIONS_still_OWED_at_the_end_are_refused_naming_the_LATEST(
        count, insertions, said):
    """`1,3` on four paragraphs labels P1, P1a, P2, P3 and runs out with
    the insertion after ¶3 still owed. Nothing past the end is named, so
    only the `used < owed` half of the test says so — the ¶9 case above
    never reaches it — and the ¶ it names is one AT the last baseline
    paragraph, not merely past it. Of several, the message names the
    latest: two distinct numbers, since one cannot tell first from last."""
    body = "".join(para(run(f"p{i}")) for i in range(1, count + 1))

    with pytest.raises(AnchorError, match=re.escape(said)):
        snap.snapshot(make_parts(body), insertions=insertions)


def test_INSERTIONS_count_PARAGRAPHS_and_a_TABLE_is_not_one():
    """Two paragraphs with a table between them are P1 and P2, with no
    room left for a paragraph inserted after ¶2. Counting the table as a
    paragraph labels a third that is not there and lets the list pass."""
    body = para(run("p1")) + table(row("cell")) + para(run("p2"))

    with pytest.raises(AnchorError, match="with 2 paragraphs in all"):
        snap.snapshot(make_parts(body), insertions=(2,))


def test_INSERTIONS_past_256_at_ONE_place_are_counted_by_VALUE():
    """CPython caches the ints up to 256, so an identity test on the
    counts reads as `<` until the 257th insertion at one place, where the
    two 257s — one counted by `Counter`, one by the walk — are different
    objects. Two baseline paragraphs with 257 each: an identity test
    mislabels ¶2 as one more insertion after ¶1, or refuses the list at
    its end, when it fits exactly."""
    n = 257
    body = "".join(para(run("x")) for _ in range(2 * (n + 1)))

    got = snap.snapshot(make_parts(body), insertions=(1,) * n + (2,) * n)

    assert [line.split("]")[0][1:] for line in got.lines] == (
        ["P1"] + [f"P1{snap._letters(i)}" for i in range(n)]
        + ["P2"] + [f"P2{snap._letters(i)}" for i in range(n)])


def test_a_NEGATIVE_insertion_is_refused():
    with pytest.raises(AnchorError, match="-1"):
        snap.snapshot(make_parts(para(run("x"))), insertions=(-1,))


# ================================================================ writing


def test_write_puts_the_three_files_beside_the_stem(tmp_path):
    got = snap.snapshot(paper_parts())

    written = got.write(tmp_path / "out" / "baseline")

    assert [p.name for p in written] == [
        "baseline.txt", "baseline_notes.txt", "baseline_structure.json"]
    text = (tmp_path / "out" / "baseline.txt").read_text(encoding="utf-8")
    assert text == "\n".join(got.lines) + "\n"
    assert (tmp_path / "out" / "baseline_notes.txt").read_text(
        encoding="utf-8") == "\n".join(got.notes) + "\n"
    record = json.loads((tmp_path / "out" / "baseline_structure.json")
                        .read_text(encoding="utf-8"))
    assert record == got.structure


def test_a_stem_WITH_a_suffix_keeps_it_rather_than_losing_it(tmp_path):
    """`with_suffix` would turn `round.v2` into `round.txt`."""
    written = snap.snapshot(make_parts(para(run("x")))).write(
        tmp_path / "round.v2")

    assert written[0].name == "round.v2.txt"


def test_write_makes_EVERY_missing_directory_above_the_stem(tmp_path):
    """Two levels, because one missing directory under an existing one is
    all a `mkdir` without `parents` can make."""
    written = snap.snapshot(make_parts(para(run("x")))).write(
        tmp_path / "rounds" / "r3" / "baseline")

    assert all(p.is_file() for p in written)


def test_the_structure_file_keeps_a_NON_ASCII_name_readable(tmp_path):
    """DSI's bookmarks are Cyrillic, and the record is read by people and
    searched with grep: `\\u0422\\u0430…` is a name neither finds."""
    body = para('<w:bookmarkStart w:id="1" w:name="Таблица1"/>', run("x"),
                '<w:bookmarkEnd w:id="1"/>')

    written = snap.snapshot(make_parts(body)).write(tmp_path / "baseline")

    assert '"Таблица1"' in written[2].read_text(encoding="utf-8")


# ================================================================ anchors


def _resolve(*specs: str, parts: dict[str, bytes] | None = None,
             **kw: Any) -> list[snap.Resolution]:
    return snap.resolve(parts or paper_parts(),
                        [snap.parse_anchor(s) for s in specs], **kw)


def test_REPLACE_is_exactly_once_and_inside_the_named_paragraph():
    (r,) = _resolve("P1=Intro paragraph")

    assert r.ok and r.reason == ""
    assert (r.total, r.in_scope, r.where, r.target) == (
        1, 1, (("P1", 1),), "P1")


def test_REPLACE_twice_document_wide_is_a_STOP_naming_both_places():
    parts = make_parts(para(run("Poland grew."))
                       + table(row("Poland", "0.31")))

    (r,) = _resolve("P1=Poland", parts=parts)

    assert not r.ok
    assert r.where == (("P1", 1), ("T1:1,1", 1))
    assert r.reason == "occurs 2 times: P1, T1:1,1"


def test_REPLACE_found_ELSEWHERE_says_where_it_is():
    (r,) = _resolve("P1=Sen 1999")

    assert not r.ok
    assert r.reason == "not in P1: it is in P2"


def test_an_anchor_found_NOWHERE():
    (r,) = _resolve("P1=nothing like this")

    assert (r.ok, r.reason, r.total) == (False, "not found", 0)


def test_a_scope_that_names_NOTHING_is_its_own_stop():
    (r,) = _resolve("P99=Intro")

    assert not r.ok
    assert r.reason == "P99 names nothing in this document"
    assert r.target == ""


def test_a_scope_that_names_NOTHING_measures_NOTHING():
    """No target, so no facts to report — even when the LAST place in the
    document has an equation, a link and a trailing space, which is the
    place a target of -1 would index. `paper_parts` ends in an endnote
    with none of the three, where measuring it and not agree."""
    parts = make_parts(para(run("x"))
                       + para(MATH.format("y"), element_link("Tbl1", "T 1"),
                              run("end ", preserve=True)))

    (r,) = _resolve("P9=x", parts=parts)

    assert (r.target, r.math, r.links, r.trailing, r.crossing,
            r.formats) == ("", 0, (), "", (), 0)
    assert len(r.format().splitlines()) == 1


def test_a_scope_of_SEVERAL_places_targets_the_one_holding_the_anchor():
    """`T1` is four cells: the target is the cell the anchor is in, and
    the scope's FIRST place only when none holds it. A one-paragraph scope
    cannot tell the place found from the fallback — its first place is
    the only one."""
    (found,) = _resolve("T1=Poland")
    (missing,) = _resolve("T1=Latvia")
    (star,) = _resolve("*=are outputs")

    assert found.target == "T1:2,1"
    assert missing.target == "T1:1,1"
    assert (star.target, star.math) == ("P3", 2)


@pytest.mark.parametrize("kind", ["append", "insert_after"])
def test_APPEND_wants_the_scope_to_END_with_it_trailing_space_excepted(kind):
    """¶5 ends `shows it. ` — the trailing space is excepted and reported,
    which is what an apply script has to strip or keep."""
    (ok,) = _resolve(f"{kind}@P5=shows it.")
    (not_end,) = _resolve(f"{kind}@P5=Table 1")

    assert ok.ok and ok.trailing == " "
    assert not not_end.ok
    assert not_end.reason == "P5 does not END with it"


def test_APPEND_measures_the_span_that_ENDS_the_paragraph():
    """An append's span starts `len(anchor)` characters before the
    paragraph's end: 40 - 16 = 24, where the italic run begins, so it
    covers two formats and no link. The lengths are chosen so no other
    operator on 40 and 16 starts there — `^` gives 56, `%` 8, `&` 0 — and
    every other start meets something else: the link, the plain prose
    alone, or nothing at all."""
    parts = make_parts(para(
        LINK_RUN.format("Sen 1999"),
        run(" argues that the", preserve=True),
        '<w:r><w:rPr><w:i/></w:rPr><w:t xml:space="preserve"> growth</w:t>'
        "</w:r>",
        '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve"> matters.'
        "</w:t></w:r>"))

    (r,) = snap.resolve(parts, [snap.Anchor("P1", "append",
                                            " growth matters.")])

    assert r.ok
    assert (r.crossing, r.formats) == ((), 2)


def test_APPEND_that_ends_its_scope_and_ALSO_occurs_elsewhere_stops():
    parts = make_parts(para(run("It ends here."))
                       + para(run("It ends here. And again.")))

    (r,) = _resolve("append@P1=It ends here.", parts=parts)

    assert not r.ok and r.reason == "occurs 2 times: P1, P2"


def test_PRESENT_asks_only_that_the_scope_holds_it():
    parts = make_parts(para(run("twice twice")) + para(run("twice")))

    (here,) = _resolve("present@P1=twice", parts=parts)
    (gone,) = _resolve("present@P1=absent", parts=parts)

    assert here.ok and here.in_scope == 2 and here.total == 3
    assert not gone.ok and gone.reason == "not found"


@pytest.mark.parametrize("spec,ok", [
    ("T1=Poland", True),
    ("T1:2,1=Poland", True),
    ("T1:1,1=Poland", False),
    ("FN2=A note", True),
    ("EN3=An endnote", True),
    ("FN3=An endnote", False),
    ("*=Intro paragraph", True),
])
def test_every_SCOPE_form(spec, ok):
    assert _resolve(spec)[0].ok is ok


def test_the_STAR_scope_is_exactly_once_anywhere():
    parts = make_parts(para(run("a b")) + para(run("a")))

    (r,) = _resolve("*=a", parts=parts)

    assert not r.ok and r.reason == "occurs 2 times: P1, P2"


def test_a_count_of_two_in_ONE_place_is_written_with_its_multiplier():
    parts = make_parts(para(run("a b a")))

    (r,) = _resolve("P1=a", parts=parts)

    assert r.reason == "occurs 2 times: P1 ×2"


def test_an_anchor_in_TWO_paragraphs_of_one_CELL_occurs_twice_there():
    """A cell's paragraphs share its label, so the count per label is a
    SUM over them. Every other fixture here adds to a label once, where
    `+`, `|` and `^` onto zero agree."""
    cell = ("<w:tc>" + para(run("Poland")) + para(run("Poland, again"))
            + "</w:tc>")
    parts = make_parts(f"<w:tbl><w:tr>{cell}</w:tr></w:tbl>")

    (r,) = _resolve("T1:1,1=Poland", parts=parts)

    assert (r.ok, r.total, r.where) == (False, 2, (("T1:1,1", 2),))
    assert r.reason == "occurs 2 times: T1:1,1 ×2"


def test_CROSSING_names_the_link_label_the_anchor_span_overlaps():
    """What an apply script needs before it writes: `replace_in_para`
    refuses a match that crosses a label, so the edit has to go around
    it. Measured in the READER's offsets, and the label is named whole."""
    (crosses,) = _resolve("P2=claim (Sen")
    (beside,) = _resolve("P2=A claim (")

    assert crosses.crossing == ("Sen 1999",)
    assert beside.crossing == ()
    assert crosses.links == ("Sen1999",)


def test_CROSSING_reads_an_ELEMENT_form_link_too():
    (r,) = _resolve("P5=Table 1 shows")

    assert r.crossing == ("Table 1",) and r.links == ("Table1",)


def test_a_label_Word_FRAGMENTED_across_runs_is_one_label():
    """Word splits a label at rsid boundaries as freely as prose; two runs
    of one link are one label to cross, named whole."""
    split = ('<w:hyperlink w:anchor="Sen1999">' + LINK_RUN.format("Sen ")
             + LINK_RUN.format("1999") + "</w:hyperlink>")
    parts = make_parts(para(run("As "), split, run(" argues.")))

    (r,) = _resolve("P1=As Sen", parts=parts)

    assert r.crossing == ("Sen 1999",)


#: Three hundred characters of prose: past 256, where CPython stops
#: caching ints and an identity test on two offsets stops reading as `==`.
FILLER = "word " * 60


def test_CROSSING_names_each_of_TWO_links_whole_far_into_a_paragraph():
    """Two links, the second fragmented across runs, and an anchor that
    crosses only the second. Its runs are one label because the second
    starts where the LAST label ended — not the first label, and not
    merely somewhere after the last, which would swallow the prose
    between the two links into one label. Past offset 256 for `is`."""
    fragmented = ('<w:hyperlink w:anchor="Deaton2013">'
                  + LINK_RUN.format("Deaton ") + LINK_RUN.format("2013")
                  + "</w:hyperlink>")
    parts = make_parts(para(run(FILLER, preserve=True),
                            element_link("Sen1999", "Sen 1999"),
                            run(" and ", preserve=True), fragmented,
                            run(" agree.", preserve=True)))

    (r,) = _resolve("P1=and Deaton 2013 agree", parts=parts)

    assert r.crossing == ("Deaton 2013",)


def test_a_note_MARKER_inside_the_span_is_not_a_FORMAT():
    """A footnote reference is a run of no visible width with properties
    of its own, and it formats no character the anchor holds, so it is
    skipped. Past offset 256: below it a zero-width run's start and end
    are one cached int, and an identity test skips it just the same."""
    marker = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
              '<w:footnoteReference w:id="2"/></w:r>')
    parts = make_parts(para(run(FILLER, preserve=True), run("claim"),
                            marker, run(" continues", preserve=True)))

    (r,) = _resolve("P1=claim continues", parts=parts)

    assert r.ok and r.formats == 1


def test_FORMATS_counts_the_distinct_run_properties_the_span_covers():
    parts = make_parts(para(run("plain "),
                            '<w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>',
                            run(" plain")))

    (both,) = _resolve("P1=plain bold", parts=parts)
    (one,) = _resolve("P1=bold", parts=parts)

    assert (both.formats, one.formats) == (2, 1)


def test_MATH_is_counted_in_the_target_paragraph_even_when_not_found():
    """The DSI batch was text-only, so a target holding an equation was a
    STOP of its own; the count is reported whatever the verdict."""
    (r,) = _resolve("P3=not there")

    assert (r.target, r.math) == ("P3", 2)


def test_NORMALIZE_matches_through_the_glyph_Word_substituted():
    parts = make_parts(para(run("the workers’ share")))

    (plain,) = _resolve("P1=workers' share", parts=parts)
    (folded,) = _resolve("P1=workers' share", parts=parts, normalize=True)

    assert not plain.ok and folded.ok


def test_INSERTIONS_let_an_anchor_name_a_new_paragraph_by_baseline_label():
    parts = make_parts(para(run("old one")) + para(run("brand new"))
                       + para(run("old two")))

    (r,) = _resolve("P1a=brand new", parts=parts, insertions=(1,))

    assert r.ok and r.target == "P1a"


# ============================================================ the spec file


def test_a_SPEC_line_is_scope_kind_anchor_with_an_optional_name_first():
    text = ("# a comment, and a blank line after it\n\n"
            "P31\treplace\tthe old words\n"
            "T1.2\tP5\tappend\tends with\ta tab\n"
            "*\tpresent\t trailing space \r\n")

    got = snap.parse_spec(text)

    assert got == [
        snap.Anchor("P31", "replace", "the old words"),
        snap.Anchor("P5", "append", "ends with\ta tab", name="T1.2"),
        snap.Anchor("*", "present", " trailing space "),
    ]


def test_a_THREE_column_SPEC_line_keeps_a_TAB_inside_its_anchor():
    """The anchor is the rest of the line, tabs included, in the
    three-column form as in the four — split once too often, the tab in
    the anchor reads as a fourth column and the kind as a scope."""
    assert snap.parse_spec("P5\tappend\tends with\ta tab\n") == [
        snap.Anchor("P5", "append", "ends with\ta tab")]


@pytest.mark.parametrize("line,why", [
    ("P31\tswap\tx", "line 1"),
    ("P31 replace x", "line 1"),
    ("Q7\treplace\tx", "line 1"),
    ("P31\treplace\t", "line 1"),
])
def test_a_SPEC_line_it_cannot_read_is_refused_by_NUMBER(line, why):
    with pytest.raises(AnchorError, match=why):
        snap.parse_spec(line)


@pytest.mark.parametrize("text,want", [
    ("P31=the words", snap.Anchor("P31", "replace", "the words")),
    ("append@P5=a = b", snap.Anchor("P5", "append", "a = b")),
    ("T4:2,3=cell", snap.Anchor("T4:2,3", "replace", "cell")),
])
def test_an_ANCHOR_on_the_command_line(text, want):
    assert snap.parse_anchor(text) == want


@pytest.mark.parametrize("text", ["no equals sign", "=empty scope",
                                  "P1=", "bogus@P1=x", "P1x1=x"])
def test_an_ANCHOR_that_cannot_be_read_is_refused(text):
    with pytest.raises(AnchorError):
        snap.parse_anchor(text)


def test_read_spec_reads_UTF8_from_a_file(tmp_path):
    spec = tmp_path / "anchors.tsv"
    spec.write_text("P1\treplace\tIntro «paragraph»\n", encoding="utf-8")

    assert snap.read_spec(spec) == [
        snap.Anchor("P1", "replace", "Intro «paragraph»")]


def test_format_says_the_verdict_first_and_the_facts_after():
    (ok, stop, spaced) = snap.resolve(paper_parts(), [
        snap.Anchor("P2", "replace", "claim (Sen", name="T1.2"),
        snap.Anchor("P1", "replace", "Sen 1999"),
        snap.Anchor("P3", "present", "Where")])

    assert ok.format().splitlines() == [
        "OK    T1.2  replace       P2  ·  in scope 1, document 1",
        "      links Sen1999 · crossing «Sen 1999» · formats 2"]
    assert stop.format().splitlines() == [
        "STOP  replace       P1  ·  in scope 0, document 1  ·  not in P1: "
        "it is in P2"]
    assert spaced.format().splitlines()[1] == "      math 2 · formats 1"
    (tail,) = _resolve("append@P5=shows it.")
    assert tail.format().splitlines()[1].endswith("· trailing ' '")


def test_what_snapshot_and_resolve_hand_back_is_FROZEN():
    """A snapshot is the state a round starts from and a resolution is a
    verdict on it; neither is a record a caller amends in place."""
    parts = make_parts(para(run("x")))
    anchor = snap.Anchor("P1", "replace", "x")
    (verdict,) = snap.resolve(parts, [anchor])

    for obj, attr in ((snap.snapshot(parts), "lines"), (anchor, "text"),
                      (verdict, "ok")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, attr, None)


# ================================================================ the CLI


def run_cli(monkeypatch, *argv: str) -> int | str | None:
    monkeypatch.setattr("sys.argv", ["docxkit", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    return exc.value.code


@pytest.fixture
def paper(tmp_path) -> str:
    return write(tmp_path / "paper.docx", paper_parts())


def test_cli_SNAPSHOT_with_no_stem_prints_the_dump(monkeypatch, capsys, paper):
    code = run_cli(monkeypatch, "snapshot", paper)
    out = capsys.readouterr().out

    assert code == 0
    assert "[P1] Intro paragraph.\n" in out
    assert "[FN2] A note, see Table 1.\n" in out
    assert "5 paragraphs (1 empty, unnumbered) · 1 tables · 2 equations" \
        in out


def test_cli_SNAPSHOT_with_a_stem_writes_the_files(monkeypatch, capsys,
                                                   paper, tmp_path):
    stem = tmp_path / "frozen"

    code = run_cli(monkeypatch, "snapshot", paper, str(stem), "--accepted",
                   "--insertions", "1")
    out = capsys.readouterr().out

    assert code == 0
    lines = (tmp_path / "frozen.txt").read_text(encoding="utf-8").splitlines()
    assert lines[1] == "[P1a] A claim (Sen 1999)."
    record = json.loads((tmp_path / "frozen_structure.json").read_text(
        encoding="utf-8"))
    assert record["view"] == "accepted" and record["insertions"] == [1]
    assert "frozen_structure.json" in out
    assert "[P1] Intro" not in out, "the dump went to the file"


@pytest.mark.parametrize("bad", ["x", "3,,4", "-2"])
def test_cli_INSERTIONS_that_are_not_paragraph_numbers(monkeypatch, capsys,
                                                       paper, bad):
    code = run_cli(monkeypatch, "snapshot", paper, "--insertions", bad)

    assert code == 2                         # argparse's usage error
    assert "--insertions" in capsys.readouterr().err


def test_cli_ANCHORS_exits_0_when_every_anchor_resolves(monkeypatch, capsys,
                                                        paper, tmp_path):
    spec = tmp_path / "spec.tsv"
    spec.write_text("P1\treplace\tIntro paragraph\n", encoding="utf-8")
    report = tmp_path / "anchors.json"

    code = run_cli(monkeypatch, "anchors", paper, str(spec),
                   "--anchor", "present@FN2=A note", "--json", str(report))
    out = capsys.readouterr().out

    assert code == 0
    assert out.splitlines()[-1] == "2 anchors: 2 OK, 0 STOP"
    rows = json.loads(report.read_text(encoding="utf-8"))
    assert [r["anchor"]["scope"] for r in rows] == ["P1", "FN2"]
    assert rows[0]["ok"] is True


def test_cli_ANCHORS_exits_1_on_any_STOP(monkeypatch, capsys, paper):
    code = run_cli(monkeypatch, "anchors", paper, "--anchor", "P1=Sen 1999",
                   "--normalize", "--insertions", "1")
    out = capsys.readouterr().out

    assert code == 1
    assert out.splitlines()[-1] == "1 anchors: 0 OK, 1 STOP"


def test_cli_ANCHORS_with_nothing_to_resolve_says_so(monkeypatch, capsys,
                                                     paper):
    code = run_cli(monkeypatch, "anchors", paper)

    assert code == 2
    assert "give a SPEC file or --anchor" in capsys.readouterr().err


def test_cli_ANCHORS_a_bad_command_line_anchor_is_a_usage_error(
        monkeypatch, capsys, paper):
    code = run_cli(monkeypatch, "anchors", paper, "--anchor", "nothing")

    assert code == 2
    assert "--anchor" in capsys.readouterr().err


def test_cli_SNAPSHOT_reads_a_file_WORD_HOLDS_and_still_writes_its_stem(
        monkeypatch, capsys, paper, tmp_path):
    """Read-only on the paper, so it answers from a snapshot copy like
    every other question — and the files it writes are its OWN, beside
    the stem, never the manuscript."""
    import zipfile as zf

    import docxkit.package as pkg
    live, real = Path(paper).resolve(), zf.ZipFile

    def held(file, *args, **kw):
        mode = args[0] if args else kw.get("mode", "r")
        if (mode == "r" and isinstance(file, str | Path)
                and Path(file).resolve() == live):
            raise PermissionError(13, "in use")
        return real(file, *args, **kw)

    monkeypatch.setattr(pkg, "is_locked", lambda path: True)
    monkeypatch.setattr(zf, "ZipFile", held)
    monkeypatch.setattr(pkg.time, "sleep", lambda _s: None)
    before = Path(paper).read_bytes()

    code = run_cli(monkeypatch, "snapshot", paper, str(tmp_path / "held"))

    assert code == 0
    assert (tmp_path / "held.txt").exists()
    assert Path(paper).read_bytes() == before
    assert zipfile.is_zipfile(paper)
