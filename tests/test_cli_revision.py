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
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "manuscript.docx",
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
        report.math_resolved = math       # the number the protocol reads
        return report

    return build


# ----------------------------------------------------------------- init

def test_init_adopts_the_manuscript_in_place(monkeypatch, tmp_path,
                                            capsys):
    """The paper keeps its name, and the author is told so."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("body"))))
    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"), "--name", "LE",
                      "--author", "Agent", "--language", "ru",
                      "--attic", str(tmp_path / "attic"))
    out = capsys.readouterr().out
    assert code == 0
    assert Path(src).exists()
    assert not (tmp_path / "proj" / "revision" / "working.docx").exists()
    assert "adopted in place" in out
    assert "LE7.docx" in out


def test_init_WORKING_names_a_copy_and_says_the_source_is_spent(
        monkeypatch, tmp_path, capsys):
    """The old migration shape, now asked for by name. The source is
    left where it was and nothing reads it again — a state the first
    version of this protocol created silently, on every paper."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("b"))))
    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"),
                      "--working", "Report/LE.docx")
    out = capsys.readouterr().out
    assert code == 0
    assert (tmp_path / "proj" / "Report" / "LE.docx").exists()
    assert Path(src).exists(), "the source was moved, not copied"
    assert "COPIED, not moved" in out


def test_init_refuses_to_rewrite_a_live_config(monkeypatch, project,
                                               capsys):
    """A clean message on stderr, not a traceback."""
    code, _ = run_cli(monkeypatch, "revision", "init",
                      str(project.working), "--root", str(project.root))
    assert code == 1
    assert "already" in capsys.readouterr().err


