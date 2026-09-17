"""One name for each part, and one definition of "the document's text".

R1 in ROBUSTNESS_PLAN put the run/text/bookmark WALKS in `_xml`. The PART
NAMES stayed scattered — the body's spelled 38 times across 16 modules, the
footnotes' 19 times across 13 — and the cost was never a typo. It was that
each site decided for itself what "the document" meant, and three decided
wrong in one week:

  * `renumber` renumbered the body and left a footnote pointing at the old
    table. Nothing dangled, because the old number still existed elsewhere;
  * `tracked.package_counts` reported "0 pending revisions" — the number the
    papers read to decide a document is at truth — for a batch that had
    edited only a footnote;
  * `compare`'s integrity layer read a field target off raw XML and returned
    the RSID of the next run, because it never assembled the footnote's
    instruction.

So the rule this file enforces: a part is named in `_xml` and nowhere else,
and an operation that describes the whole document iterates `TEXT_PARTS`.

The allowlist is short and each entry says why. Growing it is a decision;
growing it silently is the drift this exists to stop.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import module_name, source_files

#: modules that may spell a part name, and the reason each may. Keyed by
#: the importable name, so a half of a subpackage can be named without
#: exempting another module that happens to share its file name.
ALLOWED = {
    "_xml": "defines them",
    # the packaging layer works in part names by nature: it reads, writes
    # and rewrites the zip container itself
    "package": "reads and writes the container",
    # the CLI names parts in help text and argument defaults, where a
    # symbol would be less readable than the string the user types
    "cli": "user-facing strings",
}

#: Either quote, because both are a spelling of the same literal: ruff
#: settles on double quotes in this package, and a rule that only sees
#: the style the linter happens to enforce is a rule that stops working
#: the day the style does.
PART_RE = re.compile(
    r"""["']word/(document|footnotes|endnotes|comments)\.xml["']""")


def modules() -> list[Path]:
    """Every module, SUBPACKAGES INCLUDED — see `conftest.source_files`.

    This asked `SRC.glob("*.py")` until 2026-09-18, so the sixteen
    halves of `revision/` were never parametrized and the rule below
    could not fail for any of them. Demonstrated by putting a part name
    in `revision/_promote.py` and watching this file stay green.
    """
    return source_files()


@pytest.mark.parametrize("path", modules(), ids=module_name)
def test_a_part_is_named_in_one_place(path: Path):
    name = module_name(path)
    if name in ALLOWED:
        return
    text = path.read_text(encoding="utf-8")
    hits = sorted({m.group(0) for m in PART_RE.finditer(text)})
    assert not hits, (
        f"{name} spells a part name itself: {hits}. Import DOCUMENT / "
        f"FOOTNOTES / ENDNOTES / COMMENTS from ._xml, and if the operation "
        f"describes the whole document, iterate text_parts(parts) instead of "
        f"naming one part.")


def test_the_pattern_catches_a_part_name_in_EITHER_quote():
    """The other canary. A rule over source can fail by reading nothing
    — `test_the_walk_finds_the_package` covers that — or by matching
    nothing, which looks exactly the same from here: every module clean,
    every time. So the pattern is held to a specimen of what it is for.
    """
    assert PART_RE.search('parts["word/document.xml"]')
    assert PART_RE.search("parts['word/footnotes.xml']")
    assert PART_RE.search('name = "word/endnotes.xml"')
    assert not PART_RE.search('parts["word/styles.xml"]')
    assert not PART_RE.search('f"word/{name}.xml"'), (
        "a built name is not a spelling this rule can read; it is caught "
        "by the reader, not here")


def test_text_parts_covers_what_a_reader_reads():
    from docxkit._xml import DOCUMENT, ENDNOTES, FOOTNOTES, TEXT_PARTS
    assert TEXT_PARTS == (DOCUMENT, FOOTNOTES, ENDNOTES)


def test_text_parts_skips_absent_parts_and_keeps_reading_order():
    from docxkit._xml import text_parts
    parts = {"word/document.xml": b"<body/>", "word/styles.xml": b"<s/>",
             "word/endnotes.xml": b"<e/>"}
    assert text_parts(parts) == [("word/document.xml", "<body/>"),
                                 ("word/endnotes.xml", "<e/>")]


def test_the_allowlist_names_only_modules_that_exist():
    """An allowlist entry for a module that has been renamed or split stops
    guarding anything, and reads as though it still does."""
    names = {module_name(p) for p in modules()}
    assert set(ALLOWED) <= names, set(ALLOWED) - names
