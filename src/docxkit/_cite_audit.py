"""The link AUDIT: what is wrong with a document's citations.

Reports, never repairs. Every check is deliberately conservative —
MISPLACED MARKER only speaks when a key resolves to exactly one entry —
because a false positive in an audit costs more than a missed one: it
sends a human hunting for a defect that was never there.
"""
from __future__ import annotations

import html
import re
from collections import defaultdict
from typing import NamedTuple

from ._cite_grammar import (
    _DEFAULT_HEADINGS,
    IGNORED_LEADS,
    Reference,
    find_citations,
    references,
    resolve_lead,
)
from ._xml import (
    BOOKMARK_NAME_RE,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    PARA_RE,
    dead_links,
    internal_links,
    visible_text,
)

# ------------------------------------------------------ the link audit ---

#: kept as a name because `docxkit.citations` re-exports it and the
#: papers' scripts import it from that path
_BOOKMARK_NAME_RE = BOOKMARK_NAME_RE
# The optional _N is :func:`_dedup_name`'s collision suffix. Without it a
# deduped entry bookmark (minted when a STALE bookmark held the plain
# name) was invisible to the own-name scan, so every link_all run minted
# another _N and re-wrapped the citation — the Parental Style Kazenin
# spiral, nested four links deep before the audit caught it.
#: Where a bookmark or link was found, when it was not in a body
#: paragraph. Negative on purpose: everything from 0 up is a paragraph
#: index, and these have to sort before the first of them.
_NOTE_AT = {FOOTNOTES: -2, ENDNOTES: -3}
#: The same, as a reader sees it. "body" is a body-LEVEL definition
#: between paragraphs: the first audit round printed those as "fn" and
#: the API repair went hunting in footnotes.xml for bookmarks that were
#: never there.
_WHERE = {-1: "body", -2: "fn", -3: "en"}

_KEY_SHAPE_RE = re.compile(
    r"^([A-Za-z][A-Za-z.]*?)(\d{4}[a-z]?)(?:_\d+)?(?:txt)?$")
_LINK_TOKEN_RE = re.compile(
    r'<w:fldChar\b[^>]*w:fldCharType="(begin|separate|end)"'
    r"|<w:instrText[^>]*>([^<]*)</w:instrText>"
    # (?<!/)> — a SELF-CLOSING <w:hyperlink .../> wraps nothing, so it
    # must not open a frame here: it would never be popped, and every
    # later link in the paragraph would be reported as nested inside it.
    # Word leaves these ghosts behind on save; one on the Parental Style
    # manuscript is what made the twin guard in _xml necessary.
    r'|<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*(?<!/)>'
    r"|</w:hyperlink>")


def _doubled_links(para_xml: str) -> list[tuple[str, str]]:
    """(outer, inner) target pairs where one link nests inside another
    WITH A DIFFERENT TARGET — the click goes to the outer one.

    Two real shapes: a field starting inside another field's result
    (API10 P30: "Finsel et al. 2023; Wöhrmann et al. 2018" rendered as
    ONE link because the first field never ends), and an element link
    inside a field's result (the WHO-2019 back-link nested inside a
    dead absolute-URL field Word had written around it). Same-target
    nesting is form churn caught mid-flight and stays quiet.
    """
    out: list[tuple[str, str]] = []
    stack: list[list[str]] = []      # open links: [kind, target-or-""]

    def newly_known(inner: str) -> None:
        for _kind, target in stack:
            if target and target != inner:
                out.append((target, inner))

    for m in _LINK_TOKEN_RE.finditer(para_xml):
        fld, instr, el_anchor = m.group(1), m.group(2), m.group(3)
        if fld == "begin":
            stack.append(["field", ""])
        elif fld == "end":
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == "field":
                    del stack[i]
                    break
        elif instr is not None and "HYPERLINK" in instr:
            am = re.search(r'HYPERLINK\s+(?:\\l\s+)?"([^"]+)"',
                           html.unescape(instr))
            target = am.group(1) if am else instr.strip()
            open_fields = [f for f in stack if f[0] == "field"]
            if open_fields:
                newly_known(target)
                open_fields[-1][1] = target
        elif el_anchor is not None:
            inner = html.unescape(el_anchor)
            newly_known(inner)
            stack.append(["element", inner])
        elif fld is None and instr is None and el_anchor is None:
            for i in range(len(stack) - 1, -1, -1):   # </w:hyperlink>
                if stack[i][0] == "element":
                    del stack[i]
                    break
    return out


