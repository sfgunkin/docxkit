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
from docxkit.math import latex_to_omml, harvest   # equations
from docxkit.testing import latest_version, load_xml  # value-test scaffolding
from docxkit.compare import compare, render      # multi-layer diff
from docxkit.revisions import text, counts       # read either side of a redline
from docxkit.tracked import build                # redline deliverable
from docxkit.ingest import build_overrides       # author-edit round
from docxkit.comments import annotate            # comment every revision
from docxkit.word import session, export_pdf     # Word automation
from docxkit.errors import DocxKitError          # everything catchable
```

| Module | What it is for |
|---|---|
| `package` | read/write/edit the .docx package; lock checks; numbered backups |
| `find` | locate paragraphs, tables, captions **by visible text** |
| `edit` | anchor-asserting replace, run-aware replace, `xml:space` repair |
| `revisions` | read tracked changes: spans, counts, accepted/rejected views |
| `tables` | locate/read/rewrite manuscript tables, on either side of a redline |
| `math` | LaTeX→OMML via Word's own XSL, harvest existing equations, formula fingerprints |
| `testing` | scaffolding for the paper value-test suites (latest version, lock-safe loads, prose numbers) |
| `compare` | the authoritative multi-layer diff (structure/text/formula/format/glyph/fields/integrity) |
| `citations` | citation ↔ reference back-link audit |
| `word` | Word COM: compare, PDF export, page counts, Flat OPC bypass |
| `comments` | attach a comment to every tracked revision, in XML |
| `tracked` | build a tracked-changes deliverable end to end |
| `ingest` | fold the author's Word edits back into the build source |
| `word_edits` | docx-vs-python-docx-script change table (secondary) |
| `errors` | `DocxKitError` and friends — a library never calls `SystemExit` |
| `_xml` | internal: the WordprocessingML primitives, defined once |

## CLI

```
docxkit compare BUILT.docx EDITED.docx [--expect-clean] [--json report.json]
docxkit citations PAPER.docx
docxkit inspect PAPER.docx [--comments] [--revisions]
docxkit text PAPER.docx [--tracked final|original]
docxkit pdf PAPER.docx OUT.pdf [--pages 1-3]
docxkit pages PAPER.docx
```

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
- **Word cannot serialize tracked math.** `SaveAs2` and
  `Content.WordOpenXML` both raise *"A file error has occurred"* on a
  compare result containing equation changes. Accept those revisions first
  (comment them while they still exist), then extract.
- **Word's save path can hang** outright, on any drive. `extract_flat_opc`
  + `flat_opc_to_docx` bypass it. `ExportAsFixedFormat` (PDF) still works.
- **Hand-authored `w:ins`/`w:del` has repeatedly failed to open in Word.**
  Produce redlines with `CompareDocuments`, not by writing the markup.
- **Anchor on visible text, never raw XML.** Word fragments runs at rsid
  boundaries, so "Figure 6" is often stored as `Figur` + `e` + ` 6`.
- **A bare `<w:t>` with a leading/trailing space gets trimmed** by Word on
  every open+save, so the space reappears as a phantom author edit each
  round. `preserve_space()` fixes it at build time.
- **A run-aware replace whose match starts in a hyperlink run bleeds into
  the link** and no text diff will show it. `replace_in_para` refuses.
- **Word renumbers footnote ids on save**, so an author's paragraph XML
  cannot be spliced raw — `ingest` remaps ids by definition text.
- **A self-closing `<w:ins/>` is a property-level mark** (paragraph mark,
  table row), not a text range, and cannot carry a comment anchor.
- **Reading a redline's tables through python-docx silently loses every
  changed cell** — it returns `''` where the text is an insertion. On the
  AFI paper, Table 4's revised header reads `''` via python-docx and
  `Difference` via `tables.read_all`. Use `tables`, and pick a `view`.
- **Never hand-assemble OMML from LaTeX.** Go through `latex2mathml` then
  Word's own `MML2OMML.XSL` (`math.latex_to_omml`). When an equation
  reuses symbols already in the document, `math.harvest` the live element
  and deepcopy it — the only way to guarantee it renders identically.
- **A rebuild must not overwrite a deliverable someone reviewed in Word.**
  `tracked.build` stamps what it produced and refuses if the file changed.

## Tests

```
python -m pytest        # 66 tests, synthetic fixtures, no Word required
python -m ruff check .
python -m mypy          # config in pyproject; ported modules exempt
```

`_xml.py` exists because the primitives had already started to drift: the
glyph table lived in both `compare` and `ingest` and disagreed about
U+00A0, so `--expect-clean` called a non-breaking-space change a Word
artifact while `build_overrides` wrote it into the source as an author
edit. One table now, one `visible_text`, one run-text writer.

Word-dependent paths (`tracked.build`, `word.export_pdf`, `word.pages`)
are exercised against real manuscripts rather than in the unit suite.
