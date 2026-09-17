"""The CLI's end of the single-file revision protocol.

These commands take almost no arguments: they read ``revision/paper.toml``
and derive every path from it. So what is worth asserting here is that
they find the paper at all, that the exit codes DISTINGUISH the refusals
— a caller must be able to tell which one it hit without parsing English
— and that ``status`` answers the one question the whole layout exists to
answer: is this file the truth, or a proposal someone still has to
adjudicate?

As in test_cli.py, the assertions are on the FILE wherever a file is at
stake. A message is not what an author loses.
"""
from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path

import pytest
from conftest import ins, make_parts, para, run, write
from test_cli import run_cli


@pytest.fixture
def project(tmp_path):
    """A migrated paper, scaffolded the way `revision init` does it."""
    from docxkit import revision
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "manuscript.docx",
                make_parts(para(run("The paper as it stands."))))
    return revision.init(tmp_path / "proj", src, name="Test Paper")


def _ins(text: str, author: str = "Revision") -> str:
    return (f'<w:ins w:id="90" w:author="{author}" '
            f'w:date="2026-08-07T00:00:00Z">{run(text)}</w:ins>')


FOOTNOTES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
             'wordprocessingml/2006/main" xmlns:w14="http://schemas.'
             'microsoft.com/office/word/2010/wordml">'
             '<w:footnote w:id="2">{body}</w:footnote></w:footnotes>')

NS_M = ('xmlns:m="http://schemas.openxmlformats.org/'
        'officeDocument/2006/math"')


class _Doc:
    """A Word document, faked at the COM boundary."""

    def __init__(self, revisions: int = 1, text: str = "") -> None:
        self.Revisions = type("R", (), {"Count": revisions})()
        self._text = text

    def AcceptAllRevisions(self) -> None:
        pass

    @property
    def Paragraphs(self):
        return [type("P", (), {"Range": type("R", (), {
            "Text": self._text})()})()]


class _Word:
    def __init__(self, doc: _Doc | None = None,
                 explode: bool = False) -> None:
        self.doc, self.explode = doc or _Doc(), explode

    @contextlib.contextmanager
    def session(self, **_kw):
        yield "app"

    @contextlib.contextmanager
    def open_doc(self, _app, _path, **_kw):
        if self.explode:
            raise OSError("Word could not open the file")
        yield self.doc


def _fake_build(math: int = 0, revisions: int = 7):
    """tracked.build, replaced: what Word Compare resolved is an input."""
    from docxkit import tracked

    def build(original, revised, out, classify=None, **kw):
        write(Path(out), make_parts(para(run("redlined"))))
        (kw.get("progress") or (lambda _: None))(
            f"resolved {math} math revisions")
        report = tracked.BuildReport()
        report.revisions = revisions
        report.math_resolved = math       # the number the protocol reads
        return report

    return build


# ----------------------------------------------------------------- init

def test_init_adopts_the_manuscript_in_place(monkeypatch, tmp_path,
                                            capsys):
    """The paper keeps its name, and the author is told so."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("body"))))
    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"), "--name", "LE",
                      "--author", "Agent", "--language", "ru",
                      "--attic", str(tmp_path / "attic"))
    out = capsys.readouterr().out
    assert code == 0
    assert Path(src).exists()
    assert not (tmp_path / "proj" / "revision" / "working.docx").exists()
    assert "adopted in place" in out
    assert "LE7.docx" in out


def test_init_WORKING_names_a_copy_and_says_the_source_is_spent(
        monkeypatch, tmp_path, capsys):
    """The old migration shape, now asked for by name. The source is
    left where it was and nothing reads it again — a state the first
    version of this protocol created silently, on every paper."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("b"))))
    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"),
                      "--working", "Report/LE.docx")
    out = capsys.readouterr().out
    assert code == 0
    assert (tmp_path / "proj" / "Report" / "LE.docx").exists()
    assert Path(src).exists(), "the source was moved, not copied"
    assert "COPIED, not moved" in out


def test_init_refuses_to_rewrite_a_live_config(monkeypatch, project,
                                               capsys):
    """A clean message on stderr, not a traceback."""
    code, _ = run_cli(monkeypatch, "revision", "init",
                      str(project.working), "--root", str(project.root))
    assert code == 1
    assert "already" in capsys.readouterr().err


def test_init_force_rewrites_in_place(monkeypatch, project):
    """Re-running init on a MIGRATED paper, to correct its config: the
    source is the manuscript itself, and copying a file onto itself
    raises rather than being a no-op."""
    before = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "init",
                      str(project.working), "--root", str(project.root),
                      "--force")
    assert code == 0
    assert project.working.read_bytes() == before


def test_init_defaults_the_root_to_the_manuscripts_folder(monkeypatch,
                                                          tmp_path):
    src = write(tmp_path / "solo.docx", make_parts(para(run("body"))))
    code, _ = run_cli(monkeypatch, "revision", "init", str(src))
    assert code == 0
    assert (tmp_path / "revision" / "paper.toml").is_file()
    from docxkit.revision import load_paper
    assert load_paper(tmp_path).working == Path(src)


# --------------------------------------------------------------- status

def test_status_answers_truth(monkeypatch, project, capsys):
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "TRUTH" in out
    assert "Test Paper" in out


def test_status_exits_1_on_a_proposal(monkeypatch, project, capsys):
    """A non-zero status is what lets a script refuse to start a batch."""
    write(project.working, make_parts(para(run("x"), _ins("added"))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "PROPOSAL" in out
    assert "by: Revision (1)" in out


def test_status_names_a_pending_kind_only_WORD_can_clear(monkeypatch,
                                                         project, capsys):
    """"1 pending" reads as "the author has not finished", and for a
    cell merge it also means "and nothing here will ever finish it":
    `accept` and `reject` leave a `w:cellMerge` standing, so the line
    that sends the author to Word is the whole repair (BACKLOG S1)."""
    merge = ('<w:tbl><w:tr><w:tc><w:tcPr><w:cellMerge w:id="8" '
             'w:author="Revision" w:date="2026-01-01T00:00:00Z" '
             'w:vMerge="cont"/></w:tcPr>'
             + para(run("cell")) + "</w:tc></w:tr></w:tbl>")
    write(project.working, make_parts(merge))

    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 1
    assert "w:cellMerge" in out, out
    assert "only Word can" in out, out


def test_status_names_the_part_the_author_cannot_see(monkeypatch, project,
                                                     capsys):
    """Review > Next walks the body only, so "1 pending" sends an author
    hunting through prose for something that lives in a footnote."""
    write(project.working, make_parts(
        para(run("clean body")),
        footnotes=FOOTNOTES.format(body=para(_ins("hidden")))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "footnotes" in out
    assert "Review>Next SKIPS these" in out


def test_status_flags_a_baseline_the_paper_has_outgrown(monkeypatch,
                                                        project, capsys):
    """The author accepted every revision in Word and saved. Counting
    pending revisions sees TRUTH on both sides and says go; the two files
    are no longer the same paper, and a batch built here is built on the
    wrong base — which `promote` discovers only after a Word Compare."""
    write(project.working, make_parts(para(run("The paper, as accepted."))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 4, "a stale baseline exited 0 - a script would build on it"
    assert "TRUTH" in out                    # both sides still count zero
    assert "STALE" in out and "word/document.xml" in out
    assert "revision ingest" in out


def test_status_folds_a_flood_of_stale_parts_into_a_line(monkeypatch,
                                                         project, capsys):
    """The first real one listed sixteen parts, twelve of them
    `word/fonts/font*.odttf` from one tick of Word's embed-fonts box, on
    a single line nobody would read."""
    from docxkit import package
    fonts = {f"word/fonts/font{i}.odttf": f"binary{i}".encode()
             for i in range(1, 13)}
    parts = package.read_parts(project.working)
    parts.update(fonts)
    parts["word/document.xml"] = make_parts(
        para(run("edited")))["word/document.xml"]
    package.write_docx(project.working, parts)

    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    stale_line = next(ln for ln in out.splitlines() if "STALE" in ln)
    assert code == 4
    assert "word/fonts/ (12 parts)" in stale_line
    assert "font1.odttf" not in stale_line
    assert len(stale_line) < 120, stale_line


def test_status_does_not_cry_stale_over_a_pending_proposal(monkeypatch,
                                                           project, capsys):
    """A proposal is SUPPOSED to differ from its baseline. Reporting it
    as staleness would fire on every batch the protocol produces."""
    write(project.working, make_parts(para(run("x"), _ins("added"))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1 and "STALE" not in out


def test_the_stale_line_caps_a_long_list_of_loose_parts():
    """Folding by directory is not enough on its own: a package can
    diverge in a dozen parts that share no folder."""
    from docxkit.cli import _summarize
    loose = [f"part{i}.xml" for i in range(1, 8)]
    line = _summarize(loose)
    assert line.endswith("and 3 more")
    assert "part5.xml" not in line


def test_status_reports_a_missing_baseline(monkeypatch, project, capsys):
    project.prev.unlink()
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    assert code == 0
    assert "MISSING" in capsys.readouterr().out


def test_a_pending_proposal_still_exits_1_with_no_baseline(monkeypatch,
                                                           project, capsys):
    """That branch has its own `return 0 if st.is_truth else 1`, and only
    the truth half was ever run — so the code a script reads to decide
    whether it may start a batch was unpinned for a paper that has not
    been baselined yet."""
    project.prev.unlink()
    write(project.working, make_parts(para(run("x"), _ins("added"))))
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "MISSING" in out and "PROPOSAL" in out


def test_a_paper_that_has_not_migrated_says_what_to_do(monkeypatch,
                                                       tmp_path, capsys):
    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(tmp_path))
    err = capsys.readouterr().err
    assert code == 1
    assert "has not" in err and "init" in err
    # the message quotes an em dash; stderr must be UTF-8 or the one
    # message whose job is to explain the failure loses characters
    assert "—" in err


# --------------------------------------------------------------- ingest

def test_ingest_on_an_untouched_paper(monkeypatch, project, capsys):
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "no differences" in out


def test_ingest_reports_the_authors_edit(monkeypatch, project, tmp_path,
                                         capsys):
    write(project.working, make_parts(para(run("The paper, reworded."))))
    out_json = tmp_path / "ingest.json"
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root), "--json",
                      str(out_json))
    out = capsys.readouterr().out
    assert code == 0
    assert "no differences" not in out
    # nothing left pending, so the next step is to record it as truth
    assert "docxkit revision baseline" in out
    assert json.loads(out_json.read_text(encoding="utf-8"))["content"]


_LINKED = ('<w:hyperlink w:anchor="ref_Ritchie2023b">'
           "<w:r><w:t>Ritchie (2023b)</w:t></w:r></w:hyperlink>")


def _ate_a_link(project) -> None:
    """The author's Word session collapsed the paragraph and the link
    element went with it — the words all survive."""
    write(project.prev, make_parts(para(run("see "), _LINKED)))
    write(project.working,
          make_parts(para(run("see "), "<w:r><w:t>Ritchie (2023b)</w:t>"
                                       "</w:r>")))


def test_ingest_reports_a_RE_LABELLED_link_apart_from_the_losses(monkeypatch,
                                                                 project,
                                                                 capsys):
    """Its own section, and not under LOST. The two say opposite things
    to a reader: one is damage to put back before baselining, the other
    is an edit the author meant — DSI's R24.1 re-labelled four back-link
    fields and read four losses it then had to talk past."""
    write(project.prev, make_parts(para(run("see "), _LINKED)))
    write(project.working, make_parts(para(
        run("see "),
        '<w:hyperlink w:anchor="ref_Ritchie2023b">'
        "<w:r><w:t>Ritchie and Roser (2023b)</w:t></w:r></w:hyperlink>")))

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "== LOST" not in out, out
    lines = out.splitlines()
    at = lines.index("== RE-LABELLED (1) ==")
    assert "ref_Ritchie2023b" in lines[at + 1]
    assert "Ritchie (2023b)" in lines[at + 1]
    assert "Ritchie and Roser (2023b)" in lines[at + 1]
    assert "does not refuse" in out


def test_ingest_check_EXITS_on_a_hand_back_that_lost_something(monkeypatch,
                                                               project,
                                                               capsys):
    """Reporting it and exiting 0 is what let six losses scroll past on
    LI7. `--check` is what a paper can put in its own gate list."""
    from docxkit.errors import HandbackLoss

    _ate_a_link(project)
    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--paper", str(project.root))
    assert code == HandbackLoss.exit_code
    assert "LOST" in capsys.readouterr().out


def test_ingest_without_check_still_only_REPORTS(monkeypatch, project,
                                                 capsys):
    """Read-only and exit 0 stays the default: `ingest` is the command
    that is safe to run before every task."""
    _ate_a_link(project)
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    assert code == 0
    assert "LOST" in capsys.readouterr().out


def test_baseline_refuses_the_loss_and_accept_loss_lets_it_through(
        monkeypatch, project, capsys):
    from docxkit.errors import HandbackLoss

    _ate_a_link(project)
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))
    assert code == HandbackLoss.exit_code

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--accept-loss", "link:ref_Ritchie2023b (Ritchie "
                      "(2023b))", "--paper", str(project.root))
    assert code == 0
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_ingest_tells_a_link_WORD_ATE_from_a_passage_the_author_CUT(
        monkeypatch, project, capsys):
    """One report, both kinds, and they need opposite actions.

    The LOST block closed with a single explanation for the whole list:
    "Word does this silently when it collapses a paragraph to make an
    edit; the words all survive, so no content layer above shows it."
    For a link eaten by a rewrite that is exactly right. For a citation
    the author DELETED every clause of it is false — the words did not
    survive, no script can restore it, and the content layers above did
    show it: the deletion is in the `text` section a few lines up.

    Measured 2026-09-08 on Aging_Well, a hand copy-edit mixing both: 19
    LOST, 4 links whose mentions were intact and 5 whose mentions were
    gone, with no way to tell them apart. The reader either runs the
    repair lane hoping it covers everything, or reads five deliberate
    editorial cuts as damage Word did."""
    cut = ('<w:hyperlink w:anchor="ref_Cox1987">'
           "<w:r><w:t>Cox (1987)</w:t></w:r></w:hyperlink>")
    write(project.prev,
          make_parts(para(run("see "), _LINKED, run(" and "), cut)))
    # the first paragraph collapsed (link gone, words kept); the second
    # citation was deleted outright, words and all
    write(project.working, make_parts(
        para(run("see "), "<w:r><w:t>Ritchie (2023b)</w:t></w:r>")))

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0, out

    block = out[out.index("== LOST"):]
    survive, gone = (block.index("the words SURVIVE"),
                     block.index("the words are GONE"))
    assert survive < gone, block
    # each anchor under the heading that describes what happened to it
    assert survive < block.index("ref_Ritchie2023b") < gone, block
    assert block.index("ref_Cox1987") > gone, block
    # the claim that was false of the deleted half is not made about it
    assert "the words all survive" in block[survive:gone], block
    assert "not Word's doing" in block[gone:], block


def test_a_loss_that_is_not_a_link_is_listed_without_the_words_claim(
        monkeypatch, project, capsys):
    """A bookmark, a note, a comment, a glyph: Word eating one takes its
    text with it, so "the words all survive" separates nothing there and
    the report must not answer the question. They group on their own,
    under a plain heading and no explanation."""
    write(project.prev, make_parts(para(
        run("see "), _LINKED,
        '<w:bookmarkStart w:id="4" w:name="tbl_growth"/>'
        '<w:bookmarkEnd w:id="4"/>', run(" Table 1."))))
    write(project.working, make_parts(para(
        run("see "), "<w:r><w:t>Ritchie (2023b)</w:t></w:r>",
        run(" Table 1."))))

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    block = capsys.readouterr().out
    block = block[block.index("== LOST"):]

    assert "-- structure (1)" in block, block
    at = block.index("-- structure (1)")
    assert "tbl_growth" in block[at:], block
    # the claim is made about the link above it, and not about this
    assert "the words all survive" in block[:at], block
    assert "the words all survive" not in block[at:], block


def test_ingest_does_not_HEAD_a_list_that_is_all_one_kind(monkeypatch,
                                                          project, capsys):
    """The split is for a MIXED list, which is what the one explanation
    got wrong. A report of a single kind reads better flat, and the
    heading would be noise on the ordinary hand-back."""
    _ate_a_link(project)

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    assert "the words SURVIVE" not in out
    assert "the words all survive" in out, out


def _ate_two_links(project) -> None:
    """Two collapsed links, so "the flags were discarded" and "the
    anchors did not match" cannot look alike."""
    second = ('<w:hyperlink w:anchor="ref_Kok2015">'
              "<w:r><w:t>Kok et al. (2015)</w:t></w:r></w:hyperlink>")
    write(project.prev,
          make_parts(para(run("see "), _LINKED, run(" and "), second)))
    write(project.working, make_parts(para(
        run("see "), "<w:r><w:t>Ritchie (2023b)</w:t></w:r>",
        run(" and "), "<w:r><w:t>Kok et al. (2015)</w:t></w:r>")))


def test_accept_loss_takes_one_flag_PER_LOSS_as_the_refusal_prints_them(
        monkeypatch, project, capsys):
    """The refusal prints one suggested flag per loss, each on its own
    line, so the form a reader copies out of it is one flag per loss.
    Argparse kept only the LAST, and the command then refused again
    with the list one shorter and nothing saying why: "I named four, it
    says three" reads as anchors that failed to match — a spelling or
    prefix problem — not as flags discarded before the gate ran.

    Measured 2026-09-07 baselining Aging_Well R108, four deliberate
    citation-link deletions; cost one cycle."""
    from docxkit.errors import HandbackLoss

    _ate_two_links(project)
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))
    assert code == HandbackLoss.exit_code
    printed = capsys.readouterr().out + capsys.readouterr().err

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--accept-loss", "link:ref_Ritchie2023b",
                      "--accept-loss", "link:ref_Kok2015",
                      "--paper", str(project.root))

    assert code == 0, printed
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_accept_loss_still_takes_ONE_comma_separated_list(monkeypatch,
                                                          project):
    """The documented form, which the repeatable one must not cost."""
    _ate_two_links(project)

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--accept-loss",
                      "link:ref_Ritchie2023b,link:ref_Kok2015",
                      "--paper", str(project.root))

    assert code == 0
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_ingest_flags_a_style_edit_and_the_parts_that_moved(monkeypatch,
                                                            project,
                                                            capsys):
    base = make_parts(para(run("The paper as it stands.")))
    base["word/styles.xml"] = (
        b"<w:styles><w:style w:styleId='A'/></w:styles>")
    write(project.prev, base)
    changed = dict(base)
    changed["word/styles.xml"] = (
        b"<w:styles><w:style w:styleId='B'/></w:styles>")
    changed["word/numbering.xml"] = b"<w:numbering/>"
    del changed["[Content_Types].xml"]
    write(project.working, changed)

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "STYLE-level edit" in out
    assert "added" in out and "removed" in out


