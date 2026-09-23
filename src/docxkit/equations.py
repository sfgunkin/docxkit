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

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # lxml is imported lazily below so `import docxkit` does not pay for
    # it; the types are still named, so the stubs see every call here
    # rather than `Any` (which they were until 2026-09-03 — review, row 7).
    from lxml.etree import XSLT, _Element

from ._xml import (
    MT_RE,
    OMML_STRUCT,
    OMML_STRUCT_RE,
    PARA_RE,
    RUN_RE,
    element_spans,
    escape,
    in_span,
    used_prefixes,
    visible_text,
)
from .errors import AnchorError, ConversionGap, PackageError
from .revisions import _fragment_declarations

__all__ = [
    "DEFAULT_FACE",
    "EQ_NUMBER_RE",
    "M_NS",
    "OMATH_RE",
    "XSL_ENV",
    "AnchorError",
    "ConversionGap",
    "Equation",
    "PackageError",
    "ProseMath",
    "clone",
    "display",
    "display_equations",
    "document_symbols",
    "equations",
    "face",
    "find_mml2omml_xsl",
    "harvest",
    "in_display_mode",
    "inline_display",
    "is_bold",
    "is_display",
    "is_italic",
    "latex_to_omml",
    "prose_math",
    "skeleton",
    "standalone",
    "to_latex",
    "tokens",
]

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
# attributes allowed: inside a document the namespace is declared on the
# root and the tag is bare, but a harvested element serialized on its own
# carries xmlns:m, and both have to match
OMATH_RE = re.compile(r"<m:oMath\b[^>]*>.*?</m:oMath>", re.DOTALL)
# public: wordcount counts equation tokens with the SAME matcher
# structural OMML elements — the ones that change a formula's shape.
# The shared definition: `compare`'s FORMULA layer decides whether an
# equation was rewritten by comparing exactly this skeleton, and it kept
# its own copy of the tuple until they were merged.
#
# `OMATH_RE` above stays local on purpose, and the difference is real:
# this module reads HARVESTED elements, which carry xmlns:m when
# serialized on their own, while compare reads document parts. Measured
# 2026-08-11 over 282 manuscripts holding OMML: not one writes an
# attribute on `m:oMath` inside a part. Two inputs, two patterns.
_STRUCT = OMML_STRUCT
_STRUCT_RE = OMML_STRUCT_RE
# "(5)" / "(A.2)" — what a display equation carries besides its math;
# is_display strips it and the markdown export turns it into a \tag
EQ_NUMBER_RE = re.compile(r"\(\s*([A-Z]?\.?\d+)\s*\)")

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


#: Where to find the transform when Office is not in its usual place —
#: or is not installed at all. `latex_to_omml` is the one thing in this
#: package that needs Word's FILE but never needs Word RUNNING, so it is
#: the one thing that can work in CI or on a Linux box, given the path.
XSL_ENV = "DOCXKIT_MML2OMML_XSL"


def find_mml2omml_xsl(explicit: str | Path | None = None) -> Path:
    """Locate Word's MathML-to-OMML transform.

    Searched rather than hard-coded to one Office version, which is what
    made the per-paper copies break on a different machine. Checked in
    order: the argument, ``$DOCXKIT_MML2OMML_XSL``, then the Office
    install — so a machine without Office can still be told where a copy
    lives instead of being locked out of the conversion entirely.
    """
    import os

    for given, whence in ((explicit, "the path given"),
                          (os.environ.get(XSL_ENV), f"${XSL_ENV}")):
        if given:
            path = Path(given)
            if not path.exists():
                raise PackageError(f"MML2OMML.XSL not found at {path} "
                                   f"({whence})")
            return path
    for candidate in _XSL_CANDIDATES:
        if (path := Path(candidate)).exists():
            return path
    hits = sorted(Path(r"C:\Program Files").glob(
        "Microsoft Office/**/MML2OMML.XSL"))
    if hits:
        return hits[0]
    raise PackageError(
        f"MML2OMML.XSL not found — it ships with Word. Pass its path "
        f"explicitly, or set {XSL_ENV}, if Office is installed somewhere "
        f"unusual or not at all.")


#: Compiled stylesheets, by (path, mtime, size). Compiling Word's
#: transform costs 10ms of the 24ms an equation used to take, paid again
#: for every equation in the paper — and a build converts dozens. Keyed
#: on the file's stamp rather than its name so editing it during a test
#: is picked up rather than cached over.
_XSLT_CACHE: dict[tuple[str, int, int], XSLT] = {}


def _transform(xsl: str | Path | None) -> XSLT:
    from lxml import etree

    path = find_mml2omml_xsl(xsl)
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _XSLT_CACHE:
        _XSLT_CACHE[key] = etree.XSLT(etree.parse(str(path)))
    return _XSLT_CACHE[key]


#: What `latex2mathml` gives `\overline`, and what Word can draw with.
#: U+2015 HORIZONTAL BAR is not in Word's accent set, so Word centres the
#: glyph ON the letter and v-bar renders STRUCK THROUGH. U+0305
#: COMBINING OVERLINE draws it above, matching Word's own `m:bar`.
#:
#: Confirmed in a PDF render, which is the only gate that sees it: both
#: forms are valid markup, so lint, the formula diff and the text diff
#: pass on the struck-through one.
_ACCENT_CHR = {"―": "̅"}

_M = f"{{{M_NS}}}"


def _rejoin_at_separator(d: _Element) -> None:
    """Undo a fence the converter split at its separator.

    Word's ``MML2OMML.XSL`` turns the operator inside a fence into the
    delimiter's SEPARATOR: ``\\left(a+b\\right)`` comes back as two
    ``m:e`` holding ``a`` and ``b``, with the ``+`` in ``m:sepChr`` and
    in no ``m:t`` at all. Same for ``(-1)``, where the first element is
    empty, and for ``(x,y)``.

    **Rejoining is both halves of a defect, and neither was visible.**

    The page: as ``m:sepChr`` Word draws a binary operator TIGHT —
    ``(a+b)``, punctuation spacing — where the same expression written
    as runs gets the medium space it is owed, ``(a + b)``. ``(-1)`` was
    worse and is what this function was written for: Word lays the empty
    element out as a gap and the page reads ``(   −1)``.

    The text layer: a character in an attribute is in no ``m:t``, so
    `docxkit text`, the TEXT layer of `compare` and every per-paper gate
    written against extracted text read ``c_ij − c̄_j`` as ``cijcj`` —
    with no way to tell a minus from a plus. Measured 2026-08-29:
    ``(a+b)`` against ``(a−b)`` produced NO finding on any layer of
    `compare`, tokens and skeleton identical, `--expect-clean` green. A
    sign flip in a revision passed every gate the toolkit has.

    **The tell is the SEPARATOR, not the empty element.** It used to be
    the other way round — fire only when an element is empty — on the
    reasoning that ``(x,y)`` arrives in the same shape with both filled
    and there the comma is real and drawn. It is drawn either way:
    rendered through Word, ``(x, y)`` is identical in both spellings
    (2026-08-29), while the operator cases differ as above. So the
    narrow rule bought nothing and cost the observability of every fence
    an author happened to write with ``\\left…\\right`` — ``\\frac{a}{b+c}``
    keeps its operator in an ``m:t`` and ``\\left(b+c\\right)`` did not,
    which is not a property anyone would predict.

    An EMPTY ``m:sepChr`` is left alone: it means the XSL put everything
    in one element already, which is the shape this produces.
    """
    from lxml import etree

    els = [e for e in d if e.tag == _M + "e"]
    if len(els) < 2:
        return
    dpr = d.find(f"{_M}dPr")
    sep_el = None if dpr is None else dpr.find(f"{_M}sepChr")
    sep = sep_el.get(_M + "val") if sep_el is not None else None
    if dpr is None or sep_el is None or not sep:
        return                              # `(1,-2)`: nothing to rejoin
    first = els[0]
    for other in els[1:]:
        etree.SubElement(etree.SubElement(first, _M + "r"),
                         _M + "t").text = sep
        for child in list(other):
            first.append(child)             # append MOVES it, which is here
        d.remove(other)                     # the point
    # The now-childless `m:dPr` stays. Every child of it is optional, and
    # an empty one renders with Word's defaults — parentheses — which is
    # the form the render probe proved. Tidier is not better here.
    dpr.remove(sep_el)


