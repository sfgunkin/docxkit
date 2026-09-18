"""Sort a cosmic-ray run's survivors into the kinds worth acting on.

    python tools/mutation_survivors.py run.sqlite src/docxkit/styles.py

`cr-report` gives a survival PERCENTAGE, and in this package that number
is close to meaningless: every module carries
``from __future__ import annotations``, so annotations are strings that
are never evaluated and a mutation inside one cannot change behaviour.
Measured on ``styles.py``: 225 survivors, **187 of them inside a type
annotation** — equivalent by construction, not missing tests. A reader
who takes the headline at face value is reading 56% when the real figure
is 9.5%, and the usual response to a number like that is to stop running
the tool.

So this prints the survivors that are actually a question, grouped by
the definition they landed in, and says which line each is on. What to
do with them is in CONTRIBUTING: a real gap, an equivalent mutant, or
cosmetic — and only the first is a test.

Each one is shown as the line it BECAME, not as the name of the
operator that made it. A name says `ReplaceComparisonOperator_NotEq_Gt`
where the line holds two `!=`, and a reader who guesses the wrong one
writes a test against a mutant that was killed months ago: that is what
happened on `_compare_diff`'s `fmt_diff` guard (2026-08-20), and the
duplicate test passed `kill_check` because a pre-existing test failed
under the mutation it did not aim at.
"""
from __future__ import annotations

import ast
import re
import sqlite3
import sys
import textwrap
import tomllib
from collections import Counter
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]


def annotation_spans(tree: ast.Module) -> list[tuple[int, int, int, int]]:
    """Every (row, col, row, col) span that belongs to an annotation."""
    spans: list[tuple[int, int, int, int]] = []
    for node in ast.walk(tree):
        found: list[ast.expr] = []
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = node.args
            # `vararg` and `kwarg` too: `def lint(*roots: _Element | None)`
            # annotates a parameter like any other, and leaving the two out
            # presented 22 of `lint.py`'s 65 survivors as questions — its
            # real survival was 5.0 %, not the 7.5 % the round was briefed
            # on (2026-09-17). A discount that is incomplete does not read
            # as incomplete; it reads as a module with more to answer for.
            every = [*args.args, *args.posonlyargs, *args.kwonlyargs,
                     args.vararg, args.kwarg]
            found = [a.annotation for a in every
                     if a is not None and a.annotation is not None]
            if node.returns is not None:
                found.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            found = [node.annotation]
        for ann in found:
            if ann.end_lineno is not None and ann.end_col_offset is not None:
                spans.append((ann.lineno, ann.col_offset,
                              ann.end_lineno, ann.end_col_offset))
    return spans


def main_guard_spans(tree: ast.Module) -> list[tuple[int, int, int, int]]:
    """Every span belonging to an ``if __name__ == "__main__":`` block.

    Test == equivalent by construction, and for the same reason as an
    annotation: under pytest the module is IMPORTED, so `__name__` is
    its dotted name and the guard is False however the comparison is
    mutated. The body never runs either, so the whole statement goes in
    — a one-line `raise SystemExit(main())` otherwise contributes a
    survivor to every module that can be run as a script.

    Two of these under `compare.py` and three under `cli.py` read as a
    module with a gap in it, and the gap is a line no test can reach
    without launching a subprocess to reach it.
    """
    spans: list[tuple[int, int, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
                and node.end_lineno is not None
                and node.end_col_offset is not None):
            spans.append((node.lineno, node.col_offset,
                          node.end_lineno, node.end_col_offset))
    return spans


#: coverage.py's own default, which the project's `exclude_also` adds to
#: rather than replaces.
_NO_COVER = r"#\s*(pragma|PRAGMA)[:\s]?\s*(no|NO)\s*(cover|COVER)"


def excluded_patterns(root: Path) -> list[str]:
    """The line patterns coverage has been told to ignore, from
    pyproject — plus its built-in `# pragma: no cover`."""
    out = [_NO_COVER]
    try:
        with (root / "pyproject.toml").open("rb") as fh:
            conf = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return out
    report = conf.get("tool", {}).get("coverage", {}).get("report", {})
    out.extend(report.get("exclude_also", []))
    out.extend(report.get("exclude_lines", []))
    return out


def excluded_spans(text: str, tree: ast.Module,
                   patterns: list[str]) -> list[tuple[int, int, int, int]]:
    """Every span coverage has been told not to look at.

    `# pragma: no cover` is the author saying a line is defensive —
    reachable only through a state this package does not produce — and
    the coverage floor is enforced with those lines taken out. No test
    executes them, so no test can kill a mutant on one: equivalent by
    construction, exactly like an annotation.

    Eight of `_cite_build`'s 35 "real" survivors sat on one such `if`
    and the `continue` under it, which is a fifth of a module's figure
    spent on a line the project has already declared unreachable.

    A pragma on a compound statement covers the whole block, which is
    the reading coverage.py has of it.
    """
    hits = [re.compile(p) for p in patterns]
    marked = {i + 1 for i, line in enumerate(text.splitlines())
              if any(h.search(line) for h in hits)}
    spans = [(row, 0, row, 10 ** 6) for row in marked]
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, ast.stmt) and isinstance(body, list)
                and node.lineno in marked
                and node.end_lineno is not None):
            spans.append((node.lineno, node.col_offset,
                          node.end_lineno, 10 ** 6))
    return spans


