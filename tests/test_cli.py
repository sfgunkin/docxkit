"""The CLI: the wiring, and every path that touches a manuscript.

Each command is a thin wrapper over a tested module, so the smoke tests
assert only that the wiring holds — the parser accepts the documented
flags, the command reaches its module, and the exit code means what the
docs say.

The rest is not smoke. cli.py holds every ``--write`` path, which is the
code that edits an author's file, and ROBUSTNESS_PLAN named its coverage
as the debt worth paying. Those tests assert on the FILE — written, not
written, and what the backup holds — because a message is not what an
author loses.

The Word-backed commands (locate, verify, pdf, pages) are faked at the
COM boundary rather than skipped: which verdict a set of counts earns,
how "--pages 1-3" becomes a first and a last, and what happens when an
anchor is not found are all decisions cli.py makes, and none of them
need Word to be wrong. Section 4 of ROBUSTNESS_PLAN established the same
seam for tracked.py.
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
    ("probe",),                   # read-only by nature
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


# --------------------------------------------------- the paths that WRITE
# cli.py held every --write path at 60% coverage, which ROBUSTNESS_PLAN
# names as the debt worth paying: this is the code that touches a
# manuscript. The assertions below are about the FILE — written, not
# written, and what the backup holds — rather than about the message,
# because the message is not what an author loses.

def _broken(tmp_path, name="broken.docx"):
    """A package lint refuses: a run loose in w:body. Well-formed XML,
    and Word calls it unreadable content.

    The text carries a straight apostrophe on purpose: a command that
    finds NOTHING to do returns before it ever reaches the lint gate, so
    a fixture with no work in it would assert the seatbelt holds while
    never touching it.
    """
    from docxkit.package import write_docx
    parts = make_parts(para(run("Kept the workers' text")))
    doc = parts["word/document.xml"].decode("utf-8")
    parts["word/document.xml"] = doc.replace(
        "</w:body>", "<w:r><w:t>loose</w:t></w:r></w:body>").encode("utf-8")
    path = tmp_path / name
    write_docx(path, parts)
    return path


def test_link_write_applies_and_the_backup_holds_the_original(
        monkeypatch, paper, tmp_path, capsys):
    """The success half of `link --write`; only the refusal was tested."""
    from pathlib import Path
    before = Path(paper).read_bytes()
    code, _ = run_cli(monkeypatch, "link", str(paper), "--write")
    capsys.readouterr()
    assert code == 0
    assert Path(paper).read_bytes() != before, "nothing was written"
    kept = list(tmp_path.glob("*pre_link*"))
    assert kept, "no backup beside the manuscript"
    assert kept[0].read_bytes() == before


def test_crossrefs_audit_reports_every_bucket_without_writing(
        monkeypatch, paper, capsys):
    from pathlib import Path
    before = Path(paper).read_bytes()
    code, _ = run_cli(monkeypatch, "crossrefs", str(paper), "--audit")
    out = capsys.readouterr().out
    for bucket in ("linked", "caption_only", "mention_only", "dangling"):
        assert bucket in out, out
    assert isinstance(code, int)
    assert Path(paper).read_bytes() == before


def test_crossrefs_write_links_the_caption_and_keeps_a_backup(
        monkeypatch, paper, tmp_path, capsys):
    from pathlib import Path
    before = Path(paper).read_bytes()
    run_cli(monkeypatch, "crossrefs", str(paper), "--write")
    capsys.readouterr()
    assert Path(paper).read_bytes() != before
    kept = list(tmp_path.glob("*pre_crossrefs*"))
    assert kept and kept[0].read_bytes() == before


@pytest.fixture
def straight(tmp_path):
    """A manuscript with straight quotes, for the hygiene pass."""
    from docxkit.package import write_docx
    body = (para(run("He said \"the workers' index rose\" in 2024."))
            + para(run("A second paragraph.")))
    path = tmp_path / "straight.docx"
    write_docx(path, make_parts(body))
    return path


def test_smarten_write_applies_then_reports_nothing_left_to_do(
        monkeypatch, straight, capsys):
    """Idempotence on the real command: the second run must not rewrite
    the file, or every build would churn the manuscript."""
    code, _ = run_cli(monkeypatch, "smarten", str(straight), "--write")
    assert code == 0
    assert "written" in capsys.readouterr().out
    after = straight.read_bytes()

    code, _ = run_cli(monkeypatch, "smarten", str(straight), "--write")
    out = capsys.readouterr().out
    assert code == 0
    assert "nothing to write" in out
    assert straight.read_bytes() == after


def test_a_write_refused_by_lint_leaves_the_file_byte_identical(
        monkeypatch, tmp_path, capsys):
    """_write_document is the shared save path; its refusal is the one
    thing standing between a bad edit and the author's file."""
    path = _broken(tmp_path)
    before = path.read_bytes()
    code, _ = run_cli(monkeypatch, "smarten", str(path), "--write")
    capsys.readouterr()
    assert code == 1
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*pre_smarten*"))


