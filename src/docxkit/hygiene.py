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
import posixpath
import re
from dataclasses import dataclass, field

from ._xml import (
    COMMENTS,
    DOCUMENT,
    PARA_RE,
    T_PARTS_RE,
    element_spans,
    escape,
    live_properties,
    own_properties,
    set_para_property,
    text_parts,
    visible_text,
)
from ._xml import (
    append_before_close as _append_before_close,
)
from .errors import PackageError
from .package import CORE_PART, core_property, set_core_property

__all__ = [
    "CARRIED_PROPERTIES",
    "CUSTOM_XML",
    "MATH_DOWNGRADES",
    "NOTE_LEADS",
    "PackageError",
    "SmartenReport",
    "SpacingReport",
    "carry_properties",
    "dedupe_comments",
    "keep_tracking",
    "restore_math_glyphs",
    "restore_parts",
    "smarten",
    "smarten_parts",
    "strip_parts",
    "table_spacing",
]

CUSTOM_XML = "customXml/"
_CONTENT_TYPES = "[Content_Types].xml"
_DOC_RELS = "word/_rels/document.xml.rels"
_PKG_RELS = "_rels/.rels"
_ID_RE = re.compile(r'\bId="rId(\d+)"')
_TARGET_RE = re.compile(r'\bTarget="([^"]+)"')
#: The two part kinds a section references BY NAME as well as by
#: relationship, so restoring the part is only half of putting one back.
_HDR_FTR_RE = re.compile(r"^word/(?:header|footer)\d+\.xml$")
_SECT_REF_RE = re.compile(r"<w:(?:header|footer)Reference\b[^>]*/>")

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
        if _CONTENT_TYPES in parts:
            quoted = re.escape(prefix)
            xml = parts[_CONTENT_TYPES].decode("utf-8")
            xml = re.sub(rf'<Override PartName="/{quoted}[^"]*"[^>]*/>',
                         "", xml)
            parts[_CONTENT_TYPES] = xml.encode("utf-8")

    # EVERY rels part, and the Target RESOLVED rather than pattern
    # matched — the same rule `restore_parts` states, since this is its
    # mirror. A footer's relationship is in
    # `word/_rels/document.xml.rels`, but `docProps/custom.xml`'s is in
    # the PACKAGE rels and a data store's is in its own. Patching the
    # document's alone left `<Relationship Target="docProps/custom.xml"/>`
    # in `_rels/.rels` pointing at a part that is no longer in the
    # package, which is what Word reports as unreadable content — and
    # `docProps/custom.xml` is half of `tracked.CARRIED_PARTS`, so it is
    # the ordinary case rather than a contrived one.
    #
    # Resolving beats matching the text: a Target is relative to the
    # folder of the part its rels file describes, so one part is written
    # `docProps/custom.xml` from the package rels and
    # `../docProps/custom.xml` from `word/`, and a prefix test on the
    # raw string has to guess which spelling to expect.
    stripped = set(dropped)

    def _unwire(m: re.Match[str]) -> str:
        entry = m.group(0)
        target = _TARGET_RE.search(entry)
        if _external(entry) or target is None:
            return entry
        return "" if _resolve(name, target.group(1)) in stripped else entry

    for name in [n for n in parts if _is_rels(n)]:
        xml = parts[name].decode("utf-8")
        fixed = re.sub(r"<Relationship\b[^>]*/>", _unwire, xml)
        if fixed != xml:
            parts[name] = fixed.encode("utf-8")
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

    Mutates `parts` and returns the names restored. Four coordinated
    edits are what makes it a function rather than a note in a paper's
    log: the parts, the content-type Override, a Relationship on an id
    that is FREE in the target — `rId7` in the source is somebody else's
    relationship here, and Word opens a duplicated id with a repair
    warning — and, for a header or a footer, the reference in the
    SECTION properties that actually puts it on the page.

    It works on any part, not the data store alone. A footer's Target is
    ``footer3.xml`` — relative to the folder of the part its rels file
    describes — while the part is ``word/footer3.xml``, so reading the
    Target as a part name matched ``customXml/`` (written ``../``) and
    nothing under ``word/``: the file came back referenced by nothing,
    which Word ignores, and the parts gate went green because the file
    was present (Aging_Well R1, 2026-08-21). Raises
    :class:`docxkit.errors.PackageError` rather than reporting a part
    restored when it could not be wired back up.

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
            parts[_CONTENT_TYPES] = _append_before_close(
                types, "</Types>", "".join(add)).encode("utf-8")

    # EVERY rels part, not the document's alone: a footer's relationship
    # is in `word/_rels/document.xml.rels`, but `docProps/custom.xml`'s
    # is in the PACKAGE rels and `customXml/itemProps1.xml`'s is in the
    # data store's own. A rels part that came across in `missing` is
    # already the source's, byte for byte, and must not be added to.
    rid_for: dict[str, str] = {}
    for rels_name in sorted(n for n in source if _is_rels(n)):
        if rels_name in missing or rels_name not in parts:
            continue
        rels = parts[rels_name].decode("utf-8")
        for m in re.finditer(r"<Relationship\b[^>]*/>",
                             source[rels_name].decode("utf-8")):
            target = _TARGET_RE.search(m.group(0))
            if target is None or _external(m.group(0)):
                continue
            name = _resolve(rels_name, target.group(1))
            if name not in missing:
                continue
            if (held := _rid_for(rels, rels_name, name)) is not None:
                rid_for[name] = held           # already pointing at it
                continue
            was = _ID_RE.search(m.group(0))
            rid = _free_rid(rels, f"rId{was.group(1)}" if was else "")
            entry = re.sub(r'\bId="[^"]*"', f'Id="{rid}"', m.group(0))
            rels = _append_before_close(
                rels, "</Relationships>", entry)
            rid_for[name] = rid
        parts[rels_name] = rels.encode("utf-8")

    _restore_section_references(parts, source, missing, rid_for)

    # A restored part nothing REFERENCES is a part Word ignores — the
    # same outcome as the loss, now invisible to every parts gate
    # because the file is present. So it is refused rather than counted
    # as restored: this used to return the footer it had left
    # unreferenced, and `validate` went green on a manuscript whose
    # first-page footer was gone from the page (Aging_Well R1).
    #
    # Measured against the SOURCE, not against nothing: a part the
    # source does not reference either is being put back exactly as it
    # was, which is this function's whole contract. Requiring a
    # reference outright refuses a package that carries an unreferenced
    # part of its own — and every fixture that models a data store
    # without its `customXml/_rels/item1.xml.rels`. Nor is a target that
    # HAS no such rels part a dropped reference: a fragment assembled in
    # memory carries no relationship machinery at all, and this rescue
    # has to stay safe to attempt on one.
    held_by, now = _references(source), _references(parts)
    orphans = {n for n in missing
               if not _is_rels(n) and held_by.get(n) in parts
               and n not in now}
    orphans |= {n for n in missing if _HDR_FTR_RE.match(n)
                and _section_bound(source, n) and not _section_bound(parts, n)}
    if orphans:
        raise PackageError(
            "restored but referenced by nothing: " + ", ".join(sorted(orphans))
            + " — the part is in the package and Word will ignore it, which "
              "is the loss again with the parts gate now green. A header or "
              "footer also needs its reference in the section properties, "
              "and its section has to still be there to take it.")
    return missing