#: MathML's namespace, for the one pass that runs BEFORE Word's XSL.
_MML_NS = "http://www.w3.org/1998/Math/MathML"

#: Spaces chosen by WIDTH rather than by count, and not the ASCII one.
#: U+2003/2002/2009 are exact fractions of an em, so the gap does not
#: depend on the font's idea of a space; and none of them is XML
#: whitespace, so nothing downstream may collapse or trim them. A plain
#: space in `m:t` is exactly the thing `edit.preserve_space` exists to
#: rescue, and rescuing it here would be inventing the problem.
_EM_SPACE, _EN_SPACE, _THIN_SPACE = "\u2003", "\u2002", "\u2009"

_WIDTH_RE = re.compile(r"^(-?[\d.]+)\s*em$")


def _space_text(width: str) -> str:
    """The characters that draw `width`, or "" for nothing to draw."""
    m = _WIDTH_RE.match(width.strip())
    if not m:
        return ""
    try:
        em = float(m.group(1))
    except ValueError:
        return ""
    if em <= 0:                       # `\!` is negative; Word has no
        return ""                     # negative space to draw
    out = _EM_SPACE * int(em)
    rest = em - int(em)
    if rest >= 0.4:
        out += _EN_SPACE
    elif rest > 0:
        out += _THIN_SPACE
    return out


def _carry_spacing(root: _Element) -> None:
    r"""`<mspace>` -> `<mtext>`, because the XSL drops the first.

    Word's ``MML2OMML.XSL`` has no template for ``mspace``, so every
    LaTeX spacing command vanished on the way to OMML — ``\qquad``,
    ``\quad``, ``\hspace{2em}``, ``\,``, ``\;`` — silently, into
    valid markup with the right ``m:oMath`` count and a clean
    ``math --check``. On Aging_Well that ran a definition into its sign
    conditions in all nine equations of one batch, and only the page
    showed it.

    ``mtext`` is the vehicle because it is the one construct measured to
    survive that XSL: ``\mathrm{~~~~}``, the workaround a paper had
    already invented, is `mtext` underneath. This does for every spacing
    command what one paper was doing by hand for one of them.
    """
    from lxml import etree

    for space in list(root.iter(f"{{{_MML_NS}}}mspace")):
        parent = space.getparent()
        # Kept although `root.iter()` is called on the parsed document
        # root, so an `mspace` always has one: `getparent()` is typed
        # `_Element | None` and the `replace` below does not type-check
        # without it. Dead by the type system's argument, which is the
        # kind that stays.
        if parent is None:
            continue
        text = _space_text(space.get("width", ""))
        if text:
            mtext = etree.Element(f"{{{_MML_NS}}}mtext")
            mtext.text = text
            mtext.tail = space.tail
            parent.replace(space, mtext)
        else:
            parent.remove(space)


#: An operator NAME is two or more letters. One letter is a variable,
#: and `<mo>` also carries every symbol — ∈, +, = — which this must not
#: touch.
_MULTILETTER_RE = re.compile(r"^[A-Za-z]{2,}$")


def _name_operators_as_identifiers(root: _Element) -> None:
    r"""Retag a multi-letter ``<mo>`` as ``<mi>``, so Word sets it upright.

    Word's XSL marks a multi-character ``<mi>`` upright and leaves
    ``<mo>`` alone, and latex2mathml splits the operators between the
    two: ``\log``, ``\exp``, ``\sin`` and ``\ln`` arrive as ``mi`` and
    are fine, while ``\max``, ``\min``, ``\lim``, ``\sup`` and every
    ``\operatorname{…}`` arrive as ``mo`` and render ITALIC. Not
    "operator styling is missing" — INCONSISTENT, which is why nobody
    noticed until a paper needed a constrained optimization and shipped
    its equation (5) with an italic `max`.

    **The first version of this fix marked the OMML run upright instead,
    and the render caught it.** Left as ``mo``, the XSL merges the
    operator with its operand into ONE run — `\max x` becomes a single
    `<m:t>maxx</m:t>` — so styling that run upright takes the VARIABLE
    with it, and the page showed `maxx` where it should show `max` then
    an italic `x`. Retagged, the transform produces exactly the shape it
    already produced for `\log`: an upright run for the name, a
    separate default-italic run for the operand.

    The caution against this — that ``mo`` and ``mi`` are spaced
    differently, so changing the element to fix the FACE might move the
    GAPS — was worth having and does not survive measurement here:
    `\log x` (an `mi` operator all along) renders with the same absent
    gap as `\max x` does, because OMML has already flattened the
    distinction by the time Word draws it.
    """
    for mo in list(root.iter(f"{{{_MML_NS}}}mo")):
        if _MULTILETTER_RE.match((mo.text or "").strip()):
            mo.tag = f"{{{_MML_NS}}}mi"


def _normalize(root: _Element) -> None:
    """Repair what the converter emits and Word cannot draw.

    Every defect fixed here produces VALID markup, so lint, the formula
    diff and the text diff all pass while the page is wrong — only a PDF
    render catches them. That is the argument for doing it once, in the
    shared converter, rather than per paper: two manuscripts had already
    grown their own patch for the accent character alone.
    """
    for chr_el in root.iter(_M + "chr"):
        parent = chr_el.getparent()
        # `m:chr` also carries the brace of an `m:groupChr`, where
        # U+2015 would be a legitimate choice. Only the accent is wrong.
        if parent is not None and parent.tag == _M + "accPr" and (
                fixed := _ACCENT_CHR.get(chr_el.get(_M + "val") or "")):
            chr_el.set(_M + "val", fixed)
    for d in list(root.iter(_M + "d")):
        _rejoin_at_separator(d)


def latex_to_omml(latex: str, *, xsl: str | Path | None = None) -> str:
    """Convert LaTeX to an ``<m:oMath>`` element, as an XML string.

    LaTeX -> presentation MathML (latex2mathml) -> OMML (Word's own XSL),
    with a repair on each side of the transform for what that chain
    loses: :func:`_carry_spacing` before it, because the XSL has no
    template for ``mspace`` and a dropped space cannot be recovered
    afterwards, and :func:`_normalize` after it, for the markup Word
    cannot draw and the operator names it leaves italic.
    """
    # Optional extra, absent on a plain install: pyright resolves imports
    # from the environment it runs in, and mypy's ignore_missing_imports
    # does not reach it. See [project.optional-dependencies] latex.
    try:
        import latex2mathml.converter  # pyright: ignore[reportMissingImports]
    except ImportError as exc:        # say which extra, not which module
        raise PackageError(
            "latex_to_omml needs latex2mathml, which is an optional "
            "extra: pip install docxkit[latex]") from exc
    from lxml import etree

    transform = _transform(xsl)
    mathml = latex2mathml.converter.convert(latex)
    tree = etree.fromstring(mathml.encode("utf-8"))
    # BEFORE the transform: the XSL has no template for `mspace`, so a
    # spacing command that reaches it is gone and cannot be recovered
    # from the OMML afterwards.
    _carry_spacing(tree)
    _name_operators_as_identifiers(tree)
    result = transform(tree).getroot()
    if result.tag != f"{{{M_NS}}}oMath":
        found = result.find(f".//{{{M_NS}}}oMath")
        if found is None:
            raise PackageError(f"no m:oMath produced for LaTeX: {latex!r}")
        result = found
    _normalize(result)
    return str(etree.tostring(result, encoding="unicode"))


