# Working on docxkit

The rules below are not style preferences. Each one is here because
breaking it produced a broken manuscript, and the comment in the code
usually names the paper it happened to.

## What belongs here, and what stays with the paper

The **engine** is shared: how to recognise a citation, how to replace a
figure's image, how to attach a comment to a revision.

The **rules** stay with the paper: which referee point a revision answers,
what its house style is, that "WHO" in the text means "World Health
Organization" in the bibliography. Those differ per paper and always will.

The seam is a callback or a lookup the paper owns — `classify(ctx)` in
`tracked.build`, `_AUTHOR_ALIASES` in AFI's own code. If a change would
put a paper's vocabulary into docxkit, it is on the wrong side of the seam.

## Non-negotiables

- **Never save through python-docx.** It drops parts it does not model:
  saving loses comments, and it cannot see text inside `<w:ins>` at all.
  Work on the parts dict (`docxkit.package`).
- **Never hand-author `w:ins`/`w:del` to produce a deliverable.** It has
  repeatedly failed to open in Word across these papers. Use
  `CompareDocuments` (`docxkit.tracked`). Hand-authored markup is fine as
  an *edit vehicle* for small in-place changes — that is what DSI does —
  but not to build a redline.
- **Anchor on visible text, never on raw XML.** Word fragments runs at
  rsid boundaries: "Figure 6" is often stored as `Figur` + `e` + ` 6`.
- **Assert every anchor.** A replace that silently matches nothing is how
  a build keeps "succeeding" while dropping an edit.
- **Run `preserve_space` as the last build step.** An unprotected edge
  space in a bare `<w:t>` is eaten by Word and ships in the deliverable.

## A modified table is hundreds of revisions

Word's Compare makes every changed **cell** its own revision — AFI's R2
round had 153 in one table, 105 in another, 281 of 368 in total. So
`comments.annotate` coalesces by default: one balloon per distinct
comment text per table (`tables=COALESCE`).

Coalescing on the comment TEXT, not on "the first revision in the
table", is deliberate — AFI's Table 4 carries both a columns-removed
comment and a header-relabel one, and keeping only the first would drop
whichever came second. Prose is never coalesced: two paragraphs
answering one referee point are two places the reader must be shown.

`unclassified` counts **comments**, not revisions, for the same reason.
A table whose cells match no rule needs one signature, so it reports 1.
Counting revisions made AFI's "add a signature to SIG_MAP" warning fire
272 times for cells that were deliberately bare.

Pass `tables=comments.ALL` only to reproduce a deliverable built before
this existed — AFI's R1 round is pinned that way because the author
reviewed it with per-cell balloons.

## The cross-reference convention

Figures and tables are linked in both directions, and the bookmark names
are house style — `docxkit.crossrefs` implements it, papers do not
reinvent it:

| where | bookmark | links to |
|---|---|---|
| first in-text mention | `Table1` + `txt` → `Table1txt` | `Table1` |
| the caption | `Table1` | `Table1txt` |

So "as shown in Table 1" jumps to the table, and the table's caption
label jumps back to that sentence. The same `<name>txt` suffix marks the
in-text end of a **citation** link (`Halliday2020txt`), so anything
scanning for mentions must filter on the caption label — matching every
bookmark ending in "txt" reported 48 citations as missing figures.

Run it with `docxkit crossrefs PAPER.docx` (dry run) or `--write`.

## Testing

Four gates, all of which must pass:

```
python -m pytest        # synthetic fixtures, no Word required
python -m ruff check .
python -m mypy
python -m pyright       # what Pylance shows in the editor
```

Install what they need with `pip install -e .[dev]` — hypothesis is in
there because the property suite imports it at module level, so a clone
without it does not lose those tests quietly, it fails at collection.

**What CI installs is `.[dev,pdf]`, and the difference is a gate.**
pymupdf is not Windows-only and `tests/test_pages.py` builds its PDFs
with pymupdf itself, so those 15 tests run anywhere — and `pages.py`'s
85 % floor assumes they did. The other extras stay out, which makes
their imports ABSENT rather than untyped on a clean checkout: that needs
an entry in the mypy override list AND a `pyright: ignore` on the import
line. latex2mathml taught this in August and pymupdf repeated it three
days later.

