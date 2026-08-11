"""Characterization tests for the ported compare module.

compare.py is the authoritative gate every paper round relies on, and it
came over from tools/ verbatim — well-exercised but never unit-tested.
These pin its CURRENT behavior on synthetic fixtures so a future change
(or the eventual de-porting) has something to diff against. They assert
what it does, not what it should do.
"""
from __future__ import annotations

import re

import pytest
from conftest import (
    comment,
    field,
    hdr,
    make_parts,
    note,
    notes,
    para,
    row,
    run,
    table,
    write,
)

from docxkit.compare import GATED, Report, compare, render


def docs(tmp_path, body_a: str, body_b: str, **kw):
    """Two documents. Keyword arguments go to make_parts for BOTH; pass a
    `(a_value, b_value)` tuple to differ on one part."""
    def side(i):
        return {k: (v[i] if isinstance(v, tuple) else v)
                for k, v in kw.items()}

    a = write(tmp_path / "a.docx", make_parts(body_a, **side(0)))
    b = write(tmp_path / "b.docx", make_parts(body_b, **side(1)))
    return a, b


BASE = (para(run("The index rose to 0.35 in 2024."))
        + para(run("Methods follow the standard approach."))
        + para(run("Conclusions are unchanged.")))


def _rendered(report) -> str:
    """What render() prints — the half of the report a human reads."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        render(report, expect_clean=False)
    return buf.getvalue()


def test_identical_documents_compare_clean(tmp_path):
    a, b = docs(tmp_path, BASE, BASE)
    report = compare(a, b)
    for bucket in ("structure", "text", "glyph", "formula", "format",
                   "stripped_fields"):
        assert report[bucket] == [], bucket
    assert render(report, expect_clean=True) == 0


def test_a_text_edit_lands_in_the_text_bucket_and_gates(tmp_path):
    edited = BASE.replace("0.35", "0.37")
    a, b = docs(tmp_path, BASE, edited)
    report = compare(a, b)
    assert len(report["text"]) == 1
    assert render(report, expect_clean=True) == 1


def test_a_glyph_substitution_is_not_a_text_change(tmp_path):
    """Word's save artifacts (curly to straight apostrophe) go to the
    GLYPH bucket, not TEXT — treating them as edits made every round
    re-integrate phantom author edits."""
    a, b = docs(tmp_path,
                para(run("the workers’ index rose")),
                para(run("the workers' index rose")))
    report = compare(a, b)
    assert report["text"] == []
    assert len(report["glyph"]) == 1


def test_an_inserted_paragraph_is_structure(tmp_path):
    a, b = docs(tmp_path, BASE,
                BASE + para(run("An entirely new closing paragraph.")))
    report = compare(a, b)
    assert any("new closing" in str(e) for e in report["structure"])


def test_a_relocated_paragraph_reports_as_a_move(tmp_path):
    moved = (para(run("Conclusions are unchanged."))
             + para(run("The index rose to 0.35 in 2024."))
             + para(run("Methods follow the standard approach.")))
    a, b = docs(tmp_path, BASE, moved)
    report = compare(a, b)
    assert any(e.get("change") == "move" or "move" in str(e).lower()
               for e in report["structure"])
    assert report["text"] == []


def test_a_formatting_change_on_equal_text_is_format(tmp_path):
    plain = para(run("See the Journal of Things here."))
    italic = ('<w:p><w:r><w:t xml:space="preserve">See the </w:t></w:r>'
              "<w:r><w:rPr><w:i/></w:rPr><w:t>Journal of Things</w:t></w:r>"
              '<w:r><w:t xml:space="preserve"> here.</w:t></w:r></w:p>')
    a, b = docs(tmp_path, plain, italic)
    report = compare(a, b)
    assert report["text"] == []
    assert any("italic" in str(e) for e in report["format"])


def test_a_dangling_anchor_is_an_integrity_flag_on_the_built_doc(tmp_path):
    linked = para(
        run("See ")
        + '<w:hyperlink w:anchor="Nowhere2020"><w:r><w:t>nowhere'
          "</w:t></w:r></w:hyperlink>")
    a, b = docs(tmp_path, linked, linked)
    report = compare(a, b)
    assert any("dangling" in str(e).lower() for e in report["integrity"])


def test_an_unbalanced_bookmark_is_an_integrity_flag(tmp_path):
    unbalanced = para(
        '<w:bookmarkStart w:id="7" w:name="orphan_start"/>'
        + run("text with an unclosed bookmark"))
    a, b = docs(tmp_path, unbalanced, unbalanced)
    report = compare(a, b)
    assert any("bookmark" in str(e).lower() for e in report["integrity"])


def test_a_field_stripped_alongside_a_text_edit_is_reported(tmp_path):
    """stripped_fields fires only for paragraph pairs whose TEXT also
    changed — that is where Word strips machinery while the author
    rewords. A field lost with identical text does NOT reach this layer
    (it shows in the hyperlink-label review instead); pinned here so the
    blind spot is a documented fact, not a surprise."""
    from docxkit.citations import hyperlink_field
    with_field = para(run("See ") + hyperlink_field("ref_x", "Smith 2020")
                      + run(" for detail."))
    reworded = para(run("Compare Smith 2020 for more detail."))
    a, b = docs(tmp_path, with_field, reworded)
    report = compare(a, b)
    assert report["stripped_fields"], report
    assert "ref_x" in str(report["stripped_fields"])

    same_text = para(run("See Smith 2020 for detail."))
    a2, b2 = docs(tmp_path / "x" if (tmp_path / "x").mkdir() is None
                  else tmp_path, with_field, same_text)
    assert compare(a2, b2)["stripped_fields"] == []


def test_a_field_end_run_with_rpr_does_not_bleed_the_label(tmp_path):
    """Word adds an <w:rPr> to the field's closing run when the author
    saves. hyperlink_labels required a BARE closing run, so the label ran
    on to the NEXT field's end and an untouched citation was reported as
    a 90-character bled link — three false positives on Parental Style,
    invisible in the machine build because it had never seen Word.
    """
    from docxkit.citations import hyperlink_field

    cite_a = hyperlink_field("Baumrind1991", "Baumrind (1991)")
    cite_b = hyperlink_field("Hao2008", "Hao et al. (2008)")
    body = (para(run("As ") + cite_a
                 + run(" conceptualized parental style as demandingness."))
            + para(run("Also ") + cite_b
                   + run(" propose a game-theoretic explanation.")))
    worded = body.replace(
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
        "<w:r><w:rPr><w:noProof/></w:rPr>"
        '<w:fldChar w:fldCharType="end"/></w:r>')
    assert worded != body, "fixture did not reproduce Word's closing run"

    a, b = docs(tmp_path, body, worded)
    report = compare(a, b)
    # identical visible text and identical links: nothing to report
    assert report["text"] == [], report["text"]
    assert report["hyperlinks"] == [], report["hyperlinks"]


# ------------------------------------------------------- beyond document.xml
# Until 2026-08-06 this gate compared word/document.xml and nothing else:
# footnotes.xml was read and then discarded, and headers, footers, endnotes
# and comments were never opened. Across the 507 manuscripts on this
# machine that is 1,111 header/footer parts and 306 endnote parts it
# certified as unchanged without looking at them.


def test_an_edit_in_a_footnote_is_found(tmp_path):
    wave = "Data are from the {} wave."
    a, b = docs(tmp_path, BASE, BASE,
                footnotes=(notes("footnotes", note(wave.format(2024))),
                           notes("footnotes", note(wave.format(2023)))))
    report = compare(a, b)
    assert len(report["text"]) == 1, report
    assert report["text"][0]["part"] == "footnotes"
    assert any("2023" in d for d in report["text"][0]["word_diff"])
    assert render(report, expect_clean=True) == 1


def test_an_edit_in_an_endnote_is_found(tmp_path):
    end_a = notes("endnotes", note("See the appendix.", kind="endnote"))
    end_b = end_a.replace("appendix", "online appendix")
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/endnotes.xml": end_a},
                       {"word/endnotes.xml": end_b}))
    report = compare(a, b)
    assert [t["part"] for t in report["text"]] == ["endnotes"], report


def test_an_edit_in_a_header_is_found_and_named(tmp_path):
    head = hdr(para(run("Age-Friendly Index — draft")))
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": head},
                       {"word/header1.xml": head.replace("draft", "revised")}))
    report = compare(a, b)
    assert len(report["text"]) == 1, report
    assert report["text"][0]["part"] == "header1"
    assert render(report, expect_clean=True) == 1


def test_a_cached_page_number_is_not_an_edit(tmp_path):
    """The reason headers could not simply be switched on. Word caches the
    page an instance last rendered on, and two copies of ONE document
    disagree: DSI's footer1.xml caches "2" in 34 files here and "11" in 38;
    LI's caches "2", "1", "Page 1" and "Page  of". Diffing that raw would
    fail every paper's --expect-clean for a difference no reader can see."""
    foot = hdr(para(run("Page "), field("PAGE", "{n}"), run(" of "),
                    field("NUMPAGES", "{t}")), foot=True)
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/footer1.xml": foot.format(n="2", t="14")},
                       {"word/footer1.xml": foot.format(n="11", t="14")}))
    report = compare(a, b)
    assert report["text"] == [] and report["structure"] == [], report
    assert render(report, expect_clean=True) == 0


