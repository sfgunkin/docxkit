"""Did the author accept the batch, and the log row for it.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .. import guard as _guard
from .. import package, revisions, tracked
from ._common import TEXT_PARTS, _today
from ._config import Paper
from ._losses import _bookmarks, _links


@dataclass(frozen=True)
class Verdict:
    """What one cycle did to the manuscript, and what the author decided.

    Both halves are recoverable from the files and neither was recorded
    anywhere: after adjudication the manuscript reads 0 pending whether
    every revision was accepted, every one rejected, or half of each,
    and `log.md`'s outcome column was filled in by hand or not at all.
    """

    changed: int
    """Paragraphs whose text differs from the previous truth."""
    added: int
    removed: int
    proposed: tuple[int, int] = (0, 0)
    """(insertions, deletions) the batch carried, when one can be read."""
    kept: int = 0
    """Paragraphs the author kept AS PROPOSED."""
    reverted: int = 0
    """Paragraphs the author kept as they were."""
    authored: int = 0
    """Paragraphs in neither view — the author's own words."""
    links: tuple[int, int] = (0, 0)
    """(added, lost) citation links — an apparatus pass, not prose.

    A PAIR, and not the net total the first version reported, because
    `_links`' own docstring says why: "Counted as a MULTISET of pairs,
    not as a total ... a total hides a swap". It hid one. Measured: a
    round that keeps Lari's link, drops Deaton's to plain text and adds
    Sen's reported `links=0` and printed nothing, while
    `_link_changes` in the same module correctly named the lost one.
    That is the Parental Style T4(3) class — 227 against 229 — which
    this module exists to catch.
    """
    bookmarks: tuple[int, int] = (0, 0)
    """(added, lost) bookmarks, by NAME.

    Word's Compare cannot serialize a bookmark insertion, so a pass that
    adds them runs untracked and no redline can show it. Counted as a
    set difference rather than a length delta for the same reason as
    the links: re-keying a bibliography removes N anchors and adds N
    others, and `len(a) - len(b)` is zero for it.
    """
    batch: Path | None = None
    """The proposal this verdict is about, when it could be identified."""

    @property
    def offered(self) -> int:
        return self.kept + self.reverted

    @property
    def apparatus_only(self) -> bool:
        """A pass that moved the machinery and not one visible word.

        The shape Word's Compare cannot carry: linking the citations
        adds bookmarks, `tracked.build` refuses the batch
        (`bookmarkStart 132 -> 142`), so the pass runs untracked and in
        place. Nothing was left for the author to adjudicate and nothing
        recorded that it happened — which is the point of naming it.

        **Requires that no batch was identified**, and that is a real
        condition rather than an implementation detail: with a PROMOTED
        proposal behind it, this round is a batch round whatever else
        happened to the apparatus, and calling it an apparatus pass
        would name the wrong event.

        It used to cost something: a linking pass run in place while a
        valid batch sat unpromoted was reported as an adjudication of a
        batch nobody acted on. `_proposal` asks whether the batch was
        promoted now, so an unpromoted one identifies nothing and this
        answers for the pass that really happened.
        """
        return (not self.changed and not self.added and not self.removed
                and self.batch is None
                and bool(any(self.links) or any(self.bookmarks)))

    @property
    def outcome(self) -> str:
        """The verdict, in the words a log row wants.

        "accepted in full" survives the author ALSO having edited: those
        are counted separately, because "31 accepted and two sentences
        of my own" is the ordinary shape of a round and reporting it as
        "partly adjudicated" would be wrong about the part that matters.
        """
        if self.apparatus_only:
            return "untracked apparatus pass (nothing to adjudicate)"
        if self.batch is None:
            return "adjudicated (no batch to compare against)"
        if not self.offered:
            return "nothing to adjudicate"
        if not self.reverted:
            verdict = "accepted in full"
        elif not self.kept:
            verdict = "rejected in full"
        else:
            verdict = f"{self.kept} of {self.offered} kept as proposed"
        extra = f", +{self.authored} authored" if self.authored else ""
        return verdict + extra

    def summary(self) -> str:
        """The `changes` cell: what moved between the two truths."""
        bits = [f"{self.changed} ¶ changed"] if self.changed else []
        if self.added:
            bits.append(f"{self.added} added")
        if self.removed:
            bits.append(f"{self.removed} removed")
        ins, dele = self.proposed
        if ins or dele:
            bits.append(f"from {ins + dele} revisions ({ins} ins, {dele} del)")
        for (added, lost), what in ((self.links, "link"),
                                    (self.bookmarks, "bookmark")):
            if added:
                bits.append(f"+{added} {what}{'' if added == 1 else 's'}")
            if lost:
                bits.append(f"-{lost} {what}{'' if lost == 1 else 's'}")
        return ", ".join(bits) or "no visible change"


