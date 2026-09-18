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
    NS,
    comment,
    cp1252_console,
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

from docxkit.compare import BUCKETS, GATED, Report, compare, render


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


def test_a_renumbered_header_is_paired_however_LONG_its_running_head(
        tmp_path):
    """`autojunk=False` on the similarity that pairs a renumbered part.

    difflib's autojunk heuristic discards any element appearing in more
    than 1 % of a sequence longer than 200 — which for a string of text
    is most of the alphabet. A running head is the one part of a paper
    that repeats itself, and on this pair the ratio falls from 0.97 to
    0.32 with the heuristic on: below the 0.6 threshold, so the header
    is reported as one part LOST and another GAINED, the whole running
    head printed twice, and the edit that actually happened — a volume
    number and a month — buried under it.

    The short fixtures above cannot see this: under 200 elements
    difflib does not apply the heuristic at all."""
    head = ("Journal of Economic Studies, Volume 41, Number 3, September "
            "2026 — Employment and the life course in Central Asia ") * 3
    a, b = docs(tmp_path, BASE, BASE,
                extra=({"word/header1.xml": hdr(para(run(head)))},
                       {"word/header2.xml": hdr(para(run(
                           head.replace("Number 3", "Number 4")
                               .replace("September", "December"))))}))

    report = compare(a, b)

    assert report["structure"] == [], "renumbered, not lost and gained"
    assert len(report["text"]) == 1, report["text"]
    assert report["text"][0]["part"] == "header1"


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


def test_a_SIGN_FLIP_inside_a_fence_is_a_finding(tmp_path):
    """The character Word draws between a delimiter's arguments lives in
    an ATTRIBUTE — `m:sepChr` — and in no `m:t`, so the token stream
    read from the runs alone says `ab` for both `(a+b)` and `(a−b)`.

    Measured 2026-08-29 on exactly this pair: every layer clean,
    skeleton equal, `--expect-clean` green. A sign flip in a revision
    passed every gate the toolkit has, which is what makes this the
    gate rather than the converter fix beside it — the converter stops
    WRITING the shape, and every manuscript built before it still
    holds it."""
    def fence(sep: str) -> str:
        return ("<w:p>" + "<m:oMath><m:d>"
                f'<m:dPr><m:sepChr m:val="{sep}"/></m:dPr>'
                f"<m:e>{mrun('a')}</m:e><m:e>{mrun('b')}</m:e>"
                "</m:d></m:oMath></w:p>")

    report = compare(*docs(tmp_path, fence("+"), fence("−")))

    assert [f["change"] for f in report["formula"]] == ["tokens"]
    assert report["formula"][0]["from"][1] == "a+b"
    assert report["formula"][0]["to"][1] == "a−b"


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


def test_a_marker_AFTER_a_switched_off_one_is_still_read(tmp_path):
    """`continue`, not `break`. A run that had italic turned off and
    bold left on is what Word writes when an author un-italicises part
    of a formula — the off marker comes FIRST, in Word's own property
    order, and under `break` the walk stops on it and the bold is never
    seen. The equation then compares equal to a plain one."""
    off_then_bold = '<w:rPr><w:i w:val="0"/><w:b/></w:rPr>'
    a, b = docs(tmp_path, omath(mrun("x"), mrun("+y")),
                omath(mrun("x", off_then_bold), mrun("+y")))

    report = compare(a, b)

    assert len(report["formula_format"]) == 1, report
    assert report["formula_format"][0]["to"] == "x:b", report


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


def test_a_replace_block_walks_PAST_its_first_insert(tmp_path):
    """Two bounds and a `continue`, in the loop that pairs a replace
    block positionally.

    A block whose sides are unequal — one rewritten paragraph against
    three — pads the short side, and the padding is what the whole
    function's docstring is about: never truncated, never summarised.
    `break` in place of the `continue` stops at the FIRST unpaired
    offset, so a block that gained two paragraphs reports one of them
    and the report reads as complete. And `off < len(left)` written as
    `off != len(left)` is true again as soon as the index passes the
    length, which is one paragraph later — so the read that pads goes
    off the end and raises from inside the comparison.

    Read in both directions: the two bounds are separate lines, and
    each side of the block pads the other."""
    anchors = (para(run("Anchor one.")), para(run("Anchor two.")))
    one = anchors[0] + para(run("Alpha paragraph.")) + anchors[1]
    three = (anchors[0] + para(run("Bravo paragraph."))
             + para(run("Charlie paragraph."))
             + para(run("Delta paragraph.")) + anchors[1])

    grew = compare(*docs(tmp_path, one, three))
    assert [e["text"] for e in grew["structure"]
            if e["type"] == "INSERT"] == ["Charlie paragraph.",
                                          "Delta paragraph."], grew

    shrank = compare(*docs(tmp_path, three, one))
    assert [e["text"] for e in shrank["structure"]
            if e["type"] == "DELETE"] == ["Charlie paragraph.",
                                          "Delta paragraph."], shrank


def test_formatting_is_not_reported_across_a_GLYPH_difference(tmp_path):
    """`pa.wtext_f != pb.wtext_f`, not `>`.

    Two paragraphs reach `matched` when they are equal AFTER glyph
    normalization, so the prose they carry can still differ character
    for character — a straight apostrophe against the curly one Word
    substitutes on save. `fmt_diff` refuses that pair, because a
    character-by-character comparison of two different strings reports
    the OFFSET, not the emphasis: from the first differing character on,
    every position is compared against its neighbour and the report
    names emphasis that did not move.

    The direction matters, which is why the fixture puts the straight
    quote on the left: `>` is False for it, so the guard opens exactly
    where it is needed."""
    straight = ('<w:p><w:r><w:t xml:space="preserve">It is the author'
                "'s own.</w:t></w:r></w:p>")
    curly_italic = ('<w:p><w:r><w:rPr><w:i/></w:rPr><w:t '
                    'xml:space="preserve">It is the author’s own.'
                    "</w:t></w:r></w:p>")

    report = compare(*docs(tmp_path, straight, curly_italic))

    assert report["format"] == [], report["format"]
    assert [(g["from"], g["to"]) for g in report["glyph"]] == [
        ("It is the author's own.", "It is the author’s own.")]


def test_typography_that_moves_BACKWARD_is_still_a_change(tmp_path):
    """`before[i] != after[i]`, not `<`. The markers are names, and
    under `<` only a change to an alphabetically LATER one is seen: an
    equation set upright and then italicised back goes from `nor` to
    `i`, which sorts the wrong way, and the segment finder reports the
    formula as unchanged while the report still files it under
    formula_format — a change entry with nothing in it."""
    upright = omath(mrun("x", "<m:rPr><m:nor/></m:rPr>"), mrun("+y"))
    italic = omath(mrun("x", "<w:rPr><w:i/></w:rPr>"), mrun("+y"))

    report = compare(*docs(tmp_path, upright, italic))

    assert len(report["formula_format"]) == 1, report
    entry = report["formula_format"][0]
    assert entry["from"] == "x:nor" and entry["to"] == "x:i", entry


def test_a_paragraph_THREE_equations_short_is_still_padded(tmp_path):
    """`i < len(pa.omml)`, not `i != len(...)`. The loop runs to the
    LONGER side, so the shorter one is asked for an index past its end
    and the guard pads it. Under `!=` the test is true again as soon as
    the index passes the length, and the read raises from inside the
    comparison — invisible at a distance of one, which is the distance
    every existing padding test uses.

    Four bounds share the shape — the equations and their typography,
    on both sides — and one fixture, read in both directions, holds all
    four to the same line."""
    one = para(run("See "), math(mrun("x"), mrun("y"), mrun("z")))
    three = para(run("See "), math(mrun("x")), math(mrun("y")),
                 math(mrun("z")))

    report = compare(*docs(tmp_path, one, three))
    assert report["text"] == [], "the visible text is identical"
    assert sum("<none>" in str(f["from"])
               for f in report["formula"]) == 2, report["formula"]

    mirror = compare(*docs(tmp_path, three, one))
    assert sum("<none>" in str(f["to"])
               for f in mirror["formula"]) == 2, mirror["formula"]


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


def test_a_field_AFTER_a_nested_one_is_masked_too():
    """The nested-field guard, with more than one region to compare
    against — which is what a real page footer holds: a PAGE, then a
    "page N of { NUMPAGES }" whose result carries a field of its own.

    What this pins is the half of the guard that did not change on
    2026-09-16: a field coming AFTER a nested one is covered by nothing
    and must still be masked, or a footer keeps a cached page number
    that every save rewrites — the difference this whole layer exists
    to erase.

    The guard itself is now `any(s <= result_at < e for s, e, _ in
    regions)`, and the paragraph that stood here is withdrawn with the
    line it described. It argued that `regions[0]`, `==` and `is` were
    equivalent because a nested field allowed to register its own region
    was covered by the outer mask anyway. A field in the INSTRUCTION
    half is never covered by its parent: it claims a region of its own,
    letting it through is deliberate rather than harmless, and once such
    a region is in the list `regions[-1]` is no longer the rightmost —
    which is why the masking is applied `sorted(regions, reverse=True)`
    and not `reversed(regions)`. See backlog S1 and
    `test_a_VOLATILE_field_in_the_instruction_half_is_masked_as_itself`.

    That same paragraph's `start | sep.end()` argument was overturned
    separately and on the same day. The correction is in the argued list
    below, and it is killed by
    `test_the_mask_lands_on_the_RESULT_when_the_instruction_holds_text_
    too`.
    """
    from docxkit._compare_read import mask_volatile_fields

    inner = field("PAGE", "7")
    outer = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText> PAGEREF _Toc9 </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             # a cached result of its OWN, in front of the nested field:
             # without it the outer's stale slice still opens on the
             # inner's token and the two spellings agree by accident
             + run("iii") + inner
             + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    xml = "<w:p>" + field("PAGE", "3") + outer + "</w:p>"

    out = mask_volatile_fields(xml)

    assert re.findall(r"«F:\w+»", out) == ["«F:PAGE»", "«F:PAGEREF»"], out
    assert out.count("w:fldChar") == xml.count("w:fldChar")
    assert ">3<" not in out and ">7<" not in out


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


#: Every field whose cached result Word recomputes from where the
#: document happens to sit: the page it was laid out on, the day it was
#: opened or saved, the file it was saved as, what it counts inside
#: itself. Written out here in full and NOT imported from the module,
#: because a test that reads the set it is checking cannot notice a
#: member dropped from it — the shape the renderer lists had, and both
#: were found by a mutation sweep rather than by this suite.
_RECALCULATED_BY_WORD = {
    # where the field sits on the page
    "PAGE", "NUMPAGES", "SECTIONPAGES", "PAGEREF",
    # when the document was opened, saved or printed, and for how long
    "DATE", "TIME", "CREATEDATE", "SAVEDATE", "PRINTDATE", "EDITTIME",
    # what the file is called, how big it is, who last touched it
    "FILENAME", "FILESIZE", "LASTSAVEDBY", "REVNUM",
    # what it holds, counted afresh on every save
    "NUMCHARS", "NUMWORDS",
}


def test_every_field_word_RECALCULATES_is_masked():
    """The SET, not a member of it.

    Masking a cached result is what keeps a page number out of a
    redline: two copies of one document disagree about the page a field
    was last laid out on, and comparing those raw failed every paper's
    `--expect-clean` on the day headers were included. Every test above
    exercises one member, so dropping any other from `VOLATILE_FIELDS`
    breaks that for a whole class of field and fails nothing.

    Equality rather than containment, in both directions. A member
    removed is a cached value that starts being compared by content; a
    member added is a field whose result stops being compared at all,
    which is the same gate going quiet the other way round. Either way
    the list here is where the reason gets written down.
    """
    from docxkit._compare_read import VOLATILE_FIELDS, mask_volatile_fields

    assert set(VOLATILE_FIELDS) == _RECALCULATED_BY_WORD

    for kw in sorted(_RECALCULATED_BY_WORD):
        out = mask_volatile_fields("<w:p>" + field(kw, "cached") + "</w:p>")
        assert f"«F:{kw}»" in out, f"{kw} was not masked:\n{out}"
        assert ">cached<" not in out, f"{kw} kept its cached value:\n{out}"


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
    # PANDOC's spelling of every one of them. XML says `<w:b/>` and
    # `<w:b />` are the same element; pandoc writes the spaced form for
    # every self-closing tag, and this layer matched only the tight one
    # — so a `.md`-to-`.docx` deliverable read as carrying no bold and
    # no italic anywhere. Measured 2026-08-29 on Life_Expectancy's
    # round-2 response letter: 15 `<w:b />`, 85 `<w:i />`, all invisible.
    #
    # Every fixture in this file is written by a serializer that omits
    # the space, which is exactly why nothing caught it. Both spellings
    # are held here now.
    ("<w:i />", "italic"),
    ("<w:b />", "bold"),
    ("<w:strike />", "strike"),
    ("<w:smallCaps />", "smallCaps"),
    ('<w:vertAlign w:val="superscript" />', "superscript"),
    # and the valued form, which already tolerated the space before the
    # slash — pinned so the two branches cannot drift apart again
    ('<w:b w:val="1" />', "bold"),
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


def test_a_pandoc_written_document_is_not_read_as_UNFORMATTED(tmp_path):
    """The false NEGATIVE, which is the half that ships.

    The phantom differences a spaced tag produces are noise: an lxml
    round-trip normalises the spacing and 28 FORMAT locations appear on
    a pass that changed nothing. The dangerous reading is the other one
    — a genuine loss of italics between two pandoc documents passing
    `--expect-clean` in silence, which is the same class of failure as
    the size and colour blindness this file records above.

    So this compares two PANDOC-spelled documents against each other,
    not one against a Word-spelled one: the bug survives any test where
    only one side carries the space.
    """
    with_it = ('<w:p><w:r><w:rPr><w:i /></w:rPr>'
               "<w:t>Reviewer 2</w:t></w:r></w:p>")
    without = "<w:p><w:r><w:t>Reviewer 2</w:t></w:r></w:p>"

    report = compare(*docs(tmp_path, with_it, without))

    assert report["text"] == [], "the words are the same"
    assert any("italic" in str(e) for e in report["format"]), (
        "a lost italic between two pandoc files, which used to pass "
        "--expect-clean in silence")
    assert render(report, expect_clean=True) == 1


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


def test_a_colour_is_read_even_when_the_SIZE_is_unstated(tmp_path):
    """`continue`, not `break`, in the loop over the valued properties.
    Size comes first and colour second, so the walk only reaches colour
    by stepping over a size that resolved to nothing — and a styles part
    with no default size is not exotic: it is what a template that sets
    the size on every named style produces.

    Under `break` the loop ends on the missing size and the colour layer
    goes quiet for the whole document, which is the state that shipped
    `--expect-clean` OK on a pair differing in 25 runs' colour."""
    no_default = STYLES.replace('<w:rPr><w:sz w:val="24"/></w:rPr>',
                                "<w:rPr/>", 1)
    a, b = docs(tmp_path, _sized(colour="000000"), _sized(colour="1F3864"),
                extra={"word/styles.xml": no_default})

    report = compare(a, b)

    assert any("colour 1F3864" in str(e) for e in report["format"]), report
    assert not any("size" in str(e) for e in report["format"]), report


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
                 "Para", "Part", "GATED", "BUCKETS", "VOLATILE_FIELDS",
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


