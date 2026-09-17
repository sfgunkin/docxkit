# Mutation testing

The method, the instruments and the measurements — split out of
[`CONTRIBUTING.md`](../CONTRIBUTING.md) on 2026-08-30, where it was 84 %
of the file.

Nothing here is reference material to skim. Every section is a
measurement or a defect found in the instruments themselves, and several
say that an earlier number in this same file was wrong. Read it when you
are about to run a round, argue an equivalence, or quote a figure.

Start with the calibration table and `### A figure is void when the
HARNESS moves, too` — between them they decide whether the number you
are about to compare against means anything.

**Every `revision.py` figure below is VOID.** That module was 3,118
lines until 2026-08-30, when it became `revision/` — fourteen halves,
each its own mutation target. The rows are kept because they record what
was measured and when, and deleting a measurement is not the same as
superseding one; but the source they describe no longer exists, so none
of them is comparable with anything a run can produce today. Per-half
figures also start from a harness that is a superset — see the note in
`tools/harness_map.py` — so a per-half round is a NEW baseline, not a
re-measurement of these.

---

## The first per-half round: `revision/_build.py`, 2026-08-30

Harness: `tests/test_revision.py` + `tests/test_cli_revision.py`.
Quoted here because the figure is only comparable against the same two
files — the map's entry for this half names eight, and a superset can
only kill more, so 0.0 % holds for it as well.

| pass | killed | real survival | what changed |
|---|---|---|---|
| first | 74/139 | **29.5 %** (31/105) | line coverage had just reached 100 % |
| second | 100/139 | **4.8 %** (5/105) | boundary fixtures at the discriminating counts |
| third | 105/139 | **0.0 %** (0/105) | the last five ellipsis mutants |

The 34 remaining survivors are 33 type annotations (PEP 563, never
evaluated) and one keyword-only `*`. Both are equivalent by
construction, which is what `mutation_survivors` discounts them for.

**100 % line coverage and 29.5 % real survival, on the same file, in
the same hour.** Every uncovered line in `_build.py` was a warning or a
refusal, and covering them took four tests that asserted the message
appears. Twenty-six of the thirty-one survivors then said those tests
did not check *what the message says*.

**Three of the four tests were written at counts that cannot
discriminate.** Each of the three warnings names the first N items and
then says how many more, and a fixture above the threshold takes the
same branch whatever the operator is:

* `> 4` against seven parts agrees with `> 3`, `>= 4` and `!= 4`. Only
  a case at exactly 4 separates them, and only one at exactly 5
  separates `> 4` from `> 5`;
* `len(moved) - 4` against seven agrees with `% 4` and `^ 4` — all
  three give 3. They first disagree at **nine** (5, 1, 13);
* `out_of_order` returns six ids for a seven-note reversal, so a
  seven-note fixture is a six-id case wearing a different number, and
  the slice boundary goes untested either way. Seven ids needs a stated
  arrangement, not a reversal.

That is CONTRIBUTING's "build fixture counts from 3, 5, 7" rule arriving
from the other direction: the counts have to differ *from each other*
and *from the threshold*, and which counts those are is a property of
the expression, not of the fixture. Nothing but a mutation round says
which ones they are.

---

### Mutation testing

Coverage says a line RAN. Mutation testing says a test would NOTICE if
that line changed, which is the question worth asking — `_compare_render`
sat at 87% coverage while 82 of its 204 mutants survived.

```
python tools/mutation_session.py src/docxkit/edit.py \
    --tests tests/test_find_edit.py tests/test_edit_branches.py \
            tests/test_normalize_anchors.py tests/test_edit_boundaries.py \
            tests/test_locate_spans.py tests/test_replace_spans.py \
    --sample 460 --seed 20260816 --chunks 0
python tools/mutation_survivors.py .mutation-edit.sqlite src/docxkit/edit.py
```

Pass the module's WHOLE harness, and write down which files it was:
every number below is a statement about a module *and* a set of tests,
and re-running one module against a different harness later gives a
figure that looks comparable and is not. That mapping now lives in
`tools/harness_map.py`, one entry per module, and `measure_all.py` reads
it — so a re-run is comparable by construction, and a module with no
entry falls back to "every test file that names it", which is a starting
point rather than a checked harness.

`mutation_session.py` drives cosmic-ray the safe way, and each of the
four things it does was learned by getting a plausible WRONG number
first (2026-08-15/16; the detail is in its docstring):

* it runs in a **git worktree** with `PYTHONPATH` pointed at it, and
  refuses to start unless `docxkit.__file__` resolves there — otherwise
  it mutates the tree the papers import, editable-installed;
* it **verifies the unmutated harness is green before every chunk**,
  because a terminated run leaves its mutation in the file, and the next
  session then reads 1383 of 1385 "killed" off a red baseline;
* it **clears the null-outcome rows** a termination leaves, or the
  session resumes nothing at all and reports instant completion;
* it forces `PYTHONIOENCODING=utf-8`, because cosmic-ray decodes a
  KILLED mutant's pytest output as UTF-8 while pytest writes the console
  codepage — the em-dashes in this package's messages then turn kills
  into INCOMPETENT, dropping them out of the denominator, and cost 60x
  in wall clock as well.

`tools/mutate.py` is the other half and the curated one: 42 mutations,
each re-introducing a defect this package has really shipped, and every
one of them must turn the suite red. **It runs in CI, in its own job,
and not in `tools/gates.py`** — measured 2026-08-27 at **18m23s** for
the full set at `-n <physical cores>`, against about four minutes for
the whole local chain. A pre-commit gate five times longer than the
thing it guards is one people route around.

Two things it learned the hard way, both on 2026-08-27:

* **a killed run leaves its mutation in the tree.** The restore is a
  `finally`, and a kill is not an exception — an unattended run is
  stopped by being killed. One left `_set_borders` carrying its sabotage
  through an hour of unrelated work and into a batch about to be
  committed, reading the whole time as "my change broke five tests". The
  pre-mutation bytes now go to `.mutate-in-flight/` first, the next run
  REFUSES and names the file, and `--restore` puts it back. **If you see
  that directory, a source file is carrying a deliberate defect.**
* **run it on a quiet tree.** It edits `src/docxkit/` in place, so a
  pytest run started beside it reads a mutant and fails for reasons that
  have nothing to do with the change in hand. That happened here too,
  and cost a false diagnosis before the diffstat gave it away.

A DRIFTED anchor is as bad as a survivor and is reported separately: the
mutation stops testing anything and the tool exits 1 to say so. Three had
drifted by the time anyone looked — one on indentation, one on a regex
that gained a guard, and one because the function MOVED to another module
while its anchor text stayed valid. `tests/test_mutate.py` checks every
anchor against its module on every suite run, which is the fast half of
this gate and the one that catches the failure that actually happens.

A chunk is also the unit that survives being KILLED. When the run is
backgrounded under anything that caps runtime — CI, an agent harness —
size the chunk to fit inside the cap (`--chunks 1 --minutes 8`) and call
it again rather than asking for `--chunks 0` and hoping. Measured
2026-08-16: a capped background run was killed at 367 of 460 mutants,
having left its mutation in the worktree file and a row unfinished, and
the next chunk restored the file, cleared the row, re-verified the
baseline and carried on. Nothing was lost but the mutant in flight.

`--sample N` with a fixed `--seed` redraws the same mutants across
`init`s — cosmic-ray enumerates specs in a stable order — but only
against a session THIS tool sampled. Two 460-draws of `edit.py` made by
different code, same seed, overlapped by 33 %.

**To compare two suites, re-run the earlier session's SURVIVORS, not a
fresh sample.** Under a harness that only gained files a mutant can move
survived -> killed and not back, so the survivors are the entire
question: 85 mutants instead of 460, and the answer is exact instead of
sampled. Copy the old session, delete its `SURVIVED` rows, and exec it
against the new harness — cosmic-ray re-runs only the specs with no
result. Recover the old harness before trusting the comparison: the
session database does NOT record the test command, and a number measured
against a different set of test files is not comparable however
identical the mutants are. Keep the `cr-*.toml` beside the database.

**To check a TEST refactor, compare survivor SETS, not percentages.**
The source is unchanged, so the specs line up exactly: run the module
once against the old test file and once against the new, and diff the
survivors. Equal counts are not equal sets, and only the set answers
"does the consolidated suite still kill everything it killed?".
Measured 2026-08-17 after four test files were consolidated onto
`conftest`: `wordcount.py` 28 survivors of 98, `export.py` 18 of 194,
both sets IDENTICAL either way.

The same caveat applies one level up: a hand-written kill check goes
STALE the moment the source it names changes. Re-running yesterday's
scripts today reported seven "regressions" in `rebuild` that were the
S4 fix making that line unreachable, exactly as recorded when the fix
landed. Read a red line against what the source has done since before
believing it.

**A survivor re-run needs the module BYTE-IDENTICAL.** Specs are
addressed by (row, column), so a line added anywhere above them
re-points every one below it at code nobody chose — and the run
completes and reports a number either way. Fixing a defect in the
module therefore ENDS the series that measured it, and the next
measurement is a fresh draw starting a new one. Say so when you record
it; two numbers from either side of a source change are not a
comparison however carefully the seed was kept.

Measured on `edit.py`, 2026-08-16: **13.0 % -> 11.6 %** real survival,
six of fifty-six, no new survivors. A FRESH 460-draw of the same source
under the same six test files read **15.5 %** — same population, other
mutants. That gap is what a single sample is worth, and why the survivor
re-run is the design to reach for.

**Do not read `cr-report`'s percentage.** Every module here carries
`from __future__ import annotations`, so annotations are strings that are
never evaluated and a mutation inside one cannot change behaviour. On
`styles.py`: 225 survivors, **187 of them inside a type annotation** —
equivalent by construction, not missing tests. The headline said 56%
survival where the real figure was 9.5%, and a number like that is how a
tool stops being run. `tools/mutation_survivors.py` splits them and
prints only the ones that are a question.

What five real runs cost and bought, for calibration:

| module | mutants | real survivors | after |
|---|---|---|---|
| `styles.py` | 399 | 38 | 12 |
| `footnotes.py` | 494 | 76 | — |
| `revisions.py` | 858 | 120 | 73 |
| `_compare_read.py` | 449 | 51 | — |
| `equations.py` | 1,323 | 312 | — |
| `tracked.py` | 478 | 97 | — |
| `revision.py` | 1,066 | 60 | — |
| `cli.py` | 728 | 206 | — |
| `crossrefs.py` | 841 | 168 | — |
| `comments.py` | 732 | 244 | — |
| `_table_layout.py` | 2,217 | 382 | — |
| `edit.py` | 1,361 | 56* | — |
| `_cite_build.py` | 1,026 | 114* | — |

\* sampled (460 mutants), not a full run, and each measured across
several rounds of the tests the numbers asked for: `edit.py` 17.3 % ->
11.6 % real survival, `_cite_build.py` 41.1 % -> 25.2 %. The last figure
in each is PAIRED against the round before it (survivor re-run, same
mutants, harness a checked superset); the earlier ones are separate
draws and carry a couple of points of sampling noise.

**The sweep of 2026-08-17**, one module at a time, whole runs rather
than samples, each against the harness `tools/harness_map.py` names for
it (`python tools/measure_all.py --all` is the sweep; it is sequential
because the sessions share one worktree):

| module | mutants | real survival | worst cluster |
|---|---|---|---|
| `probe.py` | 168 | 36.9 % | `probe` 40 |
| `ingest.py` | 185 | 35.1 % | `build_overrides` 50 |
| `figures.py` | 653 | 30.8 % | `set_alt_text` 49 |
| `wordcount.py` | 98 | 28.6 % | the bucket defaults 12 |
| `pages.py` | 136 | 24.3 % | `sheets` 15 (needs Word) |
| `console.py` | 29 | 24.1 % | `_reconfigure` 6 (needs a console) |
| `testing.py` | 87 | 23.0 % | `prose_numbers` 16 |
| `body.py` | 251 | 14.7 % | `table` 17 |
| `find.py` | 262 | 13.4 % | `page_break_before` 11 |
| `export.py` | 194 | 9.3 % | `_pipe_table` 12 |
| `authors.py` | 108 | 8.3 % | `_collapse_people` 3 |
| `lint.py` | 506 | 8.3 % | `lint` 37 |
| `guard.py` | 50 | 6.0 % | — |
| `_compare_render.py` | 207 | 5.3 % | `_head` 4 |
| `_cite_repair.py` | 199 | 4.5 % | `wrap_link_in_bookmark` 4 |
| `errors.py` | 10 | 100 % | the exception classes |
| `tables.py` | 0 | — | a re-export facade: nothing to mutate |

and the second wave, of the modules the survivor ledgers were open on
(sampled at 460 where the module is bigger than that, seed 20260816):

| module | mutants | real survival | first measured |
|---|---|---|---|
| `_cite_audit.py` | 457 | 41.1 % -> **15.1 %** | — |
| `_compare_diff.py` | 605 | 28.4 % -> **16.2 %** | — |
| `package.py` | 336 | 25.6 % | — |
| `hygiene.py` | 536 | 19.6 % | — |
| `_table_core.py` | 821 | 44.9 % -> **12.9 %** | — |
| `edit.py` | 425* | 11.5 % | 17.3 % |
| `_cite_build.py` | 392* | 9.4 % | 41.1 % |
| `renumber.py` | 460* | 5.7 % | 15.1 % |
| `_xml.py` | 441* | 5.4 % | 8.7 % |

