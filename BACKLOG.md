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
