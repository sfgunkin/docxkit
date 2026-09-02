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
from collections.abc import Callable
from typing import NamedTuple

from ._cite_grammar import (
    _DEFAULT_HEADINGS,
    IGNORED_LEADS,
    Reference,
    find_citations,
    masked_visible_text,
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
# One word of a bookmark name, for :func:`_name_runs`. A name separates
# its words with punctuation ("ref_world_bank_2024"), with case
# ("refWorldBank2024"), or with the digits of the year — all three, and
# an acronym run ("WHOReport") splits before the capitalised word that
# follows it rather than inside it.
_NAME_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|[0-9]+")
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


def _reached(doc: str, paras: list[re.Match[str]],
             links: dict[str, list[tuple[int, str]]]) -> set[str]:
    """Bookmarks at a PLACE some link arrives at — its own or a neighbour's.

    "Nothing points at this bookmark" and "the reader arrives nowhere"
    are different statements, and the audit was making the second from
    the first. Word's own cross-reference — Insert ▸ Cross-reference —
    mints its OWN anchor at the caption (`_Ref211944524`) and points a
    `REF` field at that, so the house bookmark beside it is targeted by
    nothing while the mention lands exactly where it should.

    Measured on HCW (2026-08-22): four captions, each carrying its
    `_Ref…` anchor and its `TableN` immediately beside it, the `_Ref…`
    one linked in every case. `citations` called all four "the mention
    reaches nothing" while `crossrefs` called all twenty exhibits
    linked — one tool said broken, the other said fine, and the repair
    the finding implied would have traded Word's automatic renumbering
    for a static label.

    A PLACE is the paragraph a bookmark sits in, or — for a marker Word
    has hoisted out of one — the gap it was hoisted into.

    **Only WORD'S OWN anchor confers reach**, and that restriction is the
    whole check. Word reserves the leading underscore for the bookmarks
    it mints itself — `_Ref`, `_Toc`, `_Hlk` — so one of those beside a
    house bookmark is the same destination under two names. Two ordinary
    markers sharing a gap are NOT: li7 hoists `Kotze2022` and
    `Luhmann2016` into one, and a click on a Kotze citation says nothing
    about whether anything reaches Luhmann's entry. Clearing that would
    have been the same class of wrong answer, in the other direction.
    """
    place: dict[int, list[str]] = defaultdict(list)
    for m in re.finditer(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', doc):
        at = m.start()
        i = next((n for n, p in enumerate(paras) if p.start() <= at < p.end()),
                 None)
        if i is None:                      # hoisted: it belongs to the NEXT
            # `len(paras)` for a marker past the LAST paragraph: it is
            # the gap after the end, and it needs a key of its own.
            # Folding it onto -1 put it in the same place as the gap
            # BEFORE the first paragraph, so a linked `_Ref` hoisted
            # above the opening line cleared a bookmark at the far end
            # of the document — suppressing both findings that say so,
            # which is the wrong answer this function exists to avoid.
            i = next((n for n, p in enumerate(paras) if p.start() > at),
                     len(paras))
            i = -1 - i                     # a gap key, distinct from a para
        place[i].append(m.group(1))
    return {name for names in place.values()
            if any(n.startswith("_") and links.get(n) for n in names)
            for name in names}


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
    if km is not None:
        alpha, year = km.group(1).casefold(), km.group(2)
        owners = [r for r in entries
                  if re.sub(r"[^\w]", "", r.surname).casefold()
                  .startswith(alpha) and r.year == year]
        return owners[0] if len(owners) == 1 else None
    return _foreign_owner(name, entries)


def _name_runs(name: str) -> set[str]:
    """Every WORD-ALIGNED run of letters in a bookmark name, folded.

    "ref_world_bank_2024" yields {ref, refworld, refworldbank, world,
    worldbank, bank} — the joins are what lets a multi-word institution
    ("World Bank") answer to a name that separates its words, and the
    alignment is what stops a surname matching in the middle of another.

    That middle is not hypothetical. Both readers of a foreign scheme
    used to ask whether the surname sat ANYWHERE in the folded name, so
    "Ho, B. (2019)" adopted a stray `ref_thompson_2019` ("ho" is inside
    "refthompson") and "Li, X. (2020)" adopted `ref_polinelli_2020`.
    The builder then wired every mention of the short-surnamed work to
    another work's bookmark and reported success; the audit cleared it
    as linked. Every surname of two or three letters — Li, Ho, An, Xu,
    Ng, Wu — is one long name away from this.

    A run must be alphabetic and unbroken by digits, so the year cannot
    be joined across. A name with no boundary at all ("refthompson2019",
    all one word) matches nothing here but the whole run: that is the
    conservative half of the same rule — "refthompson" is a surname a
    document could genuinely be filing under, and silence beats a guess.
    """
    runs: set[str] = set()
    words: list[str] = []
    for w in _NAME_WORD_RE.findall(name):
        if w.isdigit():
            words = []               # the year breaks the run, not joins it
            continue
        words.append(w.casefold())
        runs.update("".join(words[i:]) for i in range(len(words)))
    return runs


def _foreign_owner(name: str, entries: list[Reference]) -> Reference | None:
    """The entry a bookmark of SOMEBODY ELSE'S scheme names.

    A manuscript wired as ``ref_<surname>_<year>`` has no key-shaped
    marker anywhere, so every work read as unlinked and this audit
    reported an UNLINKED citation for each one it could not clear
    another way — on AFI, "Surveys and ILOSTAT (2024)" and "Gmyrek et
    al.'s (2025)", both of them linked, and both reported on the
    finished manuscript (2026-08-21).

    Read the way `_cite_build._foreign_bookmark` reads it, because it is
    the same question from the other end: fold the name to letters and
    digits, and accept it when the fold ENDS with an entry's year and
    one of its WORDS is that entry's surname. The word test is
    :func:`_name_runs` and both ends call it: "holds the surname" was
    written out twice, and the same defect was in both copies. Two
    entries answering is still nobody's marker — silence beats a guess,
    as above.
    """
    flat = re.sub(r"[^0-9A-Za-z]", "", name).casefold()
    runs = _name_runs(name)
    owners = []
    for r in entries:
        if not flat.endswith(r.year):
            continue
        stem = re.sub(r"[^\w]", "", r.surname).casefold()
        if stem and stem in runs:
            owners.append(r)
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
                later_mentions: bool = False,
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

    ``stats`` counts MENTIONS as well as works — ``mentions``,
    ``mentions_linked``, ``later_unlinked`` — because "is any reference
    orphaned" and "is the apparatus finished" are different questions
    and one number cannot answer both: after ``link_all`` this audit
    reported nothing while 20 of a paper's 73 mentions were plain text
    (Aging_Well). ``later_mentions=True`` turns the plain ones into
    LATER-MENTION UNLINKED findings; it is off by default because
    whether later mentions link at all is the paper's house style.
    """
    findings, stats = _audit_findings(parts, heading=heading, ignore=ignore,
                                      later_mentions=later_mentions)
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


def _misplaced_markers(doc: str, paras: list[re.Match[str]],
                       entries: list[Reference],
                       ref_marks: dict[str, int]) -> list[_Finding]:
    """Entry markers that no longer sit at their own entry."""
    # A marker that no longer sits at its own entry: paragraph moves take
    # the <w:p> and nothing beside it, so a reorder strands body-level
    # markers one entry off (13 of them on API10). Only CONFIDENT
    # mismatches report: the key must parse as name+year and match
    # exactly one entry by surname prefix and year.
    if not entries:
        return []
    found: list[_Finding] = []
    starts = {r.index: r for r in entries}
    # Where the reference block begins. A marker sitting in PROSE is
    # the mention-side half of the pair — `<key>txt` in this
    # package's own scheme, `cite_<surname>_<year>` in a paper's —
    # and it belongs where it is. Reading it as an entry's marker
    # reported six of AFI's as misplaced, every one of them
    # correctly placed at the mention it back-links (2026-08-21).
    # The gap ABOVE the first entry is the first entry's — that is
    # where Word puts a marker it hoists out of the paragraph head —
    # so the block starts at the end of whatever precedes it.
    first = min(starts)
    block_from = paras[first - 1].end() if first else 0
    for name in ref_marks:
        owner = _marker_owner(name, entries)
        if owner is None:
            continue
        pos = doc.find(f'w:name="{name}"')
        if pos < block_from:
            continue
        at = next((r for i, r in starts.items()
                   if paras[i].start() <= pos < paras[i].end()), None)
        if at is None:                    # body-level: next entry down
            at = next((starts[i] for i in sorted(starts)
                       if paras[i].start() >= pos), None)
        if at is not None and at.index != owner.index:
            found.append(_Finding(
                "MISPLACED MARKER", name,
                f"MISPLACED MARKER: '{name}' sits at "
                f"¶{at.index + 1} (\"{at.text[:30]}\") but its entry "
                f"is ¶{owner.index + 1}"))

    return found


def unbalanced_span(label: str) -> str:
    """The bracket a link's label opens or closes and the other does not.

    A link SPAN is invisible to everything else. `citations` counts a
    link whose anchor resolves, `refstyle` does not look at spans,
    `compare`'s TEXT layer sees no character move because none moved,
    and `revision ingest` files it under RE-LABELLED — a section that
    exists to say "nothing is lost, do not block the baseline", which is
    right about the anchor and silent about the span.

    Bracket balance is the cheap, precise rule for the way spans really
    break. An author turns a narrative citation parenthetical —
    "Klimaviciute and Pestieau (2023)" becomes "(Klimaviciute and
    Pestieau 2023)" — and Word keeps the old right-hand boundary, so the
    link covers `Klimaviciute and Pestieau 2023)`: a closing bracket
    with no opening one inside the blue.

    Every house form closes what it opens — "Grossman (1972)",
    "de São José et al. (2019)", "Klimaviciute, A. and P. Pestieau.
    (2023)." — so this fires on the damage and not on the convention.
    Returns "" when the label is balanced.
    """
    depth = 0
    for ch in label:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return ")"
    return "(" if depth else ""


def _span_findings(links: dict[str, list[tuple[int, str]]],
                   bookmarks: dict[str, int],
                   where: Callable[[int], str]) -> list[_Finding]:
    """Links whose label does not close what it opens.

    A BROKEN one is reported elsewhere and reported first: an anchor
    that resolves nowhere is the bigger fact about the same link, and
    saying both would be two lines about one repair. So this asks only
    of links that are otherwise sound — where the anchor is fine and the
    blue is wrong.
    """
    out: list[_Finding] = []
    for anchor, sites in sorted(links.items()):
        if anchor not in bookmarks:
            continue
        for i, label in sites:
            if not (bracket := unbalanced_span(label)):
                continue
            out.append(_Finding(
                "UNBALANCED SPAN", anchor,
                f"UNBALANCED SPAN: the link to '{anchor}' "
                f'({where(i)}) covers "{label[:48]}" — an unmatched '
                f"'{bracket}', so the span has reached past its "
                f"mention; the anchor is fine and the blue is wrong"))
    return out


def _mention_scan(parts: dict[str, bytes], texts: list[str],
                  paras: list[re.Match[str]],
                  head_idx: int) -> list[tuple[int, str, str]]:
    """Every paragraph a citation can be MENTIONED in: `(where, text, xml)`.

    The body before the reference list, and then both note stores.

    Notes were missing here and nowhere else. `_read_notes` folds their
    bookmarks and links in, so a work cited only in a footnote resolved
    and reported correctly — but its MENTION was never in the
    denominator. Aging_Well, 2026-08-31: a round added "(World Bank
    2026)" to footnote 2 as plain text and `citations` printed
    `Mentions: 103 of 103 linked` before the link was made AND after.
    Six of that paper's works are cited only in footnotes.

    The first five paragraphs are skipped as the title block, which is
    the rule this inherits from the loop it was lifted out of.
    `_NOTE_AT`'s sentinel stands in for the index, so `where()` says
    "fn" or "en" rather than a paragraph number a reader would go
    hunting for in the body.
    """
    scan = [(i, text, paras[i].group(0))
            for i, text in enumerate(texts[:head_idx]) if i >= 5]
    for part, at in _NOTE_AT.items():
        blob = parts.get(part)
        if blob:
            scan += [(at, visible_text(m.group(0)), m.group(0))
                     for m in PARA_RE.finditer(blob.decode("utf-8"))]
    return scan


def _no_backlink(ref_marks: dict[str, int],
                 links: dict[str, list[tuple[int, str]]],
                 where: Callable[[int], str],
                 *, skip: Callable[[str], bool]) -> list[_Finding]:
    """Entries with NO link home, where the rest of the list has one.

    The convention is bidirectional — the mention links to the entry and
    the entry links home to the first mention — and the only half
    anything checked was a link pointing at a name that is not there
    (BROKEN LINK). Aging_Well, 2026-09-01: one entry of 87 lost its
    `Lokshin2022txt` bookmark, so its back-link WAS broken, and the
    paper's repair removed the dead link rather than restoring the
    target. That leaves an entry with nothing pointing home, which
    nothing could see — and the state is self-perpetuating, because
    `link_all` skips a mention that already carries a forward link, so
    the marker is never re-minted. The same warning printed at three
    consecutive close-outs while the gate exited 0.

    **Judged by the list's own MAJORITY rather than by a rule**, because
    whether entries link home at all is the paper's house style: one
    entry differing from 86 others is a finding, and 87 entries agreeing
    that they do not is a convention. `skip` drops the keys already
    reported more usefully elsewhere — an entry nobody cites has a
    reason to have no back-link.

    Measured over 100 manuscripts before it shipped: 2 findings in 1
    document, both real (two FLOPS entries whose `txt` markers exist
    nowhere in the file). The sibling rule this is closest to fired
    5,378 times across 718 of 1,873 manuscripts before it was narrowed,
    which is why an audit rule gets measured and not just argued.
    """
    home = {key: any(i == at for i, _ in links.get(key + "txt", ()))
            for key, at in ref_marks.items() if not skip(key)}
    linked = sum(home.values())
    if linked < max(3, (len(home) + 1) // 2):
        return []
    return [_Finding(
        "REF WITHOUT BACKLINK", key,
        f"REF WITHOUT BACKLINK: '{key}' ({where(ref_marks[key])}) is "
        f"cited, and its entry links to no '{key}txt' — the other "
        f"{linked} entries link home")
        for key in sorted(k for k, has in home.items() if not has)]


def _audit_findings(parts: dict[str, bytes], *,
                    heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
                    ignore: frozenset[str] | set[str] = IGNORED_LEADS,
                    later_mentions: bool = False,
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

    # Which works the text reaches, by either end. Computed HERE rather
    # than beside its own check below, because ORPHAN REF needs it too:
    # see the comment on that finding.
    cited_keys = {n[:-3] for n in cite_marks}
    cited_keys |= {a for a in links if a in ref_marks}
    # …and which PLACES a link arrives at, which is not the same
    # question. See :func:`_reached`.
    reached = _reached(doc, paras, links)
    unreached = cited_keys - reached

    issues: list[_Finding] = []
    for key, idx in sorted(ref_marks.items(), key=lambda kv: kv[1]):
        if names_a_missing_entry(key):
            issues.append(_Finding(
                "STALE BOOKMARK", key,
                f"STALE BOOKMARK: '{key}' ({where(idx)}) names a work that is "
                "no longer in the reference list — the entry was deleted and "
                "the marker stayed; remove the bookmark"))
            continue
        # ORPHAN REF and REF WITHOUT CITE were ONE FACT said twice, and
        # the redundancy is a theorem rather than a coincidence: a work
        # nothing links to is not in `cited_keys`, so every REF WITHOUT
        # CITE came with an ORPHAN REF beside it. Measured over five
        # manuscripts, `uncited-only` is 0 every time, and after a
        # `link_all` run li7 carried 20 such pairs, le14 16 and AFI's
        # baseline 5 — 41 lines saying nothing the line under them did
        # not (2026-08-21).
        #
        # So the pair collapses into the finding a reader can act on,
        # below, and what is left here is the case that is NOT the same
        # fact: the work IS cited — its `<key>txt` marker is in the
        # prose — and the hyperlink to the entry is gone, so the reader
        # clicking that citation arrives nowhere.
        if not links.get(key) and key in unreached:
            at = cite_marks.get(f"{key}txt")
            issues.append(_Finding(
                "ORPHAN REF", key,
                f"ORPHAN REF: bookmark '{key}' ({where(idx)}) has no in-text "
                f"hyperlink pointing to it, and the work IS cited"
                + (f" — '{key}txt' is at {where(at)}" if at is not None
                   else "") + ": the mention reaches nothing"))
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
    issues += _span_findings(links, bookmarks, where)
    for i, m in enumerate(paras):
        for outer, inner in _doubled_links(m.group(0)):
            issues.append(_Finding(
                "DOUBLED LINK", inner, extra=outer,
                message=f"DOUBLED LINK: '{inner}' is nested inside a "
                f"link to '{outer}' (¶{i + 1}) — the click goes "
                "to the outer one"))

    entries = references(texts, heading=heading)
    issues += _misplaced_markers(doc, paras, entries, ref_marks)

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
    # UNLINKED asks is "is this WORK linked anywhere", and it must be
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
    # The entries' own surnames, so the audit reads the same spans the
    # builder writes. Without them the audit counts a clipped mention as
    # a linked one — "82 of 82, 0 broken" over a link covering half a
    # name.
    surnames = tuple({r.surname for r in entries})
    unlinked = later = mentions = 0
    for i, text, para_xml in _mention_scan(parts, texts, paras, head_idx):
        masked = masked_visible_text(para_xml)
        for found in find_citations(text, surnames):
            c = resolve_lead(found, known=entry_keys, ignore=ignored)
            if c.surname.casefold() in ignored:
                continue
            mentions += 1
            # Is THIS MENTION linked — the question the work-level tests
            # below cannot ask. A character inside a hyperlink comes back
            # masked, which is the test `link_rest` uses to decide what
            # is left to wire, and it settles two shapes the label tests
            # were written for: a link whose label stops a character
            # short of the citation ("Davletov et al. (2016", the
            # closing parenthesis outside the hyperlink), and a LABEL
            # sitting inside the span of a match the two-author pattern
            # over-read ("…national Labor Force Surveys and ILOSTAT
            # (2024) data…", where the link is "ILOSTAT (2024)").
            if "\x00" in masked[c.start:c.end]:
                continue
            cite = text[c.start:c.end].strip()
            cores = (f"{c.authors} {c.year}", f"{c.authors} ({c.year})")
            if c.key in linked_works or any(
                    cite in lb or cores[0] in lb or cores[1] in lb
                    for lb in labels):
                # The WORK is linked somewhere and this mention is not.
                # `link_all` wires each work's first mention only, so a
                # paper whose style links the later ones too sat at "ALL
                # CHECKS PASSED" with 20 of its 73 mentions plain text
                # (Aging_Well, 2026-08-21) — the count could not tell the
                # middle state from the finished one. The count now does,
                # always; the FINDING is opt-in, because whether later
                # mentions link at all is the paper's house style and a
                # gate nobody can satisfy stops being read.
                later += 1
                if later_mentions:
                    issues.append(_Finding(
                        "LATER-MENTION UNLINKED", cite,
                        f'LATER-MENTION UNLINKED: "{cite}" ({where(i)}) '
                        "— the work is linked elsewhere but this "
                        "mention is plain text"))
                continue
            issues.append(_Finding(
                "UNLINKED", cite,
                f'UNLINKED: "{cite}" ({where(i)}) — looks like a '
                "citation but is not hyperlinked"))
            unlinked += 1

    for key in sorted(cited_keys - ref_marks.keys()):
        issues.append(_Finding(
            "CITE WITHOUT REF", key,
            f"CITE WITHOUT REF: '{key}' cited in text but no "
            "reference bookmark"))
    # Document order, like the loop this absorbed: the report is read top
    # to bottom against the manuscript. Sorted by NAME it still contains
    # everything and still reads as a list, which is why nothing noticed
    # the first time (2026-08-19) — and this is now the only line those
    # entries get, so the property has to come with it.
    # The NAME breaks the tie, and it has to: several reference markers
    # hoisted body-level into one gap share a position, a set supplies
    # the order among them, and PYTHONHASHSEED varies it per process.
    # li7 reported the same 29 findings in a different order run to run
    # (measured 2026-08-22), which is phantom churn in a report a reader
    # diffs between rounds.
    for key in sorted(ref_marks.keys() - cited_keys - reached,
                      key=lambda k: (ref_marks[k], k)):
        if names_a_missing_entry(key):
            continue          # already reported, and more usefully, as stale
        # This line carries what the ORPHAN REF beside it used to say as
        # well — no link points here AND no in-text marker names it —
        # because they were one fact, and this is the half a reader can
        # act on: a reference nobody cites is a decision about the
        # bibliography, while "the marker I just wrote has nobody
        # pointing at it" is a description of the marker.
        issues.append(_Finding(
            "REF WITHOUT CITE", key,
            f"REF WITHOUT CITE: '{key}' "
            f"({where(ref_marks[key])}) in references and nothing points "
            f"at it — no in-text hyperlink and no '{key}txt' marker"))

    # An entry with NO link home, where the rest of the list has one.
    #
    # The convention is bidirectional — the mention links to the entry
    # and the entry links home to the first mention — and the only half
    # anything checked was a link pointing at a name that is not there
    # (BROKEN LINK above). Aging_Well, 2026-09-01: one entry of 87 lost
    # its `Lokshin2022txt` bookmark, so the back-link WAS broken, and
    # the paper's repair removed the dead link rather than the target's
    # absence. That leaves an entry with nothing pointing home, which
    # nothing could see, and the state is self-perpetuating: `link_all`
    # skips a mention that already carries a forward link, so the marker
    # is never re-minted. The same warning printed at three consecutive
    # close-outs and the gate exited 0 each time.
    #
    # Judged by the list's own MAJORITY rather than by a rule, because
    # whether entries link home at all is the paper's house style: a
    # single entry differing from 86 others is a finding, and 87 entries
    # agreeing that they do not is a convention. Keys already reported
    # as uncited are left alone — an entry nobody cites has a reason to
    # have no back-link, and saying it twice is noise.
    uncited = ref_marks.keys() - cited_keys - reached
    issues += _no_backlink(
        ref_marks, links, where,
        skip=lambda k: k in uncited or names_a_missing_entry(k))

    stats = {"paragraphs": len(paras), "bookmarks": len(bookmarks),
             "cite_bookmarks": len(cite_marks),
             "ref_bookmarks": len(ref_marks), "eq_bookmarks": len(eq_marks),
             "links": sum(len(v) for v in links.values()),
             "broken": broken, "empty": len(empty), "unlinked": unlinked,
             "mentions": mentions, "later_unlinked": later,
             "mentions_linked": mentions - unlinked - later}
    return issues, stats


