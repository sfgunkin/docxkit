# docxkit robustness plan

Written 2026-08-04, after a refactoring pass that — like every previous
one — turned up defects the tests did not. This plan treats that
recurrence as the symptom and goes after the causes.

Everything below cites `file:line` and was verified against the source,
not inferred. Coverage figures are from `pytest --cov=docxkit` at 633
tests, 88% overall.

---

## 1. Why each pass finds new defects

Five structural causes, in the order they cost the most:

**C1 — The outward-facing layer is the least tested.** Coverage is
inverted against risk: `tables.py` 99%, `find.py` 100%, `refstyle.py`
98% — but `tracked.py` **0%** (312 statements), `cli.py` 63%,
`word.py` 76%, `compare.py` 80%. `tracked.py` builds the redline that
ships to journals. The modules that touch the outside world are exactly
the ones no test exercises, because they need Word and nobody built a
seam.

**C2 — Invariants live in comments, not in code.** The rules are real
and hard-won ("assert every anchor", "offsets are stale after an edit",
"never pass a data-built replacement string"), but they are enforced by
memory. Where one module learned a lesson, its siblings did not:
`edit.py:39` `_ANY_T_RE` excludes longer-named siblings; `_xml.py:44-50`
and `hygiene.py:72` still use the fragile form. `tables.py:572` has
`_const()` to stop backslash expansion; `figures.py:361` and
`comments.py:163` still pass f-strings.

**C3 — Duplication of the walks.** Eight regex literals are defined in
more than one module, including the run and text-node patterns that
every editing bug has come from. `citations.py` alone implements
field-span location three times (`:536`, `:573`, `:1251`) with
different guards — only the third has the defensive `s < pos` check.
Three divergent implementations of "the entry's own bookmark" exist
(`:972`, `:1109`, `:779`). A fix applied to one is not a fix.

**C4 — Coordinate systems are bare `int`s.** Cell index vs grid column,
XML offsets vs visible-text offsets, body vs footnotes part — all
untyped, all interchangeable to the type checker. This produced the A1
italics bug this week and is still live in `tables.set_cell`/`update`
(`:236`, `:363`), which index `tcs[col]` with no gridSpan awareness
while `fit_columns` deliberately tracks the two separately.

**C5 — Failure is advisory.** `LinkAllReport.skipped`/`unmatched` can be
ignored by a caller and a citation ships silently unlinked. `tracked.py`
has **8 blanket `contextlib.suppress(Exception)`** blocks (`:139, 149,
174, 184, 186, 194, 207, 272`), none logging; a partially-degraded build
reports success-shaped numbers.

---

## 2. Defects to fix before anything else

> **Status: phase 0 done (`1739a8c`).** P0-1, P0-2, P0-3 and P0-5 are
> fixed with regression tests; P0-1 and P0-2 are additionally
> mutation-verified (reverting either turns the suite red). **P0-4 was
> withdrawn — the claim below was wrong**; see the note under it. The
> lower-severity `word.py`/`body.py` items in this section are fixed
> too. `tracked.py` went 0% → 58%.

These were found during the analysis and are real. Fix them first; the
rest of the plan is worthless if the deliverable path can eat a file.

**P0-1 — `tracked.build()` overwrites the deliverable before validating
it.** `tracked.py:275` calls `flat_opc_to_docx(flat, out)`, writing
straight to the final path; lint runs at `:290`, verify at `:298`. If
either fails, the previous good deliverable is already gone, and
`guard.stamp()` (`:311`) never ran, so the next run misreads the wreck
as human-edited. `package.write_docx` already stages-then-renames
(`package.py:79-83`) — this path does not.
*Fix:* pack to a temp path, replace `out` only after lint and verify
pass. *Gate:* a test that makes lint fail and asserts the original file
is byte-unchanged.

**P0-2 — Every `build()` leaks a temp directory.** `tracked.py:249`
`mkdtemp`, and `rmtree` appears **zero** times in the file. Each build
leaves a full serialized document behind. *Fix:* `try/finally`.

**P0-3 — `crossrefs` can mint a colliding bookmark id.** `crossrefs.py:180`
calls the shared allocator with the body only; `citations.py:963` calls
it correctly with `(doc, foot)`. Bookmark ids must be unique
package-wide. *Fix:* thread the other parts through, or make the
allocator refuse a single-part call.

