"""Comment removal, footnotes and package hygiene.

All three were already solved inside DSI; these are the behaviours that
matter, tested where the papers can share them.
"""
from __future__ import annotations

import re

import pytest
from conftest import NS, comment, make_parts, para, run

from docxkit.comments import read_all, remove
from docxkit.errors import AnchorError
from docxkit.footnotes import append, find, find_all, remap, renumber_map
from docxkit.hygiene import (
    carry_properties,
    restore_math_glyphs,
    restore_parts,
    strip_parts,
)
from docxkit.package import core_property

# --------------------------------------------------------------- comments ---


def _commented(*ids: int) -> dict[str, bytes]:
    body = "".join(
        f'<w:p><w:commentRangeStart w:id="{i}"/>{run(f"text {i}")}'
        f'<w:commentRangeEnd w:id="{i}"/><w:r><w:rPr>'
        f'<w:rStyle w:val="CommentReference"/></w:rPr>'
        f'<w:commentReference w:id="{i}"/></w:r></w:p>' for i in ids)
    parts = make_parts(body, comment_items=tuple(
        comment(i, f"note {i}", para_id=f"AAAA{i:04d}") for i in ids))
    parts["word/commentsExtended.xml"] = (
        f"<w15:commentsEx {NS}>" + "".join(
            f'<w15:commentEx w15:paraId="AAAA{i:04d}" w15:done="0"/>'
            for i in ids) + "</w15:commentsEx>").encode("utf-8")
    parts["word/commentsIds.xml"] = (
        f"<w16cid:commentsIds {NS}>" + "".join(
            f'<w16cid:commentId w16cid:paraId="AAAA{i:04d}" '
            f'w16cid:durableId="000000{i:02d}"/>' for i in ids)
        + "</w16cid:commentsIds>").encode("utf-8")
    parts["word/commentsExtensible.xml"] = (
        f"<w16cex:commentsExtensible {NS}>" + "".join(
            f'<w16cex:commentExtensible w16cex:durableId="000000{i:02d}" '
            f'w16cex:dateUtc="2026-07-29T00:00:00Z"/>' for i in ids)
        + "</w16cex:commentsExtensible>").encode("utf-8")
    return parts


def test_read_all_lists_id_author_and_text():
    got = read_all(_commented(1, 2))
    assert [(c[0], c[2]) for c in got] == [("1", "note 1"), ("2", "note 2")]
    assert all(author == "Tester" for _, author, _ in got)


def test_remove_clears_all_six_places():
    """Deleting only the definition leaves dangling anchors, which Word
    reports as unreadable content."""
    parts = _commented(1, 2)
    assert remove(parts, ["1"]) == 1

    doc = parts["word/document.xml"].decode("utf-8")
    assert 'w:id="1"' not in doc, "an anchor survived in document.xml"
    assert "commentReference" in doc, "comment 2's reference was destroyed"
    for name, needle in (
            ("word/comments.xml", "note 1"),
            ("word/commentsExtended.xml", "AAAA0001"),
            ("word/commentsIds.xml", "AAAA0001"),
            ("word/commentsExtensible.xml", "00000001")):
        assert needle not in parts[name].decode("utf-8"), f"{name} kept it"


def test_remove_leaves_the_other_comments_intact():
    parts = _commented(1, 2, 3)
    remove(parts, ["2"])
    assert [c[0] for c in read_all(parts)] == ["1", "3"]
    for name, needle in (("word/commentsExtended.xml", "AAAA0001"),
                         ("word/commentsIds.xml", "AAAA0003")):
        assert needle in parts[name].decode("utf-8")


def test_remove_several_at_once_and_report_the_count():
    parts = _commented(1, 2, 3)
    assert remove(parts, ["1", "3"]) == 2
    assert [c[0] for c in read_all(parts)] == ["2"]


def test_remove_nothing_is_a_noop():
    parts = _commented(1)
    before = dict(parts)
    assert remove(parts, []) == 0
    assert parts == before


# -------------------------------------------------------------- footnotes ---

FOOTNOTES = (
    f"<w:footnotes {NS}>"
    f'<w:footnote w:id="-1"><w:p>{run("separator")}</w:p></w:footnote>'
    f'<w:footnote w:id="0"><w:p>{run("continuation")}</w:p></w:footnote>'
    f'<w:footnote w:id="6"><w:p>{run("EU-11 member states in our sample.")}'
    "</w:p></w:footnote>"
    f'<w:footnote w:id="7"><w:p>{run("Data are from the LFS.")}'
    "</w:p></w:footnote></w:footnotes>")


def test_find_all_skips_words_separator_notes():
    assert [f.id for f in find_all(FOOTNOTES)] == ["6", "7"]
    assert len(find_all(FOOTNOTES, include_reserved=True)) == 4


def test_find_locates_by_text():
    assert find(FOOTNOTES, "EU-11").id == "6"


def test_find_rejects_an_ambiguous_or_missing_anchor():
    with pytest.raises(AnchorError, match="0 hits"):
        find(FOOTNOTES, "nowhere")
    with pytest.raises(AnchorError, match="2 hits"):
        find(FOOTNOTES, "e")            # matches both notes


def test_append_adds_inside_the_paragraph():
    """A run placed directly in w:footnote makes Word reject the part."""
    out = append(FOOTNOTES, "EU-11", " See also Kim (2025).")
    note = find(out, "EU-11")
    assert note.text.endswith("See also Kim (2025).")
    assert "</w:p></w:footnote>" in note.xml
    assert note.xml.index("<w:r>") > note.xml.index("<w:p>")


def test_renumber_map_matches_on_text_not_id():
    """Word renumbers ids on save, so the same note has a different id in
    the author's copy."""
    authors = FOOTNOTES.replace('w:id="6"', 'w:id="4"').replace(
        'w:id="7"', 'w:id="5"')
    assert renumber_map(authors, FOOTNOTES) == {"4": "6", "5": "7"}


