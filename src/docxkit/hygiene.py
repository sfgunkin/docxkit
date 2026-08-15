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
from .package import CORE_PART, core_property, set_core_property

__all__ = [
    "CARRIED_PROPERTIES",
    "CUSTOM_XML",
    "NOTE_LEADS",
    "SmartenReport",
    "SpacingReport",
    "carry_properties",
    "restore_parts",
    "smarten",
    "strip_parts",
    "table_spacing",
]

CUSTOM_XML = "customXml/"
_CONTENT_TYPES = "[Content_Types].xml"
_DOC_RELS = "word/_rels/document.xml.rels"
_PKG_RELS = "_rels/.rels"
_ID_RE = re.compile(r'\bId="rId(\d+)"')
_TARGET_RE = re.compile(r'\bTarget="([^"]+)"')

#: What ``docProps/core.xml`` says about the DOCUMENT, as against what it
#: says about the last save. ``cp:lastModifiedBy``, ``cp:revision``,
#: ``dcterms:created`` and ``dcterms:modified`` are deliberately not here:
#: they belong to whichever file is being written, and carrying them over
#: would backdate a deliverable to its source.
CARRIED_PROPERTIES = ("dc:title", "dc:subject", "dc:creator",
                      "cp:keywords", "dc:description", "cp:category")

_CORE_CT = ('<Override PartName="/docProps/core.xml" ContentType='
            '"application/vnd.openxmlformats-package.core-properties+xml"/>')
_CORE_REL_TYPE = ("http://schemas.openxmlformats.org/package/2006/"
                  "relationships/metadata/core-properties")
_EMPTY_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package'
    '/2006/metadata/core-properties"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
    ' xmlns:dcterms="http://purl.org/dc/terms/"'
    ' xmlns:dcmitype="http://purl.org/dc/dcmitype/"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    "</cp:coreProperties>")

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
        if _CONTENT_TYPES in parts:
            xml = parts[_CONTENT_TYPES].decode("utf-8")
            xml = re.sub(rf'<Override PartName="/{quoted}[^"]*"[^>]*/>',
                         "", xml)
            parts[_CONTENT_TYPES] = xml.encode("utf-8")
        if _DOC_RELS in parts:
            xml = parts[_DOC_RELS].decode("utf-8")
            xml = re.sub(
                rf'<Relationship[^>]*Target="(?:\.\./)?{quoted}[^"]*"[^>]*/>',
                "", xml)
            parts[_DOC_RELS] = xml.encode("utf-8")
    return dropped


def _free_rid(rels_xml: str, wanted: str) -> str:
    """`wanted` if no relationship uses it, otherwise the next free rId."""
    taken = {f"rId{n}" for n in _ID_RE.findall(rels_xml)}
    if wanted and wanted not in taken:
        return wanted
    n = max((int(x) for x in _ID_RE.findall(rels_xml)), default=0)
    return f"rId{n + 1}"


def restore_parts(parts: dict[str, bytes], source: dict[str, bytes],
                  prefixes: tuple[str, ...] = (CUSTOM_XML,)) -> list[str]:
    """Copy whole part-trees back from `source`, with their references.

    The mirror of :func:`strip_parts`, and the reason it exists is that
    Word's Compare REBUILDS a document rather than annotating it, and
    what it declines to carry over it drops in silence: the three
    ``customXml/`` parts, the ``[Content_Types].xml`` Override and the
    relationship, all gone from a redline whose text is perfect. Nothing
    downstream notices — `lint` is clean, `validate` passes, Word opens
    the file happily — and `promote` then copies the batch over
    ``working.docx``, so the data store is gone from the live manuscript
    (Parental Style 2026-08-12, where the author's Word had just created
    an empty ``b:Sources`` bibliography store).

    Mutates `parts` and returns the names restored. Three coordinated
    edits are what makes it a function rather than a note in a paper's
    log: the parts, the content-type Override, and a Relationship on an
    id that is FREE in the target — `rId7` in the source is somebody
    else's relationship here, and Word opens a duplicated id with a
    repair warning.

    A part already present is left exactly as it is: the target's copy
    is the newer one, and this is a rescue, not a sync.

    This does not fight :func:`strip_parts` above it. Stripping the data
    store is a DECISION a paper makes before it submits; carrying it
    across a rebuild is the build declining to make that decision on the
    paper's behalf, in a step nobody asked for and nothing reports.
    """
    missing = sorted(n for n in source
                     if any(n.startswith(p) for p in prefixes)
                     and n not in parts)
    if not missing:
        return []
    for name in missing:
        parts[name] = source[name]

    if _CONTENT_TYPES in parts and _CONTENT_TYPES in source:
        types = parts[_CONTENT_TYPES].decode("utf-8")
        src = source[_CONTENT_TYPES].decode("utf-8")
        add = [m.group(0) for name in missing
               if f'PartName="/{name}"' not in types
               and (m := re.search(
                   rf'<Override PartName="/{re.escape(name)}"[^>]*/>', src))]
        if add:
            at = types.rindex("</Types>")
            parts[_CONTENT_TYPES] = (types[:at] + "".join(add)
                                     + types[at:]).encode("utf-8")

    if _DOC_RELS in parts and _DOC_RELS in source:
        rels = parts[_DOC_RELS].decode("utf-8")
        for m in re.finditer(r"<Relationship\b[^>]*/>",
                             source[_DOC_RELS].decode("utf-8")):
            target = _TARGET_RE.search(m.group(0))
            if target is None:
                continue
            name = target.group(1).removeprefix("../")
            if not any(name.startswith(p) for p in prefixes):
                continue
            if f'Target="{target.group(1)}"' in rels:
                continue                       # already pointing at it
            was = _ID_RE.search(m.group(0))
            rid = _free_rid(rels, f"rId{was.group(1)}" if was else "")
            entry = re.sub(r'\bId="[^"]*"', f'Id="{rid}"', m.group(0))
            at = rels.rindex("</Relationships>")
            rels = rels[:at] + entry + rels[at:]
        parts[_DOC_RELS] = rels.encode("utf-8")
    return missing


