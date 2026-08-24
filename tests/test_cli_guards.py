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

READ_ONLY_COMMANDS = [
    ("citations",), ("lint",), ("refstyle",), ("crossrefs", "--audit"),
    ("math", "--check"), ("footnotes", "--check"), ("inspect",),
    ("text",), ("probe",),
]


@pytest.fixture
def held_by_word(monkeypatch):
    """Word has the manuscript open."""
    import docxkit.package as pkg
    monkeypatch.setattr(pkg, "is_locked", lambda path: True)


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS,
                         ids=[c[0] for c in READ_ONLY_COMMANDS])
def test_a_read_only_command_runs_while_WORD_HOLDS_the_file(
        monkeypatch, capsys, command, simple_docx, held_by_word):
    verb, *flags = command

    code = _run(monkeypatch, verb, str(simple_docx), *flags)
    out = capsys.readouterr().out

    assert "Close it and retry" not in out and "locked" not in out.lower()
    assert code in (0, 1, 2), out       # it RAN; the verdict is its own
    assert "SNAPSHOT" in out, "a snapshot read has to say so"


def test_a_command_that_WRITES_still_refuses_a_locked_file(
        monkeypatch, capsys, simple_docx, held_by_word):
    """The other half, and the reason `read_only` is not the default: a
    writer that read a snapshot would compute its edit from one
    generation and save it over another."""
    _run(monkeypatch, "crossrefs", str(simple_docx), "--write")

    out = capsys.readouterr().out
    assert "SNAPSHOT" not in out, out


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
