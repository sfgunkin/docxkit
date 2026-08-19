"""Reading a redline: the two views python-docx cannot produce."""
from __future__ import annotations

import pytest
from conftest import dele, document, ins, para, para_mark_ins, run

from docxkit.revisions import (
    FINAL,
    ORIGINAL,
    accept,
    counts,
    reject,
    revision_text,
    spans,
    text,
)


def _redline():
    return document(
        para(run("The estimate "), dele("recovers"), ins("identifies"),
             run(" the effect."))
        + para(run("Unchanged paragraph.")))


def test_final_view_accepts_the_revisions():
    assert text(_redline(), FINAL) == [
        "The estimate identifies the effect.", "Unchanged paragraph."]


def test_original_view_rejects_them():
    """Deleted text comes back as ordinary runs, so it reads as prose."""
    assert text(_redline(), ORIGINAL) == [
        "The estimate recovers the effect.", "Unchanged paragraph."]


def test_the_two_views_differ_only_at_the_revision():
    final, original = text(_redline(), FINAL), text(_redline(), ORIGINAL)
    assert final[1] == original[1]
    assert final[0] != original[0]


def test_text_rejects_an_unknown_view():
    with pytest.raises(ValueError, match="final"):
        text(_redline(), "sideways")


def test_accept_and_reject_are_defined_on_raw_xml():
    xml = _redline()
    assert "recovers" not in accept(xml)
    assert "identifies" not in reject(xml)


def test_counts_reports_markup_volume():
    """A deliverable whose counts collapsed was opened in Word and
    accepted - the check that caught exactly that on the AFI paper."""
    assert counts(_redline()) == (1, 1)
    assert counts(accept(_redline()))[1] == 0


def test_spans_ignore_property_level_marks():
    xml = document(para(run("a"), ins("x")) + para_mark_ins())
    assert len(spans(xml)) == 1


def test_revision_text_includes_deleted_text():
    xml = _redline()
    got = [revision_text(xml, s) for s in spans(xml)]
    assert got == ["recovers", "identifies"]


def test_nested_revision_is_taken_as_one_span():
    """Word can wrap a deletion inside an insertion (text inserted then
    removed). The outer span owns it; it must not be counted twice."""
    inner = ('<w:ins w:id="1" w:author="A" w:date="d">'
             '<w:del w:id="2" w:author="A" w:date="d">'
             "<w:r><w:delText>gone</w:delText></w:r></w:del></w:ins>")
    xml = document(para(run("keep "), inner))
    assert len(spans(xml)) == 1


# ------------------------------------------------- equation skeletons ------


def _math_doc(*inner: str) -> str:
    return document("<w:p><m:oMath>" + "".join(inner) + "</m:oMath></w:p>")


def _del(rid: int, *inner: str) -> str:
    return (f'<w:del w:id="{rid}" w:author="A" w:date="2026-01-01T00:00:00Z">'
            + "".join(inner) + "</w:del>")


def _mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def test_accepting_a_deletion_inside_an_equation_leaves_no_shell():
    """The DSI bug: an emptied fraction survives as <m:f><m:num/><m:den/>,
    which Word renders as a blank fraction box beside the real content.

    Word's own AcceptAllRevisions prunes these, which is exactly why the
    fault only ever appeared on the XML path — and why it took a visual
    render of a shipped document to catch it.
    """
    out = accept(_math_doc(
        f"<m:f><m:num>{_del(1, _mr('a'))}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>",
        _mr("x")))
    assert "<m:f>" not in out and "<m:num" not in out
    assert "<m:t>x</m:t>" in out


def test_a_partly_emptied_object_keeps_its_surviving_glyphs():
    """Only what is text-free goes. A fraction that still has a numerator
    is a fraction, and pruning its slots would be schema-invalid anyway:
    m:den is REQUIRED by m:f."""
    out = accept(_math_doc(
        f"<m:f><m:num>{_mr('a')}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>"))
    assert "<m:f>" in out and "<m:den" in out
    assert "<m:t>a</m:t>" in out


def test_pruning_leaves_the_glyph_sequence_alone():
    """The invariant that makes the prune safe to run at all."""
    from docxkit._xml import visible_text
    doc = _math_doc(
        _mr("y"),
        f"<m:f><m:num>{_del(1, _mr('a'))}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>",
        f"<m:d><m:e>{_mr('z')}</m:e></m:d>")
    out = accept(doc)
    assert visible_text(out) == "yz"


def test_a_deliberate_spacer_is_not_an_empty_shell():
    """U+00A0 in an equation is typography. Stripping it as "no text"
    changes the render, so plain truthiness is the test, not .strip()."""
    out = accept(_math_doc(
        f"<m:d><m:e>{_mr(chr(160))}</m:e></m:d>",
        f"<m:f><m:num>{_del(1, _mr('a'))}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>"))
    assert "<m:d>" in out and "<m:f>" not in out


