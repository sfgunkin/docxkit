"""Bidirectional figure/table cross-references."""
from __future__ import annotations

import re

import pytest

from docxkit import crossrefs
from docxkit.errors import AnchorError


def para(*runs: str, ppr: str = "") -> str:
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def run(text: str, rpr: str = "") -> str:
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def doc(*paras: str) -> str:
    return "<w:document><w:body>" + "".join(paras) + "</w:body></w:document>"


def paragraph_holding(xml: str, needle: str) -> str:
    """The single <w:p> whose visible text contains `needle`.

    Matching paragraphs with a non-greedy regex over the whole document
    silently spans from one paragraph into the next, so tests that do
    that assert against the wrong block.
    """
    hits: list[str] = re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL)
    holding = [p for p in hits
               if needle in "".join(
                   re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))]
    assert len(holding) == 1, f"{needle!r}: {len(holding)} paragraphs, need 1"
    return holding[0]


# --- naming -----------------------------------------------------------

def test_anchor_names_follow_the_house_convention():
    assert crossrefs.anchor_names("Table", "1") == ("Table1", "Table1txt")
    assert crossrefs.anchor_names("Figure", "3") == ("Figure3", "Figure3txt")


def test_anchor_names_sanitise_what_word_rejects():
    # Word bookmark names take only letters, digits and underscore
    assert crossrefs.anchor_names("Table", "3.2")[0] == "Table3_2"
    assert crossrefs.anchor_names("Figure", "A-1") == ("FigureA_1",
                                                       "FigureA_1txt")


# --- caption detection ------------------------------------------------

def test_caption_needs_a_separator_not_just_the_word():
    xml = doc(
        para(run("Table 1. Employment by age group")),   # caption
        para(run("Table 1 shows employment by age.")),   # prose, not a caption
    )
    caps = crossrefs.find_captions(xml)
    assert [c.name for c in caps] == ["Table1"]


def test_captions_found_for_both_labels_and_russian():
    xml = doc(para(run("Figure 2: Trends")), para(run("Таблица 4. Итоги")))
    assert [c.name for c in crossrefs.find_captions(xml)] == ["Figure2",
                                                             "Таблица4"]


# --- the core behaviour -----------------------------------------------

def test_link_creates_both_bookmarks_and_both_hyperlinks():
    xml = doc(
        para(run("Employment rises with age, as shown in Table 1 below.")),
        para(run("Table 1. Employment by age group")),
    )
    out, report = crossrefs.link(xml)

    assert report.linked == ["Table1"]
    # the in-text mention carries Table1txt and links to Table1
    assert 'w:name="Table1txt"' in out
    assert 'w:anchor="Table1"' in out
    # the caption carries Table1 and links back to Table1txt
    assert 'w:name="Table1"' in out
    assert 'w:anchor="Table1txt"' in out


def test_only_the_label_is_hyperlinked_not_the_sentence():
    xml = doc(
        para(run("Employment rises with age, as shown in Table 1 below.")),
        para(run("Table 1. Employment by age group")),
    )
    out, _ = crossrefs.link(xml)
    link = re.search(r"<w:hyperlink w:anchor=\"Table1\">.*?</w:hyperlink>",
                     out, re.DOTALL)
    assert link is not None
    assert "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>",
                              link.group(0))) == "Table 1"
    # and the surrounding words survive
    assert "Employment rises with age, as shown in " in out
    assert " below." in out


def test_surrounding_text_keeps_its_run_properties():
    rpr = "<w:rPr><w:i/><w:lang w:val=\"es-MX\"/></w:rPr>"
    xml = doc(
        para(run("See Table 2 for detail.", rpr=rpr)),
        para(run("Table 2. Detail")),
    )
    out, report = crossrefs.link(xml)
    assert report.linked == ["Table2"]
    # three runs come out of the split; the two plain ones keep <w:i/>
    mention = paragraph_holding(out, "See ")
    plain = [r for r in re.findall(r"<w:r>.*?</w:r>", mention, re.DOTALL)
             if "rStyle" not in r]
    assert len(plain) == 2, "expected text either side of the label"
    assert all("<w:i/>" in r and 'w:val="es-MX"' in r for r in plain)


def test_figure_one_does_not_match_figure_ten():
    xml = doc(
        para(run("Figure 10 reports the gap.")),
        para(run("Then Figure 1 reports the level.")),
        para(run("Figure 1. Level")),
        para(run("Figure 10. Gap")),
    )
    out, report = crossrefs.link(xml)
    assert set(report.linked) == {"Figure1", "Figure10"}

    # Figure1txt must sit in the "Figure 1" paragraph, not the "Figure 10" one
    paras = re.findall(r"<w:p>.*?</w:p>", out, re.DOTALL)
    holder = next(p for p in paras if 'w:name="Figure1txt"' in p)
    assert "reports the level" in holder


def test_a_lowercase_mention_is_linked():
    xml = doc(
        para(run("The results in table 1 are robust.")),
        para(run("Table 1. Employment")),
    )
    out, report = crossrefs.link(xml)
    assert report.linked == ["Table1"]
    assert 'w:name="Table1txt"' in paragraph_holding(out, "are robust.")


