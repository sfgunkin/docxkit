"""The single-file revision protocol.

The tests that matter here are the REFUSALS. Everything this module
does that is worth having is a thing it declines to do: build on a
baseline the author has not adjudicated, ship equations Word baked in
unreviewably, promote onto a file that moved underneath it. Each of
those failed silently in the papers this was ported from — the batch is
produced, it looks finished, and what it cost is discovered later or
not at all. So the assertions are on the FILE and the exception type,
never on the message.

Word is faked at the module attribute `revision._word`, the same seam
tracked.py uses, because none of the decisions under test need a real
Word to be wrong.
"""
from __future__ import annotations

import contextlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import document, make_parts, para, run, write

from docxkit import revision
from docxkit.errors import (
    BaselinePending,
    DocumentLocked,
    MathResolved,
    ProtocolError,
    StaleBatch,
)

NS_M = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'


def ins(text: str, rid: int = 90, author: str = "Revision") -> str:
    return (f'<w:ins w:id="{rid}" w:author="{author}" '
            f'w:date="2026-08-07T00:00:00Z">{run(text)}</w:ins>')


def dele(text: str, rid: int = 91, author: str = "Revision") -> str:
    return (f'<w:del w:id="{rid}" w:author="{author}" '
            f'w:date="2026-08-07T00:00:00Z">'
            f"<w:r><w:delText>{text}</w:delText></w:r></w:del>")


def footnotes_part(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
        f'<w:footnote w:id="2">{body}</w:footnote></w:footnotes>')


@pytest.fixture
def project(tmp_path):
    """A migrated paper: working.docx, an identical prev.docx, config."""
    src = write(tmp_path / "manuscript.docx",
                make_parts(para(run("The paper as it stands."))))
    return revision.init(tmp_path / "proj", src, name="Test Paper",
                         author="Agent", attic=tmp_path / "attic")


# ------------------------------------------------------------ config

def test_init_copies_rather_than_moves(tmp_path):
    """A migration must be abandonable by deleting one folder."""
    src = Path(write(tmp_path / "ps5_r2.docx",
                     make_parts(para(run("body")))))
    paper = revision.init(tmp_path / "proj", src)

    assert src.exists(), "the original manuscript was moved, not copied"
    assert paper.working.read_bytes() == src.read_bytes()
    # the baseline is seeded from the same bytes: at migration time the
    # manuscript IS the last accepted truth
    assert paper.prev.read_bytes() == src.read_bytes()
    for sub in ("build", "notes", "scripts/applied"):
        assert (paper.root / "revision" / sub).is_dir()
    assert (paper.root / "revision" / "log.md").exists()


def test_init_refuses_to_overwrite_a_live_configuration(project):
    with pytest.raises(ProtocolError):
        revision.init(project.root, project.working)


def test_init_missing_manuscript(tmp_path):
    with pytest.raises(ProtocolError):
        revision.init(tmp_path / "proj", tmp_path / "nope.docx")


def test_config_is_found_from_anywhere_below(project):
    """The agent's cwd during a batch is rarely the project root."""
    deep = project.root / "revision" / "scripts" / "applied"
    assert revision.load_paper(deep).working == project.working
    assert revision.load_paper(project.root / "revision").working \
        == project.working
    # and from a FILE path, not only a directory
    assert revision.load_paper(project.working).root == project.root


def test_config_not_found_says_what_to_do(tmp_path):
    with pytest.raises(ProtocolError, match="init"):
        revision.find_config(tmp_path)


def test_paper_reads_its_own_end_of_the_protocol(project):
    assert project.name == "Test Paper"
    assert project.author == "Agent"
    assert project.batch == project.build_dir / "batch.docx"
    assert project.attic is not None


def test_paper_falls_back_when_the_config_is_bare(tmp_path):
    """A hand-written paper.toml need not repeat every default."""
    folder = tmp_path / "proj" / "revision"
    folder.mkdir(parents=True)
    (folder / "paper.toml").write_text("[paper]\n", encoding="utf-8")
    paper = revision.load_paper(tmp_path / "proj")
    assert paper.working.name == "working.docx"
    assert paper.prev.name == "prev.docx"
    assert paper.author == "Revision"
    assert paper.gates == ()
    assert paper.attic is None