def test_remap_rewrites_the_references():
    para_xml = ('<w:p><w:r><w:footnoteReference w:id="4"/></w:r>'
                '<w:r><w:footnoteReference w:id="5"/></w:r></w:p>')
    out = remap(para_xml, {"4": "6", "5": "7"})
    assert 'w:id="6"' in out and 'w:id="7"' in out
    assert 'w:id="4"' not in out


def test_remap_leaves_unmapped_ids_alone():
    para_xml = '<w:p><w:r><w:footnoteReference w:id="9"/></w:r></w:p>'
    assert remap(para_xml, {"4": "6"}) == para_xml


# ---------------------------------------------------------------- hygiene ---


def _with_custom_xml() -> dict[str, bytes]:
    parts = make_parts(para(run("body")))
    parts["customXml/item1.xml"] = b"<b:Sources/>"
    parts["customXml/itemProps1.xml"] = b"<ds:datastoreItem/>"
    parts["[Content_Types].xml"] = (
        b'<Types><Override PartName="/customXml/itemProps1.xml" '
        b'ContentType="application/xml"/>'
        b'<Override PartName="/word/document.xml" ContentType="doc"/>'
        b"</Types>")
    parts["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Id="rId1" '
        b'Target="../customXml/item1.xml"/>'
        b'<Relationship Id="rId2" Target="styles.xml"/></Relationships>')
    return parts


def test_strip_parts_removes_the_tree_and_its_references():
    """A dangling Override or relationship is what Word calls unreadable
    content."""
    parts = _with_custom_xml()
    dropped = strip_parts(parts)
    assert dropped == ["customXml/item1.xml", "customXml/itemProps1.xml"]
    assert not any(n.startswith("customXml/") for n in parts)
    ct = parts["[Content_Types].xml"].decode("utf-8")
    rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
    assert "customXml" not in ct and "customXml" not in rels
    assert "/word/document.xml" in ct, "unrelated overrides must survive"
    assert 'Id="rId2"' in rels, "unrelated relationships must survive"


def test_strip_parts_never_touches_the_manuscript():
    parts = _with_custom_xml()
    before = parts["word/document.xml"]
    strip_parts(parts)
    assert parts["word/document.xml"] == before


def test_strip_parts_on_a_clean_package_is_a_noop():
    parts = make_parts(para(run("body")))
    before = dict(parts)
    assert strip_parts(parts) == []
    assert parts == before


# Word's Compare drops the customXml data store on EVERY rebuild, and
# `promote` then copies the batch over working.docx — so the loss reaches
# the live manuscript in one step, with lint clean and validate PASSing
# (Parental Style 2026-08-12).

def test_restore_parts_puts_the_tree_back_with_its_references():
    source = _with_custom_xml()
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)                    # exactly what Compare leaves

    back = restore_parts(rebuilt, source)
    assert back == ["customXml/item1.xml", "customXml/itemProps1.xml"]
    assert rebuilt["customXml/item1.xml"] == source["customXml/item1.xml"]
    ct = rebuilt["[Content_Types].xml"].decode("utf-8")
    rels = rebuilt["word/_rels/document.xml.rels"].decode("utf-8")
    assert 'PartName="/customXml/itemProps1.xml"' in ct
    assert 'Target="../customXml/item1.xml"' in rels
    assert ct.count("</Types>") == 1 and rels.count("</Relationships>") == 1


def test_a_relationship_ALREADY_pointing_at_the_tree_is_not_doubled():
    """Word drops the PART and can leave the reference behind. Adding a
    second relationship to the same target — on a fresh id, so nothing
    downstream sees a duplicate — is what makes Word open the file with
    a repair warning, which is the failure this whole function exists to
    avoid."""
    source = _with_custom_xml()
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)
    # the rels entry survived the rebuild; the part did not
    rebuilt["word/_rels/document.xml.rels"] = (
        source["word/_rels/document.xml.rels"])

    restore_parts(rebuilt, source)

    rels = rebuilt["word/_rels/document.xml.rels"].decode("utf-8")
    assert rels.count('Target="../customXml/item1.xml"') == 1


def test_a_restored_relationship_takes_a_FREE_id():
    """The source's rId is somebody else's relationship in the rebuild,
    and Word opens a duplicated id with a repair warning."""
    source = _with_custom_xml()
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)
    # the rebuild has since minted rId1 for something of its own
    rebuilt["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Id="rId1" Target="fontTable.xml"/>'
        b'<Relationship Id="rId2" Target="styles.xml"/></Relationships>')

    restore_parts(rebuilt, source)
    rels = rebuilt["word/_rels/document.xml.rels"].decode("utf-8")
    ids = re.findall(r'Id="(rId\d+)"', rels)
    assert len(ids) == len(set(ids)), rels
    assert 'Target="fontTable.xml"' in rels, "the id's owner was overwritten"
    assert "customXml" in rels


def test_restore_parts_leaves_a_part_that_is_already_there():
    """A rescue, not a sync: the target's own copy is the newer one."""
    source = _with_custom_xml()
    live = _with_custom_xml()
    live["customXml/item1.xml"] = b"<b:Sources>newer</b:Sources>"
    assert restore_parts(live, source) == []
    assert live["customXml/item1.xml"] == b"<b:Sources>newer</b:Sources>"


# The same loss one level down, on the FIELDS of docProps/core.xml. Word
# rebuilds that part with only lastModifiedBy/revision/created/modified,
# so the part-level check above is SATISFIED while the title, author and
# keywords are gone — LI7's dc:title was missing for four days, twice,
# with nothing anywhere reporting it (2026-08-15).

_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
    'package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dcterms="http://purl.org/dc/terms/">'
    "<dc:title>Loneliness Risk Index</dc:title>"
    "<dc:creator>Michael Lokshin</dc:creator>"
    "<cp:keywords>loneliness; index</cp:keywords>"
    "<cp:revision>7</cp:revision>"
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-08-08T10:00:00Z'
    "</dcterms:modified></cp:coreProperties>")

