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
    document,
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


def test_a_label_that_swallowed_its_caption_is_named_as_one_finding(tmp_path):
    """Both sides of one edit, said once. This layer was the only place
    Parental Style's swallowed Table 4 caption was visible, and it was
    visible as two lines a reader had to correlate — a built-only
    'Table 4' and a user-only label carrying the whole caption."""
    caption = ('<w:hyperlink w:anchor="Table4txt"><w:r><w:t>Table 4'
               "</w:t></w:r></w:hyperlink>")
    swollen = ('<w:hyperlink w:anchor="Table4txt"><w:r><w:t>Table 4: The '
               "likelihood of coercive discipline</w:t></w:r></w:hyperlink>")
    tail = run(": The likelihood of coercive discipline")
    a, b = docs(tmp_path, para(caption + tail), para(swollen))
    report = compare(a, b)
    grew = [h for h in report["hyperlinks"] if h["side"] == "grew"]
    assert len(grew) == 1, report["hyperlinks"]
    assert grew[0]["label"] == "Table 4"
    assert grew[0]["to"].startswith("Table 4: The likelihood")
    # and the pair is not ALSO printed as two unrelated singletons
    assert not [h for h in report["hyperlinks"]
                if h["side"] in ("built-only", "user-only")]


def test_the_grown_label_is_PRINTED_as_one_line(tmp_path):
    """The layer is only useful if a reader meets the pair as a pair."""
    caption = ('<w:hyperlink w:anchor="Table4txt"><w:r><w:t>Table 4'
               "</w:t></w:r></w:hyperlink>")
    swollen = ('<w:hyperlink w:anchor="Table4txt"><w:r><w:t>Table 4: The '
               "likelihood of coercive discipline</w:t></w:r></w:hyperlink>")
    a, b = docs(tmp_path,
                para(caption + run(": The likelihood of coercive discipline")),
                para(swollen))
    out = _rendered(compare(a, b))
    assert "[grew] 'Table 4' -> 'Table 4: The likelihood" in out, out


def test_an_unrelated_pair_of_labels_is_not_paired(tmp_path):
    """Containment is the pairing rule because it is what the mechanism
    leaves behind. Two different links changing is still two lines."""
    a_body = para('<w:hyperlink w:anchor="A"><w:r><w:t>Smith (2020)'
                  "</w:t></w:r></w:hyperlink>")
    b_body = para('<w:hyperlink w:anchor="A"><w:r><w:t>Jones (2021)'
                  "</w:t></w:r></w:hyperlink>")
    report = compare(*docs(tmp_path, a_body, b_body))
    sides = sorted(h["side"] for h in report["hyperlinks"])
    assert sides == ["built-only", "user-only"], report["hyperlinks"]


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


def test_an_equation_ADDED_is_reported_from_the_other_side(tmp_path):
    """The mirror of the padding above, and the direction a rebuild
    produces: an equation appears where the baseline had none, and the
    entry says so with <none> on the side that did not have it."""
    one = para(run("Equation (3): "), math(mrun("x"), mrun("y")))
    two = para(run("Equation (3): "), math(mrun("x")), math(mrun("y")))

    report = compare(*docs(tmp_path, one, two))

    assert report["text"] == [], "the visible text is identical"
    assert any("<none>" in str(f["from"]) for f in report["formula"]), report


def test_the_typography_of_an_added_equation_is_padded_too(tmp_path):
    """The format lists are indexed with the same bound as the equations
    they belong to; reading past one of them raises from inside the
    comparison rather than reporting the difference."""
    plain = para(run("See "), math(mrun("x"), mrun("y")))
    extra = para(run("See "), math(mrun("x")),
                 math('<m:r><m:rPr><m:nor/></m:rPr><m:t>y</m:t></m:r>'))

    report = compare(*docs(tmp_path, plain, extra))

    assert any("<none>" in str(f["from"]) for f in report["formula"]), report


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


# --- what the first mutation run found (2026-08-17, 5.3 % survival) ---
#
# The lowest-survival module measured, and what it left was the report's
# SHAPE: the width of the rules that separate its sections, and a loop
# that must not stop at the first entry of its kind.

def test_the_section_rules_are_seventy_two_characters():
    """`_section` above splits on the rule as a SHAPE so that re-flowing
    the report is a cosmetic change — which leaves the width itself
    unasserted anywhere. It is read in a terminal beside a diff, and a
    rule of a different width from the one above reads as a different
    level of heading."""
    _code, out = _out(_empty_report())

    rules = {ln for ln in out.splitlines() if set(ln) in ({"="}, {"-"})}

    assert rules, out
    assert all(len(rule) == 72 for rule in rules), sorted(rules)


def test_every_HYPERLINK_entry_prints_not_just_the_first():
    """`continue`, not `break`. The entry naming both sides of a label
    prints on its own line and the loop goes on; stopping there hides
    every link after it — and this layer exists because a label that
    swallowed prose is invisible to all the others."""
    report = _empty_report()
    report["hyperlinks"] = [
        {"side": "grew", "label": "Table 4", "to": "Table 4: The gap",
         "n": 1},
        {"side": "user-only", "label": "Table 5", "n": 1}]

    _code, out = _out(report)

    assert "'Table 4'" in out
    assert "'Table 5'" in out


def test_a_stripped_FIELD_prints_the_context_it_has():
    report = _empty_report()
    report["stripped_fields"] = [
        {"part": "document", "context": "the sentence about coverage",
         "lost": "HYPERLINK"}]

    _code, out = _out(report)

    assert "the sentence about coverage…" in out


def test_a_stripped_field_with_NO_context_still_prints_what_was_lost():
    report = _empty_report()
    report["stripped_fields"] = [
        {"part": "document", "context": "", "lost": "HYPERLINK"}]

    _code, out = _out(report)

    assert "HYPERLINK" in out


# --- what the first mutation run found (2026-08-17, _compare_diff 28.4 %) --
#
# 172 survivors, the second-worst measured, in the engine behind
# `compare --expect-clean` — the gate every integration round is decided
# by. The clusters are the same shape throughout: a function with three
# branches tested through one of them, so which branch ran was never
# asserted.

def test_word_diff_names_a_REPLACEMENT_with_both_sides():
    from docxkit.compare import word_diff

    assert word_diff("the index rose to 0.35",
                     "the index rose to 0.37") == ['"0.35" -> "0.37"']


def test_word_diff_names_a_DELETION_as_a_deletion():
    """Not as a replacement with an empty side: the three verbs are what
    a reader skims for, and "x -> " reads as an edit that lost its
    text."""
    from docxkit.compare import word_diff

    assert word_diff("the index rose sharply to 0.35",
                     "the index rose to 0.35") == ['DEL "sharply"']


def test_word_diff_names_an_INSERTION_as_an_insertion():
    from docxkit.compare import word_diff

    assert word_diff("the index rose to 0.35",
                     "the index rose sharply to 0.35") == ['INS "sharply"']


def test_word_diff_says_nothing_about_the_words_that_did_not_change():
    from docxkit.compare import word_diff

    assert word_diff("identical prose here", "identical prose here") == []


def test_word_diff_reports_every_edit_in_the_paragraph():
    """Three verbs in one paragraph, in reading order."""
    from docxkit.compare import word_diff

    out = word_diff("alpha beta gamma delta epsilon",
                    "alpha GAMMA delta epsilon zeta")

    assert out == ['"beta gamma" -> "GAMMA"', 'INS "zeta"']


