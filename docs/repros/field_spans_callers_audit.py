"""What every `field_spans` caller does when a marker SHARES its run.

One fixture — prose in the `begin` run and in the `end` run, the shape
`remove_outer_field` was losing text on — put through each caller in
src/ that reads `field_spans`.

    python audit_field_spans_callers.py
"""
import sys

W = (r"C:\Users\Ezhik\AppData\Local\Temp\claude\C--Windows-System32"
     r"\498555e3-9088-4382-822f-51d2ea2bd5b7\scratchpad"
     r"\docxkit-fix-fieldspans")
sys.path.insert(0, W + r"\src")

from docxkit import body, edit  # noqa: E402
from docxkit._cite_repair import (  # noqa: E402
    _delete_char,
    remove_outer_field,
    respan_link,
    wrap_link_in_bookmark,
)
from docxkit._xml import field_spans, visible_text  # noqa: E402
from docxkit.edit import _label_spans_in  # noqa: E402
from docxkit.errors import AnchorError  # noqa: E402

BEGIN = '<w:fldChar w:fldCharType="begin"/>'
SEP = '<w:fldChar w:fldCharType="separate"/>'
END = '<w:fldChar w:fldCharType="end"/>'


def field(anchor, label, *, head="As ", tail=" found, the index rose."):
    """A field link whose markers share their runs with prose."""
    return (f'<w:r><w:t xml:space="preserve">{head}</w:t>{BEGIN}</w:r>'
            f'<w:r><w:instrText> HYPERLINK \\l "{anchor}" </w:instrText></w:r>'
            f"<w:r>{SEP}</w:r>"
            f"<w:r><w:t>{label}</w:t></w:r>"
            f'<w:r>{END}<w:t xml:space="preserve">{tail}</w:t></w:r>')


def show(name, fn):
    try:
        out = fn()
    except AnchorError as exc:
        print(f"{name:28} REFUSES: {str(exc)[:88]}")
    except Exception as exc:                      # noqa: BLE001
        print(f"{name:28} RAISED {type(exc).__name__}: {str(exc)[:70]}")
    else:
        print(f"{name:28} {out}")


para = "<w:p>" + field("Smith2020", "(Smith 2020)") + "</w:p>"
print("visible text:", repr(visible_text(para)))
print("field_spans :", [(s, e) for s, e, _ in field_spans(para)],
      " (run boundaries: the span starts before 'As ')")
print()

# 1. _cite_repair.remove_outer_field — SPLICES. Fixed to cut at markers.
nested = ("<w:p>" + '<w:r><w:t xml:space="preserve">As </w:t>' + BEGIN
          + "</w:r>"
          + r'<w:r><w:instrText> HYPERLINK \l "Stale" </w:instrText></w:r>'
          + f"<w:r>{SEP}</w:r>"
          + '<w:hyperlink w:anchor="Fresh"><w:r><w:t>Smith (2020)</w:t>'
          + "</w:r></w:hyperlink>"
          + f'<w:r>{END}<w:t xml:space="preserve"> found.</w:t></w:r>'
          + "</w:p>")
show("remove_outer_field",
     lambda: repr(visible_text(remove_outer_field(nested, "Stale", "Fresh"))))

# 2. _cite_repair.wrap_link_in_bookmark — INSERTS around the span.
def _wrapped():
    out = wrap_link_in_bookmark(para, "Smith2020", "Smith2020txt", 9)
    start = out.index("<w:bookmarkStart")
    shut = out.index("<w:bookmarkEnd")
    return "bookmark covers " + repr(visible_text(out[start:shut]))
show("wrap_link_in_bookmark", _wrapped)

# 3. _cite_repair.respan_link — REBUILDS the paragraph from the span.
show("respan_link",
     lambda: repr(visible_text(respan_link(para, "Smith2020",
                                           "Smith 2020"))))

# 4. _cite_repair._delete_char — guards a run by its span.
show("_delete_char (in prose)",
     lambda: repr(visible_text(_delete_char(para, 2, "s", "audit"))))
show("_delete_char (by a field)",
     lambda: repr(visible_text(_delete_char(para, 3, "(", "audit"))))

# 5. body._templates — masks field spans to find a non-link rPr.
styled = ("<w:p>" + '<w:r><w:rPr><w:b/></w:rPr>'
          + '<w:t xml:space="preserve">As </w:t>' + BEGIN + "</w:r>"
          + r'<w:r><w:instrText> HYPERLINK \l "S" </w:instrText></w:r>'
          + f"<w:r>{SEP}</w:r><w:r><w:t>S</w:t></w:r><w:r>{END}</w:r>"
          + "</w:p>")
show("body.prose_props", lambda: body.prose_props(styled))

# 6. edit.insert_in_para — field spans are a PROTECTED region.
show("insert_in_para (into prose)",
     lambda: repr(visible_text(edit.insert_in_para(para, 2, "X"))))

# 7. edit._label_spans_in — asks which run belongs to a field.
def _labels():
    runs, spans, _ = edit.run_spans(para)
    return [(lab.start, lab.end) for lab in _label_spans_in(para, runs, spans)]
show("edit._label_spans_in", _labels)

# 8. …and what that costs the public writers built on it.
show("edit.replace_in_para",
     lambda: repr(visible_text(edit.replace_in_para(para, "index", "level"))))
show("edit.replace_keeping_links",
     lambda: repr(visible_text(
         edit.replace_keeping_links(para, "index rose", "index fell"))))