#: What Word's Compare hands back: the part, holding its own save fields
#: and nothing the document said about itself.
_REGENERATED_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
    'package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dcterms="http://purl.org/dc/terms/">'
    "<cp:lastModifiedBy>Word</cp:lastModifiedBy>"
    "<cp:revision>1</cp:revision>"
    '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-08-15T09:00:00Z'
    "</dcterms:modified></cp:coreProperties>")


def _titled() -> dict[str, bytes]:
    parts = make_parts(para(run("body")))
    parts["docProps/core.xml"] = _CORE.encode("utf-8")
    parts["_rels/.rels"] = (
        b'<Relationships><Relationship Id="rId1" '
        b'Target="word/document.xml"/></Relationships>')
    return parts


def test_carry_properties_puts_back_what_a_regenerated_core_xml_lost():
    source = _titled()
    rebuilt = _titled()
    rebuilt["docProps/core.xml"] = _REGENERATED_CORE.encode("utf-8")

    carried = carry_properties(rebuilt, source)

    assert carried == ["dc:title", "dc:creator", "cp:keywords"]
    core = rebuilt["docProps/core.xml"].decode("utf-8")
    assert "<dc:title>Loneliness Risk Index</dc:title>" in core
    assert "<dc:creator>Michael Lokshin</dc:creator>" in core


def test_carry_properties_leaves_the_TIMESTAMPS_to_the_new_file():
    """core.xml's `modified` and `revision` belong to the file being
    written; carrying the part wholesale would backdate a deliverable to
    its source, which is why this is field by field."""
    source = _titled()
    rebuilt = _titled()
    rebuilt["docProps/core.xml"] = _REGENERATED_CORE.encode("utf-8")

    carry_properties(rebuilt, source)

    core = rebuilt["docProps/core.xml"].decode("utf-8")
    assert "2026-08-15T09:00:00Z" in core, "the redline's own save time"
    assert "2026-08-08" not in core
    assert "<cp:revision>1</cp:revision>" in core


def test_carry_properties_rebuilds_the_part_word_dropped_entirely():
    """Flat OPC carries no docProps at all, so the deliverable a journal
    opens is untitled unless the part, its content type and its package
    relationship are all put back."""
    source = _titled()
    rebuilt = make_parts(para(run("body")))
    rebuilt["_rels/.rels"] = (
        b'<Relationships><Relationship Id="rId1" '
        b'Target="word/document.xml"/></Relationships>')
    rebuilt["[Content_Types].xml"] = b"<Types></Types>"

    assert "dc:title" in carry_properties(rebuilt, source)

    assert "docProps/core.xml" in rebuilt
    ct = rebuilt["[Content_Types].xml"].decode("utf-8")
    rels = rebuilt["_rels/.rels"].decode("utf-8")
    assert 'PartName="/docProps/core.xml"' in ct
    assert 'Target="docProps/core.xml"' in rels
    ids = re.findall(r'Id="(rId\d+)"', rels)
    assert len(ids) == len(set(ids)), rels
    assert core_property(rebuilt, "dc:title") == "Loneliness Risk Index"


def test_carry_properties_never_overwrites_a_value_that_is_there():
    """A rescue, not a sync — the same contract as restore_parts."""
    source = _titled()
    live = _titled()
    live["docProps/core.xml"] = _CORE.replace(
        "Loneliness Risk Index", "Loneliness Risk Index, revised").encode()

    assert carry_properties(live, source) == []
    assert core_property(live, "dc:title") == "Loneliness Risk Index, revised"


def test_carry_properties_on_a_source_with_nothing_to_say_is_a_noop():
    """No part is invented for a document that never had one."""
    source = make_parts(para(run("body")))
    rebuilt = make_parts(para(run("body")))
    assert carry_properties(rebuilt, source) == []
    assert "docProps/core.xml" not in rebuilt


def test_compare_collateral_reports_a_property_the_part_no_longer_carries():
    """The minimum the build owes a reader when the carry cannot reach
    it: the part is present, the same size class, and the value is gone."""
    from docxkit.tracked import compare_collateral

    source = _titled()
    rebuilt = _titled()
    rebuilt["docProps/core.xml"] = _REGENERATED_CORE.encode("utf-8")

    notes = compare_collateral(source, rebuilt)

    assert any("property LOST: dc:title" in n for n in notes), notes
    assert not any("cp:revision" in n for n in notes), \
        "a save field is not a document property"


def test_missing_parts_ignores_what_word_regenerates():
    """docProps/* is Word's own bookkeeping; every other absence is a
    loss. Both used to be reported with the same line."""
    from docxkit.package import missing_parts

    baseline = _with_custom_xml()
    baseline["docProps/app.xml"] = b"<Properties/>"
    batch = dict(baseline)
    del batch["docProps/app.xml"]
    assert missing_parts(batch, baseline) == []
    del batch["customXml/item1.xml"]
    assert missing_parts(batch, baseline) == ["customXml/item1.xml"]


def test_remove_keeps_the_text_the_comment_was_anchored_on():
    """`_drop_reference_run` walks back to the LAST run boundary before
    the mark. Cutting at the FIRST one instead takes every earlier run
    in the paragraph with it — the prose the comment was about — and the
    existing tests only asked whether the comment's own machinery was
    gone. Seventy-two survivors sat in that walk."""
    parts = _commented(1, 2)
    remove(parts, ["1"])
    doc = parts["word/document.xml"].decode("utf-8")
    assert "text 1" in doc, "the commented prose went with the reference run"
    assert "text 2" in doc
    assert 'w:id="1"' not in doc


# ------------------------------------- math glyphs a round-trip flattens ---
#
# Word rewrites the OMML while deriving a redline and turns U+2212 into
# an ASCII hyphen doing it. Measured on AFI (2026-08-17): 2 minus signs
# in the baseline, 0 in the built batch, and the 57 in the PROSE of both
# untouched. Nothing else in the toolkit sees it — the text layer reads
# the same words and the equation still renders.

def _parts_with(math: str, *, prose: str = "unchanged prose"
                ) -> dict[str, bytes]:
    doc = (f"<w:document><w:body><w:p><w:r><w:t>{prose}</w:t></w:r>"
           f"<m:oMath><m:r><m:t>{math}</m:t></m:r></m:oMath>"
           "</w:p></w:body></w:document>")
    return {"word/document.xml": doc.encode("utf-8")}


