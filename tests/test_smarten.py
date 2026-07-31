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
