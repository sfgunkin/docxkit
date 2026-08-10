r"""Bidirectional Figure/Table cross-references.

Every figure and table mentioned in the text should be clickable, and the
object should link back to where it was discussed. That needs a bookmark
at each end and a hyperlink in each direction:

===============  ==========================================  ==============
where            bookmark                                    links to
===============  ==========================================  ==============
in-text mention  ``Table1txt``  (object name + ``txt``)       ``Table1``
the caption      ``Table1``     (the object name)             ``Table1txt``
===============  ==========================================  ==============

So "as shown in Table 1" becomes a link to the table, and the table's
"Table 1." caption label becomes a link back to that sentence.

Only the FIRST mention is linked. Bookmark names are unique within a
document, so `Table1txt` can only mark one place; the first mention is
where a reader wants to jump back to anyway.

Four rules here are not obvious, and each one came from a document that
broke without it:

* **"Figure 1" must not match "Figure 10".** The mention pattern ends
  with a negative lookahead on another digit.
* **A caption is a label, a number, AND a separator** ("Figure 7." or
  "Таблица 2:"). Merely starting with "Figure" is not enough — an
  ordinary sentence does too, and counting those found 18 figures in a
  14-figure paper.
* **Caption paragraphs are skipped when hunting the first mention**, or
  every object links to itself.
* **Splitting a run keeps its original properties.** The label becomes
  its own run and the text around it keeps the formatting it had;
  rebuilding the run from scratch silently drops italics and language
  tags.

Word bookmark names admit only letters, digits and underscore, so a
number like "3.2" becomes ``Table3_2``. Everything is idempotent: a
document already linked is left alone, which is what makes this safe to
run on every build.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import NamedTuple

from ._xml import (
    BOOKMARK_ID_RE,
    PARA_RE,
    T_RE,
    WT_RE,
    own_properties,
    visible_text,
)
from .citations import next_bookmark_id
from .errors import AnchorError, ConversionGap

__all__ = [
    "Caption",
    "LinkReport",
    "anchor_names",
    "audit",
    "caption_re",
    "field_targets",
    "find_captions",
    "link",
    "unlink",
]

#: Caption words recognised by default. Add the paper's own if it writes
#: them differently — DSI's Russian manuscripts use Рисунок/Таблица.
DEFAULT_LABELS = ("Figure", "Table", "Рисунок", "Таблица")

#: How each label may appear in PROSE, which is not how it appears in the
#: caption. English merely pluralises; Russian inflects, so the DSI
#: manuscript writes «Таблица 4» over the table and «в таблице 4» in the
#: text. Matching only the caption form linked nothing at all there.
#: A label with no entry falls back to itself plus an optional "s".
LABEL_FORMS = {
    "Figure": r"Figures?",
    "Table": r"Tables?",
    "Рисунок": r"рисун\w{0,3}",     # рисунок / рисунка / рисунке / рисунком
    "Таблица": r"таблиц\w{0,2}",    # таблица / таблице / таблицы / таблиц
}

_SUFFIX = "txt"
_BOOKMARK_RE = BOOKMARK_ID_RE          # the shared definition
# (?<!/)> — a self-closing empty hyperlink must not read as an open tag;
# see the twin note on _xml._HYPERLINK_EL_RE.
_HYPERLINK_RE = re.compile(r"<w:hyperlink\b[^>]*(?<!/)>.*?</w:hyperlink>",
                           re.DOTALL)
_PPR_RE = re.compile(r"<w:pPr>.*?</w:pPr>", re.DOTALL)
_P_OPEN_RE = re.compile(r"<w:p\b[^>]*>")
_RPR_RE = re.compile(r"<w:rPr>.*?</w:rPr>", re.DOTALL)
# a bookmark name Word will accept: letters, digits, underscore
_UNSAFE_RE = re.compile(r"[^0-9A-Za-z_]")
#: ``HYPERLINK \l "Anchor" \h`` inside a field instruction. Word splits
#: instrText across runs, so the quoted anchor is matched on its own
#: rather than the whole instruction.
_FIELD_ANCHOR_RE = re.compile(
    r'<w:instrText[^>]*>[^<]*?HYPERLINK\s+\\l\s+"([^"]+)"', re.DOTALL)


def anchor_names(label: str, number: str) -> tuple[str, str]:
    """``("Table", "1")`` -> ``("Table1", "Table1txt")``.

    The first is the bookmark on the object's caption, the second the
    bookmark on the in-text mention.
    """
    name = f"{label}{_UNSAFE_RE.sub('_', number)}"
    return name, name + _SUFFIX


@dataclass(frozen=True)
class Caption:
    """A caption paragraph: what it labels, and where it sits."""

    label: str                  # "Figure" / "Table"
    number: str                 # "1", "A2", "3.2"
    text: str                   # the caption's visible text
    start: int                  # span of the <w:p> within the part
    end: int

    @property
    def name(self) -> str:
        """The bookmark on this caption — ``Table1``."""
        return anchor_names(self.label, self.number)[0]

    @property
    def mention_name(self) -> str:
        """The bookmark on the in-text mention — ``Table1txt``."""
        return anchor_names(self.label, self.number)[1]

    @property
    def prefix(self) -> str:
        """The label as it reads in the caption — ``Table 1``."""
        return f"{self.label} {self.number}"


@dataclass
class LinkReport:
    """What :func:`link` did, per object."""

    linked: list[str] = field(default_factory=list)
    already_linked: list[str] = field(default_factory=list)
    no_mention: list[str] = field(default_factory=list)
    no_caption: list[str] = field(default_factory=list)
    #: Anchors already reached by a HYPERLINK FIELD. link() cannot see
    #: those, so it treats the object as unlinked and adds an element
    #: link on top — two schemes over one caption. Reported rather than
    #: raised: linking the REST of the document is still worth doing.
    field_form: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """True when every caption found a mention to pair with."""
        return not self.no_mention and not self.no_caption

    def format(self) -> str:
        lines = [(f"linked {len(self.linked)}, already linked "
                  f"{len(self.already_linked)}")]
        if self.no_mention:
            lines.append(f"  no in-text mention: {', '.join(self.no_mention)}")
        if self.no_caption:
            lines.append(f"  mentioned but no caption: "
                         f"{', '.join(self.no_caption)}")
        if self.field_form:
            lines.append(f"  ALREADY LINKED BY A WORD FIELD, which link() "
                         f"cannot see — check for a doubled link: "
                         f"{', '.join(self.field_form)}")
        for name, note in sorted(self.notes.items()):
            lines.append(f"  {name}: {note}")
        return "\n".join(lines)


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
    alt = "|".join(re.escape(w) for w in labels)
    return re.compile(rf"^\s*({alt})\s+([\w.-]+?)\s*[.:]\s")


#: What may not follow an exhibit number. THE boundary — :mod:`renumber`
#: matches mentions too, and a rule that lives in two modules is a rule
#: that will disagree with itself.
#:
#: Rejecting a following DIGIT is what keeps "Table 1" out of "Table 10",
#: but digits alone are not enough: papers number exhibits "Table 1.1"
#: and "Table 1A", and against those the digit test passes and the match
#: lands on a DIFFERENT exhibit. It linked the "Table 1" inside "Table
#: 1.1", left ".1" as plain text, and then reported Table 1.1 as never
#: mentioned — and in :mod:`renumber`, which rewrites text, a shift of
#: Table 1 silently renumbered Table 1.1 along with it.
#:
#: The dot is refused only when a word character follows, because the
#: overwhelmingly common thing after a mention is a full stop: "the
#: estimates appear in Table 1." must still match.
#:
#: The hyphen splits the same way and for the same reason. "Table 1-A"
#: is another exhibit, so matching Table 1 inside it linked the wrong
#: one and orphaned "-A" as plain text; but "Tables 1-3" is a RANGE, and
#: refusing every hyphen would stop the 1 there being linked at all. A
#: digit after the hyphen continues a range, a letter starts a suffix.
NUMBER_END = r"(?!\w)(?!\.\w)(?!-[^\W\d_])"


@lru_cache(maxsize=256)
def _named_bookmark(name: str) -> re.Pattern[str]:
    """``<w:bookmarkStart ... w:name="NAME">`` — the element, not the text.

    Attribute order is not meaningful, so w:name may precede w:id.
    """
    return re.compile(rf'<w:bookmarkStart\b[^>]*w:name="{re.escape(name)}"')


def _mention_re(label: str, number: str) -> re.Pattern[str]:
    """``Figure 1`` but never ``Figure 10``, ``Figure 1.1`` or ``Figure 1A``.

    Case-insensitive: prose writes "table 1" and «таблице 1» as readily
    as the capitalised form.
    """
    form = LABEL_FORMS.get(label, re.escape(label) + "s?")
    return re.compile(rf"\b{form}\s+{re.escape(number)}{NUMBER_END}",
                      re.IGNORECASE)


def _next_bookmark_id(xml: str, others: Sequence[str] = ()) -> int:
    """The next free bookmark id ACROSS the package.

    Bookmark ids must be unique document-wide, not part-wide: a figure
    bookmark minted from the body alone can collide with one already
    living in footnotes.xml, and Word pairs start/end by id.
    :mod:`docxkit.citations` has always passed every part here; this
    module used to pass only the body.
    """
    return next_bookmark_id(xml, *others)


def find_captions(xml: str, *,
                  labels: tuple[str, ...] = DEFAULT_LABELS) -> list[Caption]:
    """Every caption paragraph, in document order.

    Cached: audit() runs on top of this and callers ask for both in the
    same breath, which re-walked every paragraph of the document.
    Caption is frozen, so sharing instances is safe; the public list is
    a copy so a caller mutating it cannot poison the cache.
    """
    return list(_find_captions(xml, labels))


@lru_cache(maxsize=8)
def _find_captions(xml: str,
                   labels: tuple[str, ...]) -> tuple[Caption, ...]:
    pattern = caption_re(labels)
    out = []
    for p in PARA_RE.finditer(xml):
        text = visible_text(p.group(0)).strip()
        if (m := pattern.match(text)) is not None:
            out.append(Caption(label=m.group(1), number=m.group(2),
                               text=text, start=p.start(), end=p.end()))
    return tuple(out)


_RSTYLE_RE = re.compile(r"<w:rStyle [^>]*/>")


def _with_hyperlink_style(rpr: str) -> str:
    """Run properties with the Hyperlink character style added.

    Idempotent, and never leaves TWO rStyle children: the schema allows
    one, and a run can arrive already styled. :func:`unlink_by_anchor`
    deliberately leaves run properties alone when it unwraps a link
    ("stripping a legacy link's explicit colouring is a formatting
    decision, not a linking one"), so a wipe-and-rebuild round hands
    every former link run straight back here still carrying its
    Hyperlink style. Prepending unconditionally built an rPr Word's
    schema rejects — 24 of them on Parental Style's R2 pass, and
    nothing but a lint run would have said so.
    """
    if not rpr:
        return '<w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
    if _RSTYLE_RE.search(rpr):
        # a run becoming a hyperlink carries the Hyperlink style; any
        # other character style already on it is replaced, never doubled
        return _RSTYLE_RE.sub('<w:rStyle w:val="Hyperlink"/>', rpr, count=1)
    return rpr.replace("<w:rPr>",
                       '<w:rPr><w:rStyle w:val="Hyperlink"/>', 1)


class _RunParts(NamedTuple):
    """One run, cut around the ``w:t`` a label was found in."""

    open_tag: str
    rpr: str
    pre: str            # children between the properties and that w:t
    post: str           # children between that w:t and </w:r>


def _run_parts(run_xml: str, t_start: int, t_end: int) -> _RunParts:
    """Split a run so that NOTHING in it is lost when it is rebuilt.

    A ``w:r`` is not "properties plus one ``w:t``". It may hold several
    text nodes — Word splits them at rsid boundaries — and alongside
    them a ``w:br``, a ``w:tab``, a ``w:drawing``, a ``w:footnoteReference``
    or a rendered page break. Rebuilding the run from its open tag, its
    properties and the ONE matched ``w:t`` silently drops every one of
    those: a caption stored as ``<w:t>Table 1. </w:t><w:t>Results</w:t>``
    came back reading "Table 1." with the title gone, and no text-level
    check would show it because the linker is not supposed to change
    text at all.

    `pre` rides with the first fragment emitted and `post` with the
    last, so the run's children keep their order and their count.
    """
    open_tag = run_xml[: run_xml.index(">") + 1]
    rpr_m = own_properties(run_xml, "rPr")
    rpr = run_xml[rpr_m[0]:rpr_m[1]] if rpr_m else ""
    body_from = rpr_m[1] if rpr_m else len(open_tag)
    close = run_xml.rfind("</w:r>")
    body_to = close if close != -1 else len(run_xml)
    return _RunParts(open_tag=open_tag, rpr=rpr,
                     pre=run_xml[body_from:t_start],
                     post=run_xml[t_end:body_to])


def _split_run_at(run_xml: str, content: str, m: re.Match[str], *,
                  t_span: tuple[int, int], anchor: str,
                  bookmark_name: str, bid: int) -> str:
    """Rewrite one run so the matched label is a bookmarked hyperlink.

    The text before and after the label keeps the run's own open tag and
    properties; only the label itself gains the Hyperlink character
    style. Rebuilding the surrounding text as a bare run instead is how
    italics and language tags get dropped.
    """
    cut = _run_parts(run_xml, *t_span)
    link_rpr = _with_hyperlink_style(cut.rpr)

    # NB: `content` is the RAW text of a w:t — already XML-escaped,
    # because it was read straight out of the document. Escaping it again
    # turns a caption reading "Income & wealth" into one reading
    # "Income &amp; wealth" ON THE PAGE. Found by the property suite.
    before, label, after = (content[:m.start()], content[m.start():m.end()],
                            content[m.end():])
    parts = []
    head = cut.pre                      # attaches to whatever comes first
    if before:
        parts.append(f'{cut.open_tag}{cut.rpr}{head}'
                     f'<w:t xml:space="preserve">{before}</w:t></w:r>')
        head = ""
    parts.append(
        f'<w:bookmarkStart w:id="{bid}" w:name="{bookmark_name}"/>'
        f'<w:hyperlink w:anchor="{anchor}">{cut.open_tag}{link_rpr}{head}'
        f'<w:t xml:space="preserve">{label}</w:t></w:r></w:hyperlink>'
        f'<w:bookmarkEnd w:id="{bid}"/>')
    tail = (f'<w:t xml:space="preserve">{after}</w:t>' if after else "")
    if tail or cut.post:
        parts.append(f"{cut.open_tag}{cut.rpr}{tail}{cut.post}</w:r>")
    return "".join(parts)


def _link_mention(para_xml: str, cap: Caption, bid: int,
                  own_anchors: frozenset[str] = frozenset(),
                  ) -> tuple[str, str]:
    """Bookmark and hyperlink the label inside one paragraph.

    Returns (new_paragraph, what_happened).
    """
    pattern = _mention_re(cap.label, cap.number)
    anchor, name = cap.name, cap.mention_name

    # The label may already be a hyperlink — a manual cross-reference, or
    # an earlier tool using a different naming scheme.
    for hm in _HYPERLINK_RE.finditer(para_xml):
        if not pattern.search("".join(T_RE.findall(hm.group(0)))):
            continue
        block = hm.group(0)
        existing = re.search(r'w:anchor="([^"]+)"', block)
        mode = "wrapped an existing hyperlink"
        if existing is not None and existing.group(1) != anchor:
            old = existing.group(1)
            if old in own_anchors:
                # A bookmark under a different name on THIS object's own
                # caption — AFI's `fig4_caption`, say. Same destination,
                # so point it at the conventional name.
                block = block.replace(f'w:anchor="{old}"',
                                      f'w:anchor="{anchor}"', 1)
                mode = f"retargeted legacy anchor {old!r}"
            else:
                # Points at something else entirely. AFI's "Figure 9.a"
                # deliberately links to Figure 7's caption; overwriting
                # that would silently break the author's cross-reference.
                mode = f"kept the author's own anchor {old!r}"
        return (para_xml[:hm.start()]
                + f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
                + block
                + f'<w:bookmarkEnd w:id="{bid}"/>'
                + para_xml[hm.end():]), mode

    # Plain text: find the <w:t> holding the label and split its run.
    for tm in WT_RE.finditer(para_xml):
        m = pattern.search(tm.group(1))
        if m is None:
            continue
        r_open = max(para_xml.rfind("<w:r>", 0, tm.start()),
                     para_xml.rfind("<w:r ", 0, tm.start()))
        if r_open < 0:
            continue
        r_close = para_xml.find("</w:r>", tm.end()) + len("</w:r>")
        run = para_xml[r_open:r_close]
        return (para_xml[:r_open]
                + _split_run_at(run, tm.group(1), m,
                                t_span=(tm.start() - r_open,
                                        tm.end() - r_open),
                                anchor=anchor, bookmark_name=name, bid=bid)
                + para_xml[r_close:]), "linked"
    return para_xml, "NOT-FOUND"


def _find_mention(xml: str, cap: Caption,
                  captions: list[Caption]) -> re.Match[str] | None:
    """The first body paragraph mentioning this object, captions excluded.

    Without the exclusion an object links to its own caption, since the
    caption contains the label too.
    """
    pattern = _mention_re(cap.label, cap.number)
    caption_spans = {(c.start, c.end) for c in captions}
    for p in PARA_RE.finditer(xml):
        if (p.start(), p.end()) in caption_spans:
            continue
        if pattern.search(visible_text(p.group(0))):
            return p
    return None


def _caption_bookmarks(xml: str, cap: Caption) -> frozenset[str]:
    """Names of bookmarks that already sit on this caption's paragraph.

    A link aimed at one of these reaches this object under an older
    name, so it can be retargeted safely. Resolving it by POSITION
    rather than by guessing at legacy naming schemes means this works
    for whatever convention the paper used before.

    The gap before the paragraph counts too: a zero-length bookmark
    often sits BETWEEN paragraphs, as a sibling of the caption rather
    than inside it, and navigating to it still lands on the caption.
    AFI's `fig4_caption` is placed exactly there.
    """
    prev_close = xml.rfind("</w:p>", 0, cap.start)
    gap_from = prev_close + len("</w:p>") if prev_close != -1 else 0
    scope = xml[gap_from:cap.end]
    return frozenset(
        re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"', scope))


def _backlink_caption(para_xml: str, cap: Caption, bid: int) -> str:
    """Bookmark the caption and make its label link back to the mention.

    The bookmark wraps the caption's content — it marks the title, so a
    forward link lands on the caption itself rather than on whatever
    blank line precedes it.
    """
    anchor = cap.mention_name
    if f'w:anchor="{anchor}"' not in para_xml:
        para_xml = _wrap_label(para_xml, cap, anchor)
    return _wrap_paragraph_in_bookmark(para_xml, cap.name, bid)


def _wrap_label(para_xml: str, cap: Caption, anchor: str) -> str:
    """Turn the caption's leading "Table 1" into a link to `anchor`."""
    # A caption often separates label from number with a non-breaking
    # space, which visible_text preserves, so match both forms.
    candidates = (cap.prefix, cap.prefix.replace(" ", "\u00a0"))
    for tm in WT_RE.finditer(para_xml):
        content = tm.group(1)
        label = next((cand for cand in candidates
                      if content.lstrip().startswith(cand)), None)
        if label is None:
            continue
        # same rule as _split_run_at: these are raw, already-escaped
        # slices of the source, so they are re-emitted verbatim
        lead = content[:len(content) - len(content.lstrip())]
        raw_label = content.lstrip()[:len(label)]
        rest = content.lstrip()[len(label):]

        r_open = max(para_xml.rfind("<w:r>", 0, tm.start()),
                     para_xml.rfind("<w:r ", 0, tm.start()))
        if r_open < 0:
            continue
        r_close = para_xml.find("</w:r>", tm.end()) + len("</w:r>")
        run = para_xml[r_open:r_close]
        # everything in the run that is not the matched w:t — a rendered
        # page break, a second text node, a footnote reference — has to
        # survive the rewrite, in its own order
        cut = _run_parts(run, tm.start() - r_open, tm.end() - r_open)
        link_rpr = _with_hyperlink_style(cut.rpr)

        new = ""
        head = cut.pre                  # attaches to whatever comes first
        if lead:
            new += (f'{cut.open_tag}{cut.rpr}{head}'
                    f'<w:t xml:space="preserve">{lead}</w:t></w:r>')
            head = ""
        new += (f'<w:hyperlink w:anchor="{anchor}">'
                f'{cut.open_tag}{link_rpr}{head}'
                f'<w:t xml:space="preserve">{raw_label}</w:t></w:r>'
                "</w:hyperlink>")
        tail = f'<w:t xml:space="preserve">{rest}</w:t>' if rest else ""
        if tail or cut.post:
            new += f"{cut.open_tag}{cut.rpr}{tail}{cut.post}</w:r>"
        return para_xml[:r_open] + new + para_xml[r_close:]
    raise AnchorError(
        f"{cap.prefix}: caption label is split across runs and could not be "
        f"wrapped in a back-link ({visible_text(para_xml)[:60]!r})")


def _wrap_paragraph_in_bookmark(para_xml: str, name: str, bid: int) -> str:
    """Put a bookmark around a paragraph's content, after any ``w:pPr``."""
    # The bookmark ELEMENT, not the string: `w:name="Table1"` occurring
    # anywhere — in a w:t, in some other element's attribute — read as
    # "already bookmarked" and the caption silently got none.
    if _named_bookmark(name).search(para_xml):
        return para_xml
    if (mpp := own_properties(para_xml, "pPr")) is not None:
        at = mpp[1]
    elif (popen := _P_OPEN_RE.match(para_xml)) is not None:
        at = popen.end()
    else:
        raise AnchorError(f"{name}: caption block is not a <w:p>")
    close = para_xml.rfind("</w:p>")
    return (para_xml[:at]
            + f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
            + para_xml[at:close]
            + f'<w:bookmarkEnd w:id="{bid}"/>'
            + para_xml[close:])


def link(xml: str, *, labels: tuple[str, ...] = DEFAULT_LABELS,
         only: list[str] | None = None,
         other_parts: Sequence[str] = ()) -> tuple[str, LinkReport]:
    """Cross-link every figure and table with its first in-text mention.

    Idempotent: an object already carrying both bookmarks is left
    untouched, so this can run on every build. `only` restricts the work
    to named objects (``["Table1", "Figure3"]``).

    Returns the rewritten part and a :class:`LinkReport`. Objects whose
    caption or mention is missing are REPORTED, not raised — a paper
    legitimately has tables it never names in prose, and failing the
    build over one would be worse than saying so.

    Pass `other_parts` (footnotes.xml, endnotes.xml — every part the
    document also bookmarks) so the new ids cannot collide with one
    already in use there; ids are unique document-wide, not part-wide.
    """
    report = LinkReport()
    captions = find_captions(xml, labels=labels)
    seen: set[str] = set()
    fielded = field_targets(xml)

    for cap in captions:
        if only is not None and cap.name not in only:
            continue
        if cap.name in seen:
            report.notes[cap.name] = "duplicate caption; only the first linked"
            continue
        seen.add(cap.name)

        if (_named_bookmark(cap.name).search(xml)
                and _named_bookmark(cap.mention_name).search(xml)):
            report.already_linked.append(cap.name)
            continue

        # A field already points here. We cannot see it to skip it the way
        # the element check above does, so linking would stack a second
        # scheme on the same caption. Say so; do not silently double it.
        if fielded & {cap.name, cap.mention_name}:
            report.field_form.append(cap.name)
            continue

        # Re-find the caption: earlier edits have shifted every offset.
        current = next((c for c in find_captions(xml, labels=labels)
                        if c.name == cap.name), None)
        if current is None:                     # pragma: no cover - defensive
            continue

        mention = _find_mention(xml, current,
                                find_captions(xml, labels=labels))
        if mention is None:
            report.no_mention.append(cap.name)
            continue

        bid = _next_bookmark_id(xml, other_parts)
        new_para, mode = _link_mention(mention.group(0), current, bid,
                                       _caption_bookmarks(xml, current))
        if mode == "NOT-FOUND":
            # visible_text found the label but it is split across runs
            report.notes[cap.name] = (
                "mention found but its label is split across runs")
            report.no_mention.append(cap.name)
            continue
        if mode != "linked":
            report.notes[cap.name] = mode
        xml = xml[:mention.start()] + new_para + xml[mention.end():]

        # offsets moved again; re-find the caption before touching it
        current = next((c for c in find_captions(xml, labels=labels)
                        if c.name == cap.name), None)
        if current is None:                     # pragma: no cover - defensive
            continue
        bid = _next_bookmark_id(xml, other_parts)
        para = xml[current.start:current.end]
        xml = (xml[:current.start] + _backlink_caption(para, current, bid)
               + xml[current.end:])
        report.linked.append(cap.name)

    # Mentions with no caption to point at — a figure that was deleted
    # without its references being cleaned up.
    #
    # Restricted to names that start with a caption label. The same
    # `<name>txt` convention is used for CITATIONS in these papers
    # (`Halliday2020txt`), and matching every bookmark ending in "txt"
    # reported 48 of them as missing figures.
    alt = "|".join(re.escape(w) for w in labels)
    mention_re = re.compile(rf'w:name="((?:{alt})[0-9A-Za-z_]*)txt"')
    named = {c.name for c in captions}
    for name in sorted(set(mention_re.findall(xml))):
        if name not in named:
            report.no_caption.append(name)
    return xml, report


def audit(xml: str, *,
          labels: tuple[str, ...] = DEFAULT_LABELS,
          also: str | Iterable[str] = ()) -> dict[str, list[str]]:
    """Report the cross-reference state without changing anything.

    Keys: ``linked`` (both bookmarks present), ``caption_only``,
    ``mention_only``, ``dangling`` — hyperlinks pointing at a bookmark
    no longer in the document, which is what a deleted figure leaves
    behind — and ``misnamed``: a caption carrying an exhibit bookmark
    whose NUMBER is not the caption's, which is what a renumbering
    leaves behind (LI7's "Figure 5" caption carries bookmark Figure6;
    every link still works, one renumbering behind).

    Pass the other bookmarked parts (footnotes.xml, endnotes.xml) as
    `also`. **A link and its bookmark need not live in the same part**:
    a work cited only in a footnote carries its in-text bookmark in
    footnotes.xml while the reference entry links to it from the body.
    Reading the body alone reported four such pairs as ``dangling`` on
    Parental Style, and the false flag was written down as a known
    quirk twice before it was read as the bug it is. Captions are still
    sought in `xml` only — those live in the body.
    """
    others = [also] if isinstance(also, str) else list(also)
    every = [xml, *others]
    names = {n for part in every
             for n in re.findall(
                 r'<w:bookmarkStart[^>]*w:name="([^"]+)"', part)}
    anchors = {a for part in every
               for a in re.findall(
                   r'<w:hyperlink[^>]*w:anchor="([^"]+)"', part)}

    exhibit_re = re.compile(
        rf"^({'|'.join(re.escape(w) for w in labels)})(\d+)$")
    linked, caption_only, mention_only, misnamed = [], [], [], []
    for cap in find_captions(xml, labels=labels):
        has_cap = cap.name in names
        has_txt = cap.mention_name in names
        if has_cap and has_txt:
            linked.append(cap.name)
        elif has_cap:
            caption_only.append(cap.name)
        elif has_txt:
            mention_only.append(cap.name)
        for nm in re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]+)"',
                             xml[cap.start:cap.end]):
            em = exhibit_re.match(nm)
            if em and (em.group(1) != cap.label
                       or em.group(2) != cap.number):
                misnamed.append(f"{nm} on the '{cap.prefix}' caption")
    return {
        "linked": sorted(linked),
        "caption_only": sorted(caption_only),
        "mention_only": sorted(mention_only),
        "dangling": sorted(a for a in anchors if a not in names),
        "misnamed": sorted(misnamed),
    }


