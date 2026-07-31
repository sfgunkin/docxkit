r"""Document hygiene: parts a manuscript should not carry, glyphs it
should not mix.

Word accumulates parts nobody asked for. The recurring one is the
``customXml/`` bibliography data store, which it injects when a document
has ever seen its citation manager: it is vestigial, it travels into
submissions, and on the DSI paper it needed its own commit to remove.

Dropping the parts is the easy half. The half that goes wrong is the
references: an ``[Content_Types].xml`` Override or a relationship still
pointing at a part that no longer exists is exactly what Word reports as
"unreadable content".

:func:`smarten` is the other hygiene chore: a manuscript mixes straight
and curly quotes because autocorrect ran on some paragraphs and not
others. The matching side of that is already handled everywhere via
``normalize=True``; this is the REPAIR side, run once so the phantom
class of diffs stops existing.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from ._xml import PARA_RE, escape

__all__ = ["CUSTOM_XML", "SmartenReport", "smarten", "strip_parts"]

CUSTOM_XML = "customXml/"


def strip_parts(parts: dict[str, bytes],
                prefixes: tuple[str, ...] = (CUSTOM_XML,)) -> list[str]:
    """Drop whole part-trees by name prefix, patching what referenced them.

    Mutates `parts` and returns the names removed. ``word/document.xml``
    is never touched, so the manuscript content is provably unchanged —
    which is the point of doing this on the package rather than by
    re-saving through Word.
    """
    dropped = sorted(n for n in parts
                     if any(n.startswith(p) for p in prefixes))
    if not dropped:
        return []

    for name in dropped:
        del parts[name]

    for prefix in prefixes:
        quoted = re.escape(prefix)
        if "[Content_Types].xml" in parts:
            xml = parts["[Content_Types].xml"].decode("utf-8")
            xml = re.sub(rf'<Override PartName="/{quoted}[^"]*"[^>]*/>',
                         "", xml)
            parts["[Content_Types].xml"] = xml.encode("utf-8")
        rels = "word/_rels/document.xml.rels"
        if rels in parts:
            xml = parts[rels].decode("utf-8")
            xml = re.sub(
                rf'<Relationship[^>]*Target="(?:\.\./)?{quoted}[^"]*"[^>]*/>',
                "", xml)
            parts[rels] = xml.encode("utf-8")
    return dropped


# ------------------------------------------------------------- smarten ------

# w:t ONLY: m:t is mathematics, where a straight quote is a prime and
# "fixing" it corrupts the formula; w:delText is someone's tracked
# deletion, not ours to retypeset; w:instrText is field code.
_WT_RE = re.compile(r"(<w:t[^>]*>)([^<]*)(</w:t>)")


@dataclass
class SmartenReport:
    """What :func:`smarten` changed, and what it declined to guess."""

    apostrophes: int = 0
    quotes: int = 0
    ambiguous: int = 0            # a straight ' with no word before it —
    #                               an opening quote or an elision ('n'),
    #                               and only the author knows which
    unbalanced: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [(f"apostrophes {self.apostrophes}, "
                  f"double quotes {self.quotes}, "
                  f"left ambiguous {self.ambiguous}")]
        lines += [f"  unbalanced quotes, untouched: {snippet}"
                  for snippet in self.unbalanced]
        return "\n".join(lines)


def _smarten_para(para: str, report: SmartenReport) -> str:
    wts = list(_WT_RE.finditer(para))
    if not wts:
        return para
    decoded = [html.unescape(m.group(2)) for m in wts]
    stream = "".join(decoded)
    if "'" not in stream and '"' not in stream:
        return para

    quotes_pair = stream.count('"') % 2 == 0
    if not quotes_pair and '"' in stream:
        report.unbalanced.append(" ".join(stream.split())[:70])

    opening = True
    prev = ""
    out_texts = []
    changed = False
    for text in decoded:
        buf = []
        for ch in text:
            if ch == "'":
                if prev.isalnum():
                    # after a word character it is an apostrophe or a
                    # closing quote, and both smarten the same way:
                    # don't, workers', it's
                    buf.append("’")
                    report.apostrophes += 1
                    changed = True
                else:
                    buf.append(ch)
                    report.ambiguous += 1
            elif ch == '"' and quotes_pair:
                buf.append("“" if opening else "”")
                opening = not opening
                report.quotes += 1
                changed = True
            else:
                buf.append(ch)
            prev = ch
        out_texts.append("".join(buf))

    if not changed:
        return para
    for m, new in sorted(zip(wts, out_texts, strict=True),
                         key=lambda pair: -pair[0].start()):
        para = (para[:m.start()] + m.group(1) + escape(new) + m.group(3)
                + para[m.end():])
    return para


def smarten(xml: str) -> tuple[str, SmartenReport]:
    """Straight quotes to typographic ones, where it cannot go wrong.

    Two safe rules, nothing more:

    * ``'`` immediately after a word character becomes ``’`` — don't,
      it's, workers'. The lookback crosses run boundaries, so a
      fragmented "workers" + "' rights" still qualifies.
    * ``"`` pairs alternate ``“``/``”`` within a paragraph, and ONLY in
      paragraphs whose straight-quote count is even; an odd count means
      the pairing would be a guess, so the paragraph is left as it was
      and reported.

    A leading ``'`` (opening single quote? an elision like 'n'?) is
    counted as ambiguous and left alone. Math (``m:t``), tracked
    deletions and field instructions are never touched. Quote state does
    not cross paragraphs, matching how Word's own autocorrect decides.

    Matching through the mixture (``normalize=True``) keeps working
    either way; run this once so the mixture stops generating phantom
    diffs against author files.
    """
    report = SmartenReport()
    out = PARA_RE.sub(lambda m: _smarten_para(m.group(0), report), xml)
    return out, report
