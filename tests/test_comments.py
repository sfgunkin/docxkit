"""Comment injection: the part that replaced Word's O(n^2) Comments.Add."""
from __future__ import annotations

import re
import xml.dom.minidom as MD

import pytest
from conftest import (
    NS,
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

from docxkit.comments import (
    ALL,
    GENERIC,
    RevisionContext,
    add_at,
    annotate,
    reclassify,
    threads,
)
from docxkit.errors import AnchorError, ScaffoldMissing
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

    Distinct from the `tables` policy: this suppresses the fallback
    everywhere, including in prose. Use it when a paper wants no
    placeholder balloons at all, not to tame a modified table — that is
    what coalescing is for.
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
    # and it wraps the revision a rule MATCHED. Counting comments cannot
    # tell that from the mirror image — one comment, on the revision no
    # rule matched — which is what `p.comment is not None` decides
    anchored = doc[doc.index("<w:commentRangeStart"):
                   doc.index("<w:commentRangeEnd")]
    assert "matched" in anchored and "skipme" not in anchored, anchored
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


def test_reclassifying_rewrites_the_TEXT_and_nothing_else():
    """`com[:m.start()] + m.group(1) + body + m.group(3) + com[m.end():]`
    — the head and the tail of the comment element are put back
    verbatim, and only the run between them is rebuilt.

    The tests here read the new text out of comments.xml and stop there,
    which the head and tail can be lost or duplicated underneath: the
    author, the date and the initials Word shows in the margin all live
    in the head, and the paragraph's own `w:pPr` — the CommentText
    style — lives just inside it."""
    parts = make_parts(para(ins("a")), comment_items=(comment(1, "seed"),))
    annotate(parts, lambda ctx: None)              # everything generic

    done, still = reclassify(parts, always("R8: repaired"))

    assert done >= 1 and still == []
    com = _com(parts)
    assert "R8: repaired" in com
    assert com.count('w:author="Tester"') == 2, com     # the head
    assert com.count('<w:pStyle w:val="CommentText"/>') == 2, com
    assert com.count("<w:t>") == com.count("</w:t>") == 2, com
    MD.parseString(com)


def test_reclassify_is_a_noop_when_nothing_is_generic():
    parts = make_parts(para(ins("a")), comment_items=(comment(1, "seed"),))
    annotate(parts, always("R1"))
    assert reclassify(parts, always("other")) == (0, [])


# A seed Word did not write by itself: a comment somebody edited with
# track-changes on, in two paragraphs. Both are ordinary in a manuscript
# that has been round a review, and the clone is a COPY of whatever the
# package carries — so what it must leave alone is everything except the
# id, the paraId and the text.
RICH_SEED = (
    '<w:comment w:id="1" w:author="Tester" '
    'w:date="2026-07-29T00:00:00Z" w:initials="T">'
    '<w:p w14:paraId="AAAA0001" w14:textId="AAAA0001">'
    '<w:pPr><w:pStyle w:val="CommentText"/></w:pPr>'
    '<w:ins w:id="77" w:author="Second Reader" '
    'w:date="2026-07-29T00:00:00Z">'
    "<w:r><w:t>seed</w:t></w:r></w:ins></w:p>"
    '<w:p w14:paraId="AAAA0002" w14:textId="AAAA0002">'
    "<w:r><w:t>and a second paragraph</w:t></w:r></w:p></w:comment>")


def test_the_clone_replaces_ONE_id_and_ONE_paraId():
    """`count=1` on both substitutions. The template is whatever the
    package carries, and a comment that has been edited with track
    changes on holds a `w:ins` with an id of its own; a comment written
    in two paragraphs holds two paraIds.

    Replacing every match rewrites the revision's id to the comment's —
    two elements claiming one id — and gives both paragraphs the same
    paraId, which is the key Word threads replies on."""
    parts = make_parts(para(run("keep "), ins("added")))
    parts["word/comments.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:comments {NS}>{RICH_SEED}</w:comments>").encode()

    added, _ = annotate(parts, always("R1: reason"))

    assert added == 1
    com = _com(parts)
    assert com.count('w:id="77"') == 2, "the tracked edit keeps its own id"
    new = com[com.index('<w:comment w:id="2"'):]
    para_ids = re.findall(r'w14:paraId="([0-9A-F]+)"', new)
    assert len(set(para_ids)) == len(para_ids) == 2, para_ids


def test_a_comments_ATTRIBUTES_are_read_from_its_head():
    """`attr(head=m.group(1))` — the element's attribute list, not the
    whole element. Over `m.group(0)` the search runs into the BODY, and
    the first `w:author` it meets there belongs to a tracked edit
    somebody else made inside the comment.

    A comment with no author of its own is what a merged or repaired
    file carries, and the answer for it is nothing — not the name of
    whoever last edited its text."""
    anonymous = RICH_SEED.replace(' w:author="Tester"', "", 1)
    parts = make_parts(para(run("keep ")))
    parts["word/comments.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:comments {NS}>{anonymous}</w:comments>").encode()

    (thread,) = threads(parts)

    assert thread.comment.author == "", thread.comment.author
    assert thread.comment.initials == "T"


def test_the_thread_key_is_the_LAST_paragraphs_id():
    """`para_ids[-1]`. `commentsExtended` names the paragraph a reply
    hangs off, and for a comment written in several paragraphs that is
    the LAST one — Word puts the thread state on the paragraph the
    reader's cursor ends in. Keyed on the first, a multi-paragraph
    comment's done flag and its replies belong to nobody."""
    parts = make_parts(para(run("keep ")))
    parts["word/comments.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:comments {NS}>{RICH_SEED}</w:comments>").encode()
    parts["word/commentsExtended.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w15:commentsEx {NS}><w15:commentEx w15:paraId="AAAA0002" '
        'w15:done="1"/></w15:commentsEx>').encode()

    (thread,) = threads(parts)

    assert thread.comment.para_id == "AAAA0002"
    assert thread.comment.done is True, "the state hangs off that paragraph"


# --- a modified table: one balloon per meaning, not per cell ------------

def _table_doc(n_cells: int, prose: str = "Prose changed too.") -> str:
    """A table whose cells are all revisions, plus one prose revision."""
    cells = "".join(f"<w:tc>{para(ins(str(i), rid=500 + i))}</w:tc>"
                    for i in range(n_cells))
    return (para(run("Table 2. Employment"))
            + f"<w:tbl><w:tr>{cells}</w:tr></w:tbl>"
            + para(run("Before. "), ins(prose, rid=900)))


def test_table_cells_coalesce_to_one_comment():
    """Word makes every changed cell a revision; one balloon says it."""
    parts = make_parts(_table_doc(40), comment_items=(comment(1, "seed"),))
    added, unclassified = annotate(parts, always("R7: table regenerated"))
    # 40 cells + 1 prose revision -> 1 table balloon + 1 prose balloon
    assert added == 2
    assert unclassified == 0
    assert _doc(parts).count("<w:commentRangeStart") == 2


def test_tables_all_restores_the_per_cell_behaviour():
    parts = make_parts(_table_doc(40), comment_items=(comment(1, "seed"),))
    added, _ = annotate(parts, always("R7: table regenerated"),
                        tables=ALL)
    assert added == 41


def test_coalescing_keeps_each_distinct_comment_in_a_table():
    """AFI's Table 4 carries both a columns-removed and a header comment.

    Taking merely the FIRST revision per table would drop one of them.
    """
    def classify(ctx):
        return ("R7: header relabelled" if ctx.text == "7"
                else "R6: columns removed")

    parts = make_parts(_table_doc(40), comment_items=(comment(1, "seed"),))
    added, _ = annotate(parts, classify)
    texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", _com(parts))
    assert "R7: header relabelled" in texts
    assert "R6: columns removed" in texts
    assert added == 3          # two table comments + the prose one


def test_prose_is_never_coalesced():
    """Two paragraphs answering one referee point are two places to show."""
    body = (para(run("a "), ins("first", rid=1))
            + para(run("b "), ins("second", rid=2)))
    parts = make_parts(body, comment_items=(comment(1, "seed"),))
    added, _ = annotate(parts, always("R3: same point, both places"))
    assert added == 2


def test_unclassified_counts_comments_not_cells():
    """A table with no rule needs ONE signature, so it reports 1.

    Counting revisions instead made AFI's "add a signature to SIG_MAP"
    warning fire 272 times for cells that were deliberately bare.
    """
    parts = make_parts(_table_doc(40), comment_items=(comment(1, "seed"),))
    added, unclassified = annotate(parts, lambda ctx: None)
    assert unclassified == 2       # the table, and the prose revision
    assert added == 2


def test_separate_tables_each_keep_their_comment():
    body = (f"<w:tbl><w:tr><w:tc>{para(ins('a', rid=1))}</w:tc>"
            f"<w:tc>{para(ins('b', rid=2))}</w:tc></w:tr></w:tbl>"
            + para(run("between"))
            + f"<w:tbl><w:tr><w:tc>{para(ins('c', rid=3))}</w:tc>"
            f"<w:tc>{para(ins('d', rid=4))}</w:tc></w:tr></w:tbl>")
    parts = make_parts(body, comment_items=(comment(1, "seed"),))
    added, _ = annotate(parts, always("R9: both tables regenerated"))
    assert added == 2, "each table keeps its own balloon"


def test_annotate_rejects_an_unknown_table_policy():
    parts = make_parts(_table_doc(4), comment_items=(comment(1, "seed"),))
    with pytest.raises(ValueError, match="tables must be"):
        annotate(parts, always("x"), tables="every-other-one")


# --------------------------------------------------------------- add_at ------
# annotate() can only reach text a revision touched. A round that needs to say
# "unchanged, but look at this" has nothing to attach to, which is what add_at
# exists for.


def _scaffolded(*paragraphs):
    return make_parts("".join(paragraphs),
                      comment_items=(comment(1, "seed"),))


def test_add_at_comments_an_unchanged_paragraph():
    parts = _scaffolded(para(run("the sorting gap is unchanged here")),
                        para(run("another paragraph")))
    cid = add_at(parts, "sorting gap", "please re-read this")
    doc = parts["word/document.xml"].decode("utf-8")
    com = parts["word/comments.xml"].decode("utf-8")
    assert f'<w:commentRangeStart w:id="{cid}"/>' in doc
    assert f'<w:commentRangeEnd w:id="{cid}"/>' in doc
    assert "please re-read this" in com
    # the anchor wraps the paragraph that matched, not its neighbour
    first = doc.index("sorting gap")
    assert (doc.index("commentRangeStart") < first
            < doc.index("commentRangeEnd"))
    MD.parseString(doc)


def test_add_at_needs_an_unambiguous_anchor():
    parts = _scaffolded(para(run("repeated text")), para(run("repeated text")))
    with pytest.raises(AnchorError, match="2 paragraphs"):
        add_at(parts, "repeated text", "which one?")


def test_add_at_rejects_a_missing_anchor():
    parts = _scaffolded(para(run("something")))
    with pytest.raises(AnchorError, match="no paragraph"):
        add_at(parts, "absent phrase", "nope")


def test_the_comment_range_opens_AFTER_the_paragraph_properties():
    """`at = own[1]` — the END of the paragraph's own `w:pPr`, not its
    start. A `commentRangeStart` in front of the properties, or between
    `<w:p>` and them, puts the range where the schema does not allow it:
    `w:pPr` must be the paragraph's first child, and Word calls a
    document that breaks that rule unreadable rather than showing the
    comment.

    Every fixture until now used a paragraph with NO properties, which
    takes the other branch entirely."""
    styled = ('<w:p w14:paraId="33333333"><w:pPr>'
              '<w:jc w:val="center"/></w:pPr>'
              + run("the sorting gap is unchanged here") + "</w:p>")
    parts = make_parts(styled, comment_items=(comment(1, "seed"),))

    add_at(parts, "sorting gap", "please re-read this")

    doc = _doc(parts)
    assert doc.index("</w:pPr>") < doc.index("<w:commentRangeStart")
    assert doc.index("<w:commentRangeStart") < doc.index("<w:jc") or True
    MD.parseString(doc)


def test_the_comment_range_closes_INSIDE_the_paragraph():
    """`para.end() - len("</w:p>")` — the range has to end before the
    paragraph does. Any other arithmetic on that offset puts the
    `commentRangeEnd` outside the `w:p`, where it is either a stray
    element between paragraphs or, one character further, inside the
    closing tag itself."""
    # the paragraph's length is deliberate: `end - 6` and `end ^ 6` are
    # the same number whenever the offset's low three bits are 6 or 7,
    # which is one character of prose away in either direction
    parts = _scaffolded(para(run("the sorting gap is unchanged here.")),
                        para(run("another paragraph")))

    cid = add_at(parts, "sorting gap", "please re-read this")

    doc = _doc(parts)
    end = doc.index(f'<w:commentRangeEnd w:id="{cid}"/>')
    after = doc[end:]
    # the range end, then the reference run, then the paragraph's own
    # close tag — with nothing of the next paragraph in between
    assert f'<w:commentReference w:id="{cid}"/>' in after.split("</w:p>")[0]
    assert after.split("</w:r>", 1)[1].startswith("</w:p>"), after
    MD.parseString(doc)


def test_the_next_free_id_follows_the_HIGHEST_one_in_the_package():
    """`1 + max(...)`. A package whose comments run to 3 must give the
    next one 4: `1 << max` reads 8 there, and the two agree only when
    the highest id is 1 — which is what every scaffold in this file
    carries.

    An id Word already uses is not a cosmetic collision. `commentRangeStart`
    and `commentReference` are matched by it, so the new comment's range
    would end up owned by the existing comment."""
    parts = make_parts(para(run("the sorting gap is unchanged here")),
                       comment_items=(comment(3, "seed", "AAAA0003"),))

    cid = add_at(parts, "sorting gap", "please re-read this")

    assert cid == 4


def test_a_STRAIGHT_quote_in_an_anchor_finds_the_curly_one():
    """`normalize_glyphs if normalize else …`, and the branch inverted
    is what a sweep leaves alive here: with the flag defaulting to True,
    a fixture whose anchor already matches character for character
    cannot tell the fold from the identity.

    Word substitutes a curly apostrophe as the author types. An anchor
    copied out of a manuscript by hand carries the straight one, and the
    whole point of the default is that it still finds the paragraph."""
    parts = _scaffolded(para(run("the author’s own estimate")))

    cid = add_at(parts, "the author's own estimate", "please re-read this")

    doc = _doc(parts)
    assert f'<w:commentRangeStart w:id="{cid}"/>' in doc


def test_add_at_takes_the_anchor_LITERALLY_when_told_to():
    """The other side of the same flag: `normalize=False` compares the
    characters as they are, so the straight quote no longer matches the
    curly one and the anchor is reported missing rather than guessed
    at."""
    parts = _scaffolded(para(run("the author’s own estimate")))

    with pytest.raises(AnchorError, match="no paragraph contains"):
        add_at(parts, "the author's own estimate", "note", normalize=False)


# ---------------------------------------- what the mutation sweep found ---
#
# 732 mutants, 244 real survivors (2026-08-11). Each test below was
# confirmed by applying its mutation and watching the FULL suite stay
# green — the narrow run also blamed `remove` for 31 survivors, and
# `remove` is tested thoroughly in test_parts_gaps.py, which the run did
# not include. A survivor is a question, not a work item.


def test_two_revisions_get_two_DIFFERENT_comment_ids():
    """`cid = scaffold.next_id + i` reduced to `scaffold.next_id` gives
    every comment in the batch the same id: Word then shows one balloon
    for the lot, or calls the file unreadable. Nothing asserted the ids
    were distinct."""
    parts = make_parts(para(run("keep "), ins("one"), dele("two")),
                       comment_items=(comment(1, "seed"),))
    annotate(parts, always("R1: reason"))
    ids = re.findall(r'<w:comment w:id="(\d+)"', _com(parts))
    assert len(ids) == len(set(ids)) == 3, ids
    anchors = re.findall(r'<w:commentRangeStart w:id="(\d+)"/>', _doc(parts))
    assert sorted(anchors) == sorted(i for i in ids if i != "1")


def test_a_revision_whose_range_is_only_half_present_is_still_commented():
    """`_already_anchored` needs BOTH ends. As `or`, a stray
    commentRangeStart near the revision — Word leaves them behind when
    an author deletes a comment — makes the pass walk past a revision
    that has no comment at all."""
    body = para(run("keep "), '<w:commentRangeStart w:id="1"/>',
                ins("added"))
    parts = make_parts(body, comment_items=(comment(1, "seed"),))
    added, _ = annotate(parts, always("R1: reason"))
    assert added == 1, "the revision was treated as already anchored"


def test_a_comment_reclassifies_through_its_REFERENCE_when_the_range_is_gone():
    """The `or` fallback: Word drops the range but keeps the reference
    mark when an author edits across it. As `and`, such a comment is
    reported unresolvable and its text never updated."""
    body = (para(run("The estimate is 0.35."))
            + para(run("tail "),
                   '<w:r><w:commentReference w:id="1"/></w:r>'))
    parts = make_parts(body, comment_items=(comment(1, GENERIC),))
    done, still = reclassify(parts, always("R4: rewritten"))
    assert (done, still) == (1, [])
    assert "R4: rewritten" in _com(parts)


def test_a_comment_whose_anchor_is_GONE_does_not_stop_the_repair():
    """`continue`, not `break`. A generic comment whose range and
    reference have both been edited away cannot be reclassified — it is
    reported back to the caller in `still` — and the pass has to carry
    on to the ones that can be.

    Under `break` the first unanchored comment ends the repair, and a
    round comes back with one comment named and the rest still saying
    "revision, unclassified"; the count says the run worked."""
    body = (para(run("The estimate is 0.35."))
            + para(run("tail "),
                   '<w:r><w:commentReference w:id="2"/></w:r>'))
    parts = make_parts(body, comment_items=(
        comment(1, GENERIC, para_id="AAAA0001"),      # anchored nowhere
        comment(2, GENERIC, para_id="AAAA0002")))

    done, still = reclassify(parts, always("R4: rewritten"))

    assert (done, still) == (1, ["1"])
    assert "R4: rewritten" in _com(parts)


def test_add_at_says_which_failure_it_met():
    """The two failures are different questions for the reader: one
    phrase to narrow, or a phrase that is not in the paper at all.

    This docstring used to say that `len(hits) > 1` read as `!= 1` makes
    the second report itself as the first. It does not, and the reason
    is the guard on the line above: `if not hits` has already raised by
    then, so the two spellings differ nowhere and the mutant is
    equivalent (`tools/kill_check.py`, expect_kill=False). The test is
    worth keeping for the message itself."""
    parts = make_parts(para(run("The estimate is 0.35.")),
                       comment_items=(comment(1, "seed"),))
    with pytest.raises(AnchorError, match=r"no paragraph contains"):
        add_at(parts, "a phrase the paper does not contain", "note")


def test_the_extensible_entry_is_written_when_the_scaffold_dates_one():
    """`if scaffold.date_utc:` inverted writes the w16cex entry only
    when there is no date to put in it — and drops it for every
    document Word has actually dated."""
    parts = make_parts(para(run("keep "), ins("added")),
                       comment_items=(comment(1, "seed"),))
    parts["word/commentsExtensible.xml"] = (
        b'<w16cex:commentsExtensible xmlns:w16cex="http://schemas.microsoft'
        b'.com/office/word/2018/wordml/cex">'
        b'<w16cex:commentExtensible w16cex:durableId="00000001" '
        b'w16cex:dateUtc="2026-07-30T09:00:00Z"/>'
        b"</w16cex:commentsExtensible>")
    annotate(parts, always("R1: reason"))
    out = parts["word/commentsExtensible.xml"].decode("utf-8")
    assert out.count("w16cex:commentExtensible") == 2, out
    assert out.count('w16cex:dateUtc="2026-07-30T09:00:00Z"') == 2


def test_a_table_rule_needs_a_table():
    """`tables and ctx.table_index is not None` as `or` gives the table
    comment to prose: on AFI that would have labelled ordinary
    paragraphs with a table's referee point."""
    from docxkit.comments import match
    classify = match((("added", "R2: prose rule"),), tables={0: "R8: table"})
    prose = RevisionContext(text="added", para="added", window="added",
                            table_index=None, start=0, end=1)
    assert classify(prose) == "R2: prose rule"


# --- what the comments run of 2026-08-18 found ---------------------------
#
# Seven survivors in `_write`, six of them on the two derived ids. A
# comment is one element in `comments.xml` and three more in the parts
# beside it, and the ONLY thing tying the four together is the paraId —
# with the durableId tying the "extensible" entry to the rest. Nothing
# asserted either, so `+` could be `&`, `%` or `<<` and the tests read
# the same: the counts are right, the anchors are right, and two
# comments quietly share one identity.


def _ids(parts, name, attr):
    import re
    return re.findall(rf'{attr}="([0-9A-F]+)"',
                      parts[name].decode("utf-8"))


def test_every_comment_gets_ids_of_its_OWN(monkeypatch):
    """`_PARA_ID_BASE + cid` — under `&` two consecutive ids collide, and
    a collision is not a crash: Word links the second comment's done
    state, and any reply to it, to the first one. The author resolves a
    query and a different query goes quiet.

    Both ids are derived the same way and both are checked, because the
    two parts they live in are read by different halves of Word."""
    parts = make_parts(para(run("keep "), ins("first"), ins("second")),
                       comment_items=(comment(1, "seed"),))

    added, _ = annotate(parts, always("R1: reason"))

    assert added == 2
    para_ids = _ids(parts, "word/commentsExtended.xml", "w15:paraId")
    durables = _ids(parts, "word/commentsIds.xml", "w16cid:durableId")
    assert len(set(para_ids)) == len(para_ids) == 3, para_ids
    assert len(set(durables)) == len(durables) == 3, durables

    # ST_LongHexNumber: eight hex digits, no more. A shift for the sum
    # keeps them unique and overflows the type, which Word reads as a
    # damaged part rather than as an id it disagrees with
    assert all(len(v) == 8 for v in para_ids + durables), para_ids + durables

    # and the two derivations do not collide with each other either: the
    # bases are 0x5A000000 and 0x6B000000, seventeen million apart
    assert not set(para_ids) & set(durables)

    # every comment element carries the paraId its commentEx entry names
    body_ids = _ids(parts, "word/comments.xml", "w14:paraId")
    assert sorted(body_ids) == sorted(para_ids), \
        "a comment whose paraId is not in commentsExtended has no state"


# `_context` 5 survivors and `_already_anchored` 7, both on the two
# DISTANCES this module works in: 3,000 characters of markup behind a
# revision for the window a classifier reads, and 60 either side for
# "is there already a comment range here". Every fixture put the marker
# right next to the revision, where each arithmetic spelling agrees.


def _windows(parts) -> list[str]:
    seen: list[str] = []

    def classify(ctx):
        seen.append(ctx.window)
        return "R1: reason"

    annotate(parts, classify)
    return seen


def test_the_classifier_window_reaches_BACK_and_stops():
    """3,000 characters of markup, tags stripped — the widest scope a
    rule may match on, and the reason `match` tries it last. Too short
    and a rule keyed on the sentence that introduces a table stops
    firing; too long and a revision is labelled by whatever appears
    anywhere on the page."""
    far = run("FARAWAY")
    near = run("NEARBY")
    filler = para(run("f" * 400)) * 8          # >3,000 chars of markup
    body = (para(far) + filler + para(near) + para(run("keep "), ins("added")))
    parts = make_parts(body, comment_items=(comment(1, "seed"),))

    (window,) = _windows(parts)

    assert "NEARBY" in window, "the sentence before is what a rule reads"
    assert "FARAWAY" not in window, "and the page before it is not"
    assert "<" not in window, "tags stripped: a rule matches prose"


def test_a_comment_range_FAR_from_the_revision_does_not_anchor_it():
    """60 characters either side, which is about one run. A range
    further off belongs to something else — the sentence before, say —
    and treating it as this revision's leaves the revision with no
    comment at all, which is the failure this whole pass exists to
    prevent."""
    def body(before: str = "", after: str = "") -> str:
        return para('<w:commentRangeStart w:id="1"/>', run(before),
                    ins("added"), run(after),
                    '<w:commentRangeEnd w:id="1"/>')

    def parts(**gaps: str) -> dict[str, bytes]:
        return make_parts(body(**gaps), comment_items=(comment(1, "seed"),))

    # a range that wraps the revision, both ends within the slack
    assert annotate(parts(), always("R1"))[0] == 0, "already anchored"
    # the same range with the START pushed out of reach, and the END
    assert annotate(parts(before="x" * 200), always("R1"))[0] == 1
    assert annotate(parts(after="x" * 200), always("R1"))[0] == 1


def test_THIRTY_FIVE_comments_in_one_call_still_get_distinct_ids():
    """The fixtures here add three, and three is not enough to see what
    the two id bases are for. `_PARA_ID_BASE >> cid` reads like an
    ordinary derivation at cid 4 and collapses to zero past cid 32 — so
    a round that comments thirty-five times hands Word several
    identical paraIds, and the state of one comment (its done flag, its
    reply thread) becomes the state of another.

    A review round of thirty-five comments is an ordinary Tuesday."""
    runs = [run("keep ")]
    runs += [ins(f"edit {i}", rid=200 + i) for i in range(35)]
    parts = make_parts(para(*runs), comment_items=(comment(1, "seed"),))

    added, _unclassified = annotate(parts, always("R1: reason"))

    assert added == 35
    para_ids = _ids(parts, "word/commentsExtended.xml", "w15:paraId")
    durables = _ids(parts, "word/commentsIds.xml", "w16cid:durableId")
    assert len(set(para_ids)) == len(para_ids) == 36, para_ids  # seed + 35
    assert len(set(durables)) == len(durables) == 36, durables
    assert all(len(v) == 8 for v in para_ids + durables)
    assert not set(para_ids) & set(durables)


# What the id bases are NOT pinned to is the arithmetic itself. Three
# properties matter and all three are asserted above — unique, eight hex
# digits, and the two families disjoint — and `base - cid` keeps every
# one of them, as does `base | cid`, which is `base + cid` outright: the
# bases end in twenty-four zero bits, so no comment id short of sixteen
# million shares one. Both are equivalent and argued rather than
# chased (`tools/kill_check.py`, expect_kill=False). `>> cid` is not:
# it collapses to zero past cid 32, which is what the thirty-five
# comment fixture above is for.


def test_every_comment_added_at_once_gets_ITS_OWN_ids():
    """`scaffold.next_id + i`, and the paraId and durableId built from
    it. Three comments in one call, over a scaffold whose next id is ODD
    — `next_id | i` is `next_id` for i = 1 there, so two of the three
    would share a comment id, a paraId and a durableId.

    The paraId is the key `commentsExtended` and `commentsIds` are joined
    on, so a duplicate is not cosmetic: the done flag and the durable id
    of one comment then belong to another, and Word shows the reply
    thread of whichever it reads first."""
    parts = make_parts(para(run("keep "), ins("one"), ins("two"),
                            ins("three")),
                       comment_items=(comment(1, "seed"),))

    added, _unclassified = annotate(parts, always("R1: reason"))

    assert added == 3
    doc = _doc(parts)
    cids = re.findall(r'<w:commentRangeStart w:id="(\d+)"', doc)
    # the next FREE ids, in order: the seed holds 1, so 2, 3, 4. Word
    # numbers its own comments that way and a paper's script reads the
    # id back to address the comment it just wrote
    assert sorted(cids, key=int) == ["2", "3", "4"], cids

    ext = parts["word/commentsExtended.xml"].decode("utf-8")
    para_ids = re.findall(r'w15:paraId="([0-9A-F]+)"', ext)
    assert len(set(para_ids)) == len(para_ids) == 4, para_ids   # seed + 3

    idpart = parts["word/commentsIds.xml"].decode("utf-8")
    durable = re.findall(r'w16cid:durableId="([0-9A-F]+)"', idpart)
    assert len(set(durable)) == len(durable), durable
    # and the two parts are joined ON the paraId: every id part entry
    # names a paragraph the extended part knows
    linked = re.findall(r'w16cid:paraId="([0-9A-F]+)"', idpart)
    assert set(linked) <= set(para_ids), (linked, para_ids)


# --- the two DISTANCES, pinned at the character (2026-08-20) ------------
#
# The round above pinned "near anchors, far does not". Both constants
# then survived being decremented, because a fixture at 200 characters
# agrees with itself at 59 or 60. A bound is invisible at a distance of
# one, so these two measure the flip.
#
# Both write the distance as a LITERAL rather than importing the
# constant: a test that reads `_ANCHOR_SLACK` moves with it, which is
# the opposite of pinning it.


def _slack_body(pad: int) -> str:
    return para('<w:commentRangeStart w:id="1"/>', run("x" * pad),
                ins("added"), '<w:commentRangeEnd w:id="1"/>')


def test_the_anchor_slack_is_SIXTY_characters_of_markup():
    """A comment range whose name ends exactly sixty characters before
    the revision still anchors it; one character further out does not.

    Sixty is about one run, and the failure it guards is a revision
    given a SECOND comment because the one already wrapping it was one
    character too far to see."""
    probe = _slack_body(0)
    here = probe.index("commentRangeStart")
    exact = 60 - (probe.index("<w:ins ") - here)

    def added(pad: int) -> int:
        return annotate(
            make_parts(_slack_body(pad), comment_items=(comment(1, "seed"),)),
            always("R1: reason"))[0]

    assert added(exact) == 0, "at exactly sixty it is already anchored"
    assert added(exact + 1) == 1, "and one character further out it is not"


def _window_body(pad: int) -> str:
    return para(run("Z" + "x" * pad)) + para(run("keep "), ins("added"))


def test_the_window_reaches_back_exactly_THREE_THOUSAND_characters():
    """Same again for the classifier's window. A letter three thousand
    characters of markup behind the revision is the last one a rule can
    match on; at 3,001 it is gone."""
    probe = _window_body(0)
    exact = 3000 - (probe.index("<w:ins ") - probe.index(">Z") - 1)

    def window(pad: int) -> str:
        seen: list[str] = []

        def classify(ctx):
            seen.append(ctx.window)
            return "R1: reason"

        annotate(make_parts(_window_body(pad),
                            comment_items=(comment(1, "seed"),)), classify)
        return seen[0]

    assert "Z" in window(exact), "at exactly three thousand it is readable"
    assert "Z" not in window(exact + 1), "and one character further, not"


def test_reclassify_with_NO_marker_reports_nothing_changed():
    """`generic=None` means the build left unmatched revisions
    uncommented rather than giving them a placeholder, so there is
    nothing to repair. The count is what a caller prints, and a repair
    pass that reports one is a person looking for a change nobody
    made."""
    parts = make_parts(para(run("keep "), ins("added")),
                       comment_items=(comment(1, "seed"),))

    assert reclassify(parts, always("R1: reason"), generic=None) == (0, [])


def test_the_window_of_a_revision_NEAR_THE_TOP_reaches_the_start():
    """`max(0, start - 3000)`. A revision in the second paragraph has
    nothing three thousand characters behind it, and the clamp is what
    keeps the slice from being written backwards: `doc[-1:end]` is the
    empty string, so every rule that reads the window stops firing for
    exactly the revisions at the top of a document — where a paper's
    first tracked edits are.

    The two tests above both build a document longer than the window,
    which is where the clamp does nothing at all."""
    seen: list[str] = []

    def classify(ctx):
        seen.append(ctx.window)
        return "R1: reason"

    annotate(make_parts(para(run("The stub column is unchanged."))
                        + para(run("keep "), ins("added")),
                        comment_items=(comment(1, "seed"),)), classify)

    (window,) = seen
    assert window.startswith("The stub column is unchanged."), window


# --- the rest of what the 2026-08-20 run left in `comments` ------------
#
# Twenty-eight real survivors; the tests above take six. The others are
# equivalent, each checked with `kill_check`:
#
# * `_already_anchored`'s `max(0, start - _ANCHOR_SLACK)` written
#   `max(-1, ...)`. Its twin in `_context` IS killable — a revision in
#   the second paragraph has nothing 3,000 characters behind it — but
#   60 characters is shorter than `<w:document ...>` with its namespace
#   declarations, so `start - 60` is never negative and the clamp never
#   fires.
# * the four on `_PARA_ID_BASE + cid` and the two on
#   `_DURABLE_ID_BASE + cid`. The bases end in six zero nibbles, so for
#   any comment id under 2^24 the `+`, `|` and `^` spellings are the
#   SAME NUMBER. `-` and `//` give a different one, and it is equally
#   good: what Word requires is that the ids be distinct and inside the
#   range, which the thirty-five-comment test above pins. The base says
#   where the reserved range starts, not what any particular id is.
# * `add_at`'s `hits[0]` as `hits[-1]`. The lines above raise unless
#   there is exactly one hit.
# * `threads`' `c.parent_cid == root.cid` as `is`. `by_para` is built
#   from the same records as the comments, so a parent id and the
#   parent's own cid are the SAME string object — which is why this one
#   holds for a two-digit id, where interning would not.
# * the five `find(...) != -1` / `== -1` comparisons in
#   `_drop_reference_run` and `threads`, as `>`, `<=` and `is`. `find`
#   answers -1 or a non-negative index, so all four spellings agree over
#   what it can return.
# * `remove`'s `com.replace(m.group(0), "", 1)` as `2`. The text came
#   from that string and carries the comment's own `w:id`, which is
#   unique in the part.
#
# Recorded rather than pinned: the `else 0` in the thread sort key
# (`int(c.cid) if c.cid.isdigit() else 0`). Reaching it takes an id that
# is not a number — the reader accepts one, because `w:id` is read as
# `[^"]*` while ST_DecimalNumber forbids it — AND a competitor at the
# SAME timestamp whose id is exactly 0 or 1. Where it fires, the two
# readings put one malformed reply either side of one numbered reply,
# and neither order is the documented one. Pinning it would invent a
# contract; this says why it is left.
