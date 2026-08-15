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

---

## Fixed

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
