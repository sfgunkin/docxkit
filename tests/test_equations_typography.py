"""What the LaTeX chain loses on the way to the page.

Three defects of one family, all found on real manuscripts in one
evening: spacing commands dropped, operator names set italic, and the
prime downgraded to an apostrophe. Each produces VALID OMML with the
right `m:oMath` count, a clean `math --check`, a clean `lint`, a
`to_latex` that round-trips, and a `compare` whose text layer is silent
because no character moved.

**The only instrument that detects any of them is a rendered page.**
That is why this file has two halves: fast assertions on the markup for
the everyday suite, and a `-m word` render that asserts on what Word
actually draws. The second half exists because the first half is not
enough — the operator fix passed every markup assertion in its first
form while making the page WORSE, taking the italic operand upright
with the operator, and only the render showed it.
"""
from __future__ import annotations

import re

import pytest

from docxkit.equations import latex_to_omml

# Every test here builds its maths from LaTeX, which needs the `latex`
# extra. Without this line the file FAILED 22 tests on a checkout that
# lacked it — which CI was, from the day this file landed (2026-08-24)
# until 2026-09-03: twelve red runs, unread. CI installs the extra now,
# so there they run; here they skip and say why.
pytest.importorskip("latex2mathml", reason="needs docxkit[latex]")

UPRIGHT = '<m:sty m:val="p"/>'
#: Word draws a variable from the Mathematical Alphanumeric block; an
#: upright operator name stays ASCII. The render can therefore be read
#: by machine rather than by eye.
MATH_ALNUM = range(0x1D400, 0x1D800)

OPERATORS = ["log", "exp", "sin", "ln", "max", "min", "lim", "sup"]


def _runs(omml: str) -> list[tuple[str, bool]]:
    """(text, is upright) for every run, in order."""
    out = []
    for run in re.findall(r"<m:r>.*?</m:r>", omml, re.DOTALL):
        text = re.search(r"<m:t[^>]*>(.*?)</m:t>", run, re.DOTALL)
        out.append((text.group(1) if text else "", UPRIGHT in run))
    return out


# ----------------------------------------------------------- operators

@pytest.mark.parametrize("name", OPERATORS)
def test_every_operator_NAME_is_upright(name):
    """Not "operator styling is missing" — INCONSISTENT. `\\log`,
    `\\exp`, `\\sin` and `\\ln` arrive from latex2mathml as `mi` and
    were always upright; `\\max`, `\\min`, `\\lim` and `\\sup` arrive as
    `mo` and rendered as three or four italic variables. Nobody noticed
    until a paper needed a constrained optimization."""
    runs = _runs(latex_to_omml(rf"\{name} x"))

    assert (name, True) in runs, runs


def test_the_OPERAND_stays_italic():
    """The assertion that would have caught the first fix.

    Marking the OMML run upright looked right in the markup and was
    wrong on the page: left as `mo`, the XSL merges the operator into
    its operand as a single `<m:t>maxx</m:t>`, so styling that run took
    the VARIABLE upright too. Retagging in the MathML instead gives the
    shape `\\log` always had — two runs, one upright, one not.
    """
    runs = _runs(latex_to_omml(r"\max x"))

    assert runs == [("max", True), ("x", False)], runs


def test_operatorname_is_upright_whatever_it_names():
    """`\\operatorname{…}` takes an arbitrary name, so a fixed list of
    operators would not cover it. The rule is two-or-more letters."""
    runs = _runs(latex_to_omml(r"\operatorname{argmax} x"))

    assert ("argmax", True) in runs, runs


def test_a_SINGLE_letter_is_left_italic():
    """One letter is a variable, and italic is right for it. The rule
    has to be about names, not about `mo`."""
    runs = _runs(latex_to_omml(r"a + b"))

    assert all(not upright for _, upright in runs), runs


def test_a_SYMBOL_operator_is_untouched():
    """`mo` carries every symbol too — ∈, +, =. Retagging those would
    change how Word spaces them."""
    omml = latex_to_omml(r"a \in A")

    assert "∈" in omml
    assert [t for t, upright in _runs(omml) if upright] == []


