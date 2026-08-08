r"""Document hygiene: parts a manuscript should not carry, glyphs it
should not mix.

Word accumulates parts nobody asked for. The recurring one is the
``customXml/`` bibliography data store, which it injects when a document
has ever seen its citation manager: it is vestigial, it travels into
submissions, and on the DSI paper it needed its own commit to remove.

Dropping the parts is the easy half. The half that goes wrong is the
references: an ``[Content_Types].xml`` Override or a relationship still
pointing at a part that no longer exists is exactly what Word reports as
"unreadable content".

:func:`smarten` is the other hygiene chore: a manuscript mixes straight
and curly quotes because autocorrect ran on some paragraphs and not
others. The matching side of that is already handled everywhere via
``normalize=True``; this is the REPAIR side, run once so the phantom
class of diffs stops existing.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from ._xml import PARA_RE, T_PARTS_RE, element_spans, escape, visible_text

__all__ = [
    "CUSTOM_XML",
    "NOTE_LEADS",
    "SmartenReport",
    "SpacingReport",
    "smarten",
    "strip_parts",
    "table_spacing",
]

CUSTOM_XML = "customXml/"

#: What opens a table's note. A note belongs to the table above it — it is
#: set tight against the bottom rule, at 0 before — so it is never the
#: paragraph the spacing rule is about. The asterisk form is a note's second
#: line, which the rule must skip for the same reason.
NOTE_LEADS = ("Примечание", "Note", "Notes", "Источник", "Source", "*")


def strip_parts(parts: dict[str, bytes],
                prefixes: tuple[str, ...] = (CUSTOM_XML,)) -> list[str]:
    """Drop whole part-trees by name prefix, patching what referenced them.

    Mutates `parts` and returns the names removed. ``word/document.xml``
    is never touched, so the manuscript content is provably unchanged —
    which is the point of doing this on the package rather than by
    re-saving through Word.
    """
    dropped = sorted(n for n in parts
                     if any(n.startswith(p) for p in prefixes))
    if not dropped:
        return []

    for name in dropped:
        del parts[name]

    for prefix in prefixes:
        quoted = re.escape(prefix)
        if "[Content_Types].xml" in parts:
            xml = parts["[Content_Types].xml"].decode("utf-8")
            xml = re.sub(rf'<Override PartName="/{quoted}[^"]*"[^>]*/>',
                         "", xml)
            parts["[Content_Types].xml"] = xml.encode("utf-8")
        rels = "word/_rels/document.xml.rels"
        if rels in parts:
            xml = parts[rels].decode("utf-8")
            xml = re.sub(
                rf'<Relationship[^>]*Target="(?:\.\./)?{quoted}[^"]*"[^>]*/>',
                "", xml)
            parts[rels] = xml.encode("utf-8")
    return dropped


# ------------------------------------------------------------- smarten ------

# w:t ONLY: m:t is mathematics, where a straight quote is a prime and
# "fixing" it corrupts the formula; w:delText is someone's tracked
# deletion, not ours to retypeset; w:instrText is field code.
_WT_RE = T_PARTS_RE                    # the shared definition


@dataclass
class SpacingReport:
    """What :func:`table_spacing` set, and what it deliberately did not."""

    spaced: list[str] = field(default_factory=list)     # got `before`
    notes: list[str] = field(default_factory=list)      # pinned to 0
    skipped: list[str] = field(default_factory=list)    # and why

    def format(self) -> str:
        lines = [(f"paragraphs spaced {len(self.spaced)}, "
                  f"notes pinned {len(self.notes)}, "
                  f"skipped {len(self.skipped)}")]
        lines += [f"  skipped: {s}" for s in self.skipped]
        return "\n".join(lines)


def _is_note(text: str) -> bool:
    return text.lstrip().startswith(NOTE_LEADS)


def _is_heading(para_xml: str) -> bool:
    m = re.search(r'<w:pStyle w:val="([^"]+)"', para_xml)
    return bool(m) and m.group(1).lower().startswith("heading")


def _is_equation_carrier(tbl_xml: str) -> bool:
    """A numbered display equation is a 1×2 table whose second cell is «(N)».

    It is a table to the schema and an equation to the reader, and the
    paragraph after it continues the sentence the equation sits in — so the
    rule that separates a table from the text below does not apply to it.
    """
    rows = re.findall(r"<w:tr\b.*?</w:tr>", tbl_xml, re.DOTALL)
    if len(rows) != 1:
        return False
    cells = re.findall(r"<w:tc\b.*?</w:tc>", rows[0], re.DOTALL)
    return (len(cells) == 2
            and bool(re.fullmatch(r"\([\w.]+\)",
                                  visible_text(cells[-1]).strip())))


def _set_before(para_xml: str, twentieths: int) -> tuple[str, bool]:
    """Set `w:spacing/@w:before` on a paragraph, inserting pPr if need be."""
    m = re.search(r"<w:spacing\b[^>]*/>", para_xml)
    if m:
        tag = m.group(0)
        if re.search(rf'w:before="{twentieths}"', tag):
            return para_xml, False
        stripped = re.sub(r'\s*w:before="[^"]*"', "", tag)
        new = stripped.replace(
            "<w:spacing", f'<w:spacing w:before="{twentieths}"', 1)
        return para_xml[:m.start()] + new + para_xml[m.end():], True
    spacing = f'<w:spacing w:before="{twentieths}"/>'
    ppr = re.search(r"<w:pPr>", para_xml)
    if ppr:
        # CT_PPr order: spacing precedes ind / jc / rPr, follows pStyle
        body_start = ppr.end()
        rest = para_xml[body_start:]
        anchor = re.search(r"<w:(ind|jc|rPr|sectPr)\b", rest)
        at = body_start + (anchor.start() if anchor else 0)
        if not anchor:
            close = rest.find("</w:pPr>")
            at = body_start + close
        return para_xml[:at] + spacing + para_xml[at:], True
    open_tag = re.match(r"<w:p\b[^>]*>", para_xml)
    assert open_tag is not None
    return (para_xml[:open_tag.end()] + f"<w:pPr>{spacing}</w:pPr>"
            + para_xml[open_tag.end():], True)


def table_spacing(xml: str, *, before: int = 120,
                  note_before: int = 0) -> tuple[str, SpacingReport]:
    """House rule: the text that RESUMES after a table gets space above it.

    A table ends in a rule, and the next paragraph starts hard against it
    unless something separates them. `before` is in twentieths of a point,
    so the house 6pt is 120.

    Three things are deliberately not the paragraph that resumes:

    * a NOTE belongs to the table above it and is set tight against it, so
      it is skipped and pinned to `note_before` (0) instead;
    * a HEADING carries its own, larger spacing from its style — giving it
      6pt would make the gap SMALLER, not larger;
    * an EQUATION CARRIER is a table only to the schema; the «where …»
      that follows it continues the sentence the equation is part of.

    Idempotent, so a second call reports nothing — which makes it an audit
    as well as a repair: run it on a copy, and an empty report means the
    document already follows the rule.
    """
    report = SpacingReport()
    out = xml
    for start, end in reversed(element_spans(xml, "tbl")):
        tbl = xml[start:end]
        if _is_equation_carrier(tbl):
            report.skipped.append(
                f"equation {visible_text(tbl)[-8:].strip()}: a carrier, "
                f"not a table")
            continue
        pos = end
        while True:
            m = PARA_RE.search(out, pos)
            if m is None:
                break
            para, text = m.group(0), visible_text(m.group(0))
            if not text.strip():
                # An empty paragraph is a spacer, or the carrier of a
                # section break — a landscape page is made by putting a
                # sectPr in one right after the table. It is not the text
                # that resumes, and spacing it moves nothing a reader sees.
                pos = m.end()
                continue
            if _is_note(text):
                fixed, changed = _set_before(para, note_before)
                if changed:
                    out = out[:m.start()] + fixed + out[m.end():]
                    report.notes.append(text[:48])
                pos = m.start() + len(fixed if changed else para)
                continue
            if _is_heading(para):
                report.skipped.append(f"heading {text[:40]!r}: has its own")
                break
            fixed, changed = _set_before(para, before)
            if changed:
                out = out[:m.start()] + fixed + out[m.end():]
                report.spaced.append(text[:48])
            break
    return out, report


@dataclass
class SmartenReport:
    """What :func:`smarten` changed, and what it declined to guess."""

    apostrophes: int = 0
    quotes: int = 0
    ambiguous: int = 0            # a straight ' with no word before it —
    #                               an opening quote or an elision ('n'),
    #                               and only the author knows which
    unbalanced: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [(f"apostrophes {self.apostrophes}, "
                  f"double quotes {self.quotes}, "
                  f"left ambiguous {self.ambiguous}")]
        lines += [f"  unbalanced quotes, untouched: {snippet}"
                  for snippet in self.unbalanced]
        return "\n".join(lines)


def _smarten_para(para: str, report: SmartenReport) -> str:
    wts = list(_WT_RE.finditer(para))
    if not wts:
        return para
    decoded = [html.unescape(m.group(2)) for m in wts]
    stream = "".join(decoded)
    if "'" not in stream and '"' not in stream:
        return para

    quotes_pair = stream.count('"') % 2 == 0
    if not quotes_pair and '"' in stream:
        report.unbalanced.append(" ".join(stream.split())[:70])

    opening = True
    prev = ""
    out_texts = []
    changed = False
    for text in decoded:
        buf = []
        for ch in text:
            if ch == "'":
                if prev.isalnum():
                    # after a word character it is an apostrophe or a
                    # closing quote, and both smarten the same way:
                    # don't, workers', it's
                    buf.append("’")
                    report.apostrophes += 1
                    changed = True
                else:
                    buf.append(ch)
                    report.ambiguous += 1
            elif ch == '"' and quotes_pair:
                buf.append("“" if opening else "”")
                opening = not opening
                report.quotes += 1
                changed = True
            else:
                buf.append(ch)
            prev = ch
        out_texts.append("".join(buf))

    if not changed:
        return para
    for m, new in sorted(zip(wts, out_texts, strict=True),
                         key=lambda pair: -pair[0].start()):
        para = (para[:m.start()] + m.group(1) + escape(new) + m.group(3)
                + para[m.end():])
    return para


def smarten(xml: str) -> tuple[str, SmartenReport]:
    """Straight quotes to typographic ones, where it cannot go wrong.

    Two safe rules, nothing more:

    * ``'`` immediately after a word character becomes ``’`` — don't,
      it's, workers'. The lookback crosses run boundaries, so a
      fragmented "workers" + "' rights" still qualifies.
    * ``"`` pairs alternate ``“``/``”`` within a paragraph, and ONLY in
      paragraphs whose straight-quote count is even; an odd count means
      the pairing would be a guess, so the paragraph is left as it was
      and reported.

    A leading ``'`` (opening single quote? an elision like 'n'?) is
    counted as ambiguous and left alone. Math (``m:t``), tracked
    deletions and field instructions are never touched. Quote state does
    not cross paragraphs, matching how Word's own autocorrect decides.

    Matching through the mixture (``normalize=True``) keeps working
    either way; run this once so the mixture stops generating phantom
    diffs against author files.
    """
    report = SmartenReport()
    out = PARA_RE.sub(lambda m: _smarten_para(m.group(0), report), xml)
    return out, report
