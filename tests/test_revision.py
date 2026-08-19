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
from conftest import (
    comment,
    document,
    make_parts,
    note,
    notes,
    para,
    run,
    write,
)

from docxkit import package, revision
from docxkit.errors import (
    BaselinePending,
    DocumentLocked,
    HandbackLoss,
    MathResolved,
    ProtocolError,
    StaleBatch,
)
from docxkit.revision import glyph_runs

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
    log = (paper.root / "revision" / "log.md").read_text(encoding="utf-8")
    # the migration row carries the manuscript's digest, eight hex
    # characters of it — enough to tell two builds apart by eye, short
    # enough to sit in a table cell a person reads
    import hashlib
    full = hashlib.sha256(paper.working.read_bytes()).hexdigest().upper()
    assert f"`{full[:8]}`" in log, log


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


# -------------------------------------------- what the hand-back LOST ----

#: The shape Word leaves behind when it collapses a paragraph to make an
#: edit: the words survive, the link element does not.
LINKED = ('<w:hyperlink w:anchor="ref_Ritchie2023b">'
          "<w:r><w:t>Ritchie (2023b)</w:t></w:r></w:hyperlink>")
FLAT = "<w:r><w:t>Ritchie (2023b)</w:t></w:r>"


def _handback(project, body: str, **kw) -> None:
    """Write `body` as the author's returned working.docx."""
    write(project.working, make_parts(body, **kw))


def test_ingest_names_a_link_the_authors_word_session_ATE(project):
    """LI7 2026-08-15: 33 body links in, 28 out, and every content layer
    clean — the words are all still there."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))

    report = revision.ingest(project.working, project.prev)

    assert [loss.kind for loss in report.lost] == ["link"]
    assert "ref_Ritchie2023b" in report.lost[0].what


def test_a_lost_FOOTNOTE_is_found_by_text_not_by_id(project):
    """Word renumbers on save: 19 notes become 18 with the ids still
    contiguous, so there is no gap to notice and no id to miss."""
    write(project.prev, make_parts(
        para(run("body")),
        footnotes=notes("footnotes", note("kept", nid=2),
                        note("the vanished note", nid=3))))
    _handback(project, para(run("body")),
              footnotes=notes("footnotes", note("kept", nid=2)))

    lost = revision.ingest(project.working, project.prev).lost

    assert [loss.kind for loss in lost] == ["footnote"]
    assert lost[0].what == "the vanished note"


def test_a_lost_ENDNOTE_is_found_too(project):
    """A check that stopped at the footnotes would be a gate that cannot
    fail for any paper using the other kind."""
    write(project.prev, make_parts(
        para(run("body")),
        extra={"word/endnotes.xml":
               notes("endnotes", note("an endnote", nid=2, kind="endnote"))}))
    _handback(project, para(run("body")),
              extra={"word/endnotes.xml": notes("endnotes")})

    lost = revision.ingest(project.working, project.prev).lost
    assert [(loss.kind, loss.what) for loss in lost] == \
        [("endnote", "an endnote")]


def test_an_ordinary_author_edit_loses_NOTHING(project):
    """The gate must be silent on the normal round-trip, or it will be
    switched off inside a week."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("look at "), LINKED))

    assert revision.ingest(project.working, project.prev).lost == []


def test_baseline_REFUSES_while_a_loss_is_unacknowledged(project):
    """This is the step that makes it permanent: prev.docx is what the
    compare chain measures against afterwards."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))
    before = project.prev.read_bytes()

    with pytest.raises(HandbackLoss, match="ref_Ritchie2023b"):
        revision.baseline(project)
    assert project.prev.read_bytes() == before, "the baseline was written"


def test_force_does_not_override_the_loss_refusal(project):
    """`force` is the flag reached for by reflex, and the whole point is
    that the acknowledgement is specific."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))
    with pytest.raises(HandbackLoss):
        revision.baseline(project, force=True)


