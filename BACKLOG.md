# docxkit backlog

Defects and gaps found while using docxkit on real manuscripts, recorded
where the fix belongs. Append as you hit them; process in batches.

**Severity sets the order.** S1 silent wrong answer (reports success,
does the wrong thing) · S3 dead or permanently-red gate (people stop
reading it) · S2 wrong output no gate sees · S4 ergonomics. S3 outranks
S2 deliberately: a gate that cannot fail buys false confidence, and this
toolkit has been bitten twice that way.

**Done means:** fix + a test that fails without it + the per-paper
workaround deleted + entry moved to `## Fixed` with its commit. Keep
fixed entries; "did we ever fix that?" is a real question later.

---

## Open

### S1 WORD downgrades U+2212 to an ASCII hyphen inside OMML — on Compare AND on the author's own accept-and-save — and `validate` reports it as an unattributed `glyphs: False`

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

**Repro:** `docxkit revision build` any text-only batch on
`F:\OneDrive\__Documents\Aging_Update\Projects\AFI` and run `validate`;
`glyphs` is False even for a batch containing **zero** edits.

**Workaround in use** — none yet; the AFI round restores the two glyphs
in a post-build pass before promote. Per-paper workaround to delete when
the build does it.

### S2 no way to assert a table REORDER preserved its rows, which is exactly where a hand reorder loses a cell

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

### S2 `renumber.py` is the least-pinned module measured — 15.1 %, and a third of it is `footnote_audit`

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

**Still open:** nothing named. Not re-measured since; the next run
should be a survivor re-run, but `renumber.py` has CHANGED, so that
session is void and it must be a fresh draw.

### S2 `_xml.py` had never been mutation-tested, and 27 of its 45 survivors are the FIELD WALK

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

**Still open:** `set_run_text` 4, `own_properties` 4, `element_spans` 3,
and a tail of ones and twos. Not re-measured since the tests landed.

### S2 the link guards' own machinery is not pinned: 17 % of mutations to `edit.py` survive, and they cluster on `label_extent`

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

**Still open:** 27 in the paired sample, of which at least 11 are the
equivalences recorded in the test files. The remainder is a long tail
of ones and twos — `rep`, `_restyle`, `italicize`, `_enclosing`,
`_note_in`, `_hits`, `subscript` — with no cluster left worth naming.

### S2 41 % of mutations to `_cite_build.py` survive, and half of them are on lines the tests never run

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

**Still open:** `rewrite` 36, `scan` 25, `rebuild` 17, `_entry_keys` 17,
`link_all` 12. `rewrite` is the biggest single cluster in the package
and nothing asserts on what it produces at the value level.


**Second pass, 2026-08-16** (`e5c23cb`). `rewrite` pinned:
`tests/test_link_rest_paths.py` states which span is wrapped, the exact
report line (`Kanbur2007 @ ¶2`), idempotence through the already-linked
mask, bottom-up ordering across paragraphs, the splice, and the widening
guard — the one that abandons widening over an institution's name when
the wider span would reach into somebody else's link. Five of six
targeted mutants die.

The sixth is `sorted(todo, reverse=True)`, left unkilled DELIBERATELY
and documented in the test file: mutating it to `sorted(todo)` produces
an identical document, because `wrap_visible_span` takes VISIBLE offsets
and wrapping changes no visible text, so for non-overlapping spans the
order cannot be observed. It is an equivalent mutant, and writing a
contrived test for it would make the suite slower without making it
stronger.

**Re-measured on the SAME 460 mutants** (same draw, paired):

    real survival  41.1 %  ->  35.0 %  ->  29.3 %

Again the last figure is `tools/mutation_survivors.py`'s; the hand
rule read it as 31.1 %.

`rewrite` went from 36 survivors in the sample to 24.

**Still open:** `rewrite` 24, `scan` 23, `rebuild` 15, `_entry_keys` 12,
`link_all` 10, `_dedup_name` 8. `scan` is the next one worth doing — it
decides which mention of a work is the FIRST, which is the decision the
whole first pass is built on.


**Third pass, 2026-08-16.** `scan` pinned:
`tests/test_cite_scan_paths.py`. Eighteen of its twenty-three survivors
are outside an annotation, and they fall into three groups: four
`continue`s turned into `break`, ten on the arithmetic of the two
report lines, four on the ambiguity finding.

The `continue`s are the four places the scan skips something — a
reference paragraph, a citation with no entry, a work already claimed,
an anchor already linked. `continue` and `break` differ only in what
happens to the REST of the list, and every fixture the function had
carried one interesting citation per paragraph, where they cannot
differ at all.