`_table_core`'s two figures are the SAME run with the harness corrected:
the first was missing `tests/test_tables_update.py` and reported 216
survivors in `update`, which came back as 32 once the file that tests it
was in the run. The other two arrows are a full run followed by a
460-sample after the tests the first asked for, so those PERCENTAGES are
not strictly comparable — the clusters are: `_cite_audit`'s
`_audit_findings` went 106 -> 36 and `_doubled_links` 61 -> 18,
`_compare_diff`'s `label_moves` 31 -> 8, `replaced` 21 -> 6,
`formula_diff` 17 -> 8, and `integrity` 12 -> 0.

\* sampled. The four with a "first measured" figure are the ones whose
BACKLOG ledgers this closed; each is a FRESH draw, because every one of
those modules changed under the tests written for it and a paired series
does not survive that (see the byte-identical rule above). Fresh draws
read a few points higher than paired ones on the same source — `edit.py`
was 15.5 % fresh against 11.6 % paired on one occasion — so compare
fresh with fresh.

`errors.py` is not a failure: ten mutants, all of them renaming an
exception's docstring or its base, and the module IS the names. It is
listed so the next reader does not re-run it expecting a number.

**The third wave, 2026-08-18** — 460-sample draws of the modules the
second wave had not reached, and the tests written off them the same
day. Only `tracked.py` has been re-measured; the rest are the FIRST
figure and nothing more, and the tests named beside them are not in it:

| module | measured | after one round | after the next | what the rounds wrote |
|---|---|---|---|---|
| `tracked.py` | 36.3 % | 28.5 % | **9.4 %** | the untracked report, the Word path, the build report |
| `equations.py` | 24.9 % | 10.6 % | **10.4 %** | `prose_math`'s window, five OMML shapes, the interval branch |
| `_table_layout.py` | 18.4 % VOID | 21.0 % VOID | **12.2 %** | the harness lacked three of its files; then an S2 and an S1 |
| `cli.py` | 17.7 % | **9.1 %** | — | what `math`, `inspect`, `count`, `tasks`, `figures`, `revision ingest` and `validate` PRINT |
| `comments.py` | 17.4 %\* | 24.2 % | **14.7 %** | the two rewrites, the two distances, and an S1 in the flag |
| `crossrefs.py` | **20.8 %** | — | — | the caption-bookmark window, one run cut into three, the loop |
| `footnotes.py` | 15.6 % | **7.9 %** | — | the MARKS' half of the size report |
| `revision.py` | 14.3 % | — | — | the glyph report's two thresholds |
| `_compare_read.py` | 12.6 % (full run) | 9.8 % | **8.8 %** | `mask_volatile_fields`' scan, `pair_parts`' threshold, the address map |
| `_table_core.py` | 12.9 % | **9.6 %** | — | `update`'s block arithmetic |
| `styles.py` | 8.7 % | — | — | — |

\* incomplete: 178 of the 450 it sampled, and the percentage is over
what ran — which is why the complete run beside it reads HIGHER, not
because anything got worse. 24.2 % (93 of 385) is the module's first
whole figure, and the tests written off it are not in that number
either. `_table_layout`'s first figure is void for a different reason
— see the BACKLOG entry: three of its five harness exclusions were never
true, and a run missing the files that cover a function invents
survivors in it.

**The two `_table_layout` figures are not a comparison, and the second
is the real one.** 18.4 % came from a run whose harness was missing
three of its test files; 21.0 % (92 of 439) is the same module under all
eleven. A corrected harness reading HIGHER is not a paradox — the two
runs are different draws of a 2,834-mutant module sampled at 460, and
the earlier session's parameters are not recorded anywhere, so nothing
justifies calling them paired. What IS a comparison is the function the
exclusion hid: `drop_blank_rows` went from 12 survivors to **1** the
moment `tests/test_tables_blank_rows.py` joined the run.

**The fourth sweep, 2026-08-18 (evening)** — the modules that changed
under a fix that day, plus the two whose lists had been unusable:

| module | figure | against |
|---|---|---|
| `probe.py` | **25.0 %** (42/168) | 36.9 % before its round |
| `comments.py` | 18.4 % (71/386) | a FRESH draw: the module changed |
| `crossrefs.py` | **16.0 %** (71/445) | 20.8 % before its three rounds |
| `_table_layout.py` | 15.0 % (66/441) | a FRESH draw: the module changed |
| `hygiene.py` | **10.4 %** (47/451) | first measured |
| `figures.py` | **6.6 %** (28/427) | 34.1 % on 08-17 |
| `ingest.py` | **6.3 %** (12/189) | 35.1 % on 08-17 |
| `_xml.py` | **4.5 %** (20/444) | 5.4 % in the second wave |
| `find.py` | **4.5 %** (9/202) | 13.4 % in the first sweep |

Two of those need saying out loud.

**`comments.py` and `_table_layout.py` read HIGHER than their previous
figures and are not regressions.** Both had a defect fixed that evening,
which ends the series: a fresh draw of a changed module is a different
population, and the numbers either side of a source change are not a
comparison however carefully the seed was kept. The rule is in this file
already; these two are what it looks like in practice.

**`figures.py` was called the largest unpinned pool in the package on
the strength of a stale list, and it was not.** Its 08-17 run measured
34.1 % with 234 real survivors, the source changed eight minutes later
(`90eb4ed`, the drawing-window fix and its tests), and nothing
re-measured it — so the number went on being quoted while the work that
answered it had already been done. Freshly drawn it is 6.6 %, the
same evening's `ingest.py` 35.1 % is 6.3 %, and the largest pools left
are `crossrefs` and `comments` at 71 survivors each.

A figure whose source has moved is not a small inaccuracy: it points the
next round at the wrong module. Re-measure before quoting, and the
cheapest way to know is `git log -1 -- src/docxkit/<mod>.py` against the
session file's mtime.

**The fifth sweep, 2026-08-19 (overnight)** — every module whose
harness had not been read since the fourth, measured sequentially in a
second worktree while the tests below were being written:

| module | figure | against |
|---|---|---|
| `refstyle.py` | **44.1 %** (173/392) | first measured |
| `citations.py` | **32.2 %** (29/90) | first measured |
| `_cite_grammar.py` | 14.9 % (65/435) | first measured |
| `revision.py` | 13.7 % (50/365) | 14.3 % on 08-17 |
| `tracked.py` | 12.0 % (39/325) | 9.4 % after its three rounds |
| `revisions.py` | 9.2 % (39/422) | first measured |

`refstyle` at 44.1 % is three times the next module and the reason is
one sentence long: **not one of its 47 tests read `i.where`.** Every
issue the audit reports could have been filed against the wrong
paragraph and the suite would have stayed green — and `where` is the
whole usefulness of the report, since "the list is not alphabetical"
without a paragraph number is a list of forty entries to re-read by eye.
87 of its 173 survivors were in `audit` alone, sitting on
`f"¶{r.index + 1}"` and the snippet slices beside it.

`tracked` reads HIGHER than its 9.4 % and is not a regression: the S1
fix of 2026-08-18 added `structure_counts` and `structure_diff`, and
they went in through `build` and `validate` alone. New code arrives
unpinned; a module's figure going up after a fix is the sweep noticing
that.

**What the round found, beyond the percentages.** Two defects and a
dead branch, all three surfaced by writing a fixture per case rather
than by the numbers:

* `repair_plan` promised three issues and printed two. A
  reference-section bookmark whose name does not parse as author+year
  draws both an `ORPHAN REF` and a `REF WITHOUT CITE`, and the second
  fits none of the three readings in that branch — it fell out of the
  loop unfiled while the header counted it. Now filed under
  `investigate`, with the count-vs-lines agreement pinned as an
  invariant over four fixtures;
* `restore_math_glyphs` and `restore_parts` each stopped their walk at
  the first part they skipped, in the sense that nothing said otherwise:
  every `continue` in them was free, because each fixture happened to
  have the skipped item LAST. A package with a picture in it (the media
  part sorts before `word/document.xml`) would have lost the glyph
  repair entirely;
* `fix`'s second guard could not fire. `wanted` is keyed on the
  downgraded form and drops every entry whose value equals its key, so
  `wanted.get(text)` never returns `text`. Four mutants were living
  inside `or back == m.group(2)`; it is gone, with the argument in its
  place.

### An equivalence argued once should not be argued again

Some survivors are not gaps: the mutation changes the source and cannot
change behaviour. Annotations are discounted wholesale, but the
interesting ones are specific — `range(lo, hi + 1)` where `hi` is
filtered by the next clause, an early return whose work is a no-op.
Argue one of those in a commit message and the next sweep re-derives it
from nothing, because the survivor list looks exactly the same.

`tools/equivalents.toml` records them, keyed on the line the mutation
PRODUCED — a row number does not survive the module moving.
`mutation_survivors` takes them out of the numerator AND the
denominator, the way it treats annotations.

A wrong claim improves the module's figure, which is the one direction
of error nobody checks. So `python tools/verify_equivalents.py` applies
every claim and expects it to SURVIVE. A claim that starts being killed
has not been vindicated — the code or the harness moved and the argument
no longer describes them. Delete it and decide afresh. Run it after
changing a module whose claims touch the lines you moved.

**What it costs, and the two things that went wrong for being unsaid.**
One harness run per claim: scoped to the module you moved that is
minutes, which is the everyday use above. The whole file was 899 claims
across 46 modules on 2026-09-18 — hours, and this is the run nobody
makes. Ten claims orphaned by `effef6c` sat unreported for exactly that
reason, found later by a round doing it by hand. `--jobs N` deals the
modules out to N workers, each with a `kill_check` checkout of its own
(and so a lock of its own), longest module first: 341 claims over 18
modules took 12 minutes at four workers against an hour and more
sequentially.

And the EXIT CODE now carries the finding. `check` returns how many
cases did not match their expectation, and the tool threw that away: a
run in which three claims were killed printed three `!!` lines and
exited 0. The lines are what a person reads, the code is what a script
reads, and they disagreed — on the one tool whose whole subject is a
claim that has quietly stopped being true.

### Many survivors on ONE line is a design question, not a missing test

The usual survivor is a line whose behaviour no test happens to reach,
and the answer is a test. A line carrying a whole CLUSTER is a different
finding, and reading it as the usual kind wastes the signal.

`refstyle`'s converter had 15 of its real survivors on one line:

```python
at, end = max(0, et.start() - 1), et.end() + 1
```

Every arithmetic variant lived — plus one, minus two, shifted, xor'd.
That is not "no test covers this window". A window can only have one
right value, so fifteen wrong ones surviving says the value was never
what mattered: the line was widening a fragment by a fixed amount when
what the code needed was a fragment that occurs ONCE. On an entry
ending in a bare "et al" — no trailing character to widen into — the
fragment became a substring of an occurrence already rewritten, and
`--fix` wrote "et al.." into the first one while leaving the real one
bare. A live corruption of the author's bibliography, shipped.

So when the survivors pile onto one line, ask what the line is FOR
before writing a test for it. A test written against that line would
have pinned the arithmetic and the bug with it.

Two things the chase depended on:

**Simulate the loop the code actually runs.** The first model of the
settle loop added to `seen` as it applied, where the real one updates at
the END of a pass. That single difference reported the two-occurrence
case as killing seven mutants when it kills none, and would have aimed
the test at the wrong entry entirely.

**A guard against a HANG needs a timeout, not an assertion.** The left
boundary here stops an index going negative, where the fragment reads as
`""` and `count("")` never falls to 1. Remove it and the suite does not
fail — it stops. That test carries `@pytest.mark.timeout`, because the
regression otherwise reads as a broken machine rather than as this line.

### Subtraction hides inside its operands

The "mutant that survives at zero" note below has a second half, and it
cost more of this round than any other single thing. `a - b` is not
only `a + b`, `a | b` and `a ^ b` when `b` is 0 — it is also **`a % b`
whenever `b <= a < 2b`**, which is the ordinary case for an offset
measured from something just before it, and `a // b` whenever `a < 2b`.

