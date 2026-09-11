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
    # registered AFTER the bad one: the papers its docstring is about, and
    # the ones `continue` read as `break` silently dropped (mutation run,
    # 2026-09-11 — with the bad paper last, nothing came after it to lose)
    after = paper_at(tmp_path / "after")
    real = revision.state

    def explode(path, *args, **kw):
        if str(path) == str(bad.working):
            raise OSError("the drive went away")
        return real(path, *args, **kw)

    monkeypatch.setattr(revision._registry, "state", explode)

    rows = survey()

    assert [r.config for r in rows] == [good.config, bad.config,
                                        after.config], (
        "the papers registered AFTER the bad one are still reported")
    (broken,) = [r for r in rows if r.config == bad.config]
    assert broken.state is None
    assert "OSError" in broken.error and "drive went away" in broken.error
    assert all(r.state is not None for r in rows if r is not broken), (
        "the healthy rows are unaffected")


# --- the exit code is the ROWS' ---------------------------------------
#
# The rank table and the worst-row arithmetic were `cli._VERDICT_RANK`
# and the tail of `cli.cmd_revision_survey` until 2026-09-11, testable
# only through `argv`. They are `Survey.rank`, `Survey.exit_code` and
# `revision.survey_exit_code` now; the `_cli` tests above still pin
# that the command hands the number on unchanged.

def _row(verdict: str, root) -> revision.Survey:
    """A row carrying `verdict`, built the way `survey` builds it."""
    from pathlib import Path
    if verdict == "unreadable":
        return revision.Survey(config=Path("x/revision/paper.toml"),
                               paper=None, state=None, error="TOMLDecodeError")
    paper = paper_at(root / verdict)
    if verdict == "missing":
        return revision.Survey(config=paper.config, paper=paper, state=None,
                               missing=True, error="no manuscript")
    if verdict == "PROPOSAL":
        write(paper.working, make_parts(para(run("x "), ins("proposed"))))
    elif verdict == "stale":
        write(paper.working, make_parts(para(run("accepted, moved on"))))
    (found,) = survey([paper.config])
    return found


def test_every_verdict_has_a_rank_and_the_order_is_worst_first(tmp_path):
    rows = [_row(v, tmp_path) for v in revision._registry.VERDICTS]
    assert [r.verdict for r in rows] == list(revision._registry.VERDICTS), (
        "the fixture does not produce the verdict it names")
    assert [r.rank for r in rows] == [0, 1, 2, 3, 4]


def test_each_row_exits_on_the_scale_ONE_paper_uses(tmp_path):
    codes = {v: _row(v, tmp_path).exit_code
             for v in revision._registry.VERDICTS}
    assert codes == {"unreadable": 2, "missing": 2, "PROPOSAL": 1,
                     "stale": 4, "truth": 0}


def test_the_survey_exits_with_its_WORST_row_not_its_largest_code(tmp_path):
    """A stale baseline is 4 and an unreadable row is 2, and the
    unreadable one is worse: it is neither of the states the protocol
    has. The worst by RANK wins, not the biggest number."""
    stale, broken, truth = (_row(v, tmp_path)
                            for v in ("stale", "unreadable", "truth"))
    assert revision.survey_exit_code([stale, truth]) == 4
    assert revision.survey_exit_code([stale, broken, truth]) == 2
    assert revision.survey_exit_code([truth]) == 0


def test_an_empty_survey_is_nothing_waiting():
    assert revision.survey_exit_code([]) == 0


# --- the gaps the mutation run of 2026-09-11 found ---------------------
#
# `revision/_registry.py` measured as a half for the first time: 211
# mutants, 30 real survivors. None in the exit-code code above; all in
# the registry and the survey around it. Two more are argued in
# tools/equivalents.toml.


def test_the_registry_header_is_written_ONCE_at_the_top(tmp_path):
    """Into a file that is empty, and never again: a list a person edits
    says what it is on its first line, and a header written again after
    every paper is noise between the entries. Three papers, so a header
    before every entry and one before all but the first both miscount."""
    first = paper_at(tmp_path / "AFI")
    second = paper_at(tmp_path / "HCW")
    third = paper_at(tmp_path / "LI7")

    text = registry_path().read_text(encoding="utf-8")

    header = "# Papers on the single-file revision protocol.\n"
    assert text.startswith(header), text
    assert text.count(header) == 1, text
    assert registered() == [first.config, second.config, third.config]


def test_register_says_whether_the_paper_was_NEW(tmp_path):
    paper = paper_at(tmp_path / "HCW")
    registry_path().unlink()

    assert register(paper.config) is True
    assert register(paper.config) is False
    assert registered() == [paper.config]


