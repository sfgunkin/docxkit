"""What a rejected view keeps of an equation object the rejection emptied.

Measured 2026-10-31 with `tools/view_oracle.py --word` over 831 redlines.
An author who types INTO an existing delimiter or fraction under tracking
leaves the object unmarked and its new runs inserted. Word's Reject All
removes the runs and keeps the object standing, glyphless: four ``()``
and a fraction box in CC_age_gap's `ACC6_ARINA_07102024.docx`. The
engine pruned them, as it rightly does for Accept. The run itself does
not stay (pruning nothing broke 45 files Word agrees with), and neither
does an equation left with no glyph at all (keeping those broke 94).
"""
from __future__ import annotations

import re

from docxkit.revisions import accept, reject

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
      '2006/main" xmlns:m="http://schemas.openxmlformats.org/'
      'officeDocument/2006/math"')


def mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def tracked(kind: str, text: str, rid: int) -> str:
    """A math run inserted or deleted, the way Word wraps one."""
    return (f'<w:{kind} w:id="{rid}" w:author="A" '
            f'w:date="2026-10-31T00:00:00Z">{mr(text)}</w:{kind}>')


def delim(inner: str) -> str:
    return f"<m:d><m:e>{inner}</m:e></m:d>"


def frac(num: str, den: str) -> str:
    return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"


def doc(*maths: str) -> str:
    paras = "".join(f"<w:p><m:oMath>{m}</m:oMath></w:p>" for m in maths)
    return f"<w:document {NS}><w:body>{paras}</w:body></w:document>"


def glyphs(xml: str) -> list[str]:
    return re.findall(r"<m:t>([^<]*)</m:t>", xml)


def test_REJECT_keeps_the_delimiters_an_insertion_was_typed_into():
    """The ARINA shape: three existing delimiters, a run typed into each,
    among five original runs. Word keeps three empty `()`."""
    eq = (mr("y") + mr("=") + delim(tracked("ins", "a", 1)) + mr("+")
          + delim(tracked("ins", "b", 2)) + mr("+")
          + delim(tracked("ins", "c", 3)))

    out = reject(doc(eq))

    assert glyphs(out) == ["y", "=", "+", "+"]
    assert out.count("<m:d><m:e/></m:d>") == 3       # empty, the runs gone


def test_REJECT_keeps_a_fraction_box_but_not_an_emptied_run():
    eq = mr("x") + frac(tracked("ins", "1", 1), tracked("ins", "2", 2))

    out = reject(doc(eq))

    assert out.count("<m:f>") == 1
    assert glyphs(out) == ["x"]
    assert "<m:t></m:t>" not in out and "<m:t/>" not in out


def test_ACCEPT_still_prunes_the_delimiters_a_deletion_emptied():
    """Five deleted runs, each in its own delimiter, beside seven kept:
    Word's Accept All leaves no empty box, and nor does the engine."""
    eq = "".join(mr(c) for c in "abcdefg") + "".join(
        delim(tracked("del", c, i)) for i, c in enumerate("vwxyz", 1))

    out = accept(doc(eq))

    assert "<m:d>" not in out
    assert glyphs(out) == list("abcdefg")


def test_REJECT_still_drops_an_equation_left_with_no_glyph():
    """Every glyph inserted, inside an existing fraction: the equation
    goes whole, as Word's does — beside one that keeps its glyphs."""
    out = reject(doc(frac(tracked("ins", "1", 1), tracked("ins", "2", 2)),
                     mr("z")))

    assert out.count("<m:oMath>") == 1
    assert "<m:f>" not in out
    assert glyphs(out) == ["z"]
