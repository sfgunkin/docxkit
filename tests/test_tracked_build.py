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
import zipfile
from pathlib import Path

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


def _clean_document() -> str:
    # no XML prolog: the part is embedded inside <pkg:xmlData>
    xml = document(para(run("The revised sentence.")))
    return xml[xml.index("<w:document"):]


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
        self.Revisions = _Revisions()
        self.Comments = _Revisions()
        self.Paragraphs = _Revisions()
        self.OMaths = _Revisions()     # a real Document always has one
        self.closed = False

    def Close(self, SaveChanges=0):
        self.closed = True


class _FakeWordModule:
    """Only what tracked.build actually calls."""

    def __init__(self, body: str) -> None:
        self.body = body
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
        Path(flat).write_text(FLAT_TEMPLATE.format(body=self.body),
                              encoding="utf-8")

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


def test_the_build_leaves_no_temp_directory_behind(monkeypatch, sources,
                                                   tmp_path):
    import tempfile
    root = Path(tempfile.gettempdir())
    before = set(root.glob("docxkit_tracked_*"))
    _build(monkeypatch, _clean_document(), sources)
    assert set(root.glob("docxkit_tracked_*")) == before


def test_the_temp_directory_goes_even_when_the_build_fails(
        monkeypatch, sources):
    import tempfile
    root = Path(tempfile.gettempdir())
    before = set(root.glob("docxkit_tracked_*"))
    with pytest.raises(PackageError):
        _build(monkeypatch, _broken_document(), sources)
    assert set(root.glob("docxkit_tracked_*")) == before


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
