"""Equations: the LaTeX pipeline, harvesting, and formula fingerprints."""
from __future__ import annotations

import pytest
from conftest import document, para, run

from docxkit.errors import AnchorError, PackageError
from docxkit.math import (
    clone,
    display_equations,
    equations,
    find_mml2omml_xsl,
    harvest,
    is_display,
    latex_to_omml,
    skeleton,
    tokens,
)

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