def _marker_owner(name: str, entries: list[Reference]) -> Reference | None:
    """The entry a key-shaped bookmark names, when exactly one answers.

    Conservative on purpose, and shared by the two checks that need it —
    MISPLACED MARKER, which asks WHERE the marker sits, and the UNLINKED
    scan, which asks whether a work is linked at all. A name that does
    not parse as surname+year, or that fits two entries, belongs to
    neither check: silence beats a guess, and a second copy of this rule
    is how the two would drift apart.
    """
    km = _KEY_SHAPE_RE.match(name)
    if km is None:
        return None
    alpha, year = km.group(1).casefold(), km.group(2)
    owners = [r for r in entries
              if re.sub(r"[^\w]", "", r.surname).casefold().startswith(alpha)
              and r.year == year]
    return owners[0] if len(owners) == 1 else None


class _Finding(NamedTuple):
    """One audit finding, structured: repair_plan classifies on `kind`
    and `subject` instead of re-parsing its own audit's message strings
    — the coupling that made the first plan writer fragile."""

    kind: str          # "BROKEN LINK", "ORPHAN REF", ...
    subject: str       # the bookmark / anchor / citation concerned
    message: str       # the full rendered line, "KIND: ..."
    extra: str = ""    # DOUBLED LINK carries the OUTER target here


def audit_links(parts: dict[str, bytes], *,
                heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
                ignore: frozenset[str] | set[str] = IGNORED_LEADS,
                ) -> tuple[list[str], dict[str, int]]:
    """Audit the bidirectional citation-link convention; (issues, stats).
    The rendered-string face of :func:`_audit_findings`.

    The papers' bookmark shape: the reference entry carries ``<name>``
    and the in-text mention ``<name>txt`` (``Halliday2020`` /
    ``Halliday2020txt``), each end hyperlinking to the other; figure and
    table first-mention links follow the same shape, so they audit
    identically. Documents built on :func:`anchor_names`'s
    ``cite_``/``ref_`` naming still get the orphan, broken-link and
    cross-reference checks — only the ``txt``-pairing checks are
    specific to the suffix shape.

    Anchors resolve against EVERY bookmark in the document — including
    Word's own ``_Toc``/``_Heading`` names. The audit this replaces
    excluded underscore names from its index and then reported links to
    them as broken; LE le15 shipped an audit round with nine of those
    false positives before the cause was found.
    """
    findings, stats = _audit_findings(parts, heading=heading, ignore=ignore)
    return [f.message for f in findings], stats


def _read_notes(parts: dict[str, bytes], bookmarks: dict[str, int],
                links: dict[str, list[tuple[int, str]]],
                empty: list[tuple[str, int]]) -> None:
    """Fold both note stores into the body's own bookmarks and links.

    Which store a mention sits in is part of the answer: an anchor
    reported as "fn" that lives in endnotes.xml sends a repair looking
    in a part that does not hold it. Until 2026-08-20 the audit read
    footnotes.xml alone, so a paper whose journal takes endnotes had its
    whole apparatus reported as absent — links 1 -> 0, bookmarks 1 -> 0
    — which reads as a document with nothing to fix.
    """
    for part, at in _NOTE_AT.items():
        blob = parts.get(part)
        if not blob:
            continue
        text = blob.decode("utf-8")
        for name in _BOOKMARK_NAME_RE.findall(text):
            bookmarks.setdefault(name, at)
        for anchor, label in internal_links(text):
            links[anchor].append((at, label))
        empty += [(a, at) for a in dead_links(text)]


