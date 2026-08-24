"""`revision status --all` — which of nine papers is waiting on me?

The protocol is single-paper by design and every command takes one
`--paper`. That is right for doing work and wrong for deciding what to
work on: with nine papers on the protocol at once, "is anything waiting
for me?" had no answer short of nine invocations of `status`, so it was
not asked, and a proposal could sit unadjudicated in a paper nobody had
opened for a week.

The survey has one hard requirement beyond being correct: **it must not
die on a bad row.** A config that has moved, a manuscript that has been
deleted, a package Word is part-way through saving — each is a row, not
a traceback, because the eight healthy papers are the point.
"""
from __future__ import annotations

from conftest import make_parts, para, run, write

from docxkit import revision
from docxkit.revision import register, registered, registry_path, survey


def ins(text: str) -> str:
    return (f'<w:ins w:id="90" w:author="Revision" '
            f'w:date="2026-08-07T00:00:00Z">{run(text)}</w:ins>')


def paper_at(root, name="paper.docx", body=None):
    """A scaffolded paper, adopted in place the way `init` does it."""
    root.mkdir(parents=True, exist_ok=True)
    src = write(root / name, make_parts(body or para(run("The paper."))))
    return revision.init(root, src, name=root.name)


# ------------------------------------------------------------- registry

def test_init_registers_the_paper_it_scaffolds(tmp_path):
    """The list has to fill itself. A registry that must be curated by
    hand is one that is accurate on the day it is written."""
    paper = paper_at(tmp_path / "HCW")

    assert registered() == [paper.config]


def test_registering_the_same_paper_twice_adds_ONE_line(tmp_path):
    paper = paper_at(tmp_path / "HCW")

    assert register(paper.config) is False
    assert registered() == [paper.config]


def test_a_registry_entry_can_be_COMMENTED_OUT(tmp_path):
    """Plain text, one path per line, because it is a list a person
    edits: parking a finished paper should not require knowing a
    format."""
    paper = paper_at(tmp_path / "HCW")
    registry_path().write_text(f"# {paper.config}\n", encoding="utf-8")

    assert registered() == []


def test_a_path_that_no_longer_EXISTS_is_kept_not_pruned(tmp_path):
    """A project on a drive that happens to be disconnected is not a
    project that has been retired. Dropping it here is how a paper stops
    being watched without anyone deciding that it should — the survey
    reports it instead."""
    gone = tmp_path / "unplugged" / "revision" / "paper.toml"
    registry_path().parent.mkdir(parents=True, exist_ok=True)
    registry_path().write_text(f"{gone}\n", encoding="utf-8")

    assert registered() == [gone]
    (row,) = survey()
    assert row.verdict == "unreadable"
    assert row.error


def test_the_registry_path_follows_its_environment_variable(tmp_path,
                                                            monkeypatch):
    """Not a convenience: without it every test that scaffolds a paper
    would append to the author's real machine-wide list."""
    elsewhere = tmp_path / "somewhere" / "papers.txt"
    monkeypatch.setenv("DOCXKIT_PAPERS", str(elsewhere))

    assert registry_path() == elsewhere


def test_scan_finds_papers_at_the_depths_projects_actually_sit_at(tmp_path):
    """`Papers/_Submitted/<project>/revision/paper.toml` is four levels
    down, and the roots these live under are cloud folders with tens of
    thousands of files below them — an unbounded walk of one took over
    two minutes."""
    paper_at(tmp_path / "Top")
    paper_at(tmp_path / "Papers" / "Aging_Well")
    paper_at(tmp_path / "Papers" / "_Submitted" / "LI7")
    registry_path().unlink()                    # scan must find them anyway

    found = revision.scan(tmp_path)

    assert len(found) == 3, found
    assert registered() == sorted(found)


# --------------------------------------------------------------- survey

def test_a_settled_paper_on_a_current_baseline_is_TRUTH(tmp_path):
    paper_at(tmp_path / "HCW")

    (row,) = survey()

    assert row.verdict == "truth"
    assert row.state is not None and row.state.pending == 0
    assert not row.stale and not row.staged


def test_a_paper_with_pending_revisions_is_a_PROPOSAL(tmp_path):
    paper = paper_at(tmp_path / "HCW")
    write(paper.working, make_parts(para(run("x "), ins("proposed"))))

    (row,) = survey()

    assert row.verdict == "PROPOSAL"
    assert row.state is not None and row.state.pending == 1


