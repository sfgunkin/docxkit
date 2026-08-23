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


def test_the_caption_is_re_found_by_NAME_not_by_where_it_sorts():
    """`c.name == cap.name`, twice — every edit shifts the offsets, so
    the caption is looked up again by name before it is touched.

    Written as `>=` the lookup takes the first caption that sorts at or
    after the one wanted, and a paper with a table before a figure hands
    it "Table1" when it asked for "Figure1" — T sorts after F. The
    figure's bookmarks are then built against the table's caption, and
    the report still counts three linked objects with balanced ids,
    which is all the fixture beside this one checks.

    So this asserts WHICH names came out and where each one landed."""
    xml = doc(
        para(run("Table 1 and Table 2 and Figure 1 follow.")),
        para(run("Table 1. One")),
        para(run("Table 2. Two")),
        para(run("Figure 1. Three")),
    )

    out, report = crossrefs.link(xml)

    assert sorted(report.linked) == ["Figure1", "Table1", "Table2"]
    assert sorted(re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"',
                             out)) == [
        "Figure1", "Figure1txt", "Table1", "Table1txt", "Table2", "Table2txt"]
    # and each caption bookmark is on its OWN caption
    for name, caption in (("Figure1", "Figure 1. Three"),
                          ("Table1", "Table 1. One"),
                          ("Table2", "Table 2. Two")):
        assert f'w:name="{name}"' in paragraph_holding(out, caption), name


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


def test_unlink_reports_NOTHING_removed_from_a_document_with_no_exhibits():
    """`return xml, 0`. The count is what a batch prints and what a
    person checks a step by — "24 removed" is the number that hid a
    wrong answer on Parental_style — so the no-exhibit answer has to be
    zero, not one. A paper's front matter and its response letter both
    go through this call with nothing to remove."""
    xml = doc(para(run("Prose with no exhibit in it at all.")))

    out, removed = crossrefs.unlink(xml)

    assert removed == 0
    assert out == xml, "and nothing touched"


def test_the_split_label_refusal_quotes_SIXTY_characters_of_the_caption():
    """`visible_text(para_xml)[:60]`. The message is how a person finds
    the caption Word split, and a caption is a sentence: uncut, the
    refusal prints the whole of it, and a run of them prints a page.
    Every fixture here has a caption short enough that the cut does
    nothing."""
    long_caption = ("Table 1. Employment by age group and sex, urban and "
                    "rural, 2019 to 2024, weighted")
    assert len(long_caption) > 60
    xml = doc(
        para(run("As Table 1 shows.")),
        para(run("Table"), run(long_caption[len("Table"):])),  # rsid split
    )

    with pytest.raises(AnchorError) as exc:
        crossrefs.link(xml)

    message = str(exc.value)
    assert "split across runs" in message
    quoted = message.split("(", 1)[1].rsplit(")", 1)[0]
    assert quoted == repr(long_caption[:60]), quoted


def test_an_EMPTY_run_before_the_caption_label_is_stepped_over():
    """`continue`, not `break`, in the walk that finds the label. Word
    leaves empty runs everywhere — an rsid split, a deleted character,
    a language mark — and one in front of the caption puts a `w:t` with
    nothing in it ahead of the label.

    Under `break` the walk gives up on the first node that does not
    start with the label, which is that empty one, and the caption is
    refused as "split across runs" — the paper is stopped over a run
    holding no text at all."""
    xml = doc(
        para(run("As Table 3 shows, employment rises.")),
        para(run(""), run("Table 3. Employment by age")),
    )

    out, report = crossrefs.link(xml)

    assert report.linked == ["Table3"], report.format()
    caption = paragraph_holding(out, "Table 3. Employment by age")
    assert 'w:anchor="Table3txt"' in caption


def test_a_caption_that_could_not_be_linked_does_not_stop_the_ones_after():
    """`continue` again, in `link`'s own loop, on the NOT-FOUND arm: a
    mention whose label Word split across runs is reported and the run
    goes on. `break` there means the FIRST such caption ends the pass,
    and every exhibit after it is left plain while the report names only
    that one — the shape of a paper whose Table 1 was edited in Word."""
    xml = doc(
        para(run("As Tabl"), run("e 1 shows, employment rises.")),
        para(run("Table 1. Employment")),
        para(run("And Table 2 shows more.")),
        para(run("Table 2. Employment by sex")),
    )

    out, report = crossrefs.link(xml)

    assert report.no_mention == ["Table1"]
    assert report.linked == ["Table2"], report.format()
    assert 'w:anchor="Table2"' in out


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


def test_a_document_where_NOTHING_is_linked_is_not_a_clean_report():
    """A caption carrying NEITHER bookmark fell through all three
    buckets and was counted nowhere — which is the state of every
    caption in a manuscript nobody has run this over, and the one case
    the audit exists to report. Aging_Well's five exhibits printed the
    same all-zero line as a paper with no exhibits at all, and the
    paper's notes recorded it as "finds no captions" (2026-08-21)."""
    xml = doc(
        para(run("As Table 1 and Figure 2 show, the pattern holds.")),
        para(run("Table 1. Descriptive statistics")),
        para(run("Figure 2. The gap over time")),
    )

    state = crossrefs.audit(xml)

    assert state["unlinked"] == ["Figure2", "Table1"]
    assert state["linked"] == state["caption_only"] == []
    # …and once linked, they move out of it
    linked, _ = crossrefs.link(xml)
    assert crossrefs.audit(linked)["unlinked"] == []


def test_the_LABELS_are_the_papers_own_word_for_its_exhibits():
    """Aging_Well's fifth exhibit is a BOX. `link` has always taken the
    label set — the caption grammar fits — but a paper could not say so
    without a script."""
    xml = doc(
        para(run("Box 1 sets out how bounded rationality interacts.")),
        para(run("Box 1. Bounded rationality and the capability framework")),
    )

    assert crossrefs.audit(xml)["unlinked"] == []      # not an exhibit yet

    labels = ("Figure", "Table", "Box")
    assert crossrefs.audit(xml, labels=labels)["unlinked"] == ["Box1"]
    linked, report = crossrefs.link(xml, labels=labels)
    assert report.complete
    assert crossrefs.audit(linked, labels=labels)["linked"] == ["Box1"]


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
    # The caption carries no link home, so this is `unreached` rather
    # than `linked` — both bookmarks are present and half the round trip
    # is missing, which is the state the bucket was added for. The
    # subject here is the line below it.
    assert got["unreached"] == ["Table5: the caption links back to nothing"]
    assert not got["linked"] and not got["dangling"]
    assert len(got["misplaced_anchor"]) == 1, got["misplaced_anchor"]
    line = got["misplaced_anchor"][0]
    assert line.startswith("Table5txt sits at ¶3")
    assert "the first at ¶1" in line