# ------------------------------------------------------------- state

def test_state_reads_truth_and_proposal(tmp_path):
    clean = write(tmp_path / "clean.docx",
                  make_parts(para(run("settled text"))))
    assert revision.state(clean).is_truth
    assert revision.state(clean).label == "truth"

    proposed = write(tmp_path / "proposed.docx", make_parts(
        para(run("settled "), ins("new"), dele("old"))))
    st = revision.state(proposed)
    assert not st.is_truth
    assert st.pending == 2
    assert st.label == "proposal"
    assert st.by_author == {"Revision": 2}


def test_state_counts_footnotes_the_author_cannot_see(tmp_path):
    """The body-only count is what makes a proposal look like the truth.

    Review > Next walks the body; Simple Markup and No Markup hide
    footnote balloons entirely. A revision left in a footnote is
    invisible from the author's chair and still makes the file a
    proposal — so a count that reads document.xml alone reports "truth"
    and lets the next Compare flatten it into plain text.
    """
    path = write(tmp_path / "fn.docx", make_parts(
        para(run("body text with no revisions at all")),
        footnotes=footnotes_part(para(run("note "), ins("added")))))

    st = revision.state(path)
    assert st.pending == 1, "a footnote revision was not counted"
    assert not st.is_truth
    assert st.hidden == 1
    assert "word/footnotes.xml" in st.by_part
    assert "word/document.xml" not in st.by_part


def test_hidden_excludes_the_body(tmp_path):
    path = write(tmp_path / "body.docx",
                 make_parts(para(run("x "), ins("y"))))
    st = revision.state(path)
    assert st.pending == 1
    assert st.hidden == 0, "a body revision is reachable, not hidden"


# ------------------------------------------------------------ ingest

def test_ingest_is_read_only(project):
    """Safe to run before every task without asking — that is the point."""
    before = project.working.read_bytes()
    prev_before = project.prev.read_bytes()
    revision.ingest(project.working, project.prev)
    assert project.working.read_bytes() == before
    assert project.prev.read_bytes() == prev_before


def test_ingest_sees_nothing_when_nothing_changed(project):
    report = revision.ingest(project.working, project.prev)
    assert report.untouched
    assert not report.changed_parts


def test_ingest_reports_the_authors_text_edit(project):
    write(project.working, make_parts(
        para(run("The paper as the author now wants it."))))
    report = revision.ingest(project.working, project.prev)
    assert not report.untouched
    assert report.working_state is not None
    assert report.working_state.is_truth


def test_ingest_flags_a_style_level_edit(project):
    """A style edit changes every paragraph using it, so a batch that
    rebuilds paragraphs can undo far more than it appears to touch."""
    parts = make_parts(para(run("The paper as it stands.")))
    parts["word/styles.xml"] = b"<w:styles><w:style w:styleId='A'/></w:styles>"
    write(project.prev, parts)
    changed = dict(parts)
    changed["word/styles.xml"] = (
        b"<w:styles><w:style w:styleId='B'/></w:styles>")
    write(project.working, changed)

    report = revision.ingest(project.working, project.prev)
    assert report.style_edit


def test_ingest_does_not_cry_wolf_over_save_noise(project):
    """A Word save rewrites app.xml and settings.xml on every round-trip.

    Reporting those as author edits is what made the layer useless: it
    fired every single time the author opened the file and closed it.
    """
    def app_xml(minutes: int) -> bytes:
        return (f"<Properties><TotalTime>{minutes}</TotalTime>"
                f"</Properties>").encode()

    base = make_parts(para(run("The paper as it stands.")))
    base["docProps/app.xml"] = app_xml(1)
    write(project.prev, base)
    resaved = dict(base)
    resaved["docProps/app.xml"] = app_xml(77)
    write(project.working, resaved)

    report = revision.ingest(project.working, project.prev)
    assert report.changed_parts == []
    assert "docProps/app.xml" in report.noise_parts


# ----------------------------------------------------------- baseline