def test_a_flattened_MINUS_is_put_back():
    built = _parts_with("a - b")
    source = _parts_with("a − b")

    restored = restore_math_glyphs(built, source)

    assert restored == ["word/document.xml: 'a - b' -> 'a − b'"]
    assert "a − b" in built["word/document.xml"].decode("utf-8")


def test_PROSE_is_never_touched():
    """Only `m:t`. A hyphen in a sentence is a hyphen, and the
    round-trip does not rewrite prose in the first place."""
    built = _parts_with("a - b", prose="a well-known result")
    source = _parts_with("a − b", prose="a well−known result")

    restore_math_glyphs(built, source)

    assert "well-known" in built["word/document.xml"].decode("utf-8")


def test_a_run_the_source_spells_with_a_HYPHEN_is_left_alone():
    """A hyphen inside maths is a legitimate character — a range, a
    variable name — and the repair only puts back what a source really
    spells with the glyph."""
    built = _parts_with("x-y")
    source = _parts_with("x-y")

    assert restore_math_glyphs(built, source) == []
    assert "x-y" in built["word/document.xml"].decode("utf-8")


def test_an_AMBIGUOUS_form_is_dropped_rather_than_guessed():
    """Two source runs that flatten to the same text and disagree about
    WHICH character is the minus: one equation subtracts and hyphenates,
    the other hyphenates and subtracts. Nothing here can tell which this
    run was, and repairing on a coin flip rewrites the author's own
    character in whichever it guessed wrong."""
    built = _parts_with("a - b - c")
    a = {"word/document.xml": "<m:t>a − b - c</m:t>".encode()}
    b = {"word/document.xml": "<m:t>a - b − c</m:t>".encode()}

    assert restore_math_glyphs(built, a, b) == []
    assert "a - b - c" in built["word/document.xml"].decode("utf-8")


def test_a_source_that_spells_it_PLAINLY_vetoes_the_repair():
    """One source has the glyph and another does not: the same coin
    flip, and the same answer — leave it."""
    built = _parts_with("a - b")
    with_glyph = {"word/document.xml": "<m:t>a − b</m:t>".encode()}
    without = {"word/document.xml": b"<m:t>a - b</m:t>"}

    assert restore_math_glyphs(built, with_glyph, without) == []


def test_a_run_that_already_has_the_glyph_is_not_reported():
    built = _parts_with("a − b")
    source = _parts_with("a − b")

    assert restore_math_glyphs(built, source) == []


def test_footnotes_and_headers_are_repaired_too():
    """The equation the author is watching is as likely to be in a note
    as in the body, and Compare rewrites every part it touches."""
    built = {"word/footnotes.xml": b"<m:t>c - d</m:t>"}
    source = {"word/footnotes.xml": "<m:t>c − d</m:t>".encode()}

    restored = restore_math_glyphs(built, source)

    assert restored == ["word/footnotes.xml: 'c - d' -> 'c − d'"]


def test_a_document_with_no_math_glyphs_anywhere_is_a_no_op():
    built = _parts_with("a - b")
    before = dict(built)

    assert restore_math_glyphs(built, _parts_with("p + q")) == []
    assert built == before


# ---------------------------------------------- the relationship ids ------
#
# `_free_rid` decides which id a restored part is referenced by, and it
# had 8 survivors: the fixtures never made the WANTED id collide, which
# is the whole case it exists for — Compare renumbers the relationships
# it keeps, so the id a part had is routinely somebody else's now.

def test_the_id_a_part_HAD_is_reused_when_it_is_free():
    from docxkit.hygiene import _free_rid

    rels = '<Relationships><Relationship Id="rId1"/></Relationships>'

    assert _free_rid(rels, "rId7") == "rId7"


def test_a_TAKEN_id_moves_to_one_past_the_highest():
    """Not the next free NUMBER — one past the highest. Filling a gap
    would be legal and is not what Word does, and matching Word keeps a
    rebuilt package diffable against one it wrote."""
    from docxkit.hygiene import _free_rid

    rels = ('<Relationships><Relationship Id="rId7"/>'
            '<Relationship Id="rId3"/></Relationships>')

    assert _free_rid(rels, "rId7") == "rId8"


def test_with_no_id_wanted_the_next_one_is_taken():
    from docxkit.hygiene import _free_rid

    rels = '<Relationships><Relationship Id="rId4"/></Relationships>'

    assert _free_rid(rels, "") == "rId5"


def test_an_EMPTY_rels_file_starts_at_rId1():
    """rId0 is not a name Word writes."""
    from docxkit.hygiene import _free_rid

    assert _free_rid("<Relationships/>", "") == "rId1"


def _bare_mark(*ids: int) -> dict[str, bytes]:
    """Comment 1's reference mark sits BARE in the paragraph, with a
    text run before it — the shape a foreign or repaired document can
    carry, and the one the walk had never seen."""
    body = ""
    for i in ids:
        mark = (f'<w:commentReference w:id="{i}"/>' if i == 1 else
                f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                f'<w:commentReference w:id="{i}"/></w:r>')
        body += (f'<w:p><w:commentRangeStart w:id="{i}"/>{run(f"text {i}")}'
                 f'<w:commentRangeEnd w:id="{i}"/>{mark}</w:p>')
    return make_parts(body, comment_items=tuple(
        comment(i, f"note {i}", para_id=f"AAAA{i:04d}") for i in ids))