# ------------------------------------------------- the typography segments --

def test_marker_segments_names_the_SYMBOL_that_changed():
    """The equation-side twin of the format diff: a report that named
    the whole formula would be a report nobody can act on, which is the
    same argument `word_diff` makes about a paragraph."""
    from docxkit._compare_diff import _marker_segments

    segs = _marker_segments("x=y", ["i", "i", "i"], ["i", "i", "up"])

    assert segs == [("y", "i", "up")]


def test_marker_segments_joins_a_CONTIGUOUS_run_of_changes():
    from docxkit._compare_diff import _marker_segments

    segs = _marker_segments("abcd", ["i", "i", "i", "i"],
                            ["i", "up", "up", "i"])

    assert segs == [("bc", "i", "up")]


def test_marker_segments_reports_a_run_that_reaches_the_END():
    """The loop closes a run when the markers agree again; a run that
    never does has to be flushed after it."""
    from docxkit._compare_diff import _marker_segments

    segs = _marker_segments("abc", ["i", "i", "i"], ["i", "up", "up"])

    assert segs == [("bc", "i", "up")]


@pytest.mark.parametrize("before,after", [
    (["i", "i", "i"], ["i", "up"]),          # more markers than after
    (["i", "i", "i"], ["i", "up", "i", "i"]),   # fewer
])
def test_marker_segments_falls_back_to_the_WHOLE_formula_either_way(
        before, after):
    """Different lengths mean the character-by-character comparison
    would be reporting an offset rather than a symbol — so it says so
    about the formula as a whole instead of inventing a position. Both
    directions: a one-sided guard walks off the shorter list."""
    from docxkit._compare_diff import _marker_segments

    segs = _marker_segments("x=y", before, after)

    assert len(segs) == 1
    assert segs[0][0] == "x=y"


def test_marker_segments_falls_back_when_the_MARKERS_do_not_match_the_text():
    """Same count on both sides and neither matches the symbols: the
    lists and the text have to agree before an index means anything."""
    from docxkit._compare_diff import _marker_segments

    segs = _marker_segments("x=y", ["i", "i"], ["i", "up"])

    assert segs == [("x=y", "i", "i,up")]


# ---------------------------------------------- the INTEGRITY layer, alone --
#
# The one layer of the comparison that is a gate on the BUILT document
# rather than a difference between two — "must be clean" — and twelve of
# _compare_diff's survivors were in it. Each one is a way for it to
# report nothing: a set operation that drops the ids present on both
# sides, a comparison that only looks one way, a field depth that only
# counts up.

def _integrity(xml: str, names=None):
    from docxkit._compare_diff import integrity

    return integrity(xml, "built", names)


def test_a_bookmark_with_TWO_starts_and_one_end_is_reported():
    """`set(starts) | set(ends)` — the ids to CHECK are all of them.
    Mutated to a symmetric difference, an id present on both sides is
    dropped, which is every imbalance there can be: an id missing from
    one side entirely has no pair to be unbalanced against."""
    xml = ('<w:p><w:bookmarkStart w:id="7" w:name="Table1"/>'
           '<w:bookmarkStart w:id="7" w:name="Table1"/>'
           '<w:bookmarkEnd w:id="7"/></w:p>')

    assert any("imbalance" in i for i in _integrity(xml))


def test_a_bookmark_with_MORE_ends_than_starts_is_reported_too():
    """`!=`, not `>`. Word writes the stray end when a bookmark is
    copied, and an end with no start is what makes it 'unreadable
    content'."""
    xml = ('<w:p><w:bookmarkStart w:id="7" w:name="Table1"/>'
           '<w:bookmarkEnd w:id="7"/><w:bookmarkEnd w:id="7"/></w:p>')

    assert any("imbalance" in i for i in _integrity(xml))


def test_a_balanced_bookmark_is_no_finding():
    xml = ('<w:p><w:bookmarkStart w:id="7" w:name="Table1"/>'
           '<w:bookmarkEnd w:id="7"/></w:p>')

    assert _integrity(xml) == []


def test_an_anchor_in_BOTH_forms_is_still_checked():
    """`anchors = element anchors | field targets`. A manuscript
    mid-round holds both forms of the same link — Word rewrites a field
    into an element whenever the author saves — and a symmetric
    difference drops exactly the anchors that appear twice, which are
    the ones a half-finished repair leaves behind."""
    xml = ('<w:p><w:hyperlink w:anchor="Gone2020txt"><w:r><w:t>x</w:t>'
           "</w:r></w:hyperlink>"
           r'<w:r><w:instrText> HYPERLINK \l "Gone2020txt" \h </w:instrText>'
           "</w:r></w:p>")

    found = _integrity(xml)

    assert any("dangling" in i and "Gone2020txt" in i for i in found)


def test_a_field_MISSING_ITS_END_is_reported_with_the_sign():
    """The depth counts begin as +1 and end as -1, and the sign in the
    report is what says which half is missing — the fix for one is to
    delete the marker and for the other to add it."""
    xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           "<w:r><w:t>Table 4</w:t></w:r></w:p>")

    found = _integrity(xml)

    assert any("unbalanced field (+1)" in i for i in found)


def test_a_field_MISSING_ITS_BEGIN_is_reported_too():
    """`depth != 0`, not `> 0`: an end with no begin is -1, and it
    renders as literal field code exactly as the other does."""
    xml = ('<w:p><w:r><w:t>Table 4</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')

    found = _integrity(xml)

    assert any("unbalanced field (-1)" in i for i in found)


def test_a_balanced_field_is_no_finding():
    xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           r'<w:r><w:instrText> HYPERLINK \l "T1" \h </w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           "<w:r><w:t>Table 1</w:t></w:r>"
           '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
           '<w:p><w:bookmarkStart w:id="1" w:name="T1"/>'
           '<w:bookmarkEnd w:id="1"/></w:p></w:p>')

    assert _integrity(xml) == []


def test_the_unbalanced_field_report_QUOTES_the_paragraph_it_is_in():
    """Forty characters of it: a document with three unbalanced fields
    is three paragraphs to find, and the id is not in the text."""
    long_text = "The age-friendliness index is defined for every occupation"
    xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           f"<w:r><w:t>{long_text}</w:t></w:r></w:p>")

    found = next(i for i in _integrity(xml) if "unbalanced" in i)

    assert repr(long_text[:40]) in found
    assert long_text[:41] not in found


# ------------------------------------------- pairing the two sides of a label
#
# 31 survivors, the largest cluster in the module. This layer is the
# ONLY place the swallowed-label defect is visible — Parental Style's
# Table 4 caption came back with two thirds of it drawn blue and
# underlined — and it was reached through `compare()` on documents where
# exactly one label had changed, so which way it paired, in what order,
# and what it consumed were all free.

def _moves(gone: dict[str, int], gained: dict[str, int]):
    from collections import Counter

    from docxkit._compare_diff import label_moves

    return label_moves(Counter(gone), Counter(gained))


def test_a_label_that_GREW_is_paired_with_what_it_swallowed():
    out = _moves({"Table 4": 1},
                 {"Table 4: The likelihood of using discipline": 1})

    assert out == [{"side": "grew", "label": "Table 4",
                    "to": "Table 4: The likelihood of using discipline",
                    "n": 1}]