Each test now puts a citation the pass must still find AFTER the one it
skips. Two of the four arrangements are what manuscripts actually look
like: the source line under a table, which sits below the reference
block because these papers put their exhibits at the end, and a sentence
citing a new work beside one already cited upstream.

The two report lines are pinned by value. `¶{i + 1}` mutates to six
different arithmetic operators and four of them agree with the original
whenever `i` is even, so the citations in these fixtures sit at
paragraph index 1, where every variant reads differently.

**Twelve of twelve targeted mutants die**, each verified by hand-mutation
with the killing test named. One is left alive as equivalent and
recorded in the file: `by_key[key][0].year` -> `[1].year`. Two entries
share a key only when `key_for(surname, year)` agrees and the year goes
into that key verbatim, so every entry under one key has the same year.
The SURNAME in the same line is a different matter — the key strips
punctuation and case first, so "O'Brien" and "OBrien" are one key and
two spellings, and the report names the one the list spells first.

Writing these found the S1 at the top of this file: the fixture for the
table note would not link, because the note had been parsed as a
reference entry.

**Re-measured, PAIRED** — yesterday's session re-run over its own
survivors under today's harness, which `cr-cite.toml` confirms is the
same four test files plus `test_cite_scan_paths.py`:

    real survival  29.3 % (114/389)  ->  25.2 % (98/389)

Sixteen of the hundred-and-fourteen die, none appears. **`scan` itself
goes from 18 to 2**, and one of the two is the equivalent above.

The other was a fixture defect worth recording. `¶{i + 1}` mutates to
eleven operators, and several agree with the original at any given `i`:
index 0 agrees with `|`, index 1 with `<<`, index 2 with `|` again.
These fixtures used index 1, so `i << 1` printed the same ¶2 and lived
through the round. **Index 3 is the smallest that separates all
eleven**; the reported citations now sit there, and all twenty-two
arithmetic mutations across the two report lines die by hand-mutation.
That fix landed after the paired run, so the 25.2 % above still counts
the `<<` survivor.

**Still open** (paired sample): `rewrite` 19, `rebuild` 15,
`_entry_keys` 12, `link_all` 10, `_dedup_name` 8, `_mint_name` 8,
`unlink_by_anchor` 8. `rewrite` was pinned last round and remains the
largest — the widening rules are where its residue sits.


**Fourth pass, 2026-08-16.** `rebuild` and `_entry_keys`, the two
clusters after `rewrite`.

**`rebuild`, 15 survivors, every one of them on a `report.skipped` line
or the `except` above one.** Nothing asserted what a REFUSAL says —
only that linking worked when it worked, which is the wrong half to
leave open. A citation that was linked is visible in the document; a
citation that was not is visible only in that report, so the line is
the entire output for the case, and the paragraph number is most of the
line. `tests/test_cite_rebuild_paths.py` drives all three refusals — a
citation too ambiguous to wrap, in the body and in a footnote; an entry
whose head repeats, so its back-link would be a guess; an entry with no
head at all — and **23 of 23 mutants die**, including the two
`ExceptionReplacer`s that would have let the error out of `link_all`
instead of into a line.

**`_entry_keys`, 12 survivors, four of them in code that cannot change
the answer.** The all-caps lead-token rule added `key_for(words[0])`,
and that key is already there both ways: with one word `words[0]` IS
the surname, so its key is `r.key`; with more, the word RUN at i=0, j=1
is exactly that word. Provable, and checked against nine institutional
entry shapes before deleting it. Same shape as `label_extent`'s dead
leftward walk, found the same way, and the behaviour it was meant to
provide now has the test it never had. Six more die against new value
tests (the word-run bounds, and that every key NAMES something — an
empty name is what an off-by-one there produces, silently, because the
real keys are all still beside it). One is equivalent and recorded.

**Still open**, less what this pass took: `rewrite` 19, `link_all` 10,
`_dedup_name` 8, `_mint_name` 8, `unlink_by_anchor` 8, `_own_bookmark`
5. Not re-measured; the next run should be a survivor re-run of
`.mutation-cite_build-paired.sqlite`.


**Fifth pass, 2026-08-16.** `rewrite`, the largest cluster, taken to
its documented equivalent. **27 of 27 targeted mutants die**, verified
by hand-mutation with the killing test named. The nineteen were three
families, and this module keeps producing the same three:

* **the block skip, as a RANGE.** Entries cite each other — "extending
  Ravallion (2016)" inside a reference is ordinary — and mutating
  `skip[0] <= i <= skip[1]` to an equality protects ONE entry and
  rewrites the rest, turning the bibliography into cross-linked prose.
  The old fixture had nothing citable inside the block, so both ends
  went unchecked;