def test_baseline_records_the_new_truth(project):
    write(project.working, make_parts(para(run("Accepted and settled."))))
    written = revision.baseline(project)
    assert written == project.prev
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_baseline_refuses_a_proposal(project):
    """A baseline containing a proposal is how the next Compare
    flattens that proposal into plain text."""
    write(project.working, make_parts(para(run("x "), ins("pending"))))
    before = project.prev.read_bytes()
    with pytest.raises(BaselinePending):
        revision.baseline(project)
    assert project.prev.read_bytes() == before, "the baseline was written"


def test_baseline_force_is_for_migration(project):
    """Adopting a file that already carries revisions the author keeps."""
    write(project.working, make_parts(para(run("x "), ins("pending"))))
    revision.baseline(project, force=True)
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_baseline_names_the_part_a_revision_hides_in(project):
    write(project.working, make_parts(
        para(run("clean body")),
        footnotes=footnotes_part(para(run("n "), ins("hidden")))))
    with pytest.raises(BaselinePending, match="footnotes"):
        revision.baseline(project)


# -------------------------------------------------------------- build

class _FakeBuild:
    """tracked.build, replaced: it reports what Word Compare resolved."""

    def __init__(self, math: int = 0, out_text: str = "built") -> None:
        self.math, self.out_text = math, out_text
        self.called_with: tuple[Any, ...] = ()

    def __call__(self, original, revised, out, classify=None, **kw):
        self.called_with = (Path(original), Path(revised), Path(out))
        write(Path(out), make_parts(para(run(self.out_text))))
        say = kw.get("progress") or (lambda _: None)
        say(f"resolved {self.math} math revisions")
        report = revision.tracked.BuildReport()
        report.revisions = 4
        return report


def test_build_refuses_a_baseline_with_pending_revisions(project,
                                                         monkeypatch):
    """Compare rebuilds the redline from ACCEPTED content, so pending
    revisions are flattened into plain text and can never be rejected —
    the author's open verdicts decided for them, silently."""
    write(project.prev, make_parts(para(run("x "), ins("unadjudicated"))))
    fake = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", fake)

    with pytest.raises(BaselinePending):
        revision.build(project, project.working)
    assert not fake.called_with, "Word Compare ran anyway"
    assert not project.batch.exists()


def test_build_pending_baseline_can_be_absorbed_deliberately(project,
                                                             monkeypatch):
    write(project.prev, make_parts(para(run("x "), ins("unadjudicated"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    revision.build(project, project.working, allow_pending_baseline=True)
    assert project.batch.exists()


def test_build_refuses_when_compare_resolved_math(project, monkeypatch):
    """Measured, not suspected: on a real subscript batch the compare
    path produced 0 insertions against the hand-authored path's 4, and
    reject-all no longer restored the baseline."""
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=5))
    with pytest.raises(MathResolved):
        revision.build(project, project.working)


def test_build_ignores_a_zero_math_note(project, monkeypatch):
    """docxkit emits the note even when the count is zero, so the guard
    reads the NUMBER rather than matching the sentence."""
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=0))
    report = revision.build(project, project.working)
    assert report.revisions == 4


def test_build_math_override(project, monkeypatch):
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=2))
    revision.build(project, project.working, allow_math_resolve=True)
    assert project.batch.exists()


def test_build_defaults_to_the_staging_path(project, monkeypatch):
    fake = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", fake)
    revision.build(project, project.working)
    assert fake.called_with[2] == project.batch
    assert fake.called_with[0] == project.prev, \
        "a batch must be built on the baseline, not on the live file"


def test_build_progress_reaches_the_caller(project, monkeypatch):
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    seen: list[str] = []
    revision.build(project, project.working, progress=seen.append)
    assert seen


# ------------------------------------------------------------ promote

def test_promote_refuses_while_word_holds_the_file(project, monkeypatch):
    """A copy written over a document open in Word appears to succeed,
    and then Word writes its in-memory version on top."""
    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setattr(revision.package, "is_locked", lambda _p: True)
    before = project.working.read_bytes()

    with pytest.raises(DocumentLocked):
        revision.promote(project)
    assert project.working.read_bytes() == before