def test_the_misplaced_line_names_the_FIRST_mention_that_leads_it():
    """`ahead[0]`. The line exists to send a reader somewhere, and where
    it sends them is the EARLIEST mention that links past the marker —
    a later one is a place the reader has already scrolled through. One
    earlier mention makes `ahead[0]`, `ahead[1]` and `ahead[-1]` the
    same paragraph, which is what every fixture here had."""
    xml = doc(
        _mention("Table5", "Table 5"),                      # ¶1, the first
        _mention("Table5", "Table 5"),                      # ¶2, also ahead
        para(run("Intervening prose.")),
        _mention("Table5", "Table 5", mark="Table5txt"),    # ¶4, the marker
        para('<w:bookmarkStart w:id="1" w:name="Table5"/>'
             '<w:bookmarkEnd w:id="1"/>' + run("Table 5. The caption")),
    )

    (line,) = crossrefs.audit(xml)["misplaced_anchor"]

    assert line.startswith("Table5txt sits at ¶4")
    assert "2 earlier mention(s)" in line
    assert "the first at ¶1" in line, line


def test_an_earlier_mention_is_found_from_paragraph_TEN_onwards():
    """`_where(paras, pos) != home`, and `_where` answers a STRING.

    Compared with `<` instead — the mutation this kills — the check
    reads "¶9" as coming AFTER "¶10", because that is what string order
    says, and a mention in a single-digit paragraph drops out of the
    finding as soon as the marker reaches the tenth. A paper's exhibits
    are not in its first nine paragraphs.

    The fixtures above are three and four paragraphs long, where every
    label is one digit and the two orders agree. The nine-then-ten pair
    is the shortest one where they do not."""
    filler = [para(run(f"Paragraph {i} of the introduction."))
              for i in range(1, 9)]
    xml = doc(
        *filler,                                         # ¶1..¶8
        _mention("Table5", "Table 5"),                   # ¶9, the first
        _mention("Table5", "Table 5", mark="Table5txt"),  # ¶10, the marker
        para('<w:bookmarkStart w:id="1" w:name="Table5"/>'
             '<w:bookmarkEnd w:id="1"/>' + run("Table 5. The caption")),
    )

    (line,) = crossrefs.audit(xml)["misplaced_anchor"]

    assert line.startswith("Table5txt sits at ¶10")
    assert "1 earlier mention(s)" in line, line
    assert "the first at ¶9" in line, line


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
    # and its END too: Word pairs the two by id, and one left behind is
    # a document that opens with a repair prompt rather than a document
    # with a stray tag in it
    assert "bookmarkEnd" not in plain
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


def test_a_report_is_complete_only_when_BOTH_halves_are_empty():
    """`not self.no_mention and not self.no_caption` is what the CLI
    exits on — `return 0 if report.complete else 1` — so each half has
    to be able to fail it alone. The suite asserted the caption half
    only, and a report with an unlinkable MENTION in it would have
    exited 0: a batch step that says the paper is linked when it is
    not."""
    clean = crossrefs.LinkReport()
    clean.linked.append("Table1")
    assert clean.complete is True

    no_mention = crossrefs.LinkReport()
    no_mention.no_mention.append("Table2")
    assert no_mention.complete is False

    no_caption = crossrefs.LinkReport()
    no_caption.no_caption.append("Figure9")
    assert no_caption.complete is False


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

def test_a_legacy_bookmark_on_ANOTHER_caption_is_not_this_one_s_to_take():
    """How far back `_caption_bookmarks` reaches. The scope opens just
    after the previous paragraph's `</w:p>`, because a zero-length
    bookmark often sits BETWEEN paragraphs rather than inside the
    caption — and not one character further, because anything earlier
    belongs to another exhibit.

    The distinction is the difference between the two modes the linker
    reports. A bookmark in this caption's own gap is the same
    destination under an older name, so the link is retargeted; one on
    a DIFFERENT caption is where the author deliberately sent a reader,
    and repointing it at this exhibit breaks a cross-reference that was
    right. AFI's "Figure 9.a" links to Figure 7's caption on purpose.

    Every fixture for these modes puts the legacy bookmark in the gap
    that belongs to the caption being linked, so a scope that reaches
    back over the whole document reads the same."""
    legacy = ('<w:bookmarkStart w:id="77" w:name="fig4_caption"/>'
              '<w:bookmarkEnd w:id="77"/>')
    xml = doc(
        para(run("As "),
             '<w:hyperlink w:anchor="fig4_caption">' + run("Table 2")
             + "</w:hyperlink>",
             run(" shows, the gap is wide.")),
        legacy + para(run("Table 1. Employment by age")),
        para(run("Table 2. Employment by sex")),
    )

    _out, report = crossrefs.link(xml)

    assert "kept the author's own anchor" in report.notes.get("Table2", ""), \
        report.format()
    assert "retargeted" not in report.format()


def test_a_citation_link_BEFORE_the_mention_is_stepped_over():
    """`continue`, not `break`. The walk over a paragraph's existing
    hyperlinks skips the ones that do not hold the label, and the very
    first hyperlink in an academic sentence is usually a citation —
    `link_crossrefs` runs after `link_citations`, so by the time this
    walk happens every "(Smith 2020)" in the paragraph is already a
    hyperlink and sits in front of the mention it shares a sentence
    with.

    Under `break` the walk gives up at that first citation and falls
    through to the plain-text path, which cannot find the label inside
    a hyperlink's run: the mention comes back reported as unlinkable in
    exactly the paragraphs a finished manuscript is made of."""
    mention = para(run("As "),
                   '<w:hyperlink w:anchor="ref_Smith2020">'
                   + run("Smith (2020)") + "</w:hyperlink>",
                   run(" notes in "),
                   '<w:hyperlink w:anchor="Table1">'
                   + run("Table 1") + "</w:hyperlink>",
                   run(", the gap is wide."))
    xml = doc(mention, para(run("Table 1. Employment by age")))

    out, rep = crossrefs.link(xml)

    assert rep.linked == ["Table1"], rep.format()
    assert "wrapped an existing hyperlink" in rep.notes.get("Table1", "")
    assert 'w:anchor="ref_Smith2020"' in out, "the citation link is intact"


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