def within(spans: list[tuple[int, int, int, int]], row: int, col: int) -> bool:
    """Is (row, col) inside any of these spans?"""
    return any(r1 <= row <= r2
               and (row != r1 or col >= c1)
               and (row != r2 or col <= c2)
               for r1, c1, r2, c2 in spans)


def marker_positions(text: str,
                     tree: ast.Module) -> list[tuple[int, int]]:
    """(row, col) of every keyword-only ``*`` in a def signature.

    Mutating that ``*`` to ``/`` — cosmic-ray does, as a Mul-to-Div
    replacement — turns the parameters BEFORE it into positional-only
    ones. No call this package makes changes meaning: the arguments
    after the marker were already keyword-only, and the ones before it
    are passed positionally. It is an interface constraint, not a
    behaviour, and the test that would kill it is a call written to
    kill it rather than to use the function.

    56 of them stood in the sixth sweep's survivor lists (2026-08-19),
    one per keyword-only signature, which is enough to move every
    module's figure — the same reason the annotations are taken out.
    They are counted and named separately rather than folded into the
    annotations, because a reader may reasonably decide that a public
    function's calling convention IS a contract worth a test.
    """
    lines = text.splitlines()
    out: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.args.kwonlyargs or node.args.vararg is not None:
            continue
        end = node.body[0].lineno if node.body else node.lineno + 1
        for row in range(node.lineno, end):
            line = lines[row - 1]
            for col, ch in enumerate(line):
                # the marker, and not a multiplication in a default: a
                # bare `*` is the one with the comma straight after it
                if ch == "*" and line[col + 1:].lstrip().startswith(","):
                    out.append((row, col))
    return out


def definitions(tree: ast.Module) -> list[tuple[int, int, str]]:
    """Every def/class as (first line, last line, name)."""
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return [(n.lineno, n.end_lineno or n.lineno, n.name)
            for n in ast.walk(tree) if isinstance(n, kinds)]


def owner_of(defs: list[tuple[int, int, str]], line: int) -> str:
    """The INNERMOST definition containing `line`.

    By span, not by "the last `def` above it". A function with nested
    helpers — `replace_in_para` has four — otherwise hands every survivor
    in its own body to whichever helper was defined last, which is how
    three mutants sat under `label_end` in a report that decided which
    cluster to work on next.
    """
    holding = [(hi - lo, name) for lo, hi, name in defs if lo <= line <= hi]
    return min(holding)[1] if holding else "<module>"