def test_promote_refuses_a_stale_batch(project):
    """The author edited working.docx while the batch was being built;
    promoting would destroy those edits."""
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run("the author's own edit"))))
    before = project.working.read_bytes()

    with pytest.raises(StaleBatch):
        revision.promote(project)
    assert project.working.read_bytes() == before


def test_promote_lands_and_leaves_a_rescue_copy(project):
    write(project.batch, make_parts(para(run("the batch"))))
    original = project.working.read_bytes()

    report = revision.promote(project)
    assert project.working.read_bytes() == project.batch.read_bytes()
    assert report.rescue.exists()
    assert report.rescue.read_bytes() == original, \
        "the rescue copy does not hold the file that was replaced"


def test_each_promote_keeps_its_own_rescue(project):
    """The fixed-name version overwrote its own rescue every time, so
    only the most recent live state was ever recoverable."""
    write(project.batch, make_parts(para(run("first"))))
    first = revision.promote(project)
    revision.baseline(project)
    write(project.batch, make_parts(para(run("second"))))
    second = revision.promote(project)
    assert first.rescue != second.rescue
    assert first.rescue.exists() and second.rescue.exists()


def test_rescues_live_under_build_not_beside_the_manuscript(project):
    """Five working_rescueN.docx beside working.docx is exactly the
    ambiguity the one-file layout removed."""
    write(project.batch, make_parts(para(run("the batch"))))
    report = revision.promote(project)
    assert report.rescue.parent == project.rescue_dir
    assert project.rescue_dir.parent == project.build_dir
    assert not list(project.working.parent.glob("*rescue*"))


def test_rescues_are_stamped_not_numbered(project):
    """Numbering and pruning cannot both be right: the counter takes the
    first FREE number, so pruning 1-3 makes the next promote write a new
    file called _rescue1, older than the _rescue5 beside it."""
    stamped = revision.rescue_path(project, datetime(2026, 8, 7, 21, 54, 3))
    assert stamped.name == "working_rescue_20260807-215403.docx"

    stamped.parent.mkdir(parents=True, exist_ok=True)
    stamped.write_bytes(b"first")
    again = revision.rescue_path(project, datetime(2026, 8, 7, 21, 54, 3))
    assert again.name == "working_rescue_20260807-215403-2.docx", \
        "two promotes in one second collided"
    again.write_bytes(b"second")
    third = revision.rescue_path(project, datetime(2026, 8, 7, 21, 54, 3))
    assert third.name == "working_rescue_20260807-215403-3.docx"


def _seed_rescues(project, n: int) -> list[Path]:
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(n):
        p = revision.rescue_path(project, datetime(2026, 8, 7, 10, 0, i))
        p.write_bytes(f"rescue {i}".encode())
        made.append(p)
    return made


def test_rescues_are_listed_oldest_first(project):
    made = _seed_rescues(project, 4)
    assert revision.rescues(project) == made


def test_prune_keeps_the_newest(project):
    made = _seed_rescues(project, 7)
    gone = revision.prune_rescues(project, keep=3)
    assert gone == made[:4]
    assert revision.rescues(project) == made[4:]
    assert all(not p.exists() for p in gone)


def test_prune_zero_removes_all(project):
    _seed_rescues(project, 3)
    assert len(revision.prune_rescues(project, keep=0)) == 3
    assert revision.rescues(project) == []


def test_a_negative_keep_does_not_delete_the_newest(project):
    """Slicing with a negative limit would take from the wrong end and
    delete exactly the copies worth having."""
    made = _seed_rescues(project, 3)
    assert revision.prune_rescues(project, keep=-2) == made
    assert revision.rescues(project) == []


def test_promote_prunes_to_the_configured_depth(project):
    _seed_rescues(project, 6)
    write(project.batch, make_parts(para(run("the batch"))))
    report = revision.promote(project)
    # 6 seeded + this promote's own = 7, thinned to rescue_keep
    assert len(revision.rescues(project)) == project.rescue_keep
    assert report.pruned
    assert report.rescue.exists(), "the promote pruned its own rescue"


