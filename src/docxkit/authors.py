r"""Who a document says made its changes.

Every tracked revision, every comment and the document's own properties
carry a name, and a deliverable usually needs ONE — the author sending
it, not the six per-pass identities a pipeline happened to write. This
restamps them across the whole package in a single call:

    from docxkit import read_parts, write_docx
    from docxkit.authors import set_author

    report = set_author(parts, "Michael Lokshin")

Four places carry a name, and missing any one of them shows:

* ``w:author`` on revisions — and there are twenty elements that take
  it (``w:ins``, ``w:del``, ``w:moveFrom``/``w:moveTo``, every
  ``*PrChange``, ``w:cellIns``/``w:cellDel``/``w:cellMerge``, the
  ``customXml*RangeStart`` pair). This rewrites the ATTRIBUTE wherever
  it appears rather than listing the elements, because a list is a list
  to keep up to date and Word keeps adding to it.
* ``w:author`` and ``w:initials`` on comments. Initials are what Word
  prints in the margin balloon, so a renamed comment with stale
  initials shows the new name over the old person's monogram.
* ``word/people.xml``, which pairs a comment author with presence
  information. Leave it and Word's reviewing pane still lists the old
  names, with the comments now attributed to someone not in the list.
  Rewriting collapses several people into one, so the duplicates it
  creates are folded together.
* ``docProps/core.xml`` — ``dc:creator`` and ``cp:lastModifiedBy``, the
  names File > Info shows and the ones that follow a file into a
  journal's submission system.

Dates are never touched: a revision's ``w:date`` is when the edit
happened, which renaming its author does not change.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from typing import NamedTuple

from ._xml import Parts, escape_attr
from .package import set_core_property

__all__ = [
    "CORE_PART",
    "PEOPLE_PART",
    "AuthorReport",
    "initials_for",
    "read_authors",
    "set_author",
]

#: The attribute, not the elements that take it. Attribute order is not
#: meaningful in XML, so matching `<w:ins w:id=... w:author=...>` by
#: shape misses the ones Word writes the other way round.
_AUTHOR_ATTR_RE = re.compile(r'\b(w|w15):author="([^"]*)"')
#: Reading counts CHANGES, so it takes `w:author` only. `w15:author` in
#: people.xml is a registry entry, not an edit, and counting it makes a
#: reviewer who left one comment look like they left two.
_W_AUTHOR_RE = re.compile(r'\bw:author="([^"]*)"')
_INITIALS_ATTR_RE = re.compile(r'\bw:initials="([^"]*)"')
_PERSON_RE = re.compile(r"<w15:person\b.*?</w15:person>|<w15:person\b[^>]*/>",
                        re.DOTALL)
PEOPLE_PART = "word/people.xml"
#: Kept as a re-export: paper scripts import it from here.
CORE_PART = "docProps/core.xml"


class AuthorReport(NamedTuple):
    """What :func:`set_author` rewrote.

    `before` is who the package credited, with counts — worth printing
    before a rewrite, because it is the last chance to notice that one
    of those names is a real co-author whose edits were about to be
    absorbed into someone else's.
    """

    before: Counter[str]
    revisions: int          # w:author attributes rewritten
    comments: int           # w:initials attributes rewritten
    people: int             # word/people.xml entries left
    properties: int         # docProps names rewritten

    @property
    def total(self) -> int:
        return self.revisions + self.comments + self.properties


def initials_for(name: str) -> str:
    """"Michael Lokshin" -> "ML"; a single word gives its first letter."""
    words = [w for w in re.split(r"[\s.]+", name.strip()) if w]
    return "".join(w[0].upper() for w in words[:3]) or "?"


def read_authors(parts: Parts) -> Counter[str]:
    """Every name credited with a change or a comment, and how often.

    Names come back as a person writes them: an author stored as
    ``Smith &amp; Co`` reads as ``Smith & Co``, which is what a caller
    naming them in `only` will type.
    """
    found: Counter[str] = Counter()
    for name, blob in parts.items():
        if not name.endswith(".xml"):
            continue
        found.update(html.unescape(a) for a in
                     _W_AUTHOR_RE.findall(blob.decode("utf-8", "replace")))
    return found


def set_author(parts: Parts, name: str, *,
               initials: str | None = None,
               only: set[str] | None = None) -> AuthorReport:
    """Credit `name` with every change, comment and property.

    `only` restricts the rewrite to those existing names, for a document
    that carries a real co-author's edits alongside a pipeline's — the
    default absorbs everyone, which is right for a deliverable built by
    one person and wrong the moment two people have touched it.

    Returns what moved. Mutates `parts`; nothing is written to disk here.
    """
    if not name.strip():
        raise ValueError("set_author: an empty author name would make Word "
                         "attribute every change to nobody")
    mark = initials if initials is not None else initials_for(name)
    esc_name, esc_mark = escape_attr(name), escape_attr(mark)
    before = read_authors(parts)
    revisions = comments = properties = 0

    def rename(m: re.Match[str]) -> str:
        nonlocal revisions
        # Compare the NAME, not the markup: a co-author called
        # "Smith & Co" is stored as "Smith &amp; Co", and a caller
        # naming them in `only` spells it the way a person does.
        if only is not None and html.unescape(m.group(2)) not in only:
            return m.group(0)
        if m.group(1) == "w":       # a change; w15 is the people registry
            revisions += 1
        return f'{m.group(1)}:author="{esc_name}"'

    def restamp(m: re.Match[str]) -> str:
        nonlocal comments
        comments += 1
        return f'w:initials="{esc_mark}"'

    for part, blob in list(parts.items()):
        if not part.endswith(".xml"):
            continue
        text = blob.decode("utf-8")
        out = _AUTHOR_ATTR_RE.sub(rename, text)
        if only is None:
            out = _INITIALS_ATTR_RE.sub(restamp, out)
        if out != text:         # only the parts that named somebody
            parts[part] = out.encode("utf-8")

    # dc:creator and cp:lastModifiedBy — what File > Info shows, and what
    # follows the file into a journal's submission system. Delegated to
    # package, which knows Word's element order and CREATES what is
    # missing: a property that is not there cannot be renamed, and a
    # rewrite that only substitutes left LI7 with no author at all while
    # reporting a success.
    properties = sum(set_core_property(parts, tag, name)
                     for tag in ("dc:creator", "cp:lastModifiedBy"))

    people = _collapse_people(parts)
    return AuthorReport(before, revisions, comments, people, properties)


def _collapse_people(parts: Parts) -> int:
    """Fold word/people.xml down to one entry per author.

    Renaming several reviewers to one leaves several identical
    ``w15:person`` elements. Word tolerates that, but the reviewing pane
    lists the name once per entry, which reads as several people who
    happen to share a name.
    """
    blob = parts.get(PEOPLE_PART)
    if blob is None:
        return 0
    text = blob.decode("utf-8")
    seen: set[str] = set()
    kept: list[str] = []

    def keep(m: re.Match[str]) -> str:
        who = _AUTHOR_ATTR_RE.search(m.group(0))
        key = html.unescape(who.group(2)) if who else m.group(0)
        if key in seen:
            return ""
        seen.add(key)
        kept.append(key)
        return m.group(0)

    out = _PERSON_RE.sub(keep, text)
    if out != text:             # only when a duplicate was folded away
        parts[PEOPLE_PART] = out.encode("utf-8")
    return len(kept)