**The gates run in SERIES, and a red step hides every step behind it.**
From 2026-08-14 to 08-18 an unused variable and an unsorted import block
kept ruff red for 57 consecutive runs, and behind them sat a mypy error
on all three Python versions and a module 32 points under its coverage
floor. Each became visible only when the one in front of it was fixed.
Every step after ruff now carries `if: ${{ !cancelled() }}`: the job
still fails on any red gate, and the report says how many are red.

```
python tools/coverage_floor.py    # per-module floors, as a ratchet
```

A single global number hides the thing worth knowing: this package sat
at 88% overall while `tracked.py` — which builds the deliverable that
ships to journals — was at 0%, paid for by well-covered code elsewhere.
The floors are the CURRENT numbers, so a module can never lose coverage,
and the exceptions in that file say out loud where the debt is.
`--update` raises them after you cover more.

`cli.py` was that debt at 52%, and it is now at 100% — it holds every
`--write` path, which is the code that edits an author's file. Those
tests assert on the FILE (written, not written, and what the backup
holds) rather than on the message, because a message is not what an
author loses. `word.py` at 73% is what remains, and most of what is
uncovered there is COM itself rather than a decision of ours.

And one more, deselected by default because it drives a real Word:

```
python -m pytest -m word    # ~40s; before a release, and after ANY
                            # edit to a width table in _table_layout
```

It asks Word for the advance of every printable ASCII character and
compares the model's tables to the answer. Run it when you touch those
tables: they had been hand-tuned from a PDF render and were out by up to
10% — see V4 in `ROBUSTNESS_PLAN.md`. Expect a passing run to print
first-chance RPC exceptions from Word's teardown; read the exit code.

mypy and pyright disagree just enough to be worth running both: only the
stubs told either of them that `part.get()` can return None, and only
pyright saw it through `lxml-stubs` before the mypy override list was
trimmed. Keep `lxml-stubs` installed (it is in the `dev` extra) — without
it both checkers go quiet on every lxml call.

And one that matters more than any of them:

```
python tools/sweep.py <project-root> ...
```

The sweep runs every read-only routine over real manuscripts. **Run it
after any change to the reading routines.** The unit suite passed while
`tables.read_all` was failing on the papers' own tracked deliverables;
the sweep found that, plus a byte-order mark and nested tables, in one
pass over 347 documents. It is read-only and copies each file to TEMP, so
it cannot touch a manuscript.

For anything Word-backed, the real check is `docxkit verify` — does Word
read the file back as written, or repair it on open?

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

| module | measured | after | the tests that round wrote |
|---|---|---|---|
| `tracked.py` | 36.3 % | **9.4 %** | three rounds, below |
| `equations.py` | 24.9 % | — | `prose_math`'s context window; five OMML shapes `to_latex` claims and nothing built |
| `_table_layout.py` | 18.4 % VOID | 21.0 %, then void | the harness was missing three of its own test files; the round after it found an S2 |
| `cli.py` | 17.7 % | — | what `math`, `inspect`, `count`, `tasks` and `figures` PRINT |
| `comments.py` | 17.4 %\* | **24.2 %** | the two rewrites, and the two distances |
| `footnotes.py` | 15.6 % | — | — |
| `revision.py` | 14.3 % | — | — |
| `_compare_read.py` | 12.6 % (full run) | — | `mask_volatile_fields`' scan, and two argued equivalences |
| `styles.py` | 8.7 % | — | — |

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

The largest cluster now is 16 in `<module>` — the glyph-width table,
whose numbers are the one thing in this package that only
`pytest -m word` can really check, since the answer lives in Word.

**And 21.0 % is itself void now**, for the ordinary reason: reading the
next cluster down — 12 survivors in `_house_width` — found an S2 (the
table width written ahead of the `tblStyle` CT_TblPr wants first, which
Word drops on the next save), and fixing it changed the source. A
survivor series ends where the module does. What the round bought is in
the BACKLOG entry; the number to compare against is the next fresh
draw.

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

## Do not "harden" the XML parser without measuring it first

A review will eventually propose passing
`etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)`
everywhere, against XXE. Measured on 2026-08-09, that would make this
package **more** permissive, not less:

* lxml's DEFAULTS already refuse a document carrying an external entity —
  `load_dtd=False` is the default, so the declaration is never
  registered and the reference fails to parse. `lint` reports
  "not well-formed XML: Entity 'xxe' not defined", and `write_docx`
  refuses to write it;