def _is_rels(name: str) -> bool:
    return name.startswith("_rels/") or "/_rels/" in name


def _external(entry: str) -> bool:
    """A relationship to a URL, which names no part of this package."""
    return 'TargetMode="External"' in entry


def _resolve(rels_name: str, target: str) -> str:
    """A relationship Target read as a PART NAME.

    A Target is relative to the folder of the part its rels file
    describes, which is the parent of the ``_rels`` folder it sits in:
    ``word/_rels/document.xml.rels`` resolves ``footer3.xml`` to
    ``word/footer3.xml`` and ``../customXml/item1.xml`` to
    ``customXml/item1.xml``.

    Reading the Target as a part name with ``../`` stripped answered the
    second form and only the second form, so every part under ``word/``
    — footers, headers, a lost ``footnotes.xml`` — sat in a hole where
    :func:`restore_parts` copied the file back and matched no
    relationship at all (Aging_Well R1, 2026-08-21).
    """
    # The SEPARATOR first. A Target may legally be written with
    # backslashes — some writers emit them on Windows — and
    # `_compare_read` normalises them while this did not, so one package
    # was read two ways: `compare` matched the relationship and every
    # `hygiene` operation that restores or strips a part did not.
    # Nothing here has been seen to write that spelling; what earns the
    # change is that two readers of one format had drifted apart.
    base = posixpath.dirname(posixpath.dirname(rels_name))
    flat = target.replace(chr(92), "/")
    return posixpath.normpath(posixpath.join(base, flat)).lstrip("/")


def _rid_for(rels_xml: str, rels_name: str, part: str) -> str | None:
    """The id of the relationship pointing at `part`, if there is one."""
    for m in re.finditer(r"<Relationship\b[^>]*/>", rels_xml):
        target = _TARGET_RE.search(m.group(0))
        rid = re.search(r'\bId="([^"]*)"', m.group(0))
        if (target is not None and rid is not None
                and not _external(m.group(0))
                and _resolve(rels_name, target.group(1)) == part):
            return rid.group(1)
    return None


def _references(parts: dict[str, bytes]) -> dict[str, str]:
    """Each part some relationship points at -> the rels part holding it."""
    hit: dict[str, str] = {}
    for name, blob in parts.items():
        if not _is_rels(name):
            continue
        for m in re.finditer(r"<Relationship\b[^>]*/>",
                             blob.decode("utf-8", "replace")):
            target = _TARGET_RE.search(m.group(0))
            if target is not None and not _external(m.group(0)):
                hit.setdefault(_resolve(name, target.group(1)), name)
    return hit