def test_a_russian_mention_is_linked_in_any_case_form():
    # DSI writes «Таблица 4» over the table and «в таблице 4» in the
    # text; matching only the caption form linked nothing at all there.
    xml = doc(
        para(run("Результаты представлены в таблице 4 ниже.")),
        para(run("Таблица 4. Итоговые оценки")),
    )
    out, report = crossrefs.link(xml)
    assert report.linked == ["Таблица4"]
    mention = paragraph_holding(out, "ниже.")
    assert 'w:anchor="Таблица4"' in mention
    # the inflected form is what gets hyperlinked, so the sentence reads
    link = re.search(r"<w:hyperlink[^>]*>.*?</w:hyperlink>", mention,
                     re.DOTALL)
    assert link is not None
    assert "таблице 4" in "".join(
        re.findall(r"<w:t[^>]*>([^<]*)</w:t>", link.group(0)))


def test_the_caption_is_not_treated_as_its_own_mention():
    # only the caption names the table; nothing in prose does
    xml = doc(para(run("Some prose.")), para(run("Table 5. Orphan")))
    out, report = crossrefs.link(xml)
    assert report.no_mention == ["Table5"]
    assert "Table5txt" not in out


def test_link_is_idempotent():
    xml = doc(
        para(run("As Table 1 shows, employment rises.")),
        para(run("Table 1. Employment")),
    )
    once, first = crossrefs.link(xml)
    twice, second = crossrefs.link(once)
    assert twice == once
    assert first.linked == ["Table1"]
    assert second.already_linked == ["Table1"]
    assert second.linked == []


def test_bookmark_ids_are_unique():
    xml = doc(
        para(run("Table 1 and Table 2 and Figure 1 follow.")),
        para(run("Table 1. One")),
        para(run("Table 2. Two")),
        para(run("Figure 1. Three")),
    )
    out, report = crossrefs.link(xml)
    assert len(report.linked) == 3
    ids = re.findall(r'<w:bookmarkStart w:id="(\d+)"', out)
    assert len(ids) == len(set(ids)), "duplicate bookmark id"
    starts = re.findall(r'<w:bookmark(Start|End)[^>]*w:id="(\d+)"', out)
    assert len([s for s, _ in starts if s == "Start"]) == \
        len([s for s, _ in starts if s == "End"]), "unbalanced bookmarks"


def test_existing_bookmark_ids_are_not_reused():
    xml = doc(
        para('<w:bookmarkStart w:id="47" w:name="intro"/>',
             run("As Table 1 shows."), '<w:bookmarkEnd w:id="47"/>'),
        para(run("Table 1. Employment")),
    )
    out, _ = crossrefs.link(xml)
    new = re.search(r'<w:bookmarkStart w:id="(\d+)" w:name="Table1txt"', out)
    assert new is not None and int(new.group(1)) > 47


def test_an_authors_own_hyperlink_keeps_its_anchor():
    xml = doc(
        para('<w:hyperlink w:anchor="custom_target">',
             run("Table 3"), "</w:hyperlink>", run(" is discussed here.")),
        para(run("Table 3. Discussed")),
    )
    out, report = crossrefs.link(xml)
    assert report.linked == ["Table3"]
    assert 'w:anchor="custom_target"' in out       # not rewritten
    assert 'w:name="Table3txt"' in out             # but bookmarked


def test_a_legacy_anchor_on_the_same_caption_is_retargeted():
    # AFI's earlier scheme: the caption carried `tbl3_caption` and the
    # mention pointed at it. Same destination, older name -> retarget.
    xml = doc(
        para('<w:hyperlink w:anchor="tbl3_caption">', run("Table 3"),
             "</w:hyperlink>", run(" is discussed here.")),
        para('<w:bookmarkStart w:id="7" w:name="tbl3_caption"/>',
             run("Table 3. Discussed"), '<w:bookmarkEnd w:id="7"/>'),
    )
    out, report = crossrefs.link(xml)
    assert report.linked == ["Table3"]
    assert "retargeted legacy anchor" in report.notes["Table3"]
    mention = paragraph_holding(out, "is discussed here.")
    assert 'w:anchor="Table3"' in mention
    assert 'w:anchor="tbl3_caption"' not in mention
    # the old bookmark survives — other links may still use it
    assert 'w:name="tbl3_caption"' in out


def test_a_legacy_anchor_in_the_gap_before_the_caption_is_retargeted():
    # AFI's afi_v11 places these BETWEEN paragraphs, as siblings of the
    # caption rather than inside it. Scanning only the caption paragraph
    # missed all four of them.
    xml = doc(
        para('<w:hyperlink w:anchor="fig4_caption">', run("Figure 4"),
             "</w:hyperlink>", run(" shows the index.")),
        # the bookmark is a sibling of the caption, sitting just before it
        '<w:bookmarkStart w:id="9" w:name="fig4_caption"/>'
        '<w:bookmarkEnd w:id="9"/>',
        para(run("Figure 4. Old-Age Sorting Index")),
    )
    out, report = crossrefs.link(xml)
    assert report.linked == ["Figure4"]
    assert "retargeted legacy anchor" in report.notes["Figure4"]
    assert 'w:anchor="Figure4"' in paragraph_holding(out, "shows the index.")


