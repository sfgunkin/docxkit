"""The CLI's end of the single-file revision protocol.

These commands take almost no arguments: they read ``revision/paper.toml``
and derive every path from it. So what is worth asserting here is that
they find the paper at all, that the exit codes DISTINGUISH the refusals
— a caller must be able to tell which one it hit without parsing English
— and that ``status`` answers the one question the whole layout exists to
answer: is this file the truth, or a proposal someone still has to
adjudicate?

As in test_cli.py, the assertions are on the FILE wherever a file is at
stake. A message is not what an author loses.
"""
from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path

import pytest
from conftest import make_parts, para, run, write
from test_cli import run_cli


@pytest.fixture
def project(tmp_path):
    """A migrated paper, scaffolded the way `revision init` does it."""
    from docxkit import revision
    src = write(tmp_path / "manuscript.docx",
                make_parts(para(run("The paper as it stands."))))
    return revision.init(tmp_path / "proj", src, name="Test Paper")


def _ins(text: str, author: str = "Revision") -> str:
    return (f'<w:ins w:id="90" w:author="{author}" '
            f'w:date="2026-08-07T00:00:00Z">{run(text)}</w:ins>')


FOOTNOTES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
             'wordprocessingml/2006/main" xmlns:w14="http://schemas.'
             'microsoft.com/office/word/2010/wordml">'
             '<w:footnote w:id="2">{body}</w:footnote></w:footnotes>')

NS_M = ('xmlns:m="http://schemas.openxmlformats.org/'
        'officeDocument/2006/math"')


class _Doc:
    """A Word document, faked at the COM boundary."""

    def __init__(self, revisions: int = 1, text: str = "") -> None:
        self.Revisions = type("R", (), {"Count": revisions})()
        self._text = text

    def AcceptAllRevisions(self) -> None:
        pass

    @property
    def Paragraphs(self):
        return [type("P", (), {"Range": type("R", (), {
            "Text": self._text})()})()]


class _Word:
    def __init__(self, doc: _Doc | None = None,
                 explode: bool = False) -> None:
        self.doc, self.explode = doc or _Doc(), explode

    @contextlib.contextmanager
    def session(self, **_kw):
        yield "app"

    @contextlib.contextmanager
    def open_doc(self, _app, _path, **_kw):
        if self.explode:
            raise OSError("Word could not open the file")
        yield self.doc


def _fake_build(math: int = 0, revisions: int = 7):
    """tracked.build, replaced: what Word Compare resolved is an input."""
    from docxkit import tracked

    def build(original, revised, out, classify=None, **kw):
        write(Path(out), make_parts(para(run("redlined"))))
        (kw.get("progress") or (lambda _: None))(
            f"resolved {math} math revisions")
        report = tracked.BuildReport()
        report.revisions = revisions
        return report

    return build


# ----------------------------------------------------------------- init

def test_init_scaffolds_and_copies(monkeypatch, tmp_path, capsys):
    src = write(tmp_path / "LE7.docx", make_parts(para(run("body"))))
    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"), "--name", "LE",
                      "--author", "Agent", "--language", "ru",
                      "--attic", str(tmp_path / "attic"))
    assert code == 0
    assert (tmp_path / "proj" / "revision" / "working.docx").exists()
    assert Path(src).exists(), "the source manuscript was moved, not copied"
    assert "Nothing was moved or deleted" in capsys.readouterr().out


def test_init_refuses_to_rewrite_a_live_config(monkeypatch, project,
                                               capsys):
    """A clean message on stderr, not a traceback."""
    code, _ = run_cli(monkeypatch, "revision", "init",
                      str(project.working), "--root", str(project.root))
    assert code == 1
    assert "already" in capsys.readouterr().err


def test_init_force_rewrites_in_place(monkeypatch, project):
    """Re-running init on a MIGRATED paper, to correct its config: the
    source is working.docx itself, and copying a file onto itself
    raises rather than being a no-op."""
    before = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "init",
                      str(project.working), "--root", str(project.root),
                      "--force")
    assert code == 0
    assert project.working.read_bytes() == before