* with `resolve_entities=False`, that same file PARSES, and `&xxe;`
  survives as literal text. The refusal becomes an acceptance.

`no_network=True` and `huge_tree=False` are already the defaults too, so
the change buys nothing and costs a gate. If you want to revisit it,
write the hostile .docx first and check what the current code does with
it — the answer is in `tests/test_lint.py`'s territory, not in a
CVE checklist.

## The revision protocol lives here, the paper keeps paper.toml

`docxkit.revision` is the single-file protocol every paper on this
machine revises through: ONE `revision/working.docx`, whose state is
readable from the file itself — 0 revisions is the truth, more than 0 is
a proposal awaiting the author's verdict.

It is here for the same reason as everything else: two papers migrated
to it on one day, and the second got its tools by copying four files out
of the first. They were pure docxkit wrappers already. The third copy is
where they would have started disagreeing about what the protocol IS.

The seam is the usual one. The engine is shared — how to ingest, build,
validate, promote. What stays with the paper is `revision/paper.toml`:
its name, its author string, and the list of its own gates. Those gates
are LISTED by `revision validate` and never run. What a paper checks is
the paper's business, and a shared tool that shells out to per-project
commands is a different, larger promise than this one makes.

Three rules that are not obvious from the code:

* **The author accepts; the tool never does.** If revisions are still
  pending on handback, say WHERE and stop. `status` names the part,
  because Review > Next walks the body and both Simple Markup and No
  Markup hide footnote balloons — "1 pending" otherwise sends an author
  hunting through prose for something that is in a footnote.
* **Resolve before extend.** Word's Compare rebuilds a redline from
  ACCEPTED content, so a batch built on a baseline with pending
  revisions flattens them into plain text and the author's open verdicts
  are decided for them. `BaselinePending`, exit 3.
* **Text-only goes through Compare; anything touching math does not.**
  Word cannot serialize tracked math. Measured on a real subscript
  batch: hand-authored gave 4 insertions and reject-all restored the
  baseline; clean-build plus Compare gave 0 and it did not.
  `MathResolved`, exit 2.

`reject-all == baseline` is the check that proves a batch is fully
REVIEWABLE. If rejecting everything does not reproduce the baseline,
something in it cannot be refused and the author's veto is not real.

## Two habits worth keeping

**Validate against a real paper before believing a green suite.** Every
module in here has had a bug that only real documents exposed: the OMML
pattern rejected a namespaced tag, `parse_reference` knew one house style
of three, `find_all` counted "Figure 3 shows…" as a caption. The
synthetic tests were green each time.

**Write the reason, not the rule.** A comment saying "captions sit above
figures" is worth little; one saying it *and* that mapping to the nearest
drawing before it gets every figure wrong by one is what stops the next
person reverting it.

## Measure a proposed CHECK before writing it, not after

Not the same habit as measuring a fix. A check is a claim about what
every manuscript on this machine should look like, and the corpus can
refute it in a minute — before it costs a test suite, a CLI line and a
reader's attention.

The rule proposed for a link label that had swallowed its caption was
"no label may contain a sentence-ending `:` or `.` followed by more
words". It fires **5,378 times across 718 of 1,873 manuscripts**: many
papers link the WHOLE caption by convention, so the damaged label and
the house style are the same string. Narrowing it to exhibit back-links
and to labels that disagree with their own document's majority — the
`footnotes.sizes` framing, which is the right next thing to try — still
left 936 in 332.

That measurement is the finding. **Some defects are not a property of
one document at all**, and for those the only instrument is a
comparison: `compare` now pairs the label that lost text with the one
that gained it, and cannot cry wolf on a convention because a convention
does not change between two versions. Before adding a check, ask which
kind you have — and if the answer is "the same shape is legitimate in
some papers", it belongs in `compare`, not in an audit.

The sibling failure is a check that is right and unreadable: the same
"part dropped" line was printed for `docProps/*`, which Word regenerates
on every save, and for the customXml data store, which nothing puts
back. Three papers' worth of ignorable noise around one real loss is not
a warning. Classify, or say nothing.

## Four traps that keep coming back