def _section_bound(pkg: dict[str, bytes], part: str) -> bool:
    """Does the document's ``sectPr`` reach this header or footer?

    The relationship is not the whole reference. A footer with a
    relationship and no ``<w:footerReference>`` in the section
    properties is a part on disk that no page shows.
    """
    rid = _rid_for(pkg.get(_DOC_RELS, b"").decode("utf-8", "replace"),
                   _DOC_RELS, part)
    if rid is None:
        return False
    doc = pkg.get(DOCUMENT, b"").decode("utf-8", "replace")
    return re.search(rf'<w:(?:header|footer)Reference\b[^>]*'
                     rf'r:id="{re.escape(rid)}"', doc) is not None


#: Both spellings of a section. `element_spans` deliberately skips a
#: SELF-CLOSING element — an empty `<w:p/>` is a paragraph with no
#: content and not the start of one — and for `w:sectPr` that skip is
#: silent data loss: a section with every property left at its default
#: is written `<w:sectPr/>`, is a section, and simply does not appear in
#: the list. Pairing source to target BY POSITION across two lists that
#: count differently is how a footer ends up wired to the wrong section,
#: with the reference present, the orphan check satisfied, and the build
#: reporting the part carried across.
_SECTPR_OPEN = re.compile(r"<w:sectPr\b[^>]*>")
_SECTPR_CLOSE = "</w:sectPr>"


def _section_spans(xml: str) -> list[tuple[int, int]]:
    """Every `w:sectPr`, empty ones included, in document order.

    The open tag is matched first and the two forms told apart after,
    because an alternation cannot do it: in
    `<w:sectPr\b[^>]*(?:/>|>.*?</w:sectPr>)` the character class is
    happy to eat the closing SLASH, so `/>` fails, the second branch
    matches the `>` that is left, and one span runs from an empty
    section to the END of the next one. Written that way first, and it
    put the restored reference outside the section entirely.
    """
    out = []
    for m in _SECTPR_OPEN.finditer(xml):
        if m.group(0).endswith("/>"):
            out.append((m.start(), m.end()))
            continue
        shut = xml.find(_SECTPR_CLOSE, m.end())
        if shut == -1:                      # malformed; not ours to repair
            continue
        out.append((m.start(), shut + len(_SECTPR_CLOSE)))
    return out


def _restore_section_references(parts: dict[str, bytes],
                                source: dict[str, bytes],
                                missing: list[str],
                                rid_for: dict[str, str]) -> None:
    """Put a restored header's or footer's ``sectPr`` reference back.

    Restoring the part and its relationship is not enough for these two:
    a footer reaches the page through a ``<w:footerReference>`` in the
    SECTION properties, and Compare drops that alongside the part.
    Nothing else can put it back — a rescue that leaves the file in the
    package and the reference out of the sectPr looks exactly like a
    success and prints exactly like one.

    The type (default / even / first) is recoverable, because the source
    document's own sectPr still says it. Sections are paired by
    POSITION, which is the only pairing available: a sectPr carries no
    name. A target with fewer sections than the source is left alone and
    the part is reported orphaned by the caller.
    """
    doc = DOCUMENT
    if doc not in parts or doc not in source:
        return
    want = [n for n in missing if _HDR_FTR_RE.match(n) and n in rid_for]
    if not want:
        return
    src, out = source[doc].decode("utf-8"), parts[doc].decode("utf-8")
    src_rels = source.get(_DOC_RELS, b"").decode("utf-8")
    src_sects = _section_spans(src)
    # Newest first, so an earlier section's insertion cannot move a later
    # section's offsets out from under the next edit.
    inserts: list[tuple[int, int, str]] = []
    for name in want:
        rid = _rid_for(src_rels, _DOC_RELS, name)
        if rid is None:
            continue
        for m in re.finditer(
                rf'<w:(header|footer)Reference\b[^>]*r:id="{rid}"[^>]*/>',
                src):
            kind = m.group(1)
            at = next((i for i, (lo, hi) in enumerate(src_sects)
                       if lo <= m.start() < hi), None)
            sects = _section_spans(out)
            if at is None or at >= len(sects):
                continue
            type_m = re.search(r'w:type="([^"]*)"', m.group(0))
            kind_type = f' w:type="{type_m.group(1)}"' if type_m else ""
            lo, hi = sects[at]
            block = out[lo:hi]
            entry = (f'<w:{kind}Reference{kind_type} '
                     f'r:id="{rid_for[name]}"/>')
            if block.endswith("/>"):
                # An EMPTY section, which has no inside to insert into:
                # it is opened up around the reference. `<w:sectPr/>` and
                # `<w:sectPr></w:sectPr>` are the same section, and a
                # reference has to go in one as readily as the other.
                inserts.append((hi - 2, hi, f">{entry}</w:sectPr>"))
                continue
            last = None
            for r in _SECT_REF_RE.finditer(block):
                last = r
            opens = re.match(r"<w:sectPr\b[^>]*>", block)
            assert opens is not None
            at_in = lo + (last.end() if last else opens.end())
            inserts.append((at_in, at_in, entry))
    # Newest first, so an earlier edit cannot move a later one's offsets.
    for lo, hi, entry in sorted(inserts, reverse=True):
        out = out[:lo] + entry + out[hi:]
    parts[doc] = out.encode("utf-8")


