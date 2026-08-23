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

### S3 — RE-OPENED: the heredoc backslash defect is marked FIXED, but nothing gates the BASH path, and it corrupted a shared file twice in ten minutes

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

---

### Not three defects — one missing gate: nothing renders by default

Framing, not a defect of its own. Recorded because three entries in this file
now share a shape, and the shape is the finding:

* **spacing dropped** — `\qquad`, `\hspace`, `\;` vanish in conversion (S1);
* **operator names italic** — `\max`, `\min`, `\lim` (S1);
* **the prime downgraded** — U+2032 to an apostrophe on the accept path (S4,
  and that one at least REFUSES rather than shipping).

Every one of them produces valid OMML. `equations()` counts them correctly,
`math --check` reports clean, `lint` is clean, `to_latex` round-trips the
structure, the `m:oMath` totals are right, and `compare`'s text layer sees
nothing because no character moved. **The only instrument that detects any of
them is a person looking at a rendered page**, and nothing in the ladder
renders.

The method exists and is written down — export the PDF through Word, which
keeps maths where LibreOffice does not, then rasterise and read it. It is in
the house notes as `verify_omml_word_pdf`. It is in nobody's gate list.

So the useful fix here is probably not three patches. It is a render step
cheap enough to sit in `revision validate`, or in a paper's `[verify]` block,
for any manuscript that carries maths — something that renders the pages an
equation lands on and puts them where a human will actually look. Each of the
three would have been caught on the first run.

**And it has to render the MARKUP view, not just the page** — ezhik-82's
point, from the `word.export_pdf` entry below. `export_pdf` calls
`ExportAsFixedFormat` without `Item`, so it renders the DOCUMENT: a redline
comes out clean and looks like a batch that marked nothing. A gate built on
it would therefore inherit the very failure this note is about, one level up.
A PDF of a redline showing no markup and a `math --check` passing an italic
operator are the same defect in different clothes: **the check watches an
observable proxy rather than the object it is supposed to be about.** That
sentence covers every entry named here, the two ezhik-82 found in the
comparison layers, and the `_kill_tree` mutant that survived because the
elapsed-time assertion could not see an orphan.

Found across Aging_Well's R20 and R21, 2026-08-23/24, which gave that paper
its first mathematics: all three defects, all three found by reading the page,
none by any command.

**Partly answered, 24.08.** The two S1s above are fixed, and the render
gate has a first instance:
`tests/test_equations_typography.py::test_the_RENDER_shows_upright_operators_and_italic_variables`,
marked `-m word`, builds the equations into a real package, exports a PDF
through Word and reads the text layer BY CODEPOINT — Word draws a
variable from the Mathematical Alphanumeric block and an upright operator
name in ASCII, so "is the operator upright and the operand not" is a
machine-readable question about the page rather than about the markup
that was supposed to produce it. No eyes required, which is what makes it
a gate rather than a habit.

It is one test, not the ladder: `revision validate` still renders
nothing, and the prime entry and `export_pdf`'s markup blindness are both
still open. But the shape is now proven cheap — nine seconds, and it
caught a real regression in the fix that landed beside it.

---



### S4 — the unbalanced-field integrity flag names an EMPTY paragraph for the orphan half, so the flag cannot be located

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

---

### S4 — `RefStyleReport.cited` and `.entries` are COUNTS with collection names

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

---

### S4 — a year-labelled table COLUMN HEADER parses as a citation, so every paper with one carries an ignore entry

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

---


### S2 — Word's Compare merges a CHANGED FOOTNOTE and writes the merged string into both copies

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

---

### S4 — `ship` RE-DECLARES `build`'s flags, so every flag added to `build` is an AttributeError on `ship` until someone remembers

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

---


