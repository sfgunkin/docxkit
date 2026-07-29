"""Comment injection: the part that replaced Word's O(n^2) Comments.Add."""
from __future__ import annotations

import re
import xml.dom.minidom as MD

import pytest
from conftest import (
    comment,
    dele,
    document,
    ins,
    make_parts,
    para,
    para_mark_ins,
    row,
    run,
    table,
)

from docxkit.comments import GENERIC, RevisionContext, annotate, reclassify
from docxkit.errors import ScaffoldMissing
from docxkit.revisions import spans as revision_spans


def _doc(parts):
    return parts["word/document.xml"].decode("utf-8")


def _com(parts):
    return parts["word/comments.xml"].decode("utf-8")


def _n_comments(parts):
    return len(re.findall(r"<w:comment w:id=", _com(parts)))


def always(text):
    return lambda ctx: text


def test_revision_spans_finds_run_level_revisions():
    xml = document(para(run("keep "), ins("added"), dele("gone")))
    assert len(revision_spans(xml)) == 2


def test_revision_spans_skips_property_level_marks():
    """A self-closing <w:ins/> is an inserted paragraph mark, not a text
    range: it cannot carry a comment anchor."""
    xml = document(para_mark_ins())
    assert revision_spans(xml) == []


def test_revision_spans_mixed_document():
    xml = document(para(run("a"), ins("x"))
                   + para_mark_ins()
                   + para(dele("y")))
    assert len(revision_spans(xml)) == 2


def test_annotate_comments_every_revision():
    parts = make_parts(para(run("keep "), ins("added"), dele("gone")),
                       comment_items=(comment(1, "seed"),))
    added, unclassified = annotate(parts, always("R1: reason"))
    assert (added, unclassified) == (2, 0)
    assert _n_comments(parts) == 3          # seed + 2
    doc = _doc(parts)
    assert doc.count("<w:commentRangeStart") == 2
    assert doc.count("<w:commentRangeEnd") == 2
    assert doc.count("<w:commentReference") == 2


def test_annotate_generic_none_leaves_unmatched_revisions_bare():
    """generic=None comments only what a rule matched.

    Inserting a table makes every cell its own run-level revision; repeating one
    balloon on all of them buries the ones that carry meaning. The caller
    comments the caption and lets the cells pass.
    """
    parts = make_parts(para(run("keep "), ins("matched"), ins("skipme")),
                       comment_items=(comment(1, "seed"),))

    def only_matched(ctx):
        return "A11: reason" if "matched" in ctx.text else None

    added, unclassified = annotate(parts, only_matched, generic=None)
    assert (added, unclassified) == (1, 1)
    assert _n_comments(parts) == 2          # seed + the one matched
    doc = _doc(parts)
    assert doc.count("<w:commentRangeStart") == 1
    assert "skipme" in doc                  # the revision itself survives
    for name in ("word/comments.xml", "word/commentsExtended.xml",
                 "word/commentsIds.xml"):
        MD.parseString(parts[name].decode("utf-8"))


def test_annotate_generic_string_still_comments_everything():
    """The default is unchanged: unmatched revisions get the generic text."""
    parts = make_parts(para(run("keep "), ins("matched"), ins("skipme")),
                       comment_items=(comment(1, "seed"),))

    def only_matched(ctx):
        return "A11: reason" if "matched" in ctx.text else None

    added, unclassified = annotate(parts, only_matched, generic="fallback")
    assert (added, unclassified) == (2, 1)
    assert "fallback" in parts["word/comments.xml"].decode("utf-8")


def test_annotate_output_is_well_formed_everywhere():
    parts = make_parts(para(run("keep "), ins("added"), dele("gone")),
                       comment_items=(comment(1, "seed"),))
    annotate(parts, always("R1: reason"))
    for name in ("word/document.xml", "word/comments.xml",
                 "word/commentsExtended.xml", "word/commentsIds.xml",
                 "word/commentsExtensible.xml"):
        MD.parseString(parts[name].decode("utf-8"))