def test_a_link_label_is_cut_at_NINETY_characters(tmp_path):
    """`lab[:90]`. A hyperlink's label is the visible text, and a link
    laid over a whole sentence carries the sentence — the built-only /
    user-only lines are a LIST, one per label, and an uncut label turns
    each into a paragraph. Ninety is what fits a terminal line beside
    the side and the count; the cut is the reason the section reads.

    Checked on both sides: `gone` and `gained` truncate separately, and
    a change to one of them is invisible while the other is tested."""
    long_label = "Table 5 " + "of the appendix " * 12  # 200 characters
    assert len(long_label) > 90
    anchor = ('<w:hyperlink w:anchor="Table5"><w:r><w:t>'
              + long_label + "</w:t></w:r></w:hyperlink>")
    built, edited = docs(tmp_path, para(anchor), para(run(long_label)))

    labels = [h["label"] for h in compare(built, edited)["hyperlinks"]]
    assert labels == [long_label[:90]], labels
    assert len(labels[0]) == 90

    # the same label, now only in the user's copy
    other = [h["label"] for h in compare(*docs(
        tmp_path, para(run(long_label)), para(anchor)))["hyperlinks"]]
    assert other == [long_label[:90]], other


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

    # `compare_docs`, not `compare`: the CLI door reads each side once
    # through `_package` — so that it can diff a file the author has
    # open in Word — and calls this directly, while the module door
    # still goes through `compare`, which calls it too. It is the one
    # seam both doors share.
    real = facade.compare_docs

    def with_a_set(doc_a, doc_b):
        rep = real(doc_a, doc_b)
        rep["structure"].append({"type": "PART REMOVED", "part": "body",
                                 "text": "a part", "names": {"b1", "b2"}})
        return rep

    monkeypatch.setattr(facade, "compare_docs", with_a_set)
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
    """Every bucket, from the package's own list.

    It used to spell them out here, which made this fixture a second
    answer to "what buckets are there" — and the PARAGRAPH layer then
    passed every renderer test in this file while raising KeyError on
    the first real report."""
    return {k: [] for k in BUCKETS}


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
        "media": {"type": "MEDIA CHANGED", "part": "word/media/img.png",
                  "label": mark, "from": 100, "to": 200},
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
        "paragraph": {"context": mark, "from": [f"{mark}-from"], "to": []},
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
    (1, 1, 1, 1, 1, 1, 1), (1, 3, 1, 1, 2, 0, 1), (3, 1, 4, 1, 1, 2, 0),
    (0, 2, 0, 1, 0, 0, 0), (2, 0, 1, 0, 3, 1, 2), (0, 0, 0, 0, 1, 0, 0),
    (0, 0, 0, 0, 0, 4, 0), (0, 0, 0, 0, 0, 0, 3),
])
def test_the_headline_total_is_every_gated_layer_summed(sizes):
    """The number a reader acts on is the sum of all of them, not of the
    ones a fixture happened to fill. Asserted as the relationship over
    several shapes rather than one magic constant — a single shape lets
    an arithmetic slip land on the right answer by luck."""
    # strict=True is load-bearing: a further gated layer must fail this
    # test rather than silently go uncounted here. PARAGRAPH did, on the
    # day it was added — which is what the flag is for.
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


# PARAGRAPH and MEDIA were on neither of the two lists below, and every
# mutant the 2026-09-17 sweep left alive in the renderer was in those two
# sections. A hand-written list of layers cannot notice the layer it does
# not name, and it was the second time that shape cost a round — so both
# lists are derived from BUCKETS now, the way
# `test_the_headline_total_is_every_gated_layer_summed` derives its own
# from GATED. A layer added to the report joins these tests with it.


@pytest.mark.parametrize("bucket", list(BUCKETS))
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


def test_a_paragraph_change_prints_both_sides_and_names_the_empty_one():
    """The same `'∅'` the FORMAT test pins, one layer down. A PARAGRAPH
    entry is a property stated on one side and not the other — "hanging
    indent 720 -> ∅" — and the empty side is an empty LIST inside the
    layer. Printed as `[]` it is the layer's own spelling showing
    through, which a reader cannot tell from a value the document
    states.
    """
    body = _section(_out(_filled(paragraph=1))[1], "PARAGRAPH")

    assert "MARK-paragraph-from" in body, body
    assert "-> ∅" in body, body
    assert "[]" not in body, body


def _media_entries(*entries: dict[str, object]) -> Report:
    report = _empty_report()
    report["media"] = list(entries)
    return report


def test_a_media_entry_prints_bytes_by_WHAT_HAPPENED_to_it():
    """Nothing here diffs pixels, so the sizes ARE the finding: a
    changed figure prints both of them. An added or removed one carries
    a zero on the side it does not exist on — `_compare_diff` writes it
    — and printing the pair would offer that zero to a reader as a size.
    One number each, and it is the one that exists.

    Three entries, because the type test is an equality between strings
    that sort MEDIA ADDED < MEDIA CHANGED < MEDIA REMOVED: a fixture
    with only the changed one cannot tell `==` from `<=`, and one
    without the removed one cannot tell it from `>=`.
    """
    base = {"part": "word/media/image1.png", "label": ""}
    report = _media_entries(
        {**base, "type": "MEDIA CHANGED", "from": 66203, "to": 69327},
        {**base, "type": "MEDIA ADDED", "from": 0, "to": 12003},
        {**base, "type": "MEDIA REMOVED", "from": 40960, "to": 0})

    body = _section(_out(report)[1], "MEDIA")

    part = "word/media/image1.png"
    assert f"[MEDIA CHANGED] {part}  (66,203 -> 69,327 bytes)" in body, body
    assert f"[MEDIA ADDED] {part}  (12,003 bytes)" in body, body
    assert f"[MEDIA REMOVED] {part}  (40,960 bytes)" in body, body


def test_a_media_entry_names_the_exhibit_only_when_one_is_KNOWN():
    """`label` is "Figure 8.a. Mortality and LFP" when the document
    names the figure and "" when nothing nearby does — the same walk
    answers both ways. The em-dash suffix belongs to the first: drawn
    over an empty label it reads as a figure whose caption went
    missing, and left off a known one it sends the reader to a folder
    instead of to the page."""
    base = {"type": "MEDIA CHANGED", "from": 100, "to": 200}
    report = _media_entries(
        {**base, "part": "word/media/image1.png",
         "label": "Figure 8.a. Mortality and LFP"},
        {**base, "part": "word/media/image2.png", "label": ""})

    body = _section(_out(report)[1], "MEDIA")

    lines = {p: [ln for ln in body.splitlines() if p in ln]
             for p in ("image1.png", "image2.png")}
    assert lines["image1.png"] == [
        "  [MEDIA CHANGED] word/media/image1.png  (100 -> 200 bytes)"
        "  — Figure 8.a. Mortality and LFP"], lines
    assert lines["image2.png"] == [
        "  [MEDIA CHANGED] word/media/image2.png  (100 -> 200 bytes)"], lines


def test_the_integrity_line_claims_clean_only_when_it_is():
    """INTEGRITY is the one section whose empty state is a CLAIM rather
    than a blank — "(clean: bookmarks balanced, no dangling anchors)" is
    what a reader takes as permission to ship, so printing it over a
    list of flags is the worst sentence in the report."""
    head = "BUILT-DOC INTEGRITY"
    assert "(clean:" in _section(_out(_empty_report())[1], head)
    assert "(clean:" not in _section(_out(_filled(integrity=1))[1], head)


#: The heading each bucket prints under, for the layers whose empty
#: state is the word "(none)".
_SECTION_HEADING = {
    "structure": "STRUCTURE", "text": "TEXT", "formula": "FORMULA",
    "formula_format": "FORMULA TYPOGRAPHY", "format": "FORMAT",
    "paragraph": "PARAGRAPH", "media": "MEDIA", "hyperlinks": "HYPERLINK",
    "comments": "COMMENTS", "stripped_fields": "FIELD DIFFERENCES",
}

#: The buckets that are NOT a section of their own with a "(none)" of
#: their own — each with the test that covers its empty state instead.
#: Declared, so that an exception is a statement about where the layer IS
#: covered rather than a hole in the list nobody can see.
_NOT_A_NONE_SECTION = {
    "glyph": "test_a_clean_glyph_layer_says_none_only_when_both_halves_"
             "are_empty",
    "formula_glyph": "test_a_clean_glyph_layer_says_none_only_when_both_"
                     "halves_are_empty",
    "integrity": "test_the_integrity_line_claims_clean_only_when_it_is",
}


def test_every_bucket_is_a_section_here_or_a_declared_exception():
    """The guard on the two lists above, and the point of deriving them.

    A bucket added to the report joins `_SECTION_HEADING` — or, if its
    empty state is not a "(none)" under a heading of its own, it is
    written into `_NOT_A_NONE_SECTION` against the test that does cover
    it. Both are a sentence somebody has to write; neither is silence.
    """
    covered = set(_SECTION_HEADING) | set(_NOT_A_NONE_SECTION)
    assert covered == set(BUCKETS), (
        f"buckets nobody placed: {sorted(set(BUCKETS) - covered)}; "
        f"names that are not buckets: {sorted(covered - set(BUCKETS))}")
    assert not set(_SECTION_HEADING) & set(_NOT_A_NONE_SECTION)
    for bucket, covering in _NOT_A_NONE_SECTION.items():
        assert covering in globals(), (
            f"{bucket} names {covering}, which is not a test in this file")


@pytest.mark.parametrize("bucket,heading", sorted(_SECTION_HEADING.items()))
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


# --- the survivors of 2026-09-14 ------------------------------------------
#
# The sweep of `_compare_diff.py` left 43 real survivors, and those not
# argued away share a cause: every edge case ADDS whitespace, every
# equation is one bare run, whose skeleton is the empty string and so one
# shared object, and nothing ran past 256 characters or 256 of anything.


def test_marker_segments_falls_back_when_the_markers_OUTNUMBER_the_text():
    """The same guard from the other side: markers are one per symbol,
    and a list longer than the symbols is as far from that as a shorter
    one."""
    from docxkit._compare_diff import _marker_segments

    segs = _marker_segments("xy", ["i", "i", "i"], ["i", "up", "i"])

    assert segs == [("xy", "i", "i,up")]


def test_a_leading_space_TAKEN_AWAY_is_reported_too(tmp_path):
    """Every edge case in this file adds whitespace. Taking it away moves
    the first word back to the margin, the same indent read the other way
    round."""
    indented = BASE.replace(run("The index rose to 0.35 in 2024."),
                            run(" The index rose to 0.35 in 2024.",
                                preserve=True))
    a, b = docs(tmp_path, indented, BASE)

    assert [t["word_diff"] for t in compare(a, b)["text"]] == [
        ["EDGE leading: ' ' -> ''"]]


def test_the_SAME_edge_on_both_sides_is_no_change(tmp_path):
    """Two spaces in front on both sides is no edit, and each side's edge
    is a slice of its own text: equal strings, different objects. One
    space would not show it, since CPython keeps a single object for
    every one-character string."""
    indented = BASE.replace(run("The index rose to 0.35 in 2024."),
                            run("  The index rose to 0.35 in 2024.",
                                preserve=True))
    a, b = docs(tmp_path, indented, indented)

    assert compare(a, b)["text"] == []


def test_a_formatting_change_in_a_paragraph_LONGER_than_256_characters(
        tmp_path):
    """The formatting walk runs only when both sides hold the same number
    of characters, and that is a comparison of two ints: past 256 CPython
    builds a new object for each, so two equal lengths compared by
    identity differ and the change is never looked for."""
    tail = " and the text runs on" * 15
    plain = para(run(f"See the Journal of Things here{tail}."))
    italic = ('<w:p><w:r><w:t xml:space="preserve">See the </w:t></w:r>'
              "<w:r><w:rPr><w:i/></w:rPr><w:t>Journal of Things</w:t></w:r>"
              f'<w:r><w:t xml:space="preserve"> here{tail}.</w:t></w:r>'
              "</w:p>")
    a, b = docs(tmp_path, plain, italic)

    report = compare(a, b)

    assert report["text"] == []
    assert any("italic" in str(e) for e in report["format"]), report


def _sup(base: str, sup: str) -> str:
    """A superscript. `sSup` is a structural element with a name of more
    than one character, so each side's skeleton is a string of its own."""
    return (f"<m:sSup><m:e>{mrun(base)}</m:e>"
            f"<m:sup>{mrun(sup)}</m:sup></m:sSup>")


def test_a_TOKEN_change_inside_a_structure_is_not_a_structure_change(
        tmp_path):
    """The two skeletons are equal and are separate objects, read from
    two documents, so a structure test by identity calls every token
    change a rewrite of the formula's shape as well. The words moved, so
    the kinds ride on the TEXT entry."""
    report = compare(*docs(tmp_path, omath(_sup("x", "2")),
                           omath(_sup("y", "2"))))

    assert [t["formula"] for t in report["text"]] == [["tokens"]], report


def test_a_GLYPH_change_inside_a_structure_is_still_a_glyph_artifact(
        tmp_path):
    """A math minus flattened to a hyphen in a superscript is Word's
    artifact, not an edit. It is one only while the skeletons are equal,
    and a test by identity finds two equal skeletons unequal and sends
    the artifact to the gated FORMULA layer."""
    report = compare(*docs(tmp_path, omath(_sup("x", "−1")),
                           omath(_sup("x", "-1"))))

    assert report["formula"] == [], report["formula"]
    assert len(report["formula_glyph"]) == 1, report


def test_an_id_OPENED_and_closed_300_times_is_balanced():
    """Starts and ends are counted and the counts compared. Past 256
    CPython builds a new object for each int, so two equal counts
    compared by identity differ and a balanced id reads as unbalanced."""
    pair = ('<w:bookmarkStart w:id="7" w:name="Table1"/>'
            '<w:bookmarkEnd w:id="7"/>')

    issues = _integrity(f"<w:p>{pair * 300}</w:p>")

    assert not any("imbalance" in i for i in issues), issues


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


#: A field marker as other producers write one: a space before the close
#: (369 in 9 of 2,954 corpus packages), or a locked field (`w:fldLock`, 9
#: in 2). The patterns read only `<w:fldChar w:fldCharType="…"/>`.
#:
#: The third spelling is the same attributes in the other ORDER, which
#: XML does not distinguish and a reader of the pattern easily does:
#: `<w:fldChar\b[^>]*\bw:fldCharType=` is written that way on purpose —
#: the same reading `integrity` gives bookmark ids, after hard-coding
#: the order there made the layer find no bookmarks at all on a
#: conforming document. Added by the data census of 2026-09-18: deleting
#: the `[^>]*` from the counter's pattern changed no test.
_OTHER_BEGINS = ('<w:fldChar w:fldCharType="begin" />',
                 '<w:fldChar w:fldCharType="begin" w:fldLock="1"/>',
                 '<w:fldChar w:fldLock="1" w:fldCharType="begin"/>')


