r"""Move a block as a TRACKED change, done by Word, over pending revisions.

`tracked.build` cannot do this: Word's Compare treats the revisions
already in the original as accepted, so a round on a document that still
carries a co-author's pending changes flattens them. Moving the block in
Word itself, with Track Changes on, leaves them alone — and that is what
LFP_Inflows did by hand on 2026-11-08 (Figure 2, beside 7 revisions by
another author), meeting two traps no gate saw:

1. **The author.** ``Application.UserName`` is ignored while Office is
   signed in to an account: all 14 new revisions came out under the
   account's name, which also went into ``word/people.xml`` and
   ``docProps/core.xml``. :func:`tracked_move` sets
   ``Options.UseLocalUserInfo`` (and puts it back), reassigns any
   revision Word still credits to a NEW name, and restores the core and
   app properties from the input.
2. **The flattened copy.** ``dest.FormattedText = block.FormattedText``
   copies the source as its markup view shows it: a caption reading
   "Figure [del 1][ins 2]." arrived as the live text "Figure 12.", the
   pending deletion visible inside the new insertion. The block is copied
   through a scratch document whose revisions are ACCEPTED first, so the
   inserted copy carries the accepted text.

Nothing is trusted. After Word saves, three gates read the package:
rejecting this author's revisions must give back the input paragraph for
paragraph; accepting everything must give the input's accepted text with
the block moved; and every other author's revisions must be where they
were. A move that fails one raises :class:`MoveRefused` and the output
is left in place to inspect.

Word automation, so Windows with Word installed (the ``word`` extra).
"""
from __future__ import annotations

import re
import shutil
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import word as _word
from ._xml import (
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    PARA_RE,
    Parts,
    element_spans,
    escape_attr,
    internal_links,
    visible_text,
)
from .authors import initials_for, read_authors, set_author
from .errors import DocxKitError
from .package import read_parts, write_docx
from .revisions import accept, by_author, reject

__all__ = [
    "MoveRefused",
    "MoveReport",
    "expected_after_move",
    "tracked_move",
    "verify_move",
]

#: What Word rewrites on a save and the move did not mean to change.
_PROPERTIES = ("docProps/core.xml", "docProps/app.xml")
_CORE = "docProps/core.xml"
_PEOPLE = "word/people.xml"
#: a person and the presence record that ties them to an account
_PRESENCE_RE = re.compile(r'(<w15:person\b[^>]*\bw15:author="([^"]*)"'
                          r"[^>]*>)\s*<w15:presenceInfo\b[^>]*/>")


class MoveRefused(DocxKitError):
    """The move could not be made, or Word's result failed a gate."""


@dataclass
class MoveReport:
    """What the move did, as the package says — not as Word claimed."""

    out: Path
    #: revisions this author holds after the move
    revisions: int = 0
    #: names Word credited instead, and how many revisions were moved
    #: back to the author from each
    reassigned: dict[str, int] = field(default_factory=dict)
    restored: list[str] = field(default_factory=list)
    block: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [(f"{self.out.name}: {len(self.block)} paragraph(s) moved, "
                  f"{self.revisions} revision mark(s) by the author")]
        for name, n in self.reassigned.items():
            lines.append(f"  {n} credited to {name!r} by Word, reassigned")
        if self.restored:
            lines.append(f"  restored from the input: "
                         f"{', '.join(self.restored)}")
        return "\n".join(lines)


def _texts(xml: str) -> list[str]:
    """Every paragraph's visible text, in document order."""
    return [visible_text(m.group(0)) for m in PARA_RE.finditer(xml)]


def _unique(texts: list[str], needle: str, what: str) -> int:
    hits = [i for i, t in enumerate(texts) if needle in t]
    if len(hits) != 1:
        raise MoveRefused(f"{what} {needle!r}: {len(hits)} paragraphs hold "
                          f"it in the accepted text, need exactly 1")
    return hits[0]


def _span(texts: list[str], block: str, through: str | None,
          after: str) -> tuple[int, int, int]:
    """``(first, last, target)`` paragraph indices in `texts`."""
    first = _unique(texts, block, "block")
    last = first if through is None else _unique(texts, through, "through")
    target = _unique(texts, after, "after")
    if last < first:
        raise MoveRefused(f"through {through!r} comes before block "
                          f"{block!r}")
    if first <= target <= last:
        raise MoveRefused(f"after {after!r} lies inside the block")
    return first, last, target