def test_a_label_that_SHRANK_is_the_same_edit_caught_the_other_way():
    """The emptying case partway through — `citations` reports the fully
    emptied one as EMPTY LINK, and this is what it looks like before
    that."""
    out = _moves({"Table 4: The likelihood of using discipline": 1},
                 {"Table 4": 1})

    assert out[0]["side"] == "shrank"
    assert out[0]["label"] == "Table 4: The likelihood of using discipline"
    assert out[0]["to"] == "Table 4"


def test_two_labels_that_merely_DIFFER_are_not_a_pair():
    """Containment is the pairing rule, because that is what the
    mechanism leaves: the old label's own text survives inside the new
    one. Two unrelated labels are two findings, not one move."""
    out = _moves({"Table 4": 1}, {"Figure 9": 1})

    assert out == []


def test_the_pair_is_CONSUMED_so_it_is_not_also_printed_twice():
    """`gone` and `gained` are counters the caller then prints the
    leftovers of; a pair left in them appears again as two singletons,
    which is the report this function exists to replace."""
    from collections import Counter

    from docxkit._compare_diff import label_moves

    gone, gained = Counter({"Table 4": 1}), Counter({"Table 4: results": 1})

    label_moves(gone, gained)

    assert not gone and not gained          # both empty, no zero entries


def test_a_label_of_TWO_characters_is_not_paired_from_either_side():
    """Three characters is the floor. Two contain each other by accident
    all the time — an exhibit number, a footnote mark, a year — and a
    pairing rule on those marries unrelated links across a document.
    Both sides of the pairing are held to it: the label that grew and
    the one it grew from."""
    assert _moves({"T4": 1}, {"T4: the results": 1}) == []
    assert _moves({"T4: the results": 1}, {"T4": 1}) == []


def test_the_LONGEST_candidate_is_paired_first():
    """`sorted(gained, key=lambda s: (-len(s), s))`. Two labels can both
    contain the one that went, and the longer is the one that swallowed
    it — pairing the shorter first leaves the long one to be reported as
    a bare user-only label, which is the two-line report this function
    replaces."""
    out = _moves({"Table 4": 2},
                 {"Table 4: the results": 1,
                  "Table 4: the results of the full model": 1})

    assert [m["to"] for m in out] == [
        "Table 4: the results of the full model", "Table 4: the results"]


def test_a_label_of_exactly_THREE_characters_still_pairs():
    """`len(o) >= _LABEL_KEEP`, not `>`: three is the floor, and the
    floor is inclusive on both sides. "T44" is an exhibit back-link in
    these papers, and excluding it drops a real pairing into the
    singleton lists."""
    out = _moves({"T44": 1}, {"T44: the results": 1})

    assert [m["label"] for m in out] == ["T44"]


def test_ONE_new_label_can_swallow_TWO_old_ones():
    """`if not gained[new]: break` — stop when this label has no copies
    left, not when it still has some. A caption assembled from two links
    is what a paste does, and under the inverted test the second one is
    reported as a bare built-only label."""
    long_label = "Table 4: the results of the full model"
    out = _moves({"Table 4": 1, "the results": 1}, {long_label: 2})

    assert sorted(m["label"] for m in out) == ["Table 4", "the results"]
    assert {m["to"] for m in out} == {long_label}


def test_a_long_label_is_cut_at_ninety_characters_on_BOTH_sides():
    """The pair is printed as one line: `label` -> `to`. A reference
    entry linked whole is 200 characters, and two of them on a line is
    a paragraph."""
    old = "Table 4: " + "the results of the full model, " * 4
    new = old + "with the appendix specifications and their standard errors"

    (move,) = _moves({old: 1}, {new: 1})

    assert move["label"] == old[:90] and len(move["label"]) == 90
    assert move["to"] == new[:90] and len(move["to"]) == 90


def test_a_label_present_on_BOTH_sides_is_not_paired_with_itself():
    """`o != new`. A link whose label did not change at all — removed
    here, added there, which is what a MOVED link looks like to this
    layer — would otherwise be reported as having grown into itself."""
    out = _moves({"Table 4": 1}, {"Table 4": 1})

    assert out == []


def test_the_pairing_stops_when_ONE_side_runs_out():
    """`and`, not `or`. Two links lost that label and only one gained
    the longer one: pairing past the gained side invents a move, and the
    counter it decrements goes negative behind it."""
    from collections import Counter

    from docxkit._compare_diff import label_moves

    gone, gained = Counter({"Table 4": 2}), Counter({"Table 4: results": 1})

    out = label_moves(gone, gained)

    assert len(out) == 1
    assert gone == Counter({"Table 4": 1})      # the other is still gone


# `side = "grew" if len(new) > len(old)` mutated to `>=` is EQUIVALENT:
# the pair is chosen by containment with `o != new`, so equal lengths
# would mean equal labels, which never reach it.


def test_the_LONGEST_candidate_wins_the_pairing():
    """Both old labels sit inside the new one; the longer is the one
    that grew into it. Pairing the shorter leaves the longer to print as
    an unexplained singleton."""
    out = _moves({"Table 4": 1, "Table 4: the likelihood": 1},
                 {"Table 4: the likelihood of using discipline": 1})

    assert len(out) == 1
    assert out[0]["label"] == "Table 4: the likelihood"


def test_a_label_that_moved_TWICE_is_reported_twice():
    """Two links with the same label, both swallowed: the counts are
    what say how many, and stopping at the first leaves one of them
    printed as a singleton somewhere else in the report."""
    out = _moves({"Table 4": 2}, {"Table 4: results": 2})

    assert len(out) == 2


def test_a_pairing_stops_when_the_gained_side_runs_out():
    """One link grew, two labels could have been its source: the second
    is still gone and is still reported as gone, but not as this move."""
    from collections import Counter

    from docxkit._compare_diff import label_moves

    gone = Counter({"Table 4": 1, "Table 4: the likelihood": 1})
    gained = Counter({"Table 4: the likelihood of using discipline": 1})

    out = label_moves(gone, gained)

    assert len(out) == 1
    assert gone == Counter({"Table 4": 1})


def test_the_labels_are_CUT_in_the_report():
    """Ninety characters. A swallowed label is long by definition —
    that is what makes it a finding — and printing both sides of it in
    full is a report nobody reads to the end of."""
    long_label = "Table 4: " + "the likelihood of using discipline " * 5
    out = _moves({"Table 4": 1}, {long_label: 1})

    assert out[0]["to"] == long_label[:90]
    assert len(out[0]["to"]) == 90


# -------------------------------------------- pairing a replaced block -----
#
# `replaced` walks the two sides of one replace opcode in step. 21
# survivors: which side runs out first, what happens to the leftover,
# and whether the walk goes on after a paragraph it has nothing to say
# about were all unasserted — the fixtures all had the same number of
# paragraphs on both sides.

def test_a_block_where_the_LEFT_is_longer_reports_the_leftover_as_gone(
        tmp_path):
    a, b = docs(tmp_path,
                para(run("Alpha one changed here."))
                + para(run("Beta two changed here."))
                + para(run("Gamma three, deleted entirely.")),
                para(run("Alpha ONE rewritten."))
                + para(run("Beta TWO rewritten.")))

    report = compare(a, b)

    kinds = {s["type"] for s in report["structure"]}
    assert "DELETE" in kinds
    assert any("Gamma three" in s.get("text", "")
               for s in report["structure"])


