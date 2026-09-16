# docxkit backlog

Defects and gaps found while using docxkit on real manuscripts, recorded
where the fix belongs. Append as you hit them; process in batches.

**Severity sets the order.** S1 silent wrong answer (reports success,
does the wrong thing) · S3 dead or permanently-red gate (people stop
reading it) · S2 wrong output no gate sees · S4 ergonomics. S3 outranks
S2 deliberately: a gate that cannot fail buys false confidence, and this
toolkit has been bitten twice that way.

**Done means:** fix + a test that fails without it + the per-paper
workaround deleted + entry moved to `## Fixed` in
[`BACKLOG-ARCHIVE.md`](BACKLOG-ARCHIVE.md) with its commit. Keep fixed
entries; "did we ever fix that?" is a real question later.

**Every entry declares its own status**, on the line under its heading:

    ### S2 — the thing that is wrong
    <!-- status: open -->

`open` · `fixed` · `withdrawn` · `not-a-defect` · `note`. Invisible in
rendered markdown, and `tools/backlog_status.py` gates on it across both
files: `open` may only sit under `## Open` and `fixed` only under
`## Fixed`, while the three record statuses may sit in either, because
some are kept in `## Open` deliberately.

Declared rather than inferred, and that was measured. A detector reading
strikethrough, `FIXED`, `RETRACTED` and a commit hash out of the headings
scored **93 findings, 2 of them real** — because one entry's body says
"Raised by the same review, and not fixed" in its first paragraph and
"Closed 2026-08-18" in its fifth. Entries accumulate history and only the
last word counts; no pattern can tell which sentence is the verdict, and
the author can, once, while writing it.

**Write `Refs BACKLOG.md` in the commit that carries a fix**, and
`tools/backlog_refs.py` — in the suite, so it is a gate — turns the
missing move into a red build instead of a thing somebody notices weeks
later. The entry may move in that commit or the next; what it refuses is
a fix sitting at the tip with the record never written. That last clause
of the rule above is the one that gets dropped, every time, because it
is last: on 2026-08-27 five of the ten entries under `## Open` were
already fixed, and the batch was ordered off the stale list.

---

## Open

### ~~S1 — `revision promote` silently strips tracked-change markup from one paragraph~~ — RETRACTED 04.09
<!-- status: withdrawn -->

**Not a defect. `promote` wrote the batch byte for byte, and the batch
was intact.** Filed the same day from Health_Capacity_to_Work: after
`promote(T8_4_batch.docx)`, Table 9's shared Note was reported in
`working.docx` with the NEW text and **zero** `<w:ins>`/`<w:del>` —
2078 raw chars against the batch's 3259 — and `reject()` on it left
the new text in place, while `revision status` still counted 48
pending. The entry asked whether promote re-derives the redline
internally.

It does not, and the files say so. Measured 2026-09-04, evening:

* **three hashes agree.** `T8_4_batch.docx`, the redline `promote`
  kept in `build/redlines/` at 17:36:24, and the ledger's
  `batch_sha256` are all `333eefd53337d1c2…`; `promote` copies with
  `shutil.copyfile` and then REFUSES unless `sha256(live) ==
  sha256(batch)`, so `working.docx` at 17:36 was the same bytes;
* **the paragraph in those bytes is tracked.** Paragraph 1662 of the
  batch's `document.xml`: 3259 raw chars, 2 `w:ins`, 2 `w:del`, 7
  runs — the "pre-promote" figure the entry quoted, in the file
  promote wrote;