def test_a_mention_ALREADY_inside_a_link_is_invisible_to_the_scan():
    """What stops `link_more` linking a mention twice is the MASK.

    `masked_visible_text` gives back the characters inside a hyperlink
    as NUL, and neither pattern can match one — both spans are an
    escaped label, `\\s+` and the caption's own digits, and no character
    class in either admits NUL. So an already-linked mention is not
    skipped by a guard, it is never found at all, and that is what this
    pins: half-linked prose, where one mention of the same table is a
    link and the other is not.

    (The loop used to test each span for NUL as well. It could not fire
    — checked structurally, by brute force over 400k NUL-bearing strings
    and by asserting it under the whole suite — and it left five
    permanent survivors on a line no input reaches.)"""
    linked = ('<w:hyperlink w:anchor="Table1">' + run("Table 1")
              + "</w:hyperlink>")
    xml = doc(para(run("As "), linked, run(" shows, and Table 1 again.")),
              para(run("Table 1. First")))

    out, counts = crossrefs.link_more(xml)

    assert counts == {"Table1": 1}, "only the plain one"
    body = paragraph_holding(out, "As Table 1 shows, and Table 1 again.")
    assert body.count("<w:hyperlink") == 2, body


def test_an_EMPTY_paragraph_does_not_end_the_walk_either():
    """`if not masked.strip("\\x00 \\t"): continue` — the skip for a
    paragraph with nothing readable in it. Word writes empty paragraphs
    between blocks the way a typist writes blank lines, and the walk
    runs BACKWARDS, so `break` on the first one stops at the last blank
    line in the document and leaves every mention above it plain.

    The paragraph beside this one has text in it and no mention, which
    is a different skip two branches further down."""
    # an empty RUN, not a self-closing `<w:p/>`: the paragraph walk is a
    # regex over the paired form, so the self-closing one never reaches
    # this branch at all
    xml = doc(para(run("See Table 1 for the gradient.")),
              para(run("")),
              para(run("Table 1. First")))

    _out, counts = crossrefs.link_more(xml)

    assert counts == {"Table1": 1}, counts


def test_a_paragraph_with_nothing_to_link_does_not_end_the_walk():
    """`continue`, not `break`, and the walk runs BACKWARDS — from the
    end of the document to the start — so `break` on the first paragraph
    with no mention in it stops at whatever prose comes last and leaves
    everything ABOVE it plain. A paper's exhibits are all above its last
    plain paragraph.

    The fixtures here are all mention, mention, caption; a document is
    mostly prose."""
    xml = doc(para(run("See Table 1 for the gradient.")),
              para(run("An intervening paragraph with no exhibit in it.")),
              para(run("Table 1. First")))

    _out, counts = crossrefs.link_more(xml)

    assert counts == {"Table1": 1}, counts


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

def test_a_duplicated_caption_claims_a_CONTINUATION_span_once_too():
    """The other half of `span in claimed`. A duplicated caption puts
    two identical patterns in the list, and the second pass re-finds
    every span the first one already planned — including the bare
    number of a range, which is the shortest span this pass wraps and
    the one where a second wrap lands inside the first one's markup.

    The fixture beside this one proves the main pattern's half; the
    continuation's own `claimed` test had nothing asking about it."""
    xml = doc(
        para(run("Tables 2 and 1 report the same gradient.")),
        para(run("Table 1. First")),
        para(run("Table 1. A copy nobody renumbered")),
        para(run("Table 2. Second")),
    )

    out, counts = crossrefs.link_more(xml)

    assert counts == {"Table1": 1, "Table2": 1}, counts
    body = paragraph_holding(out, "Tables 2 and 1 report the same gradient.")
    assert body.count("<w:hyperlink") == 2, body
    assert "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", body)) == \
        "Tables 2 and 1 report the same gradient."


# Both `continue`s inside those two loops are EQUIVALENT to `break`, and
# argued rather than contrived around (`tools/kill_check.py`,
# expect_kill=False). A span is already in `claimed` only when an
# IDENTICAL pattern ran before it — which means a duplicated caption,
# and then every later span in the same loop is claimed as well, so the
# loop has nothing left to do when it stops. The one exception needs two
# captions of different labels whose continuation patterns reach the
# same digits ("Figures 2 and Tables 3 and 1"), which is not a sentence
# a paper writes, and where which caption should claim it is a coin flip
# rather than a behaviour to pin.


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
    # Both halves again, from the OTHER side of the comparison. Every
    # row above disagrees upward — "Table" after "Figure", 6 after 5 —
    # so `>` in place of `!=` reads exactly like it on all three, and
    # every disagreement a real paper makes downward goes unreported.
    ("Figure1", "Table 1. Life expectancy", True),     # label, downward
    ("Figure4", "Figure 5. Life expectancy", True),    # number, downward
    # And a two-digit exhibit, correctly named. CPython caches every
    # ONE-character string, so `!=` written as `is not` cannot be seen
    # on a single-digit number: both sides are the same object. "10" is
    # not cached, and a paper with ten tables has one.
    ("Table10", "Table 10. Life expectancy", False),
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


# `_run_parts` had 11 survivors — the three offsets that cut one run
# into "before the label", "the label" and "after it". The docstring
# names what they cost: a caption stored as two `w:t` elements came back
# reading "Table 1." with the title gone, and no text-level check shows
# it, because the linker is not supposed to change text at all.


def _parses(xml: str) -> None:
    """The three fragments have to be well-formed XML, which is what the
    open tag's own slice and the body's end offset decide: one character
    either way emits `<w:r ...><` or a run that closes twice, and every
    text-level assertion in this file still passes over it."""
    from lxml import etree
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
          '2006/main"')
    etree.fromstring(xml.replace("<w:document>", f"<w:document {ns}>", 1)
                     .encode("utf-8"))


