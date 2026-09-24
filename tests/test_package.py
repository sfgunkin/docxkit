"""Package I/O: the round trip must not lose or reorder anything."""
from __future__ import annotations

import os
import re
import stat
import time
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
from docxkit.errors import PackageError
from docxkit.package import (
    CORE_PART,
    changed_parts,
    next_backup_path,
    same_part,
    set_core_property,
)


def test_round_trip_preserves_every_part(simple_docx, tmp_path):
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts)
    assert read_parts(out) == parts


def test_the_package_representation_has_a_NAME():
    """`dict[str, bytes]` was spelt 179 times across the package with
    no name for the thing every module passes around (review
    2026-09-03, row 8). `Parts` is that name, reachable from the top."""
    from docxkit import Parts
    from docxkit.package import Parts as same

    assert Parts is same
    assert Parts.__value__ == dict[str, bytes]


def test_no_annotation_SPELLS_OUT_the_name():
    """The name existed for three weeks and 160 annotations went on
    spelling the type, because it lived in `package`, which half the
    modules that pass parts around sit beside and may not import. It is
    `_xml.Parts` now; this keeps the count at the one definition.

    Read off the AST, so a docstring quoting the type (this one) is
    not a finding — and counted, so a walk that reads nothing fails."""
    import ast

    from conftest import module_name, source_files

    spelled, annotations = [], 0
    for path in source_files(include_init=True):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            anns = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                anns += [x.annotation for x in
                         (*a.posonlyargs, *a.args, *a.kwonlyargs,
                          a.vararg, a.kwarg)
                         if x is not None and x.annotation is not None]
                anns += [node.returns] if node.returns else []
            elif isinstance(node, ast.AnnAssign):
                anns.append(node.annotation)
            for ann in anns:
                text = ast.unparse(ann)
                annotations += "Parts" in text
                if "dict[str, bytes]" in text:
                    spelled.append(f"{module_name(path)}:{ann.lineno}")

    assert annotations > 150, f"only {annotations} — is the walk reading?"
    assert not spelled, f"say `Parts` (from `_xml`): {spelled}"


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


def _romania(parts):
    parts["word/document.xml"] = (
        parts["word/document.xml"].replace(b"Poland", b"Romania"))


def test_edit_in_place_writes_the_manuscript_by_the_same_staged_RENAME(
        simple_docx, monkeypatch):
    """`write_docx` stages a sibling `.tmp` and renames it over the
    target, and its docstring calls that load-bearing — the machine
    this runs on has unreliable mains power. `edit_in_place` used to do
    exactly that into TEMP and then COPY the result over the manuscript,
    which is the interruptible write the rename exists to avoid: a
    destination opened for writing and streamed into, truncated if the
    process dies half way. The property is that the manuscript is only
    ever the DESTINATION of a rename, from a sibling."""
    import os as os_module

    real = os_module.replace
    renames: list[tuple[Path, Path]] = []

    def recording(src, dst, **kw):
        renames.append((Path(src), Path(dst)))
        return real(src, dst, **kw)

    monkeypatch.setattr("docxkit.package.os.replace", recording)
    manuscript = Path(simple_docx)

    edit_in_place(manuscript, _romania)

    assert [dst for _src, dst in renames] == [manuscript]
    assert renames[0][0].parent == manuscript.parent
    assert list(manuscript.parent.glob("*.tmp")) == []
    assert b"Romania" in read_parts(manuscript)["word/document.xml"]


def test_edit_in_place_rides_out_a_transient_read_denial(
        simple_docx, monkeypatch):
    """The OneDrive race `read_parts` was hardened against on
    2026-08-20 — [Errno 13] with nothing holding the file, gone a moment
    later. The entry point the papers are told to use read through its
    own unretried copy of the file and never met that retry."""
    from docxkit import package as pkg

    calls: list[int] = []
    monkeypatch.setattr(pkg.zipfile, "ZipFile", _flaky_zip(2, calls))
    monkeypatch.setattr(pkg.time, "sleep", lambda _s: None)

    edit_in_place(simple_docx, _romania)

    assert len(calls) > 2                     # two refusals, then through
    assert b"Romania" in read_parts(simple_docx)["word/document.xml"]


