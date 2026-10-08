"""The corpus sweep, now that it is a gate.

`tools/sweep.py` runs every read-only routine over real manuscripts. It
was written, documented in CONTRIBUTING ("run it before a release"), and
wired to nothing — no chain, no workflow, no gate — which is the state
the curated mutations were in until 2026-08-27. It is in
`tools/gates.py` now, and this file holds the three things that wiring
depends on: that a machine with no corpus SKIPS rather than passes, that
a misconfigured root FAILS rather than sweeps the remainder, and that a
bounded sweep reads across the corpus instead of one alphabetical
corner.

The sweep of a real tree is not tested here and cannot be: the corpus is
the part that does not fit in a repository. What is tested is every
decision made before the first document is opened.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import zipfile

import pytest
from conftest import document, para, run

import docxkit

ROOT = pathlib.Path(docxkit.__file__).resolve().parents[2]


def _sweep():
    spec = importlib.util.spec_from_file_location(
        "sweep", ROOT / "tools" / "sweep.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SWEEP = _sweep()


# --- where the corpus is ------------------------------------------------


def test_roots_on_the_command_line_win(monkeypatch):
    monkeypatch.setenv(SWEEP.CORPUS_ENV, "D:/from-the-environment")

    assert SWEEP.corpus_roots(["D:/from-argv"]) == ["D:/from-argv"]


def test_roots_come_from_the_environment_when_argv_is_empty(monkeypatch):
    monkeypatch.setenv(SWEEP.CORPUS_ENV, "/srv/papers")

    assert SWEEP.corpus_roots([]) == ["/srv/papers"]


def test_several_roots_split_on_the_PLATFORM_separator(monkeypatch):
    """`os.pathsep`, not a comma: a Windows root contains a colon and a
    POSIX one contains neither, so the separator has to be the one the
    platform already uses for exactly this.

    Which is also why these three tests spell their roots WITHOUT a
    drive letter: `D:/papers` is one root on Windows and two on Linux,
    and written that way they failed on every CI run until 2026-09-03
    — behind a red step nobody read."""
    monkeypatch.setenv(SWEEP.CORPUS_ENV,
                       os.pathsep.join(["/srv/papers", "/srv/redlines"]))

    assert SWEEP.corpus_roots([]) == ["/srv/papers", "/srv/redlines"]


def test_an_EMPTY_entry_is_not_a_root(monkeypatch):
    """A trailing separator is the ordinary way to write one of these,
    and `"".split(os.pathsep)` yields `['']` — a root that resolves to
    the working directory and sweeps whatever happens to be under it."""
    monkeypatch.setenv(SWEEP.CORPUS_ENV, f"/srv/papers{os.pathsep}")

    assert SWEEP.corpus_roots([]) == ["/srv/papers"]


def test_an_UNSET_corpus_is_no_roots_at_all(monkeypatch):
    monkeypatch.delenv(SWEEP.CORPUS_ENV, raising=False)

    assert SWEEP.corpus_roots([]) == []


# --- what happens when it cannot run ------------------------------------


def test_no_corpus_SKIPS_and_says_what_to_set(monkeypatch, capsys):
    """Exit 3, not 0. A sweep of nothing and a sweep of 347 documents
    that found nothing must not print the same word: this gate's whole
    subject is the document nobody anticipated, so "green over zero
    documents" is the one reading it cannot be allowed to have."""
    monkeypatch.delenv(SWEEP.CORPUS_ENV, raising=False)
    monkeypatch.setattr("sys.argv", ["sweep.py"])

    code = SWEEP.main()

    assert code == SWEEP.SKIPPED
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert SWEEP.CORPUS_ENV in out


def test_the_skip_reason_is_on_the_FIRST_line(monkeypatch, capsys):
    """`gates.py` shows one line per gate. If the instruction is not on
    it, the chain prints a skip nobody can act on."""
    monkeypatch.delenv(SWEEP.CORPUS_ENV, raising=False)
    monkeypatch.setattr("sys.argv", ["sweep.py"])

    SWEEP.main()

    first = capsys.readouterr().out.splitlines()[0]
    assert "SKIPPED" in first
    assert SWEEP.CORPUS_ENV in first