def test_splitting_a_run_keeps_its_attributes_properties_and_SIBLINGS():
    """Everything the run carried has to ride out on one of the three
    fragments: the open tag with its `w:rsidR`, the `w:rPr` on each
    piece, and — the finding this function exists for — the SECOND
    `w:t`, which sits after the matched one and belongs to the trailing
    fragment."""
    from docxkit import text_of
    rich = ('<w:r w:rsidR="00AB12CD">'
            '<w:rPr><w:i/><w:lang w:val="ru-RU"/></w:rPr>'
            '<w:t xml:space="preserve">As Table 1 shows, </w:t>'
            "<w:t>the gap is wide.</w:t></w:r>")
    xml = doc(para(rich), para(run("Table 1. Employment by age")))

    out, report = crossrefs.link(xml)

    assert report.linked == ["Table1"]
    _parses(out)
    mention = paragraph_holding(out, "the gap is wide.")
    assert text_of(mention) == "As Table 1 shows, the gap is wide."
    assert mention.count('w:rsidR="00AB12CD"') == 3, "one per fragment"
    assert mention.count("<w:lang w:val=\"ru-RU\"/>") == 3
    assert "<w:t>the gap is wide.</w:t>" in mention, "the second w:t"
    assert mention.count('<w:rStyle w:val="Hyperlink"/>') == 1


def test_the_label_fragment_takes_the_hyperlink_style_FIRST():
    """CT_RPr is a sequence and `rStyle` opens it, so the style goes
    ahead of what the run already declared rather than beside it."""
    rich = ('<w:r><w:rPr><w:i/></w:rPr>'
            "<w:t>As Table 1 shows.</w:t></w:r>")

    out, _ = crossrefs.link(doc(para(rich),
                                para(run("Table 1. Employment by age"))))

    assert ('<w:rPr><w:rStyle w:val="Hyperlink"/><w:i/></w:rPr>'
            in paragraph_holding(out, "As Table 1 shows."))


# Six of `link`'s survivors are its `continue`s mutated to `break`. Every
# fixture in this file has one caption, or a set where the first is the
# one that links — so the loop never had to carry on past a caption it
# declined. A paper has fifteen exhibits and any of them can be the one
# nobody mentions.


def _numbered_caption(n: int, kind: str = "Table") -> str:
    return para(run(f"{kind} {n}. The {kind.lower()} {n} caption"))


def _numbered_mention(n: int, kind: str = "Table") -> str:
    return para(run(f"As {kind} {n} shows, the gap is wide."))


def test_a_caption_NOBODY_mentions_does_not_stop_the_ones_after_it():
    """`continue`, not `break`. Table 1 has no mention anywhere, and
    under `break` Table 2 and Table 3 are never looked at — a report
    that reads "1 unmentioned" on a paper with two unlinked exhibits and
    no sign that the pass stopped early."""
    xml = doc(_numbered_caption(1),
              _numbered_mention(2), _numbered_caption(2),
              _numbered_mention(3), _numbered_caption(3))

    _out, report = crossrefs.link(xml)

    assert report.no_mention == ["Table1"]
    assert report.linked == ["Table2", "Table3"]


def test_a_DUPLICATE_caption_does_not_stop_the_ones_after_it():
    """Two exhibits numbered the same is an ordinary manuscript error —
    a copied block, usually — and the note says only the first is
    linked. The pass still has the rest of the paper to do."""
    xml = doc(_numbered_mention(1), _numbered_caption(1), _numbered_caption(1),
              _numbered_mention(2), _numbered_caption(2))

    _out, report = crossrefs.link(xml)

    assert "duplicate caption" in report.notes["Table1"]
    assert report.linked == ["Table1", "Table2"]


def test_a_caption_ALREADY_linked_does_not_stop_the_ones_after_it():
    """Re-running the linker is the ordinary case — it is how a paper
    checks the job is done — and the second run must still reach the
    exhibits added since."""
    first, _ = crossrefs.link(doc(_numbered_mention(1), _numbered_caption(1)))
    added = _numbered_mention(2) + _numbered_caption(2)
    xml = first.replace("</w:body>", added + "</w:body>")

    _out, report = crossrefs.link(xml)

    assert report.already_linked == ["Table1"]
    assert report.linked == ["Table2"]


def test_a_CONTINUATION_already_linked_is_not_linked_again():
    """The masking check on the continuation branch, which the repeat
    branch's idempotence test does not reach: `masked_visible_text`
    fills a linked span with NULs, and a second pass has to see them.
    Under `and` in place of `or` the bare "5" is wrapped a second time,
    nesting a hyperlink inside a hyperlink — which Word opens and no
    text-level check sees.

    It also says WHAT each link covers: the head takes "Tables 3" and
    the continuation takes the bare number alone, which is the whole
    point of the capture group."""
    import re as _re

    from docxkit import text_of
    xml = doc(
        para(run("Table 3 shows one thing.")),
        para(run("Table 5 shows a third.")),
        para(run("Results appear in Tables 3 to 5, as noted.")),
        para(run("Table 3. First")),
        para(run("Table 5. Third")),
    )
    xml, _ = crossrefs.link(xml)

    once, first = crossrefs.link_more(xml)
    twice, second = crossrefs.link_more(once)

    assert first == {"Table3": 1, "Table5": 1}
    assert second == {} and twice == once, "a second pass links nothing"
    p = paragraph_holding(once, "as noted")
    wrapped = [(m.group(1), text_of(m.group(2))) for m in _re.finditer(
        r'<w:hyperlink w:anchor="([^"]+)">(.*?)</w:hyperlink>', p, _re.DOTALL)]
    assert wrapped == [("Table3", "Tables 3"), ("Table5", "5")]


def test_a_continuation_number_ALREADY_linked_by_hand_is_left_alone():
    """A paper that linked one number by hand: the label is plain, the
    number is inside somebody else's hyperlink, and `link_more` has to
    leave it there rather than wrap a hyperlink around a hyperlink.

    What does the leaving is the MASK, not the check beside it.
    `masked_visible_text` fills linked characters with NUL, so the
    pattern then has no "5" to match at all. The NUL check in
    `link_more` is unreachable in both branches and its mutants
    survive on purpose: every element of `_mention_re`, and of the
    continuation's CAPTURE, is a literal, a whitespace class, a word
    boundary or a zero-width lookahead — none of which matches NUL,
    so a match cannot contain one. The guard stays for the day a
    pattern grows a character class that can (the continuation's own
    "[^.;:()]" repeat already does, outside the capture), and
    `tools/kill_check.py` records the two as expect_kill=False.
    """
    import re as _re

    from docxkit import text_of
    hand_linked = (
        '<w:p><w:r><w:t xml:space="preserve">Results appear in Tables 3 to '
        '</w:t></w:r><w:hyperlink w:anchor="Table5"><w:r><w:t>5</w:t></w:r>'
        "</w:hyperlink><w:r><w:t>, as noted.</w:t></w:r></w:p>")
    xml = doc(
        para(run("Table 3 shows one thing.")),
        para(run("Table 5 shows a third.")),
        hand_linked,
        para(run("Table 3. First")),
        para(run("Table 5. Third")),
    )
    xml, _ = crossrefs.link(xml)

    out, counts = crossrefs.link_more(xml)

    assert counts == {"Table3": 1}, "the 5 was already somebody's link"
    p = paragraph_holding(out, "as noted")
    links = [(m.group(1), text_of(m.group(2))) for m in _re.finditer(
        r'<w:hyperlink w:anchor="([^"]+)">(.*?)</w:hyperlink>', p, _re.DOTALL)]
    assert links == [("Table3", "Tables 3"), ("Table5", "5")]
    assert "<w:hyperlink" not in p[p.index("</w:hyperlink>"):
                                   p.rindex("<w:hyperlink")], "not nested"


