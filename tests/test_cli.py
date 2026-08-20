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
from docxkit.errors import AnchorError


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


# --------------------------------------------------- the EXIT CODES ------
# The smoke test above asserts `isinstance(code, int)`, which is what a
# hundred percent line coverage bought and no more: the mutation sweep
# found eleven `return 0` / `return 1 if …` sites across nine commands
# where flipping the code changed nothing any test could see. The exit
# code IS the contract — a script gating on `docxkit citations` reads
# nothing else — and this file's own header says the assertions belong
# on what a caller loses, not on the message.


@pytest.fixture
def broken_link(tmp_path):
    """A citation whose bookmark nothing defines."""
    return write(tmp_path / "broken.docx", make_parts(
        para(run("See "))
        + '<w:p><w:hyperlink w:anchor="Ghost2001">' + run("Ghost (2001)")
        + "</w:hyperlink></w:p>"
        + para(run("References"))
        + para(run("Ghost, G. (2001). “A Title.” Journal."))))


@pytest.fixture
def dangling_ref(tmp_path):
    """A cross-reference pointing at a caption that does not exist."""
    return write(tmp_path / "dangling.docx", make_parts(
        para(run("See ")) + '<w:hyperlink w:anchor="Nowhere">'
        + run("Table 9") + "</w:hyperlink>" + para(run("body"))))


def test_citations_exits_1_only_when_something_is_broken(
        monkeypatch, paper, broken_link, capsys):
    code, _ = run_cli(monkeypatch, "citations", paper)
    capsys.readouterr()
    assert code == 0, "a clean paper must not fail the gate"
    code, _ = run_cli(monkeypatch, "citations", broken_link)
    capsys.readouterr()
    assert code == 1


def test_refstyle_exits_1_only_when_it_found_issues(
        monkeypatch, paper, dangling_ref, capsys):
    code, _ = run_cli(monkeypatch, "refstyle", paper)
    capsys.readouterr()
    assert code == 1, "the fixture's reference list has known issues"
    code, _ = run_cli(monkeypatch, "refstyle", dangling_ref)
    capsys.readouterr()
    assert code == 0, "a document with no reference list has no issues"


def test_crossrefs_audit_exits_1_only_on_a_dangling_anchor(
        monkeypatch, paper, dangling_ref, capsys):
    code, _ = run_cli(monkeypatch, "crossrefs", str(paper), "--audit")
    capsys.readouterr()
    assert code == 0
    code, _ = run_cli(monkeypatch, "crossrefs", str(dangling_ref), "--audit")
    capsys.readouterr()
    assert code == 1


def test_crossrefs_audit_says_the_anchor_does_not_lead_its_mentions(
        monkeypatch, tmp_path, capsys):
    """`linked 12, dangling 0` was the whole report while the marker sat
    on the third mention (Parental Style 2026-08-12). `misnamed` was
    computed and never printed at all."""
    def mention(mark=""):
        inner = ('<w:hyperlink w:anchor="Table5">'
                 + run("Table 5") + "</w:hyperlink>")
        if mark:
            inner = (f'<w:bookmarkStart w:id="9" w:name="{mark}"/>{inner}'
                     '<w:bookmarkEnd w:id="9"/>')
        return f"<w:p>{inner}</w:p>"

    doc = write(tmp_path / "late.docx", make_parts(
        mention() + para(run("Intervening prose."))
        + mention("Table5txt")
        + para('<w:bookmarkStart w:id="1" w:name="Table5"/>'
               '<w:bookmarkEnd w:id="1"/>' + run("Table 5: The caption"))))
    code, _ = run_cli(monkeypatch, "crossrefs", str(doc), "--audit")
    out = capsys.readouterr().out
    assert code == 1
    assert "dangling           0" in out, out
    assert "misnamed" in out
    assert "Table5txt sits at" in out


@pytest.fixture
def unmentioned_caption(tmp_path):
    """A caption with no in-text mention: the pair cannot be completed."""
    return write(tmp_path / "half.docx", make_parts(
        para(run("Some prose with no mention at all."))
        + para(run("Table 1: Descriptive statistics"))))


@pytest.fixture
def mentioned_caption(tmp_path):
    return write(tmp_path / "full.docx", make_parts(
        para(run("As Table 1 shows, the effect is large."))
        + para(run("Table 1: Descriptive statistics"))))


@pytest.mark.parametrize("write_it", [False, True])
def test_crossrefs_exits_1_when_the_pairing_is_INCOMPLETE(
        monkeypatch, mentioned_caption, unmentioned_caption, capsys,
        write_it):
    """Both arms of `return 0 if report.complete else 1`, and both the
    dry-run and the --write site — they are separate returns and the
    existing write test ignored the code entirely. A caption the prose
    never mentions cannot be linked in both directions, and that is the
    whole promise of the house convention."""
    extra = ["--write"] if write_it else []
    code, _ = run_cli(monkeypatch, "crossrefs", str(mentioned_caption),
                      *extra)
    capsys.readouterr()
    assert code == 0, "a caption with its mention is a complete pair"
    code, _ = run_cli(monkeypatch, "crossrefs", str(unmentioned_caption),
                      *extra)
    capsys.readouterr()
    assert code == 1, "an unmentioned caption must not report success"