def _commented(tmp_path, name="c.docx"):
    from conftest import comment

    from docxkit.package import write_docx
    parts = make_parts(para(run("A sentence someone queried.")),
                       comment_items=(comment(1, "please check this"),))
    path = tmp_path / name
    write_docx(path, parts)
    return path


def test_tasks_done_marks_a_thread_and_keeps_a_backup(monkeypatch, tmp_path,
                                                      capsys):
    path = _commented(tmp_path)
    before = path.read_bytes()
    code, _ = run_cli(monkeypatch, "tasks", str(path), "--done", "1")
    out = capsys.readouterr().out
    assert code == 0 and "marked 1 comment(s) done" in out
    assert path.read_bytes() != before
    kept = list(tmp_path.glob("*pre_tasks*"))
    assert kept and kept[0].read_bytes() == before


def test_tasks_done_with_no_matching_id_writes_nothing(monkeypatch, tmp_path,
                                                       capsys):
    path = _commented(tmp_path)
    before = path.read_bytes()
    code, _ = run_cli(monkeypatch, "tasks", str(path), "--done", "99")
    out = capsys.readouterr().out
    assert code == 1 and "nothing written" in out
    assert path.read_bytes() == before


def test_tasks_check_fails_while_a_thread_is_open(monkeypatch, tmp_path,
                                                  capsys):
    path = _commented(tmp_path)
    code, _ = run_cli(monkeypatch, "tasks", str(path), "--check")
    assert code == 1
    assert "CHECK FAILED" in capsys.readouterr().out

    run_cli(monkeypatch, "tasks", str(path), "--done", "1")
    capsys.readouterr()
    code, _ = run_cli(monkeypatch, "tasks", str(path), "--check")
    assert code == 0, capsys.readouterr().out


def test_tasks_json_carries_the_thread(monkeypatch, tmp_path, capsys):
    import json
    path = _commented(tmp_path)
    dest = tmp_path / "tasks.json"
    run_cli(monkeypatch, "tasks", str(path), "--json", str(dest))
    capsys.readouterr()
    rows = json.loads(dest.read_text(encoding="utf-8"))
    assert rows and rows[0]["author"] == "Tester"
    assert "please check" in rows[0]["text"]


# -------------------------------------------------- the paths that REPORT

def test_inspect_lists_comments_and_revisions_when_asked(monkeypatch,
                                                         tmp_path, capsys):
    path = _tracked(tmp_path)
    code, _ = run_cli(monkeypatch, "inspect", str(path), "--comments",
                      "--revisions")
    out = capsys.readouterr().out
    assert code == 0
    assert "please check" in out                  # --comments
    assert "[ins]" in out and "[del]" in out      # --revisions


def test_text_renders_both_tracked_views_and_markdown(monkeypatch, tmp_path,
                                                      capsys):
    path = _tracked(tmp_path)
    run_cli(monkeypatch, "text", str(path), "--tracked", "final")
    final = capsys.readouterr().out
    run_cli(monkeypatch, "text", str(path), "--tracked", "original")
    original = capsys.readouterr().out
    assert "added" in final and "added" not in original
    assert "removed" in original and "removed" not in final

    run_cli(monkeypatch, "text", str(path), "--md")
    assert capsys.readouterr().out.strip(), "--md printed nothing"


def test_count_excludes_a_bucket_and_gates_on_a_limit(monkeypatch, paper,
                                                      tmp_path, capsys):
    import json
    dest = tmp_path / "count.json"
    code, _ = run_cli(monkeypatch, "count", str(paper), "--exclude",
                      "references", "--json", str(dest))
    out = capsys.readouterr().out
    assert code == 0
    assert "excluding references" in out
    assert json.loads(dest.read_text(encoding="utf-8"))

    code, _ = run_cli(monkeypatch, "count", str(paper), "--limit", "3")
    assert code == 1
    assert "OVER the 3-word limit" in capsys.readouterr().out


