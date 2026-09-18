"""Equations: the LaTeX pipeline, harvesting, and formula fingerprints."""
from __future__ import annotations

import pytest
from conftest import document, para, run

from docxkit.equations import (
    clone,
    display,
    display_equations,
    equations,
    find_mml2omml_xsl,
    harvest,
    in_display_mode,
    inline_display,
    is_display,
    latex_to_omml,
    skeleton,
    to_latex,
    tokens,
)
from docxkit.errors import AnchorError, PackageError

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def omath(inner: str) -> str:
    return f'<m:oMath xmlns:m="{M_NS}">{inner}</m:oMath>'


def mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def ssub(base: str, sub: str) -> str:
    return (f"<m:sSub><m:e>{mr(base)}</m:e>"
            f"<m:sub>{mr(sub)}</m:sub></m:sSub>")


def frac(num: str, den: str) -> str:
    return (f"<m:f><m:num>{mr(num)}</m:num>"
            f"<m:den>{mr(den)}</m:den></m:f>")


def _doc():
    return document(
        para(run("The share is "), omath(ssub("s", "ict")), run("."))
        + para(omath(frac("L", "N")) + run("\t(1)"))
        + para(run("Ordinary prose with no maths.")))


def test_equations_are_found_in_order():
    eqs = equations(_doc())
    assert len(eqs) == 2
    assert eqs[0].tokens == "sict"
    assert eqs[1].tokens == "LN"
    # both fingerprints are PROPERTIES, and only one of them had ever
    # been read off an Equation: the structure is what tells a fraction
    # from the same symbols written with a solidus
    assert (eqs[0].skeleton, eqs[1].skeleton) == ("sSub", "f")


def test_tokens_and_skeleton_answer_different_questions():
    """Same symbols, different structure: a token-only comparison passes
    a rewrite that changes the formula's meaning."""
    a, b = omath(frac("L", "N")), omath(mr("L") + mr("/") + mr("N"))
    assert tokens(a) == "LN"
    assert tokens(b) == "L/N"
    assert skeleton(a) == "f"
    assert skeleton(b) == ""


def test_skeleton_records_nesting():
    nested = omath(f"<m:f><m:num>{ssub('L', 'ict')}</m:num>"
                   f"<m:den>{mr('N')}</m:den></m:f>")
    assert skeleton(nested) == "f/sSub"


def test_harvest_returns_a_live_equation_to_copy():
    """Reusing the document's own element is what guarantees the new
    equation renders like its neighbours."""
    got = harvest(_doc(), "sict")
    assert "m:sSub" in got
    assert tokens(got) == "sict"


def test_harvest_reports_a_missing_symbol_clearly():
    with pytest.raises(AnchorError, match="no equation whose symbols"):
        harvest(_doc(), "zzz")


def test_harvest_can_pick_among_repeats():
    xml = document(para(omath(mr("x"))) + para(omath(mr("x"))))
    assert harvest(xml, "x", index=1)
    with pytest.raises(AnchorError, match="no index 5"):
        harvest(xml, "x", index=5)


def test_harvest_exact_refuses_a_formula_that_merely_mentions_the_symbol():
    """Harvesting a bare symbol is the case a substring match gets wrong.

    A manuscript defines C_k once and then uses it everywhere, so the
    standalone symbol is rarely the first equation containing it. The
    default match hands back the formula; exact= asks for the letter.
    """
    xml = document(para(omath(ssub("C", "k") + mr("=") + mr("1")))
                   + para(omath(ssub("C", "k"))))
    assert tokens(harvest(xml, "Ck")) == "Ck=1"
    assert tokens(harvest(xml, "Ck", exact=True)) == "Ck"


def test_harvest_exact_is_an_EQUALITY_not_an_ordering():
    """`stream.strip() == contains.strip()`, and `<=` is the mutant that
    hides behind the obvious fixture: "Ck=1" sorts AFTER "Ck", so the
    formula case answers the same either way. An equation whose symbols
    sort BEFORE the query is what parts them — a bare "C" beside the
    "Ck" being asked for — and under `<=` the walk takes the first
    equation in document order, which is the wrong one."""
    xml = document(para(omath(mr("C"))) + para(omath(ssub("C", "k"))))

    assert tokens(harvest(xml, "Ck", exact=True)) == "Ck"


def test_harvest_exact_says_which_match_it_tried():
    formula = omath(ssub("C", "k") + mr("=") + mr("1"))
    only_in_a_formula = document(para(formula))
    with pytest.raises(AnchorError, match="symbols equal 'Ck'"):
        harvest(only_in_a_formula, "Ck", exact=True)


def test_clone_detaches_a_copy():
    original = harvest(_doc(), "sict")
    copied = clone(original)
    assert tokens(copied) == tokens(original)


def test_is_display_distinguishes_inline_from_display():
    inline = para(run("The share is "), omath(ssub("s", "ict")), run("."))
    display = para(omath(frac("L", "N")))
    numbered = para(omath(frac("L", "N")) + run("\t(1)"))
    assert not is_display(inline)
    assert is_display(display)
    assert is_display(numbered), "an equation number is not prose"
    assert not is_display(para(run("no maths here")))


def test_display_centres_an_equation_ALREADY_in_display_mode():
    """Display and centred are two properties. Word promotes an
    equation to display on its own save without centring it, and
    returning such a paragraph untouched left no way to state the rule.
    """
    promoted = para('<m:oMathPara>' + omath(frac("L", "N"))
                    + '</m:oMathPara>')
    assert in_display_mode(promoted)

    fixed = display(promoted)

    assert '<m:jc m:val="center"/>' in fixed
    # m:oMathParaPr is the FIRST child, or Word repairs the document
    assert "<m:oMathPara><m:oMathParaPr>" in fixed
    assert display(fixed) == fixed              # still idempotent


def test_display_repoints_an_alignment_that_is_already_stated():
    promoted = para('<m:oMathPara><m:oMathParaPr><m:jc m:val="left"/>'
                    '</m:oMathParaPr>' + omath(frac("L", "N"))
                    + '</m:oMathPara>')

    fixed = display(promoted)

    assert '<m:jc m:val="center"/>' in fixed
    assert '<m:jc m:val="left"/>' not in fixed
    assert fixed.count("<m:oMathParaPr>") == 1


def test_display_with_jc_None_leaves_a_promoted_equation_alone():
    promoted = para('<m:oMathPara><m:oMathParaPr><m:jc m:val="left"/>'
                    '</m:oMathParaPr>' + omath(frac("L", "N"))
                    + '</m:oMathPara>')

    assert display(promoted, jc=None) == promoted


def test_the_comma_closing_a_displayed_equation_is_not_prose():
    """A display is part of the sentence that introduces it, so authors
    write ", (3)" after the maths.

    Counted as prose, that comma made `is_display` return False — so
    `display_equations` never listed the equation, no house check saw
    it, and it stayed inline. Three of one manuscript's seven equations
    were invisible to every equation tool for exactly this.
    """
    assert is_display(para(omath(frac("L", "N")) + run(", (3)")))
    assert is_display(para(omath(frac("L", "N")) + run(".")))
    # and the guard: real prose beside the maths is still prose
    assert not is_display(
        para(omath(frac("L", "N")) + run(", where L is labour.")))


