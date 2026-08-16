"""¶N means the same paragraph whoever prints it.

Nineteen sites across eight modules format a paragraph number for a
report line. They were examined on 2026-08-16 as a candidate for
extraction and left alone: every one agrees, `crossrefs` and `equations`
carry an already-1-based number so their missing `+ 1` is correct, and a
shared formatter would have moved a display convention without removing
any arithmetic — each site computes its own `i`.

What was NOT stated anywhere is the property that makes those sites
worth keeping consistent: an author reading "¶4" from one command and
"¶4" from another must be sent to the SAME paragraph. Nothing enforces
that; it holds because every module enumerates with `PARA_RE`, and
`PARA_RE` skips a self-closing `<w:p/>` on purpose. Change what counts
as a paragraph in one of them and the tools quietly disagree.
"""
from __future__ import annotations

from conftest import make_parts, para, run

from docxkit.citations import link_all
from docxkit.refstyle import audit as refstyle_audit

TARGET = 4      # 1-based, the paragraph both tools should name


def _document(before: str = "") -> dict[str, bytes]:
    return make_parts(
        before
        + para(run("First paragraph."))
        + para(run("Second paragraph."))
        + para(run("Third paragraph."))
        + para(run("A point (Nobody 1999) and (Smith & Jones 2020) here."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal.")))


def test_citations_and_refstyle_name_the_SAME_paragraph():
    parts = _document()

    cited = link_all(parts).unmatched
    issues = refstyle_audit(parts).issues

    assert cited == [f"'Nobody 1999' (¶{TARGET})",
                     f"'Smith & Jones 2020' (¶{TARGET})"], cited
    assert {i.where for i in issues if i.code == "missing-ref"} == \
        {f"¶{TARGET}"}, [(i.code, i.where) for i in issues]


def test_an_EMPTY_paragraph_shifts_nobody_s_count():
    """`PARA_RE` skips `<w:p/>` deliberately — 28 of 399 manuscripts hold
    one, and counting them would renumber every finding after it. The
    point here is that the skip is uniform: one tool counting it and
    another not is worse than either choice.
    """
    parts = _document(before="<w:p/>")

    cited = link_all(parts).unmatched
    issues = refstyle_audit(parts).issues

    assert cited == [f"'Nobody 1999' (¶{TARGET})",
                     f"'Smith & Jones 2020' (¶{TARGET})"], cited
    assert {i.where for i in issues if i.code == "missing-ref"} == \
        {f"¶{TARGET}"}, [(i.code, i.where) for i in issues]