def test_ingest_truncates_a_long_bucket(monkeypatch, project, capsys):
    """A 400-difference dump is not a report anyone reads."""
    write(project.prev, make_parts(
        "".join(para(run(f"baseline paragraph {i}")) for i in range(20))))
    write(project.working, make_parts(
        "".join(para(run(f"reworded paragraph {i}")) for i in range(20))))
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    assert code == 0
    assert "more" in capsys.readouterr().out


def test_ingest_does_not_cry_wolf_over_a_resave(monkeypatch, project,
                                                capsys):
    """A Word round-trip rewrites nearly every part and means nothing."""
    base = make_parts(para(run("The paper as it stands.")))
    write(project.prev, base)
    resaved = dict(base)
    resaved["word/document.xml"] = resaved["word/document.xml"].replace(
        b"<w:body>", b"<w:body >")
    write(project.working, resaved)
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "re-saved" in out
    assert "only save-noise" in out


def test_ingest_shows_what_is_still_pending_on_both_sides(monkeypatch,
                                                          project,
                                                          capsys):
    write(project.prev, make_parts(para(run("x"), _ins("older"))))
    write(project.working, make_parts(para(run("x"), _ins("newer"))))
    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("PROPOSAL") == 2
    assert "docxkit revision baseline" not in out


# ------------------------------------------------------------- baseline

def test_baseline_records_the_new_truth(monkeypatch, project, capsys):
    write(project.working, make_parts(para(run("Accepted and settled."))))
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))
    assert code == 0
    assert project.prev.read_bytes() == project.working.read_bytes()
    assert "baseline updated" in capsys.readouterr().out


def test_baseline_refuses_a_proposal_with_exit_3(monkeypatch, project):
    """BaselinePending is exit 3 — the number the protocol's own
    documentation already quotes."""
    write(project.working, make_parts(para(run("x"), _ins("pending"))))
    before = project.prev.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))
    assert code == 3
    assert project.prev.read_bytes() == before, "the baseline was written"


def test_baseline_force_is_for_migration(monkeypatch, project):
    write(project.working, make_parts(para(run("x"), _ins("pending"))))
    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root), "--force")
    assert code == 0


# ---------------------------------------------------------------- build

def test_build_stages_a_batch(monkeypatch, project, capsys):
    from docxkit import revision
    monkeypatch.setattr(revision.tracked, "build", _fake_build())
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert project.batch.exists()
    assert "7 revisions" in out
    assert "revision validate" in out


def test_build_to_an_explicit_out(monkeypatch, project, tmp_path, capsys):
    from docxkit import revision
    dest = tmp_path / "elsewhere.docx"
    monkeypatch.setattr(revision.tracked, "build", _fake_build())
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--out", str(dest),
                      "--paper", str(project.root))
    assert code == 0
    assert dest.exists()
    assert str(dest) in capsys.readouterr().out


def test_keep_math_REACHES_the_build(monkeypatch, project):
    """A flag that does not arrive is worse than no flag: the redline
    ships with the equations accepted and the run reports success."""
    from docxkit import revision
    seen: dict[str, object] = {}
    inner = _fake_build()

    def build(*a, **kw):
        seen.update(kw)
        return inner(*a, **kw)

    monkeypatch.setattr(revision.tracked, "build", build)
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--keep-math",
                      "--paper", str(project.root))
    assert code == 0
    assert seen["resolve_math"] is False


def test_the_math_is_resolved_when_nobody_says_otherwise(monkeypatch,
                                                         project):
    from docxkit import revision
    seen: dict[str, object] = {}
    inner = _fake_build()

    def build(*a, **kw):
        seen.update(kw)
        return inner(*a, **kw)

    monkeypatch.setattr(revision.tracked, "build", build)
    run_cli(monkeypatch, "revision", "build", str(project.working),
            "--paper", str(project.root))
    assert seen["resolve_math"] is True


def test_no_moves_REACHES_the_build(monkeypatch, project):
    """The other flag whose absence cost a whole round. A compression
    round is mostly moves, Word's move detection truncated one of them
    in the accepted view, and the accept gate refused the batch — with
    no way through the CLI to compare without it."""
    from docxkit import revision
    seen: dict[str, object] = {}
    inner = _fake_build()

    def build(*a, **kw):
        seen.update(kw)
        return inner(*a, **kw)

    monkeypatch.setattr(revision.tracked, "build", build)
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--no-moves",
                      "--paper", str(project.root))
    assert code == 0
    assert seen["moves"] is False


def test_the_moves_are_compared_when_nobody_says_otherwise(monkeypatch,
                                                           project):
    """Off by default would make every relocation a deletion plus an
    insertion, for every paper, to spare the one that measured a bad
    move. It is the answer to a refusal, not the starting setting."""
    from docxkit import revision
    seen: dict[str, object] = {}
    inner = _fake_build()

    def build(*a, **kw):
        seen.update(kw)
        return inner(*a, **kw)

    monkeypatch.setattr(revision.tracked, "build", build)
    run_cli(monkeypatch, "revision", "build", str(project.working),
            "--paper", str(project.root))
    assert seen["moves"] is True


def test_build_refuses_resolved_math_with_exit_2(monkeypatch, project):
    """Word cannot serialize tracked math: those edits would ship with
    nothing to accept or reject."""
    from docxkit import revision
    monkeypatch.setattr(revision.tracked, "build", _fake_build(math=5))
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--paper", str(project.root))
    assert code == 2


def test_build_refuses_a_pending_baseline_with_exit_3(monkeypatch,
                                                      project):
    from docxkit import revision
    write(project.prev, make_parts(para(run("x"), _ins("unadjudicated"))))
    called: list[str] = []
    monkeypatch.setattr(revision.tracked, "build",
                        lambda *a, **k: called.append("ran"))
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--paper", str(project.root))
    assert code == 3
    assert not called, "Word Compare ran despite the refusal"


def test_build_can_absorb_a_pending_baseline_deliberately(monkeypatch,
                                                          project):
    from docxkit import revision
    write(project.prev, make_parts(para(run("x"), _ins("unadjudicated"))))
    monkeypatch.setattr(revision.tracked, "build", _fake_build(math=3))
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--allow-pending-baseline",
                      "--allow-math-resolve", "--paper", str(project.root))
    assert code == 0


def test_the_flag_the_staleness_refusal_advertises_EXISTS(monkeypatch,
                                                          project):
    """`docxkit revision build --force` was `error: unrecognized
    arguments: --force`, and it is what the refusal told the reader to
    do — the guard was right and the only way out it named was fiction
    (2026-08-12). The refusal itself is asserted in test_tracked_guard;
    this asks the parser whether the flag is real, and passes it on."""
    from docxkit import revision

    seen: list[bool] = []

    def _capture(original, revised, out, classify=None, **kw):
        seen.append(kw["force"])
        return _fake_build()(original, revised, out, classify, **kw)

    monkeypatch.setattr(revision.tracked, "build", _capture)
    code, _ = run_cli(monkeypatch, "revision", "build",
                      str(project.working), "--force",
                      "--paper", str(project.root))
    assert code == 0
    assert seen == [True], "the flag parsed and was not passed on"