def test_rescue_keep_is_configurable(project):
    project.config.write_text(
        project.config.read_text(encoding="utf-8").replace(
            "rescue_keep = 5", "rescue_keep = 2"), encoding="utf-8")
    reloaded = revision.load_paper(project.root)
    assert reloaded.rescue_keep == 2
    _seed_rescues(reloaded, 4)
    revision.prune_rescues(reloaded)
    assert len(revision.rescues(reloaded)) == 2


def test_rescues_on_a_paper_that_has_never_promoted(project):
    assert revision.rescues(project) == []
    assert revision.prune_rescues(project) == []


def test_promote_needs_its_inputs(project):
    with pytest.raises(ProtocolError, match="missing"):
        revision.promote(project)          # no batch was ever built


# ----------------------------------------------------------- validate

class _FakeDoc:
    def __init__(self, revisions: int = 2, text: str = "") -> None:
        self.Revisions = type("R", (), {"Count": revisions})()
        self._text = text
        self.accepted = False

    def AcceptAllRevisions(self) -> None:
        self.accepted = True

    @property
    def Paragraphs(self) -> list[Any]:
        return [type("P", (), {"Range": type("R", (), {
            "Text": self._text})()})()]


class _FakeWord:
    """The COM boundary, replaced. Word's verdict is an input here."""

    def __init__(self, doc: _FakeDoc | None = None,
                 explode: bool = False) -> None:
        self.doc, self.explode = doc or _FakeDoc(), explode

    @contextlib.contextmanager
    def session(self, **_kw):
        yield "app"

    @contextlib.contextmanager
    def open_doc(self, _app, _path, **_kw):
        if self.explode:
            raise OSError("Word could not open the file")
        yield self.doc


def test_validate_aborts_before_word_when_lint_fails(tmp_path,
                                                     monkeypatch):
    """Lint is offline and cheap; failing early saves a Word round-trip
    and, more to the point, never opens a file known to be broken."""
    path = write(tmp_path / "bad.docx", make_parts(para(run("x"))))
    monkeypatch.setattr(revision._lint, "lint_parts",
                        lambda _parts: ["orphan bookmark 3"])
    opened: list[str] = []
    monkeypatch.setattr(revision, "_word",
                        type("W", (), {"session": lambda *a, **k:
                                       opened.append("word")})())

    report = revision.validate(path)
    assert report.lint
    assert not report.ok
    assert not opened, "Word was opened despite a lint failure"


def test_validate_reports_a_file_word_refuses(tmp_path, monkeypatch):
    path = write(tmp_path / "x.docx", make_parts(para(run("x"))))
    monkeypatch.setattr(revision, "_word", _FakeWord(explode=True))
    report = revision.validate(path)
    assert report.word_opened is False
    assert report.word_error
    assert not report.ok


def test_validate_reject_all_must_restore_the_baseline(tmp_path):
    """The gate that proves a batch is fully REVIEWABLE. If rejecting
    everything does not reproduce the baseline, something in the batch
    cannot be refused and the author's veto is not real."""
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("settled text"))))
    # a batch that rewrote the text WITHOUT marking it: the author can
    # reject every revision in the file and still not get their words
    # back, which is the whole failure this gate exists to catch
    lossy = write(tmp_path / "lossy.docx",
                  make_parts(para(run("quietly rewritten"))))
    report = revision.validate(lossy, baseline_path, use_word=False)
    assert report.reject_matches_baseline is False
    assert report.reject_detail["paragraphs"] is False
    assert not report.ok


def test_validate_reject_all_passes_on_a_faithful_batch(tmp_path):
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("settled text"))))
    faithful = write(tmp_path / "batch.docx", make_parts(
        para(run("settled text"), ins("added"))))
    report = revision.validate(faithful, baseline_path, use_word=False)
    assert report.reject_matches_baseline is True
    assert report.ok