def equations(xml: str) -> list[Equation]:
    """Every ``<m:oMath>`` in the document, in order."""
    return [Equation(index=i, start=m.start(), end=m.end(), xml=m.group(0))
            for i, m in enumerate(OMATH_RE.finditer(xml))]


def tokens(omml: str) -> str:
    """The symbol stream of an equation, separators included.

    A delimiter's ``m:sepChr`` is a character in an ATTRIBUTE: Word
    draws it between the arguments, and it is in no ``m:t``, so a stream
    read from the runs alone cannot tell ``(a+b)`` from ``(a−b)``.
    Measured 2026-08-29: `compare` reported no finding on any layer for
    that pair — tokens equal, skeleton equal, `--expect-clean` green —
    which made a sign flip inside a fence invisible to every gate.

    :func:`latex_to_omml` no longer WRITES that shape, but every
    manuscript built before it does, so the reader has to know it too.
    """
    if "m:sepChr" in omml:
        omml = _with_separators(omml)
    return html.unescape("".join(MT_RE.findall(omml)))


def _with_separators(omml: str) -> str:
    """`omml` with each separator moved to where it is DRAWN.

    :func:`_rejoin_at_separator` again, and deliberately the same
    function: the converter's repair and the reader's view of an
    unrepaired document have to agree about what the page says, and two
    spellings of that rule would be one drift per defect.

    Ordering is why this parses rather than scraping the attribute out
    with a regex. ``m:sepChr`` sits in ``m:dPr``, ahead of every
    argument, so an appended token reads ``+ab``; and the arguments
    cannot be counted by matching ``<m:e>`` either, because a subscript
    inside one has ``m:e`` of its own. Gated on the substring, so the
    documents that do not carry one — which after this is all of the
    ones docxkit builds — pay nothing.
    """
    from lxml import etree

    wrapped = f"<x {_fragment_declarations(omml)}>{omml}</x>"
    try:
        root = etree.fromstring(wrapped.encode("utf-8"))
    except etree.XMLSyntaxError:
        return omml           # a token stream is not worth a hard failure
    for d in list(root.iter(_M + "d")):
        _rejoin_at_separator(d)
    return "".join(etree.tostring(child, encoding="unicode")
                   for child in root)


def skeleton(omml: str) -> str:
    """The structural shape of an equation (sSub/nary/f/...)."""
    return "/".join(_STRUCT_RE.findall(omml))


#: OMML states a run's FACE in its own element, not in ``w:rPr``.
_STY_RE = re.compile(r'<m:sty\b[^>]*\bm:val="(p|b|i|bi)"')
#: The rarer spelling: a maths run may also carry a ``w:rPr``, and some
#: producers put the bold there. Read second, never instead.
_W_BOLD_RE = re.compile(r'<w:b\b(?![^>]*w:val="(?:0|false|none)")[^>]*/?>')
_W_ITALIC_RE = re.compile(r'<w:i\b(?![^>]*w:val="(?:0|false|none)")[^>]*/?>')
#: What Word renders when nothing states a face. OMML's default is
#: MATH-ITALIC — a variable is italic because it is a variable, which is
#: why a manuscript full of italic symbols carries no markup for it.
DEFAULT_FACE = "i"


def face(run_xml: str) -> str:
    """A maths run's face: ``"p"``, ``"b"``, ``"i"`` or ``"bi"``.

    **The guard written the natural way is wrong and reports success.**
    An OMML run states its face through ``<m:sty m:val="…"/>``, and
    ``<w:b/>`` — the spelling every prose pass uses — is a different,
    rarer one. On `Parental_style` (2026-08-13) a protocol read *"Zero
    bold-X instances may be edited"*, enumerated with ``'<w:b/>' in
    run``, and got::

        italic X: 32   bold X: 0

    All four covariate **X**'s were counted as italic and would have
    been swept into a rename, silently corrupting equations (5)-(6).
    They carry ``<m:sty m:val="bi"/>``. Correct detection gives 28 not
    bold and 4 bold, which reconciles with the protocol's independently
    derived count.

    ``m:sty`` first, ``w:rPr`` second, and :data:`DEFAULT_FACE` when
    neither states anything — a maths run with no markup renders ITALIC,
    because that is what a variable is. A caller that means "carries no
    face markup at all" wants the empty string from ``m:sty``, not this.

    The toolkit already knew this privately: `_compare_read` folds
    ``m:sty`` with ``w:b``/``w:i`` when it fingerprints FORMULA
    TYPOGRAPHY, which is why that layer stayed clean throughout. Every
    caller re-deriving it got it wrong, so it is public here.
    """
    if (m := _STY_RE.search(run_xml)) is not None:
        return m.group(1)
    bold = _W_BOLD_RE.search(run_xml) is not None
    italic = _W_ITALIC_RE.search(run_xml) is not None
    if bold and italic:
        return "bi"
    if bold:
        return "b"
    if italic:
        return "i"
    return DEFAULT_FACE


def is_bold(run_xml: str) -> bool:
    """Does this maths run render BOLD? (``m:sty`` b/bi, or ``w:b``)"""
    return face(run_xml) in ("b", "bi")


def is_italic(run_xml: str) -> bool:
    """Does this maths run render ITALIC? Includes the unmarked default."""
    return face(run_xml) in ("i", "bi")


def harvest(xml: str, contains: str, *, index: int = 0,
            exact: bool = False) -> str:
    """An existing equation from the document, to deepcopy into a new one.

    When new math reuses symbols the document already renders, copying
    the live element guarantees the result matches — same fonts, same
    spacing, same control properties — where a rebuild from LaTeX only
    usually does.

    `contains` is matched against the equation's symbol stream. Pass
    ``exact=True`` to require the whole stream, which is what harvesting
    a BARE SYMBOL needs: in a manuscript that defines ``C_k`` once and
    then uses it, 24 equations contain "Ck" and the standalone symbol is
    not the first of them, so a substring match hands back a whole
    formula where a letter was asked for — plausible, wrong, and visible
    only in the render.
    """
    def matches(stream: str) -> bool:
        if exact:
            return stream.strip() == contains.strip()
        return contains in stream

    hits = [e for e in equations(xml) if matches(e.tokens)]
    how = "equal" if exact else "contain"
    if not hits:
        raise AnchorError(f"no equation whose symbols {how} {contains!r}")
    if index >= len(hits):
        raise AnchorError(
            f"{len(hits)} equations {how} {contains!r}, no index {index}")
    # `xml` is the part this came out of, so its root can answer for any
    # prefix the fragment carries — which is how a redline's math, whose
    # runs are wrapped in w16du-stamped revisions, survives being lifted.
    return standalone(hits[index].xml, source=xml)


#: The prefixes an equation lifted out of a manuscript can carry: the
#: math namespace, the main one for w:rPr and tracked changes inside a
#: formula, and the Word extensions that ride along on those.
_NS_URIS = {
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "w16cid": "http://schemas.microsoft.com/office/word/2016/wordml/cid",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "r": ("http://schemas.openxmlformats.org/officeDocument/2006/"
          "relationships"),
}
_NS_DECL = " ".join(f'xmlns:{p}="{u}"' for p, u in _NS_URIS.items())

