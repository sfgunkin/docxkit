"""A batch as one gated unit of work.

The cases that matter are the ones a per-edit check cannot see: an edit that
rewrites the sentence a LATER edit's signature names, and a carrier moving
while every word on the page stays the same.
"""
from __future__ import annotations

import pytest
from conftest import cp1252_console, document, para, run

from docxkit import batch

BODY = (
    para(run("Figure 1 shows country averages. "),
         run("The average worker is in a similar occupation. "),
         run("Most countries fall in the middle."), pid="A1")
    + para(run("Table 3 shows where older workers are. "),
           run("The share is within 4 points in 10 of the 17 countries."),
           pid="A2")
)


def parts_of(body: str = BODY) -> dict[str, bytes]:
    return {batch.DOCUMENT: document(body).encode("utf-8")}


def xml_of(parts: dict[str, bytes]) -> str:
    return parts[batch.DOCUMENT].decode("utf-8")


# --- preflight ------------------------------------------------------------

def test_preflight_passes_a_batch_that_will_apply():
    edits = [
        batch.Edit("a", "Figure 1 shows", "country averages", "country AFIs"),
        batch.Edit("b", "Table 3 shows", "10 of the 17", "9 of the 16"),
    ]
    assert all(v.ok for v in batch.preflight(edits, xml_of(parts_of())))


def test_preflight_is_CUMULATIVE_so_it_sees_a_batch_eating_its_own_anchor():
    """The failure a per-edit check cannot see.

    Edit `a` rewrites the very sentence edit `b` is anchored on. Checked
    independently, both look fine; run in order, `b` cannot find its paragraph.
    This shape cost AFI's r4 three separate rerun cycles (batches 13, 17, 24).
    """
    edits = [
        batch.Edit("a", "Figure 1 shows", "Figure 1 shows", "Exhibit 1 gives"),
        batch.Edit("b", "Figure 1 shows", "Most countries", "Nearly all"),
    ]
    verdicts = batch.preflight(edits, xml_of(parts_of()))
    assert verdicts[0].ok
    assert not verdicts[1].ok
    assert "NO paragraph" in verdicts[1].reason

    # ... and judged on its own, the same edit is fine.
    alone = batch.preflight([edits[1]], xml_of(parts_of()))
    assert alone[0].ok


def test_preflight_reports_every_failure_in_one_pass():
    edits = [
        batch.Edit("missing", "Figure 1 shows", "not here at all", "x"),
        batch.Edit("ambiguous", "shows", "country averages", "y"),
        batch.Edit("fine", "Table 3 shows", "within 4 points", "within 5"),
    ]
    verdicts = batch.preflight(edits, xml_of(parts_of()))
    assert [v.ok for v in verdicts] == [False, False, True]
    assert "`old` is not in that paragraph" in verdicts[0].reason
    assert "2 paragraphs" in verdicts[1].reason


def test_run_refuses_the_whole_batch_when_preflight_blocks():
    parts = parts_of()
    before = xml_of(parts)
    report = batch.run("b", [
        batch.Edit("fine", "Table 3 shows", "within 4 points", "within 5"),
        batch.Edit("bad", "Figure 1 shows", "absent", "x"),
    ], parts=parts)
    assert not report.ok
    assert not report.applied, "nothing may be applied when preflight blocks"
    assert xml_of(parts) == before


# --- invariants -----------------------------------------------------------

def test_a_carrier_lost_with_no_text_change_is_caught():
    """A bookmark can vanish while every word on the page survives."""
    body = para('<w:bookmarkStart w:id="1" w:name="ref_x"/>',
                run("Figure 1 shows country averages."),
                '<w:bookmarkEnd w:id="1"/>', pid="B1")
    parts = parts_of(body)

    def drop_the_bookmark(xml: str, _p: dict[str, bytes]) -> str:
        return xml.replace('<w:bookmarkStart w:id="1" w:name="ref_x"/>', "")

    report = batch.run("b", [batch.Step("drop", drop_the_bookmark)],
                       parts=parts)
    assert not report.ok
    assert any("bookmarks 1 -> 0" in f for f in report.failures)