def test_display_equations_skips_inline_and_prose():
    found = display_equations(_doc())
    assert len(found) == 1
    assert "(1)" in found[0].group(0)


# --- a notation TABLE is not stranded maths (2026-08-27, Aging_Well) ---
#
# That paper's Appendix opens with a two-column notation table, so each
# cell of the symbol column holds nothing but maths. `math --check`
# counted 17 of them as display equations "still in INLINE mode" and
# could not exit 0 — useless as a gate on exactly the papers with the
# most equations — and the remedy it printed could not be taken either:
# `display` raises on a cell like "α, β, γ" that holds three m:oMath.

def _cell(*paras: str) -> str:
    return f"<w:tc><w:tcPr/>{''.join(paras)}</w:tc>"


def _notation_table(*symbols: str) -> str:
    """The shape a notation table really has: symbol cell, gloss cell."""
    rows = "".join(
        f"<w:tr>{_cell(para(omath(mr(s))))}"
        f"{_cell(para(run('what it means')))}</w:tr>" for s in symbols)
    return f"<w:tbl><w:tblPr/>{rows}</w:tbl>"


def test_a_maths_only_TABLE_CELL_is_not_a_display_equation():
    xml = document(_notation_table("α", "β", "γ", "δ", "ε")
                   + para(omath(frac("L", "N")) + run("\t(1)")))

    found = display_equations(xml)

    assert len(found) == 1, [m.group(0)[:60] for m in found]
    assert "(1)" in found[0].group(0)


def test_the_literal_question_is_still_askable():
    """`--in-tables` for a caller who means every maths-only paragraph
    in the file. Excluding them is the DEFAULT, not the only answer."""
    xml = document(_notation_table("α", "β", "γ", "δ", "ε")
                   + para(omath(frac("L", "N")) + run("\t(1)")))

    assert len(display_equations(xml, in_tables=True)) == 6


def test_a_cell_is_not_reported_as_stranded_INLINE_either():
    """The finding named a repair that refuses: `display` raises
    `display needs exactly one m:oMath in the paragraph` on a cell
    holding "α, β, γ". A gate whose only remedy is unavailable is the
    shape this backlog ranks above a wrong answer."""
    xml = document(_notation_table("α", "β", "γ"))

    assert inline_display(xml) == []
    assert len(inline_display(xml, in_tables=True)) == 3


def test_an_equation_AFTER_a_table_is_still_found():
    """The exclusion is a span test, and a span test that runs to the
    end of the document hides every equation below the paper's first
    table — which on these papers is most of them."""
    xml = document(_notation_table("α")
                   + para(omath(frac("L", "N")) + run("\t(2)"))
                   + _notation_table("β")
                   + para(omath(frac("K", "N")) + run("\t(3)")))

    found = display_equations(xml)

    assert [t for m in found for t in ("(2)", "(3)")
            if t in m.group(0)] == ["(2)", "(3)"]


# --- ...but the equation VEHICLE is a table too (regression, 27.08) ---
#
# The first cut of the fix above skipped every maths-only paragraph
# inside a `w:tbl`, and Aging_Well puts all thirteen of its NUMBERED
# equations in one — a full-width table, maths in the left cell, "(3)"
# right-aligned in the right, because Word has no other way to put a
# number on the margin beside a centred block. So `math --check` went
# green on a document with thirteen display equations and one of them
# stranded: it could not tell the healthy file from a sabotaged one in
# either mode. Green and blind is worse than honestly red.

def _vehicle(number: str, *, promoted: bool = True) -> str:
    """The house vehicle: maths in one cell, its number in the next."""
    maths = omath(frac("L", "N"))
    if promoted:
        maths = f"<m:oMathPara><m:oMathParaPr/>{maths}</m:oMathPara>"
    return (f"<w:tbl><w:tblPr/><w:tr>{_cell(f'<w:p>{maths}</w:p>')}"
            f"{_cell(para(run(number)))}</w:tr></w:tbl>")


def test_an_equation_in_its_NUMBER_VEHICLE_is_still_a_display_equation():
    xml = document(_vehicle("(1)") + _vehicle("(2)") + _vehicle("(3)"))

    assert len(display_equations(xml)) == 3


def test_a_STRANDED_equation_in_a_vehicle_is_still_reported():
    """The whole point of the check. One of three left in a bare
    m:oMath, and the gate has to be able to say which."""
    xml = document(_vehicle("(1)") + _vehicle("(2)", promoted=False)
                   + _vehicle("(3)"))

    stranded = inline_display(xml)

    assert len(stranded) == 1
    assert "(2)" not in stranded[0].group(0), "the maths cell, not the number"


def test_a_healthy_vehicle_document_reports_NOTHING_stranded():
    """The other half: a gate that fires on both files is as useless as
    one that fires on neither."""
    xml = document(_vehicle("(1)") + _vehicle("(2)") + _vehicle("(3)"))

    assert inline_display(xml) == []


def test_a_vehicle_is_read_per_ROW_not_per_TABLE():
    """Aging_Well's (A2) and (A3) share a two-row table. "One row is a
    vehicle, many rows is a notation table" is what the two shapes look
    like side by side, and it drops both of these."""
    two_rows = ("<w:tbl><w:tblPr/>"
                f"<w:tr>{_cell(f'<w:p>{omath(frac(chr(76), chr(78)))}</w:p>')}"
                f"{_cell(para(run('(A2)')))}</w:tr>"
                f"<w:tr>{_cell(f'<w:p>{omath(frac(chr(75), chr(78)))}</w:p>')}"
                f"{_cell(para(run('(A3)')))}</w:tr></w:tbl>")

    assert len(display_equations(document(two_rows))) == 2


def test_a_vehicle_row_covers_ITS_OWN_row_and_no_other_table():
    """A row's span is the TABLE's offset plus the row's offset within
    it, and six mutants lived on that sum — three that move where it
    starts and three that stretch where it ends. Neither shows in a
    document that holds one table: a span that begins too early or ends
    too late still contains the paragraph it was measured from.

    So this document puts a notation table on EACH side of the vehicle.
    A start that slides back swallows the first table's symbol cells, an
    end that runs on swallows the second's, and either way the count of
    display equations stops being one."""
    preamble = "".join(
        para(run(f"Paragraph {i} of the preamble, before the tables."))
        for i in range(7))
    xml = document(preamble + _notation_table("α", "β")
                   + _vehicle("(4)") + _notation_table("γ", "δ"))

    assert len(display_equations(xml)) == 1
    assert len(display_equations(xml, in_tables=True)) == 5


