r"""Locating things inside ``word/document.xml``.

Prose anchors have to be located by VISIBLE TEXT, never by raw XML: Word
fragments a sentence across runs at rsid boundaries, so "Figure 6" is
routinely stored as ``Figur`` + ``e`` + ` 6` and a ``\bFigure 6\b`` regex
silently misses it. Everything here works on the concatenation of the
``<w:t>`` / ``<m:t>`` contents and maps back to offsets.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from ._xml import (
    NOTE_REF_RE,
    PARA_RE,
    internal_links,
    matching_close,
    normalize_glyphs,
    set_para_property,
    visible_text,
)
from .errors import AnchorError

__all__ = [
    "DEFAULT_LABELS",
    "P_RE",
    "AnchorError",
    "Site",
    "body_elements",
    "caption_re",
    "edit_para",
    "find_para",
    "heading_level",
    "internal_links",
    "page_break_before",
    "para_slice",
    "para_text_at",
    "paragraphs",
    "site",
    "table_index_at",
    "table_spans",
    "text_of",
]

#: Caption words recognised by default. Add the paper's own if it writes
#: them differently — DSI's Russian manuscripts use Рисунок/Таблица.
DEFAULT_LABELS = ("Figure", "Table", "Рисунок", "Таблица")

@lru_cache(maxsize=8)
def caption_re(labels: tuple[str, ...] = DEFAULT_LABELS) -> re.Pattern[str]:
    """Label + number + separator. The separator is what makes it a caption.

    THE caption definition — wordcount and export classify by it too.
    It briefly existed in three copies that already disagreed about
    whether "Table" counts, which is the same drift that once split the
    glyph table between compare and ingest.
    """
    # [\w.-]: exhibit numbers are "1", "A2", "3.2" and "1-A". The hyphen
    # form was invisible here, so a "Table 1-A." caption was not a
    # caption at all and nothing linked to it. anchor_names sanitises
    # the bookmark (Table1_A) — Word allows only word characters there.
    #
    # Something after the separator, OR the end of the text: the title
    # often sits in the NEXT paragraph, which leaves a caption whose
    # whole text is "Figure 1." — and every caller matches this against
    # stripped text, so the trailing space it used to require was one
    # the strip had just removed. `placement.exhibit_block` then refused
    # a real caption ("no caption paragraph containing 'Figure 1.'") and
    # `_table_core._beside` could not see it standing between a table
    # and another caption. The alternation still has to CONSUME the
    # space when there is one: it is what makes "3.2." parse as the
    # number 3.2 rather than as 3 followed by a stray "2".
    alt = "|".join(re.escape(w) for w in labels)
    return re.compile(rf"^\s*({alt})\s+([\w.-]+?)\s*[.:](?:\s|$)")


# kept as aliases: several paper scripts import these from here. There
# was a third, `delta_text_of`, and nothing in four trees ever called it
# — an alias is only worth its export while someone spells it that way.
P_RE = PARA_RE
text_of = visible_text


def paragraphs(xml: str) -> list[re.Match[str]]:
    """Every ``<w:p>`` as a match, so callers keep the offsets."""
    return list(PARA_RE.finditer(xml))


def para_slice(xml: str, sig: str, also: str | None = None,
               *, normalize: bool = False) -> tuple[int, int]:
    """(start, end) of the ONE paragraph whose visible text contains `sig`.

    Raises unless exactly one matches: an anchor that hits two paragraphs
    is a latent bug that would otherwise edit whichever came first. Pass
    `also` to disambiguate (e.g. the equation number).

    `normalize` folds Word's typographic substitutions before matching, so
    an anchor written with a straight apostrophe still finds a paragraph
    Word autocorrected to a curly one.
    """
    fold = normalize_glyphs if normalize else (lambda s: s)
    sig, also = fold(sig), (None if also is None else fold(also))
    hits = [(m.start(), m.end()) for m in PARA_RE.finditer(xml)
            if sig in (t := fold(visible_text(m.group(0))))
            and (also is None or also in t)]
    if len(hits) != 1:
        raise AnchorError(
            f"para_slice({sig!r}, also={also!r}): {len(hits)} hits, need 1")
    return hits[0]


def edit_para(xml: str, sig: str, fn: Callable[[str], str],
              *, normalize: bool = False) -> str:
    """Apply `fn` to the single paragraph whose visible text contains `sig`."""
    s, e = para_slice(xml, sig, normalize=normalize)
    return xml[:s] + fn(xml[s:e]) + xml[e:]


def page_break_before(xml: str, sig: str) -> str:
    """Start the paragraph matching `sig` on a fresh page.

    The exhibit convention: give every table caption a
    ``w:pageBreakBefore`` and the table opens its own page wherever the
    prose ends up. Idempotent — a paragraph that already breaks is left
    alone. (In the pPr schema the flag sorts after ``pStyle``.)
    """
    def add(para: str) -> str:
        return set_para_property(para, "pageBreakBefore",
                                 "<w:pageBreakBefore/>")
    return edit_para(xml, sig, add)


def find_para(xml: str, sig: str) -> re.Match[str] | None:
    """First paragraph whose visible text contains `sig`, or None."""
    return next((m for m in PARA_RE.finditer(xml)
                 if sig in visible_text(m.group(0))), None)


def para_text_at(xml: str, pos: int) -> str:
    """Visible text of the paragraph containing offset `pos`."""
    for m in PARA_RE.finditer(xml):
        if m.start() <= pos < m.end():
            return visible_text(m.group(0))
    return ""


def table_spans(xml: str, expect: int | None = None) -> list[tuple[int, int]]:
    """(start, end) of every ``<w:tbl>`` in body order.

    Index into this to identify WHICH manuscript table an offset falls in.
    `expect` asserts the count, so a table added or lost upstream fails
    loudly here instead of silently shifting every later index.
    """
    out = []
    for m in re.finditer(r"<w:tbl>", xml):
        s = m.start()
        out.append((s, xml.index("</w:tbl>", s) + len("</w:tbl>")))
    if expect is not None and len(out) != expect:
        raise AnchorError(f"{len(out)} tables, expected {expect}")
    return out


def table_index_at(spans: list[tuple[int, int]], pos: int) -> int | None:
    """Index of the table containing `pos`, or None if outside every table."""
    return next((i for i, (s, e) in enumerate(spans) if s <= pos < e), None)


_OUTLINE_RE = re.compile(r'<w:outlineLvl w:val="(\d+)"')
_PSTYLE_RE = re.compile(r'<w:pStyle w:val="([^"]+)"')
# Heading1..9 and the German ids Word writes as berschrift1..9 (the
# style id drops the umlaut); a digitless Heading-family style still IS
# a heading, just an unlevelled one
_HEADING_STYLE_RE = re.compile(r"^(?:Heading|berschrift)(\d*)")


def heading_level(para_xml: str) -> int | None:
    """1..6 if the paragraph is a heading, else None — decided ONCE.

    ``outlineLvl`` wins when present (it is what Word's navigation pane
    believes); otherwise the paragraph style: Title is 1, Subtitle 2,
    Heading*N* is N. Both the word-count buckets and the markdown
    ``#`` depth answer this question, and two detectors drifting apart
    would count a paragraph as a heading while rendering it as prose.
    """
    if (m := _OUTLINE_RE.search(para_xml)) is not None:
        return min(int(m.group(1)) + 1, 6)
    if (m := _PSTYLE_RE.search(para_xml)) is not None:
        style = m.group(1)
        if style == "Title":
            return 1
        if style == "Subtitle":
            return 2
        if (h := _HEADING_STYLE_RE.match(style)) is not None:
            return min(int(h.group(1) or 1), 6)
    return None


def body_elements(xml: str) -> list[tuple[str, int, int]]:
    """``("p" | "tbl", start, end)`` for the body, in document order.

    The walk anything reading a document linearly needs: top-level tables
    as single units, paragraphs OUTSIDE tables individually. Iterating
    ``PARA_RE`` alone double-counts, because a table's cells are made of
    paragraphs too — the word-count and markdown passes both need this
    and must not disagree about it.

    Spans are depth-counted (unlike :func:`table_spans`, kept as-is for
    offset lookups), so a nested table rides along inside its outer one
    rather than truncating it.
    """
    tables: list[tuple[int, int]] = []
    pos = 0
    while (at := xml.find("<w:tbl>", pos)) != -1:
        end = matching_close(xml, at + len("<w:tbl>"), "tbl")
        tables.append((at, end))
        pos = end
    out: list[tuple[str, int, int]] = [("tbl", s, e) for s, e in tables]
    out += [("p", m.start(), m.end()) for m in PARA_RE.finditer(xml)
            if table_index_at(tables, m.start()) is None]
    out.sort(key=lambda el: el[1])
    return out


@dataclass(frozen=True)
class Site:
    """What is AT an edit site: everything an edit has to know first.

    Three facts decide whether an edit can be written: the exact string,
    whether the signature is UNIQUE, and what the match would have to
    cross. They lived in three separate commands, so every AFI r4 batch
    ran two or three and I wrote the same ad-hoc probe each time.

    `labels` is the load-bearing one. It is exactly the set
    :func:`docxkit.edit.replace_in_para` refuses to cut across, and on a
    manuscript whose citation labels include the year — "Kanbur 2007" —
    it is what says a "replace from the citation onward" edit starts
    INSIDE a link before the build says so.
    """

    #: 0-based paragraph index in this part; -1 when nothing matched.
    index: int
    #: How many paragraphs the signature matches. 0 and 2 are both
    #: answers, not errors: `para_slice` refuses either, and knowing
    #: which BEFORE writing the edit is the point.
    matches: int
    text: str
    #: The visible label of every internal link in the paragraph.
    labels: list[str]
    has_math: bool
    footnote_ids: list[str]
    #: Two spaces in a row, which Word does not show and a diff does.
    double_spaces: int
    trailing_space: bool

    def format(self) -> str:
        """One line per fact that IS the case, and the text last."""
        if not self.matches:
            return "no paragraph matches that signature"
        out = [f"paragraph {self.index}"
               + (f" (and {self.matches - 1} more match)" if self.matches > 1
                  else "")]
        if self.labels:
            out.append(f"  link labels: {self.labels} — an edit may not "
                       f"cross one without allow_hyperlink=True")
        if self.has_math:
            out.append("  holds an equation: text spanning it is not "
                       "findable by replace_in_para")
        if self.footnote_ids:
            out.append(f"  footnote marks: {self.footnote_ids}")
        if self.double_spaces:
            out.append(f"  {self.double_spaces} double space(s)")
        if self.trailing_space:
            out.append("  trailing space")
        return "\n".join([*out, f"  {self.text}"])


def site(xml: str, sig: str, *, normalize: bool = False) -> Site:
    """Survey the paragraph an edit is about to be written against.

    Read-only and refuses nothing — a signature matching none or two
    paragraphs is an ANSWER here, and the answer a caller wants before
    `para_slice` raises on it at build time.

    The FIRST match is described when there are several, because that is
    the one every anchor-taking routine in this package would act on.
    """
    fold = normalize_glyphs if normalize else (lambda s: s)
    needle = fold(sig)
    hits = [(i, m) for i, m in enumerate(PARA_RE.finditer(xml))
            if needle in fold(visible_text(m.group(0)))]
    if not hits:
        return Site(index=-1, matches=0, text="", labels=[], has_math=False,
                    footnote_ids=[], double_spaces=0, trailing_space=False)
    i, m = hits[0]
    para = m.group(0)
    text = visible_text(para)
    return Site(
        index=i,
        matches=len(hits),
        text=text,
        labels=[label for _anchor, label in internal_links(para)],
        # the substring, not a second spelling of `equations.OMATH_RE`:
        # this asks whether one is THERE, which is a presence check
        has_math="<m:oMath" in para,
        footnote_ids=NOTE_REF_RE["footnote"].findall(para),
        double_spaces=text.count("  "),
        trailing_space=text != text.rstrip())
