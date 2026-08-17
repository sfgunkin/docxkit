r"""Named styles: reading them, and applying a journal template's set.

"Format to our template" is a per-journal demand (the JITED round came
with one), and the mechanical answer is always the same: swap in the
template's ``styles.xml``, rename the style IDS the manuscript uses to
the template's names, and then LOOK at what still dangles — a style the
document references but the new part does not define renders in Word's
defaults, silently.

WHICH manuscript style maps to which template style is judgment about
two designs and stays with the paper; this module does the swap, the
remap and the audit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._xml import COMMENTS, DOCUMENT, ENDNOTES, FOOTNOTES
from .errors import AnchorError, PackageError

__all__ = [
    "DEFAULT",
    "NOWHERE",
    "RUN",
    "STYLE",
    "AnchorError",
    "Cascade",
    "PackageError",
    "Resolved",
    "Style",
    "StyleReport",
    "apply_template",
    "ensure",
    "read",
    "used",
]

_STYLE_EL_RE = re.compile(r"<w:style\b[^>]*>.*?</w:style>", re.DOTALL)
_STYLES_PART = "word/styles.xml"
# every part that can reference a style by id
_REFERRING_PARTS = (DOCUMENT, FOOTNOTES,
                    ENDNOTES, COMMENTS)
_REF_RE = re.compile(r'(<w:(?:pStyle|rStyle|tblStyle) w:val=")([^"]+)(")')


@dataclass(frozen=True)
class Style:
    """One ``w:style`` definition."""

    sid: str            # w:styleId — what the document references
    name: str           # w:name — what Word's UI shows
    type: str           # paragraph | character | table | numbering
    based_on: str | None
    xml: str


@dataclass
class StyleReport:
    """What :func:`apply_template` did and what now dangles."""

    remapped: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def format(self) -> str:
        moves = ", ".join(f"{k} x{v}" for k, v in
                          sorted(self.remapped.items())) or "none"
        lines = [f"remapped: {moves}"]
        if self.missing:
            lines.append(
                "  referenced but UNDEFINED in the new styles.xml "
                "(Word will render these with defaults): "
                + ", ".join(self.missing))
        return "\n".join(lines)


def _attr(xml: str, name: str) -> str | None:
    m = re.search(rf'<w:{name} w:val="([^"]*)"', xml)
    if m:
        return m.group(1)
    m2 = re.search(rf'w:{name}="([^"]*)"', xml)
    return m2.group(1) if m2 else None


def read(parts: dict[str, bytes]) -> list[Style]:
    """Every style the package defines."""
    if _STYLES_PART not in parts:
        raise PackageError("package has no word/styles.xml")
    xml = parts[_STYLES_PART].decode("utf-8")
    out = []
    for m in _STYLE_EL_RE.finditer(xml):
        el = m.group(0)
        out.append(Style(
            sid=_attr(el, "styleId") or "",
            name=_attr(el, "name") or "",
            type=_attr(el, "type") or "",
            based_on=_attr(el, "basedOn"),
            xml=el))
    return out


def used(xml: str) -> set[str]:
    """Style ids a part references (pStyle, rStyle, tblStyle)."""
    return {m.group(2) for m in _REF_RE.finditer(xml)}


# --------------------------------------------------------- the cascade ---
# What a run's properties RESOLVE to, which is a different question from
# what it states — and the one that decides whether a reader sees a
# difference.
#
# Two things go wrong without it, and both have been paid for here:
#
# * Word DELETES a direct property equal to the value it would inherit.
#   Measured 2026-08-10: its Compare dropped a `w:sz 20` written onto a
#   run whose paragraph style already said 20. So the same paragraph in
#   two versions can state a size in one and inherit it in the other and
#   render identically — and a comparison of what is STATED calls that a
#   change, on every author round-trip;
# * the mirror: a run that stated 20 and now states nothing, in a
#   paragraph that names no style, falls through to whatever it inherits.
#   That is a real 12pt-among-10pt defect and stating-only comparison
#   cannot see it either. `footnotes.sizes` reported both, and the false
#   one first.
#
# The order is Word's: direct run properties, then the character style
# chain, then the paragraph style chain, then docDefaults — where "the
# paragraph style" of a paragraph naming none is the one marked
# `w:default="1"`, NOT nothing. Resolving those two straight to
# docDefaults reproduced the very failure above one level out: FLOPs'
# Normal says 24 and its docDefaults 22, so 22 run-in lead-ins Word had
# merely stripped a redundant `w:sz 24` from compared as 24 -> 22, and a
# run that stated 22 and now inherits would have compared CLEAN against a
# real 11pt-to-12pt change (BACKLOG S1, 2026-08-14).

#: Where a resolved value came from, as a KIND rather than as prose.
#: WELL-FORMED is `STYLE`: a run whose paragraph carries the right
#: `pStyle` gets its size from the stylesheet, which is what the house
#: rule means. `RUN` states it directly and `DEFAULT` fell all the way
#: through to `docDefaults` — the shape of a footnote paragraph that
#: lost its style.
RUN, STYLE, DEFAULT, NOWHERE = "run", "style", "default", "nowhere"


@dataclass(frozen=True)
class Resolved:
    """What a property resolves to, and what supplied it."""

    value: str | None
    via: str                    # the phrase a report prints; "" for RUN
    kind: str                   # RUN | STYLE | DEFAULT | NOWHERE
    style: str | None = None    # the style id, when kind is STYLE


_DOC_DEFAULTS_RE = re.compile(r"<w:docDefaults\b.*?</w:docDefaults>",
                              re.DOTALL)
_STYLE_ID_RE = re.compile(r'<w:style\b[^>]*w:styleId="([^"]+)"[^>]*>(.*?)'
                          r"</w:style>", re.DOTALL)
_BASED_ON_VAL_RE = re.compile(r'<w:basedOn\b[^>]*w:val="([^"]+)"')
#: The paragraph style a paragraph that names none is IN. Both attributes
#: are matched by lookahead because their order is not ours to assume, and
#: `w:default` is an OOXML boolean, which has three spellings for true.
_DEFAULT_PSTYLE_RE = re.compile(
    r'<w:style\b(?=[^>]*\bw:type="paragraph")'
    r'(?=[^>]*\bw:default="(?:1|true|on)")[^>]*\bw:styleId="([^"]+)"')
_PSTYLE_VAL_RE = re.compile(r'<w:pStyle\b[^>]*w:val="([^"]+)"')
_RSTYLE_VAL_RE = re.compile(r'<w:rStyle\b[^>]*w:val="([^"]+)"')


def _own_rpr(style_xml: str) -> str:
    """A style's OWN run properties.

    Cut at ``w:tblStylePr``: a table style nests a whole ``w:rPr`` per
    conditional band, and the first match in the raw element is one of
    those rather than the style's own.
    """
    at = style_xml.find("<w:tblStylePr")
    return style_xml if at == -1 else style_xml[:at]


#: One compiled pattern per property, kept. This is the innermost call
#: of the whole package: `_compare_read._char_fmt` asks the cascade for
#: several properties of every RUN, and on a real pair (LI7 prev ->
#: working, 1.1 M chars) `compare.load` was 278 ms against the 34 ms the
#: comparison itself took, with `Cascade.of` -> `explain` -> `resolve`
#: 0.35 s of it across four loads. Building the pattern with an f-string
#: and handing it to `re.search` paid a cache probe per lookup.
_VAL_RE: dict[str, re.Pattern[str]] = {}


def _val(rpr: str, prop: str) -> str | None:
    """``w:val`` of ``w:<prop>`` — attribute order not assumed."""
    pattern = _VAL_RE.get(prop)
    if pattern is None:
        pattern = _VAL_RE[prop] = re.compile(
            rf'<w:{prop}\b[^>]*\bw:val="([^"]*)"')
    m = pattern.search(rpr)
    return m.group(1) if m else None


class Cascade:
    """Effective run properties, styles applied.

    Built from ``word/styles.xml``; with no styles part every lookup
    returns the DIRECT value alone, which is the honest answer rather
    than a guess about a part nobody handed over.
    """

    __slots__ = ("_based", "_default", "_default_pstyle", "_memo", "_own")

    def __init__(self, styles_xml: str | None = None) -> None:
        self._own: dict[str, str] = {}
        self._based: dict[str, str] = {}
        self._default = ""
        self._default_pstyle: str | None = None
        #: Resolution is a pure function of (prop, rpr, rstyle, pstyle)
        #: and a Cascade never changes after this constructor, so the
        #: answer is worth keeping: a manuscript repeats the same `w:rPr`
        #: blob across thousands of runs, and this is the innermost call
        #: in the package (see :data:`_VAL_RE`).
        self._memo: dict[tuple[str, str | None, str | None, str | None],
                         Resolved] = {}
        if not styles_xml:
            return
        block = _DOC_DEFAULTS_RE.search(styles_xml)
        self._default = block.group(0) if block else ""
        if (m := _DEFAULT_PSTYLE_RE.search(styles_xml)):
            self._default_pstyle = m.group(1)
        for sid, body in _STYLE_ID_RE.findall(styles_xml):
            self._own[sid] = _own_rpr(body)
            if (m := _BASED_ON_VAL_RE.search(body)):
                self._based[sid] = m.group(1)

    def _chain(self, sid: str | None, prop: str) -> str | None:
        seen: set[str] = set()
        while sid and sid in self._own and sid not in seen:
            seen.add(sid)               # a basedOn cycle is a real file
            if (found := _val(self._own[sid], prop)) is not None:
                return found
            sid = self._based.get(sid)
        return None

    def resolve(self, prop: str, *, rpr: str | None = None,
                rstyle: str | None = None, pstyle: str | None = None
                ) -> Resolved:
        """What `prop` resolves to, where from, and WHICH KIND of source.

        The kind is the part a report cannot reconstruct from the
        sentence. `footnotes.sizes` groups the reference marks by it,
        and matching on the prose ``explain`` builds ("the FootnoteText
        style") would be a parser for our own wording — the sort of
        coupling that survives exactly until someone rewords a message.

        MEMOISED per instance — see ``_memo``. The cache is keyed on
        everything the answer depends on, and a Cascade is immutable
        after construction, so a hit is the same object the miss would
        have built.
        """
        key = (prop, rpr, rstyle, pstyle)
        if (cached := self._memo.get(key)) is not None:
            return cached
        self._memo[key] = got = self._resolve(prop, rpr, rstyle, pstyle)
        return got

    def _resolve(self, prop: str, rpr: str | None, rstyle: str | None,
                 pstyle: str | None) -> Resolved:
        if rpr and (direct := _val(rpr, prop)) is not None:
            return Resolved(direct, "", RUN)
        # A paragraph that NAMES no style is not a paragraph with no
        # style: it is in the one marked `w:default="1"`, which is
        # `Normal` in every manuscript here and routinely states a size
        # docDefaults does not. Only the unnamed case falls back — a
        # named style that sets nothing inherits along its OWN basedOn
        # chain and then to docDefaults, which is Word's order, not via
        # a default style it was never based on.
        for sid in (rstyle, pstyle or self._default_pstyle):
            if (found := self._chain(sid, prop)) is not None:
                return Resolved(found, f"the {sid} style", STYLE, sid)
        if self._default and (value := _val(self._default, prop)) is not None:
            return Resolved(value, "the document default", DEFAULT)
        return Resolved(None, "", NOWHERE)

    def explain(self, prop: str, *, rpr: str | None = None,
                rstyle: str | None = None, pstyle: str | None = None
                ) -> tuple[str | None, str]:
        """``(value, where it came from)`` — "" when the run states it.

        The source is worth returning rather than recomputing: a report
        that says *"resolves to 12pt through the document default"* sends
        a reader somewhere, and *"states no size"* does not.
        """
        got = self.resolve(prop, rpr=rpr, rstyle=rstyle, pstyle=pstyle)
        return got.value, got.via

    def of(self, prop: str, *, rpr: str | None = None,
           rstyle: str | None = None, pstyle: str | None = None
           ) -> str | None:
        """What `prop` resolves to for a run, or None if nothing sets it.

        `rpr` is the run's own properties — the direct formatting, which
        wins over everything. Pass the blob rather than a value already
        picked out of it, so there is one spelling of "what does this
        element say" and not two that can disagree.
        """
        return self.explain(prop, rpr=rpr, rstyle=rstyle, pstyle=pstyle)[0]

    def style_of(self, rpr: str | None) -> str | None:
        """The character style a run names, if any."""
        m = _RSTYLE_VAL_RE.search(rpr) if rpr else None
        return m.group(1) if m else None

    @staticmethod
    def paragraph_style(p_xml: str) -> str | None:
        """The paragraph style a `w:p` NAMES, if any.

        None means "names none", which is not the same as "has none" —
        see :attr:`default_paragraph_style`, which is the style such a
        paragraph is actually in. Callers wanting the effective style
        want ``paragraph_style(p) or cascade.default_paragraph_style``;
        callers reporting on the MARKUP (has this footnote lost its
        style?) want this one, unchanged.
        """
        m = _PSTYLE_VAL_RE.search(p_xml)
        return m.group(1) if m else None

    @property
    def default_paragraph_style(self) -> str | None:
        """The `w:default="1"` paragraph style's id — what an unnamed
        paragraph is in. None when the stylesheet marks no default."""
        return self._default_pstyle

    @property
    def known(self) -> bool:
        """False when no styles part was given — nothing to resolve WITH."""
        return bool(self._own or self._default)


def ensure(parts: dict[str, bytes], style_xml: str) -> bool:
    """Append a style definition unless its id already exists.

    The definition itself should be cloned from a document where Word
    wrote it — the same rule as comment scaffolds — not hand-assembled.
    Returns True if it was added.
    """
    sid = _attr(style_xml, "styleId")
    if not sid:
        raise AnchorError("style has no w:styleId")
    xml = parts[_STYLES_PART].decode("utf-8")
    if re.search(rf'w:styleId="{re.escape(sid)}"', xml):
        return False
    close = "</w:styles>"
    at = xml.rindex(close)
    parts[_STYLES_PART] = (xml[:at] + style_xml + xml[at:]).encode("utf-8")
    return True


def apply_template(parts: dict[str, bytes],
                   template_parts: dict[str, bytes], *,
                   remap: dict[str, str] | None = None) -> StyleReport:
    """Swap in a template's ``styles.xml`` and remap the ids in use.

    `remap` renames references (old manuscript id -> template id) in
    every part that can carry one — document, notes, comments. The remap
    happens in one pass per part, each reference translated from its
    ORIGINAL id, so ``{"A": "B", "B": "C"}`` cannot chain.

    The template's theme and fonts are NOT copied: a styles.xml that
    leans on theme fonts renders differently over a different theme, and
    silently swapping ``theme1.xml`` changes colours and fonts far
    outside the styled text. If the template needs its theme, copy that
    part deliberately.

    Returns a :class:`StyleReport`; read ``missing`` — every id in it is
    a place the manuscript will fall back to Word's defaults.
    """
    if _STYLES_PART not in template_parts:
        raise PackageError("template package has no word/styles.xml")
    report = StyleReport()
    mapping = remap or {}

    for name in _REFERRING_PARTS:
        if name not in parts:
            continue
        xml = parts[name].decode("utf-8")

        def translate(m: re.Match[str]) -> str:
            new = mapping.get(m.group(2))
            if new is None:
                return m.group(0)
            report.remapped[m.group(2)] = \
                report.remapped.get(m.group(2), 0) + 1
            return m.group(1) + new + m.group(3)

        parts[name] = _REF_RE.sub(translate, xml).encode("utf-8")

    parts[_STYLES_PART] = template_parts[_STYLES_PART]

    defined = {s.sid for s in read(parts)}
    referenced: set[str] = set()
    for name in _REFERRING_PARTS:
        if name in parts:
            referenced |= used(parts[name].decode("utf-8"))
    report.missing = sorted(referenced - defined)
    return report