def test_a_field_replaced_with_typed_text_is_still_an_edit(tmp_path):
    """Masking neutralises the cached RESULT, not the field: a page number
    the author typed over by hand is a real change to the deliverable."""
    live = hdr(para(run("Page "), field("PAGE", "2")), foot=True)
    typed = hdr(para(run("Page "), run("2")), foot=True)
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/footer1.xml": live},
                       {"word/footer1.xml": typed}))
    assert compare(a, b)["text"], "a typed-over field must not be masked away"


def test_a_renumbered_header_part_is_not_added_and_removed(tmp_path):
    """Header parts are numbered after the section that references them, so
    a section edit renames header1 to header2 with the same content. Pairing
    on the name alone would report the whole running head twice — once lost,
    once gained — and bury the real edits under it."""
    head = hdr(para(run("Age-Friendly Index — running head")))
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": head},
                       {"word/header2.xml": head}))
    report = compare(a, b)
    assert report["structure"] == [] and report["text"] == [], report


def test_a_header_only_the_author_has_is_a_structural_change(tmp_path):
    head = hdr(para(run("DRAFT — do not cite")))
    a, b = docs(tmp_path, BASE, BASE,
                extra=({}, {"word/header1.xml": head}))
    report = compare(a, b)
    assert [s["type"] for s in report["structure"]] == ["PART ADDED"], report
    assert report["structure"][0]["part"] == "header1"
    assert render(report, expect_clean=True) == 1


def test_an_empty_note_part_on_one_side_is_not_a_difference(tmp_path):
    """Word writes endnotes.xml into nearly every document — 306 of the
    507 here — carrying nothing but the separator entries. A build that
    does not emit the part has lost no content, and gating on it would
    fail --expect-clean over a part with nothing in it to read."""
    seps = notes("endnotes",
                 '<w:endnote w:type="separator" w:id="-1"><w:p><w:r>'
                 "<w:separator/></w:r></w:p></w:endnote>")
    a, b = docs(tmp_path, BASE, BASE, extra=({}, {"word/endnotes.xml": seps}))
    report = compare(a, b)
    assert report["structure"] == [], report["structure"]
    assert render(report, expect_clean=True) == 0


def test_a_header_paragraph_is_never_matched_against_a_body_one(tmp_path):
    """Pooling every part's paragraphs into one sequence would let a
    running head pair with the title it repeats, and an edit to one would
    surface as a move of the other."""
    title = "Age-Friendly Index"
    head = hdr(para(run(title)))
    a, b = docs(tmp_path, para(run(title)), para(run(title + " (revised)")),
                extra={"word/header1.xml": head})
    report = compare(a, b)
    assert len(report["text"]) == 1, report
    assert "part" not in report["text"][0], "the body stays unlabelled"
    assert report["structure"] == []


def test_a_footnote_link_to_a_body_bookmark_is_not_dangling(tmp_path):
    """Bookmarks are package-wide. Resolving a footnote's citation link
    against the FOOTNOTE part's own names would call every one of them
    dangling — the reference list it points at lives in document.xml."""
    body = para('<w:bookmarkStart w:id="3" w:name="ref_Smith2020"/>'
                + run("Smith, J. (2020). A paper.")
                + '<w:bookmarkEnd w:id="3"/>')
    foot = notes("footnotes",
                 f'<w:footnote w:id="2">{para(run("See "))}'
                 '<w:p><w:hyperlink w:anchor="ref_Smith2020"><w:r>'
                 "<w:t>Smith (2020)</w:t></w:r></w:hyperlink></w:p>"
                 "</w:footnote>")
    a, b = docs(tmp_path, body, body, footnotes=foot)
    report = compare(a, b)
    assert report["integrity"] == [], report["integrity"]


def test_comments_are_reported_but_never_gate(tmp_path):
    """An author round legitimately adds comments the build cannot have,
    so gating on them would put --expect-clean permanently out of reach.
    Staying silent about them is the other way to be wrong."""
    note_to_us = comment(1, "please recheck this figure")
    a, b = docs(tmp_path, BASE, BASE,
                comment_items=((), (note_to_us,)))
    report = compare(a, b)
    assert [c["side"] for c in report["comments"]] == ["user-only"]
    assert "recheck" in report["comments"][0]["text"]
    assert render(report, expect_clean=True) == 0


# ------------------------------------------------------- where it happened
# "in: '0.312…'" tells a reviewer a number changed and leaves them to
# find it. A results table has hundreds of cells that all look like that.


def test_a_changed_table_cell_reports_its_address(tmp_path):
    grid = table(row("Country", "AFI"), row("Poland", "0.31"),
                 row("Hungary", "0.44"))
    a, b = docs(tmp_path, para(run("Intro.")) + grid,
                para(run("Intro.")) + grid.replace("0.44", "0.46"))
    report = compare(a, b)
    assert len(report["text"]) == 1, report
    assert report["text"][0]["at"] == "table 1 r3c2"
    assert "table 1 r3c2" in _rendered(report)


def test_a_paragraph_outside_a_table_has_no_address(tmp_path):
    """An ordinary prose document reads exactly as it did before any of
    this was recorded — the address is only there when it helps."""
    a, b = docs(tmp_path, BASE, BASE.replace("0.35", "0.37"))
    report = compare(a, b)
    assert "at" not in report["text"][0]
    assert '\n  in: "The index rose' in _rendered(report)


def test_a_nested_table_reads_outer_then_inner(tmp_path):
    """Nested tables are real — the sweep found them in these papers —
    and an address that named only one of the two would send a reader
    to the wrong cell."""
    inner = table(row("x", "1"))
    outer = ("<w:tbl><w:tr><w:tc>" + para(run("lead")) + inner
             + "</w:tc></w:tr></w:tbl>")
    a, b = docs(tmp_path, outer, outer.replace(">1<", ">2<"))
    report = compare(a, b)
    # the inner table's SECOND cell, inside the outer table's first
    assert report["text"][0]["at"] == "table 1 r1c1 > table 2 r1c2"


