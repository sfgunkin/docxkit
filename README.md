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

from docxkit.compare import compare, render      # multi-layer diff
from docxkit.tracked import build                # redline deliverable
from docxkit.ingest import build_overrides       # author-edit round
from docxkit.comments import annotate            # comment every revision
from docxkit.word import session, export_pdf     # Word automation
```

| Module | What it is for |
|---|---|
| `package` | read/write/edit the .docx package; lock checks; numbered backups |
| `find` | locate paragraphs, tables, captions **by visible text** |
| `edit` | anchor-asserting replace, run-aware replace, `xml:space` repair |
| `compare` | the authoritative multi-layer diff (structure/text/formula/format/glyph/fields/integrity) |
| `citations` | citation ↔ reference back-link audit |
| `word` | Word COM: compare, PDF export, page counts, Flat OPC bypass |
| `comments` | attach a comment to every tracked revision, in XML |
| `tracked` | build a tracked-changes deliverable end to end |
| `ingest` | fold the author's Word edits back into the build source |
| `word_edits` | docx-vs-python-docx-script change table (secondary) |

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

## Tests

```
python -m pytest        # synthetic fixtures, no Word required
```

Word-dependent paths (`tracked.build`, `word.export_pdf`, `word.pages`)
are exercised against real manuscripts rather than in the unit suite.
