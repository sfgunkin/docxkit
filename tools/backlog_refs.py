#!/usr/bin/env python
"""Did the fix that shipped get RECORDED?

    python tools/backlog_refs.py

`BACKLOG.md`'s own rule says done means *fix + a test that fails without
it + the per-paper workaround deleted + entry moved to `## Fixed` with
its commit*. The last clause is the one that gets dropped, every time,
because it is last: on 2026-08-27 the `## Open` section listed ten
entries of which five were already fixed — in `805e1ad`, `67459c9`,
`cb25235`, `e56906e` and `924cd2e`, every one of them carrying a commit
message that describes the defect in the backlog's own words, and not
one of them touching the file.

That is not untidiness. The batch order is set by severity, so a stale
`## Open` sets the wrong order — the S1 at the top of that night's list
was the one entry already closed. And "did we ever fix that?" is the
question `## Fixed` exists to answer; a fix with no entry is invisible to
it, so the next person to hit the symptom re-derives the diagnosis. Same
cost as an unrecorded defect, arriving from the opposite direction.

**Why the house rule could not catch it.** Every trigger in it fires on
RECORDING a defect. Nothing fires on CLOSING one, because closing already
feels like the bookkeeping — the code is written, the test is green, the
commit is made, and moving a heading afterwards reads as filing rather
than as finishing.

**What is checked, and why not the stricter thing.** A commit opts in by
writing `Refs BACKLOG.md` in its message. The obvious rule — that such a
commit must itself touch `BACKLOG.md` — is wrong here, and measurably:
all six commits that had adopted the convention by 2026-08-27 broke it,
because the code lands first and the entry moves in the commit after. So
the rule is the weaker, true one: **a `Refs BACKLOG.md` commit must be
accompanied or FOLLOWED by a commit that touches the file.** Nothing is
said about which commit; what is refused is the state where a fix sits at
the tip with the record never written.

That makes the suite red for exactly as long as the gap is open, which
is the point — the entry this closes asked for "a red suite rather than
a thing somebody notices weeks later".

**It binds only commits that opt in**, and that is a real limit worth
stating rather than papering over: a fix committed with no mention of
the backlog is invisible here. The convention costs one line per commit
and the alternative — matching commit prose against open entries — is a
guess about English, which is the shape this file has an entry about.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]

#: The opt-in. Matched case-sensitively on purpose: this is a literal
#: convention to be copied into a commit message, not a phrase to be
#: recognised through its variants.
MARKER = "Refs BACKLOG.md"

FILE = "BACKLOG.md"


def unrecorded(commits: Iterable[tuple[str, str, bool]]
               ) -> list[tuple[str, str]]:
    """Which `Refs BACKLOG.md` commits have no record after them.

    `commits` is NEWEST FIRST, as `git log` gives them: each entry is
    (sha, message, did-this-commit-CLOSE-an-entry).

    Walking newest first, a commit is recorded once any commit at or
    before it in that order — that is, at or AFTER it in time — closed
    one. So the answer is the marker-bearing commits above the newest
    closure, and it is empty the moment that closure is made.

    **Closed, not merely touched.** The third element used to mean "this
    commit edited BACKLOG.md at all", and filing a NEW defect is the most
    frequent reason to open the file — so a commit filing an entry
    retroactively marked every pending fix as recorded. Review put the
    exact history this tool was written for through it and got a clean
    answer. What is asked instead is whether the commit added a CLOSED
    heading, which is the clause the rule actually names: *entry moved to
    `## Fixed` with its commit*. See :func:`_closes`.
    """
    out: list[tuple[str, str]] = []
    for sha, message, closed in commits:
        if closed:
            break            # everything older than a closure is recorded
        if MARKER in message:
            subject = next((ln for ln in message.splitlines() if ln.strip()),
                           "")
            out.append((sha, subject.strip()))
    return out


#: A commit that CLOSES an entry adds one of these to `BACKLOG.md`: a
#: struck-through heading, or a heading naming a resolution. Filing a new
#: defect adds neither, which is the whole point of asking.
_CLOSES = re.compile(
    r"^\+#{2,3} .*(~~|\b(FIXED|CLOSED|WITHDRAWN|RETRACTED|DECIDED)\b)",
    re.MULTILINE)

#: What git says when the directory is simply not a repository. Anything
#: else on a non-zero exit is git failing, which is a different answer.
_NO_REPO = ("not a git repository", "does not have any commits yet",
            "unknown revision")


def read_log(root: Path = ROOT, limit: int = 200
             ) -> Iterator[tuple[str, str, bool]] | None:
    """The recent history as :func:`unrecorded` wants it, or None.

    None when there is no git to ask — a source tarball, an export, a
    checkout of the tree without its history. A gate that cannot see the
    history has nothing to say, and saying it anyway would be a failure
    about the packaging rather than about the backlog.

    **A git FAILURE is not "no history", and this used to answer as if it
    were.** `fatal: detected dubious ownership in repository` is ordinary
    for a repo on a second drive, in a container, or under another
    user — and it made this print "nothing to check" and exit 0 while the
    test took its skip. Green suite, green tool, dead gate. So stderr is
    read: only the spellings in :data:`_NO_REPO` mean there is nothing to
    ask, and anything else raises with what git said.

    `limit` bounds the walk. Only the commits ABOVE the newest closure
    can be unrecorded, and that closure is never far back in a repo whose
    rule is to move the entry with the fix; the bound is here so the gate
    stays flat as the history grows, and it is generous enough that
    hitting it means something else is wrong.
    """
    record, field = "\x1e", "\x1f"
    try:
        out = subprocess.run(
            ["git", "log", f"--format={record}%H{field}%B{field}",
             "-n", str(limit)],
            cwd=root, capture_output=True, text=True, encoding="utf-8",
            errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode:
        said = (out.stderr or "").strip()
        if any(spelling in said.lower() for spelling in _NO_REPO):
            return None
        raise RuntimeError(f"git log failed in {root}: {said[:300]}")
    # LAZY, and that is not a style choice: `_closes` is a subprocess per
    # commit, and `unrecorded` stops at the first closure. Eager would be
    # `limit` calls to `git show` on every run of the suite; lazy is
    # typically one.
    return ((sha, message, _closes(root, sha))
            for sha, message in _parse(out.stdout.split(record), field))


def _parse(records: Iterable[str], field: str) -> Iterable[tuple[str, str]]:
    """`git log`'s output, one (sha, message) per commit."""
    for chunk in records:
        if not chunk.strip():
            continue
        sha, _, rest = chunk.partition(field)
        message, _, _ = rest.partition(field)
        yield sha.strip(), message


def _closes(root: Path, sha: str) -> bool:
    """Did that commit add a CLOSED heading to `BACKLOG.md`?

    Asked per commit rather than from one `--name-only` walk, because
    "touched the file" is not the question — see :func:`unrecorded`. It
    costs one `git show` per commit, so the diff is restricted to the one
    path and to zero lines of context, and the walk stops at the first
    commit that answers yes.
    """
    out = subprocess.run(
        ["git", "show", "--format=", "-U0", sha, "--", FILE],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    return not out.returncode and bool(_CLOSES.search(out.stdout))


def main() -> int:
    utf8_stdout()
    commits = read_log()
    if commits is None:
        print("no git history here — nothing to check")
        return 0
    open_ = unrecorded(commits)
    if not open_:
        print(f"every {MARKER} commit is recorded in {FILE}")
        return 0
    print(f"{len(open_)} commit(s) say {MARKER} and no commit since has "
          f"touched {FILE}:\n")
    for sha, subject in open_:
        print(f"  {sha[:8]}  {subject[:70]}")
    print("\nMove the entry to `## Fixed` with its hash, and the workaround "
          "out of the paper that carried it. That is the last clause of the "
          "rule and the one that gets dropped.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