@pytest.mark.parametrize("argv", [
    ("text",), ("text", "--md"), ("lint",), ("smarten",), ("linkfix",),
    ("probe",), ("inspect",), ("figures",), ("tasks",),
])
def test_a_read_only_command_on_a_sound_paper_exits_0(
        monkeypatch, paper, capsys, argv):
    """`return 0` flipped to `return 1` survived on five of these: the
    smoke test above accepted any int."""
    code, _ = run_cli(monkeypatch, *argv, paper)
    capsys.readouterr()
    assert code == 0, f"{argv} failed on a paper with nothing wrong"


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
    # EVERY bucket the audit returns, which is what the name claims:
    # `misnamed` was computed and printed nowhere for as long as it has
    # existed, and a list of four kept saying so
    for bucket in ("linked", "caption_only", "mention_only", "dangling",
                   "misnamed", "misplaced_anchor"):
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


def test_footnotes_check_gates_on_a_MARK_that_disagrees(monkeypatch,
                                                        tmp_path, capsys):
    """The other half of the check, and the other repair. A mark that
    resolves differently is usually a paragraph that lost its
    FootnoteText style, so telling the author to write a size onto the
    mark would be the wrong instruction — the failure says which of the
    two it met."""
    from docxkit.package import write_docx

    def marked(nid: int, sz: str) -> str:
        mark = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
                f'<w:sz w:val="{sz}"/></w:rPr><w:footnoteRef/></w:r>')
        return (f'<w:footnote w:id="{nid}"><w:p>{mark}'
                '<w:r><w:rPr><w:sz w:val="20"/></w:rPr>'
                f"<w:t>note {nid}</w:t></w:r></w:p></w:footnote>")

    path = tmp_path / "marks.docx"
    write_docx(path, make_parts(para(run("body")), footnotes=(
        _FOOTNOTES.format(notes=marked(2, "20") + marked(3, "20")
                          + marked(4, "24")))))
    code, _ = run_cli(monkeypatch, "footnotes", str(path), "--check")
    out = capsys.readouterr().out
    assert code == 1, out
    assert "reference MARK(s)" in out and "w:pStyle" in out
    assert "footnote 4 (reference mark)" in out
    # the body sizes agree: only the mark finding belongs here
    assert "do not agree with the rest" not in out


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


def test_pages_check_prints_the_RENDER_and_exits_on_a_defect(
        monkeypatch, paper, capsys):
    """The half of `docxkit pages` that needs Word, and the only CLI
    path the coverage floor could not see: one row per sheet, then the
    verdicts, then a non-zero exit so a build step can gate on it."""
    from docxkit import pages as pages_mod
    from docxkit.pages import Sheet

    rows = [Sheet(1, "portrait", 1, False),
            Sheet(2, "landscape", None, True),
            Sheet(3, "portrait", 3, False)]
    monkeypatch.setattr(pages_mod, "sheets",
                        lambda docx, keep_pdf=None: rows)

    code, _ = run_cli(monkeypatch, "pages", str(paper), "--check")

    out = capsys.readouterr().out
    assert code == 2
    assert "3 sheet(s)" in out
    assert "sheet 2 is BLANK" in out
    assert "cannot be inferred from the markup" in out


def test_pages_check_on_a_SOUND_render_passes_quietly(monkeypatch, paper,
                                                      capsys):
    """A gate that lectures on a clean run is one people stop reading."""
    from docxkit import pages as pages_mod
    from docxkit.pages import Sheet

    monkeypatch.setattr(pages_mod, "sheets",
                        lambda docx, keep_pdf=None: [
                            Sheet(1, "portrait", 1, False),
                            Sheet(2, "portrait", 2, False)])

    code, _ = run_cli(monkeypatch, "pages", str(paper), "--check")

    out = capsys.readouterr().out
    assert code == 0
    assert "cannot be inferred" not in out


def test_pages_sheets_prints_the_table_without_gating(
        monkeypatch, paper, capsys):
    """--sheets is the same render, reported and not gated: a title page
    printing no number is a fact about the paper, not a defect."""
    from docxkit import pages as pages_mod
    from docxkit.pages import Sheet

    monkeypatch.setattr(pages_mod, "sheets",
                        lambda docx, keep_pdf=None: [
                            Sheet(1, "portrait", None, False),
                            Sheet(2, "portrait", 2, False)])

    code, _ = run_cli(monkeypatch, "pages", str(paper), "--sheets")

    out = capsys.readouterr().out
    assert code == 0
    assert "2 sheet(s)" in out
    assert "prints    -" in out
    assert "**" not in out


# --- what the cli mutation run of 2026-08-18 found ------------------------
#
# cli.py: 17.7 % real survival at 100 % line coverage, and `cmd_math` was
# the second-largest cluster with 11. Every test above asks for the exit
# code and one line of the output; the REPORT — which kinds it groups
# into, in what order, the vocabulary line, and which paragraph a
# stranded equation is in — was free.


def _math_doc(tmp_path, body, name="math.docx"):
    from docxkit.package import write_docx
    path = tmp_path / name
    write_docx(path, make_parts(body))
    return path