* **reject reproduces the baseline, accept the clean edit**, paragraph
  by paragraph, 0 mismatches of 2740 in the body, 15 in footnotes, 3
  in endnotes — against the rescue copy of the replaced file
  (`fb825d6f…`, the batch stamp's own `base_sha256`) and against
  `T8_4_table9_repair.docx`;
* **2078 matches nothing on disk.** That paragraph is 1777 chars in the
  clean edit, 1631 in the baseline, 1475/2522 in T8.5's clean/batch and
  1657 in T9's — no version of the file has the paragraph the entry
  measured, and the 48 it quotes could not survive a paragraph losing
  four marks. Whatever was read was not `working.docx` as promote left
  it — this paper runs a two-lane layout in which task scripts write
  the CLEAN edit onto `working.docx` (`T8_4_table9_repair.py --write`
  rebuilds exactly this Note as one untracked run), and the lane can
  be told apart only by counting marks.

**What it cost:** every batch since (T8.5 → T13) was installed by
hand-copying the batch onto `working.docx` "rather than trusting
promote" — which is what promote does, minus the rescue copy, the kept
redline, the ledger line, the lock and the two staleness refusals. The
ledger for this paper shows one promote and three baselines: the
protocol's record of four rounds is missing.

**What was real in it — the second, "unconfirmed" observation.**
`working.docx.buildinfo.json` DID name a prior batch after the promote,
because promote never touched the stamp beside the manuscript. Filed
and fixed as its own entry (archive, S3, 04.09). And the gate the entry
asked for — promote re-verifying accept/reject on its own output — is
`validate`'s gate 5 run twice on the same bytes; what promote reports
now is the hash of what it wrote, so the next "this differs from the
batch" is settled by re-hashing in a second rather than by reading
paragraphs for an afternoon.

Kept, like the `link_all` retraction below, for the shape: **a file
that differs from a byte copy was written by something else
afterwards.** The tool's first question about a promoted file is
`sha256`, not "does this paragraph carry marks" — and the entry's own
"measured, not inferred" was a measurement of a file whose identity was
inferred.

### Not seven defects — one habit: a `*.py` glob is a claim that the package is flat
<!-- status: note -->

Seven of the entries closed on 2026-08-30 are the same line of code written
seven times. `revision.py` became `revision/`, and every tool that enumerated
the package with `glob("*.py")` stopped seeing it — `test_api_surface`,
`test_layering`, `test_harness_map`, `coverage_floor`, `mutation_session`,
`measure_all`, `stale_figures`.

**Not one of them failed.** That is the whole finding. Each went on printing a
confident answer about a package it could no longer read: a coverage floor met
by a file that no longer exists, a layering graph with a hole in it, a
whole-package sweep that opened 43 of 57 modules, an API-surface test that
resolved to `docxkit` and passed. The gates in this repository are unusually
strong AND they are keyed by filename, so a rename is a two-part change whose
second part is invisible.

The lesson is not "use rglob". It is that **a gate which enumerates the thing
it guards should say how many it found**, so that a number dropping is
visible without anyone anticipating the reason. `test_harness_map` and
`test_api_surface` now derive their lists from the tree and fail on a module
they cannot place; `coverage_floor` fails on a floor naming a file that is
gone. Those three would each have caught this alone.

Left open as a note because the rule is not implemented anywhere — it is a
thing to ask when writing the next gate, not a check that exists.

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
<!-- status: withdrawn -->

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
<!-- status: not-a-defect -->

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

**An UNREFERENCED `word/numbering.xml` goes the same way, and the agent
is Word rather than Compare.** Aging_Well, 2026-08-24: a build was
refused with `LOST word/numbering.xml`, which read as Compare dropping
it. One handback later `ingest` on the AUTHOR's returned file reported
`removed: ['word/numbering.xml']` — the author's own save deleted it, in
a manuscript with zero `numPr` and zero `numId`. Word drops an
unreferenced numbering part on any save; Compare was never the agent,
only the first save anyone happened to be watching.

**So do not carry it, and do not add it to `CARRIED_PARTS`.** Carrying
means restoring at every build for Word to delete at every accept —
a config line that never wins, and one that reads as a live constraint
to whoever finds it next. Worse, it would have LOOKED right
indefinitely: the part present in every redline, absent from every
accepted file, and no gate compares those two.

**Nor can it go in `regenerated_by_word`**, which is the obvious home
and the wrong one. That function takes a NAME, and the rule here is
conditional on the document: a paper that uses numbered lists and loses
this part has lost something real. A blanket exclusion would buy silence
on the harmless case by going blind on the harmful one, which is the
`docProps/custom.xml` mistake that function's own docstring exists to
record.

**One observation of the new mechanism, on one manuscript.** Recorded as
a warning against a plausible fix rather than as an established fact.
The path there is the part worth keeping: three positions in one evening
— a per-paper script, a config entry, nothing — and the third was right
because the third OBSERVATION explained the first two. The disconfirming
evidence also arrived from a direction nobody had proposed to look in;
the experiment being designed was a second paper, and the answer was in
this paper's next handback. The cheaper experiment was the one already
running.

And the rule that generalises out of it, which is NOT "wait for a second
sighting": **ask what a second sighting could rule OUT.** Here it could
rule out nothing — Compare and the author's save both drop the part, so
two independent-looking observations would have agreed for a reason
neither observer knew, and the agreement would have read as replication.
A second observation that cannot fail is not evidence; it is
repetition.

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
<!-- status: note -->

Recorded rather than chased. A survivor that CANNOT change behaviour is
a fact about the code, and the next sweep should not spend an afternoon
rediscovering it.

**Do not choose the next module from `stale_figures --figures`, and do
not quote a figure from it without re-measuring.** Two independent
reasons, both established 2026-08-24 and both worth stating before the
entries below, because every entry below is a figure and a reader will
reach for the newest one they can see.

*The figures age, and the worst rows age worst.* The three highest in
the table each measured 3-10x lower when swept again, before a single
test was written: `guard.py` 43.6% -> 4.5%, `styles.py` 51.2% -> 13.9%,
`pages.py` 42.8% -> 9.0%. A figure ages against the SOURCE and against
the HARNESS, and `styles.py` fell from 36 real survivors to 10 on one
line added to the harness map — the recorded figure had been measuring
the map, not the module. `tools/replay_survivors.py` re-asks a stale
list in a minute; use it before mining one.

*And 23 of the rows were SAMPLES that did not say so.* `--sample` marks
the mutants it will not run SKIPPED, and a skip is a row, so `partial`
read them as complete: `_table_layout.py` at 460 of 2757, `placement.py`
at 260 of 1689, `edit.py` at 260 of 1411. They carry `SAMPLED n/N` now.
A share over a fifth of a module is a real estimate and worth having —
it is not a measurement of the module, and the column could not tell
you which it was.

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

**Re-swept 2026-09-12, after the S4/S2 citation-form fix: 131 real, none
alive (replayed).** The `DOUBLED LINK` bullet above was wrong by then, if
not from the start. `CITE WITHOUT REF` sorts before `DOUBLED LINK` and
reaches that branch, so `<=` filed it as a doubled link to untangle;
`test_the_plan_files_CITE_WITHOUT_REF_under_investigate_not_DOUBLED` kills
it. The four comparisons that ARE equivalent, the new `BRACKETED SPAN`
branch among them, carry claims in `tools/equivalents.toml` now.

**The S4/S2 lines in `_cite_repair.py`, `_cite_audit.py` and
`citations.py`, 2026-09-12.** The modules were swept whole; this entry is
about the lines that fix wrote. `_cite_grammar.py`'s share of it,
`citation_shape`, left no survivor.

    module            survivors on the fix's lines   killed   equivalent
    _cite_repair.py   66                             52       14
    _cite_audit.py     7                              4        3
    citations.py       1                              0        1

Fifteen tests in `test_citations.py` did the killing. **37 of the 52 in
`_cite_repair.py` were the three guards in `_convert` and the excerpt the
text guard quotes.** No test had ever tripped a guard, so each could be
weakened to `<` or deleted with the suite green. The tests now trip each one
by sabotaging the helper it checks: `insert_in_para` doubling or swapping a
bracket, and `relabel_link` dropping a bookmark or renaming a link. Two
older comparisons, the start-edge and end-edge tests in `respan_link`,
became equivalent when the both-edges fallback landed, and are claimed as
such.

Replayed against the new tests, `_cite_repair.py` has **67 of 1070 real
mutants alive (6.3%)**, every one on older lines: `respan_link`'s rebuild
internals, `wrap_link_in_bookmark` and `remove_outer_field`. They were not
mined. `replay_survivors` reported four of the 52 as SKIPPED rather than
killed: a mutant of a statement that spans lines does not compile when
applied to one line. `kill_check` applied those four with the whole
statement as the anchor, and all four died.

**Mined the same day: every survivor in the three modules is killed or
argued.** `_cite_repair.py` and `_cite_audit.py` were swept whole again
after the day's two repairs, `rewrap_marker` and `retarget_self_link`.
`_cite_grammar.py`'s older survivors were replayed.

    module            survivors   killed   argued
    _cite_grammar.py   67          34       33
    _cite_repair.py   144         119       23
    _cite_audit.py    199         147       46

Two rows fall short of their survivors, and both gaps are refactors. A
claim anchors on a unique line, so two identical one-line removals in
`rewrap_marker` became one statement, and its 144 survivors ran as 142
cases. For the same reason `_cite_audit.py`'s two owner readers now end on
one helper, `_sole`, and its 46 argued survivors take 45 claims. The six
that row is short went with a check in `_off_link` that the branch below
it already answered.

**Eleven `_cite_repair.py` kills were rebuild slices in `respan_link`
whose wrong answer still read right.** Every test compared visible text,
and a stray `>` or half a closing tag between runs is legal character
data, so even parsing the result passed them. `test_cite_repair_edges.py`
now rejects text outside a `w:t`. In `_cite_audit.py` the survivors sat on
thresholds and places: 45 on the majority REF WITHOUT BACKLINK waits for,
and 27 on the paragraph or gap `_reached` files a bookmark under.

Some claims rest on CPython, not on the language. `ch is "("` holds
because iterating a str yields the interpreter's cached one-character
strings; another interpreter would expire the claim, and
`verify_equivalents.py` would say so.

**`_compare_diff.py` — 743 mutants, 653 real, 617 killed (94.5%).** Of
the 36 that remain, 34 cannot change a report and 2 are cosmetic. The
sweep also puts a NUMBER on the staleness rule `tools/stale_figures.py`
already enforces: it reported 60 survivors against a worktree snapshot
taken twenty minutes before three tests landed, and **17 of the 60 were
already dead** when replayed against the harness as it stood. The tool
called it correctly and specifically — `_compare_diff.py  stale:
tests/test_compare.py`, the harness side alone, the source not having
moved — so what this adds is the cost of ignoring it: 28% of a survivor
list, all of it in the part of the module most recently worked on, which
is where the next round would have mined first. Four tests then killed 7
more — `autojunk`, the field report's paragraph number, and two
truncation widths.

The one that mattered: **`compare_paras` passes `autojunk=False` and
nothing pinned it.** difflib calls an element junk when it appears in
more than 1% of the sequence and the sequence is 200 or longer, and then
declines to match it — which describes a regression table exactly, being
hundreds of paragraphs drawn from a vocabulary of "Yes", "-", "(0.00)",
"***". Measured with autojunk left on, one added cell in a 210-paragraph
table comes back as **211 paragraphs replaced**: every cell from the
insertion to the end of the document. That is the same
report-a-human-cannot-audit failure `word_diff`'s docstring measures at
the WORD level, one level up, and the paragraph-level twin had no test.

The two left alive are the `[:60]` context width in `replaced`'s
second exit — the loss whose paragraph never reached the text layer.
Reachable only through the glyph-identical path, and cosmetic there.

The 34 equivalents fall into five classes, none worth a sixth look:

* **Interned string literals under `is` (14).** difflib's opcode tags
  and this module's own `kind`/`where` values are all identifier-like,
  so CPython interns them and `is` agrees with `==` on every input.
  Fragile as style, equivalent as behaviour.
* **Ordering over a closed domain (10)** — `citations.py`'s class,
  again. `elif tag <= "delete"` is reached only by "delete", "insert"
  and "replace", of which "delete" sorts first. The sharpest is
  `m.group(1) <= "begin"`, whose domain is fixed by the alternation
  `(begin|end)` two characters away in the regex that produced it.
* **`label_moves` (5), each for a different structural reason.**
  `-len(s)` → `~len(s)` in two sort keys is a monotone transform, so the
  order is identical; `continue` → `break` on the too-short label is
  equivalent because the walk is sorted by DESCENDING length, so once
  one is too short every later one is; `break` → `continue` on an
  exhausted count only adds iterations whose `while` guard is already
  false; and `>` → `>=` in "grew"/"shrank" cannot separate, because
  pairing requires one label to contain the other and to differ from it,
  which equal lengths forbid.
* **`hyperlink_labels`' `m.group(1)` → `m.group(0)` (2).** Group 0 adds
  the `<w:hyperlink …>` wrapper and nothing else, and `WT_RE` matches
  `<w:t>`, which the wrapper has none of. Same for the field form.
* **Three mutants on two guards whose second clause cannot fire.**
  `fmt_diff`'s `or len(pa.fmt) != len(pb.fmt)`: `_char_fmt` appends a
  character and its flags in lockstep, so equal `wtext_f` forces equal
  `len(fmt)`. `_marker_segments`' `len(before) != len(text)`: `marks` is
  collected from the `<m:r>` matches INSIDE the block `toks` is
  collected from, so `len(marks) <= len(toks)` and `!=` cannot separate
  from `<`. **That is the third and fourth dead clause this same family
  of construction invariants has produced** — `replaced` records two
  more in a comment — and the first found by a sweep rather than by
  reading. Both are kept: the invariant is a property of one helper, and
  a future `wtext_f` that normalizes where `fmt` does not would make
  them live again.

**`guard.py` — 178 mutants, 88 real, 84 killed (95.5%).** The four
survivors are `indent=1` in the two `json.dumps` calls, mutated to 0 and
to 2. The stamp is machine-read and nothing branches on its whitespace:
cosmetic, and recorded here rather than tested.

The finding is not in the survivors. It is that **`base_of` had no test
anywhere in the suite** — the function the whole staleness gate rests
on, whose own docstring records what its absence cost (`validate`
reporting twenty findings against a batch nobody was working on, and
`promote` about to copy a redline built before an entire author round
over the manuscript, Aging_Well R5). Line coverage said 96% and was not
lying: `revision.py` calls it in passing, so the lines execute. Nothing
asserted the contract, and the contract is almost entirely about the
four ways it must answer "cannot tell" rather than guess — no stamp, a
stamp predating the field, a stamp that will not parse, and a field that
is present but not a hash. The last is the sharp one: `""` is falsy but
present, so an `isinstance` check alone would return it, and a caller
comparing hashes would then find no match and call a FRESH batch stale.

Six tests, written BEFORE the sweep rather than after it, because the
harness is half of what a figure measures and there is no point
measuring a harness you already know is missing a function.

**The recorded figure was 43.6% (61/140), from 2026-08-21.** Today's is
4.5% (4/88), against a module byte-identical in length. The two cannot
be compared mutant for mutant — `--fresh` discarded the old session, so
the denominator's move from 140 to 88 has no evidence left to explain
it, and this entry does not invent one. What is certain: the figure
quoted in the table was three days old, `base_of` was untested for all
of them, and the number a reader would have acted on was wrong by an
order of magnitude in the direction that wastes an afternoon.

**`styles.py` — 604 mutants, 259 real, 252 killed (97.3%).** The seven
survivors are the `_own_rpr` set, argued equivalent one by one in a
comment at the foot of `test_styles.py` and not re-argued here.

**It was not the worst module in the package; it was the worst-MAPPED.**
The table read 51.2% (200/391). A full sweep read 13.9% (36/259), and 29
of those 36 sat in `paragraph_property` and `_ppr_attr` — whose tests
live in `test_refstyle_layout.py`, because that is where the question
comes up, and which the harness map did not name. Adding that one line
took it to 10, with no test written. This is the third instance of the
same shape (`errors.py`, `_table_core.py`, now this), and the first
found by asking the map a question rather than by being surprised by a
figure: every test file that IMPORTS a module, against the files the map
names for it.

The three that survived the map fix were a FIXTURE problem, not a
missing test. `test_paragraph_property_walks_based_on_then_doc_defaults`
walks a chain whose parent style carries no `w:pPr` of its own, so `Ref`
-> `Normal` -> docDefaults, and a mutant that breaks the middle step
arrives at the same 160 by the same route. An inherited value has to
DISAGREE with the default before the walk is observable. The third is
the one worth having beyond its mutant: a paragraph naming a style the
stylesheet does not define — the exact case this module's docstring is
about, Word rendering it in its defaults silently — was never passed to
the resolver, and the mutant there is a `KeyError` in a function every
caller is asking in order to decide whether to write a value.

**Twice in one day a stale figure sent the round at the wrong module.**
`guard.py` read 43.6% and measures 4.5%; `styles.py` read 51.2% and
measures 3.9% before any work at all. Both were the top of the table.
Pick a target by replaying or re-sweeping, never by the recorded number
— which is what `stale_figures` has been saying about QUOTING a figure,
now also true of choosing one.

**`batch.py` — 222 mutants, 166 real, 148 killed (89.2%).** Its FIRST
measurement: the module had no entry in the harness map, so no round had
ever picked it. It opened at 17.5% (29/166), the highest real figure
measured here in a day of measuring, and five tests took it to 10.8%
(18/166). Eleven mutants died for those five, replayed rather than
re-swept — the source had not moved, only the tests, which is the case
`replay_survivors` exists for and answered in a minute.

Four of the five are about what the module is FOR, and each was invisible
for a reason worth keeping:

* **the invariant gate only knew how to catch a FALL.** Every case in
  the file loses something — bookmarks 1 -> 0, paragraphs 2 -> 1 — so
  `!=` read as `<` still blocked all of them, and a carrier that
  DUPLICATES sailed through: an edit applied twice, a bookmark cloned
  with its name, a row copied. Same invisible-to-a-text-diff damage the
  gate exists for, arriving from the other side.
* **`apply_steps` "keeps going so one failure does not hide the rest"**
  — its existing test says exactly that in its docstring, and passes ONE
  step, so it cannot see it. Both `continue`s read as `break` and
  survived.
* **`preflight` reports every failure in one pass** — tested, and tested
  for the no-op verdict, and never with a no-op FIRST, so the no-op
  branch was free to end the pass there. That is the round-trip the
  whole module exists to remove.
* **the value objects are frozen, and nothing said so.** A preflight
  verdict means something only because the edits cannot change between
  being preflighted and being applied — a `Step`'s `fn` is arbitrary
  caller code holding whatever the script handed it. Three mutants turn
  `frozen=True` off.

The 18 left are bounded, and none of them moves a gate or a written
document. Eight are truncation widths in `diagnose`'s advisory sentence
(`old[:20]`, `near[0][:80]`). Five are equivalent: `hits[0]` -> `hits[-1]`
and `> 1` -> `!= 1` sit after `if not hits` and `if len(hits) > 1` have
both returned, so the list has exactly one element; `ok: bool = True` is
overwritten by `report.ok = not report.failures` on every path that
reaches it; and two `!=` -> `is not` are the interned-small-int class
recorded above. The remaining three change WHICH explanation `diagnose`
gives — wrong advice rather than wrong behaviour, costing a reader a
cycle and nothing else. Left, and named here so the next round does not
re-derive them.

**`placement.py` — recorded 8.6% (21/245), replayed 6.5% (16/245).** No
tests written: five of the twenty-one were already dead against the
harness as it stands. Listed here because the module was INVISIBLE until
today — the largest in the package, with no entry in the harness map, so
the overview a round is planned from had no line for it (see the map's
own note). The sixteen are the classes recorded above almost to a
mutant: `==` -> `>=`/`<=` over closed domains, `==` -> `is not` on
interned values, one `True` -> `False` and one number. Not mined
further, and the figure quoted here is the replayed one — the session
file still records the run it actually made.

**`pages.py` — 480 mutants, 333 real, 314 killed (94.3%), and the 19
that remain are equivalent to a mutant.** Recorded at 42.8%, the top of
the table; a full sweep read 9.0% before any work, and five tests took
it to 5.7% (19/333). **That is the third module in one
day whose recorded figure overstated it by 3-10x** — after `guard.py`
(43.6% -> 4.5%) and `styles.py` (51.2% -> 13.9%) — and the three between
them were the three worst rows in the table. Choosing by that column
sent every round of the day at a module that did not need one.

Twenty-one of the thirty were in `_printed_number`, and all of them are
GEOMETRY: the margin band a page number must sit in, and the thirds that
name its corner. Every existing case put the number unambiguously inside
both, so each threshold could be widened, halved or floored and still
answer the same. The fixtures did not disagree with the code; they never
asked it anything.

Three tests, and the first is worth having on its own account: **a lone
`42` in the middle of a sheet is not a page number.** That is what the
band is FOR, and a band widened to the whole page reads a table cell as
the printed number — silently, and as a numbering defect that is not
there. The second places a number at 28% and at 40% of the width, which
is where `left` and `centre` actually part; the third puts the NUMBER
first in an ambiguous footer, because the existing ambiguity case put
the running head first and so passed a check that only looked at the
first word.

Two more went to the 3 pt tolerance in `_outermost_line`, which took
measuring before it could be tested at all. The obvious case does not
work: **PyMuPDF gives every word on one baseline the same box** — `7`,
`page` and `Introduction` inserted at the same y all report y1 805.289 —
so descenders cannot separate them and the tolerance never applies
within a line. It applies across BASELINES: a footer holding a number
and a running head at different sizes, or a footnote sitting above the
footer. So it has a floor and a ceiling, and 2.5 pt apart is one line
while 3.5 pt apart is two. A test built on the descender theory would
have passed for the wrong reason.

The 19 that remain are equivalent, each by a construction in the code
around it. `line[0]` -> `line[-1]` sits under `if len(line) != 1:
continue`, so the list has one element and the two indexes are the same
object. `elif now > was + 1` sits under `if now <= was`, so `>` and `!=`
cannot separate. `edge == "lower"` -> `<=` or `is` is the closed-domain
and interned-literal pair recorded above. And the rest need an input
text metrics cannot produce: `(x0 + x1) / 2` -> `// 2` moves a midpoint
by less than a point, `<` -> `<=` needs one EXACTLY on a threshold, and
`width / 3` -> `width // 3` — the sharpest — needs a number whose centre
falls in a 0.4-point window.

---

### A pinned complexity number rots downward in silence
<!-- status: note -->

`tests/test_complexity_debt.py` gates the DEBT list in three directions and
not the fourth. It fails when a function JOINS the list, when a pinned one
GROWS, and when one drops below the threshold and the entry is left behind.
It says nothing when a pinned number simply gets SMALLER while staying over
the threshold — and the file describes that number as "what a later reader
measures against".

Measured on 2026-09-03, walking the package with the same `--isolated` ruff
call the test uses, three of the five entries were wrong:

    _cite_audit._audit_findings   pinned 31   actually 30
    refstyle.audit                pinned 26   actually 25
    edit.replace_in_para          pinned 26   actually 24

Not a ruff version artifact: the numbers were last touched on 2026-08-23
(`79cbad8`) and all three modules were edited through 2026-09-02, so the
functions were simplified under the pin. `edit.replace_in_para` had been
carrying a number 2 too high for ten days, which is the one that matters —
a reader deciding whether a split is worth it starts from the recorded
figure, and here it overstated the job.

**Not a defect, and deliberately not filed as one.** The one-directional
gate is the design: the file argues that shrinking the list should be a
deliberate act, and a test demanding exact equality would turn every
incidental simplification red. The note exists because the cost of that
choice is invisible — the numbers were corrected only because somebody
happened to re-measure before paying the debt down.

DEBT is empty as of 2026-09-03, so nothing is rotting today. This is for
whoever adds the next entry: re-measure before trusting the number beside
a function, and consider recording the DATE with it, which is the cheap
half of the fix and needs no new gate.

**Built 2026-09-05, and the one-directional gate deliberately kept.** A
pin is now `Pin(<complexity>, "<YYYY-MM-DD>")`, so it states when it was
true; `test_every_pin_says_WHEN_it_was_measured` refuses a bare int, a
non-ISO date and a date that has not happened yet, and the pyproject
cross-check now wants the number AND the date on one line. Re-measured
first: DEBT is still empty and nothing in the package exceeds 20, so all
three figures above are historical — `cmd_revision_validate` at 20 is the
closest anything comes. `python tools/complexity_pins.py` walks the
package (importing the measurement from the gate, so the two cannot
disagree) and prints the dict to paste back, naming each pin GREW /
SHRANK / PAID / NEW. **SHRANK is the state nothing else reports**, and
the tool exits 0 whatever it finds — a non-zero exit is one line in
`tools/gates.py` away from becoming the exact-equality gate this entry
rejects, and `test_it_exits_0_on_STALE_pins_because_it_is_not_a_gate`
holds it to that.

One thing the build found, worth knowing before the next entry: the
pyproject cross-check anchored on `<name>\s+<number>`, while the comment
around it wraps names in backticks — so an entry written in the file's
own style would have been refused with a message about drift. The
backtick is optional now.

---

### S2 — `repack` blames one exhibit by NAME and moves another when two share it
<!-- status: open -->

Found 2026-09-15 triaging the first whole mutation sweep of `repack.py`,
and measured on the live source:

    Figure 1 shows it. | Figure 1. First | IMG | z | Figure 1. Second |
    IMG | y

    blamed    {2: 'Figure 1', 4: 'Figure 1'}, 2 trials
    trial 1   Figure 1 shows it. | z | Figure 1. Second | IMG | y |
              Figure 1. First | IMG
    trial 2   the manuscript, unchanged

`repack` resolves a blamed exhibit by its name (`by_name = {x.name: x}`,
so the LAST one wins), computes the move span and the places for that
exhibit, and then asks `_moved` for `x.key`, which moves the FIRST exhibit
with that key. A trial therefore moves the other figure to a place chosen
for this one, or renders the manuscript unchanged, and both are measured
and ranked as placements with nothing said. `tried` is keyed on `x.key`
too, so the two exhibits share one record of what was tried.

Two exhibits with one number are a numbering defect in their own right,
which is why this is filed and not fixed (the user's call, 2026-09-15).
The fix, when it is taken up: resolve the blame, the search and the move
by the exhibit's position (`caption_at`) rather than its name or key, and
hand `_moved` the exhibit. That expires the claim on `repack`'s `continue
# tried for an earlier short sheet`, whose argument is that no exhibit is
met twice with a different list of places.

Workaround: renumber the duplicate before running `repack`.

---

### S1 — `prune_orphans` cuts an orphan whose only content is a legacy picture, an OLE object or a symbol
<!-- status: open -->

Found 2026-09-16 while deciding the fix for the doubled-id entry below,
by asking whether "empty and unreferenced" is ever the wrong test for a
shell. It is, for content Word still writes. `_NOTE_CONTENT_RE` admits
`w:bookmarkStart|w:hyperlink|w:drawing|w:tbl|m:oMath` and misses three
things, measured on constructed notes:

    drawing, a modern image        carriers=1  empty=False  -> kept
    bookmark / hyperlink / OMML    carriers=1  empty=False  -> kept
    pict, a LEGACY VML image       carriers=0  empty=True   -> PRUNED
    object, a LEGACY OLE equation  carriers=0  empty=True   -> PRUNED
    sym, a symbol glyph            carriers=0  empty=True   -> PRUNED
    a tracked DELETION only        carriers=0  empty=True   -> PRUNED

So an orphaned note whose whole content is a legacy picture, or an
Equation Editor 3.0 equation — which is stored as `w:object`, and which
these papers carry — is removed as litter, and `orphans`, which exists
to report the note that KEPT its content as a lost footnote rather than
litter, does not report it. The words of the contract are "drops the
SHELLS"; a note holding an equation is not a shell.

This is on ordinary DISTINCT ids. It is not the doubled-id defect below
and no fix there reaches it: that one is a lookup keyed on the id, this
one is the emptiness test itself.

The `w:delText` row is caller-dependent and should be decided, not
widened blindly: in-package `prune_orphans` runs on the simulated
ACCEPTED view, where deletions are already resolved, so a
deletion-only note there is genuinely empty — but the function is
public, and a caller running it on a raw tracked document would lose
text that a reject would have brought back.

Fix: admit `w:pict`, `w:object` and `w:sym` to the content test, and
decide `w:delText` by the view the caller is on rather than by the tag.

### S1 — `place` sets an exhibit's table flush against another table and reports no problem
<!-- status: open -->

Found 2026-09-16 triaging `placement.py`. A caption that mentions the
OTHER table is read as the second table's own, so the move lands one
`w:tbl` immediately after another with nothing between them:

    in : … 'p:Таблица 1. Первая', 'tbl:a'
    out: … 'p:Таблица 1. Первая', 'tbl:a', 'tbl:b', 'p:Проза.'
    moved: [(1, True, 'Таблица 2. То же, что в таблиц'), …]  problems: []
    audit of the result sees tables: 1 (the input had 2)

The pass reports no problem, and docxkit's own audit then sees ONE
exhibit where the manuscript had two. Two adjacent tables with no
paragraph between them are the shape Word joins into a single table —
worth confirming in Word before the fix is designed, because it decides
whether this is a lost exhibit or only a lost audit.

### S2 — `place` writes a row's revision mark FIRST in `w:trPr`
<!-- status: open -->

Found 2026-09-16, `placement.py`. Every row docxkit marks comes out in
one order:

    place,    row marked ins        trPr children: ['ins', 'cantSplit']
    own_page, row marked ins        trPr children: ['ins', 'tblHeader']
    place,    row marked del        trPr children: ['del', 'cantSplit']
    own_page, row marked trPrChange trPr children: ['trPrChange', 'tblHeader']

`CT_TrPr` extends `CT_TrPrBase`, so the schema's sequence has
`cantSplit` and `tblHeader` first and appends `ins`, `del` and
`trPrChange` after them — the reverse of what is written. Confirm by
opening a marked row in Word (it repairs silently where it can, which
is why no gate here has ever said anything) before deciding whether
this is a repair Word performs or a file it refuses.

### S2 — a marker between a caption and its table hides the exhibit from `place`
<!-- status: open -->

Found 2026-09-16, `placement.py`. One caption, one table, and one
element between them:

    none             place: 1 placement(s); audit tables=1
    bookmarkEnd      place: 0 placement(s); audit tables=0
    commentRangeEnd  place: 0 placement(s); audit tables=0
    XML comment      place: 0 placement(s); audit tables=0

The exhibit list still names `Таблица 1` in all four, so the caption is
found and only the table is lost. A bookmarkEnd there is what a
cross-reference to the caption leaves behind, and a commentRangeEnd is
what a reviewer's comment on it leaves — both are ordinary in a
manuscript under revision, and both make the pass do nothing at all
while saying nothing at all. The paired half of the same probe: a block
that ENDS with its own bookmarkEnd no longer sees the note that follows
it (`note after=None` against `160`).

---

## Where the fixed entries are

Closed entries live in [`BACKLOG-ARCHIVE.md`](BACKLOG-ARCHIVE.md) — 213
of them, under its `## Fixed`, and they are kept: *"did we ever fix
that?"* is a real question later, and several are cited from the papers
by heading. They moved out on 2026-08-30 because this file had become
91 % archive — 11 entries under `## Open` behind 213 closed ones, in
10,792 lines. A backlog is the working list, and the working list could
not be seen.

**`## Fixed` is a heading in the ARCHIVE and nowhere else**, which is
what makes the split gated rather than merely tidy: a closed entry left
in this file has no section it is allowed to sit under, so
`tools/backlog_status.py` fails on it instead of finding it a home.
That section heading is load-bearing — this one is deliberately not
called `## Fixed`.

`tools/backlog_refs.py` reads the pair too: a `Refs BACKLOG.md` commit
counts as recorded once a later commit closes an entry in EITHER file.