Both of the package's run-splitting functions cut at `tm.start() -
r_open`: where a text node begins, measured from where its run begins.
Every fixture used a run with no properties, so that distance is five
characters and every operator agrees. What makes it real is `w:rPr`:
Word writes one on every run it has touched — fonts, size, language,
and the complex-script twin of each — and 210 characters of properties
between `<w:r>` and `<w:t>` is an ordinary paragraph, not a constructed
one. At that distance `%` gives 0 where `-` gives 215.

The same shape in three other places, each needing its operands chosen
rather than written:

* `end - ls` against `end % ls` needs the last run to start before HALF
  the span's end;
* `len(content) - len(content.lstrip())` against `%` needs a caption
  indented by MORE characters than its own text — fifteen spaces, where
  an ordinary indent leaves the two spellings equal;
* `index(">") + 1` against `| 1` needs the index to be ODD, so
  `<w:r w:rsidR="00A1">` (twenty characters) and never `<w:r>` (five).

The rule: before writing the assertion, put the fixture's actual numbers
into every operator the mutation tool substitutes. If two of them agree,
the fixture is the thing to change.

### An empty run moves no glyph

`sp[1] > at` against `>=`, and `end < le` against `<=`, both decide
whether a run that touches the span's edge joins it. Under the wider
comparison an EMPTY run is written into the output — inside the
hyperlink at one end, after it at the other. Word renders that as a blue
space before the citation, and every text-identity assertion in the
suite passes straight over it, because an empty run carries no
characters. Count runs, not text, wherever a rewrite chooses boundaries.

### `is not` is not `!=`, above 256

`structure_diff` compared two counts with `!=`. Python caches integers
up to 256 and creates the rest, so two counts of 300 are equal and are
NOT the same object: under `is not` every manuscript with more than 256
of any structural tag reports a change that did not happen, and `build`
raises on it under `reject_check`. A paper with 300 table rows is an
ordinary paper. The mutation tool substitutes `is`/`is not` freely and
most of the time it is genuinely equivalent — the exception is any
comparison of COUNTS, and the fixture that tells them apart needs the
count above 256.

### Two more shapes worth naming

**A `continue` in a walk over parts is free unless the skipped item is
first.** Every one of them in `hygiene` and in `_cite_grammar`'s part
loop was, because packages in fixtures hold exactly the parts the test
needs and in the order the test wrote them. Put the skipped thing first.

**An exemption matched by `==` must not become an order comparison.**
`revision._names` decides whether `--accept-loss <token>` acknowledges a
loss, and under `>=` every token sorting above the key names it — a
misspelled flag acknowledges a footnote that really went. One wrong
token can only be on one side of the key, so the test needs both.

**The rest of the fifth sweep**, once the queue reached them:

| module | figure | against |
|---|---|---|
| `cli.py` | **8.6 %** (39/454) | 9.1 % after its round |
| `footnotes.py` | **7.8 %** (31/399) | 7.9 % after its round |

**And the same night, measured again.** The rounds above wrote tests;
this is what a second sweep said about them, run in a third worktree
(`DOCXKIT_MUT_WORKTREE=D:/docxkit-mut3`) while the writing went on:

| module | before | after | what the round wrote |
|---|---|---|---|
| `refstyle.py` | 44.1 % | **8.9 %** | where every issue says it is, and both sides of every exemption |
| `citations.py` | 32.2 % | **6.7 %** | one fixture per damage class in `repair_plan` |
| `probe.py` | 25.0 % | **12.5 %** | what the report prints, not just what it counts |
| `_cite_grammar.py` | 14.9 % | **7.6 %** | offsets where subtraction is not addition |
| `revision.py` | 13.7 % | **9.3 %** | the arithmetic in the gate before the baseline |
| `hygiene.py` | 10.9 % | **4.4 %** | the scans that must not stop, and a guard that could not fire |
| `comments.py` | 15.8 % | 13.6 % | the reference walk, read as a string |
| `crossrefs.py` | 12.9 % | 11.2 % | offsets measured from a run Word actually wrote |
| `tracked.py` | 12.0 % | **8.6 %** | the structure counts, called directly |

**These are floors, not finals.** The sweep ran while the tests were
still being written, so several modules' harnesses grew after their own
run — `refstyle` took two more rounds after its 8.9 %, `probe` one. A
figure measured against a harness that is still moving is worth less
than one measured against a still tree, and the honest way to read the
table is "at least this much better".

The two modest ones say something too. `comments` and `crossrefs` each
had ONE cluster addressed out of several, and each moved by about what
that cluster was worth. A round that reads one function deeply moves a
module's figure a little; a round that reads what the module SAYS moves
it a lot, because the unread values are spread across every function
that reports.

### An empty element is self-closing

Three defects in one night, all the same shape, and none of them found
by the sweep — they were found by reading for the shape after the first
one turned up:

* `set_core_property` matched only `<dc:title>…</dc:title>`, so a
  document whose title Word had emptied (`<dc:title/>`) took the
  "absent" branch and ended with TWO title elements, which
  CT_CoreProperties forbids;
* `set_run_text` matched only the paired `<w:t>…</w:t>`, so a write into
  a run whose text had been deleted landed nowhere and reported success.
  `tables.set_cell` into a blank cell handed back the document
  unchanged;
* the two repair helpers in `_cite_repair` paired a GHOST
  `<w:hyperlink w:anchor="X"/>` with the next `</w:hyperlink>`
  downstream, so `wrap_link_in_bookmark` wrapped its bookmark around the
  prose between them and around another work's citation.

The package already knew the shape four times over — `own_properties`
handles `<w:tcPr/>`, `_table_layout`'s border and cell-margin patterns
carry BOTH forms with a comment saying why, `lint` check 7c exists
because a border writer once inserted a second element beside an empty
one, and `_xml._HYPERLINK_EL_RE` carries `(?<!/)>` for the ghost.
Knowing it in four places did not stop three more from being written.

**So it is worth a grep rather than a memory.** Every pattern in this
package that ends `</w:something>` or `</dc:something>` is a claim that
the element is never empty. For a READER an empty element read as absent
is usually harmless; for a WRITER it is the defect, because the answer
to "absent" is to insert one — beside the one that is already there.

### And a property present TWICE, which is the writer's half of it

The same night's other shape, and the same reading found it: five
writers, each taking the FIRST copy of a property and stopping.

* `_xml.set_para_property` removed one child and re-inserted;
  `set_run_property` replaced the first and returned;
* `_table_layout._set_tbl_pr` removed one match of its pattern;
  `_set_tc_w` substituted with `count=1`;
* `crossrefs._with_hyperlink_style` did the same to `w:rStyle`;
* `edit._run_italic` and `edit._run_vert_align`, found by reading for
  the shape after the other five — seven and eight.

Two of one property in one properties element is invalid and ORDINARY.
A style turns `keepNext` off with a second `w:val="0"` element beside
the one that turns it on; a run salvaged out of two carries `w:sz`
twice; and this package itself shipped a release that wrote misplaced
properties, so the documents needing the repair are exactly the ones a
re-run has to fix. Taking one copy out leaves the stale element sorting
FIRST — which is the reading Word takes — and asked to REMOVE the
property, every one of them left it in place.

So a writer's contract is not "replace the property" but **"leave
exactly one, and it is mine"**. Back to front so the earlier offsets
stay good, and over the LIVE properties only: `w:rPrChange`,
`w:pPrChange` and `w:tcPrChange` hold a snapshot of what a tracked
change replaced, and a copy in there is the record, not a duplicate.

This was pinned the OTHER way once, on 2026-08-19, off a fixture of
identical twins — the one shape where the harm does not show. A test
that says "the document unchanged" is only as good as the fixture that
made it: give it the `w:val="0"` copy and the same code answers with
the stale element first.

### A figure says nothing about behaviour that lives in DATA

Widened 2026-09-18 from the version below, by the `lint.py` census, and
the correction matters: the class is not "a regex". It is any behaviour
living in data the mutation operators cannot reach, and a TAG TUPLE is
the commonest shape of it in this package — invisible to anyone
filtering for `re.compile`, which is what the first version of this
section would have had them do.

`lint.py` holds no regex at all; it walks lxml. Its behaviour lives in
ten tag constants, and cosmic-ray can no more take `"tc"` out of a tuple
than it can drop an alternative from a pattern. Deleting one member at a
time — 51 cases through `kill_check`, each compiled first so a broken
import could not read as a kill — left **36 survivors**, against a
harness that was if anything too wide.

Two of the 36 are worse than a quiet check:

* `_PARTS` decides which parts are read AT ALL. Drop `endnotes.xml` or
  `comments.xml` and a paper using either gets NO structural lint — and
  a journal that sets endnotes is an ordinary paper.
* `_MARKER_PARENTS` fails the other way. A row-level revision is a
  self-closing `w:ins` inside `w:trPr`, so with that half gone every
  tracked table row reads as an empty revision — and three callers
  refuse a WRITE on lint's answer. A gate nobody can pass on any redline
  that touches a table.

The fix is a parametrisation per constant, so that THE PARAMETRISATION
IS THE CONSTANT and a tag added without a case is a tag the census
finds.

### And the first instance of it: a REGEX

The sharpest limit of this whole campaign, found 2026-09-18 by the
`footnotes.py` round, which had nothing to work on.

`footnotes.py` read **REAL SURVIVAL 0.6 % (4/679)**, and all four were
cosmetic quote widths already claimed. An empty list. But
`_NOTE_CONTENT_RE` — the four lines that decide WHICH carriers make a
note more than a shell — had no mutant planned on it at all, and neither
did `_orphan_of`. Cosmic-ray mutates operators, comparisons and numbers.
The carrier list is a pattern STRING, so there is nothing in it for a
mutation operator to take hold of.

Hand-mutated instead, with `kill_check` over twelve cases — each
deleting ONE alternative or one `delText` guard, and each checked to
still compile as a regex, so an import error could not read as a kill —
**four survived**: `w:hyperlink`, `w:drawing`, `w:tbl` and `m:oMath`.
Delete any one of them and a note holding only a link, a figure, a table
or an equation reads as a shell, and `prune_orphans` CUTS it off the
page. That is the exact defect the pattern was widened for on 09-17, and
the sweep could not see it. Every legacy twin added that day (`w:pict`,
`w:object`, `w:sym`, `w:contentPart`) was killed by the test that
motivated it; it was the four the pattern had named since it was written
that nothing pinned.

**So a low figure on a regex-driven module is not evidence.** It is the
absence of a question. Two other modules carry the same shape and are
worth the same treatment before their figures are believed: `lint.py`
and `_cite_audit.py`.

The method, which is cheap: take the pattern apart one alternative at a
time, delete exactly one, confirm the result still COMPILES, and run the
harness. A fixture for a survivor must hold ONE carrier and nothing else
a reader sees — with two, dropping either alternative leaves the note
occupied by the other and the case proves nothing.

### A figure is void when the HARNESS moves, too

The rule above checks the source's commit time against the session file.
The other half cost this round an hour: `equations.py`'s survivor list
reported the `pieces[k + 1]` mutants as live, and they had been killed
an hour before the run by a fixture committed into their own harness.
Tests were written for mutants that were already dead.

`python tools/stale_figures.py --stale` answers it for every module at
once — the session file's mtime against the newest change to the module
AND to every test file `harness_map` names for it, commit time and
working-tree mtime both, because an uncommitted test is the one a run is
most likely to have picked up by accident. Run against the package at
the end of this round, 36 of 38 entries are stale and two modules have
never been measured at all.

### Three kinds of stale, and only one of them is void

`stale_figures.py` prints the same word — `stale`, with the files that
moved — for three situations that cost very different amounts. Which one
it is decides whether the answer is an hour of a stream or a sentence.

**The module moved: the figure is void.** A survivor is a line number
into a file that no longer has those lines, so the mutants are different
mutants and nothing carries over. `replay_survivors` refuses by design
rather than anchoring a case on whatever line has since slid into place.
Re-sweep.

**A claim needed a source edit to anchor: also void, and the edit looks
harmless.** `verify_equivalents.anchored` insists a claim's `was` be
exactly one line of the module, so a line the module writes TWICE cannot
be claimed until it is made unique — the trailing-comment convention,
00ca560 for `_xml.py`'s two `INSTR_RE.findall` lines and e4a050a for
`authors.py`'s two `if out != text:`. The comment changes the module,
and the session then renders its mutants from a source that no longer
exists: `authors.py` went from four argued survivors to "2 to actually
look at" — 1.9 % (2/105) — the moment the comments landed, and the
replay refused with *"authors.py itself has moved since the run"*
(2026-09-18). Nothing is wrong with the claims and the figure is wrong
anyway. The re-sweep is part of the price of disambiguating, and belongs
in the decision rather than in the next reader's afternoon.

**COPY THE SESSION ASIDE before that re-sweep**, when the point of it is
to measure what a change was worth. A re-sweep writes over the session
the old figure came from, so it destroys the evidence for its own
effect: the new number can be CONFIRMED against a prediction and cannot
be SCORED against one. `find.py` came back at 1.0 % (3/288) against a
predicted 3 and a previous 21 (2026-09-18), and the split — thirteen
claims that now anchor, five mutants the round's own tests kill, three
that no claim could key on — had to be read out of the round's commit
message, because the before-state was gone. `.mutation-<stem>.sqlite`
and its `.pristine/` beside it are the whole of what to keep.

**The harness only GAINED tests: the figure is an UPPER BOUND**, and
usually good enough to act on. A test added after a run can only KILL
mutants; it can never raise a survivor. So a module that has not moved,
under a harness that only grew, is at most the rate on record, and
re-running it buys a number that can only be lower. On 2026-09-18 that
stood behind `revision/_init.py` at 0.0 % (0/269) and `exhibits.py` at
0.2 % (1/643), both reported OF THE TREE AS PLANNED after tests landed
under them — a bound of zero IS the figure, and "at most 0.2 %" was
worth more than an hour of a stream.

Two limits, and they are what makes the bound honest. It does not hold
when tests were REMOVED: a trim that deletes a test can raise a
survivor, so a round that deletes one is re-swept rather than bounded.
And it does not hold when the module moved as well — `revision/_promote.py`
changed in f856e4d, which is the first case, whatever its harness did.

### And void when the tree moves DURING the run — the worst kind

`tracked.py` stands at 4.9 % (29/589), verified, every remaining
survivor argued. Re-measured the same evening it came back at **28.9 %
(237/821)**, and the shape of the survivor list was the tell: 66x
`_seed_scaffold`, 33x `<module>`, 33x `format`, 33x `_comment_revision`,
22x, 22x, 11x. Every cluster a multiple of eleven, which no real harness
produces.

`chunk()` puts the module back before each chunk, because cosmic-ray
leaves its mutation in the tree when a run is terminated — and it copied
the file from the WORKING TREE. Work carried on in that file while the
sweep ran, so the source was swapped half way through: the plan
describes one file and the later chunks mutate another, while the
harness in the worktree is still the copy taken at startup. The
timestamps say it plainly — the worktree's `tracked.py` at 19:28, its
`test_tracked_build.py` at 18:46.

Nothing failed, and the number is not a regression, an artefact of
sampling, or a hard module. It is not a measurement of anything.

The session snapshots the module and its harness when it is planned now,
each chunk restores from the snapshot, a resume refuses when the module
has changed since (the plan's offsets stop describing it), and a tree
that moves under a running sweep prints a note per chunk. The rule
therefore reads: **a figure is void when the source or the harness has
moved SINCE the run — or DURING it.** `stale_figures.py` answers the
first; the session itself now answers the second.

A void figure does not have to be re-swept to be useful.
`python tools/replay_survivors.py src/docxkit/<module>.py` asks its
survivor list again, one mutation at a time through `kill_check`, and
prints which are still alive. On `_compare_diff.py` (2026-08-24) that
was 60 reported survivors and **17 already dead** against a harness
three tests newer — an afternoon of tests aimed at mutants that were
killed twenty minutes after the sweep began. Replay before mining, and
quote the replayed number, not the recorded one.

The practical rule for a session that measures while it works: pick the
module you are NOT editing. Two worktrees make two sweeps safe, and
neither makes an edit to the module under measurement safe.

### A figure is about a module AND the tests the map names for it

`errors.py` read **100 % survival** — ten mutants, ten survivors, every
one of them an `exit_code`. Those numbers are the contract the paper
projects' scripts branch on and `docxkit revision status` quotes in its
own `--help`, and they were not untested at all: the test that pins them
lives in `test_revision.py`, with the protocol they belong to, and
`harness_map` named only `test_api_surface.py` and `test_cli_guards.py`
for the module. Adding the two files that exercise the contract took it
to **0 %** with no test written.

**Line coverage cannot find this.** A class attribute is executed at
import, so the harness covered those lines while being unable to kill a
single mutant on them. Measured across the package that evening, every
module's own harness reaches 94-100 % of its lines — the tell was the
mutation figure itself, which is the one number that asks whether the
tests can DISTINGUISH the code from a different program.

### The seeded sample was never the same draw twice

The section above is right about the population and wrong about
everything else, because the draw itself was not reproducible until
2026-08-19. `sample()` reads its candidates with

    select job_id from mutation_specs

and sqlite answers that from the primary key's COVERING INDEX — so the
list arrives in sorted-UUID order, and the ids are fresh per
`cosmic-ray init`. A seeded `random.sample` then picks the same
POSITIONS in a list that has been shuffled by the id generator.

Measured: two draws of 120 from `_table_layout`'s 2,720, same seed,
minutes apart, **shared five**. So the module reading 14.0, then 9.7,
then 7.7, then 8.5 across one evening was partly a different 460 each
time.

Ordering the candidates by what the mutant IS — module, row, column,
operator, occurrence — makes the draw a function of the module and the
seed, and two fresh sessions now draw the same 120. Every figure
recorded before that is an unbiased sample of its module and NOT half
of a pair; read the survivor lists rather than the difference between
two percentages.

### A sampled figure is pairwise only while the POPULATION holds

`--sample 460` keeps its seed so that two runs of one module draw the
same mutants and the before/after is a paired comparison. That holds
while the mutant population is unchanged — and a round that adds CODE
changes it. `_table_layout` went from 2,607 mutants to 2,630 to 2,637
over one evening's work, so each sample was a different 460 and the
figures moved for reasons that have nothing to do with the tests
written in between.

The number is printed and easy to check: `mutation_survivors` opens with
"460 mutants run (sampled from 2,630)", and the session prints
"sampling 460 of 2,630 mutants (seed …)". **Compare two sampled figures
only when those totals match; otherwise measure the module WHOLE, or
read the survivor list rather than the percentage.** The list is the
part that does not lie either way: a cluster that was there and is gone
is a cluster the round killed, whatever the denominator did.

### `kill_check` used to lie about a case that changed nothing

A case built with `old.replace(...)` whose inner pattern does not match
leaves `new` identical to `old`: the file is rewritten with itself, the
suite passes, and the case reports SURVIVED. That is a confident false
SURVIVOR — it sends someone to write a test that already exists — and it
happened four times in one run, on `len(stack) - 1, -1, -1)`, where the
source has a space after the minus and the pattern was written without
one. The tool refuses such a case now, the way it already refused one
that does not compile.

**And once more, over the code the night had CHANGED.** Three modules
were edited on 2026-08-19 (`_xml`, `package`, `_cite_repair`), which
voids their figures by the rule above, and two had never been measured
at all:

| module | figure | against |
|---|---|---|
| `compare.py` | **11.5 %** (7/61) | never measured — the facade the sweep had always skipped |
| `_compare_diff.py` | **12.5 %** (51/408) | 16.2 % before the round |
| `package.py` | **7.4 %** (25/338) | 25.6 %, and the old figure was stale as well |
| `figures.py` | **5.8 %** (25/428) | 6.6 % |
| `_xml.py` | 5.6 % (25/445) | 4.5 % — the module GREW |
| `_cite_repair.py` | **2.5 %** (5/199) | 9.4 % |

`_xml` reading higher is the ordinary consequence of adding code: the
self-closing `w:t` fix is three lines and its own tests kill every
mutant on them, but the module's denominator moved. A figure is a
property of a tree, not a score.

`compare.py`'s first measurement is the answer to a question nobody had
asked: the facade had never been a target because the sweep reads the
three layers behind it, and four of its seven survivors were the labels
and cuts its report is made of. The other three are the `__main__`
guard.

**What the fixes did to their own survivors** is worth one line.
`package.set_core_property` went from 27 survivors to 12, and every one
of the twelve is now equivalent BY THE FIX: `CORE_ORDER.index(tag) + 1`
decides which sibling the new element goes before, and once the reader
sees the empty form too, the tag's own slot can no longer be occupied
when that line runs. Repairing the defect turned its neighbours into
equivalents.

**The sixth sweep, 2026-08-19, carried on into the modules the fifth
had not reached.** Four shapes came out of it that were not in this
file, and each one is a fixture rule rather than a fact about a module.

### A bound is invisible at a distance of one

`i < len(xs)` and `i != len(xs)` agree on every index a short list is
asked for **except the ones past its end**, and the first of those is
`len(xs)` itself, where both are false. They part company one index
later. So a padding test built from a pair that differs by ONE — the
obvious fixture, and the one already in the file — cannot see the
difference: the loop reaches the length, stops, and never asks the
question that separates them.

`formula_diff` pads four such reads (the equations and their typography,
on both sides) and `Reporter.replaced` two more, and all six survived a
suite with three padding tests in it, each one equation or one paragraph
apart. One fixture three apart, read in both directions, killed all six.

When the fixture is a length, **make the two sides differ by two or
more**. The same applies to `range(max(len(a), len(b)))` walks generally:
one extra element exercises the guard, two exercise the bound.

### A constant whose value belongs to another program

`word.py` had never been measured, and its largest class of survivors —
41 of 110, all in `<module>` — was bare integers: `WD_FORMAT_DOCX = 16`,
`WD_WITHIN_TABLE = 12`, and a nineteen-entry map from `WdRevisionType` to
the names this package prints.

No test can kill those by exercising behaviour, because the behaviour is
Word's. A wrong number does not raise: Word does something else, quietly
and plausibly. `wdExportAllDocument` (0) in the argument that decides
whether From/To are read at all is how every page range became a full
render, and the families are one digit apart in exactly the way that
produces it — `wdFormatXMLDocument` is 12 where `wdFormatDocumentDefault`
is 16, `wdWithInTable` is 12 where `wdPrintView` is 3.

Pin them **by the name of the enum member**, in a table, with a
completeness test holding the table to the module:

```python
WD_ENUM_MEMBERS = [
    ("WD_FORMAT_DOCX", 16, "WdSaveFormat.wdFormatDocumentDefault"),
    ...
]