def test_init_defaults_the_root_to_the_manuscripts_folder(monkeypatch,
                                                          tmp_path):
    src = write(tmp_path / "solo.docx", make_parts(para(run("body"))))
    code, _ = run_cli(monkeypatch, "revision", "init", str(src))
    assert code == 0
    assert (tmp_path / "revision" / "working.docx").exists()


# --------------------------------------------------------------- status

def test_status_answers_truth(monkeypatch, project, capsys):
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "TRUTH" in out
    assert "Test Paper" in out


def test_status_exits_1_on_a_proposal(monkeypatch, project, capsys):
    """A non-zero status is what lets a script refuse to start a batch."""
    write(project.working, make_parts(para(run("x"), _ins("added"))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "PROPOSAL" in out
    assert "by: Revision (1)" in out


def test_status_names_the_part_the_author_cannot_see(monkeypatch, project,
                                                     capsys):
    """Review > Next walks the body only, so "1 pending" sends an author
    hunting through prose for something that lives in a footnote."""
    write(project.working, make_parts(
        para(run("clean body")),
        footnotes=FOOTNOTES.format(body=para(_ins("hidden")))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "footnotes" in out
    assert "Review>Next SKIPS these" in out


def test_status_reports_a_missing_baseline(monkeypatch, project, capsys):
    project.prev.unlink()
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    assert code == 0
    assert "MISSING" in capsys.readouterr().out


def test_a_paper_that_has_not_migrated_says_what_to_do(monkeypatch,
                                                       tmp_path, capsys):
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(tmp_path))
    err = capsys.readouterr().err
    assert code == 1
    assert "has not" in err and "init" in err
    # the message quotes an em dash; stderr must be UTF-8 or the one
    # message whose job is to explain the failure loses characters
    assert "—" in err


# --------------------------------------------------------------- ingest

def test_ingest_on_an_untouched_paper(monkeypatch, project, capsys):
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "no differences" in out


def test_ingest_reports_the_authors_edit(monkeypatch, project, tmp_path,
                                         capsys):
    write(project.working, make_parts(para(run("The paper, reworded."))))
    out_json = tmp_path / "ingest.json"
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root), "--json",
                      str(out_json))
    out = capsys.readouterr().out
    assert code == 0
    assert "no differences" not in out
    # nothing left pending, so the next step is to record it as truth
    assert "docxkit revision baseline" in out
    assert json.loads(out_json.read_text(encoding="utf-8"))["content"]


def test_ingest_flags_a_style_edit_and_the_parts_that_moved(monkeypatch,
                                                            project,
                                                            capsys):
    base = make_parts(para(run("The paper as it stands.")))
    base["word/styles.xml"] = (
        b"<w:styles><w:style w:styleId='A'/></w:styles>")
    write(project.prev, base)
    changed = dict(base)
    changed["word/styles.xml"] = (
        b"<w:styles><w:style w:styleId='B'/></w:styles>")
    changed["word/numbering.xml"] = b"<w:numbering/>"
    del changed["[Content_Types].xml"]
    write(project.working, changed)

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "STYLE-level edit" in out
    assert "added" in out and "removed" in out


def test_ingest_truncates_a_long_bucket(monkeypatch, project, capsys):
    """A 400-difference dump is not a report anyone reads."""
    write(project.prev, make_parts(
        "".join(para(run(f"baseline paragraph {i}")) for i in range(20))))
    write(project.working, make_parts(
        "".join(para(run(f"reworded paragraph {i}")) for i in range(20))))
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    assert code == 0
    assert "more" in capsys.readouterr().out


def test_ingest_does_not_cry_wolf_over_a_resave(monkeypatch, project,
                                                capsys):
    """A Word round-trip rewrites nearly every part and means nothing."""
    base = make_parts(para(run("The paper as it stands.")))
    write(project.prev, base)
    resaved = dict(base)
    resaved["word/document.xml"] = resaved["word/document.xml"].replace(
        b"<w:body>", b"<w:body >")
    write(project.working, resaved)
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "re-saved" in out
    assert "only save-noise" in out


def test_ingest_shows_what_is_still_pending_on_both_sides(monkeypatch,
                                                          project,
                                                          capsys):
    write(project.prev, make_parts(para(run("x"), _ins("older"))))
    write(project.working, make_parts(para(run("x"), _ins("newer"))))
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("PROPOSAL") == 2
    assert "docxkit revision baseline" not in out


# ------------------------------------------------------------- baseline

def test_baseline_records_the_new_truth(monkeypatch, project, capsys):
    write(project.working, make_parts(para(run("Accepted and settled."))))
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))
    assert code == 0
    assert project.prev.read_bytes() == project.working.read_bytes()
    assert "baseline updated" in capsys.readouterr().out


