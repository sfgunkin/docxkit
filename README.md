# docxkit

Shared tooling for Word manuscripts, factored out of the per-paper scripts
that kept being rewritten (AFI, Life Expectancy, Loneliness Index, DSI,
FLOPs, Parental Style). Before this, `flatopc_to_docx.py` existed twice
byte-for-byte, four projects had their own `read_parts`/`write_docx`, and
two disagreed about how to produce tracked changes.

```
pip install -e D:\docxkit          # already installed; editable
```

## Why not python-docx

python-docx drops what it does not model. Saving through it **loses
comments**, and it cannot see text inside `<w:ins>` at all — a tracked
insertion reads back as an empty paragraph. Everything here works on the
package parts dict, so untouched parts survive byte-for-byte.

## The API

```python
from docxkit import read_parts, write_docx, edit_in_place, backup
from docxkit import text_of, para_slice, rep, replace_in_para

from docxkit.tables import read_all, find, by_caption   # manuscript tables
from docxkit.equations import latex_to_omml, harvest   # equations
from docxkit.testing import latest_version, load_xml  # value-test scaffolding
from docxkit.compare import compare, render      # multi-layer diff
from docxkit.revisions import text, counts       # read either side of a redline
from docxkit.tracked import build                # redline deliverable
from docxkit.ingest import build_part_overrides  # author-edit round
from docxkit.ingest import apply_part_overrides #   …and its writer
from docxkit.comments import annotate            # comment every revision
from docxkit.word import session, export_pdf     # Word automation
from docxkit.word import locate                  # page/line of a phrase
from docxkit.errors import DocxKitError          # everything catchable
```

| Module | What it is for |
|---|---|
| `batch` | a set of edits as ONE gated unit of work: preflight every anchor at once, apply, hold the carriers (bookmarks, links, footnote marks, math, rows, drawings) unless the batch declares what it moves |
| `package` | read/write/edit the .docx package; lock checks; numbered backups |
| `find` | locate paragraphs, tables, captions **by visible text**; the linear body walk; `site` surveys an edit anchor before you write the edit |
| `edit` | anchor-asserting replace, run-aware replace and INSERT, link relabel, span italics, `xml:space` repair |
| `body` | build new content: paragraphs, grouped-header tables, guarded insertion; `prose_props` clones a paragraph's style without a link's |
| `revisions` | read tracked changes; accept/reject, wholesale or by predicate (`by_author`, `whitespace_only`) |
| `tables` | locate/read manuscript tables on either side of a redline; `update` rebuilds one from data, formatting preserved; `reorder_rows` / `clone_row` / `set_row` move and fill ROWS, gated on the row multiset; `house` sets the paper's style in one call |
| `equations` | LaTeX→OMML via Word's own XSL, and OMML→LaTeX back (`to_latex`); harvest, fingerprints, run `face` |
| `testing` | scaffolding for the paper value-test suites (latest version, lock-safe loads, prose numbers) |
| `figures` | find figures by caption, replace images safely, extents, landscape sections, alt-text audit/setter |
| `compare` | the authoritative multi-layer diff (structure/text/formula/formula-typography/format/glyph/fields/integrity) over EVERY part a reader sees — body, footnotes, endnotes, headers, footers, comments — with each entry addressed to its part and table cell. FORMAT covers emphasis **and size and colour**, resolved through `styles.Cascade` rather than read off the run |
| `styles` | named styles: read, remap, apply a journal template — and `Cascade`, what a run's properties RESOLVE to once the style chain and docDefaults are applied |
| `footnotes` | locate/append, and remap ids Word renumbered on save |
| `hygiene` | drop part-trees a manuscript should not carry; `smarten` straight quotes safely |
| `citations` | the grammar, the link audit, and `link_all` — build the whole citation<->entry apparatus document-wide |
| `refstyle` | reference/citation FORMAT audit against the house author-date style (initials, "(2020).", en-dashes, order, cited↔listed); `HOUSE` and `CHICAGO` presets; `convert` writes the mechanical half back, proving the entry unchanged |
| `crossrefs` | bidirectional figure/table links, the bookmark convention |
| `renumber` | shift exhibit numbers: captions, mentions, bookmarks, REF fields, single-pass; and footnote ids back into reference order |
| `wordcount` | words per bucket (prose/tables/captions/footnotes/references/appendix) for journal caps |
| `export` | the manuscript as markdown: headings, pipe tables, `$...$` math, footnotes and endnotes |
| `styles` | read styles; apply a journal template's styles.xml with id remap and a dangling audit |
| `word` | Word COM: compare, PDF export, page counts, page/line lookup, Flat OPC bypass; `shared_session` spends one cold start on a whole ladder |
| `pages` | what the RENDER says: blank sheets, printed numbers, orientation |
| `comments` | comment every tracked revision; read threads/done flags, resolve (`set_done`) |
| `authors` | who is credited with the changes: read them, or restamp every revision, comment, people entry and document property to one name |
| `tracked` | build a tracked-changes deliverable end to end |
| `guard` | stop a rebuild discarding a review someone made in Word; `restamp` records a repair the TOOL made, which is not a review |
| `ingest` | fold the author's Word edits back into the build source, part by part — a footnote the author retyped is an override too |
| `lint` | structural checks for the markup Word refuses to open (ported from DSI) |
| `console` | UTF-8 stdout, guarded — a bare reconfigure crashes off-console |
| `errors` | `DocxKitError` and friends — a library never calls `SystemExit` |
| `_xml` | internal: the WordprocessingML primitives, defined once |
| `_compare_read` / `_compare_diff` / `_compare_render` | internal: the diff's three layers — a package to paragraphs, paragraphs to a report, a report to a page. `compare` is the facade |
| `placement` | where a table SITS: anchored beside the paragraph that first mentions it, kept whole on one sheet — the XML half here, the page half measured by Word; `exhibit_block` is one exhibit's span, section break included |
| `probe` | the four facts a batch has to know first: which FORM the links take, where the exhibit blocks and section breaks sit, which bookmarks are body-level, how a phrase is split across runs |
| `revision` | the single-file protocol: one manuscript — the author's own file, named in `paper.toml` — two states read off the file itself, and the gate ladder between a proposal and the truth |
| `cli` | the `docxkit` command line — the one-off jobs, without a throwaway script |
| `_cite_grammar` / `_cite_audit` / `_cite_build` / `_cite_repair` | internal: the citation apparatus in four layers — what a citation LOOKS like, what is WRONG with a document's, how to BUILD the links, and the bookmark/hyperlink surgery each repair is made of. `citations` is the facade |
| `_table_core` / `_table_layout` | internal: reading a manuscript table and rewriting its VALUES, and measuring one to set how it LOOKS. They share the `Table` type and nothing else; `tables` is the facade |