def test_a_declared_move_is_allowed_and_an_undeclared_one_is_not():
    parts = parts_of()

    def drop_a_paragraph(xml: str, _p: dict[str, bytes]) -> str:
        i = xml.index("<w:p ")
        j = xml.index("</w:p>", i) + len("</w:p>")
        return xml[:i] + xml[j:]

    ok = batch.run("declared", [batch.Step("drop", drop_a_paragraph)],
                   parts=parts_of(), allow={"paragraphs": -1})
    assert ok.ok, ok.text()

    bad = batch.run("undeclared", [batch.Step("drop", drop_a_paragraph)],
                    parts=parts)
    assert not bad.ok
    assert any("paragraphs 2 -> 1" in f for f in bad.failures)


def test_allow_naming_an_unknown_invariant_is_an_error():
    report = batch.run("b", [
        batch.Edit("a", "Table 3 shows", "within 4 points", "within 5"),
    ], parts=parts_of(), allow={"paragrahps": -1})
    assert not report.ok
    assert any("unknown invariant" in f for f in report.failures)


# --- the settled-file guard ----------------------------------------------

def test_a_batch_refuses_to_stack_on_pending_revisions():
    """Compare treats a pending revision as ACCEPTED, so stacking decides the
    author's open verdicts for them."""
    ins = '<w:ins w:id="9" w:author="R">' + run("new") + "</w:ins>"
    body = para(ins, pid="C1")
    report = batch.run("b", [], parts=parts_of(body))
    assert not report.ok
    assert "pending" in report.failures[0]

    allowed = batch.run("b", [], parts=parts_of(body), require_settled=False)
    assert allowed.ok


# --- steps and writing ----------------------------------------------------

def test_a_step_may_mutate_parts_which_is_what_a_figure_swap_needs():
    parts = parts_of()

    def add_media(xml: str, p: dict[str, bytes]) -> str:
        p["word/media/image1.png"] = b"\x89PNG..."
        return xml.replace("country averages", "country AFIs")

    report = batch.run("b", [batch.Step("media", add_media)], parts=parts)
    assert report.ok, report.text()
    assert parts["word/media/image1.png"] == b"\x89PNG..."


def test_dry_leaves_the_parts_untouched(tmp_path):
    parts = parts_of()
    before = xml_of(parts)
    report = batch.run("b", [
        batch.Edit("a", "Table 3 shows", "within 4 points", "within 5"),
    ], parts=parts, out=tmp_path / "x.docx", dry=True)
    assert report.ok
    assert xml_of(parts) == before
    assert report.written is None
    assert not (tmp_path / "x.docx").exists()


def test_a_clean_run_writes_and_reports_where(tmp_path):
    parts = parts_of()
    out = tmp_path / "batch.docx"
    report = batch.run("b", [
        batch.Edit("a", "Table 3 shows", "10 of the 17", "9 of the 16"),
    ], parts=parts, out=out)
    assert report.ok, report.text()
    assert report.written == out and out.exists()
    assert "9 of the 16" in xml_of(parts)


@pytest.mark.parametrize("sig, old, expect", [
    ("Figure 1 shows", "no such text", "`old` is not in that paragraph"),
    ("shows", "country averages", "2 paragraphs"),
    ("nothing matches this", "x", "NO paragraph"),
])
def test_diagnose_says_which_cause_applies(sig, old, expect):
    assert expect in batch.diagnose(xml_of(parts_of()), sig, old)


# --- what the report SAYS, and the two causes diagnose was still guessing --
#
# The floor caught these: 79.6 % against 85, and every uncovered line was
# either a sentence a person reads or a failure path. A batch runner whose
# report nobody asserts is a runner that can go quiet.


