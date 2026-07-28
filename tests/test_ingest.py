"""Author-edit alignment: the rules that took several rounds to get right."""
from __future__ import annotations

import json

import pytest
from conftest import make_parts, para, run, write

from docxkit.ingest import (
    apply_overrides,
    build_overrides,
    load_paragraphs,
    update_overrides,
)


def _docx(tmp_path, name, *texts, footnotes=None, pids=None):
    pids = pids or [f"{i:08X}" for i in range(1, len(texts) + 1)]
    body = "".join(para(run(t), pid=p) for t, p in zip(texts, pids,
                                                       strict=True))
    return write(tmp_path / name,
                 make_parts(body, footnotes=footnotes))


def _texts(overrides):
    from docxkit.ingest import _cat
    return [(_cat(o), _cat(n)) for o, n in overrides]


def test_no_edits_yields_no_overrides(tmp_path):
    a = _docx(tmp_path, "a.docx", "alpha", "beta")
    b = _docx(tmp_path, "b.docx", "alpha", "beta")
    assert build_overrides(a, b) == []


def test_reworded_paragraph_pairs_positionally(tmp_path):
    """A heavily reworded paragraph has a LOW similarity ratio but is still
    the same paragraph - thresholding it would split it into a bogus
    delete+insert and lose the author's text."""
    a = _docx(tmp_path, "a.docx", "keep", "The ECA average rose sharply.")
    b = _docx(tmp_path, "b.docx", "keep",
              "Measured across economies, the mean climbed.")
    ovs = _texts(build_overrides(a, b))
    assert ovs == [("The ECA average rose sharply.",
                    "Measured across economies, the mean climbed.")]


def test_deleted_paragraph_becomes_an_empty_new(tmp_path):
    a = _docx(tmp_path, "a.docx", "keep", "drop me", "tail")
    b = _docx(tmp_path, "b.docx", "keep", "tail")
    ovs = _texts(build_overrides(a, b))
    assert ("drop me", "") in ovs


def test_inserted_paragraph_attaches_to_its_anchor(tmp_path):
    """The insert has no baseline paragraph of its own, so it rides along
    with the last paired override and lands in sequence."""
    a = _docx(tmp_path, "a.docx", "intro", "conclusion")
    b = _docx(tmp_path, "b.docx", "intro edited", "brand new", "conclusion")
    ovs = build_overrides(a, b)
    joined = "".join(n for _, n in ovs)
    assert "brand new" in joined
    assert "intro edited" in joined


def test_glyph_normalisation_is_not_an_edit(tmp_path):
    """Word turns a math minus into a hyphen and straight quotes curly on
    save; that is an artifact, not the author changing anything."""
    a = _docx(tmp_path, "a.docx", "the value is −0.15 (“net”)")
    b = _docx(tmp_path, "b.docx", "the value is -0.15 (\"net\")")
    assert build_overrides(a, b) == []


def test_footnote_ids_are_remapped_by_definition_text(tmp_path):
    """Word renumbers footnote ids on save. Splicing the author's paragraph
    raw would silently repoint the footnote at another note."""
    fn = ('<w:footnotes><w:footnote w:id="{a}"><w:p><w:r><w:t>First note.'
          '</w:t></w:r></w:p></w:footnote>'
          '<w:footnote w:id="{b}"><w:p><w:r><w:t>Second note.</w:t></w:r>'
          "</w:p></w:footnote></w:footnotes>")
    base = write(tmp_path / "base.docx", make_parts(
        para(run("body ")) , footnotes=fn.format(a="6", b="7")))
    edited_body = (para(run("body edited "))
                   + '<w:p><w:r><w:footnoteReference w:id="4"/></w:r></w:p>')
    edited = write(tmp_path / "edited.docx", make_parts(
        edited_body, footnotes=fn.format(a="4", b="5")))
    ovs = build_overrides(base, edited)
    joined = "".join(n for _, n in ovs)
    # the author's id 4 ("First note.") must become the build's id 6
    assert 'w:footnoteReference w:id="6"' in joined
    assert 'w:footnoteReference w:id="4"' not in joined


def test_update_overrides_chains_instead_of_duplicating(tmp_path):
    """Round 2 starts from what round 1 produced. Appending a second entry
    would leave round 1's anchor pointing at text the build no longer
    emits, so the entry silently stops applying."""
    store = tmp_path / "overrides.json"
    base = _docx(tmp_path, "base.docx", "original text")
    r1 = _docx(tmp_path, "r1.docx", "first revision")
    _, chained, appended, total = update_overrides(base, r1, store)
    assert (chained, appended, total) == (0, 1, 1)

    # round 2: the build now emits "first revision"
    build_after_r1 = _docx(tmp_path, "b2.docx", "first revision")
    r2 = _docx(tmp_path, "r2.docx", "second revision")
    _, chained, appended, total = update_overrides(build_after_r1, r2, store)
    assert (chained, appended, total) == (1, 0, 1), "should chain, not append"
    data = json.loads(store.read_text(encoding="utf-8"))
    assert "second revision" in data[0]["new"]
    assert "original text" in data[0]["old"], "anchor must stay the base"


def test_apply_overrides_replaces_and_counts(tmp_path):
    doc = "<w:body>" + para(run("old text")) + "</w:body>"
    entry = {"old": para(run("old text")), "new": para(run("new text"))}
    out, applied, missed = apply_overrides(doc, [entry])
    assert applied == 1 and missed == []
    assert "new text" in out


def test_apply_overrides_deletes_on_empty_new():
    doc = "<w:body>" + para(run("gone")) + para(run("kept")) + "</w:body>"
    out, applied, _ = apply_overrides(doc, [{"old": para(run("gone")),
                                             "new": ""}])
    assert applied == 1
    assert "gone" not in out and "kept" in out


def test_apply_overrides_raises_when_an_anchor_moved():
    """A missed anchor means the build changed underneath the override and
    the author's edit is being dropped - that must never pass silently."""
    doc = "<w:body>" + para(run("current")) + "</w:body>"
    stale = {"old": para(run("stale anchor")), "new": para(run("x"))}
    with pytest.raises(AssertionError, match="not found"):
        apply_overrides(doc, [stale])
    out, applied, missed = apply_overrides(doc, [stale], strict=False)
    assert applied == 0 and len(missed) == 1 and out == doc


def test_load_paragraphs_handles_a_document_without_footnotes(tmp_path):
    path = _docx(tmp_path, "p.docx", "only body")
    paras, foot = load_paragraphs(path)
    assert len(paras) == 1 and foot == ""
