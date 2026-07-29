"""Comment removal, footnotes and package hygiene.

All three were already solved inside DSI; these are the behaviours that
matter, tested where the papers can share them.
"""
from __future__ import annotations

import pytest
from conftest import NS, comment, make_parts, para, run

from docxkit.comments import read_all, remove
from docxkit.errors import AnchorError
from docxkit.footnotes import append, find, find_all, remap, renumber_map
from docxkit.hygiene import strip_parts

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
