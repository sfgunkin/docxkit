r"""Shifting exhibit numbers: captions, mentions, bookmarks, fields.

Inserting "Table 3" into a paper with ten tables means every later
table's caption, every prose mention of it, both of its cross-reference
bookmarks and every field pointing at them must move up by one — and a
miss is invisible until a referee follows "see Table 7" to the wrong
exhibit. The mechanics are the same in every paper; only WHICH exhibit
is being inserted is the paper's decision.

Two properties the implementation is built around:

* **Every replacement is computed from the original number in place**, a
  single pass with a callback — never "replace 5 with 6, then 6 with 7",
  which double-shifts whatever it touches twice.
* **Only the digits are rewritten.** The label word stays exactly as the
  prose inflects it («таблице 4» keeps its case ending), and the
  replacement is located through the paragraph's VISIBLE text, so a
  number Word split across runs still shifts.

Numbers in list or range constructions ("Tables 5–7", "Tables 5 and 6")
are left alone and reported instead: shifting the labelled 5 while the
bare 7 stays put corrupts the sentence, and only the author knows what
it should now say.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ._xml import DOCUMENT, RUN_RE, set_run_text, text_parts, visible_text
from .crossrefs import LABEL_FORMS, NUMBER_END, find_captions
from .errors import AnchorError
from .find import paragraphs

__all__ = ["ShiftReport", "audit", "audit_parts", "numbers_in_order",
           "remap", "remap_parts", "shift"]

# a mention number engaged in a range or list — the continuation the
# labelled match must not have after it
_CONTINUATION = r"\s*(?:[-–—,]|\band\b|\bи\b)\s*[A-Za-z]?\d"


@dataclass
class ShiftReport:
    """What :func:`shift` changed, and what it refused to guess at."""

    mentions: int = 0        # prose + caption occurrences rewritten
    bookmarks: int = 0       # w:name attributes
    anchors: int = 0         # w:anchor attributes on hyperlinks
    fields: int = 0          # REF instructions in field code
    flagged: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [(f"mentions {self.mentions}, "
                  f"bookmarks {self.bookmarks}, "
                  f"anchors {self.anchors}, fields {self.fields}")]
        lines += [f"  left for the author: {snippet}"
                  for snippet in self.flagged]
        return "\n".join(lines)


def _mention_re(label: str, prefix: str) -> re.Pattern[str]:
    # NUMBER_END, not a bare (?!\d): shifting "Table 1" used to rewrite
    # the 1 of "Table 1.1" and "Table 1A" too, silently renumbering an
    # exhibit the caller never named. Those are FLAGGED instead now.
    form = LABEL_FORMS.get(label, re.escape(label) + "s?")
    return re.compile(
        rf"\b(?:{form})\s+{re.escape(prefix)}(\d+){NUMBER_END}",
        re.IGNORECASE)


#: a number this module will not shift: "1A", "1.1" — a numbering scheme
#: it does not model, and guessing at one corrupts the manuscript.
#: NOT `\w`: that class includes digits, so `\d+` would give one back and the
#: "suffix" would match it — every TWO-DIGIT exhibit was flagged as a scheme
#: this module refuses to touch. Single-digit exhibits shifted; everything from
#: ten upwards was reported as the author's problem, in every paper long enough
#: to have ten of them.
_SUFFIXED = r"(?:\.\w|[^\W\d_])"


def _flag_re(label: str, prefix: str) -> re.Pattern[str]:
    form = LABEL_FORMS.get(label, re.escape(label) + "s?")
    return re.compile(
        rf"\b(?:{form})\s+{re.escape(prefix)}\d+"
        rf"(?:{_CONTINUATION}|{_SUFFIXED})",
        re.IGNORECASE)


def _shift_in_para(para_xml: str, pattern: re.Pattern[str],
                   remap_fn: Callable[[int], int]) -> tuple[str, int]:
    """Rewrite the DIGIT spans of qualifying mentions in one paragraph.

    Matches are located in the paragraph's visible text and mapped back
    to runs, so fragmentation does not hide a mention; the digits of one
    number may themselves span runs. Replacements are applied to the
    per-run texts from the highest offset down, which keeps every earlier
    offset valid however the lengths change.
    """
    runs = list(RUN_RE.finditer(para_xml))
    texts = [visible_text(r.group(0)) for r in runs]
    # `texts` mutates as edits land, so offsets index these ORIGINALS
    lens = [len(t) for t in texts]
    starts, cursor = [], 0
    for n in lens:
        starts.append(cursor)
        cursor += n
    visible = "".join(texts)

    hits = []
    for m in pattern.finditer(visible):
        n = int(m.group(1))
        if remap_fn(n) == n:
            continue
        if re.match(_CONTINUATION, visible[m.end():]):
            continue                    # range/list: flagged by the caller
        hits.append((m.span(1), n))
    if not hits:
        return para_xml, 0

    changed = set()
    for (a, b), n in sorted(hits, reverse=True):
        new = str(remap_fn(n))
        # runs overlapping the digit span, first gets the new text
        first = True
        for i in range(len(runs)):
            rs, re_ = starts[i], starts[i] + lens[i]
            if re_ <= a or rs >= b:
                continue
            head = texts[i][:max(0, a - rs)]
            tail = texts[i][max(0, min(len(texts[i]), b - rs)):]
            texts[i] = head + (new if first else "") + tail
            changed.add(i)
            first = False

    out = para_xml
    for i in sorted(changed, reverse=True):
        r = runs[i]
        out = (out[:r.start()] + set_run_text(r.group(0), texts[i])
               + out[r.end():])
    return out, len(hits)


def _shift_names(xml: str, label: str, prefix: str,
                 remap_fn: Callable[[int], int]) -> tuple[str, int, int, int]:
    """Bookmark names, hyperlink anchors and REF fields, one pass each."""
    base = re.escape(label) + re.escape(prefix)
    counts = {"w:name": 0, "w:anchor": 0, "ref": 0}

    def bump(number: str) -> str:
        return str(remap_fn(int(number)))

    attr_re = re.compile(rf'((?:w:name|w:anchor)="){base}(\d+)(txt)?(")')

    def attr_sub(m: re.Match[str]) -> str:
        new = bump(m.group(2))
        if new != m.group(2):
            counts["w:name" if m.group(1).startswith('w:name') else
                   "w:anchor"] += 1
        return (m.group(1) + label + prefix + new + (m.group(3) or "")
                + m.group(4))

    xml = attr_re.sub(attr_sub, xml)

    # REF fields and the HYPERLINK-field form of an internal link. BOTH are
    # needed: `crossrefs.link` writes `HYPERLINK \l "Table3txt"` field
    # instructions, not w:anchor attributes, and renaming the bookmarks
    # without them leaves every link pointing at the exhibit that used to
    # hold the name. Under a PERMUTATION nothing dangles — the set of names
    # is unchanged — so an audit sees no broken anchors and the reader is
    # simply sent to the wrong table.
    field_re = re.compile(
        rf'(\bREF\s+|\bHYPERLINK\s+\\l\s+"){base}(\d+)(txt)?\b')

    def field_sub(m: re.Match[str]) -> str:
        new = bump(m.group(2))
        if new != m.group(2):
            counts["ref"] += 1
        return m.group(1) + label + prefix + new + (m.group(3) or "")

    xml = field_re.sub(field_sub, xml)
    return xml, counts["w:name"], counts["w:anchor"], counts["ref"]


def shift(xml: str, label: str, *, frm: int, by: int = 1,
          prefix: str = "") -> tuple[str, ShiftReport]:
    """Shift every `label` exhibit numbered >= `frm` by `by`.

    To INSERT a new Table 3, shift first — ``shift(xml, "Table",
    frm=3)`` — then insert the caption into the freed number. To REMOVE
    Table 3, delete its caption and block, then ``shift(xml, "Table",
    frm=4, by=-1)``.

    `prefix` handles appendix numbering: ``prefix="A"`` shifts
    "Table A3" and the ``TableA3`` bookmarks, and leaves the main
    sequence alone. Integer numbering only — a "Table 3.2" scheme never
    appears in these papers and is not guessed at.

    Refuses a shift that would collide two captions (removing Table 3's
    number without removing its caption first), and refuses ``by=0``.
    Returns the new XML and a :class:`ShiftReport`; read ``flagged``
    before shipping — those are the range and list mentions ("Tables
    5–7") only the author can rewrite.
    """
    if by == 0:
        raise AnchorError("shift: by=0 would rewrite nothing")
    if frm + by < 1:
        raise AnchorError(f"shift: {frm} by {by} produces numbers below 1")

    numbers = []
    for cap in find_captions(xml, labels=(label,)):
        if prefix and not cap.number.startswith(prefix):
            continue
        digits = cap.number[len(prefix):]
        if digits.isdigit():
            numbers.append(int(digits))
    shifted = {n + by if n >= frm else n for n in numbers}
    if len(shifted) < len(set(numbers)):
        raise AnchorError(
            f"shift: captions {sorted(set(numbers))} would collide at "
            f"{sorted(shifted)} - remove or renumber the caption in the "
            f"way first")

    return _apply(xml, label, prefix,
                  lambda n: n + by if n >= frm else n)


def _apply(xml: str, label: str, prefix: str,
           remap_fn: Callable[[int], int]) -> tuple[str, ShiftReport]:
    """The one pass both `shift` and `remap` run: mentions, then names."""
    report = ShiftReport()
    mention = _mention_re(label, prefix)
    flag = _flag_re(label, prefix)
    out = []
    for p in paragraphs(xml):
        text = visible_text(p.group(0))
        if flag.search(text):
            report.flagged.append(" ".join(text.split())[:80])
        if not mention.search(text):
            continue
        new_para, n = _shift_in_para(p.group(0), mention, remap_fn)
        if n:
            report.mentions += n
            out.append((p.start(), p.end(), new_para))

    for start, end, new_para in reversed(out):
        xml = xml[:start] + new_para + xml[end:]

    xml, names, anchors, refs = _shift_names(xml, label, prefix, remap_fn)
    report.bookmarks, report.anchors, report.fields = names, anchors, refs
    return xml, report


def numbers_in_order(xml: str, label: str, *,
                     prefix: str = "") -> list[int]:
    """The caption numbers of `label`, in DOCUMENT ORDER."""
    out = []
    for cap in find_captions(xml, labels=(label,)):
        if prefix and not cap.number.startswith(prefix):
            continue
        digits = cap.number[len(prefix):]
        if digits.isdigit():
            out.append(int(digits))
    return out


def audit(xml: str, label: str, *, prefix: str = "") -> list[str]:
    """Problems with `label`'s numbering — empty list means it is sound.

    THE CHECK THAT CATCHES A REORDER. Numbering a new exhibit "one past
    the highest so far" keeps numbers UNIQUE, which is what a build
    normally asserts, and says nothing about whether they still run in
    reading order. DSI numbered two new tables 11 and 12 into §6.2 while
    §6.3 already held 9 and 10, so the captions read
    1..8, 11, 12, 9, 10 — every number unique, every cross-reference
    resolving, and the sequence backwards where the sections meet. A
    reader meets Table 11 before Table 9.

    Reports three things: numbers out of document order, gaps and
    duplicates, and mentions of a number no caption defines.
    """
    problems = []
    nums = numbers_in_order(xml, label, prefix=prefix)
    if nums != sorted(nums):
        problems.append(
            f"{label}: captions are not in document order: {nums}")
    if sorted(nums) != list(range(1, len(nums) + 1)):
        problems.append(
            f"{label}: numbering is not 1..{len(nums)}: {sorted(nums)}")
    defined = set(nums)
    mention = _mention_re(label, prefix)
    seen: set[int] = set()
    for p in paragraphs(xml):
        for m in mention.finditer(visible_text(p.group(0))):
            seen.add(int(m.group(1)))
    for n in sorted(seen - defined):
        problems.append(
            f"{label}: the text mentions {n}, but no caption defines it")
    return problems


def remap_parts(parts: dict[str, bytes], label: str, mapping: dict[int, int],
                *, prefix: str = "") -> ShiftReport:
    """:func:`remap` across every text-bearing part, in place.

    A mention lives wherever prose does — DSI's footnote 7 went on saying
    «в таблице 9» after the table it names had become 11, and nothing dangled
    because 9 still existed elsewhere. Captions are read from the body (the
    collision check needs them) and the rewrite reaches the footnotes and
    endnotes too.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    total = ShiftReport()
    for name, xml in text_parts(parts):
        if name == DOCUMENT:
            new_xml, rep = remap(xml, label, mapping, prefix=prefix)
        else:
            # captions live in the body; here only mentions and names move
            _check_permutation(mapping, doc, label, prefix)
            new_xml, rep = _apply(xml, label, prefix,
                                  lambda n: mapping.get(n, n))
        parts[name] = new_xml.encode("utf-8")
        total.mentions += rep.mentions
        total.bookmarks += rep.bookmarks
        total.anchors += rep.anchors
        total.fields += rep.fields
        total.flagged += rep.flagged
    return total


def audit_parts(parts: dict[str, bytes], label: str, *,
                prefix: str = "") -> list[str]:
    """:func:`audit` with mentions read from every text-bearing part."""
    doc = parts[DOCUMENT].decode("utf-8")
    problems = audit(doc, label, prefix=prefix)
    defined = set(numbers_in_order(doc, label, prefix=prefix))
    mention = _mention_re(label, prefix)
    for name, xml in text_parts(parts):
        if name == DOCUMENT:
            continue
        seen = set()
        for p in paragraphs(xml):
            for m in mention.finditer(visible_text(p.group(0))):
                seen.add(int(m.group(1)))
        for n in sorted(seen - defined):
            problems.append(
                f"{label}: {name} mentions {n}, but no caption defines it")
    return problems


def _check_permutation(mapping: dict[int, int], doc: str, label: str,
                       prefix: str) -> None:
    if len(set(mapping.values())) != len(mapping):
        raise AnchorError(f"remap: {mapping} sends two numbers to one")
    nums = set(numbers_in_order(doc, label, prefix=prefix))
    if len({mapping.get(n, n) for n in nums}) != len(nums):
        raise AnchorError(f"remap: {sorted(nums)} under {mapping} collides")


def remap(xml: str, label: str, mapping: dict[int, int], *,
          prefix: str = "") -> tuple[str, ShiftReport]:
    """Renumber by an arbitrary MAPPING — captions, mentions, bookmarks,
    anchors and REF fields together.

    :func:`shift` moves a tail and cannot express a swap, which is what a
    reorder needs: putting DSI's §6.2 tables before §6.3's meant
    9→11, 10→12, 11→9, 12→10 at once. Doing that as two shifts is not
    possible and doing it as sequential replacements double-renumbers
    whatever the first pass already touched.

    Atomic by construction, and for the same reason `shift` is: every
    replacement is computed from the ORIGINAL number in a single pass, so
    a permutation needs no temporary numbers.

    The mapping must be a permutation of the numbers it touches —
    otherwise two captions would end up sharing a number, which is the
    failure this function exists to repair.
    """
    if not mapping:
        raise AnchorError("remap: empty mapping")
    _check_permutation(mapping, xml, label, prefix)
    return _apply(xml, label, prefix, lambda n: mapping.get(n, n))
