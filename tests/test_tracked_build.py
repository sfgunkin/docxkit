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
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    NS,
    clean_document,
    comment,
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
    def session(self, **kw):
        self.session_kwargs = kw
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


def _baseline(path: Path, text: str) -> None:
    """Rewrite `path` to say `text` — what the redline must reject BACK to.

    The fake's compare output is not derived from the fixture inputs, so
    a test whose body is not `clean_document()` has to say what its
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
    `clean_document()` has to say what its REVISED input was. `build`
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


def test_a_word_deadline_reaches_the_Compare_session_and_names_it(
        monkeypatch, sources):
    """`word_deadline` is handed to `_word.session` as the ceiling on
    the Compare, with what it is doing in the message — and ONLY when
    one is asked for, so a caller (and every fake in this file) that
    knows no `deadline` keyword is untouched."""
    _report, fake = _build(monkeypatch, clean_document(), sources,
                           word_deadline=30)
    original, revised, _out = sources

    assert fake.session_kwargs == {
        "deadline": 30,
        "doing": f"comparing {Path(revised).name} against "
                 f"{Path(original).name}"}

    _report, bare = _build(monkeypatch, clean_document(), sources)
    assert bare.session_kwargs == {}


def test_build_writes_the_deliverable_and_stamps_it(monkeypatch, sources):
    report, fake = _build(monkeypatch, clean_document(), sources)
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
    _, fake = _build(monkeypatch, clean_document(), sources)
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
        z.writestr("word/document.xml", clean_document())
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
    fake = _FakeWordModule(clean_document())
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
        z.writestr("word/document.xml", clean_document())
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

    monkeypatch.setattr(tracked, "_word", _FakeWordModule(clean_document()))
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
        z.writestr("word/document.xml", clean_document())
        z.writestr("customXml/item1.xml",
                   '<b:Sources xmlns:b="http://schemas.openxmlformats.org'
                   '/officeDocument/2006/bibliography"/>')
    fake = _FakeWordModule(clean_document())
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
    fake = _FakeWordModule(clean_document())
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
    _, fake = _build(monkeypatch, clean_document(), sources,
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
    _build(monkeypatch, clean_document(), sources)
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
        _build(monkeypatch, clean_document(), sources)
    assert out.read_bytes() == b"AUTHOR REVIEWED THIS"


# ------------------------------------------------------------- reporting --


def test_what_compare_dropped_is_SAID_not_just_recorded(monkeypatch,
                                                        sources):
    """"Suppressing silently let a half-finished build report
    success-shaped numbers" is this module's own comment, and the loop
    that says so could be deleted with nothing going red. The report
    field was asserted; the telling was not."""
    said: list[str] = []
    fake = _FakeWordModule(clean_document())
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
    fake = _FakeWordModule(clean_document())
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
        z.writestr("word/document.xml", clean_document())
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="http://schemas.'
                   'openxmlformats.org/package/2006/metadata/core-'
                   'properties" xmlns:dc="http://purl.org/dc/elements/'
                   '1.1/"><dc:title>Loneliness Risk Index</dc:title>'
                   "</cp:coreProperties>")

    said: list[str] = []
    report, _ = _build(monkeypatch, clean_document(), sources,
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
    report, _ = _build(monkeypatch, clean_document(), sources)
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
    fake = _FakeWordModule(clean_document())
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
    _build(monkeypatch, clean_document(), sources, resolve_math=False)
    assert seeded == [None], "seeding is the classifier's business to refuse"


def test_build_report_formats_its_phases(monkeypatch, sources):
    report, _ = _build(monkeypatch, clean_document(), sources)
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
    parts = {"word/document.xml": clean_document().encode("utf-8")}
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
    fake = _FakeWordModule(clean_document())
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
    fake = _FakeWordModule(clean_document())
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
    report, _ = _build(monkeypatch, clean_document(), sources)
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
    report, _ = _build(monkeypatch, clean_document(), sources)
    assert report.dropped == []
    assert "dropped" not in report.format()


# --- the survivors of the first whole `tracked` sweep (2026-09-17) -------
#
# Five, and none of them needed Word: the count note's comparison, the
# one refusal that runs after the glyph restore, two progress lines the
# report fields beside them hid, and the tidy-up in `build`'s `finally`.
# The first also exposed a defect, fixed in the section after it.


def test_Word_counting_MORE_than_the_package_is_said_aloud_too(
        monkeypatch, sources):
    """The note is for a difference either way; `<` in place of `!=`
    kept it only for the footnote direction, which is the one every
    earlier fixture here built (a compare result reporting 0).

    Word's figure being the HIGHER one is not hypothetical: until
    2026-09-17 it was read before the math pass, and every accepted
    equation revision raised it above the package (the section below).
    Read of one document state it is usually the lower, but Word's
    collection is its own idea of one revision and the package's is
    seven element kinds, and nothing makes the first a subset of the
    second."""
    said: list[str] = []
    counted = _FakeDoc()
    counted.Revisions = type("R", (), {"Count": 2})()
    fake = _FakeWordModule(clean_document())
    fake.compare_documents = lambda word, o, r, **kw: counted  # type: ignore
    monkeypatch.setattr(tracked, "_word", fake)
    original, revised, out = sources

    report = tracked.build(original, revised, out, verify_in_word=False,
                           progress=said.append)

    assert (report.body_revisions, report.revisions) == (2, 0)
    assert ("  (Word counts 2 in the body; the package holds 0 revision "
            "elements)") in said, said


# --- the two counts the note compares, taken of ONE document state --------
#
# Word's body count used to be read straight after the Compare, and the
# package's after the math pass had accepted what it accepts — so on a
# default build the note compared two different documents. Word's figure
# came out high by exactly the math accepted: the grouping remainder was
# understated by that much or vanished, and when the two errors cancelled
# the note was not printed at all.


class _LiveRevisions:
    """A Revisions collection whose `Count` is read when it is asked, so
    an accepted revision is gone from it — `_Count` fixes it at build."""

    def __init__(self, items: list[Any]) -> None:
        self.items = items

    @property
    def Count(self) -> int:
        return len(self.items)

    def __call__(self, i: int) -> Any:
        return self.items[i - 1]


class _Leaves:
    """A revision at `span` that leaves every list holding it on Accept."""

    def __init__(self, span: tuple[int, int], *holders: list[Any]) -> None:
        self.Range = type("R", (), {"Start": span[0], "End": span[1]})()
        self.holders = holders

    def Accept(self) -> None:
        for held in self.holders:
            held.remove(self)


def _compared_with_math(prose: int, in_math: int) -> _FakeDoc:
    """A compare result reporting `prose + in_math` body revisions, the
    last `in_math` of them inside its one equation at 100–120 — which
    the default math pass accepts, leaving Word `prose`."""
    doc = _FakeDoc()
    body: list[Any] = []
    math: list[Any] = []
    math += [_Leaves((102 + 2 * k, 103 + 2 * k), body, math)
             for k in range(in_math)]
    body += [_Leaves((k, k + 1), body) for k in range(prose)] + math
    doc.Revisions = _LiveRevisions(body)
    equation = type("OMath", (), {"Range": type("R", (), {
        "Start": 100, "End": 120, "Revisions": _LiveRevisions(math)})()})()
    doc.OMaths = _Count([equation])
    return doc


FOOTNOTES_PART = """
  <pkg:part pkg:name="/word/footnotes.xml" pkg:contentType=\