def _continuation_re(label: str, number: str) -> re.Pattern[str]:
    """The bare number of a range or list mention: the "5" of "Tables 3
    to 5", "Tables 3–5" or "Tables 3, 4 and 5".

    Anchored to a nearby plural-capable label so "age 3 to 5" cannot
    match; the window between the label's own number and the target is
    kept short and clause-bound for the same reason.
    """
    form = LABEL_FORMS.get(label, re.escape(label) + "s?")
    return re.compile(
        rf"\b{form}\s+[\wА-я.]+[^.;:()]{{0,30}}?"
        rf"(?:\band\b|\bto\b|[–—,-])\s*({re.escape(number)}){NUMBER_END}",
        re.IGNORECASE)


def link_more(xml: str, *, labels: tuple[str, ...] = DEFAULT_LABELS,
              ) -> tuple[str, dict[str, int]]:
    """Forward-link every exhibit mention :func:`link` left plain.

    :func:`link` bookmarks and back-links only the FIRST mention; house
    style for the rest is a forward hyperlink to the caption and nothing
    pointing back, so this pass wraps each remaining plain mention —
    range and list continuations included ("Tables 3 to 5" links the 3
    under Table3 and the 5 under Table5). Caption paragraphs are
    skipped, already-linked spans are masked out, and a second run is a
    no-op. Run it AFTER :func:`link`.

    Returns ``(xml, {caption name: mentions linked})``.
    """
    from .citations import masked_visible_text, wrap_visible_span

    captions = find_captions(xml, labels=labels)
    counts: dict[str, int] = {}
    caption_spans = {(c.start, c.end) for c in captions}
    patterns = [(cap, _mention_re(cap.label, cap.number),
                 _continuation_re(cap.label, cap.number))
                for cap in captions]

    paras = list(PARA_RE.finditer(xml))
    for pm in reversed(paras):
        if (pm.start(), pm.end()) in caption_spans:
            continue
        para = pm.group(0)
        masked = masked_visible_text(para)
        if not masked.strip("\x00 \t"):
            continue
        todo: list[tuple[int, int, str]] = []
        claimed: set[tuple[int, int]] = set()
        for cap, main, cont in patterns:
            for m in main.finditer(masked):
                span = (m.start(), m.end())
                if "\x00" in masked[span[0]:span[1]] or span in claimed:
                    continue
                claimed.add(span)
                todo.append((span[0], span[1], cap.name))
            for m in cont.finditer(masked):
                span = (m.start(1), m.end(1))
                if "\x00" in masked[span[0]:span[1]] or span in claimed:
                    continue
                claimed.add(span)
                todo.append((span[0], span[1], cap.name))
        if not todo:
            continue
        for at, end, anchor in sorted(todo, reverse=True):
            para = wrap_visible_span(para, at, end, anchor)
            counts[anchor] = counts.get(anchor, 0) + 1
        xml = xml[:pm.start()] + para + xml[pm.end():]
    return xml, counts


