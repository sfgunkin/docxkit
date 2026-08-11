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
cosmic-ray init cr.toml run.sqlite      # module-path = ONE source file
cosmic-ray exec cr.toml run.sqlite      # test-command = the narrow suite
python tools/mutation_survivors.py run.sqlite src/docxkit/styles.py
```

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

**A suite that is too narrow INVENTS survivors, and that costs more than
one that is too broad.** `comments.py` came back as the worst module in
this table — 31 survivors in `remove`, seven loops that could each be
emptied — and `remove` is tested exhaustively in `test_parts_gaps.py`,
which was not in the run. `_table_layout`'s `drop_blank_rows` had 77 for
the same reason (`test_tables_blank_rows.py`). The three "real survivor"
numbers above are therefore upper bounds, not findings.

The cure is not a wider run: it is to let the sweep PROPOSE and the full
suite DISPOSE. Apply each candidate by hand and run everything; green
means a real gap, red names the test that already covers it. Over 48
candidates that filtered 17 artifacts out of 31 real gaps — and it is
the same "apply the mutation and watch it go red" step already required
after writing a test, run in the other direction.

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