def test_caption_bookmark_sits_after_the_paragraph_properties():
    ppr = '<w:pPr><w:jc w:val="center"/></w:pPr>'
    xml = doc(
        para(run("As Table 1 shows.")),
        para(run("Table 1. Employment"), ppr=ppr),
    )
    out, _ = crossrefs.link(xml)
    caption = paragraph_holding(out, "Employment")
    assert caption.index("</w:pPr>") < caption.index('w:name="Table1"')
    # and the bookmark closes before the paragraph does
    assert caption.index("bookmarkEnd") < caption.index("</w:p>")


def test_caption_label_with_a_non_breaking_space_is_linked():
    xml = doc(
        para(run("As Table 1 shows.")),
        para(run("Table 1. Employment")),
    )
    out, report = crossrefs.link(xml)
    assert report.linked == ["Table1"]
    assert 'w:anchor="Table1txt"' in out


def test_a_label_split_across_runs_is_reported_not_silently_skipped():
    xml = doc(
        para(run("As Table 1 shows.")),
        para(run("Table"), run(" 1. Employment")),      # Word rsid split
    )
    with pytest.raises(AnchorError, match="split across runs"):
        crossrefs.link(xml)


def test_only_restricts_the_work():
    xml = doc(
        para(run("Table 1 and Table 2 follow.")),
        para(run("Table 1. One")),
        para(run("Table 2. Two")),
    )
    out, report = crossrefs.link(xml, only=["Table2"])
    assert report.linked == ["Table2"]
    assert "Table1txt" not in out


# --- audit and unlink -------------------------------------------------

def test_audit_reports_each_state():
    xml = doc(
        para(run("As Table 1 shows.")),
        para(run("Table 1. Linked")),
        para(run("Table 9. Never mentioned")),
    )
    out, _ = crossrefs.link(xml)
    state = crossrefs.audit(out)
    assert state["linked"] == ["Table1"]
    assert state["mention_only"] == []
    assert "Table9" not in state["linked"]


def test_audit_finds_a_dangling_anchor():
    xml = doc(para('<w:hyperlink w:anchor="Figure7">', run("Figure 7"),
                   "</w:hyperlink>"))
    assert crossrefs.audit(xml)["dangling"] == ["Figure7"]


# A resolving anchor is not a well-placed anchor. Parental Style carried
# Table5txt on the THIRD mention for a day and every audit in between
# said "linked 12, dangling 0" (2026-08-12); the caption's back-link
# jumps the reader past the discussion it belongs to.

def _mention(anchor: str, text: str, mark: str = "") -> str:
    link = f'<w:hyperlink w:anchor="{anchor}">{run(text)}</w:hyperlink>'
    if not mark:
        return para(link)
    return para(f'<w:bookmarkStart w:id="9" w:name="{mark}"/>{link}'
                '<w:bookmarkEnd w:id="9"/>')


def test_audit_reports_an_anchor_that_does_not_lead_its_mentions():
    xml = doc(
        _mention("Table5", "Table 5"),                      # the FIRST one
        para(run("Intervening prose.")),
        _mention("Table5", "Table 5", mark="Table5txt"),     # marker here
        para('<w:bookmarkStart w:id="1" w:name="Table5"/>'
             '<w:bookmarkEnd w:id="1"/>' + run("Table 5. The caption")),
    )
    got = crossrefs.audit(xml)
    assert got["linked"] == ["Table5"], got
    assert not got["dangling"]
    assert len(got["misplaced_anchor"]) == 1, got["misplaced_anchor"]
    line = got["misplaced_anchor"][0]
    assert line.startswith("Table5txt sits at ¶3")
    assert "the first at ¶1" in line


def test_the_marker_on_the_first_mention_is_reported_clean():
    xml = doc(
        _mention("Table5", "Table 5", mark="Table5txt"),
        _mention("Table5", "Table 5"),                       # a later one
        para('<w:bookmarkStart w:id="1" w:name="Table5"/>'
             '<w:bookmarkEnd w:id="1"/>' + run("Table 5. The caption")),
    )
    assert crossrefs.audit(xml)["misplaced_anchor"] == []


def test_a_marker_inside_its_own_link_is_not_misplaced():
    """Whether the marker wraps the link or sits INSIDE it is a linker's
    choice that means nothing to a reader. Comparing raw offsets called
    100 of those a finding across the manuscripts on this machine —
    every one of them 'the first mention is this same paragraph'."""
    xml = doc(
        para(f'<w:hyperlink w:anchor="Table5">'
             f'<w:bookmarkStart w:id="9" w:name="Table5txt"/>'
             f'{run("Table 5")}<w:bookmarkEnd w:id="9"/></w:hyperlink>'),
        para('<w:bookmarkStart w:id="1" w:name="Table5"/>'
             '<w:bookmarkEnd w:id="1"/>' + run("Table 5. The caption")),
    )
    assert crossrefs.audit(xml)["misplaced_anchor"] == []


def test_both_link_forms_count_as_mentions():
    """A work linked once as a field and once as an element is TWO
    mentions — Word rewrites a field into an element on every author
    save, so a manuscript mid-round holds one of each."""
    field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l '
             '"Table5" \\h </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             + run("Table 5")
             + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    xml = doc(
        para(field),                                        # first, a FIELD
        _mention("Table5", "Table 5", mark="Table5txt"),
        para('<w:bookmarkStart w:id="1" w:name="Table5"/>'
             '<w:bookmarkEnd w:id="1"/>' + run("Table 5. The caption")),
    )
    assert len(crossrefs.audit(xml)["misplaced_anchor"]) == 1


