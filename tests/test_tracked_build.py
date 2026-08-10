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
from conftest import NS, document, para, run

from docxkit import tracked
from docxkit.errors import PackageError

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
    def __init__(self, text="", omaths=0, revisions=()):
        self.Text = text
        self.OMaths = _Count([object()] * omaths)
        self.Revisions = _Count(revisions)

    def Paragraphs(self, i):
        return type("P", (), {"Range": type("R", (), {"Text": self.Text})})


class _Rev:
    def __init__(self, text="", omaths=0):
        self.Range = _MathRange(text, omaths=omaths)
        self.accepted = False

    def Accept(self):
        self.accepted = True


class _OMath:
    """doc.OMaths(i) is an OMath OBJECT carrying a .Range, not a range."""

    def __init__(self, revisions=()):
        self.Range = _MathRange(revisions=revisions)


class _MathDoc:
    """A document where the two math scans see DIFFERENT revisions.

    One equation whose range INTERSECTS two revisions, and three
    revisions of which only one CONTAINS math — the shape that made
    substituting one scan for the other drop 41 revisions on AFI.
    """

    def __init__(self):
        self.intersecting = [_Rev("dropped-1"), _Rev("dropped-2")]
        self.containing = _Rev("has math", omaths=1)
        self.all_revisions = [_Rev("prose a"), self.containing,
                              _Rev("prose b")]
        self.OMaths = _Count([_OMath(revisions=self.intersecting)])
        self.Revisions = _Count(self.all_revisions)
        self.added: list[str] = []
        self.Comments = type("C", (), {
            "Add": lambda _s, rng, text: self.added.append(text),
            "Count": 0})()


def test_the_two_math_scans_select_different_revisions():
    """The AFI regression, pinned.

    The equation walk finds revisions INTERSECTING a math range; the
    revision scan finds revisions CONTAINING math. They are not
    substitutes — swapping them left 41 revisions un-accepted, and the
    counts here differ for exactly that reason.
    """
    from docxkit.tracked import (
        _accept_math_via_equations,
        _comment_and_accept_math_revisions,
    )

    via_equations = _accept_math_via_equations(_MathDoc())

    doc = _MathDoc()
    via_revisions = _comment_and_accept_math_revisions(
        doc, lambda ctx: "R1: equation revised", None)

    assert via_equations == 2          # both revisions touching the math
    assert via_revisions == 1          # only the one that contains math
    assert via_equations != via_revisions, "the scans must not coincide"
    assert doc.containing.accepted
    assert doc.added == ["R1: equation revised"]


def test_resolve_math_picks_the_cheap_walk_when_nothing_is_commented(
        monkeypatch):
    from docxkit import tracked as T
    seen = []
    def _equations(doc, *args, **kw):
        seen.append("equations")
        return 7

    def _revisions(*args, **kw):
        seen.append("revisions")
        return 3

    monkeypatch.setattr(T, "_accept_math_via_equations", _equations)
    monkeypatch.setattr(T, "_comment_and_accept_math_revisions", _revisions)
    assert T._resolve_math(_MathDoc(), None, None) == 7
    assert T._resolve_math(_MathDoc(), lambda ctx: "x", None) == 3
    assert seen == ["equations", "revisions"]


def test_a_document_with_no_equations_resolves_nothing():
    from docxkit.tracked import _accept_math_via_equations

    class NoMath:
        OMaths = _Count()
    assert _accept_math_via_equations(NoMath()) == 0


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
    assert seeded == 1
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
    assert _accept_math_via_equations(Doc()) == 0    # skipped, not raised


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
        doc, lambda ctx: "note", None) == 1


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
    assert _accept_math_via_equations(Doc(), notes) == 0
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
    assert tracked.compare_collateral(revised, redline) == [
        "part dropped: word/header1.xml"]


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