def test_an_entry_spelled_DIFFERENTLY_is_still_the_same_paper(tmp_path):
    """Entries are compared resolved. A line with `..` in it — a hand
    edit, or a scan started from another folder — names the same file,
    and a second line for it would survey the paper twice."""
    paper = paper_at(tmp_path / "HCW")
    roundabout = paper.config.parent / ".." / "revision" / paper.config.name
    registry_path().write_text(f"{roundabout}\n", encoding="utf-8")

    assert register(paper.config) is False
    assert registered() == [roundabout], "no second line was added"


def test_the_registry_folder_is_CREATED_however_deep(tmp_path, monkeypatch):
    deep = tmp_path / "not" / "there" / "yet" / "papers.txt"
    monkeypatch.setenv("DOCXKIT_PAPERS", str(deep))

    paper = paper_at(tmp_path / "HCW")

    assert registered() == [paper.config]


def test_scan_stops_at_its_DEPTH(tmp_path):
    """Four levels reach `<root>/<area>/<project>/revision/paper.toml` and
    no further, on purpose: the roots are cloud folders. A config one
    level deeper is not found by default — and IS found when the depth
    is raised, so this is the bound and not a fixture nothing could find."""
    deeper = paper_at(tmp_path / "Papers" / "_Submitted" / "2025" / "LI7")
    registry_path().unlink()

    assert revision.scan(tmp_path) == []
    assert [p.resolve() for p in revision.scan(tmp_path, depth=5)] == [
        deeper.config]


def test_a_row_is_NAMED_by_its_project_folder_whatever_that_is_called():
    """`revision/` is skipped because it is the protocol's folder and says
    nothing about the paper; any other folder IS the name — including one
    that sorts before "revision" and one that sorts after it, which is
    where `==` read as `<=` or `>=` went wrong."""
    from pathlib import Path

    def named(*parts: str) -> str:
        return revision.Survey(config=Path(*parts), paper=None, state=None,
                               error="unreadable").name

    assert named("Projects", "HCW", "revision", "paper.toml") == "HCW"
    assert named("Projects", "Aging_Well", "paper.toml") == "Aging_Well"
    assert named("Projects", "zeta", "paper.toml") == "zeta"


def test_an_unreadable_row_claims_NOTHING_about_the_file():
    """No lock, no staged batch, not missing: nothing was read, so
    nothing is reported — a row defaulting to "open in Word" would send
    the author to close a file that is not open."""
    from pathlib import Path

    row = revision.Survey(config=Path("x/revision/paper.toml"), paper=None,
                          state=None, error="OSError: the drive went away")

    assert (row.locked, row.staged, row.missing) == (False, False, False)


def test_an_error_OR_a_missing_state_is_unreadable_on_its_own(tmp_path):
    """Two ways a paper goes unread, and each is enough alone: an error
    with a state still in hand, and a paper whose state was never read.
    Read as needing both, the first came back "truth" and the second
    raised on the state it does not have."""
    paper = paper_at(tmp_path / "HCW")
    here = revision.state(paper.working)

    with_error = revision.Survey(config=paper.config, paper=paper,
                                 state=here,
                                 error="OSError: the drive went away")
    no_state = revision.Survey(config=paper.config, paper=paper, state=None)

    assert with_error.verdict == "unreadable"
    assert no_state.verdict == "unreadable"


def test_a_MISSING_manuscript_does_not_end_the_survey(tmp_path):
    """The row is appended and the walk goes ON. `continue` read as
    `break` stopped at the first missing file and dropped every paper
    registered after it, silently — the good rows this exists for."""
    gone = paper_at(tmp_path / "Aaa_unplugged")
    gone.working.unlink()
    paper_at(tmp_path / "Bbb_fine")
    paper_at(tmp_path / "Ccc_fine")

    assert [r.verdict for r in survey()] == ["missing", "truth", "truth"]


def test_a_survey_row_quotes_120_characters_of_an_ERROR_on_both_branches(
        tmp_path, monkeypatch):
    """One line per paper in a table of every paper: a config that will
    not load and a manuscript that will not read both quote their error,
    cut at the same width, so a traceback-sized message cannot push the
    row past a screen. Pinned rather than argued because the line that
    cuts it appears twice, and an argued equivalence has to be anchored
    at exactly one line."""
    from pathlib import Path

    long = "the drive went away " * 20
    unloadable = paper_at(tmp_path / "Aaa_unloadable")
    unreadable = paper_at(tmp_path / "Bbb_unreadable")
    real_load, real_state = revision.load_paper, revision.state

    def load(config, *a, **kw):
        if Path(config) == unloadable.config:
            raise OSError(long)
        return real_load(config, *a, **kw)

    def state(path, *a, **kw):
        if str(path) == str(unreadable.working):
            raise OSError(long)
        return real_state(path, *a, **kw)

    monkeypatch.setattr(revision._registry, "load_paper", load)
    monkeypatch.setattr(revision._registry, "state", state)

    rows = survey()

    assert [len(r.error) for r in rows] == [120, 120], rows
    assert all(r.error.startswith("OSError: the drive went away")
               for r in rows)