#: The element Word actually READS for Track Changes. Not the schema's
#: `w:trackChanges`: writing that leaves Word reporting Track Changes
#: OFF, with no error and no complaint about an unknown element —
#: measured twice, in two sessions. In `CT_Settings` order it sits after
#: `w:revisionView` and before `w:defaultTabStop`.
_TRACK = "<w:trackRevisions/>"
_SETTINGS = "word/settings.xml"
#: `CT_Settings` is a SEQUENCE, and Word refuses a settings part whose
#: children are out of order — so the position is decided by both
#: neighbours, not by a handful of elements to sit after.
#:
#: The old list had four entries and one of them was on the wrong side:
#: `w:documentProtection` FOLLOWS `w:trackChanges` in the sequence, so
#: "insert after it" put the element out of order in the commonest
#: shape there is. It also named none of `proofState`,
#: `attachedTemplate` or `mailMerge`, so a settings part carrying those
#: and nothing from the list got `w:trackRevisions` inserted FIRST,
#: ahead of them. Measured on all four shapes: only a lone
#: `w:revisionView` — the case the test pinned — came out right.
_BEFORE_TRACK = (
    "writeProtection", "view", "zoom", "removePersonalInformation",
    "removeDateAndTime", "doNotDisplayPageBoundaries",
    "displayBackgroundShape", "printPostScriptOverText",
    "printFractionalCharacterWidth", "printFormsData",
    "embedTrueTypeFonts", "embedSystemFonts", "saveSubsetFonts",
    "saveFormsData", "mirrorMargins", "alignBordersAndEdges",
    "bordersDoNotSurroundHeader", "bordersDoNotSurroundFooter",
    "gutterAtTop", "hideSpellingErrors", "hideGrammaticalErrors",
    "activeWritingStyle", "proofState", "formsDesign", "attachedTemplate",
    "linkStyles", "stylePaneFormatFilter", "stylePaneSortMethod",
    "documentType", "mailMerge", "revisionView",
)
_AFTER_TRACK = (
    "doNotTrackMoves", "doNotTrackFormatting", "documentProtection",
    "autoFormatOverride", "styleLockTheme", "styleLockQFSet",
    "defaultTabStop", "autoHyphenation", "consecutiveHyphenLimit",
    "hyphenationZone", "doNotHyphenateCaps", "showEnvelope",
    "summaryLength", "clickAndTypeStyle", "defaultTableStyle",
    "evenAndOddHeaders", "bookFoldRevPrinting", "bookFoldPrinting",
    "bookFoldPrintingSheets", "drawingGridHorizontalSpacing",
    "drawingGridVerticalSpacing", "displayHorizontalDrawingGridEvery",
    "displayVerticalDrawingGridEvery", "characterSpacingControl",
    "noPunctuationKerning", "printTwoOnOne", "strictFirstAndLastChars",
    "savePreviewPicture", "doNotValidateAgainstSchema",
    "saveInvalidXml", "ignoreMixedContent", "alwaysShowPlaceholderText",
    "doNotDemarcateInvalidXml", "saveXmlDataOnly", "useXSLTWhenSaving",
    "showXMLTags", "alwaysMergeEmptyNamespace", "updateFields",
    "footnotePr", "endnotePr", "compat", "docVars", "rsids",
    "attachedSchema", "themeFontLang", "clrSchemeMapping",
    "doNotIncludeSubdocsInStats", "doNotAutoCompressPictures",
    "forceUpgrade", "captions", "readModeInkLockDown", "smartTagType",
    "shapeDefaults", "doNotEmbedSmartTags", "decimalSymbol",
    "listSeparator",
)