def expected_after_move(texts: list[str], block: str, through: str | None,
                        after: str) -> list[str]:
    """`texts` with the paragraphs from `block` through `through` moved to
    follow the paragraph holding `after` — what the accepted view of a
    correct move reads."""
    first, last, target = _span(texts, block, through, after)
    moved = texts[first:last + 1]
    rest = texts[:first] + texts[last + 1:]
    at = target if target < first else target - len(moved)
    return rest[:at + 1] + moved + rest[at + 1:]


_BOOKMARK_NAME_RE = re.compile(r'<w:bookmarkStart\b[^>]*\bw:name="([^"]*)"')
_NOTE_REF_RE = re.compile(
    r"<w:(footnote|endnote)Reference\b[^>]*\bw:id=\"([^\"]*)\"")


def _carried(xml: str) -> tuple[Counter[str], Counter[str], int]:
    """What a view carries beyond its words: bookmark names (Word's own
    `_GoBack` aside, which it writes on every save), internal link
    targets, and how many note references it holds."""
    marks = Counter(n for n in _BOOKMARK_NAME_RE.findall(xml)
                    if n != "_GoBack")
    links = Counter(anchor for anchor, _label in internal_links(xml))
    return marks, links, len(_NOTE_REF_RE.findall(xml))


def _cell_texts(xml: str) -> list[str]:
    """The paragraphs that sit inside a table, in document order."""
    spans = element_spans(xml, "tbl")
    return [visible_text(m.group(0)) for m in PARA_RE.finditer(xml)
            if any(lo <= m.start() < hi for lo, hi in spans)]


def _others(author: str) -> Callable[[Any], bool]:
    return lambda r: r.author != author


def verify_move(before: Parts, after: Parts, *, block: str,
                through: str | None, where: str, author: str,
                mixed: bool = True) -> list[str]:
    """Why `after` is not `before` with the block moved by `author`; empty
    when it is. Read from the packages, in every view a reviewer can
    make: the round rejected, everything accepted, and the round
    accepted with everyone else's changes rejected (`mixed`)."""
    was, now = (p[DOCUMENT].decode("utf-8") for p in (before, after))
    mine = by_author(author)
    problems = []
    # against the input with THIS author's own earlier revisions rejected
    # too: a second move by the same author is not a failure of the first
    if _texts(reject(now, where=mine)) != _texts(reject(was, where=mine)):
        problems.append(f"rejecting {author!r}'s revisions does not give "
                        f"back the input")
    want = expected_after_move(_texts(accept(was)), block, through, where)
    if _texts(accept(now)) != want:
        problems.append("the accepted text is not the input's with the "
                        "block moved")
    if mixed:
        theirs = _texts(reject(was, where=_others(author)))
        try:
            want_mixed = expected_after_move(theirs, block, through, where)
        except MoveRefused:
            want_mixed = None       # the anchors are the co-authors' words
        got = _texts(reject(accept(now, where=mine), where=_others(author)))
        if want_mixed is not None and got != want_mixed:
            problems.append("accepting the move and rejecting everyone "
                            "else's changes gives the wrong text")
    if _cell_texts(accept(now)) != _cell_texts(accept(was)):
        problems.append("the block landed inside a table")
    if _carried(accept(now)) != _carried(accept(was)):
        problems.append("a bookmark, link target or note reference the "
                        "block carried is not in the accepted result")
    for part in (FOOTNOTES, ENDNOTES):
        a, b = before.get(part), after.get(part)
        if a is not None and b is not None and (
                _texts(accept(b.decode("utf-8")))
                != _texts(accept(a.decode("utf-8")))):
            problems.append(f"{part}: the notes' accepted text changed")
    old, new = read_authors(before), read_authors(after)
    changed = sorted(n for n in set(old) | set(new)
                     if n != author and old[n] != new[n])
    if changed:
        problems.append(f"other authors' revisions changed: "
                        f"{', '.join(changed)}")
    if new[author] <= old[author]:
        problems.append(f"no revision is credited to {author!r}")
    return problems


