"""The link BUILDER: making a document's citation apparatus.

`link_all` wires every first mention to its entry and back; `link_rest`
forward-links the later mentions; `unlink_by_anchor` tears a scheme out
so it can be rebuilt. All idempotent, so a build can run them every
round.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, replace

from ._cite_audit import _BOOKMARK_NAME_RE, _KEY_SHAPE_RE
from ._cite_grammar import (
    _DEFAULT_HEADINGS,
    _REF_YEAR_RE,
    IGNORED_LEADS,
    Reference,
    find_citations,
    key_for,
    link_in_para,
    masked_visible_text,
    references,
    strip_lead,
    wrap_visible_span,
)
from ._cite_repair import (
    _mark_para_head,
    _run_open_before,
    next_bookmark_id,
    wrap_link_in_bookmark,
)
from ._xml import (
    PARA_RE,
    RUN_RE,
    internal_links,
    visible_text,
)
from .errors import AnchorError

# --------------------------------------------------- the link BUILDER ---

_HEAD_RE = re.compile(r"\s*(.*?\(?\b\d{4}[a-z]?\)?)[.,]")


_ACRONYM_RE = re.compile(r"\(([A-Z]{2,})\)")


def _own_bookmark(para_xml: str, r: Reference) -> str | None:
    """The entry's OWN key-shaped bookmark, or None.

    Both the year and the surname must match. Matching on the year
    alone reuses whatever key-shaped bookmark happens to sit on the
    paragraph — a stray `Jones2020` left by an earlier round on a
    "Smith, A. (2020)" entry made link_all wire every "(Smith 2020)" in
    the text to the WRONG work, and report "linked 1" while doing it.
    """
    alpha = re.sub(r"[^0-9A-Za-z]", "", r.surname).casefold()
    names: list[str] = _BOOKMARK_NAME_RE.findall(para_xml)
    for n in names:
        km = _KEY_SHAPE_RE.match(n)
        if km is None or n.endswith("txt") or km.group(2) != r.year:
            continue
        # the bookmark's alpha part is the surname, possibly truncated
        # (an acronym entry files under it) — one must prefix the other
        got = km.group(1).casefold()
        if alpha.startswith(got) or got.startswith(alpha):
            return n
    return None


def _entry_keys(r: Reference) -> set[str]:
    """Every citation key this entry can answer to.

    Beyond the canonical key, an entry licenses (found on LE le15 and
    API10):

    - the acronym it names itself by — "Health Promotion Board (HPB).
      (2023)." is what "(HPB 2023)" cites;
    - its all-caps lead token — "UNDP (United Nations Development
      Programme). (2025)." files under the acronym itself;
    - its own initialism — "United Nations, Department of..." is cited
      "(UN 2024)" and "World Health Organization" "(WHO 2015)"; the
      reader connects those without a map, so the audit must too;
    - every word RUN of a multi-word institutional name, because the
      citation grammar refuses free capitalised adjacency (or "As
      Smith" would be a surname): a narrative "World Bank (2025a)" is
      captured as "Bank (2025a)", and "(World Bank 2024)" must find
      the entry filed under "World Bank Group".

    An abbreviation that is neither named nor an initialism — a paper
    citing "(GoK 2021)" for "Government of Kazakhstan" — stays a
    finding; that map is the paper's, passed via ``aliases``.
    """
    keys = {r.key}
    m = _REF_YEAR_RE.search(r.text)
    head = r.text[:m.start()] if m else r.text
    for acro in _ACRONYM_RE.findall(head):
        keys.add(key_for(acro, r.year))
    words = r.surname.split()
    if len(words[0]) >= 2 and words[0].isupper():
        keys.add(key_for(words[0], r.year))
    if len(words) > 1:
        for i in range(len(words)):
            for j in range(i + 1, len(words) + 1):
                keys.add(key_for(" ".join(words[i:j]), r.year))
        initials = "".join(w[0] for w in words if w[0].isupper())
        if len(initials) >= 2:
            keys.add(key_for(initials, r.year))
    return keys


@dataclass
class LinkAllReport:
    """What :func:`link_all` did, and what it left for a human."""

    linked: list[str] = field(default_factory=list)      # "name @ ¶n"
    already: list[str] = field(default_factory=list)     # linked before
    backlinked: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)   # cite, no entry
    skipped: list[str] = field(default_factory=list)     # anchor trouble

    def format(self) -> str:
        lines = [(f"linked {len(self.linked)}, already linked "
                  f"{len(self.already)}, back-links added "
                  f"{len(self.backlinked)}, unmatched "
                  f"{len(self.unmatched)}, skipped {len(self.skipped)}")]
        for tag, items in (("UNMATCHED", self.unmatched),
                           ("SKIPPED", self.skipped)):
            lines += [f"  {tag}: {x}" for x in items]
        return "\n".join(lines)


def link_all(parts: dict[str, bytes], *,
             aliases: dict[str, str] | None = None,
             heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
             ignore: frozenset[str] | set[str] = IGNORED_LEADS,
             ) -> LinkAllReport:
    """Build the bidirectional citation-link apparatus document-wide.

    The v2 scope docxkit deferred at birth: for every reference entry, a
    ``<SurnameYear>`` bookmark on the entry (an entry's own key-shaped
    bookmark is REUSED, so an existing convention wins) and a back-link
    from its author-year head; for every work's FIRST in-text mention
    (body first, then footnotes), a hyperlink to the entry wrapped in
    the ``<name>txt`` bookmark. Later mentions stay unlinked — the
    papers' convention — and anything already linked is left exactly as
    found, so a partially-linked paper is topped up, not rebuilt, and a
    second run is a no-op.

    Anchors that cannot be resolved safely (a citation repeated inside
    one paragraph, an unfindable head) are REPORTED and skipped, never
    guessed at. Exhibits are :func:`docxkit.crossrefs.link`'s job.
    """
    doc = parts["word/document.xml"].decode("utf-8")
    foot = parts.get("word/footnotes.xml", b"").decode("utf-8")
    report = LinkAllReport()
    filed_as = aliases or {}
    ignored = {s.casefold() for s in ignore}

    paras = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in paras]
    entries = references(texts, heading=heading)
    if not entries:
        report.skipped.append("no reference section found")
        return report
    bid = next_bookmark_id(doc, foot)
    taken = set(_BOOKMARK_NAME_RE.findall(doc))
    linked_anchors = {a for m in paras for a, _ in internal_links(m.group(0))}
    linked_anchors |= {a for a, _ in internal_links(foot)} if foot else set()

    # Names: reuse an entry's own key-shaped bookmark; mint otherwise.
    names: dict[str, str] = {}
    answers: dict[str, str] = {}
    for r in entries:
        own = _own_bookmark(paras[r.index].group(0), r)
        name = own or _dedup_name(
            re.sub(r"[^0-9A-Za-z]", "", r.surname) + r.year, taken)
        taken.add(name)
        names[r.key] = name
        for k in _entry_keys(r):
            answers.setdefault(k, r.key)

    # First mentions: body prose (outside the reference block), then
    # footnotes. Planned per paragraph, applied bottom-up so earlier
    # offsets stay valid.
    head_idx = min(r.index for r in entries)
    last_idx = max(r.index for r in entries)
    claimed: set[str] = set()
    plan: dict[int, list[tuple[str, str]]] = {}       # para -> [(cite, name)]
    fn_plan: dict[int, list[tuple[str, str]]] = {}

    def scan(texts_in: list[str], into: dict[int, list[tuple[str, str]]],
             skip: tuple[int, int] | None) -> None:
        for i, text in enumerate(texts_in):
            if skip and skip[0] <= i <= skip[1]:
                continue
            for found in find_citations(text):
                c = replace(found, authors=strip_lead(found.authors))
                if c.surname.casefold() in ignored:
                    continue
                key = answers.get(
                    key_for(filed_as.get(c.surname, c.surname), c.year))
                if key is None:
                    report.unmatched.append(
                        f"{text[c.start:c.end]!r} (¶{i + 1})")
                    continue
                if key in claimed:
                    continue
                claimed.add(key)
                name = names[key]
                if name in linked_anchors:
                    report.already.append(name)
                    continue
                into.setdefault(i, []).append((text[c.start:c.end], name))

    scan(texts, plan, (head_idx, last_idx))
    fparas = list(PARA_RE.finditer(foot)) if foot else []
    scan([visible_text(m.group(0)) for m in fparas], fn_plan, None)

    # ONE bottom-up pass per part: earlier offsets stay valid however
    # much a later paragraph grows (table notes can sit BELOW the
    # reference block, so entry and prose edits interleave).
    by_entry = {r.index: r for r in entries}
    bids = iter(range(bid, bid + 4096))

    def rebuild(i: int, para: str, where: str) -> str:
        if (r := by_entry.get(i)) is not None and where == "¶":
            name = names[r.key]
            if name not in set(_BOOKMARK_NAME_RE.findall(para)):
                para = _mark_para_head(para, name, next(bids))
            # Back-link only entries whose in-text end exists or is being
            # built: back-linking an UNCITED entry writes a dangling
            # <name>txt target — 19 of them on the Missing Market dry
            # run before this guard.
            if (r.key in claimed or name + "txt" in taken) \
                    and not internal_links(para):
                head = _HEAD_RE.match(texts[i])
                if head is None:
                    report.skipped.append(f"no head on entry ¶{i + 1}")
                else:
                    try:
                        para = link_in_para(para, head.group(1),
                                            name + "txt")
                        report.backlinked.append(name)
                    except AnchorError as exc:
                        report.skipped.append(f"back-link ¶{i + 1}: {exc}")
        for cite, name in (plan if where == "¶" else fn_plan).get(i, []):
            try:
                para = link_in_para(para, cite, name)
                para = wrap_link_in_bookmark(para, name, name + "txt",
                                             next(bids))
                report.linked.append(f"{name} @ {where}{i + 1}")
            except AnchorError as exc:
                report.skipped.append(f"{cite!r} {where}{i + 1}: {exc}")
        return para

    todo = sorted(set(plan) | set(by_entry), reverse=True)
    for i in todo:
        m = paras[i]
        doc = doc[:m.start()] + rebuild(i, m.group(0), "¶") + doc[m.end():]
    for i in sorted(fn_plan, reverse=True):
        m = fparas[i]
        foot = (foot[:m.start()] + rebuild(i, m.group(0), "fn¶")
                + foot[m.end():])
    if fn_plan:
        parts["word/footnotes.xml"] = foot.encode("utf-8")
    parts["word/document.xml"] = doc.encode("utf-8")
    return report


def _dedup_name(name: str, taken: set[str]) -> str:
    if name not in taken and name + "txt" not in taken:
        return name
    n = 2
    while f"{name}_{n}" in taken:
        n += 1
    return f"{name}_{n}"


@dataclass
class LinkRestReport:
    """What :func:`link_rest` did with the later mentions."""

    linked: list[str] = field(default_factory=list)      # "name @ ¶n"
    unmatched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [(f"further mentions linked {len(self.linked)}, "
                  f"unmatched {len(self.unmatched)}, "
                  f"skipped {len(self.skipped)}")]
        for tag, items in (("UNMATCHED", self.unmatched),
                           ("SKIPPED", self.skipped)):
            lines += [f"  {tag}: {x}" for x in items]
        return "\n".join(lines)


def _entry_names_from_document(doc: str, entries: list[Reference],
                               paras: list[re.Match[str]],
                               ) -> dict[str, str]:
    """entry key -> the bookmark name its paragraph actually carries.

    :func:`link_all` bookmarks every entry, so after it has run the
    document itself is the authority on anchor names; re-deriving them
    from surnames would silently diverge on a deduplicated name.
    """
    names: dict[str, str] = {}
    for r in entries:
        own = _own_bookmark(paras[r.index].group(0), r)
        if own:
            names[r.key] = own
    return names


def link_rest(parts: dict[str, bytes], *,
              aliases: dict[str, str] | None = None,
              heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
              ignore: frozenset[str] | set[str] = IGNORED_LEADS,
              ) -> LinkRestReport:
    """Hyperlink every citation :func:`link_all` left plain.

    :func:`link_all` links each work's FIRST mention and bookmarks it;
    house style for later mentions differs by paper, so this second pass
    is separate and optional: every remaining plain citation gets a
    forward hyperlink to its entry — no bookmark, no back-link. Run it
    AFTER :func:`link_all` (it resolves anchor names from the entry
    bookmarks link_all wrote) and it is idempotent, because a linked
    citation is masked out of the next scan.
    """
    doc = parts["word/document.xml"].decode("utf-8")
    foot = parts.get("word/footnotes.xml", b"").decode("utf-8")
    report = LinkRestReport()
    filed_as = aliases or {}
    ignored = {s.casefold() for s in ignore}

    paras = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in paras]
    entries = references(texts, heading=heading)
    if not entries:
        report.skipped.append("no reference section found")
        return report
    names = _entry_names_from_document(doc, entries, paras)
    if not names:
        report.skipped.append(
            "entries carry no bookmarks — run link_all first")
        return report
    answers: dict[str, str] = {}
    for r in entries:
        for k in _entry_keys(r):
            answers.setdefault(k, r.key)
    head_idx = min(r.index for r in entries)
    last_idx = max(r.index for r in entries)

    def rewrite(part: str, matches: list[re.Match[str]],
                skip: tuple[int, int] | None, where: str) -> str:
        for i in range(len(matches) - 1, -1, -1):
            if skip and skip[0] <= i <= skip[1]:
                continue
            para = matches[i].group(0)
            masked = masked_visible_text(para)
            text = visible_text(para)
            todo: list[tuple[int, int, str]] = []
            for found in find_citations(text):
                c = replace(found, authors=strip_lead(found.authors))
                if c.surname.casefold() in ignored:
                    continue
                if "\x00" in masked[c.start:c.end]:
                    continue                      # already inside a link
                key = answers.get(
                    key_for(filed_as.get(c.surname, c.surname), c.year))
                if key is None:
                    report.unmatched.append(
                        f"{text[c.start:c.end]!r} ({where}{i + 1})")
                    continue
                name = names.get(key)
                if name is None:
                    report.skipped.append(
                        f"{text[c.start:c.end]!r} ({where}{i + 1}): entry "
                        "has no bookmark")
                    continue
                todo.append((c.start, c.end, name))
            for at, end, name in sorted(todo, reverse=True):
                try:
                    para = wrap_visible_span(para, at, end, name)
                    report.linked.append(f"{name} @ {where}{i + 1}")
                except AnchorError as exc:
                    report.skipped.append(f"{where}{i + 1}: {exc}")
            m = matches[i]
            part = part[:m.start()] + para + part[m.end():]
        return part

    doc = rewrite(doc, paras, (head_idx, last_idx), "¶")
    if foot:
        fparas = list(PARA_RE.finditer(foot))
        foot = rewrite(foot, fparas, None, "fn¶")
        parts["word/footnotes.xml"] = foot.encode("utf-8")
    parts["word/document.xml"] = doc.encode("utf-8")
    return report


def unlink_by_anchor(xml: str, pattern: str) -> tuple[str, int, int]:
    """Unwrap internal links whose anchor matches `pattern`; drop the
    matching bookmarks.

    The normalisation opener: a document arrives with a legacy linking
    scheme (Google Docs exports anchor citations at ``bookmark=id.…``)
    and the clean scheme should replace it wholesale, dead anchors
    included. BOTH link forms are handled — a Google export writes some
    of its links as ``fldChar HYPERLINK`` fields (the reference entries,
    on Parental Style), and an element-only pass leaves those in place,
    where they silently veto :func:`link_all`'s entry back-links.
    Returns ``(xml, links_unwrapped, bookmarks_removed)``. Run
    properties are left as they are — stripping a legacy link's explicit
    colouring is a formatting decision, not a linking one.
    """
    anchor_re = re.compile(pattern)
    from ._xml import (
        _FIELD_RE,
        _HYPERLINK_EL_RE,
        _HYPERLINK_GHOST_RE,
        _INSTR_ANCHOR_RE,
        _INSTR_RE,
    )
    unwrapped = 0

    def _unwrap(m: re.Match[str]) -> str:
        nonlocal unwrapped
        if not anchor_re.search(html.unescape(m.group(1))):
            return m.group(0)
        unwrapped += 1
        return m.group(2)

    def _drop_ghost(m: re.Match[str]) -> str:
        # a self-closing empty hyperlink: nothing visible, pure junk
        nonlocal unwrapped
        if not anchor_re.search(html.unescape(m.group(1))):
            return m.group(0)
        unwrapped += 1
        return ""

    xml = _HYPERLINK_EL_RE.sub(_unwrap, xml)
    xml = _HYPERLINK_GHOST_RE.sub(_drop_ghost, xml)

    # field form: widen each matching span to whole runs, then drop the
    # scaffolding runs (fldChar, instrText) and keep the label runs
    out: list[str] = []
    pos = 0
    for m in _FIELD_RE.finditer(xml):
        instr = html.unescape("".join(_INSTR_RE.findall(m.group(1))))
        am = _INSTR_ANCHOR_RE.search(instr)
        if am is None or not anchor_re.search(am.group(1)):
            continue
        s = _run_open_before(xml, m.start())
        e = xml.find("</w:r>", m.end())
        if s < 0 or e < 0 or s < pos:      # pragma: no cover - defensive
            continue
        e += len("</w:r>")
        span = RUN_RE.sub(
            lambda rm: ("" if ("<w:fldChar" in rm.group(0)
                               or "<w:instrText" in rm.group(0))
                        else rm.group(0)),
            xml[s:e])
        out.append(xml[pos:s])
        out.append(span)
        pos = e
        unwrapped += 1
    out.append(xml[pos:])
    xml = "".join(out)

    removed = 0
    for bm in list(re.finditer(
            r'<w:bookmarkStart[^>]*w:name="([^"]+)"[^>]*/>', xml)):
        if not anchor_re.search(html.unescape(bm.group(1))):
            continue
        bid = re.search(r'w:id="(\d+)"', bm.group(0))
        xml = xml.replace(bm.group(0), "", 1)
        if bid is not None:
            xml = re.sub(
                rf'<w:bookmarkEnd[^>]*w:id="{bid.group(1)}"[^>]*/>',
                "", xml, count=1)
        removed += 1
    return xml, unwrapped, removed