def test_a_deliberate_loss_can_be_NAMED_and_then_baselines(project):
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))
    lost = revision.ingest(project.working, project.prev).lost

    revision.baseline(project, accept_loss=(lost[0].key,))
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_a_DECLARED_loss_that_did_not_happen_is_itself_refused(project):
    """A stale exemption is a switched-off gate that reads as a
    switched-on one, and it would pass the next real loss in silence."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), LINKED))

    with pytest.raises(HandbackLoss, match="has NOT lost"):
        revision.baseline(project, accept_loss=("link:ref_Gone2024 (x)",))


def test_a_first_baseline_with_no_prev_is_not_blocked(tmp_path):
    """`init` seeds prev from working, but a paper that has lost its
    build/ directory must still be able to record a truth."""
    src = write(tmp_path / "m.docx", make_parts(para(run("body"))))
    paper = revision.init(tmp_path / "p2", src)
    paper.prev.unlink()
    assert revision.baseline(paper) == paper.prev


# -------------------------------------------------------------- build

class _FakeBuild:
    """tracked.build, replaced: it reports what Word Compare resolved."""

    def __init__(self, math: int = 0, out_text: str = "built",
                 extra: str = "") -> None:
        self.math, self.out_text, self.extra = math, out_text, extra
        self.called_with: tuple[Any, ...] = ()

    def __call__(self, original, revised, out, classify=None, **kw):
        self.called_with = (Path(original), Path(revised), Path(out))
        write(Path(out), make_parts(para(self.extra + run(self.out_text))))
        say = kw.get("progress") or (lambda _: None)
        say(f"resolved {self.math} math revisions")
        report = revision.tracked.BuildReport()
        report.revisions = 4
        # the NUMBER is what the protocol reads; the line above is a
        # sentence tracked.build is free to reword, and the refusal used
        # to be a grep over it
        report.math_resolved = self.math
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


def test_build_names_the_paragraphs_compare_left_untracked(project,
                                                           monkeypatch):
    """The math count understated this badly: a merged, rewritten
    math-bearing paragraph shipped WHOLE and untracked while the batch
    read "7 revisions, 6 of them in the body" — all six of them two
    word-swaps in an unrelated paragraph (Parental Style 2026-08-10).
    Said BEFORE the handback, not after gate 5 fails."""
    write(project.prev, make_parts(para(run("the baseline sentence"))))
    monkeypatch.setattr(revision.tracked, "build",
                        _FakeBuild(out_text="a rewritten sentence"))
    seen: list[str] = []
    revision.build(project, project.working, progress=seen.append)
    said = "\n".join(seen)
    assert "UNTRACKED" in said, said
    assert "the baseline sentence" in said and "a rewritten sentence" in said
    assert "no revision on them" in said


def test_a_faithfully_tracked_build_says_nothing_about_untracking(
        project, monkeypatch):
    write(project.prev, make_parts(para(run("built"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    seen: list[str] = []
    revision.build(project, project.working, progress=seen.append)
    assert not any("UNTRACKED" in s for s in seen), seen


def test_build_no_longer_advises_a_path_that_does_not_exist(project,
                                                            monkeypatch):
    """"Author this batch by hand instead" named no supported path —
    `tracked.build` IS the Compare wrapper. The refusal now says what is
    true: this batch has no reviewable redline."""
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=5))
    with pytest.raises(MathResolved) as exc:
        revision.build(project, project.working)
    assert "no reviewable redline" in str(exc.value).lower()


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


@pytest.mark.parametrize("edit", [
    "the author's own edit", "aaa", "zzz", "a much longer sentence the "
    "author typed into the manuscript while the batch was building", "0",
])
def test_the_stale_guard_does_not_depend_on_how_two_HASHES_SORT(project,
                                                                edit):
    """`live_hash != base_hash` read as `<` still fires for about half
    of all content — whichever half the one fixture happened to land in.
    The guard's property is that ANY difference is refused, and only a
    spread of contents can assert that: these five put the live hash on
    both sides of the baseline's.

    This is the refusal that stands between a batch and an author's
    unsaved work, so "usually catches it" is not the contract.
    """
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run(edit))))
    before = project.working.read_bytes()
    with pytest.raises(StaleBatch):
        revision.promote(project)
    assert project.working.read_bytes() == before


def test_promote_refuses_when_the_RESCUE_copy_did_not_land(project,
                                                           monkeypatch):
    """A post-condition that never fires in a happy path, and so was
    never run: without it, a failed rescue means working.docx is
    overwritten with nothing left to undo it. `!=` read as `<` passes
    half the time and this branch is the whole reason the copy is
    checked at all."""
    import shutil

    def _bad(src, dst, *a, **k):
        Path(dst).write_bytes(b"not the file")
        return dst

    write(project.batch, make_parts(para(run("the batch"))))
    before = project.working.read_bytes()
    monkeypatch.setattr(shutil, "copy2", _bad)
    with pytest.raises(ProtocolError, match="rescue copy did not land"):
        revision.promote(project)
    assert project.working.read_bytes() == before, \
        "the live file was overwritten with no rescue behind it"


@pytest.mark.parametrize("landed", [b"half a file", b"a", b"zzzz", b""])
def test_promote_refuses_when_the_PROMOTE_itself_did_not_land(
        project, monkeypatch, landed):
    """The same for the copy onto working.docx — and parametrised for
    the same reason as the stale guard: `!=` read as an ordering still
    fires for whichever half of all content the one fixture landed in.
    The rescue must still be made by the real routine, or the check
    above this one fires instead and proves nothing about this one."""
    import shutil
    real = shutil.copyfile

    def _bad_onto_live(src, dst, *a, **k):
        if Path(dst) == project.working:
            Path(dst).write_bytes(landed)
            return dst
        return real(src, dst, *a, **k)

    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setattr(shutil, "copyfile", _bad_onto_live)
    with pytest.raises(ProtocolError, match="copy did not land"):
        revision.promote(project)


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
    assert stamped.name == "working_rescue_20260807-215403-000000.docx"


def test_same_moment_names_keep_their_order(project):
    """The regression that a real run found. The first version appended
    '-2' on collision, and '-' sorts BEFORE '.', so '…215403-2.docx' came
    before '…215403.docx' — the oldest copy reading as the newest, and
    prune deleting from the wrong end.
    """
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    moment = datetime(2026, 8, 7, 21, 54, 3)
    written = []
    for _ in range(7):                       # seven promotes, one second
        p = revision.rescue_path(project, moment)
        p.write_bytes(b"x")
        written.append(p)

    assert len({p.name for p in written}) == 7, "two promotes collided"
    assert len({len(p.name) for p in written}) == 1, \
        "names differ in width, so sorting them is not chronological"
    assert revision.rescues(project) == written, \
        "listed order does not match the order they were written"

    revision.prune_rescues(project, keep=2)
    assert revision.rescues(project) == written[-2:], \
        "prune kept the wrong end"


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


def test_validate_fails_on_a_part_the_batch_lost(tmp_path):
    """The reject-all gate proves the TEXT round-trips; nothing proved
    the PACKAGE did. Word's Compare drops the customXml data store on
    every rebuild and `promote` copies the batch over working.docx, so
    the loss reaches the live manuscript with lint clean, validate
    PASSing and Word opening the file happily (2026-08-12)."""
    base_parts = make_parts(para(run("settled text")))
    base_parts["customXml/item1.xml"] = (
        b'<b:Sources xmlns:b="http://schemas.openxmlformats.org'
        b'/officeDocument/2006/bibliography"/>')
    base_parts["docProps/app.xml"] = b"<Properties/>"
    baseline_path = write(tmp_path / "prev.docx", base_parts)

    without = {k: v for k, v in base_parts.items()
               if not k.startswith(("customXml/", "docProps/"))}
    batch = write(tmp_path / "batch.docx", without)
    report = revision.validate(batch, baseline_path, use_word=False)
    # docProps is Word's own bookkeeping and says nothing
    assert report.lost_parts == ["customXml/item1.xml"]
    assert report.reject_matches_baseline is True, "the TEXT is intact"
    assert not report.ok


def test_validate_reject_all_counts_the_LINKS(tmp_path):
    """Rejecting a batch that deleted linked text gives the words back
    as PLAIN TEXT: Word's Compare does not rebuild a hyperlink inside a
    rejected deletion. Parental Style T4(3) came back 227 links against
    the baseline's 229 with reject-all reporting OK, `citations` ALL
    CHECKS PASSED (later mentions, so nothing dangled), and the author
    two links short with nothing anywhere saying so (2026-08-12)."""
    linked = ('<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
              "</w:r></w:hyperlink>")
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("see"), linked, run("for detail"))))
    # the same words, the link gone: every existing arm of the gate is
    # satisfied, because paragraphs and glyphs both compare TEXT
    unlinked = write(tmp_path / "batch.docx", make_parts(
        para(run("see"), run("Table 5"), run("for detail"))))
    report = revision.validate(unlinked, baseline_path, use_word=False)
    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.reject_detail["links"] is False
    assert not report.ok
    assert report.lost_links and "Table5" in report.lost_links[0]


def test_a_link_the_baseline_never_had_is_also_a_mismatch(tmp_path):
    """`was == now`, not `was <= now`. The multiset comparison has to
    fail in BOTH directions. `link_crossrefs` writes its hyperlinks
    UNTRACKED, so a batch run through it comes back from reject-all with
    links the baseline never had — same words, same paragraphs, and a
    document that is no longer the accepted truth. Under `<=` the gate
    calls the extra links fine and the batch becomes the new baseline
    with the untracked edit inside it."""
    plain = write(tmp_path / "prev.docx", make_parts(
        para(run("see"), run("Table 5"), run("for detail"))))
    # the same words, now linked, and nothing marking the change
    linked = write(tmp_path / "batch.docx", make_parts(
        para(run("see"),
             '<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
             "</w:r></w:hyperlink>",
             run("for detail"))))
    report = revision.validate(linked, plain, use_word=False)
    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.reject_detail["links"] is False
    assert not report.ok


def test_the_link_count_is_blind_to_which_FORM_a_link_takes(tmp_path):
    """Word rewrites a field into an element on every author save, so a
    gate that told the two apart would fail on a document nobody
    changed."""
    from docxkit.citations import hyperlink_field

    element = ('<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
               "</w:r></w:hyperlink>")
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("see"), element)))
    as_field = write(tmp_path / "batch.docx", make_parts(
        para(run("see"), hyperlink_field("Table5", "Table 5"))))
    report = revision.validate(as_field, baseline_path, use_word=False)
    assert report.reject_detail["links"] is True, report.reject_detail


def test_validate_checks_footnotes_too(tmp_path):
    """A batch may be faithful in the body and lossy in a footnote."""
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("note")))))
    lossy = write(tmp_path / "batch.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("nope")))))
    report = revision.validate(lossy, baseline_path, use_word=False)
    assert report.reject_detail["footnotes"] is False
    assert not report.ok


# ----------------------------------- what gate 5 disagreed about --------
#
# `{'paragraphs': False, 'glyphs': False, 'footnotes': False} -> MISMATCH`
# is three booleans, and the decision waiting on them is whether the
# batch is salvageable or has to ship clean. Finding that out cost a
# bespoke difflib script on Parental Style, 2026-08-10.


def test_gate_5_names_the_paragraphs_it_disagrees_on(tmp_path):
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("settled one")) + para(run("settled two"))))
    lossy = write(tmp_path / "lossy.docx", make_parts(
        para(run("settled one")) + para(run("quietly rewritten"))))
    report = revision.validate(lossy, baseline_path, use_word=False)
    assert not report.ok
    got = report.reject_diff
    assert len(got) == 1, got
    assert got[0].part == "body" and got[0].index == 1
    assert got[0].baseline == "settled two"
    assert got[0].batch == "quietly rewritten"
    assert "quietly rewritten" in str(got[0])


def test_a_faithful_batch_is_asked_for_no_diagnosis(tmp_path):
    """The work only happens on failure — the gate runs on every batch."""
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("settled text"))))
    faithful = write(tmp_path / "batch.docx", make_parts(
        para(run("settled text"), ins("added"))))
    report = revision.validate(faithful, baseline_path, use_word=False)
    assert report.reject_diff == [] and report.moved_footnotes == []


def _notes(body: str, baseline_body: str):
    """(batch parts, baseline parts) differing only in footnote 2."""
    return (make_parts(para(run("body")), footnotes=footnotes_part(body)),
            make_parts(para(run("body")),
                       footnotes=footnotes_part(baseline_body)))


def test_a_moved_footnote_anchor_is_named(tmp_path):
    """Compare treats a re-anchored footnote as brand new: one w:ins over
    the whole body with no w:del. Accepting is right, rejecting empties
    it — and gate 5 could only say `footnotes: False`."""
    batch, base = _notes(para(ins("the note text")),
                         para(run("the note text")))
    assert revision.moved_footnotes(batch, base) == [2]
    # and the gate carries it through
    report = revision.validate(
        write(tmp_path / "batch.docx", batch),
        write(tmp_path / "prev.docx", base), use_word=False)
    assert report.reject_detail["footnotes"] is False
    assert report.moved_footnotes == [2], report.moved_footnotes


def test_a_moved_footnote_numbered_ONE_is_named_too():
    """`nid < 1` — the separator notes Word writes carry ids 0 and -1,
    and note 1 is a real footnote. Under `<= 1` a paper's FIRST note is
    the one finding this check cannot make, and it is the note most
    likely to move: the one on the title page or the first page of the
    text."""
    one = ('<?xml version="1.0"?><w:footnotes xmlns:w="http://schemas.'
           'openxmlformats.org/wordprocessingml/2006/main" xmlns:w14='
           '"http://schemas.microsoft.com/office/word/2010/wordml">'
           '<w:footnote w:id="1">{body}</w:footnote></w:footnotes>')
    batch = make_parts(para(run("body")),
                       footnotes=one.format(body=para(ins("the note text"))))
    base = make_parts(para(run("body")),
                      footnotes=one.format(body=para(run("the note text"))))

    assert revision.moved_footnotes(batch, base) == [1]


def test_an_ordinary_footnote_edit_is_not_called_a_moved_anchor():
    """Insertions AND deletions is someone editing the note, which
    rejects cleanly. Naming it would send a reader hunting for a moved
    reference that never moved."""
    batch, base = _notes(para(dele("old text") + ins("new text")),
                         para(run("old text")))
    assert revision.moved_footnotes(batch, base) == []


def test_a_genuinely_new_footnote_is_not_called_a_moved_anchor():
    """A note this batch ADDED is all insertion and no deletion too, and
    rejecting it is supposed to remove it. The baseline is what tells
    the two apart."""
    batch, base = _notes(para(ins("a brand new note")), para(run("")))
    assert revision.moved_footnotes(batch, base) == []


@pytest.mark.parametrize("baseline,batch", [
    ("body", "aaaa"),          # the batch sorts BEFORE the baseline
    ("body", "zzzz"),          # and after it
])
def test_gate_5_compares_for_EQUALITY_not_for_order(tmp_path, baseline,
                                                    batch):
    """`_paras(rejected) == _paras(base)` read as `>=` is True whenever
    the batch happens to sort later, so half of all lossy batches pass.
    The existing fixtures all sorted one way. This gate is what proves a
    batch is reviewable at all — a false OK here ships something the
    author cannot reject."""
    base = write(tmp_path / f"prev_{batch}.docx",
                 make_parts(para(run(baseline))))
    lossy = write(tmp_path / f"batch_{batch}.docx",
                  make_parts(para(run(batch))))
    report = revision.validate(lossy, base, use_word=False)
    assert report.reject_detail["paragraphs"] is False
    assert report.reject_detail["glyphs"] is False
    assert not report.ok


def test_gate_5_compares_the_FOOTNOTES_for_equality_too(tmp_path):
    base = write(tmp_path / "prev.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("aaa")))))
    lossy = write(tmp_path / "batch.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("zzz")))))
    report = revision.validate(lossy, base, use_word=False)
    assert report.reject_detail["footnotes"] is False


def test_the_main_story_walk_does_not_stop_at_a_text_box(tmp_path,
                                                         monkeypatch):
    """The `continue` that skips a text box, read as `break`, ends the
    walk there — so every word AFTER the box vanishes from the stream
    and gate 6 reports a mismatch on a document with nothing wrong. The
    existing fixture put the box last, where the two are the same."""
    body = (para(run("Before the box."))
            + para(f"<w:r><w:pict><w:txbxContent>{para(run('BOXED'))}"
                   f"</w:txbxContent></w:pict></w:r>")
            + para(run("After the box.")))
    path = write(tmp_path / "box.docx", make_parts(body))
    rendered = _FakeDoc(revisions=0,
                        text="Before the box.\rAfter the box.\r")
    monkeypatch.setattr(revision, "_word", _FakeWord(rendered))
    assert revision.validate(path).accept_paths_agree is True


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


def test_validate_folds_the_math_asterisk(tmp_path, monkeypatch):
    """Word sets an asterisk inside math as U+2217 ASTERISK OPERATOR, and
    NFKC leaves it alone — the two are distinct characters, not
    compatibility variants. LI7 writes "T*" eighteen times, so gate 6
    failed there on a file holding ZERO revisions."""
    path = write(tmp_path / "t.docx", make_parts(para(run("T* is the age"))))
    rendered = _FakeDoc(revisions=0, text="T∗ is the age\r")
    monkeypatch.setattr(revision, "_word", _FakeWord(rendered))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_folds_the_derivative_prime(tmp_path, monkeypatch):
    """Word returns U+2032 PRIME where the XML stores U+0027 APOSTROPHE in
    derivative notation. Parental_style writes V', S' and a^E'(x) through
    its theory section, so gate 6 failed there on a file holding ZERO
    revisions — the same shape as the T* case."""
    path = write(tmp_path / "p.docx", make_parts(para(run("V' is the value"))))
    rendered = _FakeDoc(revisions=0, text="V′ is the value\r")
    monkeypatch.setattr(revision, "_word", _FakeWord(rendered))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_still_sees_a_real_difference_in_math(tmp_path, monkeypatch):
    """The folds must not blind the gate: a character Word did not merely
    RENDER differently is still a mismatch."""
    path = write(tmp_path / "t.docx", make_parts(para(run("T* is the age"))))
    different = _FakeDoc(revisions=0, text="T+ is the age\r")
    monkeypatch.setattr(revision, "_word", _FakeWord(different))
    assert revision.validate(path).accept_paths_agree is False


NS_WP = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
         'wordprocessingDrawing"')


def picture(kind: str = "inline") -> str:
    """A figure, inline (in the text stream) or anchored (floating)."""
    return (f"<w:r><w:drawing {NS_WP}><wp:{kind}>"
            f'<wp:extent cx="457200" cy="457200"/>'
            f"</wp:{kind}></w:drawing></w:r>")


def test_validate_counts_an_inline_figure_as_word_does(tmp_path,
                                                       monkeypatch):
    """Word's Range.Text puts a SOLIDUS where an inline drawing sits —
    measured, on a package whose only content was a picture and two
    letters. `_glyph` collected `w:t`/`m:t` and contributed nothing
    there, so gate 6 reported one difference per figure on a document
    holding ZERO revisions."""
    path = write(tmp_path / "fig.docx",
                 make_parts(para(run("A"), picture(), run("B"))))
    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="A/B\r")))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_gives_a_floating_figure_no_character(tmp_path,
                                                       monkeypatch):
    """The other half of the same measurement: an ANCHORED drawing is
    not in the text stream, and Word returns nothing for it. Emitting a
    placeholder for every `w:drawing` alike would fail here."""
    path = write(tmp_path / "float.docx",
                 make_parts(para(run("E"), picture("anchor"), run("F"))))
    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="EF\r")))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_still_sees_a_slash_the_author_typed(tmp_path,
                                                      monkeypatch):
    """Why this is a placeholder and not a `_FOLD` entry: folding the
    solidus away would blind the gate to every "and/or" and every URL in
    the manuscript."""
    path = write(tmp_path / "s.docx", make_parts(para(run("and/or"))))
    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="and or\r")))
    assert revision.validate(path).accept_paths_agree is False


def test_validate_does_not_compare_a_text_box_against_the_body(tmp_path,
                                                               monkeypatch):
    """A text box is a separate STORY: its prose sits in document.xml
    like any other paragraph, and `doc.Paragraphs` does not walk it. Left
    in the stream, the gate reports a difference for every text box."""
    body = para(run("Body prose."),
                f"<w:r><w:pict><w:txbxContent>{para(run('BOXED'))}"
                f"</w:txbxContent></w:pict></w:r>")
    path = write(tmp_path / "box.docx", make_parts(body))
    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="Body prose.\r")))
    assert revision.validate(path).accept_paths_agree is True


def test_reject_all_notices_a_figure_the_batch_dropped(tmp_path):
    """Gate 5 compares paragraph text and the glyph stream, and a lost
    figure changes neither — until the stream counts figures. The
    reject-all gate is what proves a batch is fully reviewable."""
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("A"), picture(), run("B"))))
    lost = write(tmp_path / "batch.docx", make_parts(para(run("A"), run("B"))))
    report = revision.validate(lost, baseline_path, use_word=False)
    assert report.reject_detail["paragraphs"] is True, "text alone is blind"
    assert report.reject_detail["glyphs"] is False
    assert not report.ok


@pytest.mark.parametrize("rendered", ["T+ is the age", "T( is the age"])
def test_gate_6_compares_for_EQUALITY_not_for_order(tmp_path, monkeypatch,
                                                    rendered):
    """`_norm(...) == _norm(...)` read as `>=` is True whenever the XML
    side happens to sort later, so half of all real disagreements pass.
    The one existing mismatch fixture sorted the other way — these two
    put the XML on both sides of Word's answer."""
    path = write(tmp_path / "t.docx", make_parts(para(run("T* is the age"))))
    monkeypatch.setattr(revision, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text=rendered)))
    assert revision.validate(path).accept_paths_agree is False


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
    parsing English.

    These five numbers are a contract with things outside this package:
    the paper projects' scripts branch on them, `docxkit revision
    status` documents 1 for pending and 4 for a stale baseline in its
    own `--help`, and `cli.main` exits with whatever the exception
    carries. A renumbering is invisible here and wrong out there.
    """
    from docxkit.errors import HandbackLoss

    assert ProtocolError.exit_code == 1
    assert MathResolved.exit_code == 2
    assert BaselinePending.exit_code == 3
    assert StaleBatch.exit_code == 4
    assert HandbackLoss.exit_code == 5

    codes = [cls.exit_code for cls in (ProtocolError, MathResolved,
                                       BaselinePending, StaleBatch,
                                       HandbackLoss)]
    assert len(set(codes)) == len(codes), "two refusals cannot share one"
    assert 0 not in codes, "0 is success; a refusal that exits 0 is silent"


def test_document_helper_is_used():
    """conftest.document is the fixture builder these tests lean on."""
    assert "<w:body>" in document("")


def test_a_rescue_that_did_not_land_stops_the_promote(project,
                                                      monkeypatch):
    """The guard that makes the undo real. If the rescue copy is not
    what it was copied from, overwriting the manuscript would leave
    nothing to undo it with — so the promote refuses instead."""
    write(project.batch, make_parts(para(run("the batch"))))
    live_before = project.working.read_bytes()

    def truncating_copy(src, dst, *a, **kw):
        Path(dst).write_bytes(b"truncated")
        return dst

    monkeypatch.setattr(revision.shutil, "copy2", truncating_copy)
    with pytest.raises(ProtocolError, match="nothing to undo it"):
        revision.promote(project)
    assert project.working.read_bytes() == live_before, \
        "the manuscript was overwritten despite a bad rescue"


def test_rescue_names_cannot_be_exhausted_silently(project, monkeypatch):
    """Bounded, and it says so rather than looping forever. Forced here
    by coarsening the stamp so every candidate collides."""
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(revision, "_RESCUE_STAMP", "%Y%m%d")
    taken = revision.rescue_path(project, datetime(2026, 8, 7))
    taken.write_bytes(b"x")
    with pytest.raises(ProtocolError, match="no free rescue name"):
        revision.rescue_path(project, datetime(2026, 8, 7))


# ------------------------- what a redline cannot carry, and what it is not

def test_a_bookmark_the_clean_edit_removed_is_reported_as_restored():
    """Compare carries bookmarks over from the ORIGINAL side, so a
    deletion made in the clean copy is silently undone — and nothing in
    the counts shows it, because a bookmark is not tracked content. The
    orphan `Lari2023` survived two full rounds that way."""
    marked = ('<w:bookmarkStart w:id="4" w:name="Lari2023"/>'
              '<w:bookmarkEnd w:id="4"/>')
    baseline = make_parts(para(marked + run("Lari, A. (2023). Title.")))
    clean = make_parts(para(run("Lari, A. (2023). Title.")))
    built = make_parts(para(marked + run("Lari, A. (2023). Title.")))
    assert revision.restored_bookmarks(baseline, clean, built) == ["Lari2023"]


def test_a_bookmark_the_clean_edit_kept_is_not_reported():
    marked = ('<w:bookmarkStart w:id="4" w:name="Lari2023"/>'
              '<w:bookmarkEnd w:id="4"/>')
    parts = make_parts(para(marked + run("Lari, A. (2023). Title.")))
    assert revision.restored_bookmarks(parts, parts, parts) == []


def test_words_own_navigation_bookmarks_are_not_reported():
    """`_Toc` and `_Heading` names are Word's, they come and go on every
    save, and a report full of them is a report nobody reads."""
    tocd = ('<w:bookmarkStart w:id="4" w:name="_Toc12345"/>'
            '<w:bookmarkEnd w:id="4"/>')
    baseline = make_parts(para(tocd + run("A heading")))
    clean = make_parts(para(run("A heading")))
    assert revision.restored_bookmarks(baseline, clean, baseline) == []


def test_build_refuses_to_read_the_path_it_writes(project, monkeypatch):
    """`build/batch.docx` is where a batch is STAGED, and the provenance
    stamp beside it is how `guard.check` tells "docxkit wrote this" from
    "someone edited it in Word". A hand-built clean edit written there
    made the build refuse its own output as modified, and the message
    named a Word session that never happened."""
    write(project.batch, make_parts(para(run("a hand-built clean edit"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    with pytest.raises(ProtocolError, match="STAGES its output"):
        revision.build(project, project.batch)


def test_build_says_which_bookmark_compare_put_back(project, monkeypatch):
    """The build-time half: said before the handback, where the author
    can still be told the deletion has to wait for the promote."""
    marked = ('<w:bookmarkStart w:id="4" w:name="Lari2023"/>'
              '<w:bookmarkEnd w:id="4"/>')
    write(project.prev, make_parts(para(marked + run("Lari, A. (2023)."))))
    clean = project.build_dir / "clean.docx"
    write(clean, make_parts(para(run("Lari, A. (2023)."))))
    # the fake stands in for Compare, and Compare's behaviour here IS
    # the bug: it writes the baseline's bookmarks back out
    monkeypatch.setattr(
        revision.tracked, "build",
        _FakeBuild(out_text="Lari, A. (2023).", extra=marked))
    seen: list[str] = []
    revision.build(project, clean, progress=seen.append)
    said = "\n".join(seen)
    assert "Lari2023" in said and "AFTER the promote" in said


def test_a_bookmark_the_BUILD_invented_is_not_the_authors_deletion():
    """"in the build, not in the clean edit" also describes a name Word
    minted during the compare. Reporting that as a deletion the author
    made sends them looking for an edit that never happened, so the
    baseline is what decides."""
    minted = ('<w:bookmarkStart w:id="4" w:name="Compare_Mint1"/>'
              '<w:bookmarkEnd w:id="4"/>')
    baseline = make_parts(para(run("Lari, A. (2023). Title.")))
    clean = make_parts(para(run("Lari, A. (2023). Title.")))
    built = make_parts(para(minted + run("Lari, A. (2023). Title.")))
    assert revision.restored_bookmarks(baseline, clean, built) == []


# ------------------------------------- the gate that could not be passed --

#: LI7 2026-08-15, BLOCKING. Gate D4 split section 6 in two, so footnote
#: 13's cross-reference "throughout Sections 4-6" became "4-7" — one
#: character in a 489-character note. The loss check compared note TEXT,
#: so the old wording had "vanished"; `baseline` refused to record a
#: manuscript that had lost nothing, and every documented form of
#: --accept-loss came back "has NOT lost" about the same string. The
#: refusal path and the exemption path were computing "lost" differently
#: and between them there was no way through.

_NOTE = ("For interpretability, empirical LII and LBI values throughout "
         "Sections 4{}6 are reported on the same scale as the headline "
         "index, so a reader comparing two panels is comparing like with "
         "like rather than two normalisations of the same quantity.")


def _with_note(text: str) -> dict[str, bytes]:
    return make_parts(para(run("body "), _ref(13)),
                      footnotes=notes("footnotes", note(text, nid=13)))


def _ref(nid: int) -> str:
    return f'<w:r><w:footnoteReference w:id="{nid}"/></w:r>'


def test_an_EDITED_footnote_is_not_a_lost_one(project):
    """A note is prose an author edits. Its identity is its REFERENCE,
    which is still in the body — not its text, which is the thing that
    changed."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, _with_note(_NOTE.format("–7")))

    assert revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev)) == []
    revision.baseline(project)          # the whole point: it goes through
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_a_note_that_really_went_is_still_caught(project):
    """The fix must not switch the gate off: fewer notes than before,
    with a reference gone, is still a loss."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))
    assert [loss.kind for loss in lost] == ["footnote"]
    with pytest.raises(HandbackLoss):
        revision.baseline(project)


def test_the_exemption_accepts_the_words_the_refusal_PRINTED(project):
    """A hatch that will not accept the message's own words is not a
    hatch. The refusal truncates for readability; the flag must take
    that truncation."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))

    with pytest.raises(HandbackLoss) as exc:
        revision.baseline(project)
    shown = re.search(r"--accept-loss '([^']+)'", str(exc.value))
    assert shown is not None, str(exc.value)

    revision.baseline(project, accept_loss=(shown.group(1),))
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_a_PREFIX_of_the_loss_identifies_it(project):
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))
    revision.baseline(project, accept_loss=("footnote:For interpretability",))
    assert project.prev.read_bytes() == project.working.read_bytes()



# ---------------------------------------------- naming the glyph that moved --
#
# The glyph gate compared two streams of 68,829 characters and answered
# `glyphs: False`. On AFI the answer was TWO characters — a minus sign
# Word's Compare had rewritten as a hyphen inside an Appendix equation —
# and finding them took a bespoke difflib script over private imports,
# three builds after the gate first went red.

def test_two_identical_streams_have_nothing_to_report():
    assert glyph_runs("the same", "the same") == []


def test_a_swapped_MINUS_is_named_with_its_code_points():
    """The finding, exactly as it happened: a hyphen-minus and a minus
    sign print identically at 10pt, so the characters have to be spelled
    out or the reader learns nothing they did not already know."""
    was = "AFIi,2020 − AFIi,1990"
    now = "AFIi,2020 - AFIi,1990"

    run, = glyph_runs(was, now)

    assert "U+2212" in run and "U+002D" in run
    assert run.startswith("at 10: ")


def test_the_offset_is_the_BASELINE_stream_not_the_batch():
    """One number, and it has to mean one document: the baseline is the
    reference the batch is being held against, so it is the side both
    the offset and the quoted context come from."""
    was = "the estimator is − 0.15"
    now = "in fact the estimator is - 0.15"

    _inserted, swapped = glyph_runs(was, now)

    # 17 in the baseline, 25 in the batch, which now opens with 8 more
    # characters — and the reader is holding the baseline
    assert swapped.startswith("at 17: ")
    assert swapped.endswith("after ...the estimator is ")


def test_a_run_says_WHERE_it_is_by_quoting_what_precedes_it():
    """An offset into a 68,000-character stream is not a location a
    reader can act on; the words before it are."""
    was = "in the pooled sample the estimator is − 0.15 everywhere"
    now = "in the pooled sample the estimator is - 0.15 everywhere"

    run, = glyph_runs(was, now)

    lead = run.split("after ...")[1]
    assert lead == "he pooled sample the estimator is "[-24:]
    assert len(lead) == 24              # twenty-four characters of it


def test_the_quoted_CONTEXT_reads_as_one_line():
    """The glyph stream is the whole document run together, so the
    characters before a run routinely include a paragraph break; left
    raw it breaks the report into pieces that no longer line up."""
    was = "para one\nthe value is − 0.15"
    now = "para one\nthe value is - 0.15"

    run, = glyph_runs(was, now)

    assert "\n" not in run
    assert run.endswith("after ...para one the value is ")


def test_a_LONG_changed_run_is_cut_not_dumped():
    """A batch that really did lose a paragraph would otherwise print
    the paragraph, once per gate, above the instruction that matters."""
    was = "keep " + "a long stretch of prose that vanished " * 3 + "keep"
    now = "keep keep"

    run, = glyph_runs(was, now)

    assert run.count("...") >= 1
    assert len(run) < 120


def test_the_number_of_runs_is_CAPPED_and_the_rest_counted():
    was = "".join(f"{i}x" for i in range(20))
    now = "".join(f"{i}y" for i in range(20))

    runs = glyph_runs(was, now, limit=3)

    assert len(runs) == 4
    assert runs[-1] == "... and 17 more run(s)"


def test_a_CHARACTER_COUNT_is_not_printed_for_a_long_run():
    """Code points are printed for short runs only — four or fewer.
    Spelling out a hundred of them is the dump this avoids."""
    runs = glyph_runs("abcdefgh", "")

    assert "U+" not in runs[0]


def test_an_INSERTED_run_reports_an_empty_left_side():
    runs = glyph_runs("ab", "aXb")

    assert runs[0].startswith("at 1: '' -> 'X' U+0058")


# --- what the revision.py run of 2026-08-18 found -----------------------
#
# `_shown` had 4 survivors, all on its two thresholds. It is the half of
# a glyph report a reader acts on — the characters themselves, and their
# code points when the run is short enough for them to mean anything —
# and the tests above only ever gave it a one-character run, where every
# threshold agrees.


def test_a_run_is_quoted_whole_at_TWELVE_characters_and_cut_after():
    """Twelve is what fits beside the offset and the context on one
    line, and the cut has to be visible: a run quoted whole that is not
    whole tells a reader the difference is shorter than it is."""
    def quoted(n: int) -> str:
        was = "a" * n + " tail"
        return glyph_runs(was, was.upper())[0]

    assert "'" + "a" * 12 + "'" in quoted(12), "twelve is not cut"
    assert "'" + "a" * 12 + "...'" in quoted(13)
    assert "a" * 13 not in quoted(13)


def test_the_CODE_POINTS_are_printed_only_for_a_short_run():
    """A hyphen-minus and a MINUS SIGN print identically at 10pt, so for
    a run of one or two characters the code points ARE the finding. Past
    four they are a wall of hex either side of an arrow, and the
    characters are legible on their own."""
    four = glyph_runs("abcd tail", "wxyz tail")[0]
    five = glyph_runs("abcde tail", "vwxyz tail")[0]

    assert "U+0061 U+0062 U+0063 U+0064" in four
    assert "U+0077" in four, "and for the batch's side too"
    assert "U+" not in five


def test_nothing_is_spelled_out_for_a_run_with_no_characters():
    """`0 < len(cut)`: an insertion has an empty side, and `U+` with
    nothing after it is a report of a character that is not there."""
    (run,) = glyph_runs("the value is 0.15", "the value is − 0.15")

    assert "'' ->" in run, "the empty side spells out nothing at all"
    assert run.count("U+") == 2, "and the two characters added do"


def test_validate_reject_all_counts_the_STRUCTURE(tmp_path):
    """The fifth thing gate 5 compares, and the one it was blind to on
    the DSI round of 2026-08-19: a table DUPLICATED by a move (27 -> 28
    in the accepted and the rejected view alike), a moved paragraph's
    three citation bookmarks dropped on reject (127 -> 125), and a
    destroyed section break. None of them is a character, so paragraphs,
    glyphs, footnotes and links all said yes.

    The fixture is the same words in a different carrier: one paragraph
    of prose, wrapped in a table. Every text arm of the gate passes."""
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("The index rose to 0.35 in 2024."))))
    in_a_table = write(tmp_path / "batch.docx", make_parts(
        "<w:tbl><w:tr><w:tc>"
        + para(run("The index rose to 0.35 in 2024."))
        + "</w:tc></w:tr></w:tbl>"))

    report = revision.validate(in_a_table, baseline_path, use_word=False)

    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.reject_detail["links"] is True
    assert report.reject_detail["structure"] is False
    assert not report.ok
    assert report.structure_diff == ["tbl: 0 -> 1", "tr: 0 -> 1",
                                     "tc: 0 -> 1"]


def test_the_structure_gate_names_a_BOOKMARK_the_reject_dropped(tmp_path):
    """The second casualty of the same mechanism: a moved paragraph
    carrying three citation anchors comes back through Compare with the
    anchors gone. `reject-all == baseline` passed, and the paper's
    `require_reject_all_equals_baseline` was satisfied by a document
    that does not reproduce the baseline."""
    anchored = ('<w:bookmarkStart w:id="9" w:name="Moran1950"/>'
                + run("Moran (1950)") + '<w:bookmarkEnd w:id="9"/>')
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("As ", preserve=True), anchored,
             run(" showed.", preserve=True))))
    stripped = write(tmp_path / "batch.docx", make_parts(
        para(run("As ", preserve=True), run("Moran (1950)"),
             run(" showed.", preserve=True))))

    report = revision.validate(stripped, baseline_path, use_word=False)

    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.structure_diff == ["bookmarkStart: 1 -> 0"]


def test_the_structure_gate_is_blind_to_which_FORM_a_link_takes(tmp_path):
    """`w:hyperlink` is deliberately NOT counted. Word rewrites a
    caption's HYPERLINK FIELD into an element on an ordinary edit — DSI
    saw 16 -> 17 with nothing lost — and a gate that counted elements
    would fail on that. `_links` compares (anchor, label) across both
    forms, which is the comparison that means something."""
    from docxkit.citations import hyperlink_field
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("see ", preserve=True),
             hyperlink_field("Table5", "Table 5"))))
    as_element = write(tmp_path / "batch.docx", make_parts(
        para(run("see ", preserve=True),
             '<w:hyperlink w:anchor="Table5">' + run("Table 5")
             + "</w:hyperlink>")))

    report = revision.validate(as_element, baseline_path, use_word=False)

    assert report.reject_detail["structure"] is True
    assert report.reject_detail["links"] is True


# --- what the loss walk COUNTS (2026-08-19) -----------------------------
#
# `losses` is the gate between a hand-back and the baseline, and its
# arithmetic had 11 survivors across `losses` and `_lost_notes`. The
# tests above ask whether the gate fires, which is the right question
# and answers only half of it: a gate that fires on the right document
# and says the wrong thing about it sends a person looking for a note
# that never went.

def _notes_doc(*texts: str, refs: int = 0) -> dict[str, bytes]:
    """A body carrying `refs` markers and one footnote per text."""
    body = "".join(_ref(i + 13) for i in range(refs or len(texts)))
    return make_parts(
        para(run("body "), body),
        footnotes=notes("footnotes", *(note(t, nid=i + 13)
                                       for i, t in enumerate(texts))))


def test_two_notes_gone_and_one_of_them_UNNAMEABLE_says_so(project):
    """`len(named) < gone`, and the count in the sentence. Two notes of
    the same wording — "Ibid." is the ordinary one — cannot be told
    apart by text, so when one of them goes the walk can name the OTHER
    loss and only count this one. Saying "1 more, unnamed" and giving
    both totals is what lets a person check by hand; naming a note that
    is still there sends them looking for it."""
    write(project.prev, _notes_doc("Ibid.", "Ibid.", "A note that went."))
    write(project.working, _notes_doc("Ibid."))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [loss.what for loss in lost] == [
        "A note that went.",
        "1 more, unnamed — 3 footnotes before, 1 now"]


# --- a RE-LABELLED link is not a lost one (BACKLOG S3, 2026-08-19) ------
#
# `_links` keys a link by the (anchor, label) pair, which is right for
# finding a link Word ate and wrong for an author's own edit of the
# visible text. DSI's R24.1 re-labelled four back-link fields on purpose
# and `baseline` refused four legitimate edits; the paper passed
# --accept-loss four times after checking each anchor by hand. A gate
# that refuses a correct edit teaches the person to wave it through.


def _linked(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}">' + run(label)
            + "</w:hyperlink>")


def test_editing_a_links_VISIBLE_TEXT_is_not_a_loss(tmp_path):
    """The anchor is untouched and still linked, so nothing was lost —
    and `baseline` must not refuse. What changed is reported in its own
    right, because a label that moved is worth seeing."""
    before = write(tmp_path / "prev.docx", make_parts(
        para(run("As "), _linked("UnitedNations2026", "UN 2026"),
             run(" reports."))))
    after = write(tmp_path / "working.docx", make_parts(
        para(run("As "),
             _linked("UnitedNations2026", "United Nations 2026"),
             run(" reports."))))

    lost = revision.losses(package.read_parts(after),
                           package.read_parts(before))
    (change,) = revision.relabelled_links(package.read_parts(after),
                                          package.read_parts(before))

    assert lost == [], lost
    assert change.anchor == "UnitedNations2026"
    assert (change.was, change.now) == ("UN 2026", "United Nations 2026")
    assert "->" in str(change)


def test_a_link_whose_ANCHOR_stopped_being_linked_is_still_a_loss(tmp_path):
    """The half the gate was built for, and the half that still blocks:
    Word collapsed a paragraph to make an edit and the hyperlink went
    with it. Nothing links that anchor any more, so there is no
    re-labelling to explain it."""
    before = write(tmp_path / "prev.docx", make_parts(
        para(run("As "), _linked("UnitedNations2026", "UN 2026"),
             run(" reports."))))
    after = write(tmp_path / "working.docx", make_parts(
        para(run("As UN 2026 reports."))))

    lost = revision.losses(package.read_parts(after),
                           package.read_parts(before))

    assert [loss.kind for loss in lost] == ["link"]
    assert "UnitedNations2026" in lost[0].what
    assert revision.relabelled_links(package.read_parts(after),
                                     package.read_parts(before)) == []


def test_a_link_LOST_beside_one_re_labelled_is_still_counted(tmp_path):
    """Paired off one for one. An anchor linked TWICE that comes back
    once has lost a link, however the survivor is now labelled — read
    the other way, a re-label would absorb the loss and the paragraph
    Word ate would go unreported."""
    before = write(tmp_path / "prev.docx", make_parts(
        para(run("As "), _linked("Table5", "Table 5"), run(" and "),
             _linked("Table5", "the table"), run(" show."))))
    after = write(tmp_path / "working.docx", make_parts(
        para(run("As "), _linked("Table5", "Table 5 (revised)"),
             run(" shows."))))

    lost = revision.losses(package.read_parts(after),
                           package.read_parts(before))
    relabelled = revision.relabelled_links(package.read_parts(after),
                                           package.read_parts(before))

    assert len(relabelled) == 1, relabelled
    assert [loss.kind for loss in lost] == ["link"], lost


def test_baseline_does_not_refuse_a_re_labelled_link(project):
    """The refusal is the whole point of the split: this is the run DSI
    had to talk past with --accept-loss."""
    write(project.prev, make_parts(
        para(run("As "), _linked("UnitedNations2026", "UN 2026"),
             run(" reports."))))
    write(project.working, make_parts(
        para(run("As "),
             _linked("UnitedNations2026", "United Nations 2026"),
             run(" reports."))))

    assert revision.baseline(project) == project.prev


def test_notes_ADDED_while_others_are_reworded_are_not_losses(project):
    """`gone <= 0` — the walk runs only when there are FEWER notes than
    before. An author who rewords three notes and adds a fourth has lost
    nothing, and every reworded note matches nothing by text: under
    `== 0` the walk proceeds on a negative count and reports two of the
    three rewordings as vanished notes, which refuses the baseline."""
    write(project.prev, _notes_doc("First note.", "Second note.",
                                   "Third note."))
    write(project.working, _notes_doc("First note, edited.",
                                      "Second note, edited.",
                                      "Third note, edited.", "A fourth."))

    assert revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev)) == []


def test_a_bookmark_that_SURVIVED_is_not_reported_as_lost(project):
    """`_bookmarks(prev) - _bookmarks(working)`, not `&`: the difference
    is what went, the intersection is what stayed, and the two are the
    same size whenever exactly one of two bookmarks goes."""
    def _marked(*names: str) -> dict[str, bytes]:
        marks = "".join(f'<w:bookmarkStart w:id="{i}" w:name="{n}"/>'
                        f'<w:bookmarkEnd w:id="{i}"/>'
                        for i, n in enumerate(names, start=20))
        return make_parts(para(marks, run("body")))

    write(project.prev, _marked("Kept2020", "Gone2019"))
    write(project.working, _marked("Kept2020"))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [(loss.kind, loss.what) for loss in lost] == [
        ("bookmark", "Gone2019")]


def test_the_number_of_comments_lost_is_the_DIFFERENCE(project):
    """`before - after`, and the message carries the number. Three
    comments against one is two gone; `^` makes it 2 as well on some
    pairs and 4 on others, and nothing but the sentence says which."""
    def _commented(n: int) -> dict[str, bytes]:
        return make_parts(
            para(run("body")),
            comment_items=tuple(comment(i, f"note {i}",
                                        para_id=f"AAAA{i:04d}")
                                for i in range(1, n + 1)))

    write(project.prev, _commented(3))
    write(project.working, _commented(1))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [(loss.kind, loss.what) for loss in lost] == [
        ("comment", "2 comment(s) gone")]


def test_ONE_comment_lost_is_a_loss(project):
    """`> 0`, not `> 1`. One is the ordinary number to lose — a comment
    Word drops while its anchor is being edited — and a threshold of two
    lets it through the gate that makes the baseline permanent."""
    def _commented(n: int) -> dict[str, bytes]:
        return make_parts(
            para(run("body")),
            comment_items=tuple(comment(i, f"note {i}",
                                        para_id=f"AAAA{i:04d}")
                                for i in range(1, n + 1)))

    write(project.prev, _commented(2))
    write(project.working, _commented(1))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [(loss.kind, loss.what) for loss in lost] == [
        ("comment", "1 comment(s) gone")]


def test_comments_ADDED_are_not_a_loss(project):
    """`> 0`, not `!= 0`: an author who answers a query by adding a
    comment would otherwise be told "-1 comment(s) gone" and refused."""
    def _commented(n: int) -> dict[str, bytes]:
        return make_parts(
            para(run("body")),
            comment_items=tuple(comment(i, f"note {i}",
                                        para_id=f"AAAA{i:04d}")
                                for i in range(1, n + 1)))

    write(project.prev, _commented(1))
    write(project.working, _commented(3))

    assert revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev)) == []


def test_a_loss_PRINTS_the_first_seventy_characters_of_what_went():
    """The refusal lists them one per line, and the exemption flag takes
    the message's own words — so the cut is part of the contract with
    the person reading it, not a display detail."""
    long_note = ("The normalisation is by the sample mean rather than by "
                 "the base year, so the two panels are comparable.")

    printed = str(revision.Loss("footnote", long_note))

    assert printed == (
        "footnote 'The normalisation is by the sample mean rather than by "
        "the base year, '")


def test_the_printed_token_is_the_first_SIXTY_characters_of_the_key(project):
    """The refusal prints a token a person can paste back, and it has to
    be short enough to read on the line it shares with the loss. The
    test above reads the token out of the message and feeds it back,
    which is self-consistent whatever the cut is — this one says where
    the cut is."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))

    with pytest.raises(HandbackLoss) as exc:
        revision.baseline(project)

    shown = re.search(r"--accept-loss '([^']+)'", str(exc.value))
    assert shown is not None, str(exc.value)
    assert shown.group(1) == (
        "footnote:For interpretability, empirical LII and LBI values ")


@pytest.mark.parametrize("token", ["aaa-not-this-loss", "zzz-not-this-loss"])
def test_an_exemption_that_names_NOTHING_does_not_pass_a_real_loss(
        project, token):
    """`token == candidate or candidate.startswith(token) or
    token.startswith(candidate)` — three ways of matching, and the first
    is subsumed by the other two. What it must never be is an ORDER
    comparison: under `>=` any token sorting above the loss's key names
    it and under `<=` any token below does, so `--accept-loss` with a
    typo in it acknowledges a lost footnote and the baseline goes
    through. Both directions, because one wrong token can only be on one
    side of the key.

    A stale exemption that reads as a live one is the failure this
    refusal exists to prevent, in its worst form: the flag is misspelled
    and the gate opens."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))
    before = project.prev.read_bytes()

    with pytest.raises(HandbackLoss):
        revision.baseline(project, accept_loss=(token,))

    assert project.prev.read_bytes() == before

# --- the eye gate over a BATCH (BACKLOG S4, 2026-08-19) -----------------


def _pdf_of(text: str, path: Path) -> Path:
    """A one-page PDF carrying `text` — what Word would have rendered."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 200), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def test_render_accepted_renders_the_ACCEPTED_view(tmp_path, monkeypatch):
    """Accepted, never the redline: the page a reader will see is the
    accepted one, and a redline's pagination is not the deliverable's.
    The fake stands in for Word and renders whatever it was handed, so
    what reaches it is the assertion — the insertion's words, with no
    deletion left in."""
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("Employment rises "), ins("sharply"), dele("a little"))))
    seen: dict[str, str] = {}

    def fake_export(path, out_pdf, **kw):
        seen["text"] = "".join(
            re.findall(r"<w:t[^>]*>([^<]*)</w:t>",
                       package.read_parts(path)["word/document.xml"]
                       .decode("utf-8")))
        return _pdf_of(seen["text"], Path(out_pdf))

    monkeypatch.setattr("docxkit.word.export_pdf", fake_export)

    made = revision.render_accepted(batch, ["Employment rises sharply"],
                                    dpi=40)

    assert seen["text"] == "Employment rises sharply", seen
    (png,) = made.values()
    assert png is not None and png.exists()
    assert png.parent == tmp_path, "beside the batch by default"
    assert png.name.startswith("batch__p"), png.name


def test_render_accepted_cleans_up_after_itself(tmp_path, monkeypatch):
    """The accepted copy and the PDF are scratch; the PNGs are the
    answer. A gate that leaves two files per run beside a paper's batch
    is one somebody turns off."""
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("Employment rises "), ins("sharply"))))

    def fake_export(path, out_pdf, **kw):
        return _pdf_of("Employment rises sharply", Path(out_pdf))

    monkeypatch.setattr("docxkit.word.export_pdf", fake_export)

    revision.render_accepted(batch, ["Employment rises"], dpi=40)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert [n for n in left if n.endswith(".pdf")] == []
    assert [n for n in left if "accepted" in n] == []
    assert any(n.endswith(".png") for n in left), left


def test_render_accepted_asks_WORD_for_nothing_when_no_anchor_is_given(
        tmp_path, monkeypatch):
    """`--render` with nothing after it must not start Word: the whole
    step costs a session, a render and a PDF, and the answer is
    empty."""
    batch = write(tmp_path / "batch.docx", make_parts(para(run("prose"))))

    def refuse(*a, **kw):                       # pragma: no cover
        raise AssertionError("Word was started for no anchors")

    monkeypatch.setattr("docxkit.word.export_pdf", refuse)

    assert revision.render_accepted(batch, []) == {}
    assert revision.render_accepted(batch, ["", "  "]) == {}
