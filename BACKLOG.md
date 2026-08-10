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

### S3 gate 6 counts a drawing as a text difference
- **Symptom** `revision validate` gate 6 (XML accept == Word accept)
  still reports MISMATCH on a zero-revision document, now down to
  **exactly one `/` per `<w:drawing>`**: Word's `Range.Text` emits a
  placeholder character for an inline graphic, while `_glyph` collects
  only `w:t`/`m:t` and contributes nothing there.
- **Repro** Parental_style `working.docx`: 2 drawings (`Graphic 5` at
  body[375], `Graphic 7` at body[380]) → 2 `/` insertions, at those exact
  offsets.
- **Evidence** 2026-08-10. The prime half of this entry is FIXED
  (`00db587`); this is what remains.
- **Deliberately NOT fixed by folding `/`** — that character is ordinary
  prose ("and/or", URLs), and `_FOLD`'s own docstring says not to add a
  fold on suspicion. One two-sample observation is not enough to declare
  `/` "the drawing character".
- **Fix** Make the comparison drawing-aware on BOTH sides rather than
  character-folding: have `_glyph` emit a placeholder per `w:drawing`,
  and confirm against a second document what Word actually returns for an
  inline graphic before encoding it.

### S2 `latex_to_omml` output needs a normalization pass
All four are valid markup, so lint, `math` and text-diff pass while the
page is wrong. Only a PDF render catches them.
- `\overline{v}` emits `<m:acc>` with `m:chr m:val="―"` (U+2015
  HORIZONTAL BAR). Not in Word's bar-set, so Word centres the glyph ON
  the letter — **v-bar renders struck through**. Should be U+0305
  COMBINING OVERLINE.
- `\quad` emits a literal U+00A0 *inside* the math, and `\{` a literal
  brace character. Both then join the vocabulary `docxkit math` derives
  from the document's own equations — every non-breaking space in the
  reference list started reporting as prose-math, 1 finding → 19.
  `\left\{ \right\}` builds a set as delimiters and is clean.
- `\frac{(-)}{(-)}` emits an **empty `m:e`**, which draws as a blank box.
  Caught by lint, but only after the build. Parenthesised signs should be
  an `m:d` with default delimiters, as the papers write them by hand.
- **Repro** `latex_to_omml(r"\overline{v}_i")` etc.
- **Evidence** 2026-08-09/10, theory-section merge.
- **Workaround** `omml()` in
  `Parental_style/revision/scripts/applied/theory_merge.py` (accent chr);
  `fix_a3_signs.py` (clones the paper's own `m:d`).
- **Fix** Normalize in `equations`, so every paper gets it.

### S2 no display-mode support, and Word's auto-promotion is unreliable
- **Symptom** A bare `<m:oMath>` is INLINE to Word; display is
  `<m:oMathPara>`. House rule for ALL papers is display + centred, and no
  gate checks it. Word sometimes promotes a lone oMath on save and
  sometimes does not — equations (2)-(4) were written identically to (1)
  in one batch and came back promoted while (1) stayed inline.
- **Gotcha to encode** an `oMathPara` must be the ONLY content of its
  paragraph; a trailing run (a comma, an equation number) silently
  demotes it back to inline on the next Word save.
- **Evidence** 2026-08-10, user: "this is a general rule for all papers".
- **Workaround** `make_display()` in
  `Parental_style/revision/scripts/applied/fix_display_math.py`.
- **Fix** `equations.display(para, jc="center")` + a check that reports
  inline display-equations. See [[feedback_house_style_math]].

### S2 no check that footnotes share one size
- **Symptom** One footnote rendered at 12pt among 10pt neighbours. The
  offender carried **no `w:sz` at all** and inherited the body size, so
  searching for a wrong value finds nothing.
- **Gotcha** `word/footnotes.xml` also holds the separator and
  continuationSeparator at ids 0 and -1; they carry `w:type` and are not
  footnotes. A naive sweep "fixes" two non-footnotes.
- **Evidence** 2026-08-10.
- **Workaround** `fix_display_math.py`, same file as above.
- **Fix** A `hygiene` check: footnotes disagreeing on size, or lacking an
  explicit one.

### S4 `wrap_link_in_bookmark` has no "first mention" mode
- **Symptom** Refuses when a work is cited more than once (correct — it
  will not guess), but the house convention is *bookmark the first
  mention, leave later ones forward-only*, and there is no helper for it.
- **Repro** `Doepke2017`, cited 3×.
- **Workaround** Hand-rolled regex in
  `Parental_style/revision/scripts/applied/repair_round3_links.py`.
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
- **Evidence** 2026-08-09/10.
- **Workaround** Apply bookmark deletions to `working.docx` AFTER the
  promote; revision count is unaffected, a bookmark is not tracked
  content.
- **Fix** `revision build` could detect "this batch removes bookmarks"
  and say so.

### S4 `build/batch.docx` is reserved but not guarded
- **Symptom** Writing a hand-built clean edit to `build/batch.docx`
  collides with `revision build`'s provenance tracking: it reports "the
  file changed since docxkit built it — someone edited it in Word" and
  refuses.
- **Evidence** 2026-08-09. Cost a cycle to diagnose.
- **Fix** Say the path is reserved, or accept a clean edit there.

---

## Fixed

### S3 `revision status` says TRUTH/TRUTH when prev and working differ — `PENDING`
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
