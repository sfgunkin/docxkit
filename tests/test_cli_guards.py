"""What the CLI does with input it was not given correctly.

`test_cli.py` covers the commands doing their job. This covers the
boundary: an argument that does not parse, a file that is not a
manuscript, and the write path that every mutating command has to share.

The theme is that a mistake should come back as a sentence naming the
argument, not as a traceback — and that "did this write?" must have one
answer for every command rather than one per command.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
from conftest import comment, make_parts, para, run, write

from docxkit import cli
from docxkit.errors import DocxKitError, PackageError

SRC = Path(cli.__file__)


def args_with(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


# ------------------------------------------------------- --alias ----------


def test_an_alias_without_an_equals_is_a_sentence_not_a_traceback():
    """`dict(kv.split("=", 1) ...)` on a one-element list raises
    "dictionary update sequence element #0 has length 1; 2 is required",
    which names nothing the user typed."""
    with pytest.raises(DocxKitError, match="expected CITED=FILED"):
        cli._aliases(args_with(alias=["WHO"]))


@pytest.mark.parametrize("bad", ["=World Health Organization", "WHO=",
                                 "  =  ", "WHO=   "])
def test_an_alias_with_an_empty_side_is_refused(bad):
    """Accepted silently, it maps an acronym to nothing — which reads in
    the audit as an entry no one cites, the exact confusion --alias is
    there to remove."""
    with pytest.raises(DocxKitError, match="expected CITED=FILED"):
        cli._aliases(args_with(alias=[bad]))


def test_a_good_alias_still_parses_and_is_trimmed():
    got = cli._aliases(args_with(alias=["WHO=World Health Organization",
                                        " OECD = OECD "]))
    assert got == {"WHO": "World Health Organization", "OECD": "OECD"}


def test_an_equals_in_the_filed_name_belongs_to_the_filed_name():
    assert cli._aliases(args_with(alias=["A=B=C"])) == {"A": "B=C"}


def test_a_repeated_alias_that_agrees_is_allowed():
    assert cli._aliases(args_with(alias=["WHO=W", "WHO=W"])) == {"WHO": "W"}


def test_a_repeated_alias_that_disagrees_is_refused():
    """Last-wins is a silent winner for what is almost certainly a typo."""
    with pytest.raises(DocxKitError, match="given twice"):
        cli._aliases(args_with(alias=["WHO=W", "WHO=X"]))


def test_no_alias_at_all_is_not_an_error():
    assert cli._aliases(args_with(alias=None)) == {}
    assert cli._aliases(args_with()) == {}


# -------------------------------------------------------- --pages --------


@pytest.mark.parametrize("text,expected", [
    ("3", (3, 3)), ("1-3", (1, 3)), ("12-12", (12, 12)),
])
def test_a_page_range_that_makes_sense_parses(text, expected):
    assert cli._page_range(text) == expected


@pytest.mark.parametrize("text,why", [
    ("-3", "expected a page"),          # partition ate the leading dash
    ("x-y", "expected a page"),
    ("", "expected a page"),
    ("1-", "needs a last page"),        # silently meant "page 1" alone
    ("3-1", "ends before it begins"),
    ("0", "numbered from 1"),
    ("0-2", "numbered from 1"),
])
def test_a_page_range_that_does_not_is_refused_by_the_parser(text, why):
    """`int("")` and `int("x")` reached the user as a ValueError from
    inside cmd_pdf. As an argparse type it is "argument --pages: ..."
    and exit 2, with the offending text quoted."""
    with pytest.raises(argparse.ArgumentTypeError, match=why):
        cli._page_range(text)


def test_pdf_passes_the_parsed_range_through(monkeypatch, tmp_path):
    seen: dict[str, int | None] = {}

    def fake_export(docx, out, *, first, last):
        seen.update(first=first, last=last)
        dest = Path(out)
        dest.write_bytes(b"%PDF-1.4")
        return dest

    monkeypatch.setattr("docxkit.word.export_pdf", fake_export)
    paper = write(tmp_path / "p.docx", make_parts(para(run("x"))))
    out = tmp_path / "p.pdf"
    monkeypatch.setattr("sys.argv",
                        ["docxkit", "pdf", paper, str(out), "--pages", "2-5"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert seen == {"first": 2, "last": 5}


def test_pdf_without_pages_asks_for_the_whole_document(monkeypatch, tmp_path):
    seen: dict[str, int | None] = {}

    def fake_export(docx, out, *, first, last):
        seen.update(first=first, last=last)
        Path(out).write_bytes(b"%PDF-1.4")
        return Path(out)

    monkeypatch.setattr("docxkit.word.export_pdf", fake_export)
    paper = write(tmp_path / "p.docx", make_parts(para(run("x"))))
    monkeypatch.setattr("sys.argv",
                        ["docxkit", "pdf", paper, str(tmp_path / "p.pdf")])
    with pytest.raises(SystemExit):
        cli.main()
    assert seen == {"first": None, "last": None}


# -------------------------------------------------------- --limit --------


@pytest.mark.parametrize("text", ["0", "8000"])
def test_a_word_limit_parses(text):
    assert cli._word_limit(text) == int(text)


@pytest.mark.parametrize("text,why", [("-5", "cannot be negative"),
                                      ("many", "expected a number")])
def test_a_word_limit_that_is_not_one_is_refused(text, why):
    with pytest.raises(argparse.ArgumentTypeError, match=why):
        cli._word_limit(text)


def _wordy(tmp_path) -> str:
    body = para(run("One two three four five six seven eight nine ten."))
    return write(tmp_path / "w.docx", make_parts(body))


def _run(monkeypatch, *argv) -> int | str:
    """Exit code, or the MESSAGE a DocxKitError exits with (a str)."""
    monkeypatch.setattr("sys.argv", ["docxkit", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    code = exc.value.code
    return 0 if code is None else code


def test_a_zero_word_limit_is_a_limit(monkeypatch, tmp_path, capsys):
    """`if args.limit and ...` read 0 as "no limit given", so the
    strictest cap of all was the one silently ignored."""
    assert _run(monkeypatch, "count", _wordy(tmp_path), "--limit", "0") == 1
    assert "OVER the 0-word limit" in capsys.readouterr().out


def test_the_json_report_is_written_even_when_the_count_is_over(
        monkeypatch, tmp_path):
    """It sat after the `return 1`, so the failing run — the one whose
    numbers a caller actually wants — produced no file. That is what
    `_json_default` exists to prevent, in another form."""
    dest = tmp_path / "count.json"
    code = _run(monkeypatch, "count", _wordy(tmp_path), "--limit", "3",
                "--json", str(dest))
    assert code == 1
    assert json.loads(dest.read_text(encoding="utf-8"))


def test_a_count_under_the_limit_still_writes_its_report(monkeypatch,
                                                         tmp_path):
    dest = tmp_path / "count.json"
    assert _run(monkeypatch, "count", _wordy(tmp_path), "--limit", "9999",
                "--json", str(dest)) == 0
    assert json.loads(dest.read_text(encoding="utf-8"))


# ------------------------------------------- a file that is not a paper ---


COMMANDS = ["inspect", "text", "figures", "lint", "count", "linkfix",
            "refstyle", "tasks", "math", "smarten", "authors", "crossrefs",
            "link", "citations", "probe"]


@pytest.fixture
def not_a_zip(tmp_path):
    path = tmp_path / "junk.docx"
    path.write_bytes(b"this is not a zip file")
    return str(path)


@pytest.fixture
def zip_without_a_document(tmp_path):
    path = tmp_path / "notdoc.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("hello.txt", "no document part here")
    return str(path)


@pytest.mark.parametrize("cmd", COMMANDS)
def test_a_file_that_is_not_a_zip_is_refused_in_one_sentence(cmd, not_a_zip):
    """`inspect`, `text` and `figures` opened the zip themselves and let a
    raw `BadZipFile` traceback out, while every command that went through
    `read_parts` already said "cannot read ...". One door now."""
    with pytest.raises(PackageError, match="cannot read"):
        getattr(cli, f"cmd_{cmd}")(
            args_with(docx=not_a_zip, **_FLAGS.get(cmd, {})))


@pytest.mark.parametrize("cmd", COMMANDS)
def test_a_zip_that_is_not_a_document_is_refused_too(cmd,
                                                     zip_without_a_document):
    """The nastiest of the three: a valid zip got past `read_parts` and
    died on a KeyError naming a part the user never mentioned — and
    `lint` did something worse, reporting a document with no parts as
    "clean - no structural problems found"."""
    with pytest.raises(PackageError, match="not a Word document"):
        getattr(cli, f"cmd_{cmd}")(
            args_with(docx=zip_without_a_document, **_FLAGS.get(cmd, {})))


#: the flags each command reads off the namespace, defaulted to "do nothing"
_FLAGS: dict[str, dict[str, object]] = {
    "text": {"md": False, "tracked": "final"},
    "count": {"exclude": None, "limit": None, "tracked": "final",
              "json": None},
    "inspect": {"comments": False, "revisions": False},
    "figures": {"check": False},
    "math": {"check": False},
    "tasks": {"all": False, "check": False, "done": None, "json": None},
    "smarten": {"write": False},
    "authors": {"set": None, "only": None, "initials": None, "write": False},
    "crossrefs": {"write": False, "audit": False},
    "link": {"write": False, "alias": None},
    "refstyle": {"chicago": False, "json": None, "alias": None},
    "probe": {"anchor": []},
}


@pytest.mark.parametrize("fixture", ["not_a_zip", "zip_without_a_document"])
def test_compare_refuses_input_it_cannot_actually_diff(fixture, request):
    """The one that mattered most: `compare.load` reads only the text
    parts it recognises, so two files with none compared as two empty
    documents and reported nothing changed — and `--expect-clean`, the
    flag CI gates on, returned 0 for it."""
    path = request.getfixturevalue(fixture)
    with pytest.raises(PackageError):
        cli.cmd_compare(args_with(built=path, edited=path, json=None,
                                  expect_clean=True))


# ------------------------------------------------------ the one save path -


def _commented(tmp_path) -> str:
    body = para(run("Body text."))
    return write(tmp_path / "c.docx",
                 make_parts(body, comment_items=(comment(1, "check this"),)))


@pytest.mark.parametrize("argv,tag", [
    (("tasks", "--done", "1"), "pre_tasks"),
    (("authors", "--set", "M Lokshin", "--write"), "pre_authors"),
    (("link", "--write"), "pre_link"),
])
def test_a_mutating_command_writes_nothing_when_the_lint_refuses(
        monkeypatch, tmp_path, argv, tag):
    """One answer to "did this write?" for every command.

    `tasks --done` used to write with neither a lint nor preserve_space —
    the gap P0-5 closed for `link` and did not notice here — so markup
    Word cannot open had no offline gate on this path at all.
    """
    path = _commented(tmp_path)
    before = Path(path).read_bytes()
    monkeypatch.setattr("docxkit.lint.lint_parts",
                        lambda parts: ["a made-up structural problem"])
    cmd, *flags = argv
    assert _run(monkeypatch, cmd, path, *flags) == 1
    assert Path(path).read_bytes() == before
    assert not list(Path(tmp_path).glob(f"*{tag}*"))


@pytest.mark.parametrize("argv", [
    ("tasks", "--done", "1"),
    ("authors", "--set", "M Lokshin", "--write"),
])
def test_a_mutating_command_keeps_a_backup_when_it_does_write(
        monkeypatch, tmp_path, argv):
    path = _commented(tmp_path)
    before = Path(path).read_bytes()
    cmd, *flags = argv
    assert _run(monkeypatch, cmd, path, *flags) == 0
    kept = list(Path(tmp_path).glob("c_pre_*.docx"))
    assert len(kept) == 1
    assert kept[0].read_bytes() == before
    assert Path(path).read_bytes() != before


def test_the_save_path_protects_edge_whitespace_for_every_command(tmp_path):
    """`link` and `authors` linted but skipped preserve_space, so a
    PRE-EXISTING fragile edge space failed their lint and blocked a write
    that had nothing to do with it — which is the failure the step exists
    to prevent (found by smartening le14, whose references carried four).
    """
    from docxkit.package import read_parts

    body = para('<w:r><w:t>trailing space </w:t></w:r>')
    path = write(tmp_path / "s.docx", make_parts(body))
    parts = read_parts(path)
    assert "xml:space" not in parts["word/document.xml"].decode()

    assert cli._save(path, parts, "pre_test") is True
    after = zipfile.ZipFile(path).read("word/document.xml").decode()
    assert 'xml:space="preserve"' in after


# -------------------------------------------------- report serialisation --


def test_every_json_report_goes_through_the_resilient_encoder():
    """A source-level rule, because the trap is a future edit rather than
    today's data: `_json_default` exists so a set, a Path or a dataclass
    in a report cannot lose the whole run at the final step, and four
    commands called `json.dumps` directly and would not have been covered
    by it. A layering nobody checks is a layering that will not hold.
    """
    text = SRC.read_text(encoding="utf-8")
    body = text.split("def _write_json", 1)[1].split("\ndef ", 1)[1]
    stray = [ln.strip() for ln in body.splitlines() if "json.dumps" in ln]
    assert not stray, (
        f"{stray} — write reports through _write_json, which carries "
        f"_json_default")


def test_the_resilient_encoder_copes_with_what_a_report_may_hold(tmp_path):
    from dataclasses import dataclass

    @dataclass
    class Row:
        name: str

    dest = tmp_path / "r.json"
    cli._write_json(str(dest), {"seen": {"b", "a"}, "where": Path("x/y"),
                                "row": Row("n")})
    got = json.loads(dest.read_text(encoding="utf-8"))
    # str(Path(...)), not the literal: the separator is the platform's
    assert got == {"seen": ["a", "b"], "where": str(Path("x/y")),
                   "row": {"name": "n"}}


# ------------------------------------------------------------- inspect ---


def test_inspect_counts_the_tables_a_reader_can_index(monkeypatch, tmp_path,
                                                      capsys):
    """It counted the open tag, so a nested table was a table — and
    `tables.read_all`, which is what a caller then indexes, disagreed."""
    from docxkit import tables

    inner = ("<w:tbl><w:tr><w:tc>" + para(run("inner"))
             + "</w:tc></w:tr></w:tbl>")
    body = (para(run("x")) + "<w:tbl><w:tr><w:tc>" + inner
            + para(run("outer")) + "</w:tc></w:tr></w:tbl>")
    path = write(tmp_path / "n.docx", make_parts(body))

    assert _run(monkeypatch, "inspect", path) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines()
                if "tables" in ln)
    doc = zipfile.ZipFile(path).read("word/document.xml").decode()
    top = len(tables.read_all(doc))
    assert re.search(rf"tables\s+{top}\b", line)
    assert "+1 nested" in line

# --- a gate that only reads runs while Word holds the file ------------
#
# `revision status` and `ingest` learned this on 2026-08-21 and the fix
# stopped there, so `citations`, `refstyle`, `crossrefs`, `math --check`,
# `footnotes --check` and `lint` all still exited 1 with "close it and
# retry" (Aging_Well, 2026-08-23). The author having the manuscript open
# is not an edge case — it is the normal state during adjudication,
# which is exactly when someone wants to know whether a citation still
# resolves. A [verify] list that can only run when nobody is working on
# the paper is a list that gets run less.
#
# `is_locked` is the seam `package.readable` decides on, so locking the
# file for a test is telling it the truth about the one thing it asks.

#: How each command is invoked so that it READS the manuscript and
#: nothing else — the form that must answer from a snapshot.
#:
#: A dict keyed on the subcommand, because the point of this sweep is
#: that it covers every command the CLI defines rather than the ones
#: somebody remembered. `test_every_command_is_on_one_side_of_the_lock`
#: below derives the command list from `cli.build_parser()` and fails on
#: a command that is in neither this map nor `LOCK_EXEMPT`, so a new
#: command cannot join the CLI without an answer to "what does this do
#: while the author has the file open?".
#:
#: It was a list of 15 tuples, written by hand on 2026-08-23. The CLI
#: had 25 commands: `link` and `linkfix` were never swept and both
#: refused under a lock — the same defect this list was written for,
#: in the two commands `citations` sends its reader to next.
READ_ONLY_COMMANDS = {
    "citations": (), "lint": (), "refstyle": (), "inspect": (),
    "text": (), "probe": (), "count": (), "tasks": (), "smarten": (),
    "figures": (), "fit": (), "authors": (), "linkfix": (), "link": (),
    "sections": (),
    "crossrefs": ("--audit",), "math": ("--check",),
    "footnotes": ("--check",), "sites": ("Intro paragraph",),
}

#: Commands the sweep does not run, each with the reason. A command
#: belongs here when it cannot answer from a snapshot at all, not when
#: nobody has got round to it — that distinction is the whole value of
#: the list, and `LOCK_EXEMPT` is checked as strictly as the map above.
LOCK_EXEMPT = {
    "compare": "two paths, so it is awkward to parametrize — and it has "
               "its own test below, which is the one this fallback most "
               "needs: a comparison against the author's live file IS an "
               "author round",
    "verify": "opens the document in Word, which is the question rather "
              "than an obstacle to it — `verify` asks what Word reads "
              "back, and Word already has this file open",
    "pdf": "renders through Word; a snapshot would answer about a "
           "generation the author cannot see on their screen",
    "pages": "renders through Word, same as `pdf`",
    "repack": "REFUSES under a lock, by its own `is_locked` check before "
              "`_package`, and test_cli.py holds it to that: every number "
              "it prints is about the page layout, and a snapshot would "
              "report which sheets are empty in a generation the author "
              "cannot see, which is worse than refusing",
    "locate": "drives Word to lay the document out — the page a phrase "
              "lands on is Word's answer, not the package's",
    "api": "prints the package's own API surface and never opens a "
           "manuscript",
    "revision": "its subcommands take a PAPER rather than a docx, and "
                "the two that read one under a lock — `status` and "
                "`ingest` — are swept in test_cli_revision.py. The "
                "writers (`build`, `promote`, `baseline`) must refuse, "
                "and `promote` has its own test for that",
}


def _subcommands() -> dict[str, argparse.ArgumentParser]:
    """Every subcommand the CLI defines, from the parser itself.

    `cli.build_parser()` exists for this: `main` used to build its
    parser inline, so the only way to know what commands there are was
    to write them down again — and a written-down list is what this
    sweep exists to replace.

    Reaching into `_actions` is argparse's private surface and is
    deliberate here. The alternative is parsing `--help`, which is
    prose, and the failure this file is about is a list that quietly
    stops matching the thing it describes.
    """
    (action,) = [a for a in cli.build_parser()._actions
                 if isinstance(a, argparse._SubParsersAction)]
    return dict(action.choices)


@pytest.fixture
def held_by_word(monkeypatch, simple_docx):
    """Word has the manuscript open — the whole lock, not just the flag.

    Patching `is_locked` alone is not the truth about a held file, and
    the difference is what let `citations` pass this gate for as long as
    it was refusing in the field: a DIRECT read of the live path still
    succeeded here, so the second read that command made — of the path,
    after the snapshot had already been taken and announced — worked in
    the suite and raised on the author's machine.

    So the refusal is put where Windows puts it: opening the live path
    raises `PermissionError`, which is what every reader meets and what
    `read_parts` turns into "is locked (open in Word)". The snapshot
    copy is a `shutil.copy2`, which Word's share mode does allow, so it
    still works — that asymmetry IS the fallback.
    """
    import zipfile as zf

    import docxkit.package as pkg
    monkeypatch.setattr(pkg, "is_locked", lambda path: True)

    live, real = Path(simple_docx).resolve(), zf.ZipFile

    def held(file: Any, *args: Any, **kw: Any) -> Any:
        mode = args[0] if args else kw.get("mode", "r")
        if (mode == "r" and isinstance(file, str | Path)
                and Path(file).resolve() == live):
            raise PermissionError(
                13, "The process cannot access the file because it is being "
                    "used by another process")
        return real(file, *args, **kw)

    monkeypatch.setattr(zf, "ZipFile", held)
    # `read_parts` retries a sharing violation on a bounded schedule —
    # right for a OneDrive race, three wasted seconds per refusing
    # command here, and the retry itself is not what is under test.
    monkeypatch.setattr(pkg.time, "sleep", lambda _seconds: None)


@pytest.mark.parametrize("verb", sorted(READ_ONLY_COMMANDS))
def test_a_read_only_command_runs_while_WORD_HOLDS_the_file(
        monkeypatch, capsys, verb, simple_docx, held_by_word):
    """The banner is a PROMISE that a result follows, and this is what
    holds it.

    Both halves of that were unchecked until 2026-08-29. The refusal
    goes to STDERR — `main` exits with `sys.exit(f"docxkit: {exc}")` —
    and this read `capsys.readouterr().out`, so "Close it and retry"
    could not appear in what it looked at however loudly the command
    refused. `citations` had been refusing under a printed banner since
    the fallback landed, and this test was green on it the whole time:
    the two-line refusal has the same SHAPE as a clean run, which is the
    reason the defect was worth an S1, and the reason a negative
    assertion alone cannot be the gate.

    So the report itself is asserted. Whatever the command prints after
    the banner is its result — a finding, a count, a clean verdict — and
    a run with nothing after it did not run.
    """
    code = _run(monkeypatch, verb, str(simple_docx),
                *READ_ONLY_COMMANDS[verb])
    captured = capsys.readouterr()
    out, everything = captured.out, captured.out + captured.err

    assert "Close it and retry" not in everything, everything
    assert "locked" not in everything.lower(), everything
    assert code in (0, 1, 2), everything  # it RAN; the verdict is its own
    assert cli._SNAPSHOT_NOTE in out, "a snapshot read has to say so"
    assert out.replace(cli._SNAPSHOT_NOTE, "").strip(), \
        "the banner and NOTHING else is what 'did not run' looks like"


def test_COMPARE_diffs_a_side_the_author_has_open(
        monkeypatch, capsys, tmp_path, simple_docx, held_by_word):
    """The two paths make it awkward to parametrize and easy to forget,
    and it is the gate most worth having on the fallback: a comparison
    against the author's live file is the whole of an author round, so
    the one command that adjudicates one refused at exactly the moment
    it was wanted. `load` opened the zip itself, under the banner
    `_package` had already printed."""
    built = write(tmp_path / "built.docx",
                  make_parts(para(run("Intro paragraph about "
                                      "age-friendly work."))))

    code = _run(monkeypatch, "compare", str(built), str(simple_docx))
    captured = capsys.readouterr()

    assert "Close it and retry" not in captured.out + captured.err
    assert code in (0, 1), captured.out + captured.err
    assert cli._SNAPSHOT_NOTE in captured.out
    assert "[INSERT] Second paragraph" in captured.out, \
        "the snapshot's own content is what was diffed"


def test_the_snapshot_banner_is_not_printed_when_the_read_FAILS(
        capsys, tmp_path, held_by_word):
    """A package that is a zip and not a manuscript is refused — and the
    refusal used to arrive under the banner, which says a result
    follows. Ordering the two is the whole of the rule."""
    not_a_paper = tmp_path / "notes.docx"
    with zipfile.ZipFile(not_a_paper, "w") as z:
        z.writestr("hello.txt", "not a manuscript")

    with pytest.raises(PackageError, match="not a Word document"):
        cli._package(str(not_a_paper), read_only=True)

    assert cli._SNAPSHOT_NOTE not in capsys.readouterr().out


def test_every_command_is_on_one_side_of_the_LOCK_contract():
    """The property the two sweeps have and a hand-written list cannot.

    The lists above are checked against the parser itself, so a command
    added to the CLI fails this test until somebody answers "what does
    it do while the author has the file open?" — in the map, by being
    swept, or in `LOCK_EXEMPT`, with the reason.

    Written because the answer had been missed twice. `citations`
    refused under a lock for two months after its five siblings learned
    to fall back (S1, `95024d9`), and the list written to stop that
    happening again covered 15 of the CLI's 25 commands — `link` and
    `linkfix` were not among them, and both were still refusing on
    2026-08-31, in the two commands `citations` sends its reader to
    next.

    This is the `*.py` glob lesson from BACKLOG applied to a test
    rather than to a tool: **a gate that enumerates the thing it guards
    has to say how many it found**, or it goes quiet about the ones it
    stops seeing. The count below is the saying-so; the set comparison
    is what makes it act."""
    commands = set(_subcommands())
    placed = set(READ_ONLY_COMMANDS) | set(LOCK_EXEMPT)

    assert len(commands) >= 25, (
        f"the CLI enumerated only {len(commands)} commands — the sweep "
        f"cannot be trusted when its own list of what to sweep shrinks")
    assert commands == placed, (
        f"not swept and not exempt: {sorted(commands - placed)}; "
        f"named here but not in the CLI: {sorted(placed - commands)}")


def test_the_two_lock_lists_do_not_overlap():
    """A command in both is a command whose exemption is not true, and
    the sweep would keep passing while the reason sat there being read
    by whoever came next."""
    both = set(READ_ONLY_COMMANDS) & set(LOCK_EXEMPT)
    assert not both, both


#: The WRITING form of every command that has one. The other side of
#: the contract: these must refuse, because a writer that read a
#: snapshot would compute its edit from one generation and save it over
#: another.
WRITING_COMMANDS = {
    "link": ("--write",),
    "crossrefs": ("--write",),
    "smarten": ("--write",),
    "refstyle": ("--fix",),
    "tasks": ("--done", "1"),
    "authors": ("--set", "Michael Lokshin", "--write"),
}


def test_every_WRITE_flag_the_CLI_has_is_swept():
    """The same completeness rule as the read side, from the parser's
    own option strings — so a `--write` added to a seventh command
    cannot arrive without an answer about the lock."""
    have = {verb for verb, parser in _subcommands().items()
            if {"--write", "--fix", "--done", "--set"}
            & {o for a in parser._actions for o in a.option_strings}}

    assert have == set(WRITING_COMMANDS), (
        f"a write form nothing sweeps: {sorted(have - set(WRITING_COMMANDS))}")


@pytest.mark.parametrize("verb", sorted(WRITING_COMMANDS))
def test_a_command_that_WRITES_still_refuses_a_locked_file(
        monkeypatch, capsys, verb, simple_docx, held_by_word):
    """The other half of the contract, and the reason `read_only` is not
    the default.

    Asserted on the FILE and not only on the message, which is the rule
    `cli.py`'s tests already follow: a message is not what an author
    loses. One command stood for all six here until 2026-08-31, and it
    checked the banner alone.
    """
    before = Path(simple_docx).read_bytes()

    outcome = _run(monkeypatch, verb, str(simple_docx),
                   *WRITING_COMMANDS[verb])
    captured = capsys.readouterr()

    assert "SNAPSHOT" not in captured.out, captured.out
    assert Path(simple_docx).read_bytes() == before, "it wrote anyway"
    # `main` refuses a DocxKitError with `sys.exit(f"docxkit: {exc}")`,
    # so the message IS the exit status — a str, which the interpreter
    # prints and pytest hands back here. Asserting on captured output
    # instead finds nothing and says the command was silent.
    assert isinstance(outcome, str), f"exited {outcome!r}, not a refusal"
    assert "locked" in outcome.lower(), outcome


# --- where an in-place write keeps the file it is about to replace ----
#
# `docxkit smarten revision/working.docx --write` left
# `working_pre_smarten1.docx` in `revision/` (Aging_Well, 2026-08-29).
# That folder is governed by the protocol's first rule — ONE file — and
# a second .docx in it is one keystroke from being the one the author
# opens next. It was moved to `build/rescue/` by hand, which is a
# workaround and not a resolution.


@pytest.fixture
def protocol_paper(tmp_path):
    """A paper on the single-file protocol, scaffolded as `init` does."""
    from docxkit import revision
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "manuscript.docx",
                make_parts(para(run("The author's own text isn't smart."))))
    return revision.init(tmp_path / "proj", src, name="Test Paper")


def test_an_in_place_write_keeps_the_old_generation_OUT_of_the_folder(
        monkeypatch, capsys, protocol_paper):
    paper = protocol_paper

    code = _run(monkeypatch, "smarten", str(paper.working), "--write")

    assert code == 0, capsys.readouterr().out
    beside = [p.name for p in paper.working.parent.glob("*.docx")]
    assert beside == [paper.working.name], \
        f"the author's folder must hold ONE .docx, and holds {beside}"
    kept = list(paper.rescue_dir.glob("*_pre_smarten*.docx"))
    assert len(kept) == 1, f"prior generations go to {paper.rescue_dir}"
    assert "rescue" in capsys.readouterr().out, \
        "and the line says where, or a bare name reads as 'beside your file'"


def test_a_docx_that_is_NOT_the_paper_keeps_its_backup_beside_it(
        monkeypatch, capsys, protocol_paper):
    """The narrowing that makes the rule safe: a build artifact or an
    export under the same project is not the manuscript `paper.toml`
    names, and its backup belongs where it is."""
    other = write(protocol_paper.build_dir / "batch.docx",
                  make_parts(para(run("A batch isn't smart either."))))

    code = _run(monkeypatch, "smarten", str(other), "--write")

    assert code == 0, capsys.readouterr().out
    assert (Path(other).parent / "batch_pre_smarten1.docx").is_file()


def test_a_paper_NOT_on_the_protocol_keeps_its_backup_beside_it(
        monkeypatch, capsys, tmp_path):
    """No `paper.toml` anywhere above it: beside the manuscript is the
    right answer and stays the default."""
    loose = write(tmp_path / "loose.docx",
                  make_parts(para(run("There isn't a protocol here."))))

    code = _run(monkeypatch, "smarten", str(loose), "--write")

    assert code == 0, capsys.readouterr().out
    assert (tmp_path / "loose_pre_smarten1.docx").is_file()


def test_a_gate_timeout_that_is_not_a_NUMBER_names_the_argument():
    """`--gate-timeout abc` is a typo, and a typo should come back as a
    sentence rather than a ValueError traceback out of float()."""
    with pytest.raises(argparse.ArgumentTypeError) as exc:
        cli._seconds("abc")

    assert "expected a number of seconds" in str(exc.value)
    assert "abc" in str(exc.value)


@pytest.mark.parametrize("text", ["0", "-1", "-0.5"])
def test_a_gate_timeout_of_ZERO_or_LESS_is_refused_with_the_reason(text):
    """0 reads as "no timeout" to everyone who has met a timeout
    setting, and here it is the one thing the bound exists to prevent:
    a gate that cannot be bounded can stop a hand-back. The refusal says
    so, because a bare "must be positive" invites the reader to think the
    tool is being fussy."""
    with pytest.raises(argparse.ArgumentTypeError) as exc:
        cli._seconds(text)

    said = str(exc.value)
    assert "must be positive" in said
    assert "no timeout" in said, said


def test_a_gate_timeout_that_IS_a_number_comes_back_as_one():
    """argparse calls this for its `type=`, so the return value is what
    the command actually runs with — a string here would be compared
    against elapsed seconds and raise at the worst moment."""
    assert cli._seconds("90") == 90.0
    assert isinstance(cli._seconds("0.5"), float)


# --- the whole sweep of 2026-09-15 ------------------------------------


def test_MINUS_ONE_is_a_negative_word_limit_too():
    """`if n < 0`. The refusal above is tested at -5, where `n < -1`
    refuses as well; -1 is the one negative number that reading lets
    through, as a cap of minus one word."""
    with pytest.raises(argparse.ArgumentTypeError, match="cannot be negative"):
        cli._word_limit("-1")


def test_an_IGNORE_word_the_defaults_already_hold_STAYS_ignored():
    """`IGNORED_LEADS | extra`. A paper that names a word the engine
    already ignores — two scripts sharing one list, or a list copied from
    the defaults — is only repeating itself, and read as `^` the repeat
    CANCELS: the word is ignored no longer, and the grammar reads it as
    an author again."""
    from docxkit.citations import IGNORED_LEADS

    word = min(IGNORED_LEADS)

    got = cli._ignore(args_with(ignore=f"{word},Surveys"))

    assert got == IGNORED_LEADS | {"Surveys"}


def test_a_CROSSREFS_dry_run_answers_from_a_snapshot_too(
        monkeypatch, capsys, simple_docx, held_by_word):
    """`read_only=audit or not write`. The sweep above runs `crossrefs`
    with `--audit`, which is read-only under both spellings of that line;
    the DRY run is the form that tells `or` from `and`, and it writes
    nothing either, so it has no business refusing."""
    code = _run(monkeypatch, "crossrefs", str(simple_docx))

    captured = capsys.readouterr()
    assert isinstance(code, int), code
    assert cli._SNAPSHOT_NOTE in captured.out
    assert "dry run" in captured.out


def test_AUTHORS_called_without_a_write_flag_reads_a_snapshot(
        capsys, simple_docx, held_by_word):
    """`read_only=not getattr(args, "write", False)`: a caller that does
    not mention writing is asking for the report, and the report reads a
    snapshot while Word holds the file. With `True` as the default the
    same call refuses — a script reading the credits list through
    `cmd_authors` would stop working whenever the author had the paper
    open."""
    code = cli.cmd_authors(args_with(docx=str(simple_docx), set=None))

    out = capsys.readouterr().out
    assert code == 0, out
    assert cli._SNAPSHOT_NOTE in out
    assert "(no tracked changes or comments)" in out


def test_a_WRITE_reads_the_live_file_and_announces_NO_snapshot(
        monkeypatch, capsys, tmp_path):
    """`copied = False` before the branch. A writing command reads the
    live file and never binds `copied` itself, so the initial value IS
    its answer — and `True` there prints the snapshot banner over every
    successful write, telling the author the edit was computed from a
    copy of a file Word was holding."""
    loose = write(tmp_path / "loose.docx",
                  make_parts(para(run("A straight quote isn't smart."))))

    code = _run(monkeypatch, "smarten", str(loose), "--write")

    out = capsys.readouterr().out
    assert code == 0, out
    assert "written; previous version kept at" in out
    assert cli._SNAPSHOT_NOTE not in out


def test_a_docx_that_SORTS_before_the_paper_keeps_its_backup_beside_it(
        monkeypatch, capsys, protocol_paper):
    """`paper.working.resolve() == target`. The build artefact above sits
    in `revision/build/`, which sorts AFTER `manuscript.docx`, so `>=` in
    place of the equality answers it the same way; a draft beside the
    manuscript whose name sorts first is sent to `build/rescue/` by it,
    as though it were the paper."""
    draft = write(protocol_paper.root / "a_draft.docx",
                  make_parts(para(run("A draft isn't smart either."))))

    code = _run(monkeypatch, "smarten", str(draft), "--write")

    assert code == 0, capsys.readouterr().out
    assert (protocol_paper.root / "a_draft_pre_smarten1.docx").is_file()
    assert not list(protocol_paper.rescue_dir.glob("a_draft*"))
