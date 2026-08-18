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
    before = document("".join(keep + [para(run("Alpha was.")),
                                      para(run("Beta was.")),
                                      para(run("Gamma was.")),
                                      para(run("Tail."))]))
    after = document("".join(keep + [para(run("Alpha is now.")),
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
    before = document("".join(keep + [para(run("Alpha.")),
                                      para(run("Beta.")),
                                      para(run("Gamma.")),
                                      para(run("Tail."))]))
    after = document("".join(keep + [para(run("All three, merged.")),
                                     para(run("Tail."))]))

    got = changed_paragraphs(before, after)

    assert [(c.paragraph, c.before, c.after) for c in got] == [
        (3, "Alpha.", "All three, merged."),
        (4, "Beta.", ""),
        (5, "Gamma.", "")]
