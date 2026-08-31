"""`tracked.build` without Word.

Every Word touchpoint in tracked.py goes through the module attribute
`_word`, so replacing that one attribute isolates the whole pipeline —
and `flat_opc_to_docx` is pure, so the fake delegates to the real one
and lets read_parts / comments / lint / write_docx / guard all run for
real against a genuine (tiny) .docx.

The build's central safety property lives here: the deliverable at `out`
must be replaced only after every gate has passed, and must survive
untouched when one fails.
"""
from __future__ import annotations

import contextlib
import itertools
import tempfile
import zipfile
from pathlib import Path
from typing import Any, ClassVar

import pytest
from conftest import (
    NS,
    dele,
    document,
    ins,
    make_parts,
    notes,
    para,
    run,
)

from docxkit import tracked
from docxkit.errors import PackageError
from docxkit.tracked import unaccepted, untracked

FLAT_TEMPLATE = """<?xml version="1.0" standalone="yes"?>
<?mso-application progid="Word.Document"?>
<pkg:package xmlns:pkg="http://schemas.microsoft.com/office/2006/xmlPackage">
  <pkg:part pkg:name="/_rels/.rels" pkg:contentType=\
"application/vnd.openxmlformats-package.relationships+xml">
    <pkg:xmlData>
      <Relationships xmlns=\
"http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship Id="rId1" Type=\
"http://schemas.openxmlformats.org/officeDocument/2006/relationships\
/officeDocument" Target="word/document.xml"/>
      </Relationships>
    </pkg:xmlData>
  </pkg:part>
  <pkg:part pkg:name="/word/document.xml" pkg:contentType=\
"application/vnd.openxmlformats-officedocument.wordprocessingml.\
document.main+xml">
    <pkg:xmlData>{body}</pkg:xmlData>
  </pkg:part>
</pkg:package>
"""


#: Word's own comment part. The XML pass CLONES a real Word comment for
#: its template, author, date and namespace prefixes; hand-writing one is
#: how a package ends up "repaired" on open, so a build that annotates
#: needs this to exist before it starts.
COMMENTS_PART = """
  <pkg:part pkg:name="/word/comments.xml" pkg:contentType=\
"application/vnd.openxmlformats-officedocument.wordprocessingml.\
comments+xml">
    <pkg:xmlData>
      <w:comments xmlns:w=\
"http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:comment w:id="0" w:author="Revision" w:initials="R" \
w:date="2026-01-01T00:00:00Z"><w:p><w:r><w:t>scaffold</w:t></w:r></w:p>\
</w:comment>
      </w:comments>
    </pkg:xmlData>
  </pkg:part>
"""


def _clean_document() -> str:
    # no XML prolog: the part is embedded inside <pkg:xmlData>
    xml = document(para(run("The revised sentence.")))
    return xml[xml.index("<w:document"):]


def _revised_document() -> str:
    """A document carrying a real tracked insertion to comment on."""
    body = ('<w:p><w:r><w:t xml:space="preserve">Employment rises </w:t>'
            "</w:r>"
            '<w:ins w:id="101" w:author="Revision" '
            'w:date="2026-01-01T00:00:00Z">'
            "<w:r><w:t>sharply</w:t></w:r></w:ins></w:p>")
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def _broken_document() -> str:
    """Well-formed XML that Word would refuse to open.

    A run sitting directly in `w:body` rather than inside a `w:p`: it
    parses, so it survives the Flat OPC unpack, and it is exactly the
    "unreadable content" class lint exists to catch offline.
    """
    return (f"<w:document {NS}><w:body>"
            "<w:r><w:t>a run loose in the body</w:t></w:r>"
            "</w:body></w:document>")


class _Revisions:
    Count = 0

    def __call__(self, i):                       # pragma: no cover
        raise IndexError(i)


class _FakeDoc:
    def __init__(self) -> None:
        # typed loosely on purpose: tests rebind these with richer
        # collections, and COM objects are duck-typed anyway
        self.Revisions: Any = _Revisions()
        self.Comments: Any = _Revisions()
        self.Paragraphs: Any = _Revisions()
        self.OMaths: Any = _Revisions()   # a real Document always has one
        self.closed = False

    def Close(self, SaveChanges=0):
        self.closed = True


class _FakeWordModule:
    """Only what tracked.build actually calls."""

    def __init__(self, body: str, *, scaffold: bool = False) -> None:
        self.body = body
        self.scaffold = scaffold          # Word's own comment, to clone
        self.compared: dict[str, object] = {}

    @contextlib.contextmanager
    def session(self):
        yield object()

    @contextlib.contextmanager
    def open_doc(self, word, path, **kw):
        yield _FakeDoc()

    def compare_documents(self, word, orig, rev, **kw):
        self.compared = kw
        return _FakeDoc()

    def draft_view(self, doc):
        pass

    def revisions(self, doc):
        return iter(())

    def extract_flat_opc(self, doc, flat: Path) -> None:
        text = FLAT_TEMPLATE.format(body=self.body)
        if self.scaffold:
            text = text.replace("</pkg:package>",
                                COMMENTS_PART + "</pkg:package>")
        Path(flat).write_text(text, encoding="utf-8")

    def flat_opc_to_docx(self, flat, out) -> int:
        from docxkit.word import flat_opc_to_docx
        return flat_opc_to_docx(flat, out)       # pure: use the real one


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(original, revised, out) — the two inputs are never read by the
    fake, but build() opens them, so they must exist."""
    for name in ("original.docx", "revised.docx"):
        with zipfile.ZipFile(tmp_path / name, "w") as z:
            z.writestr("word/document.xml", _clean_document())
    return (tmp_path / "original.docx", tmp_path / "revised.docx",
            tmp_path / "redline.docx")


def _baseline(path: Path, text: str) -> None:
    """Rewrite `path` to say `text` — what the redline must reject BACK to.

    The fake's compare output is not derived from the fixture inputs, so
    a test whose body is not `_clean_document()` has to say what its
    original was; `build` now refuses to publish a redline whose
    reject-all does not reproduce it.
    """
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document(para(run(text))))


def _target(path: Path, text: str) -> None:
    """Rewrite `path` to say `text` — what the redline must ACCEPT to.

    The mirror of `_baseline`, and needed for the same reason: the
    fake's compare output is not derived from the fixture inputs, so a
    test whose redline accepts to something other than
    `_clean_document()` has to say what its REVISED input was. `build`
    refuses to publish a redline whose accept-all does not reproduce it.
    """
    _baseline(path, text)


def _build(monkeypatch, body: str, sources, **kw):
    fake = _FakeWordModule(body)
    monkeypatch.setattr(tracked, "_word", fake)
    original, revised, out = sources
    report = tracked.build(original, revised, out,
                           verify_in_word=False, **kw)
    return report, fake


# ------------------------------------------------------------ the build ---


def test_build_writes_the_deliverable_and_stamps_it(monkeypatch, sources):
    report, fake = _build(monkeypatch, _clean_document(), sources)
    out = sources[2]
    assert out.is_file()
    assert zipfile.ZipFile(out).read("word/document.xml")
    assert tracked._guard.stamp_path(out).is_file()
    assert report.revisions == 0
    assert fake.compared["author"] == "Revision"


def test_the_compare_options_DEFAULT_to_on(monkeypatch, sources):
    """The pair below proves they are passed through; nothing proved
    what they are when nobody passes them. `formatting=False` by default
    would have made the footnote batch of 2026-08-10 — 25 `w:rPrChange`
    and not one insertion — come back from Compare with nothing to
    review, which reads exactly like a batch Compare cannot represent."""
    _, fake = _build(monkeypatch, _clean_document(), sources)
    assert fake.compared["formatting"] is True
    assert fake.compared["whitespace"] is True
    # and `moves`, for a different reason: move detection off by default
    # would turn every relocation into a deletion and an insertion,
    # which is a longer redline for every paper to read. It is the
    # ANSWER to a refusal, not the setting to start from.
    assert fake.compared["moves"] is True


def test_the_build_carries_the_customXml_store_across_the_compare(
        monkeypatch, sources, capsys):
    """Compare drops the data store on EVERY rebuild, and `promote`
    copies the batch over working.docx — so the loss reaches the live
    manuscript in one step, with lint clean and validate PASSing. That
    paper hand-restored three parts after every build for a week."""
    original, revised, out = sources
    with zipfile.ZipFile(revised, "w") as z:
        z.writestr("word/document.xml", _clean_document())
        z.writestr("customXml/item1.xml",
                   '<b:Sources xmlns:b="http://schemas.openxmlformats.org'
                   '/officeDocument/2006/bibliography"/>')
        z.writestr("customXml/itemProps1.xml",
                   '<ds:datastoreItem xmlns:ds="http://schemas.openxmlformats'
                   '.org/officeDocument/2006/customXml"/>')
        z.writestr("[Content_Types].xml",
                   '<Types><Override PartName="/customXml/itemProps1.xml" '
                   'ContentType="application/xml"/></Types>')
        z.writestr("word/_rels/document.xml.rels",
                   '<Relationships><Relationship Id="rId4" '
                   'Target="../customXml/item1.xml"/></Relationships>')

    said: list[str] = []
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)
    report = tracked.build(original, revised, out, verify_in_word=False,
                           progress=said.append)

    built = zipfile.ZipFile(out)
    assert "customXml/item1.xml" in built.namelist()
    assert report.carried == ["customXml/item1.xml",
                              "customXml/itemProps1.xml"]
    assert any("carried across" in line for line in said)
    # the content type comes back with the part; the RELATIONSHIP half is
    # unit-tested in test_parts_gaps, because Word's flat-OPC output for
    # a two-part fixture carries no word/_rels/document.xml.rels to
    # merge into
    types = built.read("[Content_Types].xml").decode("utf-8")
    assert 'PartName="/customXml/itemProps1.xml"' in types
    # a part that was carried back is not also announced as dropped
    assert not [n for n in report.dropped if "customXml" in n], report.dropped


def test_the_build_carries_docProps_custom_across_the_compare(
        monkeypatch, sources):
    """It is on the default carry list beside the data store, because it
    is NOT Word's own bookkeeping: those are user-defined properties, and
    on the Bank manuscript that raised this they were the sensitivity
    label and the "Official Use Only" content marking (Aging_Well R1)."""
    original, revised, out = sources
    with zipfile.ZipFile(revised, "w") as z:
        z.writestr("word/document.xml", _clean_document())
        z.writestr(
            "docProps/custom.xml",
            '<Properties xmlns:vt="http://schemas.openxmlformats.org'
            '/officeDocument/2006/docPropsVTypes">'
            '<property name="Classification">'
            "<vt:lpwstr>Official Use Only</vt:lpwstr>"
            "</property></Properties>")
        z.writestr("[Content_Types].xml",
                   '<Types><Override PartName="/docProps/custom.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument'
                   '.custom-properties+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<Relationships><Relationship Id="rId3" '
                   'Target="docProps/custom.xml"/></Relationships>')

    monkeypatch.setattr(tracked, "_word", _FakeWordModule(_clean_document()))
    report = tracked.build(original, revised, out, verify_in_word=False)

    built = zipfile.ZipFile(out)
    assert report.carried == ["docProps/custom.xml"]
    assert b"Official Use Only" in built.read("docProps/custom.xml")
    assert 'PartName="/docProps/custom.xml"' in built.read(
        "[Content_Types].xml").decode("utf-8")
    assert 'Target="docProps/custom.xml"' in built.read(
        "_rels/.rels").decode("utf-8")


def test_carry_can_be_turned_off(monkeypatch, sources):
    """`carry=()` is the raw Compare output and a warning — which is
    what every build did before, and is still the right answer for a
    caller that wants Word's own package."""
    original, revised, out = sources
    with zipfile.ZipFile(revised, "w") as z:
        z.writestr("word/document.xml", _clean_document())
        z.writestr("customXml/item1.xml",
                   '<b:Sources xmlns:b="http://schemas.openxmlformats.org'
                   '/officeDocument/2006/bibliography"/>')
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)
    report = tracked.build(original, revised, out, verify_in_word=False,
                           carry=())
    assert report.carried == []
    assert "customXml/item1.xml" not in zipfile.ZipFile(out).namelist()
    assert any("part LOST: customXml/item1.xml" in n for n in report.dropped)


def test_a_body_only_count_is_not_reported_as_the_whole_batch(
        monkeypatch, sources, capsys):
    """Word's Revisions collection walks the MAIN STORY, so a footnote
    batch reads 0 there while the package holds 25. The note that says
    so had eight surviving mutants — including deleting the comparison
    outright, which makes it fire on every build, and inverting it,
    which makes it fire on none."""
    said: list[str] = []
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)
    original, revised, out = sources
    report = tracked.build(original, revised, out, verify_in_word=False,
                           progress=said.append)
    # the fake's compare result reports no body revisions at all
    assert report.body_revisions == 0
    assert not any("in the body" in line for line in said), \
        "the note fired when the two counts agree"

    said.clear()
    monkeypatch.setattr(tracked, "package_counts",
                        lambda parts: {"insertions": 0, "deletions": 0,
                                       "comments": 0, "revisions": 25})
    tracked.build(original, revised, out, verify_in_word=False, force=True,
                  progress=said.append)
    note = [line for line in said if "in the body" in line]
    assert note, "a batch whose revisions are all in footnotes said nothing"
    assert "Word counts 0 in the body" in note[0], note
    assert "25 revision elements" in note[0], note

    # And once more at THREE HUNDRED, agreeing. CPython hands out one
    # object per int up to 256, so `is not` in place of `!=` is
    # invisible on every batch this suite has ever built and fires on
    # every real one above the cache — LI7 shipped 315 revisions, and
    # the note would have told its author that -15 of them were in
    # footnotes it does not have.
    said.clear()
    big = _FakeDoc()
    big.Revisions = type("R", (), {"Count": len([0] * 300)})()
    fake.compare_documents = lambda word, o, r, **kw: big   # type: ignore
    monkeypatch.setattr(tracked, "package_counts",
                        lambda parts: {"insertions": 0, "deletions": 0,
                                       "comments": 0,
                                       "revisions": len([0] * 300)})
    tracked.build(original, revised, out, verify_in_word=False, force=True,
                  progress=said.append)
    assert not any("in the body" in line for line in said), said


def test_the_gap_between_the_two_counts_NAMES_both_of_its_causes():
    """The message used to blame footnotes for the whole difference.

    AFI r4 batch 13 read "33 revisions, 15 of them in the body; the rest
    are in footnotes or endnotes" with `footnotes.xml` and
    `endnotes.xml` holding ZERO between them: the other 18 were adjacent
    body revisions Word had GROUPED. The wording had been right in the
    batch before, which is what made it worth following.
    """
    parts = make_parts(
        para(ins(run("one"))) + para(ins(run("two"))) + para(dele(run("go"))),
        footnotes=notes("footnotes",
                        f'<w:footnote w:id="2"><w:p>{ins(run("a"))}'
                        f"</w:p></w:footnote>"))

    assert tracked.revisions_by_part(parts) == {
        "word/document.xml": 3, "word/footnotes.xml": 1}

    # Word says two: one footnote revision it does not see, and two of
    # the body's three grouped into one.
    said = tracked._revision_gap(parts, body=2, total=4)

    assert "Word counts 2 in the body" in said, said
    assert "1 of them are in word/footnotes.xml" in said, said
    assert "the remaining 1 are in word/document.xml too" in said, said
    assert "GROUPS" in said, said
    # and the body is not listed among the parts Word cannot reach: that
    # sentence is true of a note store and false of the main story
    assert "word/document.xml, where Word" not in said, said