def test_only_the_NUMBERED_row_of_a_table_carries_its_equation():
    """The other half of the row span, and the one a document with the
    number in its FIRST row cannot ask. Here the numbered row is the
    second, so the row's own offset inside the table is large — and a
    span that starts at the table rather than at the row reaches back
    over the row above it, which holds maths that is not a display
    equation at all."""
    maths = ("<m:oMathPara><m:oMathParaPr/>"
             f"{omath(frac('L', 'N'))}</m:oMathPara>")
    table = ("<w:tbl><w:tblPr/>"
             f"<w:tr>{_cell(para(omath(mr('α'))))}"
             f"{_cell(para(run('what it means')))}</w:tr>"
             f"<w:tr>{_cell(f'<w:p>{maths}</w:p>')}"
             f"{_cell(para(run('(5)')))}</w:tr></w:tbl>")

    xml = document(table)

    assert len(display_equations(xml)) == 1
    assert len(display_equations(xml, in_tables=True)) == 2


def test_the_two_KINDS_of_table_are_told_apart_in_one_document():
    """Which is the real shape: this paper has both, and the appendix
    puts them within a few paragraphs of each other."""
    xml = document(_notation_table("α", "β", "γ", "δ", "ε")
                   + _vehicle("(A1)") + _vehicle("(A2)") + _vehicle("(A3)"))

    assert len(display_equations(xml)) == 3
    assert len(display_equations(xml, in_tables=True)) == 8


def test_a_gloss_cell_is_not_an_equation_NUMBER():
    """`_is_number_cell` is the whole discriminator, so its edge is
    worth stating: a cell is a number cell only when the number is ALL
    it holds. A notation table's meaning column mentions numbers."""
    from docxkit.equations import _is_number_cell

    assert _is_number_cell(para(run("(3)")))
    assert _is_number_cell(para(run("(A12)")))
    assert not _is_number_cell(para(run("individual, i=1,…,N (3) of them")))
    assert not _is_number_cell(para(run("Meaning")))
    assert not _is_number_cell(para(run("")))


def test_a_NESTED_table_does_not_swallow_the_rest_of_the_document():
    """`element_spans` is depth-counted for exactly this reason: a
    non-greedy match closes on the inner table's end tag, so the outer
    span would stop early and the paragraphs between the two closes
    would read as body."""
    inner = _notation_table("α")
    xml = document(f"<w:tbl><w:tblPr/><w:tr>{_cell(inner)}</w:tr></w:tbl>"
                   + para(omath(frac("L", "N")) + run("\t(1)")))

    found = display_equations(xml)

    assert len(found) == 1 and "(1)" in found[0].group(0)


# --- the LaTeX pipeline needs Word's XSL, so it is environment-dependent ---

def test_xsl_is_locatable_or_reports_why():
    try:
        path = find_mml2omml_xsl()
    except PackageError as exc:
        pytest.skip(f"Word not installed here: {exc}")
    assert path.exists() and path.name.upper() == "MML2OMML.XSL"


def test_explicit_xsl_path_is_validated(tmp_path):
    with pytest.raises(PackageError, match="not found at"):
        find_mml2omml_xsl(tmp_path / "nope.xsl")


def test_latex_converts_through_words_own_transform():
    pytest.importorskip("latex2mathml")
    try:
        find_mml2omml_xsl()
    except PackageError as exc:
        pytest.skip(f"Word not installed here: {exc}")
    out = latex_to_omml(r"\frac{L_{ict}}{L_{ct}}")
    assert out.startswith("<m:oMath")
    assert skeleton(out).startswith("f"), "a fraction must produce m:f"
    assert "L" in tokens(out)


# --- display MODE, which is not the same question as is_display -------


def test_a_lone_equation_paragraph_is_still_inline_to_word():
    """`is_display` asks about the paragraph — is the maths all it holds.
    Word asks about the markup: a bare m:oMath is INLINE however alone it
    sits, and every paper here wants display, centred."""
    p = para(omath(mr("x")))
    assert is_display(p) and not in_display_mode(p)
    assert [m.group(0) for m in inline_display(document(p))] == [p]


def test_display_wraps_the_maths_and_centres_it():
    out = display(para(omath(mr("x"))))
    assert "<m:oMathPara>" in out and "</m:oMathPara>" in out
    assert '<m:jc m:val="center"/>' in out
    assert in_display_mode(out)
    assert tokens(out) == "x", "the maths itself must come through intact"


def test_display_is_idempotent():
    """It is meant to be run over a whole document, and Word promotes
    SOME equations on save by itself — so it meets both kinds."""
    once = display(para(omath(mr("x"))))
    assert display(once) == once


def test_display_leaves_the_alignment_to_word_when_asked():
    out = display(para(omath(mr("x"))), jc=None)
    assert "<m:oMathPara>" in out and "m:jc" not in out


def test_display_refuses_a_justification_word_does_not_know():
    with pytest.raises(AnchorError, match="m:jc"):
        display(para(omath(mr("x"))), jc="centre")


def test_display_drops_an_empty_run_beside_the_maths():
    """An oMathPara must be the ONLY content of its paragraph. A leftover
    run — even an empty one — has Word demote the whole thing back to
    inline on the next save."""
    out = display(para(omath(mr("x")), run("  ")))
    assert "<w:r>" not in out and in_display_mode(out)


def test_display_refuses_a_run_that_carries_text():
    """This is how equation (A.3) came back inline: the "   (A.3)" run
    appended after it demoted the display, silently."""
    with pytest.raises(AnchorError, match=r"\(A\.3\)"):
        display(para(omath(mr("x")), run("   (A.3)")))


def test_absorb_moves_the_number_inside_the_maths():
    """Which is how the appendix's own (A.1) and (A.2) are built."""
    out = display(para(omath(mr("x")), run("   (A.3)")), absorb=True)
    assert in_display_mode(out) and "<w:r>" not in out
    assert tokens(out) == "x(A.3)"


def test_absorb_refuses_text_that_sits_before_the_equation():
    """Absorbing it would move it AFTER the maths, and no text diff
    would show that it had been reordered.

    Twice, and the second fixture is the one that pins the boundary:
    with the prose run butted straight against the equation, `r.end()`
    EQUALS `math.start()` and `<=` cannot be told from `>=`. A spacer
    run between them puts the prose strictly before, where the two
    disagree — and under `>=` the prose run drops out of the walk
    entirely, the check has nothing to look at, and the sentence is
    silently moved to the far side of the maths."""
    with pytest.raises(AnchorError, match="BEFORE"):
        display(para(run("where "), omath(mr("x"))), absorb=True)
    with pytest.raises(AnchorError, match="BEFORE"):
        display(para(run("where "), run("  "), omath(mr("x"))),
                absorb=True)


def test_display_drops_a_run_butted_straight_against_the_maths():
    """The filter is `r.end() <= math.start() or r.start() >= math.end()`,
    and six mutants lived on those two boundaries. A run that ends
    exactly where the equation begins — no gap — must still read as
    OUTSIDE it. Misread as inside, it is never cut out, and an
    oMathPara with a sibling run is demoted by Word on the next save."""
    p = f'<w:p>{run("  ")}{omath(mr("x"))}{run("  ")}</w:p>'
    out = display(p)
    assert "<w:r>" not in out, "a run survived beside the oMathPara"
    assert in_display_mode(out) and tokens(out) == "x"


def test_display_refuses_a_paragraph_with_no_equation_at_all():
    """`len(maths) != 1` read as `> 1` lets zero through, and the next
    line indexes `maths[0]`. A refusal naming the count is the contract;
    an IndexError is not."""
    with pytest.raises(AnchorError, match="found 0"):
        display(para(run("ordinary prose")))