def test_baseline_refuses_a_proposal_with_exit_3(monkeypatch, project):
    """BaselinePending is exit 3 — the number the protocol's own
    documentation already quotes."""
    write(project.working, make_parts(para(run("x"), _ins("pending"))))
    before = project.prev.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))
    assert code == 3
    assert project.prev.read_bytes() == before, "the baseline was written"


def test_baseline_force_is_for_migration(monkeypatch, project):
    write(project.working, make_parts(para(run("x"), _ins("pending"))))
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root), "--force")
    assert code == 0


# ---------------------------------------------------------------- build

def test_build_stages_a_batch(monkeypatch, project, capsys):
    from docxkit import revision
    monkeypatch.setattr(revision.tracked, "build", _fake_build())
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert project.batch.exists()
    assert "7 revisions" in out
    assert "revision validate" in out


def test_build_to_an_explicit_out(monkeypatch, project, tmp_path, capsys):
    from docxkit import revision
    dest = tmp_path / "elsewhere.docx"
    monkeypatch.setattr(revision.tracked, "build", _fake_build())
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--out", str(dest),
                      "--paper", str(project.root))
    assert code == 0
    assert dest.exists()
    assert str(dest) in capsys.readouterr().out


def test_build_refuses_resolved_math_with_exit_2(monkeypatch, project):
    """Word cannot serialize tracked math: those edits would ship with
    nothing to accept or reject."""
    from docxkit import revision
    monkeypatch.setattr(revision.tracked, "build", _fake_build(math=5))
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--paper", str(project.root))
    assert code == 2


def test_build_refuses_a_pending_baseline_with_exit_3(monkeypatch,
                                                      project):
    from docxkit import revision
    write(project.prev, make_parts(para(run("x"), _ins("unadjudicated"))))
    called: list[str] = []
    monkeypatch.setattr(revision.tracked, "build",
                        lambda *a, **k: called.append("ran"))
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--paper", str(project.root))
    assert code == 3
    assert not called, "Word Compare ran despite the refusal"


def test_build_can_absorb_a_pending_baseline_deliberately(monkeypatch,
                                                          project):
    from docxkit import revision
    write(project.prev, make_parts(para(run("x"), _ins("unadjudicated"))))
    monkeypatch.setattr(revision.tracked, "build", _fake_build(math=3))
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--allow-pending-baseline",
                      "--allow-math-resolve", "--paper", str(project.root))
    assert code == 0


# ------------------------------------------------------------- validate

def test_validate_passes_a_faithful_batch(monkeypatch, project, capsys):
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: PASS" in out
    assert "-> OK" in out