**P0-4 — ~~`set_cell`/`update` address the wrong column in any row with
a merged cell.~~ WITHDRAWN: this was wrong.** Checked against the
source: `read_all`, `Table.rows`, `Table.column`, `set_cell` and
`update` are all consistently CELL-indexed, so they agree with each
other, and the Parental Style builders rely on precisely that (Table A1
has a `gridSpan`, and its builder addresses `w:tc` elements). Routing
them through `_cell_walk` would have *introduced* the bug it claimed to
fix. The real hazard is narrower: `fit_columns`/`FitReport` speak GRID
columns, so mixing the two silently addresses a different cell. Both
coordinate systems are now documented on `Table`, and
`Table.grid_columns()` converts between them deliberately.

**P0-5 — `docxkit link --write` is the one mutating CLI path with no
lint gate.** `cli.py:48-67` writes via `edit_in_place` directly, while
`cli.py:263` (`_write_document`) lints for the other commands. Given
that lint is the *only* thing that caught the malformed-XML incident
this session, this is a missing seatbelt on a live path.

*(Lower-severity, same batch: `word.py:136` stages a temp copy before
the `try/finally` that cleans it; `word.py:100` never calls
`CoUninitialize`; `body.py:81` treats `<w:pPr`/`<w:pict` as "already a
paragraph".)*

---

## 3. Validation architecture

The goal: make the invariants unbreakable rather than remembered.

> **Status: V1 and V3 done (`1e127fe`).** V1 landed in a better place
> than planned — see below. V2 and V4 remain.

**V1 — One well-formedness gate, applied by construction. DONE.**
Implemented at `package.write_docx` rather than as a per-mutator
decorator: every editing path in the toolkit lands there before
anything reaches disk, so one gate covers them all — including
`edit_in_place`, the CLI and `tracked.build` — with no per-function
opt-in to forget. It refuses to write a package whose XML does not
parse, and stays well-formedness-only so a fixture or an intermediate
state can still break a *structural* rule (the separate `lint` gate)
without being blocked. Finding the boundary between "never legitimate"
(a parse failure) and "sometimes legitimate" (a schema-order oddity)
is what made a default-on gate safe.

**V2 — Property tests for the whole mutator family.** Every public
mutator shares three invariants worth pinning as properties over
generated documents (Hypothesis is already a dependency):
1. output parses as XML;
2. visible text is unchanged, except where the operation is defined to
   change it;
3. the operation is idempotent where it claims to be.
One parametrized suite over `[fit_columns, superscript_stars,
bottom_border, set_cell, update, shift, smarten, link, link_more,
annotate, apply_template]` replaces a dozen hand-written near-duplicates
and covers combinations nobody wrote by hand.

**V3 — A shared corpus fixture. DONE** (`tests/test_pathological.py`).
Eight specimens, each reproducing a structure that has broken something
here; every mutator runs over all of them asserting parse-survival,
text-preservation and idempotence. It immediately earned its keep by
catching a live instance of the ghost-hyperlink bug in `citations`'
`_LINK_TOKEN_RE`.

Two lessons worth keeping from building it:
* **A pathological fixture is only pathological in context.** The first
  ghost-hyperlink specimen had no real link after it, so nothing could
  be swallowed and the mutation survived. The incident's shape —
  ghost, then prose, then a real link — is what makes it bite.
* **A surviving mutation is not always a gap.** `crossrefs.unlink`
  shrugged off the same mutation because its anchor filter rejects a
  span whose first anchor is not one of its own. That is a genuine
  second line of defence, not a missing test.

**V4 — Calibrate the width model against a real render.** `_ARIAL_NARROW`
(`tables.py:527`) was hand-tuned from one Word PDF. Nothing would catch a
bad edit to that table. Add a marked (`@pytest.mark.word`) test that
renders a known table and asserts predicted vs measured column widths
within tolerance — skipped in CI, run before releases.

---

## 4. Testing the COM layer (the 0% problem)

`tracked.py` reaches Word **only** through the module attribute `_word`
(`tracked.py:38`). That means `monkeypatch.setattr(tracked, "_word",
fake)` isolates the entire pipeline **with zero source changes** — and
`flat_opc_to_docx` is pure and already tested, so the fake can delegate
to it and let `read_parts`, `comments.annotate`, `lint_parts`,
`write_docx` and `guard` all run for real against a tiny in-memory docx.

`tests/test_locate.py:30-137` already establishes the fake-COM pattern
(`FakeDoc`/`FakeRange`/`FakeRevision`). Extend it into `conftest.py` and
reuse.

Order of work:
1. Extract the pure counting/comparison helpers (`tracked.py:63-67`,
   `:295`, `:298-306`) — this is the machinery that detects "Word
   repaired the file", and it is trivially testable today.
2. Fake `_word`; test `build()` end to end, including P0-1 and P0-2.
3. Regression-test `_resolve_math`'s two paths (`tracked.py:122-134`) —
   a documented past bug silently dropped 41 revisions on AFI, and
   nothing pins the equivalence.
4. `BuildReport` (`tracked.py:82-110`) — free, do it last.

*Target: `tracked.py` 0% → 75%+ without Word installed.*

---

## 5. Refactoring for safety

Ordered by defect-prevention per hour, not by tidiness.

**R1 — One walk, one home.** Move the run/text/bookmark/field patterns
and the walks built on them into `_xml.py` as the single source, and
delete the module-local copies (8 duplicated literals). Back-port
`edit.py:39`'s sibling-safe form to `_xml.py:44-50` and `hygiene.py:72`.
Give `_doubled_links` (`citations.py:646`) the self-closing guard that
`_xml.py` and `crossrefs.py` already have.

**R2 — Make the coordinate systems distinct types.** `NewType("GridCol",
int)`, `NewType("CellIdx", int)`, `NewType("XmlOffset", int)`,
`NewType("TextOffset", int)`. Zero runtime cost, and mypy then rejects
the A1-italics class of bug at the call site. Apply to `tables`,
`crossrefs`, `citations.wrap_visible_span` first.

**R3 — Kill the stale-offset hazard.** `Table` carries `start`/`end`
into a string that callers then mutate. Either (a) re-locate on use, or
(b) have mutators return a fresh `Table`, or (c) stamp each `Table` with
a hash of the source and assert it on use. (c) is cheapest and catches
misuse loudly — `fit_columns` and `superscript_stars` document the
hazard in prose today (`:621`, `:837`); `set_cell`, `update` and
`bottom_border` do not even do that.

**R4 — Split `citations.py` (1,394 lines).** Deferred once already, for
good reason (build-critical import path near a deadline). The seam is
clean and now safe to take: `grammar` (patterns, leads, `key_for`),
`parse` (references, citations), `audit` (`_audit_findings`,
`repair_plan`), `repair` (link/wrap/bookmark mutators). `_audit_findings`
alone is 155 lines and 54 branches — the branchiest function in the
package.

**R5 — Make failure non-ignorable.** Give the report objects a
`raise_for_problems()` and call it from the CLI paths; or return a
`Result` the caller must consume. At minimum, log the 8 suppressed
exceptions in `tracked.py` with what was suppressed.

---

## 6. Process guards

Cheap, and they close the loops that keep reopening:

- **`set -o pipefail` in the gate commands.** `cmd | tail -1` ate a
  non-zero exit twice this session (a pytest failure and a ruff
  failure both slipped past an `&&` chain).
- **Never patch source through a bash heredoc.** Backslash-bearing
  patches have been mangled 5+ times (`\b` → backspace, `\1` → `\x01`,
  `\n` eaten this session). Use the Write/Edit tools. This is already in
  memory; it belongs in `CONTRIBUTING` too.
- **Mutation testing in CI for the core modules.** This session's
  8-mutation run found a genuinely missing test (the span rule). Wire
  `mutmut`/`cosmic-ray` over `tables`, `citations`, `edit`, `_xml` with
  a survivor budget.
- **A coverage floor per module**, not just globally — 88% overall hides
  a 0% module.

---

## 7. Sequence

| Phase | Content | Gate |
|---|---|---|
| 0 | P0-1…P0-5 | **DONE** `1739a8c` — P0-4 withdrawn; tracked.py 0→58% |
| 1 | V1 validation gate, V3 pathological corpus | **DONE** `1e127fe` — no path can write unparseable XML |
| 2 | COM seam + `tracked.py` tests | `tracked.py` ≥75% without Word |
| 3 | R1 walks, R2 types, R3 offsets | mypy rejects a swapped-coordinate call |
| 4 | V2 property suite, mutation CI | Survivor budget met |
| 5 | R4 `citations.py` split, R5 reports | Byte-identical audit output on all papers |

Phases 0–2 are the ones that pay for themselves. Phase 5 is optional and
should wait until no paper is near a deadline — the Life Expectancy
resubmission is 2026-08-06.

**Standing gate for all of it:** the three live papers must keep
reproducing byte-identically (LE's rebuild is parts-equal to the shipped
manuscript; Parental Style's property pass is a fixed point at zero
increments; both papers' value verifiers stay at 0 mismatches).
