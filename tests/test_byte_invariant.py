"""The invariant string surgery exists for: bytes outside an edit survive.

README, `package` and `edit` justify reading and writing the package as
strings, not through python-docx, by the PARTS an edit does not touch —
they come out byte for byte. The stronger reason was written nowhere and
tested nowhere (REVIEW_2026-09-28 §1): bytes outside an edit INSIDE a
part stay identical too, so Word's Compare and a round-to-round diff see
the edit and nothing else. A parse-and-serialise round trip would lose
it — ` />` becomes `/>`, an empty paired element collapses, attributes
reorder, and the offsets the papers splice at move.

It is the property any change to the substrate (the span lexer the
review proposes) must keep, so it is pinned here before that work, over
a document spelled every way a producer spells it.
"""
from __future__ import annotations

import os
from collections.abc import Callable

import pytest
from conftest import document, make_parts, write

from docxkit import package, save
from docxkit._xml import DOCUMENT
from docxkit.edit import italicize, rep, replace_in_para, set_run_properties
from docxkit.find import edit_para

XMLNS_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

#: Everything around the target, in the spellings other producers write:
#: an empty paragraph, ` />`, attributes in an unusual order, an empty
#: `w:t`, run properties declaring a namespace, an XML comment, a nested
#: table, a bookmark, a self-closing `w:tab` — none of which a writer
#: has any business re-spelling.
BEFORE = (
    "<w:p/>"
    '<w:p w14:textId="0000AAAA" w14:paraId="0000AAAA">'
    '<w:pPr><w:spacing w:after="0" w:before="120" /></w:pPr>'
    f"<w:r><w:rPr {XMLNS_W}><w:b /></w:rPr><w:t>Heading</w:t></w:r>"
    "<w:r><w:t/></w:r></w:p>"
    "<!-- a producer's comment -->"
    "<w:tbl><w:tr><w:tc><w:tbl><w:tr><w:tc><w:p><w:r><w:t>inner</w:t>"
    "</w:r></w:p></w:tc></w:tr></w:tbl><w:p/></w:tc></w:tr></w:tbl>")
TARGET = (
    '<w:p w14:paraId="0000BBBB" w14:textId="0000BBBB">'
    '<w:bookmarkStart w:name="here" w:id="7"/>'
    "<w:r><w:t xml:space=\"preserve\">The quick brown </w:t></w:r>"
    "<w:r><w:rPr><w:i/></w:rPr><w:t>fox</w:t></w:r>"
    '<w:bookmarkEnd w:id="7"/>'
    "<w:r><w:tab/><w:t>jumps.</w:t></w:r></w:p>")
AFTER = (
    '<w:p><w:pPr><w:jc w:val="both" /></w:pPr>'
    "<w:r><w:t>Closing words.</w:t></w:r></w:p>"
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838" /></w:sectPr>')

XML = document(BEFORE + TARGET + AFTER)

#: One edit per writer, each confined to the target by its signature.
WRITERS: dict[str, Callable[[str], str]] = {
    "replace_in_para": lambda xml: edit_para(
        xml, "quick brown", lambda p: replace_in_para(p, "quick", "slow")),
    "italicize": lambda xml: edit_para(
        xml, "quick brown", lambda p: italicize(p, "brown")),
    "set_run_properties": lambda xml: edit_para(
        xml, "quick brown",
        lambda p: set_run_properties(p, {"sz": '<w:sz w:val="20"/>'})[0]),
    "rep": lambda xml: rep(xml, "quick", "slow"),
}


def _changed(before: str, after: str) -> tuple[int, int]:
    """The span of `before` that differs: common prefix and suffix cut."""
    head = len(os.path.commonprefix([before, after]))
    tail = len(os.path.commonprefix([before[head:][::-1],
                                     after[head:][::-1]]))
    return head, len(before) - tail


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_an_edit_changes_NOTHING_outside_the_paragraph_it_edits(writer):
    out = WRITERS[writer](XML)
    start = XML.index(TARGET)
    end = start + len(TARGET)

    assert out != XML, "the edit has to have happened for this to mean much"
    lo, hi = _changed(XML, out)
    assert start <= lo and hi <= end, (
        f"{writer} changed bytes outside the paragraph it edits: "
        f"{XML[min(lo, start):lo + 60]!r}")
    assert out.startswith(XML[:start]) and out.endswith(XML[end:])


def test_a_save_that_changes_nothing_writes_every_part_byte_for_byte(
        tmp_path):
    """The other half: across parts. A package with nothing for
    `preserve_space` to protect goes through the whole save — lint,
    backup, write — and comes back identical, part by part."""
    parts = make_parts("")
    parts[DOCUMENT] = XML.encode("utf-8")
    path = tmp_path / "paper.docx"
    write(path, parts)
    before = package.read_parts(path)

    report = save.save(path, dict(before))

    assert report.written and report.protected == 0
    assert package.read_parts(path) == before