# --- offsets that are not near zero (2026-08-19) ------------------------
#
# Both rewrites here cut a run at `tm.start() - r_open`: where the text
# node starts, measured from where its run starts. Every fixture in this
# file uses a run with no properties, so that distance is five
# characters and the subtraction agrees with `%`, `//` and `>>` on
# numbers that small. crossrefs measured 12.9 % with its survivors
# clustered on exactly those two lines.
#
# What makes the distance real is `w:rPr`. Word writes one on every run
# it has ever touched — fonts, size, language, and the complex-script
# twin of each — and 210 characters of properties between `<w:r>` and
# `<w:t>` is an ordinary paragraph, not a constructed one.

FAT_RPR = ('<w:rPr><w:rFonts w:ascii="Times New Roman" '
           'w:hAnsi="Times New Roman" w:eastAsia="Times New Roman" '
           'w:cs="Times New Roman"/><w:sz w:val="24"/>'
           '<w:szCs w:val="24"/><w:lang w:val="en-GB" '
           'w:eastAsia="ru-RU"/></w:rPr>')


def _visible(xml: str) -> str:
    """Every w:t in document order, joined — what a reader sees."""
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def test_a_mention_behind_a_run_full_of_PROPERTIES_is_cut_at_the_label():
    """`tm.start() - r_open` in `_link_mention`. With 210 characters of
    run properties in front of the text node the distance is 215, and
    `%` gives 0, `//` gives 43 and `>>` gives 6 — each of them cuts the
    sentence somewhere else and re-emits the pieces in order, so the
    visible text still reads right and only the position of the link
    says it went wrong."""
    xml = doc(
        para(run("As shown in Table 1 below, it rises.", rpr=FAT_RPR)),
        para(run("Table 1. Employment by age group")),
    )

    out, report = crossrefs.link(xml)

    assert report.linked == ["Table1"]
    mention = paragraph_holding(out, "As shown in ")
    assert _visible(mention) == "As shown in Table 1 below, it rises."
    link = re.search(r'<w:hyperlink w:anchor="Table1">.*?</w:hyperlink>',
                     mention, re.DOTALL)
    assert link is not None
    assert _visible(link.group(0)) == "Table 1"


def test_a_caption_LABEL_behind_the_same_properties_is_cut_at_the_label():
    """The back-link half, in `_wrap_label`, on the same arithmetic —
    and the caption is where Word's properties actually pile up, since a
    caption style sets the font and the size explicitly."""
    xml = doc(
        para(run("Employment rises with age, see Table 2 below.")),
        para(run("Table 2. Employment by age group", rpr=FAT_RPR)),
    )

    out, _report = crossrefs.link(xml)

    caption = paragraph_holding(out, "Table 2. Employment")
    assert _visible(caption) == "Table 2. Employment by age group"
    link = re.search(r'<w:hyperlink w:anchor="Table2txt">.*?</w:hyperlink>',
                     caption, re.DOTALL)
    assert link is not None
    assert _visible(link.group(0)) == "Table 2"


def test_an_INDENTED_caption_keeps_its_leading_space_outside_the_link():
    """`content[:len(content) - len(content.lstrip())]` — the run's own
    leading whitespace stays outside the link, because a blue run of
    spaces before a caption is a rendering defect a reader reports.

    Fifteen spaces, deliberately: the two lengths this line subtracts
    are 30 and 15, and `%` gives 0 where `-` gives 15. With an ordinary
    indent the leading space is shorter than the caption text and the
    two agree, which is why every fixture passed either way."""
    xml = doc(
        para(run("See Table 3 for detail.")),
        para(run(" " * 15 + "Table 3. Detail")),
    )

    out, _report = crossrefs.link(xml)

    caption = paragraph_holding(out, "Table 3. Detail")
    link = re.search(r'<w:hyperlink w:anchor="Table3txt">.*?</w:hyperlink>',
                     caption, re.DOTALL)
    assert link is not None
    assert _visible(link.group(0)) == "Table 3"
    assert _visible(caption) == " " * 15 + "Table 3. Detail"


def test_a_MENTION_outside_any_run_is_reported_not_spliced():
    """`r_open < 0`, the guard. A `w:t` that no run opens before it is
    malformed — and the mention is IN it, so the walk reaches the line
    that measures from the run's start with no run to measure from.
    `< 0` steps over it and the caption is reported as having no
    mention; `== 0` (r_open is never 0, since every paragraph opens
    with `<w:p>`) slices from -1 instead and hands an empty string to
    the rewrite, which raises."""
    xml = doc(
        para('<w:t xml:space="preserve">As shown in Table 4 below.</w:t>'),
        para(run("Table 4. Employment")),
    )

    out, report = crossrefs.link(xml)

    assert report.linked == []
    assert report.no_mention == ["Table4"]
    assert "As shown in Table 4 below." in out


def test_a_caption_LABEL_outside_any_run_is_refused_not_spliced():
    """The same guard on the back-link side. `r_open` is -1 when no run
    opens before the `w:t` the label sits in, and `< 0` steps over it —
    the caption is then refused by name, with the message that sends a
    person to look at it.

    `== 0` in its place (r_open is never 0: a paragraph opens with
    `<w:p>`) measures the run from -1 instead, which slices from the
    LAST character of the paragraph and hands the rewrite an empty
    string. What comes back is not a refusal but whatever that
    arithmetic raises."""
    xml = doc(
        para(run("As Table 7 shows.")),
        para('<w:t xml:space="preserve">Table 7. Employment</w:t>'),
    )

    with pytest.raises(AnchorError, match="split across runs"):
        crossrefs.link(xml)