def test_a_configured_root_that_does_not_exist_FAILS(monkeypatch, capsys,
                                                     tmp_path):
    """Not a skip, and not a sweep of the roots that do resolve.

    A typo'd or moved root is a misconfiguration, and sweeping the
    remainder reports a clean run over a fraction of the corpus — the
    same green line, over fewer documents, with nothing to say so.
    """
    real = tmp_path / "papers"
    real.mkdir()
    monkeypatch.setenv(SWEEP.CORPUS_ENV,
                       os.pathsep.join([str(real), str(tmp_path / "gone")]))
    monkeypatch.setattr("sys.argv", ["sweep.py"])

    code = SWEEP.main()

    assert code == 1
    out = capsys.readouterr().out
    assert "do not exist" in out
    assert "gone" in out


def test_a_root_with_no_documents_SKIPS(monkeypatch, capsys, tmp_path):
    """It exists, it is configured, and there is nothing in it. That is
    still zero documents swept, so it is still not a pass."""
    monkeypatch.setenv(SWEEP.CORPUS_ENV, str(tmp_path))
    monkeypatch.setattr("sys.argv", ["sweep.py"])

    code = SWEEP.main()

    assert code == SWEEP.SKIPPED
    assert "SKIPPED" in capsys.readouterr().out


# --- the bounded sweep --------------------------------------------------


def test_no_limit_keeps_every_document():
    paths = [pathlib.Path(f"{i}.docx") for i in range(10)]

    assert SWEEP.sample(paths, 0) == paths


def test_a_limit_above_the_corpus_keeps_every_document():
    paths = [pathlib.Path(f"{i}.docx") for i in range(3)]

    assert SWEEP.sample(paths, 7) == paths


def test_a_limit_takes_that_many():
    paths = [pathlib.Path(f"{i}.docx") for i in range(100)]

    assert len(SWEEP.sample(paths, 7)) == 7


def test_a_limit_STRIDES_rather_than_taking_a_prefix():
    """The whole point of the change.

    `paths[:limit]` over sorted paths is one alphabetical corner of one
    directory, so a bounded sweep reads the same documents every time
    and can never find anything it has not already found. The documents
    nobody anticipated are distributed through the corpus, not gathered
    under A.
    """
    paths = [pathlib.Path(f"{i:03}.docx") for i in range(100)]

    chosen = SWEEP.sample(paths, 5)

    assert chosen != paths[:5]
    assert chosen[0] == paths[0]
    assert chosen[-1] in paths[-25:]


def test_the_stride_never_repeats_a_document():
    """Two strides landing on one index is a sweep that claims N
    documents and reads N-1, with the count still printed as N."""
    for total in (3, 5, 7, 100, 347):
        paths = [pathlib.Path(f"{i:04}.docx") for i in range(total)]
        for limit in (3, 5, 7):
            chosen = SWEEP.sample(paths, limit)
            assert len(set(chosen)) == len(chosen), (total, limit)


def test_the_stride_stays_INSIDE_the_corpus():
    """An off-by-one in the stride indexes past the end. Checked at
    small counts because that is where a wrong operator coincides with
    the right one."""
    for total in (3, 5, 7, 8, 99):
        paths = [pathlib.Path(f"{i:04}.docx") for i in range(total)]
        for limit in (3, 5, 7):
            assert set(SWEEP.sample(paths, limit)) <= set(paths)


# --- and it really does sweep -------------------------------------------


