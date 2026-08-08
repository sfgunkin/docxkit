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

__all__ = ["Style", "StyleReport", "apply_template", "ensure", "read",
           "used"]

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
