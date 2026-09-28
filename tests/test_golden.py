"""`tools/golden.py` — frozen manuscripts, end to end, as digests.

The real goldens need the corpus; these hold the tool itself, on a
corpus made in `tmp_path`, so they run anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import make_parts, para, run, write

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import golden  # pyright: ignore[reportMissingImports]


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "corpus"
    (root / "done").mkdir(parents=True)
    write(root / "done" / "paper.docx",
          make_parts(para(run("A finished paper."))))
    manifest = tmp_path / "golden.toml"
    manifest.write_text('[[golden]]\npath = "done/paper.docx"\ninput = ""\n'
                        "[golden.fingerprint]\n", encoding="utf-8")
    monkeypatch.setattr(golden, "MANIFEST", manifest)
    monkeypatch.setenv(golden.CORPUS_ENV, str(root))
    return root


def test_without_a_corpus_it_SKIPS_rather_than_passing(monkeypatch, capsys):
    monkeypatch.delenv(golden.CORPUS_ENV, raising=False)

    assert golden.main([]) == golden.SKIPPED
    assert "SKIPPED" in capsys.readouterr().out


def test_recorded_then_checked_is_unchanged(corpus, capsys):
    assert golden.main(["--update"]) == 0
    assert golden.main([]) == 0
    assert "1 golden(s) unchanged" in capsys.readouterr().out


def test_the_file_holds_digests_and_counts_NEVER_the_text(corpus):
    """The repository is public: a golden that quoted a manuscript would
    publish it."""
    golden.main(["--update"])

    held = golden.MANIFEST.read_text(encoding="utf-8")
    assert "finished paper" not in held
    assert "paragraphs = 1" in held and "text_final = " in held


def test_a_change_in_what_the_package_READS_names_the_field(
        corpus, monkeypatch, capsys):
    golden.main(["--update"])
    capsys.readouterr()
    real = golden.fingerprint
    monkeypatch.setattr(golden, "fingerprint",
                        lambda path: {**real(path), "tables": 99})

    assert golden.main([]) == 1
    out = capsys.readouterr().out
    assert "CHANGED done/paper.docx" in out and "tables: 0 -> 99" in out


def test_an_input_that_itself_changed_is_MOVED_not_a_regression(
        corpus, capsys):
    golden.main(["--update"])
    write(corpus / "done" / "paper.docx",
          make_parts(para(run("An edited paper."))))

    assert golden.main([]) == 1
    assert "MOVED  done/paper.docx" in capsys.readouterr().out


def test_an_input_that_is_GONE_fails(corpus, capsys):
    golden.main(["--update"])
    (corpus / "done" / "paper.docx").unlink()

    assert golden.main([]) == 1
    assert "GONE   done/paper.docx" in capsys.readouterr().out