#: A namespace binding as the root element states it.
_XMLNS_RE = re.compile(r'xmlns:([A-Za-z][\w.-]*)="([^"]*)"')


def _declared_in(source: str) -> dict[str, str]:
    """The REAL prefix -> URI bindings a part's root element states.

    The list below can only ever name the prefixes someone thought of,
    and Word keeps adding: `w16du` alone appears in 158 equations across
    six of these manuscripts, so `standalone` refused the very fragments
    :func:`harvest` exists to lift out. The document already says what
    every prefix means — asking it is both correct and permanent, where
    extending a hard-coded list is neither.
    """
    head = re.search(r"<\w[^>]*>", source)      # skips <?xml and <!DOCTYPE
    return dict(_XMLNS_RE.findall(head.group(0))) if head else {}


def standalone(omml: str, *, source: str | None = None) -> str:
    """An equation fragment that parses on its own.

    A fragment sliced out of ``word/document.xml`` inherits its
    namespace declarations from the part's root, so it carries none of
    its own and ``etree.fromstring`` rejects it — which broke the pair
    this module documents: :func:`harvest` produced exactly what
    :func:`clone` could not read. Re-serialising it through a declaring
    wrapper puts the declarations lxml needs on the element itself.

    Pass `source` — the part the fragment came from — for any prefix
    beyond the common set below; its bindings are read off the root, so
    a namespace this module has never heard of still resolves to the URI
    the document gives it. :func:`harvest` does this for you.
    """
    from lxml import etree

    # REAL URIs only, and a refusal otherwise. revisions._fragment_
    # declarations answers the same question with a placeholder URI for
    # anything it does not know, which is right for a read-only text
    # pass and wrong here: this fragment gets INSERTED into a document,
    # and a urn:docxkit:undeclared: namespace would ship with it.
    known = dict(_NS_URIS)
    if source is not None:
        known.update(_declared_in(source))
    # What the fragment declares for ITSELF counts too, and has to: this
    # function's own output carries those declarations, so without this
    # `clone(harvest(...))` refused the very thing `harvest` had just
    # made self-contained — and the pair is the documented workflow.
    known.update(_XMLNS_RE.findall(omml))
    used = used_prefixes(omml)
    if unknown := used - set(known):
        raise AnchorError(
            f"equation uses namespace prefix(es) {sorted(unknown)} that "
            f"nothing declares; pass source=<the part it came from> so "
            f"their real URIs can be read off its root")
    # The common set is declared verbatim, and anything the source added
    # only when the fragment uses it — so an equation needing none of the
    # latter serialises exactly as it always has, which the papers'
    # byte-identical rebuilds depend on.
    extra = "".join(f' xmlns:{p}="{known[p]}"'
                    for p in sorted(used - set(_NS_URIS)))
    root = etree.fromstring(
        f"<docxkitFragment {_NS_DECL}{extra}>{omml}</docxkitFragment>"
        .encode())
    # Exactly one element, and nothing loose around it: `root[0]` took
    # the first and discarded the rest in silence, so two equations in
    # came back as one and a trailing sentence vanished.
    if len(root) != 1:
        raise AnchorError(
            f"standalone expects one element, got {len(root)}")
    if (root.text or "").strip() or (root[0].tail or "").strip():
        raise AnchorError(
            "standalone expects one element and no text around it")
    return str(etree.tostring(root[0], encoding="unicode"))


def clone(omml: str, *, source: str | None = None) -> str:
    """A detached copy of an equation element, ready to insert elsewhere.

    Accepts a fragment with or without its own namespace declarations,
    so it composes with :func:`harvest` and with :func:`latex_to_omml`
    alike. `source` is passed through to :func:`standalone`.
    """
    # Parse-and-reserialise IS the normalisation; the element is created
    # here and never shared, so the deepcopy that used to sit between the
    # two copied something nobody else could reach.
    return standalone(omml, source=source)


# -------------------------------------------------------- OMML -> LaTeX -----
# The inverse of latex_to_omml, for READING: markdown export, semantic
# formula diffs, and loading a manuscript's math into places that speak
# LaTeX. It does not have to be the inverse bijection — Word's XSL covers
# constructs no manuscript here uses — but it must never drop content
# silently: an element the walker does not know is rendered as an inline
# [?m:tag] marker (or raises, under strict), so a gap is visible in the
# output instead of missing from it.

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_GREEK = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ϵ": r"\epsilon", "ζ": r"\zeta", "η": r"\eta",
    "θ": r"\theta", "ϑ": r"\vartheta", "ι": r"\iota", "κ": r"\kappa",
    "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi", "π": r"\pi",
    "ϖ": r"\varpi", "ρ": r"\rho", "ϱ": r"\varrho", "σ": r"\sigma",
    "ς": r"\varsigma", "τ": r"\tau", "υ": r"\upsilon", "φ": r"\varphi",
    "ϕ": r"\phi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Υ": r"\Upsilon",
    "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
}

_SYMBOLS = {
    "×": r"\times", "⋅": r"\cdot", "∗": r"\ast", "±": r"\pm",
    "∓": r"\mp", "÷": r"\div", "∘": r"\circ",
    "≤": r"\le", "≥": r"\ge", "≠": r"\ne", "≈": r"\approx",
    "≃": r"\simeq", "≅": r"\cong", "≡": r"\equiv", "∝": r"\propto",
    "∼": r"\sim", "≪": r"\ll", "≫": r"\gg",
    "∞": r"\infty", "∂": r"\partial", "∇": r"\nabla",
    "→": r"\to", "⟶": r"\longrightarrow", "←": r"\leftarrow",
    "↔": r"\leftrightarrow", "⇒": r"\Rightarrow", "⇐": r"\Leftarrow",
    "⇔": r"\Leftrightarrow", "↦": r"\mapsto",
    "∈": r"\in", "∉": r"\notin", "∋": r"\ni", "⊂": r"\subset",
    "⊆": r"\subseteq", "⊃": r"\supset", "⊇": r"\supseteq",
    "∪": r"\cup", "∩": r"\cap", "∅": r"\emptyset", "∖": r"\setminus",
    "∀": r"\forall", "∃": r"\exists", "¬": r"\neg",
    "∧": r"\wedge", "∨": r"\vee", "⊕": r"\oplus", "⊗": r"\otimes",
    "⋯": r"\cdots", "…": r"\dots", "⋮": r"\vdots", "⋱": r"\ddots",
    "ℝ": r"\mathbb{R}", "ℤ": r"\mathbb{Z}", "ℕ": r"\mathbb{N}",
    "ℚ": r"\mathbb{Q}", "ℂ": r"\mathbb{C}", "𝔼": r"\mathbb{E}",
    "ℓ": r"\ell", "ℏ": r"\hbar", "°": r"^{\circ}", "′": "'", "″": "''",
    # TeX specials that appear as literal characters in m:t
    "%": r"\%", "&": r"\&", "#": r"\#", "$": r"\$", "_": r"\_",
    "{": r"\{", "}": r"\}",
    # Word's glyphs for plain operators
    "−": "-", "‐": "-", "–": "-",
    # invisible operators (times, function application, plus) and NBSP
    "⁢": "", "⁡": "", "⁤": "", " ": " ",
}

_KNOWN_FUNCS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh",
    "coth", "arcsin", "arccos", "arctan", "exp", "ln", "log", "lim",
    "min", "max", "arg", "det", "dim", "gcd", "sup", "inf", "Pr",
}

_NARY = {"∑": r"\sum", "∏": r"\prod", "∐": r"\coprod", "∫": r"\int",
         "∬": r"\iint", "∭": r"\iiint", "∮": r"\oint", "⋃": r"\bigcup",
         "⋂": r"\bigcap", "⋁": r"\bigvee", "⋀": r"\bigwedge",
         "⨁": r"\bigoplus", "⨂": r"\bigotimes"}