def pristine_source(db_path: str, src_path: str) -> tuple[str, str]:
    """The source the RUN was planned against, if the session kept one.

    Every line number here indexes into the file the mutants were
    generated from. Read the live file instead and a source that has
    moved since — a docstring added, a helper inserted — shifts every
    quote below the edit, so the report names the wrong line with
    complete confidence. `mutation_session` snapshots the module when it
    plans a run for exactly this reason; this reads it back.

    With no snapshot the fallback is the live file — what this tool
    always did, and it must not become an error — but that now returns a
    WARNING rather than an empty note. Silence there reads as "this is
    the source the run used", which is indistinguishable from "this is
    whatever is on disk today". The `.pristine` half of a session looks
    like the disposable one (49 sessions, 86 MB), so pruning it to
    reclaim space is a live temptation; doing that used to turn every
    later report on those runs into confident wrong lines with nothing
    on the page to say so.
    """
    stem = Path(db_path).stem.removeprefix(".mutation-")
    kept = Path(db_path).resolve().parent / f".mutation-{stem}.pristine"
    # the snapshot mirrors the repo's layout, so a relative path lands
    # directly; an absolute one (or a path from another working
    # directory) is matched on its file name instead
    inside = kept / src_path
    if not (inside.is_file() and inside.is_relative_to(kept)):
        # an ABSOLUTE src_path swallows the base on the join above, so
        # the snapshot is matched on the file name instead
        inside = next(kept.rglob(Path(src_path).name), kept)
    if not inside.is_file():
        # Which of the two it is decides what the reader does next: a
        # session that never kept a snapshot is history and nothing can
        # be done; a session whose snapshot is GONE is a pruning
        # mistake, and the sqlite beside it is worth no more than this.
        why = ("that session kept no snapshot"
               if not kept.is_dir()
               else f"{kept.name} exists but does not hold "
                    f"{Path(src_path).name}")
        return src_path, (
            f"  (no pristine copy — {why}. The lines below index into "
            f"the LIVE file: if it has changed since the run was "
            f"planned, they name the wrong ones.)")
    # `lines_of`, like the three other places that ask whether a file has
    # moved since the run. Nothing turns on it HERE — the snapshot holds
    # the same lines either way, so the report quotes the same text and
    # names the same rows — and it is folded in for the next reader, who
    # will find a fourth spelling of one rule and have to work out
    # whether it is an exception on purpose. Imported inside the
    # function, as `staleness` below imports `state`: these tools are
    # each other's, and nothing here is needed at import time.
    from stale_figures import lines_of  # noqa: PLC0415

    if lines_of(inside) == lines_of(Path(src_path)):
        return str(inside), ""
    return str(inside), (
        f"  (quoting {inside.name} as it was when the run was planned — "
        f"the live file has moved since)")


def staleness(src_path: str, db_path: str | Path | None = None) -> list[str]:
    """A banner when the run this list comes from is already void.

    The rule is old — a figure is void when the source or the harness
    has moved — and the tool that PROPOSES the work is the place to say
    so. Mining a stale list costs a round: `body.py`'s survivors named
    eleven mutants on one line that a previous round had already killed,
    and the tests written for them were duplicates of tests already in
    the file (2026-08-20).

    Never a refusal. A stale list is still the best guess at where to
    look, and `kill_check` disposes of what has since died — this only
    stops a reader taking the numbers at face value.

    **`db_path` is the session the caller actually opened**, and it is
    passed on rather than re-derived. Without it `state` looks for the
    session in the tool's own checkout, so reading a session by absolute
    path from a round worktree — the ordinary way this is run — found
    nothing, answered "never measured", and printed no banner over a
    list whose survivors were already dead (`guard.py`, 2026-09-18).
    """
    try:
        from harness_map import harness_for  # noqa: PLC0415
        from stale_figures import state  # noqa: PLC0415
    except ImportError:                      # pragma: no cover
        return []
    module = harness_key(src_path)
    try:
        how, moved = state(module, harness_for(module),
                           Path(db_path) if db_path else None)
    except SystemExit:                       # no harness for this module
        return []
    if how != "stale":
        return []
    return [f"  STALE: {', '.join(moved)} changed after this run — the",
            "  survivors below may already be dead. Re-measure, or let",
            "  kill_check dispose of each one before writing a test.",
            ""]