def test_every_word_constant_is_pinned():
    assert {n for n in vars(word) if n.startswith("WD_")} \
        == {n for n, _, _ in WD_ENUM_MEMBERS}
```

That is not a test restating the source. The number is checked against
the documentation it came from, and the completeness test is what makes
the table a gate rather than a copy: a constant added without a line
here is one nothing can see. Same treatment for the map — plus `sorted(
_REVISION_KINDS) == list(range(1, 20))`, since two entries given the same
number is how a dict literal breaks, and the later one wins silently.

### An early return that saves work is observable only as cost

`_Layout.find` refuses to ask Word about an empty range:

```python
if start >= self.end:
    return None
```

Delete the guard and every answer is unchanged — Find over an empty
range answers no. What changes is that a COM round trip is paid for it,
on the anchor after every ordered run's last hit. The fake counts Find
attempts (`doc.finds`), which is what makes the guard testable at all:

```python
assert doc.finds == 2, "an empty range was searched"
```

When a guard exists for speed rather than for correctness, **the count
is the assertion**. A fake that records how often it was called is worth
building for that reason alone. `==` in place of `>=` stays equivalent
here and is argued in the test's docstring: `start` is either 0 or a
hit's end offset, so it never exceeds `self.end`.

### The script guard is not a gap

`if __name__ == "__main__":` cannot be reached by a test run: the module
is IMPORTED, `__name__` is its dotted name, the guard is false however
the comparison is mutated, and the body never runs. Counted as real,
every module with a `main()` carries two or three permanent survivors —
three of `compare.py`'s seven.

`mutation_survivors.py` classifies them with the PEP-563 annotations now,
out of both numerator and denominator. `compare.py` fell from 11.5 % to
6.9 % with no test written, which is the point: the number a reader
takes at face value has to mean something.


### The sixth sweep, measured and re-measured the same morning

Every module in the package has now been measured at least once. The
three that never had been were the two the sweep could not see a way
into — `compare.py`, the facade the layers sit behind, and `word.py`,
which drives Word — and `console.py`, which is sixty lines.

| module | figure | against |
|---|---|---|
| `word.py` | **14.6 %** (52/356) | 30.6 %, its first measurement, four hours earlier |
| `pages.py` | **8.1 %** (11/136) | 19.1 %, first measured the same morning |
| `compare.py` | **3.4 %** (2/58) | 11.5 %, and both survivors are the argued `part.label == "body"` pair |
| `_compare_read.py` | **7.6 %** (24/317) | 8.5 %, first measured the same morning; fourteen of the twenty-four are argued equivalents, kill_check'd one by one |
| `probe.py` | **7.1 %** (12/168) | 12.5 %, and the fifteen killed were one fixture habit |
| `console.py` | 0.0 % (0/28) | never measured; nothing to do |
| `crossrefs.py` | **6.9 %** (57/822) | 11.2 %, and the run is the WHOLE module rather than a 460 sample — see below |

Two things about the figures from 2026-08-19 onward. The denominators
changed that morning: `mutation_survivors.py` now takes the
`if __name__ == "__main__":` block and the keyword-only `*` of a
signature out of both halves of the rate, alongside the PEP-563
annotations, so a figure from before that date is not comparable
digit-for-digit with one after it. And `crossrefs.py` was measured
WHOLE — 861 mutants rather than the usual `--sample 460` — because the
sample had been read twice already and the second reading turned up ten
survivors the first had never run.

**`--sample 460` is now REFUSED on a module already measured deeper**,
which as of 2026-08-27 is eight of the fifty live sessions: refstyle
1744, placement 1689, edit 1411, hygiene 939, compare_diff 743, styles
604, xml2 538, pages 480. That is deliberate — replacing 1,744 verdicts
with 460 makes the module's record worse while looking like maintenance,
and `crossrefs.py` above is the case it is named for. Re-measure such a
module WHOLE (`--fresh --chunks 0`, no `--sample`), read what is there
with `--report`, or pass `--force` to discard it on purpose. A sweep that
hits the refusal now says REFUSED and takes no measurement, rather than
reprinting the existing session's numbers as this round's.

**Every crossrefs survivor left is a documented equivalent**, argued in
a note at the foot of `tests/test_crossrefs.py` and confirmed one at a
time with `kill_check`. Fifty-seven stood at the measurement; reading
the list afterwards turned up one more that was not equivalent — the
skip for a paragraph with nothing readable in it, where `break` would
stop the backwards walk at the last blank line in the document — so
fifty-six remain and each of them is written down. That is a first for
this package, and it is the state worth aiming at rather than a lower
percentage: a survivor list where the reader is told which entries are
permanent does not have to be re-derived next round. The clusters are
`_caption_bookmarks`' offset arithmetic (13, all of which move the
scope by less than the element they would have to find), the
`@lru_cache` sizes (9), `_run_parts`' `close != -1` (8), and the
`rfind(..., 0, …)` starts and `r_open < 0` guards (11 between
`_wrap_label` and `_link_mention`).

One removal came out of the round rather than a test. `link_more`
scanned the paragraph's MASKED text and then tested each match for a
NUL of its own — a test that cannot fire, since both patterns are built
from an escaped label, `\s+` and the caption's digits, and no character
class in either admits NUL. Five permanent survivors sat on that line.
It was checked three ways before deleting it: structurally, by brute
force over 400k NUL-bearing strings, and by asserting it under the
whole suite.

**The two worst modules, measured whole and worked to the same standard**
(2026-08-19, after the crossrefs round):

| module | now | before |
|---|---|---|
| `word.py` | **7.4 %** (39/527) | 12.5 % measured whole, and 30.6 % at its first measurement that morning |
| `comments.py` | **6.4 %** (42/661) | 10.1 % measured whole, 13.6 % sampled |

Both were reached the same way, and it is worth naming because it is
not "write more tests":

**A fake that cannot tell two states apart hides every mutant between
them.** The ruler's fake put each measured line at x = 0, which makes
`tail - head` and `tail + head` the same number; three characters of
left margin killed the subtraction and every arithmetic spelling around
it. The same fake answered `Information` for a SPANNING range, which
Word does not — it answers for the range's active end — and once the
fake refused one, thirteen mutants on the pair of `max(...)` calls died
together. Word's own objects are the specification here: where the fake
is more forgiving than Word, the tests are measuring nothing.

**A DEFAULT that every test names has no witness.** `session(fast=True)`,
`ruler(size_pt=10.0)`, `compare_documents(whitespace=True, formatting=
True, author="Revision")`, `locate(unique=True)`, `add_at(normalize=
True)` — every one of them was passed explicitly by the test that
exercised it, so the value in the signature was free. A default of
False on any of them is a different program for every caller who does
not name it.

**What Word is ASKED to do is a separate promise from what it is asked
about.** `open_doc`'s tests recorded which file was opened; nothing
recorded `AddToRecentFiles=False` (a batch opens a document per step)
or `SaveChanges=0` — which as 1 is wdSaveChanges, and every close in
the module then writes the file back.

**A fixture of three cannot see what an id base is for.**
`_PARA_ID_BASE >> cid` reads like an ordinary derivation at cid 4 and
collapses to zero past cid 32; thirty-five comments in one call — an
ordinary review round — is what makes it a collision. `base - cid` and
`base | cid` stay equivalent and are argued as such: the bases end in
twenty-four zero bits, and every property the module needs (unique,
eight hex digits, the two families disjoint) survives them.

**A module measured the day after it landed** (`placement.py`, 2026-08-19):
**20.2 % -> 9.0 %** (116/1283), lines 90 % -> 97 %, floored at 97. It arrived
as the least-tested thing in the package by a factor of two, which is what a
day-old module looks like next to one that has been through six sweeps.

Two defects came out of the round, and both are the shape this file keeps
recording — **a report that reads as success**:

* the "still splits" line was `if pl.split and not pl.own_page`, and
  `own_page` is applied to every table that splits. The branch could not fire
  for the case it names, so a table nothing can fix was reported as fixed;
* `format()` printed the problems only under a render, and half of them are
  decided in the XML — a table nothing mentions, a block carrying a section
  break, a move that would cross a boundary. Without a renderer the report
  showed none of them.

**The fixture that killed the most was one assertion about what is NOT
written.** Every loop in the module asks `el.tag == W + "p"` before writing a
paragraph property, and the mutants of that test — `>=` is true for `w:tbl`,
`is not` is true for everything, since `W + "p"` builds a fresh string each
time — put a `w:pPr` inside a table. That is well-formed XML and unreadable
content, and nothing in the report counts elements, so no existing assertion
could see it. One walk over the output covers every writer at once.

**What is left is mostly that same comparison at sites where it does not
matter.** A body child is only ever `w:p`, `w:tbl`, `w:bookmarkStart` or
`w:bookmarkEnd`; the last three carry no text, and they sort either side of
`w:p` in a known way — so at a site that merely SKIPS a non-paragraph, every
ordering and identity spelling gives the same answer. The sites where it does
matter are the ones that write, and those are pinned.


**The module the deliverable comes out of** (`tracked.py`, 2026-08-19):
**10.4 % -> 4.9 %** (29/589), lines 96 % -> 100 %. Measured fresh: the 8.6 %
in the sixth-sweep table above was two rounds and three features old, which
is the ordinary state of a number in this file.

What the round was mostly about was the COM boundary — what `build` says and
does when Word refuses. A revision Word will not comment, an equation it will
not measure, a comment it will not add, a scaffold that cannot be seeded:
each is one `except Exception` away from a build that reports a clean pass,
and each is now a fixture that refuses in exactly that place. The `_Refuses`
helper is three lines and killed more than any assertion did.

Two fixtures were lying, both about arithmetic:

* the Timer's ticks were 100, 101, 103 — and `a % b` equals `a - b` whenever
  `b <= a < 2b`, so subtraction and modulo agreed on every phase the report
  printed. Ticks of 1.0, 3.0 and 8.0 separate them;
* the untracked walk's fixture had ONE insertion, which makes `i1` and `j1`
  the same index — the baseline index and the batch index only part company
  after the first insertion, which is the whole reason the finding carries
  the batch's. Two insertions with an unchanged paragraph between them is
  the smallest fixture that can tell.

**The paragraph number nothing had read.** `Unaccepted.__str__` carried
thirteen live mutants on one `+ 1`, because every test asked whether the
list was empty and none had ever read a finding out loud. Pinned at ¶4:
`index | 1` and `index ^ 1` both equal `index + 1` at an even index, so the
obvious fixture proves the least.

**And the counts above 256.** `verify`'s `comments_match` and the build's
body-vs-package note compare two ints computed in different places. CPython
hands out one object per int up to 256, so `is` in place of `==` is invisible
on every fixture this suite had ever built and wrong on every batch above the
cache — LI7 shipped 315 revisions. Both now run at 300, which is the only
size at which the two spellings can disagree.

Four survivors stay, argued at the foot of `tests/test_tracked_build.py`:
difflib's interned tags, a `>=` against a limit the walk meets exactly, and
`!=` -> `<` on a body count that is a subset of the package's by
construction.

**And the question that came out of the round, worth more than the figure:
does this walk READ every part it writes?** `_simulate` accepts and rejects
all three text-bearing parts and the comparison opened two of them, so an
accept-all defect was a finding in a footnote and invisible in an endnote.
Asked of the rest of the package the same evening, the same answer came back
from `refstyle` (a citation in an endnote neither checked nor counted),
`export` (the note dropped from the markdown entirely), `_cite_audit` (the
same bookmark audits as 1 in a footnote and 0 in an endnote) and
`ingest.build_overrides` (a note the author retyped produces no override at
all). `wordcount`, `probe` and `compare` were already right. The first three
are fixed; the last two are open in BACKLOG, because an audit widened without
its builder reports work nothing can do.

A short parts list is not a bug that fails — it is a report that reads as
success over the half of the document it happened to look at.


**Three modules measured FRESH the same evening**, because the table
above is a photograph of the day each row was taken and most of those
days are gone:

| module | recorded | measured 2026-08-19 | what the round wrote |
|---|---|---|---|
| `ingest.py` | 35.1 % (raw) | **5.9 %** (11/188) -> 2 left | the messages, the id fallback, a block of 257 |
| `equations.py` | 24.9 % -> 10.6 % | 8.4 % -> **5.7 %** (24/420) | the OMML branches Word's editor reaches |
| `_table_layout.py` | — | 14.0 % -> **7.7 %** (33/430) | the width tables, three rules off by one |
| `cli.py` | 28.3 % (raw, 2026-08-16) | **6.9 %** (31/449) | what the commands PRINT |
| `footnotes.py` | 15.4 % (raw, first run) | **4.5 %** (18/402) | measured only — no round needed |
| `revisions.py` | 8.5 % (2026-08-17) | 9.2 % -> **6.7 %** (28/417) | what a paragraph MERGE carries |
| `pages.py` | 19.1 % -> 8.1 % | **6.7 %** (12/180) | the render's own resolution, the two bands |
| `errors.py` | 100 % | **0.0 %** (0/10) | the harness, not the tests — see below |
| `refstyle.py` | 18.1 % | **5.8 %** (23/395) | an ISBN keeps its hyphens |
| `edit.py` | 11.1 % | **8.5 %** (36/423) | what a refusal quotes, and where the italic goes |

`_table_layout`'s second figure was read as 13.4 % until the survivor
tool was pointed at the source the RUN was planned against rather than
the live file — the classification of annotation spans moves with the
text, so a module being worked on reads several points high. See
"the survivor list reads the source the run was planned against".

`equations` went from 35 real survivors to 24 over the same population
of 1,311 — **but not, it turned out, over the same 460**. See "the
seeded sample was never the same draw twice" below: until the evening of
2026-08-19 every `--sample` figure was an independent draw, so a pair
like this one is two samples of the same module rather than a paired
measurement. Twelve of what is left in `equations` are documented
equivalents (the unreachable piece bound, `_local`'s subscript, `is` on
a one-character attribute, the delimiter count) and three need Word's
XSL.

`ingest`'s 35.1 % is the clearest case of a stale number misleading: it
is a RAW figure from before the annotation mutants came out of the
denominator, and the module measures 5.9 % with no work done to it. Two
survivors are left in it now, both argued.

**A test whose fixture has one of something cannot see an index.**
`ingest`'s equal-length branch pairs paragraphs POSITIONALLY, and a
257-paragraph fixture is what makes `==` differ from `is` — but the
mutant survived it anyway, because with every paragraph merely reworded
the similarity fallback pairs them the same way. It dies only when the
last rewritten paragraph resembles the FIRST original one, which is what
tells positional pairing from similarity pairing. The fixture has to
separate the branches, not just reach them.

**The width tables were unguarded in CI, and nothing said so.**
`_table_layout` carries the AFM glyph widths, and their oracle —
`tests/test_width_model.py`, which drives a real Word — is marked
`word`, so a plain `pytest` deselects the entire file. Seventeen live
mutants sat in the module scope, one per width group, each of them a
column measured against the wrong font. The offline half is now beside
the existing K/P/"!" pins: one character per group, every printable
ASCII present (the module's own comment calls an OMITTED character the
worse failure), no character in two groups, and the alias scales by
name. **A `-m` mark on the only test that checks a table is an
exemption, and exemptions need a second line of defence.**

**And the defect that came out of that round**: `fit_columns` wrote a
column's width into a NESTED table's cell. The comment above the cell
loop says this exact lesson about the table's own properties — a
`re.sub` over the whole body writes into a nested table whenever the
outer one lacks the property being set — and the loop below it repeated
it one element in. A nested cell's `w:w="300"` came back as 1178, inside
a 300 dxa grid, and nothing failed. `_own_tcpr`/`_set_tc_w` are the
cell-level twins of `_own_tblpr`/`_set_tbl_pr`.

**`is` is not one rule.** Three sites this evening, three different
answers: on difflib's opcode tags it is EQUIVALENT (both sides are
interned literals); on a one-character XML attribute value it is
equivalent too (CPython hands out one object per latin-1 character —
measured, not assumed); on two counts computed in different places it is
a REAL defect above 256, which is why `verify`'s comment check and the
build's body-vs-package note now run at 300. Argue the site, not the
operator.


**`equations.py`, four small rounds in one evening** (8.4 % measured
fresh). What they were about, because the pattern repeats across the
module: **the branch an author reaches through Word's equation editor
rather than by typing LaTeX.** A hidden n-ary limit, a hidden radical
degree, a bar that hangs under, a grouping character above the brace
codepoints, an accent that is not a hat — each is one guard, each was
written by nobody's test, and each turns a formula into a different
formula rather than into an error.

Three things the round is worth remembering for:

* **`standalone` had no test at all.** It is half of the documented
  `harvest` -> `clone` pair — a slice of `document.xml` carries no
  namespace declarations of its own, and this is what gives it some —
  so every mutant in it lived, including one that reads `root[1]` of a
  one-element fragment. A public function with no test file section of
  its own is worth grepping for before mining a survivor list.
* **The fixture has to reach the branch AND separate it.** Every
  grouping-character test used an arrow at U+2192, below both brace
  characters, where `>=` and `==` agree; the six blackboard commands
  are the only symbols whose LaTeX ends in `}`, so every other symbol
  makes `sym[-1]`, `sym[1]` and `sym[-2]` agree; and a trailing space at
  the END of the output is stripped, so the fixture has to put a
  variable after the symbol to see one.
* **An unreachable guard is worth measuring rather than arguing.**
  `prose_math`'s `if k + 1 < len(pieces)` carries seven mutants and
  cannot fire — one sentinel is written per equation, inside a `w:t`, so
  `split` returns exactly one more piece than there are equations. The
  case where that might come apart is a REDLINE whose equation sits in a
  `w:del`; measured, the sentinel survives it (Word writes `w:delText`
  for deleted prose, not `w:t`) and the pieces still line up.


**The 20th's rounds, and the one shape they share.** `revisions`,
`pages`, `refstyle` and `edit` all came down on the same kind of
survivor: a POSITION or a QUOTE, never a decision. Where the italic tag
goes inside a run's properties; how many characters of an anchor a
refusal prints; which band of the sheet a page number has to sit in;
where the children of an unwrapped `w:ins` land. None of them changes
what the code decides — each changes what a person is handed, or what
Word is handed, and the tests that covered those functions all asked
whether the decision was right.

Three fixtures had to be sharpened rather than written, and each one is
the same lesson at a different size:

* `_unwrap` steps a cursor by one per child, and the wrapper shifts
  right as each is inserted — so a step of TWO lands exactly where the
  wrapper now stands and the second child still ends up right. Three
  children is the smallest fixture that overshoots.
* `<w:i/>` written past the end of a run's properties appends to the
  same place the correct offset writes to. A property that sorts AFTER
  it — `w:sz` — is what makes the difference visible.
* the walk that finds a field-form label's end asks about `runs[i + 1]`,
  and with a `fldChar end` after the label there is always a run to ask
  about. The bound is only reachable from a STYLED run that ends the
  paragraph, which is what Word leaves behind when an author deletes a
  link's address.

**And a round that should not have happened.** `body.py`'s survivor list
named eleven mutants on the line that sizes a table's grid; a previous
round had already killed them, and the four tests written from that list
duplicated four already in the file. `stale_figures` had been saying
"stale: tests/test_body.py" the whole time. `mutation_survivors` prints
that banner itself now — the tool that proposes the work is where the
warning belongs.


`word.py` is the one worth reading twice. Its first figure was the
package's worst by a factor of two, and 41 of its 110 survivors were
constants — numbers Word reads, which no test can kill by exercising
behaviour. Pinning them by the name of the enum member took the module
from 30.6 % to 14.6 % in two commits, and the tests that did it are the
kind this file spent five sweeps arguing against: they assert a
literal. The difference is where the literal comes from. `16` in a test
that reads it off the line above is a copy; `16` named as
`WdSaveFormat.wdFormatDocumentDefault`, with a completeness test holding
the table to the module, is a check against the documentation the number
came from — and the documentation is the only oracle there is.

`sheets` is the other lesson, and it is about a note in a test file
rather than about code. Fifteen survivors sat in a four-line function
under a comment saying killing them needed a machine with Word. That
was wrong for two days: `sheets` calls `export_pdf` and `read_pdf`, and
substituting BOTH runs every line of it with Word never starting. A
survivor list is a claim about the tests; a note explaining why a
survivor is unreachable is a claim about the FUTURE, and it ages badly.
Re-derive one before believing it.

---

*The rest of this section is the fourth sweep's, kept in its own order.*

The largest cluster now is 16 in `<module>` — the glyph-width table,
whose numbers are the one thing in this package that only
`pytest -m word` can really check, since the answer lives in Word.

**21.0 % was then void in turn**, for the ordinary reason: reading the
next two clusters down found an S2 and an S1 — the table width written
ahead of the `tblStyle` CT_TblPr wants first, which Word drops on the
next save, and `keepNext` spliced into the middle of a caption's style
name — and fixing them changed the source. A survivor series ends where
the module does.

The fresh draw after those fixes and the tests that came with them
reads **12.2 % (54 of 442)**. Three figures for one module in one day,
and only the last one describes the module as it stands: the first was
measured without three of its test files, the second against code that
had two defects in it.

All five re-measurements landed the same day, and the shape is the
same in each: the survivors were the values a report or a rewrite
produces, and the tests that killed them assert what the code SAYS
rather than that it ran. `comments.py` is the odd one out only because
its first figure was over 178 mutants and its second over 460 — the
number went up because the run got longer, not because the module got
worse.

**`tracked.py` 36.3 % -> 28.5 % -> 9.4 %** in one day, three rounds,
and what each round found is the shape to expect:

1. **What `untracked` SAYS**, not whether the list is empty. It was
   reached only through `build`, which asks whether it is empty, so
   every value in it was free. 36.3 -> 28.5.
2. **The same report at an offset that is not zero.** Seventeen
   survivors sat on `i1 + k` and `j1 + k` mutated to `|`, `^` and `>>`,
   and every fixture started its changed block at paragraph 0 or 1 —
   where all four operators agree. See the note below; this is the most
   reusable thing the day produced.
3. **What the Word path TELLS the paper**, and the build report's own
   numbers: the sentinel offsets a classifier reads, the equation
   boundary an accept is decided on, every counter's initial 0, the cap
   on the two lists, and each phase's duration. 28.5 -> 9.4.

**An arithmetic mutant survives at zero.** `i1 + k` with `i1` at 0 is
`i1 | k`, `i1 ^ k` and `i1 >> k` all at once — four operators, one
answer, and a fixture whose interesting block starts at the top of the
document cannot tell them apart however carefully it asserts. The same
goes for `max(a - b, c - d)` where one term is the whole answer: only a
fixture where the two sides differ in LENGTH says which term won. When
a cluster of `+`/`-` survivors will not die, look at what the operands
are in the fixture before looking at the assertion — and note that the
converse holds too, `start | sep.end()` in `_compare_read` being
genuinely equivalent because an OR is never larger than the sum and the
region it moves into holds nothing the mask can find.

The ORDER is the finding. The modules that rewrite a manuscript sit at
4–9 %; the ones that REPORT on it — probe, pages, console, testing — sit
at 23–37 %. Defensible as far as consequence goes, and not as far as
trust: `probe` exists to be believed BEFORE a batch picks its approach,
and its own argument is that a two-table swap took forty minutes because
nobody knew which form the links took. Every one of those has since been
pinned by value.

Writing those tests found more than the percentages did, every round: a
function computing a value no caller read (58 mutants were living in
`label_extent`'s dead leftward walk); an S1 where two reference entries
sharing a surname and year shared one bookmark, so every link to it
landed on a coin flip; and an S1 where a sentence in the back matter
parses as a reference entry, which a real citation then links to while
the report says it matched everything. **That is the argument for the
technique** — three defects a green suite of 2,500 tests was already
passing, each found by asking what a test would NOTICE.

The sweep above added four more of the same kind, and every one of them
sat under a cluster of survivors rather than being visible in the
percentage:

* `build_overrides` placed a newly INSERTED paragraph after the last
  paragraph that happened to CHANGE — sections away from where the
  author put it — and refused the edit outright when nothing else had
  changed. 33 of `ingest.py`'s 65 survivors were on that one line;
* `find`, `set_alt_text` and `_repoint_one_drawing` each carried their
  own copy of the figure drawing WINDOW and none of them stopped at the
  next caption, so a figure whose own image was missing adopted the
  following figure's — and the accessibility check then reported both
  as described;
* `lint`'s two newest checks (the ones added for "Word says the document
  is unreadable") had no test at all: emptying their loops changed
  nothing any test could see;
* `prose_numbers` guarded a conversion that cannot raise, and three
  mutants were living inside the dead branch.

The pattern behind all four: a check asserted on the case it FIRES on
and never on the case it must stay quiet for, and a value returned but
never read back by anything.

The second wave adds a third shape, and it is the one to look for first
in anything that REFUSES: **a guard asserted from one side only.**
`rep` refused too FEW anchors and would have accepted too many;
`delete_bookmark` refused two ends and not none; `remove_outer_field`
refused none and not two; `integrity` reported a bookmark with a missing
end and not one with a spare, and a field missing its end and not one
missing its begin. Every one of those is a gate that fires on the
example somebody wrote it for and stays silent on the other half of its
own contract.

**A suite that is too narrow INVENTS survivors, and that costs more than
one that is too broad.** `comments.py` came back as the worst module in
this table — 31 survivors in `remove`, seven loops that could each be
emptied — and `remove` is tested exhaustively in `test_parts_gaps.py`,
which was not in the run. `_table_layout`'s `drop_blank_rows` had 77 for
the same reason (`test_tables_blank_rows.py`). The three "real survivor"
numbers above are therefore upper bounds, not findings.

It happened a third time on 2026-08-17, with the map that exists to
prevent it: `_table_core` came back at 44.9 % with 216 survivors in
`update`, because `tests/test_tables_update.py` — the file that tests
that function — was not in its entry. Six mutants of `update` picked by
hand all died against the corrected harness. `tests/test_harness_map.py`
now answers the claim a file's NAME makes: `test_<module>*.py` is in the
entry or in `EXCLUDED` with a reason.

The cure is not a wider run: it is to let the sweep PROPOSE and the full
suite DISPOSE. Apply each candidate by hand and run everything; green
means a real gap, red names the test that already covers it. Over 48
candidates that filtered 17 artifacts out of 31 real gaps — and it is
the same "apply the mutation and watch it go red" step already required
after writing a test, run in the other direction.

`tools/kill_check.py` is that step:

```python
from tools.kill_check import check
check("src/docxkit/edit.py", ["tests/test_find_edit.py"], [
    ("rep  count != n -> < n", "    if count != n:",
     "    if count < n:", True),                    # expect a KILL
    ("hits[0] -> hits[-1]  [claimed equivalent]",
     "    at, end = hits[0]", "    at, end = hits[-1]", False),
])
```

It mutates in its OWN worktree (the live tree is what a measuring run
copies from), refuses an anchor that is not unique, and COMPILES the
mutant before running it — a mutation that does not parse makes pytest
exit non-zero on the import, which reads exactly like a test failure and
reports a confident false kill. One did, and hid a piece of dead code
for an afternoon. Cases marked `False` are the equivalences you have
argued for, checked rather than assumed.

Expect a quarter of the tests written this way not to kill what they
were aimed at. Four of the last batch did not, and each miss was worth
more than the test: the `w:hAnsi` fallback needs a run that states NO
font (one naming its own never consults the fallback) and cannot be
shown by comparing two fallback tables, because the misreading sends
BOTH to Times; `_round_to`'s `/` and its largest-remainder ordering both
need weights that do NOT divide exactly, or every fraction is zero and
neither line is doing anything visible.

**`cli.py` is the one to read twice: 28.3%, the worst of the eight, on
the module at 100% line coverage.** That is the whole argument for
running this tool, made on the module that looked safest. Eleven
`return 0` / `return 1 if …` sites across nine commands could be flipped
with nothing going red — the smoke test asserted `isinstance(code, int)`
and the rest asserted output. The exit code is what a script reads;
`docxkit citations`, `refstyle`, `crossrefs --audit` and `crossrefs
--write` are all gates somebody pipes into `&&`.

Two traps in the confirming, both worth avoiding:

* **address the LINE, not the context.** Three commands print the same
  `(dry run - pass --write to save)`, so a `replace(old, new, 1)`
  patched a different function than its label claimed and reported a
  survivor for a branch it never touched. `tools/mutation_survivors.py`
  gives line numbers; use them;
* a mutant that runs and changes nothing visible is worth tracing before
  believing. `return 99` in a live branch still exiting 0 was the tell
  that the patch had landed elsewhere.

`revision.py` at 5.6% is the best of the seven and `tracked.py` at 20.3%
the worst, which is the right way round: the protocol is what an
author's work depends on, and most of what survives in `tracked` is COM
the fake absorbs.

**One survivor shape turned up four times and is worth knowing by
name: a guard written as `!=` or `==`, mutated to an ORDERING.** Any
single fixture puts its two values on one side of each other, so `<` or
`>=` passes for whichever half it landed in and the test still goes
green. It hit the stale-batch guard that stands between a batch and an
author's unsaved work, both post-conditions in `promote`, all three
arms of gate 5, and gate 6. The fix is not a cleverer fixture — it is
several, chosen so the values fall on both sides, asserting the
property the guard actually has: ANY difference is refused, not most.

`equations.py` is where the ratio is worst, and it is not a scandal:
roughly half its real survivors are in the `to_latex` walker's methods
for constructs no manuscript here uses — `e_sPre`, `e_groupChr`,
`e_borderBox`, `e_phant`. The walker's guarantee is that an unknown tag
is MARKED, never dropped, and that is tested; how prettily it renders a
pre-subscript is not the same promise. Judge a survivor by what its line
protects.

A second equivalent class, on top of the annotations, accounts for 43 of
`revisions.py`'s remaining 73: an ordering operator on a CLOSED string
set (`mode <= FINAL`, where `mode` is only ever `final` or `original`),
`==` read as `is` on an interned constant or on an lxml element, `[-1]`
on a `rsplit(sep, 1)` that always yields two, and removing an
`@lru_cache` that exists for speed. Thirty are genuinely unexamined —
that is where the frontier is, not at zero.

The crossrefs/comments/`_table_layout` round added five shapes to that
class, all of them worth recognising on sight:

* a guard whose two branches MEET at the boundary — `sum_f <= avail`
  read as `<` sends an exact fit down the shaving branch, which
  apportions zero and hands back the same widths;
* a lookup that returns the same thing either way: `tables.get(None)`
  is `None`, so `if tables and idx is not None` decides nothing;
* a check the guard above it has already made — `not hits` raises
  before `len(hits) > 1` can ever see zero;
* `==` read as `is` where both sides came from ONE object (a cid taken
  twice out of the same records list), which is a stronger claim than
  interning and holds by construction;
* an ordering imposed on offsets that do not move: `sorted(...,
  reverse=True)` where the spans are VISIBLE-text offsets and the edit
  changes no visible text. Bottom-up is load-bearing where a pass
  splices XML, and only there.

**The AFM width tables in `_table_layout` are a category of their own:
98 survivors, none of them a gap.** `test_width_model.py` already says
so in a note addressed to whoever runs this next — a ±1 entry falls
inside the 2.5% tolerance that gate declares. Re-measured 2026-08-11
rather than trusted: the Times apostrophe at 180 per 1000 em, mutated to
181, passes the everyday suite AND `pytest -m word` against a real Word.
The gate's promise is "no character is out by more than 2.5%", not
"every entry is exact".

Two findings worth keeping:

* the best one was already written down in prose. `set_font`'s skip for
  a `w:r` inside an `m:oMath` says in its own docstring that it has never
  fired on a real document; eighteen mutants lived on that line across
  two functions, so no test fired it either. It is the only thing between
  a formula and the body font the day the run pattern is widened;
* **a survivor can mean the test asserts nothing.**
  `test_move_range_markers_are_removed` read
  `"moveFromRange" not in "".join(text(xml, view))` — and `text()` returns
  VISIBLE text, which a range marker has none of, so it passed either
  way. Deleting the loop that removes the markers turned nothing red.
  That is the third assertion in this repo found to be satisfied by
  something other than what it names; the `"italic" in out` one below is
  another. When a survivor lands on code you believe is tested, read the
  test before writing a new one.

Two traps, both hit on 2026-08-07:

* **Killing a run strands a mutation in your source.** cosmic-ray edits
  the file in place and restores it after each mutant; interrupt it
  mid-mutant and the mutation stays on disk, where it reads as your own
  work. `git diff -- src/` before believing anything after an aborted run.
* **Do not touch the source or the tests while a run is executing.** Every
  mutant re-reads both, so an edit halfway through means the early mutants
  and the late ones were judged against different suites, and the survivor
  count is a number with no meaning. Restart the run instead.

**A survivor is a question, not a work item.** They sort into three kinds
and only the first is a missing test:

* a real gap — write the test, then *apply the mutation by hand and watch
  it go red*. A survivor that a new test does not actually kill is the
  normal outcome of guessing;
* an equivalent mutant — `n > 1` becomes `n != 1` where `n` is a count
  that is never below 1. Record it and move on; a test pinning it would
  pin an accident;
* cosmetic — the width of a rule. Same treatment.

Say which in the commit message. Two runs here have ended with the
survivor telling us something other than "write a test": an unreachable
second difflib pass, and a similarity threshold whose only effect was on
ties. Both were better findings than a test would have been.

The survivors also audit the tests themselves. That pass turned up an
assertion of `"italic" in out` that was satisfied by the section HEADING
— "FORMAT (italic/bold/super/sub/strike…)" — and so had never been
about the entry it claimed to check.

### The seventh sweep: ten modules, measured and re-measured

Every figure below was measured, worked, and measured again the same
day, with the survivors that stayed argued at the foot of the matching
test file and each argument checked by `kill_check`.

| module | now | before | what the round was about |
|---|---|---|---|
| `_compare_render.py` | **1.4 %** (3/207) | first measurement | three argued equivalents and nothing else |
| `figures.py` | **1.9 %** (8/422) | 3.8 % | the SECOND drawing: in the caption's own paragraph, beside it, sharing its relationship |
| `_table_core.py` | **2.7 %** (11/415) | 8.7 % | a stub that ignored its argument, and the arithmetic of a block's top-left corner |
| `lint.py` | **2.7 %** (12/449) | 3.6 % | an XML comment in a `w:pPr`, and a change record already in its place |
| `authors.py` | **3.7 %** (4/107) | 7.5 % | the people registry is WRITTEN, not only counted |
| `styles.py` | **3.5 %** (7/198) | 5.1 % | `Cascade.style_of`, asked directly — including with no properties at all |
| `_cite_build.py` | **2.9 %** (11/380) | 8.9 % | the report a round acts on: what it quotes, and what it skips past |
| `_compare_diff.py` | **6.0 %** (24/399) | 8.8 % | the layers a person reads — comment cuts, label moves, the move threshold |
| `_compare_read.py` | **6.0 %** (19/317) | 7.3 % | a property switched OFF, a superscript named, two heads 60 % alike |
| `_cite_audit.py` | **3.7 %** (15/409) | 11.2 %, its first measurement | the audit's own sentences: which store a finding is in, which order they come in, and five walks that ended early |
| `edit.py` | **2.8 %** (12/423) | 8.5 %, then 5.7 % | what an edit REFUSES, and where it lands when it does not |
| `renumber.py` | **3.9 %** (18/457) | 15.1 % two waves ago, then 5.3 % | a shift counts what it CHANGED, and the 257th note |
| `_cite_grammar.py` | **5.1 %** (22/428) | first measurement | four words is where a sentence starts being one |
| `find.py` | **4.0 %** (8/201) | first measurement | two silent defaults, and a table at offset zero |
| `body.py` | **2.4 %** (6/246) | first measurement | a span of zero would have written `w:gridSpan w:val="0"` |
| `_cite_repair.py` | **2.0 %** (4/198) | first measurement | four survivors, all argued — the tightest in the package |
| `export.py` | **2.0 %** (4/197) | 9.3 %, two rounds old | a short row padded, and the outer table |
| `ingest.py` | **1.6 %** (3/191) | first measurement | three survivors, all argued |
| `package.py` | **4.5 %** (15/335) | 6.6 %, its first measurement | where a NEW core property lands — eight mutants on one slice |
| `hygiene.py` | 4.9 % (22/449) | first measurement | what the house-style pass refuses to touch |
| `probe.py` | **5.4 %** (9/168) | 7.1 % | nine survivors, all argued |
| `revision.py` | **6.2 %** (21/340) | 8.8 %, its first measurement | the report a hand-back gets — **partial round**, eleven of thirty |
| `citations.py` | 5.6 % (6/107) | — | six argued: the finding-kind comparisons and the width of a rule |
| `pages.py` | **3.3 %** (6/180) | 6.1 % | six argued: an index under a length check, and four clip-rectangle origins |
| `refstyle.py` | **3.8 %** (15/395) | 4.8 % | the reference audit's own two-sided rules |
| `_xml.py` | **4.2 %** (19/448) | 4.5 %, then 4.7 % | a property present TWICE — and sixteen of the twenty argued, which is why the figure moved so little |
| `_table_layout.py` | **4.1 %** (18/439) | 7.8 %, then 4.8 % | a guard written for a document Word does emit, and a report |
| `word.py` | **2.9 %** (10/349) | 7.4 %, then 3.7 % | a limit above 256, and a temp directory Word still holds — CLOSED, the ten left are argued |
| `crossrefs.py` | 7.5 % (33/438) | 6.7 %, then 7.3 % | TWO wrong arguments in its own note — see below. The figure rose because the fixes added code, and because nearly every survivor left is argued |
| `comments.py` | **5.6 %** (21/378) | 7.4 % | two distances, pinned at the character |
| `revisions.py` | **5.5 %** (23/417) | 6.7 % | the paragraph nobody deleted, and difflib's autojunk |
| `revision.py` | **2.4 %** (8/340) | 8.8 %, 6.2 %, 4.7 % | the PARTIAL round closed: a limit, a walk, and a hash that sorts low |
| `_cite_grammar.py` | **4.2 %** (18/428) | 5.1 % | a line that merely STARTS like a stop word |
| `hygiene.py` | **3.1 %** (14/449) | 4.9 %, then 3.6 % | a relationship with no target, and a paragraph nothing smartens — CLOSED |
| `equations.py` | **3.4 %** (14/416) | 5.8 %, then 4.3 % | its first worked round — a clause that could not fire |
| `cli.py` | **4.2 %** (19/455) | 6.9 %, 7.0 %, 6.2 %, 4.6 % | the loops whose bodies nothing checked, the widths a report is read at, and two flags that did the opposite |
| `compare.py` | 3.4 % (2/58) | — | two argued, CLOSED |
| `guard.py` | 4.1 % (2/49) | — | two argued (a JSON indent), CLOSED |
| `_table_core.py` | **1.7 %** (7/415) | 2.7 %, and a PARTIAL 1.0 % | measured WHOLE at last; six argued, CLOSED |
| `edit.py` | 4.9 % (21/425) | 2.8 % | it went UP, and the rise IS the new code this day added |
| `placement.py` | **5.4 %** (23/426) | 9.6 %, 6.8 %, 6.1 % (four measurements in one day) | the worst left: a body of three hundred children, and the measurement after the fix |

`_cite_build` went back up to 4.3 % afterwards, and deliberately: the
endnote work landed new code in it (see below), and new code arrives
with survivors like everything else. Every one of the sixteen is argued.

**Closed** — every survivor argued and kill_check'd — are
`_compare_render`, `figures`, `authors`, `styles`, `_cite_audit`,
`citations`, `_cite_repair`, `ingest`, `probe`, `_cite_build`,
`_compare_diff`, `_compare_read`, `lint`, `_table_core` and `edit`. The rest of
the table's rows are rounds, not closures: `revision` is explicitly
partial, and `package`, `renumber`, `edit`, `find`, `_cite_grammar`,
`body` and `export` had their survivor lists worked but not exhausted.

**Do not read this table for the current state — ask the tool.**

    python tools/stale_figures.py --figures

prints every module's figure beside its fresh/stale verdict, read out of
the session files through the same arithmetic the survivor lists use. A
table in a document is a photograph; that command is the thing itself,
and it marks a run that stopped early (whose figure flatters) and a
facade with nothing to mutate.

**Six of these modules are CLOSED** — every survivor left is written
down at the foot of its test file with the argument for it, and
`kill_check` has confirmed each claim one at a time: `_compare_render`,
`figures`, `authors`, `styles`, `_cite_audit`, `citations`. That is the
state worth aiming at rather than a lower percentage.

### The seventh sweep: what the instruments were still getting wrong

Four days of rounds against one instrument turned up four defects in the
instrument itself, and each one had been changing what the work looked
like rather than what the numbers said.

**A survivor list that names the OPERATOR does not name the mutant.**
`ReplaceComparisonOperator_NotEq_Gt` on

    if pa.wtext_f != pb.wtext_f or len(pa.fmt) != len(pb.fmt):

is one of two mutants, and the round guessed the wrong one: the test
written from it aimed at the first `!=`, which a July round had already
pinned, and `kill_check` reported a KILL because the mutation broke that
earlier test. A duplicate test, and the real survivor still alive.
cosmic-ray stores the diff of every mutant it ran, so the list prints
the line the mutation MADE now — `-> if ... or len(pa.fmt) >
len(pb.fmt):` — and the guess is gone.

**A mutant on a line coverage is told to skip is not a missing test.**
`# pragma: no cover` is the author saying a branch is defensive, and the
coverage floor is enforced with those lines taken out — so no test
executes them and no test can kill a mutant on one. `_cite_build`
carried eight on a single defensive `if` and the `continue` under it, a
fifth of the module's figure. They are counted apart now, from
coverage's own patterns plus the project's `exclude_also`, with a pragma
on a compound statement taking the whole block.