# --------------------------------------------------------- equation typography
# An equation that says the same thing and is SET differently was
# invisible to every layer: FORMULA compares the token stream and the
# structural skeleton, neither of which moves when a variable stops being
# italic, and FORMAT walks <w:t> runs, which an equation has none of. An
# author's italics fix could be dropped by a rebuild with --expect-clean
# still reporting clean.


def math(*runs: str) -> str:
    """An inline equation, for a paragraph that holds prose too."""
    return f"<m:oMath>{''.join(runs)}</m:oMath>"


def omath(*runs: str) -> str:
    return f"<w:p>{math(*runs)}</w:p>"


def mrun(text: str, rpr: str = "") -> str:
    return f"<m:r>{rpr}<m:t>{text}</m:t></m:r>"


@pytest.mark.parametrize("rpr,marker", [
    ("<m:rPr><m:nor/></m:rPr>", "nor"),        # upright, not math-italic
    ("<w:rPr><w:i/></w:rPr>", "i"),
    ("<w:rPr><w:b/></w:rPr>", "b"),
    ('<m:rPr><m:sty m:val="bi"/></m:rPr>', "sty=bi"),
])
def test_equation_typography_is_a_gated_difference(tmp_path, rpr, marker):
    a, b = docs(tmp_path, omath(mrun("x"), mrun("+y")),
                omath(mrun("x", rpr), mrun("+y")))
    report = compare(a, b)
    assert report["formula"] == [], "not a token or structure change"
    assert len(report["formula_format"]) == 1, report
    entry = report["formula_format"][0]
    # named per symbol, so a reader sees WHICH one was reset
    assert entry["from"] == "x:plain"
    assert entry["to"] == f"x:{marker}"
    assert render(report, expect_clean=True) == 1


def test_a_rewritten_equation_is_not_also_reported_as_typography(tmp_path):
    """Typography is consulted only when the skeleton and tokens match.
    An equation that was genuinely rewritten carries its formatting with
    it, and reporting both would be one edit counted twice.

    An equation whose TOKENS changed also changed its paragraph's
    visible text, so it lands in TEXT with a formula flag rather than in
    the FORMULA bucket — that is where to look for it.
    """
    a, b = docs(tmp_path, omath(mrun("x"), mrun("+y")),
                omath(mrun("z", "<w:rPr><w:i/></w:rPr>"), mrun("+y")))
    report = compare(a, b)
    assert [t["formula"] for t in report["text"]] == [["tokens"]]
    assert report["formula_format"] == []


def test_a_restructured_equation_is_not_also_reported_as_typography(tmp_path):
    """The same rule where the paragraphs DO align: identical tokens,
    a different skeleton, and formatting that moved with it. One
    report, of the structure."""
    flat = omath(mrun("x"), mrun("1"))
    sub = omath("<m:sSub><m:e>" + mrun("x", "<w:rPr><w:i/></w:rPr>")
                + "</m:e><m:sub>" + mrun("1") + "</m:sub></m:sSub>")
    report = compare(*docs(tmp_path, flat, sub))
    assert [f["change"] for f in report["formula"]] == ["structure"]
    assert report["formula_format"] == []


@pytest.mark.parametrize("noise", [
    '<w:rPr><w:rFonts w:ascii="Cambria Math"/></w:rPr>',   # on every run
    '<w:rPr><w:lang w:val="en-GB"/></w:rPr>',              # Word rewrites it
    '<w:rPr><w:szCs w:val="24"/></w:rPr>',                 # mirrors w:sz
])
def test_equation_markup_that_is_not_typography_is_ignored(tmp_path, noise):
    """The exclusion list is the false-positive guard, so it is pinned.
    Seven real manuscripts carrying 300+ equations were opened and saved
    by Word and compared against their originals: no typography
    difference was reported for any of them. That is what makes this
    layer safe to gate, and these are the markers that would have
    broken it."""
    a, b = docs(tmp_path, omath(mrun("x"), mrun("+y")),
                omath(mrun("x", noise), mrun("+y")))
    report = compare(a, b)
    assert report["formula_format"] == [], report["formula_format"]
    assert render(report, expect_clean=True) == 0


def test_the_same_equation_split_into_different_runs_is_not_a_change(tmp_path):
    """Word fragments runs at rsid boundaries, so one save writes an
    equation as three runs and the next writes it as two. The
    fingerprint is per CHARACTER for that reason.

    Found on real documents, not here: a per-run version reported 71
    typography changes across 40 version pairs of these papers, and
    inspection of one showed 45 runs against 43 with not a single
    character's formatting altered. Per character the same 40 pairs
    report 2, both of them real.
    """
    three = omath(mrun("x", "<w:rPr><w:i/></w:rPr>"),
                  mrun("+", "<w:rPr><w:i/></w:rPr>"),
                  mrun("y", "<w:rPr><w:i/></w:rPr>"))
    one = omath(mrun("x+y", "<w:rPr><w:i/></w:rPr>"))
    report = compare(*docs(tmp_path, three, one))
    assert report["formula_format"] == [], report["formula_format"]
    assert render(report, expect_clean=True) == 0


def test_typography_switched_off_explicitly_is_not_a_change(tmp_path):
    """`<w:i w:val="0"/>` is italic turned OFF — the same state as no
    marker at all, which is how the prose FORMAT layer reads it too."""
    a, b = docs(tmp_path, omath(mrun("x"), mrun("+y")),
                omath(mrun("x", '<w:rPr><w:i w:val="0"/></w:rPr>'),
                      mrun("+y")))
    assert compare(a, b)["formula_format"] == []


# ------------------------------------------------- what mutation found
# cosmic-ray over _compare_diff.py left survivors clustered on three
# branches no test reached. Each of these kills one cluster: the
# machinery is reported in three kinds and only one kind was exercised,
# an equation count that differs on the two sides was never compared,
# and a field left open was never opened.


def test_a_lost_citation_bookmark_is_named(tmp_path):
    """stripped_fields reports three kinds of loss and only the
    hyperlink one had a test. A cite_ bookmark is what the build
    RESTORES after Word drops it, so losing it silently is the failure
    the FIELD DIFFERENCES layer exists to prevent."""
    before = para('<w:bookmarkStart w:id="4" w:name="cite_Smith2020"/>'
                  + run("As Smith (2020) shows, the effect is small.")
                  + '<w:bookmarkEnd w:id="4"/>')
    after = para(run("As Smith (2020) shows, the effect is negligible."))
    report = compare(*docs(tmp_path, before, after))
    assert report["stripped_fields"], report
    assert "cite_Smith2020" in str(report["stripped_fields"][0]["lost"])
    assert "citation bookmark" in str(report["stripped_fields"][0]["lost"])


# ------------------------------------- the block, not the pair ----------
#
# Inside a replace run the pairing is POSITIONAL, so a block of unequal
# length pairs every paragraph after the difference against its
# neighbour. Asking "did this pair lose a target" of that pairing put
# four present targets on the FIELD layer of Parental Style's comparison
# round — and a dangling-link flag is one this project may never wave
# away, so it cost a diagnosis to disprove.


def _linked(text: str, *anchors: str) -> str:
    return para(run(text) + "".join(
        f'<w:hyperlink w:anchor="{a}"><w:r><w:t>{a}</w:t></w:r>'
        "</w:hyperlink>" for a in anchors))


def test_an_inserted_paragraph_does_not_strip_the_next_ones_fields(tmp_path):
    before = (_linked("Filler above.")
              + _linked("The comparison paragraph as built.",
                        "Gracia2008", "Straus1998")
              + _linked("The second paragraph as built.", "Table2")
              + _linked("Filler below."))
    after = (_linked("Filler above.")
             + _linked("Comparison with high-income evidence")   # a heading
             + _linked("The comparison paragraph, rewritten.",
                       "Gracia2008", "Straus1998")
             + _linked("The second paragraph, rewritten.", "Table2")
             + _linked("Filler below."))
    report = compare(*docs(tmp_path, before, after))
    assert report["text"], "the rewrite itself must still be reported"
    assert report["stripped_fields"] == [], report["stripped_fields"]