def test_the_report_says_what_it_did_and_what_it_blocked(tmp_path):
    """`Report.text()` is the whole of what a caller sees — a paper's
    script prints it and nothing else. Every branch of it here: a
    blocked verdict with its reason, an applied step, a failure, the
    invariants that MOVED (and the ones that did not), and where the
    file went."""
    rep = batch.Report(name="r4 captions")
    rep.verdicts = [batch.Verdict("keeps", True),
                    batch.Verdict("blocked", False, "`old` is not there")]
    rep.applied = ["renumber the panels"]
    rep.failures = ["swap the figure  ValueError: no drawing"]
    rep.before = {"paragraphs": 12, "links": 4}
    rep.after = {"paragraphs": 11, "links": 4}
    rep.spaces_fixed = 2
    rep.written = tmp_path / "paper.docx"

    lines = rep.text().splitlines()

    assert lines[0] == "r4 captions:"
    assert "  ok   keeps" in lines
    assert "  BLOCKED blocked" in lines
    assert "          -> `old` is not there" in lines
    assert "  OK   renumber the panels" in lines
    assert "  FAIL swap the figure  ValueError: no drawing" in lines
    assert "invariants {'paragraphs': (12, 11)}" in lines[-2]
    assert "preserve_space fixed 2" in lines[-2]
    assert lines[-1] == f"  wrote {tmp_path / 'paper.docx'}"


def test_a_report_that_moved_NOTHING_says_unchanged():
    """The other side of that line: a batch whose carriers all held is
    the ordinary result, and "unchanged" is what says so. An empty dict
    printed there reads as a report that could not measure."""
    rep = batch.Report(name="r4")
    rep.before = {"paragraphs": 12}
    rep.after = {"paragraphs": 12}

    assert "invariants unchanged" in rep.text()


LINK_LABEL = ('<w:hyperlink w:anchor="Table3"><w:r><w:rPr>'
              '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>Table 3</w:t>'
              "</w:r></w:hyperlink>")


def test_diagnose_names_the_HYPERLINK_LABEL_the_match_meets():
    """`replace_in_para` refuses a match that touches a link label, and
    it is right to — but the refusal does not say WHICH label, and a
    caller staring at "spans a hyperlink" has to go and look. This is
    the round trip preflight exists to remove."""
    xml = document(para(f"{LINK_LABEL}<w:r><w:t> shows where older "
                        "workers are.</w:t></w:r>", pid="A1"))

    said = batch.diagnose(xml, "shows where", "Table 3")

    assert "hyperlink label 'Table 3'" in said
    assert "allow_hyperlink=True" in said


def test_diagnose_names_the_EQUATION_a_match_spans():
    """The other cause that reads as an anchor typo: the words are on
    the page, and half of them are inside `m:oMath`, which this module
    never rewrites."""
    math = "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"
    xml = document(para(run("The value "), math, run(" is small."),
                        pid="A2"))

    said = batch.diagnose(xml, "is small", "x is")

    assert "spans an equation" in said
    assert "never rewrites OMML" in said


def test_diagnose_says_so_when_it_cannot_model_the_refusal():
    """The honest fallback. `preflight` catches whatever the real
    replace raises, so a cause this function does not know about still
    reaches the caller as a message — with the exception beside it —
    rather than as a confident wrong diagnosis."""
    xml = document(para(f"{LINK_LABEL}<w:r><w:t> shows where older "
                        "workers are.</w:t></w:r>", pid="A1"))

    said = batch.diagnose(xml, "shows where", "shows where")

    assert "a reason preflight does not model" in said


def test_preflight_reports_an_edit_that_changes_NOTHING():
    """An edit whose `new` is its `old` applies without raising and
    leaves the document as it was. Nothing downstream can tell that
    from a batch that worked, which is why it is a verdict rather than
    a silence."""
    xml = document(para(run("Alpha beta gamma."), pid="A1"))

    (verdict,) = batch.preflight(
        [batch.Edit("noop", "Alpha", "beta", "beta")], xml)

    assert verdict.ok is False
    assert verdict.reason == "matched but changed nothing"


def test_a_step_that_RAISES_is_reported_and_the_xml_is_rolled_back():
    """`apply_steps` keeps going so one failure does not hide the rest,
    and a step that raised leaves the document as it found it — a half
    applied step is the thing a batch must never write."""
    def boom(xml: str, parts: dict[str, bytes]) -> str:
        raise ValueError("the swap could not find its drawing")

    xml = document(para(run("Alpha beta gamma."), pid="A1"))

    out, applied, failures = batch.apply_steps(
        xml, {}, [batch.Step("swap the figure", boom)])

    assert out == xml, "rolled back"
    assert applied == []
    assert failures == ["swap the figure  ValueError: "
                        "the swap could not find its drawing"]


