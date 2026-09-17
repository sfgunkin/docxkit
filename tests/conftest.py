"""Synthetic .docx fixtures.

Built from XML rather than copied from a paper: the tests then run on any
machine, need no Word, and can assert on exact bytes. Real manuscripts go
in tests/corpus/ (gitignored) for the optional round-trip tests.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import itertools
import sys
import zipfile
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterable

    from docxkit.revision import Paper

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


@pytest.fixture(scope="session")
def _registries(tmp_path_factory):
    """One directory for every test's registry file."""
    return tmp_path_factory.mktemp("registries")


#: Numbers each test's registry file within `_registries`.
_REGISTRY_IDS = itertools.count()


@pytest.fixture(autouse=True)
def _isolated_paper_registry(_registries, monkeypatch):
    """No test writes to the author's real paper registry.

    `revision.init` registers the paper it scaffolds, and this file's
    fixtures scaffold dozens. Without this the suite would append every
    throwaway tmp_path project to `%LOCALAPPDATA%\\docxkit\\papers.txt`
    — a machine-wide file, growing by a few dozen dead entries per run,
    and `status --all` reporting them as papers that have gone missing.

    **A file of its own per test, in a directory they share.** This was
    `tmp_path_factory.mktemp("registry")` per test, and a numbered
    `mktemp` lists the whole base directory to pick its number, makes a
    `-current` symlink and resolves the path — and every test's registry
    directory joined that listing, so the cost grew with the square of
    the tests run. Measured 2026-09-17 on the 737-test revision harness:
    273,236 calls into pytest's prefix matching, 1.6 s, for directories
    that each held one file.
    """
    registry = _registries / f"papers-{next(_REGISTRY_IDS)}.txt"
    monkeypatch.setenv("DOCXKIT_PAPERS", str(registry))


@pytest.fixture(autouse=True, scope="session")
def _no_translation_lookups():
    """argparse asks gettext for a translation of every string it holds,
    and `gettext.find` answers a MISS from the disk, uncached: four path
    checks per string with `LANG=en`, which is what this machine's user
    environment sets. The CLI tests build the whole parser for every
    invocation, so that was 19,490 lookups and 81,588 checks for the
    catalogues of a package that ships none — 2.3 s of 12 over
    `test_cli_revision.py` and `test_revision.py`, measured 2026-09-17.

    `LANGUAGE=C` is the lookup's own answer for "untranslated", reached
    before any path is checked, and it is what every one of those checks
    returned. Nothing in the suite reads a translated message.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LANGUAGE", "C")
        yield

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


#: The top-level pywin32 modules a collection could leave imported.
PYWIN32 = frozenset({"win32com", "pythoncom", "pywintypes"})

#: What collecting the suite imported from pywin32: recorded by
#: `pytest_collection_finish` before any test runs, and held to none by
#: `test_import_cost`.
PYWIN32_AT_COLLECTION = pytest.StashKey[list[str]]()


def pywin32_loaded(modules: Iterable[str]) -> list[str]:
    """The pywin32 modules among `modules`, sorted."""
    return sorted(m for m in modules if m.split(".")[0] in PYWIN32)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Record what collection imported from pywin32.

    `_no_real_word` stops a TEST importing it. Collection comes first and
    runs every module's top level, its tests selected or not — which is
    where `test_width_model` imported it on every run until 2026-09-13.
    """
    session.config.stash[PYWIN32_AT_COLLECTION] = pywin32_loaded(sys.modules)


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


# --- the revision protocol's workflow states ----------------------------
#
# Built ONCE and shared, because the test files each reached one of these
# states by hand — a redline copied into `build/redlines/` to stand in for
# a promote, an `ins` written into the manuscript to stand in for one, a
# stamp minted three times — and the state none of them produced, a
# batch built on the current baseline and deliberately HELD, was the one
# `revision baseline` read as the author rejecting the batch: a wrong
# verdict, pre-formatted for the paper's permanent log (Aging_Well,
# 2026-08-28; BACKLOG, "one missing class of test"). Every state here is
# reached through the protocol's own verbs where a verb exists — `init`
# scaffolds, the stamp is the one `build` writes, `promote` is the real
# one. The hand-back is the author's Word session, which this tool never
# performs on their behalf, so it is the one state written as prose.
# `tests/test_workflow_states.py` pins what each state IS.

