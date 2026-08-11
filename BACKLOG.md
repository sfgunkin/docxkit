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

### S2 `citations.link_rest` is blind to entry bookmarks Word has HOISTED
- **Symptom** Reports `'Straus et al. (1998)' (¶40): entry has no
  bookmark` and skips the mention, for works whose entry bookmark exists
  and resolves perfectly well. Word hoists a collapsed bookmark out of
  the paragraph it marks, so the reference entry's own
  `<w:bookmarkStart w:name="Straus1998"/><w:bookmarkEnd/>` sits BETWEEN
  paragraphs at body level: `…</w:p><w:bookmarkStart/><w:bookmarkEnd/>
  <w:p …>`. `link_rest` looks inside the entry paragraph, finds nothing,
  and declines.
- **Consequence** the later-mention layer silently stops being
  maintained for those works. On Parental_style that was **nine
  mentions across six works** (Straus1998, Doepke2019 ×4, Doepke2017,
  Gracia2008, Roche2020, Habibov2012) — the author noticed before any
  tool did, because `citations` reports ALL CHECKS PASSED (it resolves
  anchors document-wide, and first mentions are all linked).
- **Repro** Parental_style 2026-08-11, `working.docx` after author round
  9. `Straus1998` bookmark: 1 in the document, 0 inside its entry
  paragraph.
- **Workaround** `_link_citations` in
  `Parental_style/revision/scripts/applied/relink_mentions.py` — takes
  `link_rest`'s own skip list, derives `SurnameYear`, **verifies it
  against the document-wide bookmark set** (refusing to write a link
  that goes nowhere) and calls `link_in_para` directly.
- **Fix** Resolve entry anchors from the document-wide bookmark set,
  or accept a bookmark that sits immediately before/after the entry
  paragraph. `crossrefs` already copes with hoisting; this path does
  not. Note `citations` should probably also report the gap — "N later
  mentions unlinked" is invisible today.

### S4 `footnotes.sizes` skips the reference mark untested
- **Symptom** `sizes` asks only runs with visible text, so a paper that
  deliberately sizes the `w:footnoteRef` run gets no finding when one
  mark disagrees with the rest.
- **Why it is that way** the mark's run is formatted by the
  FootnoteReference style and states no size on purpose. Counting it put
  every conforming document on the list — that exclusion is what makes
  the check quiet enough to run twice.
- **Evidence** none. No document on this machine sizes it; the 134-file
  sweep says nothing either way. Recorded as a KNOWN EDGE rather than a
  defect, at the user's request, so the next person meets it as a
  decision rather than as a surprise.
- **Verify before fixing** find a manuscript whose footnote marks carry
  an explicit `w:sz`, and check whether one of them disagreeing is
  visible on the page. Without that, widening the rule trades a real
  quiet for a hypothetical catch — the same trade `_FOLD`'s docstring
  refuses.

### S4 `wrap_link_in_bookmark` has no "first mention" mode
- **Symptom** Refuses when a work is cited more than once (correct — it
  will not guess), but the house convention is *bookmark the first
  mention, leave later ones forward-only*, and there is no helper for it.
- **Repro** `Doepke2017`, cited 3×. **Recurred 2026-08-10** with
  `Table5`, linked twice (the wealth paragraph and the age-profile
  paragraph) after an author save stripped `Table5txt`.
- **Workaround** Hand-rolled regex in
  `Parental_style/revision/scripts/applied/repair_round3_links.py`, and
  again as `_wrap_first` in `applied/repair_round5.py` — **two copies of
  the same hack now, in the same paper.** That is the drift this file
  exists to prevent; delete both when `which="first"` lands.
- **Fix** `which="first"`.

### S4 `citations.repair_plan` proposed deleting a live entry as debris
- **Symptom** Classified `BhlerNiederberger2022` as "debris of a deleted
  entry — remove", while both the reference entry (¶133) and its citation
  (¶22) were alive. Following it would have destroyed a live reference.
- **Mitigation already present** the plan's header says the
  classification is mechanical and the repair is not. That warning is
  what saved it.
- **Evidence** 2026-08-09.
- **Fix** Before classifying as debris, check whether the entry TEXT
  still exists — the bookmark alone is not evidence.