def test_edit_in_place_writes_a_READ_ONLY_manuscript(simple_docx):
    """What `is_locked`'s wrong answer cost: `assert_unlocked` refused a
    read-only file as "open in Word", while `write_docx` one call later
    clears that bit and writes — the same file, two verdicts. OneDrive
    flips the bit mid-write (see `_replace_atomically`), so this is a
    state the manuscripts' own drive produces."""
    os.chmod(simple_docx, stat.S_IREAD)
    try:
        edit_in_place(simple_docx, _romania)
        assert b"Romania" in read_parts(simple_docx)["word/document.xml"]
    finally:
        os.chmod(simple_docx, stat.S_IREAD | stat.S_IWRITE)


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


def test_is_locked_false_for_a_READ_ONLY_file(simple_docx):
    """Measured 2026-09-03: a file with only S_IREAD set and nothing
    holding it raises PermissionError errno 13 from `open(.., "r+b")` —
    the errno a sharing violation arrives with too — and `is_locked`
    said True. So `assert_unlocked` sent the author to close a Word that
    was not open, and `readable()` snapshotted a file nobody held and
    reported reading a snapshot. The mode can tell the two apart, and
    the write path already reads it (`_clear_readonly`)."""
    os.chmod(simple_docx, stat.S_IREAD)
    try:
        assert is_locked(simple_docx) is False
    finally:
        os.chmod(simple_docx, stat.S_IREAD | stat.S_IWRITE)


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


def _flaky_zip(fail: int, calls: list[int]):
    """A `ZipFile` that raises PermissionError its first `fail` opens."""
    real = zipfile.ZipFile

    def opener(path, *a, **kw):
        calls.append(1)
        if len(calls) <= fail:
            raise PermissionError(13, "Permission denied")
        return real(path, *a, **kw)

    return opener


def test_a_TRANSIENT_read_denial_is_retried_and_the_read_lands(
        monkeypatch, simple_docx):
    """The write side rode this race out and the read side did not: two
    suites reading a manuscript on a OneDrive-backed tree failed with
    [Errno 13] while nothing held the file, and a retry read it at once.
    360 passed -> 1 failed -> 360 passed is the worst shape a gate has.
    """
    from docxkit import package as pkg

    calls: list[int] = []
    monkeypatch.setattr(pkg.zipfile, "ZipFile", _flaky_zip(2, calls))
    monkeypatch.setattr(pkg.time, "sleep", lambda _s: None)

    parts = pkg.read_parts(simple_docx)

    assert "word/document.xml" in parts
    assert len(calls) == 3                    # two refusals, then through


def test_a_read_denial_that_PERSISTS_says_the_file_is_locked(
        monkeypatch, simple_docx):
    """After five retries it is not a transient sync, it is Word — and
    the message is the one the write side already gives for it, rather
    than a bare errno the caller has no reason to retry."""
    from docxkit import package as pkg

    calls: list[int] = []
    slept: list[float] = []
    monkeypatch.setattr(pkg.zipfile, "ZipFile", _flaky_zip(99, calls))
    monkeypatch.setattr(pkg.time, "sleep", slept.append)

    with pytest.raises(PackageError, match=re.escape("locked (open in Word)")):
        pkg.read_parts(simple_docx)

    assert len(calls) == 6
    # five waits, not six: sleeping after the LAST attempt delays the
    # error by more than a second and changes nothing about it
    assert len(slept) == 5


def test_a_missing_file_is_NOT_retried(monkeypatch, tmp_path):
    """A retry is for a race. A path that does not exist will not start
    existing, and six sleeps before saying so is a CLI that hangs."""
    from docxkit import package as pkg

    slept: list[float] = []
    monkeypatch.setattr(pkg.time, "sleep", slept.append)

    with pytest.raises(PackageError, match="cannot read"):
        pkg.read_parts(tmp_path / "not_here.docx")

    assert slept == []


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