def _para_counts(parts: dict[str, bytes], view: str) -> Counter[str]:
    """Every paragraph's visible text on one side of the markup.

    Named apart from `tracked._paras`, which this module already
    imports and which answers a different question. The checkers caught
    the collision; a silent redefinition would have sent one of the two
    callers to the wrong function.
    """
    out: Counter[str] = Counter()
    for name in TEXT_PARTS:
        blob = parts.get(name)
        if blob:
            out.update(t for t in revisions.text(blob.decode("utf-8"), view)
                       if t.strip())
    return out


def _promoted(paper: Paper, batch: Path) -> bool:
    """Did this batch ever reach the manuscript?

    `promote` copies the batch into ``build/redlines/`` before it
    overwrites the paper, verifies the copy's hash and refuses the
    promote if it did not land — so a redline with the batch's bytes in
    that folder is the record that the batch was put on. Nothing else
    is: `batch.docx` is written by `build` and says nothing about what
    happened to it afterwards.

    Sizes first, hashes only for a file that could match. A paper
    accumulates one redline per round and each is the whole manuscript.
    """
    want, size = None, batch.stat().st_size
    for redline in paper.redlines():
        if redline.stat().st_size != size:
            continue
        want = want or _guard.sha256(batch)
        if _guard.sha256(redline) == want:
            return True
    return False


def _proposal(paper: Paper) -> Path | None:
    """The batch this manuscript grew out of, or None if it cannot be
    identified with certainty.

    Two questions, and both have to answer yes.

    **Was it built on this baseline?** `guard.base_of` says which
    baseline a batch was built on, so a `batch.docx` left over from an
    earlier round — the exact file the stale-batch guards exist for — is
    not mistaken for the proposal the author just adjudicated. An
    unstamped batch answers "cannot tell" and is refused here.

    **Did it reach the manuscript?** The hash above cannot answer that,
    and the difference is invisible in the files: a batch the author
    REJECTED in full and a batch that was never promoted leave the
    manuscript in exactly the same state — its revisions absent — so
    absence reads as rejection. Measured on Aging_Well, 2026-08-28: a
    Major 2 build was deliberately held back, the author's own Word
    round was ingested with two untracked repairs, and `revision
    baseline` printed a log row saying ``rejected in full, +2 authored``
    for a round in which nothing had been offered and nothing rejected.
    That row is pre-formatted for `revision/log.md`, which is the
    paper's permanent record and the first thing the next session
    reads; it was hand-corrected three times.

    So it is refused rather than inferred, and the caller says
    "adjudicated (no batch to compare against)" — the string
    :attr:`Verdict.outcome` already had for exactly this case.
    """
    batch = paper.batch
    if not batch.is_file() or not paper.prev.is_file():
        return None
    if _guard.base_of(batch) != _guard.sha256(paper.prev):
        return None
    return batch if _promoted(paper, batch) else None


