"""The link BUILDER: making a document's citation apparatus.

`link_all` wires every first mention to its entry and back; `link_rest`
forward-links the later mentions; `unlink_by_anchor` tears a scheme out
so it can be rebuilt. All idempotent, so a build can run them every
round.
"""
from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

from ._cite_audit import _BOOKMARK_NAME_RE, _KEY_SHAPE_RE
from ._cite_grammar import (
    _DEFAULT_HEADINGS,
    _REF_YEAR_RE,
    IGNORED_LEADS,
    Reference,
    extend_to_name,
    find_citations,
    key_for,
    link_in_para,
    masked_visible_text,
    references,
    resolve_lead,
    wrap_visible_span,
)
from ._cite_repair import (
    _mark_para_head,
    next_bookmark_id,
    wrap_link_in_bookmark,
)
from ._xml import (
    DOCUMENT,
    FOOTNOTES,
    PARA_RE,
    RUN_RE,
    internal_links,
    run_open_before,
    visible_text,
)
from .errors import AnchorError

# --------------------------------------------------- the link BUILDER ---

_HEAD_RE = re.compile(r"\s*(.*?\(?\b\d{4}[a-z]?\)?)[.,]")


_ACRONYM_RE = re.compile(r"\(([A-Z]{2,})\)")

#: Word's hard limit on a bookmark NAME. Anything longer is truncated on
#: save without retargeting the anchors that point at it.
WORD_BOOKMARK_LIMIT = 40
#: The in-text partner of a reference bookmark carries a "txt" suffix, so
#: the base name has to leave room for it under the same limit.
_NAME_BUDGET = WORD_BOOKMARK_LIMIT - len("txt")


#: Cyrillic -> Latin, enough for the Russian and Kazakh names these papers
#: cite. Not a standard transliteration: it exists so a bookmark name has
#: Latin letters to be built from.
_CYRILLIC = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ж": "Zh",
    "З": "Z", "И": "I", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "Kh",
    "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Shch", "Ъ": "", "Ы": "Y",
    "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
    "Ә": "A", "Ғ": "G", "Қ": "K", "Ң": "N", "Ө": "O", "Ұ": "U", "Ү": "U",
    "Һ": "H", "І": "I", "Є": "Ye", "Ї": "Yi",
}
_CYRILLIC.update({k.lower(): v.lower() for k, v in list(_CYRILLIC.items())})


def _ascii_stem(surname: str) -> str:
    """The Latin letters a bookmark name is built from.

    Stripping non-ASCII outright gave "Aczél" the stem "Aczl", and a Cyrillic
    institution no stem at all — so its name became the bare year, "2026",
    which :data:`_KEY_SHAPE_RE` does not accept as a key. :func:`link_all` then
    failed to recognise its own marker on the next run and minted "2026_2",
    then "2026_3": the pass advertises idempotency and quietly lost it.

    Accents fold and Cyrillic transliterates, so the stem is stable and still
    readable. A surname with no Latin letters at all falls back to "Ref", which
    is key-shaped and therefore reusable.
    """
    out = []
    for ch in unicodedata.normalize("NFKD", surname):
        if unicodedata.combining(ch):
            continue
        out.append(_CYRILLIC.get(ch, ch))
    # LETTERS only: _KEY_SHAPE_RE's alpha group is [A-Za-z][A-Za-z.]*, so a
    # digit anywhere in the stem costs the name its key shape — which is the
    # whole point of having one.
    stem = re.sub(r"[^A-Za-z]", "", "".join(out))
    return stem or "Ref"


def _own_bookmark(para_xml: str, r: Reference, before: str = "") -> str | None:
    """The entry's OWN key-shaped bookmark, or None.

    Both the year and the surname must match. Matching on the year
    alone reuses whatever key-shaped bookmark happens to sit on the
    paragraph — a stray `Jones2020` left by an earlier round on a
    "Smith, A. (2020)" entry made link_all wire every "(Smith 2020)" in
    the text to the WRONG work, and report "linked 1" while doing it.

    `before` is the body-level XML immediately preceding the paragraph.
    :func:`_mark_para_head` writes the marker INSIDE the paragraph, but
    WORD HOISTS IT OUT when the author saves — 86 of 167 on Parental
    Style's second handback. Reading only the paragraph then found
    nothing, so link_all minted a second name for every entry and
    re-wrapped all 71 citations (`Baumrind1991_2txt`), silently doubling
    the scheme. The surname-and-year check is what makes widening the
    search safe: a marker hoisted out of the PREVIOUS entry cannot match
    this one.
    """
    # BOTH stems: the current one, and the strip-only stem earlier runs minted.
    # A document linked before _ascii_stem existed carries «Aczl1966», and
    # recognising only «Aczel» would orphan it and mint a second marker.
    stems = {_ascii_stem(r.surname).casefold(),
             re.sub(r"[^0-9A-Za-z]", "", r.surname).casefold()}
    names: list[str] = _BOOKMARK_NAME_RE.findall(before + para_xml)
    for n in names:
        km = _KEY_SHAPE_RE.match(n)
        if km is None or n.endswith("txt") or km.group(2) != r.year:
            continue
        # the bookmark's alpha part is the surname, possibly truncated
        # (an acronym entry files under it) — one must prefix the other
        got = km.group(1).casefold()
        if any(a and (a.startswith(got) or got.startswith(a)) for a in stems):
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


