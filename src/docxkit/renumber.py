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
from dataclasses import dataclass, field

from ._xml import RUN_RE, set_run_text, visible_text
from .crossrefs import LABEL_FORMS, NUMBER_END, find_captions
from .errors import AnchorError
from .find import paragraphs

__all__ = ["ShiftReport", "shift"]

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
#: it does not model, and guessing at one corrupts the manuscript
_SUFFIXED = r"(?:\.\w|\w)"


def _flag_re(label: str, prefix: str) -> re.Pattern[str]:
    form = LABEL_FORMS.get(label, re.escape(label) + "s?")
    return re.compile(
        rf"\b(?:{form})\s+{re.escape(prefix)}\d+"
        rf"(?:{_CONTINUATION}|{_SUFFIXED})",
        re.IGNORECASE)


def _shift_in_para(para_xml: str, pattern: re.Pattern[str],
                   frm: int, by: int) -> tuple[str, int]:
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
        if n < frm:
            continue
        if re.match(_CONTINUATION, visible[m.end():]):
            continue                    # range/list: flagged by the caller
        hits.append((m.span(1), n))
    if not hits:
        return para_xml, 0

    changed = set()
    for (a, b), n in sorted(hits, reverse=True):
        new = str(n + by)
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
                 frm: int, by: int) -> tuple[str, int, int, int]:
    """Bookmark names, hyperlink anchors and REF fields, one pass each."""
    base = re.escape(label) + re.escape(prefix)
    counts = {"w:name": 0, "w:anchor": 0, "ref": 0}

    def bump(number: str) -> str:
        n = int(number)
        return str(n + by) if n >= frm else number

    attr_re = re.compile(rf'((?:w:name|w:anchor)="){base}(\d+)(txt)?(")')

    def attr_sub(m: re.Match[str]) -> str:
        new = bump(m.group(2))
        if new != m.group(2):
            counts["w:name" if m.group(1).startswith('w:name') else
                   "w:anchor"] += 1
        return (m.group(1) + label + prefix + new + (m.group(3) or "")
                + m.group(4))

    xml = attr_re.sub(attr_sub, xml)

    ref_re = re.compile(rf"(\bREF\s+){base}(\d+)(txt)?\b")

    def ref_sub(m: re.Match[str]) -> str:
        new = bump(m.group(2))
        if new != m.group(2):
            counts["ref"] += 1
        return m.group(1) + label + prefix + new + (m.group(3) or "")

    xml = ref_re.sub(ref_sub, xml)
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
        new_para, n = _shift_in_para(p.group(0), mention, frm, by)
        if n:
            report.mentions += n
            out.append((p.start(), p.end(), new_para))

    for start, end, new_para in reversed(out):
        xml = xml[:start] + new_para + xml[end:]

    xml, names, anchors, refs = _shift_names(xml, label, prefix, frm, by)
    report.bookmarks, report.anchors, report.fields = names, anchors, refs
    return xml, report