def test_relinking_an_unlinked_run_leaves_one_rstyle():
    """unlink_by_anchor leaves run properties alone by design, so a
    wipe-and-rebuild round re-links a run that still carries the
    Hyperlink style. Two rStyle children is an rPr Word's schema
    rejects — 24 of them on Parental Style's R2 pass, and only lint
    could see it.
    """
    from docxkit.crossrefs import _with_hyperlink_style

    styled = ('<w:rPr><w:rStyle w:val="Hyperlink"/>'
              '<w:color w:val="1F3864"/></w:rPr>')
    assert _with_hyperlink_style(styled).count("<w:rStyle") == 1
    assert _with_hyperlink_style(styled) == styled          # idempotent

    plain = '<w:rPr><w:color w:val="000000"/></w:rPr>'
    out = _with_hyperlink_style(plain)
    assert out.count("<w:rStyle") == 1 and "Hyperlink" in out

    assert _with_hyperlink_style("").count("<w:rStyle") == 1

    other = '<w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
    out = _with_hyperlink_style(other)
    assert out.count("<w:rStyle") == 1, "a second style was added"
    assert "Hyperlink" in out


def test_wipe_and_relink_is_schema_clean():
    """End to end: link, unlink the whole scheme, link again — the
    round trip must not accumulate run properties."""
    from docxkit.citations import unlink_by_anchor
    from docxkit.lint import lint_parts

    xml = doc(
        para(run("As Table 1 shows, employment rises.")),
        para(run("Table 1. Employment")),
    )
    linked, _ = crossrefs.link(xml)
    wiped, _, _ = unlink_by_anchor(linked, r"^(Table|Figure)[A-Za-z0-9_.]+$")
    relinked, _ = crossrefs.link(wiped)

    problems = lint_parts({"word/document.xml": relinked.encode("utf-8")})
    assert not [p for p in problems if "rStyle" in p], problems
    for m in re.finditer(r"<w:rPr>.*?</w:rPr>", relinked, re.DOTALL):
        assert m.group(0).count("<w:rStyle") <= 1, m.group(0)


def test_a_bookmark_in_another_part_is_not_dangling():
    """A link and its bookmark need not share a part: a work cited only
    in a footnote keeps its in-text bookmark in footnotes.xml while the
    reference entry links to it from the body. Reading the body alone
    called four such pairs dangling on Parental Style — and the false
    flag was written off as a quirk twice before being read as the bug.
    """
    body = doc(para('<w:hyperlink w:anchor="Smith2020txt">',
                    run("Smith, A. (2020)"), "</w:hyperlink>"))
    notes = doc(para('<w:bookmarkStart w:id="9" w:name="Smith2020txt"/>'
                     '<w:bookmarkEnd w:id="9"/>', run("(Smith 2020)")))

    assert crossrefs.audit(body)["dangling"] == ["Smith2020txt"]
    assert crossrefs.audit(body, also=notes)["dangling"] == []
    assert crossrefs.audit(body, also=[notes])["dangling"] == []
    # a genuinely dangling anchor still reports with `also` supplied
    assert crossrefs.audit(
        doc(para('<w:hyperlink w:anchor="Figure7">', run("Figure 7"),
                 "</w:hyperlink>")), also=notes)["dangling"] == ["Figure7"]


def test_unlink_restores_a_plain_document():
    xml = doc(
        para(run("As Table 1 shows, employment rises.")),
        para(run("Table 1. Employment")),
    )
    linked, _ = crossrefs.link(xml)
    plain, removed = crossrefs.unlink(linked)
    assert removed == 2
    assert "w:hyperlink" not in plain
    assert "bookmarkStart" not in plain
    # the words are all still there
    assert "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", plain)) == \
        "As Table 1 shows, employment rises.Table 1. Employment"


def test_unlink_leaves_other_hyperlinks_alone():
    xml = doc(
        para('<w:hyperlink r:id="rId9">', run("a citation"), "</w:hyperlink>",
             run(" and Table 1.")),
        para(run("Table 1. Employment")),
    )
    linked, _ = crossrefs.link(xml)
    plain, _ = crossrefs.unlink(linked)
    assert 'r:id="rId9"' in plain
    assert "a citation" in plain


def test_citation_bookmarks_are_not_mistaken_for_figure_mentions():
    # The papers use the same <name>txt convention for citations, so a
    # naive scan for bookmarks ending in "txt" reported 48 citations as
    # figures whose caption had gone missing.
    xml = doc(
        para('<w:bookmarkStart w:id="2" w:name="Halliday2020txt"/>',
             run("Halliday (2020) finds the opposite."),
             '<w:bookmarkEnd w:id="2"/>'),
        para(run("As Table 1 shows.")),
        para(run("Table 1. Employment")),
    )
    _, report = crossrefs.link(xml)
    assert report.no_caption == []
    assert report.linked == ["Table1"]


def test_link_reports_a_mention_whose_caption_is_gone():
    xml = doc(
        para('<w:bookmarkStart w:id="3" w:name="Table8txt"/>',
             run("Table 8 was deleted."), '<w:bookmarkEnd w:id="3"/>'),
    )
    _, report = crossrefs.link(xml)
    assert report.no_caption == ["Table8"]
    assert not report.complete