def test_a_settled_paper_whose_BASELINE_has_drifted_is_stale(tmp_path):
    """The state the author cannot see from the file: both count 0
    pending, and they are not the same paper."""
    paper = paper_at(tmp_path / "HCW")
    write(paper.working, make_parts(para(run("accepted, and moved on"))))

    (row,) = survey()

    assert row.verdict == "stale"
    assert row.stale == ("word/document.xml",)


def test_a_PROPOSAL_is_not_also_reported_as_stale(tmp_path):
    """`if current.is_truth` — while a proposal is pending the two files
    are SUPPOSED to differ, and saying "baseline stale" about every one
    of them is how a warning stops being read. `status` has always been
    careful about this; the survey inherited the care and not a test,
    and a mutant that asked drift of everything survived."""
    paper = paper_at(tmp_path / "HCW")
    write(paper.working, make_parts(para(run("x "), ins("proposed"))))

    (row,) = survey()

    assert row.verdict == "PROPOSAL"
    assert row.stale == (), "a pending proposal is not a stale baseline"


def test_a_batch_STAGED_but_not_promoted_is_reported(tmp_path):
    """It is not a state of the manuscript, so `status` cannot show it —
    and it is exactly the thing forgotten between sessions."""
    paper = paper_at(tmp_path / "HCW")
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(para(run("a redline"))))

    (row,) = survey()

    assert row.staged is True


def test_a_MISSING_manuscript_is_a_row_and_not_a_crash(tmp_path):
    paper = paper_at(tmp_path / "HCW")
    paper.working.unlink()

    (row,) = survey()

    assert row.verdict == "missing"
    assert "no manuscript at" in row.error


def test_ONE_bad_paper_does_not_hide_the_others(tmp_path):
    """The whole reason the survey catches exceptions per row: a survey
    that dies on the first bad entry cannot tell you about the eight
    good ones."""
    paper_at(tmp_path / "AFI")
    broken = paper_at(tmp_path / "Broken")
    broken.config.write_text("this is not toml [[[", encoding="utf-8")
    paper_at(tmp_path / "HCW")

    rows = survey()

    assert len(rows) == 3
    assert sorted(r.verdict for r in rows) == ["truth", "truth", "unreadable"]
    assert [r.name for r in rows if r.verdict == "unreadable"] == ["Broken"]


def test_a_paper_open_in_WORD_is_flagged(tmp_path, monkeypatch):
    """A handback cannot land while Word holds the file, and finding out
    at `promote` is finding out too late."""
    paper_at(tmp_path / "HCW")
    monkeypatch.setattr(revision.package, "is_locked", lambda p: True)

    (row,) = survey()

    assert row.locked is True


def test_the_survey_reads_and_writes_NOTHING(tmp_path):
    """It runs across every paper the author has, including ones with a
    proposal open in Word. Read-only is what makes that safe."""
    paper = paper_at(tmp_path / "HCW")
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")
              if p.is_file()}

    survey()

    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")
             if p.is_file()}
    assert after == before
    assert paper.working.exists()


# ------------------------------------------------------------ the view

def _cli(monkeypatch, *args):
    from test_cli import run_cli
    return run_cli(monkeypatch, "revision", "status", *args)


def test_the_view_puts_the_papers_waiting_on_you_FIRST(tmp_path, monkeypatch,
                                                       capsys):
    """Ordered by what it costs to ignore. A survey read top-down should
    reach the proposal before the eight settled papers."""
    paper_at(tmp_path / "Zzz_settled")
    waiting = paper_at(tmp_path / "Aaa_waiting")
    write(waiting.working, make_parts(para(run("x "), ins("proposed"))))

    code, _ = _cli(monkeypatch, "--all")
    out = capsys.readouterr().out

    assert out.index("Aaa_waiting") < out.index("Zzz_settled"), out
    assert "PROPOSAL" in out and "1 pending (1 in document)" in out
    assert code == 1, "a pending proposal is exit 1, as it is for one paper"


def test_the_view_exits_4_on_a_STALE_baseline_and_0_when_all_is_well(
        tmp_path, monkeypatch, capsys):
    paper = paper_at(tmp_path / "HCW")

    code, _ = _cli(monkeypatch, "--all")
    capsys.readouterr()
    assert code == 0

    write(paper.working, make_parts(para(run("accepted, and moved on"))))
    code, _ = _cli(monkeypatch, "--all")
    assert code == 4, capsys.readouterr().out