def test_the_note_PART_NAMES_are_re_exported_beside_DOCUMENT():
    """Bookmark ids must be unique across the whole document, notes
    included, so a batch that mints one wants every part that can hold
    one. `from docxkit.batch import DOCUMENT, FOOTNOTES` used to raise
    ImportError, and the caller then reached into private `_xml` or
    hard-coded "word/footnotes.xml" — the string the constant exists to
    stop anyone writing."""
    from docxkit.batch import DOCUMENT, ENDNOTES, FOOTNOTES

    assert (DOCUMENT, FOOTNOTES, ENDNOTES) == (
        "word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
    assert {"DOCUMENT", "FOOTNOTES", "ENDNOTES"} <= set(batch.__all__)


def test_an_invariant_that_goes_UP_is_blocked_as_well_as_one_that_FALLS():
    """Every invariant case here loses something — bookmarks 1 -> 0,
    paragraphs 2 -> 1 — so the gate was only ever asked about a fall.
    Read `!=` as `<` and a carrier that DUPLICATES sails through: an
    edit applied twice, a bookmark cloned with its name, a row copied.
    That is the same invisible-to-a-text-diff damage the gate exists
    for, arriving from the other side.
    """
    body = para('<w:bookmarkStart w:id="1" w:name="ref_x"/>',
                run("Figure 1 shows country averages."),
                '<w:bookmarkEnd w:id="1"/>', pid="B1")

    def clone_the_bookmark(xml: str, _p: dict[str, bytes]) -> str:
        return xml.replace(
            '<w:bookmarkEnd w:id="1"/>',
            '<w:bookmarkEnd w:id="1"/>'
            '<w:bookmarkStart w:id="2" w:name="ref_x"/>'
            '<w:bookmarkEnd w:id="2"/>')

    report = batch.run("b", [batch.Step("clone", clone_the_bookmark)],
                       parts=parts_of(body))

    assert not report.ok, report.text()
    assert any("bookmarks 1 -> 2" in f for f in report.failures), \
        report.failures

    # and the REPORT says which way it went, for the same reason: read
    # `!=` as `>` there and the line a human reads omits the increase
    # while the gate still blocks it, which is the worst of both.
    assert "'bookmarks': (1, 2)" in report.text(), report.text()

    declared = batch.run("declared", [batch.Step("clone", clone_the_bookmark)],
                         parts=parts_of(body),
                         allow={"bookmarks": 1, "bookmark_ends": 1})

    assert declared.ok, declared.text()


def test_preflight_keeps_going_PAST_an_edit_that_changed_nothing():
    """Reporting all of them at once is the whole point — three anchor
    problems otherwise cost three cycles. The no-op verdict had a test
    and the all-at-once promise had a test, and no test put a no-op
    FIRST, so the branch was free to stop the pass there."""
    xml = document(para(run("Alpha beta gamma."), pid="A1")
                   + para(run("Delta epsilon zeta."), pid="A2"))

    verdicts = batch.preflight([
        batch.Edit("noop", "Alpha", "beta", "beta"),
        batch.Edit("fine", "Delta", "epsilon", "eta"),
    ], xml)

    assert [v.ok for v in verdicts] == [False, True], \
        "the no-op must not end the pass"
    assert verdicts[0].reason == "matched but changed nothing"


def test_apply_steps_keeps_going_after_a_step_RAISES():
    """`test_a_step_that_RAISES_is_reported_and_the_xml_is_rolled_back`
    says in its docstring that apply_steps keeps going so one failure
    does not hide the rest — and passes ONE step, so it cannot see it.
    The mutant that turns that `continue` into a `break` survived it."""
    def boom(xml: str, _p: dict[str, bytes]) -> str:
        raise ValueError("the swap could not find its drawing")

    xml = document(para(run("Alpha beta gamma."), pid="A1"))

    out, applied, failures = batch.apply_steps(xml, {}, [
        batch.Step("swap the figure", boom),
        batch.Edit("after", "Alpha", "gamma", "delta"),
    ])

    assert applied == ["after"], "the step after the failure still ran"
    assert len(failures) == 1
    assert "delta" in out and "gamma" not in out


def test_apply_steps_reports_a_NO_OP_edit_and_still_applies_the_rest():
    """Reachable even though `run` preflights, because preflight sees
    only the Edits and applies them cumulatively WITHOUT the Steps
    between them: a Step that rewrites the sentence an Edit targets
    makes that Edit a no-op at apply time, having passed preflight.
    Nothing downstream can tell a no-op from a batch that worked."""
    xml = document(para(run("Alpha beta gamma."), pid="A1")
                   + para(run("Delta epsilon zeta."), pid="A2"))

    out, applied, failures = batch.apply_steps(xml, {}, [
        batch.Edit("noop", "Alpha", "beta", "beta"),
        batch.Edit("after", "Delta", "epsilon", "eta"),
    ])

    assert failures == ["noop  matched but changed nothing"]
    assert applied == ["after"], "the edit after the no-op still ran"
    assert "eta" in out


def test_the_value_objects_cannot_be_MUTATED_between_preflight_and_apply():
    """`preflight` reports on the edits it was handed; `apply_steps`
    then applies them again, separately. That verdict only means
    something if the two are the same object AND it cannot have changed
    in between — a Step's `fn` is arbitrary caller code holding whatever
    references the script gave it, and a batch that preflighted one
    anchor and applied another would be gated on a document state that
    never existed.

    Cheap to state, and three mutants turn `frozen=True` off.
    """
    import dataclasses

    edit = batch.Edit("t", "sig", "old", "new")
    step = batch.Step("label", lambda xml, parts: xml)
    verdict = batch.Verdict("t", True)

    for obj, attr, value in ((edit, "old", "something else"),
                             (step, "label", "renamed"),
                             (verdict, "ok", False)):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, attr, value)