@pytest.mark.parametrize("begin", _OTHER_BEGINS)
def test_a_balanced_field_in_ANOTHER_spelling_is_no_finding(begin):
    """Not counted, its begin left the end alone at depth -1, and a
    field that renders perfectly was reported as literal field code."""
    xml = (f"<w:p><w:r>{begin}</w:r>"
           r'<w:r><w:instrText> PAGE </w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           "<w:r><w:t>4</w:t></w:r>"
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')

    assert _integrity(xml) == []


@pytest.mark.parametrize("marker", ["separate", "end"])
def test_a_field_LABEL_is_read_whatever_its_markers_spelling(marker):
    """The label sits between `separate` and `end`, and either marker
    written ` />` hid it: the link was not on the list, so a relabelled
    field-form citation went unseen."""
    from docxkit._compare_diff import hyperlink_labels
    from docxkit.citations import hyperlink_field

    field = hyperlink_field("Hao2008", "Hao et al. (2008)").replace(
        f'<w:fldChar w:fldCharType="{marker}"/>',
        f'<w:fldChar w:fldCharType="{marker}" />')
    assert f'"{marker}" />' in field

    assert hyperlink_labels(f"<w:p>{field}</w:p>") == {"Hao et al. (2008)": 1}


def _link_field(anchor: str, label: str, end_rpr: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l "{anchor}"'
            " </w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f"<w:r><w:t>{label}</w:t></w:r>"
            f'<w:r>{end_rpr}<w:fldChar w:fldCharType="end"/></w:r>')


def test_an_EMPTY_rPr_on_a_field_s_end_run_does_not_swallow_the_next():
    """The end run's properties were read open-and-shut first, and an
    EMPTY `<w:rPr/>` taken for that opening ran on to the next
    `</w:rPr>` — here the next field's end run's — so one match covered
    both fields and the second label was never read."""
    from docxkit._compare_diff import hyperlink_labels

    xml = ("<w:p>" + _link_field("Hao2008", "Hao (2008)", "<w:rPr/>")
           + "<w:r><w:t>; </w:t></w:r>"
           + _link_field("Sen1999", "Sen (1999)",
                         "<w:rPr><w:noProof/></w:rPr>") + "</w:p>")

    assert hyperlink_labels(xml) == {"Hao (2008)": 1, "Sen (1999)": 1}


def test_a_GHOST_link_does_not_lend_its_label_to_the_prose_after_it():
    """`<w:hyperlink w:anchor="…"/>` is an empty ghost Word leaves behind
    (49 in 35 corpus packages). Read as an open tag it ran on to the NEXT
    link's close, and the prose between them read as that link's label."""
    from docxkit._compare_diff import hyperlink_labels

    xml = ('<w:p><w:hyperlink w:anchor="Gone2020"/>'
           "<w:r><w:t>Prose between them. </w:t></w:r>"
           '<w:hyperlink w:anchor="Smith2020"><w:r><w:t>Smith (2020)</w:t>'
           "</w:r></w:hyperlink></w:p>")

    assert hyperlink_labels(xml) == {"Smith (2020)": 1}


def test_a_bookmark_written_NAME_FIRST_is_a_target_its_links_reach():
    """The part's own bookmark names were read as an optional `w:name`
    straight after `w:id`, so a start written name-first (97 in 7 corpus
    packages) named nothing, and the link to it read as dangling when
    the caller's `names` did not already hold it."""
    xml = ('<w:p><w:bookmarkStart w:name="T1" w:id="1"/>'
           '<w:bookmarkEnd w:id="1"/><w:hyperlink w:anchor="T1"><w:r>'
           "<w:t>Table 1</w:t></w:r></w:hyperlink></w:p>")

    assert _integrity(xml, set()) == []


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

    The two mutants this did NOT kill were both argued equivalent
    (`tools/kill_check.py`, expect_kill=False). Both arguments are dead
    as of 2026-09-16, and neither line survives:

    * `regions[-1]` -> `regions[0]`. The argument ran that a nested
      field allowed its own region is covered by the outer mask anyway,
      the outer slice cutting seven characters early into TAG text that
      the concatenation puts back unchanged. It named its own limit —
      "it stops being equivalent the moment a boundary falls inside a
      `w:t`" — and that is exactly what happens: a long cached result
      shifts the stale slice far enough to clear `</w:r><w:r><w:t>`, and
      the outer field's own result is then left in the document.
      Measured, and pinned by
      `test_the_regions_are_masked_RIGHT_TO_LEFT`. The guard reads
      `any(s <= result_at < e for s, e, _ in regions)` now and a field
      in the INSTRUCTION half claims a region of its own on purpose, so
      the line these mutants respelled is gone.
    * `start + sep.end()` -> `start | sep.end()` was overturned the same
      day by measurement — a field whose instruction half carries a
      `w:t` tells the two spellings apart. The correction is in the
      argued list below; do not re-derive the old argument."""
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
# Seven of the eight are equivalent by construction, argued rather than
# assumed (`tools/kill_check.py`, expect_kill=False) and worth writing
# down because each looks like a gap:
#
# * the CELL counter's initial value, `[tables, 0, 1]`. A table's first
#   `w:tr` sets it to 0 before any `w:tc` is seen, so the value the stack
#   was pushed with is never read — the ROW counter's initial value is a
#   real check, and dies here;
# * `tag >= "tr"` and `tag >= "tc"` for `==`, and `>=` or `<=` for the
#   `"p"` arm. The only tags reaching them are `p`, `tc`, `tr`, and they
#   sort in that order — `"p"` is below both and `"tr"` is consumed by
#   the arm above `tc`, so every ORDERING of the three agrees with
#   equality. `!=` does not, and dies;
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


def test_every_part_label_this_package_can_build_sorts_AFTER_body():
    """The PREMISE two claims in `tools/equivalents.toml` stand on, which
    nothing else would notice losing.

    Both are on the line above — `"BUILT" if part.label == "body"` read
    as `<= "body"` and as `is "body"` — and both are arguments about a
    VOCABULARY rather than about this module: `Part.label` is assigned in
    exactly one place, `_compare_read.Part.__init__`, as the literal
    `body` for the document and the part's own stem for everything else,
    and `TEXT_PART_RE` is what says which stems exist. Every one of them
    today begins d/e/f/h, so each sorts strictly after `body` and none
    equals it: `<=` is true exactly where `==` is, and the only `body` in
    the package is an interned literal, which is what makes `is` agree.

    Add one part type whose stem sorts BEFORE `body` — `appendix`, say —
    and both claims become false while every test in this file still
    passes, because no fixture has such a part and `verify_equivalents`
    can only re-run the claims it was given. That is the failure a
    vocabulary has: the set gains a member and the code that reasons
    about its members by hand does not notice. So the enumeration is read
    from the pattern rather than written out here, and a stem added to it
    arrives in this test the day it is added.
    """
    from docxkit._compare_read import TEXT_PART_RE, Part

    alternatives = re.search(r"\(([^)]+)\)", TEXT_PART_RE.pattern)
    assert alternatives is not None, TEXT_PART_RE.pattern
    names = sorted({f"word/{stem.replace(chr(92) + 'd*', digits)}.xml"
                    for stem in alternatives.group(1).split("|")
                    for digits in ("", "2")})
    # the enumeration is only worth anything if the pattern still admits
    # what it produced — a rewritten pattern must land here, not pass
    for name in names:
        assert TEXT_PART_RE.match(name), f"{name} is not one of the parts"

    labels = {name: Part(name, "<w:p/>").label for name in names}

    assert [n for n, label in labels.items() if label == "body"] == [
        "word/document.xml"], labels
    assert all(label > "body" for name, label in labels.items()
               if name != "word/document.xml"), labels
    # `$` matches before a trailing newline too, so a zip entry can carry
    # one and still be admitted. The stem is then `document.`, which is
    # after `body` like the rest — the claims hold on it as well.
    odd = "word/document.xml\n"
    assert TEXT_PART_RE.match(odd), "the pattern no longer admits it"
    assert Part(odd, "<w:p/>").label > "body"


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

    # and the USER-only side, which is its own `append` with its own
    # copy of the number
    a2, b2 = docs(tmp_path, para(run("See nothing at all.")), linked)

    (added,) = [h for h in compare(a2, b2)["hyperlinks"]
                if h.get("side") == "user-only"]

    assert added["label"] == long_label[:90]
    assert len(added["label"]) == 90


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

    The two index mutants once argued equivalent here (`regions[0]` for
    `regions[-1]`, and the region's start for its end) are gone with the
    line they respelled, 2026-09-16. Their argument — letting the nested
    field through appends a region the outer one covers exactly — holds
    only for a field in the outer's RESULT half, which is the nesting
    this fixture has. It is false for one in the INSTRUCTION half, which
    no parent covers, so the guard now buys the output and not only the
    work."""
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


def test_a_SECOND_equation_is_walked_after_an_unchanged_first(tmp_path):
    """`continue`, not `break`: a paragraph holds as many equations as
    the author put in it, and the first one being untouched says nothing
    about the second. Under `break` a methods paragraph that repeats its
    definition and then rewrites the estimator reports nothing at all."""
    same = math(mrun("x"), mrun("+y"))
    a = f"<w:p>{same}{math(mrun('a'), mrun('+b'))}</w:p>"
    b = f"<w:p>{same}{math(mrun('a'), mrun('-b'))}</w:p>"

    report = compare(*docs(tmp_path, a, b))

    assert [t["formula"] for t in report["text"]] == [["tokens"]]


def test_a_structure_change_the_OTHER_WAY_ROUND_is_still_structure(tmp_path):
    """`ea[0] != eb[0]`, not `<`: the skeletons are strings and which
    one sorts higher is an accident of the tags. Flattening a subscript
    (`sSub` -> nothing) is the same edit as adding one, and under `<`
    only one of the two directions is reported.

    And `glyph_only` asks `ea[0] == eb[0]` — under `>=` a structural
    change whose skeleton sorts above the other's reads as glyph-only,
    which moves the finding out of the gated bucket and into the review
    one."""
    flat = omath(mrun("x"), mrun("1"))
    sub = omath("<m:sSub><m:e>" + mrun("x") + "</m:e><m:sub>"
                + mrun("1") + "</m:sub></m:sSub>")

    # sub -> flat, the direction the existing fixture does not take
    report = compare(*docs(tmp_path, sub, flat))

    assert [f["change"] for f in report["formula"]] == ["structure"]
    assert report["glyph"] == [], "a skeleton change is not a glyph one"


def test_an_equation_that_LOST_its_emphasis_names_the_symbol(tmp_path):
    """`before[i] != after[i]`, not `<`: the markers are strings and
    which sorts higher is an accident. Every fixture above adds
    emphasis, where "" sorts below anything; a symbol that LOST its
    italic is the same edit backwards, and under `<` the segment walk
    finds nothing to report — so the finding arrives with both sides
    empty.

    Word's Compare strips math-italic from a rewritten equation, which
    is where this comes from."""
    plain = omath(mrun("x"), mrun("+y"))
    italic = omath(mrun("x", "<w:rPr><w:i/></w:rPr>"), mrun("+y"))

    report = compare(*docs(tmp_path, italic, plain))

    (entry,) = report["formula_format"]
    assert entry["from"] == "x:i"
    assert entry["to"] == "x:plain"


def test_a_FIELD_FORM_link_whose_label_changed_is_reported(tmp_path):
    """The label walk reads both forms, and the field-form loop was
    free: the test beside it asserts that Word's closing run does not
    make a FALSE finding, and nothing asserted a real one. Field form is
    what half these manuscripts carry — `probe` reports it first,
    because `crossrefs.unlink` cannot see those links at all."""
    from docxkit.citations import hyperlink_field

    before = para(run("See ") + hyperlink_field("Table1", "Table 1"))
    after = para(run("See ")
                 + hyperlink_field("Table1", "Table 1: Descriptive stats"))

    report = compare(*docs(tmp_path, before, after))

    pairs = [(h.get("side"), h.get("label"), h.get("to"))
             for h in report["hyperlinks"]]
    assert pairs == [("grew", "Table 1", "Table 1: Descriptive stats")]


# --- what `load` OPENS, which is where compare's time goes --------------


def test_load_reads_the_parts_it_compares_and_NOTHING_else(tmp_path,
                                                           monkeypatch):
    """The 2026-08-15 review measured 89 % of a compare as loading, and
    the fix was to stop reading the package whole: the media, the
    custom XML, the rsid-heavy settings part and the theme are
    megabytes that no layer of this diff ever looks at.

    A read scope is invisible in every other test — the report is
    identical either way — so this asserts the ZIP entries `load`
    actually asks for. `styles.xml` is in the list and is not compared:
    the FORMAT layer resolves size and colour through it, and without it
    a document that renders identically reports a difference.
    """
    import zipfile

    from docxkit._compare_read import load
    from docxkit.package import write_docx

    path = tmp_path / "paper.docx"
    write_docx(path, {
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": document(para(run("The paper."))).encode(),
        "word/footnotes.xml": notes("footnotes",
                                    note("A note.", 2)).encode(),
        "word/endnotes.xml": notes("endnotes",
                                   note("A back note.", 2,
                                        "endnote")).encode(),
        "word/header1.xml": f"<w:hdr {NS}>{para(run('Head'))}</w:hdr>"
                            .encode(),
        "word/styles.xml": f"<w:styles {NS}/>".encode(),
        "word/comments.xml": f"<w:comments {NS}/>".encode(),
        # none of these are prose a reader sees, and two of them are the
        # big ones in a real manuscript
        "word/settings.xml": f"<w:settings {NS}/>".encode(),
        "word/theme/theme1.xml":
            b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>',
        "customXml/item1.xml": b"<props/>",
        "word/media/image1.png": b"\x89PNG not really",
    })

    read: list[str] = []
    original = zipfile.ZipFile.read

    def recording_read(self, name, *a, **kw):
        read.append(str(name))
        return original(self, name, *a, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "read", recording_read)

    load(str(path))

    # media joined the list on 2026-08-24, with the rels that NAME it:
    # a figure replaced, corrupted or deleted used to report as zero
    # changes. settings.xml, the theme and customXml stay out — they are
    # not prose a reader sees, and two of them are the big ones.
    assert set(read) == {"word/document.xml", "word/footnotes.xml",
                         "word/endnotes.xml", "word/header1.xml",
                         "word/styles.xml", "word/comments.xml",
                         "word/media/image1.png"}, read


# --- what the _compare_diff run of 2026-08-20 found -----------------------
#
# 460 mutants over the whole module, 8.8 % real survival, and the
# survivors were nearly all in the layers a reader READS rather than the
# ones the gate consults: how much of a comment the summary prints, which
# paragraph a lost target is attributed to, how short a link label may be
# and still count as one. None of them changes whether the round passes;
# every one of them changes what the person doing the round is looking at.


def test_a_long_comment_is_CUT_on_BOTH_sides_of_the_report(tmp_path):
    """`note[:110]`, twice — the built-only line and the user-only line
    are separate slices and a fixture that exercises one leaves the
    other unpinned. Reviewer notes run to paragraphs; a comment layer
    that printed them whole would push the rest of the summary off the
    screen, which is the failure this cut is for."""
    built = ("the 2019 wave is missing from Table 3 and the standard "
             "errors are not clustered by region, which the referee "
             "asked for twice")
    user = ("please recheck whether the appendix figure still matches "
            "the revised specification before this goes back to the "
            "co-authors")

    a, b = docs(tmp_path, para(run("Text.")), para(run("Text.")),
                comment_items=((comment(1, built),), (comment(2, user),)))

    seen = {c["side"]: c["text"] for c in compare(a, b)["comments"]}

    assert len(seen["built-only"]) == 110
    assert seen["built-only"].startswith("Tester: the 2019 wave")
    assert seen["built-only"].endswith("which the r"), "cut mid-word"
    assert len(seen["user-only"]) == 110
    assert seen["user-only"].startswith("Tester: please recheck")
    assert seen["user-only"].endswith("this goes ba"), "cut mid-word"


def test_a_THREE_character_label_is_long_enough_to_be_a_move(tmp_path):
    """`_LABEL_KEEP` is the length at which containment stops being a
    coincidence, and 3 is on the KEEPING side of it: "Fig" inside
    "Fig. 2" is the label a caption lost, while a two-character label
    sits inside half the prose in the document.

    Read from the other end, this is the difference between one finding
    that says what happened and two that leave the reader to pair a
    built-only label with a user-only one themselves."""
    from docxkit.citations import hyperlink_field

    a, b = docs(tmp_path,
                para(run("As shown in ") + hyperlink_field("fig2", "Fig. 2")
                     + run(", the trend holds.")),
                para(run("As shown in ") + hyperlink_field("fig2", "Fig")
                     + run(", the trend holds.")))

    assert compare(a, b)["hyperlinks"] == [
        {"side": "shrank", "label": "Fig. 2", "to": "Fig", "n": 1}]


def test_a_label_that_is_both_LOST_and_GAINED_is_not_a_move_to_itself():
    """`o != new`, asked of the exported function rather than of the
    pipeline. Inside `compare` the guard cannot fire — `gone` and
    `gained` are opposite Counter differences, so no label is in both —
    but `label_moves` is exported, and a caller who hands it overlapping
    counters must not be told a label moved to itself.

    The label is BUILT at run time on purpose: two equal literals in one
    module are one object, and identity would then answer this question
    correctly by accident."""
    from collections import Counter

    from docxkit.compare import label_moves

    label = " ".join(["Table 4: the discipline", "gradient"])
    assert label == "Table 4: the discipline gradient"

    assert label_moves(Counter({label: 1}),
                       Counter({"Table 4: the discipline gradient": 1})) == []


def test_a_move_is_still_found_PAST_an_insert_that_is_already_taken(tmp_path):
    """The skip over an already-matched insert is a `continue`, and the
    distance between that and a `break` is a second move: the paragraph
    whose partner sits behind one that is already spoken for is reported
    as a DELETE and an INSERT — two findings, in two layers, for one
    paragraph that moved.

    Two paragraphs moved as a pair is not an exotic fixture. It is what
    a section swapped with the one before it looks like."""
    x = para(run("Methods follow the standard approach."))
    y = para(run("Conclusions are unchanged from the first draft."))
    c1 = para(run("The index rose to 0.35 in 2024."))
    c2 = para(run("Coverage is complete for every oblast."))

    a, b = docs(tmp_path, x + y + c1 + c2, c1 + c2 + x + y)
    report = compare(a, b)

    assert [e["type"] for e in report["structure"]] == ["MOVE", "MOVE"]
    assert [e["text"][:9] for e in report["structure"]] == ["The index",
                                                            "Coverage "]
    assert report["text"] == []


def test_a_lost_target_is_attributed_to_the_paragraph_that_HELD_it(tmp_path):
    """`gone[0]`: the block's losses are collected together and pinned
    to the paragraph holding the FIRST of them, so the report says where
    to look. With one lost target per fixture the index is invisible —
    the second paragraph's context reads as plausibly as the first."""
    from docxkit.citations import hyperlink_field

    left = (para(run("The first paragraph cites ")
                 + hyperlink_field("aaa_ref", "Adams 2019")
                 + run(" for the baseline estimate."))
            + para(run("The second paragraph cites ")
                   + hyperlink_field("zzz_ref", "Zhang 2020")
                   + run(" for the follow-up estimate.")))
    right = (para(run("The opening paragraph reports the baseline instead."))
             + para(run("The closing paragraph reports the follow-up "
                        "instead.")))

    a, b = docs(tmp_path, left, right)

    (found,) = compare(a, b)["stripped_fields"]

    assert found["context"].startswith("The first paragraph")
    assert found["lost"] == [
        "lost hyperlink target(s): ['aaa_ref', 'zzz_ref']"]


def test_at_exactly_the_similarity_threshold_it_is_NOT_a_move(tmp_path):
    """`r > 0.85`, and the fixture sits exactly on it: every one of the
    51 characters of the old paragraph appears in the 69 of the new one,
    which is 2 x 51 / 120 = 0.85 to the last bit.

    The threshold is what separates "this paragraph moved and was
    lightly edited" from "one paragraph went and another arrived", and a
    boundary nothing tests can move by a hundredth without a single test
    noticing — in either direction, since the two readings differ only
    on the pairs that land on the line itself."""
    keep = para(run("Methods follow the standard approach."))
    old = para(run("The index rose to 0.35 in 2024 across every oblast."))
    new = para(run("The index rose to 0.35 in 2024 across every oblast "
                   "and again in 2025."))

    report = compare(*docs(tmp_path, old + keep, keep + new))

    assert [e["type"] for e in report["structure"]] == ["DELETE", "INSERT"]


def test_a_token_change_that_sorts_BACKWARD_is_still_a_token_change(tmp_path):
    """`ea[1] != eb[1]`. Whether an equation's tokens changed is a
    question about equality, and every fixture that asks it with the new
    stream sorting AFTER the old one is answered the same way by an
    ordering comparison. An author who replaced z with x made the same
    edit as one who replaced x with z."""
    a, b = docs(tmp_path, omath(mrun("z"), mrun("+y")),
                omath(mrun("x"), mrun("+y")))

    report = compare(a, b)

    assert [t["formula"] for t in report["text"]] == [["tokens"]]



def test_a_LONG_equation_still_names_the_symbol_that_changed(tmp_path):
    """The per-character typography lists are compared to the token
    stream by LENGTH before they are walked, and the length of a real
    equation is a number CPython does not cache: two lengths of 287 are
    equal and are not the same object.

    An identity test there is invisible on every short fixture and turns
    every long one into a single blob — the whole formula reported as
    changed, with its markers joined into a set, which is the report
    per-symbol segmentation exists to replace."""
    long_run = "".join(f"x_{i}+" for i in range(1, 60))
    assert len(long_run) > 256, "the point of the fixture is the length"

    a, b = docs(tmp_path,
                omath(mrun(long_run), mrun("y")),
                omath(mrun(long_run), mrun("y", "<w:rPr><w:i/></w:rPr>")))

    assert compare(a, b)["formula_format"] == [
        {"change": "formatting", "from": "y:plain", "to": "y:i"}]


def test_a_symbol_that_KEPT_its_marker_is_not_reported_as_changed(tmp_path):
    """`before[i] != after[i]`, over markers that are not single
    characters. "nor" and "sty=bi" are built at run time — split out of
    a tag name, or formatted from a value — so the two sides of an
    unchanged symbol are equal strings and separate objects, and an
    identity test calls every one of them a change.

    The report then names the symbols that did not move, beside the one
    that did, with the same marker on both sides of the arrow."""
    upright = "<m:rPr><m:nor/></m:rPr>"

    a, b = docs(tmp_path,
                omath(mrun("x", upright), mrun("y")),
                omath(mrun("x", upright), mrun("y", "<w:rPr><w:i/></w:rPr>")))

    assert compare(a, b)["formula_format"] == [
        {"change": "formatting", "from": "y:plain", "to": "y:i"}]


# Argued rather than pinned, from the same run:
#
# * `m.group(1)` widened to `m.group(0)` in `hyperlink_labels`, both
#   forms. The group is the CONTENT of a link and group 0 adds its
#   delimiters — an opening `<w:hyperlink>` tag, or a `fldChar
#   separate` run and the field's closing run. `WT_RE` reads `<w:t>`
#   elements, and none of those delimiters contains one, so the label
#   comes back the same. (`m.group(2)` was killed: neither pattern has
#   a second group.)
# * `-len(s)` written `~len(s)` in both of `label_moves`' sort keys.
#   `~n` is `-n - 1`: the same strictly decreasing function of length,
#   so longest-first is still longest-first.
# * `len(new) > len(old)` written `>=`. The pair reaching that line has
#   passed `o != new` AND `o in new or new in o`, and two different
#   strings where one contains the other cannot be the same length —
#   the equal case the operators disagree on is unreachable, and it is
#   the `o != new` guard above that makes it so.
# * the `break` after `if not gained[new]` written `continue`. It leaves
#   a loop whose `while gained[new] and gone[old]` is now false for
#   every remaining candidate, so the continuation emits nothing.
# * `holder.text[:60]` in the leftover-notes loop. Every note whose
#   holder is a paragraph has had its key popped by the offset loop
#   above — which visits every index of `left` — so the only notes
#   reaching that loop are the ones with no holder at all ("lost N
#   footnote ref(s)"), and the truncation sits on the dead side of its
#   own guard. The `if holder` / `if not holder` mutant IS killed, by
#   the AttributeError that reading `.text` off None raises.
# * `self.where != "body"` in `place`, as `>` and as `is not`. The same
#   argument compare.py makes over the same value at its own integrity
#   loop: every part label `_compare_read` produces — footnotes,
#   endnotes, header/footer N — sorts after "body", and the label is
#   that literal.
# * `len(pa.fmt) != len(pb.fmt)` in `fmt_diff` as `>`. The second half
#   of that guard is only ever reached when the first is false — the
#   two texts are EQUAL — and `_char_fmt` appends one flag set per
#   character, so equal texts have equal `fmt` lengths and neither
#   operator fires. (The `!=` in the FIRST half is pinned, by the test
#   above that puts a straight apostrophe on the built side.)
# * `len(before) != len(text)` in `_marker_segments` as `<`. `text` is
#   the token stream of the whole oMath block and `before` holds one
#   marker per character of the `m:r` runs inside it, so `before` can
#   be SHORTER — an `m:t` outside a run — and never longer. The
#   operators can only part company on the case that cannot happen.
# * `self.kind == "formatting"` in `bucket` and `!=` in `entry`, as
#   `is`, `is not` and `<=`. A FormulaChange's kind is either that
#   literal — written at the one construction site in this module, so
#   the same object — or `", ".join(kind)` over ["tokens"],
#   ["structure"] or both, every one of which sorts AFTER "formatting".
# * `starts[i] != ends[i]` in `integrity` as `is not`: both sides are
#   bookmark COUNTS, and a document with more than 256 starts of one id
#   is not a document.
# * `m.group(1) == "begin"` in `integrity` as `<=`, and the difflib tag
#   comparisons in `word_diff` and `compare_paras` as `is`, `<=`, `>=`.
#   The value sets are fixed and small — {begin, end}, {equal, delete,
#   insert, replace} — and over each of them the ordering operator
#   agrees with equality on every value that can reach the line;
#   difflib's tags are module literals, so identity agrees too.


# --- the _compare_read run of 2026-08-20 ---------------------------------
#
# 7.3 %, and the survivors were in the READING rather than in the
# comparison: which part of a match is kept, where a mask starts, how
# alike two running heads have to be before they are the same head.


def test_a_flag_switched_OFF_is_not_a_flag(tmp_path):
    """`m.group(1)`, the VALUE of `w:val`, against the whole tag. Word
    writes `<w:b w:val="0"/>` when an author unbolds a word inside a
    bold style — the property is present and says off — and the whole
    tag is never one of "0", "false", "none", so every switched-off
    property reads as switched ON.

    Both documents then differ in emphasis nothing carries, which is the
    report that gets a comparison ignored."""
    off = ('<w:p><w:r><w:rPr><w:b w:val="0"/></w:rPr>'
           "<w:t>The index rose.</w:t></w:r></w:p>")
    plain = "<w:p><w:r><w:t>The index rose.</w:t></w:r></w:p>"

    report = compare(*docs(tmp_path, off, plain))

    assert report["format"] == [], report["format"]


def test_a_SUPERSCRIPT_is_reported_by_its_name(tmp_path):
    """`va.group(1)` is the vertical alignment itself — "superscript" —
    and the whole match is `<w:vertAlign w:val="superscript"/>`. The
    difference is invisible in any test that asks whether the format
    layer FIRED and visible in the only place it matters: the line a
    reader is given, which then names an XML element at them."""
    plain = "<w:p><w:r><w:t>The index rose.</w:t></w:r></w:p>"
    sup = ('<w:p><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
           "<w:t>The index rose.</w:t></w:r></w:p>")

    report = compare(*docs(tmp_path, plain, sup))

    assert [(e["from"], e["to"]) for e in report["format"]] == [
        ([], ["superscript"])], report["format"]


def test_the_mask_replaces_the_cached_RESULT_and_nothing_else():
    """The existing tests count the mask TOKENS a walk produced; this
    one is about everything it did NOT touch. A masked field still has
    to be a field — Word reads the instruction, not the cached result,
    so a mask that ate the `instrText` would turn a page number into
    literal text on the next save — and the running head above it is
    not the comparison's business at all.

    Stated as one equality, because "the document with this one text
    node replaced" is the whole contract."""
    from docxkit._compare_read import mask_volatile_fields

    xml = para(run("Page ")) + "<w:p>" + field("PAGE", "7") + "</w:p>"

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>"), out
    assert "> PAGE </w:instrText>" in out, "the instruction was cut"


def test_two_running_heads_SIXTY_PER_CENT_alike_are_the_same_head():
    """`score >= 0.6`, and the fixture sits exactly on it: twelve
    characters, every one of them in the twenty-eight of the other, is
    2 x 12 / 40.

    Headers do not pair by name — a section edit renumbers header2 to
    header3 — so this threshold is the whole of what decides whether an
    edited running head is one part that changed or two parts, one
    added and one removed. A hundredth either way is a different report,
    and nothing said which side of it the boundary sits on."""
    from docxkit._compare_read import Part, pair_parts

    pa = Part("word/header1.xml", hdr(para(run("Running head"))))
    pb = Part("word/header2.xml", hdr(para(run("Running head, second "
                                               "version"))))

    pairs = pair_parts([pa], [pb])

    assert [(x.name if x else None, y.name if y else None)
            for x, y in pairs] == [("word/header1.xml", "word/header2.xml")]


def test_a_paragraph_carries_WORDS_id_not_the_attribute_it_sits_in():
    """`Para.pid` is `w14:paraId`'s VALUE. It is the one identifier that
    survives an edit in Word — comments.py matches on it — and it is
    public through `docxkit.compare.Para`, so what it holds is a
    contract even while this module only reads it out.

    Nothing in the package consumes it yet, which is exactly why the
    mutant that puts the whole attribute in it lived: a value carried
    and never read is a value nobody can be wrong about until someone
    uses it."""
    from docxkit._compare_read import Para

    assert Para(para(run("Text."), pid="AB12CD34"), "").pid == "AB12CD34"
    assert Para("<w:p><w:r><w:t>No id.</w:t></w:r></w:p>", "").pid is None


# Argued rather than pinned, from the same run:
#
# * `run.group(1)` and `rpr_m.group(1)` in `_char_fmt`, widened to group
#   0. Both add only the element's own tags — `<w:r ...>` around a run's
#   body, `<w:rPr>` around its properties — and everything read out of
#   them (`RPR_RE`, `WT_RE`, the flag patterns, `w:val="Hyperlink"`)
#   lives inside, so the same answers come back.
# * `_flags(rpr) | _valued(...)` written `^`. The two sets cannot
#   intersect: one holds bare names ("italic", "superscript"), the other
#   `f"{label} {value}"` pairs ("size 24"), and no name is ever a pair.
# * `stack.append([tables, 0, 0])` with 1 or -1 in the CELL slot. That
#   value is read only by a `<w:p>` reached before the table's first
#   `<w:tc>`, and a paragraph inside a table is inside a cell inside a
#   row — `<w:tr>` sets the cell counter to 0 on the way in.
# * `tag == "tr"`, `"tc"` and `"p"` as `<=`, `>=` and `is`.
#   `STRUCT_TAG_RE` admits four tags and the chain has already taken
#   "tbl"; over what is left — tr, tc, p — the ordering comparisons
#   agree with equality at every branch ("tc" < "tr", "p" < "tc"), and
#   the tags are module literals.
# * `stem == "document"` written `<=`. `TEXT_PART_RE` admits document,
#   footnotes, endnotes, header N and footer N; every one of those but
#   "document" itself sorts after it.
# * `score = 0.0` written `-1.0` in `pair_parts`. A part scoring 0.0
#   becomes `best` under the lower start where it did not before, and
#   is then refused by `score >= 0.6` just the same.
# * `result_at = start + sep.end()` written `|` — OVERTURNED 2026-09-16.
#   Kept here because the correction is worth more than the argument
#   was. It ran: `a | b` is never below `a` and never above `a + b`, so
#   the mutant's region begins between the field's own start and the end
#   of its separator, a span holding `fldChar` and `instrText` and no
#   `<w:t>` at all, and `_mask_text` masks the FIRST `<w:t>` in the
#   region it is given — the cached result either way. Its own note then
#   asked the next reader to check what that excluded: a field whose
#   INSTRUCTION half carries a `<w:t>`, which `crossrefs.dead_links`
#   records. It occurs. Measured, with a 103-character lead the two
#   spellings differ — the mutant masks the leftover text and blanks the
#   cached page number — so this was never an equivalence. It is killed
#   now by
#   test_the_mask_lands_on_the_RESULT_when_the_instruction_holds_text_too,
#   and the lesson is the one the 2026-08-20 note already gave: an
#   argument about the DOCUMENT rather than the code is a guess until
#   someone builds the document it excludes.
# * the four remaining mutants on `result_at < regions[-1][1]` — `<=`,
#   `==`, `is`, and `regions[not 1]` — GONE 2026-09-16, with the line
#   itself. The argument ran that regions are masked right to left, so a
#   nested one the guard lets through is masked first and then covered
#   entirely by the outer one, and that the guard therefore buys the
#   work and not the output. Backlog S1 made it false: a field in the
#   INSTRUCTION half is covered by no parent, so it claims a region of
#   its own deliberately, and `regions[-1]` is then no longer the
#   rightmost — hence `any(s <= result_at < e for s, e, _ in regions)`
#   and `sorted(regions, reverse=True)`. The six claims keyed on the old
#   line were deleted from `tools/equivalents.toml` rather than
#   reworded: a claim whose argument died is not a claim that needs new
#   wording. Nothing replaces them here — respelling the new guard needs
#   arguing from scratch against the new code.


# _compare_render measured 1.4 % (3/207) on the same day, and all three
# are argued:
#
# * `s["type"] == "MOVE"` written `is`. The types are literals written
#   in `_compare_diff` and read here — "MOVE", "DELETE", "INSERT",
#   "PART REMOVED" — and an all-caps identifier-shaped literal is one
#   object across the modules of one interpreter.
# * `h["n"] > 1` and `c["n"] > 1`, for the " xN" suffix, written
#   `!= 1`. `n` is a Counter value that reached the report, and
#   `_compare_diff` deletes the zero counts Counter arithmetic leaves
#   behind before it builds one — so the two can only disagree on a
#   count no producer emits.


# ------------------------------------------------------------- MEDIA
#
# The layer that did not exist until 2026-08-24, while the STRUCTURE
# layer's header claimed its ground: "paragraph insert / delete / move,
# part added / removed". A figure replaced with a different chart,
# overwritten with a 48-byte stub, or deleted outright all reported
# `REAL change locations: 0` — found on HCW, whose entire deliverable
# that round was four replaced images.

PNG = (b"\x89PNG\r\n\x1a\n" + b"first image bytes" * 4)
PNG2 = (b"\x89PNG\r\n\x1a\n" + b"a completely different chart" * 3)

_DRAWING = (
    '<w:p><w:r><w:drawing><wp:inline><a:graphic><a:graphicData>'
    '<pic:pic><pic:blipFill><a:blip r:embed="rId7"/></pic:blipFill>'
    '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>'
    "</w:r></w:p>")
_RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.'
         'openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId7" Type="http://schemas.openxmlformats.org/'
         'officeDocument/2006/relationships/image" '
         'Target="media/image1.png"/></Relationships>')