def test_a_row_that_cannot_be_READ_exits_2(tmp_path, monkeypatch, capsys):
    """Neither of the two states the protocol has, and reporting it as
    truth would be a lie."""
    broken = paper_at(tmp_path / "Broken")
    broken.config.write_text("not toml [[[", encoding="utf-8")

    code, _ = _cli(monkeypatch, "--all")

    assert code == 2, capsys.readouterr().out


def test_a_long_paper_name_says_that_it_was_TRUNCATED(tmp_path,
                                                      monkeypatch, capsys):
    """"Coercion or Persuasion? Dete" reads as a name someone typed
    badly. The ellipsis says the ROW is short, not the paper."""
    root = tmp_path / "Long"
    root.mkdir()
    src = write(root / "p.docx", make_parts(para(run("x"))))
    revision.init(root, src,
                  name="Coercion or Persuasion? Determinants of Style")

    _cli(monkeypatch, "--all")
    out = capsys.readouterr().out

    assert "Coercion or Persuasion? Determi…" in out, out


def test_an_EMPTY_registry_says_how_to_fill_it(tmp_path, monkeypatch,
                                               capsys):
    code, _ = _cli(monkeypatch, "--all")
    out = capsys.readouterr().out

    assert code == 0
    assert "no papers registered" in out
    assert "--scan" in out and str(registry_path()) in out


def test_SCAN_registers_what_it_finds_and_then_surveys(tmp_path, monkeypatch,
                                                       capsys):
    paper_at(tmp_path / "Papers" / "Aging_Well")
    paper_at(tmp_path / "Papers" / "_Submitted" / "LI7")
    registry_path().unlink()

    code, _ = _cli(monkeypatch, "--all", "--scan", str(tmp_path))
    out = capsys.readouterr().out

    assert "2 paper(s)" in out
    assert "Aging_Well" in out and "LI7" in out
    assert code == 0
    assert len(registered()) == 2


def test_the_survey_never_needs_a_paper_to_be_current(tmp_path, monkeypatch,
                                                      capsys):
    """`--paper` resolves by walking up from the cwd, and the survey is
    asked from anywhere — a shell that happens to sit outside every
    project must still get the list rather than "no paper.toml at or
    above here"."""
    paper_at(tmp_path / "HCW")
    monkeypatch.chdir(tmp_path.parent)

    code, _ = _cli(monkeypatch, "--all")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "HCW" in out



def test_the_registry_lands_under_LOCALAPPDATA_when_the_variable_is_unset(
        monkeypatch):
    """What a real machine does, and what every test here overrides."""
    from docxkit.revision import REGISTRY_ENV

    monkeypatch.delenv(REGISTRY_ENV, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/Someone/AppData/Local")

    found = registry_path()

    assert found.parts[-2:] == ("docxkit", "papers.txt")
    assert "AppData" in str(found)


def test_the_registry_falls_back_to_HOME_when_the_platform_says_nothing(
        monkeypatch):
    """Neither variable set — a bare POSIX shell, or a Windows session
    with a scrubbed environment. `~/.local/share` is the convention, and
    a registry that landed in the working directory instead would be a
    different list depending on where you ran from."""
    from docxkit.revision import REGISTRY_ENV

    monkeypatch.delenv(REGISTRY_ENV, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    found = registry_path()

    assert found.parts[-4:] == (".local", "share", "docxkit", "papers.txt")
    assert found.is_absolute(), "absolute, or the list follows the cwd"


def test_one_UNREADABLE_paper_does_not_end_the_survey(tmp_path, monkeypatch):
    """The docstring's one hard requirement, and nothing held it. A
    manuscript on a drive that went away is a ROW; the papers after it
    in the registry are the ones nobody has looked at, and an aborted
    sweep hides exactly those."""
    good = paper_at(tmp_path / "good")
    bad = paper_at(tmp_path / "bad")
    real = revision.state

    def explode(path, *args, **kw):
        if str(path) == str(bad.working):
            raise OSError("the drive went away")
        return real(path, *args, **kw)

    monkeypatch.setattr(revision, "state", explode)

    rows = survey()

    assert len(rows) == 2, "the good paper is still reported"
    (broken,) = [r for r in rows if r.config == bad.config]
    (fine,) = [r for r in rows if r.config == good.config]
    assert broken.state is None
    assert "OSError" in broken.error and "drive went away" in broken.error
    assert fine.state is not None, "the healthy row is unaffected"