def test_annotate_anchors_and_definitions_agree():
    parts = make_parts(para(ins("a"), dele("b")),
                       comment_items=(comment(1, "seed"),))
    annotate(parts, always("R1"))
    doc, com = _doc(parts), _com(parts)
    starts = set(re.findall(r'<w:commentRangeStart w:id="(\d+)"', doc))
    ends = set(re.findall(r'<w:commentRangeEnd w:id="(\d+)"', doc))
    defined = set(re.findall(r'<w:comment w:id="(\d+)"', com))
    assert starts == ends
    assert starts <= defined, "an anchor with no comment definition"


def test_annotate_side_parts_stay_in_step():
    parts = make_parts(para(ins("a"), dele("b")),
                       comment_items=(comment(1, "seed"),))
    annotate(parts, always("R1"))
    n = _n_comments(parts)
    ext = parts["word/commentsExtended.xml"].decode("utf-8")
    ids = parts["word/commentsIds.xml"].decode("utf-8")
    assert len(re.findall(r"<w15:commentEx ", ext)) == n
    assert len(re.findall(r"<w16cid:commentId ", ids)) == n


def test_annotate_is_idempotent():
    """Re-running must not double-comment: already-anchored revisions skip."""
    parts = make_parts(para(ins("a"), dele("b")),
                       comment_items=(comment(1, "seed"),))
    annotate(parts, always("R1"))
    first = _n_comments(parts)
    added, _ = annotate(parts, always("R1"))
    assert added == 0
    assert _n_comments(parts) == first


def test_annotate_reports_unclassified_and_uses_generic():
    parts = make_parts(para(ins("a")), comment_items=(comment(1, "seed"),))
    added, unclassified = annotate(parts, lambda ctx: None)
    assert (added, unclassified) == (1, 1)
    assert GENERIC in _com(parts)


def test_annotate_requires_a_word_made_scaffold():
    parts = make_parts(para(ins("a")))
    parts["word/comments.xml"] = b"<w:comments/>"
    with pytest.raises(ScaffoldMissing, match="scaffold"):
        annotate(parts, always("R1"))


def test_classifier_receives_useful_context():
    body = (para(run("Prose about displacement. "), ins("conditional"))
            + table(row("Country", "Dif."), row("Poland", "0.02")))
    parts = make_parts(body, comment_items=(comment(1, "seed"),))
    seen: list[RevisionContext] = []

    def classify(ctx):
        seen.append(ctx)
        return "R2"

    annotate(parts, classify)
    ctx = seen[0]
    assert ctx.text == "conditional"
    assert "displacement" in ctx.para
    assert ctx.table_index is None
    assert "displacement" in ctx.haystack


def test_classifier_sees_the_table_index():
    """A revision inside table 1 must be reported as table 1, so a rule can
    say "this is the decomposition table" without guessing from prose."""
    revised_cell = "<w:tc>" + para(ins("Difference")) + "</w:tc>"
    body = (table(row("untouched"))
            + f"<w:tbl><w:tr>{revised_cell}</w:tr></w:tbl>"
            + para(run("after the tables")))
    parts = make_parts(body, comment_items=(comment(1, "seed"),))
    seen: list[RevisionContext] = []

    def classify(ctx):
        seen.append(ctx)
        return "R6"

    annotate(parts, classify)
    assert len(seen) == 1
    assert seen[0].table_index == 1


def test_reclassify_repairs_generic_comments():
    parts = make_parts(para(ins("a")), comment_items=(comment(1, "seed"),))
    annotate(parts, lambda ctx: None)          # everything generic
    assert GENERIC in _com(parts)
    done, still = reclassify(parts, always("R8: repaired"))
    assert done >= 1 and still == []
    assert "R8: repaired" in _com(parts)


def test_reclassify_is_a_noop_when_nothing_is_generic():
    parts = make_parts(para(ins("a")), comment_items=(comment(1, "seed"),))
    annotate(parts, always("R1"))
    assert reclassify(parts, always("other")) == (0, [])
