"""A batch as one gated unit of work.

The cases that matter are the ones a per-edit check cannot see: an edit that
rewrites the sentence a LATER edit's signature names, and a carrier moving
while every word on the page stays the same.
"""
from __future__ import annotations

import pytest
from conftest import document, para, run

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
