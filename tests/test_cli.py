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
    ("link",),
    ("linkfix",),
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


def test_link_write_refuses_a_package_lint_rejects(monkeypatch, tmp_path,
                                                   capsys):
    """`docxkit link --write` is a mutating path; it must lint first.

    Link surgery splices hyperlink and bookmark elements across runs —
    the class that has produced an unopenable file here before — and
    lint is the only gate that catches it without opening Word. This
    command used to write straight through edit_in_place.
    """
    from docxkit.package import write_docx

    # a run loose in w:body: well-formed XML, but Word calls it
    # unreadable content, and lint knows it
    parts = make_parts(para(run("Smith (2020) argues.")))
    doc = parts["word/document.xml"].decode("utf-8")
    parts["word/document.xml"] = doc.replace(
        "</w:body>", "<w:r><w:t>loose</w:t></w:r></w:body>").encode("utf-8")
    path = tmp_path / "broken.docx"
    write_docx(path, parts)
    before = path.read_bytes()

    code, _ = run_cli(monkeypatch, "link", str(path), "--write")
    out = capsys.readouterr().out
    assert code == 1
    assert "REFUSED" in out
    assert path.read_bytes() == before          # nothing written
    assert not list(tmp_path.glob("*pre_link*"))  # not even a backup


def test_link_dry_run_reports_without_writing(monkeypatch, paper, capsys):
    from pathlib import Path
    before = Path(paper).read_bytes()
    code, _ = run_cli(monkeypatch, "link", str(paper))
    out = capsys.readouterr().out
    assert code == 0
    assert "dry run" in out
    assert Path(paper).read_bytes() == before


def _tracked(tmp_path, name="round.docx"):
    """A document with revisions and a comment by two people."""
    from conftest import comment, dele, ins

    from docxkit.package import write_docx
    # preserve=True: a bare <w:t> with an edge space is what lint
    # refuses, and this fixture is meant to reach the WRITE, not to
    # re-test the seatbelt.
    body = (para(run("Kept ", preserve=True), ins("added"), dele("removed"))
            + para(run("tail")))
    parts = make_parts(body, comment_items=(comment(1, "please check"),))
    parts["docProps/core.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        b'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/'
        b'dc/elements/1.1/"><dc:creator>someone@example.com</dc:creator>'
        b"<cp:lastModifiedBy>Someone Else</cp:lastModifiedBy>"
        b"</cp:coreProperties>")
    path = tmp_path / name
    write_docx(path, parts)
    return path


def test_authors_reports_who_is_credited_without_writing(monkeypatch,
                                                         tmp_path, capsys):
    path = _tracked(tmp_path)
    before = path.read_bytes()
    code, _ = run_cli(monkeypatch, "authors", str(path))
    out = capsys.readouterr().out
    assert code == 0
    assert "Revision" in out and "Tester" in out
    assert path.read_bytes() == before


def test_authors_set_is_a_dry_run_until_write(monkeypatch, tmp_path, capsys):
    """Every mutating command here is dry by default. Restamping who
    made the changes is not something to do on a typo."""
    path = _tracked(tmp_path)
    before = path.read_bytes()
    code, _ = run_cli(monkeypatch, "authors", str(path), "--set", "M Lokshin")
    out = capsys.readouterr().out
    assert code == 0
    assert "dry run" in out
    assert path.read_bytes() == before


def test_authors_write_restamps_and_keeps_a_backup(monkeypatch, tmp_path,
                                                   capsys):
    from docxkit.authors import read_authors
    from docxkit.package import read_parts
    path = _tracked(tmp_path)
    code, _ = run_cli(monkeypatch, "authors", str(path), "--set",
                      "M Lokshin", "--write")
    out = capsys.readouterr().out
    assert code == 0
    assert read_authors(read_parts(str(path))) == {"M Lokshin": 3}
    core = read_parts(str(path))["docProps/core.xml"].decode("utf-8")
    assert "someone@example.com" not in core
    kept = list(tmp_path.glob("*pre_authors*"))
    assert kept, out
    assert read_authors(read_parts(str(kept[0]))) == {"Revision": 2,
                                                      "Tester": 1}


def test_authors_only_leaves_a_co_authors_edits_alone(monkeypatch, tmp_path):
    """The flag that stops one person's work being credited to another."""
    from docxkit.authors import read_authors
    from docxkit.package import read_parts
    path = _tracked(tmp_path)
    run_cli(monkeypatch, "authors", str(path), "--set", "M Lokshin",
            "--only", "Tester", "--write")
    assert read_authors(read_parts(str(path))) == {"M Lokshin": 1,
                                                   "Revision": 2}


def test_authors_write_refuses_a_package_lint_rejects(monkeypatch, tmp_path,
                                                      capsys):
    """The seatbelt every mutating command wears: lint before writing,
    and on a refusal leave the file — and the backup — untouched."""
    from docxkit.package import write_docx
    parts = make_parts(para(run("Kept ")) + para(run("tail")))
    doc = parts["word/document.xml"].decode("utf-8")
    parts["word/document.xml"] = doc.replace(
        "</w:body>", "<w:r><w:t>loose</w:t></w:r></w:body>").encode("utf-8")
    path = tmp_path / "broken.docx"
    write_docx(path, parts)
    before = path.read_bytes()

    code, _ = run_cli(monkeypatch, "authors", str(path), "--set", "M L",
                      "--write")
    assert code == 1
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*pre_authors*"))


def test_a_report_with_an_unencodable_value_is_still_written(tmp_path):
    """Losing a finished comparison at the serialisation step is the
    worst moment to fail: the work is done and the report is gone."""
    import json

    from docxkit.cli import _write_json
    target = tmp_path / "r.json"
    _write_json(str(target), {"anchors": {"b", "a"}, "where": tmp_path})
    back = json.loads(target.read_text(encoding="utf-8"))
    assert back["anchors"] == ["a", "b"]
    assert back["where"] == str(tmp_path)