def test_the_gap_says_NOTHING_about_grouping_when_there_is_none():
    """Each cause is named only when it is present — which is the whole
    complaint. A batch that really is all footnotes still reads as one.
    """
    parts = make_parts(
        para(run("plain")),
        footnotes=notes("footnotes",
                        f'<w:footnote w:id="2"><w:p>{ins(run("a"))}'
                        f"</w:p></w:footnote>"))

    said = tracked._revision_gap(parts, body=0, total=1)

    assert "1 of them are in word/footnotes.xml" in said, said
    assert "GROUPS" not in said, said


def test_a_part_with_no_revisions_is_not_named_at_all():
    """`footnotes.xml` exists in nearly every manuscript. Listing it at
    zero is how the old message sent a reader to inspect it.
    """
    parts = make_parts(
        para(ins(run("one"))) + para(ins(run("two"))),
        footnotes=notes("footnotes",
                        '<w:footnote w:id="2"><w:p/></w:footnote>'))

    assert "word/footnotes.xml" not in tracked.revisions_by_part(parts)
    assert "footnotes" not in tracked._revision_gap(parts, body=1, total=2)


def test_build_passes_the_compare_options_through(monkeypatch, sources):
    """`moves` among them since 2026-08-31: a scored move truncated the
    moved paragraph in the accepted view on Aging_Well, and the switch
    that fixed it stopped at `word.compare_documents` — so the gate
    refused the round and the build had no way to answer it."""
    _, fake = _build(monkeypatch, _clean_document(), sources,
                     author="Revision R2", whitespace=False,
                     formatting=False, moves=False)
    assert fake.compared == {"author": "Revision R2", "whitespace": False,
                             "formatting": False, "moves": False}


# ----------------------------------------------- the safety property -----


def test_a_failed_lint_leaves_the_previous_deliverable_untouched(
        monkeypatch, sources):
    """The P0 defect: the build used to write `out` and validate after.

    A lint failure then left the destroyed file in place, with no backup
    — guard.check only copies a deliverable that looks hand-edited.
    """
    out = sources[2]
    out.write_bytes(b"PREVIOUS GOOD DELIVERABLE")
    tracked._guard.stamp(out)                 # ordinary case: not edited
    before = out.read_bytes()

    with pytest.raises(PackageError, match="would not open cleanly"):
        _build(monkeypatch, _broken_document(), sources)

    assert out.read_bytes() == before


def test_a_failed_build_KEEPS_its_artefact_to_be_looked_at(monkeypatch,
                                                          sources):
    """It used to delete it, and that cost two diagnoses in one day.

    When `verify` raises — Word answering "the file appears to be
    corrupted" — the refused build is the only thing that can say WHY,
    and unlinking it left nothing to open: the way to see the artefact
    was to rebuild with `verify_in_word=False`, which is a round trip
    for something already on disk a moment earlier.

    Keeping it costs one stale `~` file. Nothing globs for it — the only
    `*.docx` walk in the package filters on `<stem>_vN.docx` — and the
    next build overwrites it."""
    out = sources[2]
    with pytest.raises(PackageError):
        _build(monkeypatch, _broken_document(), sources)

    (kept,) = list(out.parent.glob("~*.building*"))
    assert kept.stat().st_size > 0, "an empty file is not evidence"


def test_a_failed_build_does_not_create_the_deliverable(monkeypatch,
                                                        sources):
    out = sources[2]
    with pytest.raises(PackageError):
        _build(monkeypatch, _broken_document(), sources)
    assert not out.exists()


def _private_tmp(monkeypatch: Any, tmp_path: Path) -> Path:
    """Point `tempfile` at a directory only this test can write to.

    Both of the tests below assert that a set of directories is UNCHANGED,
    and they used to assert it about the machine's shared temp directory —
    which any other build is entitled to write to. Under `pytest -n 8` a
    second worker's `build()` lands there mid-assertion and the test fails
    for something it is not about. That is worse than flake: the suite is
    the oracle a mutation run judges a mutant by, and a test that fails on
    its own would score a surviving mutant as killed.
    """
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def test_the_build_leaves_no_temp_directory_behind(monkeypatch, sources,
                                                   tmp_path):
    root = _private_tmp(monkeypatch, tmp_path)
    _build(monkeypatch, _clean_document(), sources)
    assert list(root.glob("docxkit_tracked_*")) == []


def test_the_temp_directory_goes_even_when_the_build_fails(
        monkeypatch, sources, tmp_path):
    root = _private_tmp(monkeypatch, tmp_path)
    with pytest.raises(PackageError):
        _build(monkeypatch, _broken_document(), sources)
    assert list(root.glob("docxkit_tracked_*")) == []


def test_build_refuses_to_overwrite_a_hand_edited_deliverable(
        monkeypatch, sources):
    from docxkit.errors import DeliverableModified
    out = sources[2]
    out.write_bytes(b"AUTHOR REVIEWED THIS")     # no stamp: treat as edited
    with pytest.raises(DeliverableModified):
        _build(monkeypatch, _clean_document(), sources)
    assert out.read_bytes() == b"AUTHOR REVIEWED THIS"


# ------------------------------------------------------------- reporting --


def test_what_compare_dropped_is_SAID_not_just_recorded(monkeypatch,
                                                        sources):
    """"Suppressing silently let a half-finished build report
    success-shaped numbers" is this module's own comment, and the loop
    that says so could be deleted with nothing going red. The report
    field was asserted; the telling was not."""
    said: list[str] = []
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)
    monkeypatch.setattr(tracked, "compare_collateral",
                        lambda revised, redline: ["part dropped: word/x.xml"])
    original, revised, out = sources
    report = tracked.build(original, revised, out, verify_in_word=False,
                           progress=said.append)
    assert report.dropped == ["part dropped: word/x.xml"]
    assert any("part dropped: word/x.xml" in line for line in said), \
        "the build recorded it and never said it"


def test_a_suppressed_word_call_is_SAID_too(monkeypatch, sources):
    """The same for the COM failures the build swallows so that one
    hostile revision cannot abort a 1,400-revision run."""
    said: list[str] = []
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)

    def _resolve(cmp_, classify, generic, suppressed):
        suppressed.append("comment on revision 7: rejected by callee")
        return tracked.MathOutcome(0)

    monkeypatch.setattr(tracked, "_resolve_math", _resolve)
    original, revised, out = sources
    tracked.build(original, revised, out, verify_in_word=False,
                  progress=said.append)
    assert any("rejected by callee" in line for line in said), \
        "a swallowed Word call was recorded and never said"


def test_the_build_carries_the_TITLE_across_the_compare(monkeypatch,
                                                        sources):
    """Compare regenerates docProps/core.xml with its own save fields
    only — and Flat OPC carries no docProps at all — so a titled
    manuscript becomes an untitled deliverable with nothing reporting
    it: metadata is not tracked-changeable, so no redline can show the
    loss. LI7's dc:title was gone for four days, twice."""
    from docxkit.package import core_property, read_parts

    _original, revised, out = sources
    with zipfile.ZipFile(revised, "w") as z:
        z.writestr("word/document.xml", _clean_document())
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="http://schemas.'
                   'openxmlformats.org/package/2006/metadata/core-'
                   'properties" xmlns:dc="http://purl.org/dc/elements/'
                   '1.1/"><dc:title>Loneliness Risk Index</dc:title>'
                   "</cp:coreProperties>")

    said: list[str] = []
    report, _ = _build(monkeypatch, _clean_document(), sources,
                       progress=said.append)

    assert report.carried_properties == ["dc:title"]
    assert core_property(read_parts(out), "dc:title") == \
        "Loneliness Risk Index"
    assert "dc:title" in report.format()
    # and SAID while it happens, not only in the report: this is the
    # one carry whose loss no later gate can see
    assert any("carried across: dc:title" in line for line in said), said


# ------------------------------------------- the reject-all gate ---------


def test_build_REFUSES_a_redline_that_cannot_be_REJECTED(monkeypatch,
                                                         sources):
    """The failure a redline exists to prevent, and the one every other
    signal calls success.

    LI7 (2026-08-15) shipped one: an over-eager math accept applied 13
    revisions' whole spans, 315 revisions went with them, and rejecting
    everything no longer gave back the submitted paper — collateral as
    far as the abstract, which holds no equation. The package linted,
    opened, verified in Word and counted plausibly throughout.
    """
    fake = _FakeWordModule(_revised_document())     # rejects to "Employment"
    monkeypatch.setattr(tracked, "_word", fake)
    original, revised, out = sources                # baseline says otherwise
    out.write_bytes(b"THE PREVIOUS DELIVERABLE")

    with pytest.raises(PackageError) as exc:
        tracked.build(original, revised, out, verify_in_word=False,
                      force=True)

    assert "does NOT reproduce" in str(exc.value)
    assert "The revised sentence." in str(exc.value), "say WHICH paragraph"
    assert out.read_bytes() == b"THE PREVIOUS DELIVERABLE", \
        "a failed gate must not destroy the redline that was there"


def test_the_reject_gate_can_be_turned_off_and_still_SAYS_it(monkeypatch,
                                                             sources):
    """Turning it off is for getting the artifact to look at — not for
    making the finding go away, so it is computed and said either way."""
    said: list[str] = []
    fake = _FakeWordModule(_revised_document())
    monkeypatch.setattr(tracked, "_word", fake)
    original, revised, out = sources

    report = tracked.build(original, revised, out, verify_in_word=False,
                           reject_check=False, accept_check=False,
                           progress=said.append)

    assert out.is_file()
    assert len(report.unrejectable) == 1
    assert any("UNREJECTABLE" in line for line in said), said


# --- the accept side of the same question (BACKLOG S2, 2026-08-19) -------
#
# `untracked` compares reject-all against the ORIGINAL and cannot cover
# this by construction: rejecting removes every insertion, so a defect
# Compare baked INSIDE one is deleted before that comparison happens.
# The tag counts do not move either — a mangled run is still one
# paragraph in one cell — so the build reports success, the reject gate
# passes BY NAME, and the corruption ships in the document the author
# reads.


def _mangled_insertion() -> str:
    """A redline that rejects PERFECTLY and accepts to the wrong words.

    What Word's Compare is known to do while deriving a redline, in the
    smallest shape that shows it: the insertion carries "sharply" as
    the clean copy asks, with one word of it rewritten.
    """
    body = ('<w:p><w:r><w:t xml:space="preserve">Employment rises </w:t>'
            "</w:r>"
            '<w:ins w:id="101" w:author="Revision" '
            'w:date="2026-01-01T00:00:00Z">'
            "<w:r><w:t>SHARPLX</w:t></w:r></w:ins></w:p>")
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def test_the_reject_gate_cannot_see_a_defect_inside_an_INSERTION():
    """The argument for the accept gate, made directly on the two
    functions: the same package is clean to one and wrong to the
    other."""
    from docxkit.tracked import unaccepted, untracked

    parts = {"word/document.xml": _mangled_insertion().encode("utf-8")}
    baseline = {"word/document.xml":
                document(para(run("Employment rises "))).encode("utf-8")}
    intended = {"word/document.xml":
                document(para(run("Employment rises sharply")))
                .encode("utf-8")}
    assert untracked(parts, baseline) == [], "rejecting reproduces it"

    (missed,) = unaccepted(parts, intended)
    assert missed.part == "body" and missed.index == 0
    assert missed.intended == "Employment rises sharply"
    assert missed.accepted == "Employment rises SHARPLX"
    assert "intended" in str(missed) and "accepted" in str(missed)


def test_build_REFUSES_a_redline_that_accepts_to_the_wrong_words(
        monkeypatch, sources):
    """And the gate in place. The message names the paragraph, because
    a build that stops without saying which one sends a person back
    through the whole document."""
    fake = _FakeWordModule(_mangled_insertion())
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment rises ")
    _target(sources[1], "Employment rises sharply")

    with pytest.raises(PackageError) as exc:
        tracked.build(sources[0], sources[1], sources[2],
                      verify_in_word=False)

    message = str(exc.value)
    assert "accepting every revision does NOT reproduce" in message
    assert "SHARPLX" in message and "sharply" in message
    assert not sources[2].exists(), "and nothing was published"


def test_the_accept_gate_can_be_turned_off_and_still_SAYS_it(monkeypatch,
                                                             sources):
    """The same bargain the reject gate offers: the flag is for getting
    the artifact to look at, not for making the finding go away."""
    said: list[str] = []
    fake = _FakeWordModule(_mangled_insertion())
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment rises ")
    _target(sources[1], "Employment rises sharply")

    report = tracked.build(sources[0], sources[1], sources[2],
                           verify_in_word=False, accept_check=False,
                           progress=said.append)

    assert sources[2].is_file()
    assert len(report.unaccepted) == 1
    assert any("UNACCEPTED" in line for line in said), said


def test_a_whitespace_blind_build_is_compared_the_same_way(monkeypatch,
                                                           sources):
    """`whitespace=False` tells Word not to treat respacing as a
    revision, so accepting legitimately leaves the ORIGINAL's spacing
    where the clean copy had changed it. Comparing exactly would refuse
    every build the Life Expectancy recipe makes.

    The words still have to match: only runs of whitespace are folded.
    """
    spaced = (f"<w:document {NS}><w:body>"
              '<w:p><w:r><w:t xml:space="preserve">Employment  rises'
              "</w:t></w:r></w:p></w:body></w:document>")
    fake = _FakeWordModule(spaced)
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment  rises")
    _target(sources[1], "Employment rises")

    report = tracked.build(sources[0], sources[1], sources[2],
                           verify_in_word=False, whitespace=False)

    assert report.unaccepted == []
    assert sources[2].is_file()


def test_the_words_still_have_to_match_when_whitespace_is_off(monkeypatch,
                                                             sources):
    """The other half of the fold: a build that ignores spacing does not
    ignore a word."""
    fake = _FakeWordModule(_mangled_insertion())
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment rises ")
    _target(sources[1], "Employment rises sharply")

    with pytest.raises(PackageError, match="accepting every revision"):
        tracked.build(sources[0], sources[1], sources[2],
                      verify_in_word=False, whitespace=False)


def test_a_faithful_redline_passes_the_reject_gate(monkeypatch, sources):
    report, _ = _build(monkeypatch, _clean_document(), sources)
    assert report.unrejectable == []
    assert "checked reject-all against the original" in \
        [label for label, _ in report.phases]