**A private checkout holds the files of the day it was made.**
`mutation_session` copies the module and its harness into the worktree;
it did not copy `tests/conftest.py`, which no harness names and every
test file imports, so the fixtures in the checkout were the ones from
the commit it was created at. `kill_check` copied `src/` and `tests/`
and not `tools/`, so a case aimed at a sweep script — they have
harnesses of their own now — anchored against a version committed weeks
ago and was refused with "anchor occurs 0 times" for a line that is in
the file. Neither produced a wrong number; both fail in a way that
points at the wrong thing.

**A measuring tool that answers differently depending on the shell that
started it is not measuring.** A four-module fan-out from a plain
`nohup` produced two tracebacks and nothing else, where the same command
from a shell that exported PYTHONIOENCODING had run all night. The
session's stdout is a pipe, so Python gives it the locale's cp1252
unless told otherwise; its em dash arrives here as U+FFFD, ` run — `
matches nothing, and a sweep that graded every one of its mutants
reports "no chunk ever graded" — then dies printing that U+FFFD to the
same cp1252 console. The sessions are told to write UTF-8 now, and the
sweep switches its own stdout before it prints anything.

And one that was only a report: under `--in` the streams interleave, so
a heading from one lands between another's heading and its numbers. The
first fan-out printed `_cite_build`'s 8.9 % under `_table_core`'s
heading, and the only thing that said which was which was the function
names in the tally beneath it. Every line under `--in` names its own
module now.