def test_removing_a_comment_whose_mark_is_NOT_in_a_run_keeps_the_prose():
    """S1, found 2026-08-18 by mutation testing `_drop_reference_run`.

    The walk took the last run to START before the mark as the run
    around it. A run that CLOSED before the mark is a neighbour, so the
    deletion ran from that neighbour's start to the next `</w:r>` after
    the mark — across the paragraph and into the next one. `remove`
    returned 2 and the body came back as `<w:p></w:p>`: every word of
    both paragraphs gone, reported as success.

    The mark itself goes, because a reference to a deleted comment is
    what Word calls unreadable content."""
    parts = _bare_mark(1, 2)

    assert remove(parts, ["1", "2"]) == 2

    doc = parts["word/document.xml"].decode("utf-8")
    assert "text 1" in doc and "text 2" in doc, "the author's prose"
    assert "commentReference" not in doc, "and nothing left pointing at it"
    assert 'w:id="1"' not in doc and 'w:id="2"' not in doc


def test_a_reference_in_an_UNCLOSED_run_does_not_stop_the_walk():
    """The malformed branch's `continue`. A run that never closes is
    what a truncated or hand-repaired document carries, and the walk
    drops the reference MARK there rather than a run it cannot find the
    end of — because a reference to a comment that no longer exists is
    what Word calls unreadable content.

    `break` in its place stops at the first one, and every reference
    after it stays in the document: `remove` reports the comments gone
    and Word refuses to open the file. Two marks are what it takes to
    see, and both have to be in the same unclosed run."""
    # the SAME id twice, because the walk runs once per comment: a
    # document with one reference per comment gives that loop a single
    # pass, and `break` cannot be told from `continue` in it. Two marks
    # for one comment is what a hand-repaired or merged file carries,
    # and this module's job is to survive those.
    body = ('<w:p><w:r><w:t>the sentence someone queried</w:t>'
            '<w:commentReference w:id="1"/>'
            '<w:commentReference w:id="1"/></w:p>')
    parts = make_parts(body, comment_items=(
        comment(1, "note 1", para_id="AAAA0001"),))

    assert remove(parts, ["1"]) == 1

    doc = parts["word/document.xml"].decode("utf-8")
    assert "commentReference" not in doc, doc
    assert "the sentence someone queried" in doc, "and the prose stays"


# The `inside` test beside those branches — whether the last run to
# START before the mark is still OPEN at it — is now belt to
# `_carries_more_than`'s braces, and its mutants are equivalent because
# of that (`tools/kill_check.py`, expect_kill=False). Read as
# `>= -1` it calls every neighbour run enclosing, and the run it then
# measures reaches from that neighbour's start to the next `</w:r>`
# AFTER the mark — which always carries the neighbour's own close tag,
# so `_carries_more_than` is true and the mark alone is dropped. The
# same output, by the other guard. Repairing the S1 above turned its
# neighbour into an equivalent.


def test_removing_ONE_of_two_comments_leaves_the_other_mark_alone():
    """The same walk, run to the end: dropping comment 1's bare mark
    must not disturb comment 2's run, which is what the offsets after
    the skipped mark decide."""
    parts = _bare_mark(1, 2)

    assert remove(parts, ["1"]) == 1

    doc = parts["word/document.xml"].decode("utf-8")
    assert 'w:commentReference w:id="2"' in doc
    assert 'w:id="1"' not in doc
    assert "text 1" in doc and "text 2" in doc


def _mark_run(cid: int, *, closed: bool = True) -> str:
    ref = (f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
           f'<w:commentReference w:id="{cid}"/>')
    return ref + ("</w:r>" if closed else "")


def _prose_then_mark(cid: int, *, closed: bool = True,
                     lead: str = "") -> tuple[dict[str, bytes], str]:
    """Prose in its own run, then the reference in its own — which is
    what Word writes, and the shape that tells the ENCLOSING run from
    the neighbour before it. Returns the parts and the mark's run, so a
    caller can say exactly what removal should leave behind."""
    mark = _mark_run(cid, closed=closed)
    body = (f'<w:p>{run(lead) if lead else ""}'
            f'<w:commentRangeStart w:id="{cid}"/>'
            f'{run("the sentence someone queried")}'
            f'<w:commentRangeEnd w:id="{cid}"/>{mark}'
            f'{run("and the paragraph goes on.")}</w:p>')
    return make_parts(body, comment_items=(
        comment(cid, f"note {cid}", para_id=f"AAAA{cid:04d}"),)), mark


@pytest.mark.parametrize("lead", ["", "A", "ABC", "A longer opening clause, ",
                                  "Prose of some other length entirely so "
                                  "the offsets are nothing like round. "])
def test_removing_a_comment_drops_ITS_run_and_NOTHING_else(lead):
    """Two things at once, and the offsets decide both.

    `starts[-1]`, not `starts[0]`: both runs start before the mark, and
    taking the first deletes the sentence the comment was ABOUT along
    with the mark on it. Then `pos = close + len("</w:r>")` decides
    where the walk resumes — `close | 6` agrees with `close + 6`
    whenever the low bits happen to be clear, which one fixture settles
    by luck, so the lead varies the offset five ways.

    The assertion is the whole document: what removal leaves must be the
    original minus the three pieces that belong to the comment."""
    parts, mark = _prose_then_mark(1, lead=lead)
    before = parts["word/document.xml"].decode("utf-8")

    assert remove(parts, ["1"]) == 1

    doc = parts["word/document.xml"].decode("utf-8")
    want = (before.replace('<w:commentRangeStart w:id="1"/>', "")
            .replace('<w:commentRangeEnd w:id="1"/>', "").replace(mark, ""))
    assert doc == want


def test_a_reference_run_that_is_never_closed_stops_the_walk():
    """`close == -1`. Malformed, and the only question is what it costs:
    the walk stops and everything already gathered plus the rest of the
    document is handed back, rather than a slice taken to an index that
    is not there."""
    parts, _mark = _prose_then_mark(1, closed=False)
    before = parts["word/document.xml"].decode("utf-8")

    assert remove(parts, ["1"]) == 1

    doc = parts["word/document.xml"].decode("utf-8")
    assert "the sentence someone queried" in doc
    assert doc.count("<w:p>") == before.count("<w:p>")
    assert 'w:commentRangeStart w:id="1"' not in doc, "the anchor still goes"
    assert "commentReference" not in doc, (
        "and so does the mark: a reference to a comment that no longer "
        "exists is what Word calls unreadable, whatever shape the run "
        "around it was left in")