# ------------------------------------------- keeping the math tracked -----


def test_build_can_KEEP_the_math_tracked(monkeypatch, sources):
    """`resolve_math=False`: nothing is accepted on the paper's behalf.

    Measured on LI7: Flat OPC serialized 1870 revisions with the math
    tracked and reject-all reproduced the submitted paper 319/319, while
    resolving the math cost 315 revisions. A paper that has measured its
    own case must be able to say so.
    """
    called: list[str] = []
    monkeypatch.setattr(tracked, "_resolve_math",
                        lambda *a, **kw: called.append("resolved"))
    said: list[str] = []
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)
    original, revised, out = sources

    report = tracked.build(original, revised, out, verify_in_word=False,
                           resolve_math=False, progress=said.append)

    assert called == [], "the math pass ran anyway"
    assert report.math_resolved == 0
    assert out.is_file()
    assert any("math left tracked" in line for line in said), said


def test_keeping_the_math_still_SEEDS_the_comment_scaffold(monkeypatch,
                                                           sources):
    """`comments.annotate` CLONES a Word-made comment. Skipping the math
    pass skips the only place one was made, and the build would fail far
    away with ScaffoldMissing and no hint of the flag that caused it."""
    seeded: list[str] = []

    def _seed(*a, **kw):
        seeded.append("seeded")
        return 0

    monkeypatch.setattr(tracked, "_seed_scaffold", _seed)
    fake = _FakeWordModule(_revised_document(), scaffold=True)
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment rises ")
    _target(sources[1], "Employment rises sharply")

    report = tracked.build(sources[0], sources[1], sources[2],
                           classify=lambda ctx: "R1: sharpened",
                           resolve_math=False, verify_in_word=False)

    assert seeded == ["seeded"]
    # a scaffold comment is not a resolved math revision, and the
    # protocol refuses a whole batch on that number
    assert report.math_resolved == 0


def test_an_unannotated_build_seeds_NO_scaffold_when_math_is_kept(
        monkeypatch, sources):
    """classify=None means no comments at all; there is nothing to clone
    and nothing to seed."""
    seeded: list[str] = []
    monkeypatch.setattr(tracked, "_seed_scaffold",
                        lambda doc, classify, *a: seeded.append(classify))
    _build(monkeypatch, _clean_document(), sources, resolve_math=False)
    assert seeded == [None], "seeding is the classifier's business to refuse"


def test_build_report_formats_its_phases(monkeypatch, sources):
    report, _ = _build(monkeypatch, _clean_document(), sources)
    text = report.format()
    assert "compared" in text and "packed" in text
    assert "revisions 0" in text
    assert report.seconds >= 0


# ------------------------------------------------------ package counts ----


def test_package_counts_reads_what_the_file_holds():
    from docxkit.tracked import package_counts
    parts = {
        "word/document.xml": (
            b'<w:document><w:body><w:ins w:id="1"><w:r><w:t>a</w:t></w:r>'
            b'</w:ins><w:del w:id="2"><w:r><w:delText>b</w:delText></w:r>'
            b"</w:del></w:body></w:document>"),
        "word/comments.xml": (
            b'<w:comments><w:comment w:id="0"/><w:comment w:id="1"/>'
            b"</w:comments>"),
    }
    assert package_counts(parts) == {"insertions": 1, "deletions": 1,
                                     "comments": 2, "revisions": 2}


def test_package_counts_includes_the_footnotes():
    """A batch that edits only a footnote reported «0 pending revisions» — the
    number this workflow reads to decide a document is at truth — while the
    footnote carried three. Word counts them, so this must too."""
    from docxkit.tracked import package_counts
    parts = {
        "word/document.xml": b"<w:document><w:body/></w:document>",
        "word/footnotes.xml": (
            b'<w:footnotes><w:footnote w:id="7">'
            b'<w:ins w:id="1"><w:r><w:t>added</w:t></w:r></w:ins>'
            b'<w:del w:id="2"><w:r><w:delText>gone</w:delText></w:r></w:del>'
            b"</w:footnote></w:footnotes>"),
    }
    assert package_counts(parts) == {"insertions": 1, "deletions": 1,
                                     "comments": 0, "revisions": 2}


def test_package_counts_sees_a_formatting_only_batch():
    """`insertions` and `deletions` are both zero for a batch of nothing
    but property revisions, and the build printed that zero as its
    headline: it read as a Compare that had produced nothing, which is
    the documented shape of the math refusal. 25 footnote `w:rPrChange`
    revisions were in the file."""
    from docxkit.tracked import package_counts
    parts = {
        "word/document.xml": b"<w:document><w:body/></w:document>",
        "word/footnotes.xml": (
            b'<w:footnotes><w:footnote w:id="7"><w:p><w:r><w:rPr>'
            b'<w:sz w:val="20"/><w:rPrChange w:id="1" w:author="A" '
            b'w:date="2026-01-01T00:00:00Z"><w:rPr/></w:rPrChange>'
            b"</w:rPr><w:t>note</w:t></w:r></w:p></w:footnote>"
            b"</w:footnotes>"),
    }
    counted = package_counts(parts)
    assert (counted["insertions"], counted["deletions"]) == (0, 0)
    assert counted["revisions"] == 1


def test_package_counts_treats_a_missing_comments_part_as_zero():
    from docxkit.tracked import package_counts
    parts = {"word/document.xml": _clean_document().encode("utf-8")}
    assert package_counts(parts)["comments"] == 0


# --------------------------------------------------- the math resolution --


class _Count:
    """A COM-ish collection: .Count, callable 1-based indexing, and
    iteration — `word.revisions` deliberately uses the enumerator
    because indexing Revisions(i) is O(i)."""

    def __init__(self, items=()):
        self._items = list(items)
        self.Count = len(self._items)

    def __call__(self, i):
        return self._items[i - 1]

    def __iter__(self):
        return iter(self._items)


class _MathRange:
    def __init__(self, text="", omaths=0, revisions=(), span=(0, 0)):
        self.Text = text
        self.OMaths = _Count([object()] * omaths)
        self.Revisions = _Count(revisions)
        self.Start, self.End = span

    def Paragraphs(self, i):
        return type("P", (), {"Range": type("R", (), {"Text": self.Text})})


class _Rev:
    def __init__(self, text="", omaths=0, span=(0, 0)):
        self.Range = _MathRange(text, omaths=omaths, span=span)
        self.accepted = False

    def Accept(self):
        self.accepted = True


class _OMath:
    """doc.OMaths(i) is an OMath OBJECT carrying a .Range, not a range."""

    def __init__(self, revisions=(), span=(0, 0)):
        self.Range = _MathRange(revisions=revisions, span=span)


class _MathDoc:
    """A document where the two math scans see DIFFERENT revisions.

    One equation at 100–200 whose ``Range.Revisions`` holds both a
    revision INSIDE it and one that merely runs THROUGH it, plus three
    revisions of which only one CONTAINS math — the shape that made
    substituting one scan for the other drop 41 revisions on AFI, and
    the shape that cost LI7 315 revisions when the equation walk
    accepted the straddler.
    """

    def __init__(self):
        self.inside = _Rev("of the equation", span=(120, 150))
        self.straddling = _Rev("abstract .. equation .. §6", span=(10, 400))
        self.intersecting = [self.inside, self.straddling]
        self.containing = _Rev("has math", omaths=1)
        self.all_revisions = [_Rev("prose a"), self.containing,
                              _Rev("prose b")]
        self.OMaths = _Count([_OMath(revisions=self.intersecting,
                                     span=(100, 200))])
        self.Revisions = _Count(self.all_revisions)
        self.added: list[str] = []
        self.Comments = type("C", (), {
            "Add": lambda _s, rng, text: self.added.append(text),
            "Count": 0})()


def test_a_revision_that_only_RUNS_THROUGH_an_equation_stays_tracked():
    """The LI7 regression, pinned (2026-08-15).

    A revision appears in an equation's ``Range.Revisions`` if it merely
    OVERLAPS it, and ``Accept()`` applies the revision's WHOLE span. On
    LI7 thirteen such accepts destroyed 315 revisions and reject-all
    stopped reproducing the submitted paper — collateral as far as the
    abstract, which holds no equation at all.
    """
    from docxkit.tracked import _accept_math_via_equations

    doc = _MathDoc()
    outcome = _accept_math_via_equations(doc)

    assert doc.inside.accepted, "a revision OF the equation is resolved"
    assert not doc.straddling.accepted, \
        "accepting this one applies its whole span, abstract included"
    assert outcome == (1, 1)         # accepted, kept


def test_the_two_math_scans_select_different_revisions():
    """The AFI regression, pinned.

    The equation walk finds revisions in a math RANGE; the revision scan
    finds revisions CONTAINING math. They are not substitutes — swapping
    them left 41 revisions un-accepted, and the counts here differ for
    exactly that reason.
    """
    from docxkit.tracked import (
        _accept_math_via_equations,
        _comment_and_accept_math_revisions,
    )

    via_equations = _accept_math_via_equations(_MathDoc())

    doc = _MathDoc()
    via_revisions = _comment_and_accept_math_revisions(
        doc, lambda ctx: "R1: equation revised", None)

    assert via_equations.accepted == 1     # the revision inside the math
    assert via_revisions.accepted == 1     # the one that contains math
    assert via_equations.kept == 1 and via_revisions.kept == 0, \
        "the scans must not coincide"
    assert doc.containing.accepted
    assert doc.added == ["R1: equation revised"]


def test_resolve_math_picks_the_cheap_walk_when_nothing_is_commented(
        monkeypatch):
    from docxkit import tracked as T
    seen = []
    def _equations(doc, *args, **kw):
        seen.append("equations")
        return T.MathOutcome(7)

    def _revisions(*args, **kw):
        seen.append("revisions")
        return T.MathOutcome(3)

    monkeypatch.setattr(T, "_accept_math_via_equations", _equations)
    monkeypatch.setattr(T, "_comment_and_accept_math_revisions", _revisions)
    assert T._resolve_math(_MathDoc(), None, None) == T.MathOutcome(7)
    assert (T._resolve_math(_MathDoc(), lambda ctx: "x", None)
            == T.MathOutcome(3))
    assert seen == ["equations", "revisions"]


def test_the_math_pass_writes_its_notes_where_the_CALLER_can_read_them():
    """`notes = [] if notes is None else notes` fills in a list when
    there is none — and must leave the caller's alone when there is.
    Inverted, every note lands in a fresh list that is dropped on
    return: the build then reports a math pass with no reasons, which
    is exactly the shape of the LI7 failure the notes exist to explain.
    """
    from docxkit import tracked as T

    class _Hostile:
        @property
        def Count(self):
            raise RuntimeError("Word is busy")

    doc = type("D", (), {"OMaths": _Hostile()})()
    notes: list[str] = []

    assert T._resolve_math(doc, None, None, notes) == T.MathOutcome(0)
    assert any("could not read doc.OMaths" in n for n in notes), notes


def test_a_document_with_no_equations_resolves_nothing():
    from docxkit.tracked import _accept_math_via_equations

    class NoMath:
        OMaths = _Count()
    assert _accept_math_via_equations(NoMath()).accepted == 0


def test_the_scaffold_comment_is_seeded_when_no_math_revision_exists(
        monkeypatch):
    """comments.annotate clones a Word-made comment; without one the
    build fails later with ScaffoldMissing, far from the cause."""
    from docxkit import tracked as T

    doc = _MathDoc()
    doc.Revisions = _Count([_Rev("prose only")])       # no math anywhere
    monkeypatch.setattr(T._word, "revisions", lambda d: iter(()),
                        raising=False)
    seeded = T._comment_and_accept_math_revisions(
        doc, lambda ctx: "generic note", None)
    assert seeded.accepted == 1
    assert doc.added == ["generic note"]


def test_no_scaffold_is_seeded_for_an_unannotated_build():
    from docxkit.tracked import _seed_scaffold
    doc = _MathDoc()
    assert _seed_scaffold(doc, None, None) == 0
    assert doc.added == []


class _SeedDoc:
    """A document that records which revision got the comment."""

    def __init__(self, revisions):
        self.added: list[str] = []
        self.Revisions = _Count(revisions)
        outer = self

        class _Comments:
            Count = 0

            def Add(self, rng, text):
                outer.added.append(text)

        self.Comments = _Comments()


def test_a_batch_with_no_revisions_seeds_NOTHING_and_says_so():
    """The count this returns is what `_resolve_math` reports as
    resolved, and a scaffold that was not seeded must not read as one
    that was: the XML pass clones the comment this promises, and the
    build fails much later with ScaffoldMissing when the promise was
    just a number."""
    from docxkit.tracked import _seed_scaffold

    doc = _SeedDoc([])

    assert _seed_scaffold(doc, lambda ctx: "a note", None, []) == 0
    assert doc.added == []


def test_the_scaffold_is_seeded_on_the_FIRST_revision():
    """`doc.Revisions(1)`, and the fixture holds three so that every
    other index is a different revision — with one, Revisions(0) and
    Revisions(-1) read back the same object through a Python list and
    the number is invisible.

    Which revision carries it is not cosmetic: the XML pass clones this
    comment, so it must be one Word will still have when it runs."""
    from docxkit.tracked import _seed_scaffold

    doc = _SeedDoc([_Rev("first"), _Rev("second"), _Rev("third")])

    assert _seed_scaffold(doc, lambda ctx: ctx.text, None, []) == 1
    assert doc.added == ["first"], doc.added


# ------------------------------------------------------------- verify ----


class _WordSaying:
    """A fake Word that reads back whatever counts the test dictates."""

    def __init__(self, comments: int, revisions: int = 0, paras: int = 1):
        self.doc = _FakeDoc()
        self.doc.Comments = _Count([object()] * comments)
        self.doc.Revisions = _Count([object()] * revisions)
        self.doc.Paragraphs = _Count([object()] * paras)

    @contextlib.contextmanager
    def session(self):
        yield object()

    @contextlib.contextmanager
    def open_doc(self, word, path, **kw):
        yield self.doc


def _redline(path: Path, *, comments: int) -> Path:
    """A package holding `comments` comments and one insertion."""
    from docxkit.package import write_docx
    body = ('<w:ins w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
            "<w:r><w:t>new</w:t></w:r></w:ins>")
    com = "".join(f'<w:comment w:id="{i}"><w:p/></w:comment>'
                  for i in range(comments))
    write_docx(path, {
        "word/document.xml": (f"<w:document {NS}><w:body><w:p>{body}</w:p>"
                              "</w:body></w:document>").encode(),
        "word/comments.xml": (f"<w:comments {NS}>{com}</w:comments>"
                              ).encode()})
    return path


def test_verify_reports_agreement_between_word_and_the_package(
        monkeypatch, tmp_path):
    path = _redline(tmp_path / "r.docx", comments=3)
    monkeypatch.setattr(tracked, "_word", _WordSaying(comments=3,
                                                      revisions=1))
    got = tracked.verify(path)
    assert got["package"] == {"insertions": 1, "deletions": 0,
                              "comments": 3, "revisions": 1}
    assert got["word"]["comments"] == 3
    assert got["comments_match"] is True