## CLI

```
docxkit compare BUILT.docx EDITED.docx [--expect-clean] [--json report.json]
docxkit citations PAPER.docx
docxkit link PAPER.docx [--write] [--only NAME,...] [--alias "WHO=WHO"]
docxkit linkfix PAPER.docx                 # audit findings -> proposed repair plan
docxkit refstyle PAPER.docx [--chicago] [--json R.json]
docxkit crossrefs PAPER.docx [--write] [--audit]   # exhibits <-> their first mention
docxkit inspect PAPER.docx [--comments] [--revisions]
docxkit lint PAPER.docx                    # structural checks, no Word needed
docxkit probe PAPER.docx [ANCHOR...]       # link form, exhibit blocks, run splits
docxkit math PAPER.docx [--check]          # symbols typeset as prose, not OMML
docxkit locate PAPER.docx ANCHOR... [--ordered] [--json R.json]
docxkit locate PAPER.docx --revisions [--limit N]
docxkit api [TOPIC] [--signatures]   # the public surface by subject
docxkit sites PAPER.docx "sig" [--part body|footnotes]  # what an edit meets
docxkit text PAPER.docx [--tracked final|original] [--md]
docxkit count PAPER.docx [--exclude references,tables,...] [--limit N]
docxkit tasks PAPER.docx [--all] [--check] [--done ID,ID]
docxkit figures PAPER.docx [--check]
docxkit footnotes PAPER.docx [--check]      # the size they agree on, and who does not
docxkit authors PAPER.docx [--set NAME] [--only A,B] [--initials XX] [--write]
docxkit smarten PAPER.docx [--write]
docxkit pdf PAPER.docx OUT.pdf [--pages 1-3]
docxkit pages PAPER.docx [--sheets] [--check]
docxkit verify PAPER.docx                  # does Word read this back unchanged?
```

