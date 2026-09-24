r"""Word counts a journal cap can actually be checked against.

Word limits come with exclusions — "8,000 words excluding references,
tables and appendices" is the JEBO shape — and Word's own counter cannot
express any of that, so the number gets estimated by copy-pasting
sections into a scratch document. From the package it is exact: every
word is visible in ``w:t``, and what section it belongs to is decidable
from the body order.

The buckets are the engine; which of them a JOURNAL excludes is the
paper's business and goes on the command line, not in here.

Counting differences from Word's statistic, so nobody chases them again:
a word here is a whitespace-separated token of the visible text. Word
tokenizes slightly differently around fields and symbols, and it counts
an equation as its layout slices rather than its ``m:t`` stream.
Measured on le14_clean: 11,621 here against Word's 11,422 (+1.7%),
almost all of it the equation-heavy sections. For a cap check that
drift is noise — and it errs safe, counting MORE than Word — but an
exact match with the status bar is not on offer.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, fields

from ._xml import DOCUMENT, ENDNOTES, FOOTNOTES, PARA_RE, Parts, visible_text
from .crossrefs import DEFAULT_LABELS, caption_re
from .equations import MT_RE, OMATH_RE
from .find import body_elements, heading_level
from .revisions import FINAL, view_transform

__all__ = [
    "APPENDIX_RE",
    "REFERENCES_RE",
    "Counts",
    "count",
    "words",
]

#: Paragraphs that OPEN the references / appendix zones. The heading's
#: own words land in the zone it opens, because that is how the caps are
#: phrased ("excluding references" means the whole section).
REFERENCES_RE = re.compile(
    r"^(References|Bibliography|Works Cited|"
    r"Список литературы|Литература)\s*:?$", re.IGNORECASE)
APPENDIX_RE = re.compile(
    r"^(Online\s+)?Appendi(x|ces)\b|^Annex(es)?\b|^Приложени[ея]\b",
    re.IGNORECASE)

# the shared caption definition, plus the abbreviated form
_CAPTION_RE = caption_re((*DEFAULT_LABELS, "Fig."))


@dataclass(frozen=True)
class Counts:
    """Words per bucket. ``total()`` applies a journal's exclusions."""

    prose: int = 0        # main-text paragraphs
    headings: int = 0     # main-text section headings
    captions: int = 0     # figure/table captions in the main text
    tables: int = 0       # everything inside main-text tables
    equations: int = 0    # m:t tokens in main-text prose paragraphs
    footnotes: int = 0    # the footnotes/endnotes parts
    references: int = 0   # the references section, wholesale
    appendix: int = 0     # the appendix section(s), wholesale

    def total(self, *, exclude: Iterable[str] = ()) -> int:
        """Sum of the buckets not named in `exclude`."""
        drop = set(exclude)
        names = {f.name for f in fields(self)}
        if unknown := drop - names:
            raise ValueError(f"unknown bucket(s): {sorted(unknown)}; "
                             f"have {sorted(names)}")
        return sum(getattr(self, f.name) for f in fields(self)
                   if f.name not in drop)

    def as_dict(self) -> dict[str, int]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def words(text: str) -> int:
    """Whitespace-separated tokens — the counting rule, defined once."""
    return len(text.split())


def _block_words(xml: str) -> int:
    """Words of a multi-paragraph block (a table, a notes part).

    Counted per paragraph, because ``visible_text`` of the whole block
    concatenates adjacent cells and notes without a separator —
    "Country" next to "Value" reads back as the single word
    "CountryValue" and the count comes out laughably low.
    """
    return sum(words(visible_text(p.group(0)))
               for p in PARA_RE.finditer(xml))


def _para_words(para_xml: str) -> tuple[int, int]:
    """(prose words, equation words) of one paragraph.

    ``visible_text`` includes ``m:t``, so the math must come OUT before
    the prose is counted or every equation would be counted twice.
    """
    math = words(" ".join(MT_RE.findall(para_xml)))
    prose = words(visible_text(OMATH_RE.sub("", para_xml)))
    return prose, math


def count(parts: Parts, *,
          view: str = FINAL,
          references_re: re.Pattern[str] = REFERENCES_RE,
          appendix_re: re.Pattern[str] = APPENDIX_RE) -> Counts:
    """Count the manuscript into :class:`Counts` buckets.

    `view` picks the side of any tracked changes — a redline's cap check
    should count what the journal will read, which is ``final``.

    Zones are switched by heading TEXT (`references_re`, `appendix_re`
    against the stripped paragraph), not by style: the papers' reference
    headings are reliable words and unreliable styles. Once a zone opens
    it runs to the next zone switch or the end — inside references or
    appendix everything (tables, captions, math) counts into that zone's
    bucket, because that is how journal exclusions are phrased.

    There is deliberately no abstract bucket: abstracts have no reliable
    terminator, and a bucket that guesses would be trusted. Papers that
    need one can subtract it by counting the abstract paragraph
    themselves.
    """
    transform = view_transform(view)
    xml = transform(parts[DOCUMENT].decode("utf-8"))

    tally = dict.fromkeys((f.name for f in fields(Counts)), 0)
    zone: str | None = None                      # None = the main text
    for kind, start, end in body_elements(xml):
        frag = xml[start:end]
        if kind == "tbl":
            tally[zone or "tables"] += _block_words(frag)
            continue
        text = visible_text(frag).strip()
        if not text:
            continue
        if references_re.match(text):
            zone = "references"
        elif appendix_re.match(text):
            zone = "appendix"
        prose, math = _para_words(frag)
        if zone is not None:
            tally[zone] += prose + math
        elif _CAPTION_RE.match(text):
            tally["captions"] += prose + math
        elif heading_level(frag) is not None:
            tally["headings"] += prose
        else:
            tally["prose"] += prose
            tally["equations"] += math

    # Word's separator/continuation notes hold no w:t, so no reserved-id
    # filtering is needed, and per-paragraph counting covers endnotes,
    # whose elements footnotes.find_all would not match.
    for name in (FOOTNOTES, ENDNOTES):
        if name in parts:
            tally["footnotes"] += _block_words(
                transform(parts[name].decode("utf-8")))
    return Counts(**tally)
