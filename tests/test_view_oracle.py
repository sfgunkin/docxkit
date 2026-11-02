"""`tools/view_oracle.py` — the accept/reject views' old-vs-new oracle.

It exists because a hand-rolled probe measured nothing: `_simulate_clean`
is cached on the XML, so a monkeypatched re-run was served the unpatched
view (2026-10-31). What is pinned here: the profile Word is compared on
counts what it claims, the diff and the verdict are key by key, and the
end-to-end run compares a real base against the working tree in their
own interpreters.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from conftest import document, para, run

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import view_oracle as vo  # noqa: E402  # pyright: ignore[reportMissingImports]


def _mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def _math(*inner: str) -> str:
    return (f'<w:p xmlns:m="http://schemas.openxmlformats.org/officeDocument'
            f'/2006/math"><m:oMath>{"".join(inner)}</m:oMath></w:p>')


def test_profile_counts_objects_SHELLS_glyphs_and_bookmarks():
    """Three fractions, one of them empty; five delimiters, two empty."""
    full_f = f"<m:f><m:num>{_mr('a')}</m:num><m:den>{_mr('b')}</m:den></m:f>"
    empty_f = "<m:f><m:num/><m:den/></m:f>"
    full_d = f"<m:d><m:e>{_mr('x')}</m:e></m:d>"
    empty_d = "<m:d><m:e><m:r><m:t/></m:r></m:e></m:d>"
    xml = document(
        '<w:bookmarkStart w:id="1" w:name="eq1"/>'
        + _math(full_f, full_f, empty_f) + '<w:bookmarkEnd w:id="1"/>'
        + _math(full_d, full_d, full_d, empty_d, empty_d)
        + para(run("Prose.")))

    got = vo.profile_xml(xml)

    assert got["objects"] == {"d": 5, "f": 3}
    assert got["shells"] == {"d": 2, "f": 1, "r": 2}   # runs: shells only
    assert got["count"] == 2
    assert got["equations"] == "ababxxx"
    assert got["bookmarks"] == ["eq1"]


def test_profile_COUNTS_comments_by_id_not_by_marker():
    """Word renumbers comments, so they are counted: three comments, one
    with a range and a reference, one reference only, one range only."""
    xml = document(para(
        '<w:commentRangeStart w:id="4"/>', run("a"),
        '<w:commentRangeEnd w:id="4"/>',
        '<w:r><w:commentReference w:id="4"/></w:r>',
        '<w:r><w:commentReference w:id="9"/></w:r>',
        '<w:commentRangeStart w:id="11"/>', run("b"),
        '<w:commentRangeEnd w:id="11"/>'))

    assert vo.profile_xml(xml)["comments"] == 3
    assert vo.profile_xml(document(para(run("none"))))["comments"] == 0


def test_profile_text_sees_a_MERGED_paragraph():
    """Same characters, one paragraph instead of two: a different text."""
    two = vo.profile_xml(document(para(run("One.")) + para(run("Two."))))
    one = vo.profile_xml(document(para(run("One."), run("Two."))))

    assert two["text"] != one["text"]
    assert two["text"] == vo.profile_xml(
        document(para(run("One.")) + para(run("Two."))))["text"]


def test_word_is_asked_about_MOVED_body_views_and_counts_the_rest():
    moved = [("a.docx", "word/document.xml|reject"),
             ("a.docx", "word/footnotes.xml|reject"),
             ("b.docx", "word/header1.xml|accept"),
             ("c.docx", "word/document.xml|accept"),
             ("c.docx", "word/document.xml|reject")]
    head = {f: {"word/document.xml|accept": ["x", {}]}
            for f in ("a.docx", "b.docx", "c.docx", "d.docx")}

    asked, unasked = vo.to_ask(moved, head, "moved")

    assert asked == {"a.docx": ["reject"], "c.docx": ["accept", "reject"]}
    assert unasked == 2
    assert sorted(vo.to_ask(moved, head, "all")[0]) == [
        "a.docx", "b.docx", "c.docx", "d.docx"]


def test_diff_is_view_by_view_and_sees_a_view_on_one_side_only():
    base = {"a.docx": {"p|accept": ["1", None], "p|reject": ["2", None]}}
    head = {"a.docx": {"p|accept": ["1", None], "p|reject": ["3", None],
                       "q|accept": ["4", None]}}

    assert vo.diff(base, head) == [("a.docx", "p|reject"),
                                   ("a.docx", "q|accept")]


def test_judge_names_the_side_word_agrees_with_per_field():
    word = {"objects": {"f": 3}, "shells": {"d": 5}, "text": "t"}
    base = {"objects": {"f": 7}, "shells": {"d": 5}, "text": "u"}
    head = {"objects": {"f": 3}, "shells": {}, "text": "v"}

    assert vo.judge(base, head, word) == {
        "objects": "head", "shells": "base", "text": "neither"}
    assert vo.judge(word, word, word) == dict.fromkeys(word, "both")


def test_no_corpus_is_SKIPPED(monkeypatch):
    monkeypatch.delenv("DOCXKIT_CORPUS", raising=False)

    assert vo.main([]) == vo.SKIPPED


def test_a_missing_root_FAILS_rather_than_measuring_the_rest(tmp_path,
                                                             capsys):
    _corpus(tmp_path)

    code = vo.main([str(tmp_path / "corpus"), str(tmp_path / "offline")])

    assert code == 1
    assert "do not exist" in capsys.readouterr().out


def test_no_view_measured_is_SKIPPED_not_nothing_changed(tmp_path, capsys):
    """A filter that matches no part measures nothing — exit 3, even
    under --expect-same, never the 0 of a clean measurement."""
    corpus = _corpus(tmp_path)

    code = vo.main([str(corpus), "--contains", "NO SUCH TEXT",
                    "--expect-same"])

    assert code == vo.SKIPPED, capsys.readouterr().out


def test_each_side_runs_ITS_OWN_engine(tmp_path, capsys):
    """A base tree whose engine answers a marker: every view differs.
    A side that silently ran the working tree would report none."""
    corpus = _corpus(tmp_path)
    stub = tmp_path / "stub" / "docxkit"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text("", encoding="utf-8")
    (stub / "revisions.py").write_text(
        "BASE = ('<w:document xmlns:w=\"http://schemas.openxmlformats.org/"
        "wordprocessingml/2006/main\"><w:body/></w:document>')\n\n"
        "def accept(xml):\n    return BASE\n\n"
        "def reject(xml):\n    return BASE\n", encoding="utf-8")

    code = vo.main([str(corpus), "--base-src", str(stub.parent),
                    "--expect-same"])

    out = capsys.readouterr().out
    assert code == 1, out
    assert "accept: 2 views differ" in out
    assert "reject: 2 views differ" in out


def _corpus(tmp_path: Path) -> Path:
    """Three redlines, one an exact copy, and a document with no
    revision at all."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name, body in (
            ("a.docx", para('<w:ins w:id="1" w:author="A">'
                            + run("new") + "</w:ins>" + run(" old"))),
            ("b.docx", para('<w:del w:id="2" w:author="B">'
                            '<w:r><w:delText>gone</w:delText></w:r></w:del>'
                            + run(" kept"))),
            ("c.docx", para(run("no revision")))):
        with zipfile.ZipFile(corpus / name, "w") as z:
            z.writestr("word/document.xml", document(body))
    (corpus / "copy.docx").write_bytes((corpus / "a.docx").read_bytes())
    return corpus


def test_end_to_end_counts_redlines_views_and_copies_once(tmp_path, capsys):
    """Two interpreters over the working tree's own `src`: the copy is
    counted once, the clean document has no view, and nothing differs.
    (Isolation is the stub test's; this one pins the bookkeeping, and
    does not move with an uncommitted change to the engine.)"""
    corpus = _corpus(tmp_path)

    code = vo.main([str(corpus), "--base-src", str(vo.ROOT / "src"),
                    "--expect-same"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "2 redlines of 3 distinct documents, 4 views" in out
    assert "reject: 0 views differ" in out


def test_the_base_is_git_archived_by_default(tmp_path, capsys):
    """No --base-src: HEAD's tree, extracted. Only that it measures."""
    code = vo.main([str(_corpus(tmp_path)), "--base", "HEAD"])

    assert code == 0
    assert "4 views; base HEAD" in capsys.readouterr().out