def test_ONE_malformed_text_node_does_not_cost_the_whole_paragraph():
    """`continue`, not `break`, under the guard above. The walk steps
    over the `w:t` it cannot measure from and keeps looking: a mention
    later in the same paragraph, in a run that is written properly, is
    still linkable.

    `break` there throws the paragraph away for one bad node — the
    caption is reported as having no mention at all, which is the
    report a person acts on by going and looking for a mention that is
    sitting right there."""
    xml = doc(
        para('<w:t xml:space="preserve">As Table 4 shows, </w:t>'
             + run("and Table 4 again, it rises.")),
        para(run("Table 4. Employment")),
    )

    out, report = crossrefs.link(xml)

    assert report.linked == ["Table4"], report.format()
    assert 'w:anchor="Table4"' in out
    assert "As Table 4 shows, " in out, "the malformed node is left alone"


def test_a_TAB_between_the_properties_and_the_text_survives_the_split():
    """`t_span`'s first half. `pre` is what sits between the run's
    properties and the text node being cut — a rendered tab, a footnote
    reference, a second text node — and in a run with nothing there it
    is empty whatever the arithmetic says, which is every fixture above.
    A tab is the common one: Word writes `<w:tab/>` inside the run for a
    caption or an indented sentence, and losing it moves the line."""
    xml = doc(
        para('<w:r>' + FAT_RPR + '<w:tab/><w:t xml:space="preserve">'
             "As shown in Table 5 below, it rises.</w:t></w:r>"),
        para(run("Table 5. Employment by age group")),
    )

    out, report = crossrefs.link(xml)

    assert report.linked == ["Table5"]
    mention = paragraph_holding(out, "As shown in ")
    assert mention.count("<w:tab/>") == 1
    assert _visible(mention) == "As shown in Table 5 below, it rises."
    head = mention[:mention.index("<w:hyperlink")]
    assert head.index("<w:tab/>") < head.index("As shown in ")


def test_a_TAB_before_a_caption_label_survives_the_back_link_split():
    """The same, in `_wrap_label`: a caption numbered from a list opens
    with a tab, and the label follows it in the same run."""
    xml = doc(
        para(run("Employment rises, see Table 6 below.")),
        para('<w:r>' + FAT_RPR + '<w:tab/><w:t xml:space="preserve">'
             "Table 6. Employment by age group</w:t></w:r>"),
    )

    out, _report = crossrefs.link(xml)

    caption = paragraph_holding(out, "Table 6. Employment")
    assert caption.count("<w:tab/>") == 1
    assert _visible(caption) == "Table 6. Employment by age group"


# --- what the sixth sweep left in crossrefs, and why --------------------
#
# 49 real survivors on 2026-08-19, and the tests above took 20. What is
# left is written down here rather than chased, because each one is
# equivalent by construction — every entry CONFIRMED with
# `tools/kill_check.py` (expect_kill=False) rather than assumed, and a
# survivor list that does not say which are permanent gets re-derived
# from scratch every round.
#
# * `_caption_bookmarks`, six of ten. `gap_from` opens the scope just
#   after the previous paragraph's `</w:p>`, and the spellings that
#   survive — `-`, `|`, `^`, the `!= 0` and `!= -2` and `else 1`
#   variants, and the rfind's own start — all move that offset by at
#   most the six characters of the tag itself. A
#   `<w:bookmarkStart … w:name="…"/>` element is fifty, and the regex
#   needs all of it, so a window that short can neither gain a bookmark
#   nor lose one. The four that die are the ones that move the offset
#   FAR: `*`, `%`, `>>` and `&` empty the scope, and `//` opens it near
#   the top of the document, where the test above catches it taking
#   another caption's legacy bookmark for its own.
# * the `rfind("<w:r>", 0, …)` start in `_wrap_label` and
#   `_link_mention`. A paragraph string opens with `<w:p`, so no run
#   begins at index 0 and searching from 1 finds the same run.
# * `_wrap_label`'s `continue` under that guard. The caption's prefix
#   occurs once, so the node the guard steps over is also the last one
#   that could have matched — `break` has nothing left to skip. Its
#   twin in `_link_mention` is NOT equivalent, and has a test: a
#   mention can appear twice in one paragraph.
# * `_run_parts`' `close != -1`. The run it is handed is
#   `para_xml[r_open:r_close]` with `r_close` measured past a `</w:r>`,
#   so the rfind always finds one and every spelling of "found" agrees.
# * the `count=1` in `unlink` was argued the same way — "bookmark ids
#   are unique document-wide, which is what `_next_bookmark_id` is
#   for" — and it was wrong for the same reason: uniqueness is what a
#   WELL-FORMED document has, and Word's Compare duplicates a table
#   when a block containing it is moved (S1 in the backlog), copy and
#   `w:id` and all. See the test above; the removal takes every copy
#   now.
#
#   The same argument was made here for the two in
#   `_with_hyperlink_style` — "`w:rPr` admits a single `w:rStyle`, an
#   rPr string has one opening tag" — and it was WRONG, which the round
#   of 2026-08-20 found by looking at what it excluded. Both halves are
#   true of a valid rPr and false of a valid RUN: `w:rPrChange` holds a
#   snapshot of the formatting a tracked change replaced, and the
#   snapshot is a `w:rPr` INSIDE the `w:rPr`. So the string has two
#   opening tags and may hold a second `w:rStyle` — and the function
#   wrote the Hyperlink style into the historical record while the
#   properties the page shows got none. See the tests above; the code no
#   longer has those lines.
# * the five on `@lru_cache`, maxsize and the decorator itself. The
#   cached functions compile a pattern from their argument and hold no
#   state; the size is a speed choice.
# * `link`'s two `if current is None: continue` arms, both marked
#   defensive: the caption was found a line earlier by the same
#   `find_captions` call over the same string.
# * the two comparisons against a MODE — `mode == "NOT-FOUND"` and
#   `mode != "linked"` — as `is` and `is not`. Both sides are the same
#   literal: `_link_mention` returns it and `link` compares against it,
#   and CPython gives an identifier-like constant one object. The
#   ORDERING spellings go the same way for a different reason: every
#   other mode this function returns begins with a lower-case letter,
#   which sorts after "NOT-FOUND".
# * `pos < at` as `<=` in the misplaced-anchor filter. The only mention
#   at exactly `at` is the marker's own, and the clause beside it drops
#   anything in the marker's own paragraph.
# * the `r_open < 0` guards as `<= 0` (and as `< 1`): `r_open` is -1 or
#   at least 1, so the two spellings differ only at a value the string
#   cannot produce.