def keep_tracking(parts: dict[str, bytes], source: dict[str, bytes]) -> bool:
    """Carry `<w:trackRevisions/>` across a Compare that dropped it.

    Word's Compare writes a fresh `settings.xml`, so a batch that turned
    Track Changes ON — because the paper had never set it and the
    author's own typing was therefore not being recorded — hands back a
    manuscript with it OFF again. The author then edits a "tracked"
    document and nothing is tracked, which is the quietest way to lose
    an author round: their edits arrive as ordinary text and the next
    reject-all cannot separate them.

    True when it had to put the element back. `source` is the document
    whose setting is being preserved — the baseline the redline was
    built from.
    """
    if _TRACK in parts.get(_SETTINGS, b"").decode("utf-8", "replace"):
        return False
    if _TRACK not in source.get(_SETTINGS, b"").decode("utf-8", "replace"):
        return False
    xml = parts.get(_SETTINGS, b"").decode("utf-8", "replace")
    if not xml:
        return False
    # After the elements that precede it in CT_Settings, or first in the
    # body if none of them is there. Order is not decoration: Word
    # refuses a settings part whose children are out of sequence.
    opened = re.search(r"<w:settings\b[^>]*>", xml)
    if opened is None:
        return False
    shut = xml.rfind("</w:settings>")
    body = (opened.end(), shut if shut != -1 else len(xml))

    # After everything that PRECEDES it and before anything that
    # FOLLOWS. Either bound alone gets it wrong: a part with only
    # followers takes the element first, and a part with only
    # predecessors takes it last, and both are what real settings look
    # like.
    after = max([body[0]] + [xml.index(">", at) + 1
                             for tag in _BEFORE_TRACK
                             if (at := xml.find(f"<w:{tag}")) != -1])
    before = min([body[1]] + [at for tag in _AFTER_TRACK
                              if (at := xml.find(f"<w:{tag}")) != -1])
    # A document whose own children are already out of sequence is not
    # this function's to repair; the follower wins, because inserting
    # after one is the arrangement Word refuses.
    at = min(after, before)
    parts[_SETTINGS] = (xml[:at] + _TRACK + xml[at:]).encode("utf-8")
    return True


def dedupe_comments(parts: dict[str, bytes]) -> list[str]:
    """Drop a comment that says the same thing twice, and say which.

    Compare does not MERGE a comment present in both inputs: the
    baseline has the author's note because they wrote it, the clean
    master has it because an earlier round restored one Compare had
    dropped, and the redline hands the author their own note duplicated
    on the same table with no way to tell which copy to resolve (Word
    confirms `Comments.Count = 2`). Neither input is wrong, which is why
    this belongs to the build.

    Matched on **author plus whitespace-collapsed text**. Never on id,
    which Compare renumbers; never on anchor, since the two copies land
    on different runs of one paragraph.

    **The dropped copy's ANCHORS go with it**, from every text-bearing
    part: `commentRangeStart`, `commentRangeEnd`, and the whole run
    holding `commentReference` — the run, because a bare `<w:r>` left
    with only its `rPr` renders as nothing and is a second kind of
    litter. A reference pointing at a comment that no longer exists is
    what Word calls "the file appears to be corrupted", and it refuses
    the WHOLE document (found on Health Capacity to Work, 2026-08-24,
    bisected to the commit that wired this into `tracked.build`).

    That half was missing from the port. The paper script this
    generalises has a `strip()` beside its `duplicates()`, and only
    `duplicates()` came across — so the function was correct about the
    part it edited and silent about the one that breaks.

    The `commentsExtended` / `commentsIds` / `commentsExtensible`
    entries for the dropped copy are left orphaned, and that is safe:
    they key off paragraph ids, and Word opens, counts and threads the
    survivor correctly. Verified in Word rather than assumed — and worth
    saying plainly that the verification covered those three satellite
    parts and never looked at `document.xml`. A claim of Word
    verification sitting above a defect is worse than no claim.
    """
    xml = parts.get(COMMENTS, b"").decode("utf-8", "replace")
    if not xml:
        return []
    dropped: list[str] = []
    gone: list[str] = []
    seen: set[tuple[str, str]] = set()
    out, at = [], 0
    # `(?<!/)>` — the guard PARA_RE and RUN_RE both carry, for the same
    # reason. CT_Comment's block content is optional, so an EMPTY
    # comment is written `<w:comment w:id="2" w:author="A"/>` and
    # without the guard one match opens on it and closes on the NEXT
    # comment's `</w:comment>`. That match then carries two comments'
    # text and one of their ids: the pair reads as a duplicate, both
    # definitions are cut, and `gone` collects only the id it found —
    # so the OTHER comment's anchors stay in the body pointing at a
    # definition that no longer exists. A dangling `commentReference`
    # is what Word calls "unreadable content", which is the failure
    # this function's anchor sweep was added to prevent, arriving
    # through a different door.
    for m in re.finditer(r"<w:comment\b[^>]*(?<!/)>.*?</w:comment>",
                         xml, re.DOTALL):
        author = re.search(r'w:author="([^"]*)"', m.group(0))
        # Through `visible_text`, not a bare `w:t` scrape: one copy
        # written by the author's Word and one restored by an earlier
        # round from another writer differ in ESCAPING — `&quot;`
        # against a literal `"` — and two spellings of one note are the
        # duplicate this exists to find, not two notes.
        text = visible_text(m.group(0)).split()
        key = (author.group(1) if author else "", " ".join(text))
        if key in seen and key[1]:
            dropped.append(f"{key[0]}: {key[1][:60]}")
            if cid := re.search(r'w:id="(\d+)"', m.group(0)):
                gone.append(cid.group(1))
            out.append(xml[at:m.start()])
            at = m.end()
            continue
        seen.add(key)
    if not dropped:
        return []
    out.append(xml[at:])
    parts[COMMENTS] = "".join(out).encode("utf-8")
    _drop_comment_anchors(parts, gone)
    return dropped