### Two package defects came out of the same week's reading

Neither was found by a mutant. Both were found by the question the sixth
sweep produced — **does this walk READ every part it writes?** — asked
of the one apparatus that had been left out:

* **the citation apparatus read `word/footnotes.xml` and nothing else.**
  A work cited only in an endnote got its entry bookmark and no link,
  and the report said nothing at all — not "skipped", not "unmatched".
  The audit reported that paper's bookmarks as 1 -> 0 and its links as
  1 -> 0, which reads as a document with nothing in it to fix, and
  `repair_plan` — which decides DEBRIS from "not among the document's
  citations" — proposed deleting the markers of every work cited there.
  A one-liner a person will run. Writer, audit and plan moved together,
  because an audit widened alone reports work its builder cannot do.
* **an endnote id was spliced into an override unremapped.** Word
  renumbers note ids on save; `build_overrides` has rewritten FOOTNOTE
  ids by definition text since the beginning — splicing one raw
  "silently repoints footnotes", as its docstring says — and did
  nothing of the kind for endnotes. The deliverable then cites the
  wrong work while the author's copy cites the right one, and
  `--expect-clean` cannot see it: it compares reference marks, not what
  they resolve to.

The second one also demonstrates the gate that catches a duplicated
pattern: the note-definition regex existed in `revision.py` already,
and `test_no_element_pattern_is_compiled_in_two_modules` failed the
moment this one was compiled rather than inlined into a `findall`.