def test_init_force_rewrites_in_place(monkeypatch, project):
    """Re-running init on a MIGRATED paper, to correct its config: the
    source is the manuscript itself, and copying a file onto itself
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
    assert (tmp_path / "revision" / "paper.toml").is_file()
    from docxkit.revision import load_paper
    assert load_paper(tmp_path).working == Path(src)


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


def test_status_flags_a_baseline_the_paper_has_outgrown(monkeypatch,
                                                        project, capsys):
    """The author accepted every revision in Word and saved. Counting
    pending revisions sees TRUTH on both sides and says go; the two files
    are no longer the same paper, and a batch built here is built on the
    wrong base — which `promote` discovers only after a Word Compare."""
    write(project.working, make_parts(para(run("The paper, as accepted."))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 4, "a stale baseline exited 0 - a script would build on it"
    assert "TRUTH" in out                    # both sides still count zero
    assert "STALE" in out and "word/document.xml" in out
    assert "revision ingest" in out


def test_status_folds_a_flood_of_stale_parts_into_a_line(monkeypatch,
                                                         project, capsys):
    """The first real one listed sixteen parts, twelve of them
    `word/fonts/font*.odttf` from one tick of Word's embed-fonts box, on
    a single line nobody would read."""
    from docxkit import package
    fonts = {f"word/fonts/font{i}.odttf": f"binary{i}".encode()
             for i in range(1, 13)}
    parts = package.read_parts(project.working)
    parts.update(fonts)
    parts["word/document.xml"] = make_parts(
        para(run("edited")))["word/document.xml"]
    package.write_docx(project.working, parts)

    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    stale_line = next(ln for ln in out.splitlines() if "STALE" in ln)
    assert code == 4
    assert "word/fonts/ (12 parts)" in stale_line
    assert "font1.odttf" not in stale_line
    assert len(stale_line) < 120, stale_line


def test_status_does_not_cry_stale_over_a_pending_proposal(monkeypatch,
                                                           project, capsys):
    """A proposal is SUPPOSED to differ from its baseline. Reporting it
    as staleness would fire on every batch the protocol produces."""
    write(project.working, make_parts(para(run("x"), _ins("added"))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1 and "STALE" not in out


def test_the_stale_line_caps_a_long_list_of_loose_parts():
    """Folding by directory is not enough on its own: a package can
    diverge in a dozen parts that share no folder."""
    from docxkit.cli import _summarize
    loose = [f"part{i}.xml" for i in range(1, 8)]
    line = _summarize(loose)
    assert line.endswith("and 3 more")
    assert "part5.xml" not in line


def test_status_reports_a_missing_baseline(monkeypatch, project, capsys):
    project.prev.unlink()
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    assert code == 0
    assert "MISSING" in capsys.readouterr().out


def test_a_pending_proposal_still_exits_1_with_no_baseline(monkeypatch,
                                                           project, capsys):
    """That branch has its own `return 0 if st.is_truth else 1`, and only
    the truth half was ever run — so the code a script reads to decide
    whether it may start a batch was unpinned for a paper that has not
    been baselined yet."""
    project.prev.unlink()
    write(project.working, make_parts(para(run("x"), _ins("added"))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "MISSING" in out and "PROPOSAL" in out


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


_LINKED = ('<w:hyperlink w:anchor="ref_Ritchie2023b">'
           "<w:r><w:t>Ritchie (2023b)</w:t></w:r></w:hyperlink>")


def _ate_a_link(project) -> None:
    """The author's Word session collapsed the paragraph and the link
    element went with it — the words all survive."""
    write(project.prev, make_parts(para(run("see "), _LINKED)))
    write(project.working,
          make_parts(para(run("see "), "<w:r><w:t>Ritchie (2023b)</w:t>"
                                       "</w:r>")))


def test_ingest_reports_a_RE_LABELLED_link_apart_from_the_losses(monkeypatch,
                                                                 project,
                                                                 capsys):
    """Its own section, and not under LOST. The two say opposite things
    to a reader: one is damage to put back before baselining, the other
    is an edit the author meant — DSI's R24.1 re-labelled four back-link
    fields and read four losses it then had to talk past."""
    write(project.prev, make_parts(para(run("see "), _LINKED)))
    write(project.working, make_parts(para(
        run("see "),
        '<w:hyperlink w:anchor="ref_Ritchie2023b">'
        "<w:r><w:t>Ritchie and Roser (2023b)</w:t></w:r></w:hyperlink>")))

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "== LOST" not in out, out
    lines = out.splitlines()
    at = lines.index("== RE-LABELLED (1) ==")
    assert "ref_Ritchie2023b" in lines[at + 1]
    assert "Ritchie (2023b)" in lines[at + 1]
    assert "Ritchie and Roser (2023b)" in lines[at + 1]
    assert "does not refuse" in out


def test_ingest_check_EXITS_on_a_hand_back_that_lost_something(monkeypatch,
                                                               project,
                                                               capsys):
    """Reporting it and exiting 0 is what let six losses scroll past on
    LI7. `--check` is what a paper can put in its own gate list."""
    from docxkit.errors import HandbackLoss

    _ate_a_link(project)
    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--paper", str(project.root))
    assert code == HandbackLoss.exit_code
    assert "LOST" in capsys.readouterr().out


def test_ingest_without_check_still_only_REPORTS(monkeypatch, project,
                                                 capsys):
    """Read-only and exit 0 stays the default: `ingest` is the command
    that is safe to run before every task."""
    _ate_a_link(project)
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    assert code == 0
    assert "LOST" in capsys.readouterr().out


def test_baseline_refuses_the_loss_and_accept_loss_lets_it_through(
        monkeypatch, project, capsys):
    from docxkit.errors import HandbackLoss

    _ate_a_link(project)
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))
    assert code == HandbackLoss.exit_code

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--accept-loss", "link:ref_Ritchie2023b (Ritchie "
                      "(2023b))", "--paper", str(project.root))
    assert code == 0
    assert project.prev.read_bytes() == project.working.read_bytes()


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


def test_keep_math_REACHES_the_build(monkeypatch, project):
    """A flag that does not arrive is worse than no flag: the redline
    ships with the equations accepted and the run reports success."""
    from docxkit import revision
    seen: dict[str, object] = {}
    inner = _fake_build()

    def build(*a, **kw):
        seen.update(kw)
        return inner(*a, **kw)

    monkeypatch.setattr(revision.tracked, "build", build)
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--keep-math",
                      "--paper", str(project.root))
    assert code == 0
    assert seen["resolve_math"] is False


def test_the_math_is_resolved_when_nobody_says_otherwise(monkeypatch,
                                                         project):
    from docxkit import revision
    seen: dict[str, object] = {}
    inner = _fake_build()

    def build(*a, **kw):
        seen.update(kw)
        return inner(*a, **kw)

    monkeypatch.setattr(revision.tracked, "build", build)
    run_cli(monkeypatch, "revision", "build", str(project.working),
            "--paper", str(project.root))
    assert seen["resolve_math"] is True


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


def test_the_flag_the_staleness_refusal_advertises_EXISTS(monkeypatch,
                                                          project):
    """`docxkit revision build --force` was `error: unrecognized
    arguments: --force`, and it is what the refusal told the reader to
    do — the guard was right and the only way out it named was fiction
    (2026-08-12). The refusal itself is asserted in test_tracked_guard;
    this asks the parser whether the flag is real, and passes it on."""
    from docxkit import revision

    seen: list[bool] = []

    def _capture(original, revised, out, classify=None, **kw):
        seen.append(kw["force"])
        return _fake_build()(original, revised, out, classify, **kw)

    monkeypatch.setattr(revision.tracked, "build", _capture)
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--force",
                      "--paper", str(project.root))
    assert code == 0
    assert seen == [True], "the flag parsed and was not passed on"


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
    assert "== lint == clean" in out, "a clean batch says so"


def test_validate_RENDERS_the_anchors_it_is_given(monkeypatch, project,
                                                  capsys, tmp_path):
    """BACKLOG S4: the eye gate, on the shared command. DSI kept a
    private 78-line script for this after every other part of its
    ladder retired onto `docxkit revision`, and the next paper to want
    one would have copied it or gone without."""
    made = {"Table 3": tmp_path / "batch__p7.png", "Table 9": None}
    asked: dict[str, object] = {}

    def fake_render(batch, anchors, **kw):
        asked.update(batch=Path(batch), anchors=list(anchors))
        return made

    monkeypatch.setattr("docxkit.revision.render_accepted", fake_render)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root),
                      "--no-word", "--render", "Table 3", "Table 9")
    out = capsys.readouterr().out

    assert code == 0, out
    assert asked["anchors"] == ["Table 3", "Table 9"]
    assert asked["batch"] == project.batch
    assert "== render ==  2 anchor(s), accepted view" in out
    assert "batch__p7.png" in out
    assert "'Table 9': on no page" in out, out


def test_validate_renders_NOTHING_unless_asked(monkeypatch, project, capsys):
    """The step costs a Word session, a render and a PDF. It runs when
    a person asks for it and not otherwise."""
    def refuse(*a, **kw):                        # pragma: no cover
        raise AssertionError("rendered without --render")

    monkeypatch.setattr("docxkit.revision.render_accepted", refuse)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    run_cli(monkeypatch, "revision", "validate", "--paper",
            str(project.root), "--no-word")

    assert "== render ==" not in capsys.readouterr().out


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
    # and WHICH paragraph, which is the half that cost a bespoke difflib
    # script to work out
    assert "quietly rewritten" in out, out


def test_validate_names_the_GLYPH_that_changed(monkeypatch, project,
                                              capsys):
    """`glyphs: False` for a 68,000-character stream says only that
    SOMETHING moved. On AFI the answer was two characters — a minus sign
    Word's Compare had rewritten as a hyphen inside an equation — and
    three builds went by blaming the edits before a bespoke difflib
    script over private imports found them."""
    write(project.prev, make_parts(
        para(run("the gap is − 0.15 in every year"))))
    write(project.batch, make_parts(
        para(run("the gap is - 0.15 in every year"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 1
    assert "GLYPH" in out, out
    assert "U+2212" in out and "U+002D" in out, out
    assert "after ...the gap is " in out, out


def test_validate_says_WHICH_VIEW_a_glyph_difference_is_about(
        monkeypatch, project, capsys):
    """BACKLOG S3. Word downgrades U+2212 to a hyphen while
    re-serialising an equation; `build` puts it back in the ACCEPTED
    view — the document that ships — and the rejected one keeps what
    Compare wrote. So a batch whose edit is perfect fails gate 5 on a
    character no author typed, and `glyphs: False` with no view named
    reads as a defect in the edit. Three consecutive rounds on AFI went
    that way, each ending in a per-paper repair script.

    The gate still fails, and should: the two views disagree. What
    changes is that the report says which one it is judging, and that
    every difference it found is that substitution and nothing else."""
    write(project.prev, make_parts(
        para(run("the gap is − 0.15 in every year"))))
    write(project.batch, make_parts(
        para(run("the gap is - 0.15 in every year"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 1
    assert "GLYPH (reject-all vs baseline)" in out, out
    assert "math character Word downgrades" in out, out
    assert "ACCEPTED view has them restored" in out


def test_a_REAL_edit_is_not_called_a_math_downgrade(monkeypatch, project,
                                                    capsys):
    """The other side of the same flag: a batch that actually changed a
    word must not be excused. `_downgraded` is applied to BOTH streams,
    so they compare equal only when the substitution is the whole of the
    difference."""
    write(project.prev, make_parts(
        para(run("the gap is − 0.15 in every year"))))
    write(project.batch, make_parts(
        para(run("the gap is - 0.19 in every year"))))

    run_cli(monkeypatch, "revision", "validate", "--no-word",
            "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "GLYPH (reject-all vs baseline)" in out, out
    assert "math character Word downgrades" not in out, out


def test_validate_names_a_moved_footnote_anchor(monkeypatch, project,
                                                capsys):
    """Compare emits a re-anchored footnote as one insertion with no
    deletion. Gate 5 could only say `footnotes: False`, and that reads
    like a lossy batch rather than a note whose reference moved."""
    from test_revision import footnotes_part
    write(project.prev, make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("the note")))))
    write(project.batch, make_parts(
        para(run("body")),
        footnotes=footnotes_part(
            para('<w:ins w:id="9" w:author="R" w:date="2026-08-11T00:00:00Z">'
                 "<w:r><w:t>the note</w:t></w:r></w:ins>"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "footnote 2" in out and "REFERENCE moved" in out, out


def test_validate_says_which_LINK_the_rejected_batch_lost(monkeypatch,
                                                          project, capsys):
    """The words come back and the hyperlink does not: Word's Compare
    does not rebuild a link inside a rejected deletion. Parental Style
    T4(3) came back two links short with reject-all reporting OK."""
    linked = ('<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
              "</w:r></w:hyperlink>")
    write(project.prev, make_parts(para(run("see"), linked)))
    write(project.batch, make_parts(para(run("see"), run("Table 5"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "'links': False" in out, out
    assert "LINK LOST -> Table5" in out


def test_validate_says_which_PART_the_batch_lost(monkeypatch, project,
                                                 capsys):
    """The reject-all gate proves the TEXT round-trips; nothing proved
    the package did, and promote copies the batch over working.docx."""
    base = make_parts(para(run("settled")))
    base["customXml/item1.xml"] = (
        b'<b:Sources xmlns:b="http://schemas.openxmlformats.org'
        b'/officeDocument/2006/bibliography"/>')
    write(project.prev, base)
    write(project.batch, {k: v for k, v in base.items()
                          if not k.startswith("customXml/")})
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "LOST customXml/item1.xml" in out, out
    assert "VERDICT: FAIL" in out


def test_status_and_ingest_SAY_when_they_read_a_snapshot(
        monkeypatch, project, capsys):
    """A snapshot mid-edit is a true statement about a moment — and the
    reader has to be told which one they are looking at."""
    from docxkit import package

    monkeypatch.setattr(package, "is_locked",
                        lambda p: Path(p) == project.working)

    for command in ("status", "ingest"):
        run_cli(monkeypatch, "revision", command, "--paper",
                str(project.root))
        out = capsys.readouterr().out
        assert "read from a SNAPSHOT" in out, command


def test_validate_aborts_on_a_batch_built_on_ANOTHER_baseline(
        monkeypatch, project, capsys):
    """The report it used to print instead was detailed, plausible and
    about a different batch — the R1 redline, two baselines old, with
    twenty LINK LOST lines nobody could act on (Aging_Well R5)."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("an older truth"))))
    guard.stamp(project.batch, base_sha256="0" * 64)

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "was NOT built on" in out
    assert "VERDICT: FAIL" in out
    assert "== lint ==" not in out, "the ladder ran on the wrong pair"


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
    monkeypatch.setattr(revision._validate, "_word", _Word(explode=True))
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
    monkeypatch.setattr(revision._validate, "_word",
                        _Word(_Doc(text="The paper as it stands.more")))
    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "verify_tables.py" in out
    assert "1 revision group(s) in the body" in out
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
    # in build/rescue/, NOT beside the manuscript: one file to open is
    # the whole point of this layout
    assert not list(project.working.parent.glob("*rescue*"))
    kept = list(project.rescue_dir.glob("*rescue*"))
    assert kept and kept[0].read_bytes() == original


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