def test_a_document_of_MORE_THAN_256_PARAGRAPHS_passes_its_own_invariants():
    """The gate compares counts, and CONTRIBUTING already names what
    that costs: Python caches integers to 256 and builds the rest, so
    two counts of 300 are equal and are NOT the same object. Under
    `is not` every invariant reads as moved, every batch against an
    ordinary manuscript fails with `paragraphs 301 -> 301, expected
    301`, and nothing that could be edited would ever be written.

    301 paragraphs is not a stress case. It is a paper. Every fixture in
    this file has two, which is why the comparison could be anything at
    all — and `report.text()` compares the same counts a second time to
    decide what to print as moved, so both of them need a document long
    enough to tell equality from identity."""
    long_body = BODY + "".join(
        para(run(f"Filler paragraph {i}."), pid=f"F{i}")
        for i in range(299))
    parts = parts_of(long_body)
    assert batch.invariants(xml_of(parts))["paragraphs"] > 256

    report = batch.run("b", [
        batch.Edit("fine", "Table 3 shows", "within 4 points", "within 5"),
    ], parts=parts)

    assert report.ok, report.failures
    assert report.failures == []
    assert "invariants unchanged" in report.text(), report.text()


# `diagnose` exists to say WHICH cause applies, so a wrong diagnosis
# sends a reader down the round trip it was written to remove. Every
# case above satisfies both halves of the condition it tests — the
# hyperlink label EQUALS `old`, the equation paragraph really has an
# equation — so an `and` widened to `or` produced the same message and
# survived.

def test_diagnose_quotes_the_FIRST_near_sentence_not_just_any_of_them():
    """The nearest-text clause is a hint about where the anchor drifted
    to, and quoting a different sentence than the one at the top of the
    paragraph points somewhere the reader has to rule out by hand.

    Two sentences carry the fragment here, which is what tells `near[0]`
    from `near[-1]`; every earlier fixture had one, where they are the
    same string."""
    body = para(run("Results: the share of older workers rose. "
                    "Also: the share of older workers fell. "
                    "Nothing else."), pid="A1")

    said = batch.diagnose(document(body), "Nothing else",
                          "the share of older workers held steady")

    assert "`old` is not in that paragraph" in said
    assert "rose" in said, said
    assert "fell" not in said, said


def test_diagnose_does_NOT_blame_an_equation_in_a_paragraph_without_one():
    """The equation branch is two conditions and both earn their place:
    the paragraph holds `m:oMath`, AND `old` is missing from the raw
    `w:t` text. The second alone is true of any escaped character —
    `visible_text` unescapes `&amp;` and the raw join does not — so a
    paragraph with an ampersand and no maths in it reads as an equation
    the moment those are joined by `or`, and the reader is sent to look
    for OMML that is not there."""
    body = para(run("Smith &amp; Lee report the result."), pid="A1")

    said = batch.diagnose(document(body), "report the result",
                          "Smith & Lee")

    assert "spans an equation" not in said, said
    assert "preflight does not model" in said, said