def test_a_target_that_moved_to_the_next_paragraph_is_not_lost(tmp_path):
    """The same rule stated the other way: the author moved a citation
    into the following sentence. It is still in the document, and the
    block is the unit that can see that."""
    before = (_linked("The instrument is discussed here.", "Angrist1998")
              + _linked("A second paragraph follows."))
    after = (_linked("The instrument is discussed in what follows.")
             + _linked("A second paragraph follows it.", "Angrist1998"))
    report = compare(*docs(tmp_path, before, after))
    assert report["stripped_fields"] == [], report["stripped_fields"]


def test_a_target_that_moved_out_of_its_block_is_not_lost(tmp_path):
    """The block is the unit, but the PART is the evidence: a link the
    author moved to a paragraph the block does not cover is still in the
    document, and 246 of the layer's remaining false claims over 748 real
    comparisons were exactly that."""
    before = (_linked("The instrument is discussed here.", "Angrist1998")
              + _linked("Unrelated paragraph.")
              + _linked("A distant paragraph, untouched."))
    after = (_linked("The instrument is discussed in what follows.")
             + _linked("Unrelated paragraph.")
             + _linked("A distant paragraph, untouched.", "Angrist1998"))
    report = compare(*docs(tmp_path, before, after))
    assert report["stripped_fields"] == [], report["stripped_fields"]


def test_a_target_that_moved_into_a_footnote_is_not_lost(tmp_path):
    """Package-wide, not part-wide: bookmarks are package-wide in Word,
    and a citation the author moved from the prose into a footnote was
    the last shape of false 'lost' left after the block rule."""
    body_before = _linked("The instrument is discussed here.", "Angrist1998")
    body_after = _linked("The instrument is discussed in the note.")
    moved = ('<w:footnote w:id="2">'
             + para(run("See ") + '<w:hyperlink w:anchor="Angrist1998">'
                    + run("Angrist and Evans (1998)") + "</w:hyperlink>")
             + "</w:footnote>")
    a, b = docs(tmp_path, body_before, body_after,
                footnotes=(notes("footnotes", note("See it.")),
                           notes("footnotes", moved)))
    report = compare(a, b)
    assert report["text"], "the fixture must really differ"
    assert report["stripped_fields"] == [], report["stripped_fields"]


def test_a_target_lost_inside_a_shifted_block_is_still_reported(tmp_path):
    """And the guard must not swallow the finding: same shifted block,
    one target genuinely gone."""
    before = (_linked("Filler above.")
              + _linked("The comparison paragraph as built.",
                        "Gracia2008", "Straus1998")
              + _linked("Filler below."))
    after = (_linked("Filler above.")
             + _linked("Comparison with high-income evidence")
             + _linked("The comparison paragraph, rewritten.", "Gracia2008")
             + _linked("Filler below."))
    report = compare(*docs(tmp_path, before, after))
    lost = str([e["lost"] for e in report["stripped_fields"]])
    assert "Straus1998" in lost, report
    assert "Gracia2008" not in lost, report


def test_a_lost_footnote_reference_is_counted(tmp_path):
    """The third kind. Word drops a footnote reference when an author
    rewrites the sentence around it, and the count is what says how
    many went."""
    ref = '<w:r><w:footnoteReference w:id="2"/></w:r>'
    before = para(run("Kazakhstan reformed its pension system") + ref
                  + run(" in 1998."))
    after = para(run("Kazakhstan reformed its pension scheme in 1998."))
    report = compare(*docs(tmp_path, before, after))
    assert report["stripped_fields"], report
    assert "lost 1 footnote ref(s)" in str(
        report["stripped_fields"][0]["lost"])


def test_an_equation_present_on_one_side_only_is_reported(tmp_path):
    """The two sides are zipped by position, and the shorter one is
    padded with <none>. Without that, a paragraph that LOST an equation
    would compare only the equations it still has and report nothing."""
    # Same visible text, different equation STRUCTURE: two inline
    # equations merged into one, which is what an author (or Word) does
    # to adjacent symbols. The paragraphs still align, so the padding is
    # the only thing that can notice the equation that went.
    two = para(run("Equation (3): "), math(mrun("x")), math(mrun("y")))
    one = para(run("Equation (3): "), math(mrun("x"), mrun("y")))
    report = compare(*docs(tmp_path, two, one))
    assert report["text"] == [], "the visible text is identical"
    assert any("<none>" in str(f["to"]) for f in report["formula"]), report


def test_a_math_minus_against_a_hyphen_is_a_glyph_artifact(tmp_path):
    """Word rewrites the math minus U+2212 as a hyphen on save. That is
    an artifact, not an edit, so it belongs in formula_glyph — which
    does NOT gate — and the generator's glyph is the one to keep."""
    proper = omath(mrun("x"), mrun("−y"))      # U+2212
    worded = omath(mrun("x"), mrun("-y"))      # hyphen-minus
    report = compare(*docs(tmp_path, proper, worded))
    assert report["formula"] == [], report["formula"]
    assert len(report["formula_glyph"]) == 1, report
    assert render(report, expect_clean=True) == 0


def test_a_field_left_open_is_an_integrity_flag(tmp_path):
    """An unbalanced HYPERLINK field renders as literal field code in
    the document — the reader sees the instruction, not the link."""
    broken = para(run("See ")
                  + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                  + '<w:r><w:instrText> REF Table1 \\h </w:instrText></w:r>'
                  + run("Table 1"))
    report = compare(*docs(tmp_path, broken, broken))
    assert any("unbalanced field" in i for i in report["integrity"]), \
        report["integrity"]


def test_a_dangling_anchor_written_as_a_field_is_caught(tmp_path):
    """Anchors come in two forms and both must be resolved: the
    element's w:anchor attribute, and the instruction text of a
    field-form HYPERLINK. A build that emits the field form would
    otherwise have its dangling links go unreported."""
    field_link = para(
        run("See ")
        + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        + '<w:r><w:instrText>HYPERLINK \\l "NoSuchBookmark"'
          "</w:instrText></w:r>"
        + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + run("the appendix")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    report = compare(*docs(tmp_path, field_link, field_link))
    assert any("NoSuchBookmark" in i for i in report["integrity"]), \
        report["integrity"]


def test_a_field_instruction_split_across_runs_resolves(tmp_path):
    """Word splits one instruction over several runs on save, and a pattern
    run over the raw XML walks straight through the tags between them: the
    old `HYPERLINK[^"]*"([^"]+)"` returned the RSID of the following run, so
    every footnote whose field Word had fragmented reported a dangling anchor
    called «00C04908». The instruction is reassembled before it is read."""
    split_field = (
        '<w:p><w:bookmarkStart w:id="9" w:name="Munda2009"/>'
        + run("See ")
        + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        + "<w:r><w:instrText>HYPERLINK</w:instrText></w:r>"
        + '<w:r w:rsidRPr="00C04908"><w:instrText xml:space="preserve">'
          ' \\l "Munda2009" \\h</w:instrText></w:r>'
        + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + run("Munda and Nardo 2009")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        + '<w:bookmarkEnd w:id="9"/></w:p>')
    report = compare(*docs(tmp_path, split_field, split_field))
    assert not any("00C04908" in i for i in report["integrity"]), \
        report["integrity"]
    assert not report["integrity"], report["integrity"]


# ---------------------------------------------- the reading layer, mutated
# A second cosmic-ray pass, over _compare_read.py: 122 survivors, and
# they clustered on the part pairing, the nesting guard in the field
# masking, and three of the four run properties FORMAT knows about.


def test_leftover_parts_too_different_to_be_the_same_one_are_not_paired(
        tmp_path):
    """The similarity fallback exists for a header Word RENUMBERED, not
    for any two orphans. Pairing unrelated parts would report one as a
    rewrite of the other and hide that a header was lost outright."""
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml":
                        hdr(para(run("Age-Friendly Index — running head")))},
                       {"word/header2.xml":
                        hdr(para(run("Confidential draft: do not circulate "
                                     "or cite without permission")))}))
    report = compare(a, b)
    kinds = sorted(s["type"] for s in report["structure"])
    assert kinds == ["PART ADDED", "PART REMOVED"], report["structure"]
    assert report["text"] == [], "unrelated parts are not a text edit"