* **`continue` turned into `break`**, in the two places the scan skips a
  citation: an ignored lead, and one already inside a link. The second
  is what every round after the first looks like — a paragraph holding
  one linked citation and one plain one — and a `break` there makes the
  pass blinder the more of the paper is already done;
* **`¶{i + 1}` on all three report lines** — linked, no-bookmark,
  refused. The existing assertion read `¶2`, where `i << 1` gives the
  same answer; at index 3 all eleven operators differ.

Two paths had never been run at all. `link_all(only=...)` names some
entries and not others, so `names.get(key)` returns None and the pass
says which citation and where. And a citation typed INSIDE an equation
object has offsets from `visible_text`, which counts the maths, that no
`w:r` covers — `wrap_visible_span` refuses, and the refusal is reported
with the paragraph rather than thrown out of `link_rest`, which would
stop a build on one odd paragraph.

`rewrite`'s only remaining survivor is the `sorted(todo, reverse=True)`
recorded as equivalent last round.

**Still open:** `link_all` 10, `_dedup_name` 8, `_mint_name` 8,
`unlink_by_anchor` 8, `_own_bookmark` 5, `_entry_names_from_document` 4.
The naming trio (`_dedup_name`, `_mint_name`, `_named`) is 19 between
them and is the next worth doing — it decides the bookmark names every
link in the document points at.


**Sixth pass, 2026-08-16.** The naming trio, by
`tests/test_cite_names.py`. **11 of 11 targeted mutants die**; three
more are equivalent or unreachable and recorded.