def test_a_misnumbered_caption_bookmark_reports():
    """LI7's 'Figure 5' caption carries bookmark Figure6 — every link
    works, one renumbering behind; existence checks cannot see it."""
    from conftest import make_parts, para, run, write  # noqa: F401

    from docxkit.crossrefs import audit
    xml = ("<w:document><w:body>"
           + para(run("Figure 5 shows the trend."))
           + para('<w:bookmarkStart w:id="9" w:name="Figure6"/>'
                  '<w:bookmarkEnd w:id="9"/>'
                  + run("Figure 5: The trend over time"))
           + "</w:body></w:document>")
    report = audit(xml)
    assert report["misnamed"] == ["Figure6 on the 'Figure 5' caption"]


# --- link_more: every later mention, forward only ----------------------

def test_link_more_links_every_later_mention_forward_only():
    xml = doc(
        para(run("Table 1 shows levels.")),
        para(run("As Table 1 confirms, and Table 1 again.")),
        para(run("Table 1. Employment")),
    )
    xml, report = crossrefs.link(xml)
    assert report.linked == ["Table1"]
    xml, counts = crossrefs.link_more(xml)
    assert counts == {"Table1": 2}
    later = paragraph_holding(xml, "confirms")
    assert later.count('w:anchor="Table1"') == 2
    assert "Table1txt" not in later          # forward only, no back-link
    xml2, counts2 = crossrefs.link_more(xml)
    assert counts2 == {} and xml2 == xml     # idempotent


def test_link_more_links_range_and_list_continuations():
    xml = doc(
        para(run("Table 3 shows one thing.")),
        para(run("Table 4 shows another.")),
        para(run("Table 5 shows a third.")),
        para(run("Results appear in Tables 3 to 5, as noted, and in "
                 "Tables 3, 4 and 5 alike.")),
        para(run("Table 3. First")),
        para(run("Table 4. Second")),
        para(run("Table 5. Third")),
    )
    xml, _ = crossrefs.link(xml)
    xml, _counts = crossrefs.link_more(xml)
    p = paragraph_holding(xml, "as noted")
    assert p.count('w:anchor="Table3"') == 2   # both "Tables 3" heads
    assert 'w:anchor="Table4"' in p            # the bare "4"
    assert p.count('w:anchor="Table5"') == 2   # both bare "5"s


def test_link_more_does_not_link_prose_ranges():
    # "age 3 to 5" is not a table list; words between the label's number
    # and the candidate break the continuation.
    xml = doc(
        para(run("Table 3 shows children age 3 to 5 by cohort.")),
        para(run("Table 3. First")),
        para(run("Table 5. Second")),
    )
    xml, _ = crossrefs.link(xml)
    xml, counts = crossrefs.link_more(xml)
    assert counts.get("Table5", 0) == 0


def test_new_bookmark_ids_clear_the_other_parts():
    """Bookmark ids are unique document-wide, not part-wide.

    Minting from the body alone can hand back an id footnotes.xml is
    already using, and Word pairs bookmarkStart/End by id — the same
    "unreadable content" class as a duplicate name. citations has always
    passed every part to the allocator; this module used not to.
    """
    body = doc(para(run("As Table 1 shows, the effect is small.")),
               para(run("Table 1. Results")))
    foot = ('<w:footnotes><w:footnote w:id="2"><w:p>'
            '<w:bookmarkStart w:id="900" w:name="Palloni2016txt"/>'
            '<w:bookmarkEnd w:id="900"/>'
            "</w:p></w:footnote></w:footnotes>")

    linked, _ = crossrefs.link(body, other_parts=[foot])
    ids = [int(i) for i in re.findall(r'<w:bookmarkStart w:id="(\d+)"',
                                      linked)]
    assert ids and min(ids) > 900

    # and without the other part, the collision is exactly what happens
    naive, _ = crossrefs.link(body)
    naive_ids = [int(i) for i in re.findall(r'<w:bookmarkStart w:id="(\d+)"',
                                            naive)]
    assert min(naive_ids) < 900


def test_an_ampersand_survives_being_linked():
    """Found by the property suite, and it corrupted the page.

    The text taken from a `w:t` is ALREADY XML-escaped; escaping it
    again turned a caption reading "Income & wealth" into one reading
    "Income &amp; wealth" — visible to the reader, in the manuscript.
    """
    from docxkit._xml import visible_text
    xml = doc(
        para(run("R&amp;D spending rises, see Table 1 below &amp; after.")),
        para(run("Table 1. Income &amp; wealth")))
    out, report = crossrefs.link(xml)
    assert report.linked == ["Table1"]
    assert visible_text(out) == visible_text(xml)
    assert "&amp;amp;" not in out


def test_a_less_than_sign_survives_being_linked():
    from docxkit._xml import visible_text
    xml = doc(para(run("For p &lt; 0.05 see Table 2 below.")),
              para(run("Table 2. Results where p &lt; 0.05")))
    out, _ = crossrefs.link(xml)
    assert visible_text(out) == visible_text(xml)
    assert "&amp;lt;" not in out


# --- runs that hold more than a w:t -----------------------------------