def test_an_equation_no_revision_touched_is_left_exactly_alone():
    """A legitimately empty object elsewhere in the document is the
    author's business — the prune is confined to equations a removal
    actually reached into."""
    doc = document(
        "<w:p><m:oMath><m:f><m:num/><m:den/></m:f></m:oMath></w:p>"
        + para(run("before "), dele("gone"), run(" after")))
    out = accept(doc)
    assert "<m:f><m:num/><m:den/></m:f>" in out
    assert "gone" not in out


# -------------------------------------------- verifying by text, not count ---


def test_changed_paragraphs_reports_only_what_moved():
    before = document(para(run("First.")) + para(run("Second."))
                      + para(run("Third.")))
    after = document(para(run("First.")) + para(run("Second, edited."))
                     + para(run("Third.")))
    from docxkit.revisions import changed_paragraphs
    got = changed_paragraphs(before, after)
    assert [(c.paragraph, c.before, c.after) for c in got] == [
        (1, "Second.", "Second, edited.")]


def test_changed_paragraphs_survives_a_paragraph_merge():
    """Accepting an inserted paragraph mark MERGES two paragraphs. Under
    index pairing every paragraph after the merge reads as changed, which
    is the noise that makes count-based verification useless."""
    from docxkit.revisions import changed_paragraphs
    before = document(para(run("First.")) + para(run("Second."))
                      + para(run("Third.")) + para(run("Fourth.")))
    after = document(para(run("First.")) + para(run("Second.Third."))
                     + para(run("Fourth.")))
    got = changed_paragraphs(before, after)
    assert [c.paragraph for c in got] == [1, 2]
    assert got[-1].after == ""          # the absorbed paragraph
    assert "Fourth." not in [c.before for c in got]


def _marked(kind: str, text: str) -> str:
    """A paragraph whose MARK carries an ins/del revision (the flag in pPr)."""
    return (f'<w:p w14:paraId="33333333"><w:pPr><w:rPr>'
            f'<w:{kind} w:id="7" w:author="A" w:date="2026-08-06T00:00:00Z"/>'
            f"</w:rPr></w:pPr>{run(text)}</w:p>")


def _joined(xml: str) -> str:
    from docxkit._xml import visible_text
    return visible_text(xml)


def test_applying_a_paragraph_mark_revision_leaves_no_markup_behind():
    """The flag lives in pPr/rPr, so unwrapping runs never reaches it.

    A batch that inserted nine paragraphs validated as "accepted" while the
    document still carried nine `w:ins` — Word would open it and report
    revisions in a document nothing remains to accept in. The same holds for
    the deletion flag on the reject side.
    """
    from docxkit.revisions import accept, reject
    inserted = document(_marked("ins", "New paragraph.") + para(run("Next.")))
    assert "w:ins" not in accept(inserted)
    assert "New paragraph." in accept(inserted)

    deleted = document(_marked("del", "Doomed.") + para(run("Next.")))
    assert "w:del" not in reject(deleted)
    assert "Doomed." in reject(deleted)


def test_applying_a_paragraph_mark_revision_still_merges_the_other_side():
    """The vanishing side must keep its old behaviour: losing a paragraph
    mark joins the paragraph to the one after it."""
    from docxkit.revisions import accept, reject
    deleted = document(_marked("del", "First.") + para(run("Second.")))
    assert "First.Second." in _joined(accept(deleted))

    inserted = document(_marked("ins", "First.") + para(run("Second.")))
    assert "First.Second." in _joined(reject(inserted))