#: The round every fixture below is about: two edits with an untouched
#: paragraph between them, so that "partly adjudicated" is expressible —
#: one edit kept as proposed, the other reverted.
ROUND_BASELINE = ("first old", "an untouched paragraph", "second old")
ROUND_PROPOSED = ("first new", "an untouched paragraph", "second new")


@dataclasses.dataclass(frozen=True)
class Round:
    """One revision round on a scaffolded paper, and the texts it is of."""

    paper: Paper
    baseline: tuple[str, ...]
    """The paragraphs of the truth the batch was built on."""
    proposed: tuple[str, ...]
    """What accepting every revision says, paragraph by paragraph."""

    def hand_back(self, *paragraphs: str) -> None:
        """The author's Word session: the markup gone, these left.

        Not a verb of the protocol — the author accepts and rejects in
        Word, and the tool never does — so this is the one transition
        a fixture writes by hand.
        """
        write(self.paper.working,
              make_parts("".join(para(run(t)) for t in paragraphs)))

    @property
    def partly(self) -> tuple[str, ...]:
        """The first edit kept as proposed, everything else as it was."""
        return (self.proposed[0], *self.baseline[1:])


def revision_round(tmp_path, *, baseline: tuple[str, ...] = ROUND_BASELINE,
                   proposed: tuple[str, ...] = ROUND_PROPOSED,
                   name: str = "HCW") -> Round:
    """A paper at the HELD state: baselined, with a batch built on that
    baseline — stamped as `build` stamps it — and NOT promoted.

    The batch proposes `proposed` over `baseline` paragraph by
    paragraph: one whose text differs is a deletion and an insertion,
    one that does not is left alone. Compare's own shape, in miniature.
    """
    from docxkit import guard, revision

    root = tmp_path / name
    root.mkdir()
    src = write(root / f"{name}.docx",
                make_parts("".join(para(run(t)) for t in baseline)))
    paper = revision.init(root, src, name=name)
    redline = "".join(
        para(run(was)) if was == now
        else para(dele(was, rid=91 + 2 * i), ins(now, rid=90 + 2 * i))
        for i, (was, now) in enumerate(zip(baseline, proposed, strict=True)))
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(redline))
    # the stamp is what ties a batch to the baseline it was built on
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    return Round(paper=paper, baseline=tuple(baseline),
                 proposed=tuple(proposed))


@pytest.fixture
def held_round(tmp_path) -> Round:
    """Built and HELD: the batch is staged and stamped, the manuscript
    is the truth, and nothing was promoted."""
    return revision_round(tmp_path)


@pytest.fixture
def promoted_round(held_round: Round) -> Round:
    """Built and PROMOTED, awaiting the author: the manuscript IS the
    redline, and `build/redlines/` holds the record of it."""
    from docxkit import revision

    revision.promote(held_round.paper)
    return held_round


@pytest.fixture
def accepted_round(promoted_round: Round) -> Round:
    """Promoted and ACCEPTED in full: every proposed paragraph, no
    markup, and a baseline the paper has outgrown."""
    promoted_round.hand_back(*promoted_round.proposed)
    return promoted_round


@pytest.fixture
def rejected_round(promoted_round: Round) -> Round:
    """Promoted and REJECTED in full: the baseline's paragraphs, no
    markup — the same file a batch that was never promoted leaves,
    which is why the promote's redline copy is the record."""
    promoted_round.hand_back(*promoted_round.baseline)
    return promoted_round


@pytest.fixture
def partly_round(promoted_round: Round) -> Round:
    """Promoted and PARTLY adjudicated: the first edit kept as proposed,
    the second reverted."""
    promoted_round.hand_back(*promoted_round.partly)
    return promoted_round