def harness_key(src_path: str) -> str:
    """How `harness_map` names this module: its path under
    ``src/docxkit``, so a subpackage half keeps its folder.

    `Path(src_path).name` is what this file read, and it is the same
    defect `replay_survivors.module_key` exists for: `revision/
    _gates.py` reduces to `_gates.py`, which is no HARNESS key and no
    session name, so `staleness` looked for `.mutation-gates.sqlite`,
    found nothing, read "never measured" and printed no banner at all.
    Every module in a subpackage was silently exempt from the staleness
    warning (noticed 2026-09-18, mining `revision/_gates.py`: the run
    was stale in its tests and the list said nothing).
    """
    marker = "src/docxkit/"
    posix = Path(src_path).as_posix()
    return posix.split(marker, 1)[1] if marker in posix else Path(
        src_path).name


def harness_drift(src_path: str,
                  db_path: str | Path | None = None) -> list[str]:
    """A banner when the harness has MOVED since the run was planned.

    `staleness` above asks whether the module or its tests have CHANGED.
    This asks the other question, which nothing asked before: whether
    the set of test files is still the same set. A session records the
    command it was planned with, so the two can simply be compared —
    and they disagree more often than anyone expected, because a test
    file renamed or added is not a file anything watches.

    Both directions are printed, and they are named rather than counted:
    a count says something moved without saying what, which is the shape
    this package has spent a day removing. See
    :func:`stale_figures.drifted` for what each direction means.
    """
    try:
        from harness_map import harness_for  # noqa: PLC0415
        from stale_figures import drifted  # noqa: PLC0415
    except ImportError:                      # pragma: no cover
        return []
    module = harness_key(src_path)
    try:
        added, dropped = drifted(module, harness_for(module),
                                 Path(db_path).parent if db_path else None)
    except SystemExit:                       # no harness for this module
        return []
    if not added and not dropped:
        return []
    out = ["  HARNESS DRIFT: this run was planned against a different set "
           "of test",
           "  files than harness_map names for the module today."]
    if added:
        out += _named(
            ["  ADDED since — an added test can only KILL, so the figure",
             "  below is an upper bound and a survivor may already be dead:"],
            added)
    if dropped:
        out += _named(
            ["  DROPPED since — the figure was measured against tests this",
             "  module no longer has, so a replay or a kill_check run today",
             "  asks a different question than the session did:"],
            dropped)
    return [*out, ""]


def _named(head: list[str], files: list[str]) -> list[str]:
    """A heading as written, then the file names, wrapped and indented."""
    return head + textwrap.wrap(", ".join(files), width=72,
                                initial_indent="    ",
                                subsequent_indent="    ")


#: Where the argued equivalences live. Beside the tooling that reads
#: them rather than in the module they describe: a claim is about a
#: mutant, not about the code, and putting it in the source would be a
#: comment nobody could check.
CLAIMS = ROOT / "tools" / "equivalents.toml"


def claims_key(src_path: str) -> str:
    """A module's key in the claims file: its path under ``src/docxkit``.

    NOT its file name, which is what this read until 2026-09-11 — and not
    what `verify_equivalents.py` ever read: it resolves a key as
    ``src/docxkit/<key>``. For a top-level module the two are the same
    string, so every claim written before then still matches. For a
    subpackage half they are not, and the two readers disagreed in both
    directions: keyed ``_validate.py``, a claim was discounted here and
    reported MODULE GONE there; keyed ``revision/_validate.py``, it
    verified there and was never discounted here. No half carried a claim
    until the first sweep of `revision/`'s halves wanted three — the
    basename shape `harness_map.session_stem` was fixed for, one reader
    over.

    The snapshot a session reads (``.mutation-<stem>.pristine/src/
    docxkit/...``) ends in the same path, so the live file and the
    snapshot give one key. A file outside the package — every scratch
    module the tests build — keeps its bare name.
    """
    posix = Path(src_path).as_posix()
    marker = "src/docxkit/"
    return posix.rsplit(marker, 1)[1] if marker in posix else Path(posix).name