def test_absorb_needs_prose_AND_the_flag_not_either():
    """`prose and absorb` read as `or`: a paragraph with nothing beside
    the maths would take the absorb path and splice an EMPTY run into
    the equation."""
    out = display(para(omath(mr("x"))), absorb=True)
    assert tokens(out) == "x"
    assert "<m:t></m:t>" not in out and "<m:t/>" not in out


def test_display_refuses_a_paragraph_with_two_equations():
    with pytest.raises(AnchorError, match="exactly one"):
        display(para(omath(mr("x")), omath(mr("y"))))


def test_display_keeps_the_paragraph_properties():
    p = ('<w:p><w:pPr><w:pStyle w:val="Equation"/></w:pPr>'
         f'{omath(mr("x"))}</w:p>')
    out = display(p)
    assert '<w:pStyle w:val="Equation"/>' in out


def test_a_promoted_paragraph_is_no_longer_reported():
    doc_xml = document(para(omath(mr("x"))) + para(run("prose")))
    (found,) = inline_display(doc_xml)
    fixed = doc_xml.replace(found.group(0), display(found.group(0)))
    assert inline_display(fixed) == []
    assert len(display_equations(fixed)) == 1, "still a display equation"


# --- what the converter emits and Word cannot draw --------------------
# Every one of these is VALID markup, so lint, the formula diff and the
# text diff pass on all of them and only a PDF render shows the page is
# wrong. The before/after of each was rendered through Word once; what
# it showed is in the test names.


def _normalized(omml: str) -> str:
    """`_normalize` alone, so these run without Word or latex2mathml."""
    from lxml import etree

    from docxkit.equations import _normalize

    root = etree.fromstring(omml.encode("utf-8"))
    _normalize(root)
    return str(etree.tostring(root, encoding="unicode"))


def _d(dpr: str, *els: str) -> str:
    return omath(f"<m:d><m:dPr>{dpr}</m:dPr>{''.join(els)}</m:d>")


def test_an_overline_accent_word_would_strike_through_is_replaced():
    """U+2015 HORIZONTAL BAR is not in Word's accent set, so Word centres
    it ON the letter: v-bar renders struck through. U+0305 COMBINING
    OVERLINE draws it above, as Word's own m:bar does."""
    out = _normalized(omath('<m:acc><m:accPr><m:chr m:val="―"/></m:accPr>'
                            f"<m:e>{mr('v')}</m:e></m:acc>"))
    assert 'm:val="̅"' in out
    assert "―" not in out


def test_a_group_character_is_left_alone():
    """`m:chr` also carries the brace of an `m:groupChr`, where a
    horizontal bar is a legitimate choice, not a mistake."""
    src = omath('<m:groupChr><m:groupChrPr><m:chr m:val="―"/>'
                f"</m:groupChrPr><m:e>{mr('x')}</m:e></m:groupChr>")
    assert _normalized(src) == src


def test_a_sign_read_as_a_separator_is_rejoined():
    """latex2mathml reads the minus in `(-1)` as the fence's SEPARATOR,
    so it arrives as an empty m:e and a `1` with the sign in m:sepChr.
    Word lays the empty element out as a gap: the page reads `(   −1)`,
    the parenthesis adrift from the sign."""
    out = _normalized(_d('<m:sepChr m:val="−"/>', "<m:e/>",
                         f"<m:e>{mr('1')}</m:e>"))
    assert "<m:e/>" not in out and "sepChr" not in out
    assert out.count("<m:e>") == 1
    assert tokens(out) == "−1"


def test_a_parenthesised_sign_keeps_its_delimiters():
    """`(-)` is two empty elements — `(  −  )` on the page. What the
    papers write by hand is an m:d with default delimiters."""
    out = _normalized(_d('<m:sepChr m:val="−"/>', "<m:e/>", "<m:e/>"))
    assert tokens(out) == "−"
    assert "<m:e/>" not in out


def test_the_brackets_of_a_rejoined_fence_survive():
    out = _normalized(_d('<m:begChr m:val="["/><m:sepChr m:val="−"/>'
                         '<m:endChr m:val="]"/>',
                         "<m:e/>", f"<m:e>{mr('1')}</m:e>"))
    assert 'm:begChr m:val="["' in out and 'm:endChr m:val="]"' in out
    assert tokens(out) == "−1"


@pytest.mark.parametrize("sep", [",", "−", "+"])
def test_a_separator_between_two_FILLED_elements_is_rejoined_TOO(sep):
    """This asserted the opposite until 2026-08-29 — that the tell is
    the EMPTY element, because `(x,y)` arrives in the same shape with
    both filled and there the separator is real and drawn between them.

    It is drawn either way, and the narrow rule cost the whole text
    layer. A character in an attribute is in no `m:t`, so `docxkit
    text`, `compare`'s TEXT layer and every per-paper gate written
    against extracted text read `(c_ij − c̄_j)` as `cijcj`. Measured:
    `(a+b)` against `(a−b)` produced no finding on ANY layer of compare.

    What the two spellings do to the PAGE was measured too, through
    Word: `(x, y)` renders identically, while a binary operator as
    `m:sepChr` is set TIGHT — `(a+b)`, punctuation spacing — and gets
    the medium space it is owed only once it is a run. So rejoining is
    the better page as well as the readable markup, and one rule beats
    an operator-vs-separator list nobody could maintain."""
    src = _d(f'<m:sepChr m:val="{sep}"/>',
             f"<m:e>{mr('x')}</m:e>", f"<m:e>{mr('y')}</m:e>")

    out = _normalized(src)

    assert "sepChr" not in out and out.count("<m:e>") == 1
    assert tokens(out) == f"x{sep}y"
    assert f"<m:t>{sep}</m:t>" in out, "the character a text pass can read"


def test_an_EMPTY_separator_is_left_alone():
    """`m:sepChr m:val=""` is what the XSL writes when it put everything
    in one element already — the shape rejoining produces. There is no
    character to move and nothing to rejoin."""
    src = _d('<m:sepChr m:val=""/>', f"<m:e>{mr('x')}{mr(',')}{mr('y')}</m:e>")

    assert _normalized(src) == src


def test_TOKENS_read_a_separator_in_a_document_this_converter_did_not_build():
    """The other half, and the one that reaches manuscripts already
    written: every equation built before the rejoin still holds its
    operator in an attribute, and a reader that walks `m:t` alone cannot
    tell `(a+b)` from `(a−b)`. `tokens` is what `compare`'s FORMULA
    layer fingerprints with."""
    plus = _d('<m:sepChr m:val="+"/>',
              f"<m:e>{mr('a')}</m:e>", f"<m:e>{mr('b')}</m:e>")
    minus = _d('<m:sepChr m:val="−"/>',
               f"<m:e>{mr('a')}</m:e>", f"<m:e>{mr('b')}</m:e>")

    assert tokens(plus) == "a+b" and tokens(minus) == "a−b"