def test_a_block_where_the_RIGHT_is_longer_reports_the_leftover_as_new(
        tmp_path):
    a, b = docs(tmp_path,
                para(run("Alpha one changed here."))
                + para(run("Beta two changed here.")),
                para(run("Alpha ONE rewritten."))
                + para(run("Beta TWO rewritten."))
                + para(run("Gamma three, brand new.")))

    report = compare(a, b)

    assert any(s["type"] == "INSERT" and "Gamma three" in s.get("text", "")
               for s in report["structure"])


def test_a_GLYPH_only_change_inside_a_replaced_block_is_not_a_text_edit(
        tmp_path):
    """Word straightens a quote on save. Inside a block where something
    else really changed, that paragraph still belongs in the glyph
    bucket — reporting it as an edit is how a round of "the author
    changed 40 paragraphs" turns out to be one."""
    a, b = docs(tmp_path,
                para(run("The “gap” is 0.35 here."))
                + para(run("Methods follow the standard approach.")),
                para(run('The "gap" is 0.35 here.'))
                + para(run("Methods follow a different approach.")))

    report = compare(a, b)

    assert any("gap" in g["from"] for g in report["glyph"])
    assert not any("gap" in t.get("context", "") for t in report["text"])
    assert any("different" in str(t.get("word_diff")) for t in report["text"])


def test_a_glyph_change_beside_a_real_edit_reaches_BOTH_layers(tmp_path):
    """The two paragraphs are matched independently — the straightened
    quote is `equal` to the matcher, which normalizes glyphs — so one
    lands in the glyph bucket and the other in text. A round of "the
    author changed 40 paragraphs" that is really one edit is what this
    separation prevents."""
    a, b = docs(tmp_path,
                para(run("The “gap” is 0.35 here."))
                + para(run("Methods follow the standard approach.")),
                para(run('The "gap" is 0.35 here.'))
                + para(run("Methods follow a different approach.")))

    report = compare(a, b)

    assert [g["from"][:9] for g in report["glyph"]] == ["The “gap”"]
    assert len(report["text"]) == 1
    assert "different" in str(report["text"][0]["word_diff"])


def test_a_text_entry_CUTS_its_context(tmp_path):
    """Sixty characters. The context is there to recognise the paragraph
    by, not to reproduce it — the word diff beside it says what changed."""
    long_a = ("The age-friendliness index is defined for every occupation "
              "in the sample as the weighted mean of ten indicators.")
    a, b = docs(tmp_path, para(run(long_a)),
                para(run(long_a.replace("ten", "twelve"))))

    entry = compare(a, b)["text"][0]

    assert entry["context"] == long_a[:60]
    assert len(entry["context"]) == 60


# ------------------------------------------------------ moves, then the rest
#
# `structure` pairs a deleted paragraph with an inserted one that is
# nearly the same text and calls it a MOVE; what it cannot pair is a
# plain DELETE or INSERT. 15 survivors: the similarity threshold, the
# ratio it prints, the bookkeeping that stops one paragraph being
# matched twice, and the cuts.

def test_a_paragraph_that_MOVED_is_one_finding_not_two(tmp_path):
    """Otherwise a reordered section reads as a deletion and an
    unrelated insertion, and the reader checks both."""
    moved = para(run("The methods section, moved to the end."))
    a, b = docs(tmp_path,
                moved + para(run("Alpha.")) + para(run("Beta.")),
                para(run("Alpha.")) + para(run("Beta.")) + moved)

    kinds = [s["type"] for s in compare(a, b)["structure"]]

    assert kinds == ["MOVE"]


def test_a_MOVE_prints_the_ratio_it_matched_on(tmp_path):
    """The ratio is how a reader tells a clean move from one that was
    moved AND rewritten — the second wants reading, the first does not.
    Three decimals, because the interesting values sit just above the
    threshold and rounding them to none says 1.0 for all of them."""
    moved = "The methods section, moved to the end of the paper."
    a, b = docs(tmp_path,
                para(run(moved)) + para(run("Alpha.")),
                para(run("Alpha."))
                + para(run(moved.replace("methods", "results"))))

    move = compare(a, b)["structure"][0]

    assert move["type"] == "MOVE"
    assert move["ratio"] == 0.922


def test_a_paragraph_REWRITTEN_past_the_threshold_is_not_a_move(tmp_path):
    """0.85 of the characters. Below it the two paragraphs are not the
    same text in a new place, and calling them a move hides an edit
    nobody would then read."""
    moved = "The methods section, moved to the end of the paper."
    a, b = docs(tmp_path,
                para(run(moved)) + para(run("Alpha.")),
                para(run("Alpha.")) + para(run(
                    "The methods section, now rewritten and placed "
                    "elsewhere.")))                      # ratio 0.54

    kinds = {s["type"] for s in compare(a, b)["structure"]}

    assert kinds == {"DELETE", "INSERT"}


# Three near-identical paragraphs, all within the 0.85 threshold of each
# other — the shape a reordered results section produces when the
# sentences differ only in which exhibit they name.
_S1 = "The methods section, moved to the end of the paper."
_S2 = "The methods section, moved to the end of the report."
_S3 = "The methods section, moved to the end of the article."


def test_ONE_inserted_paragraph_cannot_match_TWO_deleted_ones(tmp_path):
    """A paragraph already claimed as the other end of a move is not
    available to claim again — otherwise two deletions both report as
    moves into the same place, and one of those moves never happened."""
    a, b = docs(tmp_path,
                para(run(_S1)) + para(run(_S2)) + para(run("Alpha.")),
                para(run("Alpha.")) + para(run(_S3)))

    kinds = sorted(s["type"] for s in compare(a, b)["structure"])

    assert kinds == ["DELETE", "MOVE"]


def test_ONE_deleted_paragraph_cannot_match_TWO_inserted_ones(tmp_path):
    """The same rule from the other side: the walk stops at the first
    insertion it pairs with, or one deletion reports as two moves and
    the reader is told a paragraph is in two places."""
    a, b = docs(tmp_path,
                para(run(_S1)) + para(run("Alpha.")),
                para(run("Alpha.")) + para(run(_S2)) + para(run(_S3)))

    kinds = sorted(s["type"] for s in compare(a, b)["structure"])

    assert kinds == ["INSERT", "MOVE"]


def test_a_DELETE_reports_what_the_paragraph_TOOK_WITH_IT(tmp_path):
    """A deleted paragraph takes its links and bookmarks, and the entry
    names them: that is the difference between "a paragraph went" and "a
    citation's target went"."""
    a, b = docs(tmp_path,
                para(run("Alpha."))
                + ('<w:p><w:hyperlink w:anchor="Smith2020txt">'
                   "<w:r><w:t>Smith (2020)</w:t></w:r></w:hyperlink></w:p>"),
                para(run("Alpha.")))

    entry = next(s for s in compare(a, b)["structure"]
                 if s["type"] == "DELETE")

    assert entry["lost_fields"]["anchors"] == ["Smith2020txt"]


# ----------------------------------------- machinery a block really lost ---
#
# The "Word deleted my hyperlink field" layer, and the one whose false
# positives cost a diagnosis every time — a dangling-link flag is one
# this project may never wave away. Ten survivors: the three rules that
# make it worth reading (per block, not per pair; a name still present
# anywhere is not lost; counters cancel a move) were each reachable from
# one direction only.

