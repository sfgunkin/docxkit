"""Which PARTS `authors` reads and rewrites, and what it counts.

`set_author` exists so a deliverable goes out under one name, and it
sweeps the whole package to do it. The three lines no test reached are
all about the sweep's boundary: the parts it must skip, and the report it
hands back.

Skipping a non-XML part is not defensive noise. `w:author="..."` is an
ordinary byte sequence, and a .docx carries images, fonts and embedded
objects; decoding one as UTF-8 and running a regex over it would at best
find nothing and at worst rewrite bytes in the middle of a PNG.
"""
from __future__ import annotations

from collections import Counter

from docxkit.authors import PEOPLE_PART, AuthorReport, read_authors, set_author

A = 'w:id="1" w:author="Reviewer" w:date="2026-01-01T00:00:00Z"'
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
      '2006/main" xmlns:w15="http://schemas.microsoft.com/office/word/'
      '2012/wordml"')

#: A PNG whose bytes happen to spell an author attribute. Not contrived:
#: the pattern is short, and a compressed stream can produce anything.
FAKE_PNG = b'\x89PNG\r\n\x1a\n w:author="Ghost" \xff\xd8\xfe'


def parts_with(body: str, **extra: bytes) -> dict[str, bytes]:
    parts = {
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": (
            f'<w:document {NS}><w:body>{body}</w:body></w:document>'
        ).encode("utf-8"),
    }
    parts.update(extra)
    return parts


def tracked(text: str) -> str:
    return f"<w:p><w:ins {A}><w:r><w:t>{text}</w:t></w:r></w:ins></w:p>"


# ------------------------------------------------------ what is read ----


def test_a_binary_part_is_not_scanned_for_authors():
    parts = parts_with(tracked("edit"),
                       **{"word/media/image1.png": FAKE_PNG})
    found = read_authors(parts)
    assert found == {"Reviewer": 1}
    assert "Ghost" not in found


def test_an_author_is_read_the_way_a_person_writes_it():
    """Stored escaped, reported unescaped — because a caller naming them
    in `only` will type the name, not the entity."""
    body = ('<w:p><w:ins w:id="1" w:author="Smith &amp; Co" '
            'w:date="2026-01-01T00:00:00Z"><w:r><w:t>x</w:t></w:r>'
            "</w:ins></w:p>")
    assert read_authors(parts_with(body)) == {"Smith & Co": 1}


# --------------------------------------------------- what is written ----


def test_a_binary_part_is_left_byte_for_byte_alone():
    parts = parts_with(tracked("edit"),
                       **{"word/media/image1.png": FAKE_PNG})
    set_author(parts, "M Lokshin")
    assert parts["word/media/image1.png"] == FAKE_PNG
    assert b"Ghost" in parts["word/media/image1.png"]


def test_the_document_itself_is_restamped():
    parts = parts_with(tracked("edit"))
    report = set_author(parts, "M Lokshin")
    assert report.revisions == 1
    assert b'w:author="M Lokshin"' in parts["word/document.xml"]


def test_a_people_part_with_nothing_to_dedupe_is_not_rewritten():
    """`if out != text` — rewriting an unchanged part churns bytes for
    no reason, and a package diff then reports a part that did not
    change."""
    people = (f'<w15:people {NS}><w15:person w15:author="Solo">'
              f'<w15:presenceInfo w15:providerId="None" '
              f'w15:userId="Solo"/></w15:person></w15:people>').encode()
    parts = parts_with(tracked("edit"), **{PEOPLE_PART: people})
    set_author(parts, "Solo")
    assert parts[PEOPLE_PART] == people


# -------------------------------------------------- what is reported ----


def test_the_total_counts_what_was_rewritten_not_what_was_kept():
    """`people` is entries LEFT in word/people.xml, not entries renamed,
    so adding it to the total would report work that did not happen."""
    report = AuthorReport(before=Counter({"A": 3}), revisions=3, comments=2,
                          people=7, properties=1)
    assert report.total == 6


def test_the_total_of_an_untouched_document_is_zero():
    parts = parts_with("<w:p><w:r><w:t>plain</w:t></w:r></w:p>")
    assert set_author(parts, "M Lokshin").total == 0