def _with_media(image=PNG, caption="Figure 8.a. Mortality and LFP"):
    parts = make_parts(_DRAWING + para(run(caption)))
    parts["word/media/image1.png"] = image
    parts["word/_rels/document.xml.rels"] = _RELS.encode("utf-8")
    return parts


def _media_report(a_parts, b_parts):
    """NOT `_report` — this file already has one, and shadowing it at
    module level broke four move tests defined a thousand lines above."""
    from docxkit.compare import compare_docs, load_parts
    return compare_docs(load_parts(a_parts), load_parts(b_parts))


def test_a_figure_REPLACED_with_a_different_one_is_reported():
    """The HCW case, exactly: image1's bytes swapped for another
    chart's. Every other layer is silent — no character moved."""
    report = _media_report(_with_media(PNG), _with_media(PNG2))

    (entry,) = report["media"]
    assert entry["type"] == "MEDIA CHANGED"
    assert entry["part"] == "word/media/image1.png"
    assert (entry["from"], entry["to"]) == (len(PNG), len(PNG2))
    assert not report["text"] and not report["structure"], \
        "no text moved — this layer is the only one that can see it"


def test_a_figure_CORRUPTED_to_a_stub_is_reported():
    report = _media_report(_with_media(PNG),
                           _with_media(b"not an image at all"))

    (entry,) = report["media"]
    assert entry["type"] == "MEDIA CHANGED" and entry["to"] == 19


