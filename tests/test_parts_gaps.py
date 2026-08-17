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

def _parts_with(math: str, *, prose: str = "unchanged prose") -> dict:
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