### An argued equivalence can be WRONG, and the argument says how

The seventh sweep's note on `crossrefs` said the `count=1` in
`_with_hyperlink_style` was equivalent because "`w:rPr` admits a single
`w:rStyle`, an rPr string has one opening tag". Both halves are true of
a valid `w:rPr`. Neither is true of the STRING that function is handed:
`w:rPrChange` holds the formatting a tracked change replaced, and it is
a `w:rPr` nested inside the `w:rPr`. So a run whose only character
style sat in that snapshot had the Hyperlink style written into the
historical record, and the properties the page shows got none.

The mutant was killed by the fix, three defects came out of six lines,
and the lesson is about the shape of the argument rather than that one
line: **an equivalence argued from what the SCHEMA allows is an
argument about the element, not about the string**. Ask what the
argument excludes before writing it down — a snapshot, an empty
element, a second copy of something that "can only appear once" — and
the same three shapes are the ones this package keeps meeting.

Which is also the case for re-reading an argued list. The figure does
not move when a survivor is argued rather than killed, so a module
whose remaining survivors are all argued reads as unchanged forever;
what changes is whether the arguments still hold. This one had not.

**The tell, after auditing a list of them:** an argument about the CODE
is sound — "the raise above leaves exactly one hit", "the loop starts
at `header`", "both sides are the same module literal", "a Counter
value the report deletes zeroes from". An argument about the DOCUMENT
is a claim about every file the tool will ever be handed, and two of
those failed the same day:

* "`w:rPr` admits a single `w:rStyle`" — true of the element, false of
  the string, because `w:rPrChange` nests one inside another;
* "bookmark ids are unique document-wide" — true of a well-formed
  document, false of one Word's Compare has duplicated a moved block
  in, which is a defect recorded three entries up in the same BACKLOG.

Five more of that kind were re-read the same afternoon and hold, each
because the invariant is enforced by the code rather than hoped for in
the input. Write down WHICH it is, and the next reader can tell in a
sentence whether it is still true.

### Re-measure the module you just CHANGED