**One open, filed 2026-08-23** (above). Before it the section was empty: the three that were open — `crossrefs` calling an exhibit linked when nothing linked to it, and the two `refstyle` entries from Aging_Well's reference list — are in `Fixed` below, closed the day after they were filed. Before them: the cross-reference entry
raised by HCW closed the same day it was filed; **NOTHING WAS OPEN on
2026-08-21** either, the first time since this file was started that the
section held no live defect. Two records stay below because both are
instructive: a retraction, and a Word behaviour worth not chasing twice.

**Fifteen more closed on 2026-08-22, and not one came from a
manuscript.** They came from a code review of the round just
committed — the `REF` cross-reference work and the eight commits around
it — every finding reproduced against the live tree before it was
believed. Worth recording because the shapes were not the ones the
papers turn up:

* **five of the fifteen were the SAME change arriving somewhere it had
  not been carried.** `internal_links` learned the third link form;
  `crossrefs` still knew two, so `unlink` deleted bookmarks and left
  the fields dangling. The loss gates learned it by accident and began
  refusing every build, because Word re-mints those names. A change
  that teaches one reader a new fact has to be walked to every other
  reader of the same fact, and the walk is not optional when one of
  them REFUSES a build.
* **two were a rule stated in a docstring and not in the code.** `\h`
  is what makes a REF a link — written down, not required. "Only Word's
  own anchor confers reach" — written down, and then defeated by two
  gaps sharing a key.
* **two were a flag that only half worked**: `--ignore` reaching one of
  two `_resolve_lead` calls, `--strict` absent where the exit code
  needed it.

The whole round is below under 22.08. The suite went 4588 → 4610.

**Twenty-one closed on 2026-08-21**, in batches as the manuscripts
turned them up — and the last four were raised by RETIRING the
paper-side workarounds the earlier ones replaced, which is the round
worth repeating: a workaround deleted is a claim that has to be checked,
and checking it found the lettered year, the mention Word left behind,
and the two findings that were one.

**The last one out is the one to remember.** The heredoc entry said
twice, in its own text, that nothing here could fix it — and nobody had
run the one command that tests it. The same payload through the
PowerShell tool comes out intact. An entry that explains why a thing
cannot be fixed is an entry nobody re-reads; it needs the measurement
that would refute it, not the argument that supports it.

Nine came from Aging_Well's first five rounds, seven from AFI, one from
a review of the tracked gates, one was answered by simply re-reading a
manuscript (`probe` had been able to say it all along), one was measured
into existence with no manuscript involved, and one was closed as a
DECISION rather than a fix so it is not proposed again. Three shapes ran
through them.

**A number that cannot tell two states apart.** "Unlinked" counted works
and could not see a half-linked apparatus; "part dropped" counted
`docProps/*` as Word's own and could not see a sensitivity label leaving
the document; the batch stamp named `prev.docx` as a FILE and could not
say which baseline it meant; and `crossrefs --audit` printed all zeroes
for five unlinked exhibits, which is what a paper with no exhibits at
all prints. Each read as a clean report of a document in the wrong state.

**A rule written from ONE example.** The rels walk answered the
`../customXml/` spelling and no other; the year matcher took the one-year
parenthesis and dropped the group whole; the year FOLD ended at the
digits and could not see a 2023b; the italics exemption knew "working
paper" and not the four other names a numbered series goes by. The fix
in each case was to read what the format actually says — resolve the
target, expand the list, spend the letter, match the shape — rather than
to add the second example.

**The document already knew.** The one that cost the most was `link`
minting a name while a broken back-link in the same paragraph named the
anchor to create; `probe` could already say AFI's captions were
field-form; a locked file could already be copied and read. Three
separate hours went into repairs, hand-wiring and refusals for facts
that were in the file, or in this toolkit, the whole time. Before adding
a rule, look for the answer the document is already giving.

