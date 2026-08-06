"""Characterization tests for the ported compare module.

compare.py is the authoritative gate every paper round relies on, and it
came over from tools/ verbatim — well-exercised but never unit-tested.
These pin its CURRENT behavior on synthetic fixtures so a future change
(or the eventual de-porting) has something to diff against. They assert
what it does, not what it should do.
"""
from __future__ import annotations

from conftest import (
    comment,
    field,
    hdr,
    make_parts,
    note,
    notes,
    para,
    run,
    write,
)

from docxkit.compare import compare, render


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
