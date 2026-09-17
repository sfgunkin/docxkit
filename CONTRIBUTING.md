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

Ten gates, all of which must pass:

```
python tools/gates.py   # all ten, in order, first failure stops
```

Two of them can SKIP rather than pass: `sweep` needs a corpus of real
manuscripts, so on a machine without `DOCXKIT_CORPUS` it prints `skip`
and the reason; `api` needs a baseline to compare the public surface
against, and skips when the repo has neither a tag nor an upstream.
That is a third state on purpose — see the sweep below.

or, one at a time:

```
python -m pytest        # synthetic fixtures, no Word required
python -m ruff check .
python -m mypy
python -m pyright       # what Pylance shows in the editor
python tools/optional_audit.py --callers tests   # can this `| None` ever BE None?
python tools/coverage_floor.py
python tools/api_check.py          # did this break the API the papers call?
python -m deptry src               # does the SHIPPED package declare what it imports?
python tools/sweep.py              # needs DOCXKIT_CORPUS; skips without
python tools/verify_committed.py   # HEAD, not the working copy
```

**Use the runner, or chain them with `&&`.** Never `;`, and never a
pipe: the status of `pytest -q | tail -2` is TAIL's, so a red suite
reads as a pass — that put a failing test into master on 2026-08-20,
having already happened once as `pyright | tail -1`. And `mypy`'s exit
code is not usable here, because it is non-zero for a run whose only
output is notes; the gate is "no line matching `: error`", which is what
the runner applies.

Install what they need with `pip install -e .[dev]` — hypothesis is in
there because the property suite imports it at module level, so a clone
without it does not lose those tests quietly, it fails at collection.