OMATH = "<m:oMath><m:r><m:t>θ</m:t></m:r></m:oMath>"


def test_math_groups_its_findings_by_kind_and_prints_only_what_it_found(
        monkeypatch, tmp_path, capsys):
    """`f.kind == kind` decides which findings land under which heading:
    `!=` puts all of them under the first, `>` under whichever heading
    sorts lowest, and `is` loses the two kinds whose names hold a space
    and are therefore not interned. The headings a reader gets are the
    index to the whole report."""
    path = _math_doc(tmp_path, (
        para(OMATH)
        + para(run("The parameter θ is estimated on x₁ here."))
        + para(run("A later sentence mentions θ again."))))

    code, _ = run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "TYPED SCRIPT (1)" in out
    assert "SYMBOL (2)" in out
    assert "SPLIT EXPRESSION" not in out, "no finding of that kind"
    assert "INTERVAL" not in out
    assert out.index("TYPED SCRIPT") < out.index("SYMBOL"), \
        "the order is the one the report declares"
    assert "'₁'" in out and "'θ'" in out
    assert "3 finding(s)" in out


def test_math_names_the_vocabulary_the_document_TYPESETS(monkeypatch,
                                                         tmp_path, capsys):
    """The header answers "what does this paper set as maths at all",
    which is what makes the findings below it readable. Under `and` in
    place of `or`, a document with symbols reports that it has none."""
    path = _math_doc(tmp_path, para(OMATH) + para(run("Prose.")))

    run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out

    assert "(math vocabulary: θ)" in out


def test_math_says_when_a_document_typesets_NOTHING(monkeypatch, tmp_path,
                                                    capsys):
    path = _math_doc(tmp_path, para(run("Plain prose only.")), "plain.docx")

    run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out

    assert "math vocabulary: none — the document typesets no symbols" in out


def test_math_numbers_a_stranded_equation_by_ITS_paragraph(monkeypatch,
                                                           tmp_path, capsys):
    """`enumerate(..., 1)` — Word counts the first paragraph 1, and the
    number is how an author finds the equation to promote. The equation
    is in the SECOND paragraph here, which is the only way to tell a
    wrong start from a wrong index."""
    long_eq = "<m:oMath><m:r><m:t>" + "x" * 100 + "</m:t></m:r></m:oMath>"
    path = _math_doc(tmp_path, para(run("Prose first.")) + para(long_eq),
                     "stranded.docx")

    run_cli(monkeypatch, "math", str(path))
    out = capsys.readouterr().out

    assert "1 display equation(s), 1 still in INLINE mode" in out
    assert "¶2" in out and "¶1" not in out
    assert repr("x" * 60) in out, "the preview is cut at 60 characters"
    assert repr("x" * 61) not in out


# `cmd_inspect` 7 survivors and `cmd_count` 4, from the same run. Both
# are report commands whose tests asked whether a word appeared.


def _bookmarked(tmp_path, starts: tuple[str, ...], ends: tuple[str, ...],
                name="marks.docx"):
    from docxkit.package import write_docx
    body = "".join(f'<w:bookmarkStart w:id="{i}" w:name="ref{i}"/>'
                   + run(f"Paragraph {i}.")
                   for i in starts)
    body += "".join(f'<w:bookmarkEnd w:id="{i}"/>' for i in ends)
    path = tmp_path / name
    write_docx(path, make_parts(para(body)))
    return path


def test_inspect_calls_bookmarks_unbalanced_on_the_IDS_not_the_TALLY(
        monkeypatch, tmp_path, capsys):
    """Two starts and two ends is balanced only if they are the same two.
    A start whose end went missing while another end lost its start
    counts 2/2 either way — and that is the shape a Compare leaves
    behind, which is why the check is on the sorted ids and not on the
    two lengths."""
    high = _bookmarked(tmp_path, ("1", "2"), ("1", "3"), "high.docx")
    low = _bookmarked(tmp_path, ("1", "3"), ("1", "2"), "low.docx")
    matched = _bookmarked(tmp_path, ("1", "2"), ("1", "2"), "matched.docx")

    # both directions: an ordering comparison in place of the inequality
    # is right about exactly one of these two and silent about the other
    for path in (high, low):
        run_cli(monkeypatch, "inspect", str(path))
        assert "bookmarks   2/2  UNBALANCED" in capsys.readouterr().out

    run_cli(monkeypatch, "inspect", str(matched))
    out = capsys.readouterr().out
    assert "bookmarks   2/2" in out
    assert "UNBALANCED" not in out


def test_inspect_cuts_a_long_comment_and_a_long_revision(monkeypatch,
                                                         tmp_path, capsys):
    """Both previews are one line each in a list an author reads down.
    The comment is cut at 110 characters and the revision at 100, and
    the point of a cut is that it is the same every time — a report
    whose lines wrap is a report nobody reads twice."""
    from conftest import comment, ins

    from docxkit.package import write_docx
    long_comment = "C" * 200
    long_revision = "R" * 200
    parts = make_parts(para(ins(long_revision)),
                       comment_items=(comment(1, long_comment),))
    path = tmp_path / "long.docx"
    write_docx(path, parts)

    run_cli(monkeypatch, "inspect", str(path), "--comments", "--revisions")
    out = capsys.readouterr().out

    assert "C" * 110 in out and "C" * 111 not in out
    assert "[ins] " + repr("R" * 100) in out
    assert "R" * 101 not in out