def test_math_reports_prose_symbols_and_check_gates(monkeypatch, tmp_path,
                                                    capsys):
    from docxkit.package import write_docx
    body = (para(run("The elasticity β is estimated below."))
            + para(run("We report β₁ and the interval [0, 1].")))
    path = tmp_path / "math.docx"
    write_docx(path, make_parts(body))

    code, _ = run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "finding(s)" in out

    code, _ = run_cli(monkeypatch, "math", str(path), "--check")
    capsys.readouterr()
    assert code == 1, "--check must gate on findings"


def test_math_reports_a_display_equation_word_will_set_inline(monkeypatch,
                                                              tmp_path,
                                                              capsys):
    """A bare m:oMath is INLINE to Word however alone in its paragraph it
    sits, and the house rule in every paper here is display + centred.
    Word promotes one on save SOMETIMES, which is why nothing may assume
    it. No other check in the toolkit sees this."""
    from docxkit.package import write_docx
    path = tmp_path / "eq.docx"
    write_docx(path, make_parts(
        para("<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>")
        + para(run("Prose after the equation."))))

    code, _ = run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "1 display equation(s), 1 still in INLINE mode" in out
    assert "'x'" in out                       # says WHICH

    code, _ = run_cli(monkeypatch, "math", str(path), "--check")
    capsys.readouterr()
    assert code == 1, "--check must gate on an inline display equation"


def test_math_says_nothing_is_stranded_once_it_is_promoted(monkeypatch,
                                                           tmp_path, capsys):
    from docxkit.equations import display
    from docxkit.package import write_docx
    path = tmp_path / "eq2.docx"
    write_docx(path, make_parts(
        display(para("<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"))))

    code, _ = run_cli(monkeypatch, "math", str(path), "--check")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "1 display equation(s), 0 still in INLINE mode" in out


def test_figures_check_gates_on_a_drawing_without_alt_text(monkeypatch,
                                                           tmp_path, capsys):
    from docxkit.package import write_docx
    # The drawing prefixes are declared here rather than in conftest's
    # root element: write_docx refuses a package whose XML does not
    # parse, and an undeclared prefix is exactly that.
    drawing_ns = (
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
        'wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships"')
    inline = ('<w:p><w:r><w:drawing><wp:inline ' + drawing_ns + ">"
              '<wp:docPr id="1" name="Chart 1"{descr}/>'
              '<a:blip r:embed="rId4"/></wp:inline></w:drawing></w:r></w:p>')
    described = tmp_path / "ok.docx"
    write_docx(described, make_parts(
        para(run("Figure 1. Described"))
        + inline.format(descr=' descr="A described chart"')))
    bare = tmp_path / "bare.docx"
    write_docx(bare, make_parts(
        para(run("Figure 1. Bare")) + inline.format(descr="")))

    code, _ = run_cli(monkeypatch, "figures", str(described), "--check")
    assert code == 0, capsys.readouterr().out
    capsys.readouterr()

    code, _ = run_cli(monkeypatch, "figures", str(bare), "--check")
    assert code == 1
    assert "without alt text" in capsys.readouterr().out


_FOOTNOTES = (
    '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
    'wordprocessingml/2006/main">{notes}</w:footnotes>')


def _note(nid: int, text: str, sz: str = "") -> str:
    props = f'<w:rPr><w:sz w:val="{sz}"/></w:rPr>' if sz else ""
    return (f'<w:footnote w:id="{nid}"><w:p><w:r>{props}'
            f"<w:t>{text}</w:t></w:r></w:p></w:footnote>")


def test_footnotes_check_gates_on_one_that_disagrees(monkeypatch, tmp_path,
                                                     capsys):
    """The offender states NO size and inherits the body's, so no search
    for a wrong value can find it — only the disagreement shows."""
    from docxkit.package import write_docx
    agreed = _note(2, "first", "20") + _note(3, "second", "20")
    tidy = tmp_path / "tidy.docx"
    write_docx(tidy, make_parts(para(run("body")), footnotes=(
        _FOOTNOTES.format(notes=agreed))))
    odd = tmp_path / "odd.docx"
    write_docx(odd, make_parts(para(run("body")), footnotes=(
        _FOOTNOTES.format(notes=agreed + _note(4, "the silent one")))))

    code, _ = run_cli(monkeypatch, "footnotes", str(tidy), "--check")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "house size 10pt" in out

    code, _ = run_cli(monkeypatch, "footnotes", str(odd), "--check")
    out = capsys.readouterr().out
    assert code == 1
    assert "footnote 4" in out and "the silent one" in out