def test_the_wait_between_retries_GROWS(monkeypatch, tmp_path):
    """`delay * (attempt + 1)`. Both tests above replace `sleep` with a
    no-op, which is right — they are about the retries, not the clock —
    and it leaves the only thing the loop computes unread. The schedule
    is what decides whether a build rides out a OneDrive sync: 0.2s
    against a total of 3.0s across six attempts, where a flat 0.2 gives
    up after 1.0 and a shrinking one after less.

    Linear rather than exponential on purpose: the lock this waits for
    is a file being written by another process, not a server."""
    from docxkit import package as pkg

    target, tmp = tmp_path / "paper.docx", tmp_path / "paper.tmp"
    target.write_bytes(b"old")
    tmp.write_bytes(b"new")
    calls: list[int] = []
    waits: list[float] = []
    monkeypatch.setattr(os, "replace", _flaky_replace(99, calls))
    monkeypatch.setattr(pkg.time, "sleep", waits.append)

    with pytest.raises(PermissionError):
        pkg._replace_atomically(tmp, target)

    assert [round(w, 3) for w in waits] == [0.2, 0.4, 0.6, 0.8, 1.0]
    assert sum(waits) == pytest.approx(3.0), "three seconds of patience"


def test_the_LAST_attempt_does_not_sleep(monkeypatch, tmp_path):
    """`attempt < retries - 1`: the wait exists to let the other process
    finish, and after the final attempt there is nothing left to wait
    for. Five waits for six attempts."""
    from docxkit import package as pkg

    target, tmp = tmp_path / "paper.docx", tmp_path / "paper.tmp"
    target.write_bytes(b"old")
    tmp.write_bytes(b"new")
    calls: list[int] = []
    waits: list[float] = []
    monkeypatch.setattr(os, "replace", _flaky_replace(99, calls))
    monkeypatch.setattr(pkg.time, "sleep", waits.append)

    with pytest.raises(PermissionError):
        pkg._replace_atomically(tmp, target)

    assert len(calls) == 6 and len(waits) == 5


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
    """The last resort, for a part that is not a document Word wrote: a
    root holding no properties at all, written self-closing. The element
    has to go INSIDE it, which means opening the root up around it.

    Asserted by parsing the part. The first version checked only that
    `<dc:title>` came after `<cp:coreProperties` in the text, which is
    true of the part this used to write, where the property sat after the
    self-closed root as a second root and nothing could parse it
    (BACKLOG, 2026-09-14)."""
    import xml.etree.ElementTree as ET

    from docxkit.package import core_property, set_core_property

    p = {"docProps/core.xml": (
        b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="x" '
        b'xmlns:dc="y"/>')}

    assert set_core_property(p, "dc:title", "Salvaged") is True

    root = ET.fromstring(p["docProps/core.xml"])
    assert [child.tag for child in root] == ["{y}title"]
    assert core_property(p, "dc:title") == "Salvaged"


def test_a_root_OPENED_and_never_closed_takes_the_property_after_it():
    """The other half of the same last resort: a root whose opening tag is
    not self-closing and whose closing tag is missing — a truncated part,
    which nothing Word writes. There is no inside to open up, so the
    element goes straight after the opening tag, and the part stays as
    unparseable as it arrived. No test reached that half, so every
    mutation of it survived the sweep of 2026-09-14, a `group(2)` that
    raises among them."""
    from docxkit.package import set_core_property

    p = {"docProps/core.xml": (
        b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="x" '
        b'xmlns:dc="y">')}

    assert set_core_property(p, "dc:title", "Truncated") is True

    assert p["docProps/core.xml"] == (
        b'<?xml version="1.0"?><cp:coreProperties xmlns:cp="x" '
        b'xmlns:dc="y"><dc:title>Truncated</dc:title>')


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


def test_clearing_read_only_leaves_the_file_READABLE_too(tmp_path):
    """`st_mode | S_IWRITE` — the flag is ADDED to the mode. Masked with
    `&` instead, the file comes back with almost no permissions at all,
    which on a manuscript is worse than the read-only flag that started
    it."""
    import stat as stat_mod

    from docxkit.package import _clear_readonly

    target = tmp_path / "paper.docx"
    target.write_bytes(b"content")
    os.chmod(target, stat_mod.S_IREAD)

    _clear_readonly(target)

    assert os.access(target, os.W_OK)
    assert target.read_bytes() == b"content"
    target.write_bytes(b"replaced")          # and it really is writable


def test_clearing_read_only_on_a_MISSING_file_is_quiet(tmp_path):
    """It runs on the way to a retry, and the target not existing yet is
    the ordinary case for a first write."""
    from docxkit.package import _clear_readonly

    _clear_readonly(tmp_path / "not there.docx")      # must not raise