# -------------------------------------------------------------- rescues

def _seed(project, n: int):
    from datetime import datetime

    from docxkit import revision
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        p = revision.rescue_path(project, datetime(2026, 8, 7, 10, 0, i))
        p.write_bytes(f"rescue {i}".encode())


def test_rescues_lists_what_promote_left(monkeypatch, project, capsys):
    _seed(project, 3)
    code, _ = run_cli(monkeypatch, "revision", "rescues",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert out.count(f"{project.working.stem}_rescue_") == 3
    assert "keeping 5" in out


def test_rescues_on_a_paper_that_never_promoted(monkeypatch, project,
                                                capsys):
    code, _ = run_cli(monkeypatch, "revision", "rescues",
                      "--paper", str(project.root))
    assert code == 0
    assert "no rescue copies" in capsys.readouterr().out


def test_rescues_prune_to_a_depth(monkeypatch, project, capsys):
    from docxkit import revision
    _seed(project, 6)
    code, _ = run_cli(monkeypatch, "revision", "rescues", "--prune", "2",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "pruned 4, keeping 2" in out
    assert len(revision.rescues(project)) == 2


def test_rescues_bare_prune_removes_all(monkeypatch, project, capsys):
    from docxkit import revision
    _seed(project, 3)
    code, _ = run_cli(monkeypatch, "revision", "rescues", "--prune",
                      "--paper", str(project.root))
    assert code == 0
    assert "keeping 0" in capsys.readouterr().out
    assert revision.rescues(project) == []


def test_promote_reports_what_it_pruned(monkeypatch, project, capsys):
    _seed(project, 6)
    write(project.batch, make_parts(para(run("the batch"))))
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "pruned" in out and "older rescue" in out
    # reported relative to the project, not as an absolute path
    assert r"build\rescue" in out or "build/rescue" in out
    assert str(project.root) not in out


def test_doctor_is_quiet_on_a_project_that_agrees(monkeypatch, project,
                                                  capsys):
    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    assert code == 0
    assert "nothing else" in capsys.readouterr().out


def test_doctor_exits_2_and_names_the_line(monkeypatch, project, capsys):
    """A migration can gate on this, and it has to run on a tree that is
    otherwise GREEN — that is the state it exists to break."""
    stale = project.root / "tests" / "helpers.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('PAPER = next(root.glob("Report/le_v*.docx"))\n',
                     encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "tests/helpers.py:1" in out, out
    assert "pattern" in out and "Report/le_v*.docx" in out


def test_doctor_shows_patterns_and_COUNTS_the_literals(monkeypatch, project,
                                                       capsys):
    """AFI's 134 lines are why. The patterns are the dangerous kind and
    they print in full; the literals are counted, with the remedy named,
    because most of them are a spent archive."""
    for n, body in ((1, 'P = next(root.glob("Report/le_v*.docx"))\n'),
                    (2, 'P = "Report/le_v3.docx"\n'),
                    (3, 'P = "Report/le_v4.docx"\n')):
        f = project.root / f"s{n}.py"
        f.write_text(body, encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "1 PATTERN selection(s)" in out, out
    assert "s1.py:1" in out
    assert "2 literal selection(s) not shown" in out, out
    assert "s2.py" not in out, "the literals should be counted, not listed"
    assert "[doctor] skip" in out, "the remedy has to be in the message"


def test_doctor_lists_the_literals_when_asked(monkeypatch, project, capsys):
    (project.root / "s2.py").write_text('P = "Report/le_v3.docx"\n',
                                        encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor", "--literals",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "1 literal selection(s):" in out, out
    assert "s2.py:1" in out


# --- what the cli run of 2026-08-18 found here ---------------------------
#
# `cmd_revision_ingest` was cli.py's largest cluster with 13, and twelve
# of those were the cap on the per-bucket listing — the twelve lines an
# author reads to find out what happened while the batch was away, and
# the count of what did not fit. Nothing here had ever handed it more
# than a handful of changes.


def _reworded(project, n: int) -> None:
    """`n` paragraphs, every one of them changed."""
    write(project.prev, make_parts("".join(
        para(run(f"Original sentence {i}.")) for i in range(n))))
    write(project.working, make_parts("".join(
        para(run(f"Reworded sentence {i}.")) for i in range(n))))


def test_ingest_lists_TWELVE_changes_and_counts_the_rest(monkeypatch,
                                                         project, capsys):
    """Twenty-five reworded paragraphs: twelve are printed and the rest
    are a number. Which number matters — `25 - 12` is 13, and the
    operators that survived in its place read 1, 21, 8, 29 and 0, every
    one of them a plausible count of edits to a paper."""
    _reworded(project, 25)

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "-- text (25)" in out
    assert sum("Original sentence" in ln for ln in out.splitlines()) == 12
    assert "... and 13 more" in out


def test_ingest_counts_NOTHING_extra_under_the_cap(monkeypatch, project,
                                                   capsys):
    """`len(items) > 12`: under the cap there is nothing left over, and
    `!= 12` prints "and -9 more" for a paper with three edits in it."""
    _reworded(project, 3)

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    assert "-- text (3)" in out
    assert sum("Original sentence" in ln for ln in out.splitlines()) == 3
    assert "more" not in out


@pytest.mark.parametrize(("n", "extra"), [(12, ""), (13, "... and 1 more")])
def test_ingest_counts_the_rest_AT_the_cap_and_one_past_it(monkeypatch,
                                                           project, capsys,
                                                           n, extra):
    """Twelve exactly, and thirteen. The pair above proved the cap with
    25 and with 3, where `> 11` and `> 13` agree with `> 12` — a bound
    is invisible at any distance but one. At twelve there is nothing
    left over to count; at thirteen there is exactly one, which is the
    smallest number the line can carry and the one a reader trusts
    least."""
    _reworded(project, n)

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    assert f"-- text ({n})" in out
    assert sum("Original sentence" in ln for ln in out.splitlines()) == 12
    assert ("more" in out) is bool(extra), out
    if extra:
        assert extra in out


def test_an_ingest_line_quotes_TWO_HUNDRED_characters_of_the_change(
        monkeypatch, project, capsys):
    """The width of one line of the report an author reads to find out
    what happened while the batch was away. A paragraph is longer than
    that more often than not, so the cut is on almost every line."""
    long_one = "Original " + "sentence that runs on and on, " * 12
    assert len(long_one) > 201
    write(project.prev, make_parts(para(run(long_one))))
    write(project.working, make_parts(para(run("Reworded."))))

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    (line,) = [ln for ln in out.splitlines() if "word_diff" in ln]
    assert len(line) == 4 + 200, line       # "   " + the space print adds


def test_ingest_names_every_LOST_element_not_just_the_count(monkeypatch,
                                                            project, capsys):
    """The heading says how many; the lines say WHICH, and which is the
    whole of what a person can act on — `revision baseline` refuses
    until each one is restored or named."""
    _ate_a_link(project)

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    lines = out.splitlines()
    at = lines.index("== LOST (1) ==")
    assert "ref_Ritchie2023b" in lines[at + 1], (
        "the anchor is the thing to restore; the heading only counts")
    assert "link" in lines[at + 1], "and what KIND of thing it was"


def test_validate_ABORTS_before_word_on_a_lint_problem(monkeypatch, project,
                                                       capsys):
    """The ladder stops at its first rung on purpose: Word is minutes,
    and a batch that fails lint is a batch to fix, not to open. The
    heading has to say WHICH way round it went — inverted, a clean batch
    reports "0 problem(s)" and a broken one reports "clean" — and the
    lines under it name the problem, because "1 problem(s)" is not
    something a person can fix.

    Edge whitespace with no `xml:space="preserve"` is the shape: Word
    drops the space on save, and two words run together in a sentence
    the author never touched."""
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins(" and more"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 2, out
    assert "== lint == 1 problem(s)" in out
    assert "FAIL: w:t has edge whitespace" in out
    assert "ABORT before Word" in out
    assert "== counts ==" not in out, "it stopped at the first rung"


def test_validate_says_WHICH_structure_the_reject_lost(monkeypatch, project,
                                                       capsys):
    """The fifth arm of gate 5, printed. A batch whose words round-trip
    can still fail it — a move duplicates a table, a moved paragraph
    loses its bookmarks — and none of that is a character, so the line
    has to name the count that moved or the reader is told only that
    something did."""
    write(project.batch, make_parts(
        "<w:tbl><w:tr><w:tc>"
        + para(run("The paper as it stands.")) + "</w:tc></w:tr></w:tbl>"))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 1, out
    assert "NOT fully reviewable" in out
    assert "STRUCTURE tbl: 0 -> 1" in out
    assert "duplicate a table" in out


def test_status_says_when_note_definitions_are_OUT_OF_ORDER(monkeypatch,
                                                            project, capsys):
    """The line a person reads. Everything else about such a file is
    right — it renders, it counts, its text diffs clean — and the next
    `build` reports 81 glyph runs against whichever batch comes after
    the one that appended the note. This is the only place it is cheap
    to say (backlog S1, AFI r4)."""
    notes = ('<w:footnotes><w:footnote w:id="2"><w:p><w:r><w:t>first</w:t>'
             "</w:r></w:p></w:footnote>"
             '<w:footnote w:id="3"><w:p><w:r><w:t>second</w:t>'
             "</w:r></w:p></w:footnote></w:footnotes>")
    body = (para(run("Alpha"), '<w:r><w:footnoteReference w:id="3"/></w:r>')
            + para(run("Beta"), '<w:r><w:footnoteReference w:id="2"/></w:r>'))
    write(project.working, make_parts(body,
                                      extra={"word/footnotes.xml": notes}))

    run_cli(monkeypatch, "revision", "status", "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "footnote definitions are NOT in document order" in out, out
    assert "2, 3" in out
    assert "reads the part as moved" in out


# ----------------------------------------------------------------- ship
#
# The two steps run back to back on every batch and each was paying its
# own Word cold start: 13.5 s + 38.9 s on a one-edit AFI batch, about
# 52 s of 95.


def test_ship_runs_BOTH_halves_in_one_call(monkeypatch, project, capsys):
    from docxkit import revision
    monkeypatch.setattr(revision.tracked, "build", _fake_build())

    code, _ = run_cli(monkeypatch, "revision", "ship",
                      str(project.working), "--paper", str(project.root),
                      "--no-word")

    out = capsys.readouterr().out
    assert "7 revisions" in out, "the build half did not run"
    assert "== lint ==" in out, "the validate half did not run"
    # the exit code is the VALIDATE half's — this batch is a fixture
    # and fails its gates, which is the code a caller should see
    assert code == 1, out


def test_ship_opens_ONE_Word_session_for_the_pair(monkeypatch, project):
    """The whole point. `build` opens one for Compare and its in-Word
    verify, `validate` opens another for the accept it compares against
    the XML — and they run in that order, every time."""
    from docxkit import revision, word
    opened: list[int] = []

    @contextlib.contextmanager
    def counting(*, fast: bool = True):
        opened.append(1)
        yield object()

    monkeypatch.setattr(word, "session", counting)
    monkeypatch.setattr(revision.tracked, "build", _fake_build())

    run_cli(monkeypatch, "revision", "ship", str(project.working),
            "--paper", str(project.root), "--no-word")

    assert opened == [1], f"{len(opened)} Word session(s) for one batch"


def test_ship_does_NOT_validate_after_a_failed_build(monkeypatch, project,
                                                     capsys):
    """`validate` defaults to `build/batch.docx`, which after a failed
    build is whatever the PREVIOUS batch left there — so a shell `&&` is
    not what this is, and the stop is the reason it is one command."""
    from docxkit import revision

    def refuses(*a, **kw):
        raise revision.StaleBatch("batch.docx was edited in Word")

    monkeypatch.setattr(revision.tracked, "build", refuses)

    code, _ = run_cli(monkeypatch, "revision", "ship", str(project.working),
                      "--paper", str(project.root), "--no-word")

    assert code != 0
    assert "== lint ==" not in capsys.readouterr().out


def test_ship_stops_on_a_build_that_RETURNS_a_code_too(monkeypatch, project,
                                                       capsys):
    """`build` refuses by raising today. The code path is here because
    a command that starts returning one instead must not quietly become
    "validate whatever is in build/batch.docx"."""
    from docxkit import cli

    monkeypatch.setattr(cli, "cmd_revision_build", lambda args: 4)

    code, _ = run_cli(monkeypatch, "revision", "ship", str(project.working),
                      "--paper", str(project.root), "--no-word")

    assert code == 4
    assert "== lint ==" not in capsys.readouterr().out


def test_ship_takes_every_flag_BUILD_takes(monkeypatch, capsys):
    """`ship` runs `build` and delegates to `cmd_revision_build`, which
    reads `args.<flag>` — so a flag on one parser and not the other is
    not a gap, it is an AttributeError on every ship. That is what
    `--allow-stale-baseline` did the day it was added: four tests, and
    it would have been every real run.

    Asserted as the RELATIONSHIP between the two parsers rather than as
    a list, so the next flag cannot fall out of one of them."""
    import argparse

    from docxkit import cli

    build = argparse.ArgumentParser()
    ship = argparse.ArgumentParser()
    cli._build_args(build)
    cli._build_args(ship)

    def flags(p):
        return {o for a in p._actions for o in a.option_strings}

    assert flags(build) == flags(ship)
    assert "--allow-stale-baseline" in flags(build), (
        "the flag whose absence from ship was the defect")


def test_the_two_parsers_come_from_ONE_declaration(monkeypatch, capsys):
    """The point of the helper: not that the lists agree today, but that
    there is only one list. A second copy would pass the test above the
    day it was written and drift the day after."""
    import inspect

    from docxkit import cli

    source = inspect.getsource(cli.main)

    assert source.count("_build_args(r)") == 2, (
        "build and ship should each call the shared declaration once")
    assert '"--allow-math-resolve"' not in source, (
        "a flag is declared in _build_args, not in main")


def test_a_survey_row_says_a_batch_is_STAGED_and_the_file_is_OPEN(tmp_path):
    """Two marks a reader acts on immediately: something is built and
    waiting, and the paper cannot be written to because Word has it.
    Neither was covered, and a row that silently drops them sends the
    author to a paper that is not in the state the row claims."""
    from docxkit import cli
    from docxkit.revision import Survey

    row = cli._survey_row(Survey(config=tmp_path / "revision" / "paper.toml",
                                 paper=None, state=None,
                                 staged=True, locked=True))

    assert "batch staged in build/" in row
    assert "open in Word" in row


def test_a_SECOND_init_names_the_config_it_SAVED(monkeypatch, tmp_path,
                                                 capsys):
    """Re-running init rewrites the keys you gave and keeps a copy of
    what was there. The copy is only useful if its name is said — the
    author is being told "your settings changed" and needs the thing
    that lets them check what they were."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("body"))))
    run_cli(monkeypatch, "revision", "init", str(src),
            "--root", str(tmp_path / "proj"), "--name", "LE")
    capsys.readouterr()

    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"), "--name", "LE7",
                      "--force")

    out = capsys.readouterr().out
    assert code == 0
    assert "updated" in out
    assert "previous config:" in out, out
    assert "_pre_init" in out, out


def test_baseline_hands_BACK_the_row_a_log_it_did_not_scaffold_cannot_take(
        monkeypatch, project, capsys):
    """`log_batch` returns None for a log with no batch table, because
    guessing where a row belongs in the author's own document is how a
    record gets mangled. The round still happened, so the CLI prints the
    row for the author to place — silence here loses it."""
    (project.config.parent / "log.md").write_text(
        "# Revision log\n\nProse, and no table anywhere in it.\n",
        encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "no batch table" in out, out
    assert "record this round by hand" in out, out



def test_validate_says_a_paper_lists_NO_gates_of_its_own(monkeypatch,
                                                         project, capsys):
    """`--run-gates` on a paper whose toml lists none.

    Silence here reads as "they ran and passed". The line exists so that
    a paper nobody has written gates for says so — which is the same
    argument the branch above it makes for listing gates that were NOT
    run: a list of unrun checks is a reminder."""
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    run_cli(monkeypatch, "revision", "validate", "--no-word", "--run-gates",
            "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "none listed in paper.toml" in out, out


def test_baseline_with_NO_LOG_says_nothing_about_the_log(monkeypatch,
                                                         project, capsys):
    """`--no-log` is the author saying they will record the round
    themselves, so neither the logged line nor the hand-it-back refusal
    belongs — and a baseline that quietly logged anyway under a flag
    asking it not to would be the kind of thing nobody checks."""
    code, _ = run_cli(monkeypatch, "revision", "baseline", "--no-log",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "baseline updated" in out
    assert "logged:" not in out
    assert "no batch table" not in out



# ------------------------------------------------------------- redlines

def test_redlines_lists_what_each_batch_PROPOSED(monkeypatch, project,
                                                 capsys):
    """The kept redlines are the only record of what a round offered —
    including what the author rejected, which nothing else holds once
    the manuscript moves on. Listing them with their sizes is how you
    find the one worth opening."""
    project.redline_dir.mkdir(parents=True, exist_ok=True)
    kept = project.redline_dir / (
        f"{project.working.stem}_redline_20260824-140618.docx")
    write(kept, make_parts(para(run("what round one proposed"))))

    code, _ = run_cli(monkeypatch, "revision", "redlines",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert kept.name in out
    assert "never pruned" in out
    assert "1 redline(s)" in out


def test_redlines_on_a_paper_with_NONE_says_why_there_are_none(
        monkeypatch, project, capsys):
    """A paper whose batches all predate the keeping has no redlines and
    is not broken. Silence would read as a failure, and "no redlines"
    alone would read as "your rounds proposed nothing"."""
    code, _ = run_cli(monkeypatch, "revision", "redlines",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "no redlines" in out
    assert "predate" in out, "say why, not just that there are none"



def test_a_LOST_part_says_DECLARE_it_rather_than_naming_a_function(
        monkeypatch, project, capsys):
    """`validate` is a protocol command, so the paper has a paper.toml
    and the protocol drives the carry. Pointing at
    `hygiene.restore_parts` sends the reader two floors down: past the
    config that would have done it, into a function they then call by
    hand — and copying the part alone is enough for some parts and not
    others, so the hand-written version works until the day it meets a
    footer and produces one that is present, referenced by nothing, and
    on no page.
    """
    from docxkit import package

    base = package.read_parts(project.prev)
    base["customXml/item1.xml"] = (
        b'<b:Sources xmlns:b="http://schemas.openxmlformats.org'
        b'/officeDocument/2006/bibliography"/>')
    write(project.prev, base)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    run_cli(monkeypatch, "revision", "validate", "--no-word",
            "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "LOST customXml/item1.xml" in out
    assert "[batch] carry" in out, out
    assert "restore_parts" not in out, (
        "the function is the mechanism; the config is the instruction")
    # and WHY the config rather than a copy: the three coordinated edits
    # a hand-written copy leaves out.
    assert "Content-Types" in out and "sectPr" in out, out


def test_ingest_says_when_a_RE_LABEL_left_the_span_UNBALANCED(monkeypatch,
                                                              project,
                                                              capsys):
    """The section's own message is what would send a reader past this:
    "the anchors are intact, nothing is lost, `revision baseline` does
    not refuse". That is right about the anchor and silent about the
    SPAN.

    The author turned a narrative citation parenthetical and Word kept
    the old right-hand boundary, so the link covers a closing bracket
    with no opening one inside the blue. Nothing else can see it — the
    anchor resolves, no character moved — and it is damage wearing a
    re-label's clothes (Aging_Well, 2026-08-25)."""
    write(project.prev, make_parts(para(
        run("As shown "),
        '<w:hyperlink w:anchor="ref_Klim2023">'
        "<w:r><w:t>Klimaviciute and Pestieau (2023)</w:t></w:r>"
        "</w:hyperlink>")))
    write(project.working, make_parts(para(
        run("As shown ("),
        '<w:hyperlink w:anchor="ref_Klim2023">'
        "<w:r><w:t>Klimaviciute and Pestieau 2023)</w:t></w:r>"
        "</w:hyperlink>")))

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "== RE-LABELLED (1) ==" in out, out
    assert "UNBALANCED" in out, out
    assert "unmatched ')'" in out, out
    assert "reached past its mention" in out, out


def test_an_ORDINARY_re_label_gets_no_span_warning(monkeypatch, project,
                                                   capsys):
    """The other side, and the one that decides whether the warning is
    worth having: an author editing the visible text of a citation is an
    ordinary edit, and a section that cried damage over one would be a
    section people stop reading."""
    _ate_a_link(project)
    write(project.working, make_parts(para(
        run("see "),
        '<w:hyperlink w:anchor="ref_Ritchie2023b">'
        "<w:r><w:t>Ritchie and Roser (2023b)</w:t></w:r></w:hyperlink>")))

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    assert "== RE-LABELLED (1) ==" in out, out
    assert "UNBALANCED" not in out, out


def test_validate_at_a_TRUTH_state_says_there_is_nothing_to_validate(
        project, monkeypatch, capsys):
    """A truth state is the NORMAL state of a paper between rounds, and
    there is no `build/batch.docx` in one.

    It used to die with `cannot read …batch.docx: [Errno 2] No such file
    or directory`, which reads as a broken installation or a lost file.
    It cost a real detour: Life_Expectancy's round-2 protocol listed
    `revision validate` as a PRECONDITION to be run green before any
    edit, and the step is not runnable as written — the protocol author
    reasonably assumed a gate ladder could be run on a clean paper.
    """
    assert not project.batch.exists(), "the fixture is at a truth state"
    monkeypatch.chdir(project.root)

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word")

    out = capsys.readouterr().out
    assert code == 3, out
    assert "no batch to validate" in out
    assert "revision status" in out, "and what to run instead"
    assert "Errno" not in out and "Traceback" not in out
    assert "pending revision(s)" in out, "and which state the paper is in"


def test_validate_says_so_when_the_MANUSCRIPT_is_missing_too(
        project, monkeypatch, capsys):
    """No batch AND no working file — `paper.toml` naming a manuscript
    that is not there. Reading the state would raise, so it is not
    read; the answer about the batch is still worth giving, and it is
    the one the reader asked for."""
    project.working.unlink()
    monkeypatch.chdir(project.root)

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word")

    out = capsys.readouterr().out
    assert code == 3, out
    assert "no batch to validate" in out
    assert "pending revision(s)" not in out, "there is nothing to read"
    assert "Errno" not in out and "Traceback" not in out