The single-file protocol has a family of its own — one manuscript, two
recorded states, and a gate ladder between them. `init` adopts the
author's file where it is, under its own name; `revision/` beside it
holds the machinery, and `paper.toml` is the one line that says which
file is the paper:

```
docxkit revision init MANUSCRIPT.docx      # scaffold around it, in place
docxkit revision status                    # truth or proposal? (1 pending, 4 stale)
docxkit revision status --all              # every registered paper, one line each
docxkit revision status --all --scan DIR   # find papers under DIR and add them
docxkit revision doctor                    # who else in the repo selects a manuscript
docxkit revision ingest [--check] [--json R.json]   # what the author changed
docxkit revision build                     # clean edit -> redline, via Word Compare
docxkit revision validate [BATCH] [--no-word] [--render ANCHOR...]
docxkit revision ship REVISED.docx          # both, in one Word session
docxkit revision promote                   # put a validated batch on the paper
docxkit revision baseline                  # the author accepted: record the truth
docxkit revision rescues                   # the undo copies promote leaves behind
```

`validate` runs the ladder; `--render` adds the one gate no markup check
can make, rasterising the ACCEPTED page each anchor falls on so a person
can look at it.

## The expensive lessons, encoded

These are in the code with comments; they are why the modules look the way
they do.

- **Never index `Document.Revisions(i)` in a loop.** That collection is
  O(i) inside Word. Measured on a 316-revision compare: **280.3s** to scan
  by index versus **5.9s** through the enumerator, same result set. The
  indexed loop also eventually provoked *"Call was rejected by callee"*.
  `word.revisions()` uses the enumerator.
- **`Comments.Add` is O(n²) in practice** — ~0.5s per call at the 50th
  comment, ~3.4s at the 250th. Three hundred comments cost 15–20 minutes.
  `comments.annotate()` writes them into the package instead: ~1s. Word
  still does the diff (~3.5s); it just does not do the annotation.
- **Word sometimes cannot serialize tracked math — but check before
  believing it.** `SaveAs2` and `Content.WordOpenXML` have both raised
  *"A file error has occurred"* on a compare result containing equation
  changes, which is why `tracked.build` accepts those revisions first
  (commenting them while they still exist). On LI7 (2026-08-15) BOTH
  routes serialized 1870 revisions with the math left tracked, and both
  round-tripped exactly, while resolving the math cost 315 revisions —
  a revision only has to *overlap* an equation to be accepted, and
  `Accept()` applies its whole span. Hence `build(..., resolve_math=
  False)` / `revision build --keep-math`: every accepted revision is one
  the author can no longer refuse, so measure before paying that.
- **Reject-all is the gate, not the count.** `tracked.build` refuses to
  publish a redline whose reject-all does not reproduce the original
  (`tracked.untracked` names the paragraphs). Nothing else sees that
  failure: the package lints, opens, verifies in Word and counts
  plausibly while carrying edits the author was never offered.
- **Word's Compare empties `docProps/core.xml`.** The part comes back
  holding `lastModifiedBy`/`revision`/`created`/`modified` and nothing
  the document said about itself, so a part-level check passes with the
  title, author and keywords gone — LI7's `dc:title` was missing for
  four days, twice. Metadata is not tracked-changeable, so no redline
  can show it. `hygiene.carry_properties` copies the fields back (never
  the timestamps); `tracked.build` calls it.
- **Word's save path can hang** outright, on any drive. `extract_flat_opc`
  + `flat_opc_to_docx` bypass it. `ExportAsFixedFormat` (PDF) still works.
- **A page number belongs to the file it was measured in.** A redline
  paginates longer than its clean twin, because the deleted text is still
  laid out — le14: 47 pages against 41 — and no markup setting changes
  that (`ShowRevisionsAndComments=False`, `RevisionsFilter.Markup=0` and
  `RevisionsView=Final` all still measured 47). Page numbers for a
  response letter come from the clean build.