def _attribute(before: Parts, after: Parts, author: str,
               initials: str | None) -> dict[str, int]:
    """Give `author` what Word credited to a name the input never had.

    A name the input already held cannot be told apart by name, so it is
    a refusal rather than a guess: ``set_author(only=...)`` on it would
    take the co-author's own revisions too."""
    old, new = read_authors(before), read_authors(after)
    grew = {n: new[n] - old[n] for n in new if n != author and new[n] > old[n]}
    shared = sorted(n for n in grew if old[n])
    if shared:
        raise MoveRefused(
            f"Word credited the move to {', '.join(shared)}, a name the "
            f"input already carries — the new revisions cannot be told "
            f"from the old by name. Sign Office out, or rename that "
            f"author first")
    if grew:
        # set_author also rewrites dc:creator and cp:lastModifiedBy,
        # whatever `only` says — not this function's business, so put
        # back — and renames the account's w15:person while keeping its
        # presenceInfo, which ties the new author to the account's
        # identity: the leak trap 1 is about (review, 2026-11-09)
        core = after.get(_CORE)
        set_author(after, author, initials=initials, only=set(grew))
        if core is not None:
            after[_CORE] = core
        if _PEOPLE in after:
            mine = escape_attr(author)
            after[_PEOPLE] = _PRESENCE_RE.sub(
                lambda m: m.group(1) if m.group(2) == mine else m.group(0),
                after[_PEOPLE].decode("utf-8")).encode("utf-8")
    return grew


@contextmanager
def _as_author(word: Any, author: str, initials: str) -> Iterator[None]:
    """Word writing revisions under `author`, and its settings put back.

    Word PERSISTS all four, so each change is undone if anything after it
    fails, and the restore runs one setting at a time, in the order that
    keeps the user's own slot intact: UseLocalUserInfo first, so the
    names saved while it was off go back where they came from rather
    than into the local user-info Word keeps beside the account (review,
    2026-11-09). A restore that fails does not hide the error that
    brought us here."""
    options = word.Options
    saved = [(options, "UseLocalUserInfo", options.UseLocalUserInfo),
             (word, "UserName", word.UserName),
             (word, "UserInitials", word.UserInitials),
             (word, "CheckLanguage", word.CheckLanguage)]
    wanted = {"UseLocalUserInfo": True, "UserName": author,
              "UserInitials": initials,
              # language detection stamps `w:lang` on what it touches,
              # which with Track Changes on is a FORMATTING revision
              # nobody asked for ("Formatted: English (US)")
              "CheckLanguage": False}
    changed: list[tuple[Any, str, Any]] = []
    try:
        for owner, name, value in saved:
            setattr(owner, name, wanted[name])
            changed.append((owner, name, value))
        yield
    finally:
        for owner, name, value in changed:
            with suppress(Exception):       # best effort, see docstring
                setattr(owner, name, value)


def _paragraph(doc: Any, text: str) -> Any:
    rng = doc.Content
    find = rng.Find
    find.ClearFormatting()
    # `^` opens one of Find's special codes (^p, ^t, ^#…): a literal one
    # is written ^^, or an anchor holding it finds something else
    if not find.Execute(FindText=text[:255].replace("^", "^^"),
                        MatchCase=True, Forward=True, Wrap=0):
        raise MoveRefused(f"Word did not find {text!r}")
    return rng.Paragraphs(1)


#: ``WdInformation.wdWithInTable``
_WD_WITHIN_TABLE = 12


def _word_move(word: Any, doc: Any, *, block: str, through: str,
               after: str, author: str = "",
               accept_pending: bool = False) -> int:
    """The move itself, in an open document: returns the block's
    paragraph count as Word sees it. A one-paragraph block has `through`
    equal to `block`."""
    first = _paragraph(doc, block)
    last = _paragraph(doc, through)
    source = doc.Range(first.Range.Start, last.Range.End)
    target = _paragraph(doc, after)
    pending = sorted({str(r.Author) for r in source.Revisions
                      if str(r.Author) != author})
    if pending and not accept_pending:
        raise MoveRefused(
            f"the block holds pending revisions by {', '.join(pending)}. "
            f"The copy would carry them ACCEPTED, so a reviewer who "
            f"accepts the move and rejects their change gets the wrong "
            f"text. Settle them first, or pass accept_pending=True to "
            f"move the accepted text knowingly")
    dest = doc.Range(target.Range.End, target.Range.End)
    if dest.Information(_WD_WITHIN_TABLE):
        raise MoveRefused(
            f"the paragraph after {after!r} opens a table: the block would "
            f"land in its first cell. Name the paragraph after the table, "
            f"or the one before {after!r}")
    # the ACCEPTED block: through a scratch document, revisions accepted
    # there, so a pending deletion does not arrive as live text
    scratch = word.Documents.Add()
    try:
        scratch.TrackRevisions = False
        scratch.Range().FormattedText = source.FormattedText
        scratch.Revisions.AcceptAll()
        body = scratch.Range(0, scratch.Content.End - 1)
        doc.TrackRevisions = True
        dest.FormattedText = body.FormattedText
        count = int(body.Paragraphs.Count)
    finally:
        scratch.Close(SaveChanges=0)
    _delete_live(doc, source)
    doc.Save()
    return count