def test_a_separator_is_read_where_it_is_DRAWN_not_where_it_is_STORED():
    """`m:sepChr` sits in `m:dPr`, ahead of every argument, so scraping
    the attribute and appending it reads `+ab`. And the arguments cannot
    be counted by matching `<m:e>`: a subscript inside one has `m:e` of
    its own, which is the shape half this paper's symbols have."""
    sub = "<m:sSub><m:e>" + mr("c") + "</m:e><m:sub>" + mr("ij") \
        + "</m:sub></m:sSub>"
    src = _d('<m:sepChr m:val="−"/>',
             f"<m:e>{sub}</m:e>", f"<m:e>{mr('1')}</m:e>")

    assert tokens(src) == "cij−1"


def test_normalisation_reaches_a_fence_inside_a_fraction():
    """`\\frac{(-)}{(-)}` is where this was found, and the defective
    element is two levels down."""
    bad = ('<m:d><m:dPr><m:sepChr m:val="−"/></m:dPr><m:e/><m:e/></m:d>')
    out = _normalized(omath(f"<m:f><m:num>{bad}</m:num>"
                            f"<m:den>{bad}</m:den></m:f>"))
    assert "<m:e/>" not in out
    assert tokens(out) == "−−"


def _needs_word_and_latex() -> None:
    pytest.importorskip("latex2mathml")
    try:
        find_mml2omml_xsl()
    except PackageError as exc:
        pytest.skip(f"Word not installed here: {exc}")


def test_the_whole_pipeline_produces_a_drawable_overline():
    _needs_word_and_latex()
    out = latex_to_omml(r"\overline{v}_i")
    assert "―" not in out and 'm:val="̅"' in out


def test_the_whole_pipeline_keeps_a_parenthesised_sign():
    _needs_word_and_latex()
    assert tokens(latex_to_omml(r"(-1)")) == "−1"
    assert "<m:e/>" not in latex_to_omml(r"\frac{(-)}{(-)}")


# --- the documented pair must compose ---------------------------------


def _harvestable() -> str:
    """A document whose equation is BARE, as a real one is.

    The namespace is declared on the part's root; the m:oMath inherits
    it and carries no declaration of its own. Writing xmlns:m on the
    equation itself — as this fixture first did — hands harvest a
    fragment that already parses, so the defect cannot appear.
    """
    return document(para(
        "<m:oMath><m:r><m:t>λ</m:t></m:r>"
        "<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num>"
        "<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>"))


def test_clone_composes_with_harvest():
    """A fragment sliced out of document.xml inherits its namespace
    declarations from the part's root, so it carries none of its own and
    etree.fromstring rejects it. harvest produced exactly what clone
    could not read, though the two are documented as a pair."""
    from lxml import etree

    frag = harvest(_harvestable(), "λ")
    assert "xmlns:m=" in frag                       # parses on its own
    etree.fromstring(frag.encode("utf-8"))
    out = clone(frag)
    assert "<m:t>λ</m:t>" in out
    assert clone(out) == out                        # and again


def test_clone_still_accepts_a_freshly_built_equation():
    """latex_to_omml already declared its namespaces; that path must not
    regress while the harvest one is fixed."""
    # `_needs_word_and_latex`, not `if find_mml2omml_xsl() is None`: the
    # finder RAISES when the XSL is absent and never returns None, so
    # that guard could not fire — the fourth layer of the red CI of
    # 2026-09-03, reached once the `latex` extra was installed there.
    _needs_word_and_latex()
    built = latex_to_omml(r"\lambda")
    assert "<m:oMath" in clone(built)


def test_an_unknown_namespace_prefix_is_named_not_swallowed():
    from docxkit.equations import standalone
    with pytest.raises(AnchorError, match="zz"):
        standalone("<m:oMath><zz:thing/></m:oMath>")


# ------------------------------------------- the FACE of a maths run -----

#: `Parental_style` 2026-08-13: the covariate vector X is bold-italic and
#: must not be renamed; the theory's X is not. The natural guard --
#: `'<w:b/>' in run` -- counted all 32 as italic and 0 as bold, and would
#: have swept four bold X's into the rename.
BOLD_X = ('<m:r><m:rPr><m:sty m:val="bi"/></m:rPr>'
          "<w:rPr><w:rFonts w:ascii=\"Cambria Math\"/></w:rPr>"
          "<m:t>X</m:t></m:r>")
PLAIN_X = ('<m:r><m:rPr><m:sty m:val="p"/></m:rPr><m:t>X</m:t></m:r>')
UNMARKED_X = ('<m:r><w:rPr><w:rFonts w:ascii="Cambria Math"/></w:rPr>'
              "<m:t>X</m:t></m:r>")


def test_face_reads_m_sty_not_w_b():
    from docxkit.equations import face

    assert face(BOLD_X) == "bi"
    assert face(PLAIN_X) == "p"
    assert "<w:b/>" not in BOLD_X, "the whole point: w:b is not there"


def test_an_unmarked_maths_run_renders_ITALIC():
    """OMML's default face is math-italic — a variable is italic because
    it is a variable, which is why a manuscript full of italic symbols
    carries no markup for it."""
    from docxkit.equations import DEFAULT_FACE, face

    assert face(UNMARKED_X) == "i" == DEFAULT_FACE


def test_is_bold_separates_the_two_X_populations():
    from docxkit.equations import is_bold, is_italic

    assert is_bold(BOLD_X)
    assert not is_bold(PLAIN_X)
    assert not is_bold(UNMARKED_X), "the enumeration that said 'bold: 0'"
    assert is_italic(BOLD_X) and is_italic(UNMARKED_X)
    assert not is_italic(PLAIN_X)


def test_the_rarer_w_rPr_spelling_is_read_second():
    """Some producers put the bold in w:rPr instead. Read after m:sty,
    never instead of it."""
    from docxkit.equations import face

    assert face('<m:r><w:rPr><w:b/><w:i/></w:rPr><m:t>X</m:t></m:r>') == "bi"
    assert face('<m:r><w:rPr><w:b/></w:rPr><m:t>X</m:t></m:r>') == "b"
    # m:sty wins when both are stated
    assert face('<m:r><m:rPr><m:sty m:val="p"/></m:rPr>'
                "<w:rPr><w:b/></w:rPr><m:t>X</m:t></m:r>") == "p"


def test_a_switched_OFF_w_b_is_not_bold():
    from docxkit.equations import face

    assert face('<m:r><w:rPr><w:b w:val="0"/></w:rPr>'
                "<m:t>X</m:t></m:r>") == "i"


# --- standalone: the half of the harvest/clone pair nothing tested ------
#
# `harvest` gives you an element sliced out of `word/document.xml`, and
# a slice inherits its namespace declarations from the part's root — so
# it carries none, and `etree.fromstring` refuses it. `standalone` is
# what makes the slice parse on its own, and the whole harvest -> clone
# workflow this module documents goes through it. It had no test of its
# own: every mutant in it survived the 2026-08-19 measurement, including
# one that reads `root[1]` of a one-element fragment.