**Nothing else open, as of 2026-08-19.** Six were raised and closed that day; five
came from one manuscript and the sixth from mutation testing `placement` the
day after it landed — the accept-all half of gate 5's text check
(`unaccepted`), the re-labelled link that blocked `baseline`
(`relabelled_links`), the eye gate that had stayed in one paper's scripts
(`render_accepted`), and the two `placement` defects that cost DSI a blank
landscape page — a block moved out of its own section, and a note the block
never knew it had (`831ef24`) — plus the report that called a table it could
not fix fixed. All six are in Fixed. Four were raised from an earlier manuscript round
(DSI: the §6 restructure, the C/B exposition batches and F1). Three were real
and closed the same day; the fourth was **retracted — it was never a defect**,
and is kept below because the mistake is instructive. The three that were real:

* the gate that let the rest through — `reject-all == baseline` compares
  STRUCTURE COUNTS as well as text now, so a duplicated table, a dropped
  bookmark and a destroyed section break fail it BY NAME;
* the anchors a move used to lose, which are lifted out of a revision before it
  is removed rather than going with it;
* the table Word's Compare writes twice and marks neither copy of, which
  `build` now refuses at build time.

Two of those three are refusals rather than repairs, and deliberately: an
unmarked duplicate is not a revision, and an anchor cannot be put back around
words that are being restored elsewhere without pairing information this side
cannot verify. **A moved block containing a table, or a bookmarked paragraph,
still cannot go through Compare and come back cleanly** — what changed is that
nothing ships silently now.


### ~~S2 `link_all` makes no back-link for a newly-cited entry~~ — RETRACTED 19.08

**Not a defect. `link_all` was right and the report was wrong.** It said
`linked 0, already linked 54, back-links added 0, unmatched 0, skipped 0` for
five works that had just been given in-text citations, and that reads like a
no-op on new work. It was an accurate description: all five were **already
cited, in FOOTNOTES**, in the baseline, and already carried both bookmarks —
the entry anchor and the `…txt` back-link target. `link_all`'s docstring says it
takes a work's first mention "body first, then footnotes", and that is what it
had done, on an earlier run.

The check that produced the report looked for `Moran1950txt` in
`word/document.xml` only. The bookmark lives in `word/footnotes.xml`. **A
back-link that is not where you looked is not a back-link that is missing** —
and `audit_links` reporting 66/66 with 0 issues was telling the truth the whole
time.

Kept rather than deleted because the shape recurs: a report of "nothing to do"
is indistinguishable from a report of "nothing was done", and the way to tell
them apart is to look for the artefact in every part of the package, not in the
one the work happened to touch.


### Not a defect — recorded so it is not chased twice

Editing a table CELL, or deleting paragraphs just above a table caption, makes
Word's Compare rewrite that caption's HYPERLINK FIELD as a `w:hyperlink`
ELEMENT. The count moves (16 -> 17, in the accepted and the rejected view alike)
and neither accept nor reject removes it. It is a representation change only:
the caption already rendered blue and underlined via `rStyle=Hyperlink` inside
the field, and both audits stay clean. Unwrapping it makes things WORSE —
`audit_links` then reports NO BACK-LINK, because that element has become the
link's only remaining form.

**The same churn runs the OTHER way on an ordinary author save.** AFI,
2026-08-21: a repair wrote twelve `w:hyperlink` elements; the author opened
the manuscript in Word, made two word edits, saved, and eight of them came
back as `HYPERLINK` fields, with every bookmark id renumbered low and rsids
on the runs. Nothing was lost — 104 bookmarks, every anchor resolving — but
the file no longer looks like what the repair wrote, and it cost twenty
minutes of believing the repair had never applied. `ingest` calls it
save-noise, correctly.

So: **the form of a link is not evidence about who wrote it.** Verify a
repair by counting anchors and resolving them, never by "mine writes
elements and this file has fields". Both forms are live in any manuscript a
human has opened, and `wrap_link_in_bookmark` counts them together for
exactly this reason.

---