def _drop_comment_anchors(parts: dict[str, bytes], ids: list[str]) -> None:
    """Remove every anchor for `ids` from the text-bearing parts.

    Three things per id, and the third is a RUN rather than an element:
    the reference sits inside a run of its own, and deleting only the
    `<w:commentReference/>` leaves a `<w:r>` carrying nothing but its
    `rPr`, which renders as nothing and is litter of a second kind.

    Every text part, not `document.xml`: a comment can be anchored in a
    footnote, and an endnote is where several journals put the whole
    apparatus.
    """
    if not ids:
        return
    # ONE pass over each part for ALL the ids. The loops used to nest
    # the other way round, so N duplicate comments meant N decodes of
    # every text part and 2N runs of the tempered-lookahead pattern
    # below, which is the costliest regex in this module. Measured at
    # 71 ms for forty ids on a small body — nobody was waiting on it.
    # What earns the change is that the shape invites being copied.
    which = "|".join(re.escape(cid) for cid in ids)
    anchor = re.compile(rf'<w:commentRange(?:Start|End) w:id="(?:{which})"/>')
    reference = re.compile(
        rf"<w:r(?: [^>]*)?>(?:(?!</w:r>).)*?"
        rf'<w:commentReference w:id="(?:{which})"/>'
        rf"(?:(?!</w:r>).)*?</w:r>", re.DOTALL)
    for name, xml in text_parts(parts):
        fixed = reference.sub("", anchor.sub("", xml))
        if fixed != xml:
            parts[name] = fixed.encode("utf-8")


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
                parts[_CONTENT_TYPES] = _append_before_close(
                    types, "</Types>", _CORE_CT).encode("utf-8")
        if _PKG_RELS in parts:
            rels = parts[_PKG_RELS].decode("utf-8")
            if f'Target="{CORE_PART}"' not in rels:
                entry = (f'<Relationship Id="{_free_rid(rels, "")}" '
                         f'Type="{_CORE_REL_TYPE}" Target="{CORE_PART}"/>')
                parts[_PKG_RELS] = _append_before_close(
                    rels, "</Relationships>", entry).encode("utf-8")

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
    """Is this paragraph styled as a heading — NOW.

    Through `_live_ppr`, for the reason `_declared_before` states twenty
    lines below: a `w:pPrChange` snapshot records the properties a
    tracked change REPLACED, and reading it answers for the past. This
    one searched the whole paragraph, so a change that turned a Heading2
    into body text left its only `w:pStyle` inside the snapshot and the
    paragraph still read as a heading.

    It is not a cosmetic misreading. `table_spacing` treats a heading as
    "has its own spacing" and BREAKS — so the paragraph that really does
    resume after the table gets no space, and the whole table is
    abandoned with a skip line about a heading nobody can see.
    """
    m = re.search(r'<w:pStyle w:val="([^"]+)"', _live_ppr(para_xml))
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
    """The paragraph's OWN `w:before`, or None when it inherits one.

    LIVE properties only: a `w:pPrChange` snapshot records the spacing a
    tracked change REPLACED, and reading it answers for the past.
    """
    m = re.search(r'<w:spacing\b[^>]*w:before="(\d+)"', _live_ppr(para_xml))
    return int(m.group(1)) if m else None


def _live_ppr(para_xml: str) -> str:
    """The paragraph's own properties, minus the tracked-change snapshot."""
    own = own_properties(para_xml, "pPr")
    return live_properties(own[2]) if own is not None else ""


#: The paragraph MARK's run properties. CT_PPr's own `w:rPr` is a
#: CT_ParaRPr, and CT_ParaRPr has a `w:spacing` of its own — CHARACTER
#: spacing, in a different unit, about the pilcrow. It is not the
#: paragraph's spacing and must not be read as it.
_MARK_RPR_RE = re.compile(r"<w:rPr\b[^>]*(?<!/)>.*?</w:rPr>", re.DOTALL)
_SPACING_OPEN_RE = re.compile(r"<w:spacing\b[^>]*>")


