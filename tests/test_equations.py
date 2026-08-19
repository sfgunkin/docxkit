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


def test_display_equations_skips_inline_and_prose():
    found = display_equations(_doc())
    assert len(found) == 1
    assert "(1)" in found[0].group(0)


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
    would show that it had been reordered."""
    with pytest.raises(AnchorError, match="BEFORE"):
        display(para(run("where "), omath(mr("x"))), absorb=True)


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


@pytest.mark.parametrize("sep", [",", "−"])
def test_a_real_separator_between_two_filled_elements_is_untouched(sep):
    """The tell is the EMPTY element, not the separator. `(x,y)` and
    `(a-b)` arrive in exactly this shape with both elements filled, and
    there the separator is real and drawn between them. Firing on the
    separator alone would flatten both."""
    src = _d(f'<m:sepChr m:val="{sep}"/>',
             f"<m:e>{mr('x')}</m:e>", f"<m:e>{mr('y')}</m:e>")
    assert _normalized(src) == src


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
    pytest.importorskip("latex2mathml")
    if find_mml2omml_xsl() is None:
        pytest.skip("MML2OMML.XSL not installed")
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