def test_a_mark_sharing_its_run_with_PROSE_costs_only_the_mark():
    """The second half of the same S1, found by review on 2026-08-18 —
    the first fix told a NEIGHBOUR run from an enclosing one, and this
    is an enclosing run that also carries the author's sentence.

    Word writes the reference alone in its own run; another producer
    need not, and dropping the run took the sentence with it and
    reported success."""
    body = ('<w:p><w:commentRangeStart w:id="1"/>'
            '<w:r><w:t>Prose the author wrote.</w:t>'
            '<w:commentReference w:id="1"/></w:r>'
            '<w:commentRangeEnd w:id="1"/>'
            + run("and the paragraph goes on.") + "</w:p>")
    parts = make_parts(body, comment_items=(
        comment(1, "note 1", para_id="AAAA0001"),))

    assert remove(parts, ["1"]) == 1

    doc = parts["word/document.xml"].decode("utf-8")
    assert "Prose the author wrote." in doc
    assert "and the paragraph goes on." in doc
    assert "commentReference" not in doc, "the mark itself still goes"


def test_a_run_holding_ONLY_the_mark_goes_with_it():
    """The other side of that test, and the shape Word writes: a run
    whose whole content is the reference, carrying nothing but the
    CommentReference style. Leaving it behind is an empty styled run in
    the middle of a sentence."""
    body = (para(run("Prose."), '<w:commentRangeStart w:id="1"/>',
                 run("anchored"), '<w:commentRangeEnd w:id="1"/>',
                 '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                 '<w:commentReference w:id="1"/></w:r>'))
    parts = make_parts(body, comment_items=(
        comment(1, "note 1", para_id="AAAA0001"),))

    assert remove(parts, ["1"]) == 1

    doc = parts["word/document.xml"].decode("utf-8")
    assert "CommentReference" not in doc, "the run went with the mark"
    assert "Prose." in doc and "anchored" in doc


# --- the parts a scan must not stop at (2026-08-19) ---------------------
#
# hygiene's remaining survivors, and all of one kind: every `continue`
# in these two functions was free, because each fixture's parts happened
# to be in an order where stopping early and skipping one item come to
# the same thing. A package is a dict of a dozen parts in no particular
# order, and "the media file came first this time" is not a property any
# of them can rely on.


def test_a_BINARY_part_in_the_source_does_not_end_the_glyph_scan():
    """`continue`, not `break`: a real package carries images, fonts and
    a thumbnail, and the one that sorts first is nobody's choice. Under
    `break` a manuscript with a picture in it silently loses the repair
    — and the whole point of the function is that nothing else in the
    toolkit can see the difference."""
    built = _parts_with("a - b")
    source = {"word/media/image1.png": b"\x89PNG\r\n\x1a\n not xml",
              **_parts_with("a − b")}

    restored = restore_math_glyphs(built, source)

    assert restored == ["word/document.xml: 'a - b' -> 'a − b'"]


def test_a_BINARY_part_in_the_package_does_not_end_the_repair():
    """The same walk over the document being repaired."""
    built = {"word/media/image1.png": b"\x89PNG\r\n\x1a\n not xml",
             **_parts_with("a - b")}

    restored = restore_math_glyphs(built, _parts_with("a − b"))

    assert restored == ["word/document.xml: 'a - b' -> 'a − b'"]
    assert built["word/media/image1.png"].startswith(b"\x89PNG")


def test_a_math_run_the_sources_say_nothing_about_is_left_exactly_as_it_is():
    """`return m.group(0)` — the whole match, not a piece of it. Every
    fixture until now had one equation and something to say about it, so
    the arm that declines to touch a run had never run. A document with
    two equations and evidence for one is the ordinary case."""
    doc = ("<w:document><w:body><w:p>"
           "<m:oMath><m:r><m:t>a - b</m:t></m:r></m:oMath>"
           "<m:oMath><m:r><m:t>x-y</m:t></m:r></m:oMath>"
           "</w:p></w:body></w:document>")
    built = {"word/document.xml": doc.encode("utf-8")}
    source = {"word/document.xml": "<m:t>a − b</m:t>".encode()}

    restored = restore_math_glyphs(built, source)

    assert restored == ["word/document.xml: 'a - b' -> 'a − b'"]
    out = built["word/document.xml"].decode("utf-8")
    assert "<m:t>x-y</m:t>" in out, "untouched, tag and text"
    assert out.count("<m:t") == 2 and out.count("</m:t>") == 2


def test_a_relationship_the_rebuild_kept_does_not_end_the_restore():
    """`continue`, not `break`: Word drops some parts of a tree and
    keeps the references to others, so an entry already present is
    routinely followed by one that is missing. Under `break` the second
    tree is never restored and the package is left half repaired —
    which is the dangling-reference state this function exists to
    prevent."""
    source = _with_custom_xml()
    source["customXml/item2.xml"] = b"<b:Sources/>"
    source["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Id="rId1" '
        b'Target="../customXml/item1.xml"/>'
        b'<Relationship Id="rId3" Target="../customXml/item2.xml"/>'
        b'<Relationship Id="rId2" Target="styles.xml"/></Relationships>')
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)
    rebuilt["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Id="rId1" '
        b'Target="../customXml/item1.xml"/></Relationships>')

    restore_parts(rebuilt, source)

    rels = rebuilt["word/_rels/document.xml.rels"].decode("utf-8")
    assert rels.count('Target="../customXml/item1.xml"') == 1
    assert 'Target="../customXml/item2.xml"' in rels


def test_a_relationship_to_something_ELSE_does_not_end_the_restore():
    """The other `continue`: the relationships that are not ours come
    first as often as not, and every package has more of them than of
    ours."""
    source = _with_custom_xml()
    source["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Id="rId2" Target="styles.xml"/>'
        b'<Relationship Id="rId9" Target="fontTable.xml"/>'
        b'<Relationship Id="rId1" '
        b'Target="../customXml/item1.xml"/></Relationships>')
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)

    restore_parts(rebuilt, source)

    rels = rebuilt["word/_rels/document.xml.rels"].decode("utf-8")
    assert 'Target="../customXml/item1.xml"' in rels