def test_an_explicitly_ITALIC_name_keeps_what_it_asked_for():
    runs = _runs(latex_to_omml(r"\mathit{max}"))

    assert not any(upright for _, upright in runs), runs


# ------------------------------------------------------------- spacing

@pytest.mark.parametrize("latex", [
    r"x \qquad y", r"x \quad y", r"x \hspace{2em} y", r"x \; y",
    r"x \, y", r"x \: y",
])
def test_every_spacing_command_SURVIVES(latex):
    """Word's XSL has no template for `mspace`, so all of these vanished
    into valid markup — on Aging_Well, running a definition into its
    sign conditions in all nine equations of one batch."""
    spaces = [t for t, _ in _runs(latex_to_omml(latex))
              if t and not t.strip()]

    assert spaces, f"the gap in {latex!r} was dropped"


def test_a_WIDER_command_produces_a_wider_gap():
    """`\\qquad` is 2em and `\\,` is a sixth of one. A repair that made
    every gap the same width would pass the test above."""
    def width(latex: str) -> int:
        return sum(len(t) * (3 if "\u2003" in t else 1)
                   for t, _ in _runs(latex_to_omml(latex))
                   if t and not t.strip())

    assert width(r"x \qquad y") > width(r"x \quad y") > width(r"x \, y")


def test_a_NEGATIVE_space_draws_nothing():
    """`\\!` is negative and Word has no negative space to draw. Leaving
    an empty run behind would be worse than dropping it."""
    spaces = [t for t, _ in _runs(latex_to_omml(r"x \! y"))
              if t and not t.strip()]

    assert spaces == []


def test_the_gap_is_not_an_ASCII_space():
    """A plain space in `m:t` is exactly what `edit.preserve_space`
    exists to rescue from Word, and putting one here would be inventing
    that problem. These are em/en/thin spaces, which are not XML
    whitespace and cannot be collapsed or trimmed."""
    gaps = [t for t, _ in _runs(latex_to_omml(r"x \quad y"))
            if t and not t.strip()]

    assert gaps and all(" " not in g for g in gaps), gaps


# ------------------------------------------------- what the PAGE shows

@pytest.mark.word
def test_the_RENDER_shows_upright_operators_and_italic_variables(tmp_path):
    """The gate this family needs, and the one nothing in the ladder
    performs: a real Word render, read by codepoint.

    Word draws a variable from the Mathematical Alphanumeric block and
    an upright operator name in ASCII, so "is the operator upright and
    the operand not" is a machine-readable question about the PAGE
    rather than about the markup that was supposed to produce it.
    """
    pytest.importorskip("fitz", reason="needs docxkit[pdf]")
    import pymupdf

    from docxkit import package
    from docxkit.word import export_pdf

    shell = next(iter(_SHELLS()), None)
    if shell is None:
        pytest.skip("no real .docx available as a package shell")

    body = "".join(f"<w:p>{latex_to_omml(src)}</w:p>"
                   for src in (r"\max x", r"\log x", r"\lim x"))
    parts = package.read_parts(shell)
    doc = parts["word/document.xml"].decode("utf-8")
    at = doc.index("<w:body>") + len("<w:body>")
    parts["word/document.xml"] = (doc[:at] + body
                                  + doc[doc.rindex("</w:body>"):]).encode()
    built = tmp_path / "maths.docx"
    package.write_docx(built, parts)
    pdf = tmp_path / "maths.pdf"
    export_pdf(built, pdf)

    text = pymupdf.open(pdf)[0].get_text()
    for name in ("max", "log", "lim"):
        assert name in text, f"{name} is not upright on the page: {text!r}"
    assert any(ord(c) in MATH_ALNUM for c in text), \
        "no math-italic variable on the page — the operand went upright too"


def _SHELLS():
    """A real package to build the render on.

    The synthetic fixtures are enough for this library to parse and not
    enough for Word to open — "The file appears to be corrupted" — which
    is itself the reason this test is a render and not an assertion.
    """
    from pathlib import Path
    for candidate in Path(r"F:\OneDrive\__Documents").glob("*.docx"):
        if not candidate.name.startswith("~$"):
            yield candidate
            return