**A search over a `w:tbl` is not a search over THAT table.** `rows_of` and
`cells_of` count depth and say so — "a nested table's rows are not its
rows" — but a table's GRID and PROPERTIES are found by searching, and
those searches ran over the whole element. A questionnaire nests tables
freely, and the outer table only has to be MISSING a property for the
first match to be the inner table's: `fit_columns` switched a nested
table to fixed layout and left the outer one autofit, rewrote the inner
table's cell margins, measured its own columns against the inner table's
padding, and counted the inner table's `w:gridCol`s as its own — giving a
two-column table a four-column grid. Go through `_own_grid` /
`_own_tblpr`; everything before the table's own `w:tblGrid` is its own,
and nothing after it is.

Its sibling: **an element written in another attribute order is the same
element.** `<w:tblW w:type="auto" w:w="0"/>` is what one accepted paper
holds, and a pattern spelling `w:w` before `w:type` matched nothing
there — so the table kept an auto width while its columns were divided
in fixed dxa. Write `<w:tblW\b[^>]*/>`. The bookmark patterns in `_xml`
carry the same warning, and it had not travelled.


**`x or default` is a bug when `x` may be an lxml element.** An element
with no children is FALSY, so a legitimately empty `w:tcPr` or `w:pPr`
silently becomes the default and the caller's real value is discarded.
Write `x if x is not None else default`. Audited 2026-08-06: no live
site does this — the two candidates raised in review were a `str`
(where empty *does* mean "none given") and a `NamedTuple` (always
truthy, being a fixed-length tuple). It stays worth checking on review
because the failure is silent and the correct-looking form is wrong.

**Build content as STRINGS, not shared lxml elements.** In lxml,
appending an element that already has a parent MOVES it, so reusing one
`pPr` template across N paragraphs leaves the first N-1 without their
properties. This is why `body.para(ppr=...)`, `cell(tcpr=...)` and
`table(tblpr=...)` all take XML *strings*: a string is copied at every
interpolation, so the hazard cannot arise through this API. The only
places here that append live elements are `revisions._unwrap` and
`_merge_into_next`, where moving is the point. Keep new builders
string-based rather than adding a `copy.deepcopy` obligation for
callers to forget.

**Correcting text means correcting the OFFSET too.** A match carries both
what it matched and where it sat, and fixing one without the other fails
silently. `strip_lead` had been trimming a wrongly-swallowed word off a
citation's `authors` since LE le15 while leaving `start` where it was, so
every hyperlink `link_all` wrote read "Similarly, Liebman and Luttmer
(2015)": the right entry, underlined from the wrong word. The audits had
the same defect in reporting form, quoting a snippet nobody could find in
the document. Any helper that narrows or widens a match must return the
span with it — which is why `resolve_lead` and `extend_to_name` take and
return a `Citation` rather than a string.

## The ported modules

`word_edits.py` came over from `C:\Users\Ezhik\tools` unchanged and is
still exempt from lint and type checking on purpose: it is working,
well-exercised code, and reformatting it would risk behaviour for no
benefit. New code is held to the full ruleset.

`compare.py` was exempt for the same reason and is not any more. The
exemption's premise — "carried over unchanged" — stopped being true the
day it was rewritten to read every part of a package, and it is the
module most likely to be extended next. It is now three typed layers
behind a facade: `_compare_read` (a package to paragraphs) knows nothing
of differences, `_compare_diff` (paragraphs to a report) knows nothing
of files or printing, `_compare_render` (a report to a page and an exit
code) knows nothing of XML. A test asserts that stays acyclic.

Two things made the split safe to take, and both are worth reusing:

* **Characterization tests first.** The eleven that existed are what
  showed a body-only document still compares exactly as it did when the
  diff was widened past `document.xml`, so that change could be judged
  on the new parts alone.
* **An oracle over real documents.** The previous implementation was
  kept beside the new one and both were run over 210 comparisons of real
  manuscripts — every version pair and every document against itself —
  requiring byte-identical JSON. A unit suite pins the behaviour someone
  thought to write down; this pins all of it. It is a throwaway script
  and worth writing again for the next refactor of a build-critical
  path.

The third port, `_citation_audit.py`, was REWRITTEN onto the shared
grammar (2026-08-01) and folded into `citations.py`: the old audit read
only element-form links, so on a fresh build (field-form links) it
reported every entry orphaned — 127 of AFI v13's 127 findings were that
false positive — and its underscore-name filter reported Word's own
`_Heading` bookmarks as broken links.