def test_a_caption_run_with_two_text_nodes_keeps_both():
    """Word splits text at rsid boundaries, so one run routinely holds
    several w:t. Rebuilding the run from the ONE matched w:t dropped the
    rest: a caption stored as "Table 1. " + "Results" came back reading
    "Table 1." with the title gone, and no text-level check would show
    it because the linker is not supposed to change text at all."""
    d = doc(para('<w:r><w:t xml:space="preserve">Table 1. </w:t>'
                 '<w:t xml:space="preserve">Results</w:t></w:r>'),
            para(run("See Table 1 for detail.")))
    out, _ = crossrefs.link(d)
    assert "Results" in "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", out))


@pytest.mark.parametrize("extra,marker", [
    ("<w:br/>", "<w:br/>"),
    ('<w:footnoteReference w:id="3"/>', "footnoteReference"),
    ("<w:tab/>", "<w:tab/>"),
])
def test_a_run_child_beside_the_text_survives_linking(extra, marker):
    """A run may carry a break, a tab, a drawing or a note reference
    alongside its text. None of them is visible to a text diff, so
    dropping one is silent."""
    d = doc(para(f'<w:r><w:t xml:space="preserve">Table 1. Results</w:t>'
                 f"{extra}</w:r>"),
            para(run("See Table 1 for detail.")))
    out, _ = crossrefs.link(d)
    assert marker in out, f"{marker} was dropped"


# --- number boundaries -------------------------------------------------


def test_a_hyphen_suffixed_exhibit_is_its_own_object():
    """"Table 1-A" is a different table from "Table 1". Matching the
    prefix linked the wrong one and left "-A" as orphaned plain text."""
    d = doc(para(run("Table 1. Main")), para(run("Table 1-A. Appendix")),
            para(run("See Table 1-A and Table 1.")))
    out, rep = crossrefs.link(d)
    assert sorted(rep.linked) == ["Table1", "Table1_A"]
    assert not rep.no_mention, rep.format()
    linked = dict(re.findall(
        r'<w:hyperlink w:anchor="([^"]+?)(?:txt)?">.*?<w:t[^>]*>([^<]+)',
        out, re.DOTALL))
    assert linked["Table1_A"] == "Table 1-A"


def test_a_hyphen_range_still_links_its_first_number():
    """The other side of the same hyphen: "Tables 1-3" is a RANGE, and
    refusing every hyphen would stop the 1 being linked at all. A digit
    continues a range, a letter starts a suffix."""
    d = doc(para(run("Table 1. A")), para(run("Table 2. B")),
            para(run("Table 3. C")), para(run("See Tables 1-3 for detail.")))
    _, rep = crossrefs.link(d)
    assert rep.linked == ["Table1"]


# --- idempotency reads elements, not text ------------------------------


def test_the_already_linked_check_reads_bookmarks_not_prose():
    """`w:name="Table1"` occurring anywhere — in a w:t, in some other
    attribute — read as "already bookmarked", and the caption silently
    got none."""
    d = doc(para(run('Table 1. A note on w:name="Table1" conventions')),
            para(run("See Table 1 for detail.")))
    out, _ = crossrefs.link(d)
    names = re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', out)
    assert "Table1" in names and "Table1txt" in names


# --- Russian label forms ----------------------------------------------


@pytest.mark.parametrize("phrase,matches", [
    ("рисунок 1", True), ("рисунка 1", True), ("рисунке 1", True),
    ("рисунком 1", True), ("рисунков 1", True),
    ("рисуночный 1", False), ("рисованию 1", False), ("рису 1", False),
    ("таблица 1", True), ("таблице 1", True), ("таблицы 1", True),
    ("таблицами 1", False), ("табло 1", False),
])
def test_russian_label_stems_accept_inflections_but_not_neighbours(
        phrase, matches):
    """The stem forms are deliberately loose enough for Russian case
    endings. Pinning the close non-matches is what stops a future widening
    from swallowing an unrelated word."""
    label = "Рисунок" if phrase.startswith("рис") else "Таблица"
    form = crossrefs.LABEL_FORMS[label]
    got = re.match(form + r"\s+1\b", phrase, re.IGNORECASE) is not None
    assert got is matches, phrase


# ---------------------------------------- what the mutation sweep found ---
#
# 841 mutants, 168 real survivors (2026-08-11), and every one below was
# CONFIRMED by applying it to the source and watching the whole suite
# stay green. The narrow suite invents survivors on its own — three
# candidates from the same run turned out to be covered by test_cli.py —
# so a survivor is a question until the full suite has been asked.


def test_a_report_says_every_kind_of_thing_it_found():
    """Four survivors sat on format()'s branches. A report that counts
    what it will not name is the failure compare's renderer had, where
    eleven mutants each emptied one loop and none could be killed."""
    rep = crossrefs.LinkReport()
    rep.linked.append("Table1")
    rep.no_mention.append("Table2")
    rep.no_caption.append("Figure9")
    rep.field_form.append("Table3")
    rep.notes["Table4"] = "mention found but its label is split across runs"
    out = rep.format()
    assert "linked 1" in out
    assert "Table2" in out and "no in-text mention" in out
    assert "Figure9" in out and "no caption" in out
    assert "Table3" in out and "WORD FIELD" in out
    assert "Table4" in out and "split across runs" in out