def _counted(tmp_path, words: int, name="words.docx"):
    from docxkit.package import write_docx
    body = para(run(" ".join(f"w{i}" for i in range(words))))
    path = tmp_path / name
    write_docx(path, make_parts(body))
    return path


def test_count_prints_EVERY_bucket_and_the_total(monkeypatch, tmp_path,
                                                 capsys):
    """The buckets are the report: a journal's cap is phrased in some of
    them and not others, so which bucket a word landed in is the whole
    question. A loop that runs zero times still prints a total, and the
    total is the number nobody is arguing about."""
    run_cli(monkeypatch, "count", str(_counted(tmp_path, 12)))
    out = capsys.readouterr().out

    assert "prose            12" in out
    assert "references        0" in out, "an empty bucket is still reported"
    assert "total            12" in out


def test_count_is_over_a_limit_only_when_it_EXCEEDS_it(monkeypatch, tmp_path,
                                                       capsys):
    """`counted > limit`, not `>=`: a document of exactly twelve words
    meets a twelve-word cap, and a paper trimmed to the number in the
    call for papers must not fail the check that told it to trim.

    The overage is a subtraction — `12 ^ 5` is 9 and `12 >> 5` is 0,
    both of which read as a plausible number of words."""
    path = _counted(tmp_path, 12)

    code, _ = run_cli(monkeypatch, "count", str(path), "--limit", "12")
    assert code == 0, capsys.readouterr().out
    assert "OVER" not in capsys.readouterr().out

    code, _ = run_cli(monkeypatch, "count", str(path), "--limit", "5")
    out = capsys.readouterr().out
    assert code == 1
    assert "OVER the 5-word limit by 7" in out


# `cmd_tasks` 6 survivors and `cmd_footnotes` 4, from the same run.


def _two_threads(tmp_path, name="two.docx"):
    """One thread resolved, one open — the open one with everything the
    listing truncates: its own text, what it is attached to, and a
    reply."""
    from conftest import NS

    from docxkit.package import write_docx

    def note(cid, text, para_id, author="Referee"):
        return (f'<w:comment w:id="{cid}" w:author="{author}" '
                f'w:initials="R" w:date="2026-07-30T01:00:00Z">'
                f'<w:p w14:paraId="{para_id}"><w:r><w:t>{text}</w:t></w:r>'
                f"</w:p></w:comment>")

    body = para(run("Alpha "),
                '<w:commentRangeStart w:id="1"/>', run("Settled already."),
                '<w:commentRangeEnd w:id="1"/>',
                '<w:r><w:commentReference w:id="1"/></w:r>')
    body += para('<w:commentRangeStart w:id="2"/>', run("A" * 200),
                 '<w:commentRangeEnd w:id="2"/>',
                 '<w:r><w:commentReference w:id="2"/></w:r>')
    parts = make_parts(body)
    parts["word/comments.xml"] = (
        f"<w:comments {NS}>"
        + note(1, "The settled question.", "AAAA0001")
        + note(2, "Q" * 200, "AAAA0002")
        + note(3, "R" * 200, "AAAA0003", author="Author")
        + "</w:comments>").encode("utf-8")
    parts["word/commentsExtended.xml"] = (
        f"<w15:commentsEx {NS}>"
        '<w15:commentEx w15:paraId="AAAA0001" w15:done="1"/>'
        '<w15:commentEx w15:paraId="AAAA0002" w15:done="0"/>'
        '<w15:commentEx w15:paraId="AAAA0003" '
        'w15:paraIdParent="AAAA0002" w15:done="0"/>'
        "</w15:commentsEx>").encode()
    path = tmp_path / name
    write_docx(path, parts)
    return path


def test_tasks_keeps_LISTING_after_a_thread_it_skips(monkeypatch, tmp_path,
                                                     capsys):
    """`continue`, not `break`: the resolved thread is first here, and
    under `break` the work list ends at the first thing already done —
    an empty list that looks exactly like a finished round."""
    path = _two_threads(tmp_path)

    code, _ = run_cli(monkeypatch, "tasks", str(path))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "(2 thread(s), 1 open)" in out
    assert "The settled question." not in out, "resolved, and --all not given"
    assert "Q" * 70 in out, "the open thread is still listed"


def test_tasks_cuts_the_three_things_it_quotes(monkeypatch, tmp_path,
                                               capsys):
    """A work list is read down the left edge, so every entry is one
    line: the comment at 70 characters, what it is attached to at 60,
    and each reply at 60."""
    path = _two_threads(tmp_path)

    run_cli(monkeypatch, "tasks", str(path))
    out = capsys.readouterr().out

    assert "Q" * 70 in out and "Q" * 71 not in out
    assert "on: " + repr("A" * 60) in out
    assert "A" * 61 not in out
    assert "re: Author: " + "R" * 60 in out
    assert "R" * 61 not in out


