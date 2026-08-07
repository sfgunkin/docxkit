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
cr-report run.sqlite
```

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

## Two traps that keep coming back

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
