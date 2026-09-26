"""`docxkit compare-probe` — what Word's Compare makes of an edit.

Three BACKLOG claims about Compare were settled on 2026-09-25, each by a
hand-rolled scratch build, and one of them was false (Compare DOES write
`w:tcPrChange`). The command is that scratch build. Word is the fake the
build tests use: it answers with the body it is given, which is exactly
what a probe needs to be tested against — a known redline.
"""
from __future__ import annotations

from conftest import clean_document, para, run
from test_cli import run_cli
from test_tracked_build import _FakeWordModule
from test_tracked_gates import MARK, _compare_output, _pair

from docxkit import tracked


def _probe(monkeypatch, tmp_path, original: str, clean: str, redline: str,
           *extra: str) -> tuple[int | str, list[str]]:
    monkeypatch.setattr(tracked, "_word", _FakeWordModule(redline))
    orig, cln, _ = _pair(tmp_path, original, clean)
    before = sorted(p.name for p in tmp_path.iterdir())
    code, _ = run_cli(monkeypatch, "compare-probe", str(orig), str(cln),
                      *extra)
    after = sorted(p.name for p in tmp_path.iterdir())
    return code, [n for n in after if n not in before]


def test_a_faithful_redline_passes_and_writes_NOTHING_beside_the_inputs(
        monkeypatch, tmp_path, capsys):
    code, new_files = _probe(monkeypatch, tmp_path, clean_document(),
                             clean_document(), clean_document())

    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT : both views reproduce their documents" in out
    assert new_files == []


def test_a_redline_that_does_not_ACCEPT_to_the_clean_copy_is_a_finding(
        monkeypatch, tmp_path, capsys):
    drifted = clean_document().replace("The revised sentence.",
                                       "A sentence nobody wrote.")

    code, _ = _probe(monkeypatch, tmp_path, clean_document(),
                     clean_document(), drifted)

    out = capsys.readouterr().out
    assert code == 1
    assert "UNACCEPTED" in out and "UNREJECTABLE" in out
    assert "finding(s)" in out


def test_what_the_build_REPAIRED_is_printed(monkeypatch, tmp_path, capsys):
    """The note-mark space: the probe reports the repair and, since the
    views then match, passes."""
    def doc(body: str) -> str:
        return clean_document().replace("<w:body>", "<w:body>" + body, 1)

    original = doc(para(run("(Latre 2017)"), MARK,
                        run(". Japan suspended.", preserve=True)))
    clean = doc(para(run("(Latre 2017)."), MARK,
                     run(" Japan suspended.", preserve=True)))

    code, _ = _probe(monkeypatch, tmp_path, original, clean,
                     doc(_compare_output()))

    out = capsys.readouterr().out
    assert "repaired: returned the space after a note mark" in out
    assert code == 0


def test_keep_saves_the_redline_where_it_is_told(monkeypatch, tmp_path,
                                                 capsys):
    kept = tmp_path / "kept" / "redline.docx"
    kept.parent.mkdir()

    code, _ = _probe(monkeypatch, tmp_path, clean_document(),
                     clean_document(), clean_document(), "--keep",
                     str(kept))

    assert code == 0
    assert kept.is_file()
    assert f"redline kept: {kept}" in capsys.readouterr().out