def test_a_figure_DELETED_from_the_package_is_reported():
    before = _with_media()
    after = _with_media()
    del after["word/media/image1.png"]

    (entry,) = _media_report(before, after)["media"]

    assert entry["type"] == "MEDIA REMOVED"
    assert entry["part"] == "word/media/image1.png"


def test_a_figure_ADDED_is_reported():
    before = _with_media()
    del before["word/media/image1.png"]

    (entry,) = _media_report(before, _with_media())["media"]

    assert entry["type"] == "MEDIA ADDED"


def test_an_UNCHANGED_figure_is_not_a_difference():
    """The everyday case: the gate has to stay quiet through every
    author round-trip or nobody reads it."""
    assert _media_report(_with_media(), _with_media())["media"] == []


def test_the_entry_NAMES_the_exhibit_not_just_the_part():
    """"word/media/image14.png" sends a reader to a folder; "Figure 8.a"
    sends them to the page. The caption comes from the same rels walk
    `crossrefs` does."""
    (entry,) = _media_report(_with_media(PNG), _with_media(PNG2))["media"]

    assert entry["label"].startswith("Figure 8.a")


def test_a_changed_figure_FAILS_expect_clean():
    """The whole point: this is a gate, not a note. `--expect-clean` on
    a build whose figure was replaced used to print OK."""
    report = _media_report(_with_media(PNG), _with_media(PNG2))

    code, out = _out(report, expect_clean=True)

    assert code == 1
    assert "MEDIA CHANGED" in out


def test_the_THUMBNAIL_is_not_compared():
    """Word regenerates docProps/thumbnail from whatever the first page
    renders to, so it differs after an open-and-save with nothing
    edited. A difference on every round-trip is one nobody reads."""
    before, after = _with_media(), _with_media()
    before["docProps/thumbnail.jpeg"] = b"old render"
    after["docProps/thumbnail.jpeg"] = b"a different render entirely"

    assert _media_report(before, after)["media"] == []


def test_an_EMBEDDED_object_counts_as_media():
    """An embedded workbook behind a chart is content a reader can
    open."""
    before, after = _with_media(), _with_media()
    before["word/embeddings/Microsoft_Excel_Sheet1.xlsx"] = b"workbook one"
    after["word/embeddings/Microsoft_Excel_Sheet1.xlsx"] = b"workbook two!"

    (entry,) = _media_report(before, after)["media"]

    assert entry["part"].startswith("word/embeddings/")


def test_two_figures_that_SWAP_contents_are_two_changes():
    """Why the pairing is by NAME. Pairing by digest would absorb a
    renumbering — and would report this, where the pictures genuinely
    trade places, as nothing at all."""
    before, after = _with_media(), _with_media()
    before["word/media/image2.png"] = PNG2
    after["word/media/image1.png"] = PNG2
    after["word/media/image2.png"] = PNG

    changes = _media_report(before, after)["media"]

    assert len(changes) == 2, changes
    assert {c["type"] for c in changes} == {"MEDIA CHANGED"}

# --- the half of a spilled field that says WHERE ----------------------

def _seq_caption(text: str) -> str:
    return ("<w:p>" + run(text)
            + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            + "<w:r><w:instrText> SEQ Figure </w:instrText></w:r>"
            + "</w:p>")


_SPILL = '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'


def test_a_field_spilling_into_an_EMPTY_paragraph_can_be_located():
    """A field that spills does so into the paragraph next door, and the
    paragraph next door is a spacer or a section break with no text in
    it — so the half of the defect that says WHERE printed `in ''`, and
    locating it took a script counting fldCharType per paragraph."""
    from docxkit._compare_diff import integrity

    xml = document(_seq_caption("Figure 3. Mortality and LFP") + _SPILL)

    opened, orphan = integrity(xml, "BUILT", set())

    assert "(+1)" in opened and "Figure 3" in opened
    assert "(-1)" in orphan
    assert "empty paragraph 2" in orphan, orphan
    assert "Figure 3" in orphan, "and which paragraph it belongs to"


def test_a_paragraph_WITH_text_is_still_named_by_its_text():
    """The ordinary case is unchanged: a reader who can be given the
    words should be."""
    from docxkit._compare_diff import integrity

    xml = document("<w:p>" + run("A sentence that spills.")
                   + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                   + "</w:p>")

    (issue,) = integrity(xml, "BUILT", set())

    assert "'A sentence that spills.'" in issue
    assert "empty paragraph" not in issue


def test_a_field_spilling_with_NO_paragraph_before_it_still_says_where():
    """The other branch, and the one the first test never reached.

    A field can open in the very FIRST paragraph, leaving nothing to
    name the orphan half by — and that branch had no test at all, which
    a cosmic-ray sweep of this module said out loud: five arithmetic
    mutants on its paragraph number, all alive (2026-08-24).
    """
    from docxkit._compare_diff import integrity

    xml = document('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r></w:p>'
                   + _SPILL)

    opened, orphan = integrity(xml, "BUILT", set())

    assert "(+1)" in opened
    assert "the empty paragraph 1" in opened, opened
    assert "empty paragraph 2" in orphan, orphan
    assert "after" not in orphan, "there is nothing before it to name"


def test_an_ADDED_or_REMOVED_figure_is_named_by_its_exhibit_too():
    """`known = after or before`. Mutated to `and`, a figure that was
    ADDED or REMOVED loses its caption and the entry falls back to
    "word/media/image21.png" — which is the folder-not-the-page problem
    the label exists to solve, surviving in the two cases where the
    reader has least other context."""
    before = _with_media()
    after = _with_media()
    del after["word/media/image1.png"]

    (removed,) = _media_report(before, after)["media"]
    (added,) = _media_report(after, before)["media"]

    assert removed["type"] == "MEDIA REMOVED"
    assert removed["label"].startswith("Figure 8.a"), removed
    assert added["type"] == "MEDIA ADDED"
    assert added["label"].startswith("Figure 8.a"), added


def test_the_size_of_what_is_NOT_there_is_zero():
    """A removal reports the size it had and 0 for what it became; an
    addition the reverse. Nothing pinned either, so a mutant writing -1
    into a report survived — invisible on the page, because the renderer
    prints max(from, to), and nonsense to anything reading the JSON."""
    before = _with_media()
    after = _with_media()
    del after["word/media/image1.png"]

    (removed,) = _media_report(before, after)["media"]
    (added,) = _media_report(after, before)["media"]

    assert (removed["from"], removed["to"]) == (len(PNG), 0)
    assert (added["from"], added["to"]) == (0, len(PNG))


def test_a_LONG_repetitive_document_still_reports_the_ONE_paragraph_added(
        tmp_path):
    """`autojunk=False` on the paragraph alignment, which nothing pinned.

    difflib calls an element junk when it appears in more than 1% of the
    sequence and the sequence is 200 or longer — and then declines to
    match it. A regression table is exactly that: hundreds of paragraphs
    drawn from a vocabulary of "Yes", "-", "(0.00)", "***". Measured
    with autojunk left on, one added cell in a 210-paragraph table comes
    back as 211 paragraphs replaced — every cell from the insertion to
    the end of the document — which is the report-a-human-cannot-audit
    failure `word_diff` documents, one level up and unpinned until a
    cosmic-ray sweep found the mutant alive (2026-08-24).
    """
    cells = ["Yes", "No", "-", "0.00", "0.01", "(0.00)", "***", "n.a."]
    rows = [para(run(cells[i % len(cells)])) for i in range(210)]
    a_body = "".join(rows)
    b_body = "".join(rows[:105]) + para(run("0.42")) + "".join(rows[105:])

    report = compare(*docs(tmp_path, a_body, b_body))

    assert report["text"] == [], "not one cell of prose changed"
    assert len(report["structure"]) == 1, report["structure"]
    assert "0.42" in str(report["structure"][0])