def test_setting_a_property_Word_left_EMPTY_does_not_double_it():
    """S2, found 2026-08-19 by mutation testing the insert position.

    Word writes an unset core property as `<dc:title/>`, and the reader
    matched only the paired form — so `set_core_property` took its
    "absent" branch on a document that HAS the element, inserted the new
    value beside the empty one, and left two `dc:title`s in core.xml.
    CT_CoreProperties allows one of each; Word repairs the file on open
    and says nothing about what it changed.

    Nothing downstream could see it: the value reads back correctly,
    because the reader finds the new element first."""
    from docxkit.package import core_property, set_core_property

    p = core("<dc:title/><dc:creator>M</dc:creator>")

    assert set_core_property(p, "dc:title", "Loneliness Risk Index") is True

    text = p["docProps/core.xml"].decode("utf-8")
    assert text.count("<dc:title") == 1, text
    assert core_property(p, "dc:title") == "Loneliness Risk Index"
    assert text.index("<dc:title>") < text.index("<dc:creator>")


def test_an_EMPTY_property_reads_as_empty_and_not_as_absent():
    """`<dc:title/>` is a title the document HAS and has not set, which
    is a different answer from a document with no title element at all
    — the docstring makes that distinction and the self-closing form
    used to fall on the wrong side of it."""
    from docxkit.package import core_property

    assert core_property(core("<dc:title/>"), "dc:title") == ""
    assert core_property(core("<dc:creator>M</dc:creator>"),
                         "dc:title") is None


def test_setting_the_SAME_empty_value_on_an_empty_property_is_a_no_op():
    """The early return compares what is there with what is asked for,
    and both are empty here."""
    from docxkit.package import set_core_property

    p = core("<dc:title/>")

    assert set_core_property(p, "dc:title", "") is False


def test_a_DUPLICATED_sibling_takes_only_one_new_element():
    """`core.replace(nxt, element + nxt, 1)` — once, however many times
    the anchor appears. A core.xml carrying two `dc:creator`s is damaged
    already; answering it with two titles as well is a repair prompt on
    open rather than a document with a title."""
    from docxkit.package import set_core_property

    p = core("<dc:creator>M</dc:creator><dc:creator>N</dc:creator>")

    set_core_property(p, "dc:title", "T")

    text = p["docProps/core.xml"].decode("utf-8")
    assert text.count("<dc:title>") == 1, text


# --- the run of 2026-08-20: 6.6 %, and where its cluster was ------------
#
# Eight mutants on ONE line — the slice that decides where a new core
# property lands — and the docstring's promise for it ("the new element
# lands in CORE_ORDER position") had no test at all: every fixture set a
# property the file already had, which takes the other branch.


def _core(*elements: str) -> dict[str, bytes]:
    return {CORE_PART: ('<?xml version="1.0"?><cp:coreProperties '
                        'xmlns:cp="cp" xmlns:dc="dc" xmlns:dcterms="dcterms">'
                        + "".join(elements)
                        + "</cp:coreProperties>").encode("utf-8")}


def _tags(parts: dict[str, bytes]) -> list[str]:
    return re.findall(r"<(\w+:\w+)>", parts[CORE_PART].decode("utf-8"))


def test_a_NEW_core_property_lands_in_CORE_ORDER_position():
    """`CORE_ORDER.index(tag) + 1`, the elements the new one must come
    BEFORE. Word reads core.xml in schema order and rewrites what it
    finds out of place, so a property written after the wrong sibling is
    a property Word moves — or drops — on the next save.

    The mutants of that index halve it, double it, and flip its low bit.
    Halved, the new element lands before a property that should precede
    it; doubled, the list runs out and it is appended at the very end.
    Both need a tag with siblings on BOTH sides in the file, which is
    what this fixture is."""
    parts = _core("<dc:title>T</dc:title>",
                  "<cp:lastModifiedBy>L</cp:lastModifiedBy>",
                  "<dcterms:modified>M</dcterms:modified>")

    assert set_core_property(parts, "cp:revision", "7") is True

    assert _tags(parts) == ["dc:title", "cp:lastModifiedBy", "cp:revision",
                            "dcterms:modified"]