def test_the_most_similar_leftover_part_wins(tmp_path):
    """With two candidates, the pairing must take the better one — a
    first-match rule would pair the running head with whichever part
    happened to come first and report both as rewritten."""
    head = "Age-Friendly Index — running head"
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": hdr(para(run(head)))},
                       {"word/header2.xml":
                        hdr(para(run("Wholly unrelated boilerplate here"))),
                        "word/header3.xml":
                        hdr(para(run(head + " (revised)")))}))
    report = compare(a, b)
    # header1 pairs with header3 and shows a text edit; header2 is new
    assert [t.get("part") for t in report["text"]] == ["header1"], report
    assert any("revised" in str(d) for d in report["text"][0]["word_diff"])
    assert [s["type"] for s in report["structure"]] == ["PART ADDED"]


def test_nested_volatile_fields_are_masked_exactly_once():
    """The guard tested where it can be SEEN.

    Masking is offset arithmetic on one string, right to left. Register
    a region already inside another and the inner rewrite shifts the
    outer's stored offsets, so the outer slice cuts in the wrong place.
    The end-to-end comparison cannot catch that — it mangles both sides
    identically and reports clean — so this asserts on the masked XML:
    one token, and every field character still there.
    """
    from lxml import etree

    from docxkit._compare_read import mask_volatile_fields
    inner = field("PAGE", "7")
    nested = ("<w:p>"
              '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText> PAGEREF _Toc1 </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              + inner
              + '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    out = mask_volatile_fields(nested)
    assert re.findall(r"«F:\w+»", out) == ["«F:PAGEREF»"], out
    assert out.count("w:fldChar") == nested.count("w:fldChar")
    etree.fromstring(('<w:p xmlns:w="http://schemas.openxmlformats.org/'
                      'wordprocessingml/2006/main">'
                      + out[len("<w:p>"):]).encode())


def test_masking_a_field_does_not_touch_the_prose_around_it():
    """What the nested test could not see. `result_at = start + sep.end()`
    had seven surviving mutants — `-`, `//`, `%`, `>>`, `|`, `&`, `^` —
    because the existing fixture asserts only which tokens appear, and
    the outer mask overwrites a wrongly-masked inner one either way. A
    wrong offset masks the wrong REGION: the prose beside the field, or a
    slice starting inside a tag."""
    from docxkit._compare_read import mask_volatile_fields
    xml = ("<w:p>" + run("Chapter opening. ")
           + field("PAGE", "7")
           + run(" and the sentence continues.") + "</w:p>")
    out = mask_volatile_fields(xml)
    assert "Chapter opening. " in out
    assert " and the sentence continues." in out
    assert "«F:PAGE»" in out and ">7<" not in out
    assert out.count("w:fldChar") == xml.count("w:fldChar")


def test_a_field_that_is_not_volatile_keeps_its_result():
    """The `not in VOLATILE_FIELDS` test, from the fldSimple side."""
    from docxkit._compare_read import mask_volatile_fields
    simple = ('<w:p><w:fldSimple w:instr=" AUTHOR ">'
              + run("M. Lokshin") + "</w:fldSimple></w:p>")
    assert mask_volatile_fields(simple) == simple


def test_a_volatile_fldSimple_is_masked():
    from docxkit._compare_read import mask_volatile_fields
    simple = ('<w:p><w:fldSimple w:instr=" PAGE  \\* MERGEFORMAT ">'
              + run("12") + "</w:fldSimple></w:p>")
    out = mask_volatile_fields(simple)
    assert "«F:PAGE»" in out and ">12<" not in out


def test_a_volatile_field_inside_another_is_masked_once(tmp_path):
    """The same guard from the outside: a nested cached value must not
    reach the report either."""
    inner = field("PAGE", "7")
    outer = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText> PAGEREF _Toc1 </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             + inner
             + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/footer1.xml": hdr(para(outer), foot=True)},
                       {"word/footer1.xml": hdr(
                           para(outer.replace(">7<", ">9<")), foot=True)}))
    report = compare(a, b)
    assert report["text"] == [] and report["structure"] == [], report
    assert render(report, expect_clean=True) == 0


@pytest.mark.parametrize("prop,shown", [
    ("<w:b/>", "bold"),
    ("<w:strike/>", "strike"),
    ("<w:smallCaps/>", "smallCaps"),
    ('<w:vertAlign w:val="superscript"/>', "superscript"),
])
def test_every_run_property_the_format_layer_knows(tmp_path, prop, shown):
    """Italic had a test and the other four did not, so a mutation that
    stopped reading any of them survived."""
    plain = para(run("See the Journal of Things here."))
    marked = ('<w:p><w:r><w:t xml:space="preserve">See the </w:t></w:r>'
              f"<w:r><w:rPr>{prop}</w:rPr><w:t>Journal of Things</w:t></w:r>"
              '<w:r><w:t xml:space="preserve"> here.</w:t></w:r></w:p>')
    report = compare(*docs(tmp_path, plain, marked))
    assert report["text"] == []
    assert any(shown in str(e) for e in report["format"]), report["format"]


# ------------------------------------------- size and colour ------------
# Both were invisible to every layer until 2026-08-10: `--expect-clean`
# printed OK on a pair whose entire difference was 25 runs' size and
# colour. They are RESOLVED through the styles rather than read off the
# run, because Word deletes a direct property equal to the inherited one.

STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
          'wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault>'
          '<w:rPr><w:sz w:val="24"/></w:rPr></w:rPrDefault>'
          "</w:docDefaults>"
          '<w:style w:type="paragraph" w:styleId="Note">'
          '<w:rPr><w:sz w:val="20"/></w:rPr></w:style>'
          '<w:style w:type="character" w:styleId="Hyperlink">'
          '<w:rPr><w:color w:val="0563C1"/></w:rPr></w:style>'
          "</w:styles>")


def _sized(size: str | None = None, colour: str | None = None,
           pstyle: str | None = None, rstyle: str | None = None) -> str:
    rpr = ""
    if rstyle:
        rpr += f'<w:rStyle w:val="{rstyle}"/>'
    if colour:
        rpr += f'<w:color w:val="{colour}"/>'
    if size:
        rpr += f'<w:sz w:val="{size}"/>'
    ppr = f'<w:pPr><w:pStyle w:val="{pstyle}"/></w:pPr>' if pstyle else ""
    props = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return (f"<w:p>{ppr}<w:r>{props}"
            f"<w:t>The estimate is robust.</w:t></w:r></w:p>")


def _styled(tmp_path, a_body: str, b_body: str):
    return docs(tmp_path, a_body, b_body,
                extra={"word/styles.xml": STYLES})


def test_a_size_change_is_a_format_difference(tmp_path):
    """The gap this closes: `--expect-clean` said OK on a pair whose
    whole difference was the size of 25 runs."""
    report = compare(*_styled(tmp_path, _sized("20"), _sized("24")))
    assert report["text"] == []
    assert any("size 20" in str(e) and "size 24" in str(e)
               for e in report["format"]), report["format"]