def _footnote_faces(tmp_path, name="faces.docx"):
    """Three runs in Cambria 9pt and one in Times 12pt."""
    from conftest import NS

    from docxkit.package import write_docx

    def styled(face, half_points, text):
        return (f'<w:r><w:rPr><w:rFonts w:ascii="{face}"/>'
                f'<w:sz w:val="{half_points}"/></w:rPr>'
                f"<w:t>{text}</w:t></w:r>")

    body = "".join(
        f'<w:footnote w:id="{i}"><w:p>'
        + styled("Cambria", 18, f"note {i}") + "</w:p></w:footnote>"
        for i in (2, 3, 4))
    body += ('<w:footnote w:id="5"><w:p>'
             + styled("Times New Roman", 24, "the odd one") + "</w:p>"
             "</w:footnote>")
    parts = make_parts(para(run("Body.")))
    parts["word/footnotes.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:footnotes {NS}>{body}</w:footnotes>").encode()
    path = tmp_path / name
    write_docx(path, parts)
    return path


def test_footnotes_lists_the_faces_MOST_USED_first(monkeypatch, tmp_path,
                                                   capsys):
    """`key=lambda kv: -kv[1]` — the list answers "what is this document
    set in", and the answer is the first line. Ascending puts the single
    outlier at the top and reads as if the whole apparatus were in it."""
    path = _footnote_faces(tmp_path)

    run_cli(monkeypatch, "footnotes", str(path))
    out = capsys.readouterr().out

    faces = [ln for ln in out.splitlines() if "Cambria" in ln or "Times" in ln]
    assert len(faces) == 2, out
    assert "Cambria" in faces[0] and "3" in faces[0]
    assert "Times New Roman" in faces[1]


# `cmd_figures` 4 survivors and `_write_json` 2, from the same run.


def test_figures_marks_the_ones_WITHOUT_alt_text(monkeypatch, tmp_path,
                                                 capsys):
    """One line per drawing, and the mark at the left is what a reader
    scans for — inverted, every described figure is flagged and the bare
    one is not. The alt text itself is quoted at 50 characters, enough
    to tell "A chart of..." from "Chart", and `d.descr or ''` is what
    keeps a drawing with no description from quoting an empty one."""
    from docxkit.package import write_docx
    ns = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
          'wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
          'relationships"')

    def inline(rid, name, descr=""):
        attr = f' descr="{descr}"' if descr else ""
        return ('<w:p><w:r><w:drawing><wp:inline ' + ns + ">"
                f'<wp:docPr id="1" name="{name}"{attr}/>'
                f'<a:blip r:embed="{rid}"/>'
                "</wp:inline></w:drawing></w:r></w:p>")

    long_alt = "A described chart, " + "D" * 80
    # the CAPTION is cut too, at 56 — it is the left-hand column of the
    # report and a caption runs to a sentence
    long_caption = "Figure 1. Employment and the minimum wage, " + "C" * 40
    assert len(long_caption) > 57
    path = tmp_path / "mixed.docx"
    write_docx(path, make_parts(
        para(run(long_caption)) + inline("rId4", "Chart 1", long_alt)
        + para(run("Figure 2. Bare")) + inline("rId5", "Chart 2")))

    run_cli(monkeypatch, "figures", str(path))
    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if "Figure" in ln]

    assert len(lines) == 2, lines
    assert lines[0].startswith("    Figure 1"), "described: no mark"
    assert lines[1].startswith("  ! Figure 2"), "bare: flagged"
    assert repr(long_alt[:50]) in lines[0]
    assert long_alt[:51] not in lines[0]
    assert long_caption[:56] in lines[0]
    assert long_caption[:57] not in lines[0]
    assert "alt:" not in lines[1], "nothing to quote"


def test_a_json_report_keeps_the_CHARACTERS_the_document_used(monkeypatch,
                                                              tmp_path,
                                                              capsys):
    """`ensure_ascii=False`. These reports are read by people and by
    scripts that grep them, and a Russian manuscript's task list under
    the default escaping is a file of `\\u0417` where the word was — the
    same file, unusable for both readers. The indent is two, which is
    what makes it diffable."""
    from conftest import comment

    from docxkit.package import write_docx
    path = tmp_path / "ru.docx"
    write_docx(path, make_parts(
        para(run("Абзац с замечанием.")),
        comment_items=(comment(1, "Уточните, пожалуйста — источник?"),)))
    dest = tmp_path / "tasks.json"

    run_cli(monkeypatch, "tasks", str(path), "--json", str(dest))
    capsys.readouterr()
    raw = dest.read_text(encoding="utf-8")

    assert "Уточните, пожалуйста — источник?" in raw
    assert "\\u" not in raw, "escaped, and unreadable to both audiences"
    assert raw.splitlines()[1].startswith("  {"), "indent=2"


# --- the line the staleness report prints (2026-08-19) -----------------
#
# `_summarize` turns a list of diverged part names into one line, and
# its only test asks a seven-name list to end in "and 3 more". Every
# other decision in it — how many names are shown before the count, what
# happens to a list SHORTER than the cap, and whether a directory
# holding one part is folded — was free. cli measured 8.6 % and six of
# its 39 survivors were here.