def test_diagnose_names_a_label_that_is_only_PART_of_the_match():
    """The label test runs both ways on purpose: the match may sit
    inside the label, or the label inside the match. Narrowed to `and`
    only an exact equality qualifies — which is what the existing case
    happens to be — and an anchor that merely CONTAINS the label falls
    through to "a reason preflight does not model", which is the answer
    that means "go and look"."""
    xml = document(para(f"<w:r><w:t>see </w:t></w:r>{LINK_LABEL}"
                        "<w:r><w:t> for the split.</w:t></w:r>", pid="A1"))

    said = batch.diagnose(xml, "for the split", "see Table 3 for")

    assert "hyperlink label 'Table 3'" in said, said


# --- the console a paper script actually gets -----------------------------

MINUS = "−"        # U+2212, and NOT in cp1252 — unlike the em dash


def test_a_step_that_PRINTS_a_maths_glyph_still_applies():
    """The failure this guards, measured on Aging_Well R96: the step
    printed the typographic minus it was restoring, `print` raised on a
    cp1252 console, `apply_steps` caught it, ROLLED THE STEP BACK and
    reported a step failure. Same file, same code, `ok=False` where a
    UTF-8 terminal gave `ok=True` — and the only variable is the
    terminal's code page.

    That it reports failure rather than claiming success is why this is
    not an S1. The cost is that the failure reads as a fault in the
    manuscript at exactly the moment — a close-out after the author's
    accept — when a glyph problem is what you are looking for.
    """
    def repair(xml: str, _parts: dict[str, bytes]) -> str:
        print(f"  restored {MINUS} in run 3")
        return xml.replace("country averages", "country AFIs")

    with cp1252_console() as printed:
        report = batch.run("maths glyphs", [batch.Step("glyphs", repair)],
                           parts=parts_of())

    assert report.ok, report.failures
    assert report.applied == ["glyphs"]
    assert MINUS in printed(), \
        "the step ran but its report of what it restored was lost"


def test_a_REFUSED_batch_can_still_have_its_report_printed():
    """Why the call is at the top of `run` and not beside `apply_steps`.

    A preflight refusal returns before any step executes, and ONE
    refusal echoes the document back: `diagnose` quotes the hyperlink
    label it met, verbatim. The others are the toolkit's own English and
    would survive cp1252 — this one carries whatever the manuscript
    calls its exhibits, which on DSI is Cyrillic. `print(report.text())`
    is the documented way to read a Report, so the reconfigure has to
    have happened before that early return.
    """
    label = "Таблица 3"
    link = ('<w:hyperlink w:anchor="t3"><w:r><w:rPr><w:rStyle '
            f'w:val="Hyperlink"/></w:rPr><w:t>{label}</w:t></w:r>'
            "</w:hyperlink>")
    body = para(run("see "), link, run(" for the split."), pid="A1")
    edits = [batch.Edit("R22", "for the split", f"see {label} for", "x")]

    with cp1252_console() as printed:
        report = batch.run(
            "relabel", edits,
            parts={batch.DOCUMENT: document(body).encode("utf-8")})
        assert not report.ok
        print(report.text())                # the failure was raised HERE

    assert f"hyperlink label '{label}'" in printed()


def test_apply_steps_makes_the_console_safe_for_a_DIRECT_caller():
    """`apply_steps` is in `__all__` and papers call it directly; it is
    also the one place the library hands control to caller code that
    prints, so it carries the call as well as `run` does."""
    def repair(xml: str, _parts: dict[str, bytes]) -> str:
        print(f"  restored {MINUS}")
        return xml.replace("country averages", "country AFIs")

    with cp1252_console() as printed:
        _xml, applied, failures = batch.apply_steps(
            xml_of(parts_of()), {}, [batch.Step("glyphs", repair)])

    assert applied == ["glyphs"] and not failures
    assert MINUS in printed()