def verdict(paper: Paper) -> Verdict:
    """What this cycle changed, and what the author did with the batch.

    Read-only, and called BEFORE `prev.docx` is replaced — the whole
    computation is against the truth the batch was built on.

    The adjudication is counted per PARAGRAPH rather than per revision,
    and that is the honest unit here: a revision's identity does not
    survive the author's Word session, but the text of the paragraph it
    proposed does. Paragraphs the accepted and rejected views disagree
    about are the ones the batch touched; which version of each the
    manuscript now holds is the verdict. Counted as multisets, so a
    paragraph moved rather than edited is not read as one of each.
    """
    from .. import compare as _compare  # deferred: heavy import chain

    work = package.read_parts(paper.working)
    if not paper.prev.is_file():
        return Verdict(changed=0, added=0, removed=0)
    base = package.read_parts(paper.prev)
    # `compare_docs` on parts already in hand, rather than `compare` on
    # two paths: these manuscripts run to several MB and the path form
    # unzips and parses both again, on top of the two reads here and
    # the four walks below. Same answer, half the reading.
    report = _compare.compare_docs(_compare.load_parts(base),
                                   _compare.load_parts(work))
    structure = Counter(entry["type"] for entry in report["structure"])

    batch = _proposal(paper)
    kept = reverted = authored = 0
    proposed = (0, 0)
    if batch is not None:
        parts = package.read_parts(batch)
        counts = tracked.package_counts(parts)
        proposed = (counts["insertions"], counts["deletions"])
        final, original = _para_counts(parts, revisions.FINAL), \
            _para_counts(parts, revisions.ORIGINAL)
        live = _para_counts(work, revisions.FINAL)
        # Subtract the CONTEXT — the paragraphs both views share —
        # before asking which version the manuscript kept. Without it
        # the question degrades from "is this text where the batch put
        # it" to "is this text anywhere in the document", and a
        # paragraph that already existed elsewhere answers yes whatever
        # the author decided. Measured on a synthetic pair: a batch
        # proposing text that appears elsewhere reported "1 of 2 kept
        # as proposed" both when the author accepted everything and
        # when they rejected everything. Table cells make this the
        # ordinary case, not a corner one — "0.00" and a repeated
        # country name are paragraphs too.
        context = final & original
        rest = live - context
        kept = sum(((final - original) & rest).values())
        reverted = sum(((original - final) & rest).values())
        authored = sum((live - final - original).values())
    # The apparatus, which no other layer of this verdict can see: a
    # link or a bookmark is invisible to the text comparison above, and
    # a pass that adds 116 of them reports as "no visible change" —
    # which is true, and is the whole reason the round left no trace.
    was, now = _links(base), _links(work)
    was_bm, now_bm = _bookmarks(base), _bookmarks(work)
    return Verdict(
        changed=len(report["text"]),
        added=structure.get("INSERT", 0),
        removed=structure.get("DELETE", 0),
        proposed=proposed, kept=kept, reverted=reverted, authored=authored,
        links=(sum((now - was).values()), sum((was - now).values())),
        bookmarks=(len(now_bm - was_bm), len(was_bm - now_bm)),
        batch=batch)


#: The log's batch table, as every paper's `log.md` spells it.
_BATCH_HEADING = "## Batches"


_ROW_RE = re.compile(r"^\s*\|")
_HEADING_RE = re.compile(r"^#{1,6}\s")


def log_batch(paper: Paper, result: Verdict, note: str = "") -> str | None:
    """Append one row to `log.md`'s batch table; return it, or None.

    None when the paper's log has no table to append to — a log this
    tool did not scaffold is the author's document, and guessing where a
    row belongs in it is how a record gets mangled. The caller says so
    rather than this writing a table nobody asked for.

    The row lands after the LAST row of the table and not at the end of
    the file: three of the nine papers carry prose after their batch
    table, and an appended line would have been read as part of it.
    """
    log = paper.config.parent / "log.md"
    if not log.is_file():
        return None
    lines = log.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip() == _BATCH_HEADING), None)
    if start is None:
        return None
    # The table under THIS heading. A five-column table in a later
    # section is somebody else's, and took the row whenever the batch
    # table was missing (BACKLOG, 2026-09-14).
    end = next((i for i in range(start + 1, len(lines))
                if _HEADING_RE.match(lines[i])), len(lines))
    first = next((i for i in range(start, end) if _ROW_RE.match(lines[i])),
                 None)
    if first is None:
        return None
    header = [c.strip() for c in lines[first].strip().strip("|").split("|")]
    if len(header) != 5:
        return None                     # not the table this row is shaped for
    # Every contiguous line holding a pipe is a row, not only one that
    # STARTS with a pipe: GitHub's Markdown makes end pipes optional, and
    # a rule written `--- | ---` ended the walk at the header. A second
    # table further down the file is not this one.
    last = first
    while last + 1 < end and "|" in lines[last + 1]:
        last += 1
    what = note or (result.batch.stem if result.batch else "—")
    row = (f"| {_today()} | {what} "
           f"| {result.summary()} | — | {result.outcome} → truth |\n")
    lines.insert(last + 1, row)
    log.write_text("".join(lines), encoding="utf-8")
    return row
