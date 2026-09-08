# docxkit backlog — closed entries

The `## Fixed` half of [`BACKLOG.md`](BACKLOG.md), split out on
2026-08-30. Nothing here is dead: **"did we ever fix that?" is a real
question later**, and it is the question this file exists to answer.
Several papers cite an entry by its heading.

The rules are BACKLOG.md's — read them there. What matters when writing
here: an entry arrives when its fix lands, carrying its commit hash and
its `<!-- status: fixed -->` marker, and `tools/backlog_status.py` gates
that. Nothing is ever deleted from this file.

Newest first, as they were in BACKLOG.md.

## Fixed

### ~~S3 — `kill_check.sync` cannot rebuild its checkout after the DIRECTORY is deleted, and the gate stays red until somebody runs `git worktree prune`~~ — FIXED 08.09, `43c57bd`
<!-- status: fixed -->

**Fixed 2026-09-08.** `sync` runs `git worktree prune` before `add` when
`ROOT` is missing. Harmless when nothing is stale — prune only removes
registrations whose directory is gone — and the checkout can now rebuild
from the one state a person can put it in by hand.

`sync` guarded on `ROOT.exists()`, the DIRECTORY, while git also keeps a
REGISTRATION. Delete the folder and the two disagree:

    fatal: 'D:/docxkit-kc' is a missing but already registered worktree;
    use 'add -f' to override, or 'prune' or 'remove' to clear

exit 128, raised as `CalledProcessError` inside
`test_the_checkout_holds_TODAYS_tools_scripts`, so the chain stops at
`pytest` on every run until a person who knows what a worktree is
intervenes. Git names the fix in its own message and the message is
three frames deep in a traceback.

**Met by deleting folders, which is how anyone meets it.** `docxkit-kc`
and four `docxkit-mut*` copies sat on `D:` looking like abandoned
scratch directories — they are worktrees of the live repo, nothing in
the tree names them (`ROOT` is built from the repo's own name, so a grep
for the literal string finds nothing), and the one that is a live cache
is indistinguishable from the four that were not. Removing them is the
right call; git's administrative half is what made it a failure instead
of a rebuild.

**The checkout is a CACHE.** It is created once, detached, and reused
for weeks precisely so it can be thrown away — that a throwaway could
not be thrown away is the defect, not the deletion.

### ~~S2 — `ingest` explains every LOST link as a silent Word paragraph collapse, including the ones whose text the author deleted on purpose~~ — FIXED 08.09, `43c57bd`
<!-- status: fixed -->

**Fixed 2026-09-08.** `Loss` carries `words`: is the lost thing's own label
still visible anywhere in the hand-back? `_link_changes` measures it against
every text part, so a citation that moved into a footnote is not read as
deleted. `ingest` groups the LOST block by it and explains each group
separately — the collapse story only over the links whose words survive, and
*"the WORDS are gone too, so this is not Word's doing"* over the ones the
author cut. The single explanation is gone.

**Headed only when the list is MIXED.** That is the case it got wrong; a
hand-back losing one kind reads better flat, and the existing gate on naming
every element stays exactly as it was.

`baseline`'s refusal marks the same split — `[words survive]` against the
repairable ones, and it no longer asserts the collapse over a list where it is
false. Notes, bookmarks, comments and glyphs leave `words` at `None` and are
described without the claim: Word eating a footnote takes the definition and
its text together (LI7's note 15), so the question separates nothing there.

Filed as **S5**, a severity this file's scale does not define — S1/S2/S3/S4 —
and the token appears nowhere else in either file. Recorded as S2, which is
what it is: wrong output no gate sees.

`revision ingest` closes its LOST block with one explanation for the whole
list:

    Word does this silently when it collapses a paragraph to make an edit;
    the words all survive, so no content layer above shows it.

For a link eaten by a rewrite that is exactly right, and `r2`/`r11` put it
back. For a citation the author DELETED, every clause of it is false: the
words did not survive, no script can restore it, and the content layers above
did show it — the deletion is sitting in the `text` section of the same
report, a few lines up.

Measured 2026-09-08 on Aging_Well, ingesting a hand copy-edit that mixed both
kinds in one report: 19 LOST, of which 4 glyphs, 4 links whose mentions were
intact (`Robeyns2005`, `North1990`, `Box2` ×2 — r2/r11 restored all four) and
5 whose mentions were gone (`Cox1987`, `WorldBank1994`, `Holzmann2005`,
`Barr2010`, `OECD2006`, each cited in exactly one place, and that place cut).
The report gives no way to tell the two kinds apart, so the reader either runs
the repair lane hoping it covers everything, or reads five deliberate
editorial cuts as damage Word did.

`ingest` already extracts the visible text of both sides. Counting the
citation's own mentions on the working side separates the two kinds exactly:
mentions > 0 is the collapse case (repair lane), mentions == 0 is a deliberate
deletion (`--accept-loss`, and the reference entry is now orphaned — which is
what `citations` and `refstyle` report next, and is worth saying here first).

### ~~S4 — repeating `--accept-loss` silently keeps only the last one, and the refusal it produces reads like a different failure~~ — FIXED 08.09, `43c57bd`
<!-- status: fixed -->

**Fixed 2026-09-08.** `action="append"` beside the existing comma split, so
both forms work and mixtures of them do too — the printed suggestion is
copy-pasteable as printed, which was the point. `default=None`, not `[]`:
`append` mutates a mutable default in place and it would accumulate across
parses in one process, which is every test in a session.

`revision baseline --accept-loss` is documented as `ANCHOR,...` and takes a
comma-separated list, which works. Passing the flag once per loss —
`--accept-loss link:A --accept-loss link:B --accept-loss link:C` — is the
form a user reaches for when the tool has just printed one suggested flag per
loss, each on its own line:

      - link 'Kok2015 (Kok et al. 2015)'
          --accept-loss 'link:Kok2015 (Kok et al. 2015)'
      - link 'Makai2015 (Makai et al. 2015)'
          --accept-loss 'link:Makai2015 (Makai et al. 2015)'

Argparse keeps only the last, so the command refuses again with the list one
shorter. Nothing says why. The natural reading of "4 losses, I named 4, now
it says 3" is that three of the anchors failed to match — a spelling or
prefix problem — not that three of the flags were discarded before the gate
ran.

Measured 2026-09-07 baselining Aging_Well R108, four deliberate citation-link
deletions; cost one cycle. `action="append"` with the existing comma split
applied to each occurrence would make both forms work, and the printed
suggestion would then be copy-pasteable as printed, which today it is not.

### ~~S3 — `validate` says a re-emitted footnote will be emptied by reject-all when its own footnotes layer says otherwise~~ — FIXED 08.09, `43c57bd`
<!-- status: fixed -->

**Fixed 2026-09-08.** The warning is raised from the measurement instead of
the shape. `emptied_footnotes(rejected, baseline, candidates)` rejects and
compares each candidate note's own words against the baseline's; `validate`
fills it from the rejected parts it already computes, and `build` pays one
in-memory XML pass beside a Word Compare costing 40-141s.

`moved_footnotes` keeps its meaning and its name — the SHAPE is what a reader
chasing *"why is this note an insertion"* is looking for — and
`ValidateReport` now carries both, so the report cannot contradict its own
footnotes layer. A note the layer restores is reported as not part of the
mismatch rather than as a blocking finding; the strong wording survives where
rejecting measurably empties the note.

**The shape is necessary and not sufficient**, and the test fixture says why:
`moved_footnotes` flags any definition carrying an insertion and no deletion,
which includes a note the batch merely ADDED to — rejecting puts those words
back exactly.

`revision build` and `revision validate` both print, for a note whose
paragraph changed enough that Compare re-emitted the whole definition as one
insertion:

    footnote N: the whole note is one insertion with no matching deletion —
    its REFERENCE moved. Accepting is right; rejecting empties the note, so
    gate 5 will fail on it.

In the same run, `validate`'s reject-all layer reports `'footnotes': True` —
the note IS restored — and the footnotes gate passes on the rejected state.
The warning is a prediction the tool's own measurement contradicts two lines
later, and it reads as a blocking finding beside the genuine LINKS mismatch
it is printed next to.

Measured twice on Aging_Well. 2026-09-03, footnote 2, when a batch ADDED a
note and pushed the later definitions down: logged then as "one thing Compare
warned about that did not happen". 2026-09-07 (R108), footnote 12, when no
note was added at all — a task deleted a sentence from the paragraph that
carries reference 12, Compare re-emitted the definition, and the same text
printed. Reference order was `2..13` before and after, identical; the note's
own text was byte-identical; reject-all restored it.

The condition the message describes — a definition that reject-all would
empty — is real and worth warning about. What it currently keys on, a
definition emitted as an insertion with no matching deletion, is not that
condition. The reject-all footnotes layer already knows the answer; the
warning should be raised from that measurement, or downgraded to
informational when the layer disagrees with it.

### ~~S2 — a failed gate reports its last 3000 characters, so trailing noise hides the failure~~ — FIXED 08.09, `43c57bd`
<!-- status: fixed -->

**Fixed 2026-09-08.** `gates._failure` replaces `out.strip()[-3000:]`. The
tail is still the default and short output passes through whole, but the lines
a reader needs are selected first — pytest's `FAILED`/`ERROR` rows and `E   `
detail, ruff's `Found N errors`, mypy and pyright's `: error:`, traceback
frames — and any the tail would have cut are printed above it under a marker
saying how much was dropped between the two.

This is the treatment `_summary` already gave the PASSING case, which was the
asymmetry: the path that matters most was the one printing raw bytes and
hoping. Both halves are bounded, so a suite failing 300 tests cannot push its
own verdict out of the window a second way.

`gates.run` prints `out.strip()[-3000:]` when a gate fails. The window is
fixed and anchored to the END, so anything a gate emits *after* its failure
pushes the failure out of it. The gate's verdict is still right — the chain
stops, the exit code is 1 — and the printed reason is unusable.

Measured 2026-09-06. A red `pytest` gate printed 3000 characters of
`PytestBenchmarkWarning` (pytest-benchmark warns once per xdist worker;
sixteen lines at `-n 8`, all after the summary) and the actual failure —
`test_every_module_has_a_row_in_the_README_table`, a missing row for the new
`timings` module — was outside the window entirely. The chain had to be re-run
piped through `grep` to find out what had broken. Reproduced deliberately: a
one-line failing test under `-n 8`, `out[-3000:]`, failure not present.

**The plugin was the instance, not the defect.** It is fixed at source —
`-p no:benchmark` in `addopts`, because the suite has no benchmarks and
pytest-benchmark is not even in `[dev]` — and with that the same window shows
the assertion, its file and line, and the short summary. But the next gate
with a chatty tail does this again, and nothing is watching for it: a warning
burst from any plugin, a teardown that logs, a tool that prints a banner after
its result.

**Suggested fix:** make the window content-aware rather than positional. Keep
the tail, but ensure the lines a reader needs are in it — pytest's
`=== short test summary info ===` block, ruff's `Found N errors`, mypy's
`: error` lines. `_summary` already does exactly this kind of selection for
the PASSING case (`_SUMMARY`, and it takes the LAST matching line because a
run once ended with an interpreter note about the C stack). The failing case
never got the same treatment, which is the asymmetry: the path that matters
most is the one printing raw bytes and hoping.

**Not filed as S3** because the gate does fail, and does say which gate. The
cost is the reader's next twenty minutes, in the state — a red chain — where
they can least afford it.

### ~~S4 — `batch.run` prints the glyphs it repairs, and only the CLI makes stdout safe~~ — FIXED 06.09, `0a31b71`
<!-- status: fixed -->

**Fixed 2026-09-06** — `0a31b71`. `batch.run` and `batch.apply_steps` call
`utf8_stdout()`, and so does `_compare_render.render`.

**It was two sites, not one.** The entry named `batch.run`; measuring the
other library printers found `compare.render` with the same hole — public,
imported directly by paper scripts, and every line it prints quotes the
manuscript, so a report holding U+2212 ended with a `UnicodeEncodeError`
partway through, after the header and before the layer a reader was waiting
for. `citations.check_citations` was measured too and did NOT reproduce: its
output never quoted the entry text, so nothing outside cp1252 reached stdout.
Left alone rather than fixed on suspicion.

**The call is at the TOP of `run`, not only beside `apply_steps`**, and the
first reason written for that was wrong. A preflight refusal returns before
`apply_steps`, so the placement needs a refusal that echoes the DOCUMENT
back — and probing all four refusal paths showed three of them are the
toolkit's own English (`signature matches NO paragraph`, `` `old` is not in
that paragraph ``). The one that qualifies is `diagnose` quoting the
hyperlink label it met, verbatim: on DSI that label is Cyrillic
(`'Таблица 3'`), which cp1252 cannot encode either, and
`print(report.text())` is the documented way to read a Report.

**The fixture is its own finding.** `conftest.cp1252_console` is a context
manager, not a pytest fixture, because pytest re-assigns `sys.stdout` to its
own capture file at the start of every phase: a patch installed during
fixture SETUP is gone by the time the test body runs. The first version
passed the stream to nothing, the prints landed in pytest's capture where
they encode fine, and all four tests passed against unfixed code. It must
also be a real `TextIOWrapper` — the guard in `console` refuses anything
else, so a `StringIO` would test nothing.

Verified by removing the three calls: all four new tests fail with
`UnicodeEncodeError` out of `cp1252.py`.

**The per-paper workaround is NOT deleted**, against this file's own rule.
`Aging_Well/revision/scripts/r22_math_typography.py:176` still calls
`utf8_stdout()` under a comment saying to delete it with the fix. That tree
is not under git and the file was edited 36 minutes before the fix landed,
by a session working in it. The call is redundant now, not wrong. Delete
line 176 with its four-line comment, and `utf8_stdout` from the import on
line 67.

A repair that restores the typographic minus **aborts on a Windows console**,
because the step prints each restoration and cp1252 cannot encode `−`. The
write is then skipped and the run reports FAILED with a `UnicodeEncodeError`
where a manuscript problem would be reported.

Measured 2026-09-05 on Aging_Well, closing out R96 (`revision/scripts/r22_math_typography.py`,
which drives `docxkit.batch.run` directly):

    ** maths glyphs the accept flattened  UnicodeEncodeError: 'charmap' codec
       can't encode character '−' in position 31: character maps to <undefined>
      wrote None

`working.docx` was byte-identical before and after, so nothing was corrupted —
the step raised while printing, `batch.run` recorded a step failure, and the
repair did not happen. Re-run in the same shell with `PYTHONIOENCODING=utf-8`:
`maths glyphs restored: 20`, exit 0. **Same file, same code, opposite verdict,
and the variable is the terminal's code page.**

**`console.py` already says this is the toolkit's job** — *"Windows consoles
default to cp1252, which cannot encode the glyphs these documents and reports
are full of … Every paper script therefore opens with a call to reconfigure
stdout, and every one of them wrote it unguarded."* The guarded version now
exists, and `utf8_stdout` / `utf8_console` are called in exactly two places:
`cli.py:2405` and `compare.py:228`. **Both are entry points.** A caller that
imports the library and drives it — which is what every per-paper batch script
in every one of these projects does — inherits a strict cp1252 stdout, and
`batch.run` prints document glyphs on the way past.

So the safety sits at the CLI boundary while the printing sits in the library.
The asymmetry is invisible until a step prints a character outside cp1252,
which is precisely the steps that repair mathematics.

**Fix belongs in `batch.run`** (or in whatever the library uses to print step
progress): call `utf8_stdout()` once, the same way `compare.py` does. A test
that fails without it can wrap `sys.stdout` in a `TextIOWrapper` at cp1252 with
`errors="strict"` and assert the step still writes.

**Per-paper workaround now in place, to be deleted with the fix:**
`Aging_Well/revision/scripts/r22_math_typography.py` calls `utf8_stdout()` at
the top of `main`, with a comment pointing here. Any other paper script that
drives `batch.run` over mathematics has the same hole.

Severity is S4 rather than S3 because the run does report failure rather than
claiming success. The cost is that the failure reads like a defect in the
manuscript, at the exact moment — a close-out after an author's Word accept —
when a real glyph problem is what you are looking for.

### ~~S3 — `revision promote` leaves the PREVIOUS stamp beside the manuscript, so `guard.check` refuses the file promote just wrote~~ — FIXED 04.09, `ef7883d`
<!-- status: fixed -->

**Fixed 2026-09-04** — `ef7883d`. `guard.carry(src, dst)` writes `src`'s stamp
beside `dst` once `dst` holds `src`'s bytes — verbatim, repairs
included, and refusing (`DeliverableModified`) when the recorded hash
is not `dst`'s. `promote` calls it after the hash-verified copy and
reports the path as `PromoteReport.stamp`; for an unstamped batch it
returns None and REMOVES a stale stamp beside the manuscript, because
"no stamp" reads as cannot-verify where a stale one reads as another
file's provenance. The CLI prints the sha256 of what landed. Tests:
four on `carry` (`test_tracked_guard.py`), three on the promote
(`test_revision.py`), one line on the CLI output.

**Measured.** Health_Capacity_to_Work, 2026-09-04: after
`promote(T8_4_batch.docx)` at 17:36, `revision/working.docx.buildinfo.json`
still named an earlier round's `original`/`revised` pair and hash.
`promote` copies the batch onto `working.docx` and stamps nothing
there; whatever last wrote the stamp — the paper's own lane script,
which builds with `out=working.docx` — is what it kept saying.

**Why it is an S3 and not tidiness.** That lane script reads the stamp
through `tracked.build` → `guard.check(working.docx)`, and a stamp that
never matches is a refusal on every round. The script's answer is in
its own comment: `force=True`, "the guard cannot tell a task script's
write from a Word session, and refuses to overwrite working.docx". A
guard forced on every call is a guard retired — including for the
author's real edits, which is the one case it exists for. The stale
stamp was noticed only inside the S1 retracted in `BACKLOG.md` the same
day, as its "unconfirmed" second observation; the S1 was wrong and this
was the defect underneath it.

**The narrower thing deliberately not done:** `baseline` leaves the
stamp alone. After the author's accept the file is theirs, and
`check` on it must refuse — which a stamp recording the promoted hash
does correctly, and the next promote carries a fresh one over it.
<!-- status: fixed -->

**Fixed 2026-09-03** — `d1b2964`. `test_equations_typography.py` skips
at module level, with the reason, when `find_mml2omml_xsl` finds no
XSL (measured by pointing `DOCXKIT_MML2OMML_XSL` at nowhere: 1
skipped, saying which); the three sweep roots are `/srv/papers`, one
root on both platforms; `[tool.deptry.package_module_name_map]` says
`pywin32` provides `win32com` and `pythoncom`. Nothing in the package
changed.

Found the same evening as the entry below, by fixing it. Installing
`latex2mathml` on the runner turned the 22 red tests into 22
DIFFERENT red tests: they also need Word's own `MML2OMML.XSL`, which
ships with Office and not with Ubuntu. And behind those sat two more
failures that had never once been seen off this machine: three
`test_sweep.py` roots spelt `D:/papers`, which `os.pathsep` splits
into two on Linux — the test's own docstring explains exactly why, and
the test itself did not follow it — and the `deps` gate, added 09-02
and red on every interpreter since, because deptry learns that
`pywin32` provides `win32com` and `pythoncom` from the installed
distribution, which a Linux runner cannot have.

Three layers of red, each visible only once the one in front was
fixed: the 08-14 shape exactly, and the reason CI runs every step even
when an earlier one is red — which it did, and the second step went
unread because the first was already red. **A red gate has to be read
all the way down**, and a gate added to the chain has to be watched
through its first green run somewhere other than the machine it was
written on.

**And a fourth, `0206149`, behind the three.** With the XSL skip in
place the run reached `test_equations.py`, where one test guarded
itself with `if find_mml2omml_xsl() is None` — and the finder never
returns None, it raises. A guard that cannot fire, passing on every
machine with Office and failing on the one without, reachable only
once the `latex` extra existed on the runner. It uses the file's own
`_needs_word_and_latex()` now, like its siblings. Four layers, one
afternoon, none of them a defect in the package.

**And a fifth, `f2590d1`, the first time pytest itself was green
there.** The chain reached Coverage floors and read
`revision/_gates.py` at 97.3 % against a floor of 100 % — a floor
measured on this machine, where the module's POSIX halves are
pragma-excluded and its Windows halves run; on Linux the Windows halves
(`taskkill /T`, `CREATE_NEW_PROCESS_GROUP`) never execute and nothing
excluded them. Two tests fake the platform and the `subprocess` seam
both functions already take, and execute those lines anywhere; a pragma
would have hidden the `taskkill` argv from the mutation lists. Run
`33793652630` on `f2590d1`, 2026-09-04 00:0x local, is the first green
CI run since `7f979cc` on 2026-08-24: five layers, each measured on
this machine and true nowhere else. **A floor is a claim about a
platform** — a module that branches on `sys.platform` needs its
platform-only lines either excluded on both sides or executed on both.

### ~~S3 — every CI run since 2026-08-24 was red, on 22 tests that need an extra CI does not install~~ — FIXED 03.09, `46a8254`
<!-- status: fixed -->

**Fixed 2026-09-03** — `46a8254`. `tests/test_equations_typography.py`
`importorskip`s `latex2mathml` at module level with the reason, and CI
installs `.[dev,pdf,latex]` so the 22 tests run there rather than
skip. CONTRIBUTING and the pyproject comment that said `.[dev,pdf]`
say the new thing.

Found by the 2026-09-03 review's push, whose author looked at the
Actions tab because the review had just written "CI has not seen the
last two days" — and found it had not seen a GREEN run in ten. Twelve
consecutive failures, from `4032e04` (08-31) to `cc9eeec` (09-03), and
by the file's own history from `7f979cc` on 08-24, when
`test_equations_typography.py` landed calling `latex_to_omml` in 22
tests with no guard. CI installs `.[dev,pdf]`; the `latex` extra was
absent; every run raised `ModuleNotFoundError` 22 times and stopped.

**Measured before touching anything**: the whole suite, serially, with
`latex2mathml` hidden from `sys.modules`, fails exactly those 22 tests
and nothing else — the other gates had been green the whole time,
behind a red one nobody read. That is the 08-14 shape CONTRIBUTING
records (57 runs) in its third instance, and an S3 by this file's
scale: a gate that is always red is a gate people stop reading, and
the 09-01 review's "api runs in CI against a real tag" was written
over a red run.

The lesson it adds to the two before it: **a test that needs an
optional extra says so with `importorskip`, and CI installs every
extra a test can use.** Skipping alone would have made the red quiet
on the one machine that exists to run those tests; installing alone
leaves the next clean checkout where this one was. What the first
green step then exposed is the entry above this one.

### ~~S2 — `edit_in_place` writes the manuscript back with a COPY, which is the interruptible write `write_docx` exists to avoid~~ — FIXED 03.09, `b934730`
<!-- status: fixed -->

**Fixed 2026-09-03** — `b934730`. It is `read_parts` → transform →
`write_docx(path, parts, order=order)` now, five lines shorter than
what was there: the manuscript is only ever the DESTINATION of a rename
from a sibling `.tmp`, and the read carries `read_parts`' retry. Two
tests pin it — the manuscript is the sole destination `os.replace` sees
and no `.tmp` is left beside it; a transient read denial is ridden out —
and both failed on the unfixed source.

Filed from the 2026-09-03 structural review (`REVIEW_2026-09-03.md`).

`package.py:494–505`, by reading: the source was copied to TEMP with
`shutil.copy2` (unretried), read with a bare `zipfile.ZipFile`, written
by `write_docx` to a second TEMP file (atomically — into TEMP, where
atomicity buys nothing), and then `shutil.copy2(out, path)` over the
manuscript. A copy opens the destination for writing and streams into
it; the process dying or the mains failing mid-copy leaves a truncated
file where the manuscript was. `write_docx`'s own docstring says why
that matters here — "the machine this runs on has unreliable mains
power, which is the whole reason it matters" — and `_replace_atomically`'s
calls a copy "exactly the interruptible write being avoided". The one
function documented as the paper scripts' entry point (README, the
`docxkit` skill, `tools/consumers.txt` lines 13 and 108) was the one
that did not get it.

Two hardenings missed, not one: `read_parts` was given a six-attempt
retry on 2026-08-20 for the OneDrive `[Errno 13]` race two suites hit;
the `copy2` of the source at line 496 was the same read on the same
drive, unretried. Zero callers in `src/`, so no in-repo path exercised
either. `tests/test_package.py:83` covered a transform that raises — the
file IS intact, because the write never started — and nothing covered a
write-back that stops. No workaround was in use; most paper scripts call
`read_parts`/`write_docx` directly (126 of 237 files, per `batch.py`'s
docstring), which was the safe path by accident.

### ~~S2 — `is_locked` calls a read-only file "open in Word"~~ — FIXED 03.09, `b934730`
<!-- status: fixed -->

**Fixed 2026-09-03** — `b934730`. On `PermissionError` the mode
decides: a file whose `st_mode` lacks `S_IWRITE` is read-only, not
locked. The entry below proposed a read-only REFUSAL in
`assert_unlocked`; settled on measurement the other way — `write_docx`
clears that bit one call later (`_clear_readonly`, for the OneDrive flip
its docstring names), so refusing would be the two-verdicts defect in
another costume. A read-only manuscript now goes through
`edit_in_place` and comes out written. Two synthetic tests, both red on
the unfixed source; the read-only-AND-held case reaches the write
path's own retry, which already reports it.

Filed from the 2026-09-03 structural review (`REVIEW_2026-09-03.md`).

**Measured 2026-09-03**, this machine: a file with only `S_IREAD` set
and nothing holding it — `open(p, "r+b")` raises `PermissionError
errno=13 winerror=None`; `is_locked(p)` → `True`; clear the bit →
`False`. A sharing violation arrives through the same CRT path with the
same errno, so the `except PermissionError` at `package.py:168` could
not tell the two apart, and did not try.

What it cost. `assert_unlocked` refused with "is locked (open in Word).
Close it and retry" — the author closes a Word that is not open, retries,
and gets the same line, with nothing in the message that leads anywhere.
`readable()` took a snapshot of a file nobody held and yielded
`copied=True`, so `revision status` and `ingest` reported reading a
snapshot when they read the file. And the WRITE side already knew this
state: `_replace_atomically` calls `_clear_readonly` on exactly this
error, and its docstring says the OneDrive sync engine "flips it
read-only mid-write" — the package's own account of the drive these
manuscripts live on said the lock check would meet it.

### ~~S1 — `_set_tc_w` cannot see a `w:tcW` written `w:type` first, and writes a second one beside it~~ — FIXED 03.09, `6c94bd8`
<!-- status: fixed -->

**Fixed 2026-09-03** — `6c94bd8`. `_TCW_RE` is `<w:tcW\b[^>]*/>` now,
like `_TBLW_RE` twelve lines below it. A type-first cell is REPLACED,
not doubled (`test_tables_nested`), and `test_regex_registry` holds the
count of order-bound attribute patterns at zero across every module,
the `revision/` halves included — the check that would have found this
the day the sibling was fixed. Two tests; reverting the module fails
both. Nine gates green, 80 manuscripts swept.

Filed from the 2026-09-03 structural review (`REVIEW_2026-09-03.md`).

`_table_layout.py:81` read `_TCW_RE = <w:tcW w:w="[^"]*" w:type="\w+"/>`
— attribute order bound. Its one caller, `_set_tc_w` (line 481), takes
an empty match as "this cell has no width" and INSERTS one at the schema
slot (lines 489–493). A cell whose width Word wrote as
`<w:tcW w:type="dxa" w:w="1701"/>` therefore ended with two `w:tcW` in one
`w:tcPr` — the shape the 2026-08-20 round fixed in eight writers under
the contract "leave exactly one, and it is mine". Word takes the first,
which is the OLD width, so `fit_columns` returned its plan and the cell
kept the width it had. Nothing was red: Word opens the file, so `lint`
passes; `compare`'s FORMAT layer does not read cell widths; and
`FitReport` is the plan, not a read-back.

**Measured 2026-09-03**, a strided sample of 150 of the 2,854 `.docx`
under `F:\OneDrive\__Documents`, `word/document.xml` only: 84 spell
`w:w` first, **5 spell `w:type` first**, and 3 carry BOTH orders in one
document — so the failure was per cell, inside a table that is otherwise
fitted. The same 5 spell `w:tblW` type-first, which is the Corruption
and Wages case CONTRIBUTING already records.

The diagnosis is six lines of the same file. `_TBLW_RE` at line 93 was
rewritten to `<w:tblW\b[^>]*/>` with a comment naming that manuscript
and saying "the bookmark patterns in `_xml` carry the same warning" —
and the sibling pattern at line 81, same family, same afternoon, kept
the order-bound spelling. Of 231 literal `re.compile` patterns in the
package (AST count, 2026-09-03) four spell two namespaced attributes in
sequence; the other three (`_cite_audit.py:64`, `_xml.py:532`,
`styles.py:176`) are one-attribute-per-alternative or lookaheads and are
not order-bound. It was the last one.

### ~~S4 — `math --check` reports a redline's DELETED maths as a stranded display~~ — FIXED 02.09, `fc6c1b3`
<!-- status: fixed -->

**Fixed 2026-09-02.** `is_display` resolves a paragraph to its ACCEPTED side
before classifying it, and the entry's diagnosis was exactly right.

The entry offered two fixes and the general one is better, not merely tidier:
skipping a paragraph whose every `m:oMath` is deleted would have left the OTHER
half standing. `visible_text` drops `w:delText` and keeps `m:t`, so a paragraph
losing its WORDS already read as maths-only — and a paragraph that keeps live
maths while its prose goes IS a stranded display in the accepted view, which
the narrow rule would have got wrong in the other direction. One pass fixes
both.

**Reproduced independently before the fix.** Over 600 manuscripts, exactly one
other document carries the shape — `Missing Market 12082019.docx` ¶78, 17
`w:delText` runs and one `m:oMath` inside a deletion with a stray "G. " live —
and it was reported as a stranded display too. Its count went 10 → 9 with the
fix in, and the nine are real.

The report says so, as the entry asked: `math` prints that it read a tracked
file on its accepted side, and does not print it for a clean one where the
distinction does not exist. A count that silently answers about a different
view of the file than the one named on the command line is the shape this
backlog keeps finding.

`_accepted_side` is private on purpose — a per-paragraph regex approximation
for CLASSIFICATION, not a general accept: it does not unwrap `w:ins` or handle
a move, and `revisions.accept` is the function for that. Public, it would be
reached for as one.

Fifteen tests in `tests/test_deleted_math.py`. The revert check had to take out
the two lines rather than the module: stashing `equations.py` removes the
helper too and the tests then fail to IMPORT, which proves nothing. With just
the two lines gone, two behaviour tests fail. The paper's workaround — run the
gate on `build/edited.docx` while a proposal is pending — can go.

**Measured**, Aging_Well R78, 2026-09-01. A batch built with `--keep-math` deletes a
body paragraph carrying two inline equations (c_ij, f_j). On the accepted view
`math --check` exits 0 with 15 displays; on the promoted PROPOSAL it exits 1:

    16 display equation(s), 1 still in INLINE mode
       ¶64    'cijfj'
       -> equations.display(para) wraps them in m:oMathPara (one m:oMath per paragraph; it refuses more)

¶64 is the deleted paragraph: 10 `w:del`, no live `w:t`, its prose all
`w:delText`, the equations' runs inside tracked deletions. `visible_text` drops
the `w:delText` but keeps the `m:t`, so the paragraph reads as maths-only — the
exact signature of a stranded display — and the gate cannot tell a paragraph with
nothing live from one that IS an equation. `m:oMath` counts 266 on the proposal
against 264 on either clean side for the same reason.

**Diagnosis.** The check classifies each paragraph on `visible_text`, which is
the accepted side for prose and BOTH sides for maths. Six proposals on this paper
passed the gate only because none of them deleted an equation.

**Suggested fix:** resolve a tracked paragraph to its accepted side before
classifying — or skip a paragraph whose every `m:oMath` sits inside a `w:del` —
and say in the report that a tracked file was read on its accepted side. `lint`,
`citations` and `crossrefs` read the same redline without tripping.

**Workaround in use:** run the gate on `build/edited.docx` (the accepted view)
while the proposal is pending, and on the truth after the accept.

---

### ~~S2 — `revisions.accept` cannot remove a `w:cellDel` cell, so a tracked COLUMN deletion never passes the accept gate~~ — FIXED 02.09, `99b32a0`
<!-- status: fixed -->

**Fixed 2026-09-02.** `_apply_cell_revisions`, and the entry's diagnosis was
right: a `cellDel` is a `w:tcPr` property, not a `w:del` wrapper, and nothing
in the accept path walked it.

On the real R79 redline, accept now gives **4 rows x 2 cells, 2 gridCol, 8
w:p** against 4 x 3, 3, 12 before — exactly the four paragraphs the gate named.
Reject keeps the cells and drops the mark.

**Where the pass runs had to be measured.** Rows go before paragraphs, and
property changes go LAST so the row handler still sees flags a rejected
`trPrChange` would move out from under it. Cells go AFTER the property changes,
which is the opposite placement, because a `w:tcPrChange`'s SNAPSHOT carries
its own `w:cellDel` — Word records the cell's pre-change properties including
the delete mark. A strip that ran before the restore put the flag straight
back, and the rejected view still reported a revision. `_OUTSIDE_SNAPSHOT`
carries the live flag across on purpose, which is what makes this order safe
here where it is not for the row — and means there can be TWO, so the strip
takes every one rather than the first.

**The grid, only when the deletion IS a column.** A `tblGrid` declaring three
columns for rows that lay out two is a phantom column, so a deleted column
takes its `gridCol` with it, `gridSpan` honoured. Cells deleted at different
grid positions in different rows are an edit, not a column; guessing one would
corrupt a table that is merely edited, so a ragged deletion takes its cells and
leaves the grid alone.

**A third defect found on the way, and it is the more serious one.**
`_REVISION_NAMES` was blind to `cellIns`/`cellDel`/`cellMerge`, so a table
whose column deletion had nothing IN it — Word writes no content marker for an
already-empty cell, and none at all for a `cellMerge` — read as **0 pending ->
TRUTH**, which is the number the protocol decides everything on. That is the
same defect that list's own comment records for moves and formatting changes,
in an eighth spelling.

MEASURED over 500 manuscripts: one carries a cell revision, its accepted view
loses exactly the four cells of the one deleted column, **no document goes from
clean to pending**, and no other table changes shape.

`w:cellMerge` is deliberately not APPLIED — it records a merge or a split, not
an appearance, so applying it means recomputing `gridSpan` and `vMerge` across
the row, a different operation with a different failure mode and no corpus
example to measure against. It is COUNTED as pending, which is the honest half.

Twelve tests in `tests/test_cell_revisions.py`; reverting `revisions.py` fails
ten. The paper's `accept_check=False` workaround can go.

**Measured**, Aging_Well R79, 2026-09-02. A batch drops Table 1's third column.
Word's Compare serializes it correctly and cell-wise: every row keeps its third
`w:tc`, marked `w:cellDel` with its content in `w:del` — the author sees a
struck column. But `revisions.accept` removes only the `w:del` content and
leaves the emptied CELL (and its empty `<w:p>`) in place, so "accept every
revision" has four paragraphs the clean copy does not, and `tracked.build`'s
accept gate refuses:

    UNACCEPTED body ¶44: intended ''  accepted ''   (and ¶47, ¶50, ¶53 — one per row)

Word's OWN accept is right: AcceptAllRevisions on the same batch, extracted via
Flat OPC, compares CLEAN against the clean edit on every content layer
(STRUCTURE/TEXT/FORMULA/FORMAT/PARAGRAPH/HYPERLINK all none; only the standard
accept-glyph flattening). So the deliverable is unharmed — the gap is the XML
approximation's, same family as the footnote-deletion shells (fixed via
`footnotes.prune_orphans`).

**Diagnosis.** `revisions.accept` walks revision elements; a `cellDel` is a
`w:tcPr` property (`<w:cellDel>` inside `w:tcPr`), not a `w:del` wrapper, and
nothing in the accept path deletes table geometry.

**Suggested fix:** on accept, remove any `w:tc` whose `tcPr` carries
`w:cellDel` (and its `gridCol` accounting where the whole column goes); on
reject, strip the `cellDel` mark. A minimal repro is two rows × two columns
with one column deleted through Word Compare.

**Workaround in use:** `Aging_Well/revision/scripts/r79c_build.py` — build with
`accept_check=False` (patching `tracked.build` the way the compression round
patched `CompareMoves`) and prove the accept side through Word itself:
AcceptAllRevisions on a probe copy, Flat OPC out, `docxkit compare` against the
clean edit. The paper's `accept.py` must not be used on such a round's residue
without pruning emptied cells; the author's Word accept needs nothing.

---

### ~~S2 — `revision build` refuses on a pending BASELINE but is silent on a pending WORKING file, which is the commoner way to the same harm~~ — FIXED 02.09, `a8a0239`
<!-- status: fixed -->

**Fixed 2026-09-02.** `WorkingPending`, raised by `_build.build` before the
staleness check.

**The entry was wrong about one thing, and the truth is worse.** It said nothing
in `build` would have stopped it. Measured before writing the fix: the `drift`
check fires on this state too — a pending working file cannot match a clean
baseline — and raised `StaleBatch`, whose advice is to run `revision baseline`.
`baseline` REFUSES a file carrying a proposal (`test_baseline_refuses_a_
proposal`). The reader was sent into a loop between two gates, each telling
them to do what the other forbids.

That is why the check goes BEFORE the drift check, and why one test pins the
ORDER rather than the behaviour: moving the block after `drift` makes
`StaleBatch` fire again and `test_it_comes_BEFORE_the_staleness_check` fails.
Verified by actually moving it, not assumed.

**Its own class, its own exit code (6), its own switch.** The two states want
opposite advice — a pending BASELINE is cleared by adjudicating and
re-baselining, a pending WORKING file must not be baselined at all until the
author has decided — so `--allow-pending-working` is not a widening of
`--allow-pending-baseline`. One flag for both would be reached for over the
commoner refusal and would silence the rarer one.

The message names BOTH harms, because which one you get depends on which file
was staged as the clean edit and a reader cannot tell that from a message
naming one.

Nine tests in `tests/test_pending_working.py`; reverting `_build.py` fails
five.

`_build.build` reads `tracked.package_counts(package.read_parts(paper.prev))`
and raises `BaselinePending` when the BASELINE still carries revisions. Its
reason is exactly right: "Word Compare rebuilds the redline from ACCEPTED
content, so those would be flattened into plain text and could never be
rejected."

The same harm arrives far more often from the other side. Promote a batch,
have the author not adjudicate it yet, and pick up the next protocol: `prev`
is clean, `working` carries the proposal, and the build runs without a word.
What happens next depends on which file the caller stages as the clean edit:

* from `prev` — the new round is built on the PREVIOUS truth and the pending
  batch is dropped from the redline entirely;
* from `working` — Compare is handed a file with revision marks and flattens
  the pending batch in as accepted, unreviewable text.

Met on `Aging_Well`, 31 August: R75 promoted and awaiting a verdict, the next
protocol picked up in the same session. Nothing in `build` would have stopped
it. `promote`'s `StaleBatch` does catch it afterwards — live and base differ —
but only after a full Word Compare round-trip, and it reports a stale batch
rather than the actual problem, which is an author's open verdict about to be
decided for them.

The check `build` already performs on `prev` belongs on `paper.working` too,
with its own message and its own escape. The two-lane rule elsewhere in this
toolkit is stated as "a file with revision marks is never the clean master,
whatever its mtime"; `build` is where that rule should first bite.

---

### ~~S2 — nothing in docxkit can see prose that renders superscript, and a footnote sat wrong for 20 days because of it~~ — FIXED 02.09, `25e8c67`
<!-- status: fixed -->

**Fixed 2026-09-02.** `styles.raised_prose`, joined to `docxkit lint`'s
ADVISORY tier.

**It lives in `styles` because that is where the question can be asked.** The
entry's own trap — a grep for `w:vertAlign` reports the file clean — is the
argument: the run carries no `vertAlign`, the character style supplies it, and
the cascade has to be resolved before the question exists. `Cascade.resolve`
already answers it and reports the KIND of source, so the rule is one line of
judgement: a run of visible text whose `vertAlign` resolves through a STYLE
rather than the run itself. A run stating its own — `baseline` included — is
deliberate and passes.

**MEASURED over 300 manuscripts, and the measurement set the one exemption.**
Raw, the rule gives 26 findings in 24 documents, and 22 of them are a footnote
marked `*` rather than numbered: it carries the asterisk as literal TEXT in its
first run, wearing `FootnoteReference` on purpose. The discriminator is
POSITION and it is exact — a note definition OPENS with its mark, either
`<w:footnoteRef/>` or that custom text, so run 0 of a note holding no auto mark
IS the mark. A length rule would have been a guess, and would have thrown away
the raised full stop this found at the end of an unrelated footnote.

With it: **4 findings over 300 manuscripts, every one real** — this paper's
sentence in three of its generations, and that stray full stop. Re-measured
through the shipped function rather than the probe; same four.

**Not in `lint.audit_parts`, where it reads.** `lint` and `styles` are siblings
in the layering and may not import each other; `test_layering` said so the
first time this was wired the obvious way. The COMMAND is the layer that may
see both. Advisory and firmly so — Word opens the file, and the toolkit has no
command that clears this.

Fourteen tests in `tests/test_raised_prose.py`, one of which found a real
defect in the first draft: a tracked FORMATTING change nests the superseded
`w:rPr` inside the live one, so a non-greedy `<w:rPr>.*?</w:rPr>` closes on the
snapshot and a `w:rPrChange` cut applied afterwards has nothing left to match —
the historical `rStyle` leaked through and scored. `own_properties` finds the
close by depth, which is what it was written for.

Lifted from the paper's `verify_run_styles.py` minus its two STAR rules, as the
entry asked: a significance star being superscript in its own run is that
paper's house style. The workaround script stays in that paper's `[verify]`
list for them.

**Measured**, Parental_style, 2026-09-01. The author read the page and found
footnote 5 rendered entirely in superscript. Its prose run carried
`<w:rStyle w:val="FootnoteReference"/>` and **no `w:vertAlign` of its own**;
`styles.xml` gives that style `vertAlign=superscript`, so the raising was
inherited. Present since a batch of 2026-08-12/13 — every attic generation
through 08-07 is clean — and passed by every gate in the paper's list on every
round since:

| gate | why it passed |
|---|---|
| `footnotes --check` | reads SIZE only; reported "9 footnote(s), house size 10pt, 0 disagreeing" |
| `lint`, `citations`, `refstyle`, `math` | content-blind to run properties |
| `compare` FORMAT | the footnote's text was REPLACED wholesale in the same batch, so there was no text-matched pair to compare formatting on |

A first-pass grep for `w:vertAlign` also reported the file clean, which is the
trap worth recording: **the check has to resolve the character style through
`styles.xml` before the question can even be asked.**

The same file carried a second instance of the class — one table note stating
its significance stars inline while the paper's other six give each star its
own `vertAlign=superscript` run (426 star runs inside the tables and 18 of 19
outside them already obeyed the rule).

**Suggested fix.** A run-typography check, either as `footnotes --check` gaining
a "no prose wears a raising character style" test or as its own command over
body, footnotes and endnotes. The general rule needs no per-paper knowledge:
outside a note MARK, a run of words inheriting `vertAlign` from its style is a
defect. The star rule is house style and belongs in the paper.

**Workaround in use:** `Parental_style/revision/scripts/verify_run_styles.py`,
now in that paper's `[verify]` list — proved to fail before it was trusted
(2 findings on the truth of 2026-09-01, 0 after the repair, no false positives
across 426 star runs and 9 footnotes). It reads the accepted view so it answers
the same whether `working.docx` is a clean master or a redline. Fit to be
lifted upstream, minus the star rule.

---

### ~~S2 — `refstyle` does not audit the separator between a reference's issue number and its page range~~ — FIXED 02.09, `f08cc3b`
<!-- status: fixed -->

**Fixed 2026-09-02.** `_locator_findings`, a sibling of `_order_findings`
and wired into `audit` beside it.

**The rule is the paper's own majority**, as the entry suggested and for the
reason it gave: journals differ, and a paper consistently writing `40(2), 355`
is following its journal, not making an error. A module preferring the colon
would report a house style as a defect in every such paper. Same rule the
citation grammar learns the `txt`-suffix convention by.

**Both bounds on that majority were MEASURED before anything was written**, and
both had to be there. Over 300 manuscripts: 195 carry a `vol(issue)` locator
and 59 of those lists are mixed — but the mix is two different things. Half
have a "majority" of one or two entries (`ACC1.docx`, "1 of 2 agree"), and a
convention of one entry is not a convention; hence the floor of **8**. A few
run 31 one way and 8 the other — a hand-assembled review holding two
conventions at once — where naming the 8 tells the author their document has
variety, which they know; hence the cap of **2** dissenters.

At the shipped threshold: **24 documents, 25 findings**, and every one is a
real slip on reading. Several are the SAME entry across four and five
generations of one paper — Weber & Luzzi, Singer (2016), Leopold & Leopold —
which is the argument for the rule. Nobody caught them by reading, round after
round. Re-measured THROUGH `audit` rather than through the probe's own copy of
the rule, and the numbers match; on the manuscript this entry is about, it now
prints

    ¶129  locator-sep  the issue takes ":" before the pages here — this
                       entry has ";", and 41 of 42 agree on ":"

Fourteen tests in `tests/test_locator_separator.py`. Five are locator shapes
taken from the corpus (a space before the issue, no space after, a four-digit
issue, a single page, a spaced en-dash), because a locator the pattern cannot
see is not merely a dissenter it cannot report — it silently shrinks the
majority it is judging the others against.

**Measured**, Parental_style, 2026-09-01. An author edit changed one entry's
`6(1):` to `6(1);`:

    Barcellos, S., Carvalho, L., and A. Lleras-Muney. (2014). "Child gender
    and parental investments in India…" American Economic Journal: Applied
    Economics, 6(1); 157-189.

`docxkit refstyle` reports the file clean of everything but a pre-existing
alphabetisation finding: **74 entries, 74 cited, one finding, and that one is
about Doepke's position in the list.** Counting the paper's own practice, 41
of its 42 `volume(issue)` entries use a colon and exactly this one uses a
semicolon, so the convention is unambiguous and the outlier is a slip.

`refstyle` already audits the pieces around it — initials, `(2020).`, "and"
not "&", en-dashes in the page range, alphabetical order, cited-vs-listed —
which is why its silence here reads as approval.

**Suggested fix:** audit the locator as a shape, `vol(issue): first–last`,
and report a separator that disagrees with the file's own majority rather
than with a hard-coded character — journals differ, and a paper that
consistently uses something else is not making an error. Same majority rule
the citation grammar already uses to learn the `txt`-suffix convention.

**Workaround in use:** none; found by reading the ingest's word-diff and
counting the entries by hand.

---

### ~~S2 — `body.prose_props` returns a pPr's INNER content while `body.para(ppr=...)` splices its argument in verbatim, so the obvious composition writes stray children Word silently drops~~ — FIXED 02.09, `37a8496`
<!-- status: fixed -->

**Fixed 2026-09-02.** Three changes, because the shape can arrive from more
than one place, and the entry named all three.

**The pair is symmetric.** `prose_props` returns the pPr WRAPPED, as it always
returned the rPr. The asymmetry was the whole defect: two values documented as
a pair to hand straight to `para`, one carrying its wrapper and one not.

**`para` normalises either spelling.** A caller that already wraps — the paper's
own workaround did — is not punished for it, and every caller written against
the old bare shape now emits valid XML instead of children Word discards.

**`lint` refuses the shape.** That is the check that catches it whatever built
the paragraph, and it is check 1's shape one level down: a child in a container
whose schema has no place for it.

The rule is deliberately NOT the whole schema. `w:rPr` IS legal directly in a
`w:p` — it is the paragraph mark's own run properties, which every tracked
paragraph-mark revision carries — and listing it would fail every redline in
the corpus. MEASURED before shipping: **0 findings over 400 manuscripts**,
which is what a rule about a shape only a builder emits should say about files
Word wrote.

Eight tests in `tests/test_para_props_pairing.py`, and each half fails alone:
reverting `body.py` fails three, reverting `lint.py` fails the fourth. Inline
the check took `lint` from 31 to 34 and `test_complexity_debt` refused the
commit, so it is `_stray_para_props`.

**Measured**, Parental_style, 2026-09-01, building the supplemental-material
file for a submission. `prose_props(title_xml)` returned

    ('<w:spacing w:line="240" w:lineRule="auto"/><w:jc w:val="center"/><w:rPr>…</w:rPr>',
     '<w:rPr><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>')

— the rPr WITH its wrapper, the pPr WITHOUT. `para(run(text, rpr), ppr)`
then wrote `<w:p><w:spacing …/><w:jc w:val="center"/>…<w:r>` — a
paragraph whose "properties" are bare children of `w:p`. `lint` passed
it, Word opened it, and the four title-block paragraphs rendered
LEFT-aligned at 16pt: Word keeps the run properties and discards the
schema-invalid children without a word. Found only by rasterising the
PDF and looking; a grep for `<w:p>(?!<w:pPr>)<w:(spacing|jc|ind)` on the
built file then counted 4.

The two functions are documented as a pair (the skill's own example is
`para(run(...), ppr=caption_ppr)` with the ppr "ideally cloned off an
existing paragraph") and their shapes disagree. Either `prose_props`
should return the wrapped `<w:pPr>…</w:pPr>` (symmetry with its rPr),
or `para` should wrap an unwrapped `ppr` — and `lint` should refuse a
`w:p` whose first child is a pPr-only element.

Workaround in use: `_wrapped_ppr()` in
`Parental_style/revision/scripts/split_supplement.py`.

---

### ~~S1 — `citations` reports neither an unlinked mention inside a FOOTNOTE nor a reference entry with no back-link, and both were live in the same manuscript~~ — FIXED 02.09, `5f95d77`
<!-- status: fixed -->

**Fixed 2026-09-02**, both halves.

**The mention scan reads the notes.** `_read_notes` had folded their bookmarks
and links in since 2026-08-20, so a work cited only in a footnote resolved and
reported correctly — the MENTION was the one thing still stopping at
`document.xml`, which is why `Mentions: 103 of 103 linked` printed identically
before and after the link was made. `_mention_scan` now yields the body before
the reference list and then both note stores, with `_NOTE_AT`'s sentinel as the
index so a finding says "fn" rather than a paragraph number a reader would hunt
for in the body.

**An entry with no link home is reported.** `_no_backlink` asks it of the
list's own MAJORITY rather than by a rule, because whether entries link home at
all is the paper's house style: one entry differing from 86 others is a
finding, and 87 agreeing that they do not is a convention. Keys already
reported as uncited are skipped — an entry nobody cites has a reason to have no
back-link, and saying it twice is the noise this module's own comments warn
about.

MEASURED over 100 manuscripts before it shipped: **2 findings in 1 document**,
and both are real — two FLOPS entries (`BenzJaax2020`, `NVIDIA2024`) whose
`txt` markers exist nowhere in the file. The sibling rule this is closest to
fired 5,378 times across 718 of 1,873 manuscripts before it was narrowed, which
is why an audit rule is measured rather than argued.

Both new checks were lifted OUT of `_audit_findings` rather than added to it.
Inline they took the worst function in the package from 31 to 35, and
`test_complexity_debt` refused the commit; `_mention_scan` and `_no_backlink`
are their own functions and it is back under its pin.

Seven tests in `tests/test_cite_notes_and_backlinks.py`, including the one that
keeps the majority rule honest: a list where NO entry links home reports
nothing.

Two blind spots in the same gate, both measured on `Aging_Well` on 31 August
and 1 September. Each leaves the gate exiting 0 with a clean-looking count
while the house convention it exists to protect is broken.

**1. An unlinked mention in a footnote is not reported.** A round added
`(World Bank 2026)` to footnote 2 as plain text — verified: no hyperlink in
the paragraph, no `WorldBank2026` bookmark anywhere. `citations` exited 0 and
printed `Mentions: 103 of 103 linked`. After `r2` linked it, the count was
still `103 of 103`. So the counter reads the BODY only: the mention was never
in the denominator, which is why its being unlinked could not be reported.
The same round's three new BODY mentions were reported correctly, so the gap
is the part, not the case. On this manuscript six works are cited only in
footnotes.

**2. A reference entry with no back-link is not reported.** The `<key>txt`
convention is bidirectional — the mention links to the entry, the entry links
home to the first mention. One entry of 87 had lost its `Lokshin2022txt`
bookmark; the entry pointed at a name that did not exist, `remint_backlinks`
removed the dead link, and the entry sat with nothing pointing home. `citations`
exited 0 every time.

The second is worse than a missed report because it is SELF-PERPETUATING and
silent. `link_all` skips a mention that already carries a forward link, so the
`<key>txt` bookmark is never re-minted; `remint_backlinks` then finds the
target missing and removes the back-link again. The paper printed the same
warning at three consecutive close-outs and passed its gates every time. The
warning is `r2`'s, not the gate's, and it reads like a note rather than a
finding.

Both belong in `citations`'s audit: count mentions in footnotes and endnotes as
well as the body, and report an entry whose back-link target does not resolve —
or which has no back-link at all where the rest of the list does. The second
check is cheap: the convention is visible in the list's own consistency, and a
single entry differing from 86 others is exactly what a gate should notice.

Per-paper workaround while this is open:
`Aging_Well/revision/scripts/r77_lokshin_backlink.py`, which rebuilds the
bookmark with `_cite_repair.wrap_link_in_bookmark` and is idempotent.

---

### ~~S1 — `promote` prunes the rescue copy it has just written, whenever the rescue folder also holds a hand-named rescue~~ — FIXED 02.09, `70e1868`
<!-- status: fixed -->

**Fixed 2026-09-02.** Three causes, all three fixed, and the entry named
all three.

**The sort.** `_written_at` orders by the parsed stamp where there is one and
by mtime where there is not. The stamp is preferred because an mtime is
rewritten by a copy and these folders sit on a sync drive; the mtime only ever
orders a LISTING and never decides a deletion.

**The scope.** Only copies matching the stamp are deletable. A hand-named
rescue is somebody's deliberate undo, and the papers had been working around
this by renaming theirs `working_keep_` so the glob would miss them — a rename
to dodge a deletion.

**The invariant.** `promote` passes the rescue it has just written as
`protect`, and it is never deleted whatever else the folder holds. That one
would have prevented both incidents alone.

The hand-named copies still COUNT toward `keep`: five undos in a folder is five
undos whoever wrote them, and thinning the stamped ones to make room would be
this function deciding which of the author's copies matter.

Six tests in `tests/test_rescue_pruning.py`, and the revert check is the part
worth reading. Reverting the sort alone left all six GREEN, because the first
version of the sort test asserted `order[0] == STAMPED` — which is the DEFECT:
`rescues` answers oldest-first and the stamped copy in that fixture is the
newest. A test written against the bug it was meant to catch. It now pins the
newest copy sorting last, and each half of the fix fails it alone.

**Measured**, Aging_Well, 2026-08-31 23:57. `revision promote` reported

    rescue copy of the previous live file: revision\build\rescue\working_rescue_20260831-235728-542622.docx
    pruned 3 older rescue(s), keeping 5

and the file it names in the first line **was not there afterwards**. The undo
for that promote had to come from another session's `working_rescue_20260901_pre_POL.docx`
instead. Three further rescues went with it; they are not recoverable from the
working tree.

**Diagnosis.** `_promote.rescues()` globs `*_rescue_*` and returns
`sorted(...)`, and its docstring states the assumption out loud: *"the copies
are stamped rather than numbered, so sorting them as strings sorts them
chronologically."* True of names this module writes — `_RESCUE_STAMP` is
`%Y%m%d-%H%M%S-%f`, uniform width. But the glob is `*_rescue_*`, which also
catches the hand-named rescues the papers' own scripts and sessions write, and
then the sort is wrong at the separator: `-` is 0x2D and `_` is 0x5F, so

    working_rescue_20260831-235728-542622.docx   <- 23:57, the newest
    working_rescue_20260831_pre_COMP.docx        <- 18:44
    working_rescue_20260831_pre_REF2.docx        <- 21:51

sorts the newest file FIRST, i.e. as the oldest, and `prune_rescues`'
`rescues(paper)[:-limit]` puts it in the doomed slice. The count printed is
right and the files deleted are the wrong ones, which is why nothing looks
amiss.

Same family as the `-2` collision suffix that inverted this order once before
(fixed by making the stamps uniform width); what is new is that uniform width
is not enough while the folder is shared with names the tool did not write.

**Suggested fix**, cheapest first:

* **never delete the rescue this promote just wrote** — pass it to
  `prune_rescues` as protected. That is the invariant that actually matters: a
  promote must not destroy its own undo, whatever else the folder holds;
* prune only names matching `_RESCUE_STAMP`, and leave anything else alone — a
  file the tool did not write is not the tool's to delete;
* sort by the parsed stamp rather than by the string, so a mixed folder still
  lists chronologically for `revision rescues`.

**Workaround in use:** none available at the time — the copy was already gone.
Recovery came from a differently-named rescue that happened to exist.

**Measured again**, Aging_Well R78, 2026-09-01 21:01. `promote` reported
`working_rescue_20260901-210134-674000.docx` and *pruned 4 older rescue(s), keeping
5*; the five kept were all hand-named (`working_rescue_20260901_pre_DF1/pre_POL/
post_POL_accept/pre_R77/pre_S1.docx`) and the stamped file it had just written was
among the four deleted. Undo existed only because the session had copied
`working_rescue_20260901_pre_S1.docx` by hand first (same bytes as `prev.docx`).
**Workaround from that paper:** hand-named copies take a `working_keep_` prefix,
which the `*_rescue_*` glob does not match; the stamped rescue's presence is
checked after every promote.

---

### ~~S4 — no public way to unwrap a link by ANCHOR in both forms; `crossrefs.unlink` refuses field form and `unlink` by name does not exist~~ — FIXED 02.09, `66b58dc`
<!-- status: fixed -->

**Fixed 2026-09-02**, in two halves, and the second is the one the entry
asked for.

`edit.remove_link(para, anchor)` is the unit: one link, by anchor, in whichever
form the last save left, keeping the words and returning the label they showed.
`edit.remove_links(xml, keep=…)` is the sweep this entry describes — unwrap
every internal link whose anchor is not in a set of names, in document order,
reporting what went.

**Built on `edit._label_spans`, which had been reading both forms all along.**
That is the finding worth keeping: the two-form scan the entry says "does the
reading" was not only in `_xml.field_spans` + `INSTR_ANCHOR_RE`, it was already
assembled, behind an underscore, and `relabel_link` had used it since it was
written. What it did not expose is the OUTER span, and a field needs one — a
field is four runs and `_FIELD_RE` matches between the first and last fldChar,
INSIDE the runs holding them, so cutting at the match leaves two empty `w:r`
shells around the words. `_links_to` returns label and outer together now and
`_label_spans` is three lines over it, so relabelling and removing cannot
disagree about what a link IS. Disagreeing is how two papers came to re-derive
the scan privately — `_unwrap_wide` in Aging_Well (38 lines) and
`unlink_absent` in Parental_style (~30).

MEASURED over 120 manuscripts before the sweep was added, and the number
settles the design: **9,728 internal links, 7,317 of them FIELD form** — three
quarters are the shape `crossrefs.unlink` raises `ConversionGap` on rather than
touch. 9,595 removed cleanly against three invariants (the words survive, the
anchor stops resolving, nothing else moves), 133 refused as ambiguous, zero
problems. Re-measured after: 6,780 links over 80 documents, same result.

Two decisions inside it, both from the entry's own evidence:

* the sweep touches NO bookmark, unlike `remove_link`'s default. The anchors it
  unwraps are ones being kept somewhere else, so deleting their in-text twins
  would take the targets with the links;
* the `keep` set is the CALLER's to build, and the docstring says why in the
  entry's words: eleven `<key>txt` markers live in `footnotes.xml`, and a name
  set read from `document.xml` alone declared those eleven back-links dangling.
  `package.text_parts` is the iteration that gets it right.

What is NOT done: `crossrefs.unlink` still refuses field form. It can be built
on `_links_to` now, and its refusal names the reason it should be —
"24 removed" over a document whose caption links were all still live.

Per-paper workarounds left in place deliberately: both are in scripts that have
run, and the papers are mid-round. Retiring them is a paper-side change for
when each is next touched.


Splitting a manuscript into a main file and a supplemental file
(Parental_style, 2026-09-01) leaves links whose bookmark is now in the
OTHER file: main-text mentions pointing at appendix captions, caption
back-links pointing at their first mentions, a citation link inside a
table note. What was needed: "for every internal link whose target is
not among these bookmark names, keep the words, remove the link and its
Hyperlink style / underline / colour" — both element and field form,
across document AND footnotes (eleven `<key>txt` markers live in
footnotes here, and a name set read from the body alone declared their
back-links dangling).

`crossrefs.unlink` is the nearest thing and raises `ConversionGap` on
field form by design; `_xml.field_spans` + `INSTR_ANCHOR_RE` do the
reading but nothing does the unwrapping. Hand-rolled as
`unlink_absent(xml, names)` (~30 lines) in
`Parental_style/revision/scripts/split_supplement.py`; the same need
will recur for every journal that wants appendices as a separate
supplemental file. Suggested: `links.unwrap(xml, anchors=…)` or
`unlink_absent(parts)` next to `_xml.dead_links`, with the freed runs'
link styling stripped.

---

### ~~S3 — `tools/sweep.py` exits 1 forever on one corrupt corpus file, and a gate that cannot go green is one people stop running~~ — FIXED 01.09, `c2d1b1a`
<!-- status: fixed -->

**Fixed 2026-09-01.** `SPI_Case-Ezhik-PC.docx` — a 2021 file with a zip
header and no central directory — raised `BadZipFile` on open, and the sweep
counted that as a FAILED routine. Every run that reached the file exited 1,
whatever the other 299 documents said. By this file's own scale that outranks
a wrong answer nobody sees: a gate that cannot go green is one people stop
reading.

`BadZipFile` on open is now SKIPPED, and only that exception. A
`PermissionError` or a raise from inside docxkit is still a failure — skipping
`OSError` wholesale would have swallowed the locked-file case the sweep exists
to exercise, which is the trap in every skip path.

Counted and named, on the SAME line as the sweep count: `SWEPT 29 documents,
SKIPPED 1 not a document`. A skip that does not say how many it skipped is the
S3 shape arriving by the other door — "swept 300, skipped 1" and "swept 1,
skipped 300" must not read alike.

Measured over the folder that holds the file: 29 swept, 1 skipped, exit 0; and
over 80 documents of the wider corpus, 0 failures.

Found by the 2026-09-01 structural review rather than by a round, which is why
there was never an open entry.

---

### ~~S4 — the public API promised 626 names and the papers used 86, so an internal rename cost a release~~ — FIXED 01.09, `c2d1b1a`
<!-- status: fixed -->

**Fixed 2026-09-01**, and it is the `api` gate's second calibration rather
than a defect in the package.

`api_check` (`eac1053`, 31.08) guards the public surface against the last
release. It guarded all of it: 626 names across 35 modules, every one strict.
The papers — 274 scripts across nine manuscripts — import **128** of them
(2026-09-01). So renaming a parameter in a name nothing calls failed the gate
exactly as hard as breaking `read_parts`, and a gate that costs a release for
an internal rename is one people learn to push past. That is the same failure
the ADVISORY split was introduced to avoid, along the other axis.

`tools/consumers.py` walks the papers for every `from docxkit… import …` and
writes a COMMITTED snapshot; `api_check` reads it as the strict tier. A
breakage in a consumed name fails, the same breakage elsewhere prints
`unused`. Derived from the papers rather than chosen, so nothing a paper uses
can be classed advisory by an oversight.

**Resolved through griffe's aliases**, which was the part that had to be got
right: a paper imports `docxkit.tables.house` and griffe reports the breakage
at `docxkit._table_core.house`, where the function is defined. Matching the
strings as written would have put every facade name in the advisory tier —
which is most of the package, and exactly the names a paper calls.

Proved by breaking both ends: `edit.replace_in_para` losing a parameter exits
1, `footnotes.orphans` losing one exits 0.

The snapshot's second reader is `tests/test_consumers.py`: every recorded
import must still resolve, and the 20 that reach through a private path are
pinned as a set that may only SHRINK. Four `_xml` names were promoted to
`docxkit` in the same commit for that reason — `visible_text`, `DOCUMENT`,
`PARA_RE`, `RUN_RE`, which the papers import 103 times between them.

---

### ~~S4 — `import docxkit` paid ~9 ms for lxml against a docstring saying it must not, and nothing checked~~ — FIXED 31.08, `817e2f7`
<!-- status: fixed -->

**Fixed 2026-08-31.** `package.py` had `from lxml import etree` at module
level, and `package` is what `import docxkit` reaches — so every command the
CLI runs and every paper script that imports the toolkit at all parsed lxml
first. Measured in a fresh interpreter: **53.7 ms -> 43.3 ms** for `import
docxkit`, and **55.4 -> 43.5** for `docxkit.cli`, which is the one paid per
invocation.

`tests/test_layering.py` states the invariant — *"`import docxkit` must not
pay for lxml, pandas, pywin32 or the comparison's chain, which is why several
modules import inside their functions"* — and asserted the layering while the
sentence about what the layering BUYS went unchecked. pandas and pywin32 were
clean; lxml was not.

**The deferral was already written.** `malformed_parts` imports lxml inside
the function, four hundred lines below the module-level import that made it
pointless. An intention recorded in one place and contradicted in another,
where no test looked — which is the same shape as the `*.py` glob note in
`BACKLOG.md`, and the reason this is filed rather than just fixed.

`tests/test_import_cost.py` asks the question in a SUBPROCESS, which is the
only place it can be asked: by the time pytest runs, lxml and pandas are in
`sys.modules` because other tests imported them, so an in-process check
passes whatever the package does. Four tests — no third-party parser behind
`import docxkit` or `docxkit.cli`, the base chain pinned to its seven modules,
and one that asks the probe about a module that genuinely DOES import lxml,
because every other assertion is a negative and a broken probe reports those
as absent.

S4: nothing was wrong on the page, and no answer was affected. It is startup
cost and a false sentence in a docstring — but the false sentence is what
makes it worth a record, because the next person to read it would have
believed it.

---

### ~~S4 — `link` and `linkfix` still refused a Word lock two months after their five siblings learned to fall back~~ — FIXED 31.08, `eac1053`
<!-- status: fixed -->

**Fixed 2026-08-31**, and filed at the same time: it was found by the gate
that closes it rather than by a round, so there was never an open entry.

`cmd_link` read `_package(args.docx)` unconditionally, so the DRY run — a
report about what it WOULD do, which is what `link` does by default — needed
the file to itself. `cmd_linkfix`, whose own docstring says "a plan for a
human to review, never an edit", did the same. Both now take `read_only` the
way `authors` and `tasks` already did: `not args.write` for `link`, always
for `linkfix`.

**S4 rather than S1**, and the difference is worth stating because the
`citations` entry above it is an S1. That one printed the snapshot banner —
a promise that a result follows — and then refused underneath it. These two
refuse cleanly, with the message the lock deserves, so nothing is silent and
nothing is wrong: the cost is that a report about a manuscript cannot be run
while the author has the manuscript open, which is the normal state during
adjudication and exactly when someone asks what the apparatus looks like.

**The second finding is the one worth keeping.** `95024d9` fixed the
`citations` family and its entry lists what it checked — `count`, `tasks`,
`smarten`, `compare`, `figures`, `fit`, `sites`, and the four that drive
Word. `link` and `linkfix` appear nowhere in that list, and the parametrised
sweep written the same day to stop this recurring covered 15 of the CLI's 25
commands. **A hand-written list of things to sweep is a list that stops
covering what it does not remember**, which is the `*.py` glob note's lesson
arriving in a test rather than in a tool.

So the fix is the sweep as much as the two lines: the command list is derived
from `cli.build_parser()` now, every command is either swept or exempt with a
reason, the two lists may not overlap, and the write forms are swept against
the other half of the contract. Six of those, where one hand-written case had
stood for all of them. See the workflow note in `BACKLOG.md`, whose first
proposed gate this is.

---

### ~~S1 — the XML accept leaves a DELETED footnote's definition in the part, so `tracked.build` refuses a redline that is actually correct~~ — FIXED 31.08, `39fe472`
<!-- status: fixed -->

**Fixed 2026-08-31.** `tracked._simulate` prunes the shells, on BOTH views — a note the batch ADDS leaves the same shell on the reject side, where `untracked` is the gate that decides whether the author's veto is real. The reader is `footnotes.orphans`, and it looks in every part for references rather than the body alone: a running head can carry one, and a definition pruned because `document.xml` went quiet about it takes a note the page still shows.

"Empty" means no text AND no carriers. A definition holding a bookmark, a link, a drawing, a table or an equation is not litter — dropping it loses an anchor no text comparison can see go — so `Orphan.empty` counts those too, and `prune_orphans` leaves it.

The other half of the entry is kept: an unreferenced definition WITH words in it is a footnote that lost its marker, and `_refuse_accept_side` now refuses on it separately, saying the note is in the file and on no page. Measured against the clean copy rather than reported outright, because a manuscript that already carries one is not this build's doing.

Eleven tests in `tests/test_note_orphans.py`; the two that matter reproduce the entry's `'' vs ''` exactly against the old code.

The paper's workaround is retired: `Aging_Well/revision/scripts/accept.py` was 40 lines of its own and now calls `footnotes.prune_orphans`, keeping its report of a non-empty orphan.

Measured on `Aging_Well`, 31 August, with a two-revision repro: take the
truth, delete footnote 4's reference run and its definition, change
nothing else, build.

    docxkit revision build revision/build/edited.docx --keep-math
      revisions: 2
      accepting every revision does NOT reproduce edited.docx -
        1 paragraph(s) differ
        footnotes P6: intended ''
                    accepted ''
      exit 1

**Word's redline is right.** The reference sits inside a `w:del` and the
definition holds its text as `w:delText`, which is exactly how Word itself
represents a deleted footnote, and Word's own accept then removes the
definition. `revisions.accept` works part by part: it empties the note and
cannot see that the reference is gone, so the accepted view keeps an empty
definition and has one footnote more than the document the redline was
built from. `_refuse_accept_side` reads that as Word having rewritten
content and refuses.

The refusal is S1 rather than S4 because of what it says: "Word rewriting
content while it derives the redline is the usual cause", and the printed
evidence is `'' vs ''` — two empty strings, which look identical. A reader
following that sentence looks for a Compare defect in the body and finds
nothing.

On the full compression round it produced four shells, one per footnote
whose marker the batch deletes or moves (the deleted note, and the markers
of three notes whose surrounding sentences were rewritten). Everything a
reader sees is correct on both sides: accepted 14 markers, exactly the
clean copy's; rejected 12, exactly the baseline's; no paragraph carries two.

**The fix is in `revisions.accept`'s caller, not in `accept` itself** —
`accept(xml)` takes one part and cannot know about references in another.
Either `tracked`/`revision` prune footnote and endnote definitions left
unreferenced after a whole-package accept, or `_refuse_accept_side`
discounts an unreferenced empty definition before it compares. Prune only
EMPTY orphans: an unreferenced definition WITH words in it is a lost
footnote and should be reported.

Workaround in the paper: `Aging_Well/revision/scripts/accept.py` grew
`prune_orphan_notes`, which does exactly that and prints any non-empty
orphan rather than removing it.

---

### ~~S2 — `word.compare_documents` hard-codes `CompareMoves=True`, and Word's move detection can silently truncate a paragraph in the accepted view~~ — FIXED 31.08, `39fe472`
<!-- status: fixed -->

**Fixed 2026-08-31.** `moves` is threaded through `word.compare_documents`, `tracked.build`, `revision.build` and `docxkit revision build --no-moves`. Default ON: off by default would turn every relocation into a deletion plus an insertion for every paper, to spare the one that measured a bad move. It is the answer to a refusal, not the setting to start from — which is why the STRUCTURE refusal and the accept-side one both name it now.

`CompareMoves` came out of `test_the_comparison_flags_that_must_not_vary_do_not`. It is not that kind of flag: the others decide what Word LOOKS at, and move detection decides how it EXPLAINS what it found. Pinning it there read as "a move is always shown" and meant "a round that moves a passage cannot be built".

The entry's other half — that the refusal points at the link rather than at the missing sentence — is fixed with it. `_also_unaccepted` puts the paragraphs into the anchor refusal when there are any, says they are the finding to read first, and names `--no-moves`. An anchor does not go missing on its own; it goes with the words that carried it.

Measured on `Aging_Well`, 31 August. The batch relocates about 200
characters of prose and five inline `m:oMath` objects out of Section 5.1
and into Appendix A.2 — a genuine move, and Word scores it as one.

With `CompareMoves=True` the redline's ACCEPTED view reads

    ... measured in units of that floor: z_ij=... . The floor itself is
    set weakly relatively -

and stops. The rest of the sentence is gone: the `(Appendix A.2;` clause,
the `Ravallion and Chen 2011` hyperlink, and `One setting is taken as
given throughout what follows, and s is suppressed.` The build refuses,
correctly, but it refuses with `link LOST on accept: -> Ravallion2011`,
which points at the link rather than at the missing sentence.

With `CompareMoves=False` and nothing else changed, the same pair produces
the paragraph exactly. `compare_documents` already exposes `whitespace`
and `formatting` "because they change the deliverable, not just its
speed"; `moves` belongs beside them, and `revision build` should have a
flag. A round that MOVES a passage — which is most of what a compression
round is — cannot currently be built through the CLI at all.

---

### ~~S2 — `compare` has NO view of paragraph properties: an indent or a spacing change is invisible at every layer, and `--expect-clean` prints OK~~ — FIXED 31.08, `39fe472`
<!-- status: fixed -->

**Fixed 2026-08-31.** A PARAGRAPH layer beside FORMAT, in `GATED` — a layer that reported and did not gate would have printed the same `EXPECT-CLEAN OK` over the seven reference entries. Resolved through the style cascade, which needed a resolver the `Cascade` did not have: `_val` reads `w:val`, and an indent states four numbers while `keepNext` states none and means yes. `Cascade.para_element` answers for presence and `Cascade.para_attr` for the numbers.

**Per ATTRIBUTE, not per element**, and that was measured rather than reasoned: Word merges `w:ind` and `w:spacing` attribute by attribute, so a paragraph stating only `w:before` keeps its style's `after` and `line`. Element-level resolution reported a difference between two identical pages on the first pair that tried it.

`numPr` is deliberately out. Word mints fresh `numId`s on a rebuild, so the same list would compare as `numbering 3 -> 7` on any pair that went through Compare — the "measure a check before writing it" rule, applied before the layer shipped rather than after.

**Measured over 40 real version pairs** from the corpus: 328 paragraph entries against 6,888 structure and 4,112 text, and **zero pairs whose only gated difference is this layer**. It never reddens a comparison on its own, and every entry spot-checked was real.

That measurement found a reading defect underneath it, now fixed with it. `_compare_read.P_RE` was `<w:p[ >].*?</w:p>`, which `_xml` recorded as having the self-closing guard "by accident of spelling" and being "the only walk that was right". **It did not and it was not**: `[ >]` excludes the bare `<w:p/>` that the 2026-08-11 measurement looked for, and not `<w:p w14:paraId="…"/>`, which is the form Word writes. The walk swallowed the empty paragraph together with the real one after it, so the real paragraph read as stating no properties of its own — a false difference on LI5 against LI6, whose "References" headings carry byte-identical `w:pPr`. `P_RE` is `_xml.PARA_RE` now and the comment there is corrected. Before the layer existed the same merge silently mis-assigned the table-cell address and the run walk, which is why it survived: an empty paragraph contributes no text, so every text assertion passed.

Sixteen tests in `tests/test_compare_paragraph.py`, over half of them about NOT crying wolf. The report's bucket list is stated once now (`compare.BUCKETS`) — it was stated twice, and the new layer passed every renderer test in `test_compare.py` while raising `KeyError` on the first real report.

`_flags` reads run properties and `_VALUED` resolves size and colour, both
per RUN. Nothing reads `w:pPr`. So a whole class of edit — indentation,
spacing, alignment, keep-with-next — passes every layer silently.

Measured 2026-08-29 on Life_Expectancy's round-1 response letter. A
classifier bug in the paper's typesetting script gave **7 reference entries
body spacing instead of a hanging indent**:

    A (shipped)   spacing=(0, 60, 240)   ind=(left 360, hanging 360)
    B (rebuilt)   spacing=(0, 120, 240)  ind=None

and on that pair:

    docxkit compare A B --expect-clean
    REAL change locations (excl. glyph): 0
    EXPECT-CLEAN OK: build matches the user's content

Seven paragraphs of a reference list lost their hanging indent and the gate
said the documents match. Not S1 only because compare does not CLAIM to
compare paragraph properties — but `--expect-clean` is used as "nothing
changed", and for any formatting pass it is the only gate there is, which is
how the same class of blindness in run size and colour got fixed on
2026-08-10 (see the `_VALUED` note in `_compare_read`).

Fix shape: a PARAGRAPH layer beside FORMAT, resolved through the style
cascade the way size and colour are — Word deletes a pPr value equal to the
inherited one, so comparing what is STATED reports differences on documents
that render identically. Report it under its own heading so a deliberate
typesetting pass can be read and dismissed. Worth pairing with the render
gate the note below asks for: an indent is a thing you can see.

---

### ~~S2 — `revision baseline` computes its log verdict against whatever `build/batch.docx` happens to be, including a batch that was never promoted, and writes the wrong sentence into the paper's permanent log~~ — FIXED 31.08, `39fe472`
<!-- status: fixed -->

**Fixed 2026-08-31**, fix shape 1 of the two the entry asked for. `_verdict._proposal` already established that the batch was built on the current baseline; what it could not ask is whether the batch ever REACHED the manuscript. The two are invisible in the files — a batch rejected in full and a batch never promoted leave the manuscript in exactly the same state — so the record has to answer it.

`promote` copies the batch into `build/redlines/` and verifies the hash before it overwrites the paper, and that copy is the only evidence a batch was put on. `_promoted` looks for a redline with the batch's bytes (size first, hash only for a file that could match); without one, `_proposal` returns None and the outcome is `adjudicated (no batch to compare against)` — the string the code already had for exactly this case.

The listing moved onto `Paper.redlines`, because `_verdict` sits below `_promote` in the subpackage order and a second glob would be a second answer to where the redlines are. `redlines()` is unchanged for its callers.

`Verdict.apparatus_only` gets its caveat retired with it: a linking pass run in place while a valid batch sat unpromoted used to be reported as an adjudication of a batch nobody acted on.

Three tests, one of which is the entry's own: baseline a file whose `build/batch.docx` was never promoted and assert the outcome is not `rejected in full`. Another covers the case the folder makes ordinary — it is never pruned, so by round five it holds five redlines and none of them need be this one.

The per-paper workaround the entry names — renaming an unpromoted batch to `batch_x-collision_DISCARDED.docx` — is not deleted, because it sits in a COMPLETED protocol note (`Aging_Well/revision/notes/protocol_major2_082826.md`, P3, ticked 28 August) and that is a record of a round already run. Rewriting it would falsify the record. Nothing standing instructs the rename any more.

`RevisionOutcome.outcome` (`src/docxkit/revision.py`) turns kept/reverted/
offered into "the words a log row wants", and `revision baseline` prints that
row ready to paste. The counts come from comparing the live file against
`self.batch` — and nothing establishes that `self.batch` is the batch the
manuscript actually grew out of.

**Measured on `Aging_Well`, twice on 28–29 August.**

*Case 1, the clear one.* `build/batch.docx` held the Major 2 build that had
been **deliberately NOT promoted** — held back because it named a symbol the
paper already used. The author's own Word round was then ingested, two
untracked repairs ran (r22 for the flattened glyphs, r60 for a symbol typed as
text), and `revision baseline` logged:

    | 2026-08-28 | batch | 1 ¶ changed, from 304 revisions (197 ins, 107 del) | — | rejected in full, +2 authored → truth |

Nothing had been rejected, and there had been no batch to reject: the round was
an author handback plus repairs. The verdict is an artifact of measuring
against a batch that never reached the manuscript. Its revisions are absent
from the file for the obvious reason, and absence reads as rejection.

*Case 2, same shape, opposite error.* The next round WAS adjudicated, and the
author rejected a whole block of it (a display in the wrong section). The row
read `accepted in full, +1 authored`. I did not isolate the mechanism there, so
this one is reported as an observation rather than a diagnosis — but the two
together are the reason this is worth fixing rather than remembering.

**Why S2 and not S4.** The row is not a screen message. It is pre-formatted for
`revision/log.md`, which is the paper's permanent record and the first thing
the next session reads — this project's own convention is "read `log.md`
first". A confident, wrong outcome sentence there is a wrong answer no gate
sees, and it has to be hand-corrected by whoever notices. On this paper it has
been hand-corrected three times.

**Fix shape, in order of preference.**

1. **Refuse to render a verdict when the batch cannot be shown to be the
   file's parent.** `revision build` already writes `batch.docx.buildinfo.json`
   and `promote` already checks a hash; `baseline` can ask the same question.
   If the batch was never promoted, or its baseline hash does not match
   `prev.docx`, emit `adjudicated (no batch to compare against)` — the string
   the code already has for exactly this case — instead of inferring.
2. Failing that, name the uncertainty in the row rather than resolving it:
   `verdict not established (batch.docx was not promoted from this baseline)`.

A test that fails without the fix: baseline a file whose `build/batch.docx`
carries revisions that were never promoted, and assert the outcome is not
`rejected in full`.

**Related, and the reason this was noticed at all:** a protocol on this paper
now instructs its agent to rename an unpromoted batch to
`batch_x-collision_DISCARDED.docx` "so it cannot be promoted by accident". It
also cannot poison the verdict once renamed — which is a per-paper workaround
for a toolkit behaviour, and the kind this file exists to retire.

---

### ~~S4 — `revision status` silently drops the drift check on a locked file, so a STALE baseline reads as a current one~~ — FIXED 31.08, `39fe472`
<!-- status: fixed -->

**Fixed 2026-08-31**, in the words the entry proposed. `cmd_revision_status` asks whether the working state came from a snapshot and, when it did, prints what was not checked instead of calling `drift` at all:

    drift     NOT CHECKED - the file is open in Word and this comparison
              needs its saved bytes. The counts above are the snapshot's and
              are right; whether prev.docx is still the baseline this paper
              grew out of is unknown. Close the file and re-run.

Exit 1 — what the lock produced before, since `DocumentLocked` is a plain `DocxKitError` and `main` exits 1 on one — so nothing gating on this command changes its mind. What changed is that the reader is told which question went unanswered instead of inferring a clean baseline from a warning that did not appear. The `--help` line says `exit 1 pending or unchecked`.

Two tests: the locked run names the unchecked comparison, and the same two files with the file closed still exit 4 on the stale baseline, so the lock branch cannot buy its silence by disabling the check for everyone.

Measured on `Aging_Well`, 30 August, on one pair of files minutes apart.

**Locked** (the author had `working.docx` open in Word):

    docxkit: working.docx is locked (open in Word). Close it and retry.
      read from a SNAPSHOT: … describes the moment the copy was taken …
      working   0 pending -> TRUTH
      prev      0 pending -> TRUTH
    exit 1

**The same two files, after the file was closed, nothing else changed:**

    working   0 pending -> TRUTH
    prev      0 pending -> TRUTH

      ** baseline STALE: word/ (8 parts) differ(s) **
    exit 4

The pending counts are answered from the snapshot and are right. The DRIFT
check — `revision.drift`, the thing exit 4 exists for — is skipped, and its
absence is not stated. What the locked output says is "both sides settled",
which is exactly the shape of a healthy, current baseline.

**Why S4 and not S2.** The damage is bounded: `revision build` re-checks the
baseline and refuses with *prev.docx is no longer what working.docx grew out
of*, which is where this actually surfaced during a round. So nothing wrong
gets built. The cost is that `status` is the command people run to ask "where
am I", and under a lock it answers a narrower question than it appears to —
after an author has just accepted a batch, "TRUTH / TRUTH" with no warning is
the wrong impression to leave.

**Fix shape.** Say what was not checked. The snapshot banner already exists and
already explains that the read is of the last save; one more line in the same
register would do it:

    drift    not checked — the file is open; close it and re-run for the
             baseline comparison

The counts stay useful, and the reader is not left to infer a clean baseline
from a missing warning. Same family as the `citations`-on-a-lock entry fixed in
`95024d9`: a command answering from a snapshot has to say which of its answers
the snapshot could not supply.

A test that fails without it: lock a file whose `prev.docx` differs, run
`status`, and assert the output names the unchecked comparison.

---

### ~~S1 — `[batch] carry` restored a footer beside the one Compare RE-TYPED, so the section got two `default` footers and the promoted manuscript printed its page number twice~~ — FIXED 30.08, `d83444b`
<!-- status: fixed -->

**Fixed 2026-08-30.** `_restore_section_references` reconciles the section against the baseline's type -> part map instead of appending beside what Compare left. A stale reference of the same kind and type is moved to the type the BASELINE gives its part; one the baseline does not place in that section at all is dropped, because it is a reference Compare invented. Idempotent, so `carry` stays safe to leave on.

Four tests in `test_parts_gaps.py`, three of which fail against the old code with the measured symptom — `footer1: default, footer2: default`. The build's misleading line went too: it said the carried part "is not referenced from the body", which is true of the data store and false of the two parts where it matters.

`carry` puts a dropped part back "with its content type, a relationship on an
id free in the target, and — for a header or footer — the section reference
that puts it on the page". It restores the reference with the type the
BASELINE gave that part, and does not look at what the section already has.

Word's Compare does not only drop parts: it RE-TYPES the one it keeps.
Measured 2026-08-29 on Life_Expectancy's round-2 batch —

    baseline   f:even=footer1  f:default=footer2  f:first=footer3
    batch      f:default=footer1  f:default=footer2  f:first=footer3
                        ^ Compare re-typed it     ^ carry restored it

`footer1` is the paper's *even* footer (inert: `evenAndOddHeaders` is not
set, so nothing rendered it). Compare kept it and called it `default`; carry
then restored `footer2` — the real default footer, the one holding the
`PAGE` field — as a **second** `default` reference. Two default footers in
one section: the promoted proposal printed the page number TWICE on every
page, and ran 45 pages where the baseline runs 41.

**Every gate was green.** `revision validate`'s parts gate asks whether the
part is in the package; `compare` reads runs, paragraphs and links; a page
number is a field inside a part neither of them opens. It was found by
rendering the promoted file and looking at it — the same lesson as the
"nothing renders by default" note below, now with a promote behind it.

The build's own line about it is misleading too: for each carried part it
prints "it is not referenced from the body, so it goes back with its content
type and a free rId". A header or footer IS referenced from the body — from
`sectPr` — and that reference is the whole difficulty.

Fix: when restoring a header/footer reference, reconcile the whole section
against the baseline's type→part mapping rather than appending one
reference — if the section already carries a reference of that type to a
DIFFERENT part, appending is always wrong. The invariant worth encoding is
"a batch's page furniture is the baseline's page furniture". Per-paper
workaround meanwhile: `Life_Expectancy/revision/fix_section_refs.py`, which
writes the baseline's mapping onto a batch and is idempotent. A regression
test wants a baseline whose parts are typed `even`/`default`/`first` and a
Compare that keeps exactly one of them under the wrong type.

### ~~S1 — `compare`'s FORMAT layer was blind to bold/italic in a PANDOC-written docx: `<w:b />` (space before the slash) did not match its regex~~ — FIXED 30.08, `d83444b`
<!-- status: fixed -->

**Fixed 2026-08-30.** `\s*/>` rather than `/>`, for the four on/off tags and for `<w:vertAlign>` beside them. Both spellings are now in the parametrised table in `test_compare.py`, and a test compares two PANDOC-spelled documents against each other — the bug survives any fixture where only one side carries the space.

Proved against the old regex: every pandoc spelling read `[]`. `<w:bCs/>` still does not answer for `w:b`, and `w:val="0"` still reads as off.

`_compare_read._flags` reads a run property with

    re.search(rf'<w:{tag}(?:/>|\s+w:val="([^"]*)"\s*/>)', rpr)

which matches `<w:b/>` and `<w:b w:val="0"/>` but **not `<w:b />`**. XML says
those are the same element; pandoc writes the spaced form for every
self-closing tag.

Measured 2026-08-29 on Life_Expectancy's round-2 response letter, written by
pandoc: 15 `<w:b />` and 85 `<w:i />`, and `compare` reported the file as
carrying **no bold and no italic anywhere**. Reformatting it (an lxml
round-trip, which normalises the spacing) then produced **28 phantom FORMAT
change locations** of the shape

    'Reviewer 2': ['size 24'] -> ['bold', 'size 24']

on a pass that changed nothing but paragraph spacing. The noise is the
harmless half. The dangerous half is the false NEGATIVE: on any
pandoc-produced document — every `.md`-to-`.docx` deliverable — a genuine
loss of italics or bold passes `compare --expect-clean` silently, which is
the same class of failure as the size/colour blindness that entry above it
records.

Fix: tolerate whitespace before the slash (`\s*/>`), for the on/off tags AND
for `<w:vertAlign .../>` beside them, and test with a fixture written by
pandoc rather than by python-docx — every existing fixture is written by a
serializer that omits the space, which is why no test caught this.

### ~~S2 — `compare` read the on/off run flags WITHOUT the style cascade, so every Word save that drops a redundant `<w:i/>` under an `Emphasis` run was reported as ITALIC LOST~~ — FIXED 30.08, `d83444b`
<!-- status: fixed -->

**Fixed 2026-08-30.** `Cascade` could not resolve these at all: `_val` reads `w:val`, and a toggle's ON form is the bare element, so `of("i", ...)` answered None for `<w:i/>`. `Cascade.toggle` is the resolver for a property whose presence IS its value — run, then the character style's `basedOn` chain, then the paragraph style's, then docDefaults — and `_compare_read._resolved_flags` uses it.

Falls back to the stated flags with no styles part, which is the answer `_valued` gives and the honest one. Two of the five tests fail against the old code with the reported shape, `{'from': ['bold'], 'to': []}`.

`_VALUED` (size, colour) is resolved through `styles.Cascade`, and its
comment says exactly why: *"Word deletes a direct property equal to the
inherited one, so comparing what is STATED reports a difference on documents
that render identically — which is how a check that cries wolf gets
written."* The on/off flags in `_flags` — italic, bold, strike, smallCaps —
were left reading the run's own `rPr`.

So they cry wolf. Measured 2026-08-29 on Life_Expectancy, comparing the
clean generation against the same manuscript after the author's Accept All
in Word:

    'Demographic Research':       ['italic', 'size 24'] -> ['size 24']
    'Demography':                 ['italic', 'size 24'] -> ['size 24']
    'Review of Economic Studies': ['italic', 'size 24'] -> ['size 24']
    'Papeles de Población':       ['italic', 'size 24'] -> ['size 24']

Every one is false. Those runs carry `<w:rStyle w:val="Emphasis"/>`, the
style is defined `<w:rPr><w:i/><w:iCs/></w:rPr>`, and Word dropped the
direct `<w:i/>` as redundant on save. The four journal names are still
italic on the page; the runs that had `<w:i/>` with no character style kept
it, which is the tell.

**Why it matters more than noise.** This fires on an ACCEPTANCE — the one
comparison a paper runs at its most dangerous moment, when the author's
Accept All really can strip run properties (that is a documented failure on
this very toolkit's papers). A layer that reports four false losses there
teaches the reader to skim past the real one. The fix is the same Cascade
the valued properties already use.

Pairs with the pandoc `<w:b />` entry above: the on/off flags are wrong in
two independent ways — blind to a spacing variant, and blind to the style
that supplies the property.

### ~~S4 — `revision validate` at a truth state died with a raw file-not-found instead of saying there is no batch to validate~~ — FIXED 30.08, `d83444b`
<!-- status: fixed -->

**Fixed 2026-08-30.** The missing batch is caught before the read: it prints what is not there, how many pending revisions the manuscript holds and which state that puts it in, and points at `revision status`. Exit 3, as the entry suggested. A paper whose `paper.toml` names a manuscript that is gone gets the answer about the batch without the state line, rather than a second traceback.

At a truth state — the normal state of a paper between rounds — there is no
`build/batch.docx`, and the ladder says:

    $ docxkit revision validate
    docxkit: cannot read …\revision\build\batch.docx: [Errno 2] No such
    file or directory: '…\\revision\\build\\batch.docx'
    exit 1

It reads as a broken installation or a lost file, not as "there is nothing
pending; `revision status` is the check you want". It cost a real detour:
Life_Expectancy's round-2 protocol listed `revision validate` as a
PRECONDITION, to be run green before any edit, and the step is not runnable
as written — the protocol author reasonably assumed a gate ladder could be
run on a clean paper.

Fix: catch the missing batch and print what state the paper is in and what
to run instead. Exit code is a judgment call; refusing with 3 (the
BaselinePending code's sibling) beats a traceback-shaped 1.

### ~~S4 — the accept-check refusal told you to pass `accept_check=False`, which the CLI cannot do~~ — FIXED 30.08, `d83444b`
<!-- status: fixed -->

**Fixed 2026-08-30.** One `_ACCEPT_ESCAPE` sentence behind both refusals, which used to spell it out separately and were both wrong the same way. It names where the switch really lives — `tracked.build(..., accept_check=False)` from Python — says the CLI has no flag for it on purpose, and keeps the half worth keeping: the refusal is usually right and the repair is usually in the manuscript.

`revision build`'s anchor-loss refusal ends:

    Pass accept_check=False to build the file anyway and inspect it.

That is a Python keyword argument. The CLI's flags are `--allow-math-resolve`,
`--allow-stale-baseline`, `--keep-math`, `--allow-pending-baseline` and
`--force`, none of which is it. A CLI user reading that line has been told to
do something the CLI does not offer, and the honest workaround — write a
throwaway script that imports `docxkit.revision` — is the thing the CLI
exists to avoid.

Met 2026-08-29 on Life_Expectancy, where the refusal was RIGHT (two
unterminated bookmarks Compare would have dropped) and the repair was to fix
the manuscript, not to bypass the check. So the message wants both halves:
name the CLI escape if one is added, and keep saying that the refusal is
usually correct.

### ~~S1 — a survivor list quotes the LIVE file as though it were the run's own source, and says nothing when the snapshot is gone~~ — FIXED 30.08, `4fc4da7`
<!-- status: fixed -->

`mutation_survivors.pristine_source` reads the `.pristine` copy a session
took when it planned the run, because every line number in the report indexes
into the file the mutants were generated from. When the snapshot is missing it
fell back to the live file and returned an **empty note**.

Its own docstring already says what that costs: *"a source that has moved
since — a docstring added, a helper inserted — shifts every quote below the
edit, so the report names the wrong line with complete confidence."* An empty
note is indistinguishable from "this is the source the run used".

Eight of the fifty sessions on this machine have no snapshot — they predate
the mechanism — so the silent path was the live one, not a corner. It became
much more dangerous while a retention rule was being considered: the
`.pristine` half of a session *looks* like the disposable one, and pruning it
would have turned every later report on 42 sessions into confident wrong
lines with nothing on the page to say so.

**Fixed 2026-08-30.** The fallback returns a warning naming which of the two
cases it is — a session that never kept a snapshot, or a `.pristine` that
exists without the file, which is a pruning mistake with somewhere to go and
look. It is still not an error: the fallback is what this tool always did.

### ~~S1 — `mutation_session` copies only `src/docxkit/*.py` into the worktree and deletes nothing, so a module that became a subpackage is measured as its own stale predecessor~~ — FIXED 30.08, `4fc4da7`
<!-- status: fixed -->

`ensure_worktree` refreshes the private checkout from the working tree, and
its comment says why it copies ALL of `src/` rather than just the module under
test: *"refreshing only the target left every other module at whatever HEAD
was that day."* The glob is `src/docxkit/*.py`.

Measured 2026-08-30, the day `revision.py` became `revision/`: the worktree
held **no `revision/` at all** and a **144 KB `revision.py` dated six days
earlier**, which nothing removed. A round planned against
`src/docxkit/revision/_build.py` would have run with `docxkit.revision`
resolving to the pre-split module — a plausible number for source the
session's plan does not describe.

That is this module's own opening hazard, arriving through the one path it did
not guard. Not a stale MODULE: a stale LAYOUT.

**Fixed 2026-08-30.** The copy is recursive and a `.py` under
`src/docxkit` that the working tree does not have is deleted. Both halves
were needed — copying the new layout in beside the ghost leaves both, and
the loader picks.

### ~~S1 — the mutation session stem drops the folder, so `revision/_ingest.py` and `ingest.py` share one database and one `.pristine`~~ — FIXED 30.08, `4fc4da7`
<!-- status: fixed -->

A session is named `.mutation-<stem>.sqlite`, and the stem was
`module.stem.lstrip("_")`. `revision/_ingest.py` and `ingest.py` both reduce to
`ingest`.

The failure is not a crash. The second run to start resumes or overwrites the
first's database, and `mutation_survivors` then pairs that database with a
`.pristine` holding the **other module's source** — line numbers indexing into
a file the run never saw, printed with complete confidence. It is the S1 above
reached from a different direction, and the same shape as the coverage-floor
key beneath it.

The rule had **three copies**, in `mutation_session`, `measure_all` and
`stale_figures`, in three slightly different spellings — and `stale_figures`
lacked the fallback the other two had for a name that is nothing but
underscores. A rule written out three times is a rule with three chances to be
fixed in two places.

**Fixed 2026-08-30.** `harness_map.session_stem` is the only copy. A module in
a subpackage keeps its folder (`revision_build`); a top-level module keeps
exactly the name its session has always had, because 49 of them exist here and
renaming them would orphan every recorded figure.

### ~~S2 — `coverage_floor` keys on the basename, so two `__init__.py` collapse into one entry and a module is checked against another file's floor~~ — FIXED 30.08, `4fc4da7`
<!-- status: fixed -->

`measure` returned `{Path(name).name: percent}`. That was unique while every
module sat directly under `src/docxkit`, and stopped being unique the moment
`revision/` existed: `revision/__init__.py` and the package's own
`__init__.py` collide head-on, and one silently overwrites the other in the
dict.

A collision here does not raise. A module is measured against a percentage
belonging to a different file, and the gate reports a confident pass — or a
confident failure — about neither of them.

**Fixed 2026-08-30.** A module inside a subpackage keeps its folder in the
key (`revision/_losses.py`); every other key is unchanged, which is why the
40-entry FLOORS list did not have to be rewritten.

**What the split turned up on the way.** `revision.py` carried one floor at
97, described as *"held above DEFAULT deliberately: every refusal in here is a
thing that failed SILENTLY in a real paper."* Restated as fourteen floors,
`_build.py` measured **84.7 %** — below the package DEFAULT of 85, in the half
that drives Word's Compare. Nothing was lost in the split. That half had been
the least-tested thing in the protocol all along, and one aggregate over 3,118
lines could not say so. It is at 100 % now.

### ~~S2 — `measure_all --all` walks `src/docxkit/*.py`, so a whole-package sweep silently omits every module in a subpackage~~ — FIXED 30.08, `4fc4da7`
<!-- status: fixed -->

`--all` is the entry point for a fan-out sweep across several worktrees — the
thing that turns a day of wall clock into twenty minutes of thought. It
expanded to 43 modules and **none of `revision/`'s fourteen halves**, and
would have reported a whole-package sweep with 3,118 lines of the protocol
never opened.

Worse than a gap: the report reads as complete. Nothing in it names what it
did not measure.

**Fixed 2026-08-30.** `rglob`, with the name kept relative to `src/docxkit` —
which is the spelling `harness_map` keys on and the one `run` interpolates
back into a path. The smallest-first ordering is unchanged, because `--in`
deals round-robin and sorting the other way puts every big module in the last
stream.

### ~~S3 — `tools/sweep.py` was bound to nothing: no chain, no workflow, no gate~~ — FIXED 30.08, `4fc4da7`
<!-- status: fixed -->

The sweep runs every read-only routine over a corpus of real manuscripts, and
CONTRIBUTING said to run it *"after any change to the reading routines"*. That
sentence was its only binding. It is in neither `tools/gates.py` nor
`.github/workflows/ci.yml`, and no hook or command called it.

This is the state the curated mutations were in until 2026-08-27, and it
matters more here: the synthetic suite holds only the shapes somebody already
knew to write, and the sweep's whole subject is the document nobody
anticipated. `test_corpus_regressions.py` records what one pass over 347
manuscripts found — a byte-order mark, an undeclared namespace prefix, nested
tables — every one of which passed the unit suite.

**Fixed 2026-08-30.** Sixth gate in the chain. CI cannot run it — a runner has
no manuscripts and a checkout cannot carry any — so the local chain is the only
place it can live, and without `DOCXKIT_CORPUS` it exits 3 and the chain prints
`skip sweep` with the reason. That third exit state is the point: `ok` over
zero documents and `ok` over 347 are the same line.

Two things the wiring found. A configured root that does not exist used to be
swept past, reporting a clean run over a fraction of the corpus; it fails now.
And `--limit` took `paths[:N]` — one alphabetical corner of one directory, so a
bounded sweep could never find anything it had not already found. It strides.

### ~~S3 — three gates go blind to a module the day it becomes a subpackage, and one of them then reports on the WRONG module rather than none~~ — FIXED 30.08, `4fc4da7`
<!-- status: fixed -->

`src/docxkit/*.py` is how several gates enumerate the package. A directory is
not a `.py`, so on 2026-08-30 they stopped seeing `revision` — and not one of
them failed:

* **`test_api_surface`** dropped `revision`'s 53-name `__all__`, the largest
  in the package, from every test in the file. Worse than absent: `MODULES`
  was fixable with a glob, but `test_everything_DECLARED_can_actually_be_imported`
  builds its import from `path.stem`, and the stem of `revision/__init__.py`
  is `__init__` — so `__import__("docxkit.__init__")` resolves to `docxkit`
  itself. The test would have gone on passing, over the package's own 16-name
  surface, while reporting on `revision`;
* **`test_layering`** lost the whole subpackage from its graph. Only the cycle
  test noticed, and only because `revision` happens to be named in `_CYCLE`;
* **`test_harness_map`**'s "every module has an ENTRY" check left fourteen
  modules unmapped at once — the state its own docstring calls out as the one
  that fails silently, because `stale_figures` walks that dict and "not in the
  table" reads exactly like "nothing to do here".

**Fixed 2026-08-30.** All three walk subpackages. `test_api_surface` gained
`_module` (the importable name) separately from `_id` (the name a failure
prints), and a test pinning that the walk reaches `docxkit.revision` and not
`docxkit` — asserted as an object identity, because both failures produce a
real module with a real `__all__` and neither raises. `test_layering` gained
`SUBPACKAGE_HALVES`: the internal order, declared bottom-first and enforced,
which cannot live in `__init__.py` because ruff's isort sorts that block.

### ~~S4 — nothing checks that an entry sits in the SECTION that describes it, and the cheap check cannot~~ — FIXED 27.08, `9f851d0`
<!-- status: fixed -->

**Fixed 2026-08-27.** Every entry now declares its own status on the line
under its heading — `<!-- status: … -->`, one of `open`, `fixed`,
`withdrawn`, `not-a-defect`, `note` — and `tools/backlog_status.py`
gates on it: `open` only under `## Open`, `fixed` only under `## Fixed`,
the three record statuses in either, because some are kept in `## Open`
on purpose.

**213 entries stamped, and not one character of an existing heading or
body changed** — 213 insertions, 0 deletions. That was the design
constraint rather than a happy accident: a pass over every entry in a
9,700-line file is exactly where a misfiling gets introduced, and an
additive marker cannot corrupt what it annotates.

**The statuses were adjudicated, not inferred.** 205 took their section's
status; 8 were read in full first and named as records — two withdrawals,
three not-a-defects, two notes, and this entry. Reading them turned up
the sharpest argument for the whole approach, which no fixture would have
produced: *a fifth writer of CT_PPr order* says **"Raised by the same
review, and not fixed"** in its first paragraph and **"Closed
2026-08-18"** in its fifth. It is correctly filed. Entries accumulate
history and only the last word counts — no pattern can know which
sentence is the verdict, and the author can, once, at the moment of
writing.

**Kill-checked against the REAL file, healthy and deliberately broken**,
in memory rather than on disk — an hour after filing that a killed tool
leaves its sabotage in the tree, writing a deliberate defect to disk to
watch a check fail is the wrong instrument. Healthy: 0 problems. An
`open` left under `## Fixed` (the `--sample` shape): named, 1 problem. A
`fixed` left under `## Open` (the 2026-08-24 close-helper shape): named.
An entry written with no marker: named. Ten tests, and the one that keeps
the field from decaying is that a MISSING status is a finding rather than
an assumption.

**What it deliberately does not do** is check that the declaration is
TRUE. A `fixed` on a live defect passes. That is the same bargain
`tables_after`'s stated count makes, and the alternative is the inference
this entry exists to reject.

Filed 2026-08-27, out of the measurement that closed *five fixes shipped
with no `## Fixed` entry* (in `## Fixed`, 27.08).

Two misfilings were live in this file this morning, and in both
directions at once. `--sample` and the `Table` handle sat under
`## Fixed` while open — three days each, and both are closed in this
batch. The RETRACTED `link_all` entry sits under `## Open` on purpose,
and so does a not-a-defect record. On 2026-08-24 the reverse happened and
was worse: a close-helper cutting an entry "to the next `### `" took the
`## Fixed` heading with it, and every closed entry sat inside `## Open`
for three commits.

**The obvious gate was built, measured and thrown away, and that is the
finding.** A resolution-detector over all 209 entries — strikethrough,
`FIXED`, `WITHDRAWN`, `RETRACTED`, `CORRECTED`, a commit hash in the
heading — run against the real file:

    ## Open     6 entries,  4 flagged,  0 real
    ## Fixed  203 entries, 89 flagged,  2 real

**93 findings, two of them true.** Every false positive comes from a
convention this file GREW rather than declared: an entry closed by a bare
hash in the heading, twelve closed together under one parent heading, a
record that was never a defect, a body that quotes the word FIXED while
describing something else. A gate at 2 % precision is read once and
ignored, which is the dead-gate shape this file ranks above a wrong
answer.

**What would work is a declared field, not a better regex** — a
`status:` on each heading, or sections a parser can trust. That is a
change to 209 existing entries, which is why this is S4 and filed rather
than done.

**Workaround in use:** `tools/backlog_refs.py`, which asks whether the
record was WRITTEN rather than where it sits, and the two misfilings
corrected by hand in this batch.

---

### ~~S2 — `reorder_rows` reads the table back in the FINAL view whatever view the caller read it in, so a correct reorder of a REDLINE is refused~~ — FIXED 27.08, `0dc84d4`
<!-- status: fixed -->

**Fixed 2026-08-27.** `Table` carries the `view` it was read in, and the
self-check re-reads with it. That is the first of the two shapes this
entry proposed, and the reason for preferring it stands: reordering the
original view is a legitimate thing to want, and refusing a table with
revisions would take that away to fix a bug in the audit.

**Reproducing it turned up a second half the entry had not seen**, and
that one was silent rather than loud. `key` was called with cell text
scraped from the RAW xml rather than from the view, so on a redline an
ordering function saw both sides of every revision at once — `0.310.22`
where the caller's own `table.rows` says `0.31`. A key on the leading
cell would not notice; a key on a NUMBER would sort the table wrongly
and nothing downstream could tell. It reads `table.rows` now, so there is
one extraction where there were two and it is the caller's own.

Refusing where the raw row count and the view's disagree, which only a
row-level revision can cause: permuting one list by the other's indices
would move the wrong rows and still pass the multiset check, which is the
one failure this function's gate exists to make impossible.

**Kill-checked without touching the tree.** An hour after filing that a
killed `mutate.py` leaves its sabotage behind, editing the module to
watch a test fail was the wrong instrument. The old comparison is
reproducible directly — the table as the caller read it against the
result re-read as `final` gives `2 row(s) LOST, 2 GAINED`, and against
the result re-read in its own view it passes.

Found 2026-08-27 by review, while looking at a batch that touches this
function for another reason. Filed rather than fixed: it is pre-existing,
it needs `Table` to remember its view, and folding a second behaviour
change into that batch is how a fix arrives with nothing to bisect
against.

**The self-check contradicts the caller.** `reorder_rows` verifies its
own work by re-reading the table — `moved = read_all(out)[table.index]` —
and that call takes the DEFAULT view. A caller who read the document with
`view="original"`, which `by_caption(..., view=...)` and
`tables_after(..., view=...)` both offer, gets a handle whose `rows` are
the original side compared against rows read from the accepted side. The
row multisets then differ for a reason that has nothing to do with the
reorder:

    AnchorError: reordering table 0 changed its rows, not just their
    order: 2 row(s) LOST, 2 GAINED — lost ('POL','') gained ('POL','0.31')

The permutation was correct. Two cells whose text sits inside `w:ins` is
enough to produce it.

**It is also the only mutator here with no tracked-changes refusal.**
`_has_revisions` appears twice in `_table_core.py` and neither call is in
this function, so where `house()` refuses a redline cleanly and says why,
this one accepts it and then fails an integrity check about itself. Two
different answers to the same document, from one module.

**Shape of a fix.** `Table` gains the `view` it was read in, and
`reorder_rows` re-reads with it; or the function refuses a table carrying
revisions like every sibling does. The first is better — a reorder of the
original view is a legitimate thing to want — and it is the one that
needs the extra field, which is why this is a separate change.

**Workaround in use:** none needed yet; no paper has reordered a redline
table. Read the clean build, reorder, rebuild the redline — which is what
every other mutator here already requires.

---

### ~~S1 — a KILLED `mutate.py` leaves its sabotage in the working tree, and the next thing to read that file is a commit~~ — FIXED 27.08, `9c47728`
<!-- status: fixed -->

**Fixed 2026-08-27.** The pre-mutation bytes go to `.mutate-in-flight/`
BEFORE the mutation is applied, which is the only ordering that helps: the
case being guarded is the one where nothing after the write runs. A later
run finds the stash, REFUSES, and names the file and its saved original;
`--restore` puts it back.

**Refusing rather than restoring silently**, which was the choice worth
making. The saved bytes are right by construction, but an author who has
EDITED that file since the kill would have the edit overwritten by a tool
they only asked to measure something. So it says what it found and leaves
the decision.

**The line-ending half is fixed in the same loop**, and it needed both
halves. Reading bytes alone would have broken every multi-line anchor on
a CRLF checkout, since the anchors are written with `\n`: the file is
read as bytes, matched in LF, the mutant written back in the file's own
convention, and the restore is byte-for-byte from the original bytes.

`tests/test_mutate.py` is new — the tool had no tests at all, which is
most of why this and the entry below both survived. Nine of them, and the
two that matter here are the byte-exact restore and a CRLF file still
being mutated correctly.

Found 2026-08-27, in this repo, by nearly committing one.

**What happened.** A `mutate.py` run was killed part way through. It
restores each mutation in a `finally`, which covers an exception and does
not cover the process being killed — so `_set_borders` in
`_table_layout.py` was left carrying its sabotage:

    +    if _EDGE_RE.search(cell):
    +        return _EDGE_RE.sub(lambda _: borders, cell, count=1)

That is the defect the mutation is named for — the nested table's
borders rewritten instead of the outer cell's — sitting in the source, in
a batch about to be committed. It was caught by five failing tests being
three lines further down the diff than they should have been, and then
only because the diffstat had three more lines than the patch that made
it. **A `git commit -a` at any point in the previous hour would have
shipped it.**

**Why nothing said so.** `mutation_session.py` treats exactly this as
hazard two of six — "cosmic-ray restores the file after each mutant but
NOT when it is terminated, so a killed run leaves its mutation in the
tree" — and guards it by verifying the unmutated baseline before every
chunk, which turns a leftover into an immediate refusal. `mutate.py` runs
the same risk with none of that: no baseline check, no refusal on a dirty
tree, and no record of what it was holding when it died. The lesson was
learned once, written down, and applied to one of the two tools that
needs it.

**It is worse here than there**, because `mutation_session` works in a
separate `git worktree` and `mutate.py` mutates the CHECKOUT the author
is editing — and because a sabotage mutation is by construction a defect
the suite can catch, so the leftover looks like "my change broke five
tests" rather than like contamination. That reading costs a debugging
hour and then a wrong fix.

**Shape of a fix.** The cheap half: write the mutation and the path to a
sentinel file before applying it, delete the sentinel after restoring,
and refuse to start while one exists — naming the file to put back. The
cheaper half still: refuse to start on a dirty `git status` for the
modules it is about to touch, so a leftover cannot hide among real edits.
Neither needs the tool to survive being killed; both need it to say so
afterwards.

**The restore also REWRITES the line endings**, found in the same
sitting. `path.read_text()` reads through universal newlines and the
restore writes back with `newline=""`, so every module the run touched
comes back LF in a working copy that is CRLF — twelve of them here, after
one run. Invisible on this repo because `core.autocrlf=true` normalises
it away and `git diff` is empty; on a checkout with `autocrlf=false`,
which is how `BACKLOG.md` itself has to be committed, it is a twelve-file
whole-file diff that appears from nowhere. Same one-line cause as the
entry above: read and write the bytes, or read with `newline=""` too.

**Workaround in use:** read `git diff --stat` against what the patch
actually changed before believing a test failure. That is the check that
caught it, and it is not a rule anybody can be asked to remember.

---

### ~~S3 — three of `mutate.py`'s anchors have drifted, so it exits 1 on every run and nobody has noticed~~ — FIXED 27.08, `9c47728`
<!-- status: fixed -->

**Fixed 2026-08-27.** All three re-anchored, and each had drifted a
different way — which is the part worth keeping, because only one of the
three is visible by reading the anchor:

* *the staging directory leaks again* — the call moved into
  `_clear_staging`, so its indentation went from eight spaces to four;
* *the run-open scan matches `w:rPr` again* — the pattern gained
  `(?<!/)` so a self-closing `<w:r/>` no longer reads as an opening tag;
* *a field ends at the first end tag* — **the function MOVED to another
  module.** The anchor text was still correct and still unique; the
  module name was the stale part. No amount of reading the anchor would
  have shown that.

So the gate is not "does the anchor still match" but "does it match ITS
MODULE, exactly once" — `tests/test_mutate.py::
test_EVERY_anchor_matches_its_module_exactly_once`, in the suite people
actually run rather than only inside the tool nobody was running.

**In CI, in its own job — and NOT in `tools/gates.py`, which is where
this entry proposed putting it.** Measured before deciding: 42 mutations
at `-n <physical cores>` is **18m23s**, against about four minutes for
the whole local chain. `-x` already stops each mutation at its first red
test and it still costs eighteen minutes. A pre-commit gate five times
longer than the thing it guards is one people route around, so the entry
was right that it needed wiring and wrong about where. One job on 3.14
rather than a step in the three-version matrix: it is 42 suite runs, and
the answer does not depend on the interpreter.

The run that closed this: **42/42 caught, no drifted anchors, exit 0.**

Found 2026-08-27, alongside the entry above, by running the tool with its
exit code visible for the first time in a while.

    39/39 mutations caught
      SKIPPED (anchor drifted): the staging directory leaks again
      SKIPPED (anchor drifted): the run-open scan matches w:rPr again
      SKIPPED (anchor drifted): a field ends at the first end tag, so a
                                nested field closes its parent
    MUTATE_EXIT=1

`mutate.py` is the CURATED list — every mutation in it re-introduces a
defect this package has really shipped — so a drifted anchor is a defect
whose regression cover has silently gone. Three of them. The one this
batch re-anchored was a fourth, and it drifted because *this batch*
rewrote the line; these three drifted at some earlier point nobody
recorded.

**The tool says so and nothing reads it.** It exits 1 on a skip, prints
the reason, and is in neither `tools/gates.py` nor `ci.yml` — so its
report has been true and unread. `39/39 caught` at the top of the output
is what a person's eye lands on, and it is the number that looks like a
pass.

Both halves are the same shape as the entry above and as the `## Fixed`
entry about `heredoc_guard`: a check that is correct, that is not wired
to anything, and that therefore reports into an empty room.

**Shape of a fix.** Add `mutate.py` to the gate list — it is the fastest
mutation cover in the repo and the only one that is curated — and
re-anchor the three. A drifted anchor should probably also FAIL rather
than skip: the whole point is that these mutations are the ones known to
matter.

**Workaround in use:** none. Three curated defects currently have no
mutation cover, and this entry is the only record of which.

---

### ~~S3 — `tools/heredoc_guard.py` is written, tested, and wired to nothing: the trap it exists to refuse was walked into twice while closing this batch~~ — FIXED 27.08, `4f6b3bc`
<!-- status: fixed -->

**Fixed 2026-08-27.** The hook is registered in the USER's
`~/.claude/settings.json` as `PreToolUse` on `Bash`, and the TENTH
occurrence was refused four tool calls later — by this batch, appending
this file's own test additions through `cat >> … <<'ENDOFTEST'`. The
refusal named the offending line and the way through; the payload went in
through the Write tool instead.

**Measured before installing it**, because it now runs ahead of every
shell command in every session on this machine: **71 ms median** over ten
calls, min 66, max 78 — one Python start-up.

The user-level entry names the interpreter by ABSOLUTE path. That is a
choice to take PATH out of the question for a hook that must work in
every session on one machine, and **not a measurement that a bare
`python` fails** — an earlier draft of this entry said it was, and
review caught the contradiction, because the repo's own committed
registration uses a bare `python` and `$env:CLAUDE_PROJECT_DIR` and has
to, being the copy that ships to any machine. Two spellings, two jobs.

The reason that mattered is the one worth keeping: **a substring match
on the settings file cannot tell either of them apart from a dead
one.** It cannot say the interpreter starts, that the path resolves, or
that the thing at the end of it is this guard —
`test_a_registration_naming_a_path_that_is_not_THERE_is_not_one` was
worse still, skipping any command containing `$`, which is exactly the
form the repo commits, so on a CI runner it passed having checked
nothing at all. It now expands `$env:CLAUDE_PROJECT_DIR`, splits with
`shlex` so a path under `C:\Program Files` survives, and asserts that it
checked something. And
`test_the_REGISTERED_command_really_refuses_a_heredoc` RUNS the
registered script with the harness's own JSON on stdin and requires exit
2 — which is the only form of this check that cannot go quietly dead.

The repo half is three tests, and they assert what the function cannot:

* `test_THIS_repo_registers_the_guard_for_sessions_rooted_here` reads the
  COMMITTED `.claude/settings.json`, so it is a repo invariant rather
  than a fact about one machine;
* `test_the_USER_harness_registers_it_TOO_because_that_is_where_it_bites`
  is the one that would have been red all week, and it is the half the
  entry got wrong. A project-scoped hook only fires in sessions rooted at
  the project, and **not one of the nine occurrences happened in such a
  session** — they happened in paper directories and in the home
  directory, with docxkit imported. The repo registration that already
  existed could not have stopped any of them. The test SKIPS where there
  is no user harness at all (CI, a clean machine) and FAILS where one
  exists without the hook, which is the state to notice the next time a
  settings file is rewritten;
* `test_a_registration_naming_a_path_that_is_not_THERE_is_not_one` covers
  the other way this goes quietly dead: the file moves, the entry stays,
  and every session then fails the hook open.

Kill-checked rather than assumed. Fed the settings this machine carried
an hour earlier — a `Stop` hook, a `SessionStart` hook, no `PreToolUse` —
`_hooked` returns `[]`; fed one whose matcher is `Write` rather than
`Bash`, `[]` again.

Found 2026-08-27, during the batch that closed the ten entries below.

**Symptom as observed.** Two patch scripts written through a Bash
heredoc came out corrupted, in the two ways the guard's own docstring
names. The first silently failed to match its anchor:

    b = '''        z.writestr("[Content_Types].xml",  ... b"\r\n" + ...'''
    AssertionError: flat OPC writer anchor

The second was worse, because it wrote a file that then would not parse
at all:

    SyntaxError: unterminated string literal (detected at line 82)

The line was `text.index("\r\n" + heading + "\r\n")`. Both escapes had
lost their backslash and become REAL newlines inside the string literal,
so it never closed. Both heredocs were POSIX-quoted (`<<'PY'`), which is
specified to pass the body through untouched.

**The guard is correct and was never asked.** Run by hand it answers
straight away:

    >>> from heredoc_guard import offending
    >>> offending("python - <<'PY'\ns = t.replace('\\\\', x)\nPY")
    "s = t.replace('\\\\', x)"

What is missing is the registration. `~/.claude/settings.json` carries a
`Stop` hook and a `SessionStart` hook and no `PreToolUse` entry at all,
so nothing ever invokes it. `tests/test_heredoc_guard.py` passes on
every run and tests a function nobody calls.

**Why S3 and not S4.** The file's own docstring states the job: "what is
tested here is the thing the rule could not be: a refusal that does not
depend on anybody remembering." An uninstalled refusal IS the rule it
was written to replace, and the entry above it records seven prior
occurrences across two agents, the worst rewriting 387 real newlines in
a file another session was editing. Tonight makes nine. A green suite
over a gate that cannot fire is the false confidence this file ranks
above a wrong answer — and here the suite is not merely unable to fail,
it is measuring a dead path.

**Fix sketch.** The code exists; only the wiring is missing. A
`PreToolUse` matcher on `Bash` in `~/.claude/settings.json`:

    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command",
      "command": "python D:/docxkit/tools/heredoc_guard.py"}]}]

That is a change to the USER's harness configuration rather than to this
repo, which is why it is filed rather than done — it changes how every
session on this machine behaves, including sessions that have nothing to
do with docxkit. Worth deciding once and deliberately. The repo half
worth doing regardless: `test_heredoc_guard.py` should assert that the
hook is REGISTERED somewhere, not only that the function is right, or
this recurs the next time a settings file is rewritten.

**Workaround in use:** write the script with the Write tool and run it
by path, never through a heredoc. Which is the rule that has now failed
nine times, and is exactly why the guard was built.

---

### ~~S3 — five fixes shipped with no `## Fixed` entry, so tonight the backlog read as ten open defects when five were done~~ — FIXED 27.08, `9b41c10`
<!-- status: fixed -->

**Fixed 2026-08-27** — `tools/backlog_refs.py`, with
`tests/test_backlog_refs.py`.

**The stricter rule this entry proposed is wrong, and measurably.** "Fail
when a commit says `Refs BACKLOG.md` and does not itself touch
`BACKLOG.md`" was checked against the history before it was written:
**all six commits that had adopted the convention broke it**, because the
code lands first and the entry moves in the commit after. A gate red six
times for six correctly-closed defects is a gate somebody deletes.

So the rule is the weaker, true one: a `Refs BACKLOG.md` commit must be
accompanied or FOLLOWED by a commit that touches the file. Nothing is
said about WHICH commit; what is refused is the state where a fix sits at
the tip with the record never written. Over the same 905 commits it
reports zero, which is what it should say about a history whose gaps were
every one closed in the next commit — and it goes red for exactly as long
as a gap is open, which is the red suite this entry asked for.

**What it cannot see, stated rather than papered over:** a fix committed
with no mention of the backlog. The convention costs one line per commit.
The alternative that would need no convention — reading the FILE's own
structure instead of the commit messages — was built, measured and
rejected in the same sitting; it is the S4 now standing in `## Open`.

**Two ways it was still dead when first written, both from review.**

*It counted a TOUCH as a record.* Filing a new defect is the most
frequent reason to open this file, so one filing commit retroactively
marked every pending fix as recorded — and the exact history this tool
was written for came back clean through it. What the rule names is *entry
moved to `## Fixed`*, so that is what is asked: did the commit's diff ADD
a heading that says an entry is resolved. One `git show` per commit,
restricted to the one path, walked lazily and stopped at the first
closure — typically one call.

*A git FAILURE read as "no history".* `fatal: detected dubious ownership
in repository` is ordinary for a repo on a second drive, in a container,
or under another user, and it made the tool print "nothing to check" and
exit 0 while the live-repo test took its skip. Green suite, green tool,
dead gate — the shape a suppressed git error always has, since a fatal
error looks exactly like a true nothing. Only the spellings that mean
"not a repository" answer None now; anything else raises with what git
said.

And CI could not see the history at all: `actions/checkout@v4` defaults
to depth 1, so the gate reported a clean answer over commits it never
read, and on a pull request the merge commit lists no files whatsoever.
`fetch-depth: 0`.

Found 2026-08-27, starting this batch. `## Open` listed ten entries. Five
of them — the `crossrefs` half-eaten pair, `place`'s multi-column table,
the fit gate, `citations.link_all`, the link SPAN — were already fixed,
in `805e1ad`, `67459c9`, `cb25235`, `e56906e` and `924cd2e`. Every one of
those commits carries a message describing the defect in this file's own
words. None of them touched `BACKLOG.md`.

**Why it is a finding and not just untidiness.** The batch order is set
by severity, so a stale `## Open` sets the wrong order: the S1 at the top
of tonight's list was the one entry already closed, and the real first
job was an S3 three entries down. And "did we ever fix that?" is the
question `## Fixed` exists to answer — a fix with no entry is invisible
to it, so the next person to hit the symptom re-derives the diagnosis.
That is the same cost as an unrecorded defect, arriving from the
opposite direction.

**Why the rule did not catch it.** Every trigger in the house rule fires
on RECORDING a defect. Nothing fires on CLOSING one, because closing
already feels like the bookkeeping — the code is written, the test is
green, the commit is made, and moving a heading afterwards reads as
filing rather than as finishing. The rule says as much itself ("Done =
fix + a test that FAILS without it + the per-paper workaround deleted +
entry moved to `## Fixed` with its commit hash") and the last clause is
the one that gets dropped, every time, because it is last.

**Fix sketch.** This is checkable mechanically and cheaply, which is why
it is worth a gate rather than a resolution. A test walks `## Open`'s
headings and `git log` since the file's last change, and fails when a
commit message names a module and a symptom an open entry also names.
Cruder and probably enough: fail when a commit's body contains
`Refs BACKLOG.md` and the same commit does not touch `BACKLOG.md`. That
convention started in this batch, so it costs one line per commit and
turns the missing move into a red suite rather than a thing somebody
notices weeks later.

**Workaround in use:** none. The five were moved by hand in this batch.

---

### ~~S4 — `math --check` reads a symbol-only TABLE CELL as a display equation stranded inline, and offers a repair that refuses~~ — FIXED 27.08, `766a8df`; REGRESSED, RE-FIXED 27.08, `9e68cf7`
<!-- status: fixed -->

Found 2026-08-27 on Aging_Well, whose new Appendix opens with a two-column
notation table. `display_equations` counts any paragraph holding nothing but
maths, so each cell of the symbol column is one:

    docxkit math working.docx --check
      30 display equation(s), 17 still in INLINE mode
         ¶183   'cjΦj'
         ¶189   'λμij'
         -> equations.display(para) wraps them in m:oMathPara

Every one of the 17 is a notation cell — verified, not assumed. The paper does
not mean a centred display block there; it means a symbol set in the line of a
cell. And the printed remedy cannot be taken: `equations.display` raises
`display needs exactly one m:oMath in the paragraph, found 3` on cells like
"α, β, γ".

So `math --check` cannot exit 0 on any paper with a notation table, which
makes it useless as a gate for exactly the papers that have most equations.

**Fix:** exclude paragraphs inside a `w:tbl` from `display_equations`, or give
the check a `--in-tables` opt-in. A cell is not where a display equation gets
stranded. If they stay in, the advice line should not name a function that
refuses on multi-`oMath` paragraphs.

**Workaround in use:** the paper asserts every finding is inside the notation
table and reports the gate red with that reason attached
(`r37_equation_vehicle.py`), rather than contorting the cells.

**REGRESSED and re-fixed the same day, `9e68cf7`.** The first cut skipped
every maths-only paragraph inside a `w:tbl`, and a NUMBERED display
equation is one: the house vehicle is a full-width table with the maths
centred in the left cell and "(3)" right-aligned in the right, because
Word has no other way to put a number on the margin beside a centred
block. All thirteen of this paper's equations live in one. So the check
went from honestly red on nine false positives to green on a document
with thirteen display equations and one of them stranded — it could not
tell the healthy file from a sabotaged one in either mode.

Told apart by the equation NUMBER now: a maths-only paragraph whose row
carries a cell holding a number and nothing else is a display equation,
one whose row does not is a cell that happens to contain maths. Per row
and not per table, because (A2) and (A3) share a two-row table and "one
row is a vehicle, many rows is notation" loses both.

Enumerated on working.docx afterwards, by ezhik-82, because a rejected
suggestion deserves the same standard as an accepted one: twelve one-row
vehicles, ONE two-row (tbl@103, carrying (A2) and (A3)), and the 18-row
notation table with no numbered row at all. So the row-count rule would
have been right about twelve of the thirteen and silently dropped the
other two equations — which is the worst way for a rule to be wrong, and
the reason to write this number down rather than the conclusion alone.

**The lesson is about the TESTING, not the rule.** Both cuts had tests
that failed without them, and the second one is not cleverer than the
first — it is the first one measured against the actual manuscript. The
fixtures were invented from the defect report, so they contained the
table shape the report named and not the other one in the same file,
four paragraphs away. A change that makes a gate QUIETER has one
obligatory check that a fixture cannot supply: run it on the real
document in both states, healthy and broken, and confirm the two still
come out different. That is two commands, it was not run, and ezhik-82
ran it instead.

---

### ~~S4 — `write_docx` stamps every zip entry with the CURRENT time, so "byte-identical" can never prove "changed nothing"~~ — FIXED 27.08, `56f44ea`
<!-- status: fixed -->

Measured 2026-08-26 on Aging_Well while timing the round-close chain. Run any
idempotent pass twice on an unchanged manuscript and the two outputs have
different md5s:

    r29_table1_keep_together   1st=3626e3e7  2nd=049d32a8
    r30_boxes_keep_together    1st=436da11b  2nd=42cb83f4

Every entry's CONTENT is identical — `all(a.read(n) == b.read(n))` is True for
the whole namelist. What differs is `ZipInfo.date_time`, stamped from the clock
at write:

    [Content_Types].xml   a=(2026, 8, 26, 0, 37, 40)  b=(2026, 8, 26, 0, 38, 6)
    word/document.xml     a=(2026, 8, 26, 0, 37, 40)  b=(2026, 8, 26, 0, 38, 6)

Two passes that happen to finish inside the same second come out identical,
which is why this reads as intermittent: three of six passes looked
"byte-idempotent" on one run and "churning" on the next, purely by clock luck.

**Why it costs something.** The house idiom for an untracked apparatus pass is
"a re-run that reports no work IS the check that nothing was eaten" — and the
strongest form of that check, `md5 before == md5 after`, is unavailable. So is
any cheap skip-if-unchanged cache: a layout pass that wants to avoid a 6-second
Word render cannot ask "is this the file I last rendered?" without unzipping and
hashing the parts. Rescue copies cannot dedupe either — six no-op passes in one
close produce six distinct files of identical content. On a manuscript that
lives in OneDrive, each is also a sync event.

**Fix:** stamp a fixed `date_time` (or one derived from the source package)
rather than `time.localtime()`. Word does not care what the entries say. Then
byte-equality means content-equality, `md5` becomes a legitimate gate, and a
render cache keyed on the file hash is one line.

**Related, same file:** the passes write unconditionally — `r11`, `r22`, `r29`,
`r30` all print "wrote …" on a run that reported no work. Writing only when the
content actually changed would make the no-op case free, and would make the
timestamp fix visible immediately.

---

### ~~S2 — nothing checks that a FIELD is balanced: `lint` passes a document with an unterminated `fldChar`~~ — FIXED 27.08, `ffeed8c`
<!-- status: fixed -->

Found 2026-08-26 on Aging_Well, dropping a figure whose in-text mention is a
field-form hyperlink. Deleting the sentence took the field's display runs and
left `fldChar begin` + `instrText HYPERLINK \l "Figure2"` standing. Measured
on that paper's own `prev.docx` with one `fldChar end` run removed:

    before:  begin 150  end 150
    after:   begin 150  end 149
    docxkit lint halffield.docx
      clean - no structural problems found        exit 0

`lint`'s docstring says it is for "the 'Word says the file is corrupted' bug
classes … Every check here corresponds to something that actually happened",
and an unterminated field is squarely in that class: Word decides where the
field ends on its own, which in practice means swallowing the rest of the
paragraph into it.

**Nothing else names it either.** `citations` does exit 1 on the mutated file,
but for the *symptom* two paragraphs away —

    UNBALANCED SPAN: the link to 'Shkolnikov2026' (¶10) covers
    "Shkolnikov et al. 2026). Longer lives are an opp" — an unmatched ')'

— which reads as a span-width bug in a link that is in fact fine. On the real
edit the symptom was different again: `crossrefs --audit` reported
`misplaced_anchor` for a figure whose only surviving trace was the orphaned
`instrText`, i.e. a live mention of a figure no longer in the paper. Three
tools, three misleading descriptions, and none of them "a field has no end".

**Fix:** count `w:fldChar` begin/end per part in `lint.audit` — one pass, the
same shape as the existing bookmark-balance check — and report the paragraph
of any unmatched one. A `w:fldSimple` needs no pairing and should be skipped.

**Workaround in use:** `Aging_Well/revision/scripts/r34_drop_figure2.py` walks
the paragraph's run-level children tracking field depth and extends a cut
backwards to the run that opened the field, so the whole field goes with the
sentence. That belongs in a paper only because no library helper deletes a
span of visible text — `replace_in_para` and `insert_in_para` exist, a
`delete_in_para` does not, and the hand-rolled version is exactly where this
defect gets introduced.

---
### ~~S2 — `restore_math_glyphs` matches WHOLE `m:t` runs, so a run Word FUSED is never repaired~~ — FIXED 27.08, `0a3046c`
<!-- status: fixed -->

Found 2026-08-27 on Aging_Well, inserting a 13-equation model. Word's Compare
flattens glyphs inside `m:t` AND re-fragments the runs, and the restorer keys
on the run's whole text — so a character it could otherwise put back is missed
whenever the run it lands in is not the run it came from. Measured on (A7):

    edited.docx   runs: [… '=', 'λ', '1', '+', '𝜚']
    the batch     runs: [… '=', 'λ', '1', '+ϱ']

`'+ϱ'` is a key no source run holds, so nothing matched and `tracked.build`
refused the batch on that one character — after restoring fourteen others in
the same document. The same shape hit `c_{i,−j}`, where `','` and `'−'` came
back fused as `',-'`.

**Fix:** fall back to the EQUATION when the run misses. Concatenate each
source `m:oMath`'s `m:t` text, key on its downgraded form as the run map
already does, and — for the one source equation that matches unambiguously —
walk the built equation's runs restoring character by character. The existing
one-variant-only guard carries over unchanged, so nothing is guessed.

**Workaround in use:** `Aging_Well/revision/scripts/r37_equation_vehicle.py`
merges adjacent `m:r` that already share their `m:rPr` (3,380 of them), so the
source key has the same shape Word will emit, and separately normalises
U+1D71A to U+03F1 so that glyph never needs restoring. Both are the paper
working around the library.

---

### ~~S3 — `figures` assumes the caption sits ABOVE the drawing, so a caption-BELOW paper has no addressable figures and `figures --check` can never go green~~ — FIXED 27.08, `fe6bb5d`
<!-- status: fixed -->

Found 2026-08-26 on Aging_Well, whose three figures are conceptual diagrams
with the caption in the paragraph directly AFTER the image — paragraphs 22/23,
72/73, 98/99, every one of them. `_window` scans only forward from the caption,
so every figure in the paper comes back with no drawings:

    caption_index=23 number='1' embeds=[]
    caption_index=73 number='2' embeds=[]
    caption_index=99 number='3' embeds=[]
    set_alt_text: AnchorError: 'Figure 1.' has 0 drawing(s); no image_index 0
    alt_texts: [(None, 'Picture 927649438', 'rId7', None), … x3, caption None]

    docxkit figures working.docx --check
      working.docx  (3 drawing(s), 3 without alt text)
        ! (no caption window)  [Picture 927649438]      … x3
      CHECK FAILED: 3 drawing(s) without alt text

**The gate is permanently red and the only writer that could clear it
refuses.** The count of missing alt text is correct, so the failure reads as
honest; what is not visible is that `set_alt_text` — the one function that
would fix it — raises `AnchorError` on all three captions, because it addresses
its drawing through the same forward-only window. A journal accessibility pass
on this manuscript cannot be done through docxkit at all. `(no caption window)`
also reads as "this drawing has no caption" when the caption is the very next
paragraph.

**The module knows this trap in one direction only.** Its own docstring says "A
caption sits ABOVE its figure, as it does above a table. Mapping captions to
drawings by 'the nearest one before' gets every figure wrong by one" — measured
on AFI and true there. Both conventions are in use across these papers, and
nothing in the module can tell which one it is looking at.

**Fix:** let the window look BOTH ways — the drawings between the previous
caption and this one as well as those after it — or infer the convention once
per document (which side of its captions the drawings sit on, by majority) and
apply it to every figure. Inferring it also protects the off-by-one the module
already guards: on a caption-below paper a forward window whose next drawing
happens to fall within `_DRAWING_WINDOW` paragraphs hands one caption the NEXT
figure's image, silently. Not reachable on Aging_Well, whose drawings sit 49
paragraphs apart, so that half is reasoned and not measured — but it is the
same wrong-neighbour shape `_window` was written to prevent.

**No workaround in use.** Aging_Well's figures have no alt text and `figures`
is not among the paper's six gates, so nothing was routed around — the paper
simply cannot pass `figures --check` today.

---

### ~~S2 — the one gate that RENDERS has no opinion about WHERE content lands, and the rule that would prevent it has no auditor and no CLI~~ — FIXED 26.08, `cb25235`
<!-- status: fixed -->

Reported 2026-08-24 from Aging_Well, by the author reading the paper:
"Table 1 is split across pages — this is against the house rule."

Measured on the render: Table 1 straddles sheets 8→9 and its second row
breaks MID-ROW, the Health row's grounding cell starting on 8 and finishing
on 9. Box 1 straddles 6→7 and Box 2 13→14. The manuscript carries **zero**
`w:cantSplit` and **zero** `w:keepNext` — in any of its twelve table objects,
in `build/prev.docx`, and in `Documents/faw1.docx`, the file it arrived as.
The property has never been in this paper.

Every gate is green over exactly that file: `citations`, `refstyle`,
`crossrefs --audit`, `math --check`, `footnotes --check` and `lint` all exit
0, and so does `pages --check` — over its own render of the same 27 sheets.

**Three layers, and each one is looking somewhere else.**

* A paper's `[verify]` block audits what the markup SAYS — citations,
  reference style, cross-references, maths, footnotes, structure. Layout is
  not in any of their vocabularies, and correctly so.
* `pages --check` is the only command that renders as a gate, and it checks a
  blank sheet, a numbering restart, a gap in the printed sequence, and the
  corner the page number prints in. It knows how many sheets there are and
  what each one is numbered. It does not ask what LANDED on them.
* `placement.keep_together` and `tables.house` SET the property. Nothing
  audits for its absence. `refstyle` has `audit` beside `refile`, `layout`
  and `convert`; the table rules have no equivalent — and neither module has
  a CLI subcommand, so both are reachable only from a script that imports
  them. Across every paper on this machine, three implementations of the same
  house rule exist and none of them is the toolkit's: HPPA appends
  `w:cantSplit` per row in `Code/docx_postprocess.py`, LI7 string-inserts it
  in `revision/scripts/apply_r2b.py`, and `docxkit.placement` does it
  properly for nobody.

**The measurement already exists.** `placement.Placement` records each
table's caption sheet, its last sheet and whether it split — but only when a
caller hands `place()` a renderer, which no CLI does. The gate is not a new
capability; it is an existing dataclass with no way to reach it.

**What makes this one sharper than the framing note below.** That note says
nothing renders, so nobody sees. Here the render HAPPENS, inside a command
whose whole purpose is to report what the render says, and the defect is
still invisible — because the command's questions are about the sheets and
the defect is about the content on them. A house rule enforceable only by
remembering to run a writer is a house rule that decays, and this manuscript
is the proof: its table was hand-typed by the author and dropped in whole, so
no build ever had an opportunity to style it, and eight rounds of gates since
have all been green.

**Shape of a fix.** `pages` already renders and already knows the sheets;
teach it, or a `placement --audit`, to report an exhibit that straddles a
boundary and a row with no `cantSplit`. Then a paper's `[verify]` block can
carry it, and the answer to "why was this not caught" stops being "because
nothing asked".

---

### ~~S1 — `place(render=…)` cannot find a multi-COLUMN table on the page, so its fit is never measured and `own_page` can never fire~~ — FIXED 26.08, `67459c9`
<!-- status: fixed -->

Found 2026-08-24 on Aging_Well, the first real use of `place`'s render path on
a table with more than one column. The run printed:

    Table 1: kept_together=True own_page=False caption sheet 9 -> last sheet None

`last_sheet` is `None`, and `Placement.split` is `caption_sheet is not None
and last_sheet is not None and they differ` — so a `None` reads as NOT split.
`PlacementReport.format` then prints "sheet 9, whole", `_measure_and_fix`
never escalates to `own_page`, and `rendered` is `True`, which is the report's
own claim that the fit was measured. It was not.

**The probe is built without cell separators.** `_measure_and_fix` locates the
table's last row with

    _sheet_of(sheets, _text(rows[-1]).strip()[:40], pl.caption_sheet - 1)

and `_text` joins every `w:t` under the element with nothing between them. A
row of three cells therefore yields `'Social connectednessNussbaum’s Affiliati'`,
while the render — where those cells are separate table cells — reads
`'Social connectedness Nussbaum’s Affiliat'`. `_sheet_of` normalises runs of
whitespace on both sides but cannot insert a separator that is not there, so
the needle never matches. Measured on this manuscript: the joined probe
returns `None`, the same 40 characters with one space between the cells return
sheet 9.

**So the render path is a no-op on exactly the tables it is for.** A
single-column table (a box) has no cell boundary to lose and works; every
paper table with columns silently skips the measurement and the escalation.
The properties `keep_together` writes are still written — that part is fine,
and it is what actually fixed this paper's Table 1 — but "did it work" was
answered by hand, with a separate render and a per-row probe, because the
report could not answer it.

**Fix:** join a row's CELLS with a space (or a sentinel the normaliser
collapses), not its `w:t` values — `" ".join(_text(tc) for tc in
row.findall(W + "tc"))`. `_text` itself is correct for a paragraph and is used
elsewhere for captions and anchors; the bug is using it across cells. A test
needs a two-column table whose row text only matches when the cells are
separated, which is the shape every real table has and no fixture had.

**And the report should not say "whole" about a table it could not find.**
`split` conflates "measured, whole" with "not located". A third state — or a
problem appended when `caption_sheet` is known and `last_sheet` is not —
turns a silent pass into a visible one. This is the same shape as the entry
above about `pages --check`: the check watches a proxy, and the proxy agreed.

---

### ~~S2 — a citation's link SPAN survives an author's edit to the mention, and `ingest` calls that RE-LABELLED~~ — FIXED 25.08, `924cd2e`
<!-- status: fixed -->

Found 2026-08-25 on Aging_Well. **The fourth span defect on this one paper,
and the first not caused by the grammar.** The author changed a narrative
citation to the parenthetical form — "Klimaviciute and Pestieau (2023)" to
"(Klimaviciute and Pestieau 2023)". Word kept the old span's right-hand
boundary, so the link ended up covering

    Klimaviciute and Pestieau 2023)

a closing bracket with no opening one inside the blue. Nothing refuses it:
`citations` counts a link whose anchor resolves, `refstyle` does not look at
spans, `compare`'s TEXT layer sees no character move, and `revision ingest`
files it under **RE-LABELLED** — a section that exists precisely to say
"nothing is lost, do not block the baseline". Which is right about the
anchor and silent about the span.

**Fix:** an audit that has an opinion about spans. The cheap, precise version
is bracket balance: a label carrying an unmatched `(` or `)` has reached past
its mention, and a legitimate narrative citation — "de São José et al.
(2019)", "Grossman (1972)" — always closes what it opens. That rule fires on
exactly this defect and never on the house forms. It belongs beside
`audit_links`, and `ingest`'s RE-LABELLED note should carry it: an author
edit that leaves the span unbalanced is damage wearing a re-label's clothes.

**Workaround:** `repair_paren_spans` in the same script, which replaced the
paper's `PARTICLE_SPANS` table. Note what that swap bought beyond the fix —
the old workaround named its paragraph by a hard-coded signature, the author
deleted that paragraph, and `edit_para` refused with `0 hits, need 1`, killing
the whole apparatus pass after `link_all` had run and before `write_docx`.
Second time a stale signature has cost that script a silent no-op. A repair
that reads the links needs no signature and cannot go stale.

### ~~S2 — `citations.link_all` has the SAME half-eaten pair as `crossrefs`, and reports it as a benign skip~~ — FIXED 25.08, `e56906e`
<!-- status: fixed -->

Found 2026-08-25 on Aging_Well, and it is the entry at the top of this file
with the nouns changed: the convention is a PAIR — the forward link on the
first mention, and the `<Key>txt` bookmark wrapping that mention, which the
reference entry's back-link points at — and the idempotence guard tests one
half.

The author rewrote §3's social-capability row and §9's measurement paragraph.
Word kept the hyperlinks and ate the bookmarks. `link_all` then said:

    link_all: linked 19, already 45, back-links 3, unmatched 0, skipped 7
      ! 'Grewal et al. 2006' (¶50) is already inside a link — wrapping it
        would nest one link in another, and the click goes to the outer one

That message is TRUE and reads as a non-problem — it is the guard that stops
a doubled link, and it fires on every re-run of an idempotent pass. What it
does not say is that the mention it skipped is missing the bookmark half of
its pair. The manuscript was left with three reference entries linking to
bookmarks that do not exist:

    docxkit citations PAPER.docx
      - BROKEN LINK: hyperlink to 'Coast2008txt' (¶145) — no such bookmark
      - BROKEN LINK: hyperlink to 'Grewal2006txt' (¶154) — no such bookmark
      - BROKEN LINK: hyperlink to 'Zaidi2013txt' (¶202) — no such bookmark

So the audit CAN see it and the writer cannot act on it, which is the same
shape as the `crossrefs` entry: `citations` reports three broken links,
`link_all` re-run reports "already linked" and repairs nothing, exit 0 both
times.

**Fix:** ask the two questions separately — "is the mention linked?" and
"does its `<Key>txt` bookmark exist?" — as Aging_Well's `MULTI_YEAR` table
has done for five hand-wired works since R2 was written. When the second
answer is no and the first is yes, wrap the existing link rather than
skipping. The lookup must read `footnotes.xml` and `endnotes.xml` as well as
the body: five of that paper's works are cited only in footnotes, so a
body-only search reports their bookmarks missing and prints five warnings
about a correct manuscript.

**Workaround:** `remint_backlinks` in
`Aging_Well/revision/scripts/r2_link_apparatus.py`, which re-minted all three
and is idempotent (a second run does no work). Delete it when this lands.

### ~~S2 — `crossrefs --write` cannot repair what `crossrefs --audit` reports: a half-eaten pair reads as "already linked"~~ — FIXED 25.08, `805e1ad`
<!-- status: fixed -->

Found 2026-08-24 on Aging_Well. The author rewrote the paragraph mentioning
Figure 2; Word kept the forward `<w:hyperlink w:anchor="Figure2">` and ate the
`Figure2txt` bookmark the CAPTION's back-link points at. The audit says so
plainly — `caption_only: Figure2`, `dangling: Figure2txt`, every other exhibit
clean — and the writer cannot act on it:

    docxkit crossrefs PAPER.docx --write --labels Figure,Table,Box
      linked 0, already linked 5
        ALREADY LINKED BY A WORD FIELD, which link() cannot see — check for a
        doubled link: Figure2
      written; previous version kept at PAPER_pre_crossrefs1.docx

Exit 0, a file written, nothing repaired, and the audit still reporting the
same dangle afterwards.

**The pair is two objects and the guard tests one.** `link` asks "is this
mention already linked?" — which it must, because the pass is re-run after
every author hand-back and has to be idempotent — but the convention it
maintains is a PAIR: the forward hyperlink on the first mention, and the
`<key>txt` bookmark under it that the caption links back to. Word eats them
independently. A guard keyed on the half that survived is blind to the half
that did not, and the same shape has now cost this paper twice: R2's re-run
guard read a TILED link as "already linked" on 2026-08-23 (recorded in that
script's docstring), and R11's read a surviving forward link as "already
linked" here.

**Fix:** make the presence test the PAIR, not the link — a mention that is
linked but whose `<key>txt` bookmark is missing is not "already linked", it is
half-linked, and the writer should rebuild the bookmark where the surviving
link sits. `citations.wrap_link_in_bookmark(xml, anchor, name, bid,
which="first")` already does exactly that and knows both link forms; it is
what the paper's `r31_figure2_backlink.py` had to call by hand. The
per-paper workaround should not have to exist: `link`'s guard has the audit's
own vocabulary available to it (`dangling`, `caption_only`) and is not using
it.

**A second, milder point in the same output.** "check for a doubled link" is
advice, printed where the tool has everything needed to answer it: it knows
the anchor, it can see both forms, it could say "one field, no element" or
"both — here". A warning that hands the reader a task the tool could complete
is where a repair gets skipped.

---

### S4 — four inlined copies of `comments._append_before_close`
<!-- status: fixed -->

**Fixed 2026-08-25** — `9ba39e7`. The helper moved to `_xml`, where both
modules already get their XML primitives, rather than `hygiene`
importing a private from `comments`. Four call sites now share one
writer, and the `rindex` is documented where it lives: a part's closing
tag is its LAST, and a `</Relationships>` inside a Target string would
otherwise take it.

`comments.py:176` is three lines: find the closing tag, splice before it.
`hygiene.py` writes that body out again at lines 226, 254, 719 and 727 —
twice for `</Types>` and twice for `</Relationships>` — with the
`rindex` and the two-slice concatenation each time.

Not a defect: every copy is correct today. It is filed because four is
the number at which a fifth gets written without anyone deciding to, and
because this package already has an entry (S4, `a fifth writer of CT_PPr
order`) about exactly that having happened once.

---

### S4 — `_drop_comment_anchors` re-reads every text part once per COMMENT
<!-- status: fixed -->

**Fixed 2026-08-25** — `9ba39e7`. One alternation over all the ids
instead of one pass per id: 71 ms -> 2.5 ms for forty on the same body,
and linear became near-flat. The answer is unchanged and now says so —
every listed id loses all three anchors, an unlisted one keeps its own —
with a test for the empty list, which has to return BEFORE the pattern
is built rather than after, since an empty alternation matches between
every pair of characters.

`for cid in ids: for name, xml in text_parts(parts):` — so dropping N
duplicate comments decodes `document.xml`, `footnotes.xml` and
`endnotes.xml` N times over, and runs 2N passes of the tempered-lookahead
run pattern, which is the costliest regex in the file.

Measured 2026-08-25 on a body of 300 anchored comments (0.12 MB): 1.9 ms
for one id, 18.4 ms for ten, 71.0 ms for forty — linear, as expected. On
a manuscript-sized body it is under a second. So this is a note, not a
problem: an id ALTERNATION in one pass would do the same work once, and
the reason to write it down is that the shape invites being copied, not
that anyone is waiting on it.

---

### S3 — three Relationship parsers, and they have already drifted
<!-- status: fixed -->

**Fixed 2026-08-25** — `9ba39e7`. `_resolve` normalises the separator
before resolving, as `_compare_read` already did, so a Target written
with backslashes names the same part to both readers. The wider
duplication stands: `hygiene`, `figures` and `_compare_read` still hold
three readings of one format, and one of them learning something the
others have not is how this arrived. What is closed is the drift that
existed; what remains is the shape that produced it.

`hygiene` has `_free_rid` / `_rid_for` / `_references` / `_resolve`,
`figures` has `_next_rid` / `_relationship_target`, and `_compare_read`
has `_REL_RE` / `_rel_targets`. Three readings of one part format.

They no longer agree, measured 2026-08-25:

    hygiene._resolve("_rels/.rels", "word\\footer3.xml")
      -> 'word\\footer3.xml'          # untouched
    _compare_read._rel_targets       # normalises the separator, and a
                                     # leading slash, and does both

`_resolve` handles the ABSOLUTE form — `/word/footer3.xml` resolves to
`word/footer3.xml` — and does nothing about a backslash separator, which
is legal in a Target and is what some writers emit on Windows. So a
package whose rels were written that way is read one way by `compare`
and another by every `hygiene` operation that restores or strips a part:
`restore_parts` would fail to match the relationship and report the part
orphaned, and `strip_parts` would leave it dangling.

Nothing has been seen to produce that spelling here, which is why this
is S3 and not higher. What makes it worth an entry is that the drift is
already real: the three were written to do the same job and two of them
have since learned something the third has not.

---

### S2 — `carry` restores from the CLEAN COPY, which is the file that lost the part
<!-- status: fixed -->

**Fixed 2026-08-25** — `977d78b`. The clean copy is asked first and the
BASELINE second, and what is taken from the baseline is reported apart
from what is carried across: "this build went back a version for these"
is a different sentence, and the one case where an author might want to
look. Asked second and not instead, because `restore_parts` leaves a
part that is already there alone — the revised copy is the newer
document, and this is a rescue rather than a sync. There is a test for
that ordering.

The judgment this entry flagged — restore, or respect what might be a
deliberate removal — was settled on measurement rather than on the
framing it was filed with. Across 197 manuscripts in these projects
`customXml/` holds Word's `<b:Sources>` bibliography store in 146 of
them and `docProps/custom.xml` holds `ZOTERO_PREF` in 68: the database
behind every CITATION field, and what makes Zotero recognise a document
as one it manages. Six carry an MSIP sensitivity label besides — so the
original framing was right in general and wrong about the paper it was
filed from, and the retraction that replaced it was wrong the other way.
Nobody READS these parts; the tools do, and losing them stops the
author's citation workflow with nothing red anywhere.

Against that, "the author deleted it deliberately" is thin for these
particular parts: Word barely exposes custom properties and does not
expose the data store at all. The way to MEAN it stays explicit —
`strip_parts`, and `[batch] carry` for a paper that wants something
else.

Reported 2026-08-24 from Health Capacity to Work: a rebuilt redline is
missing `docProps/custom.xml` and the `customXml/` triple against
`prev.docx`. **Sized down 2026-08-25.** This was filed saying those parts carry a
World Bank MSIP sensitivity label and an "Official Use Only" content
marking, so a promote would ship an UNLABELLED document. That framing
was withdrawn by the session that reported it: on Health Capacity to
Work `docProps/custom.xml` holds a Zotero preference and a Grammarly
document id, and no manuscript here has been shown to carry a
sensitivity label at all. The MECHANISM below is unchanged and still
worth fixing — a carried part is restored from the file that lost it —
but it loses a part a reader would not miss, not a compliance marking,
and it is an S2 for the mechanism rather than for the consequence.

Recorded here rather than quietly edited away, because the entry was
acted on while it said the other thing, and a reader of the fix should
be able to see what it was sized against.

**The mechanism is not a missing list.** `CARRIED_PARTS` already names
both — `(_hygiene.CUSTOM_XML, USER_PROPERTIES)` — and
`package.regenerated_by_word` already excludes `docProps/custom.xml` by
name, with a docstring about this exact label. What restores them is
`restore_parts(parts, revised_parts, prefixes=carry)`, and the source is
the REVISED input: the author's clean copy.

**So the carry cannot help when the clean copy is where the part went.**
The baseline still has it; the file the author saved does not; and carry
copies from the one that does not. Every gate is then green, because
every gate compares the redline against the clean copy and they agree —
about the absence.

**Shape of a fix, and the judgment in it.** Fall back to the BASELINE
for a carried part the revised copy lacks. The judgment is that
"baseline has it, revised does not" cannot be distinguished from a
deliberate removal this round: the author may have stripped the
bibliography store on purpose, and restoring it would undo that. For a
compliance marking the safe default is to restore and SAY so, leaving
`strip_parts` as the way to mean it — but that is a decision about
whose intent wins, and it should be made deliberately rather than as a
side effect of widening a prefix list.

**Related and separate:** `tracked.build` unlinks `~<stem>.building.docx`
on the failure path, so a verify-in-Word refusal leaves nothing to
inspect. That cost the S1 above a bisect rather than a look, and it cost
this report a rebuild with `verify_in_word=False` to get the artefact at
all. Keeping the file on failure is a two-line change and would have
saved both.

---

### S2 — `repkit` and `safekit` carry a FORK of `coverage_floor.py`, without the guard this one paid for
<!-- status: withdrawn -->

**Withdrawn 2026-08-25, the same day it was filed, and wrong when it was
filed.** Both copies had already been brought up to date — repkit and
safekit each carry a commit "The floors were read from a suite that
never finished", trees clean — and all three now hold
`_PYTEST_USAGE_ERROR`, the red-suite exit, `--from-json` and the
`check()` that walks FLOORS rather than the measurement. The inspection
behind this entry was accurate when it ran and stale by the time it was
written down, and nothing checked it again before it was filed.

**The design question it raised was also already answered.** This said
the alternatives were one shared module or a dependency between the
toolkits, "which is a decision about coupling three toolkits". They
carry `tools/upstream_parity.py`: it compares the LOGIC of the three
copies — normalising away formatting, docstrings, the `--cov=` package
name and the console helper — so the per-repo floors and prose stay free
to differ while the implementations cannot. It is byte-identical in both
repos, takes the package name from whichever one it sits in so the guard
cannot itself fork, and has a test called
`test_the_guard_itself_is_not_a_fork`. Both report in step.

That is a better answer than the shared module this entry was reaching
for, and it was in the tree the whole time.

**What is worth keeping from this.** Reading three files and filing what
they said is not the same as checking whether anyone had acted on it, and
an entry that names other repositories has no gate of its own to keep it
honest — `stale_figures` covers measurements, and nothing covers a claim
about a sibling checkout. When both parity checks came back "in step"
the first reading was that the GUARD was broken, which is the more
alarming story and the one that fits a stale premise. Run the tool the
other repo already has before deciding it needs one.

Found 2026-08-25 while acting on a code review of this file. `D:\repkit\
tools\coverage_floor.py` and `D:\safekit\tools\coverage_floor.py` are
copies of an older docxkit version, and both still read:

    subprocess.run([... "--cov=repkit", f"--cov-report=json:{out}"],
                   cwd=ROOT, check=False, capture_output=True)

with the `CompletedProcess` thrown away. Neither has `_PYTEST_USAGE_ERROR`,
neither has the `if done.returncode:` RED-suite exit, neither has
`--from-json`. Verified by inspection of both files.

So they reproduce today the defect docxkit already spent a debugging
session diagnosing on 2026-08-21: a suite that fails or stops half way
still writes a report, `out.exists()` is true, and per-module coverage is
compared against the floors as though the run had finished — which is how
`_table_core.py: 55.8% is below its floor of 85%` sent a reader after
tests that were there all along.

Both also predate `check()` walking the FLOORS rather than the
measurement, so a floored module missing from a partial report is not
failed there either — it is simply never asked about.

**Three copies of one file with the fix in one of them is the actual
finding.** A third hand-port would leave the same shape for the next
guard. The alternatives are one shared module that all three depend on,
or a `repkit`/`safekit` dependency on `docxkit.testing` — and that is a
decision about coupling three toolkits, which is why this is filed
rather than done.

---

### ~~S1 `hygiene.dedupe_comments` drops the comment BODY and leaves its anchors~~ — FIXED 24.08
<!-- status: fixed -->

Found 2026-08-24 on Health Capacity to Work, rebuilding batch A2b's
redline for the author. `tracked.build` raised
`com_error ... 'The file appears to be corrupted.'` from its own
`verify_in_word` step, on inputs that all open in Word individually.

**Bisected to `312c301` (08-24 02:04), which wired
`_hygiene.dedupe_comments(parts)` into `tracked.build`.** Same two inputs,
same call, two versions of docxkit:

| docxkit | comments.xml | commentsExtended / Ids / Extensible | `w:commentReference` in document.xml | Word opens it |
|---|---|---|---|---|
| `1c74e08` (08-23 23:55) | ids **212, 213** | 2 / 2 / 2 | 212, 213 | **yes** — 3057 paras, 61 revisions |
| HEAD | id **213** | 2 / 2 / 2 | **212, 213** | **no** — "appears to be corrupted" |

`dedupe_comments` deletes the duplicate `<w:comment>` element from
`word/comments.xml` and nothing else. `document.xml` keeps
`<w:commentRangeStart w:id="212"/>`, `<w:commentRangeEnd w:id="212"/>`
and `<w:commentReference w:id="212"/>`, all now pointing at a comment
that does not exist. That dangling reference is what Word refuses, and
it refuses the whole document.

**The port lost half of the code it generalised.** The function is
HCW's `revision/scripts/dedupe_comments.py` moved into the toolkit, but
only its `duplicates()` half came across. The original's `strip()` does
the other half, and its comment says why:

```python
for cid in ids:
    doc = re.sub(rf'<w:commentRangeStart w:id="{cid}"/>', "", doc)
    doc = re.sub(rf'<w:commentRangeEnd w:id="{cid}"/>', "", doc)
    # the reference sits inside a run of its own; drop the whole run, or
    # a bare <w:r> with only rPr is left behind and renders as nothing
    doc = re.sub(rf'<w:r(?: [^>]*)?>(?:(?!</w:r>).)*?'
                 rf'<w:commentReference w:id="{cid}"/>'
                 rf'(?:(?!</w:r>).)*?</w:r>', "", doc, flags=re.S)
```

**The docstring reasons about the wrong parts.** It argues, correctly,
that the orphaned `commentsExtended` / `commentsIds` /
`commentsExtensible` rows are safe because they key off paragraph ids,
and closes "Verified in Word rather than assumed." The satellite parts
were indeed verified; `document.xml` was never considered, and it is the
one that breaks. A claim of Word verification sitting above the defect
is worse than no claim.

**Why no test caught it.** `tracked.build`'s own `verify_in_word` is
exactly the gate that would — and did, once a real manuscript reached
it. The fixture that exercises `dedupe_comments` cannot have carried a
`commentReference` for the duplicate, so the function looked correct
in isolation. A duplicate comment only arises when Compare merges the
same note from BOTH inputs, which needs a baseline and a revised copy
that each carry it: that is a two-document condition, not a parts-dict
one.

**Fix:** port `strip()`'s anchor removal into `hygiene.dedupe_comments`
and take the fixture from this pair — a baseline and a revised file that
both carry one author comment on the same table. Assert on the built
redline that no `w:commentReference` / `commentRangeStart` /
`commentRangeEnd` id is absent from `comments.xml`. That invariant is
cheap and belongs in the parts gate regardless of this function.

**Blast radius:** every `tracked.build` since `312c301` on a paper whose
two Compare inputs share a comment. It is not silent — Word refuses the
file outright — but the error names nothing, and the build has already
discarded the artefact by the time it surfaces (`building` is unlinked
on the failure path), so there is nothing left to inspect. Consider
keeping `~<stem>.building.docx` when `verify` raises.

**Workaround in use:** HCW built its handback with
`PYTHONPATH=<clone of docxkit @ 1c74e08>/src`. `redline.py show` then
completed and its own `dedupe_comments.py` removed the duplicate
correctly, anchors and all.

**Fixed as diagnosed.** `_drop_comment_anchors` removes the dropped
copy's `commentRangeStart`, `commentRangeEnd` and the RUN holding its
`commentReference` — the run, because a `<w:r>` left with only its
`rPr` renders as nothing and is litter of a second kind. From every
TEXT PART rather than the body: a comment can be anchored in a footnote,
and an endnote is where several journals put the whole apparatus.

Three tests, three mutants kill_check'd, and the middle one is the
finder's own point: **removing the call reproduces the defect exactly**,
which is what makes the test worth having rather than a restatement.

**The docstring's claim was the sharpest part of the report and it is
corrected in place rather than deleted.** It said "Verified in Word
rather than assumed", and the verification was real — of the three
satellite parts it was reasoning about. It never looked at
`document.xml`. The docstring now says which parts were verified and
which was not considered, because a claim of Word verification sitting
above a defect is worse than no claim, and deleting the sentence would
lose the only record of how a true statement came to cover a false one.

**Why no fixture caught it, kept because it generalises.** Every
existing case hands this function a parts dict holding
`word/comments.xml` and nothing else, so no anchor could dangle and the
function was correct about the only part it was given. A duplicate
comment is a TWO-DOCUMENT condition — Compare merging the same note from
a baseline and a revised copy — and no parts-dict fixture can express
one. The new tests supply the body the old ones omitted.

**Done since, 2026-08-27:** the finder's suggestion that
`build` keep `~<stem>.building.docx` when `verify` raises. The failure
path unlinks it, so a Word refusal leaves nothing to inspect — which is
why this cost a bisect rather than a look. `_clear_staging` keeps the
refused build and says where it is; the unlink now happens only on the
success path, where the file has already been renamed to `out`.

*(This fix narrative had been appended to the `--sample` entry below rather than to the entry it describes; moved here 2026-08-27.)*

### ~~S3 — a `--sample` run OVERWRITES a complete one, and the figure regresses with nothing to say so~~ — FIXED 27.08, `b8fcb69`
<!-- status: fixed -->

**Fixed 2026-08-27** — `would_lose()` in `tools/mutation_session.py`,
with `--force`. A `--fresh --sample N` run whose existing session graded
MORE than N mutants is refused before the unlink, naming both numbers and
the three ways on: `--report` to read what is there, `--fresh --chunks 0`
to re-measure it whole, `--force` to discard it anyway. Only a VERDICT
counts as something to lose — an INCOMPETENT mutant is finished and is
not an answer, so a session holding nothing but those has measured
nothing and the guard stays out of the way.

**A second thing was found while fixing the first**, and it is the same
shape one level down: `--sample` handed to a RESUME does nothing at all,
because the draw is planned at `init`. Silently, so it reads as "I
sampled it" against a run that is measuring something else entirely. It
says so now.

**Four more came out of review, and the first is the guard causing the
failure it was written to prevent.** `measure_all.py` builds
`--fresh --sample N` without `--force` and never read the exit code — and
the refusal returns BEFORE the unlink, so the old database is still on
disk, `db.exists()` is still true, and the sweep walked past into
`mutation_survivors.py` and printed months-old numbers as this round's
figure. Eight of the fifty live sessions have graded more than the
`--sample 460` CONTRIBUTING calls usual (refstyle 1744, placement 1689,
edit 1411, hygiene 939, compare_diff 743, styles 604, xml2 538, pages
480), so that is the ordinary path for the most-measured modules, not a
corner of it. It reads the code now and says REFUSED instead of a number.

The other three are in the guard itself:

* **`progress()` never closed its sqlite connection**, and `--fresh`
  reads the session and then unlinks it — on Windows that is
  `WinError 32`, decided by refcount timing, on the ordinary re-sample
  path. `sample()` had the same leak. Both closed;
* **an unreadable session crashed the guard**, so `--fresh` — the
  documented way to clear a session that went wrong — could no longer
  clear the one shape it is most often needed for. There is a zero-byte
  `.mutation-_xml.sqlite` in this repo root. An unreadable session now
  answers "nothing to lose", which is true;
* **`planned` was measured and thrown away.** A whole-module plan barely
  started — 822 planned, five verdicts — was replaced by a 260 sample
  with no word said. It is a NOTE and not a refusal: no verdict is lost,
  only the planning time, and the two deserve different answers.

**This entry had been sitting under `## Fixed` since it was filed**,
unfixed, which is the misfiling the S4 in `## Open` is about.

Found 2026-08-24, while reading CONTRIBUTING's calibration table against
the live session files.

**The two disagree, and the better measurement is the one that is gone.**
CONTRIBUTING records `crossrefs.py` at **6.9% (57/822)** and says of it,
in the table's own words, that "the run is the WHOLE module rather than a
460 sample". `stale_figures --figures` now reports `crossrefs.py 9.3%
(24/259) SAMPLED 260/947`. A later `--sample 260` run replaced the
complete one: `--fresh` discards the session and the sample writes a new
plan, so 822 real mutants' worth of verdicts became 259.

**Nothing about that is visible at the time or afterwards.** The sample
completes, prints a plausible number, and the only trace of the better
run is a sentence in a document nobody diffs against the tool's output.
Until today the table did not even mark the result as a sample (see the
entry above), so the regression read as a re-measurement that happened
to move.

**Why it is S3 rather than S4.** The figures are what a round is planned
from, and this is the one failure mode that makes a figure worse over
time while looking like maintenance. Sampling is the right thing to do
on a 2757-mutant module when the question is "roughly where is this" —
it is the wrong thing to leave behind as the module's record.

**Shape of a fix.** `mutation_session` refuses `--sample N` when the
session it is about to discard graded MORE mutants than N, unless the
caller says so — the same shape as `--force` on the protocol commands. A
warning would do; the check is `ran` in the old session against the new
sample size, and both numbers are in hand before the plan is written.

Deliberately not fixed while three sweeps were running against that
tool. `measure_all` spawns a fresh `mutation_session` per module, so an
edit mid-queue reaches the modules that have not started yet, and a
mistake would take the queue down silently hours from now.

---

### ~~S3 an ANCHOR does not survive Word's Compare in either direction~~ — WARNED AT BUILD TIME 24.08
<!-- status: fixed -->

Filed 2026-08-24 from a second session's measurement on Aging_Well R24,
pasted here rather than written by the finder because this file was
modified in another tree at the time and a concurrent write loses
whichever of us saves second. The measurement is theirs.

**Symptom.** Word's Compare restores the words of a rejected deletion as
plain text and orphans the bookmark, so the link is gone. Accept-all is
fine; reject-all is not.

| the same clause, the same batch | result |
| --- | --- |
| moved §8 -> §9 (a cross-section move) | `links: False`, ladder **FAIL** |
| folded into the paragraph directly above it in §8 | `links: True`, ladder **PASS** |

Same words, same citation runs. **Only the distance changed** — Compare
diffs the adjacent case as surviving text and the distant one as delete
plus insert.

**Why it is worth an entry.** The gate is doing its job and says WHAT
broke — "Word's Compare does not rebuild a link inside a rejected
deletion" — and says nothing about what to do, and the remedy is
counter-intuitive: shorten the move. Any paper whose protocol says "move
this cited clause to §N" hits it, and it only appears at the reject-all
layer, so a batch looks completely healthy until the end of the ladder.

**Shape of a fix.** Either the ladder's message names the remedy, or
`validate` says it at BUILD time — "this deletion carries N links; a
rejection will not restore them" — which is where the author can still
act on it cheaply.

**The other half, found an hour later on the same paper, and it is what
makes this general.** Two references added, their links minted BEFORE
Word's Compare ran. The ladder refused the batch: `STRUCTURE
bookmarkStart: 146 -> 150` on reject-all. **Compare does not track a
bookmark at all** — it tracks runs — so the four anchors survived a
rejection as orphans, pointing into text that no longer existed.
Accept-all was perfect; only reject-all could see it.

So the rule is not about deletions:

> **An anchor does not survive Compare in either direction. A rejected
> deletion LOSES the anchors inside it; a rejected insertion STRANDS the
> anchors minted with it.**

Both are invisible until reject-all, and both are invisible to the
author in Word, because a bookmark has no appearance.

**And this is why the papers' convention is to mint links AFTER the
handback** — which was folklore this morning and is measured now. The
convention is not a style preference; it is the only ordering in which
the anchors and the tracking model agree.

**Worth separating from the render-gate note it was nearly filed
under.** The four instances there share a shape — a check watching a
proxy instead of the object. This is not that: the check was correct and
fired. What failed is that the OPERATION was outside what the tracking
model can represent, and no amount of checking the right object helps
when the format cannot carry the thing being checked.

**What is fixed is WHEN you find out, not the Word behaviour.** Compare
still does not track an anchor and never will; nothing here can change
that. What changed is that the deletion half is now said at build time
instead of at the end of the ladder.

`revision.links_in_deletions` — the reject-side counterpart of
`restored_bookmarks` — walks every `w:del` span in every text part and
reports the internal links inside it. `revision.build` prints the count,
the anchors, and the remedy:

> N link(s) sit inside a tracked deletion (…) — Compare does not track
> an anchor, so REJECTING one of these restores its words as plain text
> and does not rebuild the link. Accept-all is unaffected; gate 5 is
> not. … Shorten the move, or mint the links after the handback.

The remedy is in the message because it is counter-intuitive, and
because by the end of the ladder the author has a batch to throw away
and the only act available to them is the one this sentence prevents.

**The insertion half needs nothing.** Links minted before Compare runs
come back as orphaned `bookmarkStart`s, and the STRUCTURE layer already
counts those — `bookmarkStart: 146 -> 150` is how the second session
found it. That half was never silent; it was only unexplained, and the
rule above explains it.

Four tests, four mutants kill_check'd. The walk is non-greedy, so two
deletions in one paragraph do not swallow the surviving link between
them; links outside a deletion are not reported, since a check that
named every link in a manuscript would fire on every batch and be
switched off within a day; and it reads `text_parts` rather than the
body, because several journals take the whole apparatus as endnotes.

---

### ~~S2 `kill_check` shares one checkout with every other caller and takes no lock~~ — FIXED 24.08
<!-- status: fixed -->

`mutation_session` guards its worktree with a lock, and the comment on
it says why: *"Two runs measuring DIFFERENT modules still mutate one
checkout, so each reads the other's mutation and every result is suspect
— silently, because both complete and both print a plausible number. A
lock in the tool is worth more than care in the caller."*

`kill_check` has the identical hazard — one checkout, mutated and
restored once per case — and had no lock.

**It matters more than it looks, because `replay_survivors` IS
`kill_check`, called once per survivor.** A replay of `refstyle.py`'s
348 holds that checkout for twenty minutes while looking exactly like
nothing is running, which is when a quick check gets run beside it.

**Measured, on the author of the entry.** A `kill_check` run during a
replay reported **four mutants SURVIVED that its tests do kill**. Both
processes mutate and restore the same files; each reads the other's
state; both finish and print a number that looks like an answer. The
four were being read as "my new tests do not work" — which is the
expensive form of this failure, because the next move is to rewrite
tests that were right.

Everything verified against that checkout while a replay was running had
to be thrown away and redone: two rounds of `kill_check` evidence, and a
348-case replay whose verdicts could not be told apart from the
corrupted ones. **The cost of the missing lock was not a wrong answer;
it was not knowing which answers were wrong.**

**The fix is the sibling's, moved one file across.** Same shape, same
stale-holder takeover, and `_alive` imported rather than written again —
on Windows the existence check cannot be `os.kill(pid, 0)`, which
TerminateProcess would make into a check that kills the holder it asked
about.

**And the shape of the miss is one this file already records five
instances of.** The lesson was learned, written down, and implemented —
in the tool where it was learned. It was never walked to the tool beside
it, which grew a caller that runs it 348 times in a row. A change that
teaches one reader a new fact has to be walked to every other reader of
the same fact; here the other reader was the same fact's other
implementation.

---

### ~~S4 a year-labelled table COLUMN HEADER parses as a citation~~ — FIXED 24.08
<!-- status: fixed -->

Found on HCW, 2026-08-23.

**Symptom as observed.** `refstyle.audit` reports, as citations with no
reference entry:

```
     ¶220  Base 1990
     ¶964  Base 2000
```

Both are **column headers** — Table A4's and Table A6's, "Base 1990",
"Base 2000", "Max LFP". A cell whose entire content is `<Capitalised word>
<four digits>` reads as a bare author-year citation, which is a form the
scanner has to accept because narrative citations look like that.

**Why S4 and not S2.** The `ignore` hook exists for exactly this and works —
`IGNORED_LEADS | {"Base", "Max"}` clears it — and the default set already
carries `Table`, `Figure`, `Panel`, `Wave`, `Round`, `Band`, `Step`, which is
the same idea. So this is noise with a supported remedy, not a wrong answer.
It is recorded because the remedy is per-paper and the trigger is not
unusual: any exhibit with year-labelled columns produces it, and a paper that
adds such a table during a revision starts failing a gate that was green.

**Shape of a fix.** A cell that IS a citation and nothing else, in a table
whose other cells in the same row are also `<word> <year>`, is a header, not a
bibliography. Alternatively, skip the first row of a table for citation
extraction — a reference is not cited from a column head. Either would remove
the need for the per-paper list, which is where a maintained ignore set drifts
into hiding a real miss.

**Took the narrow half of the suggested fix.** Not "skip the first row
for citation extraction" — only the bare-citation FALLBACK is suppressed
there: the branch that promotes a WHOLE paragraph to a citation when
nothing else matched. Every other way of finding one still runs inside a
header, so a real citation in a header sentence (`Rates as reported by
Maestas et al. (2023)`) is found exactly as before, and a bare citation
in a BODY row — a table of studies listing its sources one per cell — is
still cross-checked. Both pinned.

The row spans are walked from each `<w:tbl>` opening tag to the next
`<w:tr>`, rather than by matching a whole table: a non-greedy
`<w:tbl>.*?</w:tbl>` closes on a NESTED table's end tag, so the rest of
the outer table reads as body and the outer header stops being one.
Tested on a nested pair. `<w:tbl\b` and not `<w:tbl`, for the reason
`_compare_read.STRUCT_TAG_RE` already records: after "tbl" comes "P" in
`<w:tblPr>`, both word characters, so an unguarded pattern opens a table
at every table's PROPERTIES — also tested, and the test fails without
the boundary.

This removes the need for the per-paper `IGNORED_LEADS | {"Base", "Max"}`,
which is the point: a maintained ignore list is where a real miss goes to
hide.

---

### ~~S4 `RefStyleReport.cited` and `.entries` are COUNTS with collection names~~ — FIXED 24.08
<!-- status: fixed -->

Found on HCW, 2026-08-23, writing T17.2's cross-check.

**Symptom as observed.** `RefStyleReport`'s fields are `issues`, `entries`,
`cited`. `issues` is a list of `Issue`; `entries` and `cited` are `int`. The
obvious code

```python
for e in report.entries:
    ...
```

raises `TypeError: 'int' object is not iterable`, and `len(report.cited)`
raises the same. Nothing in the field names distinguishes the list from the
two counts.

**Why S4.** Loud and immediate — it costs one round-trip, not a wrong answer.
Recorded because two scripts hit it in one afternoon, and because the fix is
free at the next breaking change: `n_entries` / `n_cited`, or return the
collections and let callers take `len`. The collections would be the more
useful shape: a caller checking a specific entry currently has to re-extract
the reference list itself.

**Took the second of the two fixes the entry offered, which it called the
more useful shape.** `entries` is the parsed `list[Reference]` and `cited`
the `dict[str, tuple[str, str]]` of key -> (where, snippet); the counts
are `n_entries` and `n_cited`.

The rename alone would have stopped the `TypeError`, and would have left
the actual waste in place: `audit` builds both collections and, one line
after computing them, threw them away. A caller wanting to look at an
entry re-extracted the reference list the audit had just parsed — a
second parse, by a different route, that can disagree with the first.

A test pins the capability rather than the names: a report's entries can
be read, they carry surname and year, and the two sides key ALIKE so
"cited but not listed" is answerable. Not that one nests in the other —
the fixture cites `maestas_2023` and does not list it, and that gap is
the finding, not a broken invariant. Six assertions across the suite
moved to the `n_` names.

**And the claim made here when it landed was wrong.** It said a paper
script reading `.entries` as a number would get "a loud comparison
failure". Two of Health Capacity to Work's gates interpolate it in an
f-string — `f"{report.entries} entries; {len(issues)} deviations"` — and
an f-string is not loud: since the change both had been printing all 42
`Reference` objects where a number belongs, in an audit line that still
ends "0 deviations" and so still scans as passing. It was read past
once before anyone noticed.

The check that missed it was the same on both sides of the fence: a
search for ARITHMETIC on the attributes. **Grep for the attribute, not
for what you expect to be done with it** — an f-string, a `format()`,
a log line and a JSON dump all accept a list silently, and only the
first of those looks like code that reads a number.

---

### ~~S2 Word's Compare merges a CHANGED FOOTNOTE and writes the merged string into both copies~~ — CORRECTED 24.08: it is gated twice, and was when this was filed
<!-- status: fixed -->

Found on LI7, 2026-08-23, by `word_compare.py`'s round-trip gate.

A footnote whose text changed between the two documents comes back as a
wholly-deleted copy plus a wholly-inserted copy — which is right — but
Compare writes the **same character-merged string into both**. On LI7 the
footnote reads `The decomposition in (4)` in the submitted paper and
`The decomposition in (A1.1)` in the manuscript; both copies came back as
`The decomposition in (4A1.1)`. That string is in neither document, so
accept-all and reject-all each produce text that exists nowhere, and the
redline misrepresents the footnote in both views.

Why it is S2 and not S4: **nothing a person does in Word will show it.**
Review > Next walks the body, and Simple/No Markup hides footnote balloons,
so an author adjudicating the redline never sees the footnote at all. It
was caught only because LI7's round-trip compares footnote text units
against both source documents; `docxkit.tracked.verify` and `lint` are both
clean on the corrupt file, and `compare_collateral` says nothing.

The shape is exact and machine-detectable: Compare leaves the divergent
fragment in a **run of its own** in both copies —

    <delText>The decomposition in (</delText>
    <delText>4</delText>
    <delText>A1.1) weights each component ...</delText>

so the repair is "the deletion keeps the old fragment and drops the new
one; the insertion does the reverse", with no run added or removed and no
revision resolved. Per-paper workaround:
`Loneliness Index/revision/scripts/fix_compare_footnote_merge.py`.

Suggested home: a `compare_collateral` check that every wholly-inserted
footnote's text appears in the revised document and every wholly-deleted
one's appears in the original — it is the same "did Compare carry this
faithfully?" question that function already asks of parts, bookmarks and
links, and a footnote is the one place a person cannot verify by eye.

**The Word behaviour above is real and the description is exact. The
claim that nothing catches it is wrong**, and is corrected here rather
than quietly deleted, because the entry was filed as an S2 on the
strength of it and a reader coming back would otherwise act on it.

**Measured 2026-08-24**, by reconstructing the shape the entry describes
and running the gates over it. Both fire, on all four spellings the
description admits — the fragments as one run with three children or as
a run each, the two copies in one paragraph or in two:

* `tracked.untracked` — reject-all against the ORIGINAL — reports
  `footnotes ¶1: baseline 'The decomposition in (4)...' batch
  'The decomposition in (4A1.1)...'`;
* `tracked.unaccepted` — accept-all against the CLEAN COPY — reports
  `intended '(A1.1)...' accepted '(4A1.1)...'`.

Neither is advisory. `tracked.build` REFUSES on both by default, and
`revision.build` leaves `accept_check` ON precisely because "a redline
whose accepted text is not the clean copy is not a batch to hand back".

**And they are not new.** `untracked` landed 2026-08-15 and `unaccepted`
2026-08-19; this entry was filed on the 23rd. So the gates existed while
LI7 shipped the corrupt footnote.

**What the entry got right, and it is the useful half:** `verify`,
`lint` and `compare_collateral` ARE all clean on such a file, and a
person cannot see it — Review > Next walks the body and Simple Markup
hides footnote balloons. The mistake was reading "the three checks I
looked at say nothing" as "nothing says anything", which is the same
shape as an all-zero audit being read as a pass. A list of what was
checked is not a list of what exists.

Five tests now pin the shape in `test_tracked_build.py`, so the two
gates cannot lose it silently. No new check was added: adding one for a
defect that is already refused twice would be code written against a
misreading.

**What remains open belongs to the PAPER, not to this package.** Why
LI7's build did not refuse is unanswerable from here — the file is in
the paper's folder, and the candidates are a redline built before 15.08,
a `force=True`, or a flow that called neither gate. Worth ten minutes
with the actual file, and nothing in docxkit changes either way.

---

### ~~S3 RE-OPENED: the heredoc backslash defect is marked FIXED, but nothing gates the BASH path~~ — FIXED 24.08
<!-- status: fixed -->

Re-opened 2026-08-23. The entry below in `## Fixed`
("~~S3 the agent's Bash heredocs EAT BACKSLASHES~~ — FIXED 21.08") records
four occurrences and closes on two mitigations: PowerShell does not mangle,
and `ruff PLE2510` backstops a mangled control character *once the payload is
written to a `.py` file*. **Neither covers the case that has now caused the
most damage**, and calling the entry FIXED is what let it be walked into
again — twice, ten minutes apart, by an agent that had read this file.

**Fifth and sixth occurrences, measured on `tests/test_revision.py`.** The
payload was not code and not a search anchor; it was the REPLACEMENT text of
a `str.replace`, `"\\\\\\n        "`, meant to insert a Python line
continuation. It arrived halved, so the replacement wrote the two characters
backslash-n into the source. Three lines damaged — loud, a syntax error,
cheap.

The sixth is the expensive one: **the repair was a second heredoc with the
same flaw**, and its search string arrived halved too, so instead of matching
literal backslash-n it matched every REAL newline followed by indentation.
387 of them, rewritten as literal backslash-n. 2821 lines collapsed to 2574,
1113 E501s, `ast.parse` failing at line 58.

**Why the existing mitigations did not fire.**

* `assert old in s` — the entry's own "actual mitigation" — cannot help: the
  search string *did* match. It matched 387 things it was never meant to.
* `PLE2510` never ran: the mangling happened inside the running script's
  string literals, not in anything written to a `.py` file. The corrupted
  file was the OUTPUT.
* PowerShell not mangling is not a gate. Nothing routes patch scripts there,
  and `python - <<'PY'` remains the obvious thing to type.

**Why it cost more than a file.** `D:\docxkit` was being edited by a second
Claude session at the time, with uncommitted work in that same file. It had
to stop, snapshot the corruption and wait. A tooling trap that costs one
agent a minute costs two agents an hour when the file is shared.

**What made recovery possible, and it should be the documented procedure:**
diagnose read-only first and find a property that SEPARATES the damage from
the legitimate text, rather than fixing forward with more replaces. Here
`git show HEAD:<file>` proved all 7 real `\n` escapes are followed by a quote
or a letter and never by a space, while all 387 damaged sites are followed by
indentation — so the repair was provable rather than hopeful. Genuine `\` +
newline continuations then need the backslash restored by hand; plain
newlines do not.

**Fix shape. Stated as a rule about the PAYLOAD, because "be careful" has
now failed three times in one session.** There is no safe way to put a
backslash through a Bash heredoc, so the rule is not care but avoidance:
**a payload containing a backslash never goes through a heredoc at all.**
Write it to a file with the Write tool and execute the file; for a handful
of lines use an Edit call, which touches no shell. Recorded for this agent
in `feedback_never_patch_via_heredoc.md`.

**And "patch script" is too narrow a scope, which is how the third one
happened.** That payload was not a patch script: it was ordinary source
being inserted, carrying `\n` inside an f-string. Same converter, same
halving, different clothes. The rule is about backslashes in a heredoc,
not about what the heredoc is for.

**The running cost, since a measurement is what gets an entry acted on.**
Three incidents on 2026-08-23/24, across two agents sharing one tree:

| when | what | cost |
|---|---|---|
| 19:47 | `tests/test_revision.py` — a `str.replace` payload | 387 real newlines rewritten as literal `\n`, file collapsed 2821 → 2574 lines, 1113 lint errors, `ast.parse` failing; the second session had to stop, snapshot and wait |
| — | two further patch attempts by the second session | both failed the same way |
| 00:38 | `src/docxkit/cli.py` — an f-string in inserted source | two `\n` became real newlines, unterminated literal, **the whole package failed to import**, so every suite in the shared tree was red until repaired |

**If a gate is wanted**, the candidate is a hook that refuses a
`python - <<` invocation whose payload contains a backslash. The recovery
procedure, when it happens anyway, is in the entry above: diagnose
read-only, find a property that SEPARATES the damage from legitimate text,
and prove it against `git show HEAD:<file>` before writing anything.

**The gate exists: `tools/heredoc_guard.py`, a `PreToolUse` hook on
Bash, registered in `.claude/settings.json`.** It reads the tool call on
stdin and exits 2 — the blocking status — when a heredoc BODY contains a
backslash. Windows paths in the command itself are untouched, because
only text between the delimiters is examined; `python "C:\Users\..."`
is the most common command in this environment and a guard that refused
it would be switched off within the hour. Ten tests, including the two
that matter for a guard: that it does not block the Write tool (the
remedy — a guard that judged it would refuse the way out of its own
refusal) and that malformed stdin returns 0 rather than raising, since
one bad frame must not cost a shell.

**And the mechanism, MEASURED rather than inherited (24.08).** This
entry asserted there is no safe way to put a backslash through a
heredoc. True, and now precise. The probe was `<<'PY'` — POSIX-QUOTED,
which is specified to deliver its body untouched:

| written in the heredoc | what Python received |
| --- | --- |
| `\\n` | a newline |
| `\\\\` | one backslash |
| `\t` | a TAB (unchanged) |
| `\\t` | a TAB |

**A doubled backslash is halved; a single `\x` passes through.** That is
unquoted-heredoc behaviour applied to a quoted one, so the quoting is
being lost before the shell sees it and no spelling inside the heredoc
can recover it. It also explains why the trap keeps winning: `"\n"` in a
payload is FINE, and `"\\n"` — the spelling you reach for the moment
you want a literal backslash-n, which is exactly what a patch script
rewriting escapes is doing — is silently wrong.

**A seventh occurrence, found while reading this entry.** Same day,
same agent, same session: a heredoc meant to DELETE a no-op
`out.replace("\\n", " ")` from a test had its search string halved, so
it matched nothing and the replace stayed. It shipped in a pushed
commit, passing every gate, because a `.replace` of a literal
backslash-n against text that has none is a no-op that reads as
deliberate. Removed. Nothing broke — which is the point: the sixth
occurrence was loud and cost an hour, the seventh was silent and would
have stayed for ever.

**What the gate does not cover.** Hook configuration is read when a
session starts, so the session that wrote this one is not itself
guarded; and the hook is project-scoped, so the trap is still live in
the paper repositories, where the payloads are longer and the files are
manuscripts. Promoting it to the user-level settings is a change to the
environment rather than to this package, and is the author's call rather
than an agent's.

---

### ~~S1 every gate reads the WORKING copy, so a commit missing a definition was green here and broken everywhere else~~ — FIXED 24.08
<!-- status: fixed -->

`main()` called `_build_args(r)` twice; the definition was never staged.
Two commits sat in local history that way — f3a6fd4..01b1c7e — and
anyone who had only the commit would have got `NameError` from `docxkit
<anything>`, while ruff, mypy, pyright, 4,846 tests and the coverage
floor all passed here: every one of them reading the file on disk, which
had the function. The tip was repaired before the branch was pushed, so
no clone was ever actually broken; that was luck about timing, not about
the gates, and the window was two commits wide.

**The blast radius was first written up here as "and both were pushed",
which was wrong, and wrong for a reason worth keeping.** The check was
`git log --oneline origin/main..HEAD 2>/dev/null`, which printed
nothing. The branch is `master`. `origin/main` does not exist, so git
exited fatal and `2>/dev/null` ate the sentence saying so — and empty
output from a suppressed error reads exactly like empty output from a
true answer. It is the pipeline-exit-code lesson this file records three
instances of, wearing a different hat: a status was discarded and the
remaining output was believed. Never `2>/dev/null` a command whose
EMPTINESS is the answer.

**What makes it a gate defect rather than a slip.** The split-staging
that caused it is unavoidable in a working tree two sessions share: you
stage your files, not the tree. What was missing is anything that ever
looked at the RESULT. "Does this commit stand alone" was already in the
routine and was already being run — on the commit about to be made.
Nobody re-runs it on the commit made twenty minutes ago, and that is the
one that had the hole.

**The tell was visible and dismissed.** Two `test_compare` CLI tests
failed in the isolated tree and passed live. That reads as "my
verification harness is off" — a temp tree with no `.git` genuinely does
fail eight of this suite's tests, which had trained the reflex. The
difference is that those eight fail for a NAMED reason. `NameError:
name '_build_args' is not defined` names nothing about the harness.

**`tools/verify_committed.py`**, sixth gate. It exports a ref with `git
archive` — not `checkout-index`, which reads the index, where a staged
fix would hide the defect it is looking for — and asks two questions of
the export: does every module import, and does the CLI build its
parsers. The second is the one that matters, because `_build_args` is
looked up while `main()` declares subcommands, so the module imported
perfectly and only an invocation failed.

Run backwards over the history it dates the window exactly:
f3a6fd4..01b1c7e, clean either side. Its own test asserts the property
that would silently disappear if `git archive` were ever swapped for a
read of the tree: a definition present in the working copy must NOT make
the broken commit pass.

**Cheap, and last in the chain on purpose.** It reports on HEAD rather
than on the work in hand, and a broken HEAD must not stand between an
author and the lint error they are actually there to fix.

---

### ~~S4 `ship` RE-DECLARES `build`'s flags, so every flag added to `build` is an AttributeError on `ship` until someone remembers~~ — FIXED 24.08
<!-- status: fixed -->

Found 2026-08-23, immediately, by adding one flag.

`cli.py`'s `ship` subparser repeats `build`'s arguments by hand
(`--allow-math-resolve`, `--keep-math`, `--allow-pending-baseline`,
`--force`, …) and `cmd_revision_ship` delegates to `cmd_revision_build`,
which reads `args.<flag>`. Adding `--allow-stale-baseline` to `build` alone
made every `ship` invocation die with

```
AttributeError: 'Namespace' object has no attribute 'allow_stale_baseline'.
Did you mean: 'allow_pending_baseline'?
```

— four tests, and it would have been every real `ship` run. It is loud rather
than silent, which is the only reason this is S4: the failure is total and
immediate, not a wrong answer.

**Why it will happen again.** This is the "a change that teaches one reader a
new fact has to be walked to every other reader" shape this file already
records five instances of. The two parsers are one parser written twice.

**Shape of a fix.** Build the shared arguments once —
`_build_args(parser)` called by both subparsers — so a flag cannot be added
to one and not the other. Cheap, and it removes the duplication rather than
documenting it.

**Workaround in use:** the flag was added to `ship` by hand, with a comment
saying why the line exists.

**What changed.** `_build_args(parser)` — one declaration, called by
both subparsers. The two were one parser written twice, so the walk this
file keeps recording ("a change that teaches one reader a new fact has
to be walked to every other reader") can be DELETED here rather than
remembered.

`ship` also gained the help text it never had: its copy declared the
flags bare, so `docxkit revision ship --help` listed `--keep-math` and
`--allow-pending-baseline` with no explanation of either.

Two tests, and the second is the one that matters. The first asserts the
two parsers accept the same flags — which a second copy would pass on
the day it was written and fail a week later. The second asserts there
is only ONE declaration: `main`'s source calls `_build_args(r)` twice
and names no flag itself.

---

### ~~S4 `MATH_DOWNGRADES` knows the MINUS but not the PRIME, so a prime-bearing equation cannot be built~~ — FIXED 24.08
<!-- status: fixed -->

Found on Aging_Well, 2026-08-23, on the same batch.

`hygiene.MATH_DOWNGRADES` is `{"−": "-"}`. Word's accept path also
downgrades **U+2032 PRIME to an ASCII apostrophe**, and nothing puts it
back, so `revision build` refuses:

```
accepting every revision does not reproduce the EQUATIONS of edited.docx:
  equation 26: '…=λκ′(a)' in the clean copy, "…=λκ'(a)" accepted
```

**Why S4 and not S2.** It is loud — the build refuses rather than
shipping a wrong glyph, which is the gate working. The cost is that a
paper writing `\kappa'(a)`, `f'(x)` or any other primed derivative
cannot build at all until someone works out that the prime is the
problem, and the message names the equation without naming the
character.

**Fix shape.** Add `"′": "'"` to `MATH_DOWNGRADES`. The machinery around
it already handles the ambiguity conservatively — a run is repaired only
when its exact text appears in a source with the glyph put back, and an
ambiguous key is dropped — and an apostrophe inside maths is about as
legitimate as a hyphen is, so the same reasoning applies unchanged. A
test that fails without it: build a redline over an equation containing
U+2032 and assert the accepted copy still holds it.

**Workaround in use:** R20 writes the derivative as a fraction instead
of using a prime, recorded in `Aging_Well/revision/paper.toml`.

**What changed.** `MATH_DOWNGRADES = {"−": "-", "′": "'"}`. One entry, as
the entry said — the machinery around it already handles the ambiguity
conservatively, repairing a run only when its exact text appears in a
source with the glyph put back.

Fixed together with the refusal that reports it, because the two are one
experience: the build now both repairs the prime and, when a glyph it
does NOT know turns up, says which character it was.

---

### ~~S4 `crossrefs --labels` REPLACES the default labels, so a narrowed run prints a clean report about the exhibits it did not look at~~ — FIXED 24.08
<!-- status: fixed -->

Found 2026-08-23 by the other session, on a paper tonight, and passed to me
because the flag is mine (21.08). It filed the finding in that paper's config
as a gotcha; recording it here as well, because a note in one paper's config
is invisible to the next paper — and this is the shape this file already has
a name for, a number that cannot tell two states apart.

**Measured on one manuscript**, three runs, three clean reports:

```
docxkit crossrefs PAPER.docx --audit                  ->  4 linked
docxkit crossrefs PAPER.docx --audit --labels Box     ->  2 linked
docxkit crossrefs PAPER.docx --audit --labels Figure,Table,Box  ->  6 linked
```

Six is the real number. The first run missed the Boxes because `Box` is not
in the defaults; the second missed the Figures and Tables because naming one
label REPLACED the defaults rather than adding to them. Neither said so.

**Why S4 and not S2.** Replacement is a defensible reading of `--labels` —
"these are the labels this paper uses" — and the flag's own help spells the
full form (`Figure,Table,Box`). The defect is not the semantics, it is the
SILENCE: a run that examined one of three exhibit kinds prints the same shape
of clean report as a run that examined all three, and `unlinked 0` reads as
"nothing is unlinked" rather than "nothing I looked at".

**Shape of a fix.** Say what was examined, always — `4 linked · labels:
Figure, Table` — so a narrowed run is legible as narrowed. Optionally warn
when the document contains caption-shaped paragraphs whose label is NOT in
the set being audited: that is the case where the reader wanted the default
and got a subset, and the document already knows.

**Workaround in use:** name every label the paper uses, every time; the
paper's config records which ones those are.

**What changed.** The audit header names the labels it examined:
`PAPER.docx   labels: Figure, Table, Box`. The semantics of `--labels`
are untouched — replacement is a defensible reading, and the help text
spells the full form — because the defect was never the semantics. It
was that a run which examined one exhibit kind of three printed the same
shape of clean report as a run that examined all three, so `0 unlinked`
read as "nothing is unlinked" rather than "nothing I looked at".

---

### ~~S4 the unbalanced-field integrity flag names an EMPTY paragraph for the orphan half, so the flag cannot be located~~ — FIXED 24.08
<!-- status: fixed -->

Found on HCW, 2026-08-23, on every compare run in the batch.

**Symptom as observed.** The BUILT-DOC INTEGRITY gate prints

```
** BUILT: unbalanced field (+1) in 'Figure 3. Mortality and LFP, Poland and '
** BUILT: unbalanced field (-1) in ''
```

The `+1` line is useful: a caption opens a `SEQ Figure \* ARABIC` field. The
`-1` line names `''`, because the orphan `fldChar end` sits in the empty
paragraph after the caption — which is the normal shape of this defect, since
a field that spills does so into the paragraph next door, and the paragraph
next door is a spacer or a section break with no text in it. So the half that
tells you WHERE the field is broken is the half that prints nothing.

**Why S4.** It is a real gate that fires correctly and is simply hard to act
on. Both halves of one defect were locatable here only by writing a script to
count `fldCharType` per paragraph.

**Shape of a fix.** When a paragraph has no visible text, name it by
position — its index, or the previous non-empty paragraph plus "the paragraph
after" — the way the TEXT layer already says `in (footnotes, table 3 r2c1)`.
Better still, pair the two halves: `+1 in 'Figure 3. …' / -1 two paragraphs
later` is one defect, not two flags.

**What changed.** An empty paragraph is named by POSITION and by the
last paragraph that has text: `unbalanced field (-1) in the empty
paragraph 2, after 'Figure 3. Mortality and LFP…'`. That is the same
answer the TEXT layer gives when it says `in (footnotes, table 3
r2c1)` — the flag was correct all along and simply unusable.

The two halves are still two lines rather than one paired finding. That
was the entry's "better still", and it is not done: pairing them needs a
rule for which `+1` a given `-1` belongs to, and a field can spill more
than one paragraph. Both lines now name a place, which is what made the
pairing worth having.

---

### ~~S2 `tracked.build` loses `<w:trackRevisions/>` and DUPLICATES a comment present in both inputs~~ — FIXED 24.08
<!-- status: fixed -->

Found 2026-08-24 on Health_Capacity_to_Work. `build` already carries
`docProps/core.xml` and `custom.xml` back because Compare regenerates them
(`hygiene.carry_properties`, entry in `## Fixed`). Two more things Compare
rewrites, both reaching the author:

**1. Track Changes comes back OFF.** A batch had switched `<w:trackRevisions/>`
on deliberately, because it had never been set in this paper and the author's
own typing was therefore not being recorded. It did not survive the next round:
Compare writes a fresh `settings.xml`, and the accepted truth had it off again.
The author edits a "tracked" manuscript and nothing is tracked.

Note for whoever fixes this: **the element Word reads is `w:trackRevisions`,
not the schema's `w:trackChanges`.** Writing `<w:trackChanges/>` leaves Word
reporting Track Changes OFF, with no error and no complaint about an unknown
element — measured, twice, in two different sessions. In `CT_Settings` order it
sits after `w:revisionView` and before `w:defaultTabStop`.

**2. A comment in BOTH inputs is kept TWICE.** The baseline has the author's
comment because they wrote it; the clean master has it because an earlier round
restored it after a Compare dropped it. Compare does not merge the two — the
redline hands the author their own note duplicated on the same table, with no
way to tell which copy to resolve. Word confirms `Comments.Count = 2`.

Neither end is wrong, which is why this belongs in `build` rather than in either
input: the comment SHOULD be in the baseline AND in the clean master.

**Shape of a fix.** After the compare, in `build`: insert `<w:trackRevisions/>`
into `settings.xml` if absent (behind a flag if some caller wants it off), and
drop comments duplicating one already present, matching on **author +
whitespace-collapsed text** — never on id, which Compare renumbers, and never on
anchor, since the two copies land on different runs of one paragraph. Leaving
the `commentsExtended` / `commentsIds` / `commentsExtensible` entries orphaned
is safe: they key off paragraph ids, and Word opens, counts and threads the
survivor correctly. Verified in Word rather than assumed.

**Workaround to retire:** `Health_Capacity_to_Work/revision/scripts/dedupe_comments.py`
and the settings-patch block in that paper's `revision/scripts/redline.py`.

**What changed.** `hygiene.keep_tracking` and `hygiene.dedupe_comments`,
called from `build` through `_carry_rewrites` — which exists as a
function because adding the two inline pushed `build` past the
complexity ceiling the debt list pins it at, and that list may only
shrink.

They sit beside `carry_properties` and `restore_parts` for a reason
worth naming: `compare_collateral` answers *what is MISSING*, and
neither of these is missing. `settings.xml` is present and rebuilt with
Track Changes off; the comments part is present and carrying one note
twice. A gate that asks only about absence cannot see a rewrite.

* **Track Changes** is carried only when the ORIGINAL had it — turning
  it on for a paper that chose otherwise would be this tool making an
  editorial decision. The element written is `w:trackRevisions`, and
  there is a test asserting that `trackChanges` never appears: the
  entry's measurement, twice in two sessions, is that Word reads the
  first and silently ignores the second. It is inserted after
  `w:revisionView` where `CT_Settings` says it belongs, with a test on
  the ordering, because Word refuses a settings part out of sequence.
* **Duplicate comments** match on author plus whitespace-collapsed
  text. Two authors saying the same thing are two comments; the same
  author's note arriving from both inputs is one. Never on id, which
  Compare renumbers — there is a test with ids 7 and 9014 — and never
  on anchor, since the copies land on different runs of one paragraph.

**Workarounds to retire:** `dedupe_comments.py` and the settings-patch
block in `redline.py`, both in `Health_Capacity_to_Work/revision/scripts/`.
Not deleted here; that paper has a session in it.

---

### ~~S3 nothing checks that a caption's NUMBER is a FIELD — a text-reading numbering audit passed a manuscript that prints two "Table 3"s and no "Table 8"~~ — FIXED 24.08
<!-- status: fixed -->

Found 2026-08-24 on Health_Capacity_to_Work, by eye, in a PDF exported for an
unrelated reason.

Body captions numbered themselves with `SEQ Table \\* ARABIC`. One caption —
Table 3's — carried a plain-text "3" instead. The counter never advanced there,
so every caption after it evaluated one low: Table 4 printed as 3, Table 8 as 7.
**The manuscript prints two "Table 3"s and has no "Table 8".**

**Every check said the numbering was perfect**, including the paper's own
`numbering_check` (`Table 8 captions: 1..8 contiguous, MISMATCHES: 0`),
`crossrefs.audit` (18 linked, 0 misnamed) and `renumber`. All of them read the
caption's visible text — which for a field is the CACHED result Word wrote the
last time it rendered, not what it will compute next time. `docxkit compare`'s
INTEGRITY layer saw only a related symptom elsewhere (an unbalanced field).

This is the S3 shape exactly: a gate that cannot fail on the defect it exists to
catch, and which reports a confident zero while the document is wrong.

**Shape of a fix.** Cheap and text-only, no Word needed: for each label series,
assert every caption carries `SEQ <label>` in its `instrText`. A series where
one caption lacks the field is this defect, and the missing one is the culprit.
Worth folding into `crossrefs.audit` as a `fieldless` bucket, or a small
`fields.audit(xml)`. Note that the ANNEX captions here are legitimately literal
(`Table A1`…`A6` carry no field), so the rule is per-series, not global.

Also worth flagging while in there: a `SEQ` field whose `fldChar end` sits in
the FOLLOWING paragraph. It still evaluates correctly and shows up only as an
unbalanced-field integrity flag, which reads as noise next to a real one.

**Repair technique, for whoever writes the fixer:** harvest a working caption's
five runs (begin, instrText, separate, cached result, end) and swap the cached
digit — do not hand-write the field. The ones here carry `<w:i/>` on the fldChar
runs, which no specification requires and Word put there anyway. Gate the repair
on the whole document's visible text being **byte-identical** before and after:
the pass must make the field agree with the number already displayed, never move
a number.

**What changed.** `crossrefs.fieldless(xml, labels=...)`, folded into
`audit` as a bucket and gating `crossrefs --audit`'s exit code beside
`dangling` and `misplaced_anchor`. Text-only, no Word needed: it reads
the field INSTRUCTION — `SEQ <label>` in an `instrText` — and never the
caption's visible text, which for a field is the cached result of the
last render and is precisely what made every other check agree with
itself.

**Per SERIES, as the entry asked.** An annex numbers its exhibits
literally on purpose, so the comparison is against the other captions
with the same label and the same KIND of number: `Table A1`…`A6` all
literal is a house style, `Table 1..4` with one typed is this bug, and
the odd one out is named. A series of one is not a finding — there is
nothing to be inconsistent with.

Verified on HCW's exact shape (four body captions, one of them typed,
plus a literal annex pair): one finding, naming Table 3, and the annex
silent. A test asserts what made this invisible — the visible text of a
typed caption and a computed one is byte-identical.

The repair technique in the entry above is deliberately NOT implemented:
swapping a cached digit is a per-document edit that has to be gated on
the whole document's visible text being unchanged, and the gate that
finds the defect is the part every paper needs.

---

### ~~S3 `word.export_pdf` cannot render MARKUP, so a redline renders clean and looks like a batch that marked nothing~~ — FIXED 24.08
<!-- status: fixed -->

Found 2026-08-24 on Health_Capacity_to_Work, while checking that a handed-back
redline actually showed the author what changed.

`export_pdf` calls `ExportAsFixedFormat` without `Item`, which defaults to
`wdExportDocumentContent` (0) — the document WITHOUT revision marks. Export a
file carrying 187 `w:ins` and 59 `w:del` and the PDF is **clean text**: no
strikethrough, no underline, no change bars. Nothing says markup was omitted.

Why that is S3 rather than cosmetic: this module's own advice is to verify
visually with `export_pdf`, because Word keeps OMML and LibreOffice does not
(`feedback_verify_omml_word_pdf`, and the docstring says so). On a redline that
verification **returns a false negative** — the page looks right, and the one
thing you were checking, whether the revisions are there and land where you
think, is exactly what was suppressed. It cost twenty minutes of hunting a
non-existent bug: Word reported `Revisions.Count = 59` and `TrackRevisions =
True`, `settings.xml` had no `w:revisionView` hiding anything, and the render
still showed nothing.

**Reproduced and worked around** by calling COM directly:

```python
doc.ExportAsFixedFormat(OutputFileName=str(out), ExportFormat=17,
                        Item=7, From=8, To=9, Range=3)   # 7 = with markup
```

`Item=7` is `wdExportDocumentWithMarkup` and the marks appear where they should.

**Shape of a fix.** `export_pdf(..., markup: bool = False)` passing `Item=7`.
Worth pairing with a note beside `locate`'s existing "run against the CLEAN
build" warning — same trap, opposite direction: `locate` is wrong on a redline
because deleted text is still laid out, `export_pdf` is wrong on a redline
because the marks are dropped.

**Read with "Not three defects — one missing gate: nothing renders by
default" above.** That entry proposes a render step in `revision validate` or a
paper's `[verify]` block, on the grounds that a person looking at a page is the
only instrument that catches a whole class of maths defects. If that step is
built on `export_pdf` as it stands, it will be **blind on every redline** — the
file the author is actually handed — so this needs fixing first or the new gate
inherits the false negative.

### ~~S4 a `Table` handle is invalidated by editing ANY table, so the natural "fetch the batch, style each" loop always raises on its second pass~~ — FIXED 27.08, `1115816`
<!-- status: fixed -->

**Fixed 2026-08-27** — a `Table` carries the hash of its OWN bytes
alongside the hash of the document, and `_fresh` asks whether those bytes
are still at those offsets. If they are, the edit lay elsewhere, the
handle still means what it meant, and it is returned with the document
hash refreshed; all thirteen call sites bind what it gives back. The
reverse-order loop `tables_after` invites now works as written, which is
the defect as filed.

**The first draft of this fix was wrong, and the way it was wrong is the
part worth keeping.** It re-resolved a stale handle by SEARCHING the
document for its bytes, guarded on the match being unique. Review
reproduced two silent wrong answers against the live tree:

* **the edit that creates the staleness also defeats the uniqueness
  check.** Two identical panels, edit one, and the OTHER is now the only
  byte-match — so the second call rewrote the wrong panel, with no error,
  where the old code had raised. Guarding on "exactly one match" cannot
  see this, because there is exactly one match;
* **a handle from a DIFFERENT document bound and edited it.** The
  whole-document hash was the only thing tying a `Table` to the file it
  came from, and a content search throws that away. A clean build and its
  redline are two strings in one scope.

Both are one mistake: **content is not identity when content is exactly
what an edit changes.** The entry's own wording had the narrower rule all
along — *re-resolve when the edit provably lies after it* — and "the
bytes are still here" is that proof, with no search, in O(1). A table
that MOVED is refused again, which is what the test that had been
rewritten to assert the lookup goes back to asserting.

`grid_columns` and `grid_rows` gained the freshness check they never
had — the only two `(xml, table)` entry points without one. Survivable
while a handle died on the first edit anywhere; not survivable once one
legitimately outlives an edit to another table.

`tools/mutate.py`'s curated sabotage for this very guard had been
anchored on a line this change rewrote out of the module, so it was
skipped — and `mutate.py` exits 1 on a skip, silently, since nothing runs
it. Re-anchored, and split in two: one mutation per question the guard
now asks.

`tables_after`'s docstring states the true rule, since its return type is
what suggested the broken loop: an edit to ANOTHER table is fine, an edit
to THIS one means re-read, and a batch runs in reverse document order.

**This entry too had been sitting under `## Fixed` while open.**

Found 2026-08-24 on Health_Capacity_to_Work, styling one caption's TWO panels.

```python
for t in reversed(tables.tables_after(xml, "Table 9.", count=2)):
    xml, _ = tables.house(xml, t)          # AnchorError on the second iteration
```

`_fresh` compares a whole-document fingerprint, so editing the LATER table
invalidates the handle on the EARLIER one too — even though nothing before it
moved, and even though the loop was deliberately written in reverse for exactly
that reason. `tables_after` invites this by returning a LIST: the API hands you
several handles and only the first is usable.

The message ("re-read with `read_all()`/`by_caption()` after every edit") is
right and still did not prevent it — it reads as "after every edit to THIS
table", and the fix people reach for is re-locating once per pass, which also
fails. What works is re-locating before **every single call**:

```python
for pas in (tables.house, tables.fit_columns):
    for i in (1, 0):
        xml, rep = pas(xml, tables.tables_after(xml, "Table 9.", count=2)[i])
```

**Shape of a fix.** Either re-resolve a stale handle by identity when the edit
provably lies after it, or say the true rule in the message — *"a handle is
invalid after ANY edit to the part, not just to this table; re-locate before
each call"* — and note it on `tables_after`, whose return type is what suggests
the broken loop.

### Checked and NOT defects — recorded so they are not re-derived
<!-- status: not-a-defect -->

Both were suspected in an earlier session on this manuscript and re-measured
on 2026-08-24 against the current tree:

* **`revisions.accept` and row-level revision marks.** An earlier note had it
  returning Table A3 at 14 rows where Word's `AcceptAll` gives 46. It does not
  reproduce: on a 19-table redline (187 insertions, 59 deletions) `accept`
  reproduces the clean master's table count, every table's row count, and the
  full visible text exactly.
* **`by_caption` after a Flat-OPC round-trip.** An earlier note had it reporting
  Table A2 at "5 rows" against Word's 29. It is correct — `len(table.rows[0])`
  is a CELL count, and row 0 of these tables is a GROUPED header (`gridSpan`),
  so it is legitimately 2 cells over 6 columns and 3 over 7. Word agrees with
  `by_caption` on 29x6 and 46x7. **Read a data row, not row 0, when you want a
  column count.**

**What changed.** `export_pdf(..., markup=False)`. `Item` is passed by
KEYWORD and only when markup is wanted: reaching it positionally would
mean spelling out every argument before it on both paths, so the
ordinary render — the one every equation check makes — would change
shape to carry a default it already had. Two existing tests pin that
shape, and they still pass unmodified.

The default stays False deliberately. The other caller of this is the
equation check, where the accepted view IS the page a reader gets;
`markup=True` belongs to whoever is verifying a redline.

**Verified on a real package**, one insertion and one deletion:

```
markup=False   inserted text on the page: True   deleted text shown: False
markup=True    inserted text on the page: True   deleted text shown: True
```

and the render at `markup=True` shows the insertion underlined in red
and the deletion struck through, which is what an author adjudicating
from a PDF has to see.

---

### ~~S2 `link_all` CLIPS a surname that opens with a lowercase particle, so half the name stays black~~ — FIXED 24.08
<!-- status: fixed -->

Found on Aging_Well, 2026-08-23, adding de São José et al. (2019) under
referee Issue 4.

The manuscript reads `de São José et al. (2019) set out a capability
framework…`. `link_all` linked **`José et al. (2019)`** — the particle
`de São ` left outside the span, black, immediately before a blue
underlined `José`. The reference entry parsed correctly (the anchor it
minted is `deSaoJose2019`, particle and all), so this is the in-text
grammar only: `AUTHORS_PATTERN` reads a surname as its capitalized words.

**Why S2 and not S4.** Nothing catches it.

* `citations` reports `82 of 82 mentions linked, 0 broken` — the anchor
  resolves and the label is non-empty, which is all it asks.
* `refstyle` is about the entry, not the span.
* `compare`'s TEXT and STRUCTURE layers are clean: no character moved.
* Only the **ungated** HYPERLINK layer shows it, as
  `[user-only] 'José et al. (2019)'` — and it takes reading the label
  against the sentence to see that the two differ.

Same shape as the group-tiling entry this file already carries: a valid
link over the wrong span, invisible to every layer that has an opinion.
A re-run does not self-correct either — `masked_visible_text` marks the
clipped span as already linked, so any hand-wiring meant to widen it
stands aside.

**Reproduce.** A reference entry whose surname carries a particle and an
in-text mention that spells it out:

```
de São José et al. (2019)      -> links 'José et al. (2019)'
van der Klaauw (2008)          -> expected same class, untested
```

**Fix shape.** Let the surname pattern absorb a leading run of lowercase
particles (`de`, `da`, `del`, `van`, `van der`, `von`, `di`, `du`, `la`,
`le`) when the reference list's parsed surname begins with one — the
entry side already knows, so the in-text side can be told rather than
guessing. A test that fails without it: link a paragraph citing a
particle surname and assert the span, not just the anchor.

**Workaround to retire when this lands:** `widen_particle_spans` in
`Aging_Well/revision/scripts/r2_link_apparatus.py`, with its
`PARTICLE_SPANS` table. It is the mirror of the `narrow_group_spans`
workaround sitting beside it in the same file, and both exist for the
same reason.

**The diagnosis in the entry above is wrong, and the measurement says
so.** Leading particles were never the problem: `_SURNAME` has handled
them since it was written, and `van der Klaauw (2008)` and `van Ours
(2013)` both scan whole. What fails is a surname of TWO CAPITALISED
WORDS — `São José` — which the grammar refuses on purpose, because free
capitalised adjacency would file "As Smith (2020) shows" under "As
Smith". `de São José` matched as far as `de São`, found no year after
it, backtracked, and started again at `José`.

That refusal is right for GUESSING and wrong when the answer is in the
document. The entry side parses the surname correctly, particle and
all; only the in-text side was guessing.

**What changed.** `find_citations(text, names)` takes what the
reference list parsed and matches those surnames literally, longest
first, as an alternation ahead of the generic pattern — so a name the
grammar cannot infer is not inferred, it is READ. `link_all`,
`link_rest` and the audit all pass their own entries' surnames, so the
writer and the checker see the same spans. Told nothing, the scanner
behaves exactly as before.

**One property had to be restored on the way.** `link_rest` widens a
narrow capture over an institution's name and ABANDONS the widening if
it would reach into an existing link — *"linking less prettily, never
worse"*. Making the wide span the first one the scanner sees turned
that into skipping the mention altogether, which is worse rather than
less pretty. `citations_clear_of(text, masked, names)` restores the
ladder: the wide capture when it is clear of existing links, the
grammar's narrower one when it is not, nothing only when both are
blocked. It re-scans only when a wide span is actually blocked.

A second report improved with it: `link_rest`'s "entry has no bookmark"
line quoted `'Group 2024'` for `(World Bank Group 2024)` — naming
something the reader could not find in the sentence. It quotes the
whole name now.

Verified end to end: `de São José et al. (2019)` links whole, anchored
`deSaoJose2019`, where it previously linked `José et al. (2019)` and
left `de São ` black.

**Workaround to retire:** `widen_particle_spans` and its
`PARTICLE_SPANS` table in `Aging_Well/revision/scripts/r2_link_apparatus.py`.
Not deleted here — that paper has a session working in it — but it is
now dead code, and its mirror `narrow_group_spans` should be checked at
the same time: the widening it compensates for is the one
`citations_clear_of` now does correctly.

---

### ~~S1 `\max`, `\min` and `\lim` come out ITALIC, so an optimization problem renders as three variables~~ — FIXED 24.08
<!-- status: fixed -->

Found on Aging_Well, 2026-08-24, reading the rendered page of the batch that
gave that paper its first mathematics. Equation (5) is a planner problem and
its `max` is set as three italic letters, `𝑚𝑎𝑥`, rather than as an upright
operator name.

**Measured across seven operators**, by counting `<m:sty m:val="p"/>` in the
converted OMML:

| written | upright? |
|---|---|
| `\log x`, `\log_{2} x`, `\exp x` | yes |
| `\max x`, `\max_{x} y` | **no** |
| `\min x` | **no** |
| `\lim_{x} y` | **no** |

`\operatorname{max}` does not help — same result.

**The root cause is upstream and docxkit is the seam.** latex2mathml emits
different MathML for the two families:

```
\log x -> <mrow><mi>log</mi><mi>x</mi></mrow>
\max x -> <mrow><mo>max</mo><mi>x</mi></mrow>
```

`MML2OMML.XSL` marks a multi-character `<mi>` upright and leaves `<mo>`
alone, so the operator family loses its styling. Nothing downstream of
`latex_to_omml` can tell that `max` was meant as a name rather than as the
product of three variables.

**Why S1, by the same reasoning as the spacing entry above.** The output is
valid OMML, `equations()` counts it, `math --check` reports it clean, and
`to_latex` round-trips it. Only a render shows it, and nothing renders by
default. And the operators it misses are exactly the ones an economics paper
reaches for: a constrained optimization is written with `\max`, its
comparative statics with `\lim`.

**Fix shape, and the two candidates are not equivalent.** Either rewrite
`<mo>` to `<mi>` for the operator names OMML wants upright, before the
transform; or post-process the OMML to add `<m:sty m:val="p"/>` to a run whose
text is a known operator name.

**Prefer the second, and measure both against a render before choosing**
(ezhik-82's point, and it is a good one): `<mo>` and `<mi>` are LAID OUT
differently, so swapping the element to fix the face may move the gaps around
it — which would be the spacing defect above, reintroduced by the fix for this
one. The OMML post-process changes the face and nothing else.

A test that fails without it can assert on the `m:sty` stream, which is
cheaper than a render and is what the measurement above already does. A test
for the fix's SIDE EFFECT cannot be, and has to be a render.

**Workaround:** none in use. Aging_Well ships equation (5) with an italic
`max` and the defect is recorded in its `revision/log.md` as the first item
for the next round.

**SECOND OCCURRENCE, and it generalises past operator names — 2026-08-24,
Health_Capacity_to_Work.** That manuscript sets its maths upright THROUGHOUT:
every variable run carries `<m:sty m:val="p"/>` and vectors carry
`m:val="b"`, so `V`, `X`, `h`, `β` and `γ` are all upright, not just the
operators. Rebuilding equation (4) with `latex_to_omml` produced maths that
was correct and **visibly wrong** — the new equation rendered math-italic
directly beneath equation (3)'s upright one, on the same page.

So the gap is not only "some operators come out italic"; it is that
`latex_to_omml` has **no way to match the convention of the document it is
being inserted into**, and the default it emits is the one a LaTeX author
expects rather than the one Word manuscripts here use. Nothing text-based
sees it: `compare`'s FORMULA layer compares tokens and structure and reports
none, and only its FORMULA TYPOGRAPHY layer catches it — which needs a
before/after pair, so it is silent when the equation is NEW.

**Workaround in use, and it is the right default for this case:** do not
build, TRUNCATE. Equation (4) was repaired by keeping its own elements
byte-for-byte and dropping the trailing terms, which cannot change the
setting of what remains; the inline parameter list was rebuilt from its own
runs the same way, reusing the existing "and" run rather than emitting one.
This is the house rule already recorded as `feedback_harvest_omml` —
deepcopy an existing `m:oMath` when the symbols already appear in the
document — and it should probably be the documented FIRST resort in
`equations`' docstring, with `latex_to_omml` reserved for maths the document
has no precedent for.

**Fix shape for the general case:** a `style=` argument, or a
`match_document(xml)` helper that reads the prevailing `m:sty` of the
document's existing runs and applies it to a freshly converted equation.

---

**What changed.** `_name_operators_as_identifiers`, a MathML pre-pass:
a `<mo>` whose text is two or more ASCII letters is retagged `<mi>`, and
Word's XSL then applies to it the same upright rule it always applied to
`\log`. Two or more LETTERS, not a list of names — `\operatorname{…}`
takes an arbitrary one, and a fixed list would have missed it. One letter
is left alone, because one letter is a variable.

**The first version of the fix was wrong, and only the RENDER said so.**
It marked the OMML run upright after the transform, which passed every
markup assertion — and made the page worse. Left as `mo`, the XSL merges
the operator into its operand as a single `<m:t>maxx</m:t>`, so styling
that run took the VARIABLE upright with it: the page showed `maxx` where
it should show `max` then an italic `x`. `test_the_OPERAND_stays_italic`
is that lesson as an assertion.

The caution against retagging — that `mo` and `mi` are spaced
differently, so changing the element to fix the FACE might move the GAPS
— was worth having and does not survive measurement: `\log x`, an `mi`
operator all along, renders with the same absent gap as `\max x`,
because OMML has flattened the distinction by the time Word draws it.

Twelve operators verified upright in the markup and three on a rendered
page, `\sup` among them — it was broken too and had not been measured.

---

### ~~S1 `latex_to_omml` DROPS every LaTeX spacing command, silently~~ — FIXED 24.08
<!-- status: fixed -->

Found on Aging_Well, 2026-08-23, building the paper's first mathematics
(R20).

`\qquad`, `\hspace{2em}` and `\;` all vanish in
latex2mathml → `MML2OMML.XSL`. Measured, five candidates:

| written | survives as |
|---|---|
| `a > 0 \qquad b < 0` | `a>0`, `b<0` — nothing between them |
| `a > 0 \hspace{2em} b < 0` | same |
| `a > 0 \; b < 0` | same |
| `a > 0 \text{\ \ \ \ } b < 0` | four spaces, each preceded by a literal backslash |
| `a > 0 \mathrm{~~~~} b < 0` | four U+00A0 in their own maths run — clean |

**Why S1, on ezhik-82's argument rather than my first call of S2.** The
defect is a silent wrong answer *in the output medium*: nothing but a render
can see it, and nothing renders by default. The output is valid OMML,
`equations()` counts it correctly,
`m:oMath` totals are right, `math --check` reports it clean and
`to_latex` round-trips the structure. Nothing sees it. What it looks like
on the page is a definition and its sign conditions run together —
`c=f(r,θ),∂f/∂r>0,∂f/∂k>0` — because every gap between them is gone.
Every equation in that paper's two drafts has exactly that shape, so it
hit all nine.

**Reproduce.** `equations.latex_to_omml(r"a > 0 \qquad b < 0")` and read
the `m:t` runs.

**Fix shape.** Translate the spacing commands to an explicit maths run
before handing the MathML to the transform, or post-process the OMML to
insert one. A test that fails without it can assert on the `m:t` stream
rather than on a render.

**Workaround in use:** `\mathrm{~~~~}` throughout
`Aging_Well/revision/scripts/r20_model.py` (the constant `G`), with the
reason in its module docstring. Retire it when this lands.

---

**What changed.** `_carry_spacing`, a MathML pre-pass: `<mspace
width="…">` becomes `<mtext>` carrying em/en/thin spaces chosen to match
the requested width. It runs BEFORE the transform because the XSL has no
template for `mspace` at all — after it the gap is gone and cannot be
recovered.

`mtext` is the vehicle because it is the one construct measured to
survive that XSL: `\mathrm{~~~~}`, the workaround a paper had already
invented by hand, is `mtext` underneath. This does for every spacing
command what that paper was doing for one of them.

The spaces are U+2003/2002/2009 rather than ASCII: they are exact
fractions of an em, so the gap does not depend on the font's idea of a
space, and none of them is XML whitespace, so nothing downstream can
collapse or trim them. A plain space in `m:t` is precisely what
`edit.preserve_space` exists to rescue, and putting one here would be
inventing that problem. `\!` is negative and draws nothing — Word has
no negative space, and an empty run would be worse than none.

Six commands verified, plus a test that a WIDER command produces a wider
gap: a repair that made every gap identical would have passed the
first six.

---

### ~~S1 `compare` does not compare `word/media/` AT ALL: a figure replaced, corrupted or DELETED is reported as zero changes~~ — FIXED 24.08, `b657e52`
<!-- status: fixed -->

Found on HCW, 2026-08-23, during T12.2 — a task whose entire deliverable was
four replaced images.

**Symptom as observed.** `docxkit compare A B` where B differs from A only in
`word/media/` prints

```
REAL change locations (excl. glyph): 0   |   glyph-only: 0   |   ...
```

for all three of these:

* **replaced** — Figure 8.a's PNG swapped for Figure 1's, a completely
  different chart;
* **corrupted** — the part overwritten with a 48-byte stub that is not a
  valid image;
* **deleted** — the part removed from the package outright.

`--json` carries no media information either: the report's keys are
`structure, text, glyph, formula, formula_glyph, formula_format, format,
hyperlinks, integrity, stripped_fields, comments`, and the string "media"
does not occur anywhere in the output.

**Why S1 and not S2.** The STRUCTURE layer's own header is

```
STRUCTURE  (paragraph insert / delete / move, part added / removed)
```

so the layer states that it covers a part being added or removed, and then
reports `(none)` when one is removed. This is not a documented boundary a
caller could route around — it is a gate reporting success on a change it
claims to check. The skill documentation reinforces it: "STRUCTURE (incl.
moves, and a whole part added/removed)" and "**Never decide 'did this change?'
by eyeballing truncated text — let the tool enumerate.**" A caller who follows
that instruction on a figure edit is told nothing changed.

**Why it matters here specifically.** T12.2's acceptance is that the parts in
`word/media/` hash-match their sources, precisely because Word silently
recompresses images on save. The compare gate is the tool that is supposed to
answer "did the right thing land"; on this task it answered "nothing landed"
while four figures had been swapped. The only reason the swap was known to be
correct is that the paper's own script re-read the saved file and compared
SHA-256 itself.

**Repro.**

```python
from docxkit import read_parts, write_docx
parts = read_parts("paper.docx")
parts["word/media/image14.png"] = parts["word/media/image1.png"]  # or `del`
write_docx("swapped.docx", parts)
# docxkit compare paper.docx swapped.docx  ->  REAL change locations: 0
```

**Shape of a fix.** Compare the set of non-XML parts by name and by digest,
and report three cases in STRUCTURE: part added, part removed, part CHANGED
(same name, different bytes). A changed image needs no pixel diff to be worth
reporting — name plus "content differs, 66,203 -> 69,327 bytes" is enough to
send a person to look, which is all the other layers do. Consider naming the
exhibit: the caption above the drawing that references the part is available
from the same walk `crossrefs` already does.

**What changed.** A MEDIA layer, gated, in all three layers of the
comparison: `_compare_read` reads `word/media/` and `word/embeddings/` and
digests them, `_compare_diff.compare_media` pairs and reports, and
`_compare_render` prints them. `GATED` gains a sixth member, so the headline
count and `--expect-clean` both include it.

**Paired by NAME, and that is measured rather than assumed.** The
alternative — pairing by digest, to absorb a renumbering — would have hidden
the case that matters: two figures whose contents trade places keep both
names and both digests, and only a name pairing calls that two changes.
Word does not renumber media on save: checked over **110 media parts in
three real manuscripts**, every one byte-identical through an open-and-save,
so the noise a digest pairing would have absorbed does not arrive. There is
a test for the swap.

**The entry names the EXHIBIT.** `word/media/image14.png` sends a reader to
a folder; `Figure 8.a` sends them to the page. The caption comes from the
walk `crossrefs` already does — the drawing's `r:embed` through the part's
rels — looking DOWN first, because that is where a figure's caption sits in
these manuscripts. `load` therefore reads the rels as well as the parts.

**`docProps/thumbnail` is excluded, and that is measured too**: Word
regenerates it from whatever the first page renders to, so it differs after
an open-and-save with nothing edited, and a difference on every round-trip
is one nobody reads.

No pixel diff, deliberately — "content differs, 40,264 -> 48 bytes" is
enough to send a person to look, which is all any other layer does.

**Verified on the entry's own repro**, against a real 42-figure manuscript:

```
replaced   exit=1  [MEDIA CHANGED] word/media/image21.png (40,264 -> 39,484 bytes) — Montenegro
corrupted  exit=1  [MEDIA CHANGED] word/media/image21.png (40,264 -> 48 bytes)     — Montenegro
deleted    exit=1  [MEDIA REMOVED] word/media/image21.png (40,264 bytes)           — Montenegro
```

All three printed `REAL change locations: 0` before. Ten tests in
`tests/test_compare.py`. **The per-paper workaround can go**:
`A1_t112_figures.py`'s hash check is what `compare --expect-clean` now does
for every paper.

### ~~Twelve from a code review of the round just committed~~ — FIXED 24.08
<!-- status: fixed -->

`/code-review max src/docxkit/revision.py`, run against the four commits of
2026-08-23 (`00dd491`, `d58c318`, `409d68b`, `ae3605b`). Fifteen findings:
twelve mine, fixed here; three in the other session's redline retention,
passed to it. Every one reproduced against the live tree before it was
believed, and the suite was GREEN throughout — so every finding below is a
gap no test covered.

**Worth recording about the review itself:** the ten finder agents it
spawned never returned, and the orchestrator stalled for 600s waiting on
them before the watchdog killed it. Resumed with "collect whatever they have
and report it, do not start over", it produced all fifteen from its own
context in 100 seconds, each verified by EXECUTING the code rather than
reading it. The fan-out contributed nothing; the verification did.

**S1 — `run_gates`' timeout bounded nothing.** With `shell=True` the gate is
a GRANDCHILD (cmd.exe is the child), so the kill on timeout reaches the
shell and the surviving grandchild holds the pipes open, blocking
`subprocess.run`'s cleanup. Measured: `timeout=1` against a 20-second sleep
returned after **20.08s**; the same call without a shell returns in 1.03s.
The docstring promised the opposite — "a timeout reports as code -1 rather
than blocking a ladder that exists to be run before every hand-back" — and
`test_a_gate_that_HANGS_is_a_gate_that_fails` certified it while taking
30.09s, because it asserted the exit code and never the clock. Fixed with
`Popen` + a drain thread + a process-TREE kill (`taskkill /T` on Windows,
`killpg` on POSIX). The test now asserts elapsed time, and that one file
went from **32s to 6s**.

**S2 — `Verdict.links` was a net TOTAL**, which violates the invariant in
`_links`' own docstring one screen away: *"Counted as a MULTISET of pairs,
not as a total … a total hides a swap"*. It hid one. A round that keeps
Lari's link, drops Deaton's to plain text and adds Sen's reported `links=0`
and printed nothing, while `_link_changes` in the same module named the lost
one correctly — the Parental Style T4(3) class, 227 against 229, which this
module exists to catch. `Verdict.bookmarks` had the same shape as a set
LENGTH delta, so a bibliography re-key (N anchors out, N others in) read as
zero. Both are `(added, lost)` pairs now.

**S2 — `VERDICT: PASS` on a run that exited 5.** The line printed before
`_paper_gates` ran. Captured live: `VERDICT: PASS` … `1 of 1 of the paper's
gates failed.` … exit 5. Both the log template and the README treat that
line as the answer. It prints last now and reflects both halves; the string
is unchanged, so anything grepping it keeps working and is no longer lied
to.

**S2 — two abort paths said nothing about the gates.** `_skipped_gates`
exists so that silence after `--run-gates` cannot read as "they ran and were
fine", and it missed the FIRST abort in the function (batch built on another
baseline, a bare `return 2`) and `ship`'s build failure. Its docstring
enumerated two paths when there were four.

**S4 — the timeout handler threw away what the gate had printed**, replacing
`exc.output` with the literal "no output within Ns". A pytest gate wedged on
test 340 of 500 names that test in the lines before it hangs. Kept now.

**S4 — `except OSError  # a command that is not there` never fires** under a
shell: a missing command returns 1 on Windows and raises nothing. The case
it DID catch is a missing cwd, which it labelled 127 "command not found" —
sending the author after a missing tool when the project root had moved or
its drive was offline. Now checked up front and reported as 126 with the
real reason.

**S4 — `--gate-timeout 0`** made every gate report `[TIMED OUT] 0.0s`
without running and exited 5, under the near-universal convention that 0
means "no timeout". Refused now, with a message saying why there is no such
setting.

**S4 — the heartbeat arrived after the wait.** `progress` was wired in the
engine and never passed, so a 12-minute pytest gate showed an empty terminal
for twelve minutes under a 900s timeout — indistinguishable from the hang
that (per the S1 above) would not have timed out either. Passing it was not
enough: `run_gates` returned a LIST, so every gate was announced up front
and every verdict arrived together at the end. It streams now, and the
announce/run/report cycle interleaves. **The generator has a footgun and the
suite found it within a minute** — `run_gates(paper)` with the result
discarded runs nothing, which is how `test_gates_run_in_the_ORDER…` first
failed. Documented, and the call sites take `list(...)`.

**S4 — `verdict()` read `prev.docx` twice** (`compare` on paths unzips both
again) and walked both documents four more times for two integers that, per
the entry above, were wrong anyway. One read each now, through
`compare_docs(load_parts(...), load_parts(...))`.

**S4 — `apparatus_only` silently required `batch is None`**, undocumented,
so a linking pass run in place while a valid batch sat unpromoted was
reported as an adjudication of a batch nobody acted on. The condition is
real and stays; it is written down now.

**Doc — the module header said "There is no separate redline file"**, which
the other session's redline retention made false the same day.

### One the review MISSED, found by probing while it ran
<!-- status: fixed -->

`verdict`'s paragraph multiset asked *is this text in the document* rather
than *is it where the batch put it*. When a proposed paragraph's text
already appeared elsewhere, a batch reported `1 of 2 kept as proposed` BOTH
when the author accepted everything and when they rejected everything — a
wrong verdict written permanently into the paper's log. **Table cells make
this ordinary rather than exotic**: `_para_counts` walks every paragraph,
and "0.00" or a repeated country name is a paragraph. Fixed by subtracting
the context — the paragraphs both views share — before asking which version
survived. Fifteen review angles did not find it; a five-minute probe with
three synthetic cases did.

### ~~S1 the protocol kept no copy of the REDLINE, so an accepted batch became invisible everywhere~~ — FIXED 23.08, `1c74e08`
<!-- status: fixed -->

Found on Aging_Well, 2026-08-23, by the author: *"I do not see track changes
in working.docx; this seems to be a systemic problem. Other papers also lost
track changes."*

**Measured, not suspected.** Across all eight papers carrying
`revision/paper.toml`, every `working.docx` **and every rescue copy in every
one of them** holds 0 insertions and 0 deletions. The only tracked artifacts
alive anywhere are ones that escaped deletion by accident —
`Parental_style/revision/build/batch.docx` (7 ins / 7 del),
`Loneliness Index/revision/build/LI7_tracked_prerepair.docx` (1207 / 782),
`AFI/revision/build/batch.docx` (0 / 2).

**The mechanism.** `build` writes the redline to `build/batch.docx`. `promote`
copies it onto `working.docx` and rescues the file it is REPLACING — which is
clean, because a completed cycle ends with an accept. The author accepts, and
the markup leaves `working.docx`. The protocol then said to delete
`batch.docx`. So after any completed cycle the markup exists nowhere, and the
rescue ladder cannot help: it is a clean-generation ladder by construction.

**Why S1 and not S2.** Nothing reports it. Every gate passes, `status` says
TRUTH, `losses` is empty, `compare` between generations is clean — and the
question "what did that batch change?" has no answer left in the package. The
protocol's own promise is that `working.docx` is *"tracked when proposed"*;
after the accept there is no artifact that was ever tracked.

**Rebuilding is not a substitute.** Word Compare over two clean generations
reproduces a word-only batch (done here for R15 and R16, both passing the full
ladder). It CANNOT reproduce a span that crosses an untracked apparatus pass:
`tracked.build` refuses with `rejected: bookmarkStart 132 -> 142`, because
Compare will not serialize a bookmark insertion. A cumulative redline across an
apparatus pass is readable and not adjudicable.

**Fix, committed as `1c74e08`.** `Paper.redline_dir`
(`build/redlines/`), `redline_path`, and a copy in `promote` that lands and is
hash-verified BEFORE `working.docx` is overwritten — a redline that did not
land refuses the promote, on the same reasoning as the rescue that did not
land. `PromoteReport.redline` and a CLI line. **Redlines are never pruned**:
`prune_rescues` does not look in that folder, and thinning an audit trail
recreates the gap it closes. Five tests in `tests/test_revision.py`, all
verified to fail with the retention block removed.

**Why it sat uncommitted for a day.** `src/docxkit/cli.py` and `src/docxkit/revision.py`
already carried a large uncommitted refactor of `revision init` when this was
written — adopting the author's manuscript in place instead of copying it to
`working.docx` (`--working PATH`, the "is not inside" check at
`revision.py:2003`). That work is unfinished: **16 tests fail against it** on
the committed tree's own suite, all of them path-resolution tests it has not
updated. Committing would bundle the two. The suite is otherwise green — 4663
passed — and none of the 16 touches `promote`, `PromoteReport` or the redline.
That refactor landed as `00dd491`; the two were then committed separately, split by identifier and verified by checking the INDEX out into a temp tree rather than trusting the working tree.

**Per-paper workaround to retire when it commits:**
`Aging_Well/revision/scripts/rebuild_redlines.py`, the one-off backfill for
R15 and R16.

---

### ~~S2 an untracked apparatus pass changed the manuscript and left no record of what it did~~ — FIXED 23.08
<!-- status: fixed -->

Found 2026-08-23 in the protocol review.

**The shape.** Word's Compare will not serialize a bookmark insertion —
`tracked.build` refuses such a batch with `rejected: bookmarkStart 132 -> 142`
— so the citation apparatus (linking, cross-references) runs UNTRACKED and in
place, gated only by `docxkit compare` showing no text change. That is the
right call and it has a cost: the round produces no redline, nothing for the
author to adjudicate, and — since E landed this morning — a log row reading
`no visible change`, which is true and useless. A pass that added 116
bookmarks to Aging_Well was indistinguishable in the record from a round
where nothing happened.

**Fix.** `Verdict` counts the apparatus: `links` and `bookmarks`, as net
deltas against the previous truth, from `_links` and `_bookmarks` — the two
things the text comparison structurally cannot see. `apparatus_only` names
the round where those moved and no visible word did, and the row then reads

```
| 2026-08-23 | apparatus | +1 link, +1 bookmark | — | untracked apparatus pass (nothing to adjudicate) → truth |
```

A round that also moved words is still reported as adjudicated, with the
apparatus counted beside it rather than instead of it. A pass that LOSES
links reports the negative — Word strips run-level hyperlinks out of every
paragraph whose text the author rewrites, which is why the pass is re-run
every round, and a round that came back with fewer is worth a number.

Four tests in `tests/test_revision_verdict.py`. Load-bearing: dropping the
two counts fails 3, dropping the `apparatus_only` verdict fails 2.

### ~~S4 `[verify] commands` were recorded and never run, so a paper's own gates ran when someone remembered~~ — FIXED 23.08
<!-- status: fixed -->

Found 2026-08-23 in the protocol review; the author asked for it directly.

**The old boundary, and why it moved by exactly one flag.** `validate`
deliberately did not shell out, and the reasoning is in its docstring: what a
paper checks is the paper's business, and a shared tool that runs per-project
commands is a larger promise than the protocol makes. That holds for the
DEFAULT. It does not hold for the capability — across the nine papers those
lists hold between one and six commands each, and "listed, and you run them
yourself" means they run when someone remembers.

**Fix.** `run_gates(paper, timeout=900)` and `validate --run-gates`. Not part
of the ladder, not run unless asked, and when asked they run exactly as the
config spells them, through the shell, from the project root. The commands
are the author's own text in the author's own file; this neither parses nor
sanitises them, and the docstring says so.

* **A gate that hangs is a gate that fails.** Each is bounded by `timeout`
  and a timeout reports as code -1 — this ladder is meant to run before every
  hand-back, and a gate with no bound is one that can stop that happening.
* **Exit 5, not 1.** "The redline is unshippable" and "the manuscript is
  wrong" want different responses, and a script that only knows non-zero
  cannot tell them apart. A batch failure still outranks a paper gate.
* **An aborted ladder says the gates did not run.** `validate` returns early
  on a lint failure and on a batch Word cannot open; silence after the flag
  was passed reads as "they ran and were fine", which is the one thing it
  must not read as.
* The listing and the running are ONE section now. `validate` used to print
  its own "the paper's own gates (run these too)" list, so with `--run-gates`
  the reader got the commands once as a reminder and again with verdicts.

Verified end to end on a paper with two gates, one passing and one failing:
the ladder says PASS (the batch is fine), the failing gate prints its own
output, and the exit code is 5.

`tests/test_revision_gates.py`, 12 tests. Load-bearing: running them without
the flag fails 1, collapsing 5 into 1 fails 1.

### ~~S2 the author's VERDICT was recorded nowhere — after adjudication a paper reads the same whether every revision was accepted or every one rejected~~ — FIXED 23.08
<!-- status: fixed -->

Found 2026-08-23 in the protocol review. Not a wrong answer — a fact that
existed and was never written down, and then stopped existing.

**The shape.** The state model is a count of pending revisions, so a settled
manuscript reads 0 whether the author accepted the batch in full, rejected it
in full, or split it. The verdict was reconstructible from `prev.docx` and
the batch right up to the moment `baseline` runs — and `baseline`'s own next
act is `shutil.copyfile(working, prev)`, which destroys the comparison. Two
of the nine papers' `log.md` batch tables were filled in by hand and the rest
had gaps.

**What landed.** `revision.verdict(paper)` and `revision.log_batch(...)`,
called by `baseline` (default on, `--no-log` to skip, `--note` to name the
round), and computed BEFORE the copy — that ordering is the whole trick, and
reverting it makes every round report "no visible change".

* Counted per PARAGRAPH, not per revision, and that is the honest unit: a
  revision's identity does not survive the author's Word session, the text of
  the paragraph it proposed does. The batch's accepted and rejected views
  disagree about exactly the paragraphs it touched; which version the
  manuscript now holds is the verdict. Multisets, so a paragraph MOVED rather
  than edited is not counted as one of each.
* "accepted in full" survives the author having also edited — those come back
  as `+N authored`. `31 accepted and two sentences of my own` is the ordinary
  shape of a round, and calling it "partly adjudicated" would be wrong about
  the part that matters.
* **The verdict is only as good as its link to the proposal.** `_proposal`
  returns the batch only when `guard.base_of` says it was built on THIS
  baseline; a leftover `batch.docx` from an earlier round — the exact file
  the stale-batch guards exist for — answers None, and the row then says
  "adjudicated (no batch to compare against)" rather than counting one
  round's verdict against another's proposal. An unstamped batch (the
  hand-authored vehicle) answers the same.
* The row lands after the last row OF THE TABLE, not at the end of the file:
  three of the nine papers carry prose after their batch table, and an
  appended line would have been read as part of it. A log with no batch
  table is left alone entirely and the CLI prints the row for the author to
  place — a log this tool did not scaffold is the author's document.
* The row is a record and not a gate: a log that cannot take one does not
  stop the cycle from closing.

Verified against a log shaped like a real paper's — template row, a
hand-written row, prose below — with a batch accepted in full plus one
authored paragraph:

```
| 2026-08-23 | R15 tables | 1 ¶ changed, 1 added, from 2 revisions (1 ins, 1 del) | — | accepted in full, +1 authored → truth |
```

`tests/test_revision_verdict.py`, 15 tests. Each half proved load-bearing by
reverting it in a copy of the tree: computing the verdict after the copy
fails 2, taking a stale batch as the proposal fails 2, appending to the end
of the file fails 1.

### ~~S4 the protocol is single-paper and the author has nine, so "which of them is waiting on me?" had no answer~~ — FIXED 23.08
<!-- status: fixed -->

Found 2026-08-23 in the protocol review, from the author's own framing:
*"I work on several papers at the same time."* Not a defect — a capability
that was never there, which is the shape trigger 4 of the recording rule
exists for.

**The gap.** Every command takes one `--paper`, correctly: doing work on a
manuscript is a single-paper act. Deciding WHICH manuscript to work on is
not, and there was no view for it. The answer was nine invocations of
`status`, which means the question was not asked — so a proposal could sit
unadjudicated in a paper nobody had opened for a week, and `prev.docx` could
go stale behind it with the same silence.

**What landed.** `docxkit revision status --all`: one line per paper, worst
first, exit code on the same scale one paper uses (1 pending, 4 stale
baseline, 2 a row that could not be read, 0 all settled).

Measured on the author's nine papers: **1.6 s for all nine**, and it found
two things on the first run that no per-paper command had been asked —
`Health Capacity to Work` carrying 9,149 pending revisions, and `AFI` on a
baseline three parts stale with a batch still staged in `build/`.

* A registry at `%LOCALAPPDATA%\docxkit\papers.txt` (`DOCXKIT_PAPERS`
  overrides it), plain text, one `paper.toml` per line, `#` comments a
  finished paper out. `init` registers what it scaffolds — the list has to
  fill itself, because a registry that must be curated by hand is accurate
  on the day it is written. `--scan FOLDER` walks a root and adds what it
  finds, bounded to four levels: the roots these live under are cloud
  folders and an unbounded walk of one took over two minutes.
* No read-only command writes to it. A `status` with a machine-wide side
  effect would be a read command that edits state — including inside anyone
  else's test suite, which is also why `DOCXKIT_PAPERS` exists and why
  `conftest` points it at a tmp path for the whole run.
* A path that no longer resolves is KEPT and reported, never pruned: a
  project on a disconnected drive is not a project that has been retired.
* **No row can kill the survey.** A config that will not parse, a manuscript
  that has been deleted, a package Word is part-way through saving — each
  comes back as a row with its error, because the eight healthy papers are
  the point. "unreadable" and "missing" are kept apart: one is a file this
  tool could not parse, the other is a file that is not where the paper says
  it is.
* It also reports what `status` structurally cannot: a batch sitting staged
  in `build/`, which is not a state of the manuscript and is exactly the
  thing forgotten between sessions. Three of the nine had one.

Two bugs in it were caught by its own tests before it shipped: a deleted
manuscript reported as "unreadable" (the word for a config that will not
parse), and a broken row labelled `revision` — `config.parent` is the
FOLDER, so the one row that most needs to name its paper named the layout
instead.

`tests/test_revision_survey.py`, 21 tests.

### ~~S1 `revision init --force` REWRITES `paper.toml` from the template, and resets the log and the baseline with it~~ — FIXED 23.08
<!-- status: fixed -->

Found 2026-08-23 while reviewing the protocol at the author's request, not
from a paper. Measured, then measured again across every live paper.

**Symptom as observed.** On a scratch project whose config had been given two
gates and a doctor skip:

```
$ grep -n "commands|skip" revision/paper.toml
26:commands = ["pytest tests/", "python scripts/qa_links.py"]
32:skip = ["v8_restructure"]
$ docxkit revision init Report/HCW_v14.docx --root . --force
scaffolded .../revision
$ grep -n "commands|skip|carry" revision/paper.toml
26:commands = []
```

Exit 0. No warning, no backup, nothing in the output naming what went.

**Mechanism.** `init` writes the config unconditionally from
`_TOML_TEMPLATE` (`revision.py:2030`), and the template has parameters for
`name`, `language`, `working`, `author`, `rescue_keep`, `gates` and `attic`
and **no representation at all** for `[batch] carry`, `[doctor] skip`, a
non-default `prev`, or any section a paper has added for its own tooling. A
forced re-init therefore cannot round-trip them even in principle: `gates` is
passed as `""` by `init`, and the rest have nowhere to go.

**Why S1 rather than S2.** The command reports success and leaves the paper
in a state where a LATER command does the wrong thing silently. The blast
radius is every paper on the protocol — all nine carry something the template
cannot express:

| paper | would be destroyed |
|---|---|
| Aging_Well | `carry = ["word/footer3.xml"]` |
| AFI, HCW | 2 gates each |
| HPPA_Index, Life_expectancy_trends | 1 gate each |
| Life_Expectancy | 2 gates + `[deliverable]` `[analysis]` `[git]` |
| Loneliness Index | 6 gates + `[deliverable]` `[analysis]` `[git]` |
| Parental_style | 3 gates + `[analysis]` `[git]` |
| DSI | 1 gate + `[git]` |

Two of those are load-bearing beyond "a list got shorter".

* **Aging_Well's `carry` line is the fix for a shipped defect.** Word's
  Compare drops `word/footer3.xml` — the first-page footer — on every rebuild
  of that manuscript, along with `docProps/custom.xml`, which on a World Bank
  paper holds the MSIP sensitivity label and the "Official Use Only" content
  marking. That paper's log records a promote that shipped an unlabelled
  manuscript with every gate green, and `[batch] carry` is what closed it.
  Dropping the key puts the paper back in the state the defect was filed for,
  and no gate looks at whether the key is still there.
* **LI7's `[git] repo = ""`** records that the project root is NOT under
  version control and that the attic plus the safekit vault are the paper's
  only history. A config rewrite deletes the note that says recovery is not
  available.

**Repro.**

```python
from docxkit.revision import init, load_paper
paper = init(root, source)                      # any paper
cfg = paper.config
cfg.write_text(cfg.read_text() + '\n[batch]\ncarry = ["word/footer3.xml"]\n')
init(root, source, force=True)                  # exit 0
assert load_paper(root).carry == ()             # passes: the key is gone
```

**Shape of a fix.** `--force` is reached for exactly when a config needs
correcting, which is when the rest of it must survive. Three options, in the
order I would try them:

1. **Merge rather than rewrite.** Read the existing TOML, replace only the
   keys `init` is being asked to change, write the rest back. Needs a
   round-tripping writer (or a line-level edit of the keys it owns) because
   `tomllib` is read-only and re-emitting from a parsed dict loses every
   comment — and the comments in these files are half their value.
2. **Refuse when the config carries anything the template cannot express**,
   naming the keys, and tell the caller to edit the file by hand. Cheap,
   honest, and it cannot lose anything.
3. At minimum, `package.backup(config, tag="pre_init_force")` before the
   write, and print the path — the pattern `baseline --repair-math` and
   `refstyle --fix` already follow.

(2) is the smallest correct thing and (1) is what a user would want; both are
better than the current silence. Whichever lands, the test is: a config
carrying `carry`, `[doctor] skip` and an unknown section survives
`init(..., force=True)` byte-for-byte apart from the keys asked to change.

**What changed.** Option (1), the merge — `--force` is reached for when a
config needs correcting, and a refusal would have left the flag useless on
all nine papers, every one of which carries something the template cannot
express.

* `_set_key(text, section, key, value)` edits ONE key in place. A line
  editor, not a TOML round-trip: `tomllib` reads and does not write, and
  re-emitting a parsed document drops every comment — and the comments are
  half of what these files are for. A missing key is inserted under its
  section header, a missing section is appended, the trailing comment on a
  rewritten line survives, a `#` inside a quoted value is not read as one,
  and a value that opens a bracket is REFUSED rather than mangled (the one
  array in the template, `[verify] commands`, belongs to the paper).
* `init` now merges on an existing config and writes the template only when
  creating one. The keys it rewrites are the ones it was GIVEN, which is why
  `author` and `language` no longer default to "Revision" and "en": on a
  rewrite there is no way to tell a caller who means "en" from one who said
  nothing, and the paper spelling its author "Revision Agent" would lose it
  to a default nobody typed. The defaults apply to a NEW config.
* `package.backup(config, tag="pre_init")` before the write; the CLI names
  the copy.
* **`log.md` and `prev.docx` are never rewritten** — `or force` is gone from
  both. One is the paper's batch history and the other is its baseline, and
  neither was this function's to reset. That half of the defect was found
  while measuring the first: on a paper with two rounds behind it the batch
  table went 3 rows -> 1 and the baseline was re-seeded to the CURRENT
  manuscript, which would have left every later reject-all measuring against
  the wrong generation.

Verified on a scratch paper carrying two gates, a `carry` line, a `[git]`
section and a batch row: after `init --force --name "..."` all four survive
byte-identical, the name changed, the unpassed author did not, and
`paper_pre_init1.toml` sits beside the config. Tests:
`test_init_FORCE_keeps_everything_the_paper_declared`,
`test_init_FORCE_repoints_the_manuscript`, and five unit tests on `_set_key`
(insert, append, comment survival, `#` inside a value, multi-line refusal).
Reverting the fix turns the first red.

---

### ~~S2 `build` never checked that the baseline is the generation the manuscript grew out of, so the refusal arrived one Word Compare late~~ — FIXED 23.08
<!-- status: fixed -->

Found 2026-08-23 in the same protocol review as the entry above, and the
code had already written the finding down: `drift`'s docstring says *"A batch
built then is built on a stale base, and nothing says so until `promote`
refuses on a hash mismatch, after a Word Compare has been paid for."*
Nothing called it.

**The shape.** `build` checked that `prev.docx` carries no pending revisions
(`revision.py:705`) and not that it is the right generation at all. After an
accept in Word both files read 0 pending while their content has diverged, so
the redline built on that baseline presents the AUTHOR's own edits as the
agent's proposals. Nothing is destroyed — `promote` refuses on the hash — but
the cost is a full Word Compare plus a reader spending the round trying to
make sense of a redline about the wrong pair.

**Fix.** `build` calls `drift(paper.working, paper.prev)` before anything
else and raises `StaleBatch` naming the parts that moved and the two commands
that resolve it. `allow_stale_baseline=True` overrides it;
`allow_pending_baseline` implies it, because a baseline that legitimately
carries a proposal cannot match a clean manuscript — refusing the second
after being told about the first is a gate arguing with its own override.

Measured end to end: the refusal now lands in **0.29 s, exit 4, with Word
never launched**. Compared by MEANING (`part_fingerprint`) rather than by
bytes, so a Word re-save that re-mints rsids is not drift — the hash guard in
`promote` cannot make that distinction, which is why this gate is `drift` and
not a digest. Tests:
`test_build_refuses_a_baseline_the_manuscript_has_OUTGROWN`,
`test_a_WORD_RESAVE_of_the_manuscript_is_not_a_stale_baseline`,
`test_the_stale_baseline_refusal_can_be_overridden`.

Three existing fixtures wrote a baseline their manuscript had never grown out
of and went red on the new gate. They were re-pointed rather than exempted:
at build time in the real cycle the two files hold the same content, and a
fixture that could not happen is a fixture testing a state the tool will now
refuse.

---

### ~~S3 `crossrefs` still calls an exhibit "linked" when NOTHING links to it~~ — FIXED 23.08
<!-- status: fixed -->

`audit` asked whether the two bookmarks EXIST. Word keeps bookmarks and
strips run-level hyperlinks out of any paragraph an author rewrites, so
the state this was filed for — both markers, no link — is what an
ordinary round produces, and the audit called it `linked` while `link()`
called it `already_linked` and refused the repair.

`reaching(*parts)` is the missing question: every anchor something
actually links to, both element and field form, REF included. Three
things now read it.

* `audit` gains an `unreached` bucket that names the direction —
  "nothing links to the caption", "the caption links back to nothing",
  or both. `linked` means the round trip works.
* `dangling` counts field targets too. Reading element anchors alone,
  a `REF` left behind by a deleted figure was invisible: the same
  half-answer on the other side.
* `link()` asks both questions and repairs each direction on its own.
  The marker it finds is the marker it keeps — `_link_mention(...,
  mark=False)` — because minting a second bookmark of the same name is
  the failure the last round of this file spent a day on.

The `field_form` refusal narrows to what it was for: a field pointing at
a marker that is NOT there, where writing an element link would stack a
second scheme. An exhibit with both markers is past it, since a
direction a field still reaches is not a direction the repair touches.

Tests in `tests/test_crossrefs.py` — the eaten-link reproduction, one per
direction, the no-duplicate-bookmark guarantee, a field link counting as
reach, and a dangling REF.

### ~~S2 `refstyle`'s order check is a CONSECUTIVE-PAIR test~~ — FIXED 23.08
<!-- status: fixed -->

The check compared each entry's surname with the one above it, so an
appended run inverted only at its first pair: Aging_Well's author added
Diller (2016) and Sen (2004) after Zaidi and the audit named Diller
alone. Fixing the named one and re-running to a clean report would have
said the list was sorted when it was not. A same-surname misfiling —
"Sen, A. (2004)" after "Sen, A. (2009)" — it could not see at all.

`_order_findings` sorts by the key `refile` sorts by, so the report and
the repair cannot disagree about where an entry belongs, and names every
entry that has to MOVE. The message says where it belongs ("it files
between Currie and Finkelstein") rather than only that it is wrong.

**The key is a PAIR, and each half alone is wrong.** The folded surname
decides first, or "U.S. Census Bureau" files before "United Nations",
because `.` sorts ahead of a letter. The whole visible text breaks the
tie, punctuation kept, or "Scott, A. (2024)" files after "Scott, A.,
Ellison, M., … (2021)", because `(` sorts before `,`. Both cases are in
the suite, and both were already right in a hand-filed list — which is
the validation: on Aging_Well's 58 hand-filed entries the sort is a
no-op.

Silent on a list of continuation entries ("———. (2015)."), whose key is
the entry above them; `year-order` covers those and `refile` refuses
them.

### ~~S2 `refstyle` calls a work uncited when its only citation is a bare year inside a multi-year group~~ — FIXED 23.08
<!-- status: fixed -->

    before: ¶138 uncited-ref "Sen, A. (2009). The Idea of Justice…"
            while `citations` reported the same file 79 of 79 linked
    after : 60 reference entries, 60 works cited in text — clean

**A link to an entry is the document saying the work is cited.** The
module already knew that — `_trust_the_links` reads a link to settle
which part of a matched span is the citation — but only for spans the
grammar had matched. "Sen's capability approach (1985, 1999, 2009)" puts
four words between the name and the parenthesis, so there was no span to
re-read and no evidence was consulted.

`_credit_unread` credits a linked entry the prose scan never read. Two
details paid for themselves immediately:

* **after the whole walk**, not per paragraph — the prose that reads a
  work can sit in a later paragraph than the link that points at it;
* **only a work nothing else has credited, under the ENTRY's own key.**
  An entry answers to several keys — the prose writes "(National
  Academies 2020)" where the list files "National Academies of
  Sciences, Engineering, and Medicine." — and crediting a link the prose
  had already counted filed one work twice. The header line read "60
  reference entries, 62 works cited in text", a discrepancy a reader
  would go looking for, and it was the first version of this fix that
  wrote it.

### ~~S4 `refstyle` has no fixer, so every paper writes the sort itself~~ — FIXED 23.08
<!-- status: fixed -->

Filed and fixed the same day, with the rule the author stated while it
was open: the reference list starts on a NEW PAGE and every entry carries
a 0.5" hanging indent, no space before, 4 pt after.

`refstyle` now owns all three mechanical halves, and `--fix` runs them in
order — text, then order, then layout:

* `refile(parts)` sorts the list. The sort key is the entry's own visible
  text with diacritics folded, which reproduces a hand-filed list exactly
  (`(` before `,`, so "Scott, A. (2024)" comes before "Scott, A.,
  Ellison, …"). **It moves the GAP with the paragraph**: Word hoists a
  whole-paragraph bookmark out of its `w:p`, so a linked list keeps each
  entry's anchor above it as a sibling, and a sorter built on the
  paragraph matches drops all 60 with nothing but `citations` noticing.
  Refuses a list with continuation dashes, a stray paragraph, or an EMPTY
  one — `_xml.PARA_RE` skips a self-closing `<w:p …/>` by design, so a
  blank line pasted into a list is invisible to every text-layer check
  and this is where it surfaces.
* `layout(parts, spec)` writes the page break and the entry indents;
  `audit` reports the same departures through the same checker
  (`page-break`, `indent`, `spacing`), so the report and the repair
  cannot disagree. A value the paragraph would INHERIT is left alone —
  `styles.paragraph_property` resolves the style chain and docDefaults —
  because Word deletes a declaration equal to the inherited one and the
  audit would report it again every run.

Measured on Aging_Well: 60 entries, 46 on the old 6 pt after and 14
declaring nothing, the heading running on from §9. After: `0 layout/order
finding(s) left`, `compare` clean of STRUCTURE and TEXT, `citations` 79/79.

`tests/test_refstyle_layout.py`, 25 tests. **`audit` reports the layout
rules by DEFAULT** — a paper that sets its list differently passes
`page_layout=None`.

### ~~S4 four ergonomics findings from the same review~~ — FIXED 22.08
<!-- status: fixed -->

**The front door advertised the pair that now raises.** `__init__`'s
module docstring and the README both opened with
`from docxkit.ingest import build_overrides  # author-edit round`, and
that function raises `NoteEdit` the moment the author touches a note
definition — while `update_overrides` writes the `part`-carrying
entries `apply_overrides` refuses. So the documented pipeline breaks on
the next round, and `build_part_overrides`/`apply_part_overrides`
appeared in neither file. Both now name the pair that works, and
`build_overrides` says SUPERSEDED in its first line rather than in its
last paragraph.

**`probe(anchors=)` was renamed with no shim** while the CLI kept
`--anchors-from` for the identical rename. docxkit is the shared
toolkit every paper imports; a script should not break on one half of a
change that was careful about the other. `anchors=` and `Probe.anchors`
both work again.

**The coverage floor's RED guard was on the wrong side of the
missing-report check** — but the check it sat behind has a real reason,
pinned by a test: pytest's exit 4 is a USAGE error, which is what a
missing pytest-cov looks like, and "the suite is RED" would send that
reader somewhere nothing is wrong. Both are true of different exit
codes. Exit 4 with no report keeps the plugin message; any other
non-zero exit with no report — a collection error, an abort — is now
reported as RED, with the tail. `stderr` is in the tail too: it was
captured and dropped, so an internal error's traceback reached nobody.

**`revision._sha` was a byte-for-byte duplicate of `guard.sha256`**,
which this same round made public. `promote` compared a `built_on`
produced by one against a `base_hash` produced by the other, across a
gate. One spelling now.

### ~~S2 three wrong answers nothing was watching~~ — FIXED 22.08
<!-- status: fixed -->

**`audit_parts` returned a false all-clear on a file it could not
read.** `roots, _malformed = _roots(parts)` dropped the message and
audited an EMPTY list of roots, so a package whose `document.xml` does
not parse got "no duplicate bookmark names". `lint_parts` returns that
message; the advisory half is public API and a caller reaches it on its
own.

**`refstyle --ignore` cleared only half of a finding.** `audit` passed
the paper's not-an-author list to its own `_resolve_lead` and not to the
one inside `_check_prose`, which had no `ignore` parameter at all. So
"Data from Regional Household Surveys and Cameron and Roodman (2019)"
cleared its missing-ref half and kept `et-al: 3 authors named in text —
write "Surveys et al."` on the same phrase, which no value of the flag
could reach. The flag exists because the paper cannot clear it any
other way.

**`ingest`'s own state report named a deleted temp file.** It called
`state(live)` with the snapshot copy it was reading from, so
`IngestReport.working_state.path` pointed inside
`docxkit_snapshot_xxxx/`, already rmtree'd by the time the caller saw
it, and carried `from_snapshot=False` inside a report whose own flag
said True — two flags on one report disagreeing about the same fact.
`_state(parts, path, snapshot)` builds the state from parts already
read, so the report names the author's file and nothing is read twice.

### ~~S3 `docxkit lint` exited 1 on advisory findings, which is the gate the library split apart to avoid~~ — FIXED 22.08
<!-- status: fixed -->

`lint.audit` exists because the duplicate-bookmark check "shipped
inside `lint` for one commit and bricked every mutating command on a
manuscript that already had a duplicate, under a message that was not
true of it". The library split is right. `cmd_lint` then returned 1
whenever EITHER list was non-empty, so a manuscript Word opens
perfectly — one duplicate bookmark name and nothing else — failed the
command, for every CI job and paper script keyed on `docxkit lint`.
Same gate, one layer up, on a condition the toolkit still offers no
command to clear.

Advisory findings are printed and do not fail. `--strict` is there for
a caller who has cleared them and wants them kept clear, and the
default run says so in one line rather than leaving the reader to
wonder why a printed finding did not fail.

### ~~S3 Word's own anchors reached the loss gates, and one of them REFUSES the build~~ — FIXED 22.08
<!-- status: fixed -->

Teaching `internal_links` the `REF` form fed Word's auto-minted
`_Ref211944524` names into three comparisons that ask "what went
missing between these two versions":

* `compare_collateral` — a spurious `link dropped: -> _Ref211944524` on
  every build of a paper that uses Insert ▸ Cross-reference;
* `accepted_losses` — the same, and `build` turns that list into a
  `PackageError`;
* `revision._link_changes` → `losses`, which blocks `baseline`.

**Compare re-mints those names**, so the comparison is of two spellings
of one thing: a bookmark dropped and another gained, every time, for
doing nothing. The bookmark half was exposed before this round too;
only the link half was new.

`_xml.word_minted` names the rule once — Word reserves the leading
underscore, `_Ref`, `_Toc`, `_Hlk` — where `revision._bookmarks` had
been carrying it as an inline `startswith("_")`. The loss gates leave
those out on both sides.

`revision._links` does not drop them, it RE-KEYS them: the anchor
becomes one stand-in and the visible LABEL stays, so a cross-reference
that really went is still a loss while a rebuild of the same one is
not. The label is what a reader would miss anyway.

The same reserved prefix reads the other way in `_cite_audit._reached`,
where it is what says two names are one destination — worth knowing
before someone "simplifies" one of the two.

### ~~S1 two gaps shared one key, so a link at the top cleared a bookmark at the bottom~~ — FIXED 22.08
<!-- status: fixed -->

`_reached` files each bookmark under the PLACE it sits in: a paragraph
index, or a negative key for the gap Word hoisted it into. Both ends of
the document produced **-1**. A marker above the first paragraph took
`-1 - 0`; one past the LAST paragraph fell to the `else -1` default,
because the inner `next` had no paragraph to name.

So a linked `_Ref` hoisted above the opening line cleared a house
bookmark sitting after the final paragraph — one place, two ends of the
document — and the REF WITHOUT CITE line that says nothing reaches it
went quiet. Suppressing a real finding is the wrong answer this
function's own docstring says it exists to avoid; it arrived through
the arithmetic instead of through the rule.

`len(paras)` is the honest index for "after everything", and the gap
key is then `-1 - i` in every case, with no special one to fold.

### ~~S1 a four-digit page number was read as a second work~~ — FIXED 22.08
<!-- status: fixed -->

`(Acemoglu and Robinson 2012, 1215)` produced TWO citations: the work,
and a phantom by the same authors dated 1215. `audit_links` then
reported `UNLINKED: "1215)" — looks like a citation but is not
hyperlinked`, and the `Mentions: X of Y linked` line — a completeness
claim about the paper's links, added the same week — counted 2 where
the paper has 1.

Four-digit locators are routine: AER, JPE and QJE volumes all run past
page 1000. The comma-separated year list that made `Sen (1985, 1992)`
work reads one exactly like the other, and `(Sen 1999, 45)` was safe
only because 45 is not four digits.

`_works` decides how many of a group's numbers are works: **a list of
one author's works runs FORWARD**, so a number earlier than the first
year closes the list and is a page. A backstop at 2100 catches the
other direction, where a locator sorts after the year it follows. The
citation's SPAN still covers the locator, because that is what the
sentence says and what the linker must wrap.

### ~~S1 a horizontal rule after a caption took its table away~~ — FIXED 22.08
<!-- status: fixed -->

`_owns_an_image` asked "is there a picture after this caption" and
nothing else. When the caption sits UNDERNEATH its table — AFI's Tables
3 and A3, HCW's Table 7 — there is no table below to rule the picture
out, so any later `<w:pict>` answered yes: `by_caption` returned no
table, and with `required=True`, the default, it raised. For a table
sitting directly above the caption that names it.

`<w:pict>` is also Word's spelling for a HORIZONTAL RULE, and
`<w:drawing>` for any inline logo or chart, so the trigger is ordinary
document furniture rather than a figure.

The rule that was missing is in the caption's own label: **"Table 1."
names a table whatever follows it.** `find.TABLE_LABELS` says which of
the four labels those are, `_beside` reads each caption's label once
where it already has the text, and the picture question is asked only
of the rest. A caption the pattern does not match is read as a table
caption — the conservative answer, and the figure captions this exists
for all match.

The HCW behaviour it was built for is unchanged: `[Table 8][cap Figure
1][image]` still gives Figure 1 no table, and Figure 8's 2x2 grid of
panel images is still a table.

### ~~S1 `crossrefs` could not see a Word cross-reference, so `unlink` removed the bookmarks and left the fields dangling~~ — FIXED 22.08
<!-- status: fixed -->

Teaching `internal_links` the `REF` form on 22.08 left `crossrefs`
reading the two it already knew. On a document whose exhibit mentions
are Word cross-references, `field_targets` returned an empty set,
`unlink` reported "removed 2", deleted both exhibit bookmarks and left
every REF field live and dangling — **the precise answer its
ConversionGap guard exists to refuse**, arriving through the one door
the guard was not watching. `audit` was blind the same way.

One reader now, `_xml.field_anchors`, over both field forms and used by
`field_targets`, `_mention_offsets` and `internal_links`. The private
`_FIELD_ANCHOR_RE` is gone: an acknowledged duplicate is still a
duplicate, and this is the second time that sentence has been written
in this module.

**`\h` is what makes the field a link, and it was not being required.**
Word renders a switchless `REF` as static text a reader cannot click,
so counting one as a link cleared the house bookmark beside it and
suppressed both the ORPHAN REF and the REF WITHOUT CITE line that say
so. But a switchless field still DEPENDS on its bookmark — removing the
target breaks it into "Error! Reference source not found" — so the two
callers ask different questions: `ref_anchor(clickable=True)` for "can
a reader follow this", `clickable=False` for "would removing the
bookmark break something". `field_targets` asks the second.

**The name may arrive quoted.** `([^\s\]+)` took the quote with it on
a nested field (`IF 1 = 1 "REF Table1" ""`) and produced the anchor
`Table1"` — a name no bookmark has, reported as a BROKEN LINK and
carried into `tracked`'s loss gates as a target that vanishes on the
next rebuild.

### ~~S2 neither audit reads a Word CROSS-REFERENCE, so a working link reports as "the mention reaches nothing"~~ — FIXED 22.08
<!-- status: fixed -->

`internal_links` reads the third form now — `REF <bookmark> \h`, which
is what Insert ▸ Cross-reference writes — alongside the `w:hyperlink`
element and the `HYPERLINK \l` field. `\bREF\s+([^\s\\]+)` keeps
`PAGEREF` and `NOTEREF` out, and the name is unquoted, which is the one
shape difference from a HYPERLINK instruction.

Reading the field was only half of it. The finding fires on the HOUSE
bookmark, and Word's cross-reference never points at that one: it mints
its OWN anchor at the target (`_Ref211944524`) and points the field
there, so `Table6` is targeted by nothing while the mention lands
exactly where it should. `_cite_audit._reached` answers the question the
report was actually making — does a link arrive at this PLACE — where a
place is the paragraph a bookmark sits in, or the gap Word hoisted it
into.

**Only Word's own anchor confers reach, and that restriction is the
whole check.** The first cut cleared any bookmark with a linked
neighbour, and on li7 that silently dropped `Luhmann2016`, whose marker
shares a gap with `Kotze2022`'s: a click on the Kotze citation says
nothing about whether anything reaches Luhmann's entry. Suppressing a
real finding is the same class of wrong answer as inventing one, so the
rule names the reserved leading underscore — `_Ref`, `_Toc`, `_Hlk` are
Word's, and one of those beside a house bookmark is one destination
under two names.

Measured across the corpus: HCW **9 → 5** findings, all four false
ORPHAN REFs gone and its two NO BACK-LINKs and three UNLINKEDs kept.
LE, DSI, Parental Style, FLOPS v34, Aging_Well and AFI's `prev` report
byte-identically to before; li7 keeps all 29 of its findings, and the
one difference in its report — their order — is the separate defect
below, which the A/B is what turned up. `crossrefs` and `citations` now
agree on HCW's twenty exhibits. Three tests pin it, and each was
mutation-checked against the rule it guards.

**Measured and NOT changed:** `dead_links` still reads only the
HYPERLINK form, so a cross-reference rendering to nothing would go
unreported. The corpus holds 7 REF fields, none empty and none
unrendered — an unexercised path, and a check nothing has ever fired is
worse than the gap while it stays that way. Worth doing the day a paper
produces one.

### ~~S4 the citation report's order was decided by PYTHONHASHSEED~~ — FIXED 22.08
<!-- status: fixed -->

Found while A/B-ing the entry above: two runs of `docxkit citations` on
li7, same file and same code, reported the same 29 findings in a
different ORDER. REF WITHOUT CITE sorts a SET by paragraph position, and
position is not a total order — several reference markers hoisted
body-level into one gap tie, and the set supplied what came next, which
Python varies per process.

Cost is small and specific: the report is read against the manuscript
top to bottom, and it is DIFFED between rounds, where reordering reads
as churn that isn't there. The name breaks the tie now. Confirmed
identical across four hash seeds.

### ~~S3 the coverage floors read a RED suite as a measurement~~ — FIXED 22.08
<!-- status: fixed -->

`coverage_floor.measure()` runs the suite itself and reads the JSON
report. `check=False` is right — the report has to be readable when
pytest exits non-zero — but the exit code was thrown away with it, so a
run that stopped part-way was compared against the floors as though it
had finished.

**Seen once, 2026-08-21**, and it is what sent this round looking: one
failing test in the tables suite, and the tool reported

    _table_core.py: 55.8% is below its floor of 85%

for a module whose tests are all present and were mostly never reached.
A number from a partial run is not a low number; it is not a number. It
refuses now, names the failure it stopped on, and quotes no percentage.

The environment question still comes first: a pytest that rejects
`--cov` also exits non-zero, and "the suite is RED" would send that
reader somewhere there is nothing wrong. `tests/test_coverage_floor.py`
pins all three paths.

### Not a defect — the Windows fatal exception in a GREEN run
<!-- status: not-a-defect -->

`pytest -q tests/test_cli_revision.py` prints, in most runs:

    Windows fatal exception: code 0x800706be
    Thread 0x0000b924 [pytest_timeout tests/test_cli_revision.py::…]

`0x800706BE` is `RPC_S_CALL_FAILED` — Word's COM teardown, raised as a
FIRST-CHANCE exception that faulthandler prints and the process
survives. The run passes; the exit code is 0. CONTRIBUTING already says
to expect these from `pytest -m word`, and this is the same thing
reaching the everyday suite through a COM proxy released late.

Chased on 2026-08-22 because it looked like a hang. It is not: the
slowest test in the suite is 6s against a 300s ceiling, the label names
whichever test owns the timer thread rather than a culprit, and six
consecutive full runs were green. Recorded so the next reader does not
spend the same hour — what it costs is a fatal-looking line in a green
run, which is a real cost, but not a defect to fix here.

### ~~S1 a FIGURE caption takes the table ABOVE it, and every table caption in the paper shifts~~ — FIXED 21.08
<!-- status: fixed -->

**A paper's gate went red without the paper changing.** HCW's
`test_paper_values.py` was 19 green on 08-08 and 12 RED on 08-21 with
`working.docx` byte-identical to `build/prev.docx` and its repo clean.
The manuscript had not moved; this toolkit had. The failures read like
data errors — `Table 4. Old-Age Dependency Ratio for Albania: paper says
2023.0, pipeline says 22.6611` — because the value came out of the
wrong table.

**Cause: the constraint propagation `_beside` gained on 08-20** (the
entry below this one) assumes every caption wants a table. HCW's
exhibits end `[Table 8][cap Figure 1][image][cap Figure 2][image]`, so
"Figure 1." had no table under it, the table above was its ONLY
candidate, and the propagation — which exists to honour a caption that
has no choice — handed Table 8's table over. Each table caption then
shifted one exhibit up, all the way to "Table 1." answering with the 1x2
grid that holds equation (2). The UNCAPTIONED equation tables are what
let it run the whole length: they give "Table 1." a second candidate, so
nothing is forced from the top and the figure end decides everything.

Eight lookups, eight wrong tables, and not one of them a `None` that
`required=True` could fire on — the same silent shape as the defect the
propagation was added to fix.

**Measured on five manuscripts, before and after:**

| paper | captions resolving to the wrong table |
|---|---|
| Parental_style | 10 of 10 (Tables 1-5, A1-A5), plus Figure 1 |
| HCW | 8 of 8 (Tables 1-8), plus Figure 1 |
| AFI | 2 (Tables A4, A5), plus Figure A1 |
| HPPA | Figure 1 took an uncaptioned 18x3 list |
| Aging_Well | none |

**Fix.** `_owns_an_image` in `_table_core.py`: a caption whose own
exhibit is a PICTURE owns no table at all. Only the side the convention
names is asked — a picture ABOVE a caption is as often the previous
exhibit's as this one's, and a figure captioned underneath its image
needs no help, because the table above it is either behind another
caption or claimed by the caption sitting on top of it. Two clauses
carry the rule and both are pinned by mutation: the picture must be
NEARER than the table below (HCW's Figure 8 is a real 2x2 table of panel
images, and a picture inside a table always sits after that table's
start), and it must not stand behind another caption (a table captioned
underneath, with the next figure's caption below it, keeps its table).

The regression test is HCW's shape with the uncaptioned grid included;
without the fix it reports "Table 1." as the equation grid, which is
what the paper's gate was reading.

**Worth keeping:** the report that opened this was not "wrong table", it
was twelve numeric assertions failing on a manuscript nobody had
touched. A paper's suite going red the day after a shared toolkit ships
is a question about the toolkit first.

### ~~S2 a DUPLICATE bookmark name is invisible to every gate~~ — FIXED 21.08
<!-- status: fixed -->

**Found by testing the Word path on a second paper.** A one-word round
through `tracked.build` on FLOPS v34 came back **20 bookmarks lighter**
(173 -> 153, on the accepted AND the rejected view) and failed the
structure gate — whose message blames a move, and there was no move.

The twenty were all citation markers, several of them repeated:
`AykutEtAl2026txt` x6, `WorldBank2024txt` x4, `IMF2025txt` x3. They are
DUPLICATE DEFINITIONS of one name. A bookmark name may be defined once;
Word keeps whichever copy it meets first, so every link to that name
lands on a coin flip, and Compare discards the extras outright — which
is exactly what it did.

**Nothing said so.** On the same file:

    docxkit lint       clean - no structural problems found
    docxkit citations  Bookmarks: 153 ... ALL CHECKS PASSED

`citations` reports 153 because it keys bookmarks BY NAME — an audit
built on a dict cannot see a name twice — and `lint` had no check for
it at all. The paper's own `_bookmark_names` docstring describes this
failure ("two bookmarks of the same name in one document, which Word
resolves by keeping whichever it finds first, and every link to it then
lands on a coin flip") and the builder guards against CREATING one;
nothing looked for one that was already there.

**Measured before writing the check**, on 400 real manuscripts: 24 carry
a duplicate, and all 24 are that one paper — v19 through v34, including
`JITED_manuscript_anonymous.docx` and
`JITED_manuscript_with_author_details.docx`, the files that went to the
journal. Every other manuscript in the corpus is clean, so the check is
silent everywhere it should be.

**Fix.** `lint.audit` / `lint.audit_parts` — the twin of check 8
(revision ids must be unique across the package — same argument, one
element over), reported beside `lint` and never gating it. The
namespace is the PACKAGE's, not the part's: a citation's `<key>txt`
marker legitimately sits in footnotes.xml while the entry links to it
from the body.

**It shipped inside `lint` first, and that was an S3.** `beea6e6` put
the check in `lint`, and three callers refuse a write on `lint`'s
answer — `cli._save`, `tracked.build`, `revision.validate`. So every
mutating command on a manuscript that ALREADY had a duplicate died with

    REFUSED: the package would not open cleanly in Word; nothing was written

which is not true of this finding. Word opens the file; the links are
just wrong. Reproduced on the FLOPS submission file:
`docxkit authors --set … --write` exited 1 and wrote nothing, over a
condition the toolkit offered no way to clear. A gate nobody can
satisfy is the shape this file ranks ABOVE a wrong output, and it was
introduced by the commit that fixed one.

The split is the lesson, not the patch: **`lint` answers one question —
will Word refuse to open this — and its callers are entitled to that
meaning.** A correctness finding cannot live there however much it
belongs beside it. `docxkit lint` prints both, under a heading that says
which is which; `_save`, `tracked.build` and `validate` see only the
refusals. Pinned by `test_a_DUPLICATE_never_refuses_a_write` and
`test_a_DUPLICATE_bookmark_does_not_refuse_the_WRITE`.

**Left for the paper:** FLOPS had 12 duplicated names. Fixed at source
on 2026-08-21 — `link_citations_pass` in `add_calibration_v34.py` minted
`{key}txt` at every mention and now marks the first only — so the
rebuilt v34 carries 153 definitions under 153 names and survives a
Compare round 153 -> 153, where it used to lose 20. The two files in
`Documents/JITED_submission/` still carry the duplicates until the
paper re-syncs them.

### ~~S3 the agent's Bash heredocs EAT BACKSLASHES~~ — FIXED 21.08, **RE-OPENED 23.08** (see `## Open`)
<!-- status: fixed -->

> **Not fixed.** Occurrences five and six, 2026-08-23, corrupted a shared
> `tests/test_revision.py` twice in ten minutes and blocked a second session.
> The mitigations below cover the payload and the search anchor; the damage
> came through the REPLACEMENT text, where neither reaches. Entry re-opened
> at the top of `## Open` with the measurement.

**Symptom as observed.** 2026-08-20/21, three times in one session. A patch
script written as a `python - <<'PY'` heredoc reaches Python with every
backslash already halved: a `\\n` typed in the payload arrives as `\n`, and
in a non-raw string literal that becomes a REAL newline, so the file gets a
broken string and ruff reports `missing closing quote`. That half is loud.

The quiet half is `\b`. It becomes U+0008 BACKSPACE — invisible in `grep`,
in a diff and in a terminal. A regex written as `w:footnoteReference\b[^>]*`
landed in `_xml.py` as `w:footnoteReference<BS>[^>]*`, which also matches
`<w:footnoteReferenceX`, and a `\b` in this file sat as a control character
until a sweep found it.

**Why S3 rather than S4.** The loud half is a syntax error and costs a
minute. The quiet half is a REGEX THAT IS SILENTLY WRONG in the module every
other module is built on, committed green because nothing tests the boundary
that went missing — the same shape the mutation rounds exist to find,
arriving through the toolchain instead of through the code.

**Repro.** Any `python - <<'PY'` heredoc whose payload contains a doubled
backslash. Quoting the heredoc delimiter makes no difference.

**Workaround, in use.** Compose the backslash instead of typing it —
`B = chr(92)`, then build the string — or write the payload to a file with
the Write tool and exec it. Neither is a resolution: the next patch script
written the obvious way is wrong again, and wrong INVISIBLY.

**Fourth occurrence, 2026-08-23 on HCW — a shape ruff cannot backstop.**
The payload was not code being written to a file; it was a SEARCH ANCHOR for
`str.replace`. The payload was typed `old = '''… .write_text("\\n".join(lines)
…'''` — a DOUBLED backslash, because the target file contains `"\n"` and the
anchor is a plain triple-quoted string. It arrived at Python with the
backslash halved, as `"\n"`, which in a non-raw literal is a real newline. So
the anchor held a newline where the file holds backslash-n, and matched
nothing. Nothing is written to a
`.py` file, so `PLE2510` never runs — the backstop covers the payload, not the
needle. It was caught only because the patch asserted its anchor
(`assert old in s`) before replacing. **That assertion is the actual
mitigation and belongs in every patch script**, independent of this defect:
the failure mode without it is a `replace` that silently does nothing and a
script that reports success.

**Measured, 2026-08-21: ruff IS a backstop, in three of four places.**
`PLE2510` fires on a stray control character in a raw string, a plain
string, an f-string and a docstring alike — so a mangled regex in a `.py`
file fails the first gate rather than shipping. It does NOT fire on a
comment, and nothing lints `.md` at all, which is where the two that got
through this session landed (a comment-adjacent regex quote in the
backlog, and `_xml.py`'s — which ruff would have caught had it been run
before the grep that found it by hand).

So the sweep is worth running after a heredoc session for markdown and
comments; for code, the gate already refuses.

**The sweep IS a gate now, 2026-08-21** — `tests/test_control_characters.py`
reads every `.py`, `.md`, `.toml`, `.cfg` and `.yml` in the tree (421 files,
0.1 s) and fails on any control character that is not tab, newline or
carriage return, naming the file, the line and the surrounding text. That
closes the two places ruff cannot see, and "remember to run the sweep after
a heredoc session" is not something anyone should have to remember. The
pattern itself is pinned separately, because a clean tree gives the gate
nothing to find and it would otherwise be a check that cannot fail.

**CLOSED 2026-08-21 — it is the TOOL, and there is another one.** "Nothing
in this repository fixes the cause" was written twice in this entry and
never tested. The test takes one command per shell: write the same regex
to a file, read the bytes back.

    Bash tool         'PAT = re.compile("w:footnoteReference\x08[^>]*")'
    PowerShell tool   'PAT = re.compile("w:footnoteReference\b[^>]*")'

Same payload, same Python, same machine. The Bash tool's path loses the
backslash and the PowerShell tool's does not — and neither do the
Write/Edit tools, which is why every file edited that way this session
is intact while three heredocs in a row were not.

Measured on the arriving bytes, with single-quoted arguments so the
shell itself does nothing:

    typed  A\nB      arrived  A\nB     (one backslash)
    typed  A\\nB     arrived  A\nB     (one — HALVED)
    typed  A\\\\nB   arrived  A\\nB    (two — halved again)

So the rule is a tool choice rather than a habit: **a payload containing
a backslash goes through Write/Edit or the PowerShell tool.** `chr(92)`
composes one where neither is available. The Bash tool keeps everything
else, which is most things.

**The gate stays** — it is what turned this from a story into a
measurement, and it is still the only thing standing between a mangled
comment or a mangled `.md` and a commit.

Recorded in CONTRIBUTING under "A backslash does not survive the BASH
tool", where a session working here will meet it.

### ~~S2 `link_all` MARKS an entry nothing cites, and the audit reports the marker twice~~ — FIXED 21.08
<!-- status: fixed -->

**The redundancy was a theorem, not a coincidence.** `REF WITHOUT CITE`
fires for a key in `ref_marks - cited_keys`, and `cited_keys` holds
every ref bookmark some link points at — so a work reported uncited is
a work nothing links to, which is exactly what `ORPHAN REF` reports.
Measured over five manuscripts before touching anything: `uncited-only`
is **0 every time**.

    li7          as it is  ORPHAN 11  UNCITED  9  both  9
                 after link_all      22          20       20
    le14         as it is           9           6        6
                 after link_all     18          16       16
    AFI prev     after link_all      5           5        5

**Fix.** The pair collapses into the line a reader can act on — a
reference nobody cites is a decision about the bibliography, while "the
marker I just wrote has nobody pointing at it" is a description of the
marker — and that line carries what the other one said:

    REF WITHOUT CITE: 'Ghost2019' (¶8) in references and nothing points
    at it — no in-text hyperlink and no 'Ghost2019txt' marker

What is left of `ORPHAN REF` is the case that is NOT the same fact: the
`<key>txt` marker is in the prose, so the work IS cited, and the
hyperlink to the entry is gone — the reader clicking that citation
arrives nowhere. It names where the marker is.

**Two things the merge had to carry, and nearly did not.**

* **Document order.** The surviving loop sorted by NAME, and the
  absorbed one sorted by paragraph — the property fixed on 2026-08-19
  and pinned by `test_the_findings_come_in_DOCUMENT_order_not_alphabetical`,
  which would have gone green while the report went back to alphabetical
  for exactly the entries that now get only this line.
* **`repair_plan`'s reading.** It files both kinds from the same
  evidence, so a work cited in PROSE with no marker still lands in
  "recreate the lost link" — through the entry branch rather than the
  orphan one. Checked, because suppressing the finding a repair reads
  would have been the same class of defect as the one being fixed.

**Measured after:** li7 38 -> 29 as it stands and 52 -> 32 after a
`link_all` run; le14 45 -> 39 and 45 -> 29; AFI's baseline 16 -> 11.
Parental Style and DSI stay at 0 either way. 41 lines gone, none of them
carrying a fact the line under it did not.

### ~~S2 the LOST-link repair does not fire when Word left a LATER mention linked~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** `already linked` is a fact about a MENTION and the scan read it
as one about the work — any surviving link to the entry made the whole
work `already`, so the first-mention pass skipped it and the bookmark
its entry's back-link demands was never written. Word drops links
UNEVENLY; on the AFI hand-back it took the FIRST Maestas mention and
left one twelve pages on.

**Fix.** `_Mentions.unmarked`: a work whose in-text twin is DEMANDED by
a link and does not exist is a candidate however many of its other
mentions are linked. **Demanded, not merely absent** — that distinction
is the whole guard, and the first attempt without it turned a paper
wired `ref_kanbur_2007` with no in-text bookmark at all (a convention,
not a loss) into a run that tried to re-wire its linked mentions and
reported two skips where it used to report one `already`. Both cases
are pinned.

**Measured.** AFI's baseline, auditing before and after an in-memory
`link_all`: 6 -> 20 findings before the lost-link repair, 6 -> 16 with
this. le14 stays 45 -> 45; Parental Style and DSI stay 0 -> 0.

**Workaround retired:** the five hand-wired Maestas mentions in AFI's
`build_r5d.py` — see the note left in that script.

### ~~S2 `link_rest` cannot resolve an entry whose YEAR carries a letter~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** `'Maestas et al. (2023b)' (¶89): entry has no bookmark`, for an
entry that carries one. The fold must END with the work's year, and
"refmaestas2023" does not end with "2023b" — so neither of the paper's
two Maestas entries matched its own marker and `link_rest` skipped five
mentions with a reason that is false (AFI batch 28).

**Fix.** `_own_name_map` runs the search twice: the exact year, then the
BARE year for an entry whose year carries a letter. The relaxed pass
yields to a strict match and refuses a name two entries both reach for
— two works by one author in one year is precisely when a wrong guess
is undetectable, so the letter is not discarded, it is spent.

It sits under `link_all`'s naming as well as `link_rest`'s lookup,
because the same miss made `link_all` MINT a second name for an entry
that already had one — the doubling `_own_bookmark`'s docstring records.

**Workaround retired:** the five hand-wired mentions in AFI's
`build_r5d.py`.

### ~~S3 `crossrefs.audit` cannot fail on a document where NOTHING is cross-linked~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** a caption carrying NEITHER bookmark fell through all three
buckets and was counted nowhere, so five unlinked exhibits printed the
same all-zero line as a paper with no exhibits at all — and the reader
had to notice the absence of a number rather than a number being wrong.

**Fix.** A fourth bucket, `unlinked`, and the CLI prints it in the same
column as the rest: `unlinked  2  Box1, Table1`. The test builds the
case the audit exists for — a caption and a mention and no bookmarks
anywhere — and fails without it.

### ~~S4 the `crossrefs` CLI cannot be given a label the document actually uses~~ — FIXED 21.08
<!-- status: fixed -->

`docxkit crossrefs PAPER.docx --labels Figure,Table,Box`, on both
`--audit` and `--write`; `crossrefs.link` and `audit` have taken the
label set since they were written, and only the command baked
`DEFAULT_LABELS` in. Aging_Well's Box 1 audits and links now without a
script.

### ~~S1 `link` cannot repair a LOST citation link~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** a Word round-trip with track changes off drops in-text links
and the bookmarks they carried while every word on the page survives.
`link_all` then MINTED a fresh name — `ref_noone_2018txt`,
`Hudomiet2022txt` — reported `linked 7`, and left all six back-links
broken with seven orphans added beside them: the manuscript came out
worse than it went in (AFI r4 hand-back).

**Fix, and it is all evidence.** `_bookmark_names` reads what the
document says its two names are, in order:

1. the entry's OWN marker (`_own_bookmark`, unchanged);
2. **the name a dangling link DEMANDS.** The entry's back-link points at
   `cite_noone_2018` whether or not that bookmark still exists — a
   broken link naming the exact anchor to create. That is the twin;
3. **the name a surviving BOOKMARK demands.** `Kahlon2021txt` in the
   prose with no `Kahlon2021` at the entry is what `_dedup_name` turned
   into `Kahlon2021_2`, minting a second scheme beside the live one;
4. the paper's convention, then a minted name.

The entry↔twin RULE — `("ref", "cite")`, or `("", "")` for this
module's own `txt` suffix — is learned by majority from the pairs that
are still whole, so one damaged pair cannot teach the wrong shape, and
`_entry_of` runs it backwards when the ENTRY's marker is the one Word
ate. `_named` stays the last resort.

**Measured on five manuscripts**, auditing before and after an
in-memory `link_all`:

    Parental Style working.docx     0 -> 0    unchanged (a finished apparatus)
    DSI_08192026.docx               0 -> 0    unchanged
    le14.docx                      45 -> 62   BEFORE the fix
    le14.docx                      45 -> 45   after
    li7.docx                       38 -> 52   both (see the OPEN entry above)

le14 is the second manuscript with this damage and nobody had noticed:
`Halliday2020txt` alive in the prose, no `Halliday2020` at the entry,
and the old run minted `Halliday2020_2` — a parallel scheme, silently.
`test_link_all_creates_the_name_a_BROKEN_BACK_LINK_demands` fails
without the fix with exactly the reported symptom.

**Workaround retired:** AFI's `repair_r4_handback.py`, and the
hand-wiring r4 batch 23 did for the same reason.

### ~~S4 read-only `revision status` and `ingest` refuse on a Word lock~~ — FIXED 21.08
<!-- status: fixed -->

`package.readable(path)` yields `(path, copied)`: the path itself, or a
byte COPY when Word holds the file — which is what the measurement in
the entry showed works when a direct read does not. `state` and
`ingest` read through it, every read in one ingest goes through the SAME
copy (`compare` included — half an answer from a snapshot and half from
a file being edited would be worse than either), and both report
`from_snapshot` so the CLI can say

    read from a SNAPSHOT: the author has the file open in Word, so this
    describes the moment the copy was taken, not whatever they have typed since.

A snapshot mid-edit is a true statement about a moment; the alternative
was no answer at all, at the one moment the command is most useful. If
the copy fails too, the old refusal is what comes back.

### ~~S4 `locate` and `probe` call their positional an ANCHOR and mean a PHRASE~~ — FIXED 21.08
<!-- status: fixed -->

Both positionals are `phrase` now, `--anchors-from` is `--phrases-from`
(the old spelling still accepted), `probe(path, phrases=…)` fills
`Probe.phrases` and its report says `phrase '…'` — and the field-form
line says `field-form anchors (bookmark names)`, which is the other
sense, named.

The miss now explains itself when it can:

    NOT FOUND  'cite_kakwani_1977' — that is a BOOKMARK name, not words
    on the page; this searches the laid-out text (try `docxkit citations`
    or `docxkit probe`)

A wrong answer that reads like a finding costs more than the sentence
that prevents it.

### ~~S4 `docxkit.batch` re-exports `DOCUMENT` but not `FOOTNOTES`~~ — FIXED 21.08
<!-- status: fixed -->

`FOOTNOTES` and `ENDNOTES` too. Bookmark ids must be unique across the
whole document, notes included. One line, plus the test that says why.

### ~~S1 nothing ties a batch to the BASELINE it was built on~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** a refused `revision build` left the PREVIOUS redline in
`build/batch.docx`, and nothing downstream could tell. `validate` then
validated the R1 redline — two baselines and one author round old —
and printed a detailed, entirely plausible `VERDICT: FAIL` with twenty
`LINK LOST` lines describing a batch nobody was working on. `promote`
was the dangerous half: its `StaleBatch` guard asks whether the AUTHOR
moved (`live == base`), both were in sync, so it would have copied a
generation from before the whole citation apparatus over
`working.docx` with the rescue copy as the only way back.

**Fix.** `tracked.build` stamps `base_sha256` — the ORIGINAL's content,
not `"original": "prev.docx"`, which is a path whose content changes on
every `baseline` — and `guard.base_of(batch)` reads it back.

* `revision.validate` makes it **gate 0**: `built_on_this_baseline`
  False aborts before lint, because every gate below compares the two
  and would describe the wrong pair. `docxkit revision validate` prints
  which hash the batch names and exits 2;
* `revision.promote` raises `StaleBatch` on the same evidence — the
  direction that loses work silently;
* an UNSTAMPED batch answers None, not False. A hand-authored vehicle
  (the DSI path) and a batch built before the field existed cannot say,
  and refusing on "cannot tell" would break both.

`guard.sha256` is public now; `guard.base_of` is the reader. Tests:
`test_validate_ABORTS_on_a_batch_built_on_another_baseline`,
`test_promote_refuses_a_batch_built_on_ANOTHER_baseline`, and the two
beside each one that pin the fresh and the unstamped cases.

**Workaround retired:** "delete `batch.docx` after every promote". The
one that stays is real and belongs in CONTRIBUTING, not here: never
pipe a protocol command into `tail` — the shell gives you `tail`'s exit
code.

### ~~S2 `build_overrides` ingests BODY paragraphs only~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** the alignment ran over body paragraphs and both note stores
were read for one thing, remapping the ids Word renumbered. An edit the
author made INSIDE a footnote or endnote definition produced no
override at all, so the next clean build regenerated from a source that
never received it — while `revision.ingest` DESCRIBED the edit, because
`compare` reads every part a reader sees. Named in the report and
dropped by the fold-back: the pair reads as "handled".

**The design change, taken.** An override entry grows an optional
`part` key:

* `ingest.build_part_overrides(baseline, edited)` → `{part: [(old,
  new), …]}`, every part a reader edits, aligned by the same `_align`
  the body always used;
* `ingest.apply_part_overrides(parts, overrides)` takes the PACKAGE and
  reads each entry's `part`, defaulting to `word/document.xml` — so a
  store written before this key applies exactly as it always did, which
  is what the three paper pipelines holding one need;
* `update_overrides` writes `part` only when it is not the body (an
  existing store stays byte-comparable) and chains WITHIN a part: two
  stores' paragraphs can be byte-identical — "Source: authors'
  calculations." under a table and in a note — and chaining across them
  would rewrite the wrong entry;
* `build_overrides` still returns the body's list, and now RAISES
  `errors.NoteEdit` when a note edit exists rather than returning `[]`,
  which was indistinguishable from "the author changed nothing".
  `allow_note_loss=True` is the old behaviour, deliberately;
* `apply_overrides` refuses a store naming another part instead of
  counting it as a miss: it has one string to write into, so "the build
  moved under them" would be the wrong reason.

The pinning test that said "notes are ingested now — update the
docstrings and BACKLOG" did its job: it is now
`test_an_edit_inside_a_NOTE_is_ingested_per_PART`, with four more
around it.

**Known limit, documented:** a part present on ONE side only is
skipped. A missing part is a package loss (`missing_parts`,
`revision.ingest` gate it), and a note store appearing for the first
time has no baseline paragraph to anchor an insert on.

### ~~S2 a MULTI-YEAR citation parses as nothing at all~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** `find_citations("Sen (1985, 1992)")` returned `[]`. Not the
first year — NOTHING, so the author went missing with the extra years.
On Aging_Well that was 3 mentions covering 5 works: `refstyle` reported
every one as an uncited entry, and `link_all` skipped them while
reporting a clean sweep. The audit and the linker were blind in the
same place, which is why they agreed.

**Fix.** `_YEARS` — a comma-separated year list — replaces the single
`_YEAR` in both `_SEGMENT_RE` and `_NARRATIVE_RE`, and `_per_year`
expands the group into one `Citation` per work. The spans TILE the
match rather than repeating it: "Rowe and Kahn (1987" and "1997)",
because the linker wraps each span and two hyperlinks over the same
words is what `audit_links` calls a DOUBLED LINK. A single year is the
whole match, exactly as before.

The list stops at anything that is not a year, which is what keeps the
neighbours: "(Cameron et al. 2008, Roodman et al. 2019)" is still two
works and "(Sen 1999, 45)" still one work with a locator. Eight forms
are pinned in `test_a_year_LIST_is_one_citation_per_year`.

`refstyle._check_prose` skips the author-level checks for a span that
shows no author name, or "3 authors named in text" would be reported
twice about one written phrase.

**Not fixed, and out of reach of this change:** "Sen's capability
approach (1985, 1999, 2009)". The name is not adjacent to the
parenthesis, and admitting intervening words is how the grammar's
recorded false positives were made.

### ~~S2 `citations` counts a WORK, not a MENTION~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** after `link_all`, Aging_Well's audit said `0 unlinked
citation-like mentions` and `ALL CHECKS PASSED` while 20 of its 73
in-text mentions were plain text — the author found one by clicking it.
"Unlinked" was evaluated per WORK, which is the right question for "is
any reference orphaned" and the wrong one for "is the apparatus
finished", and one number answered both.

**Fix.** The mention itself is the first test now:
`masked_visible_text` over the paragraph, the same evidence `link_rest`
uses to decide what is left to wire.

* `stats` gains `mentions`, `mentions_linked` and `later_unlinked`, and
  `docxkit citations` prints `Mentions: 53 of 73 linked` — the number
  that tells the middle state from the finished one;
* a plain mention of a work that IS linked elsewhere is a
  `LATER-MENTION UNLINKED` finding under `--later-mentions`
  (`audit_links(later_mentions=True)`). Opt-in, because whether later
  mentions link at all is the paper's house style and a gate nobody can
  satisfy stops being read;
* the mask subsumes two label tests that were written for it — a link
  whose label stops a character short ("Davletov et al. (2016") and a
  label sitting INSIDE an over-read span ("Surveys and ILOSTAT (2024)")
  — so `_labels_by_para` is gone rather than left as dead code.

**Workaround retired:** Aging_Well's hand-rolled span scan in the
scratchpad.

### ~~S2 `docProps/custom.xml` is exempted as "Word regenerates it on save"~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** `REGENERATED_BY_WORD = ("docProps/",)`, so the parts gate
skipped a part Word does not synthesise. On the Aging_Well Bank
manuscript that part carries the MSIP sensitivity label and
`ClassificationContentMarkingFooterText = "Official Use Only"`: a
promote would have copied the batch over `working.docx` and the
document would have quietly stopped being labelled, every gate green.

**Fix.** `package.regenerated_by_word(name)` replaces the prefix test at
all three sites. `app.xml` and the thumbnail stay exempt — measured, 39
of 475 real manuscripts carry a thumbnail, so calling one a loss would
be a false alarm — and `docProps/custom.xml` joins the parts gate.
`tracked.build`'s default `carry` now includes it, so it is restored the
way the `customXml/` store already was.

**Workaround retired:**
`Aging_Well/revision/scripts/restore_compare_losses.py`'s custom.xml half.

### ~~S2 `restore_parts` cannot restore a FOOTER~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** the relationship walk keyed on the rels Target with `../`
stripped, which is the customXml spelling and nothing else. A footer's
Target is `footer3.xml` while the part is `word/footer3.xml`, so every
part under `word/` was in a hole: the file came back, referenced by
nothing, which Word ignores — the loss again, now invisible to the
parts gate because the file is present. And even with the relationship
back, Compare had also dropped the `<w:footerReference>` from the
section properties, which restoring a part cannot know.

**Fix, all four edits.**

* `_resolve` resolves a Target against the folder of the part its rels
  file describes (`posixpath.normpath`), which answers both spellings
  with one rule and no special case;
* EVERY rels part is read, not the document's alone — that is what
  reaches `docProps/custom.xml`, whose relationship lives in the
  PACKAGE rels;
* `_restore_section_references` puts the `w:headerReference` /
  `w:footerReference` back, reading the type off the source document's
  own sectPr and pairing sections BY POSITION, which is the only
  pairing available since a sectPr carries no name;
* what could not be wired is REFUSED — `PackageError` naming the part —
  rather than returned in the restored list. Measured against the
  SOURCE: a part the source does not reference either is being put back
  exactly as it was, and a target with no rels part at all is a
  fragment assembled in memory, not a dropped reference.

`tracked.build`'s docstring no longer says a header "wants a person" to
carry across; what still wants a person is whether the section the
reference lands in is the one the author meant.

**Workaround retired:** the same paper script's other three edits.

### ~~S4 no safe way to set run properties without walking into a field~~ — CLOSED 21.08
<!-- status: fixed -->

`edit.set_run_properties` and `edit.is_field_run` landed 2026-08-20.
What was left open was one question: whether AFI's r3 note about
`fig5_firstref` being "re-stripped by Word on EVERY edit of that
paragraph" was this bug attributed to Word.

**Checked, on the manuscript. It was.** `probe(prev.docx)` reports
`MIXED (61 element, 94 field)`, and the field-form anchors include
`fig1_firstref` … `fig10_firstref`, every table caption, and 26
citations. Figure 5's caption is `fldChar begin` / `instrText HYPERLINK
\l "fig5_firstref" \h` / `separate` / label / `end`, byte for byte the
construct r4 found on Figure 10 — so r4's "Figure 10's caption is the
only one built as a field-code hyperlink" was wrong, and `skip_fields`
matters on forty-odd captions rather than one.

(The OTHER r3 finding is a different site and a real document defect:
the in-text "Figure 5.c" mention carried an EMPTY `<w:hyperlink>`
element with its label lost, repaired by the paper's
`repair_fig5c_link.py`.)

Nothing to change here — `probe` already answers the question, and it
was never asked.

### ~~S4 `_NO_ITALICS_MARKERS` knows "working paper" and not the other names a series goes by~~ — FIXED 21.08
<!-- status: fixed -->

**Was:** both of Aging_Well's italics findings were false — "Social
Development Papers No. 1, Asian Development Bank" and "Research
Memorandum, European Centre Vienna", the working-paper format under
names the marker list did not carry.

**Fix.** The SHAPE, as the entry proposed: `_SERIES_NO_RE` matches a
capitalised series word followed by a capitalised "No. <n>", plus
"memorandum" and "technical report" on the marker list. The capital is
load-bearing — a Chicago issue number is written lowercase after the
volume ("34, no. 4"), and exempting that would suppress the finding the
check exists for. "World Development Report 2020" is still flagged;
both cases are pinned.

### ~~S2 `refstyle` reads "<Capitalised noun> and <Source> (Year)" as a two-author citation~~ — CLOSED 21.08
<!-- status: fixed -->

The LINKED half was fixed 2026-08-20 (`_trust_the_links`). The UNLINKED
half now has the only answer that is not a guess: the paper says the
word.

`resolve_lead(c, ignore=…)` STRIPS an ignored lead from a chain instead
of the caller dropping the citation on its surname — which took the
real half with it, so ILOSTAT's entry was then reported UNCITED: one
false finding traded for another. `docxkit refstyle --ignore Surveys`
and `docxkit citations --ignore Surveys` reach it from the command
line, and both audits and the linker pass it through, so a mention
narrowed this way is still LINKED rather than skipped.

Which words a paper's prose puts before "and" is the paper's
vocabulary, not the engine's — that is the seam this belongs on. The
other answer remains `docxkit link --write` first.

**Still not taken, and still deliberately:** inferring the same thing
from the reference list. It fires on the false positive AND on a real
two-author work missing from the list whose co-author has a same-year
entry, which turns an S2 false finding into an S1 silent one.

### ~~S4 `refstyle` converts the punctuation but not the NAMES~~ — DECIDED 21.08
<!-- status: fixed -->

The mechanical half ships (`convert`, `--fix`). The name half is not a
gap waiting to be filled, it is a decision: reducing "Till Von Wachter"
by last-word-is-surname gives "Wachter, T.", a RENAMED AUTHOR in a pass
whose premise is that no author changes, and the particle set that
would prevent it is a claim about names rather than a fact about the
document. `check_entry` reports the spelled-out given name and a human
acts on it. The trailing-initial period ("Allen, S..") is a trap
belonging to a reduction that does not exist.

Recorded here so it is not chased twice. The italics half is the same
answer: which span is the outlet is a judgment the audit deliberately
does not make.

### ~~S1 splitting a run DUPLICATES its `<w:noBreakHyphen/>` into every fragment — and no layer of `compare` can see it~~
<!-- status: fixed -->

**Symptom as observed.** 2026-08-21, Aging_Well. The author read the printed
page and found hyphens inside his citations:

    Rowe and Kahn (‑1987‑, ‑1997‑) nor the WHO “active aging” framework (‑WHO 2002‑)

Six of them, all in §1's third paragraph. Nothing else in the manuscript was
wrong, and every gate had passed.

**Diagnosis.** The paragraph's third run held ONE real no-break hyphen — the
author's "trade‑offs". `citations.link_all` (and the hand-wired links beside
it) wrap each citation with `_cite_grammar.wrap_visible_span`, which splits
that run into `before` / `inner` / `after` through `set_run_text` and
`_styled_run`. Those rebuild a run from the source run's children with new
`<w:t>` text — and carry `<w:noBreakHyphen/>` along, so **each fragment gets
its own copy**, landing at the fragment's start. Four wraps in one paragraph
turned one hyphen into seven. Every other element a run can hold that is not
`<w:t>` — `<w:tab/>`, `<w:br/>`, `<w:sym/>`, `<w:softHyphen/>` — is in the
same hole.

**Why S1, and it is the worst kind.** `_xml.visible_text` walks `<w:t>` only,
so a no-break hyphen contributes no character to it. `compare`'s TEXT layer
is built on `visible_text`. Measured directly: comparing the manuscript
before the repair with the manuscript after it, six visible hyphen glyphs
deleted, gives

    REAL change locations (excl. glyph): 0   |   glyph-only: 0

**Zero.** The tool reports the two documents as identical while the printed
page differs. That is also why the defect shipped through R2, R4, R7 and R8:
the passes that added the copies all reported `TEXT: (none)` and were
believed. GLYPH does not catch it either — it normalises characters that
exist, and these produce none.

**Suggested fix, two halves and both are needed.**
1. `set_run_text` / `_styled_run` must not carry a run's TEXT-BEARING
   children into a fragment that does not contain them. The split is by
   visible offset, so the fix is to render those elements INTO the offset
   model — one character each — and then place them in whichever fragment
   their offset falls in. That also fixes the offsets themselves, which are
   currently short by one per hyphen in any paragraph containing one.
2. `visible_text` should render them, so the TEXT layer can see the
   difference at all: `‑` for `noBreakHyphen`, `\t` for `tab`, `\n` for
   `br`, `­` for `softHyphen`. A gate blind to a printed character is
   worse than no gate. If that is too invasive for callers that expect pure
   `<w:t>` text, `compare` needs its own rendering pass — but it cannot go on
   comparing text that omits characters the reader sees.

**Also check the other papers.** Every manuscript that has run `link_all`
over a paragraph containing a hyphenated word is exposed, and none of their
gates would have said so.

**Workaround in use.**
`Aging_Well/revision/scripts/r2_link_apparatus.py::strip_stray_hyphens`
deletes any `<w:noBreakHyphen/>` not sitting between two word characters,
and runs at the end of every apparatus pass so a re-run cannot leave one
behind. It carries its own renderer, because `visible_text` cannot show it
the thing it is repairing.

**BOTH HALVES DONE, 2026-08-21.**

**1. The split.** `_xml.split_run(run_xml, at)` cuts one run at a VISIBLE
offset into two whole runs. Both keep the run's `w:rPr` — formatting
belongs to every fragment of what it formatted — and everything else is
CONTENT, placed on exactly one side by document order. `wrap_visible_span`
cuts instead of rebuilding: `set_run_text` keeps a run's structure, which is
right for a run being rewritten and wrong for one of three fragments,
because a `w:noBreakHyphen` is structure by that reading and a printed
character by every other. One hyphen in, one hyphen out, at every offset —
pinned by mutation, including the boundary case where the cut falls exactly
on the child.

**2. The gate.** `_xml.printed_text(xml)` renders `w:t` PLUS the children
that print without being text — `‑` for `noBreakHyphen`, `­` for
`softHyphen`, a tab for `w:tab`, a newline for `w:br`/`w:cr` — in document
order. `compare`'s TEXT layer reads that now (`Para.wtext`, its only
caller), so the two paragraphs the tool called identical read as

    'Neither trade‑offs (Rowe 1987) nor more'
    'Neither trade‑offs (‑Rowe 1987) nor more'

`visible_text` is UNCHANGED and deliberately so: every anchor in four paper
trees is written against that reading, and a tab appearing in it would move
every offset after it. `w:sym` is left unrendered — its character lives in
an attribute against a font, so rendering one is a lookup, and a wrong guess
would report a difference that is not there.

**The other papers, checked rather than assumed.** Every manuscript under
the single-file protocol was scanned for a `w:noBreakHyphen` that is not
between two word characters:

    Health_Capacity_to_Work, DSI, Life_Expectancy, Loneliness Index,
    Parental_style        hyphens 0   stray 0

AFI's baseline likewise holds none (its `working.docx` was open in Word and
refused the read — correctly, and with the message the read retry gained
yesterday). Only Aging_Well was ever exposed.

**Workaround to retire:** `strip_stray_hyphens` in
`Aging_Well/revision/scripts/r2_link_apparatus.py`. It is still what
REPAIRED that manuscript; what it no longer has to do is guard every
apparatus pass, because the pass can no longer put one there.

### ~~S2 `audit_links` cannot read a paper's OWN anchor scheme, and reports its live citations UNLINKED~~
<!-- status: fixed -->

Found 2026-08-21 by auditing AFI's finished manuscript — the same blindness
`link_all` was fixed for the day before, one module over.

**Symptom.** 104 entry bookmarks, every one `ref_<surname>_<year>`, and
`_marker_owner` resolved none of them: `_KEY_SHAPE_RE` reads
`Kanbur2007` and nothing else. So `linked_works` was empty, every mention
fell through to the label test, and the audit reported

    UNLINKED: "Surveys and ILOSTAT (2024)" (¶33)
    UNLINKED: "Gmyrek et al.'s (2025)" (¶77)

on a paper that links both. `ILOSTAT (2024)` and `Gmyrek et al. (2025)` are
live hyperlinks in those very paragraphs.

**Three fixes, and the second was found by making the first.**

`_foreign_owner` reads a marker the way `_cite_build._foreign_bookmark`
reads one — fold to letters and digits, require the year at the END and the
surname inside — and still refuses when two entries answer.

That alone traded two false findings for eleven: with foreign names now
resolving, the MISPLACED MARKER check judged the mention-side markers too,
and reported six correctly-placed `cite_<surname>_<year>` as misplaced. A
marker sitting in PROSE is the back-link half of the pair and belongs where
it is, so the check now looks only inside the reference block — whose start
is the END of the paragraph before the first entry, because the gap above
that entry is where Word puts a marker it hoists.

The remaining `UNLINKED` needed the mirror of the guard that was already
there: it tested whether the CITE was inside a label, and the two-author
swallow puts the LABEL inside the cite. The year must be in the label too,
so a cross-reference falling inside the span does not clear a citation.

**What it found on the finished paper**, once it could see: one EMPTY LINK
(`fig7_caption`, ¶57 — the field's result runs are gone and the words sit
beside it as plain text) and **five entry markers stranded one entry early**
— `ref_eurofound_2025` above Erreygers, `ref_hudomiet_2022` above Hardy, and
three more. That is exactly the reorder defect the check was written for
(13 of them on API10), and it had been invisible on this manuscript because
the check could not read its names.

`_audit_findings` came down from 35 to 31 doing it: the misplaced-marker
walk is `_misplaced_markers` now.

### ~~S3 the build's math-glyph restore covers ONE view, so validate is red every round~~
<!-- status: fixed -->

Found on AFI, 2026-08-19, across three consecutive rounds.

`revision build` now restores the minus glyph Word downgrades when Compare
re-serialises OMML — it prints `restored math glyph — 't-1990' -> 't−1990'`.
But it restores it in the ACCEPTED view only. `validate`'s reject-all check
then reports

    glyphs: False   GLYPH at 62473: '−' U+2212 -> '-' U+002D

and the batch fails, on a document whose author touched nothing. The paper's
own `repair_math_minus.py` fixes the remaining side, after which validate
passes — so every round on this manuscript is: build, validate FAILS, run the
per-paper repair, validate PASSES.

**And the repair then trips the deliverable guard.** Running it changes
`batch.docx` after `build` stamped it, so the next `build` refuses with
`DeliverableModified — someone edited it in Word` and backs the file up to
`batch_user_edited1.docx`. Nobody edited anything in Word. The recovery
("delete batch.docx if that batch is already promoted") is right but the
diagnosis is wrong, and it manufactures a spurious `_user_edited` artifact
each time.

Two fixes, either sufficient: restore the glyph on both sides of the
revision, or re-stamp after an in-tool repair. Failing both, `validate` should
name **which view** it is judging — "reject-all" vs "accept-all" — because as
printed, `glyphs: False` on a batch whose accepted view is correct reads as a
defect in the edit.

**The third one is done (2026-08-20).** Every glyph line now reads
`GLYPH (reject-all vs baseline) ...`, and when the two streams become equal
once BOTH are downgraded — that is, when the substitution is the whole of the
difference — the report says so:

    every GLYPH above is a math character Word downgrades when it
    re-serialises an equation, not an edit: the ACCEPTED view has them
    restored and the REJECTED one does not.

The gate still fails, and should: the two views disagree. What changed is that
it no longer reads as a defect in the edit. Both sides are pinned —
`test_validate_says_WHICH_VIEW_a_glyph_difference_is_about` and
`test_a_REAL_edit_is_not_called_a_math_downgrade`.

**The second one is done (2026-08-20) — `guard.restamp`.** A repair the
build cannot do is not a Word session, and the repair now says so:

    from docxkit.guard import restamp
    write_docx(paper.batch, parts)
    restamp(paper.batch, why="restored U+2212 on the rejected side")

The stamp keeps the build's own provenance and grows a `repairs` list —
reason, the hash it replaced, the hash now — so "the tool changed it" is
readable afterwards rather than assumed; this is the one call that can retire
a guard. A repair that changed nothing records nothing. `guard.check`'s
refusal names it as the fourth way on, beside the three it already listed.

What this does NOT do is decide for the caller: the assertion is theirs, and
a Word edit sitting in the file when `restamp` runs is inside the hash it
records. The docstring says to call it next to the write, in the repair.

So the round is now: build, validate FAILS and says WHICH VIEW and why, run
the repair, re-stamp, validate PASSES — with no `_user_edited` artifact and
no diagnosis of an edit nobody made. The gate is still red on a downgraded
glyph, which is the first fix's job and is still open.

**Why not the first one**, looked at the same day: `restore_math_glyphs`
repairs a run only when its EXACT text appears in a source, and Compare splits
a run at the edit boundary — so the deleted side often holds a fragment no
source spells, and there is nothing to key on. Repairing it would mean
inferring from context, which that function's docstring refuses on purpose
(a hyphen inside maths is a legitimate character). It needs a real redline
from AFI to settle, and that is a decision about the conservative rule rather
than a patch.

S3 rather than S2 because the cost is a gate that is red as a matter of
routine: the third time a clean batch fails for a reason the author did not
cause is the time people stop reading it.

**SETTLED 2026-08-21, with the AFI evidence the entry asked for** — and the
answer was not the fix this entry proposed.

Read against the real files: `build/batch.docx` has its four minus signs and
its math stream is identical to `prev.docx`'s. **`working.docx` — the
finished manuscript — has none of them**: 0 U+2212 where the baseline has 4,
16 hyphens where it has 12. The paper's own log says so and says the
workaround is "not optional on this manuscript".

So the redline was never the problem. The damage arrives on the AUTHOR'S
accept-and-save, and the step that makes it permanent is `baseline`, which
copied `working.docx` over `prev.docx` — after which the hyphens ARE the
truth and every later reject-all is measured against them. It happened
twice, wave 1 and wave 2.

`losses()` reports a `glyph` loss now, matched the way the restore matches:
a run the baseline has is gone, and a run has appeared that is exactly it
with the glyphs flattened. An author who rewrote an equation is not
reported, and neither is one who put a minus back. `baseline` refuses on it
like any other hand-back loss, so this cannot become the truth in silence:

    glyph '=−0.953 -> =-0.953'
      --accept-loss 'glyph:=−0.953 -> =-0.953'

`baseline(repair_math=True)` / `--repair-math` is the answer to the
refusal, and it is the one loss this tool may put back itself: `build`
already restores the same glyph on the redline it produces, so doing it on
the other side of the hand-back is that repair, not a new liberty. The gate
runs AFTER the repair, so anything it could not reach still refuses.

**What the entry proposed and I did NOT do:** an alignment-based restore,
keyed on position rather than on text. Written, tried against the real
files, and reverted — the exact-key `restore_math_glyphs` puts back all
four AFI runs on its own, so the second mechanism solved a problem no
specimen here shows. The paper's script argues for it (a bare `-` is
ambiguous as a key); if a manuscript ever produces that case, this is the
note to come back to.

**Workaround to retire:** `revision/scripts/repair_math_minus.py`, and the
`--expect OLD=NEW` flag with it.

### ~~S2 `refstyle.convert_text` REFUSES an entry whose title contains "&"~~
<!-- status: fixed -->

Found by review, 2026-08-21, an hour after the converter landed and while
`refstyle.py` was under measurement — recorded here rather than fixed on the
spot, because the rule against editing a module mid-run is the rule.

**Cause.** The invariant normalises `"&"` to `"and"` on ONE side:

    before = _alnum(text.replace("&", "and"))
    after  = _alnum(out)

`_alnum` drops the ampersand as punctuation, so an entry that keeps its `&`
— a TITLE's, which this deliberately does not convert — reads as
`...robotsandjobs...` before and `...robotsjobs...` after, and

    Smith, J. (2020). "Robots & Jobs." Journal, 1(1): 1-10.

raises `ConversionRefused` although the converter changed nothing at all.

**Severity.** S2, not S1: `convert` catches the refusal per entry, reports it
under `refused` and writes nothing, so the failure is a false REFUSAL and
never a corruption. It is still wrong, and on a manuscript with several such
titles it is wrong loudly.

**Fix.** Normalise both sides — `after = _alnum(out.replace("&", "and"))` —
and pin an entry whose title carries an ampersand it keeps.

**Also to fix while there:** three test fixtures written this session put a
BARE `&` in a `w:t`, which is not well-formed XML and not a document Word can
produce (`lint` says so). The behaviour is right on the escaped form —
checked by hand — but the fixtures should be `&amp;`.

**Fixed the same day**, once the measurement freed the module: both sides
are normalised now — `after = _alnum(out.replace("&", "and"))` — and an
entry that keeps its ampersand is pinned, as is one that converts the
authors' and keeps the title's.

The round that freed it found a second defect in the same function, filed
and fixed together: the `et al` fix wrote a fragment its own output
CONTAINS, so a second bare "et al" in one entry re-hit the first and made
"et al..". Every other fix here writes something that does not contain what
it replaced.

And the three bare-`&` fixtures are `&amp;` now, except where the string is
passed as TEXT rather than as XML — which is the distinction the fixtures
had lost.

### ~~S4 the revision ladder opens Word two to three times per batch~~
<!-- status: fixed -->

Fixed 2026-08-21 — `word.shared_session()` and `docxkit revision ship`.

`shared_session()` pins ONE Word instance for every `session()` inside the
block. Nesting is a no-op, so a caller may wrap a ladder without knowing
which steps open Word, and if Word cannot be started at all it yields None
and every `session()` inside behaves exactly as before: this saves a start,
it does not turn "no Word here" into a different error in a different place.

`revision ship REVISED.docx` runs `build` then `validate` in one process
inside one such block. Same two commands, same output, same exit codes —
the second just finds Word already open. It STOPS on a failed build rather
than validating whatever the previous batch left in `build/batch.docx`,
which is the file `validate` defaults to and the reason this is one command
rather than a shell `&&`.

The measured cost stands as recorded (13.5 s + 38.9 s of about 95 on a
one-edit AFI batch); what this removes is the second cold start. Nothing
here has been measured against real Word — the tests fake the COM boundary,
as this repository's Word tests do — so the SAVING is the claim to check on
the next batch, not a number this entry can assert.

### ~~S4 the primitives papers hand-roll ALREADY EXIST, filed under the task that first needed them~~
<!-- status: fixed -->

Fixed 2026-08-21 — `docxkit api [TOPIC]`.

    $ docxkit api bookmark
    citations
      bookmark               Wrap `inner` in a bookmark. With no inner, a zero-length marker.
      delete_bookmark        Remove the Start/End pair `name` (id read off the Start).
      hyperlink_field        A ``HYPERLINK \l`` field pointing at an internal bookmark.
      marker_bookmark        A zero-length bookmark at the head of the ONE paragraph matching
      next_bookmark_id       One above the highest bookmark id across the given parts.
      wrap_link_in_bookmark  Recreate `name` around the ONE link that points at `anchor`.

Read off each module's `__all__` and the objects themselves, never off a
curated index: a hand-kept list of what exists is a second thing to keep
right, and the reason this command exists is that the first one was not kept
right either. A name added to an `__all__` today is findable today.

It matches the NAME, the summary line, and the SIGNATURE — "which of these
takes a caption" is the question a caller actually has, and
`placement.exhibit_block`'s summary does not use the word. `--signatures`
prints the parameters, which is what would have saved the second of two
failed attempts at wiring three citations through `hyperlink_field`.

With no topic it lists the modules and their one-line summaries: the whole
surface is some 200 lines and nobody reads it, so what a reader wants with
no topic is where to LOOK.

**Not done: the re-homing.** The bookmark helpers still live in `citations`.
Moving them to a `bookmarks` module that `citations` re-exports is a real
change to four papers' imports for a discoverability problem this command
now answers — worth doing when something else needs that module, not on its
own.

### ~~S1 `by_caption` anchors on the first paragraph CONTAINING the caption, so body prose shadows the real caption~~
<!-- status: fixed -->

**Symptom as observed.** 2026-08-21, AFI `working.docx` (r4 round).
`repkit doctor` G4 reports `no table under caption 'Table 3.'` — while the
manuscript plainly carries `Table 3. Distribution of workers across
age-friendly and less age-friendly occupations…` with a 21-row table
directly beneath it. Tables 4 and 5, whose numbers are never written
"Table 4." in prose, resolve fine. One of 23 exhibits, reported as a
manuscript defect when the manuscript is correct.

**Cause.** `_table_core.by_caption` picks the anchor with a substring test
over the whole paragraph:

    para = next((m for m in PARA_RE.finditer(xml)
                 if caption in visible_text(m.group(0))), None)

Body prose that ends a sentence with a cross-reference — "Four ECA
economies … have positive OASI values, as do the EU and … Table 3." at
offset 75,691, some 395,000 characters ahead of the caption at 470,376 —
contains the string and wins on document order. `_beside` then does its
own job correctly on the wrong anchor: the nearest table on each side is
behind another caption, so it refuses both and returns None.

**Why S1 rather than S3.** Here it produced a red gate, which is loud and
costs an afternoon of looking for a paper defect that does not exist. The
same anchor can just as easily return a table: let the shadowing prose sit
beside a table with no caption in between and `by_caption` hands that table
back with no error at all — precisely the "a wrong table is worse than no
table" case its own docstring is written against, and one `required=True`
cannot fire on. A caller reordering rows then edits a different exhibit.

**Fix.** Prefer a paragraph whose visible text STARTS with the caption;
fall back to the "contains" match only when no such paragraph exists (some
papers do run the caption inline). `_beside` already reaches one layer down
for `caption_re()` — the definition of "this paragraph is a caption" is
sitting in the same function.

**Test that fails without it.** Prose "… as reported in Table 3." placed
before a genuine `Table 3.` caption + table: `by_caption(xml, "Table 3.")`
must return the captioned table. Second case, for the silent half: put an
UNCAPTIONED table immediately after that prose paragraph and assert it is
not what comes back.

**Affects.** repkit's G4 on any paper whose prose cross-references a table
by number at the end of a sentence — which is house style, so most of them.

**FIXED 2026-08-21.** `_caption_para` prefers a paragraph whose visible text
STARTS with the caption and falls back to "contains" only when none does —
some papers do run a caption inline, and that is a preference change, not a
narrowing. `tables_after` was reading the same anchor and now shares the
helper: it asserts a COUNT, so anchoring on the prose would refuse a correct
exhibit or accept the one next door.

Three tests, and the second is the silent half the entry asked for: with an
uncaptioned table beside the shadowing prose, the old anchor handed that
table back with no error at all. All three were checked by mutation, the
fallback included.

### ~~S4 no table-ROW operations: reordering or adding a row is `w:tr` surgery every time~~
<!-- status: fixed -->

Fixed 2026-08-21 — `tables.reorder_rows`, `tables.clone_row`,
`tables.set_row`, all three exported from the facade.

`reorder_rows(xml, table, key, *, header=1, last=())` sorts the data rows by
their CELL TEXT (`key=lambda c: order.index(c[0])` is the usual form), keeps
`header` rows in place and the values named in `last` at the bottom — which
is where "All countries" belongs and where sorting it would not put it.

Both traps the entry named are owned here:

1. **The gate is on the row-tuple MULTISET.** Count is preserved by any bug
   that swaps two cells; `rows_preserved` compares every cell of every row
   before and after, so "no value changed, only the order" is a claim rather
   than a hope. A splice that drops a row raises rather than returning.
2. **`set_row` takes a WHOLE row.** A cloned row holds the values it was
   copied from, so filling three of four cells leaves the fourth reading as
   the row above — true, plausible and wrong. `None` leaves a cell on
   purpose. Each cell keeps its own properties, and a value split across
   runs has its tail blanked rather than left hanging off the new text.

`clone_row` copies the row below itself with its `tcPr` — borders, shading,
widths — because a row built from nothing has to invent all of it.

All three go through one splice of the whole table rather than a per-row
loop over spans that the previous write already moved, and all three carry
the module's freshness guard: re-read the table between calls, or be told.

**Workaround to retire:** `AFI/revision/scripts/build_r5a.py` (reorder +
multiset gate) and `build_r5b.py` (`fill_row`). Left in the paper's tree.

### ~~S4 no way to ask what is AT an edit site, so every batch surveys it two or three times~~
<!-- status: fixed -->

Fixed 2026-08-20 — `docxkit.find.site(xml, sig)` and `docxkit sites`, with
the fields the sketch named: `index, matches, text, labels, has_math,
footnote_ids, double_spaces, trailing_space`.

It refuses nothing and raises nothing. A signature matching NONE or TWO
paragraphs is the answer a caller wants — `para_slice` refuses both at build
time, and the point is to know before writing the edit — so `matches` is a
number and `index` is -1 when there is nothing. The CLI exits 1 unless
exactly one paragraph matches, which makes the same survey usable as a gate
from a script.

`labels` is the load-bearing field the entry said it was: exactly the set
`replace_in_para` refuses to cut across. `format()` prints only the facts
that ARE the case — a survey that prints eight fields of False is the noise
that sent these three questions into three commands in the first place.

`--part footnotes|endnotes` because half a manuscript's citations live
there, and `--normalize` because it is the same fold `para_slice` takes.

**A shared definition came out of it.** `find` needed the footnote-mark ids
and would have been the FOURTH spelling of that regex (`footnotes` and
`export` had one each, and `footnotes` had a third for rewriting). They live
in `_xml` now as `NOTE_REF_RE` (the id) and `NOTE_REF_EL_RE` (the whole
element, for `export`, which substitutes a marker in and would otherwise
leave the `/>` behind). The two spellings had differed on the self-closing
form, which neither of them meant.

**Workaround to retire:** `AFI/revision/scripts/sites.py`. `--refs` (walk
the reference list) and `--grep` (regex signatures) are NOT covered; if the
paper still wants those, they are a flag on this command rather than a
script. Left for its owner.

**Checked 2026-08-21** against the finished manuscript: `site(doc, "…")`
returns the same three facts the script printed for the same paragraph —
index, the link labels an edit may not cross, and the footnote marks in it.

### ~~S4 no helper for moving an EXHIBIT BLOCK, and the block is not what it looks like~~
<!-- status: fixed -->

Fixed 2026-08-20 — `placement.exhibit_block(parts, caption)` returns a
frozen `Block`: the elements, and the three traps this job walked into.

The span rule is the TABLE rule `place` has always used, generalised by one
clause — the exhibit's body is a `w:tbl` **or** a paragraph holding a
drawing — after which "everything below it that is a note or carries no
text" is what makes the section-break paragraph part of the block rather
than a spacer to leave behind. Hoisted bookmarks in front come too, for the
reason `_blocks` already records.

Both further traps are answered rather than assumed:

* `shares_a_page` — the block has no `pageBreakBefore` and the block BEFORE
  it ends a section, so its own page is borrowed and moving it loses one;
* `last_in_body` — moving it leaves the body-level `sectPr` governing no
  content, which renders as a blank page.

`ends_a_section` is the one that cost the landscape orientations.

Read-only, deliberately: it answers what the span IS and what moving it
would cost. Where an exhibit belongs is not a question a document can be
asked, and `keep_together`/`own_page`/`space_block` already take exactly
the element list this hands back.

**A layering fix came with it.** `placement` and `crossrefs` are siblings,
and `_table_core`'s new caption check reached the same way — so
`DEFAULT_LABELS` and `caption_re`, THE caption definition, moved down into
`docxkit.find`, which is below both and is the module whose whole subject is
locating things by visible text. `crossrefs` re-exports them, so every
caller still spells it `crossrefs.caption_re`. The layering gate caught the
sibling edge; the `_table_core` one it could not see, because a private
half is checked through its facade.

`any(el.iter(W + t) for t in ...)` was in the first draft of the exhibit-body
test and is worth recording: `iter` returns a GENERATOR, which is truthy
before it yields anything, so every paragraph read as an exhibit and every
caption became its own block with the table left behind. Found by hand
before the tests existed, which is the argument for the tests.

### ~~S4 `replace_in_para` refuses a relabel without naming the flag that allows it~~
<!-- status: fixed -->

Fixed 2026-08-20, both halves — the free one and the verb.

Both refusals now end with the opt-in instead of only with "move the anchor":

    ... Anchor on plain text outside the link, or pass allow_hyperlink=True
    if the replacement lies wholly inside the label and retitling it is the
    point.

    ... Replace on each side of the link separately, or pass
    allow_hyperlink=True to rewrite the label itself -- same anchor, same
    bookmark, new words.

And the verb the entry said to consider: `edit.relabel_link(para_xml,
anchor, new_label)`. It addresses the link by ANCHOR, which is the
difference from `replace_in_para(..., allow_hyperlink=True)` — a paragraph
that says "Table 3" in prose and again as a link has one span this can mean,
and matching the words would take the first. Both link forms, and a label
SPLIT ACROSS RUNS in one call, which is the case every `<w:t>`-matching
hand-roll missed. Three refusals, all silent otherwise: an anchor the
paragraph does not link to, an anchor it links to twice, and an empty label.

**Workaround to retire:** the `<w:t>`-matching passes in AFI's
`build_r4r.py`, `build_r4u.py` and `build_r4w.py`. Left in the paper's own
tree for its owner to delete.

### ~~S4 `internal_links` is public in fact and private by import path~~
<!-- status: fixed -->

Fixed 2026-08-20. Declared in TWO public homes, deliberately: `docxkit.find`,
because locating things inside one part's XML is what that module is and a
new caller should land there; and `docxkit.revision`, because its reports
talk about links so that is where the existing callers already spell it —
the same re-export `TEXT_PARTS` and `ProtocolError` get beside it. Both names
are the one object, asserted.

The second edge is refused rather than accepted. `internal_links(parts)` now
raises

    internal_links takes ONE part's XML as a str, not dict — pass
    parts[DOCUMENT].decode('utf-8'), and loop over text_parts(parts) if you
    want the notes too

instead of a `TypeError` from inside a regex naming `_xml.py`'s line. Not
made to accept the mapping: which parts it would read is a real question, the
body alone and the body-plus-notes are different answers, and the caller is
the one who knows which they mean.

The audit the entry also asked for is not a walk anyone can write: what
`test_every_public_name_is_DECLARED` cannot see is a name a module does not
DEFINE but does hand out, and nothing static says which of those a caller
needs. So the decision is pinned by name instead, in
`test_a_PRIMITIVE_a_public_module_hands_out_is_declared_THERE`.

### ~~S1 Compare CORRUPTS a replacement inside an inline OMML field, and `resolve_math` bakes the corruption in as the accepted view~~
<!-- status: fixed -->

Found on AFI, 2026-08-19, doing R3/T3.2: two inline `<m:oMath>` fields holding
`-0.20` and `-0.38` had to become `-0.398` and `-0.487`.

Word's Compare does not treat the field as a unit. It diffs INSIDE it at
character level, matches the common prefix `-0.`, and emits the rest as an
insert beside the old digits. The field comes out reading

    -0.20398        and        -0.38487

**Both routes give the same corruption.** With `--keep-math` it is tracked and
unreadable. With the default `resolve_math` the build ACCEPTS those revisions,
so `-0.20398` is baked in as the accepted view — as though the author had
asked for it. The build's own warning covers reviewability ("NO reviewable
redline as built") and says nothing about the text being wrong.

**Nothing caught it on that path.** `validate`'s accept-all reports
structure counts; `XML accept == Word accept` compares two ways of accepting
the same batch against each other. It was caught by reading the built file.

**CORRECTION, same day.** The claim first written here — that nothing compares
the accepted view against the clean copy — is WRONG, and the error is worth
keeping. `revision build` does exactly that comparison and refuses:

    accepting every revision does NOT reproduce r4e_clean.docx — 1
    paragraph(s) differ, so the deliverable the author reads is not the
    document this redline was built from

It fired later the same day on a figure move and stopped a bad build. What is
true is narrower: **that check compares paragraph TEXT**, so it passes when
the words survive and something else does not — on the same move it passed
while all four caption hyperlinks had been stripped. The gap is the check's
SCOPE, not its absence.

S1 because the failure reports success and the wrong number is in the paper.

**Two fixes, and the second matters more:**

1. Treat an `m:oMath` as atomic when diffing — replace the whole field rather
   than diffing its runs — or refuse the batch and say so.
2. **`validate` should compare the ACCEPTED view against the revised copy the
   build was given.** That check is cheap, it is the definition of a correct
   redline, and it is absent. It would also have caught this class of thing on
   any future path into the same trap.

**The second is done, 2026-08-20** — in `build`, which is where the clean copy
is in hand (`validate` is handed a batch and a baseline and never sees the
revised copy; recording its path would be a second mechanism for the same
question).

The comparison that was missing is not text and not tag counts. `unaccepted`
already compares the accepted view against the clean copy by paragraph TEXT,
and `structure_diff` already counts carriers on both sides — what neither can
see is a HYPERLINK, because it carries no text and its tag is deliberately not
in `STRUCTURE_TAGS` (Word re-represents a field-form link as an element, and
counting the tag would refuse that harmless rewrite).

`tracked.accepted_losses(revised, accepted)` compares the ANCHORS instead —
bookmark names and link targets, through `internal_links`, which reads both
forms — and `build` refuses on it under `accept_check`, because the accepted
view is the deliverable. The exact AFI shape is pinned: a link Compare rebuilt
as prose is present in the redline (so `compare_collateral` is quiet) and gone
the moment the author accepts (so the words match and `unaccepted` is quiet
too).

A bookmark cannot be lost that way and the test beside it says why: `revisions`
LIFTS bookmarks out of an element it removes. Nothing lifts a `w:hyperlink`,
and nothing can — the element carries the words.

**Fix 1, the half of it docxkit can do: also done, same day.** How Word
diffs is not ours to change, so the entry's alternative — "or refuse the batch
and say so" — is what shipped. `tracked.accepted_math(revised, accepted)`
compares the equations of the accepted view against the clean copy's, position
by position, and `build` refuses on it under `accept_check`.

The AFI corruption is pinned with the four checks that pass it, which is why
the number reached the paper: the REJECT view is correct (it restores `-0.20`),
the counts do not move, the equation renders, and `unaccepted` compares `w:t`
while an equation's characters are `m:t` — a reading `_paras` documents as
deliberate. It runs after `restore_math_glyphs`, so the minus sign Compare
flattens is not reported twice over.

What is still not done is making the redline CORRECT rather than refused: a
batch that changes an inline equation still has to apply the maths after the
Compare, as AFI does. The refusal now says so in the message.

**Per-paper workaround now in AFI** (delete when fixed): the maths is applied
to `batch.docx` AFTER the Compare, so the two values are baked in with no
redline at all — the trade v12 made for its 19 equation changes — and
`repair_math_minus.py` grew an `--expect OLD=NEW` flag so an intended math
edit is not read as damage while every other difference still refuses.

### ~~S1 a footnote whose DEFINITION is out of document order passes every read-only gate, then blows up the next Compare~~
<!-- status: fixed -->

**Symptom as observed.** AFI r4 batch 17 added a footnote by appending its
`<w:footnote>` to the end of `word/footnotes.xml` and inserting the reference
in the body. Word renders that perfectly — notes are numbered by where their
REFERENCES sit, not by where the definitions are stored — so the PDF render was
right, `verify_v14_package.py` passed 560/560 and the paper's suite stayed green.

The next batch's `revision build` then failed like a catastrophe:

    VERDICT: FAIL
    UNACCEPTED footnotes ¶7:  intended ''  accepted ' Table 4 reports a…'
    UNACCEPTED footnotes ¶11: intended ' Table 4 reports a…'  accepted ''
    GLYPH (reject-all vs baseline) at 1749 … and 81 more run(s)
    STRUCTURE footnoteReference: 7 -> 6

Nothing was wrong with the batch. **Word's Compare rewrites footnote
definitions into document order**, so the redline's `footnotes.xml` no longer
lined up with the baseline's and the whole part read as moved. Eighty-one glyph
runs and a structure count for a one-line prose batch.

**Repro.** Take any docx with footnotes 1..N. Append a new `<w:footnote
w:id="N+1">` at the end of `footnotes.xml` and put its `footnoteReference`
somewhere in the middle of the body. `revision status`, a render and any text
gate all pass. Then `revision build` a trivially edited clean copy against it.

**Why S1.** Every read-only gate reports success on a file Word would never
have written, and the failure surfaces one batch later, attributed to the
innocent batch. I spent a build+validate cycle (52 s) and a diagnosis on a
defect introduced two batches earlier.

**Workaround** — `AFI/revision/scripts/renumber_footnotes.py`: remaps ids to
reference order and reorders the definition blocks to match, idempotent, refuses
if a reference has no definition or a definition nothing references. **Delete it
when this is fixed.**

**Fix sketch.** Two halves, and the first is the important one:
- `revision.footnotes_out_of_order(parts)` → the ids whose definition order
  differs from reference order. Call it from `revision status` and from
  `build`'s pre-flight, and say so in one line — *"footnote definitions are not
  in document order; Compare will rewrite them. Run …"* — instead of leaving the
  caller to read 81 glyph runs.
- a public `revision.add_footnote(parts, after_ref=..., text=...)` that inserts
  in the right place to begin with. **Corrected:** `footnotes.append` exists,
  but it appends text to an EXISTING footnote's last paragraph -- there is still
  no way to create a footnote and its reference as a pair, which is what was
  hand-rolled here.

**BOTH DONE, 2026-08-20.**

`footnotes.out_of_order(document_xml, notes_xml, kind=...)` answers the ids
that would move — every one of them, so a caller can quote them — and ignores
the two questions it is not (a definition nothing references; a reference with
no definition). It is called from `revision.state`, so `revision status` prints
one line about a file that otherwise looks settled, and from `revision build`'s
preflight over BOTH sides, where it is still cheap.

`footnotes.add(parts, after=..., text=...)` creates the pair. It lives in
`footnotes` rather than `revision` because it is a document operation, not a
protocol one; the entry's name is recorded here so a search for it lands. The
definition is written in REFERENCE order rather than appended, so the file it
produces is one Word could have written and `out_of_order` answers `[]` by
construction. Two things it will not do: invent the footnote scaffold for a
package that has never held a note (it refuses and says so), and hand back a
reserved id — Word's separators are -1 and 0, and "one past the highest" over a
part holding only those answers 0, which renders as the separator line.

**`AFI/revision/scripts/renumber_footnotes.py` can go** once someone confirms
the paper's existing out-of-order notes are repaired; the detector will say.

**Confirmed 2026-08-21** on the finished manuscript:
`footnotes.out_of_order(doc, notes)` answers `[]`. The script has nothing
left to do on this paper.

---

### ~~S4 nothing can test a set of edits against a document before building it~~ — FIXED 20.08, `9b7a5b3`
<!-- status: fixed -->

Shipped as `batch.preflight`, not `edit.preflight` as sketched below: it
belongs with the unit of work, not with the verb it wraps. Cumulative by
default, and deliberately WITHOUT the `independent=True` the sketch wanted —
a batch is what the caller actually has, and judging edits independently is
precisely the check that misses the failure. AFI's `build_r4v.py` runs
unchanged through it (AFI `1c527cf`).

**Symptom as observed.** `replace_in_para` refuses a match that spans or starts
inside a hyperlink; `para_slice` refuses a signature matching 0 or 2+
paragraphs. Both refusals are *correct* and their messages are good. But they
arrive **one at a time**, at build time, and a batch is a list of edits — so a
batch with three anchor problems costs three edit-and-rerun cycles.

Measured on AFI r4, batches 12-19: at least one refusal per batch from 15 on,
about ten cycles in all, roughly twenty commands. The shapes:

- the match meets a hyperlink label — and in that paper a citation label
  INCLUDES its year, so "replace from the citation onward" starts *inside* the
  link (batch 15, twice in a row: first spanning, then starting-inside);
- an edit earlier IN THE SAME BATCH removes the sentence a later signature uses
  (batch 17);
- an edit in phase 1 adds "(A.6)" to prose, so phase 2's label-based anchor
  stops being unique (batch 13);
- the match spans an `m:oMath` (batch 18).

**Why it is not S2.** Nothing is wrong; the tool is simply absent, and the cost
is entirely the caller's round-trips. But it is the single largest time sink
this toolchain has, so it should outrank the usual S4.

**Workaround** — `AFI/revision/scripts/_batch.py`:

- `preflight(edits)` applies every edit **cumulatively, in order, in memory**
  and reports all verdicts at once. It works by attempting the real
  `edit_para`/`replace_in_para` and catching what they raise, so it uses the
  same guards the build will and cannot drift from them.
- `_diagnose` then says why in the terms that fix it: it names the hyperlink
  label the match met, or says the signature now matches 0 or 2 paragraphs
  because an earlier edit moved it.
- `build_clean(name, edits, allow=…)` gates the five invariants (oMath,
  bookmarks, paragraphs, footnote marks, links) in one pass, `allow` declaring
  the ones the batch is meant to move.

Result: AFI batch 20 shipped in **2 commands against 18-22**.
**Delete `_batch.py` when this lands.**

**Fix sketch.** `docxkit.edit.preflight(xml, edits) -> list[Verdict]`, where an
edit is `(signature, old, new)` and a Verdict carries ok / the exception class /
a human reason. Cumulative by default (that is what a batch does); `independent=True`
for callers who want each judged against the original. A `docxkit preflight`
CLI reading the same tuple list would cover the common case without any script.

---

### ~~S4 the missing thing is not a verb, it is the UNIT OF WORK~~ — SHIPPED 20.08, `9b7a5b3`
<!-- status: fixed -->

`docxkit.batch`: `Edit`, `Step`, `Verdict`, `Report`, `preflight`, `diagnose`,
`invariants`, `apply_steps`, `run`. It covers both paths, and it gates EIGHT
carriers rather than the five sketched below — bookmark ends, table rows and
drawings were missing, and this round needed all three (batch 24 swapped
figures, batch 25 moved rows). It also refuses a file with revisions still
pending, because Compare treats a pending revision as accepted.

`_batch.py` was NOT deleted, contrary to the note below, and should not be:
the Compare ladder and the `paper.toml` gates are genuinely this paper's.
Only its generic half moved — 430 -> 310 lines, AFI `1c527cf`. The local
paragraph regex it lost was unguarded against a nested `<w:p>`, which the
shared one is.

Still open: `sites.py` (its own entry above), and the second-order
discoverability finding, promoted to its own entry below.

**Measured across the four papers on this machine** (AFI, Parental_style, DSI,
Life_Expectancy), 2026-08-20:

    237  python files under revision/
    126  of them do read_parts -> edit -> write_docx themselves
     63  reach past the API into raw XML
     58  use replace_in_para / edit_para, each wrapped in its own loop and gate

docxkit has 40 modules and 24 CLI commands and is rich in VERBS. What no paper
can get from it is the SENTENCE those verbs make, which is identical everywhere:

    locate -> preflight the edits -> apply -> gate the invariants ->
    write -> (redline ladder | direct) -> run the paper's gates -> baseline

So every paper builds its own. AFI has `_batch.py`; DSI has `quickfix.py` and
`tc_lib.py`; LE has `buildkit.py`; Parental_style has `cleanup_pass{,2,3}` and
`sweep`. Each is a partial, divergent implementation of the same thing — the
exact failure the protocol-script consolidation already fixed once for
`revision`.

**The size of it.** AFI's r4 batches average ~230 lines each. The single batch
that used the harness (`build_r4v.py`) is **50** — a docstring, two edits, one
call. Across ~100 batches on this machine that is roughly ten thousand lines of
re-invented scaffolding, and every line of it is a place to get the gating
subtly wrong.

**What `batch` has to cover, from what the papers actually do:**

* **both paths.** `revision build`'s Compare ladder AND direct application.
  Compare cannot carry tracked math, a moved footnote reference, a citation
  relabel, a figure swap or a table-row move — so in AFI's r4 *every* batch
  after 20 was direct, and a harness offering only the Compare path was
  abandoned rather than half-used.
* **preflight all edits at once**, cumulatively and in order, by attempting the
  real replace and catching what it raises — so it cannot drift from the guards
  — reporting every failure in one pass. Filed separately above; it is the
  single largest time sink in this toolchain.
* **invariant gating with declared exceptions.** oMath, bookmarks, paragraphs,
  footnote marks, links, table rows: unchanged unless the batch says which one
  it means to move and by how much.
* **one-command verification.** status + the paper's own `[verify]` commands +
  the suite + audits + lint + baseline. Six round-trips otherwise. Lint only
  what changed — papers' `ruff.toml` files have no `exclude` and the trees carry
  pre-existing findings — and keep audits that exit non-zero on findings
  ADVISORY, or one standing false positive makes the check permanently red.

**Workaround** — `AFI/revision/scripts/_batch.py` (preflight, build_clean,
apply_direct, ship, check) and `sites.py`. Both are written to be lifted: they
already import only public docxkit surface.

---

### ~~S3 `write_docx` retries the sharing-violation race; `read_parts` does not~~
<!-- status: fixed -->

Fixed 2026-08-20 in `package.py`. `read_parts` rides out a `PermissionError`
on the same bounded schedule `_replace_atomically` uses for the write side —
six attempts, five waits, `0.2s * n` — and raises with the wording the write
side already gives when they run out:

    working.docx is locked (open in Word). Close it and retry. ([Errno 13] ...)

`PackageError`, not `DocumentLocked`: the two are siblings rather than
parent and child, and 126 scripts across the four papers call `read_parts`
inside an `except PackageError`. The wording is what the sketch asked to
match; the type would have been a change to every one of them.

A missing file is NOT retried, and that is tested — a path that does not
exist will not start existing, and six sleeps before saying so is a CLI that
appears to hang. `retries=`/`delay=` are keyword arguments so a suite can
drive the loop without waiting on it.

The write side's own retry loop had 45 of the module's 86 survivors and now
has three tests; the read side landed with tests from the start, including
the sleep COUNT — sleeping after the last attempt delays the error by more
than a second and changes nothing about it.

### ~~S2 `tables.by_caption` assumes the caption sits ABOVE, and silently returns the wrong table~~
<!-- status: fixed -->

Fixed 2026-08-20 in `_table_core.py`. On AFI's `working.docx` two of six
lookups came back with the 2x2 grid holding Figure 5's panels — a `Table`,
not a `None`, so `required=True` could not fire — because Tables 3 and A3
have their captions underneath and "the first table after the caption" is
whatever comes next.

The caption's position is still the preference; what makes it evidence is the
document's OTHER captions. `_beside` takes the nearest table on each side and
refuses either one that has another caption standing between it and this
one — that table is the other caption's, whatever the convention. What is
left is at most one candidate per side, and the one below wins, which is the
house convention applied where it can still be true. Both ruled out raises:

    caption 'Table 7.' has no table of its own: the nearest table on each
    side is behind another caption, so it belongs to that one

Two existing tests asserted the old rule (a caption trailing every table
returned `None`); they assert the new one now, and three more cover the AFI
shape, the convention where both sides are free, and the refusal. The two
range bounds that make the caption's own paragraph not count against it are
pinned by mutation rather than argued.

The NUMBER cross-check the sketch also proposed ("Table 5." should not name a
grid of "a. Tajikistan" panels) was not taken: the structural evidence is a
fact about the document and the content test is a guess about what a table
holds.

**Workaround to retire:** `AFI/revision/scripts/build_r5a.py` addresses
tables by index against expected row counts. Left in place — it is in the
paper's own tree, and deleting it is the paper owner's call.

### ~~S2 `revision build` blames footnotes for a gap that is Word's revision GROUPING~~
<!-- status: fixed -->

Fixed 2026-08-20 in `tracked.py`. `revisions_by_part` counts revision
elements per text-bearing part (public — a paper asking "where are they?"
had no way to), and `_revision_gap` writes the two causes as separate
lines, each printed only when it is actually there:

    revisions: 33
      (Word counts 15 in the body; the package holds 33 revision elements)
      (the remaining 18 are in word/document.xml too: Word GROUPS adjacent
       revisions, so one thing to accept can be several elements)

A note store holding nothing is not named at all, which is the specific
sentence that sent a reader to inspect a clean `footnotes.xml`.

The test that pinned the old wording asserted `"0 of them"`; it now asserts
both numbers appear, and three new ones cover the shapes it could not reach —
both causes at once, footnotes alone, and a `footnotes.xml` present but
unrevised. The last of those is what the old message got wrong.

### ~~S1 `citations.link_all` layers its OWN anchor scheme over a paper that already has one~~
<!-- status: fixed -->

Fixed 2026-08-20 in `_cite_build.py`, both halves of the sketch below.

**Adopt the scheme.** `_own_bookmark` now falls through to
`_foreign_bookmark`, which reads a name through its PUNCTUATION: fold it to
letters and digits, accept it when the fold ENDS with this work's year and
contains the surname. Both halves are load-bearing and both are pinned by a
test — a marker naming a different work must not be adopted, and
`ref_kanbur_2007_notes` is an anchor ABOUT the work, not the work's.
`link_all` on a `ref_/cite_`-schemed paper now reports `linked: []
backlinked: [] skipped: []` and mints nothing.

**Refuse to nest.** The mention scan reads the LABELS of the links a
paragraph already has, and a citation sitting inside one is reported instead
of wrapped:

    'Acemoglu 2022' (¶7) is already inside a link — wrapping it would nest
    one link in another, and the click goes to the outer one

Placed AFTER the already-linked bookkeeping, not before it: a mention linked
to its OWN anchor is `already`, and putting the refusal first turned the
second run of an idempotent build into a skip.

Not in `wrap_link_in_bookmark` as the sketch guessed. By the time the writer
is called the decision is made and the paragraph has been rewritten; the scan
is where a citation is chosen, and refusing there is what keeps the report
truthful about it.

`link_all` came out of this UNDER the complexity threshold it had been pinned
at (29): the scan is a method on a frozen `_Mentions` carrier now, so the
debt entry and the file's `C901` exemption are both gone.

### ~~S2 `unlink` left half of a DUPLICATED bookmark and reported success~~
<!-- status: fixed -->

Found 2026-08-20 by auditing the arguments in a survivor note rather than by
a mutant — the second wrong one in that list, and wrong the same way.

`unlink` removed the first `w:bookmarkStart` of each name and one
`w:bookmarkEnd` of its id. The note beside the surviving mutants argued that
was safe because "bookmark ids are unique document-wide, which is what
`_next_bookmark_id` is for". Uniqueness is what a WELL-FORMED document has.
Word's Compare **duplicates a table when a block containing it is moved** —
S1 above, in this same file — and the copy carries the same `w:name` and the
same `w:id`. A paper that has been through one round of move-tracking holds
the pair.

So on such a paper `unlink` left a bookmarkStart and its End standing and
answered `1 removed`, which is precisely what its own docstring refuses two
paragraphs earlier: *"not a partial success, it is a wrong answer that
reports a healthy count"*.

Every copy of the name is taken now, and one END per START removed — never
more, because an id shared with a bookmark this pass does not own is a defect
of its own, and cutting its close would make it two.

**The general lesson**, and it is the second time today: an argument of the
form "X is unique / valid / allowed only once" is about the document the
schema describes, not about the string the function is handed. Ask what it
excludes — a tracked-change snapshot, an empty element, a copy Word made.

### ~~S1 the Hyperlink style was written into the tracked-change SNAPSHOT~~
<!-- status: fixed -->

Found 2026-08-20 by the mutation pass over `crossrefs`, while checking what
an argued equivalence had excluded. `_with_hyperlink_style` searched the whole
`w:rPr` string for a `w:rStyle` and replaced the first one it found. A
`w:rPrChange` — the formatting a tracked change replaced — is a `w:rPr` INSIDE
the `w:rPr`, so for a run whose only character style sits in that snapshot:

* the Hyperlink style landed in the historical record, which now says the
  author once styled that text as a hyperlink;
* the live properties got nothing, so the link Word draws is plain text with
  no visible difference from the prose around it;
* and `link` reported it linked, because it was — the anchor is real.

Two more in the same six lines, both found the same way:

* `<w:rPr/>` came back UNCHANGED. The prepend branch was a
  `str.replace("<w:rPr>", ...)`, which does not match the self-closing form —
  the fourth instance of that shape in this package after `set_run_text`,
  `package.set_core_property`, and `lint`'s check 7c for `<w:tcPr/>`.
* a run arriving with TWO `w:rStyle` children kept the second. The docstring
  said "never leaves TWO rStyle children"; it meant "never adds one".

The old survivor note argued the `count=1` there was equivalent because
"`w:rPr` admits a single `w:rStyle`, an rPr string has one opening tag". Both
halves are true of a valid `w:rPr` and false of a valid RUN. **An equivalence
argued from what the schema allows is an argument about the element, not
about the string the function is handed** — and the note now says so.

### ~~S1 a property present TWICE was only half removed — `22a09e6`~~
<!-- status: fixed -->

Found 2026-08-20 by the mutation pass over `_xml`, and it is the defect the
docstrings around it already named as fixed. `set_para_property` took the
first copy of the property out of `w:pPr` and stopped (`break`);
`set_run_property` replaced the first child with the wanted element and
returned.

Two of the same property in one properties element is invalid and ordinary:
a style turns `keepNext` OFF with a second `w:val="0"` element beside the one
that turns it on, and a run salvaged out of two carries `w:sz` twice. So

    set_para_property(para, "keepNext", "<w:keepNext/>")

on `<w:pPr><w:keepNext/><w:keepNext w:val="0"/></w:pPr>` answered with the
stale copy sorting FIRST, and

    set_para_property(para, "keepNext", "")

answered with the flag still there — a REMOVE that does not remove, on the
property `_table_layout._keep_with_table` writes to keep a table head with its
body and the size `footnotes` writes to repair a note.

`_keep_with_table`'s own docstring lists "a `w:keepNext w:val="0"` given a
second element beside it" as one of the four defects consolidating the writers
was meant to end. It was ended for the case where the writer PUT the second
one there, and not for the case where it found two.

**Pinned the other way on 2026-08-19** — "the document unchanged; repairing a
duplicate is `lint`'s finding, not this writer's" — off a fixture of identical
twins, which is the one shape where the harm does not show. The test now says
what changed the reading: taking every copy out is the same repair this writer
already makes when it moves a misplaced property into its slot, and the
offsets objection in the old note is answered by re-reading the properties
after each cut.

### ~~S2 the citation apparatus does not read ENDNOTES~~ — FIXED 20.08, `0db8361`, `c116411`
<!-- status: fixed -->

Found the same way, 2026-08-19, and demonstrated: the identical bookmark and
hyperlink, placed in a footnote and then in an endnote, audit as
`bookmarks 1, links 1` and `bookmarks 0, links 0`. `_audit_findings` reads
`word/document.xml` and `word/footnotes.xml` — the footnote case even has its
own sentinel (`where = -2`, "defined in a footnote") — and never opens
`word/endnotes.xml`.

So for a manuscript that files its apparatus at the back, `audit_links` reports
a clean 66/66 over the part of the paper it happened to look at. The retracted
S2 above is the same lesson from the other side: **a back-link that is not
where you looked is not a back-link that is missing** — and a bookmark nobody
counted is not a bookmark that is absent.

Not fixed here because the audit and the BUILDER have to move together:
`link_all` writes the apparatus, and an audit that reports unlinked entries in
endnotes while the builder cannot reach them replaces silence with noise.
`refstyle` (read-only, no writer) and `export` were fixed in the same pass;
`wordcount`, `probe` and `compare` were checked and already read all three
parts.

**Fixed 2026-08-20, writer and audit in one pass**, because they had to move
together for the reason above. `_cite_build._NOTE_PARTS` names both stores
once, with the label a report gives each (`fn¶`, `en¶`); `link_all` and
`link_rest` plan, wire and write both; `audit_links` reads both, with its own
sentinel per store (`-2` footnotes, `-3` endnotes) so a finding says WHICH
part it is in — an anchor reported as "fn" that lives in endnotes.xml sends a
repair looking in a file that does not hold it.

`repair_plan` came with them, and it was the dangerous half: it decides
DEBRIS from three tests — the key is not among the document's citations, no
`<name>txt` partner exists, the entry is not live — and built all three from
the body and footnotes. For a paper whose journal takes endnotes the first was
true by construction, so every marker for a work cited only there was proposed
for deletion. A one-liner a person will run.

`BLIND` in `tests/test_note_parts.py` is empty as a result, and the tests that
kept it honest still stand: a reader may not join it without one of them
failing.

### S1 an ENDNOTE id was spliced into an override unremapped — `a6377af`
<!-- status: fixed -->

Found 2026-08-20 while widening the citation apparatus, and it is the defect
the FOOTNOTE remap was written to prevent, unfixed for the other store. Word
renumbers note ids on save, so an author's paragraph carries ids that mean
something else in the build; `build_overrides` matched footnote definitions by
TEXT and rewrote their ids, and did nothing at all for endnotes.

An override carrying `w:endnoteReference w:id="4"` therefore went into the
build with the author's number, pointing at whichever note the build had given
that id. The deliverable cites the wrong work, the author's copy cites the
right one, and no gate compares the two: `--expect-clean` sees a reference
mark, not what it resolves to.

Fixed with both stores keyed in one map (`_NOTE_REF_RE`, `_NOTE_DEF_RE`), and
the note DEFINITION pattern moved into `_xml` — `revision.moved_footnotes` had
the same regex, which `test_no_element_pattern_is_compiled_in_two_modules`
caught the moment this one was compiled rather than inlined.

### S2 `fit_columns` wrote a column's width into a NESTED table's cell
<!-- status: fixed -->

Found 2026-08-19, mining `_table_layout`'s survivors, and it is the defect
`_own_grid`/`_own_tblpr` exist for — one element further in. The cell loop
replaced the first `w:tcW` in the whole `w:tc`, and a cell can CONTAIN a
table: with no width of its own to replace, the outer column's width landed
on the INNER table's first cell.

Measured on a two-column outer table whose second cell holds a one-column
nested table: the inner cell's `w:w="300"` came back as `1178`, inside a 300
dxa grid. With no `w:tcPr` of its own the outer cell was worse — the
properties element was inserted inside the nested table's first cell, where
it is not even in schema order.

Neither shows up as a failure. The document opens, the outer table lays out
correctly, and the nested one is measured against a table it is not part of.
Questionnaire appendices nest tables freely and these papers are full of
them.

Fixed by `_own_tcpr` / `_set_tc_w`, the cell-level twins of `_own_tblpr` /
`_set_tbl_pr`, with the width written in its schema slot (after `w:cnfStyle`,
before everything else). Two tests in `test_tables_nested.py`.

### S1 a mutation session restored the module from the LIVE tree between chunks — `tools/mutation_session.py`
<!-- status: fixed -->

**The instrument, not the package — and it produced a plausible wrong number.**
`tracked.py` stands at 4.9 % (29/589), verified and kill_check'd. Re-measured
the same evening it came back **28.9 % (237/821)**, with every survivor cluster
a multiple of eleven: 66x `_seed_scaffold`, 33x `<module>`, 33x `format`, 33x
`_comment_revision`, 22x, 22x, 11x.

Nothing failed. `chunk()` restores the module before each chunk — cosmic-ray
leaves its mutation behind when a run is terminated — and it copied the file
from the WORKING TREE. Editing `tracked.py` while the sweep ran therefore
swapped the source half way through: the plan in the session describes one
file, the chunks after the edit mutate another, and the harness in the
worktree is still the copy taken at startup. `D:/docxkit-mut2/src/docxkit/
tracked.py` was stamped 19:28 and its `tests/test_tracked_build.py` 18:46,
which is the whole story.

Fixed: the session snapshots the module and its harness when it is planned
(`.mutation-<stem>.pristine/`), every chunk restores from THAT, a resume
refuses outright when the module has changed since — the plan's offsets no
longer describe it — and a tree that moves under a running sweep is now a note
printed per chunk rather than a silent regrade. Eight tests, and the old
restore dies against them.

**The figure it produced is void and is not recorded anywhere.** The rule in
CONTRIBUTING — a figure is void when the source or the harness has moved — now
covers *during* as well as *since*.

### S2 `placement` reported a table it could not fix as fixed, and hid the findings a render cannot make — `0269f70`, `37023a7`
<!-- status: fixed -->

Two in the same report, both found by mutation testing the module the day
after it landed, neither visible to any test it had.

**A table that STILL splits was reported as one that was fixed.** The problem
line read:

```python
if pl.split and not pl.own_page:
    report.problems.append(f"table {N}: still splits ...")
```

`own_page` is applied to every table that split, so a table that still splits
after it always has the flag — and the branch could not fire for the case it
names. What a paper read was «1 table(s): … 1 given their own page» with no
problem under it: the last thing this module can do about an oversized table,
presented as having worked. The condition is `if pl.split` now, and the word
"still" is what the flag decides.

**And `format()` printed the problems only under a render.** Half of them
cannot come from one — a table nothing mentions, a block that carries a section
break, a move that would cross a boundary are all decided in the XML — so a
caller without a renderer was told the fit was unverified and nothing else,
while the report held findings it did not show.

**Found by:** mutation testing, 2026-08-19. placement.py measured 20.2 % real
survival — the worst in the package, which is what a module a day old looks
like — against 6-11 % everywhere else. 90 % lines, and the first figure after
the round was 97 %, floored there.

**A third thing, not a defect but worth the line:** the module and its tests
were committed without the gates. mypy read 34 errors and pyright three; the
CI run for those two commits never happened, because they were not pushed. The
type errors were mechanical (bare `list`/`re.Pattern`, `_Element | None` walks
in the tests) and are fixed in `0269f70`. The lesson is the one this file keeps
recording: a gate that is not run is not a gate.

### S1 `placement.place` moves a block OUT of its own section, silently — `831ef24`
<!-- status: fixed -->

DSI's таблица 4 is wide and owns a landscape section: «Информативность…» ends
the portrait section, and the `*` note after the table ends a landscape one, so
the section spanned bookmark + caption + table + «Примечание…» + `*` note.
`place()` moved the caption, table and «Примечание…» five paragraphs up to sit
nearer the first mention. The `sectPr` stayed behind on the note, so:

* the landscape section came to contain ONE stranded paragraph — a blank
  landscape page 26 in a 62-page paper;
* the table landed in the PORTRAIT section and was typeset in an orientation
  it was never laid out for.

**Everything reported success.** `place()` returned `moved=True`;
`citations.audit_links` gave 152 links / 0 broken; and the structure-count gate
— which counts `sectPr` explicitly — saw **3 before and 3 after**, because the
break was not deleted, only orphaned. Counting section breaks cannot see a
section break that stopped containing anything. DSI's wrapper even passed a
`render` hook, and that did not catch it either: the render check asks whether
the TABLE straddles a page, not whether the move stranded a section.

**Fix.** A block whose span contains, or is bounded by, a `pPr/sectPr` is not a
candidate for `move` — refuse it and say so in `PlacementReport.problems`,
because a table that owns a section has already been placed deliberately. If
moving it is ever wanted, the section has to travel with it, which is a
different and larger operation. The cheap correct version is the refusal.

**Found by:** DSI, 2026-08-19, from the author reporting «page 26 — lost
footnote * and incorrect page orientation». Repaired in the paper by
`revision/scripts/fix_table4_section.py`, which restores the block into the
section; the placement pass must not be re-run on that table until this lands.

### S2 `placement.NOTE` knows four words, and a table's note is not always one — `831ef24`
<!-- status: fixed -->

`NOTE = ^\s*(?:Примечание|Источник|Note|Source)\b` decides where a table's block
ENDS. DSI's таблица 4 carries a second note under the first — `* Высокая доля
самостоятельной занятости…`, the explanation of the `*` on one of its rows — and
it matches none of the four, so the block ended at «Примечание…» and the `*`
note was left behind when the table moved. A footnote-style marker under a table
is ordinary typesetting; `*`, `†`, `‡` and `a)` are all this same shape.

Related to the S1 above but INDEPENDENT of it: in a document with no sections at
all, this alone still separates a table from half of its notes, and nothing
reports it — the note is still a paragraph, so no count moves.

**Fix.** Extend the vocabulary to a leading footnote marker, and let the caller
override it the way `caption` and `mention` already can. Note the ordering trap:
the block must keep absorbing note paragraphs until one is neither a keyword
note nor a marker note, so a `*` note AFTER a «Примечание…» is included.

**Found by:** the same таблица 4, same day. Checked the rest of the paper before
filing — DSI has exactly one `*` note, and the other eleven tables end their
blocks at «Примечание…» correctly, so this cost one table, not twelve.

**Fixed 2026-08-19** (`831ef24`), with three more found while building it. Two
were pre-existing: `keep_together` cleared `keepNext` on the block's last
paragraph by walking back from the end, which for a table with NO note is the
CAPTION — so the caption was unbound from its own table; and `_flag` inserted
every property at index 0, right for `pStyle` and wrong for everything else, so
`keepNext` landed ahead of a `pStyle` already present. The third was in the new
code and is the same shape as the bug being fixed: the element after a block is
usually the NEXT table's hoisted `bookmarkStart` rather than its caption, so
the rule that zeroes the resuming paragraph's spacing silently did nothing.
`_next_content` looks past bookmarks. Eleven tests, 3825 passing.

### S4 `revision validate` had no `--render`, so the eye gate stayed per-paper — `render_accepted`
<!-- status: fixed -->

`docxkit revision validate ... --render "anchor" ["anchor" ...]` now does what
DSI's ladder did: accept-all, export through Word, and rasterise the page each
anchor falls on. Split in two, along the line the module boundary already
draws — `pages.render_anchors(pdf, anchors)` is the PyMuPDF half and
`revision.render_accepted(batch, anchors)` the Word half, so the page-finding
is testable against a PDF built in the test and needs no Word at all.

Both notes from the extraction are kept, and both are now comments in the code
that say why: the ACCEPTED view is rendered, never the redline — a redline's
pagination is not the deliverable's — and pages are walked by INDEX, because
PyMuPDF's `Document` is iterable at run time and its stubs do not say so.

Three decisions the item did not specify, each with a test:

* an anchor no page carries maps to None rather than raising. The caller asked
  to LOOK at several things and half a render is worth more than none;
* a BLANK anchor is dropped rather than matched. It is a shell artifact, and
  it would match the first page and render it for nothing — with nothing to
  render, Word is not started at all;
* the accepted copy and the PDF are scratch and go away; the PNGs are the
  answer. A gate that leaves two files per run beside a paper's batch is one
  somebody turns off.

**The workaround this replaces** is DSI's `revision/scripts/render_pages.py`,
78 lines that would have drifted on their own. It can be deleted — not done
here, since this repository does not edit the papers.

### S3 `losses` called a RE-LABELLED link a lost one, and blocked `baseline` — `relabelled_links`
<!-- status: fixed -->

Split on the one fact that decides it, as the item asked: a link is LOST when
its anchor is no longer linked from anywhere in the hand-back, and RE-LABELLED
when it is. `losses` returns the first, `relabelled_links` the second,
`IngestReport` carries both, and `revision ingest` prints them under separate
headings — "== RE-LABELLED (n) ==" says the anchors are intact and that
`baseline` does not refuse.

**Paired off one for one**, which the item did not call for and the code
needs: an anchor linked TWICE that comes back once has lost a link however the
survivor is now labelled. Each gone label consumes one gained label for the
same anchor, and what is left over is a loss — otherwise a re-label would
absorb the loss and the paragraph Word ate would go unreported. There is a test
for exactly that pair.

The reject-side check in `validate` is deliberately NOT changed: there,
rejecting the batch must restore the baseline exactly, labels included, and a
deliberate re-label lives in the working copy rather than in a rejected batch.

**The workaround this replaces** is `--accept-loss` naming four links whose
anchors had been verified by hand. DSI can stop passing it.

### S2 `build` gated reject-all's TEXT but only accept-all's STRUCTURE — `unaccepted`
<!-- status: fixed -->

`tracked.unaccepted(parts, revised, *, limit=8, fold_space=False)` mirrors
`untracked`, and `build` refuses on it behind `accept_check: bool = True`. The
two now ask the same question of both views: rejecting must reproduce the
ORIGINAL, accepting must reproduce the CLEAN COPY.

**The argument, made as a test rather than in prose.**
`test_the_reject_gate_cannot_see_a_defect_inside_an_INSERTION` builds one
package and hands it to both functions: `untracked` says it is clean, because
rejecting deletes the insertion the damage is inside, and `unaccepted` names
the paragraph. That is the whole S2 in nine lines.

**One thing the item did not anticipate.** A build made with
`whitespace=False` — the Life Expectancy recipe — legitimately accepts to the
ORIGINAL's spacing, because Word was told respacing is not a revision. Compared
exactly, the new gate would refuse every build that recipe makes. `unaccepted`
takes `fold_space`, `build` passes `not whitespace`, and the words still have
to match: two tests, one either side of that.

The walk itself is shared now (`_mismatched_paras`), so the two gates cannot
drift apart in how they diff or in what they cut. `revision.build` leaves
`accept_check` ON while it still passes `reject_check=False`, and the asymmetry
is written down beside the call: the reject side has a legitimate cause the
protocol can see and gate 5 can judge — a moved footnote reference — and the
accept side has none.

**The workaround this replaces** is DSI's hand-rolled script that hashes the
accepted paragraph text and table cells against the clean build. It exists in
one of the eight papers that use `revision/working.docx`; the other seven made
this comparison nowhere. It can be deleted from DSI now — not done here, since
this repository does not edit the papers.

### S1 a GHOST hyperlink made the repair helpers wrap the wrong span
<!-- status: fixed -->

`<w:hyperlink w:anchor="X"/>` is an empty ghost Word leaves behind when
it strips a link's contents, and `_xml._HYPERLINK_EL_RE` carries a
`(?<!/)>` guard because pairing one with the next `</w:hyperlink>`
downstream spanned 14 paragraphs on Parental Style. Both helpers in
`_cite_repair` were written without that guard.

`wrap_link_in_bookmark(doc, "Smith2020", "Smith2020txt", bid)` on a
paragraph holding a ghost for Smith2020 opened the bookmark at the ghost
and closed it at the next link's close tag — around the prose between
them and around another work's citation. No exception, nothing in any
report: the bookmark exists, so `audit_links` calls it healthy, and the
back-link to it lands on the wrong sentence.

`remove_outer_field` had the same span on its inner link, and kept the
ghost alongside the real one.

Both are REPAIR helpers, so the shape they are handed is by definition a
damaged document — which is where a ghost lives.

**Closed 2026-08-19** (`e30d359`). The guard is on both patterns
now. A ghost is not a link to wrap, so `wrap_link_in_bookmark` refuses
with "no link to X", which is the honest answer: what the caller wanted
to wrap is not there.

### S1 a write into an EMPTY run landed nowhere and reported success
<!-- status: fixed -->

`set_run_text` matched only the paired `<w:t>…</w:t>`, and a run whose
text has been deleted arrives as `<w:t/>`. The write found no `w:t` to
rewrite, returned the fragment unchanged, and every caller reported
success. `tables.set_cell` into a blank cell is the shape a paper script
meets: a table typed with its value column left empty is the ordinary
starting point for a generated table, and the call came back with the
document exactly as it was.

Found by reading, not by the sweep, the day the SAME blindness turned up
in `package.set_core_property` (`<dc:title/>`) — and `lint`'s check 7c
already names it for `<w:tcPr/>`. Three instances of one shape: an EMPTY
element is self-closing, and a pattern written for the paired form calls
it absent.

**Closed 2026-08-19** (`e91f09d`). `set_run_text` expands the
self-closing form before it writes, so the run keeps its properties and
its attributes — `<w:t xml:space="preserve"/>` is what Word leaves when
it empties a run that had edge whitespace, and that attribute is the one
thing on the tag that must survive being filled.

### S2 setting a core property Word left EMPTY wrote it twice
<!-- status: fixed -->

`docProps/core.xml` carries an unset property as `<dc:title/>`, and the
reader matched only the paired `<dc:title>…</dc:title>` form. So
`set_core_property` took its "absent" branch on a document that HAS the
element: the new value was inserted beside the empty one and the package
came back with two `dc:title`s. CT_CoreProperties allows one of each,
and Word repairs the file on open without saying what it changed.

Nothing downstream could see it. The value reads back correctly — the
reader finds the new element first — so `docxkit authors set`, the
`revision` stamp and every round that sets a title reported success.

Found by mutation testing the INSERT POSITION (`CORE_ORDER.index(tag) +
1`): the mutant that included the tag's own slot survived, which is only
possible if a document can hold the tag and still reach that branch.

**Closed 2026-08-19** (`ff63c99`). `_core_re` matches both forms and
group 1 is None for the empty one, so an empty property now reads as `""`
rather than as absent — which is the distinction `core_property`'s
docstring already drew and could not honour.

### S4 `repair_plan` promised three issues and printed two
<!-- status: fixed -->

The header counts findings (`REPAIR PLAN — N audit issue(s)`) and the buckets
are what a person actually works through, so the two have to agree. They did
not for one shape: a reference-section bookmark whose name does not parse as
author+year — `Anhang`, an appendix marker — draws BOTH an `ORPHAN REF` and a
`REF WITHOUT CITE`, and the second fits none of the three readings inside that
branch (no key to check against the citations, no entry owning it). It fell out
of the loop unfiled. The plan said 3 and listed 2, and which one had been
swallowed was left to the reader.

Found by mutation testing rather than by a manuscript: 27 of citations.py's 29
real survivors sat on the `f.kind == "..."` tests, which is what a branch
nothing ever reaches looks like from outside. Writing a fixture per damage class
surfaced the hole.

**Closed 2026-08-19** (`659af9b`). The unclassified finding goes to
`investigate`, where "no mechanical reading" is the honest answer. Pinned as an
INVARIANT — printed lines == the header count — over four fixtures, so any later
branch that forgets its `else` fails on the arithmetic whatever its damage class
turns out to be.

### S1 Word Compare duplicates a table when a block containing it is MOVED
<!-- status: fixed -->

Move body children so a `w:tbl` and its caption change position, then
`tracked.build` (clean edit + Word `CompareDocuments`). Word emits
`w:moveFrom`/`w:moveTo` rather than `w:ins`/`w:del`, and the result carries
**one table too many**. Measured on DSI: baseline 27 tables, clean permutation
27, redline **28**, and *both* `revisions.accept` and `revisions.reject` leave
28 — the moved table appears twice in the accepted view. `build` reported
success and `reject-all == baseline` passed.

Move tracking is modelled correctly for the paragraph-only case: two plain
paragraphs moved gave 8 move revisions, 27 tables held, reject-all equal to the
baseline, XML accept equal to Word accept.

**Suggested:** detect `w:moveFrom`/`w:moveTo` spanning a `w:tbl` and refuse, the
way `build` already refuses resolved math revisions.

**Closed 2026-08-19** (`4480971`), as a REFUSAL — both shapes reproduced first.
A move whose rows Word flags (`<w:trPr><w:moveTo/></w:trPr>`) was already
handled: `revisions._row_flag` reads it and 2 tables resolve to 1 in both views.
The shape that bit DSI is the other one — an unmarked copy, which is not a
revision at all, so there is nothing to accept or reject and no way to tell
which of the two is spurious.

`build` now compares `structure_counts` on both sides (rejected against the
original, accepted against the revised copy) and refuses, naming what moved:
`rejected: tbl: 27 -> 28`. `reject_check=False` still builds for inspection.
Caught at build time now rather than by counting tables by hand afterwards —
but a moved block containing a table still cannot be delivered, and that part
is Word's.

### S1 a moved paragraph carrying BOOKMARKS loses them on reject
<!-- status: fixed -->

Same mechanism, different casualty. A paragraph holding three citation anchors,
moved through Compare: accept is correct, but **reject returns 125 bookmarks
against the baseline's 127**. The anchors the bidirectional citation links
depend on are dropped, and `reject-all == baseline` passes because a bookmark
carries no glyph — so `paper.toml`'s `require_reject_all_equals_baseline` is
satisfied by a document that does not reproduce the baseline.

**Workaround in use:** refuse to move a paragraph whose bookmarkStart/End ids
are not balanced within itself, and do not move bookmarked paragraphs at all —
which cost that manuscript two of its planned exposition moves.

**Closed 2026-08-19** (`e3931b7`), for the loss; the misplacement stands.
Reproduced from the XML Word writes: the anchor sits INSIDE the `w:moveTo`, and
removing that element on reject took it along. Position markers —
`bookmarkStart`/`End`, `commentRangeStart`/`End`, `commentReference` — are now
LIFTED out of a revision element before it is removed, in document order so a
start still precedes its end. That also covers the same shape one revision kind
over: a comment range start inside a rejected insertion, which leaves an end
with no start, which Word calls damage.

What it does NOT do is put the anchor back AROUND the restored words: on a move
those words come back somewhere else, and pairing the two halves needs the range
names in output that cannot be verified against Word from here. So the anchor
stays where the revision stood, the link resolves, and gate 5 decides — it sees
both the count and the empty paragraph the move leaves behind. Losing an anchor
silently was the defect; refusing loudly is the honest answer while the rest is
unknown.

**Still true for the paper:** a bookmarked paragraph cannot be moved through
Compare and rejected back cleanly. Move it in the clean copy in its own round.

### S3 `reject-all == baseline` is blind to everything that carries no glyph
<!-- status: fixed -->

`tracked.build`'s reject check — the one that proves a batch is fully
reviewable — compares paragraph text, the glyph stream and footnotes. It does
not compare `w:tbl`, `w:tr`, `w:bookmarkStart`, `w:sectPr` or `w:hyperlink`
counts. Three separate defects below were found only by counting those by hand,
AFTER the gate had already said OK. A gate that cannot fail buys false
confidence, which is why S3 outranks S2 here.

**Suggested:** fold a structure-count comparison into whatever
`reject-all == baseline` compares, and name the first count that differs. The
per-paper workaround is a `counts()` helper copied into five batch scripts.

**Fixed 2026-08-19** (`e727117`). `tracked.structure_counts` is the fifth
thing gate 5 compares — a dict of counts over every text-bearing part, pure and
testable without Word, sitting beside `package_counts` for the same reasons. The
failure NAMES the count that moved (`STRUCTURE tbl: 0 -> 1`) rather than adding
a fifth boolean, and the `counts()` helper copied into five batch scripts is
replaced by one public function.

`w:hyperlink` is deliberately NOT counted, and has a test saying so: the
field-to-element rewrite recorded below as "not a defect" would fail a gate that
counted it, while `_links` already compares links by (anchor, label) across both
forms.

Tags counted: `tbl`, `tr`, `tc`, `bookmarkStart`, `sectPr`, `drawing`,
`footnoteReference`. The two S1s below are what it catches; both are still open
as DEFECTS, but neither can now reach a paper through a green gate.

### S4 a fifth writer of CT_PPr order, when the package already had four
<!-- status: fixed -->

Raised by the same review, and not fixed: `_keep_with_table` now carries
its own `w:pStyle` regex and its own "only pStyle precedes keepNext"
rule. The package already knows this in four places —
`_xml.set_run_property` (RPR_ORDER and its rank table),
`_table_layout._set_tbl_pr` (the `_AFTER_*` tuples),
`hygiene._set_before` (CT_PPr placement for `w:spacing`, with a third
pStyle regex), and now this.

The duplication is what made three of the four defects above possible:
`_set_tbl_pr` handles a non-self-closing property and an
existing-but-off one; the ad-hoc match handled neither, and each was
found separately.

What it wants is a `PPR_ORDER` in `_xml.py` mirroring `RPR_ORDER`, with
one `set_para_property(para_xml, tag, element)` that every CT_PPr writer
goes through — the same shape `set_run_property` already has, including
its `live_properties` discipline. Three call sites move; the fourth
(`_set_tbl_pr`) stays, since CT_TblPr is a different sequence, but it
should be rewritten as a rank table too rather than one `_AFTER_*` tuple
per property.

Not a defect today, and the reason it is filed rather than done: every
one of those writers is under test now, and the consolidation is a
refactor that wants its own round with the mutation runs re-measured
after it.

**Closed 2026-08-18** (`ee7a7c7`), and it was not only a refactor:
`find.page_break_before` still carried ALL THREE of the defects fixed in
`_keep_with_table` hours earlier — the flag read out of a `w:pPrChange`
snapshot so the break was never set, the `w:val="0"` given a second
element beside it, and `<w:pPr/>` written past, which left two `w:pPr`
in one paragraph. That is the cost of a fifth copy stated as a
measurement: the same three bugs, in a public path a paper uses to open
a table on a fresh page, found only because the copies were being
collapsed.

`_xml.set_para_property` now holds CT_PPr's order, both spellings of an
empty element, ST_OnOff, `<w:pPr/>` and `<w:p/>` expansion, live
properties only, and a top-level child scan that does not descend into
`w:pBdr` or `w:tabs`. It repairs a misplaced property rather than
overwriting it where it stands, as `_set_tbl_pr` has since that morning.
Four call sites moved; five one-off helpers went with them.

CT_TblPr is still its own thing (`_set_tbl_pr` with the `_AFTER_*`
tuples) — a different sequence, and rewriting it as a rank table is a
separate round.

### S1 four more shapes in the two S1 fixes of the same day, each reported as success — `04472c1`, `f5336ea`
<!-- status: fixed -->

Found by `/code-review` over the day's 58 commits (2026-08-18), every
one reproduced before it was believed. All four are the case the fix's
OWN test did not build, which is the pattern worth keeping:

**`_drop_reference_run` still deleted the author's sentence.** The
morning's fix told a NEIGHBOUR run from an enclosing one; this is an
enclosing run that also carries prose —
`<w:r><w:t>Prose.</w:t><w:commentReference/></w:r>` — and `remove`
dropped the whole run and returned 1. Word writes the mark alone in its
own run; another producer need not. The run goes only when the mark is
all it holds.

**`_keep_with_table` read the HISTORY.** `if "<w:keepNext/>" in para`
searched the whole paragraph, `w:pPrChange` included — the formatting a
tracked change replaced. A caption whose history carried keepNext was
reported as done while the live properties never got it.
`live_properties` exists for exactly this and the function did not call
it.

**The slot regex knew one spelling.** `<w:pStyle .../>` matched,
`<w:pStyle ...></w:pStyle>` did not, and keepNext went in ahead of the
style — the out-of-order property the whole change exists to prevent.

**`<w:keepNext w:val="0"/>` got a second one beside it.** ST_OnOff
again, three hours after `w15:done` was widened for the same reason:
a keepNext that says NO is still a keepNext, CT_PPr allows one, and Word
chooses between two on open — possibly the one that says no.

**Fixed** in `04472c1` (the run) and `f5336ea` (the three caption
shapes), with a test for each shape.

### S2 `_own_grid` handed every caller a NESTED table's grid — `04472c1`
<!-- status: fixed -->

Found in the same review. The docstring said "everything before the
first `w:tblGrid` belongs to the outer table and the first match is
always its own", which holds only while the table HAS one. An outer
table with no grid whose nested table has one sent every caller inside:

    house(xml, outer)   ->  the inner table's tblW becomes 5000pct,
                            the outer table gets nothing, report.width True

`fit_columns` would rewrite the inner table's grid the same way. A grid
that starts after the first row cannot be this table's, because CT_Tbl
puts the grid before the rows — that is the fix. The nested fixture
written that morning had no grid on the inner table, which is why it
passed.

### S2 the fix for the misordered properties could not repair what the last release wrote — `eefa243`
<!-- status: fixed -->

Also from the review, and the one that decides whether the CT_TblPr fix
was worth anything. Every table `house` touched before it carries
`w:tblW` and `w:tblLayout` ahead of `w:tblStyle`; re-running the
corrected pass is the remediation, and `_set_tbl_pr` replaced a property
where it stood rather than moving it — so the table came back
byte-identical and reported as already correct.

The element is now taken OUT and put back in its slot. That alone was
not enough: `_set_tbl_pr` anchors on the first element that must FOLLOW
the one being written, and on a misordered table `w:tblLayout` is itself
misplaced, so `w:tblW` anchored on a wrong position and stayed first.
Writing the LAST property first fixes the anchor before it is used —
tblLayout against `w:tblLook`, then tblW against the now-correct
tblLayout. The repair settles: a second run changes nothing.

### S3 `!cancelled()` ran four gates that could not run, and the floors ran the suite twice — `pushed 2026-08-18`
<!-- status: fixed -->

The condition added that morning so a red gate stops hiding the ones
behind it said too much. It did not cover ruff (whose default is
`success()`), and it did not exclude an INSTALL failure: a missing wheel
therefore skipped ruff and ran the four behind it, each failing with
`No module named …`. Five red steps, four of them noise, and the one
real cause the only one that did not look like a gate failure.

All five now carry `steps.install.outcome == 'success'`, and the
coverage floors carry `steps.pytest.outcome == 'success'` instead —
`tools/coverage_floor.py` runs the whole suite again in a subprocess, so
on a red suite it costs a second full run per version to report every
module under its floor.

### S4 four notes that were wrong about the code beside them — `eefa243`, `33f1b8b`, and the CI commit
<!-- status: fixed -->

Small, and all four would mislead the next reader:

* `set_done` counted every entry it MATCHED as changed. The number goes
  back to the author as how many comments were resolved, and a resolve
  pass is re-run — it is how a paper checks the job is done — so a
  finished round reported itself as freshly resolved.
* the pymupdf override said "an optional extra is ABSENT on CI by
  design" in the same commit range that made CI install `.[dev,pdf]`.
  Read as written, the next person removes the extra and puts
  `pages.py` back under its coverage floor. What it answers is a
  `.[dev]`-only checkout.
* `harness_map`'s new measurement one-liner was mangled onto one line
  with a `#:` in the middle, so pasting it fed `#:` to pytest as a path.
  And the rule it stated was wrong: a file's coverage ON ITS OWN is the
  wrong measurement, because fixture use looks like exercise.
  `test_tables_fit.py` covers 32 % of `_table_core` alone and adds
  NOTHING to its harness, which sits at 97 % either way — so
  `_table_core`'s two exclusions are sound, and the note now says to
  measure MARGINAL coverage.
* `footnotes.SizeReport.format` lost its degradation path to an
  `assert` written to kill two mutants. The class is public and its
  fields are writable, so a caller filling `mark_outliers` got an
  AssertionError — and under `python -O` the assert is stripped and the
  line becomes `None / 2`.

### S2 `probe` called a bookmark above every paragraph "nested", so a block move would drop it — `98a522f`
<!-- status: fixed -->

Found 2026-08-18 by mutation testing, and the surviving mutant was the
CORRECT spelling — the first time that has happened here.

    where = "body" if closed > before else "nested"

classifies a bookmark by whether a paragraph closed more recently than
one opened. The two searches are equal only when both are -1, and
`</w:p>` does not contain `<w:p`, so that is exactly one case: a
bookmark that precedes EVERY paragraph in the body. Word writes them —
a document-wide bookmark sits there.

Such a bookmark is a sibling of the paragraphs with none to travel with,
which is precisely what the field is read for: "a block move has to
carry those, and they are invisible to a paragraph-oriented edit".
Reported as nested it reads as one the edit carries for free, and the
move drops it silently.

    [('doc_top', 'nested'), ('between', 'body'), ('inside', 'nested')]

**Fixed the same session** (`98a522f`): `>=`, with the argument in a
comment beside it, and `tests/test_probe.py` carrying the case.

**S2 rather than S4** because probe is advisory only in the sense that
nothing gates on it — a batch reads it to choose an approach, and this
one understates what a move must carry.

### S3 the Word-driven width gate failed on a clean machine, on the shortest cell in its list — `984156f`
<!-- status: fixed -->

Run on 2026-08-18 because CONTRIBUTING says to run `pytest -m word`
after any edit to `_table_layout`, and that day had two. Result: 7
passed, 1 failed —

    test_the_method_agrees_with_the_afm_tables: worst 1.1%

against a 1 % bound. Nothing to do with the day's edits, and nothing to
do with the model either.

**Measured before touching it**, which is the whole of the diagnosis:

    +2.6 dxa  'No'          model 244.4  Word 247
    +3.0 dxa  '12.7'        model 350.0  Word 353
    -3.6 dxa  '-0.008'      model 516.6  Word 513

A few twips, both signs, no relation to length — the side bearings and
the whole-twip rounding a WHOLE-string measurement carries.
`word.ruler`'s docstring names the first and says to cancel it with the
`(w(c*40) - w(c*20)) / 20` difference; the per-character test above does
exactly that, and this one cannot, because whole cells are its subject.

So the bound was a statement about cell LENGTH: 2.6 dxa is 1.05 % of a
two-character cell and 0.1 % of a thirty-character one, and the shortest
string in the list decided the gate.

**Fixed** (`984156f`): one percent of the string plus four dxa, the
measurement recorded in the comment beside it, and the failure now
lists WHICH cells rather than one percentage. The guard still catches
what it exists for — a substituted face or a broken ruler is out by tens
of percent, not by three twips.

**S3 because of what a red gate costs here**: this one is deselected by
default and takes a minute, so it is run on purpose or not at all. A
gate that fails on a clean machine for a reason nobody has written down
is a gate people stop running, and the width model has no other check —
a 10 % error in the Arial Narrow digits survived months for exactly
that reason (V4 in ROBUSTNESS_PLAN.md).

### S1 `set_done` wrote a SECOND `w15:done` beside the one it could not see — `bf30a89`
<!-- status: fixed -->

Found 2026-08-18 by asking what the `done_m.group(1) == "1"` survivor in
`threads` would mean if the attribute were spelled the other legal way.
`w15:done` is ST_OnOff: Word writes 1 and 0, and the schema also allows
true/false and on/off. The pattern was `w15:done="(\d)"` — one digit.

Read side: a comment another producer had resolved came back OPEN. A
settled query returns to the work list, and `docxkit tasks --check`
fails a round that is finished.

Write side, and worse, because the writer used the same pattern:

    <w15:commentEx w15:paraId="AAAA0001" w15:done="true" w15:done="1"/>

    lxml: Attribute w15:done redefined

`set_done` could not see the flag, so it took the "add one" branch. The
part stops parsing, Word calls the document unreadable, and the only
tool that could say why is the one that wrote it. Reproduced before it
was believed.

**Fixed the same session** (`bf30a89`): the pattern reads the whole
attribute value and the truthiness is a set — `{"1", "true", "on"}`,
lowercased — so the reader and the writer agree about what the flag
says. `tests/test_comment_threads.py` carries three, two of which fail
without it.

**Reach.** Word writes `"1"`, so no paper here has hit it; a package
that has been through LibreOffice or a comment add-in can carry the
other spelling, and `_compare_read.on()` in this same package already
reads `0/false/none`, which is the shape this should have had.

### S1 `house(caption=...)` wrote keepNext into the middle of the caption's style name — `2ea64f5`
<!-- status: fixed -->

Found 2026-08-18, the same cluster as the entry below and worse.
`_keep_with_table` computed where to insert as
`existing[0] + existing[2].index(">") + 1`: the offset OF the `w:pPr`
element plus an offset INTO its content, which are different coordinate
systems. On a caption paragraph styled `Caption`:

    <w:pPr><w:pStyle w:val="Cap<w:keepNext/>tion"/><w:jc .../></w:pPr>

A tag inside an attribute value. `house` returned `caption=True`, and
Word opens the file with "unreadable content".

**Every caption in a real manuscript reaches this branch** — a Caption
style, a justification, or both — and `tests/test_tables_house.py` built
its fixture with `para(run(...))`, which carries no `w:pPr` at all. So
the branch that runs on a paper had never run in the suite, and 10 of
the module's survivors were sitting in it.

**Fixed the same session** (`2ea64f5`): the slot is after the `w:pPr`
open tag, or after the `w:pStyle` if there is one, that being the only
child CT_PPr allows before `keepNext`; and `<w:pPr/>` is EXPANDED rather
than written past, since writing after a self-closing tag's span puts
the property outside the element it belongs to. Four tests on that
branch, three of which fail without the fix.

**Both defects in this pair came from the same question**: not "is the
element in the output" but "WHERE did it go". The tests that missed them
asserted the first.

### S2 `house` put the table width ahead of the style CT_TblPr requires first — `f1b101b`
<!-- status: fixed -->

Found 2026-08-18 by asking WHERE the 12 survivors in `_house_width` put
the element, rather than whether it was in the output. CT_TblPr is a
sequence — tblStyle, tblW, tblLayout, tblLook — and the splice was at
`props.index(">") + 1`, the FRONT:

    <w:tblPr><w:tblW .../><w:tblLayout .../><w:tblStyle w:val="TableGrid"/>

Every table `body.table` builds carries a tblStyle, so every one that
`house` touched came out this way. Word repairs a table whose properties
are out of order by dropping the misplaced ones on the next save: the
width stops applying some weeks later, in the author's copy, with
nothing in any diff. The same failure `hygiene.table_spacing` records
for CT_PPr, one element up.

The tests said `'<w:tblW w:w="5000" w:type="pct"/>' in out`, which is
true wherever it lands. That is the shape to watch for in this package:
an assertion that the right string appears somewhere is an assertion
about a `find`, not about the document.

**Fixed the same session** (`f1b101b`), by routing both properties
through `_set_tbl_pr` — the ordered writer `fit_columns` has used all
along. It closed a second defect on the way: the old path wrote into
whichever `w:tblPr` came FIRST, which is a nested table's whenever the
outer table has none, so an outer table with no properties got none.

Two holes in the shared writer had to close for that, and both were
reachable only by a caller that does not write a grid first:

* no `w:tblGrid` to insert before meant `at = len(body)` — the
  properties appended AFTER the last row, which is not a table. Now
  before the first row, or after the open tag when there are no rows;
* `_own_tblpr` bounded its search by the grid and searched the WHOLE
  body without one, reaching the nested table's properties — the exact
  defect its own docstring exists for.

`tests/test_tables_house.py` carries four: the schema slot, the replace
in place, the fragment with no properties at all, and the nested table.
The first three fail without the fix; the fourth fails without the
`_own_tblpr` half.

**The module's 21.0 % figure is now void** — the source changed under
it, which ends the series. The next measurement is a fresh draw.

### S2 three of `_table_layout`'s five harness exclusions were never true, and the number it produced is void
<!-- status: fixed -->

Found 2026-08-18 while reading the sweep's survivor list. Twelve of the
79 real survivors were in `drop_blank_rows`, whose whole test file —
`tests/test_tables_blank_rows.py`, sixteen calls to it — was in
EXCLUDED for that module. `drop_blank_rows` IS `_table_layout.py`.

The exclusion said "the DATA half's files: they read cells and rewrite
values, which the layout module has no part in". Measured with
`--cov=docxkit._table_layout`, against the 13 % that merely importing
the module covers:

| file | covers | excluded as |
|---|---|---|
| `test_tables.py` | 13 % | the data half — TRUE |
| `test_tables_update.py` | 13 % | the data half — TRUE |
| `test_tables_api.py` | 22 % | the data half — false |
| `test_tables_blank_rows.py` | 26 % | the data half — false |
| `test_tables_nested.py` | 40 % | the data half — false |

This is the `_table_core` failure a second time — 216 survivors in
`update` from a harness missing `test_tables_update.py` — and it got
past the gate written for that one, because the gate accepts EXCLUDED
as an answer and an exclusion is the single claim in `harness_map.py`
that nothing checks.

**S2 rather than S3:** the gate is green and correct as far as it goes.
What is wrong is a NUMBER, published in CONTRIBUTING's sweep table
(18.4 %, 79 survivors, `drop_blank_rows` named as the second-largest
cluster), which reads as a statement about the module and is a
statement about a run missing three of its test files.

**Fix (already in):** the three files moved out of EXCLUDED into the
harness, and the note above EXCLUDED now carries the one-liner that
measures an exclusion, plus the reason to run it before writing one.
The 18.4 % is void until re-measured; that re-measurement, and the
correction in CONTRIBUTING beside the figure it replaces, close this.

**What would gate it properly:** coverage per excluded pair, which is a
minute of wall clock over eleven pairs — too slow for the default
suite, and the reason it is documented rather than gated. A cheaper
static rule was tried and rejected: an excluded file that merely NAMES
something the module defines is usually using it as a fixture, which is
what `test_tables_fit.py` does with `read_all` and `Table`.

**Closed 2026-08-18** (`b5a96a5` the harness, `92e00f7` the figure).
Re-measured under all eleven files: **21.0 % real survival, 92 of
439**, against 18.4 % under eight. The corrected harness reads HIGHER,
and that is not a paradox — the two runs are different draws of a
2,834-mutant module sampled at 460, and the earlier session's
parameters are recorded nowhere, so they were never a pair. The
comparison that IS one is the function the exclusion hid:
`drop_blank_rows` went from **12 survivors to 1**.

Both figures now stand in CONTRIBUTING with that said beside them,
which is the point of the entry: not that 18.4 % was too low, but that
it was a number about a run rather than about the module.

### S1 `comments.remove` deletes the paragraph when the reference mark is not in a run — `d5c9e25`
<!-- status: fixed -->

Found 2026-08-18 by mutation testing `_drop_reference_run` (7 real
survivors, all on the branch below), and reproduced before it was
believed:

    parts = ... two comments, comment 1's mark BARE in the paragraph
    remove(parts, ["1", "2"])            -> returns 2
    body                                 -> <w:p></w:p>

Every word of both paragraphs gone, and the call reporting success.

**Diagnosis.** The walk finds the run around the mark by taking the last
run to START before it. A run that CLOSED before the mark is a
NEIGHBOUR, not the enclosure, so the deletion ran from that neighbour's
start to the first `</w:r>` after the mark — across the rest of the
paragraph and into the next one. The branch meant to catch "no run
around it" asked `if not starts`, i.e. whether any run started earlier
at all, which is true of every paragraph with prose in it.

**Fixed in the same session** (`d5c9e25`). The test is whether that run
is still OPEN at the mark: `doc.find("</w:r>", starts[-1], at) == -1`.
Where it is not, there is no run to drop and the MARK goes instead —
a reference to a comment that no longer exists is itself what Word
reports as unreadable content, so keeping it (what the old branch did)
was the other half of the same repair prompt.
`tests/test_parts_gaps.py` carries both directions; each fails without
the fix.

**Reach.** Word always wraps the mark, and `_anchor` here writes it
wrapped too, so this needs a foreign or repaired document — which is
the kind this toolkit is pointed at, and the reason `remove` exists at
all is the DSI paper's five resolved review comments.

### S4 `tools/mutation_survivors.py` dies on the one module whose source it cannot print
<!-- status: fixed -->

Found 2026-08-18, reading the survivor report for `_table_layout.py` —
the module the current wave is measuring:

    L188   x1   in <module>
              500: "#$*_0123456789bdghknopquvxy–", 564: "+<=>−",
    UnicodeEncodeError: 'charmap' codec can't encode character
    '\u2212' (the typographic minus) in position 57

The report prints the SOURCE LINE each survivor sits on, and
`_table_layout`'s glyph-width table is a literal roll of the characters
a proportional font renders: en dash, curly quotes, the typographic
minus. On a Windows console that is cp1252, and the print raises.

It dies PART WAY. Everything above L188 had already printed, and the
`by definition:` tally at the end — which is how a round picks what to
write tests for — never printed at all. Loud enough to notice, hence S4
and not S2; but the module with the widest survivor list is the one the
tool cannot read to the end.

`console.utf8_stdout()` is in the package for exactly this, and
`tools/sweep.py` and `tools/coverage_floor.py` both call it first thing
in `main()`. `mutation_survivors.py` does not — nor do `harness_map`,
`kill_check`, `measure_all`, `mutate` or `mutation_session`, though it
is the only one of the six that prints a line of somebody's source,
which is why it is the only one that has hit this.

**Fix:** import and call `utf8_stdout()` at the top of `main()`, the way
the other two tools do (`coverage_floor.py` also carries the
`sys.path.insert` that makes the import work from a bare checkout). The
test is the report run over a module holding a non-cp1252 glyph with
stdout forced to cp1252 — which is the only way it fails, so it is the
only way it can be gated.

**Workaround in use:** `PYTHONIOENCODING=utf-8 python
tools/mutation_survivors.py .mutation-table_layout.sqlite
src/docxkit/_table_layout.py`, which is how `_table_layout`'s 18.4 %
(79 of 429) was read at all.

**Fixed 2026-08-18** (`3178e8a`), in the session that filed it.
`utf8_stdout()` is called first thing in `main()`, behind the `sys.path`
line `coverage_floor.py` already carries so the import works from a bare
checkout. `tests/test_mutation_survivors.py` runs the report over a
module holding both an en dash and U+2212 with `PYTHONIOENCODING` forced
to cp1252 and to ascii and asserts the `by definition:` tally arrives:
both fail without the call, the utf-8 case is the control that passes
either way, and a fourth test holds the replacement to being a FALLBACK
rather than the behaviour — where the console can hold the minus sign it
is printed as written. The `PYTHONIOENCODING=utf-8` workaround is gone.

### S2 `renumber.py` is the least-pinned module measured — 15.1 %, and a third of it is `footnote_audit`
<!-- status: fixed -->

Measured 2026-08-17, never looked at before. It rewrites caption numbers
and cross-references across a whole manuscript, and `shift()` is what a
paper runs when an exhibit is inserted.

    815 mutants, 692 killed, 123 survived
    REAL SURVIVAL 15.1 % (123/815)

Harness: `test_renumber` + `test_footnote_ids`, 95 % of the module by
line — the same figure the WHOLE suite reaches, so nothing else
exercises it.

| survivors | function |
|---|---|
| 40 | `footnote_audit` |
| 19 | `_shift_in_para` |
| 11 | `shift` |
| 10 | `footnotes` |
| 9 | `remap_parts` |

**The footnote half is the weakest, and it is the newest code** — added
this same week to close the S4 about `renumber` handling caption numbers
but not note ids. `footnote_audit`, `footnotes` and `remap_parts` are 59
of the 123 between them.

**`footnote_audit` pinned** (`tests/test_footnote_audit.py`), 12 of 13
targeted mutants dead. Thirty of its forty survivors sat on ONE line —
the message naming where the ids stop following the reference order,
which is the entire output for that case: a note out of order is
invisible in the document, because Word renders the marks 1, 2, 3 down
the page by position whatever the ids say.

Three of my own fixtures reached the wrong branch and the check caught
them: the early return is `not referenced AND not stored`, so
distinguishing it needs a document with notes and NO references (and the
mirror); and `b < a` against `b <= a` needs a REPEATED id before the
real descent, since equal ids are the same note twice and not a break.

**Second pass, 2026-08-17.** `_shift_in_para` and `shift` pinned; the
overlap test in `_shift_in_para` turned out to be a FOURTH copy of the
predicate consolidated into `_xml.overlaps` that morning, spelled
`re_ <= a or rs >= b` — which is why the grep that found the other
three missed it.

**Third pass, 2026-08-17.** `footnotes` and `remap_parts`.

**Eight of `remap_parts`' nine survivors were in a branch with no
effect.** It read `remap` for the body and `_check_permutation` plus
`_apply` for every other part — and `remap` IS those two calls, so the
arms differed only in which XML the permutation check reads. For the
body that is the same string; for a footnote the check is vacuous
either way, because a footnote holds no captions. Swapping the arms
changed nothing, which is why the mutants lived. The branch is gone,
the check is hoisted (it took identical arguments on every pass of the
loop), and the empty-mapping refusal that `remap` provided incidentally
is now explicit. Third piece of dead code this technique has found
here, after `label_extent`'s walk and `_entry_keys`' lead token.

`footnotes` gave up two real ones: `set(referenced) - set(stored)`
against `^`, where the symmetric difference calls a spare note
"missing" and refuses a document that is only untidy; and the note
elements being re-sorted by ID rather than by anything else, so the
file reads the way it renders.

**Closed 2026-08-17.** Re-measured as a fresh 460-draw (the module has
changed since, so the earlier session was void): **5.7 % real survival,
26 of 460**, against 15.1 % when it was first looked at. It is now among
the best-pinned modules in the package, beside `_cite_repair` and
`_compare_render`.

Nothing is left worth naming: the largest cluster is five, spread over
`footnotes`, `_shift_in_para` and `shift`, and it reads as the shape
these tests already record — `==` mutated to `is` between two computed
values, a default on a report field nothing asserts by number, a
`max(0, ...)` clamp no fixture reaches from the far side.

### S2 41 % of mutations to `_cite_build.py` survive, and half of them are on lines the tests never run
<!-- status: fixed -->

Regenerated 2026-08-15 after the first run's database was deleted; the
two runs agree (49.3 % raw then, 49.0 % now).

    996 mutants, 508 killed, 488 survived          raw 49.0 %
    134 on signature/docstring rows                un-killable
    REAL survival 354 / 862                        41.1 %

`edit.py` is 17.3 % and `revisions.py` 7.3 % on the same treatment, so
this is the least-pinned module measured. What makes it worth its own
entry is that the survivors split almost evenly into two DIFFERENT
problems, and they want different fixes:

| | survivors | by function |
|---|---|---|
| **never executed** — a coverage gap | 169 (48 %) | `link_all` 44, `rewrite` 41, `_dedup_name` 18, `rebuild` 17, `unlink_by_anchor` 15 |
| **executed, nothing asserts** — an assertion gap | 185 (52 %) | `rewrite` 41, `_entry_keys` 38, `scan` 38, `rebuild` 29 |

The harness is `test_citations` + `test_link_convention`, 84 % of the
module by line. The uncovered 16 % is where the first column lives:
the FOOTNOTE citation path (`fn_plan`, the `foot[m.end():]` splice),
the back-link undo when a wrapped mention never appeared, and
`unlink_by_anchor`'s error paths. A mutation there survives because the
line never runs — an arithmetic operator swapped into a string
concatenation would raise `TypeError` if anything reached it.

The second column is the same class as the `edit.py` entry above:
`_entry_keys` builds the multi-word surname keys an entry can be found
by, and `scan` decides which mention is the FIRST one; both run on every
test and neither is asserted at the value level, so an off-by-one in a
slice bound is invisible. `NumberReplacer` is again the dominant
operator (78).

**Suggested shape**, in the order that buys most:

1. a footnote-citation case in `test_citations` — one work cited only
   in a footnote, one cited in both prose and a footnote. That reaches
   most of the never-executed column, and it is the path LI7 uses;
2. value assertions on `_entry_keys` (given "van der Berg, A. and
   B. Smith (2019)", exactly which keys?) and on `scan`'s choice of
   first mention when a work appears three times;
3. `unlink_by_anchor`'s refusals, which currently have no test at all.

**Reproducing it:** `scratchpad/chunk.sh` in the session that produced
this, or the three hazards recorded in `REVIEW_2026-08-15.md` if the
harness is rebuilt from scratch. The numbers are only comparable against
the same test set, so quote the coverage beside any future figure.

**Partly paid, 2026-08-16** (`36a569f`).
`tests/test_cite_build_paths.py` runs the never-run column: a work cited
ONLY in a footnote, a work cited in both (the body mention wins), the
footnote splice leaving the note readable, `_dedup_name`'s collision,
the back-link undo when a wrapped mention never appeared, and
`unlink_by_anchor`'s three cases including the field form. Plus value
assertions on `_entry_keys` — which keys "World Bank Group. (2024)"
answers to, exactly.

Re-measured on a random sample of 460 (seed 20260816): **real survival
41.1 % -> 35.0 %**, about 2.5 standard errors, and coverage 84 % -> 86 %.

**Writing those tests found an S1**, which is the point of the exercise
and is filed below: two entries sharing a surname AND year produced two
bookmarks with the SAME name.

**Closed 2026-08-17.** Re-measured as a fresh 460-draw: **9.4 % real
survival, 37 of 392**, against 41.1 % at the first measurement and
25.2 % at the paired one. The harness is the nine files
`tools/harness_map.py` now records for it.

The largest remaining cluster is ten in `unlink_by_anchor`, and six of
those sit on a line the source itself marks `# pragma: no cover -
defensive`. The rest is ones and twos across the message strings and the
name-minting loop. The three defects this entry's rounds turned up — a
sentence in the back matter parsing as a reference entry, two entries
sharing one bookmark, and a dead lead-token branch in `_entry_keys` —
are fixed and held by tests.

### S2 `_xml.py` had never been mutation-tested, and 27 of its 45 survivors are the FIELD WALK
<!-- status: fixed -->

Measured 2026-08-17, the first time this module has been looked at —
and it is the bottom of the package: 33 modules import it, and today it
also gained `run_spans`, `in_span`, `overlaps` and `span_holding`, so a
defect here reaches everything and the consolidations rest on it.

    538 mutants, 471 killed, 67 survived
    22 inside a type annotation (PEP 563: unkillable)
    REAL SURVIVAL 8.7 % (45/516)

Harness: `test_xml_primitives`, `test_find_edit`, `test_compare`,
`test_citations`, `test_revisions`, `test_footnotes`, `test_body`,
`test_package` — 97 % of the module by line, against 98 % for the whole
suite at eight times the wall clock. Quote the harness beside the
number.

8.7 % is respectable for a module nobody had measured, and it sits
between `edit.py` (6.3 %) and `_cite_build.py` (11.4 %). The
DISTRIBUTION is the finding, not the rate:

| survivors | function |
|---|---|
| 17 | `field_spans` |
| 10 | `run_open_before` |
| 4 | `set_run_text` |
| 4 | `own_properties` |
| 3 | `element_spans` |

**The two at the top are one walk** — `field_spans` asks
`run_open_before` where a field's begin run opens — and it is the walk
whose own docstring says it "existed three times with three different
guards, only one of which defended against a field whose end tag is
missing". It was consolidated for that reason and then never pinned:
one test reached it, about nesting, in `test_pathological.py`.

**Pinned, 2026-08-17** (`tests/test_field_walk.py`). 10 of 13 targeted
mutants die; 3 are equivalent because the values reaching them are a
closed set (`FLDCHAR_RE` captures only begin/end/separate, and
`str.find` past position 0 never returns 0). What the tests state that
nothing did: the span opens on the RUN and not the marker; the sentinel
for "no run" is negative because every caller tests `< 0`, and 0 would
read as the top of the document; a field that cannot be closed is
skipped and does not stop the walk finding the next one; and the sort
tie-break puts the wider span first, reachable only when two begin
markers share a run.

**Closed 2026-08-17.** Re-measured as a fresh 460-draw (the module has
changed, so the paired series was void): **5.4 % real survival, 24 of
441**, against 8.7 % when it was first measured. The largest cluster is
two, and what is left reads as the equivalences the tests already
record — `==` mutated to `<=` on comparisons whose values are a closed
set, `!=` to `is not` where `str.strip` returns the same object, and
`-span[1]` to `~span[1]`, which sorts identically.

The named leftovers were checked by hand-mutation rather than waiting
for the draw: `set_run_text`, `own_properties` and `element_spans` each
have their decisions held by a test (the first run takes the text and
the rest are blanked, the properties element is the child right after
the open tag and its span covers the close, a self-closing element has
no properties and no span).

### S2 the link guards' own machinery is not pinned: 17 % of mutations to `edit.py` survive, and they cluster on `label_extent`
<!-- status: fixed -->

Found by mutation testing `edit.py` on 2026-08-15, in a worktree, after
the structural review asked for it.

    1385 mutants, 1061 killed, 324 survived        raw 23.4 %
    102 of those sit on signature/docstring rows   -- annotations under
    `from __future__ import annotations` are never evaluated, so no test
    can kill them
    REAL survival 222 / 1283                       17.3 %

For comparison `revisions.py` is 7.3 % on the same treatment. The
harness is `test_find_edit` + `test_edit_branches` +
`test_normalize_anchors`, which reach **95 % of the module by line** --
so this is not a coverage gap, it is an ASSERTION gap: the lines run and
nothing checks what they compute.

| survivors | function |
|---|---|
| 58 | `label_extent` |
| 37 | `replace_in_para` |
| 31 | `_outside` |
| 20 | `_restyle` |
| 17 | `_locate` |
| 14 | `insert_in_para` |

`NumberReplacer` is the dominant operator (69) -- an off-by-one in an
offset, invisible.

**Why this is worth an entry rather than a shrug.** `label_extent` walks
outward from a run to find where a FIELD-FORM hyperlink's label really
ends, and `_outside` decides whether an insertion point may move outside
a link or a bookmark. Both exist to serve the two S1 entries about a
link swallowing prose -- the failures where the words read correctly,
the anchor resolves, and only `compare`'s review-not-gated HYPERLINK
layer sees the damage. Mutating `lo_i -= 1` or `hi_i += 1` in that walk
leaves all 103 tests passing. The tests assert THAT a refusal happens;
they never assert WHERE the label ends, which is what the guard decides.

**Suggested shape.** Tests that state the extent as a VALUE: a paragraph
with a field-form link split across three runs, asserting the span
covers exactly the label; the same for `_outside`'s three answers (span
start, span end, None). A cheap first pass is to assert the LABEL TEXT
after every operation in the existing link tests -- which is the
assertion the S1 entries say no other layer makes.

**Caveat on the numbers:** they are only comparable against the same
harness, and three cosmic-ray hazards had to be handled to get them at
all (all recorded in `REVIEW_2026-08-15.md`): killed mutants
misclassified through a UTF-8 decode of cp1252 output, which also cost
60x in wall clock and understated the morning's `revisions.py` run; a
terminated run leaving its mutation in the tree, which produced a
1383/1385 "kill rate" on a red baseline; and the same termination
leaving null-outcome rows that make the session unresumable.

**Partly paid, 2026-08-16** (`36a569f`). `tests/test_edit_boundaries.py`
states the boundaries as VALUES: where a field-form label ends, in both
link forms and anchored from a middle run; `_outside`'s three answers;
`_restyle`'s split at both edges of a span. Hand-mutating the six exact
lines the survivors sat on now kills all of them, and `_outside` has
left the survivor list entirely.

One of those six could not be killed by any test, and that was the
finding: `label_extent` returned a ``(start, end)`` pair and walked LEFT
to compute a start **no caller ever read** — the guard asks only "does
the match run past the label". Dead computation, which is why 58 mutants
lived in it. It is now `label_end`, returning an int, and the leftward
walk is gone.

Re-measured on a reproducible random sample of 460 mutants (seed
20260816): **real survival 17.3 % -> 14.8 %**. Worth reading with its
error bar — at n=460 that is about one standard error, so the sample
alone would not settle it; the hand-mutation result and the disappearance
of `_outside` are the stronger evidence.

**Still open**, because the residue is real: `label_end` 14,
`replace_in_para` 10, `_locate` 10, `_restyle` 5, `_split_run` 5. The
`_locate` cluster is the next worth doing — it computes the run spans
every other function here consumes.

**Second pass, 2026-08-16** (`e5c23cb`). `_locate` pinned:
`tests/test_locate_spans.py` states the spans as literal values — that
they tile the visible text, that an equation between two runs shifts
every later span by ITS width (one for ``τ``, two for ``xy``), that a
note marker takes an empty span in place, that `within` answers with
offsets into the WHOLE paragraph rather than the scoped slice, and that
ambiguity is an error. Six of six targeted mutants die, including the
one that mattered most: the between-run width, which is the DSI §6.3
incident in one line.

**Re-measured on the SAME 460 mutants** (seed 20260816, identical draw,
source unchanged, only the tests differ — so this is paired, and since
tests were only added no mutant can move the other way):

    real survival  17.3 %  ->  14.8 %  ->  13.0 %

The last figure is the repo's OWN classifier
(`tools/mutation_survivors.py`, which discounts annotation mutants by
AST span). The two before it were computed by hand with a cruder
line-based rule, which errs in both directions — it read this run as
12.0 %. Quote the tool's number from here on; it already existed, and
re-deriving it by hand is what made these three not quite comparable.

`_locate` itself went from 10 survivors in the sample to 6.

**Still open:** `replace_in_para` 10, `label_end` 8, `insert_in_para` 6,
`_locate` 6, `_between_runs` 4. `replace_in_para` is now the largest,
and it is the function every paper calls most.

**Third pass, 2026-08-16.** `replace_in_para` pinned:
`tests/test_replace_spans.py`. Nine survivors show in the sample: four
are BOUNDARY comparisons — which runs the note guard inspects, which
runs the edit loop rewrites, whether the match runs on past a
hyperlink's label — three are equivalent by construction, and the last
two are the signature's keyword-only marker and the truncation in an
error message. A boundary cannot be checked from the middle of it. Every
fixture the function had put its run edges away from the offset in
question, so the comparisons were free to be one character out. Each new
test puts a run edge exactly ON it: a note marker beyond a match that
ends mid-run, a link run starting exactly where the match ends, a match
ending strictly inside a longer label (the whole-caption link several
papers write on purpose).

**Seven of seven targeted mutants die**, verified one at a time by
mutating the source and running the harness, with the killing test named
for each — a suite that is green after a test is written is not evidence
that the test kills anything.

Two are worth remembering beyond the count:

* `end > label_end(idx)` mutated to `end is not label_end(idx)` passed
  every fixture in the file, because CPython interns integers to 256 and
  every test paragraph was shorter than that. An identity comparison on
  two computed offsets is a live bug that short fixtures cannot see; the
  new test uses prose long enough to leave the cache.
* cosmic-ray mutates the keyword-only marker `*` in the signature to
  `/`, which is valid Python and makes `replace_in_para(p, old, new,
  True)` legal — a positional bool that silently disables the hyperlink
  guard and reads like data in the diff. The flags are now pinned as
  keyword-only.

Three mutants are left alive DELIBERATELY and recorded in the test file
so the next reader does not spend the afternoon twice: `strict=True` in
the `zip` (the invariant is pinned at its source in
`test_locate_spans.py`), `hits[0]` -> `hits[-1]` (the line above raises
unless the list has exactly one element), and `stop > end` -> `stop !=
end` (the slice is empty either way).

**Re-measured, and this time PAIRED properly.** Yesterday's session was
re-run over its own survivors under today's harness — the same mutant
objects, not a fresh draw, and the old cosmic-ray config was recovered
from `cr-edit.toml` so the superset claim is checked rather than
assumed (five test files then, the same five plus
`test_replace_spans.py` now):

    real survival  13.0 % (56/431)  ->  11.6 % (50/431)

Six of yesterday's fifty-six real survivors now die and **no new one
appeared**, which is what a superset harness has to produce. The six are
exactly the sampled targets — the seventh verified kill, the same
truncation in the non-normalized message, was not in the draw.

`replace_in_para`'s own body now has no unexplained survivor in this
sample: the three that remain are the three documented as equivalent
above. Its nested helpers are a separate matter and still carry eleven
between them — `label_end` 6, `labels_a_link` 2, `styled` 2, `missing`
1 — and `label_end` is where the next pass in this function belongs.

**A caveat that cost most of the afternoon.** A fresh 460-draw at the
same seed does NOT reproduce a draw some other script made — yesterday's
databases came from the hand-rolled scripts, and the two draws overlap
by 33 %. Run through that fresh draw, the same source under the same
six test files reads **15.5 %**, against 11.6 % on the paired one. Same
code, same tests, different mutants. Quote the paired number; a single
sample of 460 is worth a couple of points either way, and two of the
three figures in the progression above were read off draws that cannot
be compared with each other at all.

**Still open:** 50 real survivors in the paired sample, led by `_locate`
7, `insert_in_para` 7, `label_end` 6, `_between_runs` 4. (These counts
moved slightly against the previous note for a second reason: the
report used to attribute a survivor to the last `def` ABOVE its line,
which hands a function's own body to whichever nested helper was
defined last. It now attributes by AST span.)

**Fourth pass, 2026-08-16.** `insert_in_para` and `_between_runs`
pinned by `tests/test_insert_spans.py`, `_locate`'s residue by three
more tests in `tests/test_locate_spans.py`. **Ten of ten targeted
mutants die**, verified by hand-mutation with the killing test named;
four more are confirmed EQUIVALENT and recorded in the test files.

The survivors here were the arithmetic that decides WHERE content
lands, against tests that checked only whether it was refused. The
offsets in the new fixtures are chosen so a wrong operator gives a
wrong answer: `at - start` mutates to `at | start` and `at ^ start`,
and for most small pairs those land past the end of the run, where the
slice yields the whole body and an empty tail — the content then
appears AFTER the run rather than inside it, which a text assertion
sees and a "did it raise" assertion does not.

Two things recur, and both are worth knowing rather than counting:

* **the keyword-only marker again.** `insert_in_para` carries the same
  `*` -> `/` mutation as `replace_in_para`, with the same consequence:
  `insert_in_para(p, at, content, True)` becomes legal and silently
  disables the hyperlink guard. Every function in this package taking
  `allow_*` flags has this hole until a test says otherwise;
* **the integer-identity trap, twice more.** `at == cursor` and `s ==
  at` in `_between_runs` both survive as `is`, because CPython interns
  integers to 256 and no fixture in the file had a paragraph longer
  than that. Any comparison of two COMPUTED offsets in this module has
  the same blind spot, and a short fixture cannot see it.

**Re-measured, paired again** — the same 460 mutants, harness now seven
files:

    real survival  13.0 %  ->  11.6 %  ->  8.4 % (36/431)

Fourteen more die, none appears. The chain from 13.0 % is sound
throughout: one draw, and every step added test files without touching
`edit.py`.

**Still open:** `label_end` 6, `_outside` 3, `_split_run` 3,
`replace_in_para` 3 (the documented equivalents), `_locate` 3 (likewise),
and a tail of ones and twos.

What is left in this module is now mostly ONE shape: `lo <= run.start()
< hi`, the question "does this span contain this run", asked in
`labels_a_link`, `label_end`, `_split_run` and `_outside`. Its mutants
move a boundary by one run, and several are equivalent because a run
cannot start exactly where a hyperlink ELEMENT opens — the tag is in
the way. Distinguishing the rest needs a field-form span, whose bounds
are run boundaries and can coincide. That is the next pass here, and it
is worth doing as one test file for all four call sites rather than
four times over: the walk that lives in four places is the walk that
will disagree with itself, which is the argument `field_spans`'s own
docstring already makes about its three predecessors.

**Seventh pass, 2026-08-16.** All four sites, in one file —
`tests/test_span_membership.py`. **11 of 17 mutants die and the other
6 are confirmed EQUIVALENT**, each with the reason recorded. Paired
again, same 460:

    real survival  11.6 %  ->  8.4 %  ->  6.3 % (27/431)

`_outside` has left the survivor list entirely; `label_end` is 6 -> 3,
`_split_run` 3 -> 1, `labels_a_link` 2 -> 1, and what remains at those
three is the equivalences.

The fixtures needed two things the module's earlier tests never had.
**A styled run OUTSIDE the element**: Word leaves `rStyle Hyperlink` on
runs beside a link as freely as on the label itself, so "looks like a
link" and "is inside the link element" are different questions —
`label_end` asks the element first and falls back to the styled
neighbours, and the two answers only differ where such a run sits.
**A `w:proofErr` between runs**: without a gap the run after an element
begins exactly where the element closes, so `run.start()` and `hi` are
the same small integer and therefore the same OBJECT — `is not` then
answers what `<` answers, and the mutant hides. That is the third time
the small-integer cache has decided a test in this module; it is worth
treating as a rule rather than a surprise, because every one of these
comparisons is between two computed offsets.

**Closed 2026-08-17.** Re-measured as a fresh 460-draw: **11.5 % real
survival, 49 of 425**, against 15.5 % for the last fresh draw of the
older source (the 6.3 % above is a PAIRED figure and not comparable
with either). No cluster above eight, and the largest are the
equivalences these test files already record.

Two real gaps came out of the new draw and are fixed: `rep` refused too
FEW anchors and would have accepted too MANY — the dangerous direction,
since the replace then succeeds and edits a sentence nobody looked at —
and `preserve_space`'s three attribute cases were one test wide, so a
run that already carried the real `xml:space` and a run carrying only
the junk one were indistinguishable to the suite.

### S1 WORD downgrades U+2212 to an ASCII hyphen inside OMML — on Compare AND on the author's own accept-and-save — and `validate` reports it as an unattributed `glyphs: False`
<!-- status: fixed -->

**Widened 2026-08-17, hours after filing.** This entry first blamed
`CompareDocuments`. That is too narrow, and the narrower claim would have
sent the fix to the wrong place. Traced through the whole chain on AFI,
counting U+2212 in `m:t`:

    prev.docx      (baseline)                    2
    r3_clean.docx  (edited clean copy)           2
    batch.docx     (Compare + repair pass)       2
    rescue copy    (byte-for-byte as promoted)   2
    working.docx   (after the AUTHOR accepted)   0   <-- here

The repair survived Compare and promote intact. The glyphs were lost when
the author opened the promoted redline in Word, accepted the revisions and
saved. So a post-build repair is NOT sufficient: **any Word round-trip can
strip the character**, and on this manuscript the accept step re-serialises
the OMML (`ingest` also reports the formula's tokens and structure
changing). A paper cannot hold U+2212 in maths across an author round
unless something puts it back afterwards.

Implication for the fix: repairing inside `revision build` would not have
helped. The check belongs where a Word round-trip is detected —
`ingest`/`baseline` should report a maths glyph regression the way
`baseline` already refuses a lost link, so the author's accept cannot
silently degrade an equation.

Measured on AFI 2026-08-17. A batch built through `revision build`
reaches `validate` with:

    reject-all == baseline ? {paragraphs: True, glyphs: False,
                              footnotes: True, links: True} -> MISMATCH

and nothing says what moved. The difference is **two characters**, both
in an Appendix A equation:

    baseline  AFIi,1990 + t−199030 · (AFIi,2020 − AFIi,1990)   U+2212
    rejected  AFIi,1990 + t-199030 · (AFIi,2020 - AFIi,1990)   U+002D

Counting `m:t` across the package confirms it is not a reject-path
artefact — it is in the built batch, so **promote ships it**:

    prev.docx    math U+2212: 2    math hyphen: 14
    batch.docx   math U+2212: 0    math hyphen: 16

Prose is untouched (57 U+2212 on both sides); only OMML is rewritten.
S1 because it is a silent wrong answer in the output: the build reports
success, the equation renders with hyphens where the author typed minus
signs, and this toolchain's house style explicitly keeps U+2212 in
generated math. On AFI it also has history — earlier rounds repeatedly
recorded "differed only by the minus glyph (kept U+2212)".

**Two separate defects here, and the second is the expensive one:**

1. Compare's OMML rewrite loses the character. Detect it and restore, or
   refuse; a `glyph_repair` pass over `m:t` comparing against the
   baseline would do it, since the baseline is already in hand.
2. **`glyphs: False` names nothing.** `links` prints the anchor and label
   it lost; `paragraphs` and `footnotes` have their own detail lines.
   The glyph gate prints one boolean for a 68,829-character stream, so
   the reader learns only that *something* moved. Finding these two
   characters took a bespoke `difflib.SequenceMatcher` over
   `_glyph(_root(...))` with private imports. Print the first few
   differing runs with their code points, exactly as `links` prints its
   pairs.

Defect 2 is why this sat unexplained through three builds while I
attributed it to my own edits.

**Defect 2 FIXED 2026-08-17.** `revision.glyph_runs(before, after)`
names the runs where two rendered-character streams differ, with their
code points, in reading order, and `validate` fills `report.glyph_diff`
whenever gate 5 goes red — the CLI prints each as `GLYPH at 41520:
'−' U+2212 -> '-' U+002D   after ...(AFIi,2020 `. Offsets and context
come from the BASELINE side, six runs at most with the rest counted, cut
to twelve characters, code points only for runs of four or fewer (a
hundred of them is the dump this avoids). The bespoke difflib script is
no longer the way to find out what moved.

**Defect 1 FIXED 2026-08-17.** `hygiene.restore_math_glyphs(parts,
*sources)` puts the character back, per `m:t`, and `tracked.build` runs
it over the redline against BOTH the original and the clean edit before
the package is written — so the file Word verifies and the author opens
already has it, and `report.restored_glyphs` names every run repaired.

Conservative, because a hyphen and a minus are indistinguishable
character by character: a run is repaired only when its exact text
appears in a source with the glyph put back, an ambiguous form (two
source runs sharing a flattened form and disagreeing about which
character is the minus) is dropped rather than guessed, and prose is
never touched. That leaves the author's own hyphen alone, which was the
alternative failure.

It does NOT survive what comes next: the author accepting the revisions
in Word and saving re-serialises the OMML and eats it again. A paper
that must hold U+2212 through an author round still needs the repair run
after the promote — the toolkit now provides the pass, and the paper
decides where in its pipeline it belongs.

**Repro:** `docxkit revision build` any text-only batch on
`F:\OneDrive\__Documents\Aging_Update\Projects\AFI` and run `validate`;
`glyphs` is False even for a batch containing **zero** edits.

**Workaround in use** — none yet; the AFI round restores the two glyphs
in a post-build pass before promote. Per-paper workaround to delete when
the build does it.

### S2 no way to assert a table REORDER preserved its rows, which is exactly where a hand reorder loses a cell
<!-- status: fixed -->

`tables` can `update`, `set_cell` and `to_frame`, but nothing answers the
question a row reorder raises: *is the multiset of row tuples the same as
before?* Reordering is where a row's values get shifted a column — the
row moves, one cell stays — and a diff of the rendered table reads as
"rows moved", which is what you asked for, so the eye passes it.

**Hit on AFI 2026-08-17**, r3 task TE15.2: seven tables (1, 3, 4, 5, A2,
A3, A4) have their country rows reordered into one common order, and the
protocol's own acceptance criterion is a row-tuple multiset comparison
against a pre-edit snapshot. With no toolkit support that means
snapshotting every table to TSV first and comparing by hand afterwards.

Two traps a shared implementation should own, both found while writing
the snapshot:

* **one caption can front several `<w:tbl>` elements.** AFI's Table A3 is
  two of them — the first country-rowed, the second a 5×4 regression
  block — so `by_caption`-style resolution silently addresses one of two.
* **layout tables are indistinguishable by index.** AFI's `tbl#0` is a
  2×2 grid holding Figure 5's panel labels ("a. Tajikistan", "b.
  Albania"), not data. Anything iterating tables by position hits it
  first.

**Fix sketch.** A `tables.row_signature(table)` (sorted tuple multiset,
cells normalized) plus a `tables.assert_rows_preserved(before, after)`
that reports which row tuples appeared or vanished rather than a bare
False. `by_caption` should return every table under a caption, or say
how many it found.

**Workaround in use** — `AFI/revision/scripts/baseline_r3.py` snapshots
all 11 tables to `revision/baseline_r3/table_NN.tsv` before any edit.
Per-paper workaround to delete when the toolkit can state it.

**Fixed 2026-08-17.** `tables.row_signature(table)` is the multiset —
a Counter, because two identical rows are two rows and a reorder that
dropped one is what this catches — with whitespace collapsed and the
shared glyph table folded, so a round trip through Word is not a
changed row. `tables.rows_preserved(before, after)` returns a
`RowsReport`: falsy when rows changed, `.lost` and `.gained` naming
the row tuples, `.format()` printing them. The header is excluded by
default (`skip_header=False` to include it), since a reorder does not
touch it and a retitled column is not a lost row.

The multi-table caption is `tables.tables_after(xml, caption,
count=N)`, which returns exactly N tables or raises. There is no rule
for where such a group ENDS that a document can be asked — a caption
is text and the next one may be a figure's — so the count is stated,
the same bargain as `table_spans(expect=)`. The layout-table trap is
answered by addressing tables through a caption at all.

Held by `tests/test_rows_preserved.py` (17 tests), including the
failure this exists for: a row that moved with one value left behind,
which every other layer reads as "rows moved".

### S1 `build_overrides` put a newly INSERTED paragraph wherever the author's last other edit was — and refused the edit outright when there was no other edit
<!-- status: fixed -->

Found by measuring `ingest.py` (2026-08-17): 35.1 % real survival, the
worst module in the package, with 33 of its 65 survivors on one line —
`overrides[-1] = (overrides[-1][0], overrides[-1][1] + extra)`.

An inserted paragraph has no baseline paragraph of its own, so it has to
ride on an override anchored somewhere. That line anchored it on
`overrides[-1]`, the last CHANGED paragraph, which is the paragraph
before it only when the author's previous edit happened to be adjacent.
Measured on a three-paragraph document:

    baseline  intro          / middle / conclusion
    author    intro edited   / middle / brand new / conclusion
    integrated intro edited  / brand new / middle / conclusion   <-- wrong

Two paragraphs early, silently, with `apply_overrides` reporting every
override applied. Fix a typo in the introduction and add a paragraph in
section 5 and the new paragraph lands in the introduction.

And when there was NO other edit, `overrides` was empty, so the same
branch fell through to `raise AnchorError("leading insert with no anchor
paragraph")` — for an insert in the MIDDLE of the document. An author
who adds a paragraph and changes nothing else, which is the most
ordinary round there is, got a refusal naming their new text as a
"leading insert".

**Fix.** Anchor a pure insert on the paragraph BEFORE it,
`base_paras[i1 - 1]`, as `(prev, prev + extra)`; keep the refusal only
for `i1 == 0`, where it is true. Seven tests in `test_ingest.py`
(`test_an_added_paragraph_lands_where_the_AUTHOR_put_it` and around it)
assert the integrated ORDER rather than the override list, which is what
was wrong.

**Known limit, now in the module docstring.** The anchor is a
paragraph's XML, so two byte-identical paragraphs are one anchor. Word's
own files are safe (every paragraph carries a `w14:paraId`), but a
baseline BUILT here need not be — `docxkit.body.para` emits no paraId,
so two identical "Notes:" lines under two tables are the same anchor and
an edit to the second is applied to the first. `compare --expect-clean`
sees it; nothing in `ingest` does.

**Checked against two real rounds.** AFI's `batch.docx` against
`batch_user_edited1.docx` (11 overrides) and `batch_user_edited2.docx`
(19): 0 missed either time, and applying them to the build reproduces
the author's file paragraph for paragraph — 1362 of 1362, no
differences. Those are the case the fix is about, since both hold edits
in several sections at once.

**Workaround while it was open:** none — it was not known. Any paper
that integrated an author round with an inserted paragraph should be
checked with `compare --expect-clean` against the author's file, which
does catch it.

### S2 `ingest` alignment broke at a run of blank paragraphs in any manuscript over 200 paragraphs
<!-- status: fixed -->

Same measurement. `SequenceMatcher(..., autojunk=False)` carried a live
mutant, and the setting is load-bearing: above 200 elements difflib calls
any line appearing in more than 1 % of the sequence "popular" and refuses
to match it. A paper's blank spacer paragraphs are exactly that.

With the paragraphs either side of a five-blank run rewritten, autojunk
sweeps all seven into one replace block: five overrides rewriting a blank
paragraph as itself, and the two real edits paired positionally inside a
block that has nothing to do with them. `autojunk=False` was already
there — what was missing was any test holding it, which is why this is
filed as a gap rather than a bug. `test_a_LONG_document_aligns_ACROSS_a_
run_of_blank_paragraphs` now does, at 250 paragraphs.

### S3 `revision doctor` reports 134 selections on AFI and about three of them matter — a paper with a build archive drowns the signal — patterns first, spent folders declarable
<!-- status: fixed -->

Run against AFI 2026-08-17, the day `doctor` shipped, on the very repo
whose defect motivated it. It is correct: every line really is a
selection of some document other than the declared one. It is also
unreadable, and an unreadable gate is one people stop running — the S3
shape this file reserves for gates that cannot usefully fail.

    134 other selection(s) — each picks a document that is NOT the declared one

The breakdown is the finding. Roughly 130 are **spent one-off builders
kept as history** — `v8_restructure/phase*.py`, `v9_literature/*.py`,
`build_v10`/`build_v11`, twenty `swap_*`/`integrate_*` figure surgeries,
and `Report/replication/code/**`, which are *frozen copies inside a
shipped package* naming `afi_v14_clean.docx` correctly, because the
package keeps that filename. Under the protocol's own forward-only rule a
spent script naming an old generation is not a defect; it is the record.

What deserved a reader's eye: the three `pattern` hits
(`tests/paper_doc_helpers.py`, `swap_figure8.py`,
`reproducibility/make_replication_package.py`) — and two are already
inert, one being a retired module behind an `exit 2` guard.

**Repro:** `docxkit revision doctor` in
`F:\OneDrive\__Documents\Aging_Update\Projects\AFI` (exit 2).

**Fix sketch.** The docstring already reasons about exclusions —
`build/` and the attic are skipped as legitimately holding older
manuscripts — so the concept exists and needs only to reach the cases
that matter:

* **rank `pattern` above `literal`, and say so in the summary.** The
  docstring argues a pattern is the dangerous kind; the output buries the
  three among 131 literals. Print patterns first, or alone by default
  with literals behind a flag;
* **let a project mark spent directories** — a `[doctor] skip` list in
  `paper.toml`, defaulting to `scripts/applied/` (already the protocol's
  word for "spent") plus any packaged-code tree. AFI would declare
  `v8_restructure`, `v9_literature`, `v10_build` and
  `Report/replication/code`;
* consider skipping files git says have not changed in N months — the
  archive is exactly the code nobody touches.

**No workaround written** — the AFI resolver fix and its guard stand on
their own, and `doctor` is not yet wired into any gate. Worth settling
before it is: a `[verify]` line that prints 134 lines of noise gets
switched off rather than fixed.

**Fixed 2026-08-17**, the same day, on the first two of the three
suggestions.

`doctor` now returns PATTERNS first and the CLI prints those in full while
COUNTING the literals, naming the remedy in the same breath: `--literals`
lists them, and `[doctor] skip` in `paper.toml` retires a folder. The
default skip is `scripts/applied`, since "applied" is already the
protocol's word for a batch that has been used. On the AFI run that
would have printed three pattern lines and one counting line instead of
134.

The third suggestion — skipping files git says are untouched for N
months — is DECLINED rather than deferred. It would make the report
depend on repository history, so the same tree answers differently after
a fresh clone or a reformat, and a gate whose findings move on their own
is the thing this file keeps reserving an S3 for. A declared skip list is
explicit, reviewable in the diff, and wrong in a way somebody can see.

### S4 `footnotes()` refuses a document with a spare note, and blames the renumbering for it — the message names the note now
<!-- status: fixed -->

Found 2026-08-17 by a test written on the assumption that it would not.

A note nobody references is only untidy — `footnote_audit` reports it
and carries on. But `footnotes()` renumbers the referenced notes to
1..n and then checks that the STORED ids equal the referenced ones,
which a spare note breaks:

    footnotes: renumbering did not settle — references [1, 2],
    notes [1, 2, 9]

Refusing is defensible: the spare note may already hold an id the
renumber wants, and two notes on one id is worse than a refusal. The
MESSAGE is not. It reads as a fault in the tool, names no remedy, and
does not mention note 9 — while the audit, one function away, says
"note 9 has no reference in the body" in as many words.

**Suggested fix.** When the settle check fails and the difference is
exactly `set(stored_after) - set(after)`, say so: name the spare notes
and point at `footnote_audit`. Keep the refusal.

**Workaround in use:** none. Pinned by
`test_an_UNREFERENCED_note_makes_the_whole_renumber_REFUSE`, which
holds the BEHAVIOUR so that a fix to the message cannot quietly become
a change to the answer.

**Fixed 2026-08-17.** The refusal is unchanged, which is the point: a
spare note may hold an id the renumber wants, and two notes on one id is
worse than refusing. What changed is that it says so —

    footnotes: note(s) [9] have no reference in the body, so
    renumbering the rest would leave them holding ids it needs —
    delete them, or add the references. `footnote_audit` lists them.

rather than "renumbering did not settle", which read as a fault in the
tool and never mentioned the note. The generic settle check stays behind
it for anything else that fails to converge.

### S4 `revision` raises six exception types and exports none of them, so `except` must import from a module the caller never called — `test_an_exception_a_module_RAISES_is_importable_from_it`
<!-- status: fixed -->

`docxkit.revision` raises `ProtocolError` in eight places — `find_config`
documents it as the failure mode when a tree has not migrated — but it is
absent from `revision.__all__`, so with `py.typed` in force
`from docxkit.revision import ProtocolError` draws
`reportPrivateImportUsage`. The accepted spelling is
`from docxkit.errors import ProtocolError`: a caller must import the
exception from a different module than the function whose contract raises
it, and must know `docxkit.errors` exists to guess it.

**Hit on AFI 2026-08-17** wrapping `load_paper` so a tree without
`revision/paper.toml` falls back instead of exploding.

**Same class as the `visible_text` entry below, which is Fixed** —
including `tests/test_api_surface.py`, which walks every module and
asserts each facade re-exports everything public behind it. It does not
catch this one: `ProtocolError` is *defined* in `docxkit.errors` and only
*raised* by `revision`, so no clause covers it. **The blind spot is
exception types** — the one part of a module's contract that lives in
another module by design.

**It is the whole module, not one name.** `revision` raises six types —
`ProtocolError` (8), `BaselinePending` (2), `DocumentLocked` (2),
`HandbackLoss` (2), `MathResolved` (1), `StaleBatch` (1) — and
`revision.__all__` carries none of them, although the documented refusal
codes (`BaselinePending` 3, `MathResolved` 2, `StaleBatch` 4) are exactly
what a caller is expected to branch on.

**Fix sketch.** Re-export from each module the exceptions it raises, and
extend `test_api_surface` with the clause that would
have caught it: every exception name appearing in a `raise` in module M is
importable from M. That closes the class rather than the instance, as the
`visible_text` fix did.

**Workaround in use** import from `docxkit.errors` and accept that the
`except` clause names a module the code otherwise never touches.

**Fixed 2026-08-17.** Every public module now exports the exceptions it
raises — 18 modules, 23 names — and the class is closed rather than the
instance: `test_api_surface` gained a clause walking every `raise` and
asserting the type is importable from the module that raises it. Verified
by removing `ProtocolError` from `revision.__all__` again and watching it
fail.

`from docxkit.revision import ProtocolError, BaselinePending` and
`from docxkit.edit import AnchorError` are the spelling now. One knock-on
the existing gate caught: `equations` declared `ConversionGap` while
importing it inside a function, beside an `lxml` import it had been
grouped with by habit — `errors` is the bottom layer and costs nothing to
import at module level.

### S3 nothing surveys a migrated repo for code that still selects the OLD manuscript — and the reference that breaks is the one that does NOT name the file — `revision doctor`
<!-- status: fixed -->

`revision init` scaffolds the layout and the manuscript takes its final
name, `working.docx`. Retiring the old name is left to the migrator, who
greps for it. **A grep cannot find the references that matter**, because
the dangerous ones do not contain the filename: they select the paper by
PATTERN, and a pattern that no longer matches falls back to whatever else
is on disk — an older generation of the same paper, sitting right there.

**Observed on AFI, 2026-08-17, nine days after its migration.** The
paper's pytest suite chose its subject by globbing the highest
`afi_vN.docx` across `Report/` and `revision/`. Renaming
`revision/afi_v14_clean.docx` → `revision/working.docx` made the glob
miss, so it selected `Report/afi_v11.docx` — three generations stale.
Eleven tests failed with messages describing the OLD paper (caption count
7≠9, 22≠25 references, Table 3/4/5 cell drift) and nothing naming the
rename. The migration commit had already repointed the three scripts that
DID name `afi_v14_clean.docx` literally; the resolver was missed precisely
because it never spelled the name.

Red was luck. v11 and v14 disagreed on those counts; had they agreed, the
suite would have stayed green while gating a manuscript untouched since
July. That is the S3 shape — a gate that is alive, passing, and aimed at
the wrong document.

**Third occurrence of one class.** `Parental_style`: 20 revision scripts
hard-coded to `ps5_r1.docx` while the live paper was `ps5_r2.docx`.
API/HPPA: every script defaulted to API10 with API11 live (they compared
identical, so nothing was lost *yet*). AFI: the glob above. Each was
caught by hand, by someone who happened to look.

**Repro**

    # in a migrated paper, before the fix
    python -c "import sys; sys.path.insert(0,'Programs/v3/tests'); \
               from paper_doc_helpers import PAPER_DOCX; print(PAPER_DOCX)"
    # -> ...\Report\afi_v11.docx        while paper.toml declares
    #    ...\revision\working.docx
    docxkit revision status              # TRUTH / TRUTH — sees nothing wrong

**Fix sketch.** A `revision doctor` (or a `validate` layer) that reports
who else in the repo thinks they know where the paper is:

* every `.docx` path literal under the project that is not the declared
  `working`/`prev` — the Parental_style and API/HPPA shape;
* every glob or regex over `*.docx` in project code that does NOT match
  the declared manuscript — the AFI shape, and the one no grep finds.
  A pattern that matches nothing, or matches only files outside
  `revision/`, is the signal;
* it must run on a tree that is otherwise green, since that is exactly
  the state it is meant to break.

Cheap first cut: resolve each candidate and compare against
`load_paper(root).working`, reporting any that disagree.

**Workaround in use** — `AFI/Programs/v3/tests/paper_doc_helpers.py` now
reads `[paper] working` via `load_paper`, keeping its version glob only as
a no-config fallback, and `AFI/Programs/v3/tests/test_paper_resolution.py`
asserts the resolution itself so the next rename fails by name rather than
as table drift (mutation-verified against the pre-fix resolver). Per-paper
workaround to delete when a repo-wide check exists — and note that the
guard is per-paper by nature, so each migrated paper currently owes its
own copy.

**Fixed 2026-08-17.** `revision.doctor` and `docxkit revision doctor`.
It reads only text, opens no document, and reports rather than refuses —
exiting 2 so a migration can gate on it. Both shapes are found: a stale
LITERAL (the Parental_style and API/HPPA case) and a PATTERN that no
longer matches the manuscript (the AFI case, and the one no grep for the
filename can find). The declared `working`/`prev` pair is accepted, and
`build/`, the attic and the config itself are skipped: all three
legitimately name a document that is not the live one.

`tests/test_revision_doctor.py` builds a migrated project and puts each
shape in it; `tests/test_cli_revision.py` holds the exit codes. The
report prints paths with forward slashes whatever the platform, because
a line copied into an issue should read the same on the machine that
reads it.

### S1 `insert_in_para` places content by a count that ignores the MATHS — the DSI defect, still live in the third copy of the walk — `b34cb12`
<!-- status: fixed -->

Found 2026-08-16 by asking whether the package was ready for a refactor,
and looking for duplication to justify the answer. The run-span walk
exists three times. Two copies count what sits BETWEEN the runs; the
third does not.

    where τxyz is time, in years.        (visible text, 29 characters)
    insert " measured" at offset 19

    got     'where τxyz is time, in  measuredyears.'
    wanted  'where τxyz is time, measured in years.'

Four characters late — exactly the width of the equation. Offsets index
`visible_text`, which counts everything a reader sees; the maths lives
in an `m:r` inside an `m:oMath` SIBLING of the runs, so a cursor
advanced across `w:r` alone is short by its glyph count and every offset
after it lands early. S1: the content goes in, nothing raises, and the
words are simply in the wrong place.

**The same defect was diagnosed and fixed TWICE already** — DSI §6.2 in
`wrap_visible_span`, where a citation link wrapped the closing full stop
instead of "(Foster et al. 2013a)", and DSI §6.3 in `_locate`, where it
wrapped «ему (Friedman» four characters early. Neither fix reached
`insert_in_para`, because nothing connected the three copies. The whole
2,700-test suite passed over it: no test inserted near an equation.

**Fixed in the same pass** by extracting `_xml.run_spans` and having all
three read it. `tests/test_insert_spans.py` states the property, and
removing the between-runs term from the shared walk now fails that test.

**What this says about the refactoring question.** The duplication was
not a tidiness complaint — it was a defect that had already been paid
for twice and was still being carried. The remaining shapes are
measured: `lo <= X.start() < hi` in 7 places across 3 modules, `¶{i +
1}` in 14 across 3, `stop <= at or start >= end` in 3. Each is a
candidate on the same evidence, and each should be checked for a copy
that missed a fix before being extracted.

**The span shape was done next, and the check came back NEGATIVE** —
eight sites (not seven; two more surfaced on a wider search), and every
one spelled the comparison the same way. No copy was missing a fix. It
was extracted anyway as `_xml.in_span` / `span_holding`, on a weaker and
different argument, measured after the fact:

| suite | kills `lo <=` -> `lo <` | kills `< hi` -> `<= hi` |
|---|---|---|
| edit | yes | yes |
| footnotes | no | yes |
| citations | no | no |

The extraction does not give `footnotes` and `citations` boundary tests
of their own — it makes it impossible for them to HAVE a boundary of
their own to get wrong. The least-tested callers are now guarded by the
best-tested one, which is not something a comment in each copy could
arrange. That is the honest case for this one, and it is worth less than
the `run_spans` case; recorded so the difference between the two is not
flattened later into "duplication was removed".

**The other two candidates were taken, and split.**

`stop <= at or start >= end` — three copies, all in `edit.py`, all
identical. Extracted as `_xml.overlaps` on the same weaker argument, and
worth it for one reason the copies did not state: a zero-width span
overlaps only when the position is STRICTLY inside, which is what makes
"the match abuts a note marker" a different answer from "the match
crosses it". Crossing one moves the marker to the end of the
replacement, silently — the LI7 regression the note guard exists for.
That property now has a test of its own rather than being implied by
three inequalities.

`¶{i + 1}` — 19 sites in 8 modules, and **NOT extracted**. The check
found no divergence, and more than that, no arithmetic worth sharing:
`crossrefs` and `equations` carry an already-1-based number, so their
missing `+ 1` is correct, and every site computes its own `i`, so a
shared formatter would move a display convention while leaving every
mutant exactly where it was. What the examination DID turn up is a
property nothing stated: an author reading "¶4" from `docxkit citations`
and "¶4" from `docxkit refstyle` must be sent to the same paragraph.
That holds only because every module enumerates with `PARA_RE`, which
skips a self-closing `<w:p/>` — and `tests/test_paragraph_numbering.py`
now says so, with an empty paragraph in the fixture to prove the skip is
uniform. A test, not a refactor, was the right output here.

**The eyeballed list ran out, so the next one was found by tool**
(2026-08-17): `pylint --enable=duplicate-code --min-similarity-lines=4`
over `src/`, which reported exactly one block — the entry-bookmark walk,
in `_cite_build._entry_names_from_document` and in
`citations.repair_plan`. `citations.py` ALREADY imports the former and
re-implements it anyway.

**And the obvious extraction would have introduced a defect.** The two
accumulate differently: a dict keyed by `r.key`, and a set of names. Two
entries under one key have two distinct names — `Kanbur2007` and
`Kanbur2007_2` — so the dict keeps only the second. Measured:

    dict (key -> name) : {'kanbur_2007': 'Kanbur2007_2'}
    set  (repair_plan) : ['Kanbur2007', 'Kanbur2007_2']
    lost by the dict   : ['Kanbur2007']

`repair_plan` reading that dict would find `Kanbur2007` unaccounted for
and propose it for DELETION as debris — the 2026-08-09 failure the
comment directly above that walk describes, a live reference proposed
for deletion. So the duplication was load-bearing in one direction and
not the other.

What is shared is the WALK, extracted as `_own_bookmarks` returning
PAIRS; each caller builds its own container. The near-miss is pinned by
`test_repair_plan_calls_BOTH_names_of_a_collided_entry_live`, which
fails against the naive version. And the gap arithmetic is now guarded
by BOTH suites rather than one — better than the `in_span` case, where
only the strongest suite saw it.

`duplicate-code` at that threshold now reports nothing across the
package.

**Then the same detector over `tests/`** (2026-08-17), and the criterion
there is not the same. Duplicated FIXTURES are usually right: a test
that builds its own document reads standalone, and sharing a constant
couples two tests so that changing one breaks the other. What is worth
removing is a duplicated HELPER, especially one that already exists.

    min-similarity-lines   before   after
    8                      1        0
    5                      2        0
    4                      4        2   (both fixture DATA, left)

Three findings, in descending order of what they cost:

1. **`tables` had no layering check at all.** `test_citations.py` and
   `test_compare.py` each carried a copy of the intra-family import-order
   walk — which `test_layering.py` does NOT cover, because it steps over
   any dependency starting with an underscore. Two of the three facade
   families were checked and the third was not, and a per-family copy is
   exactly how that happens: nobody wrote one for `tables`. Now one
   parametrized test over `FACADE_HALVES`, verified to bite for all
   three by reversing each declared order in turn.

   The copies had NOT drifted from each other — but `FACADE_HALVES`
   spelled `citations` in a different order from the one
   `test_citations.py` enforced, and nothing noticed because that dict
   was only ever read as a set. It is an order now, and says so.

2. **Two files defined `make_parts` shadowing conftest's, with a
   different contract**: `footnotes=` took the inner note elements in
   one and a whole part in the other. One name, two meanings, in a suite
   where every other file uses conftest's. Both now use the shared one.

3. Three cite test files hand-rolled a footnotes-part builder that
   `conftest.notes`/`note` already provided — all three written the same
   day, which is how that happens.

### S4 `_HEAD_RE` and `_REF_YEAR_RE` disagree about a space, and the entry silently loses its back-link — `0f12e2a`
<!-- status: fixed -->

Found 2026-08-16 while building a fixture for `rebuild`'s "no head"
path. Both regexes decide where a reference's year ends, and they
differ by one token:

    _REF_YEAR_RE = r"\(?\b(YEAR)\b\)?\s*[.,]"      # space allowed
    _HEAD_RE     = r"\s*(.*?\(?\b\d{4}[a-z]?\)?)[.,]"   # space NOT allowed

So "Kanbur, R. (2007) . Poverty and distribution. Journal." — a stray
space before the period, which hand-typed lists really do carry —
parses as a reference entry and then has no recognisable head:

    link_all: linked 1, back-links added 0, skipped 1
              SKIPPED: no head on entry ¶6

The in-text mention is linked; the entry gets NO back-link, so the pair
is half-built and the reader cannot get back from the reference to the
sentence. **S4 rather than S2 because it is reported** — the line names
the paragraph, and `crossrefs --audit` would find the missing partner.

**Fix.** Allow the same `\s*` in `_HEAD_RE`, outside the capturing
group so the head text stays clean:

    r"\s*(.*?\(?\b\d{4}[a-z]?\)?)\s*[.,]"

Better still, have one definition of "where a reference head ends" and
call it twice. Two regexes for one concept is what produced the
disagreement.

**Check when fixing:** `_HEAD_RE` matches any `\d{4}` where
`_REF_YEAR_RE` matches a plausible YEAR, so widening it also widens
what counts as a head on an entry beginning with a number — "1000 Days
Partnership. (2019)." is the shape to test.

**The fix has a consequence, and it is the reason this is filed rather
than done.** Once the two agree, "parsed as an entry but has no head"
becomes unreachable by construction: `_HEAD_RE` is the more permissive
of the two on every other axis (`\d{4}` against a constrained YEAR),
and `.*?` reaches any year on the line. The other candidate route was
checked and does not exist — a manual line break does NOT defeat the
match, because `visible_text` drops `<w:br/>` rather than emitting a
newline.

So the branch would become dead code, and the choice is between
deleting it — twice today dead code found this way was deleted, in
`label_extent` and in `_entry_keys` — and keeping it as a documented
defensive guard against a future edit to either regex. That decision
also costs the seven mutants
`tests/test_cite_rebuild_paths.py::test_an_entry_with_no_recognisable_HEAD_is_reported`
currently kills, which become permanent residue either way. Worth a
minute's thought rather than a reflex; the entry is here so the thought
happens once.

**Workaround in use:** none. `tests/test_cite_rebuild_paths.py` uses
this entry shape deliberately, to pin that the case is REPORTED; that
test will need its fixture changed when this is fixed, and it says so.

**Fixed 2026-08-16** (`0f12e2a`). By removing the second definition, not
by adding the missing token to it: `reference_head` sits beside
`parse_reference` and reads the year with the expression that decides the
paragraph IS an entry. Checked against fourteen entry shapes, including
the "1000 Days Partnership. (2019)." case flagged above; the new
definition agrees with the old on all but the one this was about.

The branch it makes unreachable is KEPT, and the decision recorded where
it will be read: `tests/test_cite_rebuild_paths.py` notes that its seven
mutants are permanent residue, so the next survivor report is not read as
a gap. A guard across a module boundary is not dead computation — the
two sides drifting apart is what this entry was.

### S1 a sentence in the back matter parses as a reference ENTRY, and a real citation then links to it — reported as "linked 1, unmatched 0" — `1f4f7e9`
<!-- status: fixed -->

Found 2026-08-16 while writing the `scan` tests, from a fixture that
would not link: a paragraph placed after the reference block had been
swallowed by the block.

    body:   "Employment rates come from the register (Eurostat 2023)."
            "References"
            "Kanbur, R. (2007). Poverty and distribution. Journal."
            "Data availability"
            "The data are drawn from Eurostat (2023)."

    link_all: linked 1, already linked 0, back-links added 1,
              unmatched 0, skipped 0
    written:  'Eurostat 2023' -> ThedataaredrawnfromEurostat2023
              'The data are drawn from Eurostat (2023)' -> ...txt

The citation resolves to the DATA-AVAILABILITY SENTENCE, and the reader
who clicks it lands there instead of on the entry. Nothing shows it: the
anchor resolves, so `crossrefs --audit` passes; the words read correctly,
so no text diff moves; and the report says it linked one and missed
none, which is the definition of S1.

**Diagnosis.** `references()` reads from the heading to the paragraph
that ENDS the list, and the stops are `Appendix`/`Appendices`/`Figures`/
`Tables`, the Russian pair, and a figure or table caption. The back
matter journals print after the references — "Data availability",
"Acknowledgements", "Funding", "Notes" — ends nothing, so its paragraphs
are offered to `parse_reference`, which accepts any of them carrying a
"(year)". The sentence above becomes an entry filed under the surname
"The data are drawn from Eurostat", and `_entry_keys` then licenses
every word RUN of that supposed institutional name, `eurostat_2023`
among them. That is the key the citation resolves through.

`_ends_the_list`'s own docstring records this failure once already — a
prose paragraph in an appendix parsing as an entry, "(Jensen 1906)",
minting a bookmark out of the surrounding equation glyphs. This is the
same defect through the one door that fix did not close.

**Measured on three back-matter sections**, one sentence each: "Data
availability" produces the junk entry; "Acknowledgements" ("We thank the
World Bank (2024) team for comments.") and "Funding" ("Supported by the
Research Council (2021) under grant 4.") do not — `parse_reference`
refuses those two shapes. So it is neither every paper nor a rarity: one
sentence shape in three. No live manuscript has been checked.

**Suggested fix, in two layers**, because the stop list alone is a patch
on the symptom:

1. add the back-matter headings to `_DEFAULT_STOPS`. Cheap, targeted,
   and no real entry is a heading;
2. bound the author field. A six-word surname containing "are", "drawn"
   and "from" is a sentence, and `parse_reference` accepting it is the
   root of both this and the appendix incident. The bound has to be
   lenient — "United Nations, Department of Economic and Social Affairs"
   is a real entry with two lowercase words — so it is a shape rule
   rather than a word count. Whatever the rule, an entry that only just
   clears it is worth REPORTING: `link_all` already has an `unmatched`
   channel, and "filed an entry under a six-word surname" is a line an
   author can act on.

**Workaround in use:** none. This came from a fixture, not from a paper,
and the fixture now carries the table caption that a real exhibit would
have — which is what ends the block properly.

**Fixed 2026-08-16** (`1f4f7e9`). Both layers, and neither gate that fired
was relaxed: `_DEFAULT_STOPS` gained the journal back matter with stops
matched as a word-boundary prefix, and `_reads_as_prose` reports the
case no bound can catch on a new `LinkAllReport.suspect` channel. The
measured document now reports `linked 0, unmatched 2` and writes no link.
`tests/test_reference_bounds.py` fails without it — including the two
Cyrillic institution names, which are why the prose test is Latin-script
only.

### S1 two reference entries with the same surname AND year get the SAME bookmark name, and every link to it lands on a coin flip — `36a569f`
<!-- status: fixed -->

Found 2026-08-16 while writing the tests the mutation entries asked for
— not by mutation testing itself, but by the case a test needed.

"Smith, J. (2020)" and "Smith, A. (2020)" are two people, and a
reference list carrying both is ordinary; so is one that has dropped its
2020a/2020b suffixes. `link_all` keyed its `names` map on the entry's
surname+year KEY, so the second entry's name overwrote the first, and
both entry paragraphs were then marked with it:

    bookmark names, in order: ['Smith2020_2txt', 'Smith2020_2', 'Smith2020_2']
    report: linked 1, already linked 0, back-links added 2, skipped 0

Two bookmarks of one name in one document. Word keeps whichever it finds
first, so the in-text link resolves to one of the two works at random —
and the report says it linked 1 and skipped nothing. Silent, and no gate
sees it: the anchor resolves, the words read correctly, `citations`
passes.

**Fixed.** `names` is keyed by the entry's PARAGRAPH, so every entry
gets its own name and `_dedup_name`'s suffix does what it was written to
do. And the citation itself is genuinely ambiguous — "(Smith 2020)"
names both works — so it is no longer linked to either: it is REPORTED
as unmatched, naming the count and suggesting the 'a'/'b' suffixes,
which is something an author can act on. Linking it to whichever entry
came second was the wrong kind of helpful.

Tests: `test_two_entries_with_the_SAME_surname_and_year_get_distinct_names`.
`link_all` grew from 28 to 29 by the added branch, recorded in
pyproject.toml and in `tests/test_complexity_debt.py` — which is what
made me notice the growth at all.

### S3 the hand-back loss gate calls an EDITED footnote a lost one, and then refuses the exemption for it — the two paths disagree and the gate cannot be passed — `17701a5`
<!-- status: fixed -->

The new `baseline` loss check (exit 5) is the fix for the S1 entry below, and
it is the right idea. But it identifies a footnote by its TEXT, so editing one
character inside a footnote reads as the old footnote having disappeared.

**Hit on LI7 2026-08-15, blocking.** Gate D4 split section 6 into two, so
footnote 13's cross-reference "throughout Sections 4–6" became "Sections 4–7" —
a one-character edit. The footnote is 489 characters before and after, and the
only diff is `'6'` → `'7'`. `baseline` refused:

    docxkit: working.docx lost 1 thing(s) since prev.docx …
      - footnote 'For interpretability, empirical LII and LBI values throughout Sections'

**And the escape hatch refuses it too**, which is what makes this S3 rather
than S2. All three documented forms were tried:

    --accept-loss "For interpretability, … throughout Sections"          -> "has NOT lost"
    --accept-loss "footnote:For interpretability, … throughout Sections" -> "has NOT lost"
    --accept-loss "<the full old sentence, verbatim>"                    -> "has NOT lost"

So the refusal path says the footnote WAS lost and the exemption path says it
was NOT, about the same string, in the same invocation pair. The two are
computing "lost" differently — the refusal appears to compare full note text
while the exemption resolves the argument against something else — and between
them there is no way through. A paper cannot baseline after editing any
footnote.

**Suggested shape.** Identify notes by `w:id` and by their REFERENCE in the
body, not by their text: a footnote whose reference still exists has not been
lost, however much its wording changed. Text is the right identity for a
*link label*, never for a note that authors edit. Failing that, at minimum
make the exemption resolve against exactly the string the refusal printed —
a hatch that will not accept the message's own words is not a hatch.

**Workaround in use** LI7 2026-08-15: verified the footnote by hand (489 chars
both sides, one digit changed), confirmed `qa_links.py` PASS on prev → working
with 29 anchors and none lost, then copied `working.docx` over
`build/prev.docx` to do what `baseline` does. Recorded in `revision/log.md`.

**Fixed.** Both halves, because the entry is right that they were two
different questions being asked of one word.

*What "lost" means for a note.* The check compared note TEXT as a
multiset, so a reworded note read as a vanished one. It now decides on
the REFERENCE: a note whose marker is still in the body has not been
lost, however much its wording changed. Text is the right identity for a
link LABEL — a label is markup — and the wrong one for a note, which is
prose an author edits. Counting rather than matching ids, because Word
renumbers ids on save; that is the same fact `renumber.footnotes` exists
for. The text is still used to SAY which note went, and when the count
and the text disagree the report says so ("2 more, unnamed — 19
footnotes before, 17 now") instead of naming the wrong ones.

*The hatch that would not take the message's own words.* The refusal
printed a 70-character truncation and the exemption then demanded an
exact match against the full string, so the reader was shown a token
that could not work. `--accept-loss` now matches by PREFIX in either
direction, and the refusal PRINTS the flag to pass:

      - footnote 'For interpretability, empirical LII and LBI values th…'
          --accept-loss 'footnote:For interpretability, empirical LII a…'

Tests that fail without it, in `test_revision.py`:
`test_an_EDITED_footnote_is_not_a_lost_one` (the LI7 note, one character
changed in 489, asserting `baseline` goes through),
`test_a_note_that_really_went_is_still_caught` (the fix must not switch
the gate off), `test_the_exemption_accepts_the_words_the_refusal_PRINTED`
(which parses the flag out of the refusal and feeds it straight back),
and `test_a_PREFIX_of_the_loss_identifies_it`.

**Worth saying plainly:** this shipped this afternoon and blocked a
paper within hours. The gate was tested against a link Word had eaten
and never against an author EDITING a footnote, which is the ordinary
case — the S1 it fixes was about Word destroying structure, and the
test set inherited that framing whole.

### S2 `body.table` builds a table in NO house style, so every paper re-derives the same six settings — and copying a neighbouring table propagates the wrong one — `edd0202`
<!-- status: fixed -->

`booktabs` sets the RULES beautifully and stops there. Everything else the
house style specifies — Arial Narrow 10 pt at run level *and* in each cell's
paragraph default so empty cells inherit it, `tblW 5000 pct` + autofit,
`cantSplit` on every row, `keepNext` on the caption, landscape for a wide one —
has no home in the toolkit. `body.table`'s default is `TableGrid`: a full box
grid, which is the exact opposite of the house three-line style.

**Hit on LI7 2026-08-15, and the failure mode is the interesting part.** A new
Appendix 5 table was built with `body.table`'s defaults and its caption's
properties cloned from the nearest existing table — **Table A3, one of that
paper's un-converted ones**. Table 1 and Table A2 are the two in house style;
A1 and A3 predate it. So "match the neighbouring table" propagated the wrong
generation, and matching a *caption* turned out not to match a *table* at all.
The author caught it by eye: *"Table A4 should be build accourding to the house
style and place in landscape, use Areal Narrow 10 font — why this has not
happened?"*

Two further defects rode in with it, neither visible to any text-layer gate:
the lead paragraph carried `rStyle=Hyperlink` (blue, underlined, linking
nowhere) because the caller's `props()` helper lifts the FIRST `w:rPr` in a
template paragraph and in that paragraph the first one belongs to a citation
link; and a blank trailing page, from a pre-existing empty paragraph with no
`pPr` inheriting 13 pt of default spacing.

**Suggested shape.** `tables.house(xml, table, *, font="Arial Narrow",
size=10, landscape=False)` — or a `style=` argument on `body.table` — applying
the run/paragraph fonts, width, `cantSplit` and caption `keepNext` in one call,
with `booktabs` composing onto it. The settings are not in dispute; they are
written down in the user's house-style note and reimplemented per paper.
Separately, a `props`-style helper that lifts a paragraph's PROSE properties
should skip runs inside hyperlinks — lifting a link's `rPr` as a prose template
is a trap with no signal.

**Workaround in use** LI7's `apply_r2b.py`: `CELL_RPR`/`HEAD_RPR`/`CELL_PPR`
literals, a local `cant_split()` that merges into an existing `w:trPr` rather
than adding a second (a second one is invalid — `lint` catches it), and an
explicit section-break paragraph for the landscape run.

**Fixed.** `tables.house(xml, table, *, font, size, caption=None)` sets
the whole thing in one call: the face on all four ``w:rFonts``
attributes and both size fields, at RUN level and in each cell's
PARAGRAPH default; ``tblW 5000 pct`` + autofit; ``cantSplit`` on every
row; and ``keepNext`` on the caption when one is named. `booktabs`
composes onto it — one sets the face and the width, the other the
rules, and neither touches the other's settings.

Three details the entry did not have to state and the implementation
does. `w:cs` and `w:eastAsia` are not decoration: a cell holding one
non-Latin character falls back to another face for exactly that
character, which reads as a stray glyph in one cell of an otherwise
uniform table. `cantSplit` MERGES into an existing ``w:trPr`` rather
than adding a second, because `body.table` already gives the header row
one for ``tblHeader`` and a second is invalid — `lint` catches it, which
is how the workaround learned. And the pass is IDEMPOTENT, which took
knowing that `own_properties` answers with the INNER text while its span
covers the whole element: comparing the two halves against each other
reported every run as changed on every run.

The second defect that rode in with it is fixed too:
`body.prose_props(para)` lifts a paragraph's ``pPr`` and the ``rPr`` of
its first PROSE run, skipping runs inside a ``w:hyperlink``, inside a
fldChar field, or carrying the ``Hyperlink`` style. The obvious version
lifts the first ``w:rPr`` in the paragraph, and a paragraph that opens
on a citation is ordinary — so the new paragraph renders blue and
underlined, linking nowhere, with every text-layer check passing. A
paragraph whose runs are ALL labels answers with an empty ``rPr``:
no properties is a template a caller can see through, a link's are not.

Tests: thirteen in `tests/test_tables_house.py` (including the
composition with `booktabs`, the second-`trPr` refusal, idempotence, and
the tracked-table refusal) and four in `test_body.py`.

**Workaround retired:** the `CELL_RPR`/`HEAD_RPR`/`CELL_PPR` literals
and local `cant_split()` in LI7's `apply_r2b.py` — an applied script, so
it stays as the record of that batch; the next paper calls `house`.

### S2 `link --write` names bookmarks in ITS convention, not the paper's, and cannot be told otherwise — `edd0202`
<!-- status: fixed -->

`docxkit link` builds citation↔entry links document-wide, and the names it
mints are its own: `UnitedNations2024`, `WorldHealthOrganization2024`,
`Schunemann2017_2`. LI7's convention — used by all 79 of its existing wired
pairs — is `<Surname><Year>` for the entry and `+txt` for the in-text anchor:
`Kanbur2007` / `Kanbur2007txt`. There is no `--convention`, no naming hook, and
no way to say "these six only".

**Hit on LI7 2026-08-15.** Six citations needed wiring: four new references on
one page, one in a footnote, one whose link the author's Word session had
emptied. The dry run offered `linked 7, back-links added 5, unmatched 5,
skipped 11` — more than asked for, under the wrong names, and with a `_2`
collision suffix. The same builder took this paper's audit from 26 findings to
56 once before, which is recorded in its own log. So all six were hand-wired
from the field-form pattern read off an existing pair.

**Suggested shape.** A `key=` callable (surname, year → name) so a paper can
state its convention once, and a `only=`/`--only` filter so a repair can be
scoped to named citations instead of the whole document. Both are small next to
the audit that already finds the work.

**Workaround in use** LI7's `apply_r2b.py`: `FWD`/`ANCHORED` XML templates
cloned from the `Kanbur2007` pair, applied to an explicit six-item list.

**Fixed.** `link_all(parts, naming=..., only=...)` and `docxkit link
--only`.

`naming` is ``(surname, year) -> bookmark name``, so a paper states its
convention once: LI7's ``Kanbur2007`` / ``Kanbur2007txt`` instead of
this module's minted form. An entry's OWN key-shaped bookmark still
wins over both — an existing anchor is never renamed — and a convention
name that COLLIDES, or that Word's 40-character cap would truncate on
save, falls back to the minted form and says so in the report. Both of
those are silent otherwise, and the truncation is the worse one: Word
applies it on SAVE without retargeting the links, so every anchor to
that name is orphaned.

`only` scopes the pass to named works — by key, surname or bookmark
name. The reference BLOCK is still read whole, and that is not an
oversight: its bounds are what tell an entry from a sentence, and
narrowing them would set the builder loose inside the reference list.
The test asserting exactly that is the one worth keeping.

Tests: six in `tests/test_link_convention.py`.

**Workaround retired:** the `FWD`/`ANCHORED` templates and the explicit
six-item list in LI7's `apply_r2b.py`.

### S4 `renumber` handles caption numbers but not footnote/endnote ids — `edd0202`
<!-- status: fixed -->

`renumber` remaps "Figure N"/"Table N" labels and their bookmarks. Footnote
`w:id`s are a different namespace with the same problem, and nothing addresses
them: restore or move a footnote and its id no longer follows reference order.

**Hit on LI7 2026-08-15.** A footnote the author had deleted was restored with
the next FREE id (19) while its reference sits fifteenth. Word does not care —
displayed numbers come from reference position — and every gate passed. But
`qa_acceptance` addresses footnotes by `w:id`, so two criteria began failing on
footnotes nobody had touched: the content was right and the index into it was
wrong. Diagnosing that cost more than the fix.

**Suggested shape.** `renumber.footnotes(parts)` — reorder `w:id`s to match
reference order across `document.xml` and `footnotes.xml` (two-pass through a
placeholder, since the old and new id spaces overlap), and sort the note
elements to match. Worth pairing with an `audit` that simply reports when ids
and reference order disagree; that is the check that would have caught it.

**Workaround in use** LI7's `revision/scripts/fix_footnote_ids.py`.

**Fixed.** `renumber.footnotes(parts)` renumbers footnote ids into
reference order and returns what moved; `renumber.footnote_audit(parts)`
is the cheap check that would have caught it, and
`renumber.footnote_order(parts)` gives the two orders side by side.

The remap goes through a PLACEHOLDER, which is the whole trick: a direct
substitution collides — 19 -> 15 while 15 -> 16 shares one id space —
and the second pass rewrites what the first had already moved. The note
ELEMENTS are sorted to match as well; Word does not require it, but a
note stored out of sequence is what made this hard to see. Word's own
separator and continuation notes (ids 0 and -1) are never renumbered and
stay at the head of the part. A reference to a note that does not exist
is REFUSED rather than renumbered onto something else.

The audit also reports a note nothing references and a reference with no
note, because those are the same question asked from the other side.

Tests: nine in `tests/test_footnote_ids.py`, including that the note
TEXT follows its id — the property the whole entry is about.

**Workaround retired:** LI7's `revision/scripts/fix_footnote_ids.py`
(already applied; `renumber.footnotes` is what the next paper calls).

### S1 `RUN_RE` reads a self-closing `<w:r/>` as an OPENING tag — the defect `PARA_RE` was fixed for, in the walk nine modules use — `865faa8`
<!-- status: fixed -->

Found by the structural review of 2026-08-15, not by a paper — which is
the point: it had been there since the pattern was written, and every
gate in the package was green over it.

`_xml.RUN_RE` was `<w:r\b[^>]*>.*?</w:r>`. `[^>]*` swallows the slash of
an EMPTY run, so the match opened at `<w:r/>` and closed at the NEXT
run's `</w:r>`, returning one match spanning two elements. Demonstrated
on a paragraph holding one empty run between two real ones:

    runs found by RUN_RE: 3          <- three real runs, and one empty
       run 1: '<w:r><w:t xml:space="preserve">The share rose to </w:t></w:r>'
       run 2: '<w:r/><w:r><w:t>0.15</w:t></w:r>'      <- two elements, one match
       run 3: '<w:r><w:t xml:space="preserve"> in 2024.</w:t></w:r>'

**Corpus scan, 899 manuscripts:** 28 carry a `<w:r/>`; 32 carry the
`<w:p/>` that `PARA_RE` was fixed for in `6acc545`.

**Why it survived, and why it is S1 anyway.** An empty run contributes
no visible text, so every OFFSET stayed correct and every text assertion
passed — `replace_in_para` on the paragraph above still produced exactly
the right words. What was wrong was run IDENTITY: the count, the
boundaries, and which `w:rPr` a walk believes belongs to a run, which
for a merged pair is the EMPTY one's. Fourteen call sites in nine
modules walk runs with this, including `_xml.editable_text`,
`edit._locate`, `renumber`, `footnotes`, `_cite_grammar`,
`_table_layout` and `_compare_read`, and the property-reading ones are
where it would have surfaced as a wrong answer rather than a silent one.

**Fixed.** `(?<!/)>` on `_xml.RUN_RE`, `_xml.RUN_OPEN_RE`,
`_compare_read.RUN_RE`, `_compare_read.MATH_RUN_RE` (`<m:r/>`),
`_compare_read.STRUCT_TAG_RE` (`<w:p/>`), `_table_core._TR_RE`
(`<w:tr/>`) and `crossrefs._P_OPEN_RE` — the last being the pre-fix
`PARA_RE` spelling, latent because its one caller is only ever handed a
caption paragraph, and fixed anyway because "latent" is a claim about
today's callers.

**And the class is closed.** `tests/test_regex_registry.py` walks every
module-level `re.compile` in the package (158 of them) and asserts that
none reads an empty container as an opening tag. It probes rather than
reads the source, so an alternation like
`<(/?)w:(tbl|tr|tc|p)\b[^>]*?>` is covered too, and it auto-exempts the
patterns that CAPTURE the slash — `_ELEMENT_OPEN_RE`, `_RPR_CHILD_RE`,
`revisions._OPEN_RE` — because those hand the answer to their caller.

The same review measured what does NOT matter: attribute-tolerance
divergence, where 22 elements are spelled several ways across the
package. **0 of 899 manuscripts** carry an attribute on `m:oMath`,
`w:rPr`, `w:tc`, `w:sz`, `w:pStyle` or `w:rStyle`, so consolidating
those spellings would buy nothing. Recorded so the next reader does not
re-derive it.

### S1 `replace_in_para` guards hyperlinks but NOT footnote references, and a match hops over one invisibly — `865faa8`
<!-- status: fixed -->

`labels_a_link` refuses a match that starts inside or spans a hyperlink, with
`allow_hyperlink` as the deliberate escape hatch — the entry above records what
that guard is worth. **A `w:footnoteReference` carries no visible text at all**,
so a visible-text match spans one without any signal, and the rebuild moves the
reference. There is no `spans_a_footnote` check and no flag to acknowledge one.

**Hit on LI7 2026-08-15.** The Figure-1 paragraph reads:

    ... from South Korea (UN 2024).  <<FN11>>   The left panel of Figure 1 ...

The obvious anchor for a sentence inserted after the opening — `"). The left
panel of "` — is contiguous in visible text and spans FN11. Word's Compare then
re-emitted **footnote 12**, which holds an OMML formula, as an insertion with no
matching deletion; reject-all stopped reproducing the baseline, so the author
could not refuse it.

Measured, three scratch redlines off the same baseline:

| build | result |
|---|---|
| that edit alone | reject-all FAILS, one footnote paragraph unrejectable |
| every other edit in the batch, without it | clean, 5 revisions |
| same edit anchored AFTER the reference | clean, **1** revision |

Note what each layer said: `lint` clean, `compare` 0 hyperlink diffs and
integrity clean, the caller's own assertion satisfied because the words really
are in that order. **`reject_check` is what refused it** — which is exactly the
argument for that gate, and also why this needs fixing upstream: the paper only
learned the anchor was wrong because a build failed, not because the edit was
refused where it was made.

**Suggested shape.** Mirror `labels_a_link` — refuse a match that spans a
`w:footnoteReference` / `w:endnoteReference` / `w:commentReference` unless
`allow_notes=True`, and say which note in the message. The scan already walks
the runs; this is a second predicate on the same walk. A hyperlink and a
footnote anchor fail the same way and deserve the same guard.

**Workaround in use** anchor on the run AFTER the reference and let the marker
stay where it is, asserting the footnote reference ids and their order in the
body are unchanged before and after the edit.

**Fixed.** `replace_in_para` refuses a match that CROSSES a
`w:footnoteReference`, `w:endnoteReference` or `w:commentReference`,
naming the note, with `allow_notes=True` as the deliberate escape.

The boundary cases are why it took a rule rather than a check. A marker
has ZERO visible width, so a match that merely ABUTS one does not touch
it and is not refused — anchoring beside a marker is the correct way to
edit that sentence, and a guard that forbade it would be switched off
within a week. A single touched run cannot move a marker either: the
text is rewritten where it stands and nothing after it is emptied. What
is refused is exactly "the marker is strictly inside the replaced span",
which is the shape that bit.

Tests: `test_replace_in_para_refuses_to_cross_a_NOTE_reference` (the LI7
Figure-1 paragraph), `test_the_guard_covers_endnotes_and_comments_too`,
`test_a_match_that_ABUTS_a_marker_is_not_refused`,
`test_a_match_after_the_marker_is_not_refused`,
`test_the_note_guard_has_its_own_opt_in`.

**Workaround to retire:** LI7 can anchor its R2a edits normally again.

### S1 nothing GATES a hand-back: `ingest` reports what the author's Word session destroyed, `validate` does not look, and `baseline` records it as truth — `865faa8`
<!-- status: fixed -->

The protocol's whole safety claim is that `working.docx` is the one file and
its state is readable. But between the author handing it back and
`revision baseline` writing it over `prev.docx`, **nothing fails on lost
content**. `ingest` sees it and prints it. `validate` checks lint, counts, the
accept/reject round-trip and the math — all of which are about the BATCH, and
there is no batch on a hand-back. `baseline` just copies.

So the failure mode is: the author edits normally, Word removes structure
silently, the operator reads a long `ingest` dump, and one line in it scrolls
past. Then `baseline` makes the loss the new truth and the previous state is
gone from the compare chain.

**Hit on LI7 2026-08-15, and it is worth being precise about who did what,
because the first diagnosis was wrong.** The manuscript came back missing three
`Figure 4` cross-references, a `European Commission 2024` citation, and
footnote 15 in full — note, reference, and the `Ritchie 2023b` link inside it.
It was reported as the *generated* file having lost them. Measured through the
chain, it had not:

| stage | body `w:hyperlink` | footnote `w:hyperlink` | footnotes |
|---|---|---|---|
| `prev` | 33 | 15 | 19 |
| the edited clean build | 33 | 15 | 19 |
| the Compare redline | 33 | 15 | 19 |
| after the author's session | **28** | **14** | **18** |

and accepting the redline preserved everything three ways — Word's
`AcceptAllRevisions`, the XML accept, and accept-then-**Save through Word**,
which is the path a human takes and which the first test had bypassed by
reading Flat OPC. Word had collapsed one paragraph into a single run to make
four copyedits, and every link and the footnote reference in it went at once.

**Word then renumbered.** 19 notes became 18 with the ids still contiguous, so
there is no gap to notice and no id to miss — the only way to see it is to
count. `ingest` DID count it, and said `stripped_fields: lost 1 footnote
ref(s)`, and that is the whole of the protection.

**Suggested shape.** `revision ingest --check`, exiting non-zero when the
hand-back lost a hyperlink (BOTH forms — this paper carries 33 element-form
and 130 field-form), a footnote or endnote, a bookmark, or a comment; and
`baseline` refusing while such a loss is unacknowledged, the way it already
refuses on pending revisions. An `--accept-loss ANCHOR,…` escape hatch keeps
the deliberate case honest — here one of the six was a *repair*, a link whose
label had bled across a whole sentence, and a gate with no way to say so is a
gate that gets switched off.

**Workaround in use** LI7's `revision/scripts/qa_links.py`: surveys both link
forms in `document.xml` and `footnotes.xml`, plus the footnote reference and
note counts, exits 1 on any loss, `--expect-lost` declares a deliberate one,
and a declared loss that did NOT happen is itself a failure so a stale
exemption cannot hide the next real one. Wired into `paper.toml` `[verify]`.
Control run `prev → batch` PASSES, which is what proved the redline clean.

**Fixed.** `revision.losses(working, prev)` names what an author's Word
session destroyed — links (both forms), footnotes, endnotes, bookmarks,
comments — and two gates consume it:

* `revision ingest --check` exits 5 (`HandbackLoss.exit_code`) when the
  hand-back lost something. Without the flag it still SAYS it and still
  exits 0: `ingest` is the command that is safe to run before every
  task, and that has to stay true;
* `revision.baseline` REFUSES while a loss is unacknowledged, because
  that is the step that makes it permanent — `prev.docx` is what the
  compare chain measures against afterwards. `accept_loss=(...)` /
  `--accept-loss` names the deliberate ones, by anchor, note text or
  `kind:what`. **`force` does not override it**: `force` is the flag
  reached for by reflex, and the acknowledgement costs one anchor.

Naming a loss that did NOT happen is itself refused, which is the rule
LI7's `qa_links.py` arrived at: a stale exemption is a switched-off gate
that reads as a switched-on one, and it would pass the next real loss in
silence.

Notes are matched on their TEXT, never their id — the entry's own
finding: Word renumbered 19 notes to 18 with the ids still contiguous,
so there is no gap to notice. `footnotes.find_all(kind="endnote")` was
added for the same reason a footnote-only check would have been a gate
that cannot fail for any paper using the other kind.

Tests: `test_ingest_names_a_link_the_authors_word_session_ATE`,
`test_a_lost_FOOTNOTE_is_found_by_text_not_by_id`,
`test_a_lost_ENDNOTE_is_found_too`,
`test_an_ordinary_author_edit_loses_NOTHING`,
`test_baseline_REFUSES_while_a_loss_is_unacknowledged`,
`test_force_does_not_override_the_loss_refusal`,
`test_a_deliberate_loss_can_be_NAMED_and_then_baselines`,
`test_a_DECLARED_loss_that_did_not_happen_is_itself_refused`,
`test_a_first_baseline_with_no_prev_is_not_blocked`, plus two in the CLI
suite for the exit codes.

**Workaround to retire:** LI7's `revision/scripts/qa_links.py`.

### S2 no public way to ask whether a MATH run is bold, so every guard written against `w:b` guards NOTHING — `865faa8`
<!-- status: fixed -->

A paper that renames one symbol and must not touch its bold twin has to
ask "is this `m:r` bold?" and there is no API for it. The obvious
implementation is wrong in a way that reports success.

**Hit on `Parental_style` 2026-08-13.** The theory's parenting time
`X_i` was renamed to `τ_i` to de-collide with the empirical covariate
vector **X**, and the protocol's guard read: *"Boldface (OMML bold /
`\mathbf`) identifies it. Zero bold-X instances may be edited."* Written
the natural way — `'<w:b/>' in run` — the enumeration returned:

    italic X: 32   bold X: 0

**All four covariate X's were counted as italic and would have been
swept into the rename**, silently corrupting equations (5)–(6) and the
endogeneity paragraph. They carry `<m:sty m:val="bi"/>`, not `<w:b/>`:
OMML states its own face through `m:sty` (`p`/`b`/`i`/`bi`), and a
`w:rPr` bold is a different, rarer spelling. Correct detection gives
`28 plain / 4 bold`, which then reconciles exactly with the protocol's
independently-derived count of 29.

The toolkit already knows this — `_compare_read.py:158` folds
`m:nor|m:sty|m:scr|w:i|w:b|…` when it fingerprints FORMULA TYPOGRAPHY,
which is why that layer reported clean throughout. The knowledge is
private, so every caller re-derives it and gets it wrong.

**Suggested shape.** `equations.face(run) -> {"plain","b","i","bi"}` (or
`is_bold`/`is_italic` predicates) reading `m:sty` first and `w:rPr`
second, exported and documented in the skill next to `to_latex`. Cheap;
the parsing exists.

**Workaround in use** `re.search(r'<m:sty m:val="b[i]?"/>', run)`,
asserted against a known-good count before and after the edit.

**Fixed.** `equations.face(run) -> "p" | "b" | "i" | "bi"`, plus
`is_bold` and `is_italic`, reading `m:sty` first and `w:rPr` second.

One thing the entry did not say and the API must: **the default is
ITALIC**, not plain. A maths run with no face markup renders
math-italic, because that is what a variable is — which is why a
manuscript full of italic symbols carries no markup for it.
`DEFAULT_FACE` is exported so the assumption is visible rather than
buried, and `is_bold` — the predicate the guard actually wanted — is
false for it either way.

Tests: `test_face_reads_m_sty_not_w_b`,
`test_an_unmarked_maths_run_renders_ITALIC`,
`test_is_bold_separates_the_two_X_populations`,
`test_the_rarer_w_rPr_spelling_is_read_second`,
`test_a_switched_OFF_w_b_is_not_bold`.

**Workaround to retire:** `Parental_style`'s regex against `m:sty`.

### S2 replacement is guarded against links, INSERTION is not offered at all — so callers hand-roll it and land inside one — `865faa8`
<!-- status: fixed -->

`replace_in_para` takes this class seriously: `labels_a_link` refuses a
match that starts inside a hyperlink *or* spans one, with
`allow_hyperlink` as a deliberate escape hatch and two S1 entries below
recording what happened when it was missing. There is no equivalent for
**inserting** text at a position inside a paragraph, because there is no
inline-insertion helper at all — `body` stops at whole paragraphs
(`insert_after`/`insert_before`), and `edit` has `set_run_text`,
`replace_in_para`, `rep`, and nothing that puts a run *between* runs.

So every caller writes the string surgery themselves, and the obvious
version is wrong twice over. Both failures hit `Parental_style` on
2026-08-13.

**1. Prepending to a paragraph whose first run is a link label.** The
Bhalotra–Clarke paragraph, moved into §6, opens directly on its
citation's field-form hyperlink, so its first `<w:t>` *is* the link
label. Fronting the paragraph with a connective sentence by prepending
there put the sentence inside the link. Measured label afterwards:

    'A further consideration concerns the twin instrument itself. Bhalotra and Clarke (2020)'

Blue and underlined across the whole sentence on the page. **Every
text-layer check passed** — `citations` ALL CHECKS PASSED, `crossrefs`
12/12, `lint` clean, and the caller's own acceptance grep
(`startswith(CONNECTIVE + "Bhalotra and Clarke (2020)")`) was satisfied
by construction, because the words really are in that order. Only
`compare`'s HYPERLINK layer sees it, as a `[grew]` label, and that layer
is explicitly REVIEW-not-gated. Cost: a promote undone and the batch
rebuilt.

**2. Finding the run boundary by hand.** The same day, splicing an
inline OMML τ into a prose run located the reopening tag with
`head.rfind("<w:r")` — which matches `<w:rPr` too. That spliced a
paragraph mid-properties and silently destroyed the `(B.2)` equation
label two screens away, surfacing as a bogus "equation label lost"
failure in an unrelated assertion.

**Suggested shape.** `edit.insert_in_para(para, at, xml_or_text)` —
offset in VISIBLE text, splits the containing run, and refuses when the
offset falls inside a hyperlink label or a bookmark span unless told
otherwise, mirroring `replace_in_para`'s contract exactly. `labels_a_link`
already exists and is private; this is mostly plumbing it to the
insertion case.

**Workaround in use** rebuild the whole run with `set_run_text` twice
around the inserted element, never splice; insert new runs *before* the
first `<w:r>` rather than into it; and assert the LABEL — the visible
text between `fldCharType="separate"` and `"end"` — rather than the
paragraph text, which cannot distinguish the two states.

**Hand-rolled TWICE MORE on LI7, 2026-08-15**, in `fix_r2a_links.py`
(`split_run`) and `apply_r2b.py` (`_wrap`) — near-identical functions in
one session, because there is still nothing to call. Between them they
re-derived, independently, two guards this entry already names: skip runs
already inside an element-form `w:hyperlink`, and skip runs already inside
a field-form HYPERLINK, or wrapping the second of three identical "Figure
4" labels nests a link inside a link. That is four copies of this hack
across two papers. A per-occurrence detail worth folding into the fix:
after the first wrap the target legitimately appears in more than one run,
so "exactly one run" stops being the right invariant — count the
OCCURRENCES up front and take the leftmost each pass.

**Fixed.** `edit.insert_in_para(para_xml, at, content)` — offset in
VISIBLE text, content spliced as XML when it starts with `<` and wrapped
in a run otherwise (escaped, `xml:space="preserve"` when it has edge
whitespace). Inside a run the run is REBUILT as two through
`set_run_text`, never spliced, which is the workaround's own recipe
promoted into the toolkit.

The placement rule is where the thinking went. **On the EDGE of a link
or a bookmark the content lands OUTSIDE it** — that is precisely the
Bhalotra-Clarke failure: at offset 0 of a paragraph that opens on a
link, "before the first run" is a position INSIDE the `w:hyperlink`, and
what the caller means is before the element. Strictly inside a label it
refuses, with `allow_hyperlink` / `allow_bookmark` as the escapes. A
fldChar FIELD is never split, flag or no flag: the halves would not be
two fields, they would be one broken one.

"Outside" is decided by what the element SHOWS: an edge is available
only when nothing the element displays lies on that side of the offset.
With text on both sides the caller really is splitting a label, and that
is the refusal.

Tests: `test_insert_at_the_front_of_a_LINK_LED_paragraph_stays_outside_it`
(the measured failure, asserting the LABEL did not grow),
`test_xml_content_goes_in_verbatim_and_splits_the_run`,
`test_inserting_INSIDE_a_label_is_refused`,
`test_a_bookmark_span_is_not_grown_by_an_insert_at_its_edge`,
`test_a_fldChar_FIELD_is_never_split`, and five more.

**Workaround to retire:** `Parental_style`'s hand-rolled splices.

### S2 `pages` returns a count and nothing else, so pagination defects ship — `865faa8`
<!-- status: fixed -->

`docxkit pages PAPER.docx` prints `52`. Everything a pagination question
actually needs is absent: which sheets are BLANK, what number each sheet
PRINTS, and each sheet's ORIENTATION.

**Two defects shipped in Parental_style because nothing surfaced them.**
Both were found by the author reading the PDF on 2026-08-12, not by any
gate:

* page numbering restarted at 1 after the References (`pgNumType
  w:start="1"` on the second section), and `titlePg` was set on all four
  sections with no first-page footer, so the opening sheet of every
  section printed nothing. Rendered: `… 28, -, -, 3, -, 5 …`;
* a blank landscape sheet between Tables 2 and 3, from two empty
  paragraphs that would not fit beside Table 2.

Both survived every gate in the toolkit. `lint` is clean on each, and
`compare` reports **zero real change locations** for either fix -- which
is correct, since neither moves a word, and is exactly why no text-layer
check can ever see them.

**The diagnostic lesson, worth encoding rather than relearning.**
Pagination cannot be inferred from the XML. Two plausible causes for the
blank page were derived from the markup and BOTH were falsified by
re-rendering: shrinking the `sectPr` host paragraph (still 53 pages), and
removing a redundant `<w:br w:type="page"/>` stacked on the section break
(still 53). Only dumping the block sequence between the two captions
found the real cause. Anything worth calling `pages` has to measure the
RENDER, not the source.

**Suggested shape.** `pages PAPER.docx [--check]`, one row per sheet:
index, orientation, printed number, `BLANK` flag. `--check` exits
non-zero on a blank sheet, a numbering restart, or a gap in the printed
sequence. The machinery exists already -- `pdf` exports through Word and
the repo parses PDFs elsewhere.

**Workaround in use** ~40 lines of PyMuPDF, hand-rolled THREE times in
one session on `Parental_style`: sampling the bottom 12 % of each page
for a digit, and reading `page.rect` for orientation.

**A FOURTH hand-roll, LI7 2026-08-15.** Appendix 5 went in landscape and
shipped a **blank trailing sheet**, invisible to `lint`, `compare`,
`citations` and the paper's own link gate — `docxkit pages` said `47` and
nothing else. Finding it took PyMuPDF again: `page.rect` per sheet for
orientation, `get_text()` length to spot the blank, and then
`get_drawings()` to measure that the table's bottom rule rendered at
y=519.6 against a margin at 540 — 20 pt left, and the trailing empty
paragraph needed 13. **The measurement was the whole diagnosis**: two
plausible causes were derived from the XML first and both were wrong.
Add `--rules` or expose the lowest drawn Y per page alongside the blank
flag; "how much room is left on this sheet" is the question every
table-placement defect actually asks.

**Fixed.** A new module, `docxkit.pages`, and `docxkit pages --sheets /
--check`: one row per sheet — index, orientation, printed number, BLANK
— with `--check` exiting 2 on a blank sheet, a numbering RESTART or a
GAP in the printed sequence.

The entry's diagnostic lesson is built into the shape. It measures the
RENDER, and the analysis is split so that only the first step needs Word
at all: `sheets(docx)` renders and reads, `read_pdf(pdf)` reads,
`problems(rows)` is pure. The tests BUILD their PDFs with PyMuPDF rather
than shipping fixtures, so the whole layer is testable on a machine with
no Word on it.

A sheet that prints NOTHING is reported and does not fail: a title page
legitimately carries no number, and a gate that fails on every paper is
a gate nobody runs. The RESTART and the GAP are what fail — which is
exactly what `… 28, -, -, 3, -, 5 …` is.

PyMuPDF is a new optional extra (`docxkit[pdf]`), imported lazily with a
message naming it, the same shape as `latex` and `pandas`.

Tests: eight in `tests/test_pages.py`.

**Workaround to retire:** `Parental_style`'s ~40 lines of PyMuPDF,
hand-rolled three times in one session.

### S4 `visible_text` is public API in practice but exported from no public module, so a typed caller must import a private one — `865faa8`
<!-- status: fixed -->

`visible_text` is the reader's text — the entry in Fixed below settles that it
lives in `_xml` and names the reading `para_slice`, `crossrefs`, `citations`
and `compare` all locate with. It is re-exported through `body` and `edit`, but
it is in neither `__all__`, so with `py.typed` in force Pyright rejects both
spellings and points the caller at `docxkit._xml` — a private module — as the
only accepted import.

**Hit in three scripts on LI7 2026-08-15** (`fix_r2a_links.py`, `apply_r2b.py`,
`qa_links.py`), each of which needs exactly this reading to assert that run
surgery left the paragraph's visible text byte-identical. `from docxkit.body import visible_text` and
`from docxkit.edit import visible_text` both draw
`reportPrivateImportUsage`; the suggested fix is to import the underscore
module, which is worse advice than the diagnostic it replaces.

**Suggested shape.** Add `visible_text` (and `editable_text`, which has the
same problem) to `__all__` wherever it is meant to be reached — most naturally
`docxkit.body` — or re-export both from the package root beside `read_parts`
and `write_docx`. Same class as the `RUN_RE`/`T_RUN_RE` `__all__` gap already
fixed below.

**Workaround in use** import from `docxkit.body` and live with the diagnostic;
ruff and mypy are both clean on it, so only Pyright complains.

**Fixed**, and much wider than the one name. Sixteen modules defined
public names they did not declare — including `revision.validate`, the
protocol's whole gate ladder, and `crossrefs.link_more`, which five
`Parental_style` scripts already call. All filled.

The class is closed rather than the instance: `tests/test_api_surface.py`
walks every module and asserts (a) every public function, class and
constant is in `__all__`, (b) every name in `__all__` actually exists,
and (c) each facade re-exports everything public behind it — which found
six more names `citations`, `tables` and `compare` were not passing
through. `compare.py` gained the `__all__` it never had.

Namespace-URI shorthands (`W`, `M`, `WP`, `MATH`) are the one exemption,
listed in the test with its reason: declaring them would bless four
copies of a constant that belongs in `_xml`.

### S1 `_resolve_math` accepts revisions that merely INTERSECT an equation, and takes hundreds of unrelated ones with them — `a03d9d1`
<!-- status: fixed -->

`tracked.build` calls `_resolve_math` unconditionally. With `classify=None`
that is `_accept_math_via_equations`, which walks `doc.OMaths` and accepts
**every revision in each equation's `Range`**. A revision does not have to BE
a math change to be in that range — it only has to overlap it — so one long
formatting or move revision that happens to span an equation is accepted
whole, along with every revision inside it.

**Measured on LI7 2026-08-15**, one Compare of the same pair saved three ways:

| route | package revisions | reject-all == submitted |
|---|---|---|
| A `SaveAs2`, math kept | 1870 | **319/319 PASS** |
| B Flat OPC, math kept | 1870 | **319/319 PASS** |
| C Flat OPC, math resolved (what `build` does) | 1555 | **FAIL — 35 units** |

Thirteen `Accept()` calls destroyed **315 revisions**, and the collateral
reached the abstract, which contains no equation at all: its rejected text
came back as "…in aging populations.  the theoretical foundation…", the words
"The paper presents" simply gone, unrejectable. A/B also settle the premise in
the docstring — *"Word cannot serialize a compare result containing tracked
math"* — for this manuscript at least: **both** SaveAs2 and Flat OPC serialized
1870 revisions with the math tracked, and both round-tripped exactly.

So the accept is not paying for a save that would otherwise fail; on this
paper it is pure loss, and the loss is the one thing a redline exists to
prevent. It is also invisible: `build` reports `math_resolved` as a count, the
deliverable opens cleanly, Word's own numbers look plausible, and nothing
fails until someone diffs a reject-all against the baseline.

Fixes, in the order they seem right:

1. `resolve_math: bool = True` on `tracked.build`, so a paper that has proved
   it does not need it can turn it off. Cheapest, and unblocks LI7.
2. Narrow the selection: accept only revisions CONTAINED in an equation range,
   not merely intersecting it. `_comment_and_accept_math_revisions` already
   selects by `rev.Range.OMaths.Count`, which is closer — the note at
   `_resolve_math` explains the two paths select differently and keeps both,
   but does not consider that the cheap one is also the destructive one.
3. Try the save first and resolve only on failure, which is what the premise
   actually justifies.
4. Whatever else: `build` should not report success when reject-all no longer
   reproduces the original. It has both documents; it could check.

Per-paper workaround to delete when fixed: LI7's
`revision/scripts/word_compare.py` assembles the same pipeline out of
`word.compare_documents` + `extract_flat_opc` + `lint_parts` + `verify` +
`guard` + `restore_parts` specifically to skip `_resolve_math`, and runs the
reject-all gate itself before publishing.

**Fixed.** Four changes, in the order this entry proposed them.

1. `resolve_math=False` on `tracked.build`, passed through
   `revision.build` and `docxkit revision build --keep-math`. Nothing is
   accepted on the paper's behalf. The comment scaffold an annotated
   build needs is still seeded — skipping the math pass skips the only
   place Word made one, and the build would otherwise fail far away with
   `ScaffoldMissing` and no hint of the flag that caused it.
2. The equation walk selects revisions CONTAINED in the equation's range
   (`Start`/`End` re-read per revision, because accepting shifts them),
   not revisions that touch it. One that merely runs through an equation
   is counted and reported as `math_kept`, never accepted.
   `_comment_and_accept_math_revisions` is deliberately NOT narrowed: its
   selection was verified revision by revision on AFI, and (4) now
   catches its collateral before anything is published.
3. "Try the save first, resolve only on failure" is NOT implemented —
   with (1) available and (4) gating, the cost of guessing wrong is a
   loud failure rather than a silent loss, and the retry needs a
   manuscript that actually refuses to serialize before it can be
   written against anything.
4. `untracked` — the reject-all comparison — moved out of `revision.py`
   into `tracked.py` and became a gate: `build` refuses to publish when
   rejecting every revision does not reproduce the original, and names
   the paragraphs. The check EXISTED; it lived one layer up, in a
   protocol LI7 does not use. `revision.build` keeps its
   report-and-let-gate-5-decide behaviour (`reject_check=False`) because
   one cause of a reject-all difference is legitimate and visible only
   from there: a moved footnote REFERENCE makes Compare emit the whole
   note as an insertion.

Found on the way: `revision.build` detected resolved math by GREPPING
`tracked.build`'s progress lines for "math revision" plus a number. It
reads `report.math_resolved` now. Rewording that sentence — which this
change does — would have disabled the protocol's math refusal in silence.

Tests that fail without it:
`test_a_revision_that_only_RUNS_THROUGH_an_equation_stays_tracked` (the
LI7 shape — one equation at 100–200, a revision inside it, and one
spanning 10–400 that must stay tracked),
`test_build_REFUSES_a_redline_that_cannot_be_REJECTED`,
`test_the_reject_gate_can_be_turned_off_and_still_SAYS_it`,
`test_a_faithful_redline_passes_the_reject_gate`,
`test_build_can_KEEP_the_math_tracked`,
`test_keeping_the_math_still_SEEDS_the_comment_scaffold`,
`test_keep_math_REACHES_the_build`. Suite 2150 green; ruff, mypy and
pyright clean.

**Still open, and the last step of this entry:** LI7's
`revision/scripts/word_compare.py` still assembles the pipeline by hand.
Reverting it to `tracked.build(..., resolve_math=False)` needs a Word run
against the manuscript, so it is not done here.

### S1 Compare REGENERATES `docProps/core.xml` empty, and `compare_collateral` calls that "not a loss" — `a03d9d1`
<!-- status: fixed -->

`tracked.build` carries `customXml/` back and then classifies the
`docProps/*` parts as regenerated rather than lost — correct at the part
level, and the docstring in `compare_collateral` says so explicitly. But
Word regenerates `core.xml` with only `lastModifiedBy`/`revision`/
`created`/`modified`. **Every property the document actually carried —
`dc:title`, `dc:creator`, `dc:subject`, `cp:keywords` — is gone, and the
build reports success.** The part-level check is what hides it: the part
is present, the same size class, and nothing in the report distinguishes
"Word rewrote this" from "Word emptied this".

**Hit on LI7 twice, unnoticed for four days.** `dc:title` = "Loneliness
Risk Index" was set deliberately on 2026-08-08 as its own batch, because
Word, Explorer and PDF export were all falling back on the filename. The
LANG promote (2026-08-11) emitted a `core.xml` with no `dc:title`; the
N5/M5 promote (2026-08-12) dropped `docProps/core.xml`, `app.xml` and
`custom.xml` out of the package entirely, and the author's accept-and-save
put two of the three back — still untitled. Nothing surfaced it: metadata
is not tracked-changeable, so there is no revision for an author to
reject, and no text/link/format layer of `compare` looks at `docProps`.
Found by diffing the part list by hand while resuming the paper.

`carry` is not the fix. `restore_parts` copies a whole part back, and
`core.xml`'s `modified`/`revision` legitimately belong to the redline,
not to the input — copying it wholesale would backdate the deliverable.
What is needed is a FIELD-level carry: take `dc:title`, `dc:creator`,
`dc:subject`, `cp:keywords`, `cp:category` from the revised input when
the regenerated part lacks them, leave the timestamps alone, and say so
in the report. Same argument as the customXml default: "three mechanical
edits and no judgment" belongs here, not in a paper's script directory.

Minimum acceptable fix if the carry is judged too clever: make
`compare_collateral` compare the CONTENT of a regenerated `core.xml`
against the input's and warn per lost property. A warning would have
caught this on 2026-08-11.

Per-paper workaround to delete when fixed: LI7's
`revision/scripts/qa_metadata.py` (asserts `dc:title` + the part list
against `prev.docx`, and is wired into its `paper.toml` `[verify]`) and
`revision/scripts/apply_title.py` (re-sets the title, and rebuilds the
part, its content-type override and its package relationship because it
has had to).

**Fixed.** `hygiene.carry_properties(parts, source)`, the field-level
carry this entry asked for, called by `tracked.build` between
`restore_parts` and `compare_collateral`. It copies `dc:title`,
`dc:subject`, `dc:creator`, `cp:keywords`, `dc:description` and
`cp:category` from the revised input wherever the regenerated part lacks
them, and never `cp:lastModifiedBy`, `cp:revision`, `dcterms:created` or
`dcterms:modified` — those belong to the file being written, which is why
this is field by field and not `restore_parts`. A value already present
is left alone: a rescue, not a sync. When Compare dropped the part
outright — Flat OPC always does — the part, its content-type Override and
a package relationship on a FREE rId are rebuilt, which is the whole of
LI7's `apply_title.py` minus the paper's own title string.

The "minimum acceptable fix" landed as well, for what a carry cannot
reach: `compare_collateral` compares the regenerated part's CONTENT and
says `property LOST: dc:title = 'Loneliness Risk Index'`. A save field is
not a document property, so `cp:revision` changing is not reported.

Tests that fail without it, in `test_parts_gaps.py`:
`test_carry_properties_puts_back_what_a_regenerated_core_xml_lost`,
`test_carry_properties_leaves_the_TIMESTAMPS_to_the_new_file`,
`test_carry_properties_rebuilds_the_part_word_dropped_entirely`,
`test_carry_properties_never_overwrites_a_value_that_is_there`,
`test_carry_properties_on_a_source_with_nothing_to_say_is_a_noop`,
`test_compare_collateral_reports_a_property_the_part_no_longer_carries`.

**Still open, and the last step of this entry:** LI7's `qa_metadata.py`
and `apply_title.py`. The title string is the paper's, so `qa_metadata`
keeps a job; `apply_title`'s part-rebuilding half is now redundant.

### S1 `Cascade` skips the DEFAULT paragraph style, so a paragraph that names none resolves through docDefaults instead — `a87f201`
<!-- status: fixed -->

`Cascade.resolve` walks direct → character style → paragraph style →
docDefaults, and `Cascade.paragraph_style` returns the style a `w:p`
**names**. A paragraph that names none does not thereby have no
paragraph style: it takes the one marked `w:default="1"`, which is
`Normal` in every manuscript here. The chain gets `pstyle=None`, skips
the style step entirely, and answers from docDefaults — a part that
usually says something DIFFERENT.

**Hit on `FLOPsExport` 2026-08-14, integrating an author handback.**
That paper's `Normal` says `w:sz 24` and its docDefaults says `22`. Word
renders both spellings of the paragraph at 12pt. `compare` reported:

    FORMAT  'Training market. '  ['italic', 'size 24'] -> ['italic', 'size 22']

on **22 run-in lead-ins**, on a pair where the author had changed the
size of nothing — Word had merely dropped a direct `w:sz 24` equal to
the value `Normal` already supplied, which is the round-trip this layer
exists to survive. Reproduction, two paragraphs that differ only in
whether they spell the style they are already in:

    names no style   pstyle=None      -> sz=22 (the document default)
    names Normal     pstyle='Normal'  -> sz=24 (the Normal style)

**S1 rather than S3 because the mirror case is silent.** The false
positive is loud and costs a reader's time; the reverse — a run that
STATED `sz 22` in a `Normal` paragraph and now inherits — resolves to 22
on both sides and reports **clean on a real 11pt→12pt change**. That is
the exact failure `_VALUED`'s comment says resolving was introduced to
prevent ("misses the mirror case (a run that stated 10pt and now
inherits the 12pt default)"): it was fixed for the direct-vs-docDefaults
pair and left open for the direct-vs-default-STYLE pair, which is the
common one, because a python-docx build names a style on almost nothing.

**Suggested shape.** `Cascade` reads the `w:default="1"` paragraph
style's id at construction (`_STYLE_ID_RE` already walks every style
body; the attribute is on the same element) and `resolve` falls back to
it when `pstyle` is None, BEFORE docDefaults. Also worth exposing as
`Cascade.default_paragraph_style`, since `_compare_read` is not the only
caller that passes a `paragraph_style(...)` that can be None.
`footnotes.sizes` takes the same route and will report the same way on
any manuscript whose footnote paragraphs name no style.

**Workaround in use** none — the FLOPs build stopped writing the
redundant `Pt(12)`, which removes the trigger for that paper (and is
right anyway, per the "Word drops a redundant pPr value" rule) but does
nothing about the missed-change direction.

**Fixed.** `Cascade` reads the `w:default="1"` paragraph style at
construction and `resolve` falls back to it when `pstyle` is None, before
docDefaults; exposed as `Cascade.default_paragraph_style`. A NAMED style
deliberately does not fall back — it inherits along its own `basedOn`
chain, which is Word's order.

Validated against **Word itself**, which is the only authority on what a
paragraph is in: 12 probes over 5 transition classes and 4 documents,
Word agreed with the new resolution **12/12 and with the old 0/12** —
including the two classes where the fix makes the size SMALLER (`24 -> 22`,
`28 -> 24`) and the one where nothing resolved at all before
(`None -> 24`). Corpus measurement over **1,562 manuscripts**: 772 have at
least one run whose resolved size changes, 1.43 M runs in total, dominated
by `22 -> 24` (docDefaults 11pt → Normal 12pt). `footnotes --check` over
1,272 footnote-bearing documents flips **no verdict** — 33 name a more
accurate size with the same pass/fail — so no paper's gate goes red. The
FLOPs pair that surfaced it now reports 0 FORMAT entries where it reported
22, with its 10 real text edits untouched.

### S1 `export_pdf`'s page range is DISCARDED — every "pages 1–3" render is the whole document — `9a9fdfc`
<!-- status: fixed -->

`docxkit pdf PAPER.docx OUT.pdf --pages 1-3` writes all 52 pages and
reports success. Measured on `Parental_style/revision/working.docx`
2026-08-13, three exports from one file:

    full          1,920,546 bytes   52 pages
    --pages 1-3   1,920,546 bytes   52 pages
    --pages 9     1,920,546 bytes   52 pages

Byte-identical. The CLI is innocent — `cmd_pdf` parses the range and
passes it through correctly. The defect is in `word.export_pdf`:

    doc.ExportAsFixedFormat(str(out_pdf), WD_EXPORT_PDF, False, 0, 0,
                            first, last)

`ExportAsFixedFormat(OutputFileName, ExportFormat, OpenAfterExport,
OptimizeFor, **Range**, From, To, …)`. The 5th positional is
`WdExportRange` and it is hardcoded **0 = `wdExportAllDocument`**, which
tells Word to export everything and ignore `From`/`To`. It has to be
**3 = `wdExportFromTo`** for the range to be honoured. `word.py` defines
only `WD_EXPORT_PDF = 17`; there is no `WD_EXPORT_FROM_TO` constant to
reach for, which is probably how the 0 got written.

**Why it is S1 and not S4.** Nothing fails. The file is written, the
byte count is printed, and the pages you asked for are all present —
along with the other 49. A referee excerpt, an editor's "just send me
the tables", or a figure-only render all ship the entire manuscript,
and the only way to notice is to open the PDF and count.

**Fix:** pass 3 as `Range`, name the constant, and test that a
`first=2, last=3` export has `page_count == 2`. Both the export and a
PDF page count already exist in the repo, so the test needs no new
machinery.

**Workaround in use** export the whole document and slice with the
`Read` tool's `pages` argument, or PyMuPDF.

**Fixed.** `WD_EXPORT_FROM_TO` / `WD_EXPORT_ALL_DOCUMENT` named, `Range`
set to the former rather than written as a bare integer at the call
site — which is likely how a `0` got there. The existing test asserted
the call SHAPE and never `args[4]`, so it passed with the bug; it now
asserts the constant and fails without the fix. Proven against real
Word on the 52-page manuscript: `--pages 1-3` → **3 pages, 143KB**,
`--pages 9` → **1 page**, against 52 pages and 1.9MB before.

### S4 `edit.RUN_RE` is not exported although `T_RUN_RE` is — `9a9fdfc`
<!-- status: fixed -->

`edit.__all__` lists `T_RUN_RE` but not `RUN_RE`, so
`from docxkit.edit import RUN_RE` — the way to walk whole `w:r`
elements, which is what run-aware surgery needs — is flagged
`reportPrivateImportUsage` by pyright while the sibling constant next to
it imports clean. `docxkit._xml` works but is private.

Hand-rolling the pattern instead is its own trap and cost real time on
`Parental_style` 2026-08-13: `head.rfind("<w:r")` also matches
`<w:rPr`, which spliced a paragraph mid-properties and silently
destroyed the `(B.2)` equation label two screens away. `RUN_RE`'s
`<w:r\b` is exactly the guard that prevents it.

**Fix:** add `RUN_RE` to `edit.__all__` beside `T_RUN_RE`.

**Fixed.** Added to `edit.__all__`; a test asserts both patterns are
exported and that `RUN_RE` matches `<w:r>` but not `<w:rPr>` — the
distinction the hand-rolled version got wrong.

### S1 `allow_hyperlink=True` lets the LINK SWALLOW the replacement — `e04b700`
<!-- status: fixed -->
**Pre-fix damage still in a submitted manuscript (found 2026-08-12).**
Parental_style's Table 5 caption back-link owns the whole phrase
"Table 5: The incidence of harsh parental coercive actions", where
Table 4's owns two words. Editing that prose afterwards required the
very opt-in that caused it. Repair is queued paper-side; noted here
because the entry's value is knowing where the damage landed.
Both halves, because the entry's own "why it is S1" was that nothing
catches it.

**The refusal.** `allow_hyperlink` answered one question and was
silently answering a second. It answers only its own now: a match may
TOUCH a link, and a match that starts in a label and ends OUTSIDE it is
refused — that is the write putting words into a label that were never
the link's. `grow_link_label=True` is the deliberate retitle. The
label's extent is the whole `w:hyperlink` element rather than the run,
because Word fragments a label as freely as it fragments prose and a
one-run reading passes the fragmented case straight through.

**The check went where the mechanism is, and only after the entry's own
suggestion was measured and failed.** "No link label may contain a
sentence-ending `:` or `.` followed by more words" fires **5,378 times
across 718 of 1,873 manuscripts on this machine**: many papers link the
WHOLE caption by convention, so the damaged label and the house style
are the same string. Restricting it to exhibit back-links and to labels
that disagree with their own document's majority — the `footnotes.sizes`
framing, which is the honest thing to try next — still left 936 in 332.
**The difference is not a property of one document**, and no static rule
can be. That is worth more than the check would have been.

So `compare.label_moves` pairs the label that LOST text with the one
that gained it: `[grew] 'Table 4' -> 'Table 4: The likelihood…'`, one
finding. That layer was already the only place the Parental Style
caption was visible — as two lines, a `built-only` and a `user-only`,
for the reader to correlate. Both directions, because a label that
SHRANK is the emptying case caught partway.

### S2 `crossrefs --audit` never checks that an anchor leads its mentions — `79d6163`, `8c6ffb8`
<!-- status: fixed -->
`misplaced_anchor`, beside `misnamed` — and both are PRINTED now. The
second was computed and never shown by the CLI at all, which is the same
class one notch quieter.

Two things the sketch did not know:

* **compare PARAGRAPHS, not offsets.** Whether the marker wraps its own
  link or sits inside it is a linker's choice that means nothing to a
  reader, and an offset comparison called **100 of those a finding** —
  every one of them "the first mention is in this same paragraph";
* a field is located at its INSTRUCTION rather than at its `begin`, so a
  bookmark that legitimately wraps the whole field cannot read as
  sitting after it. Both link forms count together, as the entry asked.

Measured over 1,873 manuscripts: **113 findings in 98 documents against
4,379 linked exhibits**, clustered on repeated versions of a few papers
— what a real defect looks like in an archive. Verified by hand on a
paper unrelated to the report: `Social protection Engel curve
05112022.docx` mentions and links Figure 2 at ¶54, and `Figure2txt` sits
at ¶60, a paragraph about Figure 3. Exits 1, as `dangling` does.

**Workaround to retire** the hand-rolled sweep in the Parental_style
session; it stays in that paper's `log.md` as the record of the round.

### S2 `validate`'s reject-all check is blind to HYPERLINKS — `91055cd`, `8c6ffb8`
<!-- status: fixed -->
`links` is the fourth thing gate 5 compares: a MULTISET of (anchor,
label) pairs over every text-bearing part, so a link that survives
somewhere else is not called lost and a swap cannot hide inside a total.
Both link forms are read together — Word rewrites a field into an
element on every author save, and a gate that told the two apart would
fail on a document nobody touched.

`validate` names the ones that went (`LINK LOST -> Table5`). "links:
False" beside three other booleans is the shape this protocol has
already been bitten by.

**Run against every real batch on this machine** — Parental_style (544
revisions), Loneliness Index (23) and DSI (0) — both new gates pass and
`lost_parts` is empty. A widened gate is only worth having if it stays
silent on work that is fine.

### S2 `revision build` silently DROPS every `customXml/` part — `c288968`, `91055cd`
<!-- status: fixed -->
Both suggestions, because they answer different halves.

**(1) The build CARRIES it across.** `hygiene.restore_parts` is the
mirror of `strip_parts`: the parts, the `[Content_Types].xml` Override,
and a Relationship on an id that is FREE in the target — the source's
`rId7` is somebody else's relationship in a rebuilt package, and Word
opens a duplicated id with a repair warning. `tracked.build` runs it
before lint and before the stamp, so nothing downstream ever sees a
package docxkit did not write; `carry=()` gets the raw Compare output.

**And the warning that stays is readable.** "part dropped" was printed
identically for `docProps/*`, which Word regenerates on save, and for
the data store, which nothing puts back.
`package.REGENERATED_BY_WORD` names the ignorable ones once; everything
else is `part LOST`, and those sort first.

**(2) `validate` compares the PART LIST.** `package.missing_parts`
against the baseline, and it fails the ladder: the reject-all gate
proves the text round-trips, and a part that is not there has no text
for it to read.

**Workaround to retire** the pre-promote check in
`Parental_style/revision/log.md`, and the inline restore that day's
batch carried.

### S4 `revision build`'s staleness refusal advertises a flag that does not exist — `91055cd`, `8c6ffb8`
<!-- status: fixed -->
The flag exists now: `revision.build(..., force=True)`, CLI `--force`,
passed down to the guard. Added rather than deleted from the message,
because `guard.check` takes the backup BEFORE it refuses — so the spent
batch survives either way, and the remedy the message named was the
right one all along, just unimplemented at both doors. The message names
the other two ways out as well, in the order they are usually right.

**The trigger retired itself.** That paper tripped this on every build
because it hand-restored `customXml/` after each one; the entry above
means it no longer has to.

### S4 `footnotes --check` calls the malformed majority "house" — `aea00f5`
<!-- status: fixed -->
The marks are grouped by HOW they resolve, and **the styled ones set the
house however few they are**. On Parental_style five footnote paragraphs
carried no `w:pStyle`, fell through `Normal` to a 12pt `docDefaults` and
took the majority with them, so the two the check flagged were the two
carrying `pStyle FootnoteText` — the well-formed ones. A count cannot
tell malformed from house; a resolution can.

With no styled mark anywhere the commonest value still stands, and
`mark_house_from` says which of the two answers was given, because they
deserve different confidence.

**Measured over 1,535 manuscripts with footnotes: 293 hold a mark
disagreement, and every one of them is now decided by a style.** The
document COUNT cannot move — outliers are non-empty exactly when the
resolved sizes differ, under either rule — so this changes no document's
verdict, only which side of it is named. API10 is the shape beside
Parental_style's: five marks state 11pt directly and four take 10pt from
`FootnoteText`, so the old rule made 11pt the house and flagged the four
that agree with the paper's own stylesheet.

`unstyled` names the footnotes whose paragraphs carry no `pStyle` — the
actionable fact the entry asked for, one attribute lookup — and the
report now tells the reader to give them the style rather than to write
a size onto the mark, which is the repair the old report pointed away
from.

`styles.Cascade.resolve` returns the KIND beside the value and the
phrase; `explain` is a thin wrapper over it. Grouping on the sentence
`explain` builds ("the FootnoteText style") would have been a parser for
our own wording.

**Workaround to retire**
`Parental_style/revision/scripts/applied/footnote_style.py` stays as the
record of its round, but its reasoning is upstream now.

### S4 two definitions of "what this paragraph says" — `35fd07b`
<!-- status: fixed -->
**Decision (2026-08-11, the author's): name both.** `visible_text` is
the reader's — `w:t` and `m:t` — and what `para_slice`, `crossrefs`,
`citations` and compare locate with. `editable_text` is what a run walk
can address, now a name in `_xml` rather than a join inlined in
`replace_in_para`. Over 399 manuscripts they differ on 256, and the
maths is the only thing they differ over.

Widening the editor was rejected on the grounds recorded when the entry
was opened: it would find phrases it could not write. Instead the
refusal explains itself — when the anchor is in the reader's text and
not in the run walk, `replace_in_para` names the equation.

`edit.py` had held both readings all along: `_locate` was fixed for
this in the DSI §6.3 round, with a comment that "two definitions of
visible in one call path is one too many", and `replace_in_para` beside
it still joined the runs alone.

### S2 `PARA_RE` read a self-closing `<w:p/>` as an open tag — `6acc545`
<!-- status: fixed -->
Found by the refactor that consolidated the duplicated element patterns
into `_xml`, and it was in the shared definition itself: `[^>]*`
swallows the slash of an EMPTY paragraph, so the walk ran on to the next
paragraph's close and the span a caller got back began at the blank line
BEFORE the one it asked for. Splicing that span deletes the author's
blank line; `probe` reported "(no table follows)" for a table sitting
right under its caption.

**816 paragraph spans in 233 of 399 manuscripts started too early.** No
oracle saw it — the merged block's TEXT is the text that was asked for,
so only the offsets moved. `_compare_read.P_RE` had the guard by
accident of spelling and was the only paragraph walk in the package that
was right.

Fixed with the `(?<!/)>` ghost guard already used for hyperlinks. An
empty paragraph is invisible to the walk rather than returned as its
own, which keeps every report's `¶N` numbering where it was.

### S4 `footnotes.sizes` skips the reference mark untested — `cf6c0f2`
<!-- status: fixed -->
The entry refused to widen anything without evidence and named the
evidence it wanted. Measured over 331 manuscripts with footnotes: **26
state a size on the mark, and in 22 of them exactly ONE mark RESOLVES
differently from the rest** — 10pt against 11pt in IGM, TCC and Parental
Style, several submitted. So "no document on this machine sizes it" was
false.

LI's is the shape that matters: every mark run is byte-identical, one
note's PARAGRAPH lost its `FootnoteText` style, and that mark alone
falls to the document default and is drawn a point larger — while its
body text states 20 like everyone else, so the existing check reports
the note as conforming.

The marks are now compared to EACH OTHER, which keeps the quiet the
exclusion was protecting: 291 of 331 documents say nothing, and the 40
that speak are versions of three papers with one finding apiece. A mark
whose size does not resolve is not judged, the way the body half already
declines. `--check` says which of the two it met, because they need
different repairs.

### S4 `citations.repair_plan` proposed deleting a live entry as debris — `fda1788`
<!-- status: fixed -->
The evidence it used could not work for that name: the bookmark was
minted by an older strip-only stem (accents dropped, not folded) while
"Bühler-Niederberger (2022)" keys as `bühlerniederberger_2022`, because
`\w` keeps the umlaut. The two spellings never meet, so a live work
reads as uncited however carefully it is cited.

The question now goes to the reference LIST, as the entry demanded —
`_own_bookmark` knows both stems and reads the hoisted gap — and a
finding on a live entry is re-classified as the lost citation LINK it
actually is. Both bookmark placements tested: reading the entry
paragraph alone brings the false debris call straight back.

### S4 a bookmark deletion cannot ship through Word Compare — `114b464`
<!-- status: fixed -->
`restored_bookmarks(baseline, clean, built)` names them and `build` says
so before the handback, with the remedy the three rounds arrived at.
Three sides, because the BASELINE is what makes the answer mean
something: "in the build, not in the clean edit" also describes a name
Word MINTED during the compare, and reporting that as the author's
deletion sends them looking for an edit they never made.

### S4 `build/batch.docx` is reserved but not guarded — `114b464`
<!-- status: fixed -->
It refuses at the call now, and names `build/clean.docx` as the place to
put a hand-built edit. The old failure came from the far end — the
provenance stamp reading the edit as a Word session that never happened.

### S4 `wrap_link_in_bookmark` has no "first mention" mode — `3d42a31`
<!-- status: fixed -->
`which="first"`. The rewrite also fixed a counting bug the entry did not
know about: the two link FORMS were counted separately, so a work linked
once as a field and once as an element passed the element branch as
unique — and Word rewrites a field into an element on every author save,
so a manuscript mid-round holds one of each. The bookmark would have
landed wherever form churn left it.

**Workarounds to retire** `repair_round3_links.py` and `_wrap_first` in
`repair_round5.py`; both stay as records of their rounds, but neither
technique is forced on the next paper.

### S2 `revision build` under-reports what Compare baked in untracked — `af355b7`
<!-- status: fixed -->
### S2 a moved footnote ANCHOR makes Compare emit the footnote as an unmatched insert — `af355b7`
<!-- status: fixed -->
### S4 `revision validate` says reject-all MISMATCH but not WHAT failed — `af355b7`
<!-- status: fixed -->
Three entries, one commit, because they are the same complaint from
different ends: the protocol knew a batch was unreviewable and would not
say what.

`untracked(parts, baseline)` returns the paragraphs where reject-all does
not reproduce the baseline — the computation gate 5 already performed and
threw away. `build` says it BEFORE the handback, `validate` after.
`moved_footnotes` names the second cause by itself: insertions, no
deletions, and text already at that id in the baseline (the last clause
is what keeps a genuinely NEW note off the list).

The MathResolved refusal no longer advises "author this batch by hand
instead", which named no supported call. It says what is true: the batch
has no reviewable redline.

**Two of the four footnote tests reached none of this** —
`moved_footnotes` only runs when gate 5 FAILS, and those fixtures
rejected cleanly, so both mutations lived. They test the function
directly now.

### S2 `citations.link_rest` is blind to entry bookmarks Word has HOISTED — `a2f28a2`
<!-- status: fixed -->
`link_all` already reads the body-level gap before each entry, for this
exact reason and with this exact comment. `_entry_names_from_document`
did not, so the two halves of one convention disagreed about where a
marker lives. The surname-AND-year test in `_own_bookmark` is what makes
the wider search safe.

Measured read-only on the three live manuscripts:

                          skipped        would link
    Parental_style        0 -> 0          0 -> 0
    Life_Expectancy       5 -> 3          3 -> 5
    Loneliness Index     44 -> 7          1 -> 38

**Thirty-seven later mentions on LI** the pass had been declining. What
still skips are entries whose bookmark is genuinely absent or filed
under a name the surname test cannot match ("Commission 2024", "UN
2019b") — a different question.

**Not done:** the entry's second suggestion, that `citations` report "N
later mentions unlinked". The audit deliberately treats a later mention
as fine — the house convention links first mentions only — so that
number would contradict the check beside it. `link_rest`'s own report is
where the count belongs, and it is there.

**Workaround to retire** `_link_citations` in `relink_mentions.py`; the
script stays as the record of the round.

### S2 `compare`'s FIELD layer reports targets that are present as lost — `122a180`
<!-- status: fixed -->
The entry guessed "pairs paragraphs by text"; the real mechanism is that
inside a replace run the pairing is POSITIONAL, so the inserted Heading2
made the block 4 against 5 and shifted every pair after it by one.

Three rules, measured over 748 real comparisons (every version pair on
this machine, and every document against itself):

    per pair                1,463 named lost, 594 still present  59.4%
    per BLOCK               1,764 named lost, 246 still present  86.1%
    + surviving, per part   1,540 named lost,  27 still present  98.2%
    + surviving, package    1,521 named lost,   8 still present  99.5%

It also names MORE true losses (869 → 1,513): a pair whose prose came
through glyph-identical never reached the old test at all. TEXT,
STRUCTURE and GLYPH are byte-identical across all 748.

The header no longer asserts a cause and a direction it cannot know.

### S1 `replace_in_para` empties a hyperlink's LABEL when the match spans it — `031e96d`
<!-- status: fixed -->
Both halves, because the entry's own "why it is S1" was that nothing
catches it.

**The refusal.** A run is somebody's label if it is hyperlink-STYLED or
if it sits inside a `<w:hyperlink>` element — the style is what a
field-form result run carries, the element is what an unstyled
element-form label has. Both forms fail the same way and both were
reproduced first. Same `allow_hyperlink` opt-in as the existing guard.

**The check.** `_xml.dead_links`, reported by the citation audit as
EMPTY LINK. It went there rather than into `lint` because the file is
not malformed — Word opens it happily — and `write_docx` must not start
refusing documents over it.

**It found live damage in submitted work.** 103 hits over 397
manuscripts, ~10 distinct defects repeated across archived versions:
LE ¶25's `Elder2013` is an empty field standing where the citation was
("confirmed by [ ]Ludwig and Zimper (2013)"), LE ¶40's `Table3` the same,
five of LI's footnote citations read as plain "(Catalano 2003)" followed
by a train of empty fields, and IGM ¶716's `Table4_text`. **Each of those
papers needs a repair round of its own** — recorded here because the
toolkit is what found them.

A link inside a tracked DELETION is excluded: it is not in the final
document. Four sit in LE le12, and reporting them would put every
redline on the list.

**Workaround to retire** `_link_labels` in `readability_pass.py` is no
longer needed as a guard — the refusal is upstream of it now — but the
script stays as the record of the round.

### S2 a possessive citation is left unlinked and reported UNLINKED — `a66259c`
<!-- status: fixed -->
The entry blamed the author-chain grammar and the grammar was innocent:
`find_citations` returns `"Doepke and Zilibotti's (2017)"` whole. Two
other things were wrong, one per layer, and both are wider than the
entry.

**The key carried the possessive.** The apostrophe is a NAME character
(D'Souza), so `key_for` stripped the punctuation without removing the
*s*: `beckers_1981`, which no entry answers to. A SINGLE-author
possessive could not be linked at all — the reported case worked only by
luck, its lead author being someone else. On a chain the suffix falls
outside `_NAME` and `"Doepke et al.'s (2019)"` was invisible to the
finder.

**The audit paired a mention to the links by its WORDING.** Resolving it
to its entry instead, over 397 real manuscripts: 36 changed, **41
findings removed, 0 added**. Thirty-eight are one shape nobody had
named — a label stopping a character short, `"Davletov et al. (2016"`,
because the closing parenthesis sits in a run outside the hyperlink.

The measurement also caught the fix overreaching: LE le12's finding is
real (the author retyped the sentence and dropped its link, while the
tracked DELETION beside it still carried the old one), so the evidence
must be visible in the FINAL document.

**Workaround** `repair_round5.py` stays as the record of a spent round;
the technique is no longer forced on the next paper.

### S3 `compare`'s FORMAT layer cannot see size or colour — `6920980`
<!-- status: fixed -->
FORMAT now carries `size` and `colour`, **resolved** through the new
`styles.Cascade` — direct run properties, then the character style
chain, then the paragraph style chain, then docDefaults — rather than
read off the run. The resolution is the whole design, not a refinement:
Word deletes a direct property equal to the inherited one, so comparing
what a run STATES reports a change on every author round-trip, which is
how a widened gate becomes a gate nobody reads.

Both directions are tested, and the pair that opened the entry now
enumerates correctly:

    footnote 5   size 24 -> colour 000000, size 20     the real fix
    footnote 6   size 20 -> colour 000000, size 20     colour only, and
                                                       right: it resolved
                                                       to 20 either way
    footnote 7   size 24 -> colour 000000, size 20     the real fix

Hyperlink runs still contribute no EMPHASIS — their underline is
structural — but their colour IS compared, resolved through the
Hyperlink style so the ordinary case is equal on both sides. That is
what makes footnote 5's eleven links in Word's default blue visible
where the house navy was meant.

**Measured before shipping, over three corpora: 136 documents compared
against THEMSELVES, 0 noisy.** The version-pair findings are all real —
a body size changed between two generations of one paper, citation links
gaining or losing a colour. With no `styles.xml` in the package the
layer compares emphasis only and says so in its docstring: silence
beats a guess, because a stated-value comparison there would report the
redundant-declaration case as a change.

**Second copy retired.** `footnotes.sizes` had grown its own resolver an
hour earlier; it now uses `Cascade`, which is also strictly wider — it
had known paragraph styles only, and a run's own character style carries
a size just as well.

### S3 `revisions.accept`/`reject` ignore every PROPERTY revision — `760b45b`
<!-- status: fixed -->
Both views passed a `*PrChange` straight through, so an XML-accepted
file still counted as a proposal and a rejected one kept the formatting
it was supposed to undo. What that cost: **gate 5, `reject-all ==
baseline`, could not fail on a formatting-only batch** — it compares
paragraph text and the glyph stream, and reject changed no formatting
anyway, so the gate that exists to prove the author's veto is real
passed vacuously on the Parental_style footnote round.

Accept drops the record; reject puts the snapshot back. Three things a
wholesale restore would have lost, each now carried across by hand and
named in the code: `pPrChange/pPr` is CT_PPrBase and cannot hold the
paragraph MARK's `w:rPr` — where that kind of revision's own flag lives;
`sectPrChange/sectPr` is CT_SectPrBase and drops every header and footer
reference, which CT_SectPr puts FIRST; a `w:trPr` carries the row's own
insert flag beside the formatting record. Property changes are applied
LAST for the same reason.

`test_revision_state.py` had a guard that `_has_revisions` and
`revision.state` agree on all seven kinds. It now has the third face of
it — anything `state` counts is something the simulator can APPLY —
which fails 8 ways without this fix.

### S3 a batch of 25 revisions is reported as "0 revisions" — `760b45b`
<!-- status: fixed -->
`revision build` printed `revisions: 0` and gate 3 `opened, 0 revision
groups` for a batch carrying 25 `w:rPrChange` in `word/footnotes.xml`,
because Word's `Document.Revisions` walks the MAIN STORY only. It reads
as "Compare could not represent this batch" — the documented
`MathResolved` failure — and half an hour went into proving the batch
was sound. `package_counts` gained a `revisions` key over every kind and
every text-bearing part, `BuildReport.revisions` is read off the built
PACKAGE with Word's count kept beside it as `body_revisions`, and both
messages now say "in the body" where that is what they mean.

### S2 `footnotes.sizes` flags a note whose STYLE supplies the size — `760b45b`
<!-- status: fixed -->
`sizes` takes `styles_xml` and resolves a run that states nothing
through its paragraph's `pStyle` chain (`basedOn` followed, cycles
survived), then the document default. On the manuscript that produced
the check:

    blind to styles   3 disagreeing — footnotes 5, 6 and 7
    with the styles   2 disagreeing — "resolves to 12pt through the
                                       document default"

Footnote 6 carries `pStyle FootnoteText`, that style says `w:sz 20`, and
it had always rendered at 10pt: a false positive on the first real paper
the check was pointed at, which the 134-document sweep could not surface
because no other paper mixes the two. Word agreed independently — its
Compare DROPPED the redundant explicit size written onto that run and
kept only the colour, the same "Word deletes a declaration equal to the
inherited value" behaviour `table_spacing` already records.

Without the part the disagreement is still reported: the answer
genuinely is not in `footnotes.xml`, and silence would be a claim this
cannot support.

### S4 `revision status` printed every stale part on one line — `760b45b`
<!-- status: fixed -->
Sixteen names, twelve of them `word/fonts/font*.odttf` from one tick of
Word's embed-fonts box. Folded by directory —
`word/fonts/ (12 parts)` — and capped at four entries with "and N more".
The test written for the cap caught a bug in the fold: a part at the
package ROOT has no directory, and folding it under `""` dropped
`[Content_Types].xml` off the line entirely.

### S2 no check that footnotes share one size — `a07f8fd`
<!-- status: fixed -->
`footnotes.sizes(xml) -> SizeReport`, plus `docxkit footnotes PAPER.docx
[--check]`. It went to `footnotes` rather than `hygiene` as the entry
suggested, because `footnotes.fonts` was already asking the neighbouring
question and `set_font` is already the repair — a footnote check in
`hygiene` would have split the seam.

Reported as a DISAGREEMENT, not as a wrong value, which is what the
entry's symptom demands: the offender states nothing, so no search for a
wrong number can find it. The house size is what most footnotes state,
so a document whose footnotes all inherit — every size in styles.xml,
perfectly ordinary — reports nothing. Ids 0 and -1 are skipped by
`find_all` already. Runs with no visible text are not asked: the
`w:footnoteRef` run is formatted by the FootnoteReference style and
states no size on purpose, and counting it would put every conforming
document on the list.

**Swept over real manuscripts, which is the only way to know a check
like this does not cry wolf: 134 clean, 0 flagged** across Life
Expectancy, DSI and FLOPsExport.

**And it found a LIVE one the workaround missed.** Parental_style
`revision/working.docx` still has three footnotes (5, 6, 7) whose text
runs carry no `w:sz`. *(Corrected the same day: TWO of them — 5 and 7 —
actually rendered wrong. Footnote 6 takes 10pt from `pStyle
FootnoteText`, which is the style-resolution entry above.)* `fix_display_math.py` skipped them because it
tested `'<w:sz w:val=' in blob` and the PARAGRAPH MARK's `w:rPr` carries
one — the mark's own formatting, not the runs'. Worth a batch on that
paper: `footnotes.set_font(xml, size=10)`.

### S2 no display-mode support, and Word's auto-promotion is unreliable — `eee8274`
<!-- status: fixed -->
`equations.display(para, jc="center")` wraps the paragraph's maths in an
`m:oMathPara`, idempotently; `equations.inline_display(xml)` is the audit
half and `docxkit math` now prints "N display equation(s), M still in
INLINE mode" with the equation named, gated by `--check`.

Both halves of the gotcha were put through Word rather than trusted, by
round-tripping a built document through Flat OPC — the package Word
hands back is what Word would have saved:

| written | after Word |
|---|---|
| bare `m:oMath` | **promoted** — and with no `oMathParaPr`, so not centred either |
| `display()` | kept, centring and all |
| `display(absorb=True)` | kept |
| `display()` + a trailing run | **demoted back to inline** |

So the auto-promotion is real, unreliable *and* not enough (it does not
centre), and the trailing-run demotion reproduces exactly. `display`
therefore drops empty runs, REFUSES a run carrying text — naming it —
and offers `absorb=True` to move it inside the maths instead, which is
how a numbered appendix equation is built. Text BEFORE the equation is
refused even under `absorb`: moving it after the maths is a reordering
no text diff would show.

### S2 `latex_to_omml` output needs a normalization pass — `ab891bd`
<!-- status: fixed -->
New `equations._normalize`, run on every conversion. Each before/after
was RENDERED through Word, which is the only gate that sees any of this.

* **the accent** — `\overline{v}` → `m:chr` U+2015 HORIZONTAL BAR, and
  the render confirmed it: the v is struck through. Now U+0305
  COMBINING OVERLINE, which draws as Word's own `m:bar` does. An
  `m:groupChr`'s character is left alone — a bar is legitimate there.
* **the sign** — worse than reported, and not confined to
  `\frac{(-)}{(-)}`: latex2mathml reads the minus in **`(-1)`** as the
  fence's SEPARATOR, so it arrives as an empty `m:e` plus `1` with the
  sign in `m:sepChr`, and the page reads `(   −1)`. Same for `[-1]`,
  `|-1|`, `\{-1\}`, `(-)`. Now rejoined into one `m:e` with the sign
  inline; delimiters survive. **The tell is the empty element, not the
  separator**: `(x,y)` and `(a-b)` arrive in the same shape with both
  elements filled, where the separator is real and drawn — firing on
  the separator alone would flatten them.
* **the NBSP** — did not reproduce as written. On latex2mathml 3.81.0
  `\quad` emits nothing at all (the spacing is dropped), and `\{x\}`
  builds a proper `m:d`, not a literal brace. The NBSP that does reach
  the math comes from `\text{ if }` and `~`, where the space is CONTENT
  and the converter is right to keep it. So the fix went where the harm
  was: `document_symbols` no longer harvests the NBSP or the invisible
  operators into the paper's vocabulary. `to_latex` still knows them —
  it has to render them — but a space is not evidence of math, which is
  what turned one finding into nineteen. Braces left alone: a bare
  brace in a paper's math is a fair thing to flag.

**Workarounds:** `theory_merge.py` and `fix_a3_signs.py` stay in
`scripts/applied/` — spent scripts are records of a round, not code to
delete — but neither technique is forced on the next paper.
**Bonus:** `word.export_pdf` resolves its destination. Handed a relative
path it wrote the render into WORD's working directory and returned a
path with no file at it. Found by using it for the render above.

### S3 gate 6 counts a drawing as a text difference — `712e2fd`
<!-- status: fixed -->
Measured before encoding, as the entry demanded — a synthetic package
whose only content was a picture and two letters, so the character at
the drawing's offset could not be a neighbour's. Word's `Range.Text`:

| form | what Word returns |
|---|---|
| `w:drawing` + `wp:inline` | one `/` (U+002F, ord 47) |
| `w:drawing` + `wp:anchor` (floating) | **nothing** — not in the stream |
| `w:pict`, `w:object` (legacy inline) | U+0001, already stripped by `_norm` |
| a text box's prose | absent — a different STORY |

So `_glyph` emits `/` for an inline drawing only, and grew a
`main_story=True` mode that prunes `w:txbxContent` for the gate that
compares against Word (the XML-to-XML gate still wants that prose). The
text-box half was NOT in the original report — the same probe found it,
and it would have kept gate 6 permanently red on any paper with a text
box. Still not a `_FOLD` entry: folding `/` away would blind the gate to
every "and/or" and every URL.
**Bonus:** gate 5 (reject-all == baseline) now notices a figure a batch
dropped. Neither paragraph text nor the old glyph stream changed when a
drawing vanished.
**Verified on the paper that reported it:** Parental_style
`working.docx`, zero revisions — gate 6 `False` before, `True` after.

### S3 `revision status` says TRUTH/TRUTH when prev and working differ — `a897948`
<!-- status: fixed -->
New `revision.drift(working, prev)` compares MEANING part by part
(`package.part_fingerprint`, save-noise excluded) and returns the parts
that differ; `status` asks it only of a settled file — while a proposal
is pending the two are *supposed* to differ — and exits **4** with the
part named and the remedy printed. Exit 0 now means both settled AND
built on a current baseline, which is what a script checking it was
already assuming. Verified failing without the fix: the stale case
exited 0.
**Bonus:** `ruff` and `mypy` were both red at HEAD on
`tests/test_pathological.py` (a long line and an untyped wrapper from
`1c09490`). Fixed here — two of the four gates being red is the same
S3 class as the entry above.

### S1 `crossrefs.unlink`/`link` blind to field-form hyperlinks — `1c09490`
<!-- status: fixed -->
`unlink` removed the bookmarks, left every HYPERLINK field standing and
returned "24 removed". Now raises `ConversionGap` naming the anchors and
saying what to do instead; `link` reports them as `field_form` rather
than stacking a second scheme on the caption. New public helper
`crossrefs.field_targets(xml)`.
**Workaround to retire:** the symmetric identifier swap in
`Parental_style/revision/scripts/applied/swap_tables_1_2.py` stays as a
record of the round, but the technique is no longer forced — a future
paper gets a clear refusal instead of a wrong answer.
**Bonus:** the pathological harness now treats a deliberate refusal as a
SAFE mutator outcome (nothing written ⇒ parseable, text-preserving and
idempotent all hold). Only an uncontrolled exception is a failure.

### S3 `_norm` did not fold U+2032 `′` against U+0027 `'` — `00db587`
<!-- status: fixed -->
Gate 6 (XML accept == Word accept) could not pass on a paper that writes
derivatives; proved on a ZERO-revision file. Folded, with a test verified
to fail without the fix. What remains of that entry is the drawing
placeholder, still open above.

### S3 cover letter printed "ALL CHECKS PASSED: /" — repkit, `c3391ab`
<!-- status: fixed -->
Recorded here because it is the same class: `refresh` re-writes the
letter without re-running the suite, so it passes no check count, and the
template interpolated it anyway. Fixed with a fallback and a regression
test verified to fail against the old template. (Lives in repkit; listed
once here as the worked example of the format.)

### S1 — `citations` refused on a Word lock under a printed snapshot banner — FIXED 29.08, `95024d9`
<!-- status: fixed -->

Two reads: `cmd_citations` took the snapshot through `_package`, printed
the banner, and then handed `check_citations` the PATH, which read it
again and refused. `check_citations(parts=...)` takes the package the
caller already holds; the CLI passes it.

**`probe` had the identical defect**, and was found by the test written
for this one — same shape, same fix (`probe(parts=...)`). The entry's
"worth checking" list is now answered: `count`, `tasks` (read mode),
`smarten` (dry run) and `compare` were all refusing and now fall back —
`compare` mattered most, since diffing the file the author has open IS
the author round, and `compare.load` opened the zip itself; `figures`,
`fit` and `sites` were already falling back; `pages`, `locate`, `pdf`
and `verify` drive Word over the live file and refuse by design.

**The banner is printed LAST now.** It promises a result, so a read that
fails must not carry it — `_package` validated the package AFTER
printing it, so "not a Word document" arrived under the same banner.

**The gate could not fail, in two independent ways**, which is the part
worth keeping. `main` exits with `sys.exit(f"docxkit: {exc}")`, and
`pytest.raises(SystemExit)` catches that before anything is written, so
the refusal reached neither stdout nor stderr and
`assert "Close it and retry" not in capsys.readouterr().out` was
vacuous. And `held_by_word` patched `is_locked` alone, leaving a DIRECT
`read_parts` of the live path succeeding — so the second read this
defect is made of worked in the suite and raised on the author's
machine. The fixture now makes opening the live path raise
`PermissionError`, which is what Windows does and what `readable`'s copy
survives, and the test asserts a REPORT follows the banner: the banner
and nothing else is what "did not run" looks like.

**Tests:** `test_cli_guards.py` — fifteen read-only commands
parametrized under a real lock, the banner-order refusal, and `compare`
against a held side. Verified red before the fix.

### S1 — a binary operator inside `\left( … \right)` became the delimiter's `m:sepChr`, and NO layer could see it — FIXED 29.08, `95024d9`
<!-- status: fixed -->

**Filed as an S2 and escalated on the measurement the entry asked for.**
It named the condition itself: *"The FORMULA layer compares tokens and
structure and may well catch it; that was NOT measured here and should
be, because if it does not, this is an S1 and not an S2."* Measured on
2026-08-29 — `(a+b)` against `(a−b)`, two documents, one character
apart:

    formula          (none)      tokens 'ab' both sides, skeleton 'd' both
    text / glyph     (none)      no character moved in any m:t
    every layer      (none)      --expect-clean GREEN

A sign flip in a revision passed every gate the toolkit has.

Both halves fixed. `_rejoin_at_separator` now fires on the SEPARATOR
rather than on an empty element, so the character lands in an `m:t`
where a text pass can read it; and `equations.tokens` reads an
`m:sepChr` in a document this converter did NOT build — which is every
manuscript built before today — placing it where it is DRAWN. That
needs a parse: `m:sepChr` sits in `m:dPr` ahead of every argument, so
scraping the attribute reads `+ab`, and the arguments cannot be counted
by matching `<m:e>` because a subscript inside one has `m:e` of its own.
It is gated on the substring, so a document without one pays nothing.
`_compare_read._omml` held a SECOND copy of the token join and went on
reading the runs alone; it now calls the shared one.

**The narrow rule was checked against Word before being widened**, since
the old docstring's reason for it was a claim about the page: rendered,
`(x, y)` is identical in both spellings, while a binary operator as
`m:sepChr` is set TIGHT — `(a+b)`, punctuation spacing — and gets the
medium space it is owed only once it is a run. So rejoining is the
better page as well as the readable markup, and one rule beats an
operator-versus-separator list nobody could maintain. An empty
`m:sepChr` is still left alone.

**Tests:** `test_equations.py` (the rejoin, an empty separator left
alone, `tokens` on an unrepaired document, and a separator read past a
nested `m:e`) and `test_compare.py::test_a_SIGN_FLIP_inside_a_fence_is_a_finding`
— the end-to-end gate. The test that asserted the OPPOSITE rule was
replaced, with the render measurement in its docstring.

### S2 — `reorder_rows` refused on a table with a row-level tracked deletion — FIXED 29.08, `95024d9`
<!-- status: fixed -->

The guard from `0dc84d4` compared the raw `<w:tr>` count against the
count in the table's VIEW, which diverge for exactly one reason — a
row-level revision — and told the caller to re-read, which reproduces
the identical refusal. It was a behavioural regression on the documented
core workflow (one country order across Tables 1, 3, 4, 5, A3 and A4,
over a Word Compare redline, which is where row-level deletions live).

**Paired, not refused**, as the entry proposed: `revisions.rows_in_view`
answers per row whether it is in a view — the transform only ever DROPS
rows, so that is the whole mapping — and the permutation runs over the
slots holding a visible row past the header. A row the view hides keeps
its slot; `header` now counts the rows the CALLER can see, which is the
only reading that survives a deleted row above the header. The remaining
refusal is the row walk and the transform disagreeing about what a row
is, and it says that is a docxkit bug rather than sending the caller
round the loop again.

A RAW multiset check sits beside the view-level one, marked defensive:
`rows_preserved` reads the view, where a hidden row is not there to be
counted, so a row dropped by the slot loop would pass it as "a correct
sort of the visible rows".

**The missing fixture is the reusable half.** The suite was green at
5274 with the regression present, because the three tests added beside
the guard used cell-level `w:ins`, where the row counts stay equal — the
guard's only reachable branch had no fixture. `conftest.row` now takes
`revision="del"`/`"ins"`, and four tests use it: the sort that used to
refuse, where the hidden rows end up, the mirror case (an inserted row
read as `original`), and the refusal that is left.

### S4 — `smarten --write` dropped its backup beside the manuscript — FIXED 29.08, `95024d9`
<!-- status: fixed -->

`working_pre_smarten1.docx` landed in `revision/`, whose first rule is
ONE file — a second .docx there is one keystroke from being the one the
author opens next.

Option 2 from the entry, because it fixes the command as it was actually
typed: `cli._prior_generations` resolves `paper.toml` the way `revision
status` finds its own paths, and returns `build/rescue/` for the file
that config NAMES as working — a build artifact or an export under the
same project keeps its backup beside itself, and a paper not on the
protocol is unchanged. `package.backup` grew `into=`, creating the
folder if needed.

**One fix rather than four**, as the entry suspected: `link --write`,
`crossrefs --write`, `authors --set --write`, `refstyle --fix`,
`tasks --done` and `smarten --write` all write through `_write_back`.
The "previous version kept at ..." line is now relative to the
manuscript, because a bare name reads as "beside your file" wherever it
actually went.

**Workaround to retire:** the hand `move` of `working_pre_smarten1.docx`
into `build/rescue/` on Aging_Well.