def test_standalone_gives_a_harvested_fragment_its_own_declarations():
    """The documented pair, end to end: what `harvest` returns is what
    `clone` has to be able to read."""
    from docxkit.equations import standalone

    naked = "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"

    out = standalone(naked)

    assert f'xmlns:m="{M_NS}"' in out
    assert clone(out)                      # parses on its own now


def test_standalone_refuses_TWO_elements_rather_than_keeping_the_first():
    """`len(root) != 1`. Taking `root[0]` and dropping the rest is the
    silent version: two equations go in, one comes back, and the
    difference is a formula nobody notices is missing."""
    from docxkit.equations import standalone

    two = (omath(mr("x")) + omath(mr("y"))).replace(
        f' xmlns:m="{M_NS}"', "", 1)

    with pytest.raises(AnchorError, match="got 2"):
        standalone(two)


def test_standalone_refuses_a_SENTENCE_around_the_equation():
    """Text before the element, and text after it — `root.text` and
    `root[0].tail`. Serialising the element alone would drop either one,
    and the caller is inserting the result into a document: the words
    would simply be gone from the paragraph they were written in."""
    from docxkit.equations import standalone

    naked = "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"

    with pytest.raises(AnchorError, match="no text around it"):
        standalone("where " + naked)
    with pytest.raises(AnchorError, match="no text around it"):
        standalone(naked + " for every i")
    # whitespace is not a sentence: a fragment sliced with its
    # surrounding newline still passes
    assert standalone("\n  " + naked + "\n")


def test_standalone_refuses_a_PREFIX_nothing_declares():
    """The refusal that keeps a made-up URI out of a document: a prefix
    the fragment uses and nothing binds cannot be guessed, and a
    placeholder would SHIP inside the manuscript. The message names the
    prefix and the way to resolve it."""
    from docxkit.equations import standalone

    fragment = ("<m:oMath><m:r><zz:ann>note</zz:ann><m:t>x</m:t>"
                "</m:r></m:oMath>")

    with pytest.raises(AnchorError, match=r"\['zz'\]"):
        standalone(fragment)


def test_standalone_takes_an_unknown_prefix_from_the_PART_it_came_from():
    """`source=` — the part's root binds every prefix the document
    really uses, and reading the URI off it is what makes a redline's
    math (w14, wp14, whatever the paper's Word wrote) harvestable."""
    from docxkit.equations import standalone

    part = ('<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main" xmlns:zz="urn:example:zz"/>')
    fragment = ("<m:oMath><m:r><zz:ann>note</zz:ann><m:t>x</m:t>"
                "</m:r></m:oMath>")

    out = standalone(fragment, source=part)

    assert 'xmlns:zz="urn:example:zz"' in out
    assert "urn:docxkit:undeclared" not in out


def test_harvest_names_the_index_it_does_not_have_at_the_BOUNDARY():
    """`index >= len(hits)`, and `>` is invisible at a distance: with
    two equations, index 5 is refused either way and index 2 is the one
    that parts them. Past the bound the list is indexed anyway, and the
    author gets an IndexError instead of a sentence naming how many
    equations actually match."""
    xml = document(para(omath(mr("x"))) + para(omath(mr("x"))))

    assert tokens(harvest(xml, "x", index=1)) == "x"
    with pytest.raises(AnchorError, match="2 equations contain 'x', no "
                                          "index 2"):
        harvest(xml, "x", index=2)


def test_the_gap_message_quotes_SIXTY_characters_of_the_equation():
    """`tokens(omml)[:60]`. The quote is how a person finds the formula
    the converter could not render; uncut, one refusal prints a whole
    display equation, and `strict=True` is used by callers that
    convert every equation in a document."""
    from docxkit.errors import ConversionGap

    long_math = omath(mr("x" * 80) + "<m:zzz/>")

    with pytest.raises(ConversionGap) as exc:
        to_latex(long_math, strict=True)

    assert "x" * 60 in str(exc.value)
    assert "x" * 61 not in str(exc.value)


def test_a_TRACKED_insertion_inside_an_equation_keeps_its_TEXT():
    """`_text(el.text or "")`, on the `w:t` branch — the one a REDLINE
    reaches: Word wraps inserted math in `w:ins`, and the text then
    hangs off a WordprocessingML run inside the equation. `and` in place
    of `or` renders every such run as nothing, so a formula that was
    edited under track-changes converts to the half that was not.

    The empty form is here too, and it is the same recurring shape: an
    element with no text is self-closing, and `el.text` is then None
    rather than "" — which the mutant hands straight to the character
    mapper."""
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def redlined(inner: str) -> str:
        return (f'<m:oMath xmlns:m="{M_NS}" xmlns:w="{W_NS}">{inner}'
                + mr("y") + "</m:oMath>")

    kept = "<w:ins><w:r><w:t>x=</w:t></w:r></w:ins>"
    empty = "<w:ins><w:r><w:t/></w:r></w:ins>"
    dropped = "<w:del><w:r><w:t>gone</w:t></w:r></w:del>"

    assert to_latex(redlined(kept)) == "x=y"
    assert to_latex(redlined(empty)) == "y"
    assert to_latex(redlined(dropped)) == "y"


# --- what is left in the walk's own helpers, and why --------------------
#
# `_local`: `tag.rsplit("}", 1)[-1] if "}" in tag else tag`. The
# maxsplit is 1, so a tag WITH a brace splits into exactly two parts and
# `[-1]`, `[1]` and `[+1]` are the same element; a tag without one never
# reaches the subscript. Argued rather than tested.


# --- what is left in equations.py, and why ------------------------------
#
# Every survivor from the 2026-08-19 measurement is now killed or here.
# The arguments, each kill_check'd as an equivalence rather than assumed:
#
#   `_MATH_GLYPHS = frozenset(_SYMBOLS) | frozenset(_NARY)` -> `^`. The
#   two tables are disjoint — measured, 85 glyphs either way — so union
#   and symmetric difference agree. They would NOT agree if a character
#   were ever added to both, and the mutant is the shape of that bug:
#   the shared glyph would silently leave the vocabulary.
#
#   `_mval(el, "rPr/sty") == "p"` -> `>=`. The legal values are p, b, i
#   and bi; only "p" is >= "p", so the comparison cannot separate them
#   differently over the domain the schema allows.
#
#   `if ns == _W_NS` -> `>=`, and `parent.tag == _M + "accPr"` -> `<=`.
#   Both compare against a fixed URI or tag, and every namespace and
#   element the walk actually meets sorts on the same side of it.
#
#   `if name == "t"` -> `is`. A one-character string is one object in
#   CPython however it was made, including a slice of a tag.
#
#   `tag.rsplit("}", 1)[-1]` -> `[1]`, `[+1]`. maxsplit is 1, so the
#   part after the brace is both the last element and the second.
#
#   `if k + 1 < len(pieces)` in `prose_math`, seven of them: the guard
#   cannot fire, argued in test_prose_math.py with the measurement.
#
#   `latex_to_omml`'s three need Word's MML2OMML.XSL, which a plain
#   install does not have; the test that would reach them skips.


# --- the run of 2026-08-20: 4.3 % (18/416) ----------------------------