# ------------------------------------------------------------- validate

def test_validate_passes_a_faithful_batch(monkeypatch, project, capsys):
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT: PASS" in out
    assert "-> OK" in out
    assert "== lint == clean" in out, "a clean batch says so"


def test_validate_RENDERS_the_anchors_it_is_given(monkeypatch, project,
                                                  capsys, tmp_path):
    """BACKLOG S4: the eye gate, on the shared command. DSI kept a
    private 78-line script for this after every other part of its
    ladder retired onto `docxkit revision`, and the next paper to want
    one would have copied it or gone without."""
    made = {"Table 3": tmp_path / "batch__p7.png", "Table 9": None}
    asked: dict[str, object] = {}

    def fake_render(batch, anchors, **kw):
        asked.update(batch=Path(batch), anchors=list(anchors))
        return made

    monkeypatch.setattr("docxkit.revision.render_accepted", fake_render)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root),
                      "--no-word", "--render", "Table 3", "Table 9")
    out = capsys.readouterr().out

    assert code == 0, out
    assert asked["anchors"] == ["Table 3", "Table 9"]
    assert asked["batch"] == project.batch
    assert "== render ==  2 anchor(s), accepted view" in out
    assert "batch__p7.png" in out
    assert "'Table 9': on no page" in out, out


def test_validate_renders_NOTHING_unless_asked(monkeypatch, project, capsys):
    """The step costs a Word session, a render and a PDF. For a batch
    that touches no EQUATION it runs when a person asks for it and not
    otherwise — the default render below is for the maths."""
    def refuse(*a, **kw):                        # pragma: no cover
        raise AssertionError("rendered without --render")

    monkeypatch.setattr("docxkit.revision.render_accepted", refuse)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    run_cli(monkeypatch, "revision", "validate", "--paper",
            str(project.root), "--no-word")

    assert "== render ==" not in capsys.readouterr().out


# --- the equation pages, rendered by DEFAULT --------------------------
#
# BACKLOG, "nothing renders by default": the opt-in above stayed unused
# while four defects only a page can show — spacing dropped, an operator
# set italic, an expression half maths and half prose — went through a
# green ladder, every one in an equation the batch had just written.

#: The prose the equation's page is found by — the paragraph's own
#: first line. Long enough to be a phrase and not a label.
_LEAD = "We assume throughout that"


def _math_batch(project, text: str = "a>0") -> None:
    """A batch that adds one sentence carrying one equation.

    `preserve`, because an unpreserved edge space is exactly what `lint`
    refuses, and the ladder aborts there before any page is named."""
    write(project.batch, make_parts(
        para(run("The paper as it stands."))
        + para(f'<w:ins w:id="92" w:author="Revision" '
               f'w:date="2026-08-07T00:00:00Z">'
               f'{run(_LEAD + " ", preserve=True)}</w:ins>',
               f'<w:ins w:id="93" w:author="Revision" '
               f'w:date="2026-08-07T00:00:00Z"><m:oMath {NS_M}><m:r>'
               f"<m:t>{text}</m:t></m:r></m:oMath></w:ins>")))


def _fake_render(monkeypatch, tmp_path):
    asked: dict[str, object] = {}

    def fake(batch, anchors, **kw):
        asked.update(batch=Path(batch), anchors=list(anchors))
        return {a: tmp_path / f"batch__p{i + 2}.png"
                for i, a in enumerate(anchors)}

    monkeypatch.setattr("docxkit.revision.render_accepted", fake)
    return asked


def test_validate_renders_the_pages_of_the_equations_a_batch_ADDS(
        monkeypatch, project, capsys, tmp_path):
    """Without being asked, and saying which pages and why."""
    from docxkit import revision
    asked = _fake_render(monkeypatch, tmp_path)
    monkeypatch.setattr(revision._validate, "_word", _Word(_Doc()))
    _math_batch(project)

    run_cli(monkeypatch, "revision", "validate", "--paper",
            str(project.root))
    out = capsys.readouterr().out

    assert asked["anchors"] == [_LEAD], asked
    assert asked["batch"] == project.batch
    assert ("== render ==  1 anchor(s), accepted view — 1 for equations "
            "the batch adds or changes") in out, out
    assert f"{_LEAD!r} -> batch__p2.png" in out


def test_the_default_render_says_so_when_NO_WORD_stops_it(
        monkeypatch, project, capsys, tmp_path):
    """Offline means offline — and silence there would read as "no
    equation changed", which is the one thing it must not read as."""
    asked = _fake_render(monkeypatch, tmp_path)
    _math_batch(project)

    run_cli(monkeypatch, "revision", "validate", "--paper",
            str(project.root), "--no-word")
    out = capsys.readouterr().out

    assert not asked, "rendered under --no-word"
    assert "== render ==  1 equation page(s) NOT rendered (--no-word)" in out


def test_a_paper_that_opted_out_renders_only_what_it_NAMES(
        monkeypatch, project, capsys, tmp_path):
    from docxkit import revision
    asked = _fake_render(monkeypatch, tmp_path)
    monkeypatch.setattr(revision._validate, "_word", _Word(_Doc()))
    project.config.write_text(
        project.config.read_text(encoding="utf-8").replace(
            "render_math = true", "render_math = false"),
        encoding="utf-8")
    _math_batch(project)

    run_cli(monkeypatch, "revision", "validate", "--paper",
            str(project.root))
    assert not asked and "== render ==" not in capsys.readouterr().out

    run_cli(monkeypatch, "revision", "validate", "--paper",
            str(project.root), "--render", "Table 3")
    out = capsys.readouterr().out
    assert asked["anchors"] == ["Table 3"]
    assert "== render ==  1 anchor(s), accepted view\n" in out, out


def test_named_anchors_and_the_equation_pages_render_in_ONE_section(
        monkeypatch, project, capsys, tmp_path):
    from docxkit import revision
    asked = _fake_render(monkeypatch, tmp_path)
    monkeypatch.setattr(revision._validate, "_word", _Word(_Doc()))
    _math_batch(project)

    run_cli(monkeypatch, "revision", "validate", "--paper",
            str(project.root), "--render", "Table 3", _LEAD)
    out = capsys.readouterr().out

    assert asked["anchors"] == ["Table 3", _LEAD], (
        "the page named by hand is not rendered twice")
    assert "== render ==  2 anchor(s), accepted view\n" in out, (
        "nothing was ADDED to what was named, so nothing is claimed")


def test_a_missing_reader_is_said_and_does_not_fail_the_batch(
        monkeypatch, project, capsys):
    """PyMuPDF is an optional extra. The ladder has spoken above; the
    render is a person's check, and its absence is a line, not an exit."""
    def no_reader(batch, anchors, **kw):
        raise ImportError("reading the render needs PyMuPDF: pip install "
                          "'docxkit[pdf]'")

    monkeypatch.setattr("docxkit.revision.render_accepted", no_reader)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--paper",
                      str(project.root), "--no-word", "--render", "Table 3")
    out = capsys.readouterr().out

    assert code == 0, out
    assert "not rendered: reading the render needs PyMuPDF" in out
    assert "VERDICT: PASS" in out