# --- the mention that is already a hyperlink: which MODE comes back -----

def _already_linked(anchor: str, *, legacy_in_gap: str = "") -> str:
    mention = para(run("As "),
                   f'<w:hyperlink w:anchor="{anchor}">'
                   + run("Table 1") + "</w:hyperlink>",
                   run(" shows, the gap is wide."))
    gap = (f'<w:bookmarkStart w:id="77" w:name="{legacy_in_gap}"/>'
           '<w:bookmarkEnd w:id="77"/>') if legacy_in_gap else ""
    return doc(para(run("Opening prose.")), mention,
               gap + para(run("Table 1. Employment by age")))


@pytest.mark.parametrize("anchor, note, legacy", [
    ("Table1", "wrapped an existing hyperlink", ""),
    ("fig4_caption", "retargeted legacy anchor", "fig4_caption"),
    ("Figure7", "kept the author's own anchor", ""),
])
def test_every_mode_reaches_the_report(anchor, note, legacy):
    """`mode == "NOT-FOUND"` and `mode != "linked"` are what put these in
    the report, and both survived as ORDERINGS (`<`, `>`): one fixture
    puts every value on one side of a string comparison, so half of all
    real disagreements pass. The fix is fixtures on both sides, which is
    what these three are — the same shape as the guard survivors on
    revision's gates."""
    _, rep = crossrefs.link(_already_linked(anchor, legacy_in_gap=legacy))
    assert note in rep.notes.get("Table1", ""), rep.format()
    assert rep.linked == ["Table1"]


def test_a_split_label_is_reported_as_a_mention_it_could_not_link():
    """The "NOT-FOUND" mode itself: visible_text finds the label, the
    run walk cannot, and the object must be reported rather than
    silently skipped."""
    xml = doc(para(run("As Tabl"), run("e 1 shows, the gap is wide.")),
              para(run("Table 1. Employment by age")))
    _, rep = crossrefs.link(xml)
    assert rep.no_mention == ["Table1"]
    assert "split across runs" in rep.notes["Table1"]


# --- link_more: two mentions in ONE paragraph ---------------------------

def test_link_more_links_two_mentions_in_one_paragraph():
    """The suite had never put two mentions in one paragraph.

    `sorted(todo, reverse=True)` is what the sweep flagged, and chasing
    it settled a question rather than finding a bug: the order is
    EQUIVALENT here, because `wrap_visible_span` takes VISIBLE-text
    offsets and wrapping a span changes no visible text. Bottom-up
    matters where a pass splices XML — `link` does, and is written that
    way for the reason `link_more` does not need to be."""
    xml = doc(
        para(run("Both Table 1 and Table 2 report the same gradient.")),
        para(run("Table 1. First")), para(run("Table 2. Second")))
    out, counts = crossrefs.link_more(xml)
    assert counts == {"Table1": 1, "Table2": 1}
    body = paragraph_holding(out, "Both Table 1 and Table 2")
    assert "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", body)) == \
        "Both Table 1 and Table 2 report the same gradient."
    assert 'w:anchor="Table1"' in body and 'w:anchor="Table2"' in body


def test_link_more_is_a_no_op_on_a_second_run():
    """A linked mention is masked out of the next scan, so a second run
    plans nothing."""
    xml = doc(para(run("See Table 1 for the gradient.")),
              para(run("Table 1. First")))
    once, first = crossrefs.link_more(xml)
    twice, again = crossrefs.link_more(once)
    assert first == {"Table1": 1} and again == {}
    assert twice == once


def test_link_more_claims_a_span_once_when_a_caption_is_duplicated():
    """`... or span in claimed` as `and` links the same span twice, and
    the second wrap lands inside the markup the first one wrote.

    It needs a DUPLICATE caption to show: two Caption objects of one
    name put two identical patterns in the list, and `claimed` is the
    only thing between them. A paper gets there by copying a table and
    editing the copy — `link` has a report line for exactly that ("only
    the first linked"), so it is a shape this toolkit already meets."""
    xml = doc(para(run("See Table 1 for the gradient.")),
              para(run("Table 1. First")),
              para(run("Table 1. A copy nobody renumbered")))
    out, counts = crossrefs.link_more(xml)
    assert counts == {"Table1": 1}, counts
    body = paragraph_holding(out, "See Table 1 for the gradient.")
    assert body.count("<w:hyperlink") == 1, body


# --- the loop must not stop at the first thing it skips ------------------

def test_link_keeps_going_past_a_caption_it_skips():
    """Every `continue` in `link` survived as a `break`: nothing had a
    second caption AFTER a skipped one, so a loop that stopped early was
    indistinguishable from one that carried on."""
    xml = doc(
        para(run("Both Table 1 and Table 2 matter.")),
        para(run("Table 1. First")),
        para(run("Table 2. Second")),
    )
    once, _ = crossrefs.link(xml, only=["Table1"])
    _twice, rep = crossrefs.link(once)
    assert rep.already_linked == ["Table1"]
    assert rep.linked == ["Table2"], rep.format()