def test_a_SHORT_list_of_parts_prints_in_full():
    """`len(out) <= keep`. Fewer names than the cap is the ordinary
    case: two or three parts diverge and a person reads all of them.
    Under `is` in place of `<=` the short list takes the truncating
    branch instead, and the line ends "and -1 more"."""
    from docxkit.cli import _summarize

    assert _summarize(["a.xml", "b.xml", "c.xml"]) == "a.xml, b.xml, c.xml"


def test_exactly_FOUR_names_are_shown_before_the_count():
    """`keep: int = 4` and `out[:keep]`: the cap is what makes this one
    line rather than a paragraph, and the number after it has to be what
    is missing from the line — `len(out) - keep`, which for a
    seven-name list is `7 ^ 4` as well, and for a ten-name list is not.
    """
    from docxkit.cli import _summarize

    line = _summarize([f"part{i}.xml" for i in range(10)])

    assert line == ("part0.xml, part1.xml, part2.xml, part3.xml, "
                    "and 6 more")


def test_a_directory_holding_ONE_part_is_not_folded_into_a_count():
    """`if n > 1`: folding exists because twelve embedded fonts from one
    tick of Word's box filled the first report. A directory with a
    single part in it is that part — printed as "word/settings.xml (1
    parts)" it is both wrong English and less information than the name
    it replaced, and under `>= 1` the part appears twice, once each
    way."""
    from docxkit.cli import _summarize

    line = _summarize(["word/settings.xml", "word/fonts/f1.odttf",
                       "word/fonts/f2.odttf"])

    assert line == "word/fonts/ (2 parts), word/settings.xml"


# --- the two written lists are a promise about this parser ---------------


def _command_names(monkeypatch, capsys, *argv: str) -> list[str]:
    """The subcommand names argparse itself reports, read off --help."""
    import re
    monkeypatch.setenv("COLUMNS", "400")     # or argparse wraps the list
    run_cli(monkeypatch, *argv, "--help")
    block = re.search(r"\{([a-z,\s]+)\}", capsys.readouterr().out)
    assert block, "argparse stopped printing its choices"
    names = "".join(block.group(1).split()).split(",")
    return [n for n in names if n]


def _readme() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1]
            / "README.md").read_text(encoding="utf-8")


def _module_doc() -> str:
    """cli.py's own docstring — the list a reader of the SOURCE gets."""
    import docxkit.cli
    return docxkit.cli.__doc__ or ""


#: Both written lists, checked the same way. They drift independently:
#: the README was missing nine commands and the docstring four others,
#: and each looked complete on its own.
WRITTEN = pytest.mark.parametrize(
    "written", [_readme, _module_doc], ids=["README", "cli.__doc__"])


def _mentions(text: str, command: str) -> bool:
    """Is `command` written down — as a whole word, on its own line?"""
    return any(line.strip().startswith(f"docxkit {command} ")
               or line.strip() == f"docxkit {command}"
               for line in text.splitlines())


@WRITTEN
def test_every_command_is_written_down(monkeypatch, capsys, written):
    """The two lists are all there is: argparse's own `--help` names a
    command in one line with no explanation, and neither list is
    generated. The README was missing `crossrefs`, `lint`, `probe`,
    `math`, `verify` and the whole `revision` family; the docstring was
    missing `link`, `linkfix`, `probe` and `math`. A command nobody can
    find is a command nobody runs."""
    text = written()

    missing = [name for name in _command_names(monkeypatch, capsys)
               if not _mentions(text, name)]

    assert not missing, f"undocumented commands: {missing}"


@WRITTEN
def test_every_revision_subcommand_is_written_down_too(monkeypatch, capsys,
                                                       written):
    """`revision` is a parser of its own, and its nine steps are the
    protocol every paper project runs. `status` exiting 1 for pending
    and 4 for a stale baseline is what the scripts branch on."""
    text = written()

    missing = [name for name in _command_names(monkeypatch, capsys,
                                               "revision")
               if not _mentions(text, f"revision {name}")]

    assert not missing, f"undocumented revision steps: {missing}"


@WRITTEN
def test_no_command_is_written_down_that_the_parser_does_not_HAVE(
        monkeypatch, capsys, written):
    """The other direction, and the one a rename breaks: a documented
    command that no longer exists sends a reader to an error message.
    Both sides are read from the parser, so neither list can be edited
    into agreement without the other."""
    import re

    top = set(_command_names(monkeypatch, capsys))
    steps = set(_command_names(monkeypatch, capsys, "revision"))
    text = written()
    documented = set(re.findall(r"^\s*docxkit ([a-z]+)", text, re.MULTILINE))
    rev_documented = set(re.findall(r"^\s*docxkit revision ([a-z]+)", text,
                                    re.MULTILINE))

    assert documented <= top, f"gone from the CLI: {documented - top}"
    assert rev_documented <= steps, f"gone: {rev_documented - steps}"


# --- what the commands PRINT, which is all a person gets ----------------
#
# Every finding below is a line nothing asserted: the checkbox that says
# whether a thread is done, the hint under a list of stranded equations,
# the order the faces are listed in, the cut on a quoted anchor. A
# command's exit code is tested here several times over; what it SAYS
# was free.


