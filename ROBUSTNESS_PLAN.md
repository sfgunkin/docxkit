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

> **Status: EVERY phase done** (`1739a8c`, `1e127fe`,
> `db612f0`, `a1319e0`, `285253d`). 829 tests, package 91%,
> `tools/mutate.py` 17/17. R2 declined and P0-4 withdrawn, both with
> reasons recorded below.
>
> **Phase 0 status (`1739a8c`).** P0-1, P0-2, P0-3 and P0-5 are
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

> **Status: all four done.** V1 and V3 in `1e127fe` (V1 landed in a
> better place than planned — see below), V2 with the property suite in
> `a1319e0`, V4 on 2026-08-06 — and V4 found the width model already
> wrong by up to 10%, not merely unguarded.

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

**V4 — Calibrate the width model against a real render. DONE**
(`tests/test_width_model.py`, `docxkit.word.ruler`). `_ARIAL_NARROW` was
hand-tuned from one Word PDF and nothing would have caught a bad edit to
it — which turned out to be the wrong worry, because the table was
already wrong. Word was asked for the advance of every printable ASCII
character in each font, and the hour the test first ran it found four
defects:

* `_ARIAL["K"]` was 722 against a true 667 (Helvetica's value), and
  `_ARIAL["P"]` and `_ARIAL["!"]` were in no group at all, so both took
  the 600 fallback — P by 10%, "!" by 116%.
* Every hand-set `_ARIAL_NARROW` override was too wide, digits by 9.9%.
  Arial Narrow IS a uniform 0.820 scaling of Arial: every character
  measures within 0.4% of it, digits exactly (456 = 0.820 x 556). The
  old comment asserted the opposite in so many words.
* Four alias scales were off by 3-5%, three of them *under*-providing,
  which is the direction that wraps a row.

Three things worth keeping:
* **An omitted character is the failure mode to design the test around.**
  A wrong entry is off by a percent or two; a missing one silently takes
  600 and is off by a factor. That is why the test sweeps all of
  printable ASCII rather than a representative sample.
* **The old test asserted the model's mistake.** It pinned digits at 501
  and letters at 0.835 because it was written from the same hand-tuned
  numbers it was meant to check. A test that only repeats what the code
  believes cannot contradict it; this one asks Word.
* **The end-to-end version of this test was written and then deleted.**
  "Fit a table, render it, assert no row wrapped" is the property that
  matters, and it could not fail: `ComputeStatistics(wdStatisticLines)`
  returns 0 for a cell so the assertion never fired, and once that was
  fixed the check still passed with the model scaled to 0.600, the cell
  margins zeroed and `pad` cut to 0.90. `fit_columns` divides a fixed
  total, so a uniform error only changes how the leftover is shared.
  Shipping it would have added the appearance of an end-to-end
  guarantee and nothing else. The reasoning is kept in the test file so
  the next person does not rebuild it.

---

## 4. Testing the COM layer (the 0% problem)

> **Status: done (`db612f0`).** `tracked.py` is at 99% with no Word
> installed. The predicted lever worked exactly as described — one
> monkeypatched module attribute, zero source changes — and the only
> extraction needed was `package_counts()`. The AFI equivalence is
> pinned by a test asserting the two math scans must NOT coincide,
> and reverting to the cheap walk turns the suite red.
>
> Worth recording: the fakes have to model COM's *shape*, not just its
> names. `doc.OMaths(i)` yields an OMath object carrying a `.Range` —
> returning a range directly made the walk silently find nothing and
> the first version of the regression test passed for the wrong
> reason.

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

**R2 — Make the coordinate systems distinct types. DECLINED.**
`NewType` would force every caller to wrap plain ints — including the
paper scripts, which are type-checked since the `py.typed` marker
shipped — and the bug it targets happened in *paper* code, which
internal-only types cannot see. Phase 0 already documented both systems
on `Table` and added `grid_columns()` to convert between them; that is
where the value actually was. Original proposal follows.

~~Make the coordinate systems distinct types.~~ `NewType("GridCol",
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

**R4 — Split `citations.py`. DONE (`285253d`), once the Life
Expectancy paper was submitted and the precondition lapsed.**
Four layers behind an unchanged facade. Two things worth keeping:
* **The re-exports must use `from x import y as y`.** Ruff's `--fix`
  strips a plain re-export as unused, taking with it the private names
  `refstyle` and the tests reach through the facade. PEP 484's alias
  form is the signal that it is deliberate.
* **The layering was already there** — one back-edge (`marker_bookmark`
  reaching forward for a helper filed with the builder) was the entire
  structural change. A test now asserts it stays acyclic, because a
  layering nobody checks is a layering that will not hold.

Original proposal follows.

~~Split `citations.py` (1,394 lines).~~ Deferred once already, for
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

**R6 — One definition of the document's text. DONE.**
R1 put the run/text/bookmark WALKS in `_xml`. The PART NAMES stayed
scattered: the body's spelled 38 times across 16 modules, the footnotes'
19 times across 13. The cost was never a typo — it was that each site
decided for itself what "the document" meant, and three decided wrong in
one week. `renumber` renumbered the body and left a footnote pointing at
the old table (nothing dangled: the old number still existed elsewhere).
`tracked.package_counts` reported "0 pending revisions" — the number the
papers read to decide a document is at truth — for a batch that had
edited only a footnote. `compare`'s integrity layer read a field target
off raw XML and returned the RSID of the next run, never having assembled
the footnote's instruction.

`_xml` now owns `DOCUMENT`, `FOOTNOTES`, `ENDNOTES`, `COMMENTS`, the
`TEXT_PARTS` tuple and `text_parts(parts)`; 14 modules import them and
none spells a part itself. `tests/test_part_names.py` enforces it per
module with a three-entry allowlist, each entry saying why — because a
layering nobody checks is a layering that will not hold, which is what
R4 learned.

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
  8-mutation run found a genuinely missing test (the span rule).
  `tools/mutate.py` now carries 41 curated mutations, each re-introducing
  a defect this codebase really shipped — but curated means "the ones
  someone thought of", and its coverage by module is uneven:

      _table_layout 9   crossrefs 5   revisions 3   _table_core 2
      _xml          6   tracked   5   equations 3   word/package/lint/
                                                    body/_cite_* 1 each

  Nothing for `compare` or the `_compare_*` layers — the authoritative
  gate, ~560 statements — and nothing for `authors`. A GENERIC runner
  finds what nobody thought of, which is the failure mode that bit twice
  on 2026-08-06: a render test that survived the width model scaled to
  0.600, cell margins zeroed AND `pad` cut to 0.90, and an older test
  that asserted the model's own wrong numbers back at it. Both were
  found by hand-mutating; a runner automates exactly that.

  **DONE for the compare stack (2026-08-07), with cosmic-ray.**
  `_compare_diff` (`d344d0d`, `7da6b2d`), `_compare_read` (`be082dc`)
  and `_compare_render` — the last of the three at 204 mutants, 82
  survived, now 9. All nine are recorded as equivalent or cosmetic: six
  are the width of a printed rule, and three are `n > 1` against
  `n != 1` on a count never below 1, and `== "MOVE"` against `is` on an
  interned literal.

  The survivors said one thing: `render()` had its RETURN value tested
  and its OUTPUT tested nowhere, which inverts what the module is for.
  Eleven of them sat on the gate arithmetic — every fixture filled ONE
  bucket, and three of the five gated layers had no test that reached
  the exit code at all, so dropping a term left a real difference no
  longer failing `--expect-clean`.

  Worth keeping: **the run audits the tests, not just the code.** It
  found an assertion of `"italic" in out` that was satisfied by the
  section HEADING — "FORMAT (italic/bold/super/sub/strike…)" — and so
  had never been about the entry it claimed to check. And a mark
  collector that matched only at the START of a string, which silently
  excused the one layer whose content is `"- 0.35"`-shaped lines. Both
  passed green and asserted nothing.

  Checked on this machine (Python 3.14.6): `mutmut` 3.7.0 resolves with
  7 dependencies, `cosmic-ray` 8.4.6 with 15 (SQLAlchemy, aiohttp).
  mutmut is the lighter one. Scope a first run to `_compare_*`, `_xml`,
  `edit` and `_table_layout`; runtime is the only real cost.
- **A coverage floor per module**, not just globally — 88% overall hides
  a 0% module. **DONE** (`tools/coverage_floor.py`): the floors are the
  CURRENT numbers, so a module can never lose coverage, and the
  exceptions name the debt instead of averaging it away. `cli.py` at 52%
  was the one to pay down — it holds every `--write` path, which is the
  code that touches a manuscript. **Paid on 2026-08-07: 60% → 100%**,
  asserting on the FILE (written, not written, what the backup holds)
  rather than on the message. The Word-backed commands are faked at the
  COM boundary rather than skipped — which verdict a set of counts
  earns, and how `--pages 1-3` becomes a first and a last, are decisions
  `cli.py` makes and none of them need Word to be wrong. `word.py` at
  73% is what is left, and most of that is COM itself.

---

## 7. Sequence

| Phase | Content | Gate |
|---|---|---|
| 0 | P0-1…P0-5 | **DONE** `1739a8c` — P0-4 withdrawn; tracked.py 0→58% |
| 1 | V1 validation gate, V3 pathological corpus | **DONE** `1e127fe` — no path can write unparseable XML |
| 2 | COM seam + `tracked.py` tests | **DONE** `db612f0` — tracked.py 58→99%, package 91% |
| 3 | R1 walks, R2 types, R3 offsets | **DONE** `a1319e0` — R2 declined, see below |
| 4 | V2 property suite, mutation CI | **DONE** `a1319e0` — 17/17 caught; found a live escaping bug |
| 5 | R4 `citations.py` split, R5 reports | **DONE** — R5 `a1319e0`, R4 `285253d` |

Phases 0–2 are the ones that pay for themselves. Phase 5 is optional and
should wait until no paper is near a deadline — the Life Expectancy
resubmission is 2026-08-06.

**Standing gate for all of it:** the three live papers must keep
reproducing byte-identically (LE's rebuild is parts-equal to the shipped
manuscript; Parental Style's property pass is a fixed point at zero
increments; both papers' value verifiers stay at 0 mismatches).