def test_verify_compares_the_COUNTS_not_the_objects(monkeypatch, tmp_path):
    """`==`, not `is`. Word's count and the package's are computed in
    two different places, and CPython only hands back one object per
    int up to 256 — so below the cache the two spellings agree on
    every count, and above it the identity test reads every agreement
    as a Word repair. A build then refuses a deliverable that is fine,
    and the paper with three hundred comments is exactly the one nobody
    wants to rebuild."""
    path = _redline(tmp_path / "r.docx", comments=300)
    monkeypatch.setattr(tracked, "_word",
                        _WordSaying(comments=len([0] * 300), revisions=1))

    got = tracked.verify(path)

    assert got["package"]["comments"] == 300
    assert got["word"]["comments"] == 300
    assert got["comments_match"] is True


def test_verify_reports_the_disagreement_word_repair_causes(
        monkeypatch, tmp_path):
    """Word silently drops markup it dislikes; the count is the tell."""
    path = _redline(tmp_path / "r.docx", comments=5)
    monkeypatch.setattr(tracked, "_word", _WordSaying(comments=2))
    got = tracked.verify(path)
    assert got["package"]["comments"] == 5
    assert got["word"]["comments"] == 2
    assert got["comments_match"] is False


def test_a_build_word_repairs_raises_and_keeps_the_old_deliverable(
        monkeypatch, sources):
    """The other half of the P0-1 property: a verify mismatch must not
    publish either, and the previous deliverable must survive."""
    out = sources[2]
    out.write_bytes(b"PREVIOUS GOOD DELIVERABLE")
    tracked._guard.stamp(out)
    before = out.read_bytes()

    # the package will hold 0 comments; Word claims 99 -> repaired
    saying = _WordSaying(comments=99)
    fake = _FakeWordModule(_clean_document())
    fake.session = saying.session                            # type: ignore
    fake.open_doc = saying.open_doc                          # type: ignore
    monkeypatch.setattr(tracked, "_word", fake)

    with pytest.raises(PackageError, match="repaired on open"):
        tracked.build(sources[0], sources[1], out, verify_in_word=True)
    assert out.read_bytes() == before
    # and the refused build is kept, which is the whole point of a
    # verify mismatch: the package and Word disagree, and the file they
    # disagree about is the evidence.
    assert list(out.parent.glob("~*.building*"))


# ------------------------------------------- the annotate path, for real --


def test_a_build_that_annotates_comments_every_revision(monkeypatch,
                                                        sources):
    """The heart of the pipeline, with comments.annotate running for
    real: the Flat OPC carries Word's scaffold comment, the XML pass
    clones it, and the package must hold both comments afterwards."""
    fake = _FakeWordModule(_revised_document(), scaffold=True)
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment rises ")
    _target(sources[1], "Employment rises sharply")
    out = sources[2]

    report = tracked.build(sources[0], sources[1], out,
                           classify=lambda ctx: "R1: sharpened",
                           verify_in_word=False)

    from docxkit.package import read_parts
    from docxkit.tracked import package_counts
    counts = package_counts(read_parts(out))
    assert counts["insertions"] == 1
    assert counts["comments"] == report.comments_total >= 1
    assert report.comments_added >= 1


def test_a_successful_verify_is_recorded_on_the_report(monkeypatch,
                                                       sources):
    saying = _WordSaying(comments=0, revisions=4)
    fake = _FakeWordModule(_revised_document())
    fake.session = saying.session                            # type: ignore
    fake.open_doc = saying.open_doc                          # type: ignore
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment rises ")
    _target(sources[1], "Employment rises sharply")

    report = tracked.build(sources[0], sources[1], sources[2],
                           verify_in_word=True)
    assert report.verified_comments == 0
    assert report.verified_revisions == 4
    assert "verified in Word" in [label for label, _ in report.phases]


def test_the_progress_callback_reports_a_forced_overwrite(monkeypatch,
                                                          sources):
    """force=True proceeds over a hand-edited deliverable, but the
    backup it took has to be announced — silently discarding an author's
    review is the incident guard.py exists for."""
    out = sources[2]
    out.write_bytes(b"AUTHOR REVIEWED THIS")          # unstamped
    said: list[str] = []
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)

    tracked.build(sources[0], sources[1], out, verify_in_word=False,
                  force=True, progress=said.append)
    assert any("backed up" in line for line in said), said
    assert any(p.read_bytes() == b"AUTHOR REVIEWED THIS"
               for p in out.parent.glob("*user_edited*"))


# --------------------------------------------- a COM object that raises ---


class _Exploding:
    """A collection whose members raise, as COM members do."""

    Count = 1

    def __call__(self, i):
        raise RuntimeError("Call was rejected by callee")


def test_one_unreachable_equation_does_not_abort_the_math_pass():
    from docxkit.tracked import _accept_math_via_equations

    class Doc:
        OMaths = _Exploding()
    assert _accept_math_via_equations(Doc()).accepted == 0   # skipped


def test_a_revision_that_raises_is_skipped_not_fatal(monkeypatch):
    from docxkit import tracked as T

    class Hostile:
        @property
        def Range(self):
            raise RuntimeError("Call was rejected by callee")

    doc = _MathDoc()
    monkeypatch.setattr(T._word, "revisions",
                        lambda d: iter([Hostile(), doc.containing]),
                        raising=False)
    assert T._comment_and_accept_math_revisions(
        doc, lambda ctx: "note", None).accepted == 1


# ------------------------------------------- failure is not advisory ------


def test_a_swallowed_word_failure_is_recorded_not_hidden():
    """A COM call that fails must not leave success-shaped numbers.

    Every call here is suppressed so one hostile revision cannot abort a
    1400-revision build; suppressing SILENTLY is what let a
    half-finished build look complete.
    """
    from docxkit.tracked import _accept_math_via_equations

    class Doc:
        OMaths = _Exploding()

    notes: list[str] = []
    assert _accept_math_via_equations(Doc(), notes).accepted == 0
    assert notes and "unreachable" in notes[0]


def test_a_comment_word_refuses_is_recorded_with_the_text():
    from docxkit.tracked import _comment_revision

    class Hostile:
        Range = _MathRange("the revised sentence")

        class Comments:
            @staticmethod
            def Add(rng, text):
                raise RuntimeError("Call was rejected by callee")

    notes: list[str] = []
    _comment_revision(Hostile(), Hostile(), lambda ctx: "R1", None, notes)
    assert notes and "comment not added" in notes[0]


def test_the_report_prints_what_was_skipped():
    report = tracked.BuildReport()
    report.suppressed = [f"equation {i}: unreachable" for i in range(12)]
    text = report.format()
    assert "12 Word call(s) failed" in text
    assert "and 2 more" in text            # the list is capped at ten


def test_a_clean_build_reports_nothing_suppressed(monkeypatch, sources):
    report, _ = _build(monkeypatch, _clean_document(), sources)
    assert report.suppressed == []
    assert "failed" not in report.format()


# ------------------------------------ what Word's Compare quietly removes ---
#
# Compare rebuilds the document rather than annotating it, and drops what
# it declines to carry over without a word. All three shapes below came
# off ONE manuscript (LI7) on one day, and every one was found by hand
# afterwards because the build reported revisions and comments and
# nothing else.

def _pkg(doc_xml: str, **extra: str) -> dict[str, bytes]:
    parts = {"word/document.xml": document(doc_xml).encode("utf-8")}
    parts.update({k: v.encode("utf-8") for k, v in extra.items()})
    return parts


def test_a_dropped_part_is_reported():
    """word/header1.xml and three customXml items, on the RF-a promote."""
    revised = _pkg(para(run("x")), **{"word/header1.xml": "<w:hdr/>"})
    redline = _pkg(para(run("x")))
    (note,) = tracked.compare_collateral(revised, redline)
    assert note.startswith("part LOST: word/header1.xml")


def test_a_part_word_REGENERATES_is_not_reported_as_a_loss():
    """The same "part dropped" line was printed for docProps/app.xml —
    which Word rewrites on every save — and for the customXml data
    store, which nothing puts back. The real loss was unreadable inside
    the noise, and it reached a live manuscript that way (Parental Style
    2026-08-12). The regenerated ones sort LAST, and say so."""
    revised = _pkg(para(run("x")), **{"docProps/app.xml": "<Properties/>",
                                      "customXml/item1.xml": "<b:Sources/>"})
    notes = tracked.compare_collateral(revised, _pkg(para(run("x"))))
    assert notes[0].startswith("part LOST: customXml/item1.xml")
    assert notes[1].startswith("part dropped: docProps/app.xml")
    assert "regenerates" in notes[1]


def test_docProps_custom_is_a_LOSS_not_word_bookkeeping():
    """It sat under the same "Word regenerates it on save" line as
    app.xml, and the parts gate skipped it by design. It is not Word's:
    those are user-defined properties, and on this Bank manuscript they
    were the sensitivity label and the "Official Use Only" footer
    marking (Aging_Well R1, 2026-08-21)."""
    revised = _pkg(para(run("x")),
                   **{"docProps/custom.xml": "<Properties/>",
                      "docProps/app.xml": "<Properties/>"})
    notes = tracked.compare_collateral(revised, _pkg(para(run("x"))))
    assert notes[0].startswith("part LOST: docProps/custom.xml")
    assert notes[1].startswith("part dropped: docProps/app.xml")


def test_a_dropped_bookmark_is_reported():
    """OECD2021txt: its start had no matching end, so Word discarded it
    and the reference entry's back-link pointed at nothing."""
    revised = _pkg('<w:bookmarkStart w:id="1" w:name="OECD2021txt"/>'
                   + para(run("x")))
    assert tracked.compare_collateral(revised, _pkg(para(run("x")))) == [
        "bookmark dropped: OECD2021txt"]


def test_a_dropped_link_is_reported():
    """162 links in, 161 out, and nothing said so."""
    linked = ('<w:hyperlink w:anchor="Hadiyana2021">'
              + run("Hudiyana 2022") + "</w:hyperlink>")
    revised = _pkg(f"<w:p>{linked}</w:p>")
    redline = _pkg(para(run("Hudiyana 2022")))
    assert tracked.compare_collateral(revised, redline) == [
        "link dropped: -> Hadiyana2021"]


def test_carrying_everything_over_reports_nothing():
    same = _pkg('<w:bookmarkStart w:id="1" w:name="Keep"/>'
                + para(run("x")), **{"word/header1.xml": "<w:hdr/>"})
    assert tracked.compare_collateral(same, dict(same)) == []


def test_something_the_redline_GAINED_is_not_a_loss():
    """The direction matters and only an asymmetric case shows it. Each
    of these three lines is a set DIFFERENCE; read as a symmetric
    difference (`^`) or a union (`|`) — five surviving mutants between
    them — anything the redline gained is announced as dropped, and the
    warning that exists to catch a real loss starts crying wolf on every
    build. Word's Compare adds bookmarks of its own."""
    revised = _pkg(para(run("x")))
    redline = _pkg('<w:bookmarkStart w:id="9" w:name="_Toc12345"/>'
                   + f'<w:hyperlink w:anchor="Added">{run("y")}</w:hyperlink>'
                   + para(run("x")), **{"word/footer1.xml": "<w:ftr/>"})
    assert tracked.compare_collateral(revised, redline) == []


def test_what_the_redline_ADDS_is_not_a_loss():
    """The build writes comments.xml into the redline; only what the
    revised copy had and the redline lacks counts."""
    revised = _pkg(para(run("x")))
    redline = _pkg(para(run("x")), **{"word/comments.xml": "<w:comments/>"})
    assert tracked.compare_collateral(revised, redline) == []


def test_bookmarks_are_read_from_every_part_not_just_the_body():
    """A citation bookmark can live in footnotes.xml, and losing one
    there is exactly as fatal to the link."""
    revised = _pkg(para(run("x")), **{
        "word/footnotes.xml": document(
            '<w:bookmarkStart w:id="9" w:name="Jdanov2008txt"/>'
            + para(run("note")))})
    redline = _pkg(para(run("x")), **{
        "word/footnotes.xml": document(para(run("note")))})
    assert tracked.compare_collateral(revised, redline) == [
        "bookmark dropped: Jdanov2008txt"]


def test_the_report_prints_what_compare_dropped():
    report = tracked.BuildReport()
    report.dropped = [f"bookmark dropped: B{i}" for i in range(12)]
    text = report.format()
    assert "dropped 12 thing(s)" in text
    assert "and 2 more" in text            # capped at ten, like suppressed


def test_a_clean_build_reports_nothing_dropped(monkeypatch, sources):
    report, _ = _build(monkeypatch, _clean_document(), sources)
    assert report.dropped == []
    assert "dropped" not in report.format()


# ------------------------------------- the gate the deliverable exists for --
#
# `untracked` is what makes a redline REFUSABLE: a paragraph the batch
# changed with no revision covering it is an edit the author was never
# offered. Parental Style shipped a merged, rewritten math-bearing
# paragraph that way while its batch read "7 revisions, 6 of them in the
# body"; LI7 shipped 315 revisions' worth from an over-eager math accept.
#
# 44 survivors, the largest cluster in this module: it was reached only
# through `build`, which asks whether the list is EMPTY, so everything
# the list says — which paragraph, which side, how many — was free.

def _parts(*paras: str, footnotes: str | None = None) -> dict[str, bytes]:
    return make_parts("".join(paras), footnotes=footnotes)


def test_a_paragraph_changed_with_NO_revision_is_named():
    baseline = _parts(para(run("The index rose to 0.35 in 2024.")))
    batch = _parts(para(run("The index rose to 0.37 in 2024.")))

    (found,) = untracked(batch, baseline)

    assert found.part == "body"
    assert found.index == 0
    assert found.baseline == "The index rose to 0.35 in 2024."
    assert found.batch == "The index rose to 0.37 in 2024."


def test_a_properly_TRACKED_change_is_not_a_finding():
    """Rejecting it restores the baseline, which is the whole test."""
    baseline = _parts(para(run("The index rose.")))
    batch = _parts(para(dele("The index rose.") + ins("The index fell.")))

    assert untracked(batch, baseline) == []


def test_a_paragraph_the_batch_ADDED_reports_an_empty_baseline():
    """The two sides are what a reader compares, and one of them being
    empty is the finding: nothing was there before."""
    baseline = _parts(para(run("Alpha.")))
    batch = _parts(para(run("Alpha.")), para(run("Beta, out of nowhere.")))

    (found,) = untracked(batch, baseline)

    assert (found.baseline, found.batch) == ("", "Beta, out of nowhere.")
    assert found.index == 1