def test_the_field_report_COUNTS_paragraphs_and_truncates_the_one_before():
    """Both halves of `where`, and neither was observable before.

    The paragraph number was only ever asserted at paragraph 2, where
    `i + 1` and `i * 2` agree, so the arithmetic was free to be anything
    else. The 40-character truncation was only ever asserted on a
    27-character caption, where every truncation width agrees. Two
    sweeps' worth of survivors sat in those two coincidences.
    """
    from docxkit._compare_diff import integrity

    lead = "Figure 3. Mortality and labour-force participation in ECA"
    assert len(lead) > 40, "the point of the case is to be truncated"
    xml = document(
        para(run(lead) + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>')
        + para(run(" "))          # a spacer does not become the `after`
        + _SPILL)

    opened, orphan = integrity(xml, "BUILT", set())

    assert f"{lead[:40]!r}" in opened, opened
    assert "the empty paragraph 3" in orphan, orphan
    assert f"after {lead[:40]!r}" in orphan, orphan


def test_a_stripped_field_shows_the_START_of_the_paragraph_that_held_it(
        tmp_path):
    """The context is a reader's only handle on WHERE the machinery went,
    and every case that reached it used a paragraph shorter than the
    truncation — under which the width is unobservable and the mutants
    that moved it survived."""
    from docxkit.citations import hyperlink_field

    lead = ("The within-occupation component of the change in age-friendly "
            "employment accounts for most of it, see ")
    a, b = docs(tmp_path,
                para(run(lead) + hyperlink_field("ref_x", "Table 4")
                     + run(" for detail.")),
                para(run(lead + "Table 4 for more detail.")))

    (entry,) = compare(a, b)["stripped_fields"]

    assert entry["context"] == lead[:60]
    assert len(entry["context"]) == 60


# --- the on/off flags resolve through the STYLES, like size and colour --
#
# Word deletes a direct property equal to the inherited one. `_VALUED`
# has always been resolved through `styles.Cascade` for that reason; the
# toggles were read off the run, so they cried wolf. Measured 2026-08-29
# on Life_Expectancy, comparing a clean generation against the same
# manuscript after the author's Accept All:
#
#   'Demographic Research': ['italic', 'size 24'] -> ['size 24']
#
# and three more like it. Every one is false: those runs carry
# `<w:rStyle w:val="Emphasis"/>`, the style defines `<w:i/>`, and the
# names are still italic on the page. It fires on an ACCEPTANCE, which
# is the one comparison a paper runs when Accept All really can strip
# run properties — four false losses there teach the reader to skim past
# the real one.

EMPHASIS_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
    'wordprocessingml/2006/main">'
    '<w:style w:type="character" w:styleId="Emphasis">'
    "<w:rPr><w:i/><w:iCs/></w:rPr></w:style>"
    '<w:style w:type="character" w:styleId="Strong">'
    "<w:rPr><w:b/></w:rPr></w:style>"
    "</w:styles>")


def _emph_run(rpr: str) -> str:
    return (f"<w:p><w:r><w:rPr>{rpr}</w:rPr>"
            "<w:t>Demographic Research</w:t></w:r></w:p>")


def test_a_REDUNDANT_direct_italic_dropped_by_Word_is_not_a_loss(tmp_path):
    """The four journal names. Before: the run states `<w:i/>` AND names
    the Emphasis style. After Word's save: the style alone, because the
    direct one was redundant. Same italic on the page, and the layer
    reported it as lost."""
    before = _emph_run('<w:rStyle w:val="Emphasis"/><w:i/>')
    after = _emph_run('<w:rStyle w:val="Emphasis"/>')
    styles = {"word/styles.xml": EMPHASIS_STYLES}

    report = compare(*docs(tmp_path, before, after,
                           extra=(styles, styles)))

    assert report["format"] == [], report["format"]
    assert render(report, expect_clean=True) == 0


def test_a_REAL_loss_of_italic_is_still_reported(tmp_path):
    """The signal the change must not cost: the style goes too."""
    before = _emph_run('<w:rStyle w:val="Emphasis"/>')
    after = _emph_run("")
    styles = {"word/styles.xml": EMPHASIS_STYLES}

    report = compare(*docs(tmp_path, before, after,
                           extra=(styles, styles)))

    assert any("italic" in str(e) for e in report["format"]), report["format"]


def test_a_run_that_turns_a_STYLED_italic_off_reads_as_off(tmp_path):
    """`<w:i w:val="0"/>` against a style that sets `<w:i/>`. The direct
    value wins, so this run is NOT italic — and a comparison against a
    plain run must see no difference."""
    off = _emph_run('<w:rStyle w:val="Emphasis"/><w:i w:val="0"/>')
    plain = _emph_run("")
    styles = {"word/styles.xml": EMPHASIS_STYLES}

    report = compare(*docs(tmp_path, off, plain, extra=(styles, styles)))

    assert not any("italic" in str(e) for e in report["format"]), \
        report["format"]


def test_bold_resolves_through_a_style_too(tmp_path):
    """All four toggles go through the cascade, not italic alone — the
    other three had no test when italic got one."""
    before = _emph_run('<w:rStyle w:val="Strong"/><w:b/>')
    after = _emph_run('<w:rStyle w:val="Strong"/>')
    styles = {"word/styles.xml": EMPHASIS_STYLES}

    report = compare(*docs(tmp_path, before, after, extra=(styles, styles)))

    assert report["format"] == [], report["format"]


def test_with_NO_styles_part_the_flags_are_read_off_the_run(tmp_path):
    """The honest answer when there is nothing to resolve with, and the
    same one `_valued` gives. A package with no styles.xml must not
    start reporting every styled run as unformatted."""
    before = _emph_run("<w:i/>")
    after = _emph_run("")

    report = compare(*docs(tmp_path, before, after))

    assert any("italic" in str(e) for e in report["format"]), report["format"]


def test_render_survives_the_cp1252_console_a_LIBRARY_caller_gets(tmp_path):
    """`compare.render` is public and `docxkit.compare` is imported
    directly by paper scripts, which reach a Windows console with no
    reconfigure — `compare.main` and `cli.main` were the only two places
    that made stdout safe, and neither is on this path.

    Every line render prints quotes the manuscript, so one paragraph
    carrying a typographic minus (U+2212, and NOT in cp1252, unlike the
    em dash) ended the report with a UnicodeEncodeError partway through
    — after the header, before the layer a reader was waiting for.
    """
    minus = "−"
    a, b = docs(tmp_path,
                para(run("The coefficient is 0.15 in every specification.")),
                para(run(f"The coefficient is {minus}0.15 in every "
                         f"specification.")))
    report = compare(a, b)

    with cp1252_console() as printed:
        code = render(report, expect_clean=True)

    assert code == 1
    out = printed()
    assert minus in out, "the report stopped at the glyph it was reporting"
    assert "REAL change locations" in out, "it did not reach its own summary"


# --- the paragraph's EDGES ---------------------------------------------
#
# Aging_Well, 2026-09-11 (backlog S1): an author hand pass rewrote A.4's
# opening as ` The following parameter values…`, a leading space in the
# first w:t that Word prints as an INDENT. `--expect-clean` exited 0 on
# it with `TEXT (none)`: the matchers read stripped text, and the word
# tokeniser yields no token for a space in front of the first word. An
# interior double space already failed. The gap was at the edge.

def test_a_LEADING_space_is_a_TEXT_change_that_gates(tmp_path):
    edited = BASE.replace(run("The index rose to 0.35 in 2024."),
                          run(" The index rose to 0.35 in 2024.",
                              preserve=True))
    a, b = docs(tmp_path, BASE, edited)
    report = compare(a, b)

    assert [t["word_diff"] for t in report["text"]] == [
        ["EDGE leading: '' -> ' '"]]
    assert report["glyph"] == [], "an indent is not a glyph artifact"
    assert render(report, expect_clean=True) == 1
    assert "EDGE leading" in _rendered(report)


def test_a_TRAILING_space_is_reported_the_same_way(tmp_path):
    edited = BASE.replace(run("Conclusions are unchanged."),
                          run("Conclusions are unchanged. ", preserve=True))
    a, b = docs(tmp_path, BASE, edited)

    assert [t["word_diff"] for t in compare(a, b)["text"]] == [
        ["EDGE trailing: '' -> ' '"]]


def test_an_edge_that_moved_inside_a_REWRITE_is_named_beside_the_words(
        tmp_path):
    """A rewritten paragraph lands in a replace block, where the words
    are diffed; the edge goes on the same entry, so the one line a
    reader checks carries both."""
    edited = BASE.replace(run("The index rose to 0.35 in 2024."),
                          run(" The index rose to 0.37 in 2024.",
                              preserve=True))
    a, b = docs(tmp_path, BASE, edited)

    (entry,) = compare(a, b)["text"]
    assert entry["word_diff"] == ['"0.35" -> "0.37"',
                                  "EDGE leading: '' -> ' '"]


def test_a_BLANK_paragraph_gaining_a_space_is_not_a_change(tmp_path):
    """A lone space prints as an empty line either way, and Word puts
    one in and takes one out of spacer paragraphs as it pleases."""
    a, b = docs(tmp_path, BASE + para(),
                BASE + para(run(" ", preserve=True)))

    report = compare(a, b)

    assert report["text"] == [] and report["structure"] == [], report


# --- the whole sweep of 2026-09-15 ------------------------------------
#
# 15.2 % real survival (70/460), and half of it in `_media_labels` — the
# walk that gives a changed figure the caption a reader can find it by.
# It arrived on 2026-08-24 with the MEDIA layer above and was reached
# only through fixtures whose caption sits immediately under the
# drawing, where every spelling of its window agrees with every other.

_VERT_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
    'wordprocessingml/2006/main">'
    '<w:style w:type="character" w:styleId="Sup">'
    '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>'
    '<w:style w:type="character" w:styleId="Base">'
    '<w:rPr><w:vertAlign w:val="baseline"/></w:rPr></w:style>'
    "</w:styles>")


@pytest.mark.parametrize(("rpr", "flags"), [
    ('<w:vertAlign w:val="superscript"/>', {"superscript"}),
    ('<w:vertAlign w:val="subscript"/>', {"subscript"}),
    ('<w:rStyle w:val="Sup"/>', {"superscript"}),
    ('<w:vertAlign w:val="baseline"/>', set()),
    ('<w:rStyle w:val="Base"/>', set()),
])
def test_a_resolved_vertAlign_is_the_VALUE_unless_it_is_baseline(rpr, flags):
    """A vertical alignment is a VALUE, not a toggle, and `baseline` is
    the value that means "not raised at all". Reporting it as a flag
    makes the run that states the default differ from the run that
    inherits it — the crying wolf this whole layer resolves to avoid —
    and refusing every value at or below `baseline` throws away
    superscript and subscript with it, since both sort after it.

    Asked THROUGH a cascade, because that is the half nothing reached:
    the four vertAlign fixtures elsewhere in this file compare documents
    with no styles.xml, where `_flags` answers instead and this line
    never runs.
    """
    from docxkit._compare_read import _resolved_flags
    from docxkit.styles import Cascade

    assert _resolved_flags(Cascade(_VERT_STYLES), f"<w:rPr>{rpr}</w:rPr>",
                           None) == flags


def test_an_indent_AS_LONG_as_the_line_it_indents_is_still_an_EDGE(tmp_path):
    """`raw[:len(raw) - len(raw.lstrip())]`, the whitespace a paragraph
    opens with. A remainder IS that subtraction whenever the indent is
    shorter than what follows it, which is every fixture in the section
    above — one space in front of a sentence. Four spaces in front of
    two characters is where the two part company, and a short indented
    line is what a table cell or a hand-set label is.

    Under the other spelling the edge reads empty, the stripped texts
    are equal, and `--expect-clean` says the documents match.
    """
    a, b = docs(tmp_path, BASE + para(run("Hi")),
                BASE + para(run("    Hi", preserve=True)))

    report = compare(a, b)

    assert [t["word_diff"] for t in report["text"]] == [
        ["EDGE leading: '' -> '    '"]]
    assert render(report, expect_clean=True) == 1


def test_the_mask_lands_on_the_RESULT_when_the_instruction_holds_text_too():
    """A `w:t` between a field's begin and its separate is not
    hypothetical: `crossrefs.dead_links` records the shape — an edit
    across a link leaves the replacement text in the run that held the
    start of the match. The argued list above says `start | sep.end()`
    cannot be told from `start + sep.end()` because the span OR can land
    in holds fldChar and instrText and no text, and asks the next reader
    to check what that excludes. This is that span with text in it, and
    the two spellings differ.

    The lead's LENGTH is load-bearing, which is why it is asserted: an
    OR equals a sum only while the two offsets share no bit, so a
    fixture has to put one there. At this length the other spelling
    masks the leftover text and BLANKS the cached page number — after
    which two copies of the document agree about a page number by
    accident, and a paragraph that really lost a word reports as a
    masked field.
    """
    from docxkit._compare_read import mask_volatile_fields

    lead = ("An edit across this field left the replacement text inside "
            "the instruction half, where Word ignores it.")
    assert len(lead) == 103, "the offsets are what tell the two apart"
    xml = ("<w:p>" + run(lead)
           + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
           + run("left over")
           + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           + run("7")
           + '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>"), out


#: Lead lengths, because every arithmetic bug this function has had was
#: offset arithmetic and a single fixture decides those by luck — the
#: argument overturned above survived on exactly that.
_LEADS = ["", "A", "ABC", "A longer opening line. ",
          "Prose of some other length entirely, so the offsets are "
          "nothing like round. "]


def _nested_in_instruction(outer: str, inner: str, inner_result: str,
                           outer_result: str) -> str:
    """A field whose INSTRUCTION half carries a field of its own.

    `_wrapping` above is the OTHER nesting — a field inside the outer's
    cached result — and until 2026-09-16 it was the only one any fixture
    here held. Word writes this one too: what a cross-reference resolves
    can itself be a field, and `{ PAGEREF { REF _Toc1 } }` puts the
    INNER field's separator in front of the outer's.
    """
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> {outer} '
            "</w:instrText></w:r>"
            + field(inner, inner_result)
            + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run(outer_result)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


@pytest.mark.parametrize("lead", _LEADS)
def test_the_mask_opens_on_THIS_field_s_separator_not_a_nested_one(lead):
    """Backlog S1, 2026-09-16. `SEPARATE_RE.search(body)` took the FIRST
    separator in the span, and a field nested in the INSTRUCTION half
    puts its own there first, so the mask opened on the INNER field's
    cached result. Measured on `{ PAGEREF { REF _Toc1 } }`:

        Table 3  ->  «F:PAGEREF»   the reader's cross-reference, gone
        17       ->  <w:t></w:t>   the page number, blanked, not masked

    Both of those are wrong in the same direction. `compare` masks both
    sides alike, so an edit turning that "Table 3" into "Table 5" left
    two identical strings behind and reached no layer at all — which
    `test_an_edit_inside_a_nested_cross_reference_is_SEEN` below states
    as the loss it is.

    One equality, like `test_the_mask_replaces_the_cached_RESULT_and_
    nothing_else`: "the document with the OUTER field's cached value
    replaced" says both halves at once — what was masked, and what was
    left alone.
    """
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "")
           + _nested_in_instruction("PAGEREF _Toc1", "REF _Toc1",
                                    "Table 3", "17") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>17</w:t>", "<w:t>«F:PAGEREF»</w:t>"), out
    assert "<w:t>Table 3</w:t>" in out, "the cross-reference a reader sees"