def test_a_colour_change_is_a_format_difference(tmp_path):
    report = compare(*_styled(tmp_path, _sized(colour="000000"),
                              _sized(colour="1F3864")))
    assert any("colour 1F3864" in str(e) for e in report["format"])


def test_a_redundant_declaration_is_not_a_difference(tmp_path):
    """The reason these are RESOLVED and not read off the run. Word
    deletes a direct property equal to the inherited one — measured on
    2026-08-10, its Compare dropped a `w:sz 20` from a run whose
    paragraph style already said 20. Both sides render at 10pt, and a
    comparison of what is STATED calls that a change on every author
    round-trip."""
    states_it = _sized("20", pstyle="Note")
    inherits_it = _sized(pstyle="Note")
    report = compare(*_styled(tmp_path, states_it, inherits_it))
    assert report["format"] == [], report["format"]
    assert render(report, expect_clean=True) == 0


def test_dropping_a_declaration_that_changes_the_render_IS_a_difference(
        tmp_path):
    """The mirror, and the defect that started this: a run that stated
    10pt and now states nothing, in a paragraph with NO style, falls to
    the 12pt document default."""
    report = compare(*_styled(tmp_path, _sized("20"), _sized()))
    assert any("size 20" in str(e) and "size 24" in str(e)
               for e in report["format"]), report["format"]


def test_a_character_style_supplies_the_value_too(tmp_path):
    """A run naming the Hyperlink style and one stating its colour
    directly render the same."""
    report = compare(*_styled(tmp_path, _sized(rstyle="Hyperlink"),
                              _sized(colour="0563C1", rstyle="Hyperlink")))
    assert report["format"] == [], report["format"]


def test_a_link_that_changed_colour_is_reported(tmp_path):
    """Hyperlink runs contribute no EMPHASIS — their underline is
    structural — but their colour is compared like anything else's. One
    manuscript's citation links sat in Word's default blue while every
    other link in the paper was the house navy, and nothing said so."""
    report = compare(*_styled(tmp_path, _sized(rstyle="Hyperlink"),
                              _sized(colour="1F3864", rstyle="Hyperlink")))
    assert any("colour 1F3864" in str(e) for e in report["format"])


def test_auto_and_absent_are_the_same_claim_about_colour(tmp_path):
    """Word writes each in different years of the same document."""
    report = compare(*_styled(tmp_path, _sized(), _sized(colour="auto")))
    assert report["format"] == [], report["format"]


def test_without_a_styles_part_the_layer_compares_emphasis_only(tmp_path):
    """Silence rather than a guess: with nothing to resolve THROUGH, a
    stated-value comparison would report the redundant-declaration case
    above as a change on every round-trip."""
    report = compare(*docs(tmp_path, _sized("20"), _sized("24")))
    assert report["format"] == []
    italic = _sized("20").replace("<w:rPr>", "<w:rPr><w:i/>")
    still = compare(*docs(tmp_path, _sized("20"), italic))
    assert any("italic" in str(e) for e in still["format"])


def test_parts_are_reported_in_a_stable_order(tmp_path):
    """Two runs must list their parts the same way, or a reader
    comparing today's report to yesterday's is reading noise."""
    from docxkit.compare import load_parts
    parts = make_parts(BASE, footnotes=notes("footnotes", note("a note")),
                       extra={"word/endnotes.xml":
                              notes("endnotes", note("an endnote",
                                                     kind="endnote")),
                              "word/header1.xml": hdr(para(run("head"))),
                              "word/footer1.xml": hdr(para(run("foot")),
                                                      foot=True)})
    assert [p.label for p in load_parts(parts).parts] == [
        "body", "footnotes", "endnotes", "header1", "footer1"]