def _docx(path: pathlib.Path, text: str) -> None:
    """The smallest package the sweep's routines will open."""
    parts = {
        "[Content_Types].xml":
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxml'
            'formats.org/package/2006/content-types"><Default '
            'Extension="xml" ContentType="application/xml"/><Override '
            'PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.'
            'document.main+xml"/></Types>',
        "word/document.xml": document(para(run(text))),
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in parts.items():
            zf.writestr(name, body)


def test_a_real_root_is_swept(monkeypatch, capsys, tmp_path):
    """The wiring end to end: two documents on disk, found, opened, and
    reported on, with an exit code the chain can read."""
    for name in ("alpha.docx", "beta.docx"):
        _docx(tmp_path / name, "a paragraph of prose")
    monkeypatch.setenv(SWEEP.CORPUS_ENV, str(tmp_path))
    monkeypatch.setattr("sys.argv", ["sweep.py"])

    code = SWEEP.main()

    assert code in (0, 1)          # swept; whether it found faults is
    out = capsys.readouterr().out  # the corpus's business, not the wiring's
    assert "alpha.docx" in out
    assert "beta.docx" in out


def test_a_skipped_name_is_not_swept(monkeypatch, capsys, tmp_path):
    """Word's lock files and the papers' own backups are not corpus."""
    _docx(tmp_path / "paper.docx", "prose")
    _docx(tmp_path / "~$paper.docx", "prose")
    _docx(tmp_path / "paper_old.docx", "prose")
    monkeypatch.setenv(SWEEP.CORPUS_ENV, str(tmp_path))
    monkeypatch.setattr("sys.argv", ["sweep.py"])

    SWEEP.main()

    out = capsys.readouterr().out
    assert "paper.docx" in out
    assert "~$paper.docx" not in out
    assert "paper_old.docx" not in out


@pytest.mark.parametrize("limit", [1, 2])
def test_the_LIMIT_env_bounds_a_sweep(monkeypatch, capsys, tmp_path, limit):
    for i in range(5):
        _docx(tmp_path / f"paper{i}.docx", "prose")
    monkeypatch.setenv(SWEEP.CORPUS_ENV, str(tmp_path))
    monkeypatch.setenv(SWEEP.LIMIT_ENV, str(limit))
    monkeypatch.setattr("sys.argv", ["sweep.py"])

    SWEEP.main()

    out = capsys.readouterr().out
    assert f"({limit} of 5 documents, strided)" in out


# --- findings: what an audit change does to the corpus ------------------


def _linked(path: pathlib.Path, *anchors: str) -> None:
    """A document whose links point at bookmarks it does not hold."""
    body = "".join(
        para(f'<w:hyperlink w:anchor="{a}">{run(a)}</w:hyperlink>',
             pid=f"{i + 1:08X}")
        for i, a in enumerate(anchors))
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", document(body))


def test_findings_are_recorded_per_audit_as_kind_and_subject(tmp_path):
    _linked(tmp_path / "p.docx", "Smith2020", "Jones2011", "Table3")
    found = SWEEP.findings_of((tmp_path / "p.docx").read_bytes())

    assert set(found) == set(SWEEP.AUDITS)
    broken = {s for k, s in found["citations"] if k == "BROKEN LINK"}
    assert broken == {"Smith2020", "Jones2011", "Table3"}
    assert found["citations"] == sorted(found["citations"])


@pytest.mark.parametrize(("subject", "expected"), [
    ("Table3", "exhibit"), ("figure2txt", "exhibit"),
    ("TableA7txt", "exhibit"),
    ("Denisova2012", "author-year key"), ("OBrien2015txt", "author-year key"),
    ("Jackson2009a", "author-year key"),
    ("Meltzer and Richard 1981", "in-text citation"),
    ("Shorrocks (1978)", "in-text citation"),
    ("WB_WDI", "other"), ("Arpino_text", "other"), ("Wikipedia", "other"),
])
def test_a_subject_has_a_shape(subject, expected):
    assert SWEEP.shape(subject) == expected


def _record(commit: str, **docs: object) -> dict[str, object]:
    return {"commit": commit, "documents": docs}


def test_a_diff_counts_what_went_and_what_came_by_document():
    """Three findings at the start; one goes, two come, one stays — and
    a document present only AFTER is counted out loud, not diffed."""
    before = _record("aaa", a={"citations": [["BROKEN LINK", "Smith2020"],
                                             ["BROKEN LINK", "Table3"]],
                               "crossrefs": [], "lint": []},
                     b={"citations": [["ORPHAN REF", "Jones2011"]],
                        "crossrefs": [], "lint": []})
    after = _record("bbb", a={"citations": [["BROKEN LINK", "Smith2020"]],
                              "crossrefs": [["UNLINKED", "Table3"]],
                              "lint": []},
                    b={"citations": [["ORPHAN REF", "Jones2011"],
                                     ["ORPHAN REF", "Jones2011"]],
                       "crossrefs": [], "lint": []},
                    c={"citations": [["ORPHAN REF", "Ng2001"]] * 7,
                       "crossrefs": [], "lint": []})

    delta = SWEEP.diff_findings(before, after)

    assert [k for _, k in delta["gone"]] == [
        ("citations", "BROKEN LINK", "Table3")]
    assert sorted(k for _, k in delta["new"]) == [
        ("citations", "ORPHAN REF", "Jones2011"),   # a DUPLICATE is new
        ("crossrefs", "UNLINKED", "Table3")]
    assert delta["changed"] == 2
    assert delta["only"] == 1


def test_a_diff_prints_the_commits_the_kinds_and_the_shapes(capsys):
    before = _record("aaa", a={"citations": [["BROKEN LINK", "Table3"]] * 3
                               + [["BROKEN LINK", "Smith2020"]] * 5,
                               "crossrefs": [], "lint": []})
    after = _record("bbb", a={"citations": [], "crossrefs": [], "lint": []})

    SWEEP.diff_findings(before, after)

    out = capsys.readouterr().out
    assert "aaa -> bbb" in out
    assert "GONE 8   NEW 0" in out
    assert "author-year key 5, exhibit 3" in out


def test_an_error_that_changes_is_reported_not_diffed(capsys):
    before = _record("a", d="ERROR KeyError: 'word/document.xml'")
    after = _record("b", d={"citations": [["BROKEN LINK", "X2020"]] * 5,
                            "crossrefs": [], "lint": []})

    delta = SWEEP.diff_findings(before, after)

    assert delta["new"] == [] and len(delta["errors"]) == 1
    assert "ERROR CHANGED d" in capsys.readouterr().out


@pytest.mark.parametrize("jobs", [1, 3])
def test_findings_end_to_end_record_then_diff(monkeypatch, capsys, tmp_path,
                                              jobs):
    """Record, change the corpus, record again with --diff: the delta is
    the change. `jobs=3` runs the worker processes, which must be able
    to import the job by name — so this module IS `sweep` for the test.

    A broken link is two findings, one per audit: citations' BROKEN LINK
    and crossrefs' DANGLING. Each is the right answer for its own audit.
    """
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    monkeypatch.setitem(sys.modules, "sweep", SWEEP)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i, anchors in enumerate([("A2001",), ("B2002", "C2003"),
                                 ("D2004", "E2005", "F2006")]):
        _linked(corpus / f"p{i}.docx", *anchors)
    before, after = tmp_path / "before.json", tmp_path / "after.json"

    monkeypatch.setattr("sys.argv", ["sweep.py", str(corpus), "--findings",
                                     str(before), "--jobs", str(jobs)])
    assert SWEEP.main() == 0
    record = SWEEP._load(before)
    assert len(record["documents"]) == 3 and record["commit"]

    _linked(corpus / "p1.docx", "B2002")
    monkeypatch.setattr("sys.argv", ["sweep.py", str(corpus), "--findings",
                                     str(after), "--diff", str(before),
                                     "--jobs", str(jobs)])
    capsys.readouterr()
    assert SWEEP.main() == 0
    out = capsys.readouterr().out
    assert "3 documents compared, 1 changed" in out
    assert "GONE 2   NEW 0" in out
    assert "citations BROKEN LINK" in out and "crossrefs DANGLING" in out
    assert "'C2003'" in out

    monkeypatch.setattr("sys.argv", ["sweep.py", "--diff", str(before),
                                     str(after)])
    assert SWEEP.main() == 0
    assert "GONE 2   NEW 0" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [
    ["--diff", "before.json"],                       # nothing to compare
    ["--diff", "a.json", "b.json", "c.json"],
    ["--diff", "a.json", "b.json", "--findings", "c.json"],
])
def test_a_diff_that_cannot_mean_anything_is_refused(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["sweep.py", *argv])
    with pytest.raises(SystemExit) as exc:
        SWEEP.main()
    assert exc.value.code == 2