@pytest.mark.parametrize("lead", _LEADS)
def test_a_VOLATILE_field_in_the_instruction_half_is_masked_as_itself(lead):
    """The same nesting with a volatile field inside, which is what the
    coverage guard decides.

    The inner field's cached page number sits BEFORE the region its
    parent claims, so the parent does not cover it and it claims one of
    its own. A guard that asks only the LAST claimed region — as this
    one did until 2026-09-16 — leaves that `7` in the document:
    measured, that spelling returns ['7', '«F:PAGEREF»'] where this
    asserts ['«F:PAGE»', '«F:PAGEREF»'].

    What it does NOT pin is the ORDER the two regions are applied in.
    `test_the_regions_are_masked_RIGHT_TO_LEFT` below does, and says why
    a fixture this size cannot.

    It has to be masked rather than merely left alone: a `w:t` in an
    instruction half is text this comparison reads (see
    `test_the_mask_lands_on_the_RESULT_when_the_instruction_holds_text_
    too`), so an unmasked page number there is a difference on every
    pair of copies — the crying wolf this whole layer exists to stop.
    """
    from lxml import etree

    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "")
           + _nested_in_instruction("PAGEREF _Toc1", "PAGE", "7", "17")
           + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace(
        "<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>").replace(
        "<w:t>17</w:t>", "<w:t>«F:PAGEREF»</w:t>"), out
    assert re.findall(r"«F:\w+»", out) == ["«F:PAGE»", "«F:PAGEREF»"], out
    etree.fromstring(('<w:p xmlns:w="http://schemas.openxmlformats.org/'
                      'wordprocessingml/2006/main">'
                      + out[len("<w:p>"):]).encode())


@pytest.mark.parametrize("lead", _LEADS)
def test_the_regions_are_masked_RIGHT_TO_LEFT(lead):
    r"""`sorted(regions, reverse=True)`, and why `reversed(regions)` is
    not the same walk once a field nests in an INSTRUCTION half.

    Regions used to be appended in document order, so reversing the list
    took them right to left and every stored offset stayed valid while
    the ones behind it were rewritten. An instruction-half region breaks
    that: it is appended AFTER its parent's and lies BEFORE it, so
    append order rewrites the earlier one first and the parent's offsets
    go stale by whatever length that rewrite changed.

    The SIZE of that shift is the whole question, which is why this
    fixture's nested result is long. Masking `7` as `«F:PAGE»` shifts by
    seven characters, and seven characters before a region's start is
    still inside `separate"/>` — tag text, which `_mask_text` leaves
    alone and the concatenation puts back unchanged. That is the same
    accident that makes the `regions[0]` mutant equivalent, and it means
    a short fixture decides this by luck. A 35-character cached date
    shifts 27 the other way, which clears `</w:r><w:r><w:t>` and the
    page number behind it: the stale slice then holds no `<w:t>` at all
    and the outer field's cached result is left in the document.
    Measured — append order returns ['«F:DATE»', '17'] here.
    """
    from docxkit._compare_read import mask_volatile_fields

    stamp = "Tuesday, 15 September 2026 at 22:01"
    xml = ("<w:p>" + (run(lead) if lead else "")
           + _nested_in_instruction(
               "PAGEREF _Toc1", 'DATE \\@ "dddd, d MMMM yyyy"', stamp, "17")
           + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace(
        f"<w:t>{stamp}</w:t>", "<w:t>«F:DATE»</w:t>").replace(
        "<w:t>17</w:t>", "<w:t>«F:PAGEREF»</w:t>"), out


@pytest.mark.parametrize("lead", _LEADS)
def test_a_NON_volatile_field_wrapping_another_is_left_untouched(lead):
    """The control, and what pins the two tests above to the NESTING
    rather than to masking in general: the same shape with a TOC outside
    instead of a PAGEREF. Nothing in it is volatile, and it comes back
    byte for byte — before the fix as well as after."""
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "")
           + _nested_in_instruction('TOC \\o "1-3"', "REF _Toc1",
                                    "Table 3", "17") + "</w:p>")

    assert mask_volatile_fields(xml) == xml


@pytest.mark.parametrize("lead", _LEADS)
def test_a_volatile_field_under_a_NON_volatile_parent_is_still_masked(lead):
    """The fourth corner of the same square: a parent that claims no
    region of its own must not shield the volatile field in its
    instruction half either. A TOC is exactly where Word keeps page
    numbers it recalculates, so this is the shape that would fill a
    redline with page numbers nobody typed."""
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "")
           + _nested_in_instruction('TOC \\o "1-3"', "PAGE", "7", "17")
           + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>"), out


def test_an_edit_inside_a_nested_cross_reference_is_SEEN(tmp_path):
    """What the S1 above cost, stated as the gate rather than as the
    masked XML: two documents differing in one cross-reference's visible
    text and in nothing else.

    Masking runs on both sides alike, so a mask that lands on the wrong
    text does not report the difference — it ERASES it. `--expect-clean`
    exited 0 over this pair, which is a false negative in the one gate
    whose job is to certify that no edit was lost."""
    nested = _nested_in_instruction("PAGEREF _Toc1", "REF _Toc1",
                                    "Table 3", "17")
    a, b = docs(tmp_path, BASE + para(nested),
                BASE + para(nested.replace(">Table 3<", ">Table 5<")))

    report = compare(a, b)

    assert report["text"], "the edit reached no layer"
    assert render(report, expect_clean=True) == 1


# --- what the _compare_read sweep of 2026-09-17 found ---------------------
#
# Twelve survivors, all in the code dc8bdc8 wrote. Four respell the
# coverage guard so that a field nested in a RESULT half is never covered
# (`result_at == e`, `result_at is e`, `s == result_at`, `s is result_at`),
# and every fixture above that nests there gives the inner field a
# one-character page number, whose seven-character growth leaves the
# parent's stale end inside tag text. Two more need a RUN that holds more
# than one `fldChar`, which no fixture here had: CT_R is a sequence of any
# number of run-content elements, and writers other than Word use that.
# The other six are argued equivalent.

#: A cached result long enough that masking it SHRINKS the text by more
#: than the markup between a region's end and the text after the field —
#: the distance a stale end then overshoots by. It was a 35-character
#: date, which carried 27 characters past a region ending after the
#: `</w:r>`; the region ends at the `end` MARK now, 38 characters
#: earlier, and the fixture has to reach that much further.
_CACHED = ("D:\\OneDrive\\Papers\\_Submitted\\Life_Expectancy\\"
           "LE13_tracked_changes_2026-09-15.docx")


def _covered(tail: str) -> str:
    """A FILENAME nested in a PAGEREF's RESULT half, then prose."""
    return (_wrapping("PAGEREF _Toc1", field("FILENAME \\p", _CACHED))
            + run(tail))