def test_a_merge_puts_the_absorbed_content_in_ORDER_after_the_pPr():
    """Where the merged children land is 13 mutants' worth of arithmetic:
    `list(nxt).index(nxt_ppr) + 1`. Off by one and the absorbed runs go
    BEFORE the surviving paragraph's own properties — which Word rejects
    — and out of order among themselves, which reads as scrambled prose
    no count would catch."""
    # REJECTING an inserted paragraph mark is what joins them: the mark
    # was added, so undoing it puts the two paragraphs back together
    xml = document(
        f'<w:p><w:pPr><w:rPr><w:ins {D}/></w:rPr></w:pPr>'
        f"{run('one ')}{run('two ')}{run('three ')}</w:p>"
        f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>{run("tail")}</w:p>')
    out = reject(xml)
    assert out.count("<w:p ") + out.count("<w:p>") == 1, out
    assert _joined(out) == "one two three tail"
    # and the surviving paragraph's own properties still come first
    assert out.index('<w:jc w:val="center"/>') < out.index("one ")


def test_a_merge_into_a_paragraph_with_no_properties_still_orders():
    xml = document(
        f'<w:p><w:pPr><w:rPr><w:ins {D}/></w:rPr></w:pPr>'
        f"{run('a ')}{run('b ')}</w:p>"
        f'<w:p>{run("c")}</w:p>')
    assert _joined(reject(xml)) == "a b c"


def test_changed_paragraphs_reports_the_index_and_both_sides():
    """The existing pair only ever moved ONE paragraph, where k is 0 and
    every arithmetic mutation of `i1 + k` is equivalent. A wider block,
    with the two sides at different offsets, is what pins it."""
    from docxkit.revisions import changed_paragraphs
    before = document(para(run("Keep.")) + para(run("A."))
                      + para(run("B.")) + para(run("C."))
                      + para(run("End.")))
    after = document(para(run("Keep.")) + para(run("New."))
                     + para(run("End.")))
    got = changed_paragraphs(before, after)
    assert [(c.paragraph, c.before, c.after) for c in got] == [
        (1, "A.", "New."), (2, "B.", ""), (3, "C.", "")]


def test_changed_paragraphs_reports_an_insertion_at_its_own_offset():
    from docxkit.revisions import changed_paragraphs
    before = document(para(run("One.")) + para(run("Four.")))
    after = document(para(run("One.")) + para(run("Two."))
                     + para(run("Three.")) + para(run("Four.")))
    got = changed_paragraphs(before, after)
    assert [(c.paragraph, c.before, c.after) for c in got] == [
        (1, "", "Two."), (2, "", "Three.")]


def test_changed_paragraphs_is_empty_when_nothing_changed():
    from docxkit.revisions import changed_paragraphs
    doc = document(para(run("Only.")))
    assert changed_paragraphs(doc, doc) == []


def _row(cells: str, flag: str = "") -> str:
    trpr = (f'<w:trPr><w:{flag} w:id="8" w:author="A" '
            f'w:date="2026-08-07T00:00:00Z"/></w:trPr>') if flag else ""
    return f"<w:tr>{trpr}{cells}</w:tr>"


def _cell(text: str) -> str:
    return f"<w:tc><w:tcPr/>{para(run(text))}</w:tc>"


def test_an_inserted_table_disappears_when_its_rows_are_rejected():
    """An inserted table is encoded as nothing but flagged rows. A simulation
    blind to `trPr` leaves the whole table standing, emptied of text, where
    Word removes it — so reject-all stopped matching the baseline for every
    batch that adds a table."""
    from docxkit.revisions import accept, reject
    tbl = ("<w:tbl><w:tblPr/><w:tblGrid/>"
           + _row(_cell("Регион") + _cell("2025"), "ins")
           + _row(_cell("Астана") + _cell("0,726"), "ins")
           + "</w:tbl>")
    doc = document(para(run("before")) + tbl + para(run("after")))
    assert "w:tbl" not in reject(doc)
    assert "Астана" not in reject(doc)
    assert "before" in reject(doc) and "after" in reject(doc)
    kept = accept(doc)
    assert "Астана" in kept and "w:ins" not in kept


def test_rejecting_one_inserted_row_keeps_the_rest_of_the_table():
    from docxkit.revisions import reject
    tbl = ("<w:tbl><w:tblPr/><w:tblGrid/>"
           + _row(_cell("original"))
           + _row(_cell("added"), "ins")
           + "</w:tbl>")
    out = reject(document(tbl))
    assert "w:tbl" in out
    assert "original" in out and "added" not in out


def test_a_deleted_row_survives_rejection_without_its_flag():
    from docxkit.revisions import accept, reject
    tbl = ("<w:tbl><w:tblPr/><w:tblGrid/>"
           + _row(_cell("doomed"), "del")
           + _row(_cell("stays"))
           + "</w:tbl>")
    assert "doomed" in reject(document(tbl))
    assert "w:del" not in reject(document(tbl))
    assert "doomed" not in accept(document(tbl))
    assert "stays" in accept(document(tbl))


# --------------------------------------------- FORMATTING revisions ----
# A property change is recorded as a snapshot of the OLD properties
# nested in the new ones. Accepting means dropping the record; rejecting
# means putting the snapshot back. Both views passed it straight through
# until 2026-08-10, which is what let `reject-all == baseline` pass on a
# batch of nothing else.

D = 'w:id="1" w:author="Reviewer" w:date="2026-01-01T00:00:00Z"'


def test_accepting_a_formatting_change_keeps_the_new_properties():
    xml = document(
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {D}>'
        f'<w:rPr><w:sz w:val="24"/></w:rPr></w:rPrChange></w:rPr>'
        f"<w:t>note</w:t></w:r></w:p>")
    out = accept(xml)
    assert '<w:sz w:val="20"/>' in out
    assert "rPrChange" not in out, "accepted, and still on the tally"
    assert '<w:sz w:val="24"/>' not in out


def test_rejecting_a_formatting_change_puts_the_old_ones_back():
    """What makes the author's veto real. The text is identical either
    way, so no text comparison can tell these two apart — which is
    exactly why the gate built on one could not fail."""
    xml = document(
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {D}>'
        f'<w:rPr><w:sz w:val="24"/></w:rPr></w:rPrChange></w:rPr>'
        f"<w:t>note</w:t></w:r></w:p>")
    out = reject(xml)
    assert '<w:sz w:val="24"/>' in out
    assert '<w:sz w:val="20"/>' not in out
    assert "rPrChange" not in out


def test_rejecting_a_paragraph_change_keeps_the_marks_own_properties():
    """`pPrChange/pPr` is CT_PPrBase: it cannot hold the paragraph MARK's
    `w:rPr`. Restore the snapshot wholesale and the mark loses its own
    formatting — and, worse, the flag that kind of revision lives in."""
    xml = document(
        f'<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:b/></w:rPr>'
        f'<w:pPrChange {D}><w:pPr><w:jc w:val="left"/></w:pPr>'
        f"</w:pPrChange></w:pPr><w:r><w:t>x</w:t></w:r></w:p>")
    out = reject(xml)
    assert '<w:jc w:val="left"/>' in out
    assert '<w:jc w:val="center"/>' not in out
    assert "<w:b/>" in out, "the paragraph mark's properties were dropped"


def test_a_paragraph_with_both_kinds_still_has_its_mark_rejected():
    """The ordering guard. The mark's insert flag lives in the `w:rPr`
    the restore above carries across, so property changes are applied
    LAST — otherwise the flag moves out from under the handler that was
    about to act on it, and an inserted paragraph mark stops being
    rejectable."""
    xml = document(
        f'<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:ins {D}/></w:rPr>'
        f'<w:pPrChange {D}><w:pPr><w:jc w:val="left"/></w:pPr>'
        f"</w:pPrChange></w:pPr><w:r><w:t>first</w:t></w:r></w:p>"
        + para(run("second")))
    out = reject(xml)
    assert out.count("<w:p ") + out.count("<w:p>") == 1, "the mark survived"
    assert "first" in out and "second" in out


def test_what_a_reject_carries_across_goes_back_in_SCHEMA_ORDER():
    """Presence is not enough. CT_PPr puts the paragraph mark's `w:rPr`
    AFTER the base properties and CT_SectPr puts its references FIRST,
    so a restore that appends both, or prepends both, writes markup Word
    rejects — while a test asserting only that the element survived goes
    green. The mutation sweep found it: `side == "first"` read as
    `side >= "first"` is True for "last" too, and nothing noticed."""
    para_xml = document(
        f'<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:b/></w:rPr>'
        f'<w:pPrChange {D}><w:pPr><w:jc w:val="left"/></w:pPr>'
        f"</w:pPrChange></w:pPr><w:r><w:t>x</w:t></w:r></w:p>")
    out = reject(para_xml)
    assert out.index('<w:jc w:val="left"/>') < out.index("<w:rPr>"), \
        "the mark's properties were put BEFORE the base ones"

    sect = document(
        f"<w:p><w:r><w:t>body</w:t></w:r></w:p><w:sectPr>"
        f'<w:headerReference w:type="default"/>'
        f'<w:pgSz w:w="12240" w:h="15840"/>'
        f'<w:sectPrChange {D}><w:sectPr>'
        f'<w:pgSz w:w="15840" w:h="12240"/></w:sectPr></w:sectPrChange>'
        f"</w:sectPr>")
    back = reject(sect)
    assert back.index("headerReference") < back.index('w:w="15840"'), \
        "the running head was put AFTER the page size"


def test_accepting_clears_EVERY_formatting_record_not_just_the_first():
    """The other `continue` in that loop. With `break` the first record
    of each kind goes and the rest stay, so the document still counts as
    a proposal — and `state` would say so while the accept reported
    success."""
    xml = document(
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {D}>'
        f'<w:rPr><w:sz w:val="24"/></w:rPr></w:rPrChange></w:rPr>'
        f"<w:t>first</w:t></w:r>"
        f'<w:r><w:rPr><w:i/><w:rPrChange {D}><w:rPr/></w:rPrChange>'
        f"</w:rPr><w:t>second</w:t></w:r></w:p>")
    assert xml.count("<w:rPrChange") == 2
    assert "<w:rPrChange" not in accept(xml)


def test_a_property_change_the_predicate_declines_stops_nothing():
    """`continue`, not `break`: one revision an author's predicate leaves
    alone must not end the pass over the rest."""
    from docxkit.revisions import by_author
    other = 'w:id="2" w:author="Someone Else" w:date="2026-01-01T00:00:00Z"'
    xml = document(
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {other}>'
        f'<w:rPr><w:sz w:val="24"/></w:rPr></w:rPrChange></w:rPr>'
        f"<w:t>first</w:t></w:r></w:p>"
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {D}>'
        f'<w:rPr><w:sz w:val="28"/></w:rPr></w:rPrChange></w:rPr>'
        f"<w:t>second</w:t></w:r></w:p>")
    out = accept(xml, where=by_author("Reviewer"))
    # the OPENING tag: a surviving element serialises as two occurrences
    assert out.count("<w:rPrChange") == 1, "the walk stopped at the skip"
    assert 'w:author="Someone Else"' in out


def test_rejecting_a_section_change_keeps_the_running_heads():
    """`sectPrChange/sectPr` is CT_SectPrBase, which has no header or
    footer reference — and CT_SectPr puts them FIRST, so they go back at
    the front or the section does not parse as Word wrote it."""
    xml = document(
        f"<w:p><w:r><w:t>body</w:t></w:r></w:p><w:sectPr>"
        f'<w:headerReference w:type="default"/>'
        f'<w:pgSz w:w="12240" w:h="15840"/>'
        f'<w:sectPrChange {D}><w:sectPr>'
        f'<w:pgSz w:w="15840" w:h="12240"/></w:sectPr></w:sectPrChange>'
        f"</w:sectPr>")
    out = reject(xml)
    assert "headerReference" in out, "the running head was rejected away"
    assert 'w:w="15840"' in out, "the landscape page size was not restored"
    assert out.index("headerReference") < out.index('w:w="15840"')


def test_rejecting_a_row_change_leaves_the_rows_own_flag_alone():
    """A `w:trPr` carries both the formatting record and the row's own
    insert flag. Rejecting the first must not take the second, or the
    inserted row stops being rejectable."""
    tbl = ("<w:tbl><w:tblPr/><w:tblGrid/><w:tr><w:trPr>"
           f'<w:ins {D}/><w:trHeight w:val="300"/>'
           f'<w:trPrChange {D}><w:trPr><w:trHeight w:val="200"/></w:trPr>'
           "</w:trPrChange></w:trPr>" + _cell("added") + "</w:tr></w:tbl>")
    assert "added" not in reject(document(tbl)), "the row was not rejected"


def test_an_empty_snapshot_means_there_were_no_properties():
    """Word writes `<w:rPrChange><w:rPr/></w:rPrChange>` for a run that
    had no direct formatting at all — which is the commonest case in a
    Compare, and emptying the live properties is exactly right."""
    xml = document(
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {D}><w:rPr/>'
        f"</w:rPrChange></w:rPr><w:t>note</w:t></w:r></w:p>")
    out = reject(xml)
    assert "<w:rPr/>" in out or "<w:rPr></w:rPr>" in out
    assert 'w:sz' not in out


def test_a_selective_accept_by_author_now_reaches_formatting():
    """"Accept everything this author did" means their formatting too."""
    from docxkit.revisions import by_author
    xml = document(
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {D}>'
        f'<w:rPr><w:sz w:val="24"/></w:rPr></w:rPrChange></w:rPr>'
        f"<w:t>note</w:t></w:r></w:p>")
    assert "rPrChange" not in accept(xml, where=by_author("Reviewer"))
    assert "rPrChange" in accept(xml, where=by_author("Somebody Else"))


def test_whitespace_only_still_does_not_touch_formatting():
    """The predicate is about respacing noise. A formatting revision has
    no text at all, and bulk-accepting one is never what was meant."""
    from docxkit.revisions import whitespace_only
    xml = document(
        f'<w:p><w:r><w:rPr><w:sz w:val="20"/><w:rPrChange {D}>'
        f'<w:rPr><w:sz w:val="24"/></w:rPr></w:rPrChange></w:rPr>'
        f"<w:t>note</w:t></w:r></w:p>")
    assert "rPrChange" in accept(xml, where=whitespace_only)


# `changed_paragraphs` had 5 survivors, four of them on `old[i1 + k]`
# and `new[j1 + k]` — the same shape `tracked.untracked` had, and for
# the same reason: the fixtures above change ONE paragraph, or two at
# index 1, where `i1 | k` and `i1 ** k` agree with the sum. This is the
# verification a redline is accepted on, so which paragraph it names and
# what it quotes are the whole of it.


def test_a_block_of_paragraphs_deep_in_the_document_is_quoted_by_PAIR():
    """Three rewritten paragraphs starting at index 3. At index 0 or 1
    every bitwise spelling of `i1 + k` lands on the same entry; here they
    name the wrong before-and-after, and a reader checking a redline is
    handed a pair of sentences that were never opposite each other."""
    from docxkit.revisions import changed_paragraphs
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    before = document("".join([*keep, para(run("Alpha was.")),
                               para(run("Beta was.")),
                               para(run("Gamma was.")),
                               para(run("Tail."))]))
    after = document("".join([*keep, para(run("Alpha is now.")),
                              para(run("Beta is now.")),
                              para(run("Gamma is now.")),
                              para(run("Tail."))]))

    got = changed_paragraphs(before, after)

    assert [(c.paragraph, c.before, c.after) for c in got] == [
        (3, "Alpha was.", "Alpha is now."),
        (4, "Beta was.", "Beta is now."),
        (5, "Gamma was.", "Gamma is now.")]


def test_a_paragraph_the_batch_DROPPED_deep_in_the_document():
    """The `else ""` on the other side, at an offset: three paragraphs
    become one, so two of the three entries have nothing after them —
    and each must still quote the paragraph it LOST, not its neighbour."""
    from docxkit.revisions import changed_paragraphs
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    before = document("".join([*keep, para(run("Alpha.")),
                               para(run("Beta.")),
                               para(run("Gamma.")),
                               para(run("Tail."))]))
    after = document("".join([*keep, para(run("All three, merged.")),
                              para(run("Tail."))]))

    got = changed_paragraphs(before, after)

    assert [(c.paragraph, c.before, c.after) for c in got] == [
        (3, "Alpha.", "All three, merged."),
        (4, "Beta.", ""),
        (5, "Gamma.", "")]


# --- what a MOVE does to the anchors inside it (DSI, 2026-08-19) --------
#
# Word writes a moved paragraph twice: the old place wrapped in
# `w:moveFrom`, the new one in `w:moveTo`. When the moved run sequence
# carries a citation anchor, the `w:bookmarkStart` sits INSIDE the
# `w:moveTo` — and rejecting the move removed that element with the
# anchor in it. 127 bookmarks in the baseline, 125 in the rejected view,
# `reject-all == baseline` passing because a bookmark carries no glyph,
# and the paper's bidirectional citation links quietly one-directional.

_WHEN = 'w:id="{i}" w:author="A" w:date="2026-08-19T00:00:00Z"'


def _moved_with_anchor() -> str:
    """A paragraph moved through Compare, its citation anchor inside the
    `w:moveTo` — which is where Word puts it."""
    old_place = (f'<w:p><w:moveFrom {_WHEN.format(i=2)}>'
                 f"<w:r><w:t>As Moran (1950) showed.</w:t></w:r>"
                 "</w:moveFrom></w:p>")
    new_place = (f'<w:p><w:moveTo {_WHEN.format(i=4)}>'
                 '<w:bookmarkStart w:id="9" w:name="Moran1950"/>'
                 "<w:r><w:t>As Moran (1950) showed.</w:t></w:r>"
                 '<w:bookmarkEnd w:id="9"/></w:moveTo></w:p>')
    return document(para(run("Before.")) + new_place
                    + para(run("Between.")) + old_place)


def test_rejecting_a_MOVE_keeps_the_anchors_it_carried():
    """The anchor is the document's, not the revision's. It no longer
    wraps the sentence — that text is being restored somewhere else, and
    gate 5 is what decides whether the result is acceptable — but it is
    still there, and a link to it still resolves."""
    xml = _moved_with_anchor()

    out = reject(xml)

    assert out.count("<w:bookmarkStart") == 1
    assert out.count("<w:bookmarkEnd") == 1
    assert 'w:name="Moran1950"' in out
    assert text(out, ORIGINAL) == ["Before.", "Between.",
                                   "As Moran (1950) showed."]


def test_accepting_the_same_move_keeps_them_where_they_were():
    xml = _moved_with_anchor()

    out = accept(xml)

    assert out.count("<w:bookmarkStart") == 1
    assert text(out, FINAL) == ["Before.", "As Moran (1950) showed.",
                               "Between."]


def test_rejecting_an_INSERTION_keeps_a_comment_anchor_inside_it():
    """The same shape one revision kind over: a comment whose range
    start sits inside a rejected insertion is a comment Word reports as
    damaged, and `commentRangeEnd` without its start is what does it."""
    xml = document(
        para(run("Kept. "),
             f'<w:ins {_WHEN.format(i=7)}>'
             '<w:commentRangeStart w:id="3"/>'
             "<w:r><w:t>added text</w:t></w:r>"
             '<w:commentRangeEnd w:id="3"/>'
             '<w:r><w:commentReference w:id="3"/></w:r>'
             "</w:ins>"))

    out = reject(xml)

    assert "added text" not in out, "the insertion goes"
    assert out.count("<w:commentRangeStart") == 1
    assert out.count("<w:commentRangeEnd") == 1
    assert out.count("<w:commentReference") == 1


def test_the_anchors_keep_their_ORDER_when_they_are_lifted():
    """A start still precedes its end, or the pair is worse than lost:
    Word reads a `bookmarkEnd` before its `bookmarkStart` as damage."""
    xml = document(
        para(f'<w:ins {_WHEN.format(i=8)}>'
             '<w:bookmarkStart w:id="1" w:name="first"/>'
             "<w:r><w:t>one</w:t></w:r>"
             '<w:bookmarkEnd w:id="1"/>'
             '<w:bookmarkStart w:id="2" w:name="second"/>'
             "<w:r><w:t>two</w:t></w:r>"
             '<w:bookmarkEnd w:id="2"/></w:ins>'))

    out = reject(xml)

    assert (out.index('w:name="first"') < out.index("<w:bookmarkEnd")
            < out.index('w:name="second"'))
def test_the_lifted_anchors_keep_their_WHOLE_sequence():
    """`parent.insert(at + offset, marker)`, and the fixture above
    cannot see the `-` spelling: with four markers it produces
    start1, end2, start2, end1, where the FIRST end still sits between
    the two starts and every assertion about "a start precedes an end"
    holds. Word reads that as two crossed bookmark ranges.

    So this asserts the sequence, not a relation inside it."""
    import re

    xml = document(
        para(f'<w:ins {_WHEN.format(i=8)}>'
             '<w:bookmarkStart w:id="1" w:name="first"/>'
             "<w:r><w:t>one</w:t></w:r>"
             '<w:bookmarkEnd w:id="1"/>'
             '<w:bookmarkStart w:id="2" w:name="second"/>'
             "<w:r><w:t>two</w:t></w:r>"
             '<w:bookmarkEnd w:id="2"/></w:ins>'))

    out = reject(xml)

    order = re.findall(r'<w:bookmark(Start|End) w:id="(\d)"', out)
    assert order == [("Start", "1"), ("End", "1"),
                     ("Start", "2"), ("End", "2")], order



def test_TWO_equations_touched_by_one_pass_are_both_pruned():
    """`not any(om is seen for seen in touched)` — the list of equations
    a removal reached into, collected before the elements leave the
    tree. Read as `is not`, the test becomes "every equation seen so far
    IS this one", which is true only while the list is empty: the first
    equation is collected and no other ever is.

    A paper with two display equations in one round is ordinary, and the
    second would keep the empty fraction box this prune exists to
    remove."""
    out = accept(document(
        "<w:p><m:oMath>"
        f"<m:f><m:num>{_del(1, _mr('a'))}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>"
        "</m:oMath></w:p>"
        "<w:p><m:oMath>"
        f"<m:f><m:num>{_del(3, _mr('c'))}</m:num>"
        f"<m:den>{_del(4, _mr('d'))}</m:den></m:f>"
        "</m:oMath></w:p>"))

    assert "<m:f>" not in out and "<m:num" not in out, out


def test_a_view_name_BUILT_at_runtime_is_still_the_view():
    """`view == FINAL`, and `is` is the mutant that hides behind every
    test in this file: they all pass the module's own constant.

    No caller outside this module does. `docxkit text --tracked final`
    hands over a string argparse built from argv, a paper.toml hands
    over one tomllib built, a JSON report one json built — and none of
    them is the constant's object, however equal. Under `is` the CLI's
    own documented flag raises "view must be 'final' or 'original'".
    """
    from docxkit.revisions import view_transform

    built = "".join(["fi", "nal"])          # what argparse would hand over
    other = "".join(["origi", "nal"])
    assert (built, other) == (FINAL, ORIGINAL)
    assert built is not FINAL and other is not ORIGINAL

    assert view_transform(built) is accept
    assert view_transform(other) is reject
    assert text(_redline(), built) == text(_redline(), FINAL)
    assert text(_redline(), other) == text(_redline(), ORIGINAL)


def test_a_whole_DOCUMENT_comes_back_as_a_whole_document():
    """`_parse` says whether it had to wrap a fragment, and `_serialize`
    reads that flag to decide between "print the root" and "print the
    root's children". Told the wrong way round for a real document, the
    result is its BODY with the `w:document` element and every namespace
    declaration stripped off — which `write_docx` refuses and Word calls
    corrupt, but only once it reaches a package.

    Every other test here reads the text back out, where the wrapper is
    invisible."""
    out = accept(_redline())

    assert out.lstrip().startswith("<w:document")
    assert out.rstrip().endswith("</w:document>")
    assert "xmlns:w=" in out


def test_spans_finds_a_revision_that_opens_the_FRAGMENT():
    """`pos = 0`. `spans` is given a paragraph as often as a document —
    `comments.annotate` walks paragraph by paragraph — and a revision
    that starts at offset 0 is the ordinary shape of one: `<w:ins>` is
    the first thing in the string.

    Starting the scan at 1 finds every later revision and silently
    drops that one, which is an anchor nobody comments."""
    fragment = ('<w:ins w:id="1" w:author="A" w:date="d">'
                "<w:r><w:t>opening</w:t></w:r></w:ins>"
                '<w:ins w:id="2" w:author="A" w:date="d">'
                "<w:r><w:t>second</w:t></w:r></w:ins>")

    found = spans(fragment)

    assert len(found) == 2
    assert found[0][0] == 0, found


def test_the_text_view_is_CACHED_between_identical_calls():
    """`@lru_cache(maxsize=8)`. The walk costs ~7ms per call over a
    real manuscript and the audits ask for the same view of the same
    document several times in a row; the simulation underneath it is
    ~50ms. Removing the decorator changes no answer, which is why
    nothing caught it — this asserts the cache is there and that the
    public function hands out a COPY, so a caller mutating its result
    cannot poison it."""
    from docxkit.revisions import _text_cached

    _text_cached.cache_clear()
    xml = _redline()

    first = text(xml, FINAL)
    second = text(xml, FINAL)

    assert _text_cached.cache_info().hits >= 1
    assert first == second and first is not second
    first.append("mutated by the caller")
    assert text(xml, FINAL) == second


# --- what is left in revisions.py, and why ------------------------------
#
# `if m.group(2) == "/"` in `spans` -> `>=`. The group is the
# self-closing slash or the empty string, and "" is the only string that
# sorts below "/", so the two spellings agree on both.
#
# `if mode == FINAL` in `_apply_property_changes` -> `<=`, and
# `if side == "first"` -> `is` / `<=`. Both compare against a value from
# a fixed set — final/original, first/last — and over those the
# orderings and the identities cannot disagree with equality. `side`
# comes from a module-level table of literals, so `is` holds too.
#
# `c.tag.rsplit("}", 1)[-1]` -> `[1]`, `[+1]`, and the maxsplit -> 2.
# Every element here is namespaced, so the split gives exactly two parts
# and the last is the second.
#
# `whitespace_only`'s two comparisons -> `>`, `is not`, `<=`. The
# empty string is the only one that sorts at or below `""`, and the only
# one that is `""`, so every spelling of "has text" and "is all spaces"
# agrees on every string.
#
# `if el is om or el.getparent() is None` in `_prune_math` -> `and`.
# The first term skips the equation ROOT, which is handled after the
# loop; the second skips an element already detached. `oMath` is not in
# MATH_OBJECTS, so processing the root does nothing, and the iteration
# is materialised before any removal, so nothing in it is detached —
# the guard cannot be observed from either side.
#
# `if mode == ORIGINAL` in `_simulate_where` -> `is`. This one is
# reachable in principle — a runtime-built view name flows into
# `_simulate` from `text()` — but the branch it guards converts
# `w:delText` to `w:t`, and `visible_text` reads both, so the difference
# cannot be seen through the only public caller that forwards the
# string. `view_transform`'s two comparisons ARE tested, because their
# answer is the transform itself.


def test_an_insertion_of_SEVERAL_runs_unwraps_them_in_order():
    """`at += 1` — the cursor that walks the wrapper's children into the
    place the wrapper stood. Word writes one `w:ins` around several runs
    whenever the inserted text changes formatting mid-phrase (a citation
    in italics, a superscript marker), so a multi-run insertion is the
    ordinary shape, not an exotic one.

    Stepping by two interleaves them with whatever follows: the words
    are all present, the paragraph reads as a different sentence, and no
    count moves.

    THREE runs, because two cannot see it: the wrapper shifts right by
    one on every insertion, so a step of two lands exactly where the
    wrapper now stands and the second child still ends up in the right
    place. The third is the one that overshoots the tail."""
    xml = document(para(run("head "),
                        '<w:ins w:id="1" w:author="A" w:date="d">'
                        + run("one ") + run("two ") + run("three ")
                        + "</w:ins>",
                        run("tail")))

    assert text(accept(xml)) == ["head one two three tail"]