*Kept for the shape of the file.* This section was empty on 2026-08-18, the
first time since it was started. Thirteen were opened and closed on the 17th–
18th and not one came from a manuscript: eight from the mutation rounds and five
from a review of that day's commits — the first time this file had been filled
by looking rather than by being bitten. **The mutation rounds found offsets
nothing asserted**; the question that finds those is not "is the element in the
output" but "WHERE did it go". **The review found the case each fix's own test
did not build:** a fix and its test are written together and share an author's
blind spot, which is what the second reader is for.

The four raised on the 19th broke that run — all four came from a manuscript,
and being bitten is still how the gate-shaped ones get found. **Three of the
four were found by comparing STRUCTURE across the baseline, accepted, rejected
and target views** of the same redline, which is a check no gate was making.
The fourth was found the same way and was wrong anyway, because the artefact it
looked for was in a part of the package it never opened.


### Mutation analysis — the equivalent mutants, by module

Recorded rather than chased. A survivor that CANNOT change behaviour is
a fact about the code, and the next sweep should not spend an afternoon
rediscovering it.

**Setup, for cosmic-ray 8.7** (8.4's recipe in the toolkit memory is out
of date in three ways): `work_items` keeps only `job_id`, so the
operator and position come from `cosmic-ray dump`; the dump spells
outcomes lower case where the sqlite column holds them upper; and the
annotation-equivalent class has MOVED — 8.4 had an operator whose name
said "annotation", 8.7 reaches the same code through
`ReplaceBinaryOperator_BitOr_*`, because a modern annotation is a binary
or (`str | None`). Under `from __future__ import annotations` those are
never evaluated. They are 341 of `styles.py`'s 604 mutants, and counting
them scored it 41.9% against a real 85.5%. `PYTHONIOENCODING=utf-8` is
needed on the DUMP side too, for the same reason as the exec side: it
re-emits pytest output full of em dashes, dies on a cp1252 pipe, and
hands back an empty stdout — every module then reads 0.0%.

**`citations.py` — 141 mutants, 119 real, 5 equivalent (95.8%).** Twelve
survived the sweep; seven are killed by the `repair_plan` bucket tests
and the `check_citations` report tests added with this entry. The five
that remain are equivalent because the KINDS ARE A CLOSED SET of six
strings, and a comparison can only differ from `==` on a value that can
reach it:

* `f.kind == "BROKEN LINK"` → `<=`. "BROKEN LINK" sorts first of the
  six, so nothing is less than it.
* `f.kind == "REF WITHOUT CITE"` → `>=` and `f.kind == "ORPHAN REF"` →
  `<=`. Both sit inside `elif f.kind in ("ORPHAN REF", "REF WITHOUT
  CITE")`, so only those two strings reach them, and neither comparison
  can separate them differently.
* `f.kind == "DOUBLED LINK"` → `<=`. Every other kind is matched by an
  earlier branch, so only "DOUBLED LINK" arrives.
* `check_citations(docx_path, *, ...)` → the keyword-only marker
  mutated as a binary operator. Equivalent by construction.

---


### S4 — `MATH_DOWNGRADES` knows the MINUS but not the PRIME, so a prime-bearing equation cannot be built

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

---

### S4 — every read-only GATE refuses on a Word lock, though `status` and `ingest` no longer do

Found on Aging_Well, 2026-08-23, running the paper's own `[verify]` list
while the author had the manuscript open in Word to adjudicate a batch.

All six exit 1 with `working.docx is locked (open in Word). Close it and
retry. ([Errno 13] Permission denied)`: `citations`, `refstyle`,
`crossrefs`, `math --check`, `footnotes --check`, `lint`.