@pytest.mark.parametrize("lead", _LEADS)
def test_a_field_in_a_claimed_region_claims_no_region_of_its_own(lead):
    """`any(s <= result_at < e ...)` respelled as `s <= result_at == e`,
    `result_at is e`, `s == result_at` or `s is result_at`: each is false
    for a field nested in its parent's RESULT, so the nested field claims
    a region too.

    That region lies inside the parent's and is applied first, and the
    parent's stored end goes stale by however much the inner rewrite
    changed the length. With a one-character page number the end lands
    early, in tag text, and nothing shows. With this cached path it
    lands LATE — past the `end` mark, past the `</w:r>` after it, and
    over the whole ` (draft)` run — so that run falls inside the
    parent's mask and is blanked. The `reach` assertion is what keeps
    the fixture able to see that, and it is not decoration: the same
    mutants stopped being killed the moment the region stopped ending
    after the `</w:r>`, and only the fixture had to change.
    """
    from docxkit._compare_read import mask_volatile_fields

    reach = (len('<w:fldChar w:fldCharType="end"/></w:r>')
             + len(run(" (draft)")) - len("</w:r>"))
    assert len(_CACHED) - len("«F:FILENAME»") >= reach
    xml = ("<w:p>" + (run(lead) if lead else "") + _covered(" (draft)")
           + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace(f"<w:t>{_CACHED}</w:t>",
                              "<w:t>«F:PAGEREF»</w:t>"), out


def test_an_edit_just_after_a_field_that_wraps_another_is_SEEN(tmp_path):
    """The test above as the gate sees it. The overshooting mask blanks
    the prose after the field on BOTH sides, so "(draft)" against
    "(final)" leaves two identical strings and `--expect-clean` passes a
    real edit."""
    a, b = docs(tmp_path, BASE + para(_covered(" (draft)")),
                BASE + para(_covered(" (final)")))

    report = compare(a, b)

    assert report["text"], "the edit reached no layer"
    assert render(report, expect_clean=True) == 1


def _sharing_a_run(outer: str, shown: str, inner: str, result: str, *,
                   whole: bool = False) -> str:
    """A field nested in `outer`'s RESULT, its `begin` in the run that
    holds the outer `separate` and the text `shown` after it — and, with
    `whole`, the outer `begin` and instruction as well.

    Word gives every `fldChar` a run of its own; the schema does not ask
    for that, and a generated document puts them together. This said
    "`field_spans` opens the inner span at that run's `<w:r>`, so the
    walk in `_own_separator` meets the OUTER field's separator before
    this field's begin" — true until the same day, when that walk was
    found to miscount on exactly this shape and replaced by
    `_field_marks`, which pairs the marks themselves. The tests on this
    fixture now pin that the answers they assert did not move with it.
    """
    begin = '<w:fldChar w:fldCharType="begin"/>'
    instr = f'<w:instrText xml:space="preserve"> {outer} </w:instrText>'
    opening = (f"<w:r>{begin}{instr}" if whole
               else f"<w:r>{begin}</w:r><w:r>{instr}</w:r><w:r>")
    return (opening
            + '<w:fldChar w:fldCharType="separate"/>'
            f'<w:t xml:space="preserve">{shown}</w:t>'
            + begin + "</w:r>"
            f'<w:r><w:instrText xml:space="preserve"> {inner} '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run(result)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


@pytest.mark.parametrize("lead", _LEADS)
def test_a_separator_ahead_of_the_field_s_begin_is_not_its_own(lead):
    """`kind == "separate" and depth == 1` respelled `depth <= 1`.

    The walk starts at the `<w:r>` of the run holding the begin, so a
    parent's separator in that run is met at depth 0, before the begin.
    `== 1` passes over it; `<= 1` returns it, and the PAGEREF's mask then
    opens at the TOC's separator — the entry text a reader sees becomes
    `«F:PAGEREF»` and the page number is blanked. The TOC is not volatile
    and claims no region, so nothing else would have masked that text.

    The line that mutant respelled is gone: `_field_marks` gives a
    `separate` to the innermost field still open, and the TOC's is met
    while the TOC is. What this pins now is that answer.
    """
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "")
           + _sharing_a_run('TOC \\o "1-3"', "Introduction, page ",
                            "PAGEREF _Toc1", "17") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>17</w:t>", "<w:t>«F:PAGEREF»</w:t>"), out


def test_an_edit_in_the_run_a_nested_field_begins_in_is_SEEN(tmp_path):
    """The `depth <= 1` spelling at the gate: the entry text masked on
    both sides, and a renamed section passes `--expect-clean`."""
    def entry(title: str) -> str:
        return _sharing_a_run('TOC \\o "1-3"', f"{title}, page ",
                              "PAGEREF _Toc1", "17")

    a, b = docs(tmp_path, BASE + para(entry("Introduction")),
                BASE + para(entry("Background")))

    report = compare(a, b)

    assert report["text"], "the edit reached no layer"
    assert render(report, expect_clean=True) == 1


@pytest.mark.parametrize("lead", _LEADS)
def test_a_field_whose_walk_lands_on_its_PARENT_s_separator_is_covered(lead):
    """`s <= result_at < e` respelled `s < result_at < e`.

    The PAGEREF's begin, instruction and separator all share the run the
    nested PAGE begins in, so the PAGE's walk meets the parent's begin
    first and returns the PARENT's separator at depth 1. Its `result_at`
    is then exactly the start of the region the parent claimed, and `<=`
    calls it covered — the right answer, since the page number is in the
    parent's result. `<` lets it claim that start a second time, and the
    second mask runs on offsets the first has moved.

    Both regions carry the same keyword (the span's first instruction is
    the parent's), so the damage shows only through the stale end, and
    the length of the parent's cached text is what decides it: masking
    it shrinks the text by far more than the 43-character end run and
    the ` (draft)` run after it, so the second mask reaches that prose
    and blanks it — an edit there would reach no layer. With a run per
    `fldChar` the inner field finds its own separator strictly inside
    the region and the two spellings agree.

    Withdrawn in part the same day. The walk that returned the PARENT's
    separator was the defect `test_a_field_whose_BEGIN_shares_its_parent_
    s_run_is_masked_as_itself` describes, and with the marks paired by
    `_field_marks` every field finds its own separator on this fixture
    too — so `<` and `<=` agree here now and the mutant is argued
    equivalent. The output asserted is still the right one, and stays.
    """
    from docxkit._compare_read import mask_volatile_fields

    shown = ("Why the index moved in 2024, and what it measures across "
             "the regions and the years, p. ")
    end_run = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    overshoot = len(shown) + len("7") - len("«F:PAGEREF»")
    assert overshoot >= len(end_run) + len(run(" (draft)")) - len("</w:r>")
    xml = ("<w:p>" + (run(lead) if lead else "")
           + _sharing_a_run("PAGEREF _Toc1", shown, "PAGE", "7", whole=True)
           + run(" (draft)") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace(
        f'<w:t xml:space="preserve">{shown}</w:t>',
        '<w:t xml:space="preserve">«F:PAGEREF»</w:t>').replace(
        "<w:t>7</w:t>", "<w:t></w:t>"), out


# --- a field is its fldChars, not their runs (2026-09-17) -----------------
#
# The same sweep's two defects. `mask_volatile_fields` took its fields from
# `field_spans`, whose spans have RUN boundaries — right for a caller that
# splices whole runs, wrong for one that asks where a cached result begins
# and ends. A run holding more than one run-content element moved both
# edges: the mask ran on to the `</w:r>` after the `end`, over prose, and
# the separator walk started counting at the `<w:r>` before the `begin`,
# over somebody else's `fldChar`.

_END_RUN_BEGIN = ('<w:r><w:fldChar w:fldCharType="end"/>'
                  '<w:fldChar w:fldCharType="begin"/></w:r>')


def _page_then_prose(page: str, tail: str) -> str:
    """A PAGE field whose `end` shares its run with the prose after it."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run(page)
            + '<w:r><w:fldChar w:fldCharType="end"/>'
            f'<w:t xml:space="preserve">{tail}</w:t></w:r>')


@pytest.mark.parametrize("lead", _LEADS)
def test_prose_after_a_field_s_END_in_the_same_run_is_not_masked(lead):
    """The mask ended at the `</w:r>` closing the run that holds `end`, so
    text after the `end` in that run was inside it and came back blank.
    It is not the field's cached result: it is the sentence the page
    number sits in."""
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "")
           + _page_then_prose("7", " of the 2024 report.") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>"), out


def test_an_edit_after_a_field_s_END_in_the_same_run_is_SEEN(tmp_path):
    """The gate, and why the defect above is an S1: both sides were
    masked alike, so "2024" against "2019" left two blank strings and
    `--expect-clean` exited 0 over a real edit."""
    a, b = docs(tmp_path,
                BASE + para(_page_then_prose("7", " of the 2024 report.")),
                BASE + para(_page_then_prose("7", " of the 2019 report.")))

    report = compare(a, b)

    assert report["text"], "the edit reached no layer"
    assert render(report, expect_clean=True) == 1


def _ref_then_page(page: str) -> str:
    """A REF, then a PAGE whose `begin` shares a run with the REF's `end`."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> REF _Ref1 </w:instrText>'
            "</w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run("Table 3") + _END_RUN_BEGIN
            + '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText>'
            "</w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run(page)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


@pytest.mark.parametrize("lead", _LEADS)
def test_a_field_whose_BEGIN_shares_a_run_with_an_earlier_END_is_masked(lead):
    """The separator walk counted depth from the `<w:r>` of the run holding
    the `begin`. The REF's `end` in that run took it to -1, the PAGE's
    `begin` back to 0, and the PAGE's own separator sat at depth 0, where
    `depth == 1` never found it: the page number was left in the text.
    A regression from dc8bdc8 — the `SEPARATE_RE.search` it replaced
    found the only separator in the span and masked this correctly."""
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "") + _ref_then_page("7")
           + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>"), out


def test_a_page_number_after_a_shared_END_BEGIN_run_compares_clean(tmp_path):
    """Two copies of one document that disagree only about the page the
    field was last laid out on. Unmasked, that is a TEXT change on every
    round — the crying wolf this masking exists to stop."""
    a, b = docs(tmp_path, BASE + para(_ref_then_page("7")),
                BASE + para(_ref_then_page("9")))

    report = compare(a, b)

    assert report["text"] == [], report["text"]
    assert render(report, expect_clean=True) == 0


def _page_in_a_shared_instruction(page: str) -> str:
    """`{ PAGEREF _Toc1 { PAGE } }`, the inner `begin` in the run that
    holds the outer `begin` and instruction."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/>'
            '<w:instrText xml:space="preserve"> PAGEREF _Toc1 </w:instrText>'
            '<w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run(page)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run("17")
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


@pytest.mark.parametrize("lead", _LEADS)
def test_a_field_whose_BEGIN_shares_its_parent_s_run_is_masked_as_itself(
        lead):
    """The same miscount the other way. Counting from the shared run, the
    inner walk met the PARENT's `begin` first, reached its own separator
    at depth 2, skipped it, and returned the parent's — so the inner
    field was judged covered by the parent's region, which lies AFTER
    its page number. Nothing masked the `7`."""
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + (run(lead) if lead else "")
           + _page_in_a_shared_instruction("7") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace(
        "<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>").replace(
        "<w:t>17</w:t>", "<w:t>«F:PAGEREF»</w:t>"), out


def test_a_page_number_in_a_shared_instruction_run_compares_clean(tmp_path):
    a, b = docs(tmp_path, BASE + para(_page_in_a_shared_instruction("7")),
                BASE + para(_page_in_a_shared_instruction("9")))

    report = compare(a, b)

    assert report["text"] == [], report["text"]
    assert render(report, expect_clean=True) == 0


def _one_run(first: str, between: str, total: str) -> str:
    """"Page { PAGE } of { NUMPAGES }" with both fields and the prose
    between them in ONE run — the shape a generated document gets when
    every element is appended to the run it already has."""
    def fld(instr: str, result: str) -> str:
        return ('<w:fldChar w:fldCharType="begin"/>'
                f'<w:instrText xml:space="preserve"> {instr} </w:instrText>'
                '<w:fldChar w:fldCharType="separate"/>'
                f"<w:t>{result}</w:t>"
                '<w:fldChar w:fldCharType="end"/>')
    return ("<w:r>" + fld("PAGE", first)
            + f'<w:t xml:space="preserve">{between}</w:t>'
            + fld("NUMPAGES", total) + "</w:r>")


@pytest.mark.parametrize("lead", _LEADS)
def test_two_fields_and_the_prose_between_them_in_ONE_run(lead):
    """Both defects at once. Every span here was the whole run, so both
    fields walked from the PAGE's `begin`, both took the PAGE's
    separator, and one mask ran from there to the run's end: " of " was
    blanked with the page count."""
    from docxkit._compare_read import mask_volatile_fields

    xml = "<w:p>" + (run(lead) if lead else "") + _one_run("3", " of ", "12")
    xml += "</w:p>"

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>3</w:t>", "<w:t>«F:PAGE»</w:t>").replace(
        "<w:t>12</w:t>", "<w:t>«F:NUMPAGES»</w:t>"), out


def test_one_run_holding_two_fields_shows_prose_and_hides_numbers(tmp_path):
    """The gate on the same run: a different page count is not a change,
    and a different word between the two fields is."""
    a, b = docs(tmp_path, BASE + para(_one_run("3", " of ", "12")),
                BASE + para(_one_run("4", " of ", "13")))
    report = compare(a, b)
    assert report["text"] == [], report["text"]
    assert render(report, expect_clean=True) == 0

    a, c = docs(tmp_path, BASE + para(_one_run("3", " of ", "12")),
                BASE + para(_one_run("3", " from ", "12")))
    report = compare(a, c)
    assert report["text"], "the edit reached no layer"
    assert render(report, expect_clean=True) == 1


@pytest.mark.parametrize("stray", ["end", "separate"])
def test_a_fldChar_with_no_field_open_is_passed_over(stray):
    """A part whose marks do not balance. `compare` reads the copy the
    author sends back, and a `separate` or an `end` with nothing open is
    what a half-deleted field leaves behind; the walk keeps a stack, and
    without the `open_fields` guard on both branches the stray mark
    indexes an empty list and the whole comparison raises.

    Passing over it is also the answer `field_spans` gives, and the
    field AFTER the stray must still be masked: a damaged paragraph is
    not a reason to compare every page number in the part by value.
    """
    from docxkit._compare_read import mask_volatile_fields

    xml = ("<w:p>" + run("A sentence. ")
           + f'<w:r><w:fldChar w:fldCharType="{stray}"/></w:r>'
           + run("More prose. ") + field("PAGE", "7") + "</w:p>")

    out = mask_volatile_fields(xml)

    assert out == xml.replace("<w:t>7</w:t>", "<w:t>«F:PAGE»</w:t>"), out


def _captioned(texts: list[str | None]) -> dict[str, bytes]:
    """A document whose `None` paragraph draws image1.png.

    An empty string is an EMPTY paragraph and never `<w:p/>`: the walk
    reads `P_RE`, which skips the self-closing form on purpose, so the
    two spellings are documents with different paragraph INDICES — and
    the indices are the whole question below.
    """
    body = "".join(_DRAWING if t is None else para(run(t)) if t else para()
                   for t in texts)
    parts = make_parts(body)
    parts["word/_rels/document.xml.rels"] = _RELS.encode("utf-8")
    return parts


@pytest.mark.parametrize(("texts", "caption"), [
    # the caption two BELOW, past the spacer a figure usually sits on
    pytest.param(["Title of the paper", "Some prose here.",
                  "More prose here.", "Above two.", "Above one.", None,
                  "", "Figure 1. The caption", "Body text after."],
                 "Figure 1. The caption", id="two-below"),
    # nothing below within reach, and the caption directly above: three
    # paragraphs down is OUTSIDE the window and must not be taken
    pytest.param(["Title of the paper", "Some prose here.",
                  "More prose here.", "Above two.", "The caption above",
                  None, "", "", "Three below."],
                 "The caption above", id="above-with-text-three-below"),
    # the caption two above, with the paragraph between them blank
    pytest.param(["Title of the paper", "Some prose here.",
                  "More prose here.", "Caption above two", "", None,
                  "", ""],
                 "Caption above two", id="two-above"),
    # nothing within two either way: the label is empty rather than
    # something fetched from further off
    pytest.param(["Title of the paper", "Some prose here.", "Further up",
                  "", "", None, "", ""],
                 "", id="neither-within-two"),
    # the drawing in the SECOND paragraph, where the window above it
    # runs off the start of the document
    pytest.param(["Caption above", None, "", ""],
                 "Caption above", id="second-paragraph"),
])
def test_the_caption_a_FIGURE_is_NAMED_by(texts, caption):
    """The window is the drawing's own paragraph, then the two below it,
    then the two above, nearest first — below first because that is
    where a figure's caption sits in these manuscripts, and above
    because some journals' styles put it there.

    Thirty of this module's seventy survivors are that window's
    arithmetic, every one alive because the fixtures reaching it put the
    caption immediately under the drawing, where `i + 1` agrees with
    `i * 1`, `i << 1`, `i ^ 1` and the rest. Each case here puts the
    nearest text at one END of the window, or one paragraph outside it,
    so a window that reaches too far answers with the wrong line and one
    that stops too soon answers with none.

    The label is the whole output of this walk: without it a changed
    figure is reported as `word/media/image1.png`, which sends a reader
    to a folder rather than to the page.
    """
    from docxkit._compare_read import _media_labels

    assert _media_labels(_captioned(texts)) == {
        "word/media/image1.png": caption}


def test_a_part_with_NO_rels_does_not_stop_the_label_walk():
    """The walk reads every text part in NAME order, and the rels it
    needs are a part of their own. A part without them is ordinary —
    `word/document.xml` sorts first, and a body that draws nothing has
    no image relationships at all — so stopping there leaves every
    figure in the notes and the headers unlabelled, with nothing in the
    report to say which exhibit changed.
    """
    from docxkit._compare_read import _media_labels

    parts = make_parts(para(run("The figure is in the note below.")))
    parts["word/footnotes.xml"] = notes(
        "footnotes", '<w:footnote w:id="2">' + _DRAWING
        + para(run("Figure 1. In a note")) + "</w:footnote>").encode("utf-8")
    parts["word/_rels/footnotes.xml.rels"] = _RELS.encode("utf-8")

    assert _media_labels(parts) == {
        "word/media/image1.png": "Figure 1. In a note"}


def test_a_drawing_whose_rId_the_rels_do_not_NAME_is_not_a_figure():
    """`targets.get(rid)` answers None for an id the rels do not carry —
    a drawing left behind by an edit that took its relationship with it.
    The set of drawn parts then holds None, and asking whether None
    matches the media pattern raises TypeError: a comparison that stops
    on a document Word opens without complaint.
    """
    from docxkit._compare_read import _media_labels

    parts = _captioned(["Figure 1. The caption", None, ""])
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b'r:embed="rId7"', b'r:embed="rId9"')

    assert _media_labels(parts) == {}


# --- the data census of 2026-09-18 ---------------------------------------
#
# cosmic-ray mutates operators, comparisons and numbers, so behaviour
# that lives in DATA — one member of a tuple, one alternative or one
# guard of a regex — is invisible to a sweep, and `_compare_diff` reads
# every part it touches through patterns. Forty such deletions were put
# through `kill_check` by hand; six changed no test, and these are the
# four shapes behind five of them. The sixth is argued rather than
# pinned: the `(?<!/)` guard on the RUN opening of `_FIELD_END_RE` can
# only decide a match where a self-closing `<w:r/>` is followed by a
# `w:fldChar` standing outside any run, and a field character is a child
# of a run.


@pytest.mark.parametrize("kind,label,name", [
    ("anchors", "hyperlink target", "Smith2020txt"),
    ("cites", "citation bookmark", "cite_Smith2020")])
def test_what_SURVIVES_is_read_for_BOTH_kinds_when_the_caller_is_silent(
        kind, label, name):
    """`compare_paras` without `surviving` falls back to every field name
    the other side carries, and that set is built over both kinds. A
    fallback that reads one kind calls a target which merely MOVED out of
    its block lost — the dangling-link flag this project may never wave
    away, raised by the comparison itself.

    The surviving copy has to land OUTSIDE the replace block, so the two
    sit either side of a paragraph both documents share: a name still
    inside the block is not lost under any reading of the fallback, and
    a fixture built that way proves nothing about it.
    """
    from docxkit._compare_diff import compare_paras

    def holding(text: str):
        return _para(text, anchors=[name] if kind == "anchors" else [],
                     cites=[name] if kind == "cites" else [])

    moved = holding("epsilon")
    left = [_para("alpha"), holding("beta"),
            _para("delta"), _para("omega")]
    right = [_para("alpha"), _para("gamma"), _para("delta"), moved,
             _para("omega")]

    report = _empty_report()
    compare_paras(left, right, report)
    assert report["stripped_fields"] == [], "it moved; it is not lost"

    lost = _empty_report()
    compare_paras(left, [p for p in right if p is not moved], lost)
    assert [n for e in lost["stripped_fields"] for n in e["lost"]] == [
        f"lost {label}(s): ['{name}']"], "and a real loss is still named"


@pytest.mark.parametrize("marker", ["separate", "end"])
def test_a_field_LABEL_is_read_whatever_ORDER_its_attributes_are_in(marker):
    r"""Attribute order is not meaningful in XML, which is why both
    patterns that find a field-form label read
    `<w:fldChar\b[^>]*\bw:fldCharType=` rather than the attribute they
    want first — the reading `integrity` was given after hard-coding the
    order made it find no bookmarks at all on a conforming document.

    A locked field writes `w:fldLock` first. Wanting the type first, the
    whole field form stops matching and the link drops off the list: the
    same silence a ` />` marker caused, in the one spelling the
    parametrisation above it does not carry.
    """
    from docxkit._compare_diff import hyperlink_labels
    from docxkit.citations import hyperlink_field

    locked = hyperlink_field("Hao2008", "Hao et al. (2008)").replace(
        f'<w:fldChar w:fldCharType="{marker}"/>',
        f'<w:fldChar w:fldLock="1" w:fldCharType="{marker}"/>')
    assert f'w:fldLock="1" w:fldCharType="{marker}"' in locked, "it applied"

    assert hyperlink_labels(f"<w:p>{locked}</w:p>") == {"Hao et al. (2008)": 1}


def test_a_literal_HYPERLINK_in_PRESERVED_text_is_still_field_code():
    r"""The check reads `<w:t[^>]*>` and not `<w:t>`, and the difference
    is every realistic instance of the defect: a field code that has come
    apart shows the instruction as it was written, opening and closing on
    a space — exactly the text node Word marks `xml:space="preserve"`.
    """
    preserved = ('<w:p><w:r><w:t xml:space="preserve"> HYPERLINK '
                 r'\l "Smith2020" \h </w:t></w:r></w:p>')
    bare = "<w:p><w:r><w:t>HYPERLINK</w:t></w:r></w:p>"

    for xml in (preserved, bare):
        assert any("literal HYPERLINK field code" in i
                   for i in _integrity(xml)), xml

    instruction = ('<w:p><w:r><w:instrText xml:space="preserve">'
                   r' HYPERLINK \l "Smith2020" \h '
                   "</w:instrText></w:r></w:p>")
    assert not any("literal HYPERLINK" in i
                   for i in _integrity(instruction, {"Smith2020"})), \
        "an instruction inside its field is not field code on the page"