_FENCES = {"(": "(", ")": ")", "[": "[", "]": "]",
           "{": r"\{", "}": r"\}", "|": "|", "‖": r"\|",
           "⟨": r"\langle", "⟩": r"\rangle", "⌊": r"\lfloor",
           "⌋": r"\rfloor", "⌈": r"\lceil", "⌉": r"\rceil", "": "."}

_ACCENTS = {"̂": r"\hat", "̃": r"\tilde", "̄": r"\bar",
            "¯": r"\bar", "̅": r"\bar", "̇": r"\dot",
            "̈": r"\ddot", "̆": r"\breve", "̌": r"\check",
            "⃗": r"\vec", "→": r"\vec", "̀": r"\grave",
            "́": r"\acute"}


def _char(ch: str) -> str:
    if ch in _SYMBOLS:
        sym = _SYMBOLS[ch]
        # a trailing space stops "\le x" fusing into the command "\lex"
        return sym + " " if sym.startswith("\\") and sym[-1].isalpha() \
            else sym
    if ch in _GREEK:
        return _GREEK[ch] + " "
    if ord(ch) >= 0x1d400:
        # a math-alphanumeric glyph (𝑥, 𝛽): Unicode records what letter
        # it styles, so decompose and map the base letter instead
        import unicodedata
        decomp = unicodedata.decomposition(ch)
        if decomp.startswith("<font> "):
            return _char(chr(int(decomp.split()[1], 16)))
    return ch


def _text(raw: str) -> str:
    return "".join(_char(c) for c in raw)


def _local(el: _Element) -> str:
    tag = str(el.tag)
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _mval(el: _Element, path: str) -> str | None:
    """The ``m:val`` of a property child, or None if absent."""
    hit = el.find("/".join(f"{{{M_NS}}}{p}" for p in path.split("/")))
    return None if hit is None else hit.get(f"{{{M_NS}}}val")


def _mval_or(el: _Element, path: str, default: str) -> str:
    """:func:`_mval`, with `default` for an ABSENT value only — an
    explicitly empty ``m:val=""`` is a value, and it comes back ``""``."""
    val = _mval(el, path)
    return default if val is None else val


class _Walker:
    def __init__(self) -> None:
        self.gaps: list[str] = []

    def children(self, el: _Element) -> str:
        return "".join(self.walk(child) for child in el)

    def arg(self, el: _Element, name: str) -> str:
        hit = el.find(f"{{{M_NS}}}{name}")
        return "{" + (self.children(hit) if hit is not None else "") + "}"

    def bare(self, el: _Element, name: str) -> str:
        hit = el.find(f"{{{M_NS}}}{name}")
        return self.children(hit) if hit is not None else ""

    def walk(self, el: _Element) -> str:
        name = _local(el)
        ns = el.tag.rsplit("}", 1)[0].lstrip("{") if "}" in el.tag else ""
        if ns == _W_NS:
            # a redline's equation wraps math in w:ins/w:del: render the
            # FINAL view (insertions kept, deletions dropped) rather than
            # silently losing whatever sat inside the wrapper
            if name == "t":
                return _text(el.text or "")
            if name in ("ins", "moveTo", "r", "p", "smartTag"):
                return self.children(el)
            return ""              # del/moveFrom, bookmarks, proofErr...
        method = getattr(self, "e_" + name, None)
        if method is not None:
            return str(method(el))
        if name.endswith("Pr"):            # `ctrlPr` among them
            return ""                          # properties are not content
        self.gaps.append(name)
        return rf"\text{{[?m:{name}]}}" + self.children(el)

    # --- leaves ------------------------------------------------------------
    def e_t(self, el: _Element) -> str:
        return _text(el.text or "")

    def e_r(self, el: _Element) -> str:
        # Through the walker, not `findall("m:t")`: an edited equation
        # wraps a run's OWN text in w:ins/w:del, so the text sits one
        # level below and a direct-children scan silently dropped it.
        # Measured over 5,527 equations in the corpus: 589 characters
        # gone, and one fraction rendered as \frac{}{{}_{}} — every
        # symbol it had was inside a revision. The walker already knows
        # to keep an insertion and drop a deletion; this now asks it,
        # rather than deciding the same question a second way.
        body = self.children(el)
        rpr = el.find(f"{{{M_NS}}}rPr")
        upright = rpr is not None and (
            rpr.find(f"{{{M_NS}}}nor") is not None
            or _mval(el, "rPr/sty") == "p")
        if upright and body.strip():
            return rf"\text{{{body}}}"
        return body

    # --- structures --------------------------------------------------------
    def e_oMath(self, el: _Element) -> str:
        return self.children(el)

    def e_oMathPara(self, el: _Element) -> str:
        return self.children(el)

    def e_f(self, el: _Element) -> str:
        kind = _mval(el, "fPr/type")
        num, den = self.arg(el, "num"), self.arg(el, "den")
        if kind in ("lin", "skw"):
            return f"{num}/{den}"
        if kind == "noBar":
            return f"{{{num[1:-1]} \\atop {den[1:-1]}}}"
        return rf"\frac{num}{den}"

    def e_sSup(self, el: _Element) -> str:
        return self.arg(el, "e") + "^" + self.arg(el, "sup")

    def e_sSub(self, el: _Element) -> str:
        return self.arg(el, "e") + "_" + self.arg(el, "sub")

    def e_sSubSup(self, el: _Element) -> str:
        return (self.arg(el, "e") + "_" + self.arg(el, "sub")
                + "^" + self.arg(el, "sup"))

    def e_sPre(self, el: _Element) -> str:
        return ("{}_" + self.arg(el, "sub") + "^" + self.arg(el, "sup")
                + self.arg(el, "e"))

    def e_rad(self, el: _Element) -> str:
        hide = _mval(el, "radPr/degHide")
        deg = self.bare(el, "deg")
        e = self.arg(el, "e")
        if hide == "1" or not deg.strip():
            return rf"\sqrt{e}"
        return rf"\sqrt[{deg}]{e}"

    def e_nary(self, el: _Element) -> str:
        op = _NARY.get(_mval(el, "naryPr/chr") or "∫", r"\int")
        sub, sup = self.bare(el, "sub"), self.bare(el, "sup")
        out = op
        if sub.strip() and _mval(el, "naryPr/subHide") != "1":
            out += f"_{{{sub}}}"
        if sup.strip() and _mval(el, "naryPr/supHide") != "1":
            out += f"^{{{sup}}}"
        return out + " " + self.arg(el, "e")

    def e_d(self, el: _Element) -> str:
        # an unmapped fence renders as itself: possibly odd TeX, but
        # visibly odd, where a silent "(" would claim a bracket the
        # equation never had.
        #
        # The defaults apply to an ABSENT character only. An EMPTY one
        # is how OMML says "no delimiter on this side" — Word's cases
        # brace is begChr "{" with endChr "" — and read through `or` it
        # took the default and a piecewise function came back as
        # `\left\{ x \right)` (backlog S2, 2026-09-18).
        raw_beg = _mval_or(el, "dPr/begChr", "(")
        raw_end = _mval_or(el, "dPr/endChr", ")")
        beg = _FENCES.get(raw_beg, raw_beg)
        end = _FENCES.get(raw_end, raw_end)
        sep = _mval_or(el, "dPr/sepChr", "|")
        joint = rf" \middle{_FENCES.get(sep, sep)} " if sep else " "
        inner = joint.join(
            self.children(e) for e in el.findall(f"{{{M_NS}}}e")) \
            if len(el.findall(f"{{{M_NS}}}e")) > 1 \
            else self.bare(el, "e")
        return rf"\left{beg} {inner} \right{end}"

    def e_func(self, el: _Element) -> str:
        fname = self.bare(el, "fName").strip()
        if fname in _KNOWN_FUNCS:
            fname = "\\" + fname
        elif fname and re.fullmatch(r"[A-Za-z]+", fname):
            fname = rf"\operatorname{{{fname}}}"
        return fname + " " + self.arg(el, "e")

    def e_acc(self, el: _Element) -> str:
        mark = _ACCENTS.get(_mval(el, "accPr/chr") or "̂", r"\hat")
        return mark + self.arg(el, "e")

    def e_bar(self, el: _Element) -> str:
        pos = _mval(el, "barPr/pos")
        cmd = r"\overline" if pos == "top" else r"\underline"
        return cmd + self.arg(el, "e")

    def e_groupChr(self, el: _Element) -> str:
        chr_ = _mval(el, "groupChrPr/chr") or "⏟"
        if chr_ == "⏟":
            return r"\underbrace" + self.arg(el, "e")
        if chr_ == "⏞":
            return r"\overbrace" + self.arg(el, "e")
        pos = _mval(el, "groupChrPr/pos")
        cmd = r"\overset" if pos == "top" else r"\underset"
        return f"{cmd}{{{_text(chr_)}}}" + self.arg(el, "e")

    def e_limLow(self, el: _Element) -> str:
        base = self.bare(el, "e").strip()
        low = self.bare(el, "lim")
        # "lim" under "n -> inf" is the operator taking its limit, which
        # LaTeX writes as \lim_{...}; anything else is a generic underset
        if base.lstrip("\\") in _KNOWN_FUNCS:
            # `chr(92)` was here because an f-string could not hold a
            # backslash before PEP 701; requires-python is >=3.12, so it
            # can, and the literal says what it means
            return rf"\{base.lstrip('\\')}_{{{low}}}"
        return rf"\underset{{{low}}}{{{base}}}"

    def e_limUpp(self, el: _Element) -> str:
        return (rf"\overset{{{self.bare(el, 'lim')}}}"
                f"{{{self.bare(el, 'e')}}}")

    def e_m(self, el: _Element) -> str:
        rows = []
        for mr in el.findall(f"{{{M_NS}}}mr"):
            rows.append(" & ".join(self.children(e)
                                   for e in mr.findall(f"{{{M_NS}}}e")))
        body = r" \\ ".join(rows)
        return rf"\begin{{matrix}} {body} \end{{matrix}}"

    def e_eqArr(self, el: _Element) -> str:
        lines = [self.children(e) for e in el.findall(f"{{{M_NS}}}e")]
        body = r" \\ ".join(lines)
        return rf"\begin{{aligned}} {body} \end{{aligned}}"

    def e_box(self, el: _Element) -> str:
        return self.bare(el, "e")

    def e_borderBox(self, el: _Element) -> str:
        return r"\boxed" + self.arg(el, "e")

    def e_phant(self, el: _Element) -> str:
        return r"\phantom" + self.arg(el, "e")

    def e_e(self, el: _Element) -> str:
        return self.children(el)