def test_a_package_with_no_relationships_part_is_left_alone():
    """`_DOC_RELS in parts AND in source` — both, not either. A fragment
    assembled in memory has no rels part at all, and `or` reaches into
    the one that is missing and raises KeyError on a rescue that is
    supposed to be safe to attempt."""
    source = _with_custom_xml()
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)
    del rebuilt["word/_rels/document.xml.rels"]

    back = restore_parts(rebuilt, source)

    assert back == ["customXml/item1.xml", "customXml/itemProps1.xml"]
    assert "word/_rels/document.xml.rels" not in rebuilt


def test_a_restored_relationship_KEEPS_its_own_id_when_that_id_is_free():
    """`f"rId{was.group(1)}" if was else ""` — the id the source used is
    the one to ask for, so a package rebuilt from a source whose ids are
    still free comes back byte-comparable to it. Only a collision moves
    it."""
    source = _with_custom_xml()
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)
    rebuilt["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Id="rId5" '
        b'Target="styles.xml"/></Relationships>')

    restore_parts(rebuilt, source)

    rels = rebuilt["word/_rels/document.xml.rels"].decode("utf-8")
    assert ('<Relationship Id="rId1" Target="../customXml/item1.xml"/>'
            in rels)


# --- the reference walk, read as a string (2026-08-19) ------------------
#
# `_drop_reference_run` is the function the 2026-08-18 S1 lived in, and
# it came back from the next measurement with 16 survivors — the most of
# any function in the module. The tests above go through `remove` and
# ask what SURVIVES, which is the right question for a data-loss defect
# and cannot see where the cursor lands: `pos = at + len(needle)` is
# `at | len(needle)` and `at & len(needle)` too, as long as the document
# holds ONE mark and everything after it is appended in one go.
#
# So these call the walk directly and compare the whole string. Two
# marks under one id is the shape that makes the cursor observable —
# damaged, but so is every document this function is reached for.

def _drop(doc: str, cid: str = "1") -> str:
    from docxkit.comments import _drop_reference_run
    return _drop_reference_run(doc, cid)


MARK = '<w:commentReference w:id="1"/>'


def test_TWO_marks_under_one_id_both_go_and_nothing_between_them_moves():
    """`continue`, and the cursor it continues from. A mark left behind
    is a reference to a comment that no longer exists, which is what
    Word calls unreadable content — and a cursor that lands one
    character out eats a character of the author's prose on its way to
    the second one."""
    doc = ("<w:p><w:r><w:t>Alpha.</w:t></w:r>"
           f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>{MARK}'
           "</w:r><w:r><w:t>Beta, between the two.</w:t></w:r>"
           f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>{MARK}'
           "</w:r><w:r><w:t>Gamma.</w:t></w:r></w:p>")

    assert _drop(doc, "1") == (
        "<w:p><w:r><w:t>Alpha.</w:t></w:r>"
        "<w:r><w:t>Beta, between the two.</w:t></w:r>"
        "<w:r><w:t>Gamma.</w:t></w:r></w:p>")


def test_TWO_BARE_marks_under_one_id_both_go():
    """The same, on the branch that drops only the mark. Both `continue`
    statements have to keep the walk going; under `break` the second
    mark stays in a document whose comment is gone."""
    doc = (f"<w:p>{MARK}<w:r><w:t>Between.</w:t></w:r>{MARK}</w:p>")

    assert _drop(doc, "1") == "<w:p><w:r><w:t>Between.</w:t></w:r></w:p>"


def test_a_mark_BEFORE_any_run_in_the_document_is_dropped_alone():
    """`bool(starts) and ...` — the guard, not an optimisation. With no
    run open before the mark there is no `starts[-1]` to search from,
    and under `or` the walk indexes an empty list. A mark ahead of every
    run is what a paragraph whose comment anchors its opening looks like
    after a merge."""
    doc = f"<w:p>{MARK}<w:r><w:t>The opening sentence.</w:t></w:r></w:p>"

    assert _drop(doc, "1") == (
        "<w:p><w:r><w:t>The opening sentence.</w:t></w:r></w:p>")


def test_a_run_with_NO_properties_holding_only_the_mark_goes_whole():
    """`run_xml.index(">") + 1` — the body starts after the run's own
    opening tag, and one character either side of that is either the
    `>` itself (which reads as content, so the run is kept, empty, in
    the middle of a sentence) or the first character of the mark (which
    reads as nothing left, on a run that is holding prose)."""
    doc = ("<w:p><w:r><w:t>Prose.</w:t></w:r>"
           f"<w:r>{MARK}</w:r>"
           "<w:r><w:t>More prose.</w:t></w:r></w:p>")

    assert _drop(doc, "1") == (
        "<w:p><w:r><w:t>Prose.</w:t></w:r>"
        "<w:r><w:t>More prose.</w:t></w:r></w:p>")


def test_a_run_with_ATTRIBUTES_and_no_properties_goes_whole_too():
    """`<w:r w:rsidR="00A1">` — the opening tag is longer than five
    characters, which is what makes the `index(">")` a search rather
    than a constant."""
    # twenty characters, so `index(">")` is 19 -- ODD, and `19 | 1` is
    # 19 while `19 + 1` is 20. On an even index the two agree, which is
    # every run tag whose length is odd, `<w:r>` among them
    doc = ("<w:p><w:r><w:t>Prose.</w:t></w:r>"
           f'<w:r w:rsidR="00A1">{MARK}</w:r>'
           "</w:p>")

    assert _drop(doc, "1") == "<w:p><w:r><w:t>Prose.</w:t></w:r></w:p>"