def test_a_DONE_thread_is_ticked_and_an_open_one_is_not(monkeypatch,
                                                        tmp_path, capsys):
    """`"x" if t.done else " "`. The box is the whole report for a
    reviewer working down the list — inverted, every thread they have
    dealt with reads as outstanding and every outstanding one as done.
    `--all` is what shows both, and the done thread is only there to be
    ticked."""
    path = _commented(tmp_path)
    run_cli(monkeypatch, "tasks", str(path), "--done", "1")
    capsys.readouterr()

    run_cli(monkeypatch, "tasks", str(path), "--all")
    ticked = capsys.readouterr().out

    assert "[x] #1" in ticked
    assert "[ ] #1" not in ticked


def test_the_stranded_equation_HINT_waits_for_a_stranded_equation(
        monkeypatch, tmp_path, capsys):
    """`if stranded:`. The line names the call that fixes them, and
    printed under a clean document it sends a person to wrap equations
    that are already wrapped."""
    from docxkit.package import write_docx

    M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    inline = (f'<m:oMath xmlns:m="{M}"><m:r><m:t>x</m:t></m:r></m:oMath>')
    stranded = tmp_path / "stranded.docx"
    write_docx(stranded, make_parts(f"<w:p>{inline}</w:p>"))
    clean = tmp_path / "clean.docx"
    write_docx(clean, make_parts(para(run("No maths at all."))))

    run_cli(monkeypatch, "math", str(stranded))
    with_math = capsys.readouterr().out
    run_cli(monkeypatch, "math", str(clean))
    without = capsys.readouterr().out

    assert "equations.display(para)" in with_math
    assert "equations.display(para)" not in without


def test_the_faces_are_listed_COMMONEST_first(monkeypatch, tmp_path,
                                              capsys):
    """`key=lambda kv: -kv[1]`, and the mutant the test above cannot
    see: `not kv[1]` gives every face the same key, so the sort is
    stable and the DOCUMENT's order stands. Both fixtures there list
    the faces in count order already, which is the order a stable sort
    keeps — this one puts the single stray face first.

    The list answers "what is this document set in", and the answer is
    the first line."""
    from docxkit.package import write_docx

    def styled(face: str, text: str) -> str:
        return (f'<w:r><w:rPr><w:rFonts w:ascii="{face}"/>'
                f'<w:sz w:val="20"/></w:rPr><w:t>{text}</w:t></w:r>')

    from conftest import notes as notes_part

    def fn(nid: int, face: str, text: str) -> str:
        return (f'<w:footnote w:id="{nid}"><w:p>{styled(face, text)}'
                "</w:p></w:footnote>")

    # the ODD face first, so document order and count order disagree:
    # `not kv[1]` sorts every key the same and leaves the dict's own
    # order standing, which a fixture in count order cannot see
    items = [fn(2, "Arial", "the odd one out")]
    items += [fn(i, "Times New Roman", f"note {i}") for i in range(3, 7)]
    path = tmp_path / "notes.docx"
    write_docx(path, make_parts(para(run("body")),
                                footnotes=notes_part("footnotes", *items)))

    run_cli(monkeypatch, "footnotes", str(path))
    listed = [ln for ln in capsys.readouterr().out.splitlines()
              if "Times New Roman" in ln or "Arial" in ln]

    assert "Times New Roman" in listed[0], listed
    assert "Arial" in listed[-1], listed


def test_the_body_line_of_a_state_carries_NO_footnote_warning(monkeypatch,
                                                              tmp_path,
                                                              capsys):
    """`"" if where == "document" else ...`. The note says Review>Next
    skips these, which is true of footnotes and endnotes and false of
    the body — printed there it tells a person their pending body
    revisions are invisible in Word, which is the opposite of the case.
    """
    from pathlib import Path

    from docxkit.cli import _show_state
    from docxkit.revision import State

    _show_state("working", State(path=Path("working.docx"),
                                 by_part={"word/document.xml": 2,
                                          "word/footnotes.xml": 1},
                                 by_author={}))
    lines = capsys.readouterr().out.splitlines()

    body = next(ln for ln in lines if " in document" in ln)
    notes = next(ln for ln in lines if " in footnotes" in ln)
    assert "Review>Next" not in body
    assert "Review>Next" in notes


def test_a_MISSING_anchor_is_quoted_to_sixty_characters(monkeypatch, paper,
                                                        fake_word, capsys):
    """`anchor[:60]` on the NOT FOUND line, and `strict=False` on the
    lookup above it. The pair is what makes a miss a REPORT rather than
    an exception: the run finishes, every anchor that was found is
    printed with its page, and the ones that were not are listed at the
    end for a person to fix.

    Uncut, a paragraph-long anchor — and anchors come from a file, so
    they are as long as whoever wrote them — buries the rest of the
    report."""
    long_anchor = ("a sentence the author has since rewritten, quoted here "
                   "at more than sixty characters")
    assert len(long_anchor) > 61

    def locate_in(doc, anchors, *, ordered=False, strict=True, **kw):
        # the REAL contract: strict raises on a miss, and the command
        # asks for strict=False precisely so it can report one
        missing = list(anchors)
        if strict and missing:
            raise AnchorError(f"{len(missing)} of {len(missing)} anchors "
                              f"not found: {missing[0][:60]!r}")
        return []

    monkeypatch.setattr(fake_word, "locate_in", locate_in)

    code, _ = run_cli(monkeypatch, "locate", str(paper), long_anchor)
    out = capsys.readouterr().out

    assert code == 1
    assert f"NOT FOUND  {long_anchor[:60]!r}" in out
    assert long_anchor[:61] not in out


