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

### S2 no public way to ask whether a MATH run is bold, so every guard written against `w:b` guards NOTHING

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

### S2 replacement is guarded against links, INSERTION is not offered at all — so callers hand-roll it and land inside one

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

### S2 `pages` returns a count and nothing else, so pagination defects ship

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

---

## Fixed

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
