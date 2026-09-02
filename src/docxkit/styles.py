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
from collections.abc import Iterator
from dataclasses import dataclass, field

from ._xml import (
    COMMENTS,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    PARA_RE,
    RUN_RE,
    own_properties,
    visible_text,
)
from .errors import AnchorError, PackageError

__all__ = [
    "DEFAULT",
    "NOWHERE",
    "RUN",
    "STYLE",
    "AnchorError",
    "Cascade",
    "PackageError",
    "Raised",
    "Resolved",
    "Style",
    "StyleReport",
    "apply_template",
    "ensure",
    "paragraph_property",
    "raised_prose",
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


#: An ON/OFF run property, present-means-on. `\s*/>` and not `/>`: XML
#: says `<w:i/>` and `<w:i />` are one element and pandoc writes the
#: spaced form for every self-closing tag — the same blindness that made
#: `compare` read a pandoc document as carrying no italics at all.
_TOGGLE_RE: dict[str, re.Pattern[str]] = {}

#: What OOXML writes for "off" in a toggle's `w:val`. Everything else,
#: the absent attribute included, is on.
_OFF = frozenset({"0", "false", "off", "none"})


def _toggle(rpr: str, prop: str) -> bool | None:
    """Is this toggle ON, OFF, or unstated (None) in this blob?

    Toggles do not resolve the way `sz` and `color` do: presence is the
    value. `<w:i/>` is italic on, `<w:i w:val="0"/>` is italic off, and
    neither can be read by :func:`_val`, which needs an attribute —
    which is why the cascade could not see a single one of them.

    `<w:bCs/>` must not answer for `w:b`, so the tag is closed off with
    ``\\b`` and the two forms are spelled out rather than left to a
    prefix match.
    """
    pattern = _TOGGLE_RE.get(prop)
    if pattern is None:
        pattern = _TOGGLE_RE[prop] = re.compile(
            rf'<w:{prop}(?:\s*/>|\s+[^>]*?/>|\s*>)')
    m = pattern.search(rpr)
    if m is None:
        return None
    got = re.search(r'\bw:val="([^"]*)"', m.group(0))
    return got is None or got.group(1) not in _OFF


#: One compiled pattern per paragraph property, for the same reason
#: `_VAL_RE` is kept: the comparison asks for several of these per
#: paragraph over a whole manuscript.
_EL_RE: dict[str, re.Pattern[str]] = {}


def _element_re(tag: str) -> re.Pattern[str]:
    pattern = _EL_RE.get(tag)
    if pattern is None:
        pattern = _EL_RE[tag] = re.compile(
            rf"<w:{tag}\b[^>]*?(?:/>|>.*?</w:{tag}>)", re.DOTALL)
    return pattern


_ATTR_RE: dict[str, re.Pattern[str]] = {}


def _attr_of(element: str, name: str) -> str | None:
    """``w:<name>`` ON this element — ``<w:ind w:hanging="360"/>`` -> 360.

    Not :func:`_attr` above, which searches a whole blob and falls back
    to any attribute of that name anywhere in it. Here the element is
    the question: an indent's `left` is the one on the `w:ind`, and a
    blob-wide search would answer with a table cell's.
    """
    pattern = _ATTR_RE.get(name)
    if pattern is None:
        pattern = _ATTR_RE[name] = re.compile(rf'\bw:{name}="([^"]*)"')
    m = pattern.search(element)
    return m.group(1) if m else None


def _element(xml: str, tag: str) -> str | None:
    """The first whole ``w:<tag>`` element in `xml`, or None (see below).

    The element and not a value, because a paragraph property is not
    one: ``<w:jc w:val="both"/>`` states a value, ``<w:ind w:left="360"
    w:hanging="360"/>`` states four, and ``<w:keepNext/>`` states none
    and means yes. :func:`_val` can read the first of those and no more,
    which is why the cascade could answer for a run's size and had
    nothing to say about an indent.
    """
    m = _element_re(tag).search(xml)
    return m.group(0) if m else None


_PPR_DEFAULT_RE = re.compile(r"<w:pPrDefault\b.*?</w:pPrDefault>", re.DOTALL)


class Cascade:
    """Effective run properties, styles applied.

    Built from ``word/styles.xml``; with no styles part every lookup
    returns the DIRECT value alone, which is the honest answer rather
    than a guess about a part nobody handed over.
    """

    __slots__ = ("_based", "_default", "_default_pstyle", "_memo", "_own",
                 "_pdefault")

    def __init__(self, styles_xml: str | None = None) -> None:
        self._own: dict[str, str] = {}
        self._based: dict[str, str] = {}
        self._default = ""
        self._pdefault = ""
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
        # The PARAGRAPH half of the document defaults, kept apart from
        # the whole block: `w:rPrDefault` holds a `w:spacing` too — the
        # letter spacing of a run — and a paragraph asking the block for
        # "spacing" would be answered by that one.
        pdef = _PPR_DEFAULT_RE.search(self._default)
        self._pdefault = pdef.group(0) if pdef else ""
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

    def _chain_el(self, sid: str | None, tag: str) -> str | None:
        seen: set[str] = set()
        while sid and sid in self._own and sid not in seen:
            seen.add(sid)
            if (found := _element(self._own[sid], tag)) is not None:
                return found
            sid = self._based.get(sid)
        return None

    def _para_sources(self, ppr: str | None,
                      pstyle: str | None) -> Iterator[str]:
        """The property blobs a paragraph resolves through, nearest first.

        Its own properties, then its style's ``basedOn`` chain, then the
        ``w:default="1"`` paragraph style for a paragraph that names
        none, then the document's ``pPrDefault``. Word's order, and the
        same one :meth:`resolve` walks for a run.
        """
        if ppr:
            yield ppr
        sid = pstyle or self._default_pstyle
        seen: set[str] = set()
        while sid and sid in self._own and sid not in seen:
            seen.add(sid)               # a basedOn cycle is a real file
            yield self._own[sid]
            sid = self._based.get(sid)
        if self._pdefault:
            yield self._pdefault

    def para_element(self, tag: str, *, ppr: str | None = None,
                     pstyle: str | None = None) -> str | None:
        """The ``w:<tag>`` element in force for a PARAGRAPH, styles applied.

        For the properties whose PRESENCE is the whole value —
        `keepNext`, `keepLines`, `pageBreakBefore`. Ask
        :meth:`para_attr` for the ones that carry numbers.

        Resolved rather than read off the paragraph, for the reason
        :data:`_compare_read._VALUED` gives about size and colour: Word
        deletes a direct property equal to the inherited one, so
        comparing what is STATED reports a difference between documents
        that render identically. A reference list whose entries carry
        the hanging indent through their style and one that states it on
        every paragraph are the same page.

        Pass the paragraph's OWN ``w:pPr`` inner, with any
        ``w:pPrChange`` already cut off (:func:`docxkit._xml.
        live_properties`): that snapshot is the formatting a tracked
        change REPLACED, and reading it answers about the past.
        """
        for blob in self._para_sources(ppr, pstyle):
            if (found := _element(blob, tag)) is not None:
                return found
        return None

    def para_attr(self, tag: str, attr: str, *, ppr: str | None = None,
                  pstyle: str | None = None) -> str | None:
        """One ATTRIBUTE of a paragraph property, styles applied.

        Per attribute and not per element, because that is how Word
        merges these: a paragraph that states ``<w:spacing w:before="0"/>``
        directly keeps its style's `after` and `line`. Resolving the
        element as a unit makes such a paragraph read as having lost
        them, and the pair it is compared against — one that states
        nothing and inherits all three — comes back as a difference
        between two identical pages. Measured writing the layer that
        needed this, which is the whole hazard it exists to avoid.

        Every ``w:<tag>`` in a blob is examined, not just the first: a
        paragraph's ``w:pPr`` nests the paragraph mark's ``w:rPr``, and
        that carries a ``w:spacing`` of its own — the letter spacing of
        a run, which states none of these attributes and must not stop
        the walk.

        That inner loop is DEFENCE and not mechanism, which is worth
        saying because a mutation reducing it to the first match
        survives the suite. Measured 2026-08-31 over 300 manuscripts:
        685 blobs hold two or more ``w:spacing`` and **not one** puts
        the letter-spacing element before the paragraph's own. Schema
        order is why — ``w:spacing`` precedes ``w:rPr`` in ``CT_PPr``
        and ``w:pPr`` precedes ``w:rPr`` in ``CT_Style`` — and Word
        repairs a pPr written out of order by dropping the misplaced
        child (see :data:`docxkit._xml.PPR_ORDER`). Kept anyway, at the
        cost of one loop: the failure it prevents is silent, the
        paragraph would read as stating no spacing at all, and a
        contrived test for a shape Word repairs would pin the wrong
        thing.
        """
        pattern = _element_re(tag)
        for blob in self._para_sources(ppr, pstyle):
            for m in pattern.finditer(blob):
                if (value := _attr_of(m.group(0), attr)) is not None:
                    return value
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

    def toggle(self, prop: str, *, rpr: str | None = None,
               rstyle: str | None = None, pstyle: str | None = None
               ) -> bool:
        """Is this ON/OFF property in force for a run, styles applied?

        The `of`/`explain` pair cannot answer for these: they read
        ``w:val``, and a toggle's ON form is the bare element. So the
        cascade was blind to italic, bold, strike and smallCaps
        entirely, and `compare` read them off the run instead — which
        cries wolf for exactly the reason the valued properties are
        resolved here and not read off the run.

        Word deletes a direct property equal to the inherited one, so a
        run styled `Emphasis` (which defines ``<w:i/>``) loses its own
        ``<w:i/>`` on save. Measured 2026-08-29 on Life_Expectancy: four
        journal names reported as ITALIC LOST, on a comparison against
        the author's own Accept All, every one of them still italic on
        the page. A layer that reports four false losses at the moment
        an acceptance really can strip run properties teaches its reader
        to skim past the real one.

        Resolution order is the run, then the character style's
        ``basedOn`` chain, then the paragraph style's, then the document
        default — the same order :meth:`resolve` uses. Word's true
        toggle semantics XOR a direct value against the style's; that
        difference only shows for a run that turns a styled italic OFF,
        which reads correctly here as off.
        """
        if rpr is not None and (direct := _toggle(rpr, prop)) is not None:
            return direct
        for start in (rstyle, pstyle or self._default_pstyle):
            if (found := self._toggle_chain(start, prop)) is not None:
                return found
        if self._default:
            got = _toggle(self._default, prop)
            if got is not None:
                return got
        return False

    def _toggle_chain(self, sid: str | None, prop: str) -> bool | None:
        """:meth:`_chain`, for a property whose ON form has no value."""
        seen: set[str] = set()
        while sid and sid in self._own and sid not in seen:
            seen.add(sid)               # a basedOn cycle is a real file
            if (found := _toggle(self._own[sid], prop)) is not None:
                return found
            sid = self._based.get(sid)
        return None

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


#: The word boundary is load-bearing: without it `<w:pPrDefault>` opens
#: a match that then runs to the `</w:pPr>` INSIDE it, and docDefaults
#: reads as an empty blob.
_PPR_RE = re.compile(r"<w:pPr\b[^>]*(?<!/)>.*?</w:pPr>", re.DOTALL)


def _ppr_attr(ppr: str, tag: str, attr: str) -> str | None:
    """``w:<attr>`` of ``w:<tag>`` inside one ``w:pPr`` blob.

    Not :func:`_attr`, which reads an attribute off an element this
    module already has in hand; this one goes looking for the element.
    """
    m = re.search(rf'<w:{tag}\b[^>]*?\bw:{attr}="([^"]*)"', ppr)
    return m.group(1) if m else None


def paragraph_property(styles_xml: str | None, pstyle: str | None,
                       tag: str, attr: str) -> str | None:
    """What a paragraph INHERITS for ``w:<tag>/@w:<attr>``, or None.

    Walks the ``w:basedOn`` chain from `pstyle` (or the default paragraph
    style when a paragraph names none) and then ``w:docDefaults``. The
    answer excludes the paragraph's own ``w:pPr`` — the question this
    exists to answer is "would writing this value be REDUNDANT?".

    **Why it is worth resolving rather than always writing.** Word
    deletes a paragraph-property declaration whose value equals the
    inherited one, so a formatting pass that writes a redundant value
    comes back dirty on the next audit for ever — measured on eleven DSI
    table notes, where an explicit ``w:before="0"`` over an inherited 0
    was gone after one save and the audit reported the same eleven every
    run. Correct an explicit DISAGREEING value; leave an inheriting
    paragraph inheriting.

    Attribute-shaped rather than ``w:val``-shaped on purpose: the
    properties this question comes up for — ``w:spacing/@w:before``,
    ``w:ind/@w:hanging`` — carry their value in an attribute of their
    own, which :class:`Cascade` (a RUN cascade, reading ``w:val``)
    cannot answer.
    """
    if not styles_xml:
        return None
    own: dict[str, str] = {}
    based: dict[str, str] = {}
    for sid, body in _STYLE_ID_RE.findall(styles_xml):
        m = _PPR_RE.search(body)
        own[sid] = m.group(0) if m else ""
        if (b := _BASED_ON_VAL_RE.search(body)):
            based[sid] = b.group(1)

    if pstyle is None and (m := _DEFAULT_PSTYLE_RE.search(styles_xml)):
        pstyle = m.group(1)

    seen: set[str] = set()
    sid = pstyle
    while sid and sid in own and sid not in seen:
        seen.add(sid)                   # a basedOn cycle is a real file
        if (found := _ppr_attr(own[sid], tag, attr)) is not None:
            return found
        sid = based.get(sid)

    block = _DOC_DEFAULTS_RE.search(styles_xml)
    if block is None:
        return None
    ppr = _PPR_RE.search(block.group(0))
    return _ppr_attr(ppr.group(0), tag, attr) if ppr else None


@dataclass(frozen=True)
class Raised:
    """One run of prose that renders raised or lowered, and why."""

    part: str            # word/footnotes.xml
    where: str           # "fn 5", "¶12" — the note or paragraph
    style: str           # the character style supplying it
    value: str           # superscript | subscript
    text: str            # what a reader sees raised


#: The elements that ARE a note mark. A run holding one is the mark
#: itself, whose whole job is to be raised.
_NOTE_MARK_RE = re.compile(
    r"<w:(?:footnoteRef|endnoteRef|footnoteReference|endnoteReference"
    r"|commentReference|annotationRef)\b")
#: The AUTO mark specifically. A note definition opens with its mark
#: either as this element or, for a note marked `*` rather than
#: numbered, as literal text in the first run — and that text run wears
#: `FootnoteReference` legitimately. See :func:`raised_prose`.
_AUTO_MARK_RE = re.compile(r"<w:(?:footnoteRef|endnoteRef)\b")
#: A body reference that says the mark is the text after it, rather than
#: an auto number. Spec-derived: no manuscript in the corpus exercised
#: it, and the suppression can only ever REMOVE a finding.
_CUSTOM_MARK_RE = re.compile(
    r"<w:(?:footnote|endnote)Reference\b[^>]*"
    r'w:customMarkFollows="(?:1|true|on)"')
_RPRCHANGE_RE = re.compile(r"<w:rPrChange\b.*?</w:rPrChange>", re.DOTALL)
_RAISING = ("superscript", "subscript")
#: A deleted run is going away; its typography is not a defect.
_DEL_RE = re.compile(r"<w:del\b[^>]*(?<!/)>.*?</w:del>", re.DOTALL)


def raised_prose(parts: dict[str, bytes]) -> list[Raised]:
    r"""Prose that renders raised because its CHARACTER STYLE says so.

    A footnote's whole sentence rendered in superscript for 20 days and
    every gate passed it: `footnotes --check` reads SIZE only, `lint`,
    `citations`, `refstyle` and `math` are content-blind to run
    properties, and `compare`'s FORMAT layer had no text-matched pair
    because the note had been replaced wholesale in the same batch. The
    author found it by reading the page (Parental_style, 2026-09-01).

    **A grep for ``w:vertAlign`` reports such a file clean**, which is
    the trap worth recording. The run carried
    ``<w:rStyle w:val="FootnoteReference"/>`` and no ``vertAlign`` of
    its own; ``styles.xml`` gives that style ``vertAlign=superscript``,
    so the raising was inherited and the character style has to be
    resolved before the question can even be asked. That is what
    :class:`Cascade` is for, and why this lives here.

    So: a run of visible text whose ``vertAlign`` resolves through a
    STYLE rather than the run itself. A run stating its own
    ``vertAlign`` — including ``baseline`` — is deliberate and passes.

    **What is exempt, and why it is position rather than length.** A
    note definition OPENS with its mark. Usually that is
    ``<w:footnoteRef/>``, which this skips as a mark like any other; but
    a footnote marked ``*`` rather than numbered carries the asterisk as
    literal TEXT in the first run, wearing ``FootnoteReference`` on
    purpose. Measured over 300 manuscripts, that one case is 22 of 26
    findings. The discriminator is exact and needs no heuristic — run 0
    of a note paragraph holding no auto mark IS the mark — where a
    length rule would have been a guess, and would have missed the
    raised full stop this found at the end of an unrelated footnote.

    With it: **4 findings over 300 manuscripts, every one real** — the
    Parental_style sentence in three generations of that paper, and that
    stray full stop.
    """
    blob = parts.get(_STYLES_PART)
    cascade = Cascade(blob.decode("utf-8") if blob else None)
    if not cascade.known:
        return []          # no styles part: nothing to inherit FROM
    found: list[Raised] = []
    for part in (DOCUMENT, FOOTNOTES, ENDNOTES):
        raw = parts.get(part)
        if raw:
            found.extend(_raised_in(raw.decode("utf-8"), part, cascade))
    return found


#: A note DEFINITION and its id, for naming the finding. A paragraph
#: index into `footnotes.xml` is not the note a reader can look up:
#: Word's separator and continuation notes sit at the head of the part
#: and a long note runs to several paragraphs, so "note 7" was footnote
#: 5. The id is what every other message in the package names a note by.
_NOTE_EL_RE = re.compile(r'<w:(footnote|endnote)\b[^>]*w:id="(-?\d+)"'
                         r"[^>]*>.*?</w:\1>", re.DOTALL)


def _note_at(spans: list[tuple[int, int, str]], at: int) -> str | None:
    """The id of the note containing `at`."""
    return next((nid for lo, hi, nid in spans if lo <= at < hi), None)


def _raised_in(xml: str, part: str, cascade: Cascade) -> list[Raised]:
    """:func:`raised_prose` over one part."""
    notes = part in (FOOTNOTES, ENDNOTES)
    spans = ([(m.start(), m.end(), m.group(2))
              for m in _NOTE_EL_RE.finditer(xml)] if notes else [])
    label = "fn" if part == FOOTNOTES else "en"
    gone = [(m.start(), m.end()) for m in _DEL_RE.finditer(xml)]
    found: list[Raised] = []
    for i, pm in enumerate(PARA_RE.finditer(xml)):
        para = pm.group(0)
        pstyle = Cascade.paragraph_style(para)
        runs = list(RUN_RE.finditer(para))
        custom = notes and not _AUTO_MARK_RE.search(para)
        for j, rm in enumerate(runs):
            if custom and j == 0:
                continue                       # the note's own mark
            run = rm.group(0)
            if (j and _CUSTOM_MARK_RE.search(runs[j - 1].group(0))):
                continue                       # a body custom mark
            text = visible_text(run)
            if not text.strip() or _NOTE_MARK_RE.search(run):
                continue
            at = pm.start() + rm.start()
            if any(lo <= at < hi for lo, hi in gone):
                continue
            # The run's OWN properties, its rPrChange cut. A tracked
            # FORMATTING change stores the SUPERSEDED properties as a
            # complete `w:rPr` NESTED inside the live one, so both a
            # non-greedy `<w:rPr>.*?</w:rPr>` and a `w:rPrChange` cut
            # applied after it are wrong: the first closes on the
            # snapshot and returns the element cut in half, leaving the
            # historical `w:rStyle` in and the cut with nothing to
            # match. `own_properties` finds the close by depth, which is
            # what it was written for; the snapshot then comes out.
            own = own_properties(run, "rPr")
            rpr = _RPRCHANGE_RE.sub("", own[2]) if own else ""
            got = cascade.resolve("vertAlign", rpr=rpr,
                                  rstyle=cascade.style_of(rpr),
                                  pstyle=pstyle)
            if got.kind == STYLE and got.value in _RAISING:
                nid = _note_at(spans, at) if notes else None
                where = f"{label} {nid}" if nid else f"¶{i + 1}"
                found.append(Raised(part, where, got.style or "?",
                                    got.value, text.strip()))
    return found