The names carry two constraints that pull against each other — Word's
cap, which truncates ON SAVE without retargeting the links that pointed
at the full name, and uniqueness, where a collision mis-targets a link
rather than merely breaking it — and both had been asserted only
through their consequences. Nothing said what a name IS. The tests now
state them: the surname and the year; the exact cut for an
institutional author (Parental Style's 90-character one); `_2` then
`_3` with no gaps; and that a name whose `…txt` twin is taken is
already a collision, because the pair is the unit.

Two paths had never run. `_dedup_name` was never called with a FRESH
name, which is why four `name + "txt"` mutants lived there — every one
would raise `TypeError` the moment the line ran. And the pathological
fallback, where all ninety-nine truncated candidates are taken and the
answer is a name too long rather than one that collides, had never been
reached at all.

`_mint_name`'s `if keep < 1: break` is UNREACHABLE and its two mutants
are permanent residue: the budget is 37, a year is 4 or 5 characters
and the widest suffix is 3, so `keep` never falls below 29. A test
states that arithmetic instead, and the guard is kept because a change
to `WORD_BOOKMARK_LIMIT` is exactly what it is for.

**Still open:** `link_all` 10, `unlink_by_anchor` 8, `_own_bookmark` 5,
`_entry_names_from_document` 4.


**Seventh pass, 2026-08-16.** The last four named clusters, in
`tests/test_cite_anchor_reuse.py` and `tests/test_cite_link_all_paths.py`.
**18 of 23 targeted mutants die**; five are confirmed EQUIVALENT and
recorded, and three more are the `# pragma: no cover - defensive` guard
in the field walk, which is residue by an earlier decision rather than
by oversight.

`_own_bookmark`, `_entry_names_from_document` and `unlink_by_anchor`
all answer one kind of question — is this marker mine? — and all three
were asserted only where the answer was yes. The failures behind them
are in their docstrings and none was loud: a name not recognised is
minted again, so a second run silently DOUBLES the scheme; a name
recognised too eagerly points every link at another work; a hoisted
bookmark not found made `link_rest` decline nine mentions across six
works, which the author noticed before any tool did.

Two of those now have the tests they were missing. **Idempotence** —
`link_all` run twice leaves the document byte-identical — is the
property `_own_bookmark` exists for and nothing had stated it. And the
**gap** before an entry is read as that entry's own: widening it by one
paragraph reaches into the previous entry's gap, where a stale marker
from an earlier scheme is then answered to while the entry's own sits
unused. The same arithmetic appears in `link_all` and in
`_entry_names_from_document`, and both are pinned.

`link_all`'s residue was the parts of the document that are NOT the
body: the footnotes it also links, also reads existing links from, and
also has to write back — three separate mutants, each of which loses
footnote work silently. Plus the two report `format` loops, which every
other test in the suite ignores because they all read the report's
LISTS; the printed text is what a paper's build log actually shows.

**The paired session for this module is now VOID, and that is worth
knowing before the next measurement.** `.mutation-cite_build-paired.sqlite`
holds specs addressed by (row, column) in the source as it stood before
2026-08-16's fixes — and this module has since lost `_HEAD_RE` and the
dead lead-token branch and gained `_prose_entries`, so every position
below the first change points at the wrong code. Re-running it would
mutate lines nobody chose and report the result as a comparison.

So the next measurement here is a FRESH draw at the recorded seed and
harness, and it starts a new series: it cannot be compared with the
25.2 % above, because that figure belongs to a source this one no
longer is. The rule generalises — a survivor re-run needs the module
byte-identical, so fixing a defect in it ends the series that measured
the defect. The edit-side session is unaffected: nothing in `edit.py`
changed, only tests were added.


**The new series, 2026-08-16** — fresh 460-mutant draw, seed 20260816,
harness the ten cite test files:

    real survival  11.4 % (46/405)     <- new series, starts here

**Read the 46 before reading the percentage**, because most of it is
residue this session created on purpose. Nine sit on `"no head on entry
¶{i + 1}"`, the line the S4 fix made unreachable — recorded in
`tests/test_cite_rebuild_paths.py` when that decision was taken, and
this is what it looks like in a report. Another nine or so are the
equivalences recorded across the test files. The rest is a thin tail:
`unlink_by_anchor` 6, `scan` 5, `_mint_name` 4, `_entry_keys` 3,
`rewrite` 3.

The draw also turned up four live ones the earlier sample had missed,
all now pinned: the truncation in `_prose_entries`' report line; a
NON-matching ghost hyperlink returning its anchor instead of itself;
`link_rest`'s options taking a positional bool; and `where == "¶"`,
which is the only thing keeping the entry-marking branch off the
FOOTNOTES — paragraph indices are per part, so footnote ¶3 and body ¶3
are different paragraphs with the same number, and loosening that
comparison stamps a note carrying a citation with the entry's own
bookmark name.

**One finding was systematic and is now a gate.** The keyword-only
marker `*` mutates to the positional-only `/`, which is valid Python,
and the mutant survived in `replace_in_para`, then `insert_in_para`,
then `link_rest` — three functions, one hole. Every flag in this
package turns a guard OFF, and a positional bool says nothing about
which. `test_a_BOOL_option_is_always_keyword_only` walks all 43 modules
and holds every public signature to it, so the fourth one cannot
happen. The package passed it unmodified, which is why it could be
added as a gate rather than a fix.

---

## Fixed

### S3 `revision doctor` reports 134 selections on AFI and about three of them matter — a paper with a build archive drowns the signal — patterns first, spent folders declarable

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
`restored_bookmarks(baseline, clean, built)` names them and `build` says
so before the handback, with the remedy the three rounds arrived at.
Three sides, because the BASELINE is what makes the answer mean
something: "in the build, not in the clean edit" also describes a name
Word MINTED during the compare, and reporting that as the author's
deletion sends them looking for an edit they never made.

### S4 `build/batch.docx` is reserved but not guarded — `114b464`
It refuses at the call now, and names `build/clean.docx` as the place to
put a hand-built edit. The old failure came from the far end — the
provenance stamp reading the edit as a Word session that never happened.

### S4 `wrap_link_in_bookmark` has no "first mention" mode — `3d42a31`
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
### S2 a moved footnote ANCHOR makes Compare emit the footnote as an unmatched insert — `af355b7`
### S4 `revision validate` says reject-all MISMATCH but not WHAT failed — `af355b7`
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
Sixteen names, twelve of them `word/fonts/font*.odttf` from one tick of
Word's embed-fonts box. Folded by directory —
`word/fonts/ (12 parts)` — and capped at four entries with "and N more".
The test written for the cap caught a bug in the fold: a part at the
package ROOT has no directory, and folding it under `""` dropped
`[Content_Types].xml` off the line entirely.

### S2 no check that footnotes share one size — `a07f8fd`
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
Gate 6 (XML accept == Word accept) could not pass on a paper that writes
derivatives; proved on a ZERO-revision file. Folded, with a test verified
to fail without the fix. What remains of that entry is the drawing
placeholder, still open above.

### S3 cover letter printed "ALL CHECKS PASSED: /" — repkit, `c3391ab`
Recorded here because it is the same class: `refresh` re-writes the
letter without re-running the suite, so it passes no check count, and the
template interpolated it anyway. Fixed with a fallback and a regression
test verified to fail against the old template. (Lives in repkit; listed
once here as the worked example of the format.)