def test_another_comments_mark_is_not_touched_by_the_walk():
    """The needle carries the id, so a second comment's mark is prose as
    far as this walk is concerned — and it must come back byte for byte,
    the run around it included."""
    other = '<w:commentReference w:id="2"/>'
    doc = ("<w:p><w:r><w:t>Prose.</w:t></w:r>"
           f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>{MARK}'
           "</w:r>"
           f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>{other}'
           "</w:r></w:p>")

    assert _drop(doc, "1") == (
        "<w:p><w:r><w:t>Prose.</w:t></w:r>"
        '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
        f"{other}</w:r></w:p>")


def test_a_document_with_no_mark_at_all_comes_back_unchanged():
    doc = "<w:p><w:r><w:t>Nothing to do here.</w:t></w:r></w:p>"

    assert _drop(doc, "1") is not None
    assert _drop(doc, "1") == doc


def test_a_run_that_is_never_CLOSED_costs_the_mark_and_nothing_else():
    """`close == -1`. The document is malformed and the walk cannot
    know where the run ends, so it takes the mark alone and leaves the
    rest exactly as it found it. Reached directly here because the
    slice a wrong branch would take (`doc[starts[-1]:5]`) is an empty
    string, and what happens to it next is an exception rather than a
    finding."""
    doc = f"<w:p><w:r><w:t>Prose.</w:t></w:r><w:r>{MARK}</w:p>"

    assert _drop(doc, "1") == "<w:p><w:r><w:t>Prose.</w:t></w:r><w:r></w:p>"


def test_a_SHARED_run_does_not_end_the_walk_either():
    """The third `continue`, and its cursor. A mark sharing its run
    with the author's prose costs only the mark -- and the walk has to
    carry on to the second mark, landing exactly past the first."""
    doc = ("<w:p>"
           f"<w:r><w:t>Prose the author wrote.</w:t>{MARK}</w:r>"
           "<w:r><w:t>Between.</w:t></w:r>"
           f"<w:r><w:t>And more prose.</w:t>{MARK}</w:r></w:p>")

    assert _drop(doc, "1") == (
        "<w:p><w:r><w:t>Prose the author wrote.</w:t></w:r>"
        "<w:r><w:t>Between.</w:t></w:r>"
        "<w:r><w:t>And more prose.</w:t></w:r></w:p>")


def test_a_relationship_with_NO_TARGET_does_not_end_the_restore():
    """The third `continue` in that walk, and the last one without a
    test — its two neighbours have had one since the round that wrote
    them. A `<Relationship>` with no `Target` is malformed and a
    rebuild can leave one; under `break` it ends the walk, and every
    tree below it is restored as a part with nothing pointing at it,
    which is the dangling half of the defect this function exists to
    avoid."""
    source = _with_custom_xml()
    source["word/_rels/document.xml.rels"] = (
        b'<Relationships><Relationship Id="rId7"/>'
        b'<Relationship Id="rId1" '
        b'Target="../customXml/item1.xml"/></Relationships>')
    rebuilt = _with_custom_xml()
    strip_parts(rebuilt)

    restore_parts(rebuilt, source)

    rels = rebuilt["word/_rels/document.xml.rels"].decode("utf-8")
    assert 'Target="../customXml/item1.xml"' in rels


def test_a_paragraph_nothing_SMARTENS_keeps_its_entities():
    """`changed = False`. The rewrite below it re-escapes every `w:t` it
    touches, so a paragraph that needed no smartening but ran the loop
    anyway comes back with its character entities resolved —
    `&#8212;` as a literal em dash. Nothing is wrong with the document
    that produces, and everything is wrong with the DIFF: a compare
    against the previous round then reports a paragraph the author
    never touched.

    The fixture has a quote in it (or the guard above returns early)
    and nothing to do with it: an apostrophe that opens a word is not
    the possessive this pass converts."""
    from docxkit.hygiene import smarten

    xml = ("<w:document><w:body><w:p><w:r>"
           "<w:t>&#8212;'tis a quote nobody pairs</w:t>"
           "</w:r></w:p></w:body></w:document>")

    out, report = smarten(xml)

    assert out == xml, out
    assert (report.apostrophes, report.quotes) == (0, 0)


# --- what the run of 2026-08-20 left in `hygiene`: 3.6 % (16/449) -----
#
# Two of the sixteen are the tests above. The rest are equivalent, each
# through kill_check:
#
# * `_is_equation_carrier`'s `rows[0]` as `rows[-1]` and `cells[-1]` as
#   `cells[1]`: the lines above raise the count to exactly one row and
#   exactly two cells.
# * `_set_before`'s `.replace("<w:spacing", ..., 1)` as `2`. The string
#   being replaced IS one matched `<w:spacing .../>` tag, so it holds
#   the needle once and a larger count finds nothing more.
# * `_set_before`'s `out != para_xml` as `is not`: `set_para_property`
#   hands back the string it was given when it changes nothing.
# * `_smarten_para`'s `stream.count('"') % 2 == 0` as `<= 0` (a
#   remainder of 2 is 0 or 1), its `ch == "'"` as `is` (a
#   one-character string is interned), its `strict=True` as `False`
#   (the two lists are built together, one entry per `w:t`), and its
#   sort key `-start()` as `~start()`, which orders identically.
# * `restore_math_glyphs`' `len(texts) == 1` as `<= 1`: `texts` is a
#   set that had something added to it, so it is never empty.
# * its `if out != text` as `>`, `>=` and `is not`. `re.sub` hands back
#   the same object when nothing matched, and every substitution this
#   makes replaces a downgraded character with the glyph it stands for
#   — MATH_DOWNGRADES maps U+2212 to a hyphen, and U+2212 sorts above
#   it — so a changed string always sorts higher. That last one is an
#   argument about the TABLE, and it is worth re-reading if a downgrade
#   is ever added whose glyph sorts BELOW its plain form.
#
# Recorded rather than argued: `table_spacing`'s `pos = m.start() +
# len(para)` read as `|`. OR never answers below `m.start()`, so the
# walk still moves forward, but it can land INSIDE the paragraph it
# just handled — and then the next search finds the same one, computes
# the same offset, and does not stop. Every fixture here agrees with
# `+` because the two numbers share no bits; what a test for the other
# case would assert is that the loop terminates, which is a test that
# hangs when it fails.