def test_the_same_placement_from_an_ODD_position_in_the_order():
    """`index ^ 1` is `index + 1` for an even index and `index - 1` for
    an odd one, so the fixture above cannot see it: `cp:revision` is
    sixth. `dcterms:created` is seventh, and one place BACK is
    `cp:revision` — which this file has, so the mutant writes the new
    element in front of it."""
    parts = _core("<dc:title>T</dc:title>", "<cp:revision>7</cp:revision>",
                  "<dcterms:modified>M</dcterms:modified>")

    assert set_core_property(parts, "dcterms:created", "2026-08-20") is True

    assert _tags(parts) == ["dc:title", "cp:revision", "dcterms:created",
                            "dcterms:modified"]


def test_a_package_compared_with_an_EQUAL_copy_reports_nothing():
    """`before[name] == after[name]` written `is`. Two reads of one file
    give equal bytes in different objects, so identity there sends every
    part in the package down to `same_part` and out into `resaved` — a
    round-trip report that lists all forty parts as re-saved when
    nothing was written at all.

    The bytes here are copied deliberately: `bytes(x)` hands back the
    same object, and a fixture built that way cannot see the
    difference."""
    raw = b"<w:document><w:body/></w:document>"
    copy = bytes(bytearray(raw))
    assert copy is not raw and copy == raw

    assert changed_parts({"word/document.xml": raw},
                         {"word/document.xml": copy}) == {
        "changed": [], "added": [], "removed": [], "resaved": []}


def test_a_missing_package_is_a_PackageError():
    """`except (OSError, …)`: the CLI turns a PackageError into a
    message, and a raw FileNotFoundError walked straight through it as a
    traceback. The handler had no test — mutated to an exception the
    body cannot raise, nothing noticed."""
    with pytest.raises(PackageError, match="cannot read"):
        read_parts("D:/docxkit/no-such-file.docx")


def test_a_LEAF_keeps_the_space_a_container_may_drop():
    """`if not kids`. Text between child elements is indentation and
    comparing it reports every re-serialisation; text in a LEAF is the
    prose, spaces and all. Inverted, the leaf's text is stripped and two
    parts whose only difference is a leading space in a `w:t` compare as
    the same part — which is the whole failure `preserve_space` exists
    to prevent, arriving through the check that would have caught it."""
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
          '2006/main"')
    spaced = (f"<w:document {ns}><w:body><w:p><w:r>"
              '<w:t xml:space="preserve"> lead</w:t>'
              "</w:r></w:p></w:body></w:document>")

    assert same_part(spaced.encode("utf-8"),
                     spaced.replace("> lead<", ">lead<").encode("utf-8")) \
        is False


# Argued rather than pinned, from the same run:
#
# * five of the eight on `CORE_ORDER.index(tag) + 1` — `* 1`, `** 1`,
#   `+ 0`, `// 1` and `| 1`. Each of them starts the slice AT the tag
#   rather than after it, and the branch they are in is the one where
#   the file does not contain that tag, so the extra entry matches
#   nothing.
# * `replace("</cp:coreProperties>", …, 1)` written 2, and
#   `_CORE_OPEN_RE.sub(…, count=1)` written 0 or 2: a core part has one
#   closing tag and one opening one.
# * `mm.group(1)` written `group(0)` in that sub: `_CORE_OPEN_RE` is one
#   group around the whole match.
# * `if attempt < retries - 1` written `!=` and `is not`: `attempt`
#   comes from `range(retries)`, so it never passes `retries - 1`.


def test_the_read_retry_BACKS_OFF_instead_of_hammering(monkeypatch,
                                                       simple_docx):
    """A sharing violation is usually over in a moment and occasionally
    is not, so the waits grow: 0.2, 0.4, 0.6 ... A constant schedule
    spends the same six attempts inside the first second, which is the
    part of the window a lock is least likely to have cleared."""
    from docxkit import package as pkg

    calls: list[int] = []
    slept: list[float] = []
    monkeypatch.setattr(pkg.zipfile, "ZipFile", _flaky_zip(99, calls))
    monkeypatch.setattr(pkg.time, "sleep", slept.append)

    with pytest.raises(PackageError):
        pkg.read_parts(simple_docx, retries=4, delay=0.5)

    assert slept == [0.5, 1.0, 1.5]


# `read_parts`'s remaining survivor from the 2026-08-21 round, argued:
# `if attempt < retries - 1` -> `!= retries - 1`. `attempt` runs over
# `range(retries)`, so it reaches the last index exactly and never
# passes it — the two spellings stop the loop on the same attempt.