def field_targets(xml: str) -> set[str]:
    """Anchors reached by a Word HYPERLINK FIELD rather than an element.

    ``link`` and ``unlink`` only understand element-form
    ``<w:hyperlink w:anchor="...">``. The same link can equally be a
    field — ``<w:instrText>HYPERLINK \\l "X" \\h</w:instrText>`` between
    fldChars — and a manuscript can hold both forms at once. Parental_style
    holds 53 element and 160 field, and there is nothing in the rendered
    page to tell them apart.
    """
    return {m.group(1) for m in _FIELD_ANCHOR_RE.finditer(xml)}


def unlink(xml: str, *,
           labels: tuple[str, ...] = DEFAULT_LABELS) -> tuple[str, int]:
    """Remove the cross-reference bookmarks and unwrap their hyperlinks.

    For rebuilding from scratch when numbering has changed. Hyperlinks
    pointing anywhere else — a citation, a URL — are left alone.

    Raises :class:`ConversionGap` if any exhibit link is FIELD form.
    Removing the bookmarks while leaving those fields standing is not a
    partial success, it is a wrong answer that reports a healthy count:
    on Parental_style it said "24 removed" and left every caption link
    live, which was found only much later and by hand.
    """
    ours: set[str] = set()
    for cap in find_captions(xml, labels=labels):
        ours.update((cap.name, cap.mention_name))
    if not ours:
        return xml, 0

    fielded = sorted(ours & field_targets(xml))
    if fielded:
        raise ConversionGap(
            f"{len(fielded)} exhibit link(s) are Word FIELD form, which "
            f"unlink cannot see or remove: {', '.join(fielded[:6])}"
            + (" ..." if len(fielded) > 6 else "")
            + ". Removing the bookmarks alone would leave the links live "
              "and report success. Retarget the fields in place instead "
              "(swap the anchor names), or convert them to element form "
              "first.")

    removed = 0
    for name in sorted(ours):
        m = re.search(rf'<w:bookmarkStart[^>]*w:name="{re.escape(name)}"\s*/>',
                      xml)
        if m is None:
            continue
        bid = re.search(r'w:id="(\d+)"', m.group(0))
        xml = xml[:m.start()] + xml[m.end():]
        if bid is not None:
            xml = re.sub(rf'<w:bookmarkEnd w:id="{bid.group(1)}"\s*/>', "",
                         xml, count=1)
        removed += 1

    def _unwrap(m: re.Match[str]) -> str:
        anchor = re.search(r'w:anchor="([^"]+)"', m.group(0))
        if anchor is None or anchor.group(1) not in ours:
            return m.group(0)
        inner = re.sub(r"</?w:hyperlink[^>]*>", "", m.group(0))
        return re.sub(r'<w:rStyle w:val="Hyperlink"/>', "", inner)

    return _HYPERLINK_RE.sub(_unwrap, xml), removed