**The precedent is already in `## Fixed`** — "S4 read-only `revision
status` and `ingest` refuse on a Word lock", closed 21.08 by reading a
snapshot and saying so:

```
read from a SNAPSHOT: the author has the file open in Word, so this
describes the moment the copy was taken, not whatever they have typed since.
```

That fix stopped at those two commands. Everything else that only READS
still refuses.

**Why it matters more than it sounds.** The author having the manuscript
open is not an edge case, it is the normal state during adjudication —
which is exactly when someone wants to check whether a citation resolves
or an equation is still display mode. And a `[verify]` list that can only
run when nobody is working on the paper is a list that gets run less.

**Fix shape.** The snapshot fallback already exists; extend it to the
read-only commands, with the same banner so nobody mistakes a snapshot
for the live file. `--write` paths must keep refusing.

### S4 — `crossrefs --labels` REPLACES the default labels, so a narrowed run prints a clean report about the exhibits it did not look at

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

---

### S4 — the math-glyph refusal quotes both strings and never says WHICH CHARACTER differs, which is the one thing a reader cannot see

Found 2026-08-24 by the other session, diagnosing a real build refusal on a
paper with `\kappa'(a)` in it. Recorded here rather than in that paper
because the message is `revision`'s, not the paper's.

**Symptom as observed.** `revision build`'s accept-check refuses and prints

```
equation 26: '…=λκ′(a)' in the clean copy, "…=λκ'(a)" accepted
```

which is the right pair of strings and genuinely useful — it is how the
U+2032 gap in `MATH_DOWNGRADES` was found at all. What it does not say is
that the difference is `′` U+2032 PRIME against `'` U+0027 APOSTROPHE. At a
terminal's font size those two glyphs are near-identical, and the reader is
being asked to spot the difference by eye between two quoted strings that
look the same. **Twenty minutes to diagnose what a codepoint would have
answered in ten seconds.**

**Why it is worth an entry despite being ergonomics.** This is the class of
message a person only reads while already stuck, and the whole value of
quoting both forms is defeated if the difference is invisible in the medium
the message is printed to. The refusal is otherwise well built — it names the
equation, both views, and the reason — so the fix is one line of it.

**Shape of a fix.** On the first differing position, append the codepoints:

```
equation 26: differs at char 5 — '′' U+2032 vs "'" U+0027
```

`glyph_runs` already walks both strings to build the quoted pair, so the
index is in hand; `unicodedata.name` gives the rest. Worth doing for every
glyph refusal in the module, not just this one — the minus/hyphen pair
(U+2212 vs U+002D) has exactly the same problem and is the one this toolkit
hits most.


---

## Fixed

### ~~S2 `tracked.build` loses `<w:trackRevisions/>` and DUPLICATES a comment present in both inputs~~ — FIXED 24.08

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


### S4 a `Table` handle is invalidated by editing ANY table, so the natural "fetch the batch, style each" loop always raises on its second pass

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

**Was:** a caption carrying NEITHER bookmark fell through all three
buckets and was counted nowhere, so five unlinked exhibits printed the
same all-zero line as a paper with no exhibits at all — and the reader
had to notice the absence of a number rather than a number being wrong.

**Fix.** A fourth bucket, `unlinked`, and the CLI prints it in the same
column as the rest: `unlinked  2  Box1, Table1`. The test builds the
case the audit exists for — a caption and a mention and no bookmarks
anywhere — and fails without it.

### ~~S4 the `crossrefs` CLI cannot be given a label the document actually uses~~ — FIXED 21.08

`docxkit crossrefs PAPER.docx --labels Figure,Table,Box`, on both
`--audit` and `--write`; `crossrefs.link` and `audit` have taken the
label set since they were written, and only the command baked
`DEFAULT_LABELS` in. Aging_Well's Box 1 audits and links now without a
script.

### ~~S1 `link` cannot repair a LOST citation link~~ — FIXED 21.08

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

`FOOTNOTES` and `ENDNOTES` too. Bookmark ids must be unique across the
whole document, notes included. One line, plus the test that says why.

### ~~S1 nothing ties a batch to the BASELINE it was built on~~ — FIXED 21.08

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