def test_validate_fails_an_unreviewable_batch(monkeypatch, project,
                                              capsys):
    """Rejecting everything must restore the baseline, or the author's
    veto is not real."""
    write(project.batch, make_parts(para(run("quietly rewritten"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "MISMATCH" in out
    assert "NOT fully reviewable" in out
    # and WHICH paragraph, which is the half that cost a bespoke difflib
    # script to work out
    assert "quietly rewritten" in out, out


def test_validate_does_not_call_a_RESTORED_note_part_of_the_mismatch(
        monkeypatch, project, capsys):
    """Gate 5 is red for a different reason — an untracked body edit —
    and a footnote the batch merely ADDED to carries an insertion with
    no deletion, which is the shape the warning used to key on. Its
    words come back on reject, so it is not part of this mismatch and
    must not be printed as though it were: the report's own footnotes
    layer says `True` two lines above."""
    from test_revision import footnotes_part

    settled = make_parts(
        para(run("body")),
        footnotes=footnotes_part(para(run("the note text"))))
    write(project.prev, settled)
    write(project.working, settled)          # else `drift` fires first
    write(project.batch, make_parts(
        para(run("quietly rewritten")),
        footnotes=footnotes_part(para(run("the note text"),
                                      ins("See also Kok.")))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 1 and "NOT fully reviewable" in out, out
    assert "'footnotes': True" in out, out
    assert "not part of this mismatch" in out, out
    assert "rejecting empties it" not in out, out


def test_validate_names_the_GLYPH_that_changed(monkeypatch, project,
                                              capsys):
    """`glyphs: False` for a 68,000-character stream says only that
    SOMETHING moved. On AFI the answer was two characters — a minus sign
    Word's Compare had rewritten as a hyphen inside an equation — and
    three builds went by blaming the edits before a bespoke difflib
    script over private imports found them."""
    write(project.prev, make_parts(
        para(run("the gap is − 0.15 in every year"))))
    write(project.batch, make_parts(
        para(run("the gap is - 0.15 in every year"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 1
    assert "GLYPH" in out, out
    assert "U+2212" in out and "U+002D" in out, out
    assert "after ...the gap is " in out, out


def test_validate_says_WHICH_VIEW_a_glyph_difference_is_about(
        monkeypatch, project, capsys):
    """BACKLOG S3. Word downgrades U+2212 to a hyphen while
    re-serialising an equation; `build` puts it back in the ACCEPTED
    view — the document that ships — and the rejected one keeps what
    Compare wrote. So a batch whose edit is perfect fails gate 5 on a
    character no author typed, and `glyphs: False` with no view named
    reads as a defect in the edit. Three consecutive rounds on AFI went
    that way, each ending in a per-paper repair script.

    The gate still fails, and should: the two views disagree. What
    changes is that the report says which one it is judging, and that
    every difference it found is that substitution and nothing else."""
    write(project.prev, make_parts(
        para(run("the gap is − 0.15 in every year"))))
    write(project.batch, make_parts(
        para(run("the gap is - 0.15 in every year"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 1
    assert "GLYPH (reject-all vs baseline)" in out, out
    assert "math character Word downgrades" in out, out
    assert "ACCEPTED view has them restored" in out


def test_a_REAL_edit_is_not_called_a_math_downgrade(monkeypatch, project,
                                                    capsys):
    """The other side of the same flag: a batch that actually changed a
    word must not be excused. `_downgraded` is applied to BOTH streams,
    so they compare equal only when the substitution is the whole of the
    difference."""
    write(project.prev, make_parts(
        para(run("the gap is − 0.15 in every year"))))
    write(project.batch, make_parts(
        para(run("the gap is - 0.19 in every year"))))

    run_cli(monkeypatch, "revision", "validate", "--no-word",
            "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "GLYPH (reject-all vs baseline)" in out, out
    assert "math character Word downgrades" not in out, out


def test_validate_names_a_moved_footnote_anchor(monkeypatch, project,
                                                capsys):
    """Compare emits a re-anchored footnote as one insertion with no
    deletion. Gate 5 could only say `footnotes: False`, and that reads
    like a lossy batch rather than a note whose reference moved."""
    from test_revision import footnotes_part
    write(project.prev, make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("the note")))))
    write(project.batch, make_parts(
        para(run("body")),
        footnotes=footnotes_part(
            para('<w:ins w:id="9" w:author="R" w:date="2026-08-11T00:00:00Z">'
                 "<w:r><w:t>the note</w:t></w:r></w:ins>"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "footnote 2" in out and "REFERENCE moved" in out, out


def test_validate_says_which_LINK_the_rejected_batch_lost(monkeypatch,
                                                          project, capsys):
    """The words come back and the hyperlink does not: Word's Compare
    does not rebuild a link inside a rejected deletion. Parental Style
    T4(3) came back two links short with reject-all reporting OK."""
    linked = ('<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
              "</w:r></w:hyperlink>")
    write(project.prev, make_parts(para(run("see"), linked)))
    write(project.batch, make_parts(para(run("see"), run("Table 5"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "'links': False" in out, out
    assert "LINK LOST -> Table5" in out


def test_validate_says_which_PART_the_batch_lost(monkeypatch, project,
                                                 capsys):
    """The reject-all gate proves the TEXT round-trips; nothing proved
    the package did, and promote copies the batch over working.docx."""
    base = make_parts(para(run("settled")))
    base["customXml/item1.xml"] = (
        b'<b:Sources xmlns:b="http://schemas.openxmlformats.org'
        b'/officeDocument/2006/bibliography"/>')
    write(project.prev, base)
    write(project.batch, {k: v for k, v in base.items()
                          if not k.startswith("customXml/")})
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 1
    assert "LOST customXml/item1.xml" in out, out
    assert "VERDICT: FAIL" in out


def test_status_and_ingest_SAY_when_they_read_a_snapshot(
        monkeypatch, project, capsys):
    """A snapshot mid-edit is a true statement about a moment — and the
    reader has to be told which one they are looking at."""
    from docxkit import package

    monkeypatch.setattr(package, "is_locked",
                        lambda p: Path(p) == project.working)

    for command in ("status", "ingest"):
        run_cli(monkeypatch, "revision", command, "--paper",
                str(project.root))
        out = capsys.readouterr().out
        assert "read from a SNAPSHOT" in out, command


def test_status_under_a_LOCK_names_the_check_it_could_not_run(
        monkeypatch, project, capsys):
    """Measured on Aging_Well, 2026-08-30, on one pair of files minutes
    apart. Locked, `status` printed

        working   0 pending -> TRUTH
        prev      0 pending -> TRUTH

    and stopped. Closed, the same two files printed the same counts and
    then `** baseline STALE: word/ (8 parts) differ(s) **`, exit 4. The
    counts come from the snapshot and are right; the DRIFT check reads
    the saved bytes and never ran, and its absence was not stated — so
    the locked output has the exact shape of a healthy, current
    baseline. After an author has just accepted a batch, that is the
    wrong impression to leave."""
    from docxkit import package

    # a baseline that really has drifted: the live file says something
    # else, and a closed run would exit 4 on it
    write(project.prev, make_parts(para(run("the previous truth"))))
    write(project.working, make_parts(para(run("what the author has now"))))
    monkeypatch.setattr(package, "is_locked",
                        lambda p: Path(p) == project.working)

    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert "drift" in out and "NOT CHECKED" in out
    assert "Close the file" in out
    assert code == 1, "not 0: a run that could not ask is not a clean one"


def test_status_with_the_file_CLOSED_still_reports_the_stale_baseline(
        monkeypatch, project, capsys):
    """The other half of the pair above, so the lock branch cannot buy
    its silence by disabling the check for everyone."""
    write(project.prev, make_parts(para(run("the previous truth"))))
    write(project.working, make_parts(para(run("what the author has now"))))

    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--paper", str(project.root))

    assert code == 4
    assert "baseline STALE" in capsys.readouterr().out


def test_validate_aborts_on_a_batch_built_on_ANOTHER_baseline(
        monkeypatch, project, capsys):
    """The report it used to print instead was detailed, plausible and
    about a different batch — the R1 redline, two baselines old, with
    twenty LINK LOST lines nobody could act on (Aging_Well R5)."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("an older truth"))))
    guard.stamp(project.batch, base_sha256="0" * 64)

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "was NOT built on" in out
    assert "VERDICT: FAIL" in out
    assert "== lint ==" not in out, "the ladder ran on the wrong pair"


def test_validate_aborts_on_lint_with_exit_2(monkeypatch, project,
                                             capsys):
    from docxkit import revision
    write(project.batch, make_parts(para(run("x"))))
    monkeypatch.setattr(revision._lint, "lint_parts",
                        lambda _p: ["orphan bookmark 3"])
    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 2
    assert "ABORT before Word" in out


def test_validate_reports_a_file_word_refuses(monkeypatch, project,
                                              capsys):
    from docxkit import revision
    write(project.batch, make_parts(para(run("x"))))
    monkeypatch.setattr(revision._validate, "_word", _Word(explode=True))
    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root))
    assert code == 3
    assert "FAILED (corrupted)" in capsys.readouterr().out


def test_validate_with_word_lists_the_papers_own_gates(monkeypatch,
                                                       project, capsys):
    """They are LISTED, never run: what a paper checks is the paper's
    business, and shelling out is a larger promise than this makes."""
    from docxkit import revision
    project.config.write_text(
        project.config.read_text(encoding="utf-8").replace(
            "commands = []",
            'commands = ["python scripts/verify_tables.py"]'),
        encoding="utf-8")
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("more"))))
    monkeypatch.setattr(revision._validate, "_word",
                        _Word(_Doc(text="The paper as it stands.more")))
    code, _ = run_cli(monkeypatch, "revision", "validate",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "verify_tables.py" in out
    assert "1 revision group(s) in the body" in out
    assert "XML accept == Word accept ? OK" in out


def test_validate_warns_about_shells_accepting_would_create(monkeypatch,
                                                            project,
                                                            capsys):
    from docxkit import revision
    write(project.batch, make_parts(
        f'<w:p><m:oMath {NS_M}><w:del w:id="7" w:author="R" '
        f'w:date="2026-08-07T00:00:00Z"><m:r><m:t>x</m:t></m:r>'
        f"</w:del></m:oMath></w:p>"))
    monkeypatch.setattr(
        revision.revisions, "accept",
        lambda xml, **_k: re.sub(r"<w:del\b.*?</w:del>", "", xml,
                                 flags=re.DOTALL))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    assert code == 1
    assert "empty OMML shells" in capsys.readouterr().out


def test_validate_takes_an_explicit_batch_and_baseline(monkeypatch,
                                                       project, tmp_path,
                                                       capsys):
    batch = write(tmp_path / "other.docx", make_parts(para(run("same"))))
    base = write(tmp_path / "base.docx", make_parts(para(run("same"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", str(batch),
                      "--baseline", str(base), "--no-word",
                      "--paper", str(project.root))
    assert code == 0
    assert "other.docx" in capsys.readouterr().out


def test_validate_says_nothing_about_reject_all_with_no_baseline(
        monkeypatch, project, capsys):
    project.prev.unlink()
    write(project.batch, make_parts(para(run("x"))))
    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "reject-all" not in out, \
        "a reject-all verdict was printed with nothing to compare against"


# -------------------------------------------------------------- promote

def test_promote_lands_and_leaves_a_rescue(monkeypatch, project, capsys):
    write(project.batch, make_parts(para(run("the batch"))))
    original = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert project.working.read_bytes() == project.batch.read_bytes()
    assert "rescue copy" in out
    assert "never accepts on their behalf" in out
    # the hash of what landed, so a later "this differs from the batch"
    # is settled by re-hashing rather than by reading paragraphs
    from docxkit.guard import sha256
    assert sha256(project.working)[:16] in out
    # in build/rescue/, NOT beside the manuscript: one file to open is
    # the whole point of this layout
    assert not list(project.working.parent.glob("*rescue*"))
    kept = list(project.rescue_dir.glob("*rescue*"))
    assert kept and kept[0].read_bytes() == original


def test_promote_SAYS_where_the_carried_stamp_landed(monkeypatch, project,
                                                     capsys):
    """`promote` carries a stamped batch's provenance onto the
    manuscript, and the CLI is the only place the author learns it
    happened — `revision.promote` returns the path, but nobody at a
    terminal reads a dataclass.

    It matters because the stamp is what `guard.check` reads next round:
    a paper building with `out=working.docx` (HCW's lane script) was
    passing `force=True` every round to get past a stamp promote had
    never refreshed. The line below is how the author sees that the
    round left the guard in a state that will not need forcing.
    """
    from docxkit import guard

    write(project.batch, make_parts(para(run("the batch"))))
    guard.stamp(project.batch, original="prev.docx", revised="clean.docx",
                base_sha256=guard.sha256(project.prev))

    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "stamp carried beside it" in out
    # the NAME it prints is the file that is actually there, not a
    # cheerful line about a path the report happened to hold
    landed = guard.stamp_path(project.working)
    assert landed.exists() and landed.name in out
    assert guard.check(project.working) is None, \
        "it announced a stamp that still calls the file an author edit"


def test_promote_says_NOTHING_about_a_stamp_when_the_batch_had_none(
        monkeypatch, project, capsys):
    """The other direction, and the reason the line is conditional: an
    unstamped batch (the hand-authored vehicle) leaves nothing to carry,
    and announcing one would name a file that is not there."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("unstamped"))))

    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))

    assert code == 0
    assert "stamp carried" not in capsys.readouterr().out
    assert not guard.stamp_path(project.working).exists()


def test_promote_refuses_a_stale_batch_with_exit_4(monkeypatch, project):
    """The author edited working.docx while the batch was being built."""
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run("the author's own edit"))))
    before = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    assert code == 4
    assert project.working.read_bytes() == before


def test_promote_refuses_while_word_holds_the_file(monkeypatch, project):
    """DocumentLocked is not a protocol refusal: exit 1 with a message."""
    from docxkit import revision
    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setattr(revision.package, "is_locked", lambda _p: True)
    before = project.working.read_bytes()
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    assert isinstance(code, str)
    assert "open in Word" in code
    assert project.working.read_bytes() == before


def test_promote_refuses_a_batch_a_tool_changed_and_names_RESTAMP(
        monkeypatch, project, capsys):
    """Exit 4 with nothing written, and the refusal carries the command
    that clears it — DSI's round needed two private modules instead."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("as built"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    write(project.batch, make_parts(para(run("relinked"))))
    before = project.working.read_bytes()

    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))

    assert code == 4
    assert project.working.read_bytes() == before
    assert "docxkit revision restamp --why" in capsys.readouterr().err


def _changed_since_build(project):
    from docxkit import guard

    write(project.batch, make_parts(para(run("as built"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    write(project.batch, make_parts(para(run("relinked"))))


def test_restamp_records_the_tool_pass_and_promote_then_takes_it(
        monkeypatch, project, capsys):
    from docxkit import guard

    _changed_since_build(project)

    code, _ = run_cli(monkeypatch, "revision", "restamp", "--why",
                      "relink: links only", "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "relink: links only" in out
    assert guard.describes(project.batch) is True
    assert guard.base_of(project.batch) == guard.sha256(project.prev), \
        "the restamp dropped the build's own provenance"
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    assert code == 0


def test_restamp_of_an_UNCHANGED_batch_writes_nothing(monkeypatch, project,
                                                      capsys):
    from docxkit import guard

    write(project.batch, make_parts(para(run("as built"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    before = guard.stamp_path(project.batch).read_bytes()

    code, _ = run_cli(monkeypatch, "revision", "restamp", "--why", "x",
                      "--paper", str(project.root))

    assert code == 0
    assert "nothing to restamp" in capsys.readouterr().out
    assert guard.stamp_path(project.batch).read_bytes() == before


def test_restamp_REFUSES_an_unstamped_batch(monkeypatch, project, capsys):
    """Minting a stamp here would invent a build record — one with no
    baseline in it, which `promote` reads as "cannot tell"."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("hand-authored"))))

    code, _ = run_cli(monkeypatch, "revision", "restamp", "--why", "x",
                      "--paper", str(project.root))

    assert code == 1
    assert "no readable stamp" in capsys.readouterr().out
    assert not guard.stamp_path(project.batch).exists()


def test_restamp_with_no_batch_says_so(monkeypatch, project, capsys):
    code, _ = run_cli(monkeypatch, "revision", "restamp", "--why", "x",
                      "--paper", str(project.root))

    assert code == 3
    assert "no batch to restamp" in capsys.readouterr().out


def test_restamp_without_WHY_is_refused_by_the_parser(monkeypatch, project,
                                                      capsys):
    code, _ = run_cli(monkeypatch, "revision", "restamp",
                      "--paper", str(project.root))

    assert code == 2
    assert "--why" in capsys.readouterr().err


def test_restamp_prints_the_HASH_that_promote_prints_next(monkeypatch,
                                                          project, capsys):
    """`sha256(target)[:16]`, the prefix `promote` and `validate` quote
    too. The restamp line exists so that the next command's line can be
    held against it — "is the manuscript promote just wrote the batch I
    restamped" — and a prefix one character longer or shorter matches
    neither. Nothing read the hash in the line before: the tests above
    assert the reason and the stamp."""
    from docxkit import guard

    _changed_since_build(project)
    expected = guard.sha256(project.batch)[:16]

    run_cli(monkeypatch, "revision", "restamp", "--why", "relink",
            "--paper", str(project.root))
    said = re.findall(r"\(sha256 ([0-9a-f]+)", capsys.readouterr().out)
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    said += re.findall(r"\(sha256 ([0-9a-f]+)", capsys.readouterr().out)

    assert code == 0
    assert said == [expected, expected]


def test_validate_WARNS_that_promote_will_refuse_a_changed_batch(
        monkeypatch, project, capsys):
    """Warned, not failed: every gate reads the bytes that are there, and
    the stamp is promote's question. But a PASS alone, followed by a
    refusal one command later, is the sequence DSI walked into.

    The batch is the baseline's own parts, re-zipped STORED after the
    stamp: other bytes, the same document, so every gate passes and the
    exit code is the stamp's to change — which it must not."""
    import zipfile

    from docxkit import guard, package

    parts = package.read_parts(project.prev)
    write(project.batch, parts)
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    with zipfile.ZipFile(project.batch, "w", zipfile.ZIP_STORED) as z:
        for name, blob in parts.items():
            z.writestr(name, blob)
    assert guard.describes(project.batch) is False

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "== stamp ==" in out and "revision restamp" in out
    assert code == 0


def test_validate_says_NOTHING_about_a_stamp_that_matches(monkeypatch,
                                                          project, capsys):
    from docxkit import guard

    write(project.batch, make_parts(para(run("as built"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))

    run_cli(monkeypatch, "revision", "validate", "--no-word",
            "--paper", str(project.root))

    assert "== stamp ==" not in capsys.readouterr().out


def test_withdraw_puts_the_baseline_back_and_says_where_the_proposal_is(
        monkeypatch, project, capsys):
    from docxkit import guard

    write(project.batch, make_parts(para(run("the proposal"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    run_cli(monkeypatch, "revision", "promote", "--paper", str(project.root))
    capsys.readouterr()

    code, _ = run_cli(monkeypatch, "revision", "withdraw", "--why",
                      "wrong numbers", "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert project.working.read_bytes() == project.prev.read_bytes()
    assert "redlines" in out and "unstaged" in out
    assert str(project.root) not in out, "paths are the project's, relative"


def test_withdraw_says_NOTHING_about_unstaging_a_batch_rebuilt_since(
        monkeypatch, project, capsys):
    """The line names a file that was removed; a rebuilt batch was not,
    and announcing it would send the reader looking for a missing one."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("the proposal"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    run_cli(monkeypatch, "revision", "promote", "--paper", str(project.root))
    write(project.batch, make_parts(para(run("already rebuilt"))))
    capsys.readouterr()

    code, _ = run_cli(monkeypatch, "revision", "withdraw", "--why",
                      "rebuilt first", "--paper", str(project.root))

    assert code == 0
    assert "unstaged" not in capsys.readouterr().out
    assert project.batch.exists()


def test_withdraw_REFUSES_with_nothing_promoted(monkeypatch, project):
    before = project.working.read_bytes()

    code, _ = run_cli(monkeypatch, "revision", "withdraw", "--why", "x",
                      "--paper", str(project.root))

    assert code == 1
    assert project.working.read_bytes() == before


def test_withdraw_without_WHY_is_refused_by_the_parser(monkeypatch, project,
                                                       capsys):
    """`required=True` on withdraw's `--why`, the second of two identical
    lines — `restamp`'s is the first, and its test above says nothing
    about this one. The reason is what the ledger keeps beside the
    hashes, so a withdraw without one is refused before anything moves.
    A proposal IS promoted here: with nothing promoted the command
    refuses anyway, with exit 1, and the flag would never be the reason."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("the proposal"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    run_cli(monkeypatch, "revision", "promote", "--paper", str(project.root))
    proposal = project.working.read_bytes()
    capsys.readouterr()

    code, _ = run_cli(monkeypatch, "revision", "withdraw",
                      "--paper", str(project.root))

    assert code == 2
    assert "--why" in capsys.readouterr().err
    assert project.working.read_bytes() == proposal, "the withdraw ran"


def test_promote_takes_explicit_paths(monkeypatch, project, tmp_path):
    batch = write(tmp_path / "b.docx", make_parts(para(run("explicit"))))
    code, _ = run_cli(monkeypatch, "revision", "promote", str(batch),
                      "--base", str(project.prev),
                      "--paper", str(project.root))
    assert code == 0
    assert project.working.read_bytes() == Path(batch).read_bytes()


# -------------------------------------------------------------- rescues

def _seed(project, n: int):
    from datetime import datetime

    from docxkit import revision
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        p = revision.rescue_path(project, datetime(2026, 8, 7, 10, 0, i))
        p.write_bytes(f"rescue {i}".encode())


def test_rescues_lists_what_promote_left(monkeypatch, project, capsys):
    _seed(project, 3)
    code, _ = run_cli(monkeypatch, "revision", "rescues",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert out.count(f"{project.working.stem}_rescue_") == 3
    assert "keeping 5" in out


def test_rescues_on_a_paper_that_never_promoted(monkeypatch, project,
                                                capsys):
    code, _ = run_cli(monkeypatch, "revision", "rescues",
                      "--paper", str(project.root))
    assert code == 0
    assert "no rescue copies" in capsys.readouterr().out


def test_rescues_prune_to_a_depth(monkeypatch, project, capsys):
    from docxkit import revision
    _seed(project, 6)
    code, _ = run_cli(monkeypatch, "revision", "rescues", "--prune", "2",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "pruned 4, keeping 2" in out
    assert len(revision.rescues(project)) == 2


def test_rescues_bare_prune_removes_all(monkeypatch, project, capsys):
    from docxkit import revision
    _seed(project, 3)
    code, _ = run_cli(monkeypatch, "revision", "rescues", "--prune",
                      "--paper", str(project.root))
    assert code == 0
    assert "keeping 0" in capsys.readouterr().out
    assert revision.rescues(project) == []


def test_promote_reports_what_it_pruned(monkeypatch, project, capsys):
    _seed(project, 6)
    write(project.batch, make_parts(para(run("the batch"))))
    code, _ = run_cli(monkeypatch, "revision", "promote",
                      "--paper", str(project.root))
    out = capsys.readouterr().out
    assert code == 0
    assert "pruned" in out and "older rescue" in out
    # reported relative to the project, not as an absolute path
    assert r"build\rescue" in out or "build/rescue" in out
    assert str(project.root) not in out


def test_doctor_is_quiet_on_a_project_that_agrees(monkeypatch, project,
                                                  capsys):
    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    assert code == 0
    assert "nothing else" in capsys.readouterr().out


def test_doctor_exits_2_and_names_the_line(monkeypatch, project, capsys):
    """A migration can gate on this, and it has to run on a tree that is
    otherwise GREEN — that is the state it exists to break."""
    stale = project.root / "tests" / "helpers.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('PAPER = next(root.glob("Report/le_v*.docx"))\n',
                     encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "tests/helpers.py:1" in out, out
    assert "pattern" in out and "Report/le_v*.docx" in out


def test_doctor_shows_patterns_and_COUNTS_the_literals(monkeypatch, project,
                                                       capsys):
    """AFI's 134 lines are why. The patterns are the dangerous kind and
    they print in full; the literals are counted, with the remedy named,
    because most of them are a spent archive."""
    for n, body in ((1, 'P = next(root.glob("Report/le_v*.docx"))\n'),
                    (2, 'P = "Report/le_v3.docx"\n'),
                    (3, 'P = "Report/le_v4.docx"\n')):
        f = project.root / f"s{n}.py"
        f.write_text(body, encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "1 PATTERN selection(s)" in out, out
    assert "s1.py:1" in out
    assert "2 literal selection(s) not shown" in out, out
    assert "s2.py" not in out, "the literals should be counted, not listed"
    assert "[doctor] skip" in out, "the remedy has to be in the message"


def test_doctor_lists_the_literals_when_asked(monkeypatch, project, capsys):
    (project.root / "s2.py").write_text('P = "Report/le_v3.docx"\n',
                                        encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor", "--literals",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "1 literal selection(s):" in out, out
    assert "s2.py:1" in out


def test_doctor_prints_a_MISSPELT_config_key_in_full_and_FIRST(
        monkeypatch, project, capsys):
    """`rescue_kep = 3` takes the default in silence, and the rescue
    ladder is then a depth nobody set. A key doubt names the line, the
    key and the one it is within a typo of; it prints before the
    patterns and is never counted away like a literal."""
    cfg = project.config
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(
        "rescue_keep = 5", "rescue_kep = 3"), encoding="utf-8")
    (project.root / "s2.py").write_text('P = "Report/le_v3.docx"\n',
                                        encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2
    assert "1 config key(s)" in out, out
    assert "revision/paper.toml:" in out
    assert "rescue_kep" in out and "rescue_keep" in out
    assert out.index("rescue_kep") < out.index("literal selection")


# --- what the cli run of 2026-08-18 found here ---------------------------
#
# `cmd_revision_ingest` was cli.py's largest cluster with 13, and twelve
# of those were the cap on the per-bucket listing — the twelve lines an
# author reads to find out what happened while the batch was away, and
# the count of what did not fit. Nothing here had ever handed it more
# than a handful of changes.


def _reworded(project, n: int) -> None:
    """`n` paragraphs, every one of them changed."""
    write(project.prev, make_parts("".join(
        para(run(f"Original sentence {i}.")) for i in range(n))))
    write(project.working, make_parts("".join(
        para(run(f"Reworded sentence {i}.")) for i in range(n))))


def test_ingest_lists_TWELVE_changes_and_counts_the_rest(monkeypatch,
                                                         project, capsys):
    """Twenty-five reworded paragraphs: twelve are printed and the rest
    are a number. Which number matters — `25 - 12` is 13, and the
    operators that survived in its place read 1, 21, 8, 29 and 0, every
    one of them a plausible count of edits to a paper."""
    _reworded(project, 25)

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "-- text (25)" in out
    assert sum("Original sentence" in ln for ln in out.splitlines()) == 12
    assert "... and 13 more" in out


def test_ingest_counts_NOTHING_extra_under_the_cap(monkeypatch, project,
                                                   capsys):
    """`len(items) > 12`: under the cap there is nothing left over, and
    `!= 12` prints "and -9 more" for a paper with three edits in it."""
    _reworded(project, 3)

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    assert "-- text (3)" in out
    assert sum("Original sentence" in ln for ln in out.splitlines()) == 3
    assert "more" not in out


@pytest.mark.parametrize(("n", "extra"), [(12, ""), (13, "... and 1 more")])
def test_ingest_counts_the_rest_AT_the_cap_and_one_past_it(monkeypatch,
                                                           project, capsys,
                                                           n, extra):
    """Twelve exactly, and thirteen. The pair above proved the cap with
    25 and with 3, where `> 11` and `> 13` agree with `> 12` — a bound
    is invisible at any distance but one. At twelve there is nothing
    left over to count; at thirteen there is exactly one, which is the
    smallest number the line can carry and the one a reader trusts
    least."""
    _reworded(project, n)

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    assert f"-- text ({n})" in out
    assert sum("Original sentence" in ln for ln in out.splitlines()) == 12
    assert ("more" in out) is bool(extra), out
    if extra:
        assert extra in out


def test_an_ingest_line_quotes_TWO_HUNDRED_characters_of_the_change(
        monkeypatch, project, capsys):
    """The width of one line of the report an author reads to find out
    what happened while the batch was away. A paragraph is longer than
    that more often than not, so the cut is on almost every line."""
    long_one = "Original " + "sentence that runs on and on, " * 12
    assert len(long_one) > 201
    write(project.prev, make_parts(para(run(long_one))))
    write(project.working, make_parts(para(run("Reworded."))))

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    (line,) = [ln for ln in out.splitlines() if "word_diff" in ln]
    assert len(line) == 4 + 200, line       # "   " + the space print adds


def test_ingest_names_every_LOST_element_not_just_the_count(monkeypatch,
                                                            project, capsys):
    """The heading says how many; the lines say WHICH, and which is the
    whole of what a person can act on — `revision baseline` refuses
    until each one is restored or named."""
    _ate_a_link(project)

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    lines = out.splitlines()
    at = lines.index("== LOST (1) ==")
    assert "ref_Ritchie2023b" in lines[at + 1], (
        "the anchor is the thing to restore; the heading only counts")
    assert "link" in lines[at + 1], "and what KIND of thing it was"


def test_validate_ABORTS_before_word_on_a_lint_problem(monkeypatch, project,
                                                       capsys):
    """The ladder stops at its first rung on purpose: Word is minutes,
    and a batch that fails lint is a batch to fix, not to open. The
    heading has to say WHICH way round it went — inverted, a clean batch
    reports "0 problem(s)" and a broken one reports "clean" — and the
    lines under it name the problem, because "1 problem(s)" is not
    something a person can fix.

    Edge whitespace with no `xml:space="preserve"` is the shape: Word
    drops the space on save, and two words run together in a sentence
    the author never touched."""
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins(" and more"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 2, out
    assert "== lint == 1 problem(s)" in out
    assert "FAIL: w:t has edge whitespace" in out
    assert "ABORT before Word" in out
    assert "== counts ==" not in out, "it stopped at the first rung"


def test_validate_says_WHICH_structure_the_reject_lost(monkeypatch, project,
                                                       capsys):
    """The fifth arm of gate 5, printed. A batch whose words round-trip
    can still fail it — a move duplicates a table, a moved paragraph
    loses its bookmarks — and none of that is a character, so the line
    has to name the count that moved or the reader is told only that
    something did."""
    write(project.batch, make_parts(
        "<w:tbl><w:tr><w:tc>"
        + para(run("The paper as it stands.")) + "</w:tc></w:tr></w:tbl>"))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 1, out
    assert "NOT fully reviewable" in out
    assert "STRUCTURE tbl: 0 -> 1" in out
    assert "duplicate a table" in out


def test_status_says_when_note_definitions_are_OUT_OF_ORDER(monkeypatch,
                                                            project, capsys):
    """The line a person reads. Everything else about such a file is
    right — it renders, it counts, its text diffs clean — and the next
    `build` reports 81 glyph runs against whichever batch comes after
    the one that appended the note. This is the only place it is cheap
    to say (backlog S1, AFI r4)."""
    notes = ('<w:footnotes><w:footnote w:id="2"><w:p><w:r><w:t>first</w:t>'
             "</w:r></w:p></w:footnote>"
             '<w:footnote w:id="3"><w:p><w:r><w:t>second</w:t>'
             "</w:r></w:p></w:footnote></w:footnotes>")
    body = (para(run("Alpha"), '<w:r><w:footnoteReference w:id="3"/></w:r>')
            + para(run("Beta"), '<w:r><w:footnoteReference w:id="2"/></w:r>'))
    write(project.working, make_parts(body,
                                      extra={"word/footnotes.xml": notes}))

    run_cli(monkeypatch, "revision", "status", "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "footnote definitions are NOT in document order" in out, out
    assert "2, 3" in out
    assert "reads the part as moved" in out


# ----------------------------------------------------------------- ship
#
# The two steps run back to back on every batch and each was paying its
# own Word cold start: 13.5 s + 38.9 s on a one-edit AFI batch, about
# 52 s of 95.


def test_ship_runs_BOTH_halves_in_one_call(monkeypatch, project, capsys):
    from docxkit import revision
    monkeypatch.setattr(revision.tracked, "build", _fake_build())

    code, _ = run_cli(monkeypatch, "revision", "ship",
                      str(project.working), "--paper", str(project.root),
                      "--no-word")

    out = capsys.readouterr().out
    assert "7 revisions" in out, "the build half did not run"
    assert "== lint ==" in out, "the validate half did not run"
    # the exit code is the VALIDATE half's — this batch is a fixture
    # and fails its gates, which is the code a caller should see
    assert code == 1, out


def test_ship_opens_ONE_Word_session_for_the_pair(monkeypatch, project):
    """The whole point. `build` opens one for Compare and its in-Word
    verify, `validate` opens another for the accept it compares against
    the XML — and they run in that order, every time."""
    from docxkit import revision, word
    opened: list[int] = []

    kwargs: list[dict[str, object]] = []

    @contextlib.contextmanager
    def counting(*, fast: bool = True, **kw):
        opened.append(1)
        kwargs.append(kw)
        yield object()

    monkeypatch.setattr(word, "session", counting)
    monkeypatch.setattr(revision.tracked, "build", _fake_build())

    run_cli(monkeypatch, "revision", "ship", str(project.working),
            "--paper", str(project.root), "--no-word")

    assert opened == [1], f"{len(opened)} Word session(s) for one batch"
    # and the ONE session carries the paper's ceiling over both halves
    assert kwargs == [{"deadline": 600.0,
                       "doing": f"{project.name}: build and validate"}]


def test_ship_does_NOT_validate_after_a_failed_build(monkeypatch, project,
                                                     capsys):
    """`validate` defaults to `build/batch.docx`, which after a failed
    build is whatever the PREVIOUS batch left there — so a shell `&&` is
    not what this is, and the stop is the reason it is one command."""
    from docxkit import revision

    def refuses(*a, **kw):
        raise revision.StaleBatch("batch.docx was edited in Word")

    monkeypatch.setattr(revision.tracked, "build", refuses)

    code, _ = run_cli(monkeypatch, "revision", "ship", str(project.working),
                      "--paper", str(project.root), "--no-word")

    assert code != 0
    assert "== lint ==" not in capsys.readouterr().out


def test_ship_stops_on_a_build_that_RETURNS_a_code_too(monkeypatch, project,
                                                       capsys):
    """`build` refuses by raising today. The code path is here because
    a command that starts returning one instead must not quietly become
    "validate whatever is in build/batch.docx"."""
    from docxkit import cli

    monkeypatch.setattr(cli, "cmd_revision_build", lambda args: 4)

    code, _ = run_cli(monkeypatch, "revision", "ship", str(project.working),
                      "--paper", str(project.root), "--no-word")

    assert code == 4
    assert "== lint ==" not in capsys.readouterr().out


def _choices(parser):
    """The subparsers hanging off `parser`, by name."""
    import argparse

    action = next(a for a in parser._actions
                  if isinstance(a, argparse._SubParsersAction))
    return action.choices


def _steps():
    """The real `docxkit revision <step>` parsers, as objects."""
    from docxkit import cli

    return _choices(_choices(cli.build_parser())["revision"])


def _flags(parser) -> set[str]:
    return {o for a in parser._actions for o in a.option_strings
            if o.startswith("--")} - {"--help"}


def _shared_flags() -> set[str]:
    """What the ONE declaration, `_build_args`, puts on a parser."""
    import argparse

    from docxkit import cli

    declared = argparse.ArgumentParser()
    cli._build_args(declared)
    return _flags(declared)


def test_ship_takes_every_flag_BUILD_takes():
    """`ship` runs `build` and delegates to `cmd_revision_build`, which
    reads `args.<flag>` — so a flag on one parser and not the other is
    not a gap, it is an AttributeError on every ship. That is what
    `--allow-stale-baseline` did the day it was added: four tests, and
    it would have been every real run.

    Asked of the REAL parsers. It used to call `_build_args` on two
    fresh parsers and compare them, which is the same function applied
    twice: it could not fail, and the question it names — whether the
    parser a person actually reaches carries those flags — was never
    put (BACKLOG, 2026-09-18).
    """
    steps = _steps()

    assert _flags(steps["build"]) <= _flags(steps["ship"])
    assert "--allow-stale-baseline" in _flags(steps["ship"]), (
        "the flag whose absence from ship was the defect")


def test_the_two_parsers_come_from_ONE_declaration():
    """Not that the lists agree today, but that there is only one list.

    Asked of the parser objects. It read `inspect.getsource(build_parser)`
    until 2026-09-18 and looked for one flag NAME — so a flag declared
    inline on `build` and not on `ship`, which is the drift it exists to
    prevent, passed it: demonstrated by adding `--allow-anything` there
    and watching it stay green.

    `build` carries the shared declaration and `--paper`, which `_rev`
    gives every step, and nothing else. `ship` carries the same plus
    `validate`'s own gate flags, because it is the two commands in one —
    derived from `validate` rather than listed, so a new gate flag does
    not have to be added here as well.
    """
    steps = _steps()
    shared = _shared_flags()
    gates = _flags(steps["validate"]) - {"--paper", "--baseline"}

    assert "--allow-math-resolve" in shared, (
        "the shared declaration is empty or moved — every assertion "
        "below would be vacuous")
    assert _flags(steps["build"]) == shared | {"--paper"}
    assert _flags(steps["ship"]) == shared | gates | {"--paper"}


def test_a_SHARED_flag_means_the_same_thing_on_both_parsers():
    """The half a name comparison cannot see: a second declaration that
    spells a flag the same way and gives it another default, another
    type or another help line. `ship --no-moves` meaning something other
    than `build --no-moves` is a worse failure than its absence, because
    nothing downstream reads as wrong.
    """
    steps = _steps()
    build = {o: a for a in steps["build"]._actions for o in a.option_strings}
    ship = {o: a for a in steps["ship"]._actions for o in a.option_strings}

    def shape(action):
        return (type(action).__name__, action.nargs, action.const,
                action.default, action.type, action.choices, action.help)

    for flag in sorted(_shared_flags()):
        assert shape(build[flag]) == shape(ship[flag]), flag


def test_a_survey_row_says_a_batch_is_STAGED_and_the_file_is_OPEN(tmp_path):
    """Two marks a reader acts on immediately: something is built and
    waiting, and the paper cannot be written to because Word has it.
    Neither was covered, and a row that silently drops them sends the
    author to a paper that is not in the state the row claims."""
    from docxkit import cli
    from docxkit.revision import Survey

    row = cli._survey_row(Survey(config=tmp_path / "revision" / "paper.toml",
                                 paper=None, state=None,
                                 staged=True, locked=True))

    assert "batch staged in build/" in row
    assert "open in Word" in row


def test_a_SECOND_init_names_the_config_it_SAVED(monkeypatch, tmp_path,
                                                 capsys):
    """Re-running init rewrites the keys you gave and keeps a copy of
    what was there. The copy is only useful if its name is said — the
    author is being told "your settings changed" and needs the thing
    that lets them check what they were."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("body"))))
    run_cli(monkeypatch, "revision", "init", str(src),
            "--root", str(tmp_path / "proj"), "--name", "LE")
    capsys.readouterr()

    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"), "--name", "LE7",
                      "--force")

    out = capsys.readouterr().out
    assert code == 0
    assert "updated" in out
    assert "previous config:" in out, out
    assert "_pre_init" in out, out


def test_baseline_hands_BACK_the_row_a_log_it_did_not_scaffold_cannot_take(
        monkeypatch, project, capsys):
    """`log_batch` returns None for a log with no batch table, because
    guessing where a row belongs in the author's own document is how a
    record gets mangled. The round still happened, so the CLI prints the
    row for the author to place — silence here loses it."""
    (project.config.parent / "log.md").write_text(
        "# Revision log\n\nProse, and no table anywhere in it.\n",
        encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "no batch table" in out, out
    assert "record this round by hand" in out, out



def test_validate_says_a_paper_lists_NO_gates_of_its_own(monkeypatch,
                                                         project, capsys):
    """`--run-gates` on a paper whose toml lists none.

    Silence here reads as "they ran and passed". The line exists so that
    a paper nobody has written gates for says so — which is the same
    argument the branch above it makes for listing gates that were NOT
    run: a list of unrun checks is a reminder."""
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    run_cli(monkeypatch, "revision", "validate", "--no-word", "--run-gates",
            "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "none listed in paper.toml" in out, out


def test_baseline_with_NO_LOG_says_nothing_about_the_log(monkeypatch,
                                                         project, capsys):
    """`--no-log` is the author saying they will record the round
    themselves, so neither the logged line nor the hand-it-back refusal
    belongs — and a baseline that quietly logged anyway under a flag
    asking it not to would be the kind of thing nobody checks."""
    code, _ = run_cli(monkeypatch, "revision", "baseline", "--no-log",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "baseline updated" in out
    assert "logged:" not in out
    assert "no batch table" not in out



# ------------------------------------------------------------- redlines

def test_redlines_lists_what_each_batch_PROPOSED(monkeypatch, project,
                                                 capsys):
    """The kept redlines are the only record of what a round offered —
    including what the author rejected, which nothing else holds once
    the manuscript moves on. Listing them with their sizes is how you
    find the one worth opening."""
    project.redline_dir.mkdir(parents=True, exist_ok=True)
    kept = project.redline_dir / (
        f"{project.working.stem}_redline_20260824-140618.docx")
    write(kept, make_parts(para(run("what round one proposed"))))

    code, _ = run_cli(monkeypatch, "revision", "redlines",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert kept.name in out
    assert "never pruned" in out
    assert "1 redline(s)" in out


def test_redlines_on_a_paper_with_NONE_says_why_there_are_none(
        monkeypatch, project, capsys):
    """A paper whose batches all predate the keeping has no redlines and
    is not broken. Silence would read as a failure, and "no redlines"
    alone would read as "your rounds proposed nothing"."""
    code, _ = run_cli(monkeypatch, "revision", "redlines",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0
    assert "no redlines" in out
    assert "predate" in out, "say why, not just that there are none"



def test_a_LOST_part_says_DECLARE_it_rather_than_naming_a_function(
        monkeypatch, project, capsys):
    """`validate` is a protocol command, so the paper has a paper.toml
    and the protocol drives the carry. Pointing at
    `hygiene.restore_parts` sends the reader two floors down: past the
    config that would have done it, into a function they then call by
    hand — and copying the part alone is enough for some parts and not
    others, so the hand-written version works until the day it meets a
    footer and produces one that is present, referenced by nothing, and
    on no page.
    """
    from docxkit import package

    base = package.read_parts(project.prev)
    base["customXml/item1.xml"] = (
        b'<b:Sources xmlns:b="http://schemas.openxmlformats.org'
        b'/officeDocument/2006/bibliography"/>')
    write(project.prev, base)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    run_cli(monkeypatch, "revision", "validate", "--no-word",
            "--paper", str(project.root))

    out = capsys.readouterr().out
    assert "LOST customXml/item1.xml" in out
    assert "[batch] carry" in out, out
    assert "restore_parts" not in out, (
        "the function is the mechanism; the config is the instruction")
    # and WHY the config rather than a copy: the three coordinated edits
    # a hand-written copy leaves out.
    assert "Content-Types" in out and "sectPr" in out, out


def test_ingest_says_when_a_RE_LABEL_left_the_span_UNBALANCED(monkeypatch,
                                                              project,
                                                              capsys):
    """The section's own message is what would send a reader past this:
    "the anchors are intact, nothing is lost, `revision baseline` does
    not refuse". That is right about the anchor and silent about the
    SPAN.

    The author turned a narrative citation parenthetical and Word kept
    the old right-hand boundary, so the link covers a closing bracket
    with no opening one inside the blue. Nothing else can see it — the
    anchor resolves, no character moved — and it is damage wearing a
    re-label's clothes (Aging_Well, 2026-08-25)."""
    write(project.prev, make_parts(para(
        run("As shown "),
        '<w:hyperlink w:anchor="ref_Klim2023">'
        "<w:r><w:t>Klimaviciute and Pestieau (2023)</w:t></w:r>"
        "</w:hyperlink>")))
    write(project.working, make_parts(para(
        run("As shown ("),
        '<w:hyperlink w:anchor="ref_Klim2023">'
        "<w:r><w:t>Klimaviciute and Pestieau 2023)</w:t></w:r>"
        "</w:hyperlink>")))

    code, _ = run_cli(monkeypatch, "revision", "ingest",
                      "--paper", str(project.root))
    out = capsys.readouterr().out

    assert code == 0, out
    assert "== RE-LABELLED (1) ==" in out, out
    assert "UNBALANCED" in out, out
    assert "unmatched ')'" in out, out
    assert "reached past its mention" in out, out


def test_an_ORDINARY_re_label_gets_no_span_warning(monkeypatch, project,
                                                   capsys):
    """The other side, and the one that decides whether the warning is
    worth having: an author editing the visible text of a citation is an
    ordinary edit, and a section that cried damage over one would be a
    section people stop reading."""
    _ate_a_link(project)
    write(project.working, make_parts(para(
        run("see "),
        '<w:hyperlink w:anchor="ref_Ritchie2023b">'
        "<w:r><w:t>Ritchie and Roser (2023b)</w:t></w:r></w:hyperlink>")))

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))
    out = capsys.readouterr().out

    assert "== RE-LABELLED (1) ==" in out, out
    assert "UNBALANCED" not in out, out


def test_validate_at_a_TRUTH_state_says_there_is_nothing_to_validate(
        project, monkeypatch, capsys):
    """A truth state is the NORMAL state of a paper between rounds, and
    there is no `build/batch.docx` in one.

    It used to die with `cannot read …batch.docx: [Errno 2] No such file
    or directory`, which reads as a broken installation or a lost file.
    It cost a real detour: Life_Expectancy's round-2 protocol listed
    `revision validate` as a PRECONDITION to be run green before any
    edit, and the step is not runnable as written — the protocol author
    reasonably assumed a gate ladder could be run on a clean paper.
    """
    assert not project.batch.exists(), "the fixture is at a truth state"
    monkeypatch.chdir(project.root)

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word")

    out = capsys.readouterr().out
    assert code == 3, out
    assert "no batch to validate" in out
    assert "revision status" in out, "and what to run instead"
    assert "Errno" not in out and "Traceback" not in out
    assert "pending revision(s)" in out, "and which state the paper is in"


def test_validate_says_so_when_the_MANUSCRIPT_is_missing_too(
        project, monkeypatch, capsys):
    """No batch AND no working file — `paper.toml` naming a manuscript
    that is not there. Reading the state would raise, so it is not
    read; the answer about the batch is still worth giving, and it is
    the one the reader asked for."""
    project.working.unlink()
    monkeypatch.chdir(project.root)

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word")

    out = capsys.readouterr().out
    assert code == 3, out
    assert "no batch to validate" in out
    assert "pending revision(s)" not in out, "there is nothing to read"
    assert "Errno" not in out and "Traceback" not in out


# --- the whole sweep of 2026-09-15 ------------------------------------
#
# The survey row was cli.py's largest cluster, 30 of 175: its name cut
# and every one of its marks. The rest is free in the same way — the gate
# block the ladder prints, the widths of two hashes, and the namespaces a
# caller builds without a flag in them.


@pytest.mark.parametrize(("name", "shown"), [
    ("Short", "Short"),
    ("N" * 32, "N" * 32),
    ("N" * 33, "N" * 31 + "…"),
])
def test_a_survey_row_cuts_a_name_PAST_thirty_two_and_says_it_did(
        tmp_path, name, shown):
    """`name if len(name) <= 32 else name[:31] + "…"`. A bound is
    invisible at any distance but one, so the cases are a short name,
    thirty-two characters exactly — printed whole — and thirty-three,
    cut to thirty-one and an ellipsis so the column is as wide either
    way. Any other operator in the join raises on the cut, and `==` in
    place of `<=` cuts "Short" to "Short…"."""
    from docxkit.cli import _survey_row
    from docxkit.revision import Survey

    row = _survey_row(Survey(config=tmp_path / name / "revision"
                             / "paper.toml", paper=None, state=None))

    assert row == f"  unreadable {shown:<33}"


def test_a_survey_row_carries_ONLY_the_marks_its_paper_has_earned(project):
    """Every mark on the row is a branch, and each was free in one
    direction: a settled paper printed "0 pending ()" under a flipped
    `is_truth`, "baseline stale: " under a flipped `stale`, and a
    trailing gap under a flipped `error` — rows that look busy for a
    paper with nothing waiting. The pending mark names each part by its
    LAST path segment; the first is `word` for all three of them."""
    from docxkit.cli import _survey_row
    from docxkit.revision import survey

    def row() -> str:
        (only,) = survey([project.config])
        return _survey_row(only)

    assert row() == f"  {'truth':<9} {'Test Paper':<33}"

    write(project.working, make_parts(
        para(run("x"), _ins("added")),
        footnotes=FOOTNOTES.format(body=para(_ins("hidden")))))
    assert row() == (f"  {'PROPOSAL':<9} {'Test Paper':<33}"
                     "   2 pending (1 in document, 1 in footnotes)")

    write(project.working, make_parts(para(run("Accepted, and settled."))))
    assert row() == (f"  {'stale':<9} {'Test Paper':<33}"
                     "   baseline stale: word/document.xml")


def test_status_ALL_with_NOTHING_registered_says_so_and_exits_0(monkeypatch,
                                                               capsys):
    """Nothing registered is nothing waiting: exit 0, and the one line
    that says how the list gets filled. The flipped test surveyed the
    empty list instead, and printed "0 paper(s)" with no advice."""
    code, _ = run_cli(monkeypatch, "revision", "status", "--all")

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith("no papers registered yet (")
    assert "paper(s) ·" not in out


def test_status_ALL_lists_every_registered_paper_ROW_by_row(monkeypatch,
                                                            project, capsys):
    """`status --all` alone is a survey — `all or scan`, where `and`
    wanted a folder as well and fell through to one paper's status with
    no paper to find — and a survey prints its rows. The loop over them
    was free: the count line under it still said "1 paper(s)"."""
    code, _ = run_cli(monkeypatch, "revision", "status", "--all")

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.splitlines()[0] == f"  {'truth':<9} {'Test Paper':<33}"
    assert "  1 paper(s) · " in out
    assert "no papers registered" not in out


def test_status_SCAN_registers_what_it_finds_and_then_surveys_it(
        monkeypatch, project, capsys):
    """`for root in args.scan or []`. `init` registers the paper it
    scaffolds, so the registry is emptied first: the paper on the list
    afterwards is the one the walk found, and a scan that walked nothing
    leaves "no papers registered" behind it."""
    from docxkit.revision import registered, registry_path

    registry_path().write_text("", encoding="utf-8")
    assert registered() == []

    code, _ = run_cli(monkeypatch, "revision", "status",
                      "--scan", str(project.root))

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.splitlines()[0] == f"scanned {project.root}: 1 paper(s)"
    assert f"  {'truth':<9} {'Test Paper':<33}" in out.splitlines()


def test_status_called_with_ONLY_a_paper_answers_for_that_paper(project,
                                                                capsys):
    """`getattr(args, "all", False)`: a namespace a script builds, not the
    parser, carries no `--all`, and no flag is the one-paper question.
    Defaulted to `True`, the same call becomes a survey and dies reading
    `args.scan`, which that namespace does not have either."""
    import argparse

    from docxkit.cli import cmd_revision_status

    code = cmd_revision_status(argparse.Namespace(paper=str(project.root)))

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith(f"{project.name}\n  {project.working}\n"), out


@pytest.mark.parametrize(("n", "shown"), [
    (2, "3, 2"),
    (6, "7, 6, 5, 4, 3, 2"),
    (7, "8, 7, 6, 5, 4, 3 ..."),
])
def test_the_OUT_OF_ORDER_line_names_SIX_ids_and_says_when_there_are_more(
        capsys, n, shown):
    """`ids[:6]` and `" ..." if len(ids) > 6`. The test above has two ids
    and asks only that they appear, so the cut and the ellipsis were both
    free: two, six and seven are the three sides of a bound of six, and
    the WHOLE line is asserted, so an ellipsis where none belongs is a
    failure too."""
    from docxkit.cli import _show_state
    from docxkit.revision import State

    ids = [str(i) for i in range(n + 1, 1, -1)]
    _show_state("working", State(path=Path("working.docx"), by_part={},
                                 by_author={},
                                 notes_unordered={"footnote": ids}))

    (line,) = [ln for ln in capsys.readouterr().out.splitlines()
               if "NOT in document order" in ln]
    assert line == ("      footnote definitions are NOT in document order: "
                    f"{shown} — Word's Compare will rewrite them, and the "
                    "next build reads the part as moved")


def test_an_UNBALANCED_re_label_is_quoted_to_FORTY_EIGHT_characters(
        monkeypatch, project, capsys):
    """`change.now[:48]`. The label a person has to find and repair is
    quoted on the line that says what is wrong with it, and the test
    above uses one shorter than the cut, where every width agrees."""
    label = "Klimaviciute, Pestieau and their many co-authors 2023)"
    assert len(label) > 49
    write(project.prev, make_parts(para(
        run("As shown "),
        '<w:hyperlink w:anchor="ref_Klim2023">'
        "<w:r><w:t>Klimaviciute and Pestieau (2023)</w:t></w:r>"
        "</w:hyperlink>")))
    write(project.working, make_parts(para(
        run("As shown ("),
        '<w:hyperlink w:anchor="ref_Klim2023">'
        f"<w:r><w:t>{label}</w:t></w:r></w:hyperlink>")))

    run_cli(monkeypatch, "revision", "ingest", "--paper", str(project.root))

    assert (f"     ref_Klim2023: {label[:48]!r} carries an unmatched ')'"
            in capsys.readouterr().out.splitlines())


def test_doctor_does_not_count_a_misspelt_KEY_among_the_literals(
        monkeypatch, project, capsys):
    """`d.kind == "literal"`. "key" sorts below "literal", so `<=` in its
    place counts every config-key doubt a second time as a literal
    selection — and the literals are the count a reader is told to
    skim."""
    cfg = project.config
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(
        "rescue_keep = 5", "rescue_kep = 3"), encoding="utf-8")
    (project.root / "s2.py").write_text('P = "Report/le_v3.docx"\n',
                                        encoding="utf-8")

    code, _ = run_cli(monkeypatch, "revision", "doctor",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2, out
    assert "\n1 config key(s)" in out
    assert "\n1 literal selection(s) not shown" in out, out


def test_baseline_ECHOES_each_accepted_loss_and_the_row_it_LOGGED(
        monkeypatch, project, capsys):
    """Two lines an author reads to confirm the round: which losses they
    signed off, one per flag, and the row that went into `log.md`. The
    loop over the first was free, and a flipped `verdict is not None`
    sent a logged round down the branch for a log with no table — telling
    the author to record by hand a row that was already written."""
    _ate_two_links(project)

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--accept-loss", "link:ref_Ritchie2023b",
                      "--accept-loss", "link:ref_Kok2015",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert code == 0, out
    assert [ln for ln in lines if ln.startswith("  accepted loss: ")] == [
        "  accepted loss: link:ref_Ritchie2023b",
        "  accepted loss: link:ref_Kok2015"]
    assert any(ln.startswith("logged: ") for ln in lines), out
    assert "no batch table" not in out


def test_init_writes_the_NAME_it_is_given(monkeypatch, tmp_path):
    """`name=args.name or ""`. Read as `and`, a name given on the command
    line reaches `init` as the empty string, which is "not given": the
    paper is filed under its folder's name instead, and every survey row
    and log heading carries that."""
    from docxkit.revision import load_paper

    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("body"))))

    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"),
                      "--name", "Life Expectancy")

    assert code == 0
    assert load_paper(tmp_path / "proj").name == "Life Expectancy"


def test_init_WORKING_that_SORTS_first_is_still_a_copy(monkeypatch, tmp_path,
                                                       capsys):
    """`adopted = paper.working == source`. The copy in the test above
    lands in `Report/`, which sorts after `LE7.docx`, so `<=` answers it
    the same way; a copy in `Copy/` sorts first, and `<=` calls it the
    manuscript adopted in place — telling the author that the file they
    will go on opening is the one nothing reads any more."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("b"))))

    code, _ = run_cli(monkeypatch, "revision", "init", str(src),
                      "--root", str(tmp_path / "proj"),
                      "--working", "Copy/LE.docx")

    out = capsys.readouterr().out
    assert code == 0, out
    assert "COPIED, not moved" in out
    assert "adopted in place" not in out


def test_a_THIRD_init_names_the_NEWEST_saved_config(monkeypatch, tmp_path,
                                                    capsys):
    """`saved[-1]`, sorted by modification time. The second-init test
    above leaves one saved config, where the first and the last are the
    same file; a third run leaves two, and the one to name is the copy
    this run has just taken."""
    import os

    (tmp_path / "proj").mkdir()
    folder = tmp_path / "proj" / "revision"
    src = write(tmp_path / "proj" / "LE7.docx", make_parts(para(run("body"))))
    base = ["revision", "init", str(src), "--root", str(tmp_path / "proj")]
    run_cli(monkeypatch, *base, "--name", "LE")
    run_cli(monkeypatch, *base, "--name", "LE7", "--force")
    (older,) = folder.glob("paper_pre_init*.toml")
    stamp = older.stat().st_mtime - 3600
    os.utime(older, (stamp, stamp))
    capsys.readouterr()

    code, _ = run_cli(monkeypatch, *base, "--name", "LE8", "--force")

    out = capsys.readouterr().out
    (newest,) = set(folder.glob("paper_pre_init*.toml")) - {older}
    assert code == 0, out
    assert f"  previous config: {newest.name}" in out.splitlines(), out


def test_rescues_PRUNE_names_every_copy_it_removed(monkeypatch, project,
                                                  capsys):
    """The count line said "pruned 4" whether or not the four were named
    above it. They are the undo copies of four promotes, and which ones
    went is what a person checks before trusting the prune."""
    from docxkit import revision

    _seed(project, 6)
    doomed = [p.name for p in revision.rescues(project)[:4]]

    run_cli(monkeypatch, "revision", "rescues", "--prune", "2",
            "--paper", str(project.root))

    lines = capsys.readouterr().out.splitlines()
    assert [ln for ln in lines if ln.startswith("  removed ")] == [
        f"  removed {name}" for name in doomed]


def test_a_NEGATIVE_prune_keeps_none_and_SAYS_none(monkeypatch, project,
                                                  capsys):
    """`max(0, args.prune)`, beside `prune_rescues`, which reads a
    negative depth as zero rather than slicing from the wrong end. The
    line has to report the depth that was applied: "keeping -1" is not a
    number of copies."""
    _seed(project, 3)

    code, _ = run_cli(monkeypatch, "revision", "rescues", "--prune", "-1",
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 0, out
    assert "pruned 3, keeping 0" in out


def test_a_BARE_prune_means_keep_NONE():
    """`const=0`. The bare-prune test above finds every copy gone, which
    a depth of -1 also produces — `prune_rescues` reads it as zero — so
    it is the parser's own value that is asserted: the help says
    "default 0: all"."""
    from docxkit.cli import build_parser

    args = build_parser().parse_args(["revision", "rescues", "--prune"])

    assert args.prune == 0


@pytest.mark.parametrize(("configured", "passed"), [("600", 600.0),
                                                    ("0", None)])
def test_validate_hands_the_papers_WORD_DEADLINE_to_the_ladder(
        monkeypatch, project, capsys, configured, passed):
    """`word_deadline=paper.word_deadline or None`: a ceiling in seconds,
    where 0 is "no ceiling" and `word.session` spells that None. Read as
    `and`, a paper's 600 arrives as None — the one Word session in the
    ladder left unbounded — and its 0 as a deadline of no seconds."""
    from docxkit import revision

    project.config.write_text(project.config.read_text(
        encoding="utf-8").replace("word_deadline = 600",
                                  f"word_deadline = {configured}"),
        encoding="utf-8")
    seen: dict[str, object] = {}
    real = revision.validate

    def spy(*args, **kw):
        seen.update(kw)
        return real(*args, **kw)

    monkeypatch.setattr(revision, "validate", spy)
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    run_cli(monkeypatch, "revision", "validate", "--no-word",
            "--paper", str(project.root))

    assert seen["word_deadline"] == passed, capsys.readouterr().out


def test_the_BASELINE_abort_quotes_SIXTEEN_characters_of_both_hashes(
        monkeypatch, project, capsys):
    """Two prefixes a person compares by eye, so they are as long as each
    other and as every other hash this package prints. The test above
    stamps a hash of zeros, and sixteen zeros read the same as fifteen or
    seventeen to an `in` check; a hash whose digits all differ does
    not."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("an older truth"))))
    guard.stamp(project.batch, base_sha256="0123456789abcdef" * 4)

    run_cli(monkeypatch, "revision", "validate", "--no-word",
            "--paper", str(project.root))

    assert ("   it says it was built on 0123456789abcdef, and prev.docx is "
            f"{guard.sha256(project.prev)[:16]}"
            in capsys.readouterr().out.splitlines())


def test_promote_quotes_SIXTEEN_characters_of_the_landed_hash(monkeypatch,
                                                              project,
                                                              capsys):
    """The promote test above asks that sixteen characters appear, and
    seventeen contain sixteen. The width is the one `validate` prints and
    the one a person re-hashes against."""
    from docxkit.guard import sha256

    write(project.batch, make_parts(para(run("the batch"))))

    run_cli(monkeypatch, "revision", "promote", "--paper", str(project.root))

    out = capsys.readouterr().out
    landed = sha256(project.working)[:16]
    assert f"(sha256 {landed}, the batch's own bytes)" in out, out


def _with_gates(project, *commands: str) -> None:
    """The paper's own `[verify] commands`, as `paper.toml` spells them."""
    listed = ", ".join(json.dumps(command) for command in commands)
    project.config.write_text(project.config.read_text(
        encoding="utf-8").replace("commands = []", f"commands = [{listed}]"),
        encoding="utf-8")


def _fake_gates(monkeypatch, *results) -> None:
    """`run_gates`, replaced: each result announced and then yielded, as
    the real one streams them."""
    from docxkit import revision

    def run_gates(paper, *, timeout, progress=None):
        for result in results:
            if progress is not None:
                progress(f"gate: {result.command}")
            yield result

    monkeypatch.setattr(revision, "run_gates", run_gates)


def test_run_gates_prints_each_VERDICT_and_the_output_of_ONLY_the_failures(
        monkeypatch, project, capsys):
    """The block a person reads when `--run-gates` goes red, whole. Three
    gates with the failure in the middle, so every decision in it shows:
    the loop over what ran (nothing, under `for gate in []`), whose
    output is printed (the passing gates' chatter, under `not gate.ok`),
    and the count of failures — two passes and one failure, because with
    one of each `sum(1 for ... if gate.ok)` counts the same 1."""
    from docxkit.revision import GateResult

    _with_gates(project, "gate one", "gate two", "gate three")
    _fake_gates(monkeypatch,
                GateResult("gate one", 0, 1.5, "passing chatter"),
                GateResult("gate two", 3, 2.0,
                           "Traceback\nAssertionError: 41 != 42"),
                GateResult("gate three", 0, 0.5, "more chatter"))
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins("and more"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      "--run-gates", "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 5, out
    assert out[out.index("== the paper's own gates =="):].splitlines() == [
        "== the paper's own gates ==  3, from the project root",
        "   · gate one",
        "     [pass] 1.5s",
        "   · gate two",
        "     [FAIL (3)] 2.0s",
        "        Traceback",
        "        AssertionError: 41 != 42",
        "   · gate three",
        "     [pass] 0.5s",
        "",
        "1 of 3 of the paper's gates failed.",
        "",
        "VERDICT: FAIL",
    ], out


def test_the_gate_HEARTBEAT_is_flushed_as_it_is_printed(monkeypatch,
                                                        project):
    """`flush=True`. Through a pipe stdout is block-buffered, and a
    heartbeat printed but not flushed arrives with everything else when
    the suite ends — the twelve silent minutes it was added to end. So
    the console here records what it held at each flush, and the
    heartbeat has to be the last thing in one of them."""
    import argparse
    import io

    from docxkit.cli import _paper_gates
    from docxkit.revision import GateResult, ValidateReport

    class Console(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.flushed: list[str] = []

        def flush(self) -> None:
            self.flushed.append(self.getvalue())
            super().flush()

    _with_gates(project, "python -m pytest")
    _fake_gates(monkeypatch, GateResult("python -m pytest", 0, 720.0, ""))
    console = Console()
    monkeypatch.setattr("sys.stdout", console)

    _paper_gates(argparse.Namespace(paper=str(project.root), run_gates=True,
                                    gate_timeout=900.0),
                 ValidateReport(path=project.batch, baseline=None))

    assert any(held.endswith("   · python -m pytest\n")
               for held in console.flushed), console.flushed


def test_a_namespace_that_does_not_ASK_to_run_gates_runs_none(project,
                                                              capsys):
    """`getattr(args, "run_gates", False)`, three times over. A caller that
    builds its own namespace and says nothing about gates has not asked
    for them: a paper that lists none gets silence rather than "none
    listed", a paper that lists some gets the reminder rather than a run,
    and an aborted ladder says nothing about gates nobody wanted.
    Defaulted to `True`, the second call reaches for a timeout the
    namespace never had."""
    import argparse

    from docxkit.cli import _paper_gates, _skipped_gates
    from docxkit.revision import ValidateReport

    bare = argparse.Namespace(paper=str(project.root))
    report = ValidateReport(path=project.batch, baseline=None)

    _paper_gates(bare, report)
    assert capsys.readouterr().out == ""

    _with_gates(project, "python scripts/verify_tables.py")
    _paper_gates(bare, report)
    assert capsys.readouterr().out == (
        "\n== the paper's own gates ==  1 listed, NOT run (--run-gates)\n"
        "   · python scripts/verify_tables.py\n")

    assert _skipped_gates(bare, 2) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("asked", [False, True])
def test_an_ABORTED_ladder_mentions_the_gates_only_when_they_were_ASKED_for(
        monkeypatch, project, capsys, asked):
    """`run_gates and paper.gates`. A paper with gates of its own whose
    ladder aborts says they did not run only when the run asked for them:
    `or` says it on every abort, and `not` says it exactly when nobody
    asked."""
    _with_gates(project, "python scripts/verify_tables.py")
    write(project.batch, make_parts(
        para(run("The paper as it stands."), _ins(" and more"))))

    code, _ = run_cli(monkeypatch, "revision", "validate", "--no-word",
                      *(["--run-gates"] if asked else []),
                      "--paper", str(project.root))

    out = capsys.readouterr().out
    assert code == 2, out
    assert ("NOT run: the ladder aborted above" in out) is asked, out


def test_ship_stops_on_a_NEGATIVE_build_code_as_well(monkeypatch, project,
                                                    capsys):
    """`!= 0`, not `> 0`. The test above returns 4; any code that is not
    a success stops the ship, and a negative one read through `> 0`
    would go on to validate whatever the previous batch left in
    build/."""
    from docxkit import cli

    monkeypatch.setattr(cli, "cmd_revision_build", lambda args: -1)

    code, _ = run_cli(monkeypatch, "revision", "ship", str(project.working),
                      "--paper", str(project.root), "--no-word")

    assert code == -1
    assert "== lint ==" not in capsys.readouterr().out


def test_a_glyph_difference_is_EXCUSED_only_when_the_report_says_so(capsys):
    """`getattr(report, "glyph_math_only", False)`. The excuse is the
    report's own claim, read off it; a report that makes no claim about
    maths gets its GLYPH lines and nothing to explain them away."""
    from types import SimpleNamespace

    from docxkit.cli import _say_glyphs

    _say_glyphs(SimpleNamespace(glyph_diff=["U+2212 -> U+002D"]))

    assert capsys.readouterr().out == (
        "   GLYPH (reject-all vs baseline) U+2212 -> U+002D\n")


@pytest.mark.parametrize("verb", ["validate", "ship"])
def test_the_GATE_TIMEOUT_defaults_to_run_gates_own(verb):
    """`default=900` on both parsers, restated from `run_gates`, which is
    what a caller outside the CLI gets. The help says "default 900", and
    a parser that drifted from the function would give a CLI run a
    different bound from a script's."""
    import inspect

    from docxkit.cli import build_parser
    from docxkit.revision import run_gates

    argv = ["revision", verb, *(["revised.docx"] if verb == "ship" else [])]

    args = build_parser().parse_args(argv)

    assert args.gate_timeout == \
        inspect.signature(run_gates).parameters["timeout"].default == 900