def to_latex(omml: str, *, strict: bool = False) -> str:
    """Render an ``m:oMath`` (or a whole equation slice) as LaTeX.

    Built for reading — markdown export, formula diffs — not for a
    guaranteed round-trip. A construct with no rendering becomes an
    inline ``[?m:tag]`` marker so it cannot vanish silently; `strict`
    raises :class:`~docxkit.errors.ConversionGap` instead. Regular
    ``w:r`` runs inside the math (comment anchors, bookmarks) contribute
    nothing, matching how Word renders them.
    """
    from lxml import etree

    # a slice out of document.xml declares no namespaces of its own, and
    # a redline's math carries prefixes like w16du that even a full list
    # would chase forever — the placeholder-URI trick from revisions
    # covers whatever the fragment actually uses
    wrapped = f"<x {_fragment_declarations(omml)}>{omml}</x>"
    root = etree.fromstring(wrapped.encode("utf-8"))
    walker = _Walker()
    out = walker.children(root)
    if strict and walker.gaps:
        raise ConversionGap(
            f"no LaTeX rendering for m:{', m:'.join(sorted(set(walker.gaps)))}"
            f" in equation {tokens(omml)[:60]!r}")
    out = re.sub(r"  +", " ", out)
    # the guard space a command needs before a letter is noise before }
    return re.sub(r" +}", "}", out).strip()


def is_display(para_xml: str) -> bool:
    """True if a paragraph is a display equation.

    A display equation is a paragraph whose visible content is the maths:
    it carries an ``<m:oMath>`` and no prose beyond an equation number,
    the sentence punctuation that closes the equation, and whitespace.

    The punctuation clause is not pedantry. A displayed equation is part
    of the sentence that introduces it, so authors write ``... , (3)``
    after the maths — and with the comma counted as prose this returned
    False, so `display_equations` did not list the equation, the house
    check never saw it and it stayed inline. Three of one manuscript's
    seven were invisible to every equation tool for that reason.
    """
    if "<m:oMath" not in para_xml:
        return False
    para_xml = _accepted_side(para_xml)
    if "<m:oMath" not in para_xml:
        return False               # the maths itself is being deleted
    # strip the maths first: visible_text includes m:t, so leaving it in
    # would make every display equation look like a paragraph of prose
    prose = visible_text(OMATH_RE.sub("", para_xml))
    without_number = EQ_NUMBER_RE.sub("", prose)
    return not without_number.strip(" \t\r\n.,;:")


def _accepted_side(para_xml: str) -> str:
    r"""`para_xml` with its tracked DELETIONS removed.

    The classification above reads :func:`visible_text`, which drops
    ``w:delText`` and keeps ``m:t``. So a paragraph being DELETED — its
    prose all in deletions, its equations' runs inside them — reads as
    maths and nothing else, which is the exact signature of a stranded
    display. `math --check` exited 0 on the accepted view of a batch and
    1 on the promoted proposal, naming the deleted paragraph
    (Aging_Well R78, 2026-09-01):

        16 display equation(s), 1 still in INLINE mode
           ¶64    'cijfj'

    The remedy printed with it — ``equations.display(para)`` — would
    have wrapped an equation on its way out of the document.

    Resolving to the accepted side is the general answer rather than
    "skip a paragraph whose every ``m:oMath`` is deleted", and it costs
    nothing extra: the same pass also drops the DELETED PROSE that made
    a paragraph look maths-only in the first place. A paragraph keeping
    live maths and losing its words IS a stranded display in the
    accepted view, and still reports.

    Independently reproduced before the fix: over 600 manuscripts,
    exactly one other document carries the shape (`Missing Market
    12082019.docx` ¶78 — 17 ``w:delText`` runs and one ``m:oMath``
    inside a deletion, with a stray "G. " live), and it was reported as
    a stranded display too.
    """
    # Any spelling of a deletion's name: asked for `<w:del ` with a space,
    # one whose name a tab or a newline ended was left in (2026-09-17).
    if not re.search(r"<w:del(?=[\s/>])", para_xml):
        return para_xml
    for lo, hi in reversed(element_spans(para_xml, "del")):
        para_xml = para_xml[:lo] + para_xml[hi:]
    return para_xml