def test_a_caption_with_only_one_of_its_two_bookmarks_is_not_skipped():
    """`and` read as `or`: half an apparatus counts as linked, and the
    pass that would have completed it walks past."""
    half = doc(
        para(run("As Table 1 shows, the gap is wide.")),
        para('<w:bookmarkStart w:id="5" w:name="Table1"/>'
             '<w:bookmarkEnd w:id="5"/>' + run("Table 1. Employment")))
    out, rep = crossrefs.link(half)
    assert rep.already_linked == []
    assert rep.linked == ["Table1"]
    assert 'w:name="Table1txt"' in out


# --- audit ---------------------------------------------------------------

def test_audit_separates_a_half_linked_pair_from_a_linked_one():
    xml = doc(
        para('<w:bookmarkStart w:id="1" w:name="Table1"/>'
             '<w:bookmarkEnd w:id="1"/>' + run("Table 1. Caption only")),
        para('<w:bookmarkStart w:id="2" w:name="Figure2txt"/>'
             '<w:bookmarkEnd w:id="2"/>' + run("Figure 2. Mention only")),
    )
    got = crossrefs.audit(xml)
    assert got["caption_only"] == ["Table1"]
    assert got["mention_only"] == ["Figure2"]
    assert got["linked"] == []


@pytest.mark.parametrize("bookmark, caption, misnamed", [
    ("Figure6", "Figure 5. Life expectancy", True),    # LI7's own case
    ("Table1", "Figure 1. Life expectancy", True),     # the LABEL half
    ("Figure5", "Figure 5. Life expectancy", False),
])
def test_audit_reads_both_halves_of_a_misnamed_bookmark(bookmark, caption,
                                                        misnamed):
    """LI7's "Figure 5" caption carries bookmark Figure6 — every link
    works, one renumbering behind. Fourteen survivors sat on that
    comparison, and a fixture that only ever disagrees about the NUMBER
    cannot tell the label half from a constant."""
    xml = doc(para(f'<w:bookmarkStart w:id="1" w:name="{bookmark}"/>'
                   '<w:bookmarkEnd w:id="1"/>' + run(caption)))
    got = crossrefs.audit(xml)["misnamed"]
    assert bool(got) is misnamed, got


# --- what the crossrefs run of 2026-08-18 found -------------------------
#
# 20.8 % real survival, the least-pinned module in the package now that
# the others have had their rounds, and 14 of the 91 survivors sit on ONE
# line of `_caption_bookmarks`:
#
#     gap_from = prev_close + len("</w:p>") if prev_close != -1 else 0
#
# It decides how far back the scan for "bookmarks that already point at
# this caption" reaches. The test above proves it reaches into the GAP
# before the caption; nothing proved where it STOPS, and a scan that
# starts at the top of the document calls every bookmark in the paper a
# legacy name for this one caption.
#
# Two of the fourteen cannot be killed, and the argument is short enough
# to keep (`tools/kill_check.py`, expect_kill=False):
#
# * `prev_close | 6` and `prev_close - 6` both move the window's start by
#   at most six characters, and those six ARE the `</w:p>` tag — no
#   `<w:bookmarkStart` can begin inside it, so the scope holds the same
#   bookmarks either way;
# * the `prev_close != -1` fallback is unobservable for the same reason.
#   Without it a caption in the first paragraph scans from offset 5
#   instead of 0, and the first five characters of any document are
#   `<w:do`.


def test_a_bookmark_in_an_EARLIER_paragraph_is_not_this_captions():
    """`prev_close + len("</w:p>")` — the scan starts after the previous
    paragraph closes, so what is inside that paragraph belongs to it.
    Mutated to `&` or `|` the window opens near the start of the
    document, and a link to something else entirely is reported as a
    legacy name for this caption and retargeted away from the object the
    author pointed it at."""
    elsewhere = para('<w:bookmarkStart w:id="5" w:name="other_thing"/>',
                     run("An earlier paragraph with a bookmark of its own."),
                     '<w:bookmarkEnd w:id="5"/>')
    mention = para(run("As "),
                   '<w:hyperlink w:anchor="other_thing">' + run("Table 1")
                   + "</w:hyperlink>", run(" shows."))
    xml = doc(elsewhere, mention, para(run("Table 1. Employment by age")))

    _out, report = crossrefs.link(xml)

    assert report.linked == ["Table1"]
    assert "kept the author's own anchor" in report.notes["Table1"]
    assert "retargeted" not in report.notes["Table1"]


def test_a_caption_in_the_FIRST_paragraph_still_finds_its_own_bookmarks():
    """`if prev_close != -1 else 0`: there is no previous `</w:p>` to
    measure from, and the fallback is the top of the document. Without
    it the window starts at 5 — `-1 + len("</w:p>")` — and a legacy
    bookmark on the caption itself goes unseen, so a link that already
    resolves is reported as unlinked and rewritten."""
    caption = para('<w:bookmarkStart w:id="9" w:name="tbl1_caption"/>',
                   run("Table 1. Employment by age"),
                   '<w:bookmarkEnd w:id="9"/>')
    mention = para(run("As "),
                   '<w:hyperlink w:anchor="tbl1_caption">' + run("Table 1")
                   + "</w:hyperlink>", run(" shows."))

    _out, report = crossrefs.link(doc(caption, mention))

    assert report.linked == ["Table1"]
    assert "retargeted legacy anchor 'tbl1_caption'" in report.notes["Table1"]