#: ``WdRevisionType.wdRevisionDelete``
_WD_DELETE = 2


def _delete_live(doc: Any, source: Any) -> None:
    """Delete `source` as a tracked change, LEAVING another author's
    pending deletions inside it theirs.

    ``source.Delete()`` takes them over: measured 2026-11-09, a caption
    holding a co-author's deleted "1" came back with that "1" inside the
    new author's deletion, so rejecting the round restored it as live
    text ("Figure12") and the co-author's change was gone. Only the live
    stretches between the existing deletions are deleted, last first, so
    the earlier ranges do not move. A pending INSERTION is live text and
    is deleted with the rest — Word nests it, the co-author's insertion
    holding this author's deletion, which rejects back correctly.
    """
    start, end = int(source.Start), int(source.End)
    gone = sorted((max(start, int(r.Range.Start)), min(end, int(r.Range.End)))
                  for r in source.Revisions
                  if int(r.Type) == _WD_DELETE)
    live, at = [], start
    for lo, hi in gone:
        if lo > at:
            live.append((at, lo))
        at = max(at, hi)
    if at < end:
        live.append((at, end))
    for lo, hi in reversed(live):
        doc.Range(lo, hi).Delete()


def tracked_move(src: str | Path, out: str | Path, *, block: str,
                 after: str, author: str, through: str | None = None,
                 initials: str | None = None, keep_properties: bool = True,
                 accept_pending: bool = False,
                 deadline: float | None = 600,
                 _move: Callable[..., int] | None = None) -> MoveReport:
    """Move the paragraphs from the one holding `block` through the one
    holding `through` (or `block`'s alone) to follow the paragraph holding
    `after`, as a tracked change by `author`. Writes `out`; `src` is not
    touched. Every anchor is visible text, unique in the accepted view.

    `keep_properties` restores ``docProps/core.xml`` and ``app.xml`` from
    `src`: Word stamps its own account into them on save.

    A block holding ANOTHER author's pending revisions is refused: the
    copy carries the block's accepted text, so "accept the move, reject
    their change" would give the wrong words, and the tool does not
    settle anyone's revisions for them. `accept_pending=True` moves it
    anyway, knowingly — LFP_Inflows' caption "Figure [del 1][ins 2]" was
    that case — and skips the gate for that mixed verdict, which by
    construction it cannot pass.
    """
    src, out = Path(src), Path(out)
    before = read_parts(src)
    texts = _texts(accept(before[DOCUMENT].decode("utf-8")))
    first, last, _ = _span(texts, block, through, after)
    mark = initials if initials is not None else initials_for(author)
    shutil.copy2(src, out)
    run = _move or _word_move
    with _word.session(fast=False, deadline=deadline,
                       doing="tracked_move") as word, \
            _word.open_doc(word, out.resolve(), read_only=False) as doc, \
            _as_author(word, author, mark):
        run(word, doc, block=block, through=through or block, after=after,
            author=author, accept_pending=accept_pending)
    parts = read_parts(out)
    report = MoveReport(out=out, block=texts[first:last + 1])
    report.reassigned = _attribute(before, parts, author, mark)
    if keep_properties:
        for name in _PROPERTIES:
            if name in before and parts.get(name) != before[name]:
                parts[name] = before[name]
                report.restored.append(name)
    write_docx(out, parts)
    problems = verify_move(before, parts, block=block, through=through,
                           where=after, author=author,
                           mixed=not accept_pending)
    if problems:
        raise MoveRefused(f"{out.name}: " + "; ".join(problems)
                          + " — the output is left in place to inspect")
    report.revisions = Counter(read_authors(parts))[author]
    return report