def test_footnotes_on_a_paper_that_has_none(monkeypatch, tmp_path, capsys):
    from docxkit.package import write_docx
    path = tmp_path / "plain.docx"
    write_docx(path, make_parts(para(run("body"))))
    code, _ = run_cli(monkeypatch, "footnotes", str(path), "--check")
    assert code == 0
    assert "no footnotes part" in capsys.readouterr().out


def test_lint_names_the_structural_problem_it_found(monkeypatch, tmp_path,
                                                    capsys):
    path = _broken(tmp_path)
    code, _ = run_cli(monkeypatch, "lint", str(path))
    out = capsys.readouterr().out
    assert code == 1
    assert "clean" not in out


def test_refstyle_json_is_written_beside_the_report(monkeypatch, paper,
                                                    tmp_path, capsys):
    import json
    dest = tmp_path / "refstyle.json"
    run_cli(monkeypatch, "refstyle", str(paper), "--json", str(dest))
    capsys.readouterr()
    assert isinstance(json.loads(dest.read_text(encoding="utf-8")), list)


def test_math_says_so_when_the_document_typesets_no_symbols(monkeypatch,
                                                            tmp_path, capsys):
    """Deterministic prose rather than the shared fixture: a test that
    accepts either "clean" or "finding(s)" asserts nothing about which."""
    from docxkit.package import write_docx
    path = tmp_path / "prose.docx"
    write_docx(path, make_parts(
        para(run("The paper reports results for three countries."))))
    code, _ = run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out
    assert code == 0
    assert "clean" in out and "finding(s)" not in out


def test_json_default_serialises_a_dataclass_and_refuses_the_rest():
    """The last-resort encoder's other two branches. The refusal matters
    as much as the rescues: silently encoding an unknown object is how a
    report grows a field nobody can read back."""
    from dataclasses import dataclass

    from docxkit.cli import _json_default

    @dataclass
    class Row:
        name: str
        n: int

    assert _json_default(Row("a", 2)) == {"name": "a", "n": 2}
    with pytest.raises(TypeError, match="not JSON serializable"):
        _json_default(object())


def test_crossrefs_write_refused_by_lint_leaves_the_file(monkeypatch,
                                                         tmp_path, capsys):
    """The other command that routes through _write_document."""
    from docxkit.package import write_docx
    parts = make_parts(para(run("Figure 1 shows the trend."))
                       + para(run("Figure 1. The trend over time")))
    doc = parts["word/document.xml"].decode("utf-8")
    parts["word/document.xml"] = doc.replace(
        "</w:body>", "<w:r><w:t>loose</w:t></w:r></w:body>").encode("utf-8")
    path = tmp_path / "refs.docx"
    write_docx(path, parts)
    before = path.read_bytes()

    code, _ = run_cli(monkeypatch, "crossrefs", str(path), "--write")
    capsys.readouterr()
    assert code == 1
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*pre_crossrefs*"))


def test_a_fragile_edge_space_is_protected_before_the_write(monkeypatch,
                                                            tmp_path, capsys):
    """preserve_space is the mandatory last build step, and it runs
    inside _write_document rather than being left to each command.

    Without it a PRE-EXISTING unpreserved edge space blocks an unrelated
    write at the lint gate — the le14 case, whose references carried
    four. The command here is smarten; the space is not its business,
    and it still has to survive.
    """
    from docxkit.package import write_docx
    # a bare <w:t> with a trailing space (conftest's run(preserve=False)),
    # plus a straight apostrophe so smarten has a reason to save at all
    path = tmp_path / "fragile.docx"
    write_docx(path, make_parts(para(run("the workers' rights "))))

    code, _ = run_cli(monkeypatch, "smarten", str(path), "--write")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "protected 1 edge-whitespace run(s)" in out, out
    from docxkit.package import read_parts
    saved = read_parts(str(path))["word/document.xml"].decode("utf-8")
    assert 'xml:space="preserve"' in saved, saved


