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
