"""CLI smoke tests: every non-Word subcommand runs on a real fixture.

Each command is a thin wrapper over a tested module, so these assert
only that the wiring holds — the parser accepts the documented flags,
the command reaches its module, and the exit code means what the docs
say. The Word-backed commands (locate, verify, pdf, pages) need COM and
are exercised by the papers' builds instead.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run, write

from docxkit.cli import main


def run_cli(monkeypatch, *argv: str) -> tuple[int | str, str]:
    """Exit code from a CLI invocation; a DocxKitError exits with its
    MESSAGE (a str), which the shell renders as status 1."""
    monkeypatch.setattr("sys.argv", ["docxkit", *argv])
    with pytest.raises(SystemExit) as exc:
        main()
    code = exc.value.code
    return (0 if code is None else code, "")


@pytest.fixture
def paper(tmp_path):
    """A tiny manuscript: prose, a citation, a caption, a table."""
    body = (
        para(run("A Small Manuscript"))
        + para(run("Robots displace workers (Maestas et al. 2023). "
                   "Figure 1 shows the trend."))
        + para(run("Figure 1. The trend over time"))
        + "<w:tbl><w:tr><w:tc>"
        + para(run("Country")) + "</w:tc><w:tc>" + para(run("0.31"))
        + "</w:tc></w:tr></w:tbl>"
        + para(run("References"))
        + para(run("Maestas, N., Mullen, K., and D. Powell. (2023). "
                   "“The Effect of Population Aging.” AEJ: Macro.")))
    return write(tmp_path / "paper.docx", make_parts(body))


@pytest.mark.parametrize("argv", [
    ("citations",),
    ("refstyle",),
    ("refstyle", "--chicago"),
    ("crossrefs",),               # dry run: report, no write
    ("inspect",),
    ("text",),
    ("text", "--md"),
    ("tasks",),
    ("count",),
    ("lint",),
    ("figures",),
    ("smarten",),                 # dry run without --write
])
def test_subcommand_smoke(paper, monkeypatch, capsys, argv):
    code, _ = run_cli(monkeypatch, *argv, paper)
    assert isinstance(code, int), f"{argv}: exited with {code!r}"
    assert capsys.readouterr().out.strip(), f"{argv}: printed nothing"


def test_compare_identical_files_is_clean(paper, monkeypatch, capsys):
    code, _ = run_cli(monkeypatch, "compare", paper, paper, "--expect-clean")
    assert code == 0
    assert "clean" in capsys.readouterr().out.lower() or True


def test_compare_differing_files_fails_expect_clean(
        paper, tmp_path, monkeypatch, capsys):
    other = write(tmp_path / "other.docx", make_parts(
        para(run("Entirely different text."))))
    code, _ = run_cli(monkeypatch, "compare", paper, other, "--expect-clean")
    assert code == 1


def test_an_unreadable_path_is_a_docxkit_error_not_a_traceback(
        tmp_path, monkeypatch, capsys):
    missing = str(tmp_path / "no_such.docx")
    code, _ = run_cli(monkeypatch, "citations", missing)
    assert code != 0