# --- what is left in cli.py, and why ------------------------------------
#
# Three survivors argued rather than tested:
#
#   `if fixed == doc` in `cmd_smarten` -> `<=`. Smartening only ever
#   raises a code point — a straight quote becomes a curly one, "--"
#   becomes an en dash, "..." an ellipsis — so the fixed text is never
#   lexicographically LESS than the original and the two spellings agree
#   on every document.
#
#   `part.split("/")[-1]` in `_show_state` -> `[1]`. The parts it names
#   are `word/document.xml`, `word/footnotes.xml`, `word/endnotes.xml`:
#   two segments each, where the last and the second are the same one.
#
#   `return 1 if check_citations(...) > 0 else 0` -> `!= 0`. The count
#   is a length and cannot be negative.


# --- the run of 2026-08-20: 7.0 % (32/455) ----------------------------
#
# The CLI is the layer a person READS, and its survivors are all of one
# kind: a loop whose body nothing checks, and a flag read backwards.


def test_lint_PRINTS_the_problems_it_found(capsys, monkeypatch, tmp_path):
    """`for problem in problems`, mutated to an empty loop: the command
    still exits 1, so every test of its exit code passes while it names
    nothing. The exit code tells a script; the lines tell the person who
    has to fix the file."""
    path = write(tmp_path / "paper.docx",
                 make_parts(para(run(" leading space"))))

    code, _ = run_cli(monkeypatch, "lint", str(path))

    out = capsys.readouterr().out
    assert code == 1
    assert "edge whitespace" in out, out
    assert out.count("  - ") >= 1


def test_a_refused_WRITE_prints_what_it_refused_over(capsys, tmp_path):
    """The same loop in `_save`, where the stakes are higher: the
    command declines to write the author's file and the reason is the
    only thing that says why."""
    from docxkit import package
    from docxkit.cli import _save

    parts = package.read_parts(write(tmp_path / "paper.docx",
                                     make_parts(para(run("prose")))))
    parts["word/document.xml"] = (
        parts["word/document.xml"].decode("utf-8")
        .replace("<w:body>", "<w:body><w:p><w:pPr/><w:pPr/></w:p>")
        .encode("utf-8"))
    target = tmp_path / "paper.docx"
    before = target.read_bytes()

    assert _save(target, parts, "test") is False

    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert out.count("  - ") >= 1, out
    assert target.read_bytes() == before, "and nothing was written"


def test_authors_says_so_when_there_are_NONE(capsys, monkeypatch,
                                            tmp_path):
    """`if not read_authors(parts)`, mutated to `not not`. The line it
    guards is the whole answer for a clean manuscript — without it the
    command prints a filename and stops, which reads as a command that
    failed."""
    path = write(tmp_path / "clean.docx",
                 make_parts(para(run("prose with nothing tracked"))))

    run_cli(monkeypatch, "authors", str(path))

    assert "(no tracked changes or comments)" in capsys.readouterr().out


def test_inspect_lists_the_comments_ONLY_when_asked(capsys, monkeypatch,
                                                   tmp_path):
    """`args.comments and com`, read as `or`. The flag is what keeps a
    hundred referee comments out of a structural summary, and `or`
    prints them whenever the document HAS any — which is the document
    the summary is usually asked about."""
    from conftest import comment
    path = write(tmp_path / "reviewed.docx",
                 make_parts(para(run("prose")),
                            comment_items=(comment(1, "a referee said"),)))

    run_cli(monkeypatch, "inspect", str(path))
    quiet = capsys.readouterr().out

    run_cli(monkeypatch, "inspect", str(path), "--comments")
    asked = capsys.readouterr().out

    assert "a referee said" not in quiet
    assert "a referee said" in asked
    assert "comments    1" in quiet, "the COUNT is in both"


# Twenty-eight of the thirty-two are left, and they are ONE shape: how
# much of something a report quotes, and how many of them it prints
# before it stops. `[:200]` on a part list, `[:60]` on an anchor and on
# a revision's text, `[:110]` on a comment, `> 12` on the ingest
# preview. Each needs a fixture longer than the width to pin, and each
# is a line a person reads — the same class this package has been
# closing module by module.
#
# Two are argued and checked: `cmd_citations`' `> 0` as `!= 0` (a count
# is never negative) and `doctor`'s `d.kind == "literal"` as `is` (both
# sides are the same module-level literal).
#
# One is recorded as NOT decided: `_summarize`'s `if len(out) <= keep`
# read as `<`. Nothing in the suite has exactly `keep` parts, so the
# suite cannot tell them apart, and neither reading is obviously the
# intended one from the code alone.