def test_validate_checks_footnotes_too(tmp_path):
    """A batch may be faithful in the body and lossy in a footnote."""
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("note")))))
    lossy = write(tmp_path / "batch.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("nope")))))
    report = revision.validate(lossy, baseline_path, use_word=False)
    assert report.reject_detail["footnotes"] is False
    assert not report.ok


def test_lint_catches_a_shell_that_already_exists(tmp_path):
    """The cheap gate gets there first, and aborts before Word."""
    body = f'<w:p><m:oMath {NS_M}><m:r><m:t></m:t></m:r></m:oMath></w:p>'
    report = revision.validate(write(tmp_path / "shell.docx",
                                     make_parts(body)), use_word=False)
    assert any("oMath" in problem for problem in report.lint)
    assert not report.ok


def test_validate_flags_shells_that_ACCEPTING_would_create(tmp_path,
                                                           monkeypatch):
    """The regression guard for a fix that has already been made once.

    A manuscript shipped visibly broken equations because the XML accept
    left empty OMML shells where Word's own accept prunes them. docxkit
    fixed that, and `revisions.accept` now prunes — so the only way to
    reach this branch is to break the fix, which is exactly what the
    fake below does. Lint cannot cover this: the shell does not exist in
    the file being linted, only in what accepting it would produce.
    """
    body = (f'<w:p><m:oMath {NS_M}>'
            f'<w:del w:id="77" w:author="R" w:date="2026-08-07T00:00:00Z">'
            f"<m:r><m:t>x</m:t></m:r></w:del></m:oMath></w:p>")
    path = write(tmp_path / "regressed.docx", make_parts(body))
    assert not revision.validate(path, use_word=False).lint

    def _accept_without_pruning(xml: str, **_kw: object) -> str:
        # the pre-fix behaviour: drop the deleted run, keep its parent
        return re.sub(r"<w:del\b.*?</w:del>", "", xml, flags=re.DOTALL)

    monkeypatch.setattr(revision.revisions, "accept",
                        _accept_without_pruning)
    report = revision.validate(path, use_word=False)
    assert report.empty_shells == 1
    assert not report.ok


def test_validate_compares_the_two_accept_paths(tmp_path, monkeypatch):
    """Accept can be simulated in XML or performed by Word, and the
    manuscript that shipped broken equations is what they disagreed on."""
    path = write(tmp_path / "x.docx", make_parts(
        para(run("kept", preserve=True), ins("added"))))
    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(text="keptadded")))
    report = revision.validate(path)
    assert report.accept_paths_agree is True
    assert report.ok

    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(text="something else")))
    disagree = revision.validate(path)
    assert disagree.accept_paths_agree is False
    assert not disagree.ok


def test_validate_folds_presentational_differences(tmp_path, monkeypatch):
    """Word returns U+2212 for the math minus and math letters from the
    Mathematical Italic block; the XML holds a hyphen and ASCII. Folding
    those is what stops every equation reporting a mismatch."""
    path = write(tmp_path / "m.docx", make_parts(para(run("a-b"))))
    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="a−b\r")))
    report = revision.validate(path)
    assert report.accept_paths_agree is True


def test_validate_skips_word_when_asked(tmp_path, monkeypatch):
    path = write(tmp_path / "x.docx", make_parts(para(run("x"))))
    monkeypatch.setattr(revision, "_word", _FakeWord(explode=True))
    report = revision.validate(path, use_word=False)
    assert report.word_opened is None
    assert report.ok


def test_validate_does_not_accept_in_a_file_word_has_open(tmp_path,
                                                          monkeypatch):
    """AcceptAllRevisions on the author's own open window would rewrite
    what they are looking at."""
    path = write(tmp_path / "x.docx", make_parts(para(run("x"))))
    doc = _FakeDoc()
    monkeypatch.setattr(revision, "_word", _FakeWord(doc))
    monkeypatch.setattr(revision.package, "is_locked", lambda _p: True)
    revision.validate(path)
    assert not doc.accepted


def test_exit_codes_are_distinct():
    """A caller must be able to tell WHICH refusal it hit without
    parsing English."""
    assert BaselinePending.exit_code == 3
    assert MathResolved.exit_code == 2
    assert StaleBatch.exit_code == 4
    assert ProtocolError.exit_code == 1


def test_document_helper_is_used():
    """conftest.document is the fixture builder these tests lean on."""
    assert "<w:body>" in document("")