def _audit_findings(parts: dict[str, bytes], *,
                    heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
                    ignore: frozenset[str] | set[str] = IGNORED_LEADS,
                    ) -> tuple[list[_Finding], dict[str, int]]:
    doc = parts[DOCUMENT].decode("utf-8")
    paras = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in paras]

    bookmarks: dict[str, int] = {}          # first definition wins
    links: dict[str, list[tuple[int, str]]] = defaultdict(list)
    empty: list[tuple[str, int]] = []       # (anchor, where) — label lost
    for i, m in enumerate(paras):
        for name in _BOOKMARK_NAME_RE.findall(m.group(0)):
            bookmarks.setdefault(name, i)
        for anchor, label in internal_links(m.group(0)):
            links[anchor].append((i, label))
        empty += [(a, i) for a in dead_links(m.group(0))]
    for name in _BOOKMARK_NAME_RE.findall(doc):
        bookmarks.setdefault(name, -1)      # BODY-LEVEL, between paragraphs
    _read_notes(parts, bookmarks, links, empty)

    cite_marks = {n: i for n, i in bookmarks.items()
                  if not n.startswith("_") and n.endswith("txt")}
    eq_marks = {n: i for n, i in bookmarks.items()
                if not n.startswith("_") and n.startswith("Eq")}
    ref_marks = {n: i for n, i in bookmarks.items()
                 if not n.startswith("_") and n not in cite_marks
                 and n not in eq_marks}

    def where(i: int) -> str:
        return _WHERE.get(i) or f"¶{i + 1}"

    entry_years = {r.year[:4] for r in references(texts, heading=heading)}

    def names_a_missing_entry(name: str) -> bool:
        """Does this key-shaped bookmark name a work the list no longer has?

        A reference marker outlives its entry: delete the paragraph in Word and
        the bookmark is hoisted to body level rather than removed, so the audit
        went on reporting a work that is not in the document — as an UNCITED
        REFERENCE, which sent a reader looking for an entry that was not there.

        Matched on the YEAR alone, deliberately. The alpha part is minted from
        the surname and a Cyrillic or hand-placed name shares none of it
        (`MFA2026`), so requiring it to match would call live entries stale.
        A year no entry carries is evidence enough, and costs no false report.
        """
        if not entry_years:
            return False      # no list parsed — nothing to be missing FROM
        m = _KEY_SHAPE_RE.fullmatch(name)
        if m is None:
            return False              # not key-shaped: not ours to judge
        return m.group(2)[:4] not in entry_years

    issues: list[_Finding] = []
    for key, idx in sorted(ref_marks.items(), key=lambda kv: kv[1]):
        if names_a_missing_entry(key):
            issues.append(_Finding(
                "STALE BOOKMARK", key,
                f"STALE BOOKMARK: '{key}' ({where(idx)}) names a work that is "
                "no longer in the reference list — the entry was deleted and "
                "the marker stayed; remove the bookmark"))
            continue
        if not links.get(key):
            issues.append(_Finding(
                "ORPHAN REF", key,
                f"ORPHAN REF: bookmark '{key}' ({where(idx)}) "
                "has no in-text hyperlink pointing to it"))
    for name, idx in sorted(cite_marks.items(), key=lambda kv: kv[1]):
        if not links.get(name):
            issues.append(_Finding(
                "NO BACK-LINK", name,
                f"NO BACK-LINK: in-text bookmark '{name}' "
                f"({where(idx)}) has no reference back-link"))
        if name[:-3] not in ref_marks:
            issues.append(_Finding(
                "MISSING REF", name,
                f"MISSING REF: in-text citation '{name}' "
                f"({where(idx)}) links to '{name[:-3]}' but no "
                "reference bookmark exists"))
    # A link that shows nothing. Reported here rather than in `lint`
    # because the file is not malformed — Word opens it happily — and
    # `write_docx` must not start refusing documents over it.
    for anchor, spot in empty:
        issues.append(_Finding(
            "EMPTY LINK", anchor,
            f"EMPTY LINK: hyperlink to '{anchor}' ({where(spot)}) shows no "
            "text — nothing on the page carries this link; the mention it "
            "wrapped is plain text now, or gone"))
    broken = 0
    for anchor, sites in sorted(links.items()):
        if anchor not in bookmarks:
            for i, label in sites:
                issues.append(_Finding(
                    "BROKEN LINK", anchor,
                    f"BROKEN LINK: hyperlink to '{anchor}' "
                    f'({where(i)}, "{label[:40]}") '
                    "— no such bookmark"))
                broken += 1
    for i, m in enumerate(paras):
        for outer, inner in _doubled_links(m.group(0)):
            issues.append(_Finding(
                "DOUBLED LINK", inner, extra=outer,
                message=f"DOUBLED LINK: '{inner}' is nested inside a "
                f"link to '{outer}' (¶{i + 1}) — the click goes "
                "to the outer one"))

    # A marker that no longer sits at its own entry: paragraph moves take
    # the <w:p> and nothing beside it, so a reorder strands body-level
    # markers one entry off (13 of them on API10). Only CONFIDENT
    # mismatches report: the key must parse as name+year and match
    # exactly one entry by surname prefix and year.
    entries = references(texts, heading=heading)
    if entries:
        starts = {r.index: r for r in entries}
        for name in ref_marks:
            owner = _marker_owner(name, entries)
            if owner is None:
                continue
            pos = doc.find(f'w:name="{name}"')
            at = next((r for i, r in starts.items()
                       if paras[i].start() <= pos < paras[i].end()), None)
            if at is None:                    # body-level: next entry down
                at = next((starts[i] for i in sorted(starts)
                           if paras[i].start() >= pos), None)
            if at is not None and at.index != owner.index:
                issues.append(_Finding(
                    "MISPLACED MARKER", name,
                    f"MISPLACED MARKER: '{name}' sits at "
                    f"¶{at.index + 1} (\"{at.text[:30]}\") but its entry "
                    f"is ¶{owner.index + 1}"))

    # Unlinked citation-like text, on the shared grammar. Only body
    # prose before the reference list; the first five paragraphs are the
    # title block, where author names read as citations.
    wanted = {h.casefold()
              for h in ((heading,) if isinstance(heading, str) else heading)}
    head_idx = next((i for i, t in enumerate(texts)
                     if t.strip().rstrip(":").casefold() in wanted),
                    len(texts))
    ignored = {s.casefold() for s in ignore}
    # What the bibliography files, for resolve_lead's evidence test. The
    # alias keys _entry_keys mints live one layer up, in _cite_build; the
    # canonical keys are what this decision needs.
    entry_keys = {r.key for r in entries}
    labels = {lb.strip() for sites in links.values() for _, lb in sites}
    # The convention links a work's FIRST mention only, so the question
    # this check asks is "is this WORK linked anywhere", and it must be
    # asked of the work — not of the wording. Pairing on the label text
    # alone read "Doepke and Zilibotti's (2017)" as unlinked while the
    # entry was linked from two other paragraphs, because no label
    # carries the possessive (Parental Style ¶92, 2026-08-10): a false
    # positive that cost a hand-written link_in_para in the paper's
    # repair script. Measured over 397 real manuscripts, 38 of the 44
    # findings this quiets are one shape — a link whose label stops a
    # character short of the citation, "Davletov et al. (2016" and
    # "Angrist and Evans (1998", because the closing parenthesis sits in
    # a run outside the hyperlink. Those mentions ARE linked.
    #
    # The evidence must be visible in the FINAL document: a link inside
    # deleted text is not a link. Its label comes back empty (a deleted
    # run holds `w:delText`, which no visible-text reader returns), and
    # requiring a non-empty one is what keeps le12's finding — the
    # author retyped the sentence, which dropped the hyperlink, while
    # the tracked deletion beside it still carried the old one.
    #
    # The label test stays as the fallback for a document whose
    # bookmarks are not key-shaped — anchor_names' cite_/ref_ naming, or
    # a work cited with no entry to resolve against.
    linked_works = {owner.key for name in ref_marks
                    if any(lb.strip() for _, lb in links.get(name, ()))
                    for owner in (_marker_owner(name, entries),)
                    if owner is not None}
    unlinked = 0
    for i, text in enumerate(texts[:head_idx]):
        if i < 5:
            continue
        for found in find_citations(text):
            c = resolve_lead(found, known=entry_keys)
            if c.surname.casefold() in ignored:
                continue
            if c.key in linked_works:
                continue
            cite = text[c.start:c.end].strip()
            cores = (f"{c.authors} {c.year}", f"{c.authors} ({c.year})")
            if any(cite in lb or cores[0] in lb or cores[1] in lb
                   for lb in labels):
                continue
            issues.append(_Finding(
                "UNLINKED", cite,
                f'UNLINKED: "{cite}" (¶{i + 1}) — looks like a '
                "citation but is not hyperlinked"))
            unlinked += 1

    cited_keys = {n[:-3] for n in cite_marks}
    cited_keys |= {a for a in links if a in ref_marks}
    for key in sorted(cited_keys - ref_marks.keys()):
        issues.append(_Finding(
            "CITE WITHOUT REF", key,
            f"CITE WITHOUT REF: '{key}' cited in text but no "
            "reference bookmark"))
    for key in sorted(ref_marks.keys() - cited_keys):
        if names_a_missing_entry(key):
            continue          # already reported, and more usefully, as stale
        issues.append(_Finding(
            "REF WITHOUT CITE", key,
            f"REF WITHOUT CITE: '{key}' "
            f"({where(ref_marks[key])}) in references but never "
            "cited in text"))

    stats = {"paragraphs": len(paras), "bookmarks": len(bookmarks),
             "cite_bookmarks": len(cite_marks),
             "ref_bookmarks": len(ref_marks), "eq_bookmarks": len(eq_marks),
             "links": sum(len(v) for v in links.values()),
             "broken": broken, "empty": len(empty), "unlinked": unlinked}
    return issues, stats