def test_a_separator_with_NO_character_rejoins_nothing():
    """`if sep_el is None or not sep`. An `m:sepChr` may carry no
    `m:val` at all — the default separator — and there is no character
    to rejoin the halves with. Read as `and`, the guard needs BOTH to
    be true, so a valueless element falls through and the two halves
    are merged with a text node of nothing: the empty `m:e` disappears
    and the gap it drew becomes no gap and no sign.

    The empty element is what the papers see (`(   −1)`), so the repair
    matters; doing it with nothing to insert is a silent edit."""
    out = _normalized(_d("<m:sepChr/>", "<m:e/>", f"<m:e>{mr('1')}</m:e>"))

    assert "<m:e/>" in out, "nothing to rejoin with, so nothing rejoined"
    assert out.count("<m:e>") == 1
    assert tokens(out) == "1"


def test_standalone_refuses_a_fragment_with_NO_element():
    """`len(root) != 1` covers both sides of "exactly one". Read as
    `> 1`, an empty fragment falls through the raise into `root[0]` —
    an IndexError from inside the converter, where the message it
    replaces says what was expected and what arrived."""
    from docxkit.equations import standalone
    from docxkit.errors import AnchorError

    with pytest.raises(AnchorError, match="got 0"):
        standalone("")
    with pytest.raises(AnchorError, match="got 2"):
        standalone(omath(mr("x")) + omath(mr("y")))


def test_a_delimiter_with_THREE_arguments_keeps_BOTH_separators():
    """The rejoin walks every argument after the first, not just the
    second. `\\left(a\\middle|b\\middle|c\\right)` is the shape, and a
    guard that asks for exactly two arguments leaves it unrejoined —
    with the separator still in an attribute, where no token stream can
    see it and a sign flip inside the fence stays invisible."""
    three = ('<m:d><m:dPr><m:sepChr m:val="|"/></m:dPr>'
             f"<m:e>{mr('a')}</m:e><m:e>{mr('b')}</m:e>"
             f"<m:e>{mr('c')}</m:e></m:d>")

    assert tokens(omath(three)) == "a|b|c"


# --- the defensive halves nothing had reached (2026-09-18) ------------


def test_a_paragraph_whose_MATHS_is_deleted_is_not_a_display_equation():
    """The other half of the accepted view. `_accepted_side` takes the
    deletion out, and what is left carries no `m:oMath` at all — so the
    paragraph is not a display equation, and reporting it as one names a
    repair for markup on its way out of the document."""
    deleted = ('<w:p><w:del w:id="1" w:author="R" '
               f'w:date="2026-01-01T00:00:00Z">{omath(mr("x"))}'
               "</w:del></w:p>")

    assert is_display(deleted) is False
    assert display_equations(document(deleted)) == []


def test_an_UNPARSABLE_token_stream_is_handed_back_rather_than_raised():
    """`tokens` reads a separator by parsing, and a token stream is not
    worth a hard failure: a fragment that will not parse is returned as
    it came. The `except` is the whole of that promise."""
    broken = '<m:d><m:dPr><m:sepChr m:val="|"/></m:dPr><m:e><m:r>'

    assert tokens(broken) == ""


def test_a_maths_run_whose_properties_state_NO_face_is_left_alone():
    """`m:rPr` without an `m:sty` is the ordinary shape — a run carrying
    an alignment or a break and nothing about its face. The upright test
    asks the properties for a value that is not there, and gets None."""
    run_xml = ("<m:r><m:rPr><m:aln/></m:rPr><m:t>x</m:t></m:r>")

    assert to_latex(omath(run_xml)) == "x"


def test_the_XSL_is_taken_from_the_CANDIDATES_before_the_glob(
        tmp_path, monkeypatch):
    """The candidate list names the paths Office uses; the glob under it
    is the fallback for an install somewhere else. A candidate that
    exists is the answer, and the glob is not consulted."""
    from docxkit import equations

    fake = tmp_path / "MML2OMML.XSL"
    fake.write_text("<xsl/>", encoding="utf-8")
    monkeypatch.setattr(equations, "_XSL_CANDIDATES", (str(fake),))

    assert equations.find_mml2omml_xsl() == fake


def test_the_GLOB_is_the_last_resort_and_takes_the_FIRST_hit(monkeypatch):
    """With no candidate matching, the search widens to Office's whole
    tree. The skip is decided HERE, from this machine's own glob, rather
    than from what the function answers — a skip taken on the function's
    refusal would read a broken search as "no Office"."""
    from pathlib import Path

    from docxkit import equations

    hits = sorted(Path(r"C:\Program Files").glob(
        "Microsoft Office/**/MML2OMML.XSL"))
    if not hits:
        pytest.skip("no Office install for the glob to find")
    monkeypatch.setattr(equations, "_XSL_CANDIDATES", ())

    assert equations.find_mml2omml_xsl() == hits[0]


# --- where the ALIGNMENT is written (2026-09-18) ----------------------
#
# `m:oMathParaPr` arrives in three shapes — absent, self-closing, and
# present with or without an `m:jc` inside — and `_set_math_jc` splices
# a string for each. Thirty-nine mutants lived there, most of them the
# `+` of a splice written as another operator, which any assertion on
# the whole paragraph kills; the two that are about the BEHAVIOUR are
# the test for the self-closing form and the count of the substitution.

_CENTRED = '<m:jc m:val="center"/>'


def _display_para(pr: str) -> str:
    return (f"<w:p><m:oMathPara>{pr}"
            f"<m:oMath>{mr('x')}</m:oMath></m:oMathPara></w:p>")


@pytest.mark.parametrize("have", [
    pytest.param("", id="no_properties_at_all"),
    pytest.param("<m:oMathParaPr/>", id="self_closing"),
    pytest.param("<m:oMathParaPr></m:oMathParaPr>", id="empty_but_paired"),
    pytest.param('<m:oMathParaPr><m:jc m:val="left"/></m:oMathParaPr>',
                 id="an_alignment_to_replace"),
])
def test_the_alignment_lands_in_the_properties_whatever_shape_they_are_in(
        have):
    """One answer from four starting points, byte for byte. The
    self-closing form is the one with no `</m:oMathParaPr>` to find: read
    as the paired form it sends `str.index` looking for a close tag that
    is not there, and the paragraph comes back as a ValueError from
    inside a formatting call."""
    from docxkit.equations import _set_math_jc

    got = _set_math_jc(_display_para(have), "center")

    assert got == _display_para(
        f"<m:oMathParaPr>{_CENTRED}</m:oMathParaPr>")


def test_an_alignment_is_replaced_rather_than_ADDED_beside_the_old_one():
    """The substitution's count is 1 because `m:jc` is the only child
    `m:oMathParaPr` has: two of them is not a document Word writes or
    keeps."""
    from docxkit.equations import _set_math_jc

    got = _set_math_jc(_display_para(
        '<m:oMathParaPr><m:jc m:val="left"/></m:oMathParaPr>'), "right")

    assert got.count("<m:jc") == 1
    assert 'm:val="right"' in got and 'm:val="left"' not in got


def test_a_paragraph_with_no_display_maths_is_returned_UNTOUCHED():
    from docxkit.equations import _set_math_jc

    inline = f"<w:p><m:oMath>{mr('x')}</m:oMath></w:p>"

    assert _set_math_jc(inline, "center") == inline