def _para(text: str, *, anchors=(), cites=(), footnotes=0):
    """A Para built the way the comparison builds them — from XML, so
    the fields are the ones `_fields` really extracts."""
    from docxkit._compare_read import Para

    inner = "".join(f'<w:hyperlink w:anchor="{a}">{_R(a)}</w:hyperlink>'
                    for a in anchors)
    inner += "".join(f'<w:bookmarkStart w:id="7" w:name="{c}"/>'
                     f'<w:bookmarkEnd w:id="7"/>' for c in cites)
    inner += "<w:r><w:footnoteReference w:id=\"2\"/></w:r>" * footnotes
    return Para(f"<w:p>{_R(text)}{inner}</w:p>")


def _R(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def test_a_target_the_block_LOST_is_named():
    from docxkit._compare_diff import stripped_block

    notes = stripped_block([_para("a", anchors=["Smith2020txt"])],
                           [_para("a")])

    assert notes[0][0] == "lost hyperlink target(s): ['Smith2020txt']"


def test_a_target_that_MOVED_between_paragraphs_is_not_lost():
    """The block is the unit the answer is true of. Asked per pair, this
    is a loss and a gain — and 594 of 1,463 "losses" over 748 real
    comparisons were exactly this."""
    from docxkit._compare_diff import stripped_block

    left = [_para("a", anchors=["Smith2020txt"]), _para("b")]
    right = [_para("a"), _para("b", anchors=["Smith2020txt"])]

    assert stripped_block(left, right) == []


def test_a_target_still_PRESENT_elsewhere_in_the_part_is_not_lost():
    """`present` is every name the other side's whole part carries. A
    citation that went from the prose into a footnote accounted for the
    last 27 of the false losses."""
    from docxkit._compare_diff import stripped_block

    notes = stripped_block([_para("a", anchors=["Smith2020txt"])],
                           [_para("a")], present={"Smith2020txt"})

    assert notes == []


def test_a_CITATION_bookmark_is_named_as_one():
    """Two kinds, and the label is what tells a reader whether to look
    for a link or for the bookmark it points at."""
    from docxkit._compare_diff import stripped_block

    notes = stripped_block([_para("a", cites=["cite_Smith2020"])],
                           [_para("a")])

    assert notes[0][0] == "lost citation bookmark(s): ['cite_Smith2020']"


def test_the_note_carries_the_paragraph_that_HELD_the_target():
    """So the report can still say where to look — the LAST paragraph on
    the left that had it, since that is where a reader will find its
    remains."""
    from docxkit._compare_diff import stripped_block

    first = _para("first", anchors=["Smith2020txt"])
    last = _para("last", anchors=["Smith2020txt"])

    (_note, holder), = stripped_block([first, _para("x"), last],
                                      [_para("a")])

    assert holder is last


def test_a_target_the_block_GAINED_is_not_a_loss():
    """Counter subtraction keeps the positive side only."""
    from docxkit._compare_diff import stripped_block

    assert stripped_block([_para("a")],
                          [_para("a", anchors=["New2021txt"])]) == []


def test_FEWER_footnote_references_is_reported_as_a_count():
    """A footnote reference has no name to report, so the finding is how
    many went — and the holder is None, because a number does not have
    one."""
    from docxkit._compare_diff import stripped_block

    notes = stripped_block([_para("a", footnotes=3)],
                           [_para("a", footnotes=1)])

    assert notes == [("lost 2 footnote ref(s)", None)]


def test_MORE_footnote_references_is_not_a_loss():
    from docxkit._compare_diff import stripped_block

    assert stripped_block([_para("a", footnotes=1)],
                          [_para("a", footnotes=3)]) == []


# ------------------------------------------- the format layer's own guard --

def test_the_format_layer_names_the_SEGMENT_that_changed():
    """Character by character, so the entry says which words took the
    emphasis rather than that the paragraph did — the same argument
    `word_diff` makes about a sentence."""
    from docxkit._compare_diff import fmt_diff
    from docxkit._compare_read import Para

    plain = Para('<w:p><w:r><w:t>See the Journal here.</w:t></w:r></w:p>')
    part = Para('<w:p><w:r><w:t xml:space="preserve">See the </w:t></w:r>'
                "<w:r><w:rPr><w:i/></w:rPr><w:t>Journal</w:t></w:r>"
                '<w:r><w:t xml:space="preserve"> here.</w:t></w:r></w:p>')

    (segment, was, now), = fmt_diff(plain, part)

    assert segment == "Journal"
    assert "italic" in now and "italic" not in was


def test_the_format_layer_says_NOTHING_when_the_prose_differs():
    """A character-by-character comparison of two different strings
    reports the offset, not the emphasis — so the layer declines, and
    the text layer is what reports that pair."""
    from docxkit._compare_diff import fmt_diff
    from docxkit._compare_read import Para

    # the SAME LENGTH, deliberately: the length check alone would let
    # this pair through, and then every character of it reads as a
    # formatting change at an offset that means nothing
    one = Para("<w:p><w:r><w:t>See the Journal here.</w:t></w:r></w:p>")
    other = Para('<w:p><w:r><w:rPr><w:i/></w:rPr>'
                 "<w:t>See the Gazette here.</w:t></w:r></w:p>")

    assert len(one.wtext_f) == len(other.wtext_f)
    assert fmt_diff(one, other) == []


def test_a_format_run_that_reaches_the_END_is_still_reported():
    """The loop closes a run when the flags agree again; one that never
    does has to be flushed after it, or emphasis on the last words of a
    paragraph is invisible."""
    from docxkit._compare_diff import fmt_diff
    from docxkit._compare_read import Para

    plain = Para("<w:p><w:r><w:t>See the Journal</w:t></w:r></w:p>")
    tail = Para('<w:p><w:r><w:t xml:space="preserve">See the </w:t></w:r>'
                "<w:r><w:rPr><w:b/></w:rPr><w:t>Journal</w:t></w:r></w:p>")

    (segment, _was, now), = fmt_diff(plain, tail)

    assert segment == "Journal"
    assert "bold" in now


def test_the_paragraph_pairing_keeps_its_OFFSET_across_a_matched_block(
        tmp_path):
    """`b[j1 + (k - i1)]` — the two sides of an equal block are walked in
    step, and an offset slip pairs a paragraph with its neighbour. Both
    would then report as glyph changes against each other, which reads
    as two edits where there was one."""
    a, b = docs(tmp_path,
                para(run("Alpha “one”.")) + para(run("Beta “two”."))
                + para(run("Gamma three.")),
                para(run("Changed opening.")) + para(run('Alpha "one".'))
                + para(run('Beta "two".')) + para(run("Gamma three.")))

    report = compare(a, b)

    pairs = [(g["from"], g["to"]) for g in report["glyph"]]
    assert pairs == [("Alpha “one”.", 'Alpha "one".'),
                     ("Beta “two”.", 'Beta "two".')]


def test_a_COMMENT_only_one_side_carries_is_reported_with_its_side(tmp_path):
    """Never gated — an author round legitimately adds comments — and
    which side it is on is the whole content of the finding: one is the
    author's note to read, the other is a comment the build carries and
    their copy does not."""
    from conftest import comment

    a, b = docs(tmp_path, para(run("Text.")), para(run("Text.")),
                comment_items=((comment(1, "built note"),), ()))

    report = compare(a, b)

    assert [(c["side"], c["text"]) for c in report["comments"]] == [
        ("built-only", "Tester: built note")]


def test_a_comment_the_AUTHOR_added_is_reported_as_user_only(tmp_path):
    from conftest import comment

    a, b = docs(tmp_path, para(run("Text.")), para(run("Text.")),
                comment_items=((), (comment(1, "please check"),)))

    report = compare(a, b)

    assert [(c["side"], c["text"]) for c in report["comments"]] == [
        ("user-only", "Tester: please check")]


# --- what the _compare_read run of 2026-08-18 found -----------------------
#
# 12.6 % real survival over a full run, and the largest cluster by far was
# `mask_volatile_fields` with 16 — every one of them on the SCAN rather
# than on the masking, which the tests above cover well. The fixtures all
# held one field, or one inside another, so nothing said what happens
# after a field the scan declines: the two `continue`s survived as
# `break`, and the guard that recognises a nested field survived every
# way of spelling it, including reading the FIRST region instead of the
# last.
#
# It matters because the scan is what keeps a page number out of a
# redline. One `break` in the wrong place and every volatile field after
# the first non-volatile one is compared by its cached value — "7" against
# "9" — and the review fills with changes nobody made.


def _uncalculated(instr: str) -> str:
    """A field Word has never calculated: begin, instruction, end. No
    separator, so there is no cached result to mask."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> {instr} '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _wrapping(instr: str, inner: str) -> str:
    """A field whose cached result CONTAINS another field."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> {instr} '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + inner
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def test_a_field_the_scan_DECLINES_does_not_end_the_scan():
    """`continue` mutated to `break`. AUTHOR is not volatile and keeps
    its result; the PAGE field after it must still be masked, or a
    document with an author field near the top compares every page
    number in it by value."""
    from docxkit._compare_read import mask_volatile_fields
    xml = ("<w:p>" + field("AUTHOR", "M. Lokshin")
           + run(" wrote page ") + field("PAGE", "7") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert "M. Lokshin" in out, "AUTHOR is not volatile"
    assert "«F:PAGE»" in out and ">7<" not in out


def test_a_volatile_field_with_NO_cached_result_does_not_end_the_scan():
    """The other `continue`. A field Word never calculated has nothing
    to mask and is not a reason to stop looking."""
    from docxkit._compare_read import mask_volatile_fields
    xml = ("<w:p>" + _uncalculated("PAGE")
           + field("DATE", "3 March 2026") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert "«F:DATE»" in out and "3 March 2026" not in out


def test_TWO_volatile_fields_in_a_row_are_masked_separately():
    """Neither is inside the other, so the nesting guard must not read
    the second as covered by the first."""
    from docxkit._compare_read import mask_volatile_fields
    xml = ("<w:p>" + field("PAGE", "7") + run(" of ")
           + field("NUMPAGES", "12") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert re.findall(r"«F:\w+»", out) == ["«F:PAGE»", "«F:NUMPAGES»"]
    assert ">7<" not in out and ">12<" not in out
    assert " of " in out


def test_a_field_nested_in_a_claimed_region_does_not_end_the_scan():
    """The third `continue`, and the one a nesting fixture alone cannot
    see: the inner PAGE is the last span in a document that ends there,
    so `break` and `continue` agree. Put a volatile field AFTER the
    nested one and they part company — `break` leaves the page count
    unmasked, and a redline then reports "12" against "14".

    The two mutants this does NOT kill are equivalent by construction,
    argued rather than assumed (`tools/kill_check.py`, expect_kill=False):

    * `regions[-1]` -> `regions[0]` registers the inner field as a region
      of its own, and the right-to-left rewrite then cuts the outer slice
      seven characters early — but those seven characters are TAG text
      either side of the split, `_mask_text` rewrites only `w:t` content,
      and the concatenation puts the same string back. It stops being
      equivalent the moment a boundary falls inside a `w:t`, which no
      field Word writes does.
    * `start + sep.end()` -> `start | sep.end()` moves the region's start
      EARLIER (an OR is never larger than the sum) into the field's code
      region, which holds `instrText` and no `w:t` — so the first `w:t`
      the mask finds is the cached result either way."""
    from lxml import etree

    from docxkit._compare_read import mask_volatile_fields
    xml = ("<w:p>" + field("DATE", "3 March 2026")
           + _wrapping("PAGEREF _Toc1", field("PAGE", "7"))
           + run(" of ") + field("NUMPAGES", "12") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert re.findall(r"«F:\w+»", out) == [
        "«F:DATE»", "«F:PAGEREF»", "«F:NUMPAGES»"]
    assert out.count("w:fldChar") == xml.count("w:fldChar")
    etree.fromstring(('<w:p xmlns:w="http://schemas.openxmlformats.org/'
                      'wordprocessingml/2006/main">'
                      + out[len("<w:p>"):]).encode())


@pytest.mark.parametrize("lead", ["", "A", "ABC", "A longer opening line. ",
                                  "Prose of some other length entirely, so "
                                  "the offsets are nothing like round. "])
def test_the_masked_region_starts_at_the_CACHED_RESULT_at_any_offset(lead):
    """`result_at = start + sep.end()` with `+` mutated to `|` or `^`
    agrees with addition whenever the two operands share no bits, which
    a single fixture decides by luck. Five lead lengths do not."""
    from docxkit._compare_read import mask_volatile_fields
    xml = ("<w:p>" + run(lead + "before ") + field("PAGE", "7")
           + run(" after") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert lead + "before " in out and " after" in out
    assert "«F:PAGE»" in out and ">7<" not in out


# `pair_parts` had 6 survivors: the similarity score that decides
# whether a RENAMED part is the same part. The test above renames a
# header whose content is IDENTICAL, where every spelling of "best
# match" and every threshold agrees.

_RUNNING_HEAD = "Age-Friendly Index — running head, 2026 revision"


def test_a_renamed_header_pairs_with_the_CLOSEST_candidate(tmp_path):
    """Two spare parts on the far side and only one of them is this
    header renumbered. Pairing it with the other reports the running
    head as rewritten from end to end, and buries the one word that
    changed."""
    near = hdr(para(run(_RUNNING_HEAD.replace("2026", "2027"))))
    far = hdr(para(run("Zeta Omicron Pi: an unrelated banner entirely!!")))
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": hdr(para(run(_RUNNING_HEAD)))},
                       {"word/header2.xml": near, "word/header3.xml": far}))

    report = compare(a, b)

    assert [(s["type"], s["part"]) for s in report["structure"]] == [
        ("PART ADDED", "header3")], report
    assert [t["part"] for t in report["text"]] == ["header1"]


def test_a_part_too_UNLIKE_anything_is_added_and_removed(tmp_path):
    """The threshold is what stops the pairing being a guess: below it
    the two are different parts, and saying so is the honest report —
    one lost, one gained — rather than a text diff of two unrelated
    running heads."""
    far = hdr(para(run("Zeta Omicron Pi: an unrelated banner entirely!!")))
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": hdr(para(run(_RUNNING_HEAD)))},
                       {"word/header2.xml": far}))

    report = compare(a, b)

    assert sorted((s["type"], s["part"]) for s in report["structure"]) == [
        ("PART ADDED", "header2"), ("PART REMOVED", "header1")], report
    assert report["text"] == []


# `_addresses` had 8 survivors — the counters that turn a paragraph
# offset into "table 1 r3c2". The tests above ask for ONE address, and
# one address cannot tell a counter that starts at the wrong number from
# one that does not: every cell of a one-cell fixture is r1c1 whatever
# the arithmetic. These ask for the whole map.
#
# Four of the eight are equivalent by construction, argued rather than
# assumed (`tools/kill_check.py`, expect_kill=False) and worth writing
# down because each looks like a gap:
#
# * the CELL counter's initial value, `[tables, 0, 1]`. A table's first
#   `w:tr` sets it to 0 before any `w:tc` is seen, so the value the stack
#   was pushed with is never read — the ROW counter's initial value is a
#   real check, and dies here;
# * `tag >= "tr"` and `tag >= "tc"` for `==`. The only tags reaching
#   those arms are `p`, `tc`, `tr`, and they sort in that order — `"p"`
#   is below both and `"tr"` is consumed by the arm above `tc`;
# * `tag is "p"` for `==`. CPython caches every one-character latin-1
#   string, so a regex group of `"p"` IS the literal. `"tc"` is not, and
#   an `is` there does die.


def test_every_cell_of_a_table_gets_its_own_address():
    """Rows and cells both count from ONE, the way a person reads a
    table and the way `tables.read_all` numbers them. Starting either at
    zero sends a reader one row up or one column left — into the header,
    usually, which is the cell most likely to look plausible."""
    from docxkit._compare_read import _addresses
    xml = document(table(row("a", "b"), row("c", "d")))

    got = sorted(_addresses(xml).values())

    assert got == ["table 1 r1c1", "table 1 r1c2",
                   "table 1 r2c1", "table 1 r2c2"]


def test_a_paragraph_outside_any_table_has_no_entry():
    """The map is only consulted for paragraphs it holds, so prose must
    not appear in it — an address on a paragraph that has none reads as
    a cell of whatever table happens to be open."""
    xml = document(para(run("prose")) + table(row("a"))
                   + para(run("more prose")))

    got = _sorted_addresses(xml)

    assert got == ["table 1 r1c1"], "one cell, and nothing else addressed"


def _sorted_addresses(xml: str) -> list[str]:
    from docxkit._compare_read import _addresses
    return sorted(_addresses(xml).values())


def test_the_cell_counter_RESTARTS_on_every_row():
    """`stack[-1][2] = 0` when a row opens. Without it the second row's
    first cell is c3 — a column that may not exist, and a reader sent to
    a table's edge looking for a number that is in the middle."""
    xml = document(table(row("a", "b", "c"), row("d", "e", "f")))

    assert _sorted_addresses(xml) == [
        "table 1 r1c1", "table 1 r1c2", "table 1 r1c3",
        "table 1 r2c1", "table 1 r2c2", "table 1 r2c3"]


def test_two_tables_are_numbered_in_DOCUMENT_order():
    """Which is what makes the address agree with `tables.read_all` —
    the numbering a paper's own scripts index by."""
    xml = document(table(row("a")) + para(run("between")) + table(row("b")))

    assert _sorted_addresses(xml) == ["table 1 r1c1", "table 2 r1c1"]


def test_a_nested_table_reads_OUTER_then_inner():
    """And the outer table's own cell keeps its address: the inner
    table's paragraphs carry both, so a reader walks in from the outside."""
    inner = table(row("x"))
    xml = document("<w:tbl><w:tr><w:tc>" + para(run("lead")) + inner
                   + "</w:tc></w:tr></w:tbl>")

    assert _sorted_addresses(xml) == [
        "table 1 r1c1", "table 1 r1c1 > table 2 r1c1"]


# --- what the facade LABELS things (2026-08-19) ------------------------
#
# `compare.py` is the only module in the package that has never been
# measured — the sweep reads the three layers behind it and the facade
# itself was never a target. Reading it for what a test would notice
# turned up the same shape the sweep keeps finding: three values that go
# into the report and are read by nobody.
#
# The report is the deliverable. "BUILT" against "BUILT/footnotes" is
# which document a person opens; the 110-character extract is how they
# recognise a part they have never heard of; the 90-character cut is
# what keeps a reference entry's label from filling the screen.

def test_an_integrity_flag_says_which_PART_of_the_built_doc_it_is_in(
        tmp_path):
    """`"BUILT" if part.label == "body" else f"BUILT/{part.label}"`. The
    flags are read next to the document, and a dangling anchor in a
    footnote is found by opening the notes — not by scrolling the body
    looking for a link that is not there."""
    body = para(run("See ") + '<w:hyperlink w:anchor="NowhereBody">'
                + run("here") + "</w:hyperlink>")
    foot = notes("footnotes",
                 '<w:footnote w:id="2"><w:p>'
                 '<w:hyperlink w:anchor="NowhereNote">'
                 "<w:r><w:t>there</w:t></w:r></w:hyperlink>"
                 "</w:p></w:footnote>")
    a, b = docs(tmp_path, body, body, footnotes=foot)

    flags = compare(a, b)["integrity"]

    assert any(f.startswith("BUILT:") and "NowhereBody" in f for f in flags)
    assert any(f.startswith("BUILT/footnotes:") and "NowhereNote" in f
               for f in flags)


def test_a_part_that_was_REMOVED_carries_an_extract_of_itself(tmp_path):
    """`pa.blob[:110]`: the label alone is "header1", which says nothing
    about what was in it. A hundred and ten characters is enough to
    recognise a running head and short enough for one line."""
    head = ("The Age-Friendly Index for the Republic of Kazakhstan — "
            "running head, second draft, revised after the referee round")
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": hdr(para(run(head)))}, {}))

    (removed,) = compare(a, b)["structure"]

    assert removed["type"] == "PART REMOVED" and removed["part"] == "header1"
    assert len(removed["text"]) == 110
    assert removed["text"].startswith("The Age-Friendly Index")
    assert removed["text"].endswith("after the referee "), "cut mid-word"

    # and the same part on the other side, which is the other branch:
    # a header the USER's document has and the build does not
    a2, b2 = docs(tmp_path, BASE, BASE,
                  extra=({}, {"word/header1.xml": hdr(para(run(head)))}))

    (added,) = compare(a2, b2)["structure"]

    assert added["type"] == "PART ADDED" and added["part"] == "header1"
    assert added["text"] == removed["text"]


def test_a_long_hyperlink_LABEL_is_cut_at_ninety_characters(tmp_path):
    """A reference entry is a link whose label is the whole entry, and
    an untruncated one fills the line the finding shares with its count.
    """
    long_label = ("Acemoglu, D., and P. Restrepo. (2020). Robots and Jobs: "
                  "Evidence from US Labor Markets. Journal of Political "
                  "Economy, 128(6): 2188-2244.")
    linked = para(run("See ") + '<w:hyperlink w:anchor="Ref1">'
                  + run(long_label) + "</w:hyperlink>")
    a, b = docs(tmp_path, linked, para(run("See nothing at all.")))

    (only,) = [h for h in compare(a, b)["hyperlinks"]
               if h.get("side") == "built-only"]

    assert only["label"] == long_label[:90]
    assert len(only["label"]) == 90
    assert only["n"] == 1


# --- the leftovers, and where they are cut (2026-08-19) ----------------
#
# `structure` pairs what was deleted with what was inserted and calls
# the close matches MOVES. Its fixtures each have one of each, so the
# inner loop's `break` — one insert per delete — never had to hold, and
# the three extracts it prints (90 characters for a move, 110 for a
# delete or an insert) were read by nothing.

def _report():
    from docxkit._compare_diff import Report
    return Report(structure=[], text=[], glyph=[], formula=[],
                  formula_glyph=[], formula_format=[], format=[],
                  hyperlinks=[], integrity=[], stripped_fields=[],
                  comments=[])


def _walk(left: list[str], right: list[str]):
    from docxkit._compare_diff import compare_paras
    report = _report()
    compare_paras([_para(t) for t in left], [_para(t) for t in right],
                  report)
    return report


LONG = ("The decomposition in this section is sensitive to the ranking of "
        "its components, which the appendix sets out in full, with the "
        "standard errors alongside.")


def test_one_deleted_paragraph_matches_ONE_move_not_two():
    """`break` after a match: a paragraph moved once is one finding. Two
    near-identical destinations is the ordinary case in a reordered
    section — a heading repeated, a caption reused — and reporting the
    same deletion as two moves reads as content duplicated."""
    report = _walk([LONG, "Untouched."],
                   ["Untouched.", LONG + " One.", LONG + " Two."])

    moves = [s for s in report["structure"] if s["type"] == "MOVE"]

    assert len(moves) == 1


def test_a_MOVE_quotes_ninety_characters_of_what_moved():
    """The move is reported against the deletion, so the extract has to
    name the paragraph as it WAS — that is the one a person searches the
    old document for."""
    report = _walk([LONG, "A.", "B."], ["A.", "B.", LONG + " With a tail."])

    (move,) = [s for s in report["structure"] if s["type"] == "MOVE"]

    assert move["text"] == LONG[:90] and len(move["text"]) == 90


def test_a_DELETE_and_an_INSERT_quote_a_hundred_and_ten():
    """More than a move, because there is no counterpart to compare
    against: the whole finding is this text, and 110 characters is what
    makes an unfamiliar paragraph recognisable."""
    other = ("A wholly unrelated paragraph about something else entirely, "
             "added in this round and long enough to be cut by the same "
             "hundred and ten characters.")
    report = _walk([LONG, "A."], ["A.", other])

    kinds = {s["type"]: s for s in report["structure"]}

    assert kinds["DELETE"]["text"] == LONG[:110]
    assert kinds["INSERT"]["text"] == other[:110]
    assert len(kinds["DELETE"]["text"]) == len(kinds["INSERT"]["text"]) == 110


def test_an_EQUAL_block_after_an_insertion_pairs_the_right_paragraphs():
    """`b[j1 + (k - i1)]` — the partner's index, measured from where the
    equal block starts on each side. With a paragraph inserted at the
    top the two offsets differ, and `|` in place of `+` pairs paragraph
    2 with paragraph 1: every later finding is then reported against the
    wrong text, and a document with one added heading reads as rewritten
    throughout."""
    same = ["First paragraph, unchanged.", "Second paragraph, unchanged.",
            "Third paragraph, unchanged."]
    report = _walk(same, ["A new opening paragraph.", *same])

    assert report["text"] == [], "nothing but the insertion changed"
    inserts = [s for s in report["structure"] if s["type"] == "INSERT"]
    assert [s["text"] for s in inserts] == ["A new opening paragraph."]

    # and the same block after a REPLACE, where the equal run starts at
    # 1 on BOTH sides: `k >> i1` is 0, 1, 1 where `k - i1` is 0, 1, 2,
    # so the last two paragraphs pair with one and the same partner
    edited = _walk(["The opening, as it was.", *same],
                   ["The opening, rewritten.", *same])

    assert [t["context"] for t in edited["text"]] == [
        "The opening, as it was."], "one edit, and it is the first"
    assert not edited["structure"] and not edited["glyph"]


def test_a_glyph_substitution_the_OTHER_WAY_ROUND_is_still_reported(tmp_path):
    """`pa.text != pb.text`, not `>`. The existing fixture has the curly
    apostrophe on the A side, where every comparison operator fires;
    with the straight one there — which is what a round that ran
    `hygiene.smarten` produces — `>` is False and the finding vanishes
    entirely. Not into TEXT: nowhere."""
    a, b = docs(tmp_path,
                para(run("the workers' index rose")),
                para(run("the workers’ index rose")))

    report = compare(a, b)

    assert report["text"] == []
    assert len(report["glyph"]) == 1
    assert report["glyph"][0]["from"] == "the workers' index rose"
    assert report["glyph"][0]["to"] == "the workers’ index rose"


def test_a_glyph_finding_quotes_a_hundred_and_twenty_characters(tmp_path):
    """Both sides, because the finding IS the pair — a reader compares
    them character by character to see which glyph moved, and a cut that
    lands differently on the two sides is a diff of the cut."""
    long = ("The estimate is robust to the specification and to the "
            "sample, as the appendix sets out at length, with the "
            "standard errors in the second panel of each table.")
    a, b = docs(tmp_path, para(run(long.replace("'", "'") + " it's fine")),
                para(run(long + " it’s fine")))

    report = compare(a, b)

    (glyph,) = report["glyph"]
    assert len(glyph["from"]) == 120 and len(glyph["to"]) == 120
    assert glyph["from"] == (long + " it's fine")[:120]


def test_a_text_edit_quotes_SIXTY_characters_of_context(tmp_path):
    """`pa.text[:60]` — the context is what places the word diff in the
    document, and the word diff itself carries the change."""
    long = ("The estimate is robust to the specification and to the "
            "sample, as the appendix sets out at length.")
    a, b = docs(tmp_path, para(run(long)),
                para(run(long.replace("robust", "sensitive"))))

    report = compare(a, b)

    (edit,) = report["text"]
    assert edit["context"] == long[:60] and len(edit["context"]) == 60


def test_a_SECOND_field_after_a_nested_one_is_still_masked():
    """A running head holds a DATE and a PAGEREF wrapping a PAGE, and
    the walk has to mask two of the three: the nested one is inside a
    region already claimed and the one after it is not.

    The two index mutants on that guard (`regions[0]` for `regions[-1]`,
    and the region's start for its end) both SURVIVE this and are argued
    equivalent rather than pinned: letting the nested field through
    appends a region the outer one covers exactly, and masking it first
    leaves the same string. What the guard buys is the work, not the
    output."""
    from docxkit._compare_read import mask_volatile_fields

    nested = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              '<w:r><w:instrText> PAGEREF _Toc1 </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              + field("PAGE", "7")
              + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    # the DATE comes FIRST, so two regions are already claimed when the
    # nested PAGE is judged — with one region the last and the first are
    # the same entry and every index agrees
    out = mask_volatile_fields("<w:p>" + field("DATE", "8 May") + nested
                               + "</w:p>")

    assert re.findall(r"«F:\w+»", out) == ["«F:DATE»", "«F:PAGEREF»"], out
    assert out.count("PAGEREF _Toc1") == 1, "the instruction is not masked"


def test_the_FIRST_of_two_equally_similar_parts_is_the_pair(tmp_path):
    """`r > score`, not `>=`: with two candidates that match a leftover
    part equally well the walk keeps the first, so the same pair of
    documents gives the same report twice running. Under `>=` the last
    one wins, and which part is reported ADDED depends on the order
    `read_parts` happened to yield them in."""
    head = "Age-Friendly Index — running head"
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": hdr(para(run(head)))},
                       {"word/header2.xml": hdr(para(run(head + " (v2)"))),
                        "word/header3.xml": hdr(para(run(head + " (v3)")))}))

    report = compare(a, b)

    # header1 pairs with header2 — the first equally-good candidate —
    # so header3 is the one reported as added
    assert [(s["type"], s["part"]) for s in report["structure"]] == [
        ("PART ADDED", "header3")]
    assert [t.get("part") for t in report["text"]] == ["header1"]
