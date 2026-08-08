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
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._xml import PARA_RE, used_prefixes, visible_text
from .errors import AnchorError, PackageError
from .revisions import _fragment_declarations

__all__ = [
    "OMATH_RE",
    "Equation",
    "ProseMath",
    "clone",
    "display_equations",
    "document_symbols",
    "equations",
    "find_mml2omml_xsl",
    "harvest",
    "is_display",
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
MT_RE = re.compile(r"<m:t[^>]*>([^<]*)</m:t>")
# structural OMML elements — the ones that change a formula's shape
_STRUCT = ("sSub", "sSup", "sSubSup", "nary", "f", "d", "rad", "func",
           "acc", "bar", "groupChr", "limLow", "limUpp", "m", "eqArr", "box")
_STRUCT_RE = re.compile(r"<m:(" + "|".join(_STRUCT) + r")\b")
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
    # Optional extra, absent on a plain install: pyright resolves imports
    # from the environment it runs in, and mypy's ignore_missing_imports
    # does not reach it. See [project.optional-dependencies] latex.
    import latex2mathml.converter  # pyright: ignore[reportMissingImports]
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
    return html.unescape("".join(MT_RE.findall(omml)))


def skeleton(omml: str) -> str:
    """The structural shape of an equation (sSub/nary/f/...)."""
    return "/".join(_STRUCT_RE.findall(omml))


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
    return standalone(hits[index].xml)


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


def standalone(omml: str) -> str:
    """An equation fragment that parses on its own.

    A fragment sliced out of ``word/document.xml`` inherits its
    namespace declarations from the part's root, so it carries none of
    its own and ``etree.fromstring`` rejects it — which broke the pair
    this module documents: :func:`harvest` produced exactly what
    :func:`clone` could not read. Re-serialising it through a declaring
    wrapper puts the declarations lxml needs on the element itself, and
    only the ones actually used.
    """
    from lxml import etree

    # REAL URIs only, and a refusal otherwise. revisions._fragment_
    # declarations answers the same question with a placeholder URI for
    # anything it does not know, which is right for a read-only text
    # pass and wrong here: this fragment gets INSERTED into a document,
    # and a urn:docxkit:undeclared: namespace would ship with it.
    unknown = used_prefixes(omml) - set(_NS_URIS)
    if unknown:
        raise AnchorError(
            f"equation uses undeclared namespace prefix(es) "
            f"{sorted(unknown)}; add them to equations._NS_URIS")
    root = etree.fromstring(
        f"<docxkitFragment {_NS_DECL}>{omml}</docxkitFragment>"
        .encode())
    return str(etree.tostring(root[0], encoding="unicode"))


def clone(omml: str) -> str:
    """A detached copy of an equation element, ready to insert elsewhere.

    Accepts a fragment with or without its own namespace declarations,
    so it composes with :func:`harvest` and with :func:`latex_to_omml`
    alike.
    """
    from lxml import etree

    element = etree.fromstring(standalone(omml).encode("utf-8"))
    return str(etree.tostring(copy.deepcopy(element),
                              encoding="unicode"))


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


def _local(el: Any) -> str:
    tag = str(el.tag)
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _mval(el: Any, path: str) -> str | None:
    """The ``m:val`` of a property child, or None if absent."""
    hit = el.find("/".join(f"{{{M_NS}}}{p}" for p in path.split("/")))
    return None if hit is None else hit.get(f"{{{M_NS}}}val")


class _Walker:
    def __init__(self) -> None:
        self.gaps: list[str] = []

    def children(self, el: Any) -> str:
        return "".join(self.walk(child) for child in el)

    def arg(self, el: Any, name: str) -> str:
        hit = el.find(f"{{{M_NS}}}{name}")
        return "{" + (self.children(hit) if hit is not None else "") + "}"

    def bare(self, el: Any, name: str) -> str:
        hit = el.find(f"{{{M_NS}}}{name}")
        return self.children(hit) if hit is not None else ""

    def walk(self, el: Any) -> str:
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
        if name.endswith("Pr") or name == "ctrlPr":
            return ""                          # properties are not content
        self.gaps.append(name)
        return rf"\text{{[?m:{name}]}}" + self.children(el)

    # --- leaves ------------------------------------------------------------
    def e_t(self, el: Any) -> str:
        return _text(el.text or "")

    def e_r(self, el: Any) -> str:
        body = "".join(_text(t.text or "")
                       for t in el.findall(f"{{{M_NS}}}t"))
        rpr = el.find(f"{{{M_NS}}}rPr")
        upright = rpr is not None and (
            rpr.find(f"{{{M_NS}}}nor") is not None
            or _mval(el, "rPr/sty") == "p")
        if upright and body.strip():
            return rf"\text{{{body}}}"
        return body

    # --- structures --------------------------------------------------------
    def e_oMath(self, el: Any) -> str:
        return self.children(el)

    def e_oMathPara(self, el: Any) -> str:
        return self.children(el)

    def e_f(self, el: Any) -> str:
        kind = _mval(el, "fPr/type")
        num, den = self.arg(el, "num"), self.arg(el, "den")
        if kind in ("lin", "skw"):
            return f"{num}/{den}"
        if kind == "noBar":
            return f"{{{num[1:-1]} \\atop {den[1:-1]}}}"
        return rf"\frac{num}{den}"

    def e_sSup(self, el: Any) -> str:
        return self.arg(el, "e") + "^" + self.arg(el, "sup")

    def e_sSub(self, el: Any) -> str:
        return self.arg(el, "e") + "_" + self.arg(el, "sub")

    def e_sSubSup(self, el: Any) -> str:
        return (self.arg(el, "e") + "_" + self.arg(el, "sub")
                + "^" + self.arg(el, "sup"))

    def e_sPre(self, el: Any) -> str:
        return ("{}_" + self.arg(el, "sub") + "^" + self.arg(el, "sup")
                + self.arg(el, "e"))

    def e_rad(self, el: Any) -> str:
        hide = _mval(el, "radPr/degHide")
        deg = self.bare(el, "deg")
        e = self.arg(el, "e")
        if hide == "1" or not deg.strip():
            return rf"\sqrt{e}"
        return rf"\sqrt[{deg}]{e}"

    def e_nary(self, el: Any) -> str:
        op = _NARY.get(_mval(el, "naryPr/chr") or "∫", r"\int")
        sub, sup = self.bare(el, "sub"), self.bare(el, "sup")
        out = op
        if sub.strip() and _mval(el, "naryPr/subHide") != "1":
            out += f"_{{{sub}}}"
        if sup.strip() and _mval(el, "naryPr/supHide") != "1":
            out += f"^{{{sup}}}"
        return out + " " + self.arg(el, "e")

    def e_d(self, el: Any) -> str:
        # an unmapped fence renders as itself: possibly odd TeX, but
        # visibly odd, where a silent "(" would claim a bracket the
        # equation never had
        raw_beg = _mval(el, "dPr/begChr") or "("
        raw_end = _mval(el, "dPr/endChr") or ")"
        beg = _FENCES.get(raw_beg, raw_beg)
        end = _FENCES.get(raw_end, raw_end)
        sep = _mval(el, "dPr/sepChr") or "|"
        inner = rf" \middle{sep} ".join(
            self.children(e) for e in el.findall(f"{{{M_NS}}}e")) \
            if len(el.findall(f"{{{M_NS}}}e")) > 1 \
            else self.bare(el, "e")
        return rf"\left{beg} {inner} \right{end}"

    def e_func(self, el: Any) -> str:
        fname = self.bare(el, "fName").strip()
        if fname in _KNOWN_FUNCS:
            fname = "\\" + fname
        elif fname and re.fullmatch(r"[A-Za-z]+", fname):
            fname = rf"\operatorname{{{fname}}}"
        return fname + " " + self.arg(el, "e")

    def e_acc(self, el: Any) -> str:
        mark = _ACCENTS.get(_mval(el, "accPr/chr") or "̂", r"\hat")
        return mark + self.arg(el, "e")

    def e_bar(self, el: Any) -> str:
        pos = _mval(el, "barPr/pos")
        cmd = r"\overline" if pos == "top" else r"\underline"
        return cmd + self.arg(el, "e")

    def e_groupChr(self, el: Any) -> str:
        chr_ = _mval(el, "groupChrPr/chr") or "⏟"
        if chr_ == "⏟":
            return r"\underbrace" + self.arg(el, "e")
        if chr_ == "⏞":
            return r"\overbrace" + self.arg(el, "e")
        pos = _mval(el, "groupChrPr/pos")
        cmd = r"\overset" if pos == "top" else r"\underset"
        return f"{cmd}{{{_text(chr_)}}}" + self.arg(el, "e")

    def e_limLow(self, el: Any) -> str:
        base = self.bare(el, "e").strip()
        low = self.bare(el, "lim")
        # "lim" under "n -> inf" is the operator taking its limit, which
        # LaTeX writes as \lim_{...}; anything else is a generic underset
        if base.lstrip("\\") in _KNOWN_FUNCS:
            return rf"\{base.lstrip(chr(92))}_{{{low}}}"
        return rf"\underset{{{low}}}{{{base}}}"

    def e_limUpp(self, el: Any) -> str:
        return (rf"\overset{{{self.bare(el, 'lim')}}}"
                f"{{{self.bare(el, 'e')}}}")

    def e_m(self, el: Any) -> str:
        rows = []
        for mr in el.findall(f"{{{M_NS}}}mr"):
            rows.append(" & ".join(self.children(e)
                                   for e in mr.findall(f"{{{M_NS}}}e")))
        body = r" \\ ".join(rows)
        return rf"\begin{{matrix}} {body} \end{{matrix}}"

    def e_eqArr(self, el: Any) -> str:
        lines = [self.children(e) for e in el.findall(f"{{{M_NS}}}e")]
        body = r" \\ ".join(lines)
        return rf"\begin{{aligned}} {body} \end{{aligned}}"

    def e_box(self, el: Any) -> str:
        return self.bare(el, "e")

    def e_borderBox(self, el: Any) -> str:
        return r"\boxed" + self.arg(el, "e")

    def e_phant(self, el: Any) -> str:
        return r"\phantom" + self.arg(el, "e")

    def e_e(self, el: Any) -> str:
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

    from .errors import ConversionGap

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
    it carries an ``<m:oMath>`` and no prose beyond an equation number
    and whitespace.
    """
    if "<m:oMath" not in para_xml:
        return False
    # strip the maths first: visible_text includes m:t, so leaving it in
    # would make every display equation look like a paragraph of prose
    prose = visible_text(OMATH_RE.sub("", para_xml))
    without_number = EQ_NUMBER_RE.sub("", prose)
    return not without_number.strip()


def display_equations(xml: str) -> list[re.Match[str]]:
    """Paragraph matches for every display equation, in body order."""
    return [m for m in PARA_RE.finditer(xml) if is_display(m.group(0))]


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
_MATH_GLYPHS = frozenset(_SYMBOLS) | frozenset(_NARY)
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