def claimed_equivalents(src_path: str,
                        kind: str = "equivalent") -> dict[str, str]:
    """Settled mutants of one KIND for this module -> the argument.

    Keyed on the line the mutation PRODUCED, as `became` renders it,
    because a row number does not survive the module moving and these
    are meant to outlive several such moves.

    Two kinds, and the difference is what may be done with the number.
    An `equivalent` mutant CANNOT be killed, so it leaves the numerator
    and the denominator together — the same arithmetic the annotations
    get. A `cosmetic` one — a truncation width, the length of a quoted
    snippet — really does change what the code does, and a test
    asserting the exact character count would kill it. It is simply not
    worth one. So it leaves the LIST, which is a queue of tests to
    write, and stays in the FIGURE, which is a claim about how much of
    the module is held: discounting it would report work nobody means to
    do as work that cannot be done.
    """
    if not CLAIMS.exists():
        return {}
    with CLAIMS.open("rb") as fh:
        doc = tomllib.load(fh)
    entry = doc.get(claims_key(src_path), {})
    return {c["line"].strip(): c["why"] for c in entry.get("claims", ())
            if "line" in c and c.get("kind", "equivalent") == kind}


#: The operators a claim may key on instead of a line. ONLY those whose
#: mutation adds no line at all: a claim is keyed on what the mutation
#: PRODUCED, and there is nothing to key on when the answer is a
#: deletion. Kept to an allowlist rather than admitting any operator,
#: because `verify_equivalents` applies such a claim by deleting the
#: anchored line, which is the right mutation for these and the wrong
#: one for an operator that rewrites.
LINELESS_OPERATORS = ("core/RemoveDecorator",)


def claimed_by_operator(src_path: str,
                        kind: str = "equivalent") -> dict[tuple[str, str], str]:
    """Settled mutants keyed on the OPERATOR and the line it stood on.

    The second keying scheme, and it exists because the first cannot
    reach a mutation that REMOVES a line. `became` reads the first added
    line of the stored diff, so a removed decorator renders as the empty
    string — and a claim keyed on "" would settle every lineless mutant
    the module ever has, which is the ambiguity the line keying refuses
    by demanding a unique anchor.

    So the key is the pair: which operator, and which line it was
    applied to. That names one mutation the way `line` does for the
    rest, and where it does NOT — where two survivors answer to the same
    pair — `classify` settles neither and says so. Over-matching
    quietly is worse than reporting three mutants nobody can act on.

    Three of find.py's survivors are this shape (2026-09-18): the
    `@lru_cache` on each pattern builder, removed outright, which cannot
    change an answer because `re.compile` caches behind it.
    """
    if not CLAIMS.exists():
        return {}
    with CLAIMS.open("rb") as fh:
        doc = tomllib.load(fh)
    entry = doc.get(claims_key(src_path), {})
    return {(c["operator"], c["was"].strip()): c["why"]
            for c in entry.get("claims", ())
            if "operator" in c and c.get("kind", "equivalent") == kind}