def _own_spacing(para_xml: str) -> str | None:
    """The paragraph's own `w:spacing`, as a self-closing tag.

    Two ways the plain search for `<w:spacing\b[^>]*/>` over the whole
    `pPr` got this wrong, and each one damaged the paragraph.

    TOO BROAD: it reached inside the paragraph mark's `w:rPr` and found
    the character spacing there. `_set_before` then carried that tag's
    attributes up, and wrote `<w:spacing w:before="120" w:val="20"/>` as
    a direct child of `pPr` — `w:val` is not a CT_Spacing attribute, so
    a schema-invalid element, on a paragraph that had declared no
    spacing at all.

    TOO NARROW: `<w:spacing w:after="0" w:line="240"></w:spacing>` is
    legal and did not match, so the branch that KEEPS the paragraph's
    other attributes was skipped and a bare `<w:spacing w:before="120"/>`
    replaced it — `w:after` and `w:line` gone, which is the exact loss
    the element is built here to prevent.

    CT_Spacing has no child elements, so the long form is the short one
    with a closing tag and normalising it loses nothing.
    """
    m = _SPACING_OPEN_RE.search(_MARK_RPR_RE.sub("", _live_ppr(para_xml)))
    if m is None:
        return None
    tag = m.group(0)
    return tag if tag.endswith("/>") else tag[:-1] + "/>"


def _set_before(para_xml: str, twentieths: int) -> tuple[str, bool]:
    """Set `w:spacing/@w:before` on a paragraph, inserting pPr if need be.

    The PLACEMENT is `_xml.set_para_property`'s; what stays here is the
    element itself, because a `w:spacing` tag carries `w:after` and
    `w:line` beside the value being set and those are the paragraph's
    own.
    """
    tag = _own_spacing(para_xml)
    if tag is not None:
        if re.search(rf'w:before="{twentieths}"', tag):
            return para_xml, False
        stripped = re.sub(r'\s*w:before="[^"]*"', "", tag)
        spacing = stripped.replace(
            "<w:spacing", f'<w:spacing w:before="{twentieths}"', 1)
    else:
        spacing = f'<w:spacing w:before="{twentieths}"/>'
    out = set_para_property(para_xml, "spacing", spacing)
    return out, out != para_xml


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
    # Reversed, so that every edit lands AFTER the table still to be
    # looked at and positions taken from `xml` stay good in `out`.
    spans = element_spans(xml, "tbl")
    for i, (start, end) in reversed(list(enumerate(spans))):
        tbl = xml[start:end]
        if _is_equation_carrier(tbl):
            report.skipped.append(
                f"equation {visible_text(tbl)[-8:].strip()}: a carrier, "
                f"not a table")
            continue
        # The walk stops at the NEXT table, because a table is not text
        # that resumes after the one above it. Unbounded, the search
        # steps over an empty spacer — correctly, it is not the text
        # that resumes — and finds the first paragraph of the next
        # table's first CELL, writing 6pt above a header row and
        # reporting it as a paragraph spaced. Two tables with a spacer
        # between them is what a paper that stacks its exhibits at the
        # end looks like, which is this house style.
        #
        # `element_spans` gives the outermost table only, so the next
        # span is always a sibling and its start is the true boundary.
        limit = spans[i + 1][0] if i + 1 < len(spans) else len(xml)
        pos = end
        while True:
            m = PARA_RE.search(out, pos)
            if m is None or m.start() >= limit:
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
                # `_set_before`'s second answer is not read here: this
                # branch ends in `continue`, and a note that was already
                # at `note_before` is skipped by the guard above rather
                # than by the flag. Assigned and never read, it carried a
                # mutant nothing could kill (2026-08-20).
                if declared is not None and declared != note_before:
                    para, _ = _set_before(para, note_before)
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


def smarten_parts(parts: dict[str, bytes]) -> SmartenReport:
    """:func:`smarten`, over every part a reader sees. Mutates `parts`.

    `_xml.TEXT_PARTS` states the rule this exists for: an operation that
    describes the DOCUMENT is wrong if it stops at the body. `smarten`
    takes one part's XML — every other chore in this module takes the
    package — so its only caller smartened `word/document.xml` and left
    the footnotes alone. An economics manuscript keeps a large share of
    its prose in footnotes, so the phantom diffs this exists to end
    survived in exactly the part nobody re-reads.

    One report for the package, with an unbalanced paragraph labelled by
    the part it is in: "the quotes are odd somewhere" is not an
    actionable sentence when the somewhere could be four files.
    """
    total = SmartenReport()
    for name, xml in text_parts(parts):
        fixed, report = smarten(xml)
        total.apostrophes += report.apostrophes
        total.quotes += report.quotes
        total.ambiguous += report.ambiguous
        where = name.removeprefix("word/").removesuffix(".xml")
        total.unbalanced += [snippet if where == "document"
                             else f"{where}: {snippet}"
                             for snippet in report.unbalanced]
        if fixed != xml:
            parts[name] = fixed.encode("utf-8")
    return total


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