def _named(r: Reference, convention: Callable[[str, str], str] | None,
           taken: set[str], report: LinkAllReport) -> str:
    """The paper's name for this entry, or the one this module mints.

    The convention wins where it can, and says so where it cannot:
    a collision mis-targets a link, and a name over Word's cap is
    truncated ON SAVE with every hyperlink left pointing at the full
    name — both silent, both worse than an unconventional name.
    """
    if convention is None:
        return _mint_name(r, taken)
    proposed = convention(r.surname, r.year)
    if len(proposed) > _NAME_BUDGET:
        report.skipped.append(
            f"{proposed!r} is {len(proposed)} characters and its in-text "
            f"twin {proposed}txt would pass Word's {WORD_BOOKMARK_LIMIT}-"
            f"character cap, which Word applies ON SAVE without retargeting "
            f"the links — minted instead")
    elif proposed in taken or proposed + "txt" in taken:
        report.skipped.append(
            f"{proposed!r} is already taken by another anchor — minted "
            f"instead, because a collision mis-targets a link")
    else:
        return proposed
    return _mint_name(r, taken)


def _wanted(only: Collection[str] | None, entries: list[Reference],
            names: dict[str, str]) -> set[str] | None:
    """The keys `only` selects — by key, surname or bookmark name."""
    if only is None:
        return None
    asked = {str(o).casefold() for o in only}
    return {r.key for r in entries
            if {r.key.casefold(), r.surname.casefold(),
                names[r.key].casefold()} & asked}