### S4 a bookmark deletion cannot ship through Word Compare
- **Symptom** Compare carries bookmarks over from the ORIGINAL side, so
  deleting one in the clean copy is silently overwritten when the redline
  is built. The orphan `Lari2023` bookmark survived two full rounds.
- **Evidence** 2026-08-09/10. **Third occurrence 2026-08-10**: dropping
  the `Conley1999` and `Ingoglia2021` entries removed each bookmark in
  the clean copy, and Compare put both back — `citations` on the built
  batch reported `STALE BOOKMARK` and `REF WITHOUT CITE` for entries
  that no longer existed. Confirms the pattern is systematic, not a
  one-off. Note the bookmarks were HOISTED clear of their entry
  paragraphs, so deleting the paragraph did not take them either.
- **Workaround** Apply bookmark deletions to `working.docx` AFTER the
  promote; revision count is unaffected, a bookmark is not tracked
  content.
- **Fix** `revision build` could detect "this batch removes bookmarks"
  and say so.

### S2 `revision build` under-reports what Compare baked in untracked
- **Symptom** It warns `resolved N math revisions … Author this batch by
  hand instead`, which reads as "N equation edits are untracked". The
  real damage was far wider: restructuring a math-bearing paragraph
  (merging two paragraphs, one holding an inline oMath) shipped the
  **entire rewritten paragraph** untracked, and the batch's headline
  count looked healthy — 7 revisions, 6 of them in the body — while the
  central edit had no revision marks at all.
- **Repro** Parental_style 2026-08-10, protocol_theory_opening.
  `docxkit revision build` → "resolved 5 math revisions", 7 revisions;
  `docxkit locate batch.docx --revisions` → all 6 body revisions are the
  two word-swaps in an unrelated paragraph.
- **Also** the advice has no tool behind it: `tracked.build` IS the
  Compare wrapper, so "author this batch by hand" names no supported
  path. Either provide one or say plainly that such a batch has no
  redline.
- **Not steerable by authoring.** Built twice — delete-and-reinsert, then
  rewrite-in-place so neither the footnote reference nor the oMath moved
  — and Compare emitted **byte-identical** output. It diffs document
  CONTENT, not the XML it is handed.
- **Fix** Report which PARAGRAPHS lost tracking, not just a math count;
  `locate --revisions` already has the data.

### S2 a moved footnote ANCHOR makes Compare emit the footnote as an unmatched insert
- **Symptom** When a footnote's reference moves (same footnote, new
  position in the text), Compare treats it as a brand-new footnote:
  the whole footnote body is wrapped in one `<w:ins>` with **no matching
  `<w:del>`**. Accepting is correct; **rejecting empties the footnote.**
  This is one of the two reasons a batch fails gate 5 while looking fine.
- **Repro** Parental_style 2026-08-10: footnote 2 re-anchored from the
  deleted roadmap paragraph to the new opening sentence.
  `revisions.reject(footnotes.xml)` → empty footnote body.
- **Fix** Detectable before the handback: a footnote part whose `w:ins`
  count is non-zero and `w:del` count is zero, when the footnote existed
  in the baseline, is always this. Warn by name.

### S4 `revision validate` says reject-all MISMATCH but not WHAT failed
- **Symptom** Gate 5 prints `{'paragraphs': False, 'glyphs': False,
  'footnotes': False} -> MISMATCH` and stops. Three booleans do not say
  which paragraph, or whether the cause is one word or a whole section.
- **Evidence** 2026-08-10. Cost a bespoke diff script
  (`difflib` over reject-all vs `prev.docx` paragraph text) to learn that
  the merged paragraph was untracked and footnote 2 came back empty —
  which is exactly the information needed to decide whether the batch is
  salvageable or has to ship clean.
- **Fix** On mismatch, print the first few differing paragraphs the way
  `compare`'s TEXT layer does. The comparison is already computed.

### S4 `build/batch.docx` is reserved but not guarded
- **Symptom** Writing a hand-built clean edit to `build/batch.docx`
  collides with `revision build`'s provenance tracking: it reports "the
  file changed since docxkit built it — someone edited it in Word" and
  refuses.
- **Evidence** 2026-08-09. Cost a cycle to diagnose.
- **Fix** Say the path is reserved, or accept a clean edit there.

---

## Fixed

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