#: What a Word round-trip downgrades inside OMML, and what it becomes.
#: MINUS SIGN is the one that keeps happening: this toolchain writes
#: U+2212 in generated maths (it is the character a minus IS, and it
#: sets with the right width beside a digit), Word's Compare rewrites
#: the OMML while deriving a redline, and the character comes back as
#: an ASCII hyphen. Measured on AFI 2026-08-17: 2 in the baseline, 0 in
#: the built batch, 57 in the PROSE of both — only maths is rewritten.
#:
#: PRIME is the second, found on Aging_Well 2026-08-23: Word's accept
#: path returns U+2032 as an ASCII apostrophe, so a paper writing
#: `\kappa'(a)` or `f'(x)` could not build at all until someone worked
#: out that the derivative was the problem. Loud rather than silent —
#: the build refuses instead of shipping the wrong glyph, which is the
#: gate working — but a refusal nobody can act on costs the same
#: afternoon as a wrong answer.
#: Glyphs Word's Compare/accept round-trip flattens inside `m:t`, and what
#: it flattens each one TO. Every entry was measured on a manuscript, not
#: guessed: U+2212 and U+2032 on LE and LI, then U+1D71A and U+2113 on
#: Aging_Well 2026-08-26, where a `\varrho` discount rate and an `\ell`
#: instrument index came back as their plain cousins in ten and five
#: equations and `tracked.build` refused the batch on gate 4.
MATH_DOWNGRADES = {"−": "-", "′": "'", "𝜚": "ϱ", "ℓ": "l"}

_MATH_T_RE = re.compile(r"(<m:t[^>]*>)([^<]*)(</m:t>)")


def _downgraded(text: str) -> str:
    for glyph, plain in MATH_DOWNGRADES.items():
        text = text.replace(glyph, plain)
    return text


def _as_utf8(blob: bytes) -> str | None:
    """The part as text, or None when it is not UTF-8 at all.

    NOT `errors="replace"`, which is what the read-only scanners in this
    module use. This one WRITES BACK, and a lossy decode re-encoded is
    silent corruption: every undecodable byte returns as U+FFFD. A part
    that cannot be read as UTF-8 is not a part this function can act on,
    so it is left byte for byte alone.

    Bare `.decode("utf-8")` was the third option and the worst of them.
    A `customXml/` data store written by another tool in UTF-16 is legal
    and is carried by `restore_parts` — which `tracked.build` calls
    before this — so one third-party store killed the whole build with a
    UnicodeDecodeError, after Word's Compare had already run.
    """
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return None


def restore_math_glyphs(parts: dict[str, bytes],
                        *sources: dict[str, bytes]) -> list[str]:
    """Put back math glyphs a Word round-trip flattened, per ``m:t``.

    `sources` are the documents this one was DERIVED from — for a
    redline, the original and the clean edit — and they are the
    statement of intent: if the text a run should hold is spelled with
    U+2212 there and with a hyphen here, Word did that, not an author.

    Conservative on purpose, because the two are indistinguishable
    character by character:

    * a run is only repaired when its exact text appears in a source
      with a downgraded glyph put back, so nothing is inferred from
      context;
    * an ambiguous key is dropped — if two source runs share a
      downgraded form and disagree about the glyphs, neither is used,
      since a hyphen inside maths is a legitimate character (a range, a
      variable name) and guessing would rewrite the author's;
    * prose is never touched: only ``m:t``, which is what the
      round-trip rewrites.

    Mutates `parts`; returns one line per run repaired.
    """
    # EVERY source run, not only the ones carrying a glyph: a source
    # that spells this run with a plain hyphen is exactly the evidence
    # that says "leave it alone", and collecting only the glyph-bearing
    # ones would make that vote invisible.
    intent: dict[str, set[str]] = {}
    for source in sources:
        for name, blob in source.items():
            if not name.endswith(".xml"):
                continue
            if (src_text := _as_utf8(blob)) is None:
                continue
            for m in _MATH_T_RE.finditer(src_text):
                text = m.group(2)
                intent.setdefault(_downgraded(text), set()).add(text)
    wanted = {plain: next(iter(texts)) for plain, texts in intent.items()
              if len(texts) == 1 and next(iter(texts)) != plain}
    if not wanted:
        return []

    restored: list[str] = []
    for name, blob in list(parts.items()):
        if not name.endswith(".xml"):
            continue
        if (text := _as_utf8(blob)) is None:
            continue

        def fix(m: re.Match[str], part: str = name) -> str:
            # `back == m.group(2)` was a second guard here and could not
            # fire: `wanted` is keyed on the DOWNGRADED form and drops
            # every entry whose value equals its key, so a hit is always
            # a change. Four mutants were living inside it (2026-08-19).
            back = wanted.get(m.group(2))
            if back is None:
                return m.group(0)
            restored.append(f"{part}: {m.group(2)!r} -> {back!r}")
            return m.group(1) + back + m.group(3)

        out = _MATH_T_RE.sub(fix, text)
        if out != text:
            parts[name] = out.encode("utf-8")
    return restored