`_xml` was measured at 4.5 %, worked, and measured again the same
afternoon. The second sample reached the lines the fix had just
written, and found two holes in them: the slot walk's `break` (a run
with two properties the new one sorts ahead of is the ordinary case)
and a same-name scan whose identity reading holds for one-character
property names and fails for every longer one. Both were pinned within
the hour.

New code is the least-measured code in the package, and a fix is new
code. The figure will not go down — the survivors that were ARGUED are
still survivors — but the sample lands somewhere new every time, and
the newest lines are where it has never been.

### Do not A/B a mutant by patching the LIVE file

The quick way to see what a mutant does is to patch the module, run the
thing, and restore it in a `finally`. It reads two answers out of one
file, and on 2026-08-20 it produced a contradiction that took a quarter
of an hour to chase: `_blocks` appeared to leave a hoisted bookmark
behind, then appeared not to, with the same fixture. What it was
actually reading was the live file in three different states — one of
the probes overlapped a sweep measuring that same module.

`kill_check` exists for this. It has its OWN checkout, refreshes it
from the live tree, applies one mutation there, and never touches the
file anyone else is reading. A probe that needs to compare two
behaviours belongs in it, or in a copy of the module under a scratch
name — never in `src/`.

### A gate's status is lost to whatever runs after it — four times now

`pyright | tail -1` swallowed pyright's status and is written up above.
On 2026-08-20 the same shape came back as `pytest -q | tail -2`, run
that way all afternoon so the summary line would show: `tail` returns 0
over a failing suite, and a commit went through red. The gates are
run UNPIPED, chained with `&&`, and anything that needs trimming gets
it after the chain, not inside it.

**A THIRD time, 2026-08-21.** `python tools/gates.py 2>&1 | tail -6` in a
`&&` chain with `git commit`: mypy refused a new test file, the gate exited
1, `tail` exited 0, and the commit went in red. The runner exists because of
this exact shape and was invoked through it.

**A FOURTH, 2026-08-24, and it was not a pipeline.** The command was the
recommended shape above with one word changed:

    python tools/gates.py > g.txt 2>&1; echo "exit=$?"; \
        grep -E "^FAILED|pytest" g.txt | head -2 && git add … && git commit …

`grep` found the failure, so grep SUCCEEDED, so `&&` ran the commit — and
a red mypy reached master. Reading the failure and acting on it were the
same command, so the exit code that mattered sat two commands upstream of
the `&&`.

The rule survives the variant; the reason for it gets wider. It is not
"a pipeline hides a status", it is **anything between the gate and the
commit has its own exit code, and `&&` reads the nearest one.** A grep, a
`tail`, an `echo`, a `head` — each is a command that can succeed while
the thing it is reporting failed.

So the shape below is not "redirect instead of piping". It is: the gate
run ENDS the command. Read the status. Then, separately, commit.

There is no wording that fixes a habit. What does: never put a gate run and
a commit in one chain. Redirect and read the status —

    python tools/gates.py > /tmp/g.txt 2>&1; echo "exit=$?"; tail -6 /tmp/g.txt

— and commit as its own command, after reading that number.

### A backslash does not survive the BASH tool. It survives PowerShell.

**Never put a backslash in a `python - <<'PY'` heredoc.** Five times on
2026-08-20/21 a patch script written that way arrived with its
backslashes halved — `\\` as `\` — and what that costs depends on where
it lands: a broken quote (ruff catches it), a line continuation that
silently joins two lines, or `\b` as U+0008 BACKSPACE, which `grep`, a
diff and the terminal all render as nothing.
`w:footnoteReference\b[^>]*` went into `_xml.py` as a regex that also
matches `<w:footnoteReferenceX` and read as correct in every review.

**Measured 2026-08-21, and it is the TOOL, not the shell.** The same
payload, writing the same regex to a file:

    Bash tool         'PAT = re.compile("w:footnoteReference\x08[^>]*")'
    PowerShell tool   'PAT = re.compile("w:footnoteReference\b[^>]*")'

So the rule is a tool choice, not a habit to remember:

* a payload containing a backslash goes through the **Write/Edit tools**
  (every file this session edited that way is intact) or the
  **PowerShell tool**;
* `chr(92)` still composes one where a literal backslash must reach the
  output and neither is available;
* the Bash tool is for everything else, which is most things.

**And the sweep for the damage is a gate** —
`tests/test_control_characters.py` reads every `.py`, `.md`, `.toml`,
`.cfg` and `.yml` in the tree in 0.1 s and names the file, the line and
the surrounding text, so `pytest` refuses what a session used to have to
remember to look for. Ruff's `PLE2510` catches the character in a string
of any kind — raw, plain, f-string, docstring — but not in a comment,
and nothing lints `.md`. Those two are what the sweep is for.

### A fixture that HASHES is a fixture with a fresh draw in it

The test for `promote`'s stale-batch guard needed content whose hash
sorts BELOW the baseline's, and searched for one. A docx carries the
time it was zipped, so the baseline hash is a new number on every run —
and when it lands near the bottom of the range no candidate sorts under
it. Green a hundred times, red once, and passing alone: the signature
of a fixture that draws.

The fix is not more tries. Write BOTH candidates, sort them by hash,
and `shutil.copy2` them into place — copying preserves the bytes, so
the ordering the test asserts is the ordering it gets.

### A test can ask about the MACHINE instead of the code

`stale_figures --figures` reads the session files, and the first test
written for it asserted that some module had a figure. It passed here
and failed on all three Pythons in CI, twice: a checkout has no session
files — they are local and none is committed — so every line reads
"never measured" and the list of measured ones is empty.

The tell is that the assertion was about a POPULATION the repository
does not carry. What holds in any checkout is the shape: one line per
module in the harness map, each ending in a verdict, and any line that
does carry a figure carrying it in the documented form. Verified by
running the test in `D:/docxkit-kc` — a checkout with no session files,
which is what CI is, and which is sitting there anyway for `kill_check`.

The same trap is behind two of the instrument defects above: the sweep
that answered differently depending on the shell that started it, and
the private checkouts that held the files of the day they were made.
**When a tool reads the machine's state, its tests have to say which
part of that state is the contract.**

### A stub that ignores its argument hides every mutant at its call sites

`_table_core._Span` lets a hand-walked element stand in for an
`re.Match`, and its `group` took an index and returned the whole element
whatever it was given. Seventeen of that module's 36 survivors were
`tc.group(0)` written `group(1)` or `group(-1)` at every call site in
the file — none of them killable, because a typo read as the answer the
caller wanted. It raises `IndexError` now, like the thing it imitates,
and the tests that already walk those calls kill all seventeen.

This is the fake-that-is-too-forgiving lesson from the `word.py` round
in a smaller and more common shape: **where a stand-in is more permissive
than the thing it stands in for, every test that goes through it is
measuring less than it looks.** The tell in a survivor list is a cluster
of index or argument mutants spread across unrelated call sites — they
share a callee, and the callee is the finding.

### The layers a person READS are the ones nothing pins

Six modules came down in the same week — the comparison's three layers,
the citation builder, the figures, the tables — and the survivors were
almost never in what the code decides. They were in what it hands back:

* how much of a comment, a suspect entry, or a paragraph the report
  quotes — `note[:110]`, `surname[:60]`, `text[:90]`, each of them the
  difference between a summary and a screenful;
* which paragraph a finding names — `¶{i + 1}` under seven arithmetic
  mutants, several of which agree with `+` at the index the fixture
  happened to use. Index 0 agrees with `|`, index 1 with `<<`, index 2
  with `|` again; index 3 is the smallest that separates all seven, and
  a report line at index 1 is a fixture that cannot see them;
* whether a count is mentioned at all — `", suspect N" if self.suspect
  else ""`, which has to be right in both directions or a clean round
  reads as a finding;
* which of two things the finding is ABOUT — `gone[0]`, `hits[0]`,
  `regions[-1]`, all invisible in a fixture with one of them.

None of those changes whether a round passes. Every one of them changes
what the person doing the round is looking at, which is the whole
product of a comparison.

### The eighth sweep: the FIGURES were the thing that was wrong

Four rounds ran against `guard`, `styles`, `pages`, `batch`, `placement`
and `refstyle` on 2026-08-24, and the largest finding was not in any of
them. **The table those modules were chosen from was wrong in three
independent ways, and each way flatters or damns a module without
touching its code.**

**The three worst rows in the table were overstated by 3-10x.**
`guard.py` recorded 43.6% and measured 4.5%; `styles.py` 51.2% and
13.9%; `pages.py` 42.8% and 9.0% — every one of them before a single
test was written. A figure ages against the SOURCE and against the
HARNESS, and `stale_figures` says which moved. Believe it: the whole day
was spent at modules that did not need one.

**A recorded figure can be measuring the harness rather than the
module.** 29 of `styles.py`'s 36 real survivors sat in two functions
whose tests live in `test_refstyle_layout.py`, a file the map did not
name. Adding that one line took it from 36 to 10 with no test written.
Third instance of that shape (`errors.py`, `_table_core.py`, now this),
and the first found by ASKING rather than by being surprised: list every
test file that IMPORTS a module, diff against what the map names, look
at the ones with a whole function's worth of survivors.

**A `--sample` run reads as a complete one.** It marks the mutants it
will not run SKIPPED, and a skip IS a row, so the "did it finish" check
said yes. 23 of ~44 rows turned out to be samples wearing no mark, some
a sixth of the module — `_table_layout` 460 of 2757, `placement` 260 of
1689. The test is `ran < graded`, not `graded < planned`. They carry
`SAMPLED n/N` now. And a sample can REPLACE a complete run: see the open
backlog entry, where `crossrefs.py` went from 57/822 to a 260 sample and
the better measurement is simply gone.

**A module with no entry in the map is invisible rather than
unmeasured.** `harness_for` falls back to the files that NAME a module,
so it still runs — but the table walks the map, and "not in the table"
reads exactly like "nothing to do here". Two modules sat outside the
programme that way, one of them the largest in the package. A test now
asserts every module has an entry.

**And the tool that verifies a finding needs the same lock as the tool
that finds them.** `replay_survivors` IS `kill_check` called once per
survivor, so a replay holds one shared checkout for twenty minutes while
looking exactly like nothing is running. A `kill_check` run beside one
reported four mutants SURVIVED that its tests do kill. The cost was not
a wrong answer — it was not knowing which answers were wrong, so two
rounds of evidence and a 348-case replay all had to be redone.

**Two habits that came out of the round itself**, both cheap:

* **kill_check names the test that killed each mutant. Read that name.**
  A kill attributed to a test you did not write means yours is not
  carrying it — which is the cheapest redundancy check there is, because
  it costs nothing beyond the verification you were already running.
  Three tests were written and dropped that way in one afternoon.
* **Ask what ELSE would make this number come out right.** Twice a test
  of mine was green for a reason other than the one in its docstring: a
  table fixture asserting a surname the surrounding PROSE supplied, and
  an assertion for "any issue at paragraph 6" that three different code
  paths could satisfy. If the answer is "several things", the check is
  decoration.

### The ninth sweep: `revision/`'s halves measured, and three instruments that could not see them

The first measurement of three of `revision/`'s halves, and `pages.py`
again, on 2026-09-11 — four modules in four worktrees at once, each
against the harness `harness_map` names. **cosmic-ray 8.7.0**, which
plans more mutants than the 8.4.6 behind every figure above (503 for
`pages.py` against 180), so these are not a continuation of those rows.

| module | mutants | real survival | worked | left |
|---|---|---|---|---|
| `pages.py` | 503 | 9.0 % (31/345) | `page_texts`, which every caller stubs and no test called: 12 survivors, 2 tests | 19, in `_printed_number`, `_outermost_line` and `problems` — known since 24.08, not this round's |
| `revision/_baseline.py` | 54 | 13.2 % (7/53) | the refusal that tells a Word-eaten link from a cut clause, and the verb's timing | none: 5 killed, 2 argued |
| `revision/_registry.py` | 211 | 18.1 % (30/166) | the registry's header, `..` spellings, the scan depth, a `continue` that dropped every paper after a bad one | none: 28 killed, 2 argued |
| `revision/_validate.py` | 398 | 11.2 % (33/295) | the anchor phrase's two bounds, a stamp that sorts high, `glyph_math_only` beside a footnote | none: 23 killed, 8 argued, 2 cosmetic |

**`left` is counted from `kill_check`, not from a second sweep**: every
survivor above was applied in the checkout and watched die against the
test written for it, or argued in `tools/equivalents.toml` and checked
by `verify_equivalents.py`. The code added that day — `ValidateReport.
exit_code`, `survey_exit_code`, `BaselineReport`, `math_anchors`,
`render_anchors`' folding — survived nothing but the two bounds, which
the planned tree's tests read through the constants.

**The run's own findings were in the instruments, and all three are in
BACKLOG-ARCHIVE.md under 11.09.**

* **A mutant of the isolation escapes it.** One mutant of
  `registry_path` skipped the `DOCXKIT_PAPERS` override, and its harness
  appended 160 throwaway papers to the author's real registry. Correctly
  KILLED; nothing reports side effects. `sandboxed_appdata` puts every
  per-user root a mutant can reach beside the worktree.
* **`by: ?` is a broken checkout, not a verdict.** `kill_check.sync`
  copied the package with a flat glob and left the halves a fortnight
  stale; every harness importing them failed to collect, and six correct
  claims read "killed". The note on `*.py` globs, one tool further on.
  It also refused its own lock, so a multi-module check ended after the
  first module.
* **The two readers of the claims file keyed a half differently** — by
  file name and by path — so no claim about a half could both count and
  be checked. Keyed by path now.

A kill with no named test, a verdict that arrives faster than the
harness could have run, a figure no second reader can reproduce: each of
those was an instrument talking about itself, and each read at first as
a finding about the code.

