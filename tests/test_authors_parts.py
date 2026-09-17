"""Which PARTS `authors` reads and rewrites, and what it counts.

`set_author` exists so a deliverable goes out under ONE name, and it
sweeps the whole package to do it. What the suite had never exercised was
the edge of that sweep: the parts it must skip, the registry it must
collapse, and the numbers it reports afterwards.

Skipping a non-XML part is not defensive noise. `w:author="..."` is an
ordinary byte sequence, and a .docx carries images, fonts and embedded
objects; decoding one as UTF-8 and running a substitution over it would
at best find nothing and at worst rewrite bytes inside a PNG.

Two of these tests are about the difference between an edit and a record
of one. A `w15:author` in the people registry is renamed like any other,
but it is NOT a tracked change, and counting it reports more edits than
the document contains. And renaming several reviewers to one name leaves
several identical `w15:person` elements, which Word tolerates and its
reviewing pane lists once per entry — reading as several people who
happen to share a name.
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
        ).encode(),
    }
    parts.update(extra)
    return parts


def tracked(text: str) -> str:
    return f"<w:p><w:ins {A}><w:r><w:t>{text}</w:t></w:r></w:ins></w:p>"


# ------------------------------------------------------ what is read ----


def binary_first(body: str) -> dict[str, bytes]:
    """The image BEFORE the document.

    Order matters to what this proves. With the media part last, skipping
    it and stopping at it look identical — the test passes either way and
    checks nothing about the guard.
    """
    parts: dict[str, bytes] = {"word/media/image1.png": FAKE_PNG}
    parts.update(parts_with(body))
    return parts


def test_a_binary_part_is_not_scanned_for_authors():
    found = read_authors(binary_first(tracked("edit")))
    assert found == {"Reviewer": 1}
    assert "Ghost" not in found


def test_a_binary_part_is_skipped_rather_than_stopped_at():
    """`continue`, not `break`: the parts AFTER an image still hold the
    document."""
    parts = binary_first(tracked("edit"))
    report = set_author(parts, "M Lokshin")
    assert report.revisions == 1
    assert b'w:author="M Lokshin"' in parts["word/document.xml"]


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
    """The part a `set_author` had nothing to do to comes back as it
    was, byte for byte.

    What this does NOT pin is the `if out != text` guard itself. This
    docstring used to say that rewriting an unchanged part makes "a
    package diff report a part that did not change", and that is not
    so: `package.changed_parts` compares CONTENT, so a rewrite with
    equal bytes is invisible to it — and to every other reader here.
    Only `is` can see the difference, which is why the two mutants on
    that line are claimed equivalent in `tools/equivalents.toml` rather
    than killed. A test that could tell them apart would be pinning
    object identity, which this package deliberately does not promise.
    """
    people = (f'<w15:people {NS}><w15:person w15:author="Solo">'
              f'<w15:presenceInfo w15:providerId="None" '
              f'w15:userId="Solo"/></w15:person></w15:people>').encode()
    parts = parts_with(tracked("edit"), **{PEOPLE_PART: people})
    set_author(parts, "Solo")
    assert parts[PEOPLE_PART] == people


# ------------------------------------------------ the people registry ----


def people_of(*names: str) -> bytes:
    entries = "".join(
        f'<w15:person w15:author="{n}"><w15:presenceInfo '
        f'w15:providerId="None" w15:userId="{n}"/></w15:person>'
        for n in names)
    return f"<w15:people {NS}>{entries}</w15:people>".encode()


def test_a_registry_entry_is_renamed_but_is_not_a_revision():
    """`m.group(1) == "w"`. `w15:author` in the people registry is not a
    tracked change — counting it would report more edits than the
    document contains."""
    parts = parts_with(tracked("edit"), **{PEOPLE_PART: people_of("Old")})
    report = set_author(parts, "M Lokshin")
    assert report.revisions == 1                 # the w:ins, not the w15
    assert b'w15:author="M Lokshin"' in parts[PEOPLE_PART]


def test_reviewers_renamed_to_one_name_collapse_to_one_entry():
    """Word tolerates several identical `w15:person` elements, but the
    reviewing pane lists the name once per entry — which reads as several
    people who happen to share a name."""
    parts = parts_with(tracked("edit"),
                       **{PEOPLE_PART: people_of("Alice", "Bob", "Carol")})
    report = set_author(parts, "M Lokshin")
    assert report.people == 1
    assert parts[PEOPLE_PART].count(b"<w15:person ") == 1


def test_distinct_reviewers_are_left_distinct():
    """`only` protects a real co-author, so the registry must keep them."""
    parts = parts_with(tracked("edit"),
                       **{PEOPLE_PART: people_of("Alice", "Bob")})
    report = set_author(parts, "M Lokshin", only={"Reviewer"})
    assert report.people == 2
    assert parts[PEOPLE_PART].count(b"<w15:person ") == 2


# --------------------------------------------------------- initials ----


def test_initials_come_from_the_first_three_words():
    from docxkit.authors import initials_for

    assert initials_for("Ana Maria Lopez Garcia") == "AML"
    assert initials_for("Michael Lokshin") == "ML"
    assert initials_for("Lokshin") == "L"
    assert initials_for("M. Lokshin") == "ML"


def test_a_nameless_string_still_yields_a_mark():
    from docxkit.authors import initials_for

    assert initials_for("   ") == "?"


def test_every_comment_initial_is_counted():
    body = (tracked("edit")
            + '<w:p><w:r><w:t>x</w:t></w:r></w:p>')
    comments = (f'<w:comments {NS}>'
                f'<w:comment w:id="1" w:author="Reviewer" w:initials="R">'
                f"<w:p><w:r><w:t>one</w:t></w:r></w:p></w:comment>"
                f'<w:comment w:id="2" w:author="Reviewer" w:initials="R">'
                f"<w:p><w:r><w:t>two</w:t></w:r></w:p></w:comment>"
                f"</w:comments>").encode()
    parts = parts_with(body, **{"word/comments.xml": comments})
    report = set_author(parts, "M Lokshin")
    assert report.comments == 2
    assert parts["word/comments.xml"].count(b'w:initials="ML"') == 2


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