def link_all(parts: dict[str, bytes], *,
             aliases: dict[str, str] | None = None,
             heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
             ignore: frozenset[str] | set[str] = IGNORED_LEADS,
             naming: Callable[[str, str], str] | None = None,
             only: Collection[str] | None = None,
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

    `naming` is the paper's own CONVENTION: ``(surname, year) ->
    bookmark name``. The names minted here are this module's —
    ``UnitedNations2024``, ``Schunemann2017_2`` — and a manuscript that
    already wires 79 pairs as ``Kanbur2007`` / ``Kanbur2007txt`` had no
    way to say so, so its six new citations were hand-wired instead
    (LI7, 2026-08-15). An entry's OWN key-shaped bookmark still wins
    over both: an existing anchor is never renamed. A convention that
    collides with a name already taken, or that Word's 40-character cap
    would truncate, falls back to the minted form and SAYS so — a
    truncated bookmark orphans every link pointing at it, silently.

    `only` scopes the pass to named works: keys (``kanbur_2007``),
    surnames, or bookmark names. Everything else is left exactly as
    found, which is what a repair of six citations needs — the same
    builder took one paper's audit from 26 findings to 56 when it was
    turned loose on the whole document. The reference block is still
    read whole, because that is what tells prose from entries.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    foot = parts.get(FOOTNOTES, b"").decode("utf-8")
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

    # The body-level XML just before each paragraph: where Word leaves a
    # marker it has hoisted out of the paragraph head on save.
    gaps = {i: doc[(paras[i - 1].end() if i else 0):m.start()]
            for i, m in enumerate(paras)}

    # Names: reuse an entry's own key-shaped bookmark; then the paper's
    # convention if it states one; mint otherwise.
    names: dict[str, str] = {}
    answers: dict[str, str] = {}
    by_key = {r.key: r for r in entries}
    for r in entries:
        own = _own_bookmark(paras[r.index].group(0), r, gaps[r.index])
        names[r.key] = own or _named(r, naming, taken, report)
        taken.add(names[r.key])
        for k in _entry_keys(r):
            answers.setdefault(k, r.key)

    # The whole reference block is read either way: `only` decides what
    # is WRITTEN, not what is understood, and the block's bounds below
    # are what tell an entry from a sentence.
    wanted = _wanted(only, entries, names)

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
                c = resolve_lead(found, known=answers)
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
                if wanted is not None and key not in wanted:
                    continue
                claimed.add(key)
                name = names[key]
                if name in linked_anchors:
                    report.already.append(name)
                    continue
                c = extend_to_name(text, c, by_key[key].surname)
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
        if (r := by_entry.get(i)) is not None and where == "¶" \
                and (wanted is None or r.key in wanted):
            name = names[r.key]
            # the gap counts too: a marker Word hoisted out of this
            # paragraph is still this entry's marker, and adding a second
            # one inside would leave two bookmarks of the same name
            if name not in set(_BOOKMARK_NAME_RE.findall(gaps[i] + para)):
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

    # A back-link is decided from `claimed`, which is filled while
    # PLANNING; the in-text wrap that creates its <name>txt target runs
    # later in the same pass and can legitimately refuse (a citation
    # occurring twice in one paragraph is ambiguous, so link_in_para
    # raises). Entries are rebuilt bottom-up, and the reference list sits
    # BELOW the prose, so the back-link is already written by then.
    # Shipping it anyway leaves a dangling anchor — silent, and only an
    # audit finds it (Parental Style 2026-08-05: Bhalotra and Clarke,
    # welded by hand). Undo any back-link whose target never appeared.
    if report.backlinked:
        marks = set(_BOOKMARK_NAME_RE.findall(doc))
        if foot:
            marks |= set(_BOOKMARK_NAME_RE.findall(foot))
        for name in list(report.backlinked):
            if name + "txt" in marks:
                continue
            doc, _, _ = unlink_by_anchor(
                doc, rf"^{re.escape(name)}txt$")
            report.backlinked.remove(name)
            report.skipped.append(
                f"back-link {name}: its in-text mention was not wrapped, "
                f"so {name}txt does not exist — back-link removed")

    if fn_plan:
        parts[FOOTNOTES] = foot.encode("utf-8")
    parts[DOCUMENT] = doc.encode("utf-8")
    return report


def _dedup_name(name: str, taken: set[str]) -> str:
    if name not in taken and name + "txt" not in taken:
        return name
    n = 2
    while f"{name}_{n}" in taken:
        n += 1
    return f"{name}_{n}"


def _mint_name(r: Reference, taken: set[str]) -> str:
    """A bookmark name Word will not truncate.

    Word caps a bookmark name at :data:`WORD_BOOKMARK_LIMIT` characters
    when it SAVES, and does not retarget the hyperlinks that pointed at
    the full name — every anchor is silently orphaned, and the document
    still opens, so only an audit finds it. Institutional authors blow
    the limit easily: "State Committee of the Republic of Uzbekistan on
    Statistics and United Nations Children's Fund (UNICEF)" + year mints
    a 90-character name (Parental Style, 2026-08-05: four entries, eight
    dead anchors, discovered only when the author saved in Word).

    Only the alpha part is truncated, so the name keeps the shape
    ``<alpha><year>[_N]`` that :data:`_KEY_SHAPE_RE` requires, and
    :func:`_own_bookmark` still recognises it on a later run because it
    matches the surname by prefix in either direction.
    """
    alpha = _ascii_stem(r.surname)
    for n in range(1, 100):
        suffix = "" if n == 1 else f"_{n}"
        keep = _NAME_BUDGET - len(r.year) - len(suffix)
        if keep < 1:
            break
        name = alpha[:keep] + r.year + suffix
        if name not in taken and name + "txt" not in taken:
            return name
    # Pathological: uniqueness beats the cap, because a name collision
    # mis-targets a link while an over-long one merely breaks it.
    return _dedup_name(alpha + r.year, taken)


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

    The BODY-LEVEL gap before each entry counts as the entry's own, the
    same way :func:`link_all` reads it. Word hoists a collapsed bookmark
    out of the paragraph it marks, so a settled manuscript keeps
    ``…</w:p><w:bookmarkStart/><w:bookmarkEnd/><w:p …>`` — and reading
    the paragraph alone found nothing, so :func:`link_rest` declined
    every later mention of those works with "entry has no bookmark".
    Nine mentions across six works on Parental Style (2026-08-11), which
    the author noticed before any tool did: the later-mention layer had
    quietly stopped being maintained. `_own_bookmark` requires the
    surname AND the year to match, which is what makes the wider search
    safe — a marker hoisted out of the previous entry cannot match this
    one.
    """
    names: dict[str, str] = {}
    for r in entries:
        m = paras[r.index]
        before = doc[(paras[r.index - 1].end() if r.index else 0):m.start()]
        own = _own_bookmark(m.group(0), r, before)
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
    doc = parts[DOCUMENT].decode("utf-8")
    foot = parts.get(FOOTNOTES, b"").decode("utf-8")
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
    by_key = {r.key: r for r in entries}
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
                c = resolve_lead(found, known=answers)
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
                # Widen over the institution's name, but not into an
                # existing link: the narrow span already cleared the mask,
                # so falling back to it links less prettily, never worse.
                wide = extend_to_name(text, c, by_key[key].surname)
                if "\x00" not in masked[wide.start:wide.end]:
                    c = wide
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
        parts[FOOTNOTES] = foot.encode("utf-8")
    parts[DOCUMENT] = doc.encode("utf-8")
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
        INSTR_ANCHOR_RE,
        INSTR_RE,
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
        instr = html.unescape("".join(INSTR_RE.findall(m.group(1))))
        am = INSTR_ANCHOR_RE.search(instr)
        if am is None or not anchor_re.search(am.group(1)):
            continue
        s = run_open_before(xml, m.start())
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