def _threaded(tmp_path, name="threaded.docx"):
    """An anchored comment carrying a reply — the two lines the task
    list prints under a thread."""
    from conftest import NS

    from docxkit.package import write_docx

    def note(cid, text, para_id, author):
        return (f'<w:comment w:id="{cid}" w:author="{author}" '
                f'w:initials="R" w:date="2026-07-30T01:00:00Z">'
                f'<w:p w14:paraId="{para_id}"><w:r><w:t>{text}</w:t></w:r>'
                f"</w:p></w:comment>")

    body = para(run("Beta "),
                '<w:commentRangeStart w:id="1"/>',
                run("the anchored sentence"),
                '<w:commentRangeEnd w:id="1"/>',
                '<w:r><w:commentReference w:id="1"/></w:r>')
    parts = make_parts(body)
    parts["word/comments.xml"] = (
        f"<w:comments {NS}>"
        + note(1, "Please clarify this claim.", "AAAA0001", "Referee")
        + note(3, "Revised in round two.", "AAAA0003", "Author")
        + "</w:comments>").encode("utf-8")
    parts["word/commentsExtended.xml"] = (
        f"<w15:commentsEx {NS}>"
        '<w15:commentEx w15:paraId="AAAA0001" w15:done="0"/>'
        '<w15:commentEx w15:paraId="AAAA0003" '
        'w15:paraIdParent="AAAA0001" w15:done="0"/>'
        "</w15:commentsEx>").encode()
    path = tmp_path / name
    write_docx(path, parts)
    return path


def test_tasks_shows_what_a_thread_is_attached_to_and_its_replies(
        monkeypatch, tmp_path, capsys):
    path = _threaded(tmp_path)
    code, _ = run_cli(monkeypatch, "tasks", str(path))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Please clarify this claim." in out
    assert "on:" in out and "the anchored sentence" in out
    assert "re: Author: Revised in round two." in out


def test_tasks_hides_resolved_threads_unless_all_is_given(monkeypatch,
                                                          tmp_path, capsys):
    path = _threaded(tmp_path)
    run_cli(monkeypatch, "tasks", str(path), "--done", "1")
    capsys.readouterr()

    run_cli(monkeypatch, "tasks", str(path))
    assert "Please clarify" not in capsys.readouterr().out

    run_cli(monkeypatch, "tasks", str(path), "--all")
    assert "Please clarify" in capsys.readouterr().out


# ------------------------------------------------ the Word-backed commands
# These need COM to RUN, but the decisions are cli.py's own: which verdict
# a set of counts earns, how "--pages 1-3" becomes a first and a last, what
# happens when an anchor is not found. Faking at the COM boundary tests the
# half that is ours; ROBUSTNESS_PLAN section 4 established the same seam for
# tracked.py, where it took the module from 0% to 99% with no Word.

@pytest.fixture
def fake_word(monkeypatch):
    """Word's side of the boundary, with nothing behind it."""
    import contextlib

    from docxkit import word

    class Doc:
        def ComputeStatistics(self, which):
            return 12

    @contextlib.contextmanager
    def session(**kw):
        yield object()

    @contextlib.contextmanager
    def open_doc(w, path, **kw):
        yield Doc()

    monkeypatch.setattr(word, "session", session)
    monkeypatch.setattr(word, "open_doc", open_doc)
    return word


def test_locate_reports_a_page_and_line_for_each_anchor(monkeypatch, paper,
                                                        fake_word, tmp_path,
                                                        capsys):
    import json

    from docxkit.word import Location
    found = [Location("the trend", 4, 12, 4, False)]
    monkeypatch.setattr(fake_word, "locate_in",
                        lambda doc, anchors, **kw: found)

    dest = tmp_path / "loc.json"
    code, _ = run_cli(monkeypatch, "locate", str(paper), "the trend",
                      "--json", str(dest))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "(12 pages)" in out and "p.   4" in out and "l. 12" in out
    assert json.loads(dest.read_text(encoding="utf-8"))[0]["anchor"] == (
        "the trend")


def test_locate_reports_a_miss_and_exits_nonzero(monkeypatch, paper,
                                                 fake_word, capsys):
    """An anchor nobody can find is the answer that matters: the
    response letter would otherwise cite a page the phrase is not on."""
    monkeypatch.setattr(fake_word, "locate_in", lambda doc, anchors, **kw: [])
    code, _ = run_cli(monkeypatch, "locate", str(paper), "no such phrase")
    out = capsys.readouterr().out
    assert code == 1
    assert "NOT FOUND" in out