def test_validate_fails_an_unreviewable_batch(monkeypatch, project,
                                              capsys):
    """Rejecting everything must restore the baseline, or the author's
    veto is not real."""
    write(project.batch, make_parts(para(run("quietly rewritten"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "MISMATCH" in out
    assert "NOT fully reviewable" in out


def test_validate_aborts_on_lint_with_exit_2(monkeypatch, project,
                                             capsys):
    from docxkit import revision
    write(project.batch, make_parts(para(run("x"))))
    monkeypatch.setattr(revision._lint, "lint_parts",
                        lambda _p: ["orphan bookmark 3"])
    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 2
    assert "ABORT before Word" in out


def test_validate_reports_a_file_word_refuses(monkeypatch, project,
                                              capsys):
    from docxkit import revision
    write(project.batch, make_parts(para(run("x"))))
    monkeypatch.setattr(revision, "_word", _Word(explode=True))
    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root))
    assert code == 3
    assert "FAILED (corrupted)" in capsys.readouterr().out


def test_validate_with_word_lists_the_papers_own_gates(monkeypatch,
                                                       project, capsys):
    """They are LISTED, never run: what a paper checks is the paper's
    business, and shelling out is a larger promise than this makes."""
    from docxkit import revision
    project.config.write_text(
        project.config.read_text(encoding="utf-8").replace(
            "commands = []",
            'commands = ["python scripts/verify_tables.py"]'),
        encoding="utf-8")
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("more"))))
    monkeypatch.setattr(revision, "_word",
                        _Word(_Doc(text="The paper as it stands.more")))
    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "verify_tables.py" in out
    assert "1 revision groups" in out
    assert "XML accept == Word accept ? OK" in out


def test_validate_warns_about_shells_accepting_would_create(monkeypatch,
                                                            project,
                                                            capsys):
    from docxkit import revision
    write(project.batch, make_parts(
        f'<w:p><m:oMath {NS_M}><w:del w:id="7" w:author="R" '
        f'w:date="2026-08-07T00:00:00Z"><m:r><m:t>x</m:t></m:r>'
        f"</w:del></m:oMath></w:p>"))
    monkeypatch.setattr(
        revision.revisions, "accept",
        lambda xml, **_k: re.sub(r"<w:del\b.*?</w:del>", "", xml,
                                 flags=re.DOTALL))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    assert code == 1
    assert "empty OMML shells" in capsys.readouterr().out


def test_validate_takes_an_explicit_batch_and_baseline(monkeypatch,
                                                       project, tmp_path,
                                                       capsys):
    batch = write(tmp_path / "other.docx", make_parts(para(run("same"))))
    base = write(tmp_path / "base.docx", make_parts(para(run("same"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", str(batch),
                      "--baseline", str(base), "--no-word",
                      "--paper", str(project.root))
    assert code == 0
    assert "other.docx" in capsys.readouterr().out


def test_validate_says_nothing_about_reject_all_with_no_baseline(
        monkeypatch, project, capsys):
    project.prev.unlink()
    write(project.batch, make_parts(para(run("x"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "reject-all" not in out, \
        "a reject-all verdict was printed with nothing to compare against"


# -------------------------------------------------------------- promote

def test_promote_lands_and_leaves_a_rescue(monkeypatch, project, capsys):
    write(project.batch, make_parts(para(run("the batch"))))
    original = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert project.working.read_bytes() == project.batch.read_bytes()
    assert "rescue copy" in out
    assert "never accepts on their behalf" in out
    rescues = list(project.working.parent.glob("*rescue*"))
    assert rescues and rescues[0].read_bytes() == original


def test_promote_refuses_a_stale_batch_with_exit_4(monkeypatch, project):
    """The author edited working.docx while the batch was being built."""
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run("the author's own edit"))))
    before = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    assert code == 4
    assert project.working.read_bytes() == before


def test_promote_refuses_while_word_holds_the_file(monkeypatch, project):
    """DocumentLocked is not a protocol refusal: exit 1 with a message."""
    from docxkit import revision
    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setattr(revision.package, "is_locked", lambda _p: True)
    before = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    assert isinstance(code, str)
    assert "open in Word" in code
    assert project.working.read_bytes() == before


def test_promote_takes_explicit_paths(monkeypatch, project, tmp_path):
    batch = write(tmp_path / "b.docx", make_parts(para(run("explicit"))))
    code, _ = run_cli(monkeypatch, "revision", "promote", str(batch),
                      "--base", str(project.prev),
                      "--paper", str(project.root))
    assert code == 0
    assert project.working.read_bytes() == Path(batch).read_bytes()