- **Page numbers need `Repaginate()` first, and a collapsed range.**
  `session(fast=True)` switches background pagination off, so an untouched
  document answers from a stale layout (le14_clean's end reported page 3
  before repaginating, 41 after), and `Information()` answers for a
  range's ACTIVE END — ask a whole document and you get its last page.
  `word.locate` handles both.
- **Word's Find raises rather than misses**: an unescaped `^` is "not a
  valid special character" and anything over 255 characters is "String
  parameter too long". It also cannot match across a paragraph mark, and
  a revision's text often STARTS with the paragraph mark it inserted.
  `word.search_text` normalizes an anchor into what Find accepts (first
  non-blank line, carets escaped, cut to 255 as Word counts it).
- **The COM cost is fresh objects, not dynamic name lookup.** makepy
  static binding measured no gain at all over win32com's dynamic dispatch
  (5.8s vs 5.9s per 150 revisions, identical results) — but a Find
  configured from scratch on a new Range costs ~105 ms per anchor against
  ~52 ms through one reused Range/Find pair re-aimed with `SetRange`.
  `locate` keeps one pair; the per-revision walk was measured both ways
  and does not care (~55 ms/revision either way — that cost is Word's).
- **Hand-authored `w:ins`/`w:del` has repeatedly failed to open in Word.**
  Produce redlines with `CompareDocuments`, not by writing the markup.
- **Anchor on visible text, never raw XML.** Word fragments runs at rsid
  boundaries, so "Figure 6" is often stored as `Figur` + `e` + ` 6`.
- **A bare `<w:t>` with a leading/trailing space gets trimmed** by Word on
  every open+save, so the space reappears as a phantom author edit each
  round. `preserve_space()` fixes it at build time.
- **A run-aware replace whose match starts in a hyperlink run bleeds into
  the link** and no text diff will show it. `replace_in_para` refuses, and
  the refusal names `allow_hyperlink=True` — retitling a link is a real
  operation, and `edit.relabel_link(para, anchor, new_label)` is its verb:
  same anchor, new words, addressed by ANCHOR so a paragraph that also says
  those words in prose is not the one rewritten.
- **Word renumbers footnote ids on save**, so an author's paragraph XML
  cannot be spliced raw — `ingest` remaps ids by definition text.
- **A self-closing `<w:ins/>` is a property-level mark** (paragraph mark,
  table row), not a text range, and cannot carry a comment anchor.
- **A paragraph-mark revision MERGES paragraphs**, and Compare also emits
  `w:moveFrom`/`w:moveTo`. Simulating accept/reject without those gives
  wrong answers on a good deliverable — on LE it made a bibliography
  entry look truncated and the paragraph counts 928 vs 926.
- **A comment lives in six parts**, chained id→paraId→durableId. Deleting
  only the definition leaves dangling anchors: `comments.remove`.
- **Reading a redline's tables through python-docx silently loses every
  changed cell** — it returns `''` where the text is an insertion. On the
  AFI paper, Table 4's revised header reads `''` via python-docx and
  `Difference` via `tables.read_all`. Use `tables`, and pick a `view`.
- **Never hand-assemble OMML from LaTeX.** Go through `latex2mathml` then
  Word's own `MML2OMML.XSL` (`math.latex_to_omml`). When an equation
  reuses symbols already in the document, `math.harvest` the live element
  and deepcopy it — the only way to guarantee it renders identically.
- **What a run STATES is not what it renders.** Word deletes a direct
  property equal to the value it would inherit — measured: its Compare
  dropped a `w:sz 20` from a run whose paragraph style already said 20.
  So a stated-value comparison reports a change on documents that render
  identically, and misses the mirror case (a run that stated 10pt and now
  inherits the 12pt default). Resolve through `styles.Cascade`: direct
  run properties, then the character style chain, then the paragraph
  style chain, then docDefaults.
- **A bare `<m:oMath>` is INLINE to Word**, however alone in its paragraph
  it sits; display is `<m:oMathPara>`, and Word promotes a lone one on
  save *sometimes* — measured, one equation of four. `equations.display`
  sets it, and `docxkit math` reports the ones still inline. An
  `oMathPara` must be the ONLY content of its paragraph: a trailing run —
  an equation number, a comma — has Word demote it back on the next save,
  which is also measured, so `display` refuses one rather than writing
  markup Word will undo.
- **A note is not always a footnote.** Word keeps two note stores, and
  which one a manuscript uses is the journal's house style rather than
  anything about the paper. Half this package read `word/footnotes.xml`
  and nothing else — including the accept/reject gates, which SIMULATE
  all three text parts and compared two of them, so a defect Word's
  Compare left in an endnote passed a build silently. `tracked`,
  `refstyle`, `export`, `wordcount`, `probe`, `compare` and — since
  2026-08-20, writer and audit together — the citation apparatus read
  both now. `tests/test_note_parts.py` is what keeps that list from
  growing back: its `BLIND` set is empty, and a reader may not join it
  without a test failing. `ingest.build_overrides` is the one reader
  left that is body-only, and its blindness is a different shape (an
  edit inside ANY note definition, not one part against the other).
- **A cell can contain a table.** `w:tc` is not a leaf, so a `re.sub`
  over one finds the INNER cells' properties: `fit_columns` wrote an
  outer column's width — 1178 dxa — into a nested table's 300 dxa cell
  whenever the outer cell stated no width of its own, and put the
  properties element inside the nested table when it had no `w:tcPr`
  either. The same shape one level up cost the outer table its
  `tblLayout` and cell margins. Anything that asks a table or a cell
  about ITS OWN properties goes through `_own_grid` / `_own_tblpr` /
  `_own_tcpr`, which stop at the first row or the first child.
- **A rebuild must not overwrite a deliverable someone reviewed in Word.**
  `tracked.build` stamps what it produced and refuses if the file changed.
- **A caption sits ABOVE what it names — usually.** Two of AFI's six
  table captions sit underneath, so `tables.by_caption` treats the
  convention as a preference and the document's other captions as the
  evidence: a table with ANOTHER caption between it and this one belongs
  to that one, and if both sides are ruled out it raises rather than
  handing back a neighbour.
- **A figure caption sits ABOVE its image**, one figure can be several
  images (AFI's Figure 5 is three Lorenz curves), and replacing image
  bytes changes *every* drawing sharing that relationship — AFI's Figures
  8/11/12 all pointed at `image10`. `figures.replace_image` refuses until
  you say whether to isolate.

## Tests

```
python -m pytest        # synthetic fixtures, no Word required
python -m pytest -m word   # the width model, measured against real Word
python tools/coverage_floor.py             # per-module floors, a ratchet
python tools/sweep.py <project-root> ...   # every routine over real papers
python -m ruff check .
python -m mypy          # package + tests; word_edits exempt, nothing else
python -m pyright       # what Pylance shows in the editor; no exemptions
```

`_xml.py` exists because the primitives had already started to drift: the
glyph table lived in both `compare` and `ingest` and disagreed about
U+00A0, so `--expect-clean` called a non-breaking-space change a Word
artifact while `build_overrides` wrote it into the source as an author
edit. One table now, one `visible_text`, one run-text writer.

Word-dependent paths (`tracked.build`, `word.export_pdf`, `word.pages`)
are exercised against real manuscripts rather than in the unit suite.

The one exception is the column-width model, which now has Word itself
as its oracle: `docxkit.word.ruler` asks how wide Word ACTUALLY lays text
out, and `tests/test_width_model.py -m word` holds every metric table to
that answer. It was worth building — the tables had been hand-tuned from
a single PDF render, and the first run found Arial's K, P and "!" wrong
(the last two missing entirely, taking a 600 fallback), every Arial
Narrow override too wide (digits by 9.9%), and four alias scales out by
3-5%.

`tools/sweep.py` runs every read-only routine over a corpus and reports
failures, implausible results and timings. It is read-only and copies
each file to TEMP, so it cannot touch a manuscript. The last full run
covered **347 documents across ten projects with zero failures**; the
three bugs it found first time round (a BOM, undeclared namespace
prefixes in fragments, nested tables) are pinned in
`tests/test_corpus_regressions.py`.

One of its routines is `compare.self`: a document diffed against
**itself**, which must report nothing. It is the cheapest false-positive
gate the authoritative diff has, and it earned its place immediately —
on the run that widened `compare` past `document.xml` it caught a
Word-written `endnotes.xml` holding only separator entries being
reported as a whole part gained. Measured clean on 499 manuscripts.