def test_the_comparison_layers_stay_acyclic():
    """Each layer may import only from the ones below it.

    read <- diff <- render, with compare.py the facade over all three:
    reading knows nothing of differences, diffing knows nothing of files
    or printing, rendering knows nothing of XML. The facade's own import
    of the CLI's JSON writer is deferred into the function that needs it
    for the same reason — at module level it would be a cycle.

    Written because the citations split needed the same guard for the
    same reason: a layering nobody checks is a layering that will not
    hold. This one is what stops the next feature landing in whichever
    file it was easiest to reach.
    """
    import ast
    from pathlib import Path

    import docxkit
    src = Path(docxkit.__file__).parent
    order = ["_compare_read", "_compare_diff", "_compare_render"]
    for i, mod in enumerate(order):
        tree = ast.parse((src / f"{mod}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module in order:
                assert order.index(node.module) < i, (
                    f"{mod} imports from {node.module}, which is not "
                    "below it")
            assert node.module != "compare", (
                f"{mod} imports the facade — that is a cycle")


def test_the_facade_still_exports_what_callers_import():
    """The re-exports are load-bearing and ruff --fix strips a plain one
    as unused, which is why they are written `from x import y as y`.
    These are the names the CLI, the sweep, the tests and the papers
    reach for; losing one is a broken import at someone else's build."""
    import docxkit.compare as facade
    for name in ("compare", "compare_docs", "render", "load", "load_parts",
                 "word_diff", "integrity", "hyperlink_labels", "Doc",
                 "Para", "Part", "GATED", "VOLATILE_FIELDS",
                 "mask_volatile_fields"):
        assert hasattr(facade, name), f"compare.{name} is gone"


def test_a_link_only_in_the_user_copy_is_reported_for_review(tmp_path):
    """The built-only side of this layer had a test; the user-only side
    had none, so half of it could stop working unnoticed.

    A link present only in the author's copy is either a build
    regression or prose the author bled into a link. Neither shows in
    TEXT — the words still match exactly — which is the whole reason
    this layer sits alongside it.
    """
    linked = para(run("As ")
                  + '<w:hyperlink w:anchor="ref_Smith2020"><w:r>'
                    "<w:t>Smith (2020)</w:t></w:r></w:hyperlink>"
                  + run(" argues."))
    report = compare(*docs(tmp_path, para(run("As Smith (2020) argues.")),
                           linked))
    assert report["text"] == [], report["text"]
    assert [(h["side"], h["label"]) for h in report["hyperlinks"]] == [
        ("user-only", "Smith (2020)")]


def test_both_command_lines_are_one_comparison(tmp_path, monkeypatch, capsys):
    """`docxkit compare` and `python -m docxkit.compare` are two front
    doors to one comparison, and they have drifted before.

    The last-resort JSON encoder was added to the CLI's path and not to
    the module's own — so the entry point living in the very file the
    fix was written for could still finish a comparison and lose it at
    the final step. Nothing failed when they disagreed. This asserts
    they agree on both things a caller can observe: the exit code, and
    the bytes written to --json.
    """
    from docxkit import cli
    from docxkit import compare as facade

    a, b = docs(tmp_path, BASE, BASE.replace("0.35", "0.37"))
    seen = {}
    for name, entry, argv0 in (("cli", cli.main, ["docxkit", "compare"]),
                               ("module", facade.main, ["docxkit-compare"])):
        dest = tmp_path / f"{name}.json"
        monkeypatch.setattr("sys.argv", [*argv0, a, b, "--expect-clean",
                                         "--json", str(dest)])
        with pytest.raises(SystemExit) as exc:
            entry()
        capsys.readouterr()
        code = exc.value.code
        seen[name] = (0 if code is None else code,
                      dest.read_text(encoding="utf-8"))

    assert seen["cli"][0] == seen["module"][0] == 1, seen
    assert seen["cli"][1] == seen["module"][1], "the two reports differ"
    assert '"text"' in seen["cli"][1] and "0.37" in seen["cli"][1]


@pytest.mark.parametrize("door", ["cli", "module"])
def test_neither_door_loses_a_report_json_cannot_encode(
        tmp_path, monkeypatch, capsys, door):
    """The exact bug the facade's own comment records, on both doors.

    `_json_default` exists because the worst moment to fail is the last
    one: the comparison already done, the report never written. Today no
    layer emits a set — the encoder is a seatbelt for the one that will
    — so nothing in the ordinary fixtures exercises it, and the door
    that lacked it looked exactly like the door that had it.
    """
    from docxkit import cli
    from docxkit import compare as facade

    a, b = docs(tmp_path, BASE, BASE)

    def with_a_set(path_a, path_b):
        rep = facade.compare_docs(facade.load(path_a), facade.load(path_b))
        rep["structure"].append({"type": "PART REMOVED", "part": "body",
                                 "text": "a part", "names": {"b1", "b2"}})
        return rep

    monkeypatch.setattr(facade, "compare", with_a_set)
    entry = cli.main if door == "cli" else facade.main
    argv0 = ["docxkit", "compare"] if door == "cli" else ["docxkit-compare"]
    dest = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", [*argv0, a, b, "--json", str(dest)])

    with pytest.raises(SystemExit):
        entry()
    capsys.readouterr()

    import json
    assert dest.exists(), f"{door}: the finished comparison never reached disk"
    assert json.loads(dest.read_text(encoding="utf-8")
                      )["structure"][0]["names"] == ["b1", "b2"]


# ------------------------------------------------------------ the report
# A cosmic-ray pass over _compare_render.py: 204 mutants, 62 killed, 82
# survived. They were not scattered — nearly all of them said one thing.
# render() had its RETURN value tested and its OUTPUT tested nowhere, so
# a mutation that stopped a layer printing its entries, or miscounted the
# summary, or printed "(none)" over a list of real differences, changed
# nothing any test looked at.
#
# That inverts the module's whole reason for existing. Its docstring is
# "nothing here truncates a list or summarises a count in place of the
# entries" — a report a reader has to guess at is the failure this tool
# is FOR. The exit code was pinned; the report a human acts on was not.
#
# The worst cluster was the arithmetic behind the gate (:145-146): eleven
# mutants of `real = structure + text + formula + formula_format + format`
# survived, because every existing fixture fills ONE bucket, and three of
# the five buckets had no test that reached the exit code at all. A
# dropped term means a real difference silently stops failing
# --expect-clean, which every paper round reads as "nothing left to
# integrate".

def _empty_report() -> Report:
    return {k: [] for k in ("structure", "text", "glyph", "formula",
                            "formula_glyph", "formula_format", "format",
                            "hyperlinks", "integrity", "stripped_fields",
                            "comments")}


def _entry(bucket: str) -> object:
    """One entry, shaped as the producers really build them.

    Keys come from the code that emits them, not from what the renderer
    happens to read: _compare_diff structure :371/:379/:384, text :348,
    format :318, formula :139, stripped_fields :353, comments :442, and
    compare.py :134 for hyperlinks. A fixture inventing its own shapes
    would test the renderer against fiction.
    """
    mark = f"MARK-{bucket}"
    return {
        "structure": {"type": "DELETE", "part": "footnotes", "text": mark,
                      "lost_fields": {"anchors": [], "cites": [],
                                      "footnotes": 0}},
        "text": {"context": mark, "at": "table 3 r2c1",
                 "word_diff": [f"- {mark}-old", f"+ {mark}-new"]},
        "formula": {"change": "tokens", "from": f"{mark}-from",
                    "to": f"{mark}-to"},
        "formula_format": {"change": "formatting", "from": f"{mark}-from",
                           "to": f"{mark}-to"},
        # `from` carries a MARK rather than a plain "italic": the FORMAT
        # heading is "(italic/bold/super/sub/strike, ...)", so asserting
        # "italic" in the output passed on the HEADING and said nothing
        # about the entry. A mutation blanking this side survived under
        # exactly that vacuous assertion.
        "format": {"text": mark, "from": [f"{mark}-from"], "to": []},
        "glyph": {"from": f"{mark}-from", "to": f"{mark}-to"},
        # from/to are TUPLES here and the renderer prints element [1] —
        # element 0 is the equation id, so an off-by-one prints the
        # wrong half of the pair.
        "formula_glyph": {"change": "glyph", "from": ("eq1", f"{mark}-from"),
                          "to": ("eq1", f"{mark}-to")},
        "hyperlinks": {"side": "user-only", "label": mark, "n": 1},
        "comments": {"side": "user-only", "text": mark, "n": 1},
        "integrity": mark,                       # a plain string, not a dict
        "stripped_fields": {"context": mark, "lost": [f"{mark}-lost"]},
    }[bucket]


def _out(report: Report, expect_clean: bool = False) -> tuple[int, str]:
    """The exit code AND the page — the half never asserted."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = render(report, expect_clean)
    return code, buf.getvalue()


def _filled(**sizes: int) -> Report:
    report = _empty_report()
    for bucket, n in sizes.items():
        report[bucket] = [_entry(bucket)] * n
    return report


def _section(out: str, heading: str) -> str:
    """The body under ONE heading.

    The rules `_head` draws are the only reliable boundary, and the last
    section runs straight into the summary — so a naive "everything
    after the heading" slice reads the NEXT layer's "(none)" as this
    one's, which is exactly the false pass this helper exists to stop.
    """
    # Split on the rule as a SHAPE, not at its current width: re-flowing
    # the report to 80 columns is a cosmetic change and must not fail
    # every test here with "no section headed ...".
    chunks = re.split(r"^={5,}$", out, flags=re.MULTILINE)
    for i in range(1, len(chunks) - 1, 2):
        if chunks[i].strip().startswith(heading):
            return re.split(r"^-{5,}$", chunks[i + 1], flags=re.MULTILINE)[0]
    raise AssertionError(f"no section headed {heading!r} in:\n{out}")


@pytest.mark.parametrize("bucket", list(GATED))
def test_every_gated_layer_fails_the_gate_on_its_own(bucket):
    """--expect-clean must fail on ANY gated layer.

    Only text, structure and formula_format had a test that reached the
    exit code; formula and format had fixtures that filled the bucket
    and stopped there. Dropping either term left a real difference no
    longer failing the gate, and nothing went red.
    """
    assert _out(_empty_report(), expect_clean=True)[0] == 0, "empty is clean"
    code, _ = _out(_filled(**{bucket: 1}), expect_clean=True)
    assert code == 1, f"a difference in {bucket} alone did not fail the gate"


def test_an_integrity_flag_alone_fails_the_gate():
    """The sixth term, and the only one in the OR rather than the sum: a
    built doc whose bookmarks do not balance is not shippable even when
    every visible layer matches."""
    assert _out(_filled(integrity=1), expect_clean=True)[0] == 1


@pytest.mark.parametrize("sizes", [
    (1, 1, 1, 1, 1), (1, 3, 1, 1, 2), (3, 1, 4, 1, 1),
    (0, 2, 0, 1, 0), (2, 0, 1, 0, 3), (0, 0, 0, 0, 1),
])
def test_the_headline_total_is_every_gated_layer_summed(sizes):
    """The number a reader acts on is the sum of all five, not of the
    ones a fixture happened to fill. Asserted as the relationship over
    several shapes rather than one magic constant — a single shape lets
    an arithmetic slip land on the right answer by luck."""
    # strict=True is load-bearing: a sixth gated layer must fail this
    # test rather than silently go uncounted here.
    report = _filled(**dict(zip(GATED, sizes, strict=True)))
    _, out = _out(report)
    assert f"REAL change locations (excl. glyph): {sum(sizes)}" in out, out


@pytest.mark.parametrize("glyph,formula_glyph", [
    (1, 1), (3, 1), (1, 3), (2, 2), (0, 2), (2, 0)])
def test_the_glyph_total_is_both_glyph_layers_summed(glyph, formula_glyph):
    _, out = _out(_filled(glyph=glyph, formula_glyph=formula_glyph))
    assert f"glyph-only: {glyph + formula_glyph}" in out, out


def test_the_summary_counts_each_review_layer_separately():
    """Four counts share one line, and a reader tells "nothing to do"
    from "eyeball these" by which number moved."""
    _, out = _out(_filled(integrity=2, stripped_fields=3, hyperlinks=1,
                          comments=4))
    for label, n in (("built-doc integrity flags", 2),
                     ("field-restores (info)", 3),
                     ("hyperlink diffs (review)", 1),
                     ("comment diffs (review)", 4)):
        assert f"{label}: {n}" in out, f"{label} miscounted:\n{out}"


def _marks(value: object) -> set[str]:
    """Every MARK- token an entry carries, however deeply nested.

    Asserting on the bucket's own name was not enough: an entry whose
    two halves both said "MARK-formula_glyph" still printed one of them
    when a mutation read the wrong tuple element. Collecting the tokens
    means each printed FIELD is pinned, not each layer.
    """
    # Found ANYWHERE in the string, not just at its start: a word_diff
    # line really reads "- 0.35", so a start-anchored match collected
    # nothing from the one layer whose content IS those lines, and the
    # mutation that stopped printing them stayed green.
    if isinstance(value, str):
        return set(re.findall(r"MARK-[\w-]+", value))
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        return {m for v in value for m in _marks(v)}
    return set()


@pytest.mark.parametrize("bucket", [
    "structure", "text", "glyph", "formula", "formula_glyph",
    "formula_format", "format", "hyperlinks", "integrity",
    "stripped_fields", "comments"])
def test_every_layer_prints_every_part_of_its_entry(bucket):
    """Each layer must SAY what it found, in full. Eleven mutants
    emptied one loop apiece and survived: the summary count was still
    right, so the report claimed differences it then declined to name.

    Every field is asserted, not just one per layer — the word-level
    diff under a TEXT entry and the second half of a glyph pair are
    the CONTENT of those layers, and both had mutations that dropped
    them while the entry's other half still printed.
    """
    entry = _entry(bucket)
    expected = _marks(entry)
    assert expected, f"{bucket}: the fixture carries no marks to look for"
    _, out = _out(_filled(**{bucket: 1}))
    missing = sorted(m for m in expected if m not in out)
    assert not missing, f"{bucket} never printed {missing}:\n{out}"


def test_a_format_change_prints_both_sides_and_names_the_empty_one():
    """'was -> ∅' is the whole content of a FORMAT entry; either side
    printing the other's value makes it unreadable.

    Asserted inside the SECTION, because the heading names four run
    properties and matching against the whole page reads the heading
    instead of the entry.
    """
    body = _section(_out(_filled(format=1))[1], "FORMAT")
    assert "MARK-format-from" in body, body
    assert "∅" in body, body


def test_the_integrity_line_claims_clean_only_when_it_is():
    """INTEGRITY is the one section whose empty state is a CLAIM rather
    than a blank — "(clean: bookmarks balanced, no dangling anchors)" is
    what a reader takes as permission to ship, so printing it over a
    list of flags is the worst sentence in the report."""
    head = "BUILT-DOC INTEGRITY"
    assert "(clean:" in _section(_out(_empty_report())[1], head)
    assert "(clean:" not in _section(_out(_filled(integrity=1))[1], head)


@pytest.mark.parametrize("bucket,heading", [
    ("structure", "STRUCTURE"), ("text", "TEXT"), ("formula", "FORMULA"),
    ("formula_format", "FORMULA TYPOGRAPHY"), ("format", "FORMAT"),
    ("hyperlinks", "HYPERLINK"), ("comments", "COMMENTS"),
    ("stripped_fields", "FIELD DIFFERENCES")])
def test_a_layer_with_nothing_in_it_says_so(bucket, heading):
    """"(none)" under a heading is how a reader tells "clean" from
    "this layer did not run". Printing it over a list of real
    differences is the same bug in the other direction, so both
    directions are asserted."""
    empty = _section(_out(_empty_report())[1], heading)
    assert "(none)" in empty, f"{heading} did not say none:\n{empty}"

    filled = _section(_out(_filled(**{bucket: 1}))[1], heading)
    assert "(none)" not in filled, f"{heading} claimed none:\n{filled}"


def test_a_clean_glyph_layer_says_none_only_when_both_halves_are_empty():
    """GLYPH is the one section fed by two buckets, so its "(none)"
    hangs on an `and` that a single-bucket fixture cannot exercise."""
    for filled in ({"glyph": 1}, {"formula_glyph": 1},
                   {"glyph": 1, "formula_glyph": 1}):
        section = _section(_out(_filled(**filled))[1], "GLYPH")
        assert "(none)" not in section, f"{filled}:\n{section}"
    assert "(none)" in _section(_out(_empty_report())[1], "GLYPH")


@pytest.mark.parametrize("bucket", ["hyperlinks", "comments"])
@pytest.mark.parametrize("n,shown", [(1, False), (2, True), (5, True)])
def test_a_label_seen_more_than_once_prints_its_count(bucket, n, shown):
    """One occurrence prints bare; several print ' xN'. The threshold is
    the whole point — a citation link that went from one occurrence to
    four is a different report than one that moved."""
    report = _filled(**{bucket: 1})
    report[bucket][0] = {**report[bucket][0], "n": n}
    _, out = _out(report)
    assert (f" x{n}" in out) is shown, f"n={n}:\n{out}"


def test_the_expect_clean_verdict_is_printed_only_when_asked():
    """A plain run reports; --expect-clean also renders a verdict. The
    verdict appearing on a run that never asked for it tells a reader
    the build was gated when it was not."""
    clean = _empty_report()
    assert "EXPECT-CLEAN" not in _out(clean, expect_clean=False)[1]
    assert "EXPECT-CLEAN OK" in _out(clean, expect_clean=True)[1]
    assert "EXPECT-CLEAN FAILED" in _out(_filled(text=1), expect_clean=True)[1]


@pytest.mark.parametrize("lost", [
    {"anchors": ["ref_Smith2020"], "cites": [], "footnotes": 0},
    {"anchors": [], "cites": ["cite_Smith2020"], "footnotes": 0},
])
def test_a_deleted_paragraph_names_the_fields_it_lost(lost):
    """Either kind alone must raise the annotation. It is an `or`, and
    a fixture that sets both cannot tell a dead branch from a live one —
    which is how a mutation that read only one side survived."""
    report = _filled(structure=1)
    report["structure"][0] = {**report["structure"][0], "lost_fields": lost}
    _, out = _out(report)
    assert "LOST FIELDS" in out, out


def test_a_moved_paragraph_prints_its_ratio_and_a_deleted_one_does_not():
    """The move ratio is what says whether a MOVE is the same paragraph
    or two that merely rhyme."""
    report = _filled(structure=1)
    report["structure"][0] = {"type": "MOVE", "ratio": 0.93, "text": "moved"}
    assert "move ratio 0.93" in _out(report)[1]
    assert "move ratio" not in _out(_filled(structure=1))[1]


def test_word_diff_pinpoints_a_single_edit_in_a_repetitive_paragraph():
    """difflib's autojunk treats any token filling >1% of a long
    sequence as noise, so in a repetitive paragraph a one-word edit came
    back as one enormous replace block. The paragraph matchers in this
    module already pass autojunk=False; word_diff did not."""
    from docxkit.compare import word_diff
    a = " ".join(["the quantity of the good and the price of the good"] * 40)
    b = a.replace("price of the good", "price of the service", 1)
    out = word_diff(a, b)
    # localised to the clause that changed, not the 440-word paragraph
    assert sum(len(line) for line in out) < 150, out
    assert any("service" in line for line in out), out
