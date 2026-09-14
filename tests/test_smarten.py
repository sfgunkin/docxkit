"""hygiene.smarten — only the safe typography, everything else reported."""
from __future__ import annotations

from docxkit._xml import visible_text
from docxkit.hygiene import smarten


def para(*runs: str) -> str:
    return "<w:p>" + "".join(runs) + "</w:p>"


def run(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def test_apostrophes_after_word_characters_curl():
    xml, report = smarten(para(run("don't touch workers' rights")))
    assert visible_text(xml) == "don’t touch workers’ rights"
    assert report.apostrophes == 2


def test_lookback_crosses_run_boundaries():
    xml, report = smarten(para(run("workers"), run("' rights")))
    assert visible_text(xml) == "workers’ rights"
    assert report.apostrophes == 1


def test_a_leading_apostrophe_is_ambiguous_and_left():
    xml, report = smarten(para(run("rock 'n' roll")))
    # the ' before n could be an elision or an opening quote; the one
    # after n follows a word character and is safe
    assert visible_text(xml) == "rock 'n’ roll"
    assert (report.apostrophes, report.ambiguous) == (1, 1)


def test_a_paragraph_STARTING_with_an_apostrophe_is_ambiguous_too():
    """The lookback starts empty at each paragraph: there is no previous
    character, so the first one cannot be "after a word". Carrying a
    word character in from nowhere would curl an opening quote into a
    closing one, at the start of the sentence, where it is most visible.
    """
    xml, report = smarten(para(run("'tis the season, workers' hours")))

    assert visible_text(xml) == "'tis the season, workers’ hours"
    assert (report.apostrophes, report.ambiguous) == (1, 1)


def test_paired_double_quotes_alternate():
    xml, report = smarten(para(run('she said "no" and "yes"')))
    assert visible_text(xml) == "she said “no” and “yes”"
    assert report.quotes == 4


def test_quote_pairing_crosses_runs_but_not_paragraphs():
    two = (para(run('"split'), run(' quote"'))
           + para(run('"again"')))
    xml, _ = smarten(two)
    assert visible_text(xml) == "“split quote”“again”"


def test_an_odd_quote_count_leaves_the_paragraph_and_reports():
    xml, report = smarten(para(run('a "dangling quote')))
    assert visible_text(xml) == 'a "dangling quote'
    assert report.quotes == 0
    assert report.unbalanced and "dangling" in report.unbalanced[0]


def test_math_is_never_touched():
    xml, report = smarten(
        "<w:p><m:oMath><m:r><m:t>f'(x)</m:t></m:r></m:oMath>"
        + run("the f' here curls") + "</w:p>")
    assert "<m:t>f'(x)</m:t>" in xml            # the prime survives
    assert "f’ here" in visible_text(xml)
    assert report.apostrophes == 1


def test_tracked_deletions_and_field_code_are_not_ours():
    xml, _ = smarten(
        "<w:p><w:del w:id=\"1\"><w:r><w:delText>author's</w:delText>"
        "</w:r></w:del>"
        '<w:r><w:instrText> REF x\'y </w:instrText></w:r></w:p>')
    assert "author's" in xml and "REF x'y" in xml


def test_entities_round_trip():
    xml, _ = smarten(para(run("R&amp;D's rise")))
    assert "R&amp;D’s rise" in xml


def test_untouched_document_comes_back_identical():
    doc = para(run("no straight glyphs at all — already ’typeset“”"))
    xml, report = smarten(doc)
    assert xml == doc
    assert report.apostrophes == report.quotes == 0


# --- the report, and the order the edits go back in (2026-08-19) --------
#
# hygiene measured at 10.9 % real survival with 10 survivors in
# `_smarten_para`. Two of them are the shape this repo keeps finding: a
# guard read only from the side it fires on (`unbalanced` was asserted
# for the odd-count paragraph and never for the even one), and a value
# printed but never read back (the 70-character cut on the snippet).
#
# The third is the sort. Replacements go back RIGHT TO LEFT so that each
# one lands at an offset the earlier ones have not moved, and in a
# document whose runs are all the same length after smartening that
# ordering is invisible — every fixture here was one. An entity is what
# changes a run's length: `&#39;` is five characters in the XML and one
# after `html.unescape`, so a run holding one SHRINKS when it is written
# back, and every offset after it in the paragraph moves.


def test_a_paragraph_whose_quotes_BALANCE_is_not_reported_unbalanced():
    """`not quotes_pair and '"' in stream` — both, not either. Under
    `or` every paragraph carrying a straight double quote is reported,
    including the ones that were just smartened correctly, and the
    report's one job is to name the paragraphs a person still has to
    decide by hand."""
    _xml, report = smarten(para(run('she said "no" and "yes"')))

    assert report.quotes == 4
    assert report.unbalanced == []


def test_the_unbalanced_snippet_is_the_first_seventy_characters():
    """Long enough to find the paragraph in the document, short enough
    to stay on one terminal line — and normalised, because the run
    boundaries a fragmented paragraph carries are not the reader's
    problem."""
    long = ("This section of the argument runs on for a while before it "
            'opens a "quotation that never closes, and then continues '
            "for some distance after that.")

    _xml, report = smarten(para(run(long)))

    assert report.unbalanced == [
        "This section of the argument runs on for a while before it opens "
        'a "qu']
    assert len(report.unbalanced[0]) == 70


def test_two_runs_that_SHRINK_are_written_back_right_to_left():
    """`key=lambda pair: -pair[0].start()`. `&#39;` is five characters
    in the XML and one after unescaping, so the first run written back
    is four characters shorter than the slice it replaced — and every
    match offset after it in the paragraph is stale. Ascending, the
    second replacement lands four characters early: inside the first
    run's closing tag."""
    xml, report = smarten(para(run("don&#39;t"), run(" it&#39;s so")))

    assert report.apostrophes == 2
    assert visible_text(xml) == "don’t it’s so"
    assert xml == para(run("don’t"), run(" it’s so"))


# --- the whole package ----------------------------------------------------

def _package(body: str, footnote: str = "", endnote: str = ""):
    parts = {"word/document.xml":
             f"<w:document><w:body>{body}</w:body></w:document>".encode()}
    if footnote:
        parts["word/footnotes.xml"] = (
            f"<w:footnotes><w:footnote>{footnote}"
            "</w:footnote></w:footnotes>").encode()
    if endnote:
        parts["word/endnotes.xml"] = (
            f"<w:endnotes><w:endnote>{endnote}"
            "</w:endnote></w:endnotes>").encode()
    return parts


def test_smarten_parts_reaches_the_FOOTNOTES_and_the_ENDNOTES():
    """`_xml.TEXT_PARTS` states the rule: an operation that describes
    the DOCUMENT is wrong if it stops at the body. `smarten` takes one
    part's XML — every other chore in `hygiene` takes the package — so
    its only caller smartened `word/document.xml` and left the notes
    alone.

    An economics manuscript keeps a large share of its prose in
    footnotes, so the phantom class of diffs this exists to end survived
    in exactly the part nobody re-reads."""
    from docxkit.hygiene import smarten_parts

    parts = _package(
        para(run("the workers' share")),
        footnote=para(run('See Smith\'s note on "growth".')),
        endnote=para(run("the authors' own data")))

    report = smarten_parts(parts)

    assert visible_text(parts["word/footnotes.xml"].decode()) == (
        "See Smith’s note on “growth”.")
    assert visible_text(parts["word/endnotes.xml"].decode()) == (
        "the authors’ own data")
    assert report.apostrophes == 3
    assert report.quotes == 2


def test_an_UNBALANCED_paragraph_is_named_by_the_part_it_is_in():
    """One report for the package, so "the quotes are odd somewhere" is
    not an actionable sentence when the somewhere could be four files.
    The body is left unlabelled, because that is where a reader looks
    first and a prefix on every line would be noise."""
    from docxkit.hygiene import smarten_parts

    parts = _package(
        para(run('an odd " in the body')),
        footnote=para(run('an odd " in a note')))

    report = smarten_parts(parts)

    assert len(report.unbalanced) == 2, report.unbalanced
    body = [u for u in report.unbalanced if not u.startswith("footnotes:")]
    note = [u for u in report.unbalanced if u.startswith("footnotes:")]
    assert len(body) == 1 and len(note) == 1, report.unbalanced


def test_a_package_with_no_notes_is_not_an_error():
    """An absent part is not a failure — a document with no footnotes
    simply has none, which is what `text_parts` is for."""
    from docxkit.hygiene import smarten_parts

    parts = _package(para(run("the workers' share")))

    report = smarten_parts(parts)

    assert report.apostrophes == 1
    assert set(parts) == {"word/document.xml"}


# --- the survivors of 2026-09-14 ------------------------------------------


def test_the_BODY_is_the_part_left_UNLABELLED():
    """The body is unlabelled and every other part is named. The test
    above could not say which: it split the lines on the footnotes'
    label, which a body line carrying a `document:` prefix passes too."""
    from docxkit.hygiene import smarten_parts

    parts = _package(
        para(run('an odd " in the body')),
        footnote=para(run('an odd " in a note')),
        endnote=para(run('and " in an endnote')))

    report = smarten_parts(parts)

    assert report.unbalanced == ['an odd " in the body',
                                 'footnotes: an odd " in a note',
                                 'endnotes: and " in an endnote']


def test_a_repair_that_SORTS_LOWER_is_still_written_back():
    """Written back when the text changed, and "changed" is inequality,
    not order. A literal `>` is legal in XML text and comes back escaped
    beside the curled apostrophe, and `&` sorts below `>`, so the repaired
    part sorts below the original and an ordering test keeps the
    original."""
    from docxkit.hygiene import smarten_parts

    parts = _package(para(run("x > y, and it's so")))

    smarten_parts(parts)

    assert visible_text(parts["word/document.xml"].decode()) == \
        "x > y, and it’s so"