# --- the ACCEPTED side of a redline (2026-09-18) ----------------------


def test_a_paragraph_whose_prose_is_DELETED_is_read_without_it():
    """`math --check` reads `visible_text`, which drops `w:delText` and
    keeps `m:t` — so a paragraph on its way OUT of the document reads as
    maths and nothing else, the exact signature of a stranded display.
    It reported one, with a remedy that would have wrapped an equation
    the author was removing (Aging_Well R78).

    Fourteen mutants lived in the pass that resolves this: the guard
    that looks for a deletion at all, the walk over the spans, and the
    splice that takes each one out."""
    from docxkit.equations import _accepted_side

    para_xml = (
        "<w:p>"
        '<w:del w:id="1" w:author="R" w:date="2026-01-01T00:00:00Z">'
        "<w:r><w:delText>The identity </w:delText></w:r></w:del>"
        f"<m:oMath>{mr('x')}</m:oMath>"
        '<w:del w:id="2" w:author="R" w:date="2026-01-01T00:00:00Z">'
        "<w:r><w:delText> follows.</w:delText></w:r></w:del>"
        "</w:p>")

    got = _accepted_side(para_xml)

    assert got == f"<w:p><m:oMath>{mr('x')}</m:oMath></w:p>"
    assert "w:del" not in got


def test_a_paragraph_with_NO_deletion_is_handed_back_as_it_stands():
    """The early return, and the reason the guard is a regex rather than
    an `in`: a `w:delText` inside a `w:del` is named by both, and a
    paragraph carrying neither must not be walked at all."""
    from docxkit.equations import _accepted_side

    para_xml = f"<w:p><w:r><w:t>Plain.</w:t></w:r>{omath(mr('x'))}</w:p>"

    assert _accepted_side(para_xml) == para_xml


# --- the width table of `_space_text` (2026-09-18) --------------------
#
# `\qquad` is 2em, `\,` is a sixth of one, and what the spacing repair
# DRAWS for a width is arithmetic over three characters: an em space per
# whole unit, then an en or a thin space for the remainder. The tests
# above assert that a gap exists, that a wider command gives a wider one
# and that a negative one draws nothing — none of which pins the
# arithmetic, and seventeen mutants lived in it.
#
# Held as a table, both directions: a width whose answer changes fails
# its own row, and the module's three space characters are named here so
# that swapping one for an ASCII space fails too.

EM_SPACE, EN_SPACE, THIN_SPACE = " ", " ", " "


@pytest.mark.parametrize("width,drawn", [
    pytest.param("", "", id="nothing_at_all"),
    pytest.param("junk", "", id="not_a_width"),
    pytest.param("2", "", id="no_unit"),
    pytest.param("1.2.3em", "", id="matches_the_pattern_but_is_no_number"),
    pytest.param("0em", "", id="zero"),
    pytest.param("-0.5em", "", id="a_negative_fraction"),
    pytest.param("-2em", "", id="a_negative_whole"),
    pytest.param("1em", EM_SPACE, id="one_em"),
    pytest.param("2em", EM_SPACE * 2, id="two_em"),
    pytest.param(" 2em ", EM_SPACE * 2, id="spaces_round_the_width"),
    pytest.param("3em", EM_SPACE * 3, id="three_em"),
    pytest.param("0.2em", THIN_SPACE, id="a_thin_remainder"),
    pytest.param("0.39em", THIN_SPACE, id="just_under_the_en_cut"),
    pytest.param("0.4em", EN_SPACE, id="exactly_the_en_cut"),
    pytest.param("0.5em", EN_SPACE, id="an_en_remainder"),
    pytest.param("1.2em", EM_SPACE + THIN_SPACE, id="whole_plus_thin"),
    pytest.param("1.5em", EM_SPACE + EN_SPACE, id="whole_plus_en"),
    pytest.param("2.5em", EM_SPACE * 2 + EN_SPACE, id="two_whole_plus_en"),
])
def test_what_a_spacing_WIDTH_draws(width, drawn):
    """The cut is at 0.4 of an em: at or above it an en space, below it
    and above zero a thin one, and nothing at all for a remainder of
    zero. `1.2.3em` matches the width pattern and is not a number, which
    is the one input that reaches the `except` — there is no other way
    into it, since the pattern admits only digits and dots."""
    from docxkit.equations import _space_text

    assert _space_text(width) == drawn


def test_the_three_SPACE_characters_are_the_ones_the_module_uses():
    """The other direction of the table above: the widths are held
    against these three, so a repair that drew an ASCII space — the very
    character `edit.preserve_space` exists to rescue from Word — would
    pass every row while changing what reaches the page."""
    from docxkit import equations

    assert (equations._EM_SPACE, equations._EN_SPACE,
            equations._THIN_SPACE) == (EM_SPACE, EN_SPACE, THIN_SPACE)
    assert " " not in EM_SPACE + EN_SPACE + THIN_SPACE


# The other sixteen are equivalent by construction, each checked with
# `kill_check`:
#
# * the four on `prose_math`'s `pieces[k + 1] if k + 1 < len(pieces)`
#   and its neighbour. The pieces come from splitting on a sentinel
#   this function itself substituted for every equation, so there are
#   exactly `len(maths) + 1` of them and the guard cannot fire: `<=`,
#   `!=`, `is not` and `k // 1` all answer the same thing over the
#   range `k` actually takes.
# * `display`'s `maths[0]` as `maths[-1]`, and `standalone`'s `root[0]`
#   — both are guarded by a raise unless there is exactly one.
# * `face`'s `if italic: return "i"`. OMML's default face IS italic, so
#   the branch and the fallthrough return the same string; `not italic`
#   swaps two answers that are equal.
# * `walk`'s `name == "t"` as `>=`. The names that sort at or above it
#   in the `w` namespace — `tab`, `tbl`, `tc`, `tr` — carry no element
#   TEXT, so `_text(el.text or "")` and the `return ""` beneath agree.
# * `walk`'s `ns == _W_NS` as `>=`. The math namespace sorts BELOW the
#   wordprocessing one (`officeDocument` before `wordprocessingml`), and
#   so does every other namespace an equation carries.
# * `e_d`'s `len(...) > 1` as `!= 1`: with no `m:e` at all the join over
#   an empty list and `bare` both answer "".
# * `_local`'s `rsplit("}", 1)[-1]` as `rsplit("}", 2)[-1]` — the last
#   piece is the last piece.
# * `_MATH_GLYPHS`' `-` as `^`: `_INVISIBLE` is a subset of the union it
#   is taken from, so the symmetric difference IS the difference.
# * `_rejoin_at_separator`'s `len(els) < 2` as `< 1`. A single `m:e` has
#   nothing to rejoin: every write in the function is inside
#   `for other in els[1:]`, which is empty.
# * `find_mml2omml_xsl`'s `if hits:` inverted. That branch is the glob
#   over `C:\Program Files` reached only when Office is installed
#   somewhere the candidate list does not name — which no test can
#   arrange, and which the message beneath it is written for.