def test_the_paragraph_number_counts_in_the_view_the_reader_OPENS():
    """`label, j1 + k` — the index into the REJECTED view, not into the
    baseline. The two part company as soon as the batch adds a
    paragraph above the difference, and they are the same number in
    every fixture that does not.

    A person takes this number to `working.docx` and counts down. Read
    off the baseline it is short by every insertion above it, which on
    a real batch is most of them."""
    # TWO insertions with an unchanged paragraph between them: the
    # second is where the two indices part company, because by then the
    # batch is one paragraph ahead of the baseline
    baseline = _parts(para(run("Alpha.")), para(run("Gamma.")))
    batch = _parts(para(run("Alpha.")), para(run("Inserted one.")),
                   para(run("Gamma.")), para(run("Inserted two.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.batch) for f in found] == [
        (1, "Inserted one."), (3, "Inserted two.")], found
    assert "¶2" in str(found[0]) and "¶4" in str(found[1])


def test_an_unaccepted_paragraph_is_quoted_at_seventy_characters():
    """The accept side's own record, and the same cut as the reject
    side's: two paragraphs, side by side, on one line each. Uncut, one
    finding fills the terminal and the eight the limit allows fill a
    screen nobody reads."""
    long_line = ("The revised sentence, at some length, because a "
                 "paragraph in a paper usually is.")
    assert len(long_line) > 71
    intended = _parts(para(run(long_line)))
    parts = _parts(para(run("Employment rises "),
                        ins("sharply, and not what was asked for")))

    (missed,) = unaccepted(parts, intended)

    assert missed.intended == long_line
    assert repr(long_line[:70]) in str(missed)
    assert repr(long_line[:71]) not in str(missed)


def test_unaccepted_stops_at_EIGHT_findings_by_default():
    """`limit: int = 8`. The refusal prints every finding it is given,
    and a batch that went wrong at the top goes wrong all the way down
    — a document whose accept reproduces nothing would print a page per
    paragraph. Eight is what a person reads before going to look at the
    file, and the reject side has stopped there since it was written."""
    intended = _parts(*[para(run(f"Intended {i}.")) for i in range(12)])
    parts = _parts(*[para(run(f"Accepted {i}.")) for i in range(12)])

    assert len(unaccepted(parts, intended)) == 8
    assert len(unaccepted(parts, intended, limit=3)) == 3


def test_unaccepted_compares_the_SPACING_too_unless_told_not_to():
    """`fold_space: bool = False`. The default is the exact comparison,
    because a build that tracks whitespace must reproduce it — only a
    `whitespace=False` build legitimately accepts to the original's
    spacing, and `build` passes the flag for exactly that case.

    Defaulted the other way, respacing inside an insertion — which is
    Word rewriting content, the thing this gate exists to catch — would
    pass every build."""
    intended = _parts(para(run("Employment rises sharply here.")))
    parts = _parts(para(run("Employment  rises sharply here.")))

    (missed,) = unaccepted(parts, intended)
    assert missed.accepted == "Employment  rises sharply here."

    assert unaccepted(parts, intended, fold_space=True) == []


def test_a_paragraph_the_batch_LOST_reports_an_empty_batch():
    baseline = _parts(para(run("Alpha.")), para(run("Beta, now gone.")))
    batch = _parts(para(run("Alpha.")))

    (found,) = untracked(batch, baseline)

    assert (found.baseline, found.batch) == ("Beta, now gone.", "")


def test_a_MERGE_reports_every_paragraph_of_the_block():
    """Three paragraphs replaced by one is the shape that shipped: the
    walk covers the LONGER side, so the two that vanished are named as
    well as the one that stayed."""
    baseline = _parts(para(run("First.")), para(run("Second.")),
                      para(run("Third.")))
    batch = _parts(para(run("All three, merged.")))

    found = untracked(batch, baseline)

    assert [(f.baseline, f.batch) for f in found] == [
        ("First.", "All three, merged."), ("Second.", ""), ("Third.", "")]


def test_the_FOOTNOTES_are_checked_too_and_labelled():
    """An edit the author cannot refuse is as bad in a note as in the
    body, and the label is which file to open."""
    notes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<w:footnotes {NS}><w:footnote w:id="2">'
             f"{para(run('The note, as built.'))}</w:footnote></w:footnotes>")
    changed = notes.replace("as built", "as edited")

    (found,) = untracked(_parts(para(run("x")), footnotes=changed),
                         _parts(para(run("x")), footnotes=notes))

    assert found.part == "footnotes"
    assert found.batch == "The note, as edited."


def test_the_list_STOPS_at_eight():
    """A batch that lost its revisions entirely would otherwise print
    the manuscript, and the first eight are enough to say the batch is
    not reviewable."""
    baseline = _parts(*(para(run(f"Paragraph {i}.")) for i in range(12)))
    batch = _parts(*(para(run(f"Paragraph {i} rewritten."))
                     for i in range(12)))

    assert len(untracked(batch, baseline)) == 8
    assert len(untracked(batch, baseline, limit=3)) == 3


def test_the_finding_PRINTS_where_it_is_and_both_sides():
    """One-based in the message, because that is how Word counts, and
    zero-based in the field, because that is how a caller indexes."""
    baseline = _parts(para(run("Alpha.")), para(run("Beta.")))
    batch = _parts(para(run("Alpha.")), para(run("Beta, changed.")))

    (found,) = untracked(batch, baseline)

    printed = str(found)
    assert printed.startswith("body ¶2: baseline 'Beta.'")
    assert "batch    'Beta, changed.'" in printed


# --- the second round, from the re-measurement of 2026-08-18 -------------
#
# 36.3 % -> 28.5 % after the tests above, and `untracked` was STILL the
# largest cluster with 23. Seventeen of them sat on `i1 + k` and `j1 + k`
# mutated to `|`, `^`, `>>` — which agree with `+` whenever the left
# operand is 0, and every fixture above starts its changed block at
# paragraph 0 or 1. A paper's untracked edit is on page nine.


def test_a_block_deep_in_the_document_reports_the_paragraphs_it_IS():
    """`i1 + k` with `i1` at 3: `3|1` is 3 and `3^1` is 2, where `3+1`
    is 4. At index 0 every one of those is the same number, which is why
    a fixture that starts at the top cannot tell them apart — and the
    report would then name the wrong three paragraphs of a manuscript
    whose author is looking for the one nobody offered them."""
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    baseline = _parts(*keep, para(run("Alpha original.")),
                      para(run("Beta original.")),
                      para(run("Gamma original.")), para(run("Tail.")))
    batch = _parts(*keep, para(run("Alpha rewritten.")),
                   para(run("Beta rewritten.")),
                   para(run("Gamma rewritten.")), para(run("Tail.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.baseline, f.batch) for f in found] == [
        (3, "Alpha original.", "Alpha rewritten."),
        (4, "Beta original.", "Beta rewritten."),
        (5, "Gamma original.", "Gamma rewritten.")]


def test_an_INSERTED_paragraph_shifts_the_batch_side_and_not_the_other():
    """The two offsets are different numbers here, so `j1` cannot stand
    in for `i1`: the batch has one paragraph more, the baseline runs out
    first, and the last finding is a paragraph that exists on one side
    only. It is also what an untracked insertion looks like — the
    paragraphs after it all read as changed, because they have moved."""
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    baseline = _parts(*keep, para(run("Alpha original.")),
                      para(run("Beta original.")), para(run("Tail.")))
    batch = _parts(*keep, para(run("New paragraph.")),
                   para(run("Alpha rewritten.")),
                   para(run("Beta rewritten.")), para(run("Tail.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.baseline, f.batch) for f in found] == [
        (3, "Alpha original.", "New paragraph."),
        (4, "Beta original.", "Alpha rewritten."),
        (5, "", "Beta rewritten.")]


def test_the_limit_is_KEYWORD_only():
    """A bare number at the call site would read as a third document."""
    baseline = _parts(para(run("Alpha.")))
    batch = _parts(para(run("Beta.")))

    with pytest.raises(TypeError):
        untracked(batch, baseline, 3)          # type: ignore[call-arg]


def test_a_MERGE_deep_in_the_document_covers_the_LONGER_side():
    """`max(i2 - i1, j2 - j1)` decides how far the walk goes, and only a
    block where the two sides differ in LENGTH says which term won: three
    paragraphs became one, so the baseline side is the longer one. With
    `i1` at 3, `i2 >> i1` is 0 and the walk stops after the first — the
    two paragraphs that vanished go unnamed, which is the Parental Style
    shape exactly, one page further in."""
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    baseline = _parts(*keep, para(run("First.")), para(run("Second.")),
                      para(run("Third.")), para(run("Tail.")))
    batch = _parts(*keep, para(run("All three, merged.")),
                   para(run("Tail.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.baseline, f.batch) for f in found] == [
        (3, "First.", "All three, merged."),
        (4, "Second.", ""),
        (5, "Third.", "")]


# --- the Word path's own report, from the same re-measurement ------------
#
# `_comment_revision` 13 survivors and `_accept_math_via_equations` 11,
# the two largest after `untracked`. Both run only through Word, so the
# fakes above are the whole harness — and they asserted what the
# functions DID (a comment added, a revision accepted) and never what
# they were told. Eight of the thirteen sat on the two sentinels the
# context carries, which is what a paper's classifier reads.


class _ClassifierRange:
    """A revision's range: its own text, and the paragraph around it."""

    Text: str | None = "the revised phrase"
    PARAGRAPHS: ClassVar[dict[int, str]] = {
        1: "The paragraph the revision sits in.",
        2: "A different paragraph entirely."}

    def Paragraphs(self, i):
        text = self.PARAGRAPHS[i]
        return type("P", (), {"Range": type("R", (), {"Text": text})})


class _NullTextRange(_ClassifierRange):
    """Word hands back None for an empty range, not an empty string."""

    Text = None


class _CommentDoc:
    def __init__(self):
        self.added: list[str] = []
        self.Comments = type("C", (), {
            "Add": lambda _s, rng, text: self.added.append(text),
            "Count": 0})()


def test_what_the_CLASSIFIER_is_handed_on_the_Word_path():
    """The paper's own function reads this, and a build makes one call
    per revision. `window` is the paragraph because Word gives no wider
    scope here, `table_index` is None because it cannot say, and the two
    offsets are -1: a sentinel that means "not located", where 0 and 1
    are real positions a rule could match on."""
    from docxkit.comments import RevisionContext
    from docxkit.tracked import _comment_revision
    seen: list[RevisionContext] = []

    def classify(ctx):
        seen.append(ctx)
        return "R1: the comment"

    doc = _CommentDoc()
    _comment_revision(doc, type("Rev", (), {"Range": _ClassifierRange()}),
                      classify, None)

    (ctx,) = seen
    assert ctx.text == "the revised phrase"
    assert ctx.para == "The paragraph the revision sits in."
    assert ctx.window == ctx.para
    assert ctx.table_index is None
    assert (ctx.start, ctx.end) == (-1, -1)
    assert doc.added == ["R1: the comment"]


def test_a_range_Word_reports_as_None_reaches_the_classifier_as_TEXT():
    """`rng.Text or ""` — with `and` in its place the context carries
    None, and a classifier doing `"table" in ctx.text` raises inside the
    paper's own code, one revision into a build of fourteen hundred."""
    from docxkit.tracked import _comment_revision
    seen = []

    def classify(ctx):
        seen.append(ctx.text)
        return "R1"

    _comment_revision(_CommentDoc(),
                      type("Rev", (), {"Range": _NullTextRange()}),
                      classify, None)

    assert seen == [""]


class _BoundedMathDoc:
    """One equation at 100-200 and four revisions around its edges."""

    def __init__(self):
        self.exact = _Rev("exactly the equation", span=(100, 200))
        self.inside = _Rev("well within it", span=(120, 150))
        self.overhangs_left = _Rev("starts in the prose", span=(90, 150))
        self.overhangs_right = _Rev("runs past the end", span=(150, 250))
        self.revisions = [self.exact, self.inside,
                          self.overhangs_left, self.overhangs_right]
        self.OMaths = _Count([_OMath(revisions=self.revisions,
                                     span=(100, 200))])
        self.Revisions = _Count(self.revisions)


def test_a_revision_ON_the_equation_boundary_is_OF_the_equation():
    """`lo <= span[0] and span[1] <= hi`, at the two places it is
    decided. A revision that covers the equation exactly is the whole of
    it and must be accepted; one that starts a character earlier, or
    ends a character later, carries prose with it — and `Accept()`
    applies the WHOLE span, which is how thirteen accepts destroyed 315
    revisions on LI7."""
    from docxkit.tracked import _accept_math_via_equations

    doc = _BoundedMathDoc()
    outcome = _accept_math_via_equations(doc)

    assert doc.exact.accepted, "a revision covering it exactly is OF it"
    assert doc.inside.accepted
    assert not doc.overhangs_left.accepted, "it starts in the prose"
    assert not doc.overhangs_right.accepted, "it ends in the prose"
    assert outcome == (2, 2)          # accepted, kept


# --- the report itself, from the same re-measurement --------------------
#
# `format` 9 survivors, `__init__` 8, `mark` and `seconds` 5 between
# them, `__str__` 4. This is the text a paper's author reads to decide
# whether a redline is worth opening, and the numbers in it were free:
# every counter's initial 0, the cap on the two lists, the "and N more"
# arithmetic, and every phase duration.


def test_a_FRESH_report_counts_nothing():
    """Every counter starts at 0 and every list empty, so a build that
    fails before its first phase reports a build that did nothing —
    rather than one that resolved a revision it never saw."""
    report = tracked.BuildReport()

    assert (report.revisions, report.body_revisions) == (0, 0)
    assert (report.math_resolved, report.math_kept) == (0, 0)
    assert (report.comments_added, report.comments_total) == (0, 0)
    assert report.unclassified == 0
    assert report.verified_comments is None
    assert report.verified_revisions is None
    assert report.suppressed == report.dropped == []
    assert report.carried == report.carried_properties == []
    assert report.restored_glyphs == []
    assert report.unrejectable == []
    assert report.phases == []


@pytest.mark.parametrize("field,head", [
    ("suppressed", "Word call(s) failed"),
    ("dropped", "thing(s) the revised copy had"),
])
def test_the_two_lists_print_TEN_and_then_a_count(field, head):
    """Ten is the cap, and the line after it is a subtraction, not a
    remainder: with 21 notes `21 % 10` also reads "1 more", which is
    what a 12-item fixture cannot tell apart from `21 - 10`."""
    def rendered(n: int) -> list[str]:
        report = tracked.BuildReport()
        setattr(report, field, [f"note {i}" for i in range(n)])
        return report.format().splitlines()

    at_three = rendered(3)
    assert sum("- note" in ln for ln in at_three) == 3
    assert not [ln for ln in at_three if "more" in ln], (
        "under the cap there is no remainder, and `!= 10` prints -7 more")

    at_ten = rendered(10)
    assert sum("- note" in ln for ln in at_ten) == 10
    assert not [ln for ln in at_ten if "more" in ln], "ten is not capped"
    assert any(head in ln for ln in at_ten)

    at_eleven = rendered(11)
    assert sum("- note" in ln for ln in at_eleven) == 10
    assert "    ... and 1 more" in at_eleven

    assert "    ... and 11 more" in rendered(21)


def test_the_math_KEPT_line_appears_only_when_something_was_kept():
    """A revision that overlaps an equation without being of it is left
    tracked on purpose, and saying so is how a reader knows the number
    is a decision rather than a failure. Saying it when the count is
    zero — "0 revision(s) overlap an equation" — is noise on every
    clean build there is."""
    quiet = tracked.BuildReport()
    loud = tracked.BuildReport()
    loud.math_kept = 3

    assert "overlap an equation" not in quiet.format()
    assert "3 revision(s) overlap an equation" in loud.format()


def test_a_phase_is_timed_from_the_one_BEFORE_it(monkeypatch):
    """`now - self._last` is the phase; `now - self._t0` is the build.
    Mutated to `+` the phases read as clock readings, and every one of
    them looks like the slowest step there has ever been."""
    # every reading after the marks is 10.0, because `seconds` is a
    # property and the assertions below ask for it more than once.
    #
    # The numbers are chosen so each reading is more than TWICE the one
    # before: `a % b` is `a - b` for every b <= a < 2b, so a clock that
    # ticks 100, 101, 103 cannot tell the subtraction from a modulo —
    # which is what the first version of this test did, and four
    # mutants lived behind it.
    ticks = itertools.chain([1.0, 3.0, 8.0], itertools.repeat(10.0))
    monkeypatch.setattr(tracked, "time", type("T", (), {
        "perf_counter": staticmethod(lambda: next(ticks))}))

    report = tracked.BuildReport()       # 1.0
    report.mark("compare")               # 3.0
    report.mark("comments")              # 8.0

    assert report.phases == [("compare", 2.0), ("comments", 5.0)]
    assert report.seconds == 9.0         # 10.0, from the start
    assert "[   2.0s] compare" in report.format()


def test_an_untracked_finding_names_the_paragraph_WORD_shows():
    """Word numbers the third paragraph 3, and the field counts from 0,
    so the message adds one — `index << 1` is 4 for the same finding,
    and the author opens the wrong paragraph. Both sides are cut at 70
    characters, and the second line is padded to the width of the first
    so the two read as a column."""
    long_baseline = "The sentence as the baseline has it, " + "x" * 60
    finding = tracked.Untracked("body", 2, long_baseline,
                                "What the batch has instead.")

    first, second = str(finding).splitlines()

    assert first.startswith("body ¶3: baseline ")
    assert first.endswith(repr(long_baseline[:70]))
    assert len(long_baseline) > 70, "the fixture has to be cut to say so"
    assert second == (" " * len("body ¶3") + "  batch    "
                      + repr("What the batch has instead."))


def test_an_unaccepted_finding_names_the_paragraph_WORD_shows():
    """The accept side's own message, and the same arithmetic: thirteen
    mutants sat on that `+ 1` — `index | 1`, `index ^ 1`, `index << 1`
    and the rest — because nothing had ever read a paragraph number
    out of an Unaccepted, only out of an Untracked.

    Both sides are cut at 70 and the second line is padded to the width
    of the first, so intended and accepted read as a column."""
    long_accepted = "What accepting everything leaves there, " + "x" * 60
    # index 3, not 2: `2 | 1` and `2 ^ 1` are both 3, so an even index
    # is a paragraph number two of the spellings agree on
    finding = tracked.Unaccepted("body", 3, "What the clean copy says.",
                                 long_accepted)

    first, second = str(finding).splitlines()

    assert first.startswith("body ¶4: intended ")
    assert len(long_accepted) > 70, "the fixture has to be cut to say so"
    assert second == (" " * len("body ¶4") + "  accepted "
                      + repr(long_accepted[:70]))


# --- the move that duplicates a table (DSI, 2026-08-19) -----------------
#
# Word's Compare answers a moved block by writing the table TWICE and
# marking neither copy. On DSI the redline carried 28 tables against the
# baseline's 27, and BOTH accept and reject left 28 — so the author could
# not get rid of it, and every other signal read as success. A move whose
# rows Word DOES flag is handled (`revisions._row_flag` reads `w:trPr`);
# this is the shape that cannot be resolved, only refused.


def _table_xml(cell: str = "cell") -> str:
    return ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>" + cell
            + "</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")


def test_build_REFUSES_a_redline_that_carries_a_table_twice(monkeypatch,
                                                            sources):
    """The refusal names both counts. Nothing here can tell which copy
    is the spurious one — an unmarked table is not a revision — so the
    answer is to say so before the file reaches an author."""
    doubled = _clean_document().replace(
        "</w:body>", _table_xml() + _table_xml() + "</w:body>")
    with pytest.raises(PackageError, match="STRUCTURE"):
        _build(monkeypatch, doubled, sources)


def test_the_structure_refusal_can_be_turned_off_like_the_other_one(
        monkeypatch, sources):
    """`reject_check=False` builds the file anyway, which is what a
    person inspecting the damage needs."""
    doubled = _clean_document().replace(
        "</w:body>", _table_xml() + _table_xml() + "</w:body>")

    report, _ = _build(monkeypatch, doubled, sources, reject_check=False,
                       accept_check=False)

    assert report.structure_diff, "still reported, just not fatal"
    assert any("tbl:" in d for d in report.structure_diff)


# --- the structure counts, read directly (2026-08-19) -------------------
#
# `structure_counts` and `structure_diff` were added on 2026-08-18 to
# close the S1 where Word's Compare duplicated a moved table and every
# gate passed. They went in through `build` and `validate`, which is
# where they matter, and were never called directly — so the module came
# back at 12.0 % with 7 of its 39 survivors in a two-line function.
#
# Both are public (`__all__`), and a per-paper script is the caller the
# docstring is written for.


def test_a_tag_MISSING_from_a_count_reads_as_zero():
    """`was.get(tag, 0)`. `structure_counts` fills every tag in, but the
    function is public and takes any two mappings — a script that
    counted only the tags it cared about is the ordinary caller, and a
    default of anything but zero turns "this document has no tables"
    into "this document has one"."""
    from docxkit.tracked import structure_diff

    assert structure_diff({"tbl": 1}, {}) == ["tbl: 1 -> 0"]
    assert structure_diff({}, {"tbl": 1}) == ["tbl: 0 -> 1"]
    assert structure_diff({}, {}) == []


def test_the_diff_reads_in_TAG_order_not_dict_order():
    """The order is STRUCTURE_TAGS', so two runs over two documents
    produce lines a person can compare down the column."""
    from docxkit.tracked import STRUCTURE_TAGS, structure_diff

    was = {"drawing": 2, "tbl": 27}
    now = {"drawing": 1, "tbl": 28}

    assert structure_diff(was, now) == ["tbl: 27 -> 28", "drawing: 2 -> 1"]
    assert STRUCTURE_TAGS.index("tbl") < STRUCTURE_TAGS.index("drawing")


def test_counts_that_are_EQUAL_and_large_are_not_a_difference():
    """`!=`, not `is not`. Python caches small integers and creates the
    rest, so two counts of 300 are equal and are not the same object —
    and under `is not` every long manuscript reports a structural change
    that did not happen, which `build` raises on under `reject_check`.
    A paper with 300 table rows is an ordinary paper."""
    from docxkit.tracked import structure_diff

    was = {"tr": len(range(300))}
    now = {"tr": len([0] * 300)}

    assert was["tr"] == now["tr"] and was["tr"] is not now["tr"]
    assert structure_diff(was, now) == []


def test_the_counts_come_from_every_text_bearing_part():
    """A bookmark in a footnote is a bookmark, and a batch that edits
    only the notes must not read as a batch that changed nothing."""
    from docxkit.tracked import structure_counts

    parts = make_parts(
        para(run("body")),
        footnotes=notes("footnotes",
                        '<w:footnote w:id="2"><w:p>'
                        '<w:bookmarkStart w:id="4" w:name="InANote"/>'
                        "<w:r><w:t>note</w:t></w:r></w:p></w:footnote>"))

    assert structure_counts(parts)["bookmarkStart"] == 1


def test_a_row_PROPERTY_is_not_counted_as_a_row():
    """`<w:tr\\b` does not match `<w:trPr` — there is no word boundary
    between two word characters — and a table whose rows all carry
    properties would otherwise count double."""
    from docxkit.tracked import structure_counts

    parts = make_parts(
        "<w:tbl><w:tblPr/><w:tr><w:trPr><w:cantSplit/></w:trPr>"
        "<w:tc><w:tcPr/><w:p/></w:tc></w:tr></w:tbl>")

    counts = structure_counts(parts)
    assert (counts["tbl"], counts["tr"], counts["tc"]) == (1, 1, 1)


# --- what `untracked` prints, and how it matches --------------------------

def test_a_long_document_matches_without_the_junk_heuristic():
    """`autojunk=False`. difflib treats an element appearing in more
    than 1 % of a sequence longer than 200 as junk and refuses to anchor
    on it — and a manuscript is exactly that: two hundred paragraphs of
    which many repeat. With the heuristic on, the ONE paragraph the
    batch really changed is reported along with a stretch of its
    neighbours, and the finding a person is meant to act on is buried in
    a list of paragraphs that are identical on both sides."""
    same = [para(run("The same boilerplate sentence.")) for _ in range(250)]
    baseline = _parts(*same)
    changed = list(same)
    changed[200] = para(run("The one sentence the batch rewrote."))
    batch = _parts(*changed)

    found = untracked(batch, baseline)

    # an insert at 200 and the delete that balances it at the end: two
    # findings, not the eight the limit truncates a whole-tail replace to
    assert len(found) == 2
    assert found[0].index == 200
    assert found[0].batch == "The one sentence the batch rewrote."


def test_the_printed_finding_cuts_each_side_at_seventy_characters():
    """A finding is one line per side in a report a person reads next to
    the document; a paragraph printed whole would be the manuscript."""
    long_line = ("The decomposition is sensitive to the ranking of its "
                 "components, which the appendix sets out in full.")
    baseline = _parts(para(run(long_line)))
    batch = _parts(para(run(long_line.replace("sensitive", "robust"))))

    (found,) = untracked(batch, baseline)

    lines = str(found).splitlines()
    assert lines[0] == ("body ¶1: baseline 'The decomposition is sensitive "
                        "to the ranking of its components, which'")
    assert lines[1].endswith("'The decomposition is robust to the ranking "
                             "of its components, which th'")


def test_a_part_OUTSIDE_word_is_not_read_for_anchors():
    """`startswith("word/") AND endswith(".xml")` — both. Under `or`,
    `[Content_Types].xml` and `docProps/core.xml` join the walk, and a
    bookmark named in a custom XML data store reads as one the document
    carries. The collateral check then compares two different sets."""
    from docxkit.tracked import _anchors

    parts = make_parts(para('<w:bookmarkStart w:id="1" w:name="Real"/>'
                            + run("text") + '<w:bookmarkEnd w:id="1"/>'))
    parts["customXml/item1.xml"] = (
        b'<b:Sources><w:bookmarkStart w:name="NotOurs"/></b:Sources>')

    names, _targets = _anchors(parts)

    assert names == {"Real"}

# --- what the build SAYS when Word refuses ------------------------------
#
# Every COM call in the math pass is wrapped, and each one appends to
# `notes` — which `build` prints as "WARNING:" and puts on the report.
# None of those arms had a test: a Word that refuses one equation would
# have been silent, and the pass would have reported a clean resolve.


class _Refuses:
    """A COM object that raises on the one thing it is asked."""

    def __init__(self, what: str) -> None:
        self._what = what

    @property
    def Count(self):
        raise RuntimeError(f"Call was rejected by callee ({self._what})")


def test_a_document_whose_OMaths_cannot_be_read_says_so():
    """`doc.OMaths.Count` is the first COM call of the math pass, and
    Word refuses it on a document it is still repairing. The pass
    answers "nothing resolved" — which is right — and the reason has to
    reach the report, or the build says it resolved no math on a
    document full of it."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    notes: list[str] = []
    doc = type("D", (), {"OMaths": _Refuses("OMaths")})()

    assert _accept_math_via_equations(doc, notes) == T.MathOutcome(0)
    assert any("could not read doc.OMaths" in n for n in notes), notes


def test_a_revision_that_cannot_be_PLACED_is_named_and_stepped_over():
    """The offsets decide whether a revision is inside the equation or
    merely runs through it. When Word will not give them, the revision
    cannot be judged — so it is left tracked, named in the notes, and
    the walk carries on to the rest of the equation."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    class _NoSpan:
        accepted = False

        @property
        def Range(self):
            raise RuntimeError("Call was rejected by callee (Range)")

        def Accept(self):                            # pragma: no cover
            raise AssertionError("a revision that could not be placed "
                                 "must not be accepted")

    good = _Rev("of the equation", span=(120, 150))
    # the revisions are walked BACKWARDS, so the unplaceable one is
    # LAST in the list and FIRST in the walk — placed the other way
    # round `continue` and `break` do the same thing here
    doc = type("D", (), {
        "OMaths": _Count([_OMath(revisions=[good, _NoSpan()],
                                 span=(100, 200))])})()
    notes: list[str] = []

    out = _accept_math_via_equations(doc, notes)

    assert good.accepted, "the revision beside it is still resolved"
    assert out == T.MathOutcome(1)
    assert any("could not be placed" in n for n in notes), notes


def test_a_revision_word_will_not_ACCEPT_is_named_not_counted():
    """`Accept()` is where Word refuses a compare result it cannot
    serialise. The count must not include it — a build that reports
    "resolved 3" and resolved 2 sends the paper on with tracked math in
    it, which is the save hang this whole pass exists to avoid."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    class _Stubborn(_Rev):
        def Accept(self):
            raise RuntimeError("Word refused")

    doc = type("D", (), {
        "OMaths": _Count([_OMath(revisions=[_Stubborn(span=(120, 150))],
                                 span=(100, 200))])})()
    notes: list[str] = []

    assert _accept_math_via_equations(doc, notes) == T.MathOutcome(0)
    assert any("not accepted" in n for n in notes), notes


def test_a_revision_that_cannot_be_INSPECTED_is_named_by_number():
    """The other walk, the one that selects by what a revision
    CONTAINS. `rev.Range.OMaths` is a COM call per revision, and the
    number in the note is how a person finds the one Word choked on."""
    from docxkit import tracked as T

    class _Opaque:
        @property
        def Range(self):
            raise RuntimeError("Call was rejected by callee")

    doc = type("D", (), {
        "Revisions": _Count([_Opaque()]),
        "Comments": type("C", (), {"Count": 0, "Add": lambda *a: None})()})()
    notes: list[str] = []

    T._comment_and_accept_math_revisions(doc, lambda ctx: "x", None, notes)

    assert any("revision 1: could not be inspected" in n
               for n in notes), notes


def test_a_scaffold_that_cannot_be_SEEDED_says_what_it_costs():
    """The XML pass CLONES a Word-made comment, so a build that
    annotates and could not seed one fails later with ScaffoldMissing, a
    long way from here. The note is what connects the two."""
    from docxkit import tracked as T

    doc = type("D", (), {"Revisions": _Refuses("Revisions")})()
    notes: list[str] = []

    assert T._seed_scaffold(doc, lambda ctx: "x", None, notes) == 0
    assert any("no comment scaffold could be seeded" in n
               for n in notes), notes


def test_the_report_names_the_revisions_that_merely_OVERLAP_an_equation():
    """`math_kept` on the report, and the line `format()` prints for it.
    Accepting one of those applies its whole span — the LI7 collateral —
    so a build that keeps some has to say how many, or the number that
    matters is the one nobody sees."""
    report = tracked.BuildReport()
    report.math_resolved, report.math_kept = 4, 2

    out = report.format()

    assert "2 revision(s) overlap an equation" in out, out

def test_the_report_names_what_was_CARRIED_back_across_the_compare():
    """Compare drops the customXml data store on every rebuild and
    `build` puts it back. What went back is a change to the deliverable
    that no gate reports, so `format()` is the only place a person can
    read it."""
    report = tracked.BuildReport()
    report.carried = ["customXml/item1.xml"]
    report.carried_properties = ["title"]

    out = report.format()

    assert "carried back across the Compare: customXml/item1.xml" in out
    assert "properties carried back into core.xml" in out and "title" in out


def test_a_math_revision_word_will_not_accept_says_the_build_may_not_SAVE():
    """The other walk's `Accept()`, and the note that names the
    consequence rather than the call: Word cannot serialise a compare
    result containing tracked math, so a build that could not resolve
    one may hang on save. A person reading "resolved 3" learns nothing
    about the one that stayed."""
    from docxkit import tracked as T

    class _Stubborn:
        def __init__(self):
            self.Range = _MathRange("has math", omaths=1)

        def Accept(self):
            raise RuntimeError("Word refused")

    doc = type("D", (), {
        "Revisions": _Count([_Stubborn()]),
        "Comments": type("C", (), {"Count": 0,
                                   "Add": lambda *a: None})()})()
    notes: list[str] = []

    T._comment_and_accept_math_revisions(doc, lambda ctx: "x", None, notes)

    assert any("may fail to save" in n for n in notes), notes


def test_the_build_SAYS_what_it_resolved_and_what_it_kept(monkeypatch,
                                                          sources):
    """The two numbers the math pass produces, on the progress line a
    person watches. `math_kept` is the LI7 number — revisions that
    merely overlap an equation and stay tracked — and a build that
    resolved some and kept some has to say both, or the ones that
    stayed are invisible until the save hangs."""
    said: list[str] = []
    monkeypatch.setattr(tracked, "_resolve_math",
                        lambda *a, **kw: tracked.MathOutcome(3, 2))
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)

    report = tracked.build(sources[0], sources[1], sources[2],
                           verify_in_word=False, progress=said.append)

    assert (report.math_resolved, report.math_kept) == (3, 2)
    assert any("resolved 3 math revisions" in line for line in said), said
    assert any("2 revision(s) merely OVERLAP" in line for line in said), said


def test_the_build_says_which_math_GLYPH_it_put_back(monkeypatch, sources):
    """Word flattens U+2212 to an ASCII hyphen while deriving a redline
    — measured on AFI: 2 in the baseline, 0 in the build, the 57 in the
    prose untouched. `restore_math_glyphs` puts back only what a source
    really spells that way, and what it did is on the progress line,
    because nothing else in the build would ever mention it."""
    said: list[str] = []
    monkeypatch.setattr(tracked._hygiene, "restore_math_glyphs",
                        lambda *a: ["equation 3: U+2212 restored"])
    fake = _FakeWordModule(_clean_document())
    monkeypatch.setattr(tracked, "_word", fake)

    report = tracked.build(sources[0], sources[1], sources[2],
                           verify_in_word=False, progress=said.append)

    assert report.restored_glyphs == ["equation 3: U+2212 restored"]
    assert any("restored math glyph — equation 3" in line
               for line in said), said

def test_an_unreachable_equation_does_not_end_the_math_pass():
    """`continue`, not `break`. `doc.OMaths(i).Range` is a COM call per
    equation and Word refuses one on a document it is repairing; the
    rest of the paper still has math in it. Under `break` the first
    refusal ends the pass, and the revisions after it stay tracked —
    which is the save hang this pass exists to avoid, reported as a
    clean resolve."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    class _Unreachable:
        @property
        def Range(self):
            raise RuntimeError("Call was rejected by callee")

    good = _Rev("of the equation", span=(120, 150))
    # OMaths is walked BACKWARDS, so the unreachable one is second in
    # the list and first in the walk
    doc = type("D", (), {"OMaths": _Count([
        _OMath(revisions=[good], span=(100, 200)), _Unreachable()])})()
    notes: list[str] = []

    out = _accept_math_via_equations(doc, notes)

    assert good.accepted, "the equation before it is still resolved"
    assert out == T.MathOutcome(1)
    assert any("unreachable" in n for n in notes), notes


def test_an_unclassified_math_revision_still_gets_the_GENERIC_comment():
    """`comment or generic or _comments.GENERIC`, and the last term is
    what makes the chain safe: the XML pass CLONES a Word-made comment,
    so this one exists to be cloned. `and` in its place hands Word None
    and the comment is never made — the build then fails much later
    with ScaffoldMissing."""
    from docxkit import tracked as T

    added: list[str] = []
    doc = type("D", (), {
        "Comments": type("C", (), {
            "Add": lambda _s, rng, text: added.append(text), "Count": 0})(),
        "Paragraphs": _Count([])})()
    rev = _Rev("some math")

    T._comment_revision(doc, rev, lambda ctx: None, None, [])

    assert added == [T._comments.GENERIC], added


def test_a_comment_word_refuses_names_THIRTY_characters_of_the_revision():
    """The note is how a person finds the revision Word would not
    comment, and a revision's text is a sentence: thirty characters is
    the quote, and uncut every refusal prints a paragraph."""
    from docxkit import tracked as T

    long_text = "The sentence this revision rewrites, at length."
    assert len(long_text) > 31

    class _Refusing:
        Count = 0

        def Add(self, rng, text):
            raise RuntimeError("Word refused")

    doc = type("D", (), {"Comments": _Refusing(),
                         "Paragraphs": _Count([])})()
    notes: list[str] = []

    T._comment_revision(doc, _Rev(long_text), lambda ctx: "x", None, notes)

    assert any(f'"{long_text[:30]}"' in n for n in notes), notes
    assert not any(long_text[:31] in n for n in notes), notes


def test_a_build_verifies_in_word_and_closes_the_compare_UNSAVED(
        monkeypatch, sources):
    """Two defaults nothing named. `verify_in_word=True` reopens the
    result and fails the build if Word had to repair it — passed
    explicitly by every test here, so the default was free — and the
    compare result is closed with `SaveChanges=0`, because 1 is
    wdSaveChanges and Word would write the scratch redline somewhere."""
    closes: list[dict[str, int]] = []
    checked: list[Path] = []

    class _Recording(_FakeDoc):
        def Close(self, SaveChanges: int = 0) -> None:
            closes.append({"SaveChanges": SaveChanges})
            self.closed = True

    class _RecordingWord(_FakeWordModule):
        def compare_documents(self, word, orig, rev, **kw):
            return _Recording()

    monkeypatch.setattr(tracked, "_word",
                        _RecordingWord(_clean_document()))

    def fake_verify(path):
        checked.append(Path(path))
        return {"word": {"comments": 0, "revisions": 0},
                "comments_match": True}

    monkeypatch.setattr(tracked, "verify", fake_verify)

    tracked.build(sources[0], sources[1], sources[2])

    assert checked, "the default reopens the result in Word"
    assert closes == [{"SaveChanges": 0}], closes


# --- what is left in tracked.py, and why ---------------------------------
#
# Four survivors after this round, each argued rather than tested:
#
#   `if tag == "equal"` -> `is`. The tags come from difflib as its own
#   string literals; both sides are identifier-like constants, so
#   CPython hands out one object and the two spellings cannot disagree.
#   A test would pin the interning, not the walk.
#
#   `if len(out) >= limit` -> `==`, and -> `is`. `out` grows one finding
#   at a time and the check runs after each, so it meets the limit
#   exactly and never passes it; `is` adds the small-int cache, and a
#   caller asking for more than 256 findings has already given up on
#   reading them.
#
#   `if report.body_revisions != report.revisions` -> `<`. Word's count
#   walks the main story and the package's counts every text-bearing
#   part, so the body count is a subset by construction: it can be
#   lower, never higher. The identity spelling of the same comparison
#   IS tested, above the small-int cache, because that one differs on
#   any batch of 257 revisions or more.


# --- the parts the gates SIMULATE, and the parts they used to READ -------
#
# `_simulate` accepts and rejects all three text-bearing parts — body,
# footnotes AND endnotes — and the walk that reads the result read two
# of them. So an accept-all defect was a finding in a footnote and
# invisible in an endnote, which is where several journals put the whole
# apparatus. Nothing else covers it: the tag counts do not move for a
# retyped sentence, `compare` runs on the deliverable rather than inside
# the build, and the reject gate's own text check stops at the same two
# parts. `revision.TEXT_PARTS` carries the same warning beside its own
# list — a count that reads only the body calls such a file truth.


def _endnote_parts(text: str, *, tracked_as: str | None = None
                   ) -> dict[str, bytes]:
    """A one-paragraph body and one endnote holding `text`."""
    inner = para(run(text)) if tracked_as is None else para(
        dele(tracked_as) + ins(text))
    return make_parts(
        para(run("The body says the same in every version of this.")),
        extra={"word/endnotes.xml": notes("endnotes",
                                          f'<w:endnote w:id="2">{inner}'
                                          "</w:endnote>")})


def test_an_untracked_change_in_an_ENDNOTE_is_a_finding():
    """The reject side: a sentence the batch retyped, in a part the
    walk did not open."""
    baseline = _endnote_parts("The elasticity is 0.35.")
    batch = _endnote_parts("The elasticity is 0.37.")

    (found,) = untracked(batch, baseline)

    assert found.part == "endnotes"
    assert found.baseline == "The elasticity is 0.35."
    assert found.batch == "The elasticity is 0.37."
    assert str(found).startswith("endnotes ¶1:")


def test_a_TRACKED_change_in_an_endnote_is_still_not_a_finding():
    """The other half, and the one that says the widened walk did not
    just start crying wolf: rejecting the batch restores the baseline
    endnote, so there is nothing to report."""
    baseline = _endnote_parts("The elasticity is 0.35.")
    batch = _endnote_parts("The elasticity is 0.37.",
                           tracked_as="The elasticity is 0.35.")

    assert untracked(batch, baseline) == []


def test_an_endnote_accept_all_does_not_reproduce_is_a_finding():
    """The accept side, which is the one that ships: the reader opens
    the accepted document, and until now nothing compared its endnotes
    against the clean copy at all."""
    revised = _endnote_parts("The elasticity is 0.37.")
    # accepting the batch leaves a mangled sentence behind — the shape
    # `hygiene.restore_math_glyphs` and `compare_collateral` both exist
    # for, in the one part neither gate was reading
    batch = _endnote_parts("The elasticity is 0.7.",
                           tracked_as="The elasticity is 0.35.")

    (missed,) = unaccepted(batch, revised)

    assert missed.part == "endnotes"
    assert missed.intended == "The elasticity is 0.37."
    assert missed.accepted == "The elasticity is 0.7."


def test_every_part_the_gates_SIMULATE_has_a_name_to_report_it_under():
    """`_PART_LABELS` is keyed by part name rather than zipped against
    `TEXT_PARTS`, so a fourth text-bearing part cannot arrive and be
    reported under its neighbour's label — it fails here instead."""
    from docxkit._xml import TEXT_PARTS
    from docxkit.tracked import _PART_LABELS

    assert set(_PART_LABELS) == set(TEXT_PARTS)
    assert len(set(_PART_LABELS.values())) == len(TEXT_PARTS)


# --- what ACCEPTING loses that neither other check can see ---------------
#
# BACKLOG S1, AFI 2026-08-19: a batch that moved four captions passed the
# text comparison and the collateral one while all four caption
# hyperlinks had been stripped. Each of those two is blind here by
# construction — `compare_collateral` looks at the redline AS BUILT,
# where the link is still present inside a deletion, and `unaccepted`
# compares paragraph TEXT, which a hyperlink does not carry.

_WHEN = 'w:id="7" w:author="R" w:date="2026-01-01T00:00:00Z"'


def _link_rebuilt_as_plain_text() -> tuple[dict[str, bytes],
                                           dict[str, bytes]]:
    """(clean copy, redline) for the shape Compare produces when it
    rebuilds a hyperlink as prose: the link deleted, the same words
    inserted beside it."""
    link = ('<w:hyperlink w:anchor="Table1"><w:r><w:delText>Table 1'
            "</w:delText></w:r></w:hyperlink>")
    redline = make_parts(
        f"<w:p><w:del {_WHEN}>{link}</w:del>"
        f'<w:ins {_WHEN}><w:r><w:t>Table 1</w:t></w:r></w:ins>'
        "<w:r><w:t> shows the gradient.</w:t></w:r></w:p>")
    revised = make_parts(
        '<w:p><w:hyperlink w:anchor="Table1"><w:r><w:t>Table 1</w:t></w:r>'
        "</w:hyperlink><w:r><w:t> shows the gradient.</w:t></w:r></w:p>")
    return revised, redline


def test_a_link_the_ACCEPT_loses_is_a_finding():
    """The accepted view is the deliverable — the document the author
    reads — and this is the only check that looks at its anchors."""
    from docxkit.tracked import _accept, _simulate, accepted_losses

    revised, redline = _link_rebuilt_as_plain_text()

    found = accepted_losses(revised, _simulate(redline, _accept))

    assert found == ["link LOST on accept: -> Table1"]


def test_the_other_two_checks_are_BLIND_to_it():
    """Stated as a test because it is the whole reason the third one
    exists: the words survive the accept, so the text comparison is
    silent, and the link is present in the redline as built, so the
    collateral comparison is too."""
    from docxkit.tracked import compare_collateral, unaccepted

    revised, redline = _link_rebuilt_as_plain_text()

    assert unaccepted(redline, revised) == []
    assert compare_collateral(revised, redline) == []


def test_a_BOOKMARK_inside_a_deletion_survives_the_accept():
    """The other carrier, and it needs no finding: `revisions` LIFTS a
    bookmark out of an element it is about to remove, which is the fix
    for "a moved paragraph carrying bookmarks loses them" two entries
    up in the same backlog.

    Worth a test beside the link one because it says why the link is
    the case that needed a check: nothing lifts a `w:hyperlink`, and
    nothing can — the element carries the words, so lifting it would
    leave the deleted text on the page."""
    from docxkit.tracked import _accept, _simulate, accepted_losses

    mark = ('<w:bookmarkStart w:id="3" w:name="Table1"/>'
            "<w:r><w:delText>Table 1</w:delText></w:r>"
            '<w:bookmarkEnd w:id="3"/>')
    redline = make_parts(f"<w:p><w:del {_WHEN}>{mark}</w:del>"
                         f'<w:ins {_WHEN}><w:r><w:t>Table 1</w:t></w:r>'
                         "</w:ins></w:p>")
    revised = make_parts('<w:p><w:bookmarkStart w:id="3" w:name="Table1"/>'
                         "<w:r><w:t>Table 1</w:t></w:r>"
                         '<w:bookmarkEnd w:id="3"/></w:p>')

    accepted = _simulate(redline, _accept)

    assert accepted_losses(revised, accepted) == []
    assert b'w:name="Table1"' in accepted["word/document.xml"]


def test_a_link_RE_REPRESENTED_in_the_other_form_is_not_a_loss():
    """Word's Compare rewrites a field-form hyperlink as an element,
    and that is harmless — the backlog says so in its own words. The
    anchors are compared by NAME through `internal_links`, which reads
    both forms, so the count of `w:hyperlink` elements moving is not
    what this asks."""
    from docxkit.tracked import accepted_losses

    field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             "<w:r><w:instrText> HYPERLINK "
             + chr(92) + 'l "Table1" </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             "<w:r><w:t>Table 1</w:t></w:r>"
             '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    revised = make_parts(f"<w:p>{field}</w:p>")
    accepted = make_parts('<w:p><w:hyperlink w:anchor="Table1">'
                          "<w:r><w:t>Table 1</w:t></w:r></w:hyperlink></w:p>")

    assert accepted_losses(revised, accepted) == []


def test_a_batch_that_loses_nothing_reports_nothing():
    from docxkit.tracked import accepted_losses

    same = make_parts('<w:p><w:hyperlink w:anchor="Table1">'
                      "<w:r><w:t>Table 1</w:t></w:r></w:hyperlink></w:p>")

    assert accepted_losses(same, dict(same)) == []


# --- the equation Compare diffed INSIDE ---------------------------------


def _mangled_equation() -> tuple[dict[str, bytes], dict[str, bytes]]:
    """(clean copy, redline) for what Compare does to an inline field.

    It matches the common prefix `-0.` of `-0.20` and `-0.398` and
    emits the rest as an insertion BESIDE the old digits — so accepting
    reads `-0.20398` and rejecting reads `-0.20`, which is right. AFI
    R3/T3.2, 2026-08-19."""
    redline = make_parts(
        "<w:p><m:oMath><m:r><m:t>-0.</m:t></m:r><m:r><m:t>20</m:t></m:r>"
        f'<w:ins {_WHEN}><m:r><m:t>398</m:t></m:r></w:ins></m:oMath>'
        "<w:r><w:t> in every year.</w:t></w:r></w:p>")
    revised = make_parts(
        "<w:p><m:oMath><m:r><m:t>-0.398</m:t></m:r></m:oMath>"
        "<w:r><w:t> in every year.</w:t></w:r></w:p>")
    return revised, redline


def test_an_equation_the_accept_MANGLES_is_a_finding():
    """The number in the paper. Accepting gives `-0.20398` — the old
    digits with the new ones inserted after them — and that is the
    document the author reads."""
    from docxkit.tracked import _accept, _simulate, accepted_math

    revised, redline = _mangled_equation()

    found = accepted_math(revised, _simulate(redline, _accept))

    # The line also names the first character that differs, as of
    # 24.08: the two quoted forms are near-identical by construction —
    # that is what makes it a glyph problem — so a reader was being
    # asked to diff them by eye. Here the difference is a digit rather
    # than a lookalike, which is the case where the addition says least
    # and still costs nothing.
    (line,) = found

    assert line.startswith("equation 1: '-0.398' in the clean copy, "
                           "'-0.20398' accepted")
    assert "differs at char" in line, line


def test_every_OTHER_check_passes_that_document():
    """Which is why the number reached the paper. The reject view is
    CORRECT — it restores the original `-0.20` — so the reject gate is
    right to pass; the counts do not move; the equation renders; and
    `unaccepted` compares `w:t`, which an equation's characters are
    not."""
    from docxkit.tracked import (
        _accept,
        _reject,
        _simulate,
        accepted_losses,
        structure_counts,
        structure_diff,
        unaccepted,
    )

    revised, redline = _mangled_equation()
    accepted = _simulate(redline, _accept)

    assert unaccepted(redline, revised) == []
    assert accepted_losses(revised, accepted) == []
    assert structure_diff(structure_counts(revised),
                          structure_counts(accepted)) == []
    from docxkit.tracked import _math_texts
    assert _math_texts(_simulate(redline, _reject)) == ["-0.20"], (
        "the ORIGINAL number, which is what makes the reject gate right "
        "to pass")


def test_an_equation_the_accept_reproduces_is_not_a_finding():
    """A math edit applied to the built batch — the trade a paper makes
    for a redline it can hand back — comes out equal on both sides."""
    from docxkit.tracked import accepted_math

    same = make_parts("<w:p><m:oMath><m:r><m:t>-0.398</m:t></m:r>"
                      "</m:oMath></w:p>")

    assert accepted_math(same, dict(same)) == []


def test_an_equation_the_accept_LOSES_is_reported_as_a_count():
    """Position-by-position comparison needs the two lists to be the
    same length, and when they are not the count is the finding — an
    equation gone is not an equation changed."""
    from docxkit.tracked import accepted_math

    revised = make_parts("<w:p><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"
                         "<m:oMath><m:r><m:t>y</m:t></m:r></m:oMath></w:p>")
    accepted = make_parts("<w:p><m:oMath><m:r><m:t>x</m:t></m:r>"
                          "</m:oMath></w:p>")

    (found,) = accepted_math(revised, accepted)

    assert found == ("the clean copy has 2 equation(s) and accepting the "
                     "redline gives 1")


def test_the_gap_counts_the_grouped_revisions_by_SUBTRACTION():
    """Word's number and the package's differ by however many elements
    it folded into one. Anything that happens to agree on small numbers
    — and several bitwise spellings do — is a different sentence on the
    next batch."""
    parts = make_parts(
        para(ins(run("one"))) + para(ins(run("two")))
        + para(ins(run("three"))) + para(dele(run("go"))))

    said = tracked._revision_gap(parts, body=2, total=4)

    assert "the remaining 2 are in word/document.xml too" in said, said


def test_accepted_math_reports_an_equation_the_accept_ADDED():
    """Compare duplicates as readily as it drops. A count test that only
    looks one way calls the extra equation no difference at all."""
    eq = "<w:p><m:oMath><m:r><m:t>%s</m:t></m:r></m:oMath></w:p>"
    was = make_parts(eq % "x")
    now = make_parts(eq % "x" + eq % "y")

    said = tracked.accepted_math(was, now)

    assert said and "1 equation(s)" in said[0] and "gives 2" in said[0]


def test_accepted_losses_does_not_report_an_anchor_the_accept_GAINED():
    """A link the accepted view has and the clean copy does not is not
    a LOSS — Word re-representing a field as an element adds targets
    this way, and reporting them refuses a build for nothing."""
    linked = ('<w:hyperlink w:anchor="Extra"><w:r><w:t>x</w:t>'
              "</w:r></w:hyperlink>")
    was = make_parts(para(run("text")))
    now = make_parts(para(run("text"), linked))

    assert tracked.accepted_losses(was, now) == []


def test_the_ANCHOR_refusal_carries_the_paragraphs_when_there_are_any():
    """An anchor does not go missing on its own. On Aging_Well a scored
    move truncated a paragraph in the accepted view — a clause, a link
    and the sentence after it — and the build refused with `link LOST on
    accept: -> Ravallion2011`, the smallest visible symptom of it. The
    round was spent on the link. The refusal now hands over the
    paragraphs and names the switch that fixed that case."""
    report = tracked.BuildReport()
    report.accepted_losses = ["link LOST on accept: -> Ravallion2011"]
    report.unaccepted = [tracked.Unaccepted(
        "body", 5, "The floor itself is set weakly relatively to income.",
        "The floor itself is set weakly relatively")]

    with pytest.raises(PackageError) as caught:
        tracked._refuse_accept_side(report, "v12.docx")

    said = str(caught.value)
    assert "1 paragraph(s) also differ" in said
    assert "set weakly relatively to income" in said, "quote BOTH sides"
    assert "--no-moves" in said


def test_the_anchor_refusal_is_silent_about_paragraphs_when_there_are_none():
    """The common case is an anchor loss alone, and a sentence about
    paragraphs that do not differ sends the reader looking for them."""
    report = tracked.BuildReport()
    report.accepted_losses = ["bookmark LOST on accept: Table1"]

    with pytest.raises(PackageError) as caught:
        tracked._refuse_accept_side(report, "v12.docx")

    assert "also differ" not in str(caught.value)


def test_the_MATH_ONLY_refusal_speaks_only_about_the_maths():
    """It runs after the glyph restore, when the other two have already
    been asked and answered. Letting it re-raise the anchor loss reports
    the same finding twice and blames the equation pass for it."""
    report = tracked.BuildReport()
    report.accepted_losses = ["link LOST on accept: -> Table1"]
    report.accepted_math = ["equation 1: '-0.20' in the clean copy"]

    with pytest.raises(PackageError, match="EQUATIONS"):
        tracked._refuse_accept_side(report, "v12.docx", math_only=True)


# tracked's other survivors from the 2026-08-21 round, argued:
#
# `if grouped > 0` -> `!= 0` in `_revision_gap`. Word's count walks the
# main story and the package's counts every element in it, so the body
# figure is a subset by construction — the same argument the note above
# makes for the comparison that produced it, one line further on.
#
# `zip(was, now, strict=True)` -> `strict=False` in `accepted_math`: the
# length check three lines above has already returned when they differ,
# so there is no ragged pair left for either spelling to meet.


# --- Word MERGING a changed footnote (BACKLOG S2, 2026-08-23) ------------
#
# A footnote whose text changed comes back as a wholly-deleted copy plus
# a wholly-inserted one — right — with the SAME character-merged string
# written into both. On LI7 `(4)` and `(A1.1)` both came back `(4A1.1)`,
# a string in neither document, so accept-all and reject-all each
# produce text that exists nowhere.
#
# The entry filed it as undetectable. It is detected twice, and these
# pin that: a person cannot see it (Review > Next walks the body, and
# footnote balloons are hidden under Simple Markup), so the only thing
# standing between the merge and the deliverable is these two gates.

_FN_WAS = "The decomposition in (4) weights each component."
_FN_NOW = "The decomposition in (A1.1) weights each component."
#: The divergent fragment in a run of its own, which is the shape that
#: makes the damage machine-detectable at all.
_FN_PIECES = ("The decomposition in (", "4", "A1.1) weights each component.")
_STAMP = 'w:author="R" w:date="2026-08-23T00:00:00Z"'


def _one_run(tag: str) -> str:
    return "<w:r>" + "".join(
        f"<w:{tag}>{t}</w:{tag}>" for t in _FN_PIECES) + "</w:r>"


def _run_each(tag: str) -> str:
    return "".join(f"<w:r><w:{tag}>{t}</w:{tag}></w:r>" for t in _FN_PIECES)


def _merged_note(shape, one_para: bool) -> str:
    gone = f'<w:del w:id="90" {_STAMP}>{shape("delText")}</w:del>'
    added = f'<w:ins w:id="91" {_STAMP}>{shape("t")}</w:ins>'
    body = (f"<w:p>{gone}{added}</w:p>" if one_para
            else f"<w:p>{gone}</w:p><w:p>{added}</w:p>")
    return f'<w:footnote w:id="2">{body}</w:footnote>'


def _note_parts(inner: str) -> dict[str, bytes]:
    return make_parts(para(run("The paper as it stands.")),
                      footnotes=notes("footnotes", inner))


def _plain_note(text: str) -> str:
    return f'<w:footnote w:id="2">{para(run(text))}</w:footnote>'


@pytest.mark.parametrize("shape", [_one_run, _run_each],
                         ids=["one-run", "run-per-fragment"])
@pytest.mark.parametrize("one_para", [True, False],
                         ids=["one-paragraph", "two-paragraphs"])
def test_a_MERGED_footnote_is_caught_on_both_sides(shape, one_para):
    """Whichever way Compare spells it. The fragments arrive as one run
    with three children or as a run each, and the two copies land in one
    paragraph or in two — four spellings, and a gate that caught only
    the one that was reported would be worth very little."""
    redline = _note_parts(_merged_note(shape, one_para))

    rejected = untracked(redline, _note_parts(_plain_note(_FN_WAS)))
    accepted = unaccepted(redline, _note_parts(_plain_note(_FN_NOW)))

    assert rejected, "reject-all must not reproduce the original silently"
    assert accepted, "accept-all must not reproduce the clean copy silently"
    assert any("4A1.1" in str(u) for u in rejected), rejected
    assert any("4A1.1" in str(u) for u in accepted), accepted


def test_the_merged_footnote_gate_names_the_PART_not_just_the_paragraph():
    """`(4A1.1)` is a string in neither document, and a reader told only
    "paragraph 1 differs" would look in the body, where nothing is
    wrong. The footnote is the one place a person cannot check by eye,
    so the note has to say where to look."""
    redline = _note_parts(_merged_note(_one_run, True))

    (found,) = untracked(redline, _note_parts(_plain_note(_FN_WAS)))

    assert "footnote" in str(found).lower(), found


def test_the_accept_refusal_does_not_name_a_flag_the_CLI_LACKS():
    """It said "Pass accept_check=False", which is a Python keyword
    argument. The CLI's flags are `--allow-math-resolve`,
    `--allow-stale-baseline`, `--keep-math`, `--allow-pending-baseline`
    and `--force`, none of which is it — so a CLI reader had been told
    to do something the CLI does not offer, and the honest workaround
    (a throwaway script importing `docxkit.revision`) is the thing the
    CLI exists to avoid."""
    said = tracked._ACCEPT_ESCAPE

    assert "tracked.build(" in said, "name where the switch really lives"
    assert "from Python" in said
    assert "the CLI has no flag for this" in said
    assert "usually right" in said, (
        "the refusal was RIGHT on Life_Expectancy — two unterminated "
        "bookmarks — and the repair was the manuscript, not the switch")


def test_every_accept_side_refusal_carries_the_same_escape():
    """One sentence, not two that can drift. Both refusals used to spell
    it out separately and both were wrong the same way.

    Counted against the RAISES rather than pinned at a number: it was
    pinned, and a third refusal — the orphan note — then failed this
    test for carrying the escape correctly, which is the opposite of
    what it is for. The math refusal is the one exception and names
    itself, because its repair is a math edit rather than a switch."""
    import re as _re

    src = Path(tracked.__file__).read_text(encoding="utf-8")
    body = src.split("def _refuse_accept_side")[1].split("\ndef ")[0]

    assert "accept_check=False to build" not in body
    assert body.count("_ACCEPT_ESCAPE") == body.count("raise PackageError") - 1
    assert not _re.search(r"Pass accept_check", body)