**What CI installs is `.[dev,pdf,latex]`, and the difference is a gate.**
pymupdf is not Windows-only and `tests/test_pages.py` builds its PDFs
with pymupdf itself, so those 15 tests run anywhere — and `pages.py`'s
85 % floor assumes they did. latex2mathml joined it on 2026-09-03 for
the same reason: `test_equations_typography.py` calls `latex_to_omml`
in 22 tests, and from the day it landed (08-24) until then every CI run
was red on a checkout that did not have the extra — twelve in a row,
unread. The `word` extra stays out, which makes its import ABSENT
rather than untyped on a clean checkout: that needs an entry in the mypy
override list AND a `pyright: ignore` on the import line, and a test
that needs an optional extra says so with `pytest.importorskip` —
latex2mathml taught this in August, pymupdf repeated it three days
later, and the typography file repeated it for ten days.

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
export DOCXKIT_CORPUS=<project-root>[;<project-root>...]
python tools/sweep.py            # or pass the roots as arguments
```

The sweep runs every read-only routine over real manuscripts. The unit
suite passed while `tables.read_all` was failing on the papers' own
tracked deliverables; the sweep found that, plus a byte-order mark and
nested tables, in one pass over 347 documents. It is read-only and
copies each file to TEMP, so it cannot touch a manuscript.

**It is a gate now** (2026-08-30), sixth in `tools/gates.py`. Until then
this section said "run it after any change to the reading routines" and
nothing anywhere ran it — not the chain, not CI, not a hook. That is the
state the curated mutations were in until 2026-08-27, and it is the same
lesson: a tool whose only binding is a sentence in a document is a tool
that runs when somebody remembers, which is not a gate.

CI cannot run it — a runner has no manuscripts and a checkout cannot
carry any — so the local chain is the only place it can live. Without
`DOCXKIT_CORPUS` it exits 3 and the chain prints `skip sweep` with the
reason. That third state is the point: `ok` over zero documents and `ok`
over 347 are the same line, and this is the gate where the difference is
everything. `DOCXKIT_CORPUS_LIMIT=N` bounds it for a machine where the
corpus is on a sync-on-demand drive; the sample is STRIDED across the
corpus, because a bounded sweep that reads the same alphabetical corner
every time can never find anything it has not already found.

For anything Word-backed, the real check is `docxkit verify` — does Word
read the file back as written, or repair it on open?

### Can this `| None` ever BE None?

```
python tools/optional_audit.py --callers tests   # the gate, expects 0
python tools/optional_audit.py                   # src alone, to read
```

An Optional the constructor cannot produce is a claim about the code
that is not true, and every reader of it grows an `is not None` branch
nothing can take. `PromoteReport.redline` was `Path | None = None` beside
a `promote` that either raised or returned the redline it had made, so
`cmd_revision_promote` tested it for None forever; the second of that
shape turned up in the same file the same afternoon (2026-08-24). Neither
type checker sees it — it is not a type error — and mutation testing
cannot either, because a branch no input reaches has no mutant that dies.

It fails only on an Optional something READS as optional, so a field
added today, before the test that exercises it, is not a toll: it is
listed as "nothing has been misled yet" and the gate stays green. The
suite counts as a caller (`--callers tests`) because a default no shipped
code omits but one test does is a live branch.

The src-only run is the review tool and is NOT gated: it stands at 2 —
`Table.source` and `Table.body`, which are None on a hand-built Table, a
documented contract for callers outside this package — and a gate on it
would need an allowlist of exactly those two.

Read its docstring before adding a rule. Nine of the first ten candidates
it produced were the tool's ignorance rather than the code's — lxml's
`getnext()`, an Optional `@property` read as an attribute, `cls(...)` in
a classmethod, a tuple unpacked or indexed out of a call, a loop variable
drawn from a `list[int | None]` — and `tests/test_optional_audit.py`
keeps one fixture per rule so the next one added cannot quietly lose one.

### Mutation testing

Coverage says a line RAN. Mutation testing says a test would NOTICE if
that line changed, which is the question worth asking. It is the largest
body of method in this repository and it now lives in its own file:

**[`docs/mutation-testing.md`](docs/mutation-testing.md)** — the tools
(`mutate.py`, `mutation_session.py`, `mutation_survivors.py`,
`kill_check.py`, `stale_figures.py`), the eight measured sweeps, the
calibration table, and the 32 lessons that came out of them: what an
equivalent mutant is and how to argue one, why a figure is void when the
harness moves, and the instrument defects that made whole rounds
incomparable.

Split out on 2026-08-30. It was 1,942 of CONTRIBUTING's 2,341 lines
— 84 % of a file people are asked to read before their first change —
and the eleven things a contributor actually needs were behind it.

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
machine revises through: ONE manuscript — the author's own file, under
its own name, wherever they keep it — whose state is readable from the
file itself: 0 revisions is the truth, more than 0 is a proposal
awaiting the author's verdict.

**It is a subpackage** since 2026-08-30 — `revision/`, fourteen private
halves behind `revision/__init__.py`, where it was one 3,118-line
module. The import path is unchanged (`from docxkit import revision`,
`docxkit.revision.validate`) and so is every name, private helpers
included: the facade re-exports all 93.

Two things to know before editing it. The halves are ordered, bottom
first, in `SUBPACKAGE_HALVES` in `tests/test_layering.py`, and a half
may import only what is below it — that order is the reason the split
is worth anything, and it is not readable from `__init__.py` because
ruff's isort sorts that block alphabetically. And the module aliases at
the top of the facade (`tracked`, `package`, `_word`, `_lint`, …) are
the suite's fake seam: `monkeypatch.setattr(revision.tracked, "build",
…)` mutates a shared module object and works from anywhere, but
`monkeypatch.setattr(revision, "_word", fake)` rebinds a name and must
name the half that reads it — `revision._validate`.

It used to impose the name `revision/working.docx` on every project,
and that cost the thing it was meant to buy. With nine papers on the
protocol, Explorer, the Word title bar and the taskbar all said
`working.docx`, and the author could not tell which paper was open
(2026-08-23). `init` adopts the file in place now and writes its path
into `paper.toml`; `revision/` is machinery, and the manuscript does
not live in it.

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

`tracked.py` followed on 2026-09-11, by the same recipe and with one
difference worth knowing: the Word pipeline — `build`, `verify`, the
math pass — STAYED in the facade, and only the XML gates
(`_tracked_gates`) and the report with its refusals (`_tracked_report`)
moved out. The suite fakes Word by rebinding `tracked._word`,
`tracked.verify`, `tracked.package_counts` and the rest on the facade
module, and `build` reads every one of those names from its own module's
globals at call time; a split that moved `build` into a half would have
moved that seam with it, test by test. One seam did move — `BuildReport`
reads the clock from `_tracked_report.time` — and one test names it.

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