def test_the_hyperlink_style_goes_to_the_LIVE_properties():
    """`w:rPrChange` holds the formatting a tracked change replaced, and
    it is a `w:rPr` nested inside the `w:rPr`. A run whose only
    `w:rStyle` sits in that snapshot had the Hyperlink style written
    into the historical record — the page kept the style it had, the
    link showed as plain text, and the tracked-change record said the
    author had once styled it as a hyperlink.

    The defect `_run_italic` and `_run_vert_align` each learned
    separately, and the reason the old survivor note's "an rPr string
    has one opening tag" was wrong."""
    from docxkit.crossrefs import _with_hyperlink_style

    date = 'w:id="7" w:author="A" w:date="2026-01-01T00:00:00Z"'
    rpr = (f'<w:rPr><w:b/><w:rPrChange {date}>'
           f'<w:rPr><w:rStyle w:val="Emphasis"/></w:rPr>'
           f"</w:rPrChange></w:rPr>")

    out = _with_hyperlink_style(rpr)

    live, _, past = out.partition("<w:rPrChange")
    assert '<w:rStyle w:val="Hyperlink"/>' in live
    assert '<w:rStyle w:val="Emphasis"/>' in past, "the past stands"
    assert out.count("<w:rStyle") == 2


def test_an_EMPTY_run_properties_element_is_expanded_not_passed_over():
    """`<w:rPr/>` is real Word output, and the replace was written for
    the paired form — so the run came back untouched and became a link
    wearing no Hyperlink style, which reads on the page as plain text.

    The fourth instance of that shape in this package: `set_run_text`,
    `package.set_core_property` and `lint`'s check 7c for `<w:tcPr/>`."""
    from docxkit.crossrefs import _with_hyperlink_style

    assert (_with_hyperlink_style("<w:rPr/>")
            == '<w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>')
    assert (_with_hyperlink_style("<w:rPr></w:rPr>")
            == '<w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>')


def test_a_run_carrying_TWO_character_styles_comes_out_with_one():
    """The schema allows one `w:rStyle`, and the docstring says this
    never leaves two. It meant "never ADDS a second" — handed a run that
    already had two, it replaced the first and left the other."""
    from docxkit.crossrefs import _with_hyperlink_style

    out = _with_hyperlink_style(
        '<w:rPr><w:rStyle w:val="A"/><w:rStyle w:val="B"/><w:b/></w:rPr>')

    assert out == '<w:rPr><w:rStyle w:val="Hyperlink"/><w:b/></w:rPr>'


# --- what the run of 2026-08-20 added to that list ---------------------
#
# `link_more`'s four, none of them worked and each checked:
#
# * both `if span in claimed: continue` arms, as `break`. A span is
#   claimed only by an EARLIER pattern that matched the same text at the
#   same offsets — and two patterns doing that are two captions of one
#   label and number, whose patterns are identical and whose match sets
#   therefore coincide. (Different labels cannot cross-match: every form
#   is followed by `\s+`, so `Figs?` does not reach into "Figure".) The
#   loop that meets a claimed span has nothing unclaimed left to append,
#   so `break` skips nothing.
# * the continuation span's `m.end(1)` as `m.end(0)`. What follows group
#   1 in `_continuation_re` is `NUMBER_END`, which is three lookaheads
#   and consumes nothing, so the group ends where the match does.
# * `sorted(todo, reverse=True)` as `reverse=False`. NOT equivalent, and
#   recorded rather than pinned: the two orders differ only in which
#   fragments come out carrying a redundant `xml:space="preserve"`. The
#   links land on the same words and the visible text is identical
#   either way, because these are VISIBLE-text offsets and wrapping a
#   span in a hyperlink does not move one. Which is worth knowing: the
#   reverse sort reads like the usual splice-from-the-back rule, and
#   here it is not load-bearing.
#
# And one on the code that round WROTE, from re-measuring the module the
# same afternoon: `open_end = rpr.index(">") + 1` as `^ 1`. `<w:rPr>` is
# seven characters, so the `>` is at index 6 — and 6 ^ 1 IS 6 + 1. The
# two part company only for an odd index, which needs an attribute on
# `w:rPr`, and CT_RPr has none.


def test_unlink_takes_EVERY_copy_of_a_duplicated_bookmark():
    """Word's Compare DUPLICATES a table when a block containing it is
    moved — S1 in the backlog — and the copy carries the same `w:name`
    and the same `w:id`. A paper that has been through one round of
    move-tracking holds the pair.

    Taking one of each left a bookmarkStart and its End standing and
    reported "1 removed", which is the shape this module's own
    docstring refuses elsewhere: "not a partial success, a wrong answer
    that reports a healthy count"."""
    def block(bid: int) -> str:
        return (f'<w:bookmarkStart w:id="{bid}" w:name="Table1"/>'
                "<w:p><w:r><w:t>Table 1. Sources</w:t></w:r></w:p>"
                f'<w:bookmarkEnd w:id="{bid}"/>')

    xml = doc(para(run("See Table 1 above."))) .replace(
        "</w:body>", block(7) + block(7) + "</w:body>")

    out, removed = crossrefs.unlink(xml)

    assert removed == 2, "both, and the count says both"
    assert "<w:bookmarkStart" not in out
    assert "<w:bookmarkEnd" not in out


def test_unlink_removes_one_END_per_START_and_no_more():
    """The other side of the removal, and the reason it is a `count=1`
    inside a loop rather than a `count=0` outside one: an id shared
    with a bookmark this pass does not own is a defect of its own, and
    cutting its close would turn one broken bookmark into two.

    A document with one START and two ENDS of that id is already
    broken. What unlink owes it is not to make it worse."""
    xml = ("<w:document><w:body>"
           "<w:p><w:r><w:t>See Table 1 above.</w:t></w:r></w:p>"
           '<w:bookmarkStart w:id="7" w:name="Table1"/>'
           "<w:p><w:r><w:t>Table 1. Sources</w:t></w:r></w:p>"
           '<w:bookmarkEnd w:id="7"/><w:bookmarkEnd w:id="7"/>'
           "</w:body></w:document>")

    out, removed = crossrefs.unlink(xml)

    assert removed == 1, "one bookmark, however many closes it has"
    assert "<w:bookmarkStart" not in out
    assert out.count("<w:bookmarkEnd") == 1, "one taken, one left alone"


