"""Synthetic .docx fixtures.

Built from XML rather than copied from a paper: the tests then run on any
machine, need no Word, and can assert on exact bytes. Real manuscripts go
in tests/corpus/ (gitignored) for the optional round-trip tests.
"""
from __future__ import annotations

import contextlib
import io
import sys
import zipfile

import pytest

NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" '
    'xmlns:w16cid="http://schemas.microsoft.com/office/word/2016/wordml/cid" '
    'xmlns:w16cex="http://schemas.microsoft.com/office/word/2018/wordml/cex"'
)


def run(text: str, *, style: str | None = None, preserve: bool = False) -> str:
    rpr = f'<w:rPr><w:rStyle w:val="{style}"/></w:rPr>' if style else ""
    space = ' xml:space="preserve"' if preserve else ""
    return f"<w:r>{rpr}<w:t{space}>{text}</w:t></w:r>"


def para(*runs: str, pid: str = "11111111") -> str:
    return f'<w:p w14:paraId="{pid}" w14:textId="{pid}">{"".join(runs)}</w:p>'


def document(body: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:document {NS}><w:body>{body}</w:body></w:document>")


def comments(*items: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:comments {NS}>{''.join(items)}</w:comments>")


def comment(cid: int, text: str, para_id: str = "AAAA0001") -> str:
    return (f'<w:comment w:id="{cid}" w:author="Tester" '
            f'w:date="2026-07-29T00:00:00Z" w:initials="T">'
            f'<w:p w14:paraId="{para_id}" w14:textId="{para_id}">'
            f'<w:pPr><w:pStyle w:val="CommentText"/></w:pPr>'
            f"{run(text)}</w:p></w:comment>")


def hdr(body: str, foot: bool = False) -> str:
    """A header (or footer) part. Word numbers these after the section
    that references them, so the NAME is not stable across an edit."""
    tag = "w:ftr" if foot else "w:hdr"
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<{tag} {NS}>{body}</{tag}>")


def notes(kind: str, *items: str) -> str:
    """A footnotes/endnotes part; `items` are already-built note elements."""
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:{kind} {NS}>{''.join(items)}</w:{kind}>")


def note(text: str, nid: int = 2, kind: str = "footnote") -> str:
    return f'<w:{kind} w:id="{nid}">{para(run(text))}</w:{kind}>'


def field(instr: str, result: str) -> str:
    """A fldChar field with a cached result — PAGE, DATE, HYPERLINK."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> {instr} '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f"{run(result)}"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def table(*rows: str) -> str:
    return f"<w:tbl>{''.join(rows)}</w:tbl>"


def row(*cells: str, revision: str | None = None, rid: int = 95) -> str:
    """A table row; `revision` flags the ROW itself as ins/del.

    A row-level revision lives in ``w:trPr`` and is a FLAG on the row,
    not a wrapper around content — Word makes the whole row appear or
    disappear, so the document has one more row than the view does. It
    is the case every `w:tr` walk has to account for and the one no
    fixture here carried: `reorder_rows` shipped a guard whose only
    reachable branch fired on exactly this shape, and the suite was
    green at 5274 because the three tests written beside it used
    cell-level ``w:ins``, where the two row counts stay equal.
    """
    trpr = (f'<w:trPr><w:{revision} w:id="{rid}" w:author="Revision" '
            f'w:date="2026-07-29T00:00:00Z"/></w:trPr>') if revision else ""
    return ("<w:tr>" + trpr
            + "".join(f"<w:tc>{para(run(c))}</w:tc>" for c in cells)
            + "</w:tr>")


def ins(text: str, rid: int = 90) -> str:
    return (f'<w:ins w:id="{rid}" w:author="Revision" '
            f'w:date="2026-07-29T00:00:00Z">{run(text)}</w:ins>')


def dele(text: str, rid: int = 91) -> str:
    return (f'<w:del w:id="{rid}" w:author="Revision" '
            f'w:date="2026-07-29T00:00:00Z">'
            f"<w:r><w:delText>{text}</w:delText></w:r></w:del>")


def para_mark_ins(rid: int = 92) -> str:
    """A property-level (self-closing) revision: an inserted paragraph mark."""
    return (f'<w:p w14:paraId="22222222"><w:pPr><w:rPr>'
            f'<w:ins w:id="{rid}" w:author="Revision" '
            f'w:date="2026-07-29T00:00:00Z"/></w:rPr></w:pPr>'
            f"{run('tail')}</w:p>")


def make_parts(body: str, *, comment_items: tuple[str, ...] = (),
               footnotes: str | None = None,
               extra: dict[str, str] | None = None) -> dict[str, bytes]:
    parts = {
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": document(body).encode("utf-8"),
    }
    if comment_items:
        parts["word/comments.xml"] = comments(*comment_items).encode("utf-8")
        parts["word/commentsExtended.xml"] = (
            f'<w15:commentsEx {NS}><w15:commentEx w15:paraId="AAAA0001" '
            f'w15:done="0"/></w15:commentsEx>').encode()
        parts["word/commentsIds.xml"] = (
            f'<w16cid:commentsIds {NS}><w16cid:commentId '
            f'w16cid:paraId="AAAA0001" w16cid:durableId="0000AAAA"/>'
            f"</w16cid:commentsIds>").encode()
        parts["word/commentsExtensible.xml"] = (
            f'<w16cex:commentsExtensible {NS}><w16cex:commentExtensible '
            f'w16cex:durableId="0000AAAA" '
            f'w16cex:dateUtc="2026-07-29T00:00:00Z"/>'
            f"</w16cex:commentsExtensible>").encode()
    if footnotes is not None:
        parts["word/footnotes.xml"] = footnotes.encode("utf-8")
    for name, xml in (extra or {}).items():
        parts[name] = xml.encode("utf-8")
    return parts


def write(path, parts: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in parts.items():
            z.writestr(name, blob)
    return str(path)


@contextlib.contextmanager
def cp1252_console():
    """stdout as a Windows console gives it: cp1252, `errors="strict"`.

    The default console code page on every machine these manuscripts are
    written on, and the one thing the everyday suite cannot see —
    pytest's captured stdout is not a `TextIOWrapper` at all, so
    `console.utf8_stdout` is a no-op under it and a library that never
    reconfigures looks identical to one that does.

    It must be a real `TextIOWrapper` for that reason: the guard in
    `console` refuses anything else, so a `StringIO` would test nothing.

    **A context manager rather than a fixture, and that is not a style
    choice.** pytest re-assigns `sys.stdout` to its own capture file at
    the start of every phase, so a patch installed during fixture SETUP
    is gone by the time the test body runs — the first version of this
    passed the stream to nothing and the prints landed in pytest's
    capture, where they encode fine and prove nothing.

    Yields a callable returning what was printed, decoded by whatever
    encoding the stream ENDED UP with: a library that made the console
    safe leaves UTF-8 behind, and that is the assertion.
    """
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict",
                              newline="\n")
    was = sys.stdout
    sys.stdout = stream

    def printed() -> str:
        stream.flush()
        return buf.getvalue().decode(stream.encoding, errors="replace")

    try:
        yield printed
    finally:
        sys.stdout = was


@pytest.fixture
def simple_docx(tmp_path):
    """Two paragraphs and a two-row table."""
    body = (para(run("Intro paragraph about age-friendly work."))
            + para(run("Second paragraph mentioning Figure 1."))
            + table(row("Country", "AFI"), row("Poland", "0.31")))
    return write(tmp_path / "simple.docx", make_parts(body))


@pytest.fixture
def tracked_docx(tmp_path):
    """A redline: two run-level revisions plus one property-level mark."""
    body = (para(run("Kept text "), ins("inserted"), dele("removed"),
                 run(" tail."))
            + para_mark_ins()
            + table(row("Country", "Dif."), row("Poland", "0.02")))
    return write(tmp_path / "tracked.docx",
                 make_parts(body, comment_items=(comment(1, "seed comment"),)))


@pytest.fixture(autouse=True)
def _isolated_paper_registry(tmp_path_factory, monkeypatch):
    """No test writes to the author's real paper registry.

    `revision.init` registers the paper it scaffolds, and this file's
    fixtures scaffold dozens. Without this the suite would append every
    throwaway tmp_path project to `%LOCALAPPDATA%\\docxkit\\papers.txt`
    — a machine-wide file, growing by a few dozen dead entries per run,
    and `status --all` reporting them as papers that have gone missing.
    """
    registry = tmp_path_factory.mktemp("registry") / "papers.txt"
    monkeypatch.setenv("DOCXKIT_PAPERS", str(registry))

@pytest.fixture(autouse=True)
def _no_real_word(request, monkeypatch):
    """No test outside `-m word` starts or attaches to a Word instance.

    `shared_session` opens one COM instance for a whole ladder, and
    several CLI paths enter it before reading any flag — `revision
    ship` does, because its BUILD half needs Compare whatever
    `--no-word` says about the validate half. A test that fakes
    `tracked.build` still went through it and still reached Word.

    Under `-n 8` that is eight workers attaching to one Word at once,
    and it fails the way COM fails: `Windows fatal exception: code
    0x800706be` — RPC_S_CALL_FAILED — dumped by faulthandler, the
    worker gone, the run partial. Three gate chains went red that way
    on 2026-08-25 and passed on the retry, with the FLOORS gate
    reporting `_table_layout.py` at 56.5% and then 66.3%: a coverage
    drop in a module nobody had touched, which is the shape of a
    partial run and not of a defect.

    Yielding None is not a stub, it is what `shared_session` already
    does when Word cannot be started — "the point is to save a start,
    never to turn no-Word-here into a different error in a different
    place" — so every `session()` inside behaves as it does on a
    machine without Word. A test that WANTS Word says so with the
    `word` marker and gets the real one.
    """
    if request.node.get_closest_marker("word"):
        return
    # The IMPORT, not the function. `session` opens with `import
    # pythoncom`, and a None in `sys.modules` makes that raise exactly
    # as it does on a machine without the `word` extra — which is what
    # CI is. Blocking the function instead would have answered for the
    # two things worth keeping real: `shared_session`'s sharing, which
    # one test exists to count, and `session` itself, which
    # `test_word_session_ruler` tests against fakes of its own. Those
    # fakes go into `sys.modules` too, from a fixture that runs after
    # this one, so they win where they are wanted.
    monkeypatch.setitem(sys.modules, "pythoncom", None)
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)


def clean_document() -> str:
    """A minimal `w:document` with no XML prolog.

    The part is embedded inside `<pkg:xmlData>` in the Flat OPC fixture
    the tracked-build tests unpack, and a prolog there is not legal.
    """
    xml = document(para(run("The revised sentence.")))
    return xml[xml.index("<w:document"):]


@pytest.fixture
def sources(tmp_path):
    """(original, revised, out) for a `tracked.build` run.

    Here rather than in a test module because TWO now need it —
    `test_tracked_build` and `test_tracked_gates`, split on 2026-09-02 —
    and a fixture shared by importing it reads as unused to a linter
    while every test that takes it by name reads as REDEFINING it. That
    is ruff F401 and five F811s for code pytest resolves correctly;
    conftest is where a shared fixture stops being an argument with the
    tooling.

    The two inputs are never read by the fake Word module, but `build`
    opens them, so they have to exist.
    """
    for name in ("original.docx", "revised.docx"):
        with zipfile.ZipFile(tmp_path / name, "w") as z:
            z.writestr("word/document.xml", clean_document())
    return (tmp_path / "original.docx", tmp_path / "revised.docx",
            tmp_path / "redline.docx")