def carry_properties(parts: dict[str, bytes], source: dict[str, bytes],
                     tags: tuple[str, ...] = CARRIED_PROPERTIES) -> list[str]:
    """Copy what a document says about ITSELF across a rebuild.

    :func:`restore_parts` one level down. Word's Compare regenerates
    ``docProps/core.xml`` holding only ``lastModifiedBy``, ``revision``,
    ``created`` and ``modified`` — so the part is present, the part-level
    check is satisfied, and ``dc:title``, ``dc:creator``, ``dc:subject``
    and ``cp:keywords`` are gone. LI7's title was set on 2026-08-08 in a
    batch of its own, because Word, Explorer and PDF export were all
    falling back on the filename; it was missing again by 2026-08-11 and
    nobody saw it for four days. Metadata is not tracked-changeable, so
    there is no revision to reject and no text, link or format layer that
    looks at ``docProps`` — only a carry or a warning can catch it.

    Copying the PART wholesale is what this deliberately does not do:
    ``core.xml``'s ``modified`` and ``revision`` belong to the file being
    written, and a redline stamped with its source's save time is a
    worse defect than an untitled one. Hence field by field, and only
    the fields in :data:`CARRIED_PROPERTIES`.

    A value already present is left alone — the target's is the newer
    one, and this is a rescue, not a sync. The part is REBUILT if it is
    missing entirely (Flat OPC carries no ``docProps`` at all), with its
    content-type override and a package relationship on a free id.

    Mutates `parts`; returns the tags carried.
    """
    wanted = {tag: value for tag in tags
              if (value := core_property(source, tag))
              and not core_property(parts, tag)}
    if not wanted:
        return []

    if CORE_PART not in parts:
        parts[CORE_PART] = _EMPTY_CORE.encode("utf-8")
        if _CONTENT_TYPES in parts:
            types = parts[_CONTENT_TYPES].decode("utf-8")
            if f'PartName="/{CORE_PART}"' not in types:
                at = types.rindex("</Types>")
                parts[_CONTENT_TYPES] = (types[:at] + _CORE_CT
                                         + types[at:]).encode("utf-8")
        if _PKG_RELS in parts:
            rels = parts[_PKG_RELS].decode("utf-8")
            if f'Target="{CORE_PART}"' not in rels:
                entry = (f'<Relationship Id="{_free_rid(rels, "")}" '
                         f'Type="{_CORE_REL_TYPE}" Target="{CORE_PART}"/>')
                at = rels.rindex("</Relationships>")
                parts[_PKG_RELS] = (rels[:at] + entry
                                    + rels[at:]).encode("utf-8")

    return [tag for tag, value in wanted.items()
            if set_core_property(parts, tag, value)]


# ------------------------------------------------------------- smarten ------

# w:t ONLY: m:t is mathematics, where a straight quote is a prime and
# "fixing" it corrupts the formula; w:delText is someone's tracked
# deletion, not ours to retypeset; w:instrText is field code.
_WT_RE = T_PARTS_RE                    # the shared definition


@dataclass
class SpacingReport:
    """What :func:`table_spacing` set, and what it deliberately did not."""

    spaced: list[str] = field(default_factory=list)     # got `before`
    notes: list[str] = field(default_factory=list)      # corrected to 0
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
    # `m is not None`, not `bool(m)`: only the former narrows the Optional
    # away for a type checker, and the gate went red on the difference.
    return m is not None and m.group(1).lower().startswith("heading")


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


def _declared_before(para_xml: str) -> int | None:
    """The paragraph's OWN `w:before`, or None when it inherits one."""
    m = re.search(r'<w:spacing\b[^>]*w:before="(\d+)"', para_xml)
    return int(m.group(1)) if m else None


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
      it is skipped, and pinned to `note_before` (0) only when it declares
      a space of its own that disagrees — a note that INHERITS is left to
      inherit, because Word deletes a declaration equal to the inherited
      value the next time it saves, and a rule that cannot survive a save
      is an audit that can never come back clean;
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
                # Only an explicit, WRONG value is corrected. A note that
                # declares nothing inherits, and writing an explicit 0 on
                # top of an inherited 0 is a change Word deletes on its
                # next save — which it did, on all eleven of DSI's notes,
                # so the audit came back with the same eleven every run.
                declared = _declared_before(para)
                changed = False
                if declared is not None and declared != note_before:
                    para, changed = _set_before(para, note_before)
                    out = out[:m.start()] + para + out[m.end():]
                    report.notes.append(text[:48])
                pos = m.start() + len(para)
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