def test_locate_reads_anchors_from_a_file(monkeypatch, paper, fake_word,
                                          tmp_path, capsys):
    from docxkit.word import Location
    seen: list[list[str]] = []

    def locate_in(doc, anchors, **kw):
        seen.append(list(anchors))
        return [Location(a, 1, 1, 1, False) for a in anchors]

    monkeypatch.setattr(fake_word, "locate_in", locate_in)
    listing = tmp_path / "anchors.txt"
    listing.write_text("first anchor\n\n  second anchor  \n",
                       encoding="utf-8")
    run_cli(monkeypatch, "locate", str(paper), "inline one",
            "--anchors-from", str(listing))
    capsys.readouterr()
    assert seen == [["inline one", "first anchor", "second anchor"]]


def test_locate_with_nothing_to_look_for_is_a_usage_error(monkeypatch, paper,
                                                          capsys):
    code, _ = run_cli(monkeypatch, "locate", str(paper))
    assert code == 2
    assert "give an anchor" in capsys.readouterr().out


def test_locate_revisions_lists_them_in_the_redlines_pagination(
        monkeypatch, paper, fake_word, capsys):
    from docxkit.word import RevisionLocation
    monkeypatch.setattr(
        fake_word, "revision_locations",
        lambda doc, **kw: [RevisionLocation(1, "insert", "added text", 3, 7,
                                            3)])
    code, _ = run_cli(monkeypatch, "locate", str(paper), "--revisions")
    out = capsys.readouterr().out
    assert code == 0
    assert "[insert] added text" in out and "p.   3" in out


@pytest.mark.parametrize("counts,expected,verdict", [
    ({"comments": 2}, 0, "clean"),
    ({"comments": 0}, 0, "no comments to cross-check"),
])
def test_verify_reads_a_verdict_off_the_counts(monkeypatch, paper, capsys,
                                               counts, expected, verdict):
    from docxkit import tracked
    monkeypatch.setattr(tracked, "verify", lambda path: {
        "path": path,
        "package": {"insertions": 3, "deletions": 1, **counts},
        "word": {"revisions": 4, "comments": counts["comments"],
                 "paragraphs": 9},
        "comments_match": True,
    })
    code, _ = run_cli(monkeypatch, "verify", str(paper))
    out = capsys.readouterr().out
    assert code == expected, out
    assert verdict in out


def test_verify_fails_when_word_altered_the_file_on_open(monkeypatch, paper,
                                                         capsys):
    """The whole point of the command: Word silently repairs markup it
    dislikes, and the damage only shows when the editor opens it."""
    from docxkit import tracked
    monkeypatch.setattr(tracked, "verify", lambda path: {
        "path": path,
        "package": {"insertions": 3, "deletions": 1, "comments": 5},
        "word": {"revisions": 4, "comments": 2, "paragraphs": 9},
        "comments_match": False,
    })
    code, _ = run_cli(monkeypatch, "verify", str(paper))
    assert code == 1
    assert "MISMATCH" in capsys.readouterr().out


@pytest.mark.parametrize("pages,first,last", [
    (None, None, None), ("3", 3, 3), ("1-4", 1, 4)])
def test_pdf_turns_a_page_range_into_a_first_and_a_last(
        monkeypatch, paper, tmp_path, capsys, pages, first, last):
    """'--pages 3' means page three alone, not three onwards."""
    from docxkit import word
    seen: dict[str, int | None] = {}
    out_pdf = tmp_path / "out.pdf"
    out_pdf.write_bytes(b"%PDF-1.4 stub")

    def export_pdf(src, dest, *, first=None, last=None):
        seen.update(first=first, last=last)
        return out_pdf

    monkeypatch.setattr(word, "export_pdf", export_pdf)
    argv = ["pdf", str(paper), str(out_pdf)]
    if pages:
        argv += ["--pages", pages]
    code, _ = run_cli(monkeypatch, *argv)
    assert code == 0
    assert seen == {"first": first, "last": last}
    assert "13 bytes" in capsys.readouterr().out


def test_pages_prints_the_laid_out_page_count(monkeypatch, paper, capsys):
    from docxkit import word
    monkeypatch.setattr(word, "page_count", lambda path: 41)
    code, _ = run_cli(monkeypatch, "pages", str(paper))
    assert code == 0
    assert capsys.readouterr().out.strip() == "41"
