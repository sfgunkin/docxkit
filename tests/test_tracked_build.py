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
from conftest import NS, dele, document, ins, make_parts, para, run

from docxkit import tracked
from docxkit.errors import PackageError
from docxkit.tracked import untracked

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
    assert "0 of them" in note[0]


def test_build_passes_the_compare_options_through(monkeypatch, sources):
    _, fake = _build(monkeypatch, _clean_document(), sources,
                     author="Revision R2", whitespace=False,
                     formatting=False)
    assert fake.compared == {"author": "Revision R2",
                             "whitespace": False, "formatting": False}


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


def test_a_failed_build_leaves_no_staging_file_behind(monkeypatch,
                                                      sources):
    out = sources[2]
    with pytest.raises(PackageError):
        _build(monkeypatch, _broken_document(), sources)
    assert not list(out.parent.glob("~*.building*"))


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

    report, _ = _build(monkeypatch, _clean_document(), sources)

    assert report.carried_properties == ["dc:title"]
    assert core_property(read_parts(out), "dc:title") == \
        "Loneliness Risk Index"
    assert "dc:title" in report.format()


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
                           reject_check=False, progress=said.append)

    assert out.is_file()
    assert len(report.unrejectable) == 1
    assert any("UNREJECTABLE" in line for line in said), said


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
    assert not list(out.parent.glob("~*.building*"))


# ------------------------------------------- the annotate path, for real --


def test_a_build_that_annotates_comments_every_revision(monkeypatch,
                                                        sources):
    """The heart of the pipeline, with comments.annotate running for
    real: the Flat OPC carries Word's scaffold comment, the XML pass
    clones it, and the package must hold both comments afterwards."""
    fake = _FakeWordModule(_revised_document(), scaffold=True)
    monkeypatch.setattr(tracked, "_word", fake)
    _baseline(sources[0], "Employment rises ")
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
    # every reading after the marks is 104.0, because `seconds` is a
    # property and the assertions below ask for it more than once
    ticks = itertools.chain([100.0, 101.0, 103.0], itertools.repeat(104.0))
    monkeypatch.setattr(tracked, "time", type("T", (), {
        "perf_counter": staticmethod(lambda: next(ticks))}))

    report = tracked.BuildReport()       # 100.0
    report.mark("compare")               # 101.0
    report.mark("comments")              # 103.0

    assert report.phases == [("compare", 1.0), ("comments", 2.0)]
    assert report.seconds == 4.0         # 104.0, from the start
    assert "[   1.0s] compare" in report.format()


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
