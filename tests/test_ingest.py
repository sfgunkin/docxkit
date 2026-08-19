"""Author-edit alignment: the rules that took several rounds to get right."""
from __future__ import annotations

import json

import pytest
from conftest import make_parts, note, notes, para, run, write

from docxkit.errors import AnchorError
from docxkit.ingest import (
    _cat,
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
    with pytest.raises(AnchorError, match="not found"):
        apply_overrides(doc, [stale])
    out, applied, missed = apply_overrides(doc, [stale], strict=False)
    assert applied == 0 and len(missed) == 1 and out == doc


def test_load_paragraphs_handles_a_document_without_footnotes(tmp_path):
    path = _docx(tmp_path, "p.docx", "only body")
    paras, foot = load_paragraphs(path)
    assert len(paras) == 1 and foot == ""


# -- what the first mutation run found unasserted (2026-08-17, 35.1 %) ----
#
# The worst module measured: 65 real survivors, 50 of them in
# `build_overrides` and 33 on the single line that placed a pure insert.
# That line was placing it WRONG, and the case above it refused the edit
# outright — neither had a test, so both had been shipping.

def _order(base_texts, overrides, pids=None):
    """The paragraph order applying these overrides to the build gives."""
    import re

    pids = pids or [f"{i:08X}" for i in range(1, len(base_texts) + 1)]
    body = "".join(para(run(t), pid=q)
                   for t, q in zip(base_texts, pids, strict=True))
    out, _applied, _missed = apply_overrides(
        body, [{"old": o, "new": n} for o, n in overrides], strict=False)
    return re.findall(r"<w:t[^>]*>([^<]*)</w:t>", out)


def test_a_paragraph_added_with_NO_other_edit_is_integrated(tmp_path):
    """This raised `leading insert with no anchor paragraph` — for an
    insert in the MIDDLE of the document, because the branch that placed
    inserts keyed on "is there an earlier override" rather than "what
    paragraph does this follow". An author adding a paragraph and
    changing nothing else is the most ordinary round there is.
    """
    a = _docx(tmp_path, "a.docx", "intro", "middle", "conclusion")
    b = _docx(tmp_path, "b.docx", "intro", "middle", "brand new",
              "conclusion")

    ovs = build_overrides(a, b)

    assert _order(["intro", "middle", "conclusion"], ovs) == [
        "intro", "middle", "brand new", "conclusion"]


def test_an_added_paragraph_lands_where_the_AUTHOR_put_it(tmp_path):
    """The insert is anchored on the paragraph BEFORE it, not on the
    last paragraph that happened to change. Fixing a typo in the
    introduction and adding a paragraph in section 5 used to put the new
    paragraph in the introduction — the author's text, integrated, in
    the wrong place, with nothing raised."""
    a = _docx(tmp_path, "a.docx", "intro", "middle", "conclusion")
    b = _docx(tmp_path, "b.docx", "intro edited", "middle", "brand new",
              "conclusion")

    ovs = build_overrides(a, b)

    assert _order(["intro", "middle", "conclusion"], ovs) == [
        "intro edited", "middle", "brand new", "conclusion"]


def test_a_paragraph_added_at_the_END_is_integrated(tmp_path):
    a = _docx(tmp_path, "a.docx", "intro", "conclusion")
    b = _docx(tmp_path, "b.docx", "intro", "conclusion", "a coda")

    ovs = build_overrides(a, b)

    assert _order(["intro", "conclusion"], ovs) == [
        "intro", "conclusion", "a coda"]


def test_an_insert_after_a_DELETED_paragraph_does_not_collide(tmp_path):
    """Anchoring on the paragraph before means the anchor is sometimes
    one this round already rewrites — and two overrides sharing an `old`
    is a guaranteed miss, because the first consumes it and the second
    raises `anchor not found`."""
    a = _docx(tmp_path, "a.docx", "intro", "drop me", "conclusion")
    b = _docx(tmp_path, "b.docx", "intro", "brand new", "conclusion")

    ovs = build_overrides(a, b)

    assert [o for o, _ in ovs] == list(dict.fromkeys(o for o, _ in ovs))
    assert _order(["intro", "drop me", "conclusion"], ovs) == [
        "intro", "brand new", "conclusion"]


def test_an_insert_after_a_REPEATED_LINE_lands_on_the_right_copy(tmp_path):
    """The anchor is a PARAGRAPH, not its text, and a manuscript repeats
    text — a bare "Notes:" line under every table. Word gives each
    paragraph its own `w14:paraId`, so the two copies are different
    anchors and the insert lands under the table the author was reading.
    """
    notes = "Notes: standard errors in parentheses."
    base = ["Table 1", notes, "Table 2", notes]
    a = _docx(tmp_path, "a.docx", *base)
    b = _docx(tmp_path, "b.docx", *base, "a closing remark")

    ovs = build_overrides(a, b)

    assert _order(base, ovs) == [*base, "a closing remark"]


def test_an_insert_at_the_VERY_START_has_nothing_to_anchor_on(tmp_path):
    """It really is a leading insert here, and the message says which
    paragraph — the override list is anchored on the build's own
    paragraphs, and there is none before the first."""
    a = _docx(tmp_path, "a.docx", "intro", "conclusion")
    b = _docx(tmp_path, "b.docx", "a new opening", "intro", "conclusion")

    with pytest.raises(AnchorError, match="a new opening"):
        build_overrides(a, b)


def test_an_insert_inside_a_reworded_block_rides_the_LAST_pair(tmp_path):
    """Two rewritten paragraphs and one new one between them: the extra
    attaches to the last PAIRED override, so it lands after the second
    rewrite rather than before it."""
    a = _docx(tmp_path, "a.docx", "first para", "second para")
    b = _docx(tmp_path, "b.docx", "first para rewritten",
              "second para rewritten", "and a new one")

    ovs = _texts(build_overrides(a, b))

    assert ovs == [("first para", "first para rewritten"),
                   ("second para", "second para rewrittenand a new one")]


def test_a_MERGE_pairs_the_survivor_by_similarity(tmp_path):
    """Baseline longer than the author's: the pairing loop decides which
    baseline paragraph the surviving text came from, and the rest are
    deletions. Skipping it turns an edit into a pair of deletions and
    loses the author's sentence."""
    a = _docx(tmp_path, "a.docx", "keep",
              "The ECA average rose sharply in 2019.", "A short aside.")
    b = _docx(tmp_path, "b.docx", "keep",
              "The ECA average rose sharply in 2019 and after.")

    ovs = _texts(build_overrides(a, b))

    assert ("The ECA average rose sharply in 2019.",
            "The ECA average rose sharply in 2019 and after.") in ovs
    assert ("A short aside.", "") in ovs


# ------------------------------------------------------ applying them ----

def test_a_MISSED_override_does_not_stop_the_ones_after_it():
    """`continue`, not `break`. A miss is reported and the remaining
    edits are still applied — stopping would drop every later edit while
    reporting only the first as missing."""
    body = "".join(para(run(t), pid=f"{i:08X}")
                   for i, t in enumerate(["alpha", "beta"], 1))
    gone = para(run("vanished"), pid="000000FF")

    out, applied, missed = apply_overrides(
        body, [{"old": gone, "new": para(run("x"), pid="000000FF")},
               {"old": para(run("beta"), pid="00000002"),
                "new": para(run("beta edited"), pid="00000002")}],
        strict=False)

    assert applied == 1
    assert missed == ["vanished"]
    assert "beta edited" in out


def test_an_override_applies_to_ONE_paragraph_not_every_copy():
    """`replace(old, new, 1)`. A manuscript repeats paragraphs — a bare
    "Notes:" line under each table — and one override means one
    paragraph, not all of them."""
    same = para(run("Notes: standard errors in parentheses."), pid="0000000A")
    body = same + para(run("between"), pid="0000000B") + same

    out, applied, _missed = apply_overrides(
        body, [{"old": same, "new": para(run("Notes: clustered."),
                                         pid="0000000A")}], strict=False)

    assert applied == 1
    assert out.count("Notes: standard errors in parentheses.") == 1
    assert out.count("Notes: clustered.") == 1


def test_the_strict_message_NAMES_the_first_few_misses():
    """Three of them, and the count says how many there really are: a
    build that moved under twenty overrides prints twenty paragraphs
    otherwise, and the instruction after them is what matters."""
    overrides = [{"old": para(run(f"gone {i}"), pid=f"{i:08X}"), "new": ""}
                 for i in range(5)]

    with pytest.raises(AnchorError) as exc:
        apply_overrides("<w:body/>", overrides)

    assert "5 override anchor(s) not found" in str(exc.value)
    assert str(exc.value).count("gone ") == 3


def test_a_stored_override_chains_only_onto_its_OWN_output(tmp_path):
    """`e["new"] == old`. Mutated to `or`, the first stored entry with
    any output at all is treated as this round's ancestor: round two's
    edit overwrites an unrelated round-one entry, and round one's edit
    is gone from the file with the count still reading "chained"."""
    a = _docx(tmp_path, "a.docx", "alpha", "beta")
    b = _docx(tmp_path, "b.docx", "alpha", "beta edited")
    store = tmp_path / "overrides.json"
    store.write_text(json.dumps(
        [{"old": "<w:p>unrelated</w:p>", "new": "<w:p>output</w:p>"}]),
        encoding="utf-8")

    _fresh, chained, appended, total = update_overrides(a, b, store)

    assert (chained, appended, total) == (0, 1, 2)
    assert json.loads(store.read_text(encoding="utf-8"))[0]["new"] == \
        "<w:p>output</w:p>"


def test_the_override_file_keeps_its_TEXT_readable(tmp_path):
    """`ensure_ascii=False`. These files are read by whoever is
    integrating the round, and a paragraph escaped to \\u2019 sequences is
    unreadable exactly when someone is trying to see what an override
    does."""
    a = _docx(tmp_path, "a.docx", "the workers' share")
    b = _docx(tmp_path, "b.docx", "the workers’ share, revised")
    store = tmp_path / "overrides.json"

    update_overrides(a, b, store)

    assert "’" in store.read_text(encoding="utf-8")


def test_a_footnote_is_matched_on_the_SAME_text_not_a_LATER_one(tmp_path):
    """`ut.strip() == bt.strip()`. Mutated to `>=` the match becomes
    alphabetical: every build note whose text sorts before the author's
    matches too, and the last one wins — so the author's footnote is
    repointed at a note about something else, with the reference itself
    looking perfectly healthy.
    """
    # the build's notes are ordered so the WRONG one sorts last
    build_fn = ('<w:footnotes>'
                '<w:footnote w:id="6"><w:p><w:r><w:t>Zebra counts.</w:t>'
                "</w:r></w:p></w:footnote>"
                '<w:footnote w:id="7"><w:p><w:r><w:t>Alpha counts.</w:t>'
                "</w:r></w:p></w:footnote></w:footnotes>")
    user_fn = ('<w:footnotes>'
               '<w:footnote w:id="3"><w:p><w:r><w:t>Zebra counts.</w:t>'
               "</w:r></w:p></w:footnote></w:footnotes>")
    base = write(tmp_path / "base.docx",
                 make_parts(para(run("body ")), footnotes=build_fn))
    edited = write(tmp_path / "edited.docx", make_parts(
        para(run("body edited "))
        + '<w:p><w:r><w:footnoteReference w:id="3"/></w:r></w:p>',
        footnotes=user_fn))

    joined = "".join(n for _, n in build_overrides(base, edited))

    assert 'w:footnoteReference w:id="6"' in joined      # Zebra counts.
    assert 'w:footnoteReference w:id="7"' not in joined


def test_a_LONG_document_aligns_ACROSS_a_run_of_blank_paragraphs(tmp_path):
    """`autojunk=False`, and it only bites above 200 paragraphs — which
    every real manuscript is. difflib then calls any line appearing in
    more than 1 % of the document "popular" and refuses to match it, and
    a paper's blank spacer paragraphs are exactly that.

    With the two paragraphs either side of a blank run rewritten, the
    blanks have no adjacent match to be extended over, so they are swept
    into one seven-paragraph replace block: five overrides rewriting a
    blank paragraph as itself, and the real edits paired positionally
    inside a block that has nothing to do with them.
    """
    base = [f"Paragraph {i} of the manuscript." for i in range(250)]
    for i in range(100, 105):
        base[i] = ""
    edited = list(base)
    edited[99] = "A completely different sentence about elasticity."
    edited[105] = "Another wholly rewritten line about coverage."

    a = _docx(tmp_path, "a.docx", *base)
    b = _docx(tmp_path, "b.docx", *edited)

    assert _texts(build_overrides(a, b)) == [
        ("Paragraph 99 of the manuscript.",
         "A completely different sentence about elasticity."),
        ("Paragraph 105 of the manuscript.",
         "Another wholly rewritten line about coverage.")]


def test_an_edit_inside_a_NOTE_is_not_ingested(tmp_path):
    """**A known gap, pinned rather than fixed** — BACKLOG S2,
    2026-08-19.

    The alignment runs over BODY paragraphs. Footnotes are read for one
    purpose, remapping the ids Word renumbered, and endnotes are not
    read at all — so a sentence the author retyped inside a note
    definition yields no override, and the next clean build regenerates
    from a source that never received it.

    `revision.ingest` DESCRIBES the change (it runs `compare`, which
    reads every part a reader sees), which is what makes this worth
    pinning: named in the report and dropped by the fold-back reads as
    handled.

    This test is the documentation's witness. When the gap is closed it
    fails, and the two docstrings and the BACKLOG entry have to be
    rewritten before it can pass again.
    """
    def paper(path, foot, end):
        return write(path, make_parts(
            para(run("The body sentence, identical in both.")),
            footnotes=notes("footnotes", note(foot, 2)),
            extra={"word/endnotes.xml": notes("endnotes",
                                              note(end, 2, "endnote"))}))

    base = paper(tmp_path / "base.docx", "The baseline footnote.",
                 "The baseline endnote.")
    edited = paper(tmp_path / "edited.docx", "The footnote, retyped.",
                   "The endnote, retyped.")

    assert build_overrides(base, edited) == [], (
        "notes are ingested now — update the docstrings and BACKLOG")