def test_a_caption_whose_runs_all_carry_ATTRIBUTES_is_still_wrapped():
    """`rfind("<w:r>", 0, ...)` and `rfind("<w:r ", 0, ...)` are two
    searches because Word writes both — a run with an rsid is
    `<w:r w:rsidR="00A1">`, and on a real manuscript that is most of
    them. A document with no bare `<w:r>` in it leans entirely on the
    second search, and every fixture here had one.
    """
    attr = '<w:r w:rsidR="00A1"><w:t>%s</w:t></w:r>'
    xml = doc("<w:p>" + attr % "As Table 1 shows." + "</w:p>",
              "<w:p>" + attr % "Table 1. Employment" + "</w:p>")

    out, report = crossrefs.link(xml)

    assert report.linked == ["Table1"], report.format()
    # the caption's label became the BACK-link — which is the half that
    # goes through `_wrap_label`, and the half a run with no bare
    # `<w:r>` in front of it would otherwise skip
    assert 'w:anchor="Table1txt"' in out, out
    assert "<w:hyperlink" in out.split("Employment")[0], out


# crossrefs' other survivors from the 2026-08-21 round, argued:
#
# `_wrap_label`'s `rfind("<w:r>", 0, ...)` read as `rfind("<w:r>", 1,
# ...)`: index 0 of a paragraph is `<w:p`, so no run can open there.
#
# `_caption_bookmarks`' `prev_close != -1 else 0` read as `else 1`, as
# `!= +1` and as `!= ~1`: `prev_close` is a `rfind` result, so it is -1
# or the index of a `</w:p>` — which cannot be 1 or -2 — and the `else`
# arm's 0 versus 1 is the first character of the part, which is `<`.
#
# `_run_parts`' `close != -1` read as `close >= -1`: this is called on
# a run being SPLIT at a text match, so the run has a `</w:r>` by
# construction and the -1 arm is unreachable from here.
#
# `_with_hyperlink_style`'s `rpr.index(">") + 1` read as `^ 1` and `| 1`:
# the three agree whenever that index is even, which is a fact about
# the fixture rather than about the code — pinning it would freeze a
# byte offset, and the malformed output it produces on an odd one is
# what `lint` refuses.
#
# `link`'s `mode == "NOT-FOUND"` as `is`: one literal, in this module.


# --- a bookmark is not a link -----------------------------------------
# The state Word leaves on an ordinary author round: it keeps bookmarks
# and strips run-level hyperlinks out of any paragraph whose text it
# rewrites. Both markers survive, nothing points at either, and until
# 2026-08-23 `audit` called that `linked` and `link()` called it done.


def _both_marks(*, forward: bool, back: bool) -> str:
    """A figure with both bookmarks, and only the links asked for."""
    mention = (('<w:hyperlink w:anchor="Figure1">' + run("Figure 1")
                + "</w:hyperlink>") if forward else run("Figure 1"))
    caption = (('<w:hyperlink w:anchor="Figure1txt">' + run("Figure 1")
                + "</w:hyperlink>") if back else run("Figure 1"))
    return doc(
        para('<w:bookmarkStart w:id="1" w:name="Figure1txt"/>'
             + mention + '<w:bookmarkEnd w:id="1"/>'
             + run(" shows the trend.")),
        para('<w:bookmarkStart w:id="2" w:name="Figure1"/>'
             + caption + run(". The caption") + '<w:bookmarkEnd w:id="2"/>'),
    )


def test_audit_will_not_call_an_exhibit_linked_when_NOTHING_links_to_it():
    got = crossrefs.audit(_both_marks(forward=False, back=False))
    assert got["linked"] == []
    assert got["unreached"] == [
        "Figure1: nothing links to the caption and "
        "the caption links back to nothing"]


def test_audit_names_WHICH_direction_is_gone():
    forward_only = crossrefs.audit(_both_marks(forward=True, back=False))
    assert forward_only["unreached"] == [
        "Figure1: the caption links back to nothing"]
    back_only = crossrefs.audit(_both_marks(forward=False, back=True))
    assert back_only["unreached"] == [
        "Figure1: nothing links to the caption"]


def test_both_links_present_is_the_only_way_to_be_linked():
    got = crossrefs.audit(_both_marks(forward=True, back=True))
    assert got["linked"] == ["Figure1"] and got["unreached"] == []


def test_link_REPAIRS_an_exhibit_whose_links_word_ate():
    """It used to refuse: `already_linked`, because the bookmarks were
    there. The bookmarks are what Word keeps."""
    out, rep = crossrefs.link(_both_marks(forward=False, back=False))
    assert rep.linked == ["Figure1"] and rep.already_linked == []
    assert crossrefs.audit(out)["linked"] == ["Figure1"]


def test_the_repair_does_not_mint_a_SECOND_bookmark_of_the_same_name():
    """The marker survived; a duplicate name is what `link` would have
    written by re-running its whole first-mention path."""
    out, _ = crossrefs.link(_both_marks(forward=False, back=False))
    for name in ("Figure1", "Figure1txt"):
        assert out.count(f'w:name="{name}"') == 1, name


def test_a_field_link_counts_as_reaching_the_caption():
    r"""`HYPERLINK \l` is the same link to a reader, and a paper holds
    both forms at once."""
    field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             r'<w:r><w:instrText>HYPERLINK \l "Figure1" \h</w:instrText>'
             "</w:r>"
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             + run("Figure 1")
             + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    xml = doc(
        para('<w:bookmarkStart w:id="1" w:name="Figure1txt"/>' + field
             + '<w:bookmarkEnd w:id="1"/>' + run(" shows the trend.")),
        para('<w:bookmarkStart w:id="2" w:name="Figure1"/>'
             '<w:hyperlink w:anchor="Figure1txt">' + run("Figure 1")
             + "</w:hyperlink>" + run(". The caption")
             + '<w:bookmarkEnd w:id="2"/>'),
    )
    got = crossrefs.audit(xml)
    assert got["linked"] == ["Figure1"] and got["unreached"] == []


def test_dangling_sees_a_FIELD_pointing_at_a_bookmark_that_is_gone():
    """The same half-answer on the other side: reading element anchors
    alone, a REF left behind by a deleted figure was invisible."""
    xml = doc(para(run("As set out above"),
                   '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                   r'<w:r><w:instrText>REF Figure9 \h</w:instrText></w:r>'
                   '<w:r><w:fldChar w:fldCharType="end"/></w:r>'))
    assert crossrefs.audit(xml)["dangling"] == ["Figure9"]