def display_equations(xml: str, *,
                      in_tables: bool = False) -> list[re.Match[str]]:
    """Paragraph matches for every display equation, in body order.

    Tables hold both kinds of maths-only paragraph and they have to be
    told apart, which is what :func:`_vehicle_rows` does. A NOTATION
    table's symbol cell is a label — Aging_Well's Appendix opens with
    eighteen rows of symbol and meaning, and counting those made
    `math --check` report seventeen display equations "still in INLINE
    mode" that were nothing of the kind, with a printed remedy that
    refuses them (`display` raises on a cell like "α, β, γ" holding
    three ``m:oMath``). An equation VEHICLE is the opposite: a table
    used precisely so a display equation can carry its number, the
    maths in one cell and "(3)" in the next. Every numbered equation in
    that same paper is in one.

    So the discriminator is the equation NUMBER, not the table. A
    maths-only paragraph whose row carries a number cell is a display
    equation; one whose row does not is a cell that happens to contain
    maths. It is the number that says the paper means a numbered
    display block, and it is already the marker :func:`is_display` uses
    to read one in running text.

    `in_tables` counts every maths-only paragraph in a table, vehicle
    or not — the literal question, for a caller who means it.

    An UNNUMBERED display equation inside a table is the case this gets
    wrong, and it is skipped rather than reported. Callers are told how
    many: see `docxkit math`, which prints the count it did not check.
    """
    paragraphs = [m for m in PARA_RE.finditer(xml) if is_display(m.group(0))]
    if in_tables:
        return paragraphs
    tables = element_spans(xml, "tbl")
    numbered = _vehicle_rows(xml)
    return [m for m in paragraphs
            if not any(in_span(m.start(), t) for t in tables)
            or any(in_span(m.start(), r) for r in numbered)]


def _is_number_cell(cell_xml: str) -> bool:
    """A cell holding an equation number and nothing else."""
    text = visible_text(cell_xml).strip()
    return bool(text) and not EQ_NUMBER_RE.sub("", text).strip()


def _vehicle_rows(xml: str) -> list[tuple[int, int]]:
    """Table rows carrying an equation NUMBER in a cell of their own.

    The house vehicle for a numbered display equation: a full-width
    table, the maths centred in the left cell, "(3)" right-aligned in
    the right. Word has no other way to put a number on the margin
    beside a centred block.

    Per ROW and not per table, because a vehicle is not always one row.
    Aging_Well's (A2) and (A3) share a two-row table, so "a multi-row
    table is a notation table" — which is what the shapes look like
    side by side — would drop both. What the two really disagree about
    is whether the row numbers something.
    """
    rows: list[tuple[int, int]] = []
    for lo, _hi in element_spans(xml, "tbl"):
        block = xml[lo:_hi]
        for r_lo, r_hi in element_spans(block, "tr"):
            row = block[r_lo:r_hi]
            if any(_is_number_cell(row[c_lo:c_hi])
                   for c_lo, c_hi in element_spans(row, "tc")):
                rows.append((lo + r_lo, lo + r_hi))
    return rows


# ------------------------------------------------------ display MODE ----
# `is_display` above is about the paragraph: is the maths all it holds?
# This is about the markup Word reads: a bare `<m:oMath>` is INLINE, and
# display is `<m:oMathPara>`. A paragraph can be the first and not the
# second, which is exactly the defect these three exist for — the house
# rule in every paper here is display and centred, and nothing checked
# it.
#
# Word's auto-promotion cannot be relied on to do it: equations (2)-(4)
# of one manuscript were built identically to (1) and came back from a
# save promoted, while (1) stayed inline.

_OMATHPARA_RE = re.compile(r"<m:oMathPara\b")
#: `m:jc` takes ST_Justification. centerGroup is Word's own default for
#: a display equation; the house rule is plain center.
_JC_VALUES = ("center", "centerGroup", "left", "right")


def in_display_mode(para_xml: str) -> bool:
    """True if the paragraph's maths is in an ``m:oMathPara``."""
    return bool(_OMATHPARA_RE.search(para_xml))


def inline_display(xml: str, *,
                   in_tables: bool = False) -> list[re.Match[str]]:
    """Display equations Word will lay out INLINE, in body order.

    The audit half of :func:`display`. A paragraph holding nothing but
    its equation, with that equation in a bare ``m:oMath``, renders as a
    left-aligned run of text where the paper means a centred display.

    Table cells are excluded with :func:`display_equations`, and for the
    same reason: `display` is the repair this reports, and it refuses a
    notation cell holding three ``m:oMath`` — so a finding there names
    a fix that cannot be applied.
    """
    return [m for m in display_equations(xml, in_tables=in_tables)
            if not in_display_mode(m.group(0))]


_OMATHPARAPR_RE = re.compile(r"<m:oMathParaPr\b[^>]*?(/?)>")
_MJC_RE = re.compile(r'<m:jc m:val="[^"]*"\s*/>')


def _set_math_jc(para_xml: str, jc: str) -> str:
    """`para_xml` with its `m:oMathPara` aligned `jc`.

    ``m:oMathParaPr`` is the FIRST child of ``m:oMathPara`` — written
    anywhere else Word repairs the document — and ``m:jc`` is its only
    child, so there is no slot to compute.
    """
    element = f'<m:jc m:val="{jc}"/>'
    opening = re.search(r"<m:oMathPara\b[^>]*>", para_xml)
    if opening is None:                     # not in display mode
        return para_xml
    pr = _OMATHPARAPR_RE.match(para_xml, opening.end())
    if pr is None:
        return (para_xml[:opening.end()]
                + f"<m:oMathParaPr>{element}</m:oMathParaPr>"
                + para_xml[opening.end():])
    if pr.group(1) == "/":                  # <m:oMathParaPr/>
        return (para_xml[:pr.start()]
                + f"<m:oMathParaPr>{element}</m:oMathParaPr>"
                + para_xml[pr.end():])
    close = para_xml.index("</m:oMathParaPr>", pr.end())
    inner = para_xml[pr.end():close]
    inner = (_MJC_RE.sub(element, inner, count=1) if _MJC_RE.search(inner)
             else element + inner)
    return para_xml[:pr.end()] + inner + para_xml[close:]


def display(para_xml: str, *, jc: str | None = "center",
            absorb: bool = False) -> str:
    """Put a paragraph's equation into display mode, centred.

    Idempotent: run over a whole document twice, the second pass changes
    nothing.

    A paragraph ALREADY in display mode has its alignment set to `jc`
    and is otherwise left alone. Returning it untouched was the obvious
    reading of "idempotent" and it made the function unable to state the
    house rule it exists for: display AND centred are two properties,
    and an equation Word promoted on its own save has the first without
    the second. One such equation sat uncentred in a manuscript with no
    tool able to fix it — `display` skipped it as already done.

    **An ``oMathPara`` must be the only content of its paragraph.** A
    run left beside it — a comma, an equation number — makes Word demote
    the whole thing back to inline on the next save, silently, and the
    paragraph looks right in the XML while the page is wrong. So:

    * runs with no visible text are dropped (they demote it too);
    * a run WITH text is refused, naming what it holds;
    * ``absorb=True`` moves that text inside the maths instead, which is
      how a numbered appendix equation is built. Text BEFORE the
      equation is still refused — absorbing it would move it after the
      maths and no diff would say so.

    Pass ``jc=None`` to leave the alignment to Word.
    """
    if jc is not None and jc not in _JC_VALUES:
        raise AnchorError(f"m:jc takes one of {_JC_VALUES}, not {jc!r}")
    if in_display_mode(para_xml):
        return para_xml if jc is None else _set_math_jc(para_xml, jc)
    maths = list(OMATH_RE.finditer(para_xml))
    if len(maths) != 1:
        raise AnchorError(
            f"display needs exactly one m:oMath in the paragraph, "
            f"found {len(maths)}")
    math = maths[0]

    prose = visible_text(OMATH_RE.sub("", para_xml)).strip()
    runs = [r for r in RUN_RE.finditer(para_xml)
            if r.end() <= math.start() or r.start() >= math.end()]
    if prose:
        if not absorb:
            raise AnchorError(
                f"a run beside the equation ({prose!r}) makes Word demote "
                f"the display back to inline on the next save. Move it "
                f"inside the maths with absorb=True, or take it out of "
                f"the paragraph.")
        if any(r.start() < math.start() and visible_text(r.group(0)).strip()
               for r in runs):
            raise AnchorError(
                f"{prose!r} sits BEFORE the equation; absorbing it would "
                f"move it after the maths, and no text diff would show it")

    inner = math.group(0)
    if prose and absorb:
        inner = inner.replace(
            "</m:oMath>", f"<m:r><m:t>{escape(prose)}</m:t></m:r></m:oMath>")
    pr = (f"<m:oMathParaPr><m:jc m:val=\"{jc}\"/></m:oMathParaPr>"
          if jc else "")
    wrapped = f"<m:oMathPara>{pr}{inner}</m:oMathPara>"

    out, at = [], 0
    for r in runs:                          # every run outside the maths
        out.append(para_xml[at:r.start()])
        at = r.end()
    out.append(para_xml[at:])
    stripped = "".join(out)
    # the maths moved once the runs around it were cut out; find it again
    remade = OMATH_RE.search(stripped)
    assert remade is not None               # it was there a moment ago
    return stripped[:remade.start()] + wrapped + stripped[remade.end():]