# ------------------------------------ the bytes are the CONTENT (27.08) ---
#
# `writestr` stamps every entry from the clock, so an idempotent pass
# over an unchanged manuscript wrote a different md5 each time it took
# more than a second to run — and the SAME one when two runs happened
# to finish inside one, which is why it read as intermittent rather
# than as always. Measured on Aging_Well 2026-08-26: three of six
# passes looked byte-idempotent on one run and churning on the next,
# purely by clock luck. Every entry's content was identical throughout.

def _md5(path: Path) -> str:
    import hashlib

    return hashlib.md5(path.read_bytes()).hexdigest()


def test_the_SAME_parts_write_the_SAME_bytes(simple_docx, tmp_path,
                                             monkeypatch):
    """"A re-run that reports no work IS the check that nothing was
    eaten" is the house idiom, and its strongest form — md5 before ==
    md5 after — was unavailable while the clock was in the file.

    The clock is MOVED between the two writes on purpose. Two runs that
    finish inside one second came out identical even before this was
    fixed, which is exactly why the defect read as intermittent — and
    a test that writes twice in a millisecond passes either way.
    """
    parts = read_parts(simple_docx)
    first, second = tmp_path / "a.docx", tmp_path / "b.docx"
    a_day_later = iter([1_000_000_000.0, 1_000_086_400.0])
    monkeypatch.setattr(time, "time",
                        lambda: next(a_day_later, 1_000_086_400.0))

    write_docx(first, parts)
    write_docx(second, parts)

    assert _md5(first) == _md5(second)


def test_a_REAL_edit_still_changes_the_bytes(simple_docx, tmp_path):
    """The other half, and the one that makes the first mean anything:
    a fixed stamp must not make two DIFFERENT documents hash alike."""
    parts = read_parts(simple_docx)
    before = tmp_path / "before.docx"
    write_docx(before, parts)

    parts["word/document.xml"] += b"<!-- a real edit -->"
    after = tmp_path / "after.docx"
    write_docx(after, parts)

    assert _md5(before) != _md5(after)


def test_every_entry_carries_the_FIXED_stamp(simple_docx, tmp_path):
    """Named by value, because the hash equality above holds for any
    constant and would not notice the stamp moving to a different one —
    and a stamp that moved between docxkit versions would make every
    cached hash in every paper stale at once."""
    out = tmp_path / "out.docx"
    write_docx(out, read_parts(simple_docx))

    with zipfile.ZipFile(out) as z:
        stamps = {i.date_time for i in z.infolist()}

    assert stamps == {(1980, 1, 1, 0, 0, 0)}


def test_the_entries_are_still_DEFLATED(simple_docx, tmp_path):
    """`writestr` took the archive's compression from a bare name and a
    hand-built ZipInfo does not — a `ZipInfo` defaults to STORED, which
    would quietly triple the size of every manuscript the toolkit
    writes."""
    out = tmp_path / "out.docx"
    write_docx(out, read_parts(simple_docx))

    with zipfile.ZipFile(out) as z:
        kinds = {i.compress_type for i in z.infolist()}

    assert kinds == {zipfile.ZIP_DEFLATED}


# --- the survivors of 2026-09-14 ------------------------------------------
#
# The sweep of `package.py` left 39 real survivors, and 18 of them were in
# `readable`, which nothing in this file called: `revision status` and
# `revision ingest` use it, and are tested elsewhere.


def test_readable_hands_over_an_UNLOCKED_file_as_it_is(simple_docx):
    """Nothing holds the file, so there is nothing to copy: the path
    itself, and `copied` False, which is what lets the caller say it read
    the manuscript rather than a snapshot."""
    from docxkit.package import readable

    with readable(simple_docx) as (path, copied):
        assert (path, copied) == (Path(simple_docx), False)


def test_readable_SNAPSHOTS_a_file_another_process_holds(simple_docx,
                                                         monkeypatch):
    """Word holds `working.docx` while the author edits it, and a
    read-only command still has to answer. It answers from a byte copy,
    says so, and the copy is gone once the block ends."""
    from docxkit import package as pkg

    src = Path(simple_docx)
    monkeypatch.setattr(pkg, "is_locked", lambda _path: True)

    with pkg.readable(src) as (path, copied):
        assert copied is True
        assert path != src and path.name == src.name
        assert path.read_bytes() == src.read_bytes()
        snapshot = path

    assert not snapshot.exists(), "the snapshot was cleaned up"


