"""Package I/O: the round trip must not lose or reorder anything."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest
from conftest import make_parts, para, run, write

from docxkit import (
    backup,
    edit_in_place,
    is_locked,
    read_parts,
    write_docx,
)
from docxkit.package import next_backup_path


def test_round_trip_preserves_every_part(simple_docx, tmp_path):
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts)
    assert read_parts(out) == parts


def test_write_preserves_member_order(simple_docx, tmp_path):
    with zipfile.ZipFile(simple_docx) as z:
        order = z.namelist()
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts, order=order)
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == order


def test_write_includes_parts_the_transform_added(simple_docx, tmp_path):
    """A transform that adds media must not have it silently dropped."""
    with zipfile.ZipFile(simple_docx) as z:
        order = z.namelist()
    parts = read_parts(simple_docx)
    parts["word/media/image1.png"] = b"\x89PNG-not-really"
    out = tmp_path / "out.docx"
    write_docx(out, parts, order=order)
    assert "word/media/image1.png" in read_parts(out)


def test_edit_in_place_rewrites_and_preserves_untouched(simple_docx):
    before = read_parts(simple_docx)

    def transform(parts):
        xml = parts["word/document.xml"].decode("utf-8")
        parts["word/document.xml"] = xml.replace("Poland", "Romania").encode()
        return "done"

    assert edit_in_place(simple_docx, transform) == "done"
    after = read_parts(simple_docx)
    assert b"Romania" in after["word/document.xml"]
    assert after["[Content_Types].xml"] == before["[Content_Types].xml"]


def test_edit_in_place_dry_does_not_write(simple_docx):
    before = read_parts(simple_docx)

    def transform(parts):
        parts["word/document.xml"] = b"<destroyed/>"
        return "dry"

    assert edit_in_place(simple_docx, transform, dry=True) == "dry"
    assert read_parts(simple_docx) == before


def test_edit_in_place_leaves_file_intact_when_transform_raises(simple_docx):
    """A crash mid-transform must not truncate the manuscript."""
    before = read_parts(simple_docx)

    def transform(parts):
        parts["word/document.xml"] = b"<half-written/>"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        edit_in_place(simple_docx, transform)
    assert read_parts(simple_docx) == before


def test_backup_numbers_sequentially(tmp_path):
    src = tmp_path / "paper.docx"
    write(src, make_parts(para(run("x"))))
    first = backup(src, "user_edited")
    second = backup(src, "user_edited")
    assert first.name == "paper_user_edited1.docx"
    assert second.name == "paper_user_edited2.docx"
    assert (next_backup_path(src, "user_edited").name
            == "paper_user_edited3.docx")


def test_is_locked_false_for_closed_file(simple_docx):
    assert is_locked(simple_docx) is False


def test_is_locked_false_for_missing_file(tmp_path):
    assert is_locked(tmp_path / "nope.docx") is False


# --- did the author change this part, or did Word just re-save it? ---

_STYLE = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          b'<w:styles xmlns:w="http://schemas.openxmlformats.org/'
          b'wordprocessingml/2006/main">'
          b'<w:style w:type="paragraph" w:styleId="Normal">'
          b'<w:name w:val="Normal"/><w:rPr><w:sz w:val="24"/></w:rPr>'
          b"</w:style></w:styles>")


def _resaved(blob: bytes) -> bytes:
    """What a Word save does to a part it did not change: bind an extra
    namespace prefix, add rsids, reorder attributes, reindent."""
    w14 = (b'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
           b'xmlns:w="')
    return (blob.replace(b'xmlns:w="', w14)
                .replace(b"<w:style ", b'<w:style w:rsidR="00AB12CD" ')
                .replace(b"</w:style>", b"</w:style>\n  "))


def test_part_fingerprint_ignores_what_a_word_save_rewrites():
    """Comparing raw bytes reports a style edit on every author round-trip,
    and a warning that cries wolf is the one nobody reads."""
    from docxkit.package import part_fingerprint, same_part
    assert _resaved(_STYLE) != _STYLE
    assert same_part(_STYLE, _resaved(_STYLE))
    assert part_fingerprint(_STYLE) == part_fingerprint(_resaved(_STYLE))


def test_part_fingerprint_still_sees_a_real_style_edit():
    from docxkit.package import same_part
    bigger = _STYLE.replace(b'<w:sz w:val="24"/>', b'<w:sz w:val="28"/>')
    assert not same_part(_STYLE, bigger)


def test_part_fingerprint_keeps_leaf_whitespace():
    """A space inside a w:t is content, not indentation."""
    from docxkit.package import same_part
    doc = make_parts(para(run("Section 5")))["word/document.xml"]
    spaced = doc.replace(b"Section 5", b"Section  5")
    assert not same_part(doc, spaced)


def test_part_fingerprint_falls_back_to_bytes_for_non_xml():
    from docxkit.package import same_part
    assert same_part(b"\x89PNG binary", b"\x89PNG binary")
    assert not same_part(b"\x89PNG binary", b"\x89PNG other")


def test_write_leaves_no_staging_file_behind(simple_docx, tmp_path):
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts)
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_failed_write_keeps_the_previous_file_and_cleans_up(
        simple_docx, tmp_path, monkeypatch):
    """An interrupted save must not destroy the manuscript it replaces.

    Staging plus rename is what makes that true; the test pins it by
    breaking the rename, which is the last thing to happen.
    """
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts)
    before = out.read_bytes()

    def boom(src, dst, **kw):
        raise OSError("disk went away")

    monkeypatch.setattr("docxkit.package.os.replace", boom)
    with pytest.raises(OSError, match="disk went away"):
        write_docx(out, parts)

    assert out.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_rides_out_a_transient_lock(simple_docx, tmp_path,
                                          monkeypatch):
    """OneDrive holds the target open for a moment; that is not failure.

    The sync engine intermittently locks or read-onlys a file that is
    being replaced — the same race Stata surfaces as r(608). Giving up
    on the first refusal would turn it into a lost save.
    """
    import os as os_module

    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts)

    real = os_module.replace
    tries = {"n": 0}

    def flaky(src, dst, **kw):
        tries["n"] += 1
        if tries["n"] < 3:
            raise PermissionError(32, "being used by another process")
        return real(src, dst, **kw)

    monkeypatch.setattr("docxkit.package.os.replace", flaky)
    monkeypatch.setattr("docxkit.package.time.sleep", lambda _s: None)
    write_docx(out, parts)

    assert tries["n"] == 3
    assert read_parts(out) == parts


def test_write_gives_up_on_a_permanent_lock(simple_docx, tmp_path,
                                            monkeypatch):
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"

    def locked(src, dst, **kw):
        raise PermissionError(32, "locked forever")

    monkeypatch.setattr("docxkit.package.os.replace", locked)
    monkeypatch.setattr("docxkit.package.time.sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        write_docx(out, parts)
    assert list(tmp_path.glob("*.tmp")) == []


def test_changed_parts_separates_real_edits_from_a_re_save():
    from docxkit.package import changed_parts
    before = {"word/styles.xml": _STYLE, "word/document.xml": b"<a/>",
              "word/footer1.xml": b"<f/>"}
    after = {"word/styles.xml": _resaved(_STYLE),          # noise
             "word/document.xml": b"<a><b/></a>",          # real
             "docProps/core.xml": b"<c/>"}                 # Word restored it
    got = changed_parts(before, after)
    assert got == {"changed": ["word/document.xml"],
                   "added": ["docProps/core.xml"],
                   "removed": ["word/footer1.xml"],
                   "resaved": ["word/styles.xml"]}


# ------------------------------------------------ docProps/core.xml ---
#
# Word's Compare drops docProps outright and the copy Word writes back
# afterwards is missing individual elements, so "set" here has to mean
# "create if absent" — a rewrite that only substitutes leaves a
# deliverable with no title and no author while reporting success.

_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
         'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/'
         'dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">')


def core(inner: str = "") -> dict[str, bytes]:
    return {"docProps/core.xml":
            (_HEAD + inner + "</cp:coreProperties>").encode("utf-8")}


def test_reading_a_property_that_is_there():
    from docxkit.package import core_property
    p = core("<dc:title>Loneliness Risk Index</dc:title>")
    assert core_property(p, "dc:title") == "Loneliness Risk Index"


def test_absent_element_and_absent_part_both_read_as_none():
    """Different from an empty string, and worth telling apart."""
    from docxkit.package import core_property
    assert core_property(core("<dc:title></dc:title>"), "dc:title") == ""
    assert core_property(core(), "dc:title") is None
    assert core_property({}, "dc:title") is None


def test_setting_an_existing_property_replaces_it():
    from docxkit.package import core_property, set_core_property
    p = core("<dc:title>Old</dc:title>")
    assert set_core_property(p, "dc:title", "New") is True
    assert core_property(p, "dc:title") == "New"


def test_setting_the_same_value_changes_nothing():
    from docxkit.package import set_core_property
    p = core("<dc:title>Same</dc:title>")
    before = p["docProps/core.xml"]
    assert set_core_property(p, "dc:title", "Same") is False
    assert p["docProps/core.xml"] == before


def test_a_missing_property_is_created_in_words_order():
    """CORE_ORDER is read off Word's own files: title precedes creator,
    which precedes lastModifiedBy. Out of order opens fine and fails a
    strict validator."""
    from docxkit.package import set_core_property
    p = core("<dc:creator>M</dc:creator>"
             "<cp:lastModifiedBy>M</cp:lastModifiedBy>")
    assert set_core_property(p, "dc:title", "Loneliness Risk Index") is True
    text = p["docProps/core.xml"].decode("utf-8")
    assert text.index("<dc:title>") < text.index("<dc:creator>")
    assert text.index("<dc:creator>") < text.index("<cp:lastModifiedBy>")


def test_a_property_with_no_later_sibling_goes_last():
    from docxkit.package import set_core_property
    p = core("<dc:title>T</dc:title>")
    set_core_property(p, "dcterms:modified", "2026-08-08T00:00:00Z")
    text = p["docProps/core.xml"].decode("utf-8")
    assert text.index("<dc:title>") < text.index("<dcterms:modified>")
    assert text.endswith("</cp:coreProperties>")


def test_a_value_with_markup_characters_is_escaped():
    """A title carrying & or < would otherwise close the element early
    and make Word call the document unreadable."""
    from docxkit.package import core_property, set_core_property
    p = core()
    set_core_property(p, "dc:title", "Aging & Loneliness <2026>")
    text = p["docProps/core.xml"].decode("utf-8")
    assert "&amp;" in text and "&lt;2026&gt;" in text
    assert core_property(p, "dc:title") == ("Aging &amp; Loneliness "
                                            "&lt;2026&gt;")


def test_a_package_with_no_core_part_is_left_alone():
    from docxkit.package import set_core_property
    p: dict[str, bytes] = {}
    assert set_core_property(p, "dc:title", "T") is False
    assert p == {}


def test_the_result_parses():
    from lxml import etree

    from docxkit.package import set_core_property
    p = core("<dc:creator>M</dc:creator>")
    set_core_property(p, "dc:title", "A & B")
    etree.fromstring(p["docProps/core.xml"])


# --- what the first mutation run found (2026-08-17, package 25.6 %) -----
#
# 45 of the 86 survivors were in `_replace_atomically` — the retry loop
# that rides out a Windows sharing violation, which is what Word holding
# a file and OneDrive syncing one both look like. Nothing tested it at
# all: the happy path renames on the first attempt, and every mutation
# of the retry arithmetic left that untouched.

def _flaky_replace(fail: int, calls: list[int]):
    """An `os.replace` that raises PermissionError its first `fail`
    times, as a locked target does."""
    real = os.replace

    def replace(src, dst):
        calls.append(1)
        if len(calls) <= fail:
            raise PermissionError(32, "The process cannot access the file")
        real(src, dst)

    return replace


def test_a_locked_target_is_RETRIED_and_the_write_lands(monkeypatch,
                                                        tmp_path):
    """Word holds the file for a moment on save, and OneDrive holds it
    while it syncs. One PermissionError is not a failed build."""
    from docxkit import package as pkg

    target, tmp = tmp_path / "paper.docx", tmp_path / "paper.tmp"
    target.write_bytes(b"old")
    tmp.write_bytes(b"new")
    calls: list[int] = []
    monkeypatch.setattr(os, "replace", _flaky_replace(2, calls))
    monkeypatch.setattr(pkg.time, "sleep", lambda _s: None)

    pkg._replace_atomically(tmp, target)

    assert target.read_bytes() == b"new"
    assert len(calls) == 3                    # two refusals, then through


def test_the_retries_RUN_OUT_and_the_error_is_raised(monkeypatch,
                                                     tmp_path):
    """Six attempts, then the caller hears about it: a silent failure
    here loses the build's output and leaves the old file in place."""
    from docxkit import package as pkg

    target, tmp = tmp_path / "paper.docx", tmp_path / "paper.tmp"
    target.write_bytes(b"old")
    tmp.write_bytes(b"new")
    calls: list[int] = []
    monkeypatch.setattr(os, "replace", _flaky_replace(99, calls))
    monkeypatch.setattr(pkg.time, "sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        pkg._replace_atomically(tmp, target)

    assert len(calls) == 6
    assert target.read_bytes() == b"old"


def test_the_WAIT_grows_with_each_attempt(monkeypatch, tmp_path):
    """A fixed delay is six tries inside a second and a quarter; Word's
    save takes longer than that. The wait steps up so the last attempt
    is more than a second after the first."""
    from docxkit import package as pkg

    target, tmp = tmp_path / "paper.docx", tmp_path / "paper.tmp"
    target.write_bytes(b"old")
    tmp.write_bytes(b"new")
    slept: list[float] = []
    monkeypatch.setattr(os, "replace", _flaky_replace(99, []))
    monkeypatch.setattr(pkg.time, "sleep", slept.append)

    with pytest.raises(PermissionError):
        pkg._replace_atomically(tmp, target)

    assert slept == [0.2, 0.4, 0.6000000000000001, 0.8, 1.0]
    assert len(slept) == 5              # no wait after the last attempt


def test_a_READ_ONLY_target_is_cleared_before_each_retry(monkeypatch,
                                                         tmp_path):
    """OneDrive marks a file read-only while it syncs, and that is a
    PermissionError the retry alone would never get past."""
    from docxkit import package as pkg

    target, tmp = tmp_path / "paper.docx", tmp_path / "paper.tmp"
    target.write_bytes(b"old")
    tmp.write_bytes(b"new")
    cleared: list[Path] = []
    monkeypatch.setattr(os, "replace", _flaky_replace(1, []))
    monkeypatch.setattr(pkg.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pkg, "_clear_readonly", cleared.append)

    pkg._replace_atomically(tmp, target)

    assert cleared == [target]


def test_an_unlocked_target_is_replaced_ON_THE_FIRST_TRY(monkeypatch,
                                                         tmp_path):
    """No sleeping on the ordinary path: a build writes many files."""
    from docxkit import package as pkg

    target, tmp = tmp_path / "paper.docx", tmp_path / "paper.tmp"
    target.write_bytes(b"old")
    tmp.write_bytes(b"new")
    slept: list[float] = []
    monkeypatch.setattr(pkg.time, "sleep", slept.append)

    pkg._replace_atomically(tmp, target)

    assert target.read_bytes() == b"new"
    assert slept == []


def test_a_property_lands_before_its_IMMEDIATE_successor():
    """CORE_ORDER is a sequence, and the search starts at the element
    right after the new one — start it one further along and a title
    inserted into a document that carries only a subject lands after it,
    which opens fine and fails a strict validator."""
    from docxkit.package import set_core_property

    p = core("<dc:subject>Ageing</dc:subject>")

    set_core_property(p, "dc:title", "Age-Friendly Jobs")

    text = p["docProps/core.xml"].decode("utf-8")
    assert text.index("<dc:title>") < text.index("<dc:subject>")


def test_an_UNKNOWN_tag_goes_last_where_it_displaces_nothing():
    from docxkit.package import set_core_property

    p = core("<dc:title>T</dc:title>")

    assert set_core_property(p, "cp:category", "Report") is True

    text = p["docProps/core.xml"].decode("utf-8")
    assert text.index("<dc:title>") < text.index("<cp:category>")
    assert text.endswith("</cp:coreProperties>")


def test_a_core_part_with_no_CLOSE_tag_still_gets_the_property_inside():
    """The last resort, for a part that is not a document Word wrote:
    the element goes just after the root's open tag, which is the only
    place it can go and still be inside the root."""
    from docxkit.package import set_core_property

    p = {"docProps/core.xml": (
        '<?xml version="1.0"?><cp:coreProperties xmlns:cp="x" '
        'xmlns:dc="y"/>').encode("utf-8")}

    assert set_core_property(p, "dc:title", "Salvaged") is True

    text = p["docProps/core.xml"].decode("utf-8")
    assert text.index("<dc:title>") > text.index("<cp:coreProperties")


def test_an_UNCHANGED_part_does_not_stop_the_walk():
    """`continue`, not `break`: the parts are sorted by name, so the
    first unchanged one is usually `[Content_Types].xml` — stopping
    there would report a package where nothing changed at all."""
    from docxkit.package import changed_parts

    before = {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"a"}
    after = {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"b"}

    report = changed_parts(before, after)

    assert report["changed"] == ["word/document.xml"]


def test_a_NON_XML_part_does_not_stop_the_malformed_walk():
    """Media comes first alphabetically in `word/`, and a document.xml
    that does not parse is the finding this exists for."""
    from docxkit.package import malformed_parts

    parts = {"word/media/image1.png": b"\x89PNG not xml at all",
             "word/document.xml": b"<w:document><w:body></w:document>"}

    bad = malformed_parts(parts)

    assert len(bad) == 1
    assert bad[0].startswith("word/document.xml: ")