# ------------------------------------------------- math typed as prose ----
# House rule: a symbol or expression that belongs to the model is an
# <m:oMath>, not letters in the body font. Two things go wrong when it is
# not — the symbol renders in a different face from the equation it comes
# from, and half-expressions appear, where the SYMBOL is math and the
# relation beside it is prose ("θᵢ" as OMML, "=0" as text).
#
# Precision comes from the document itself: the symbols inside its own
# equations are the paper's symbols, so those characters appearing in
# prose are unformatted math rather than ordinary words. That is why this
# does not carry a fixed vocabulary — a paper that never writes θ never
# gets a θ finding.

#: Greek letters, and the glyphs that are mathematical wherever they
#: appear — REUSING the tables to_latex already keeps, because a second
#: copy of a symbol table is a copy that will disagree with the first.
#: (Defining a private `_GREEK` set here shadowed the dict above and
#: broke to_latex; the tests caught it, which is the argument for not
#: writing the table twice.)
#:
#: Latin letters are deliberately NOT harvested: "C" is a variable in
#: half these papers and an ordinary word-letter everywhere else, and
#: flagging it would bury every real finding.
_PROSE_GREEK = frozenset(_GREEK)
#: A space is not evidence of math, wherever it appears. `to_latex` has
#: to know the invisible operators and the NBSP — they are characters it
#: meets inside `m:t` and must render — but harvesting them into the
#: paper's VOCABULARY makes every non-breaking space in the reference
#: list read as unformatted math: one real finding became nineteen. The
#: math that seeded it came from `\text{ if }` and `~`, where the space
#: is content and the converter is right to keep it.
_INVISIBLE = frozenset("⁢⁡⁤ ")
_MATH_GLYPHS = (frozenset(_SYMBOLS) | frozenset(_NARY)) - _INVISIBLE
#: Unicode sub/superscripts — "poor man's math", typed instead of built.
_SUB_SUP = set("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼ"
               "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ")
#: A relation that continues an expression the symbol started.
_RELATION = "=<>≤≥≠≈∈∉"
_INTERVAL_RE = re.compile(r"[\[(]\s*-?[\d.]+\s*,\s*-?[\d.]+\s*[\])]")
# capture the WHOLE operand, not its first character: a finding
# that reads "cmax = 1" when the text says "cmax = 100" sends a
# reader hunting for something that is not there
_TRAILING_RE = re.compile(rf"^\s*([{_RELATION}])\s*([\w.,*+-]+)")
_LEADING_RE = re.compile(rf"([\w.,*+-]+)\s*([{_RELATION}])\s*$")


@dataclass(frozen=True)
class ProseMath:
    """One symbol or expression sitting in prose instead of in OMML."""

    kind: str          # "split expression" | "symbol" | "typed script" ...
    para: int          # 1-based paragraph number
    symbol: str        # what was found
    context: str       # the surrounding words, for locating it

    def __str__(self) -> str:
        return (f"{self.kind.upper()}: {self.symbol!r} (¶{self.para}) "
                f"— …{self.context}…")


def document_symbols(xml: str) -> set[str]:
    """The Greek letters and math glyphs this document's OMML uses.

    The paper's own vocabulary, which is what makes the audit precise:
    a character is only "unformatted math" if the document typesets it
    as math somewhere else.
    """
    used: set[str] = set()
    for m in OMATH_RE.finditer(xml):
        for t in MT_RE.findall(m.group(0)):
            used |= {c for c in html.unescape(t)
                     if c in _PROSE_GREEK or c in _MATH_GLYPHS}
    return used


def prose_math(xml: str, *, symbols: set[str] | None = None
               ) -> list[ProseMath]:
    """Symbols and expressions typeset as prose rather than as OMML.

    Ordered by how certain the finding is: an expression cut in half by
    the run boundary first, then math typed with Unicode sub/superscripts,
    then the paper's own symbols loose in a sentence, then interval
    notation beside an equation.

    Deliberately NOT reported: a bare ``=`` between plain words and a
    number. "p = 0.012" and "(mean Gini = 64.6)" are statistics prose,
    and a rule that flags them is a rule nobody runs twice.
    """
    from ._xml import PARA_RE, visible_text

    known = document_symbols(xml) if symbols is None else symbols
    out: list[ProseMath] = []
    for i, pm in enumerate(PARA_RE.finditer(xml), 1):
        para = pm.group(0)
        maths = list(OMATH_RE.finditer(para))
        # the sentinel must sit INSIDE a w:t, or visible_text drops
        # it and the pieces stop lining up with the equations
        prose = visible_text(OMATH_RE.sub("<w:t>\u0000</w:t>", para))
        pieces = prose.split("\u0000")

        # 1. an expression split across the OMML boundary
        for k, math in enumerate(maths):
            after = pieces[k + 1] if k + 1 < len(pieces) else ""
            before = pieces[k] if k < len(pieces) else ""
            sym = visible_text(math.group(0))
            if (m := _TRAILING_RE.match(after)):
                out.append(ProseMath(
                    "split expression", i, f"{sym}{m.group(0).rstrip()}",
                    (before[-36:] + sym + after[:36]).strip()))
            elif (m := _LEADING_RE.search(before)):
                out.append(ProseMath(
                    "split expression", i, f"{m.group(0).strip()}{sym}",
                    (before[-36:] + sym + after[:36]).strip()))

        # 2. math typed with Unicode sub/superscripts
        for piece in pieces:
            for ch in sorted(set(piece) & _SUB_SUP):
                at = piece.index(ch)
                out.append(ProseMath(
                    "typed script", i, ch,
                    piece[max(0, at - 36):at + 36].strip()))

        # 3. the paper's own symbols, loose in a sentence
        for piece in pieces:
            for ch in sorted(set(piece) & known):
                at = piece.index(ch)
                out.append(ProseMath(
                    "symbol", i, ch,
                    piece[max(0, at - 36):at + 36].strip()))

        # 4. interval notation, but only where the paragraph is doing
        #    maths — a results table full of confidence intervals is not
        if maths:
            for piece in pieces:
                for m in _INTERVAL_RE.finditer(piece):
                    lo = max(0, m.start() - 36)
                    out.append(ProseMath(
                        "interval", i, m.group(0),
                        piece[lo:m.end() + 36].strip()))
    return out