"application/vnd.openxmlformats-officedocument.wordprocessingml.\
footnotes+xml">
    <pkg:xmlData>{notes}</pkg:xmlData>
  </pkg:part>
"""


class _FakeWordAfterMath(_FakeWordModule):
    """Compare hands back `doc`; the package carries `body` and, when
    `footnote` is given, a footnotes part holding it."""

    def __init__(self, body: str, doc: _FakeDoc,
                 footnote: str | None = None) -> None:
        super().__init__(body)
        self.doc, self.footnote = doc, footnote

    def compare_documents(self, word, orig, rev, **kw):
        self.compared = kw
        return self.doc

    def extract_flat_opc(self, doc, flat: Path) -> None:
        super().extract_flat_opc(doc, flat)
        if self.footnote is None:
            return
        xml = notes("footnotes", f'<w:footnote w:id="2">{self.footnote}'
                                 "</w:footnote>")
        part = FOOTNOTES_PART.format(notes=xml[xml.index("<w:footnotes"):])
        text = Path(flat).read_text(encoding="utf-8")
        Path(flat).write_text(text.replace("</pkg:package>",
                                           part + "</pkg:package>"),
                              encoding="utf-8")


@pytest.mark.parametrize(("in_math", "footnote", "note"), [
    (2, None,
     "  (Word counts 3 in the body; the package holds 4 revision elements)\n"
     "  (the remaining 1 are in word/document.xml too: Word GROUPS adjacent "
     "revisions, so one thing to accept can be several elements)"),
    (1, para(ins("in a note", rid=5), pid="33333333"),
     "  (Word counts 3 in the body; the package holds 4 revision elements)\n"
     "  (1 of them are in word/footnotes.xml, where Word's own count and "
     "Review > Next do not go)"),
], ids=["the grouping remainder, understated by the math accepted",
        "a footnote revision, silent when the two errors cancelled"])
def test_the_count_note_reads_Word_AFTER_the_math_pass(
        monkeypatch, sources, in_math, footnote, note):
    """Word's body count and the package's, of the document that is
    EXTRACTED. Three body revisions Word keeps, and `in_math` more inside
    an equation that the math pass accepts.

    With two accepted and four elements in the body — `a` and `b`
    adjacent, which Word counts as one — the note used to say "Word
    counts 5" and name no cause. With one accepted and a footnote
    revision beside three body elements, the stale 4 equalled the
    package's 4 and the note, whose first job is a footnote Word's count
    does not reach, said nothing."""
    kept = para(run("Kept ", preserve=True), ins("a", rid=1),
                ins("b", rid=2), pid="11111111")
    also = para(run("Also ", preserve=True), ins("c", rid=3),
                pid="22222222")
    more = "" if footnote else para(run("More ", preserve=True),
                                    ins("d", rid=4), pid="44444444")
    body = f"<w:document {NS}><w:body>{kept}{also}{more}</w:body></w:document>"
    doc = _compared_with_math(prose=3, in_math=in_math)
    fake = _FakeWordAfterMath(body, doc, footnote)
    monkeypatch.setattr(tracked, "_word", fake)
    original, revised, out = sources
    said: list[str] = []

    # the gates are not the subject, and the conftest inputs are not
    # what this redline rejects or accepts to
    report = tracked.build(original, revised, out, verify_in_word=False,
                           reject_check=False, accept_check=False,
                           progress=said.append)

    assert report.math_resolved == in_math
    assert [line for line in said if "in the body" in line] == [note], said
    assert (report.body_revisions, report.revisions) == (3, 4)


def _equation_para(number: str, inserted: str = "") -> str:
    """One paragraph: an inline equation, then prose that never changes.

    `inserted` goes in as a tracked insertion INSIDE the `m:oMath`, after
    the old digits — the shape AFI R3/T3.2 came back in."""
    tracked_digits = (f'<w:ins w:id="7" w:author="R" '
                      f'w:date="2026-01-01T00:00:00Z"><m:r><m:t>{inserted}'
                      f"</m:t></m:r></w:ins>") if inserted else ""
    return (f"<w:p><m:oMath><m:r><m:t>{number}</m:t></m:r>{tracked_digits}"
            "</m:oMath><w:r><w:t xml:space=\"preserve\"> in every year."
            "</w:t></w:r></w:p>")


def _mangled_equation_sources(sources) -> tuple[Path, Path, Path, str]:
    """(original, revised, out, redline body) for a mangled number.

    Rejecting the redline reads `-0.20`, which is the original — so the
    reject gate is right to pass. Accepting reads `-0.20398` where the
    clean copy says `-0.398`, and neither the paragraph text (`w:t`
    only) nor the anchors nor the counts can see it: the equation gate
    is the only one that refuses this build."""
    original, revised, out = sources
    for path, number in ((original, "-0.20"), (revised, "-0.398")):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml",
                       document(_equation_para(number)))
    body = (f"<w:document {NS}><w:body>"
            f"{_equation_para('-0.20', inserted='398')}</w:body>"
            "</w:document>")
    return original, revised, out, body


def test_a_mangled_equation_REFUSES_the_build_while_accept_check_is_on(
        monkeypatch, sources):
    """The equation gate runs apart from the other accept-side refusals,
    after the glyph restore, under its own `if accept_check`. Inverted,
    it lets the wrong number through on every default build and refuses
    the one build that asked not to be refused — so both halves are
    here, on the one fixture where this gate alone decides."""
    original, revised, out, body = _mangled_equation_sources(sources)
    monkeypatch.setattr(tracked, "_word", _FakeWordModule(body))

    with pytest.raises(PackageError, match="EQUATIONS") as refused:
        tracked.build(original, revised, out, verify_in_word=False)

    assert "'-0.20398' accepted" in str(refused.value), refused.value
    assert not out.exists(), "a refused build must not publish"

    report = tracked.build(original, revised, out, verify_in_word=False,
                           accept_check=False)

    assert out.is_file()
    (finding,) = report.accepted_math
    assert finding.startswith("equation 1: '-0.398' in the clean copy, "
                              "'-0.20398' accepted"), finding


def test_a_part_carried_from_the_BASELINE_is_said_part_by_part(
        monkeypatch, sources):
    """The clean copy had lost the data store too, so it comes back from
    the baseline — "this build went back a version for these", the one
    sentence an author might want to act on. The report field holds the
    names either way; only the progress line says it DURING the build,
    and the fixture has two parts so the line is one per part."""
    original, revised, out = sources
    with zipfile.ZipFile(original, "w") as z:
        z.writestr("word/document.xml", clean_document())
        z.writestr("customXml/item1.xml",
                   '<b:Sources xmlns:b="http://schemas.openxmlformats.org'
                   '/officeDocument/2006/bibliography"/>')
        z.writestr("customXml/itemProps1.xml",
                   '<ds:datastoreItem xmlns:ds="http://schemas.openxmlformats'
                   '.org/officeDocument/2006/customXml"/>')
    said: list[str] = []
    monkeypatch.setattr(tracked, "_word", _FakeWordModule(clean_document()))

    report = tracked.build(original, revised, out, verify_in_word=False,
                           progress=said.append)

    assert report.carried == []
    assert report.carried_from_baseline == ["customXml/item1.xml",
                                            "customXml/itemProps1.xml"]
    baseline = [line for line in said if "from the BASELINE" in line]
    assert baseline == [
        f"  carried from the BASELINE: {name} (the clean copy no longer "
        f"has it either — `strip_parts` is how to mean its removal)"
        for name in report.carried_from_baseline], said


def test_a_comment_de_duplicated_across_the_Compare_is_said_by_name(
        sources):
    """Compare hands the author their own note twice when both inputs
    carry it, and the build drops one copy. Dropping an author's comment
    is not something to do silently: the progress line names it, and the
    report field beside it cannot stand in for that line."""
    parts = make_parts(para(run("Employment rises.")), comment_items=(
        comment(1, "Check this number against Table 3."),
        comment(2, "Check this number against Table 3.")))
    report = tracked.BuildReport()
    said: list[str] = []

    tracked._carry_rewrites(parts, sources[0], report, said.append)

    (note,) = report.deduped_comments
    assert "Check this number" in note, note
    assert said == [f"  de-duplicated a comment present in BOTH inputs: "
                    f"{note}"], said


def test_tidying_a_staging_directory_already_gone_raises_nothing(tmp_path):
    """The tidy-up runs in `build`'s `finally`, so whatever it raises
    REPLACES the build's own outcome — a refusal's PackageError, or the
    return of a deliverable already published. A temp cleaner, or Word
    still holding `flat.xml` open on Windows, is enough to fail the
    removal; an absent directory fails it on every platform. What comes
    after it must still happen: the refused build is named."""
    building = tmp_path / "~redline.building.docx"
    building.write_bytes(b"what Word was given")
    said: list[str] = []

    tracked._clear_staging(tmp_path / "gone", building, False, said.append)

    assert building.exists()
    assert said == [
        "  the refused build is kept at ~redline.building.docx — open it "
        "to see what Word was given; the next build overwrites it"]


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
