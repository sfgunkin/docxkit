r"""Equations: building OMML, reusing it, and reading it back.

Equations touch more of these papers than anything else — about fifty
files — and had been solved separately in each: DSI's ``omml_lib``,
AFI's ``v10_math`` / ``convert_text_to_omml`` / ``number_equations``, and
the ``omath()`` / ``omath_display()`` helpers re-written inside the VLI,
FLOPs, Life Expectancy and life-expectancy-trends generators.

Two rules the papers arrived at the hard way:

* **Do not hand-assemble OMML from a LaTeX string.** Go through
  ``latex2mathml`` to presentation MathML and then Word's own
  ``MML2OMML.XSL``. Word wrote that transform; a hand-built element
  renders subtly differently, if at all.
* **When an equation reuses symbols already in the document, harvest the
  existing ``<m:oMath>`` and deepcopy it** rather than rebuilding from
  LaTeX. That is the only way to guarantee the new equation renders
  identically to the surrounding ones.

Verify the result visually by exporting to PDF through Word
(:func:`docxkit.word.export_pdf`) — Word keeps the math, LibreOffice does
not.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from ._xml import PARA_RE, visible_text
from .errors import AnchorError, PackageError

__all__ = [
    "OMATH_RE",
    "Equation",
    "clone",
    "display_equations",
    "equations",
    "find_mml2omml_xsl",
    "harvest",
    "is_display",
    "latex_to_omml",
    "skeleton",
    "tokens",
]

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
# attributes allowed: inside a document the namespace is declared on the
# root and the tag is bare, but a harvested element serialized on its own
# carries xmlns:m, and both have to match
OMATH_RE = re.compile(r"<m:oMath\b[^>]*>.*?</m:oMath>", re.DOTALL)
_MT_RE = re.compile(r"<m:t[^>]*>([^<]*)</m:t>")
# structural OMML elements — the ones that change a formula's shape
_STRUCT = ("sSub", "sSup", "sSubSup", "nary", "f", "d", "rad", "func",
           "acc", "bar", "groupChr", "limLow", "limUpp", "m", "eqArr", "box")
_STRUCT_RE = re.compile(r"<m:(" + "|".join(_STRUCT) + r")\b")

# Word ships the transform with Office; the version folder varies.
_XSL_CANDIDATES = (
    r"C:\Program Files\Microsoft Office\root\Office16\MML2OMML.XSL",
    r"C:\Program Files (x86)\Microsoft Office\root\Office16\MML2OMML.XSL",
    r"C:\Program Files\Microsoft Office\Office16\MML2OMML.XSL",
    r"C:\Program Files\Microsoft Office\root\Office15\MML2OMML.XSL",
)


@dataclass(frozen=True)
class Equation:
    """One ``<m:oMath>``, with the fingerprints used to compare formulas."""

    index: int
    start: int
    end: int
    xml: str

    @property
    def tokens(self) -> str:
        """The symbols, in order — catches a changed variable or number."""
        return tokens(self.xml)

    @property
    def skeleton(self) -> str:
        """The structure — catches a rewrite that keeps the same symbols.

        A fraction turned into a ratio with a solidus has identical
        tokens and a different skeleton; comparing only text misses it.
        """
        return skeleton(self.xml)


def find_mml2omml_xsl(explicit: str | Path | None = None) -> Path:
    """Locate Word's MathML-to-OMML transform.

    Searched rather than hard-coded to one Office version, which is what
    made the per-paper copies break on a different machine.
    """
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise PackageError(f"MML2OMML.XSL not found at {path}")
        return path
    for candidate in _XSL_CANDIDATES:
        if (path := Path(candidate)).exists():
            return path
    hits = sorted(Path(r"C:\Program Files").glob(
        "Microsoft Office/**/MML2OMML.XSL"))
    if hits:
        return hits[0]
    raise PackageError(
        "MML2OMML.XSL not found — it ships with Word. Pass its path "
        "explicitly if Office is installed somewhere unusual.")


def latex_to_omml(latex: str, *, xsl: str | Path | None = None) -> str:
    """Convert LaTeX to an ``<m:oMath>`` element, as an XML string.

    LaTeX -> presentation MathML (latex2mathml) -> OMML (Word's own XSL).
    """
    import latex2mathml.converter
    from lxml import etree

    transform = etree.XSLT(etree.parse(str(find_mml2omml_xsl(xsl))))
    mathml = latex2mathml.converter.convert(latex)
    result = transform(etree.fromstring(mathml.encode("utf-8"))).getroot()
    if result.tag != f"{{{M_NS}}}oMath":
        found = result.find(f".//{{{M_NS}}}oMath")
        if found is None:
            raise PackageError(f"no m:oMath produced for LaTeX: {latex!r}")
        result = found
    return str(etree.tostring(result, encoding="unicode"))


def equations(xml: str) -> list[Equation]:
    """Every ``<m:oMath>`` in the document, in order."""
    return [Equation(index=i, start=m.start(), end=m.end(), xml=m.group(0))
            for i, m in enumerate(OMATH_RE.finditer(xml))]


def tokens(omml: str) -> str:
    """The symbol stream of an equation."""
    import html

    return str(html.unescape("".join(_MT_RE.findall(omml))))


def skeleton(omml: str) -> str:
    """The structural shape of an equation (sSub/nary/f/...)."""
    return "/".join(_STRUCT_RE.findall(omml))


def harvest(xml: str, contains: str, *, index: int = 0) -> str:
    """An existing equation from the document, to deepcopy into a new one.

    When new math reuses symbols the document already renders, copying
    the live element guarantees the result matches — same fonts, same
    spacing, same control properties — where a rebuild from LaTeX only
    usually does.

    `contains` is matched against the equation's symbol stream.
    """
    hits = [e for e in equations(xml) if contains in e.tokens]
    if not hits:
        raise AnchorError(f"no equation whose symbols contain {contains!r}")
    if index >= len(hits):
        raise AnchorError(
            f"{len(hits)} equations contain {contains!r}, no index {index}")
    return hits[index].xml


def clone(omml: str) -> str:
    """A detached copy of an equation element, ready to insert elsewhere."""
    from lxml import etree

    element = etree.fromstring(omml.encode("utf-8"))
    return str(etree.tostring(copy.deepcopy(element),
                              encoding="unicode"))


def is_display(para_xml: str) -> bool:
    """True if a paragraph is a display equation.

    A display equation is a paragraph whose visible content is the maths:
    it carries an ``<m:oMath>`` and no prose beyond an equation number
    and whitespace.
    """
    if "<m:oMath" not in para_xml:
        return False
    # strip the maths first: visible_text includes m:t, so leaving it in
    # would make every display equation look like a paragraph of prose
    prose = visible_text(OMATH_RE.sub("", para_xml))
    without_number = re.sub(r"\(\s*[A-Z]?\.?\d+\s*\)", "", prose)
    return not without_number.strip()


def display_equations(xml: str) -> list[re.Match[str]]:
    """Paragraph matches for every display equation, in body order."""
    return [m for m in PARA_RE.finditer(xml) if is_display(m.group(0))]