def test_readable_falls_back_to_the_ORIGINAL_when_the_copy_fails(
        simple_docx, monkeypatch):
    """If the copy is refused too there is nothing better to offer: the
    original path comes back with `copied` False, and the caller meets its
    usual refusal rather than an OSError from inside the snapshot."""
    from docxkit import package as pkg

    def no_copy(*_a, **_k):
        raise PermissionError("the copy was refused as well")

    monkeypatch.setattr(pkg, "is_locked", lambda _path: True)
    monkeypatch.setattr(pkg.shutil, "copy2", no_copy)

    with pkg.readable(simple_docx) as (path, copied):
        assert (path, copied) == (Path(simple_docx), False)


def test_readable_does_not_fail_the_read_when_the_snapshot_will_not_GO(
        simple_docx, monkeypatch):
    """The snapshot's folder is removed on the way out, after the read it
    served has succeeded, and Windows refuses that while anything still
    has the copy open. A cleanup that fails is not a read that failed."""
    from docxkit import package as pkg

    removed: list[bool] = []
    real = pkg.shutil.rmtree

    def rmtree(path, ignore_errors=False, **_kw):
        if not ignore_errors:
            raise PermissionError("the copy is still open")
        removed.append(True)
        real(path, ignore_errors=True)

    monkeypatch.setattr(pkg, "is_locked", lambda _path: True)
    monkeypatch.setattr(pkg.shutil, "rmtree", rmtree)

    with pkg.readable(simple_docx) as (_path, copied):
        assert copied is True

    assert removed == [True]


def test_is_locked_says_TRUE_for_a_writable_file_another_process_holds(
        simple_docx, monkeypatch):
    """The other half of the read-only case above: the open is refused
    and the file's mode says it is writable, so something holds it."""
    from docxkit import package as pkg

    def held(*_a, **_k):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(pkg, "open", held, raising=False)

    assert pkg.is_locked(simple_docx) is True


def test_read_parts_retries_on_the_SAME_schedule_as_the_write_side():
    """"On the same bounded schedule `_replace_atomically` uses for the
    write side": one direction hardened and the other not is what made a
    paper's suite randomly red. Pinned as that relation, not as numbers."""
    import inspect

    from docxkit import package as pkg

    read = inspect.signature(pkg.read_parts).parameters
    write = inspect.signature(pkg._replace_atomically).parameters

    assert (read["retries"].default, read["delay"].default) == (
        write["retries"].default, write["delay"].default)


def test_clearing_read_only_that_the_SYSTEM_refuses_is_quiet(tmp_path,
                                                            monkeypatch):
    """It runs on the way to a retry, and a `chmod` the system refuses
    must not end the write that was about to try again."""
    from docxkit import package as pkg

    target = tmp_path / "paper.docx"
    target.write_bytes(b"content")

    def refused(*_a, **_k):
        raise PermissionError("access is denied")

    monkeypatch.setattr(pkg.os, "chmod", refused)

    pkg._clear_readonly(target)                     # must not raise


def test_discarding_a_staging_file_that_will_not_GO_is_quiet(tmp_path,
                                                            monkeypatch):
    """`_discard` runs in the failure path of a write, and the error that
    matters there is the write's: a staging file the system will not
    remove must not replace it."""
    from docxkit import package as pkg

    staged = tmp_path / "paper.docx.tmp"
    staged.write_bytes(b"half written")

    def refused(self, missing_ok=False):
        raise PermissionError("the file is in use")

    monkeypatch.setattr(type(staged), "unlink", refused)

    pkg._discard(staged)                            # must not raise


def test_a_backup_into_a_folder_TWO_levels_down_creates_both(simple_docx,
                                                            tmp_path):
    """`into` names a folder "created if it is not there", and the one the
    protocol uses, `build/rescue/`, sits under a `build/` that may not
    exist yet either."""
    dest = backup(simple_docx, "rescue", into=tmp_path / "build" / "rescue")

    assert dest == tmp_path / "build" / "rescue" / "simple_rescue1.docx"
    assert dest.read_bytes() == Path(simple_docx).read_bytes()