def became(diff: str | None) -> str:
    """The line the mutation produced, out of cosmic-ray's stored diff.

    The FIRST added line: a mutation that spans several (a loop body
    replaced by `pass`) still names itself in its first one, and the
    rest is context a reader of a survivor list does not need.
    """
    for line in (diff or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            return line[1:].strip()
    return ""


class Counts(NamedTuple):
    """What one session file says, sorted into the kinds that matter."""

    ran: int
    killed: int
    survived: int
    graded: int          # rows the run has an answer for
    planned: int         # rows it was planned with
    annotated: int
    in_guard: int
    in_marker: int
    in_nocov: int
    claimed: int
    skin: list[tuple[int, int, str, str, str | None]]
    real: list[tuple[int, int, str, str, str | None]]
    lines: list[str]
    tree: ast.Module
    #: operator-keyed claims that name more than one surviving mutant,
    #: as (operator, line) — settled by nobody, reported by `main`
    ambiguous: tuple[tuple[str, str], ...] = ()

    @property
    def partial(self) -> bool:
        """Did the run stop before it had graded everything?

        A sampled run marks the mutants it will not run SKIPPED, so a
        FINISHED one has a row per spec either way. Fewer rows means the
        session was killed, timed out, or is still going — and the
        figure from a run that stopped early is not the module's: it is
        whatever the first N mutants happened to say. `_table_core`
        read 1.0 % that way (2/209) against a true 2.7 % (11/415) on
        2026-08-20, ten minutes after a stream was stopped.
        """
        return self.graded < self.planned

    @property
    def sampled(self) -> bool:
        """Was this a `--sample` run rather than the whole module?

        `partial` cannot answer it. A sampled run marks the mutants it
        will not run SKIPPED, which IS a row, so `graded == planned` and
        the figure prints as though the module had been measured whole.

        That is a number hiding its own denominator: `refstyle.py` was
        recorded at 13.1% (34/259) and the module has 1750 mutants, so
        the figure was a sixth of it wearing no mark. The same defect as
        a count that cannot tell "nothing there" from "not looking",
        which this file exists to prevent.
        """
        return self.ran < self.graded

    @property
    def base(self) -> int:
        """The denominator: what a test COULD have killed."""
        return (self.ran - self.annotated - self.in_guard - self.in_marker
                - self.in_nocov - self.claimed)

    @property
    def share(self) -> float:
        """How much of this module a test would not notice changing.

        The COSMETIC ones count. They are out of the printed list
        because no test should pin what they change — the width of a
        truncation, the arithmetic of a fragment whose correctness
        rests on something else — but they are survivors: the code does
        something different and the suite does not notice. Leaving them out of the
        rate as well would turn a decision not to bother into a claim
        that there was nothing there.
        """
        found = len(self.real) + len(self.skin)
        return found / self.base * 100 if self.base else 0.0


def classify(db_path: str, src_path: str) -> Counts | None:
    """Read a session file and sort its survivors. None if it graded
    nothing.

    One spelling of "what does this run say", because there are two
    readers of it now — the survivor list a round is mined from, and the
    table `stale_figures --figures` prints. Two would drift, and the
    drift would be in the number quoted at people.

    Sharing the function was not enough, and the drift happened anyway:
    the two readers handed it DIFFERENT SOURCES. The report resolved the
    snapshot first, the table passed the live file, and every row of the
    table for a module that had moved was computed by applying this
    run's row numbers to a file those rows no longer describe. The
    annotation discount is what collapses — it is a span test, and spans
    move. `_compare_read` printed 30.0 % (128/426) beside a true 6.0 %
    (19/317), discounting ONE annotation mutant where there were 110,
    and read as the worst module in the package while being one of the
    better ones.

    So the resolution happens HERE, where no caller can skip it.
    :func:`pristine_source` stays public for the banner the report
    prints; what it returns is no longer the caller's responsibility.
    """
    if not Path(db_path).is_file():
        # `sqlite3.connect` would CREATE it (BACKLOG S4): see `main`.
        raise FileNotFoundError(f"no session at {db_path}")
    src_path, _ = pristine_source(db_path, src_path)
    text = Path(src_path).read_text(encoding="utf-8")
    tree = ast.parse(text)
    spans = annotation_spans(tree)
    guards = main_guard_spans(tree)
    markers = set(marker_positions(text, tree))
    nocov = excluded_spans(text, tree, excluded_patterns(ROOT))

    rows = sqlite3.connect(db_path).execute("""
        SELECT s.start_pos_row, s.start_pos_col, s.operator_name,
               r.test_outcome, r.diff
        FROM mutation_specs s JOIN work_results r ON s.job_id = r.job_id
        ORDER BY s.start_pos_row
    """).fetchall()
    if not rows:
        return None
    planned = sqlite3.connect(db_path).execute(
        "SELECT count(*) FROM mutation_specs").fetchone()[0]

    # SKIPPED rows are the ones `mutation_session.py --sample` marked so
    # they would not run. Counting them as killed reads a 460-mutant
    # sample as 1361 mutants with 901 free kills, and the share then
    # answers a question nobody asked.
    ran = [r for r in rows if r[3] != "SKIPPED"]
    survived = [r for r in ran if r[3] == "SURVIVED"]
    unreached = [r for r in survived if within(spans, r[0], r[1])
                 or within(guards, r[0], r[1])
                 or within(nocov, r[0], r[1])
                 or (r[0], r[1]) in markers]
    annotated = sum(1 for r in unreached if within(spans, r[0], r[1]))
    in_guard = sum(1 for r in unreached
                   if within(guards, r[0], r[1])
                   and not within(spans, r[0], r[1]))
    in_nocov = sum(1 for r in unreached
                   if within(nocov, r[0], r[1])
                   and not within(spans, r[0], r[1])
                   and not within(guards, r[0], r[1]))
    # Argued equivalences come out LAST, so a mutant that is already
    # discounted for being in an annotation is not discounted twice —
    # which would take it out of the denominator once per reason and
    # deflate the rate.
    claims = claimed_equivalents(src_path)
    open_ = [r for r in survived if r not in unreached]
    settled = [r for r in open_ if became(r[4]) in claims]
    # …and the mutants no line can name. A claim may key on the OPERATOR
    # and the line it stood on instead, for the mutations that REMOVE a
    # line and so render as nothing at all. Line keying stays
    # authoritative: only a row `became` has no answer for is eligible,
    # so a claim cannot reach past a mutant that names itself.
    lines = text.splitlines()
    by_operator = claimed_by_operator(src_path)
    wanted: dict[tuple[str, str], list[tuple[int, int, str, str, str | None]]]
    wanted = {}
    for row in open_:
        if row in settled or became(row[4]):
            continue
        key = (row[2], lines[row[0] - 1].strip() if row[0] <= len(lines)
               else "")
        if key in by_operator:
            wanted.setdefault(key, []).append(row)
    # A key that names more than one mutant settles NEITHER. Quietly
    # covering both is the hazard the line keying refuses by demanding a
    # unique anchor, and it would be worse here: the reader cannot see
    # the over-match, because what is missing from the list is what the
    # claim swallowed.
    ambiguous = tuple(sorted(k for k, rows_ in wanted.items()
                             if len(rows_) > 1))
    settled += [r for k, rows_ in wanted.items() if len(rows_) == 1
                for r in rows_]
    skin_of = claimed_equivalents(src_path, "cosmetic")
    skin = [r for r in open_ if r not in settled and became(r[4]) in skin_of]
    return Counts(
        ran=len(ran), killed=len(ran) - len(survived), survived=len(survived),
        graded=len(rows), planned=planned,
        annotated=annotated, in_guard=in_guard,
        in_marker=len(unreached) - annotated - in_guard - in_nocov,
        in_nocov=in_nocov, claimed=len(settled), skin=skin,
        real=[r for r in open_ if r not in settled and r not in skin],
        lines=lines, tree=tree, ambiguous=ambiguous)


def main() -> int:
    # This report QUOTES the module's source, and a module that lays out
    # glyph widths or parses Word's typography holds characters cp1252
    # cannot encode. Without this the run raises part way down the list,
    # after printing enough to look like a report and before the tally
    # that says which definition to write tests for.
    utf8_stdout()
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    db_path, src_path = sys.argv[1], sys.argv[2]
    if not Path(db_path).is_file():
        # Refused BEFORE anything opens it. `sqlite3.connect` CREATES a
        # missing file, and the report then died on "no such table": a
        # traceback where this sentence belongs, and a 0-byte session
        # left in the repo root (BACKLOG S4, three on 2026-09-12). The
        # obvious name is the wrong one for a module with a leading
        # underscore, which is what the stem below is for.
        from harness_map import session_stem  # noqa: PLC0415
        print(f"no session at {db_path}: nothing was read, and nothing was "
              f"created. The session for {src_path} is "
              f".mutation-{session_stem(src_path)}.sqlite")
        return 2
    for banner in staleness(src_path, db_path):
        print(banner)
    for banner in harness_drift(src_path, db_path):
        print(banner)
    src_path, note = pristine_source(db_path, src_path)
    counts = classify(db_path, src_path)
    if counts is None:
        print("no results in that database — has `cosmic-ray exec` run?")
        return 2
    if note:
        print(note)
    lines, tree = counts.lines, counts.tree
    real = counts.real
    annotated, in_guard = counts.annotated, counts.in_guard
    in_marker, in_nocov = counts.in_marker, counts.in_nocov
    if counts.partial:
        print(f"  INCOMPLETE: {counts.graded} of {counts.planned} mutants "
              f"have an answer — the run was stopped, timed out, or is\n"
              f"  still going. The figure below is the first "
              f"{counts.graded} mutants, not the module.\n")
    sample = (f" (sampled from {counts.planned})"
              if counts.planned > counts.ran and not counts.partial else "")
    print(f"{counts.ran} mutants run{sample} · {counts.killed} killed · "
          f"{counts.survived} survived")
    print(f"  {annotated} of the survivors are inside a TYPE "
          f"ANNOTATION — equivalent by\n  construction (PEP 563: never "
          f"evaluated), so they are not a question")
    if in_guard:
        is_are = "is" if in_guard == 1 else "are"
        print(f'  {in_guard} {is_are} inside `if __name__ == "__main__":`'
              f" — equivalent under a\n  test run, which IMPORTS the "
              f"module and never runs it as a script")
    if in_nocov:
        is_are = "is" if in_nocov == 1 else "are"
        print(f"  {in_nocov} {is_are} on a line coverage is told to SKIP "
              f"(`# pragma: no cover`\n  and friends) — no test runs it, "
              f"so no test can kill a mutant on it")
    if in_marker:
        is_are = "is" if in_marker == 1 else "are"
        print(f"  {in_marker} {is_are} the keyword-only `*` of a signature, "
              f"mutated to `/`:\n  an interface constraint, and no call in "
              f"this package changes meaning")
    if counts.claimed:
        is_are = "is" if counts.claimed == 1 else "are"
        print(f"  {counts.claimed} {is_are} argued EQUIVALENT in "
              f"tools/equivalents.toml — a claim that\n  starts being "
              f"killed is a claim that expired, and "
              f"`verify_equivalents.py` says so")
    for operator, anchor in counts.ambiguous:
        print(f"  !! an operator-keyed claim on {operator.replace('core/', '')}"
              f" names MORE THAN ONE\n  surviving mutant of `{anchor[:50]}` — "
              f"it settles none of them. Give the\n  line a trailing comment "
              f"so each mutant has a key of its own")
    # An annotation mutant cannot be killed, so every one that ran also
    # survived: taking them out of the numerator means taking the same
    # count out of the denominator, or the rate is quietly deflated.
    if counts.skin:
        is_are = "is" if len(counts.skin) == 1 else "are"
        print(f"  {len(counts.skin)} {is_are} COSMETIC — a width, a quoted length, an\n  arithmetic the answer does not turn on. Out of the list below and\n  still IN the rate: a test could kill them, and none should be written")
    found = len(real) + len(counts.skin)
    print(f"  {len(real)} to actually look at — REAL SURVIVAL "
          f"{counts.share:.1f}% ({found}/{counts.base})\n")

    defs = definitions(tree)
    by_line: dict[int, list[str]] = {}
    for row, _col, op, _, diff in real:
        by_line.setdefault(row, []).append(
            became(diff) or op.replace("core/", ""))

    for line, ops in sorted(by_line.items()):
        print(f"  L{line:<5} x{len(ops):<3} in {owner_of(defs, line)}")
        print(f"          {lines[line - 1].strip()[:82]}")
        for text in sorted(set(ops)):
            print(f"       -> {text[:82]}")

    per_def = Counter(owner_of(defs, line) for line in by_line
                      for _ in by_line[line])
    if per_def:
        print("\nby definition:",
              ", ".join(f"{n}x {name}" for name, n in per_def.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
