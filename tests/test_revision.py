"""The single-file revision protocol.

The tests that matter here are the REFUSALS. Everything this module
does that is worth having is a thing it declines to do: build on a
baseline the author has not adjudicated, ship equations Word baked in
unreviewably, promote onto a file that moved underneath it. Each of
those failed silently in the papers this was ported from — the batch is
produced, it looks finished, and what it cost is discovered later or
not at all. So the assertions are on the FILE and the exception type,
never on the message.

Word is faked at the module attribute `revision._word`, the same seam
tracked.py uses, because none of the decisions under test need a real
Word to be wrong.
"""
from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    NS,
    comment,
    document,
    make_parts,
    note,
    notes,
    para,
    run,
    write,
)

from docxkit import package, revision
from docxkit.errors import (
    BaselinePending,
    DocumentLocked,
    HandbackLoss,
    MathResolved,
    ProtocolError,
    StaleBatch,
)
from docxkit.revision import (
    _link_changes,
    _selects_declared,
    _set_key,
    glyph_runs,
    losses,
    moved_footnotes,
)

NS_M = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'


def ins(text: str, rid: int = 90, author: str = "Revision") -> str:
    return (f'<w:ins w:id="{rid}" w:author="{author}" '
            f'w:date="2026-08-07T00:00:00Z">{run(text)}</w:ins>')


def dele(text: str, rid: int = 91, author: str = "Revision") -> str:
    return (f'<w:del w:id="{rid}" w:author="{author}" '
            f'w:date="2026-08-07T00:00:00Z">'
            f"<w:r><w:delText>{text}</w:delText></w:r></w:del>")


def footnotes_part(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
        f'<w:footnote w:id="2">{body}</w:footnote></w:footnotes>')


@pytest.fixture
def project(tmp_path):
    """A migrated paper: the author's own file, an identical prev.docx,
    config. The manuscript sits IN the project and keeps its name —
    `init` adopts it in place and copies nothing."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "manuscript.docx",
                make_parts(para(run("The paper as it stands."))))
    return revision.init(tmp_path / "proj", src, name="Test Paper",
                         author="Agent", attic=tmp_path / "attic")


# ------------------------------------------------------------ config

def test_init_adopts_the_manuscript_IN_PLACE(tmp_path):
    """The author's file IS the working file: same name, same folder.

    The first shape of this protocol copied every paper to
    `revision/working.docx`, and with nine papers on it nothing in
    Explorer or the Word title bar said which project was open (author,
    2026-08-23). The copy also outlived its purpose — the original was
    never read again, and retiring it was a step nobody performed.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    src = Path(write(proj / "ps5_r2.docx", make_parts(para(run("body")))))
    paper = revision.init(proj, src)

    assert paper.working == src, "the manuscript was copied, not adopted"
    assert src.exists()
    assert list(proj.glob("*.docx")) == [src], "a second copy was made"
    assert not (proj / "revision" / "working.docx").exists()
    # and the config says so, relative to the root so the project stays
    # movable
    assert 'working  = "ps5_r2.docx"' in \
        paper.config.read_text(encoding="utf-8")
    # the baseline is seeded from the same bytes: at migration time the
    # manuscript IS the last accepted truth
    assert paper.prev.read_bytes() == src.read_bytes()
    for sub in ("build", "notes", "scripts/applied"):
        assert (paper.root / "revision" / sub).is_dir()
    log = (paper.root / "revision" / "log.md").read_text(encoding="utf-8")
    # the migration row carries the manuscript's digest, eight hex
    # characters of it — enough to tell two builds apart by eye, short
    # enough to sit in a table cell a person reads
    import hashlib
    full = hashlib.sha256(paper.working.read_bytes()).hexdigest().upper()
    assert f"`{full[:8]}`" in log, log


# --- init and its config writer: the sweep's survivors (2026-09-14) -----


def test_set_key_rewrites_a_value_that_merely_CONTAINS_a_bracket():
    """Only a value that opens more brackets than it closes spans lines; a
    name with a closing bracket in it is a scalar like any other."""
    text = '[paper]\nname = "Draft v2]"\n'

    assert revision._set_key(text, "paper", "name", '"Final"') == (
        '[paper]\nname = "Final"\n')


def test_set_key_appends_a_missing_section_after_exactly_ONE_blank_line():
    for body in ('[paper]\nname = "x"\n', '[paper]\nname = "x"\n\n',
                 '[paper]\nname = "x"'):
        assert revision._set_key(body, "attic", "path", '"D:/a"') == (
            '[paper]\nname = "x"\n\n[attic]\npath = "D:/a"\n'), repr(body)


def test_set_key_under_a_header_that_ENDS_the_file_starts_a_new_line():
    """A section cut back by hand to its header, with no Enter after it,
    leaves the config ending on `[attic]` with no newline, and a key
    inserted after that line joined it: `[attic]path = "D:/a"`, which TOML
    refuses, so every later `revision` command fails to read its config.
    The missing-SECTION branch above already allowed for such a file."""
    for body in ('[paper]\nname = "x"\n[attic]', "[attic]"):
        assert revision._set_key(body, "attic", "path", '"D:/a"') == (
            body + '\npath = "D:/a"\n'), repr(body)


def test_set_key_keeps_the_COMMENT_after_an_unquoted_value():
    text = "[batch]\nrescue_keep = 5  # newest first\n"

    assert revision._set_key(text, "batch", "rescue_keep", "7") == (
        "[batch]\nrescue_keep = 7  # newest first\n")


def test_init_naming_the_manuscripts_OWN_path_copies_nothing_even_forced(
        tmp_path):
    """Copying a file onto itself raises rather than doing nothing, which is
    why `init` compares the two paths by value before it copies."""
    (tmp_path / "proj").mkdir()
    src = Path(write(tmp_path / "proj" / "manuscript.docx",
                     make_parts(para(run("The paper.")))))

    paper = revision.init(tmp_path / "proj", src, working="manuscript.docx",
                          force=True)

    assert paper.working.resolve() == src.resolve()


def test_init_copies_to_a_working_path_in_a_NEW_folder_that_sorts_first(
        tmp_path):
    """`working=` names where the copy goes, folders and all — here a path
    that sorts before the source's, which an ordering test would take for
    the source itself."""
    (tmp_path / "proj").mkdir()
    src = Path(write(tmp_path / "proj" / "manuscript.docx",
                     make_parts(para(run("The paper.")))))

    paper = revision.init(tmp_path / "proj", src, working="a/new/copy.docx")

    assert paper.working.read_bytes() == src.read_bytes()


def test_a_FORCED_init_writes_an_attic_it_is_given_and_none_it_is_not(
        tmp_path):
    from docxkit.revision._init import _toml_str

    (tmp_path / "proj").mkdir()
    src = Path(write(tmp_path / "proj" / "manuscript.docx",
                     make_parts(para(run("The paper.")))))
    config = revision.init(tmp_path / "proj", src).config

    revision.init(tmp_path / "proj", src, force=True)
    assert "None" not in config.read_text(encoding="utf-8")

    attic = tmp_path / "attic"
    revision.init(tmp_path / "proj", src, force=True, attic=attic)
    assert f"path = {_toml_str(str(attic))}" in config.read_text(
        encoding="utf-8")


def test_the_log_NAMES_the_paper_and_pads_its_path_column_to_26(tmp_path):
    """A given name, not the folder's, and the folder's when none is given;
    the path column filled to 26 characters, and one space at the least
    after a path longer than that."""
    heads = []
    for folder, rel, name in (("short_root", "working.docx", "Short Paper"),
                              ("long", "manuscripts/the_long_manuscript.docx",
                               "")):
        source = tmp_path / folder / rel
        source.parent.mkdir(parents=True)
        write(source, make_parts(para(run("The paper."))))
        paper = revision.init(tmp_path / folder, source, name=name)
        log = (paper.root / "revision" / "log.md").read_text(
            encoding="utf-8").splitlines()
        heads += [log[0], next(ln for ln in log if "THE paper" in ln)]

    assert heads == [
        "# Short Paper — revision log",
        "    working.docx" + " " * 14
        + "THE paper — your file, your name, edited in place",
        "# long — revision log",
        "    manuscripts/the_long_manuscript.docx "
        "THE paper — your file, your name, edited in place"]


def test_init_refuses_to_overwrite_a_live_configuration(project):
    with pytest.raises(ProtocolError):
        revision.init(project.root, project.working)


def test_init_missing_manuscript(tmp_path):
    with pytest.raises(ProtocolError):
        revision.init(tmp_path / "proj", tmp_path / "nope.docx")


def test_init_can_be_given_a_name_and_then_it_COPIES(tmp_path):
    """`working=`: the author asked for the manuscript somewhere else.

    That is the old migration shape, and it now has to be asked for —
    the source is left where it was and nothing reads it again, which
    the CLI says out loud.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    src = Path(write(proj / "draft.docx", make_parts(para(run("body")))))

    paper = revision.init(proj, src, working="Report/HCW.docx")

    assert paper.working == proj / "Report" / "HCW.docx"
    assert paper.working.read_bytes() == src.read_bytes()
    assert src.exists(), "the source was moved, not copied"
    assert 'working  = "Report/HCW.docx"' in \
        paper.config.read_text(encoding="utf-8")


def _lived_in(paper) -> None:
    """Everything a paper accumulates that `init` never put there."""
    cfg = paper.config
    text = cfg.read_text(encoding="utf-8").replace(
        "commands = []",
        'commands = [\n  "pytest tests/",   # the acceptance suite\n'
        '  "python scripts/qa_links.py",\n]')
    text = text.replace(
        f"rescue_keep = {revision.RESCUE_KEEP}",
        f'rescue_keep = {revision.RESCUE_KEEP}\n'
        f'carry = ["word/footer3.xml"]', 1)
    text += ('\n[doctor]\nskip = ["v8_restructure"]\n'
             '\n[git]\nrepo = ""   # NOT under version control: the attic\n'
             "            # is this paper's only history\n")
    cfg.write_text(text, encoding="utf-8")
    log = paper.root / "revision" / "log.md"
    log.write_text(log.read_text(encoding="utf-8")
                   + "| 2026-08-20 | R14 | 31 revs | green | accepted |\n",
                   encoding="utf-8")


def test_init_FORCE_keeps_everything_the_paper_declared(tmp_path):
    """`--force` is reached for when a config needs correcting, which is
    exactly when the rest of it has to survive.

    It used to rewrite the config from the template, the log from the
    template and prev.docx from the live file. Measured 2026-08-23 on a
    paper with two rounds behind it: the batch table went 3 rows -> 1,
    the baseline was re-seeded to the CURRENT manuscript, and the config
    came back with `commands = []` and no `[doctor]` at all — exit 0, no
    warning, no backup. Every live paper carried something the template
    cannot express, and Aging_Well's `carry = ["word/footer3.xml"]` is
    the fix for a promote that once shipped a manuscript without its
    sensitivity label.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    src = Path(write(proj / "HCW_v14.docx", make_parts(para(run("body")))))
    paper = revision.init(proj, src, author="Revision Agent")
    _lived_in(paper)
    # the live file moves on, so a re-seeded baseline would be visible
    write(src, make_parts(para(run("two rounds later"))))
    before_log = (proj / "revision" / "log.md").read_text(encoding="utf-8")
    before_prev = paper.prev.read_bytes()

    again = revision.init(proj, src, name="Renamed", force=True)

    text = again.config.read_text(encoding="utf-8")
    assert again.carry == ("word/footer3.xml",), text
    assert again.gates == ("pytest tests/", "python scripts/qa_links.py")
    assert again.doctor_skip == ("v8_restructure",)
    assert "[git]" in text and "only history" in text, "a section was dropped"
    assert "# the acceptance suite" in text, "a comment was dropped"
    # what was asked for DID change, and what was not did not
    assert again.name == "Renamed"
    assert again.author == "Revision Agent", "an unpassed default overwrote it"
    # the paper's history and its baseline are not this function's to reset
    assert (proj / "revision" / "log.md").read_text(encoding="utf-8") \
        == before_log
    assert again.prev.read_bytes() == before_prev
    # and the config it replaced is beside it
    assert list((proj / "revision").glob("paper_pre_init*.toml"))


def test_init_FORCE_repoints_the_manuscript(tmp_path):
    """The reason to force a re-init: the paper moved or was renamed."""
    proj = tmp_path / "proj"
    (proj / "Report").mkdir(parents=True)
    src = Path(write(proj / "old.docx", make_parts(para(run("body")))))
    revision.init(proj, src)
    moved = proj / "Report" / "HCW_v15.docx"
    src.rename(moved)

    again = revision.init(proj, moved, force=True)

    assert again.working == moved
    assert 'working  = "Report/HCW_v15.docx"' in \
        again.config.read_text(encoding="utf-8")


def test_a_key_the_config_does_not_have_yet_is_INSERTED():
    """A config predating a key still has to receive it: `_set_key`
    inserts under the section header rather than reporting success and
    writing nothing."""
    text = '[paper]\nname = "P"\n\n[batch]\nauthor = "A"\n'

    out = _set_key(text, "paper", "working", '"Report/P.docx"')

    assert 'working = "Report/P.docx"' in out
    # INSIDE [paper]: before the next header is not enough — inserting
    # at the header index puts the key above `[paper]`, in no section at
    # all, and "before [batch]" is still true of that. A mutant did
    # exactly this and survived.
    assert out.index("[paper]") < out.index("working") < out.index("[batch]")
    assert 'name = "P"' in out and 'author = "A"' in out
    import tomllib
    assert tomllib.loads(out)["paper"]["working"] == "Report/P.docx", \
        "the key has to be READ BACK from the section it was meant for"


def test_the_SAME_key_in_another_section_is_left_alone():
        """`if current != section: continue`. Without it the first
        matching key anywhere in the file is rewritten — and `path`
        lives in `[attic]` while a paper's own tooling may keep one
        under a section of its own. Dropping the scope survived every
        test until this one, because none had a name in two places."""
        text = ('[analysis]\npath = "Programs"\n\n'
                '[attic]\npath = "D:/old"\n')

        out = _set_key(text, "attic", "path", '"D:/PaperAttic/P"')

        import tomllib
        parsed = tomllib.loads(out)
        assert parsed["attic"]["path"] == "D:/PaperAttic/P"
        assert parsed["analysis"]["path"] == "Programs", \
            "the other section's key was rewritten"


def test_a_section_the_config_does_not_have_yet_is_APPENDED():
    out = _set_key('[paper]\nname = "P"\n', "attic", "path", '"D:/A"')

    assert out.startswith('[paper]\nname = "P"\n')
    assert out.rstrip().endswith('[attic]\npath = "D:/A"')


def test_the_comment_on_a_rewritten_key_SURVIVES():
    """These lines explain themselves, and the explanation is as much
    the file's content as the value is."""
    text = '[paper]\nworking  = "old.docx"   # THE paper; edited here only\n'

    out = _set_key(text, "paper", "working", '"new.docx"')

    assert "# THE paper; edited here only" in out
    assert '"old.docx"' not in out


def test_a_HASH_inside_the_value_is_not_read_as_a_comment():
    text = '[paper]\nname = "R#3 draft"\n'

    out = _set_key(text, "paper", "language", '"ru"')

    assert '"R#3 draft"' in out, out


def test_a_MULTI_LINE_value_is_refused_rather_than_mangled():
    """The one array in the template belongs to the paper. Rewriting its
    first line would leave the rest dangling as TOML nothing can parse,
    and a config that no longer loads is worse than one not updated."""
    text = '[verify]\ncommands = [\n  "pytest",\n]\n'

    with pytest.raises(ProtocolError, match="spans several lines"):
        _set_key(text, "verify", "commands", '"x"')


def test_init_refuses_a_manuscript_OUTSIDE_the_project(tmp_path):
    """Adopting in place means the paper is in the project: every
    command finds `paper.toml` by walking up from where it is started,
    including from the manuscript itself."""
    src = Path(write(tmp_path / "loose.docx", make_parts(para(run("b")))))

    with pytest.raises(ProtocolError, match="not inside"):
        revision.init(tmp_path / "proj", src)

    # and naming a destination inside the project is the way through
    paper = revision.init(tmp_path / "proj", src, working="paper.docx")
    assert paper.working == (tmp_path / "proj" / "paper.docx")


def test_config_is_found_from_anywhere_below(project):
    """The agent's cwd during a batch is rarely the project root."""
    deep = project.root / "revision" / "scripts" / "applied"
    assert revision.load_paper(deep).working == project.working
    assert revision.load_paper(project.root / "revision").working \
        == project.working
    # and from a FILE path, not only a directory
    assert revision.load_paper(project.working).root == project.root


def test_config_not_found_says_what_to_do(tmp_path):
    with pytest.raises(ProtocolError, match="init"):
        revision.find_config(tmp_path)


def test_paper_reads_its_own_end_of_the_protocol(project):
    assert project.name == "Test Paper"
    assert project.author == "Agent"
    assert project.batch == project.build_dir / "batch.docx"
    assert project.attic is not None


def test_paper_falls_back_when_the_config_is_bare(tmp_path):
    """A hand-written paper.toml need not repeat every default."""
    folder = tmp_path / "proj" / "revision"
    folder.mkdir(parents=True)
    (folder / "paper.toml").write_text("[paper]\n", encoding="utf-8")
    paper = revision.load_paper(tmp_path / "proj")
    assert paper.working.name == "working.docx"
    assert paper.prev.name == "prev.docx"
    assert paper.author == "Revision"
    assert paper.gates == ()
    assert paper.attic is None
    assert paper.render_math is True, "a paper that says nothing renders"


def test_a_paper_can_turn_the_equation_render_OFF(project):
    """`[verify] render_math = false` — the scaffold writes the key
    with its default, so the switch is in front of whoever reads the
    config, and a config from before the key existed still renders."""
    text = project.config.read_text(encoding="utf-8")
    assert "render_math = true" in text, "the scaffold names the default"

    project.config.write_text(
        text.replace("render_math = true", "render_math = false"),
        encoding="utf-8")

    assert revision.load_paper(project.root).render_math is False


def test_the_config_reader_refuses_a_key_KNOWN_does_not_list():
    """The gate's own instrument. `doctor` measures a config key against
    `KNOWN`; if `load_paper` could read a key the table does not list,
    a typo of THAT key would be invisible. So every read goes through
    `_read`, which raises on an undeclared one — the table cannot fall
    behind the code, because the suite loads a paper on every run."""
    from docxkit.revision._config import KNOWN, _read

    assert _read({"batch": {"author": "A"}}, "batch", "author", "x") == "A"
    assert _read({}, "batch", "author", "x") == "x"
    assert _read({"batch": {}}, "batch", "carry", ()) == ()
    with pytest.raises(KeyError, match="KNOWN"):
        _read({"batch": {"rescue_kep": 3}}, "batch", "rescue_kep", 5)
    # the thirteen keys the protocol reads — ten measured 2026-09-03
    # against the 29 the nine registered papers carry, plus
    # `word_deadline` the same evening, `[paper] timings` on
    # 2026-09-07, which turns protocol step recording off for a tree
    # that must stay exactly as declared (a replication package), and
    # `[verify] render_math` on 2026-09-11, the opt-out from rendering
    # the pages of the equations a batch adds or changes
    assert sum(len(keys) for keys in KNOWN.values()) == 13


def test_word_deadline_is_read_from_batch_and_defaults_to_TEN_MINUTES(
        tmp_path, project):
    assert project.word_deadline == 600.0
    text = project.config.read_text(encoding="utf-8")
    assert "word_deadline = 600" in text, "the template documents the key"
    folder = tmp_path / "bare" / "revision"
    folder.mkdir(parents=True)
    (folder / "paper.toml").write_text("[batch]\nword_deadline = 0\n",
                                       encoding="utf-8")
    assert revision.load_paper(tmp_path / "bare").word_deadline == 0.0


def test_init_without_an_attic_declares_NONE_not_a_drive_letter(tmp_path):
    """The template wrote `D:\\PaperAttic\\<name>` for a paper given no
    attic — one machine's drive letter, shipped as everyone's default
    (review 2026-09-03, row 9). An attic is the paper's to name; left
    unnamed, `doctor` skips nothing extra, and the section stays in the
    file so naming it later is a one-line edit under a header that is
    already there."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "m.docx", make_parts(para(run("x"))))

    paper = revision.init(tmp_path / "proj", src)

    assert paper.attic is None
    text = paper.config.read_text(encoding="utf-8")
    assert "D:" not in text
    assert "[attic]" in text
    later = revision._set_key(text, "attic", "path", '"E:/attic"')
    assert '[attic]\npath = "E:/attic"' in later
    paper.config.write_text(later, encoding="utf-8")
    assert revision.load_paper(paper.root).attic == Path("E:/attic")


# ------------------------------------------------------------- state

def test_state_reads_truth_and_proposal(tmp_path):
    clean = write(tmp_path / "clean.docx",
                  make_parts(para(run("settled text"))))
    assert revision.state(clean).is_truth
    assert revision.state(clean).label == "truth"

    proposed = write(tmp_path / "proposed.docx", make_parts(
        para(run("settled "), ins("new"), dele("old"))))
    st = revision.state(proposed)
    assert not st.is_truth
    assert st.pending == 2
    assert st.label == "proposal"
    assert st.by_author == {"Revision": 2}


def test_state_counts_footnotes_the_author_cannot_see(tmp_path):
    """The body-only count is what makes a proposal look like the truth.

    Review > Next walks the body; Simple Markup and No Markup hide
    footnote balloons entirely. A revision left in a footnote is
    invisible from the author's chair and still makes the file a
    proposal — so a count that reads document.xml alone reports "truth"
    and lets the next Compare flatten it into plain text.
    """
    path = write(tmp_path / "fn.docx", make_parts(
        para(run("body text with no revisions at all")),
        footnotes=footnotes_part(para(run("note "), ins("added")))))

    st = revision.state(path)
    assert st.pending == 1, "a footnote revision was not counted"
    assert not st.is_truth
    assert st.hidden == 1
    assert "word/footnotes.xml" in st.by_part
    assert "word/document.xml" not in st.by_part


def test_hidden_excludes_the_body(tmp_path):
    path = write(tmp_path / "body.docx",
                 make_parts(para(run("x "), ins("y"))))
    st = revision.state(path)
    assert st.pending == 1
    assert st.hidden == 0, "a body revision is reachable, not hidden"


# ------------------------------------------------------------ ingest

def test_ingest_is_read_only(project):
    """Safe to run before every task without asking — that is the point."""
    before = project.working.read_bytes()
    prev_before = project.prev.read_bytes()
    revision.ingest(project.working, project.prev)
    assert project.working.read_bytes() == before
    assert project.prev.read_bytes() == prev_before


def test_ingest_sees_nothing_when_nothing_changed(project):
    report = revision.ingest(project.working, project.prev)
    assert report.untouched
    assert not report.changed_parts


def test_ingest_reports_the_authors_text_edit(project):
    write(project.working, make_parts(
        para(run("The paper as the author now wants it."))))
    report = revision.ingest(project.working, project.prev)
    assert not report.untouched
    assert report.working_state is not None
    assert report.working_state.is_truth


def test_ingest_flags_a_style_level_edit(project):
    """A style edit changes every paragraph using it, so a batch that
    rebuilds paragraphs can undo far more than it appears to touch."""
    parts = make_parts(para(run("The paper as it stands.")))
    parts["word/styles.xml"] = b"<w:styles><w:style w:styleId='A'/></w:styles>"
    write(project.prev, parts)
    changed = dict(parts)
    changed["word/styles.xml"] = (
        b"<w:styles><w:style w:styleId='B'/></w:styles>")
    write(project.working, changed)

    report = revision.ingest(project.working, project.prev)
    assert report.style_edit


def test_a_STYLE_only_edit_is_not_untouched_and_a_TEXT_edit_no_style_edit(
        project):
    """`untouched` wants no content change AND no changed part, and a
    styles.xml edit is the second without the first. `style_edit` is a
    property: as a plain method it would read true of every report
    (mutation sweep, 2026-09-14)."""
    parts = make_parts(para(run("The paper as it stands.")))
    parts["word/styles.xml"] = b"<w:styles><w:style w:styleId='A'/></w:styles>"
    write(project.prev, parts)
    restyled = dict(parts)
    restyled["word/styles.xml"] = (
        b"<w:styles><w:style w:styleId='B'/></w:styles>")
    write(project.working, restyled)

    assert not revision.ingest(project.working, project.prev).untouched

    write(project.prev, make_parts(para(run("The paper as it stands."))))
    write(project.working, make_parts(
        para(run("The paper as the author now wants it."))))

    assert not revision.ingest(project.working, project.prev).style_edit


def test_ingest_does_not_cry_wolf_over_save_noise(project):
    """A Word save rewrites app.xml and settings.xml on every round-trip.

    Reporting those as author edits is what made the layer useless: it
    fired every single time the author opened the file and closed it.
    """
    def app_xml(minutes: int) -> bytes:
        return (f"<Properties><TotalTime>{minutes}</TotalTime>"
                f"</Properties>").encode()

    base = make_parts(para(run("The paper as it stands.")))
    base["docProps/app.xml"] = app_xml(1)
    write(project.prev, base)
    resaved = dict(base)
    resaved["docProps/app.xml"] = app_xml(77)
    write(project.working, resaved)

    report = revision.ingest(project.working, project.prev)
    assert report.changed_parts == []
    assert "docProps/app.xml" in report.noise_parts


# ----------------------------------------------------------- baseline

def test_baseline_records_the_new_truth(project):
    write(project.working, make_parts(para(run("Accepted and settled."))))
    written = revision.baseline(project)
    assert written.prev == project.prev
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_baseline_refuses_a_proposal(project):
    """A baseline containing a proposal is how the next Compare
    flattens that proposal into plain text."""
    write(project.working, make_parts(para(run("x "), ins("pending"))))
    before = project.prev.read_bytes()
    with pytest.raises(BaselinePending):
        revision.baseline(project)
    assert project.prev.read_bytes() == before, "the baseline was written"


def test_baseline_force_is_for_migration(project):
    """Adopting a file that already carries revisions the author keeps."""
    write(project.working, make_parts(para(run("x "), ins("pending"))))
    revision.baseline(project, force=True)
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_baseline_names_the_part_a_revision_hides_in(project):
    write(project.working, make_parts(
        para(run("clean body")),
        footnotes=footnotes_part(para(run("n "), ins("hidden")))))
    with pytest.raises(BaselinePending, match="footnotes"):
        revision.baseline(project)


# -------------------------------------------- what the hand-back LOST ----

#: The shape Word leaves behind when it collapses a paragraph to make an
#: edit: the words survive, the link element does not.
LINKED = ('<w:hyperlink w:anchor="ref_Ritchie2023b">'
          "<w:r><w:t>Ritchie (2023b)</w:t></w:r></w:hyperlink>")
FLAT = "<w:r><w:t>Ritchie (2023b)</w:t></w:r>"


def _handback(project, body: str, **kw) -> None:
    """Write `body` as the author's returned working.docx."""
    write(project.working, make_parts(body, **kw))


def test_ingest_names_a_link_the_authors_word_session_ATE(project):
    """LI7 2026-08-15: 33 body links in, 28 out, and every content layer
    clean — the words are all still there."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))

    report = revision.ingest(project.working, project.prev)

    assert [loss.kind for loss in report.lost] == ["link"]
    assert "ref_Ritchie2023b" in report.lost[0].what


def test_a_lost_FOOTNOTE_is_found_by_text_not_by_id(project):
    """Word renumbers on save: 19 notes become 18 with the ids still
    contiguous, so there is no gap to notice and no id to miss."""
    write(project.prev, make_parts(
        para(run("body")),
        footnotes=notes("footnotes", note("kept", nid=2),
                        note("the vanished note", nid=3))))
    _handback(project, para(run("body")),
              footnotes=notes("footnotes", note("kept", nid=2)))

    lost = revision.ingest(project.working, project.prev).lost

    assert [loss.kind for loss in lost] == ["footnote"]
    assert lost[0].what == "the vanished note"


def test_a_lost_ENDNOTE_is_found_too(project):
    """A check that stopped at the footnotes would be a gate that cannot
    fail for any paper using the other kind."""
    write(project.prev, make_parts(
        para(run("body")),
        extra={"word/endnotes.xml":
               notes("endnotes", note("an endnote", nid=2, kind="endnote"))}))
    _handback(project, para(run("body")),
              extra={"word/endnotes.xml": notes("endnotes")})

    lost = revision.ingest(project.working, project.prev).lost
    assert [(loss.kind, loss.what) for loss in lost] == \
        [("endnote", "an endnote")]


def test_an_ordinary_author_edit_loses_NOTHING(project):
    """The gate must be silent on the normal round-trip, or it will be
    switched off inside a week."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("look at "), LINKED))

    assert revision.ingest(project.working, project.prev).lost == []


def test_baseline_REFUSES_while_a_loss_is_unacknowledged(project):
    """This is the step that makes it permanent: prev.docx is what the
    compare chain measures against afterwards."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))
    before = project.prev.read_bytes()

    with pytest.raises(HandbackLoss, match="ref_Ritchie2023b"):
        revision.baseline(project)
    assert project.prev.read_bytes() == before, "the baseline was written"


def test_force_does_not_override_the_loss_refusal(project):
    """`force` is the flag reached for by reflex, and the whole point is
    that the acknowledgement is specific."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))
    with pytest.raises(HandbackLoss):
        revision.baseline(project, force=True)


def test_a_deliberate_loss_can_be_NAMED_and_then_baselines(project):
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), FLAT))
    lost = revision.ingest(project.working, project.prev).lost

    revision.baseline(project, accept_loss=(lost[0].key,))
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_a_DECLARED_loss_that_did_not_happen_is_itself_refused(project):
    """A stale exemption is a switched-off gate that reads as a
    switched-on one, and it would pass the next real loss in silence."""
    write(project.prev, make_parts(para(run("see "), LINKED)))
    _handback(project, para(run("see "), LINKED))

    with pytest.raises(HandbackLoss, match="has NOT lost"):
        revision.baseline(project, accept_loss=("link:ref_Gone2024 (x)",))


#: Seven linked citations, one per paragraph. The hand-back below
#: flattens THREE of them keeping the words — Word collapsing a
#: paragraph — and cuts the other FOUR clauses outright. Counts only
#: addition separates: 3 against 4, never 1 against 2.
_CITED = [("Adams2020", "Adams (2020)"), ("Brown2021", "Brown (2021)"),
          ("Clark2022", "Clark (2022)"), ("Davis2023", "Davis (2023)"),
          ("Evans2024", "Evans (2024)"), ("Ford2025", "Ford (2025)"),
          ("Gray2026", "Gray (2026)")]


def _cited(kept_words: int):
    """(prev, working) with every link lost; the first `kept_words` keep
    their words, the rest are cut with their clause."""
    prev = "".join(para(run("As "), _linked(anchor, label), run(" shows."))
                   for anchor, label in _CITED)
    working = "".join(
        para(run(f"As {label} shows.")) if i < kept_words
        else para(run("A sentence about something else."))
        for i, (_anchor, label) in enumerate(_CITED))
    return make_parts(prev), make_parts(working)


def test_the_refusal_marks_EACH_loss_whose_words_survive(project):
    """"Word collapsed a paragraph, the link can be rebuilt" is true of
    a loss that kept its words and false of one the author cut, and
    asserting it over a cut passage sent a reader to look for damage to
    repair, five times in one report. So each loss is marked, and the
    count is of the marked ones. Found by mutation, 2026-09-11: the
    marker, the count and the choice of sentence were none of them
    asserted."""
    prev, working = _cited(kept_words=3)
    write(project.prev, prev)
    write(project.working, working)

    with pytest.raises(HandbackLoss) as refused:
        revision.baseline(project)

    said = str(refused.value)
    assert "lost 7 thing(s)" in said, said
    assert said.count("[words survive]") == 3, said
    assert "3 of these keep their words, marked above" in said, said
    assert "Put back anything Word ate" not in said


def test_with_NO_words_surviving_the_refusal_does_not_claim_a_collapse(
        project):
    prev, working = _cited(kept_words=0)
    write(project.prev, prev)
    write(project.working, working)

    with pytest.raises(HandbackLoss) as refused:
        revision.baseline(project)

    said = str(refused.value)
    assert "[words survive]" not in said, said
    assert "keep their words" not in said, said
    assert "Put back anything Word ate" in said, said


def test_a_first_baseline_with_no_prev_is_not_blocked(tmp_path):
    """`init` seeds prev from working, but a paper that has lost its
    build/ directory must still be able to record a truth."""
    (tmp_path / "p2").mkdir()
    src = write(tmp_path / "p2" / "m.docx", make_parts(para(run("body"))))
    paper = revision.init(tmp_path / "p2", src)
    paper.prev.unlink()
    assert revision.baseline(paper).prev == paper.prev


# -------------------------------------------------------------- build

class _FakeBuild:
    """tracked.build, replaced: it reports what Word Compare resolved.

    `notes_xml` writes a footnotes part into the BUILT file. Three of
    `build`'s warnings read the file Compare produced rather than the
    parts that made it — deliberately, so that what they say describes
    the deliverable the author is about to open — and a fake that can
    only write one paragraph cannot reach any of them.
    """

    def __init__(self, math: int = 0, out_text: str = "built",
                 extra: str = "", notes_xml: str | None = None) -> None:
        self.math, self.out_text, self.extra = math, out_text, extra
        self.notes_xml = notes_xml
        self.called_with: tuple[Any, ...] = ()
        self.kwargs: dict[str, Any] = {}

    def __call__(self, original, revised, out, classify=None, **kw):
        self.called_with = (Path(original), Path(revised), Path(out))
        self.kwargs = kw
        write(Path(out), make_parts(para(self.extra + run(self.out_text)),
                                    footnotes=self.notes_xml))
        say = kw.get("progress") or (lambda _: None)
        say(f"resolved {self.math} math revisions")
        report = revision.tracked.BuildReport()
        report.revisions = 4
        # the NUMBER is what the protocol reads; the line above is a
        # sentence tracked.build is free to reword, and the refusal used
        # to be a grep over it
        report.math_resolved = self.math
        return report


def test_build_refuses_a_baseline_the_manuscript_has_OUTGROWN(project):
    """`drift`, at the top of `build` instead of at `promote`.

    After an accept in Word both files read 0 pending while their
    content has diverged, so a redline built then presents the AUTHOR's
    own edits as the agent's proposals. `promote` refuses it on the
    hash — one Word Compare later, and after a reader has spent the
    round trying to make sense of a redline about the wrong pair.
    `drift`'s own docstring named this gap and nothing closed it.
    """
    write(project.working, make_parts(para(run("the author moved on"))))
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("a proposed edit"))))

    with pytest.raises(StaleBatch, match="grew out of") as exc:
        revision.build(project, clean)

    assert "revision ingest" in str(exc.value)
    assert "revision baseline" in str(exc.value)
    assert "word/document.xml" in str(exc.value), "which part moved"
    # ONE part moved, so there is nothing to summarise. Asserted because
    # `> 4` and `!= 4` agree at every count this file used to test, and
    # only a case BELOW the threshold separates them.
    assert "more" not in str(exc.value)


def _stale_message(project, differing: int) -> str:
    """`build`'s refusal when exactly `differing` parts have moved.

    One of them is always `word/document.xml`; the rest are invented
    parts, which `drift` counts as ADDED.
    """
    extra = {f"word/custom{i}.xml": f"<x>{i}</x>"
             for i in range(differing - 1)}
    write(project.working,
          make_parts(para(run("the author moved on")), extra=extra))
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("a proposed edit"))))

    with pytest.raises(StaleBatch) as exc:
        revision.build(project, clean)
    return str(exc.value)


def test_the_stale_baseline_refusal_names_a_SHORT_list_in_full(project):
    """At the boundary exactly, where the summary must NOT appear.

    Four is the threshold, and it is the only count that separates
    `> 4` from `> 3`, `>= 4` and `!= 4` — every one of which prints the
    same sentence at any larger number. Measured: those three survived
    a round against a seven-part fixture.
    """
    said = _stale_message(project, 4)

    assert "more" not in said, said
    assert said.count("word/custom") == 3, "all three, plus document.xml"


def test_the_stale_baseline_refusal_summarises_from_FIVE(project):
    """One past the threshold, which is what separates `> 4` from
    `> 5` — the two agree at four and at nine, the counts this file
    tested first."""
    said = _stale_message(project, 5)

    assert "and 1 more" in said, said
    assert said.count("word/custom") == 4


def test_the_stale_baseline_refusal_SUMMARISES_a_long_list(project):
    """Four parts named, then a count. A refusal that prints every part
    of a package the author re-saved is one nobody reads to the end —
    and the instruction to run `ingest` is at the end.

    NINE differ, not seven. The count is `len(moved) - 4`, and at seven
    `- 4`, `% 4` and `^ 4` all evaluate to 3: the fixture agreed with
    two wrong operators, and both survived the first round. Nine is the
    smallest count above the threshold where the three disagree
    (5, 1, 13).
    """
    said = _stale_message(project, 9)

    assert "and 5 more" in said, said
    assert said.count("word/custom") == 4, "four named, then the count"
    assert "revision ingest" in said, "the instruction survives the trim"


def test_build_says_a_NOTE_DEFINITION_is_out_of_document_order(
        project, monkeypatch):
    """Cheap, and said before Word sees the file.

    Word numbers a note by where its REFERENCE is and stores the
    definitions in whatever order the file holds them, so a paper whose
    definitions are shuffled renders correctly and passes every
    read-only gate. Compare then rewrites the definitions INTO document
    order, and the whole part reads as MOVED against the baseline — on
    AFI, 81 glyph runs and a structure count for a one-line prose batch,
    reported against the batch after the one that appended the note.
    """
    body = (para(run("first") + _ref(3))
            + para(run("second") + _ref(2)))
    shuffled = notes("footnotes", note("b", nid=2), note("a", nid=3))
    write(project.prev, make_parts(body, footnotes=shuffled))
    write(project.working, make_parts(body, footnotes=shuffled))
    clean = write(project.build_dir / "clean.docx",
                  make_parts(body, footnotes=shuffled))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())

    said: list[str] = []
    revision.build(project, clean, progress=said.append)

    order = [ln for ln in said if "not in document order" in ln]
    assert order, said
    assert any(ln.startswith("baseline:") for ln in order), (
        "which SIDE carries it — the baseline and the edit are fixed "
        "in different files")
    assert any(ln.startswith("clean edit:") for ln in order)
    assert "footnote" in order[0]
    # TWO ids, so nothing is trimmed. Below the threshold is the only
    # place `> 6` and `!= 6` disagree.
    assert "..." not in order[0]


def _reversed_notes(count: int, kind: str = "footnotes", *,
                    defined: list[int] | None = None) -> tuple[str, str]:
    """(body, notes part) for `count` notes, DEFINED out of order.

    `defined` gives the definition order explicitly. `out_of_order` does
    not simply count the shuffled ones — a seven-note reversal yields
    six ids, not seven — so a fixture that needs an exact answer has to
    state the arrangement rather than derive it.
    """
    ids = list(range(2, 2 + count))
    tag = kind.removesuffix("s")
    body = "".join(
        para(run(f"p{i}")
             + f'<w:r><w:{tag}Reference w:id="{i}"/></w:r>') for i in ids)
    part = notes(kind, *(note(f"n{i}", nid=i, kind=tag)
                         for i in (defined or list(reversed(ids)))))
    return body, part


def _order_note(project, monkeypatch, count: int, *,
                defined: list[int] | None = None) -> str:
    """The out-of-order line `build` says for `count` shuffled notes."""
    body, part = _reversed_notes(count, defined=defined)
    write(project.prev, make_parts(body, footnotes=part))
    write(project.working, make_parts(body, footnotes=part))
    clean = write(project.build_dir / "clean.docx",
                  make_parts(body, footnotes=part))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())

    said: list[str] = []
    revision.build(project, clean, progress=said.append)
    return next(ln for ln in said
                if ln.startswith("baseline:") and "document order" in ln)


def test_the_note_order_warning_names_SIX_in_full(project, monkeypatch):
    """Six is the threshold and the only count that separates `> 6`
    from `> 5`, `>= 6` and `!= 6` — eight mutants of that comparison
    survived the first round against a two-note fixture, which takes
    the same branch whatever the operator says."""
    line = _order_note(project, monkeypatch, 6)

    assert "..." not in line, line
    for nid in range(2, 8):
        assert str(nid) in line, f"note {nid} is not named"


def test_the_note_order_warning_TRIMS_a_longer_one(project, monkeypatch):
    """Eight rather than seven: `out_of_order` returns six ids for a
    seven-note reversal, so a seven-note fixture is a six-id case
    wearing a different number and the slice boundary goes untested."""
    line = _order_note(project, monkeypatch, 8)

    assert "..." in line, line
    named = [nid for nid in range(2, 10) if str(nid) in line]
    assert len(named) == 6, f"six named, then the ellipsis: {named}"


def test_the_note_order_warning_trims_at_SEVEN_as_well(project, monkeypatch):
    """One past the threshold, which is what separates `> 6` from
    `> 7`. Seven is awkward to reach — a seven-note reversal yields six
    ids — so the definition order is stated rather than derived.
    """
    line = _order_note(project, monkeypatch, 8,
                       defined=[2, 4, 3, 6, 5, 8, 9, 7])

    named = [nid for nid in range(2, 10) if str(nid) in line]
    assert len(named) == 6, f"six named, then the ellipsis: {named}"
    assert "..." in line, line


def test_an_ENDNOTE_is_checked_even_when_there_are_NO_footnotes(
        project, monkeypatch):
    """The loop runs over both kinds and SKIPS a part that is absent.

    `continue` -> `break` survived the first round: with a footnotes
    part present in every fixture the two are indistinguishable. A
    paper with endnotes and no footnotes is the ordinary shape for a
    journal that wants them at the back, and `break` reports nothing
    for it.
    """
    body, part = _reversed_notes(3, kind="endnotes")
    parts = make_parts(body, extra={"word/endnotes.xml": part})
    write(project.prev, parts)
    write(project.working, parts)
    clean = write(project.build_dir / "clean.docx", parts)
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())

    said: list[str] = []
    revision.build(project, clean, progress=said.append)

    assert any("endnote definitions are not in document order" in ln
               for ln in said), said


def test_build_names_the_links_sitting_inside_a_DELETION(project,
                                                         monkeypatch):
    """Reject-all cannot restore them, and no author sees it in Word.

    Compare does not track an anchor: rejecting a deletion restores its
    words as plain text and does not rebuild the link that was in them.
    A batch whose accept-all is perfect then fails gate 5 on
    `links: False`, and on the page a lost link is blue text that is
    still blue until you click it.

    Said at BUILD time on purpose — by the end of the ladder the author
    has a batch to throw away and the finding is unusable.
    """
    gone = ('<w:del w:id="77" w:author="R" w:date="2026-08-07T00:00:00Z">'
            '<w:hyperlink w:anchor="Table1">'
            "<w:r><w:delText>Table 1</w:delText></w:r>"
            "</w:hyperlink></w:del>")
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(extra=gone))

    said: list[str] = []
    revision.build(project, clean, progress=said.append)

    (line,) = [ln for ln in said if "tracked deletion" in ln]
    assert "Table1" in line, "the anchor, so it can be found"
    assert "REJECTING" in line
    assert "Shorten the move" in line, "the remedy is counter-intuitive"
    # ONE link, so nothing is trimmed — the only place `> 4` and
    # `!= 4` disagree is below the threshold.
    assert "..." not in line


def _deleted_links(project, monkeypatch, count: int) -> str:
    """The links-in-deletions line for `count` distinct anchors."""
    gone = "".join(
        f'<w:del w:id="{70 + i}" w:author="R" '
        f'w:date="2026-08-07T00:00:00Z">'
        f'<w:hyperlink w:anchor="Anchor{i}">'
        f"<w:r><w:delText>label {i}</w:delText></w:r>"
        f"</w:hyperlink></w:del>" for i in range(count))
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(extra=gone))

    said: list[str] = []
    revision.build(project, clean, progress=said.append)
    return next(ln for ln in said if "tracked deletion" in ln)


def test_the_deleted_links_warning_names_FOUR_in_full(project, monkeypatch):
    """The threshold exactly, and the only count at which `> 4` differs
    from `> 3`, `>= 4` and `!= 4`. Eight mutants of this one comparison
    survived the first round against a single-link fixture."""
    line = _deleted_links(project, monkeypatch, 4)

    assert "..." not in line, line
    for i in range(4):
        assert f"Anchor{i}" in line


def test_the_deleted_links_warning_TRIMS_a_longer_one(project, monkeypatch):
    """Five: one past the boundary, so the slice `[:4]` is pinned from
    both sides — `[:3]` drops an anchor that must be there and `[:5]`
    keeps one that must not."""
    line = _deleted_links(project, monkeypatch, 5)

    assert "..." in line, line
    assert "5 link(s)" in line
    for i in range(4):
        assert f"Anchor{i}" in line
    assert "Anchor4" not in line, "the fifth is behind the ellipsis"


def test_build_hands_tracked_the_settings_the_PROTOCOL_depends_on(
        project, monkeypatch):
    """Four constants, each load-bearing and each invisible in the
    output, so a round mutated all four and the suite noticed none.

    `verify_in_word` is what makes a batch openable at all;
    `reject_check=False` is the asymmetry this module's own comment
    argues for at length — the protocol REPORTS an unrejectable
    paragraph and lets gate 5 judge it, because refusing here would
    leave the author paragraph names and no file to look at.
    """
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    fake = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", fake)

    revision.build(project, clean)

    assert fake.kwargs["verify_in_word"] is True
    assert fake.kwargs["reject_check"] is False, (
        "refusing here would hand back names and no file — see the "
        "comment above the call")
    assert fake.kwargs["resolve_math"] is True, "the default"
    assert fake.kwargs["force"] is False, "the default"


def test_build_PASSES_ON_the_two_switches_it_is_given(project, monkeypatch):
    """The other side of the defaults: both reach `tracked.build`
    rather than being read and dropped."""
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    fake = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", fake)

    revision.build(project, clean, resolve_math=False, force=True)

    assert fake.kwargs["resolve_math"] is False
    assert fake.kwargs["force"] is True


def test_build_names_a_footnote_whose_REFERENCE_moved(project, monkeypatch):
    """Compare emits the whole note as an insertion with no matching
    deletion, so rejecting empties it and gate 5 fails on a note the
    counts say nothing about (Parental Style 2026-08-10, footnote 2
    re-anchored onto a new opening sentence).

    Accepting is right, which is why this is a note and not a refusal.
    """
    with_note = make_parts(para(run("body") + _ref(2)),
                           footnotes=notes("footnotes", note("the note")))
    write(project.prev, with_note)
    write(project.working, with_note)     # else `drift` fires first
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    reinserted = notes("footnotes",
                       f'<w:footnote w:id="2">'
                       f'<w:p>{ins("the note")}</w:p></w:footnote>')
    monkeypatch.setattr(revision.tracked, "build",
                        _FakeBuild(notes_xml=reinserted))

    said: list[str] = []
    revision.build(project, clean, progress=said.append)

    (line,) = [ln for ln in said if "REFERENCE moved" in ln]
    assert "footnote 2" in line
    assert "Accepting is right" in line
    assert "gate 5" in line, "and what it costs if they do not"
    assert "MEASURABLY empties it" in line, "measured, not predicted"


def test_build_does_not_predict_gate_5_for_a_note_reject_all_RESTORES(
        project, monkeypatch):
    """The same shape — an insertion with no matching deletion — over a
    note the batch merely ADDED to, whose words rejecting puts back.

    Warning here said "rejecting empties the note, so gate 5 will fail
    on it" about notes gate 5 then passed, and `validate` printed
    `'footnotes': True` about the same note in the same run. A build
    warning that the ladder goes on to contradict is one an author
    learns to skip, including the time it is real."""
    with_note = make_parts(para(run("body") + _ref(2)),
                           footnotes=notes("footnotes", note("the note")))
    write(project.prev, with_note)
    write(project.working, with_note)     # else `drift` fires first
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    added_to = notes("footnotes",
                     f'<w:footnote w:id="2"><w:p>{run("the note")}'
                     f'{ins("and more")}</w:p></w:footnote>')
    monkeypatch.setattr(revision.tracked, "build",
                        _FakeBuild(notes_xml=added_to))

    said: list[str] = []
    revision.build(project, clean, progress=said.append)

    (line,) = [ln for ln in said if "REFERENCE moved" in ln]
    assert "gate 5 is not at risk" in line, line
    assert "nothing to do" in line, line
    assert "MEASURABLY" not in line


def test_the_stale_baseline_refusal_can_be_overridden(project, monkeypatch):
    """`allow_stale_baseline`, and almost nothing should pass it."""
    write(project.working, make_parts(para(run("the author moved on"))))
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())

    revision.build(project, clean, allow_stale_baseline=True)


def test_a_WORD_RESAVE_of_the_manuscript_is_not_a_stale_baseline(
        project, monkeypatch):
    """Compared by MEANING, not by bytes: a Word round-trip re-mints the
    rsids in every part it touches, and a refusal that fires on all of
    them is one nobody reads. `promote`'s hash guard cannot make that
    distinction, which is why this gate is `drift` and not a digest."""
    parts = package.read_parts(project.working)
    doc = parts["word/document.xml"].decode("utf-8")
    assert "<w:p " in doc
    parts["word/document.xml"] = doc.replace(
        "<w:p ", '<w:p w:rsidR="00AB12CD" ').encode("utf-8")
    package.write_docx(project.working, parts)
    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())

    revision.build(project, clean)          # must not raise StaleBatch


def test_build_refuses_a_baseline_with_pending_revisions(project,
                                                         monkeypatch):
    """Compare rebuilds the redline from ACCEPTED content, so pending
    revisions are flattened into plain text and can never be rejected —
    the author's open verdicts decided for them, silently."""
    write(project.prev, make_parts(para(run("x "), ins("unadjudicated"))))
    fake = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", fake)

    with pytest.raises(BaselinePending):
        revision.build(project, project.working)
    assert not fake.called_with, "Word Compare ran anyway"
    assert not project.batch.exists()


def test_build_pending_baseline_can_be_absorbed_deliberately(project,
                                                             monkeypatch):
    write(project.prev, make_parts(para(run("x "), ins("unadjudicated"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    revision.build(project, project.working, allow_pending_baseline=True)
    assert project.batch.exists()


def test_build_refuses_when_compare_resolved_math(project, monkeypatch):
    """Measured, not suspected: on a real subscript batch the compare
    path produced 0 insertions against the hand-authored path's 4, and
    reject-all no longer restored the baseline."""
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=5))
    with pytest.raises(MathResolved):
        revision.build(project, project.working)


def test_build_ignores_a_zero_math_note(project, monkeypatch):
    """docxkit emits the note even when the count is zero, so the guard
    reads the NUMBER rather than matching the sentence."""
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=0))
    report = revision.build(project, project.working)
    assert report.revisions == 4


def test_build_math_override(project, monkeypatch):
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=2))
    revision.build(project, project.working, allow_math_resolve=True)
    assert project.batch.exists()


def test_build_defaults_to_the_staging_path(project, monkeypatch):
    fake = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", fake)
    revision.build(project, project.working)
    assert fake.called_with[2] == project.batch
    assert fake.called_with[0] == project.prev, \
        "a batch must be built on the baseline, not on the live file"


def test_build_names_the_paragraphs_compare_left_untracked(project,
                                                           monkeypatch):
    """The math count understated this badly: a merged, rewritten
    math-bearing paragraph shipped WHOLE and untracked while the batch
    read "7 revisions, 6 of them in the body" — all six of them two
    word-swaps in an unrelated paragraph (Parental Style 2026-08-10).
    Said BEFORE the handback, not after gate 5 fails."""
    base = make_parts(para(run("the baseline sentence")))
    write(project.prev, base)
    write(project.working, base)        # at build time the two agree
    monkeypatch.setattr(revision.tracked, "build",
                        _FakeBuild(out_text="a rewritten sentence"))
    seen: list[str] = []
    revision.build(project, project.working, progress=seen.append)
    said = "\n".join(seen)
    assert "UNTRACKED" in said, said
    assert "the baseline sentence" in said and "a rewritten sentence" in said
    assert "no revision on them" in said


def test_a_faithfully_tracked_build_says_nothing_about_untracking(
        project, monkeypatch):
    base = make_parts(para(run("built")))
    write(project.prev, base)
    write(project.working, base)        # at build time the two agree
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    seen: list[str] = []
    revision.build(project, project.working, progress=seen.append)
    assert not any("UNTRACKED" in s for s in seen), seen


def test_build_no_longer_advises_a_path_that_does_not_exist(project,
                                                            monkeypatch):
    """"Author this batch by hand instead" named no supported path —
    `tracked.build` IS the Compare wrapper. The refusal now says what is
    true: this batch has no reviewable redline."""
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild(math=5))
    with pytest.raises(MathResolved) as exc:
        revision.build(project, project.working)
    assert "no reviewable redline" in str(exc.value).lower()


def test_a_paper_can_declare_the_PART_its_Compare_eats(project, monkeypatch):
    """Word's Compare drops Aging_Well's first-page footer on every
    rebuild — part, relationship AND the sectPr reference — and the
    paper carried a 130-line script to put all three back. It is not a
    default because a header or footer is reached from the section
    properties as well: `restore_parts` puts that reference back or
    refuses, but whether the section is the one the author meant is a
    question about the rendered page. So the paper says it once."""
    from docxkit import revision as rev

    project.config.write_text(
        project.config.read_text(encoding="utf-8").replace(
            "[batch]", '[batch]\ncarry = ["word/footer3.xml"]', 1),
        encoding="utf-8")
    paper = rev.load_paper(project.root)
    assert paper.carry == ("word/footer3.xml",)

    fake = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", fake)
    revision.build(paper, paper.working)

    assert fake.kwargs["carry"] == (*rev.tracked.CARRIED_PARTS,
                                    "word/footer3.xml")
    # …and a paper that declares nothing still gets the two every paper
    # gets: the data store and the user-defined properties
    assert revision.build(project, project.working) is not None
    assert fake.kwargs["carry"] == rev.tracked.CARRIED_PARTS


def test_build_progress_reaches_the_caller(project, monkeypatch):
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    seen: list[str] = []
    revision.build(project, project.working, progress=seen.append)
    assert seen


# ------------------------------------------------------------ promote

def test_promote_refuses_while_word_holds_the_file(project, monkeypatch):
    """A copy written over a document open in Word appears to succeed,
    and then Word writes its in-memory version on top."""
    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setattr(revision.package, "is_locked", lambda _p: True)
    before = project.working.read_bytes()

    with pytest.raises(DocumentLocked):
        revision.promote(project)
    assert project.working.read_bytes() == before


def test_promote_refuses_a_stale_batch(project):
    """The author edited working.docx while the batch was being built;
    promoting would destroy those edits."""
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run("the author's own edit"))))
    before = project.working.read_bytes()

    with pytest.raises(StaleBatch):
        revision.promote(project)
    assert project.working.read_bytes() == before


@pytest.mark.parametrize("edit", [
    "the author's own edit", "aaa", "zzz", "a much longer sentence the "
    "author typed into the manuscript while the batch was building", "0",
])
def test_the_stale_guard_does_not_depend_on_how_two_HASHES_SORT(project,
                                                                edit):
    """`live_hash != base_hash` read as `<` still fires for about half
    of all content — whichever half the one fixture happened to land in.
    The guard's property is that ANY difference is refused, and only a
    spread of contents can assert that: these five put the live hash on
    both sides of the baseline's.

    This is the refusal that stands between a batch and an author's
    unsaved work, so "usually catches it" is not the contract.
    """
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run(edit))))
    before = project.working.read_bytes()
    with pytest.raises(StaleBatch):
        revision.promote(project)
    assert project.working.read_bytes() == before


def test_the_READ_ONLY_commands_snapshot_a_file_Word_holds(project,
                                                           monkeypatch):
    """`status` and `ingest` are documented read-only, and the
    protocol's own resume ritual is to run them both — which is exactly
    what one wants while the author still has the manuscript open. Both
    refused with "close it and retry" (2026-08-21), while a byte copy of
    the same locked file read perfectly.
    """
    from docxkit import package
    from docxkit import revision as rev

    monkeypatch.setattr(package, "is_locked",
                        lambda p: Path(p) == project.working)

    st = rev.state(project.working)
    report = rev.ingest(project.working, project.prev)

    assert st.from_snapshot is True
    assert report.from_snapshot is True
    assert st.path == project.working, "the report names the REAL file"
    # …and so does the one INSIDE the ingest report, which was built
    # from the snapshot copy: it named a temp path already deleted by
    # the time the caller saw it, and said from_snapshot=False inside a
    # report whose own flag said True.
    assert report.working_state.path == project.working
    assert report.working_state.path.exists()
    assert report.working_state.from_snapshot is True
    assert rev.state(project.prev).from_snapshot is False


def test_a_snapshot_that_cannot_be_COPIED_refuses_as_before(project,
                                                            monkeypatch):
    """The fallback has to be the old answer, not a half-read one."""
    import shutil

    from docxkit import package

    monkeypatch.setattr(package, "is_locked", lambda _p: True)
    monkeypatch.setattr(shutil, "copy2", _raise_permission)

    with package.readable(project.working) as (path, copied):
        assert (path, copied) == (project.working, False)


def _raise_permission(*_a, **_kw):
    raise PermissionError("the sharing violation this fallback is for")


def test_promote_refuses_a_batch_built_on_ANOTHER_baseline(project):
    """The other stale direction, and the one that loses work silently.

    The guard above asks whether the AUTHOR moved. This asks whether the
    BATCH did: a refused build leaves the PREVIOUS redline in
    build/batch.docx, live and base stay in sync so nothing else
    objects, and promoting replaces the manuscript with a generation
    from before an entire author round (Aging_Well R5, 2026-08-21).
    """
    from docxkit import guard

    write(project.batch, make_parts(para(run("a redline of an older truth"))))
    guard.stamp(project.batch, base_sha256="0" * 64)
    before = project.working.read_bytes()

    with pytest.raises(StaleBatch, match="not built on"):
        revision.promote(project)

    assert project.working.read_bytes() == before


def test_promote_takes_a_batch_stamped_with_THIS_baseline(project):
    from docxkit import guard

    write(project.batch, make_parts(para(run("the batch"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))

    report = revision.promote(project)

    assert project.working.read_bytes() == project.batch.read_bytes()
    assert report.rescue.exists()


def test_promote_still_takes_an_UNSTAMPED_batch(project):
    """A batch nothing built — a hand-authored edit vehicle, or one from
    before the stamp carried a baseline — cannot answer the question,
    and refusing on "cannot tell" would break the DSI path outright."""
    write(project.batch, make_parts(para(run("hand-authored"))))

    revision.promote(project)

    assert project.working.read_bytes() == project.batch.read_bytes()


def test_promote_refuses_a_batch_CHANGED_since_its_stamp_BEFORE_writing(
        project):
    """The stamp is checked before anything is written, not by `carry`
    after the manuscript has already been replaced.

    DSI, 2026-09-16: a relink pass changed `build/batch.docx` after
    `revision build` stamped it, `validate` passed it, and `promote`
    copied it over the manuscript, took the rescue and kept the redline
    — then refused in `guard.carry`, exit 1, leaving no carried stamp, no
    ledger line and no pruning. A command that reported failure had done
    the dangerous half of its work. Refused up front, nothing moves."""
    from docxkit import guard
    from docxkit.revision import _ledger

    write(project.batch, make_parts(para(run("as the build wrote it"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    write(project.batch, make_parts(para(run("as a tool pass left it"))))
    before = project.working.read_bytes()

    with pytest.raises(StaleBatch, match="restamp") as refused:
        revision.promote(project)

    assert "changed since" in str(refused.value)
    assert project.working.read_bytes() == before
    assert revision.rescues(project) == [], "a rescue was taken anyway"
    assert project.redlines() == [], "a redline was kept anyway"
    assert not _ledger.ledger_path(project).exists()
    assert not guard.stamp_path(project.working).exists()


def test_promote_takes_a_batch_a_tool_RESTAMPED(project):
    """The way through the refusal above when the change was a tool's:
    `guard.restamp` records the repair, and the stamp carried beside the
    manuscript keeps that record."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("as the build wrote it"))))
    guard.stamp(project.batch, base_sha256=guard.sha256(project.prev))
    write(project.batch, make_parts(para(run("relinked"))))
    guard.restamp(project.batch, why="relink: citation links only")

    report = revision.promote(project)

    assert project.working.read_bytes() == project.batch.read_bytes()
    assert report.stamp is not None
    carried = json.loads(report.stamp.read_text(encoding="utf-8"))
    assert carried["repairs"][0]["why"] == "relink: citation links only"


def test_promote_refuses_when_the_RESCUE_copy_did_not_land(project,
                                                           monkeypatch):
    """A post-condition that never fires in a happy path, and so was
    never run: without it, a failed rescue means working.docx is
    overwritten with nothing left to undo it. `!=` read as `<` passes
    half the time and this branch is the whole reason the copy is
    checked at all."""
    import shutil

    def _bad(src, dst, *a, **k):
        Path(dst).write_bytes(b"not the file")
        return dst

    write(project.batch, make_parts(para(run("the batch"))))
    before = project.working.read_bytes()
    monkeypatch.setattr(shutil, "copy2", _bad)
    with pytest.raises(ProtocolError, match="rescue copy did not land"):
        revision.promote(project)
    assert project.working.read_bytes() == before, \
        "the live file was overwritten with no rescue behind it"


@pytest.mark.parametrize("landed", [b"half a file", b"a", b"zzzz", b""])
def test_promote_refuses_when_the_PROMOTE_itself_did_not_land(
        project, monkeypatch, landed):
    """The same for the copy onto working.docx — and parametrised for
    the same reason as the stale guard: `!=` read as an ordering still
    fires for whichever half of all content the one fixture landed in.
    The rescue must still be made by the real routine, or the check
    above this one fires instead and proves nothing about this one."""
    import shutil
    real = shutil.copyfile

    def _bad_onto_live(src, dst, *a, **k):
        if Path(dst) == project.working:
            Path(dst).write_bytes(landed)
            return dst
        return real(src, dst, *a, **k)

    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setattr(shutil, "copyfile", _bad_onto_live)
    with pytest.raises(ProtocolError, match="copy did not land"):
        revision.promote(project)


def _bytes_hashing(*, below: str) -> bytes:
    """What a failed copy left behind, hashing BELOW `below`.

    Both landing checks compare two hex digests with `!=`, and an
    ordering in place of it still refuses every copy that falls on one
    side of the file it is compared with. The payloads above all fall on
    the same side, so the mutant reads as the real check; this picks one
    from the other side, deterministically and in a few tries.
    """
    import hashlib

    for n in range(1000):
        blob = b"a copy that stopped part way %d" % n
        if hashlib.sha256(blob).hexdigest() < below:
            return blob
    raise AssertionError("no payload hashed below the file")


def test_promote_refuses_a_RESCUE_that_hashes_BELOW_the_live_file(
        project, monkeypatch):
    """The other half of the rescue check. `b"not the file"` above sorts
    above working.docx's digest, so `!=` read as `>` refuses it and
    looks like the real post-condition; a copy that sorts below is let
    through, and the manuscript is then overwritten with nothing to undo
    it — which is the one thing this check exists to prevent."""
    import shutil

    from docxkit import guard

    write(project.batch, make_parts(para(run("the batch"))))
    landed = _bytes_hashing(below=guard.sha256(project.working))
    before = project.working.read_bytes()
    monkeypatch.setattr(shutil, "copy2",
                        lambda _s, d, *a, **k: Path(d).write_bytes(landed))

    with pytest.raises(ProtocolError, match="rescue copy did not land"):
        revision.promote(project)

    assert project.working.read_bytes() == before
    assert project.redlines() == [], "a refused promote kept no redline"


def test_promote_refuses_ITS_OWN_copy_that_hashes_BELOW_the_batch(
        project, monkeypatch):
    """And the other half of the check on the copy onto working.docx.
    The four payloads parametrised above all sort above the batch, so
    `>` refuses all four; one that sorts below leaves the manuscript
    holding bytes nobody built, with the batch's stamp carried beside it
    to say they were reviewed."""
    import shutil

    from docxkit import guard

    real = shutil.copyfile
    write(project.batch, make_parts(para(run("the batch"))))
    landed = _bytes_hashing(below=guard.sha256(project.batch))

    def _bad_onto_live(src, dst, *a, **k):
        if Path(dst) == project.working:
            return Path(dst).write_bytes(landed)
        return real(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "copyfile", _bad_onto_live)

    with pytest.raises(ProtocolError, match="copy did not land"):
        revision.promote(project)

    assert project.working.read_bytes() == landed
    assert not guard.stamp_path(project.working).exists(), \
        "no stamp certifies bytes the promote refused"


def test_promote_lands_and_leaves_a_rescue_copy(project):
    write(project.batch, make_parts(para(run("the batch"))))
    original = project.working.read_bytes()

    report = revision.promote(project)
    assert project.working.read_bytes() == project.batch.read_bytes()
    assert report.rescue.exists()
    assert report.rescue.read_bytes() == original, \
        "the rescue copy does not hold the file that was replaced"


def test_promote_carries_the_batch_stamp_beside_the_manuscript(project):
    """The manuscript now IS the batch, and `guard.check` on it must say
    "untouched" rather than "someone edited it in Word". A paper that
    builds with `out=working.docx` (HCW's lane script) reads exactly
    that, and was passing `force=True` every round to get past a stamp
    promote had never refreshed — which retires the guard for the
    author's real edits as well."""
    from docxkit import guard

    write(project.batch, make_parts(para(run("the batch"))))
    guard.stamp(project.batch, original="prev.docx", revised="clean.docx",
                base_sha256=guard.sha256(project.prev))

    report = revision.promote(project)

    stamp = guard.stamp_path(project.working)
    assert report.stamp == stamp and stamp.exists()
    assert guard.check(project.working) is None, \
        "the guard called the file promote just wrote an author edit"
    assert not list(project.working.parent.glob("*user_edited*"))
    assert guard.base_of(project.working) == guard.sha256(project.prev)
    # the batch keeps its own: verdict/validate still ask base_of(batch)
    assert guard.base_of(project.batch) == guard.sha256(project.prev)


def test_promote_replaces_the_stamp_a_PRIOR_round_left_beside_it(project):
    """The incident's shape: a stamp beside working.docx naming an
    earlier batch's inputs, still there after a later promote. Without
    the carry, `check` refuses the freshly promoted file and `base_of`
    names a baseline it was never built on."""
    from docxkit import guard

    guard.stamp(project.working, original="prev.docx",
                revised="OLD_clean.docx", base_sha256="0" * 64)
    write(project.batch, make_parts(para(run("the new batch"))))
    guard.stamp(project.batch, original="prev.docx",
                revised="NEW_clean.docx",
                base_sha256=guard.sha256(project.prev))

    revision.promote(project)

    recorded = json.loads(
        guard.stamp_path(project.working).read_text(encoding="utf-8"))
    assert recorded["revised"] == "NEW_clean.docx"
    assert recorded["sha256"] == guard.sha256(project.working)
    assert guard.check(project.working) is None


def test_promote_of_an_UNSTAMPED_batch_removes_the_stale_stamp(project):
    """A hand-authored vehicle has no stamp to carry. What must not
    survive is the previous one: it would describe a file that is gone,
    and `check` reading "no stamp" (cannot verify — cautious) is the
    truthful answer where a stale hash is another file's provenance."""
    from docxkit import guard

    guard.stamp(project.working, original="prev.docx",
                revised="OLD_clean.docx", base_sha256="0" * 64)
    write(project.batch, make_parts(para(run("hand-authored"))))

    report = revision.promote(project)

    assert report.stamp is None
    assert not guard.stamp_path(project.working).exists()
    assert guard.base_of(project.working) is None


def test_promote_keeps_the_REDLINE_the_rescue_ladder_does_not(project):
    """The rescue holds the file being REPLACED, which is clean. Only
    this copy holds the markup.

    Measured across eight protocol papers on 2026-08-23: every
    working.docx and every rescue copy in all of them carried 0
    insertions and 0 deletions, because a completed cycle ends with the
    author's accept and the ladder only ever rescued clean generations.
    The author opened a manuscript and could not see what a batch had
    changed, and nothing in the package could tell them."""
    write(project.batch, make_parts(para(run("the batch"))))
    batch_bytes = project.batch.read_bytes()

    report = revision.promote(project)

    assert report.redline is not None, "no redline was kept"
    assert report.redline.exists()
    assert report.redline.read_bytes() == batch_bytes, \
        "the kept redline is not the batch that was promoted"
    assert report.redline != report.rescue
    assert report.redline.read_bytes() != report.rescue.read_bytes(), \
        "the redline holds the same clean file the rescue does"


def test_a_corrupt_redline_copy_is_DELETED_not_left_behind(project,
                                                           monkeypatch):
    """The refusal must not leave a lie in the one folder nothing prunes.

    A truncated copy here is stamped and named exactly like a good
    redline, and the batch it claims to record is the one thing nobody
    can reconstruct afterwards. An audit trail with a corrupt entry in
    it is worse than a gap: a gap is visible."""
    import shutil
    real = shutil.copy2

    def _bad_redline(src, dst, *a, **k):
        if Path(dst).parent == project.redline_dir:
            Path(dst).write_bytes(b"truncated")
            return dst
        return real(src, dst, *a, **k)

    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setattr(shutil, "copy2", _bad_redline)
    with pytest.raises(ProtocolError, match="redline copy did not land"):
        revision.promote(project)

    left = list(project.redline_dir.glob("*.docx"))
    assert left == [], f"a corrupt redline was left behind: {left}"


def test_redlines_lists_them_oldest_first(project):
    """The permanent record gets a first-class accessor, as rescues do."""
    assert revision.redlines(project) == [], "nothing promoted yet"
    kept = []
    for word in ("first", "second", "third"):
        write(project.batch, make_parts(para(run(word))))
        kept.append(revision.promote(project).redline)
        revision.baseline(project)
    assert revision.redlines(project) == kept, "not in promote order"


def test_redlines_is_empty_not_an_error_without_the_folder(project):
    """A paper whose batches all predate the retention has no folder."""
    assert not project.redline_dir.exists()
    assert revision.redlines(project) == []


def test_redlines_live_in_their_own_folder_under_build(project):
    write(project.batch, make_parts(para(run("the batch"))))
    report = revision.promote(project)
    assert report.redline is not None
    assert report.redline.parent == project.redline_dir
    assert project.redline_dir.parent == project.build_dir
    assert project.redline_dir != project.rescue_dir
    assert not list(project.working.parent.glob("*redline*"))


def test_each_promote_keeps_its_own_redline(project):
    write(project.batch, make_parts(para(run("first"))))
    first = revision.promote(project)
    revision.baseline(project)
    write(project.batch, make_parts(para(run("second"))))
    second = revision.promote(project)
    assert first.redline != second.redline
    assert first.redline is not None and second.redline is not None
    assert first.redline.exists() and second.redline.exists()


def test_pruning_rescues_never_touches_a_redline(project):
    """Thinning the audit trail would recreate the gap it closes, so
    `prune_rescues` must not see this folder at all."""
    project.config.write_text(
        project.config.read_text(encoding="utf-8").replace(
            "rescue_keep = 5", "rescue_keep = 1"), encoding="utf-8")
    paper = revision.load_paper(project.root)
    for word in ("first", "second", "third"):
        write(paper.batch, make_parts(para(run(word))))
        revision.promote(paper)
        revision.baseline(paper)
    kept = list(paper.redline_dir.glob("*.docx"))
    assert len(kept) == 3, f"a redline was pruned away: {kept}"
    assert len(revision.rescues(paper)) == 1


def test_promote_refuses_when_the_REDLINE_copy_did_not_land(project,
                                                            monkeypatch):
    """Refuse before overwriting: after the author accepts, this batch's
    markup would exist nowhere, so a redline that did not land is worth
    the same refusal a rescue that did not land already gets."""
    import shutil
    real = shutil.copy2

    def _bad_redline(src, dst, *a, **k):
        if Path(dst).parent == project.redline_dir:
            Path(dst).write_bytes(b"not the file")
            return dst
        return real(src, dst, *a, **k)

    write(project.batch, make_parts(para(run("the batch"))))
    before = project.working.read_bytes()
    monkeypatch.setattr(shutil, "copy2", _bad_redline)
    with pytest.raises(ProtocolError, match="redline copy did not land"):
        revision.promote(project)
    assert project.working.read_bytes() == before, \
        "the live file was overwritten with no redline behind it"


def test_each_promote_keeps_its_own_rescue(project):
    """The fixed-name version overwrote its own rescue every time, so
    only the most recent live state was ever recoverable."""
    write(project.batch, make_parts(para(run("first"))))
    first = revision.promote(project)
    revision.baseline(project)
    write(project.batch, make_parts(para(run("second"))))
    second = revision.promote(project)
    assert first.rescue != second.rescue
    assert first.rescue.exists() and second.rescue.exists()


def test_rescues_live_under_build_not_beside_the_manuscript(project):
    """Five working_rescueN.docx beside working.docx is exactly the
    ambiguity the one-file layout removed."""
    write(project.batch, make_parts(para(run("the batch"))))
    report = revision.promote(project)
    assert report.rescue.parent == project.rescue_dir
    assert project.rescue_dir.parent == project.build_dir
    assert not list(project.working.parent.glob("*rescue*"))


def test_rescues_are_stamped_not_numbered(project):
    """Numbering and pruning cannot both be right: the counter takes the
    first FREE number, so pruning 1-3 makes the next promote write a new
    file called _rescue1, older than the _rescue5 beside it."""
    stamped = revision.rescue_path(project, datetime(2026, 8, 7, 21, 54, 3))
    assert stamped.name == (f"{project.working.stem}_rescue_"
                            f"20260807-215403-000000.docx")


def test_same_moment_names_keep_their_order(project):
    """The regression that a real run found. The first version appended
    '-2' on collision, and '-' sorts BEFORE '.', so '…215403-2.docx' came
    before '…215403.docx' — the oldest copy reading as the newest, and
    prune deleting from the wrong end.
    """
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    moment = datetime(2026, 8, 7, 21, 54, 3)
    written = []
    for _ in range(7):                       # seven promotes, one second
        p = revision.rescue_path(project, moment)
        p.write_bytes(b"x")
        written.append(p)

    assert len({p.name for p in written}) == 7, "two promotes collided"
    assert len({len(p.name) for p in written}) == 1, \
        "names differ in width, so sorting them is not chronological"
    assert revision.rescues(project) == written, \
        "listed order does not match the order they were written"

    revision.prune_rescues(project, keep=2)
    assert revision.rescues(project) == written[-2:], \
        "prune kept the wrong end"


def _seed_rescues(project, n: int) -> list[Path]:
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(n):
        p = revision.rescue_path(project, datetime(2026, 8, 7, 10, 0, i))
        p.write_bytes(f"rescue {i}".encode())
        made.append(p)
    return made


def test_rescues_are_listed_oldest_first(project):
    made = _seed_rescues(project, 4)
    assert revision.rescues(project) == made


def test_prune_keeps_the_newest(project):
    made = _seed_rescues(project, 7)
    gone = revision.prune_rescues(project, keep=3)
    assert gone == made[:4]
    assert revision.rescues(project) == made[4:]
    assert all(not p.exists() for p in gone)


def test_prune_zero_removes_all(project):
    _seed_rescues(project, 3)
    assert len(revision.prune_rescues(project, keep=0)) == 3
    assert revision.rescues(project) == []


def test_a_negative_keep_does_not_delete_the_newest(project):
    """Slicing with a negative limit would take from the wrong end and
    delete exactly the copies worth having."""
    made = _seed_rescues(project, 3)
    assert revision.prune_rescues(project, keep=-2) == made
    assert revision.rescues(project) == []


def test_promote_prunes_to_the_configured_depth(project):
    _seed_rescues(project, 6)
    write(project.batch, make_parts(para(run("the batch"))))
    report = revision.promote(project)
    # 6 seeded + this promote's own = 7, thinned to rescue_keep
    assert len(revision.rescues(project)) == project.rescue_keep
    assert report.pruned
    assert report.rescue.exists(), "the promote pruned its own rescue"


def test_rescue_keep_is_configurable(project):
    project.config.write_text(
        project.config.read_text(encoding="utf-8").replace(
            "rescue_keep = 5", "rescue_keep = 2"), encoding="utf-8")
    reloaded = revision.load_paper(project.root)
    assert reloaded.rescue_keep == 2
    _seed_rescues(reloaded, 4)
    revision.prune_rescues(reloaded)
    assert len(revision.rescues(reloaded)) == 2


def test_rescues_on_a_paper_that_has_never_promoted(project):
    assert revision.rescues(project) == []
    assert revision.prune_rescues(project) == []


def test_promote_needs_its_inputs(project):
    with pytest.raises(ProtocolError, match="missing"):
        revision.promote(project)          # no batch was ever built


# ----------------------------------------------------------- validate

class _FakeDoc:
    def __init__(self, revisions: int = 2, text: str = "") -> None:
        self.Revisions = type("R", (), {"Count": revisions})()
        self._text = text
        self.accepted = False

    def AcceptAllRevisions(self) -> None:
        self.accepted = True

    @property
    def Paragraphs(self) -> list[Any]:
        return [type("P", (), {"Range": type("R", (), {
            "Text": self._text})()})()]


class _FakeWord:
    """The COM boundary, replaced. Word's verdict is an input here."""

    def __init__(self, doc: _FakeDoc | None = None,
                 explode: bool = False) -> None:
        self.doc, self.explode = doc or _FakeDoc(), explode

    @contextlib.contextmanager
    def session(self, **kw):
        self.session_kwargs = kw
        yield "app"

    @contextlib.contextmanager
    def open_doc(self, _app, _path, **_kw):
        if self.explode:
            raise OSError("Word could not open the file")
        yield self.doc


def test_validate_aborts_before_word_when_lint_fails(tmp_path,
                                                     monkeypatch):
    """Lint is offline and cheap; failing early saves a Word round-trip
    and, more to the point, never opens a file known to be broken."""
    path = write(tmp_path / "bad.docx", make_parts(para(run("x"))))
    monkeypatch.setattr(revision._lint, "lint_parts",
                        lambda _parts: ["orphan bookmark 3"])
    opened: list[str] = []
    monkeypatch.setattr(revision._validate, "_word",
                        type("W", (), {"session": lambda *a, **k:
                                       opened.append("word")})())

    report = revision.validate(path)
    assert report.lint
    assert not report.ok
    assert not opened, "Word was opened despite a lint failure"


def test_validate_reports_a_file_word_refuses(tmp_path, monkeypatch):
    path = write(tmp_path / "x.docx", make_parts(para(run("x"))))
    monkeypatch.setattr(revision._validate, "_word", _FakeWord(explode=True))
    report = revision.validate(path)
    assert report.word_opened is False
    assert report.word_error
    assert not report.ok


def test_the_protocol_puts_a_CEILING_on_its_Word_sessions(
        tmp_path, monkeypatch, project):
    """Row 6 of the 2026-09-03 review: Word's save path can hang
    indefinitely, and until then the only ceiling anywhere was
    pytest's. `[batch] word_deadline` (default 600 s) reaches
    `validate`'s one session and `build`'s Compare, each named; 0 is
    no ceiling, and the library default stays None."""
    path = write(tmp_path / "x.docx", make_parts(para(run("x"))))
    fake = _FakeWord()
    monkeypatch.setattr(revision._validate, "_word", fake)

    revision.validate(path, word_deadline=45)
    assert fake.session_kwargs == {"deadline": 45,
                                   "doing": "validating x.docx"}
    revision.validate(path)
    assert fake.session_kwargs == {}

    clean = write(project.build_dir / "clean.docx",
                  make_parts(para(run("edit"))))
    built = _FakeBuild()
    monkeypatch.setattr(revision.tracked, "build", built)
    revision.build(project, clean)
    assert built.kwargs["word_deadline"] == 600.0

    unbounded = revision.load_paper(project.root)
    object.__setattr__(unbounded, "word_deadline", 0.0)
    revision.build(unbounded, clean)
    assert built.kwargs["word_deadline"] is None


def test_validate_ABORTS_on_a_batch_built_on_another_baseline(tmp_path):
    """Gate 0. Everything below compares the batch with the baseline, so
    a mismatched pair produces a full and entirely plausible verdict
    about a document nobody is working on: twenty LINK LOST findings
    against a redline two baselines old, read for several minutes as if
    they were this round's (Aging_Well R5, 2026-08-21)."""
    from docxkit import guard

    base = write(tmp_path / "prev.docx", make_parts(para(run("settled"))))
    stale = write(tmp_path / "batch.docx", make_parts(
        para(run("settled"), ins("added"))))
    guard.stamp(stale, base_sha256="0" * 64)

    report = revision.validate(stale, base, use_word=False)

    assert report.built_on_this_baseline is False
    assert report.built_on == "0" * 64
    assert not report.ok
    assert report.counts == {}, "the ladder ran on the wrong pair anyway"
    assert report.reject_matches_baseline is None


def test_validate_runs_the_ladder_when_the_batch_names_THIS_baseline(
        tmp_path):
    from docxkit import guard

    base = write(tmp_path / "prev.docx", make_parts(para(run("settled"))))
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("settled"), ins("added"))))
    guard.stamp(batch, base_sha256=guard.sha256(base))

    report = revision.validate(batch, base, use_word=False)

    assert report.built_on_this_baseline is True
    assert report.ok


def test_validate_says_UNKNOWN_rather_than_stale_for_an_unstamped_batch(
        tmp_path):
    """A hand-authored batch and one built before the stamp carried a
    baseline both answer "cannot tell", which is not the same as
    "wrong": refusing on it would break the DSI vehicle outright."""
    base = write(tmp_path / "prev.docx", make_parts(para(run("settled"))))
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("settled"), ins("added"))))

    report = revision.validate(batch, base, use_word=False)

    assert report.built_on_this_baseline is None
    assert report.ok


def test_validate_reject_all_must_restore_the_baseline(tmp_path):
    """The gate that proves a batch is fully REVIEWABLE. If rejecting
    everything does not reproduce the baseline, something in the batch
    cannot be refused and the author's veto is not real."""
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("settled text"))))
    # a batch that rewrote the text WITHOUT marking it: the author can
    # reject every revision in the file and still not get their words
    # back, which is the whole failure this gate exists to catch
    lossy = write(tmp_path / "lossy.docx",
                  make_parts(para(run("quietly rewritten"))))
    report = revision.validate(lossy, baseline_path, use_word=False)
    assert report.reject_matches_baseline is False
    assert report.reject_detail["paragraphs"] is False
    assert not report.ok


def test_validate_reject_all_passes_on_a_faithful_batch(tmp_path):
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("settled text"))))
    faithful = write(tmp_path / "batch.docx", make_parts(
        para(run("settled text"), ins("added"))))
    report = revision.validate(faithful, baseline_path, use_word=False)
    assert report.reject_matches_baseline is True
    assert report.ok


def test_validate_fails_on_a_part_the_batch_lost(tmp_path):
    """The reject-all gate proves the TEXT round-trips; nothing proved
    the PACKAGE did. Word's Compare drops the customXml data store on
    every rebuild and `promote` copies the batch over working.docx, so
    the loss reaches the live manuscript with lint clean, validate
    PASSing and Word opening the file happily (2026-08-12)."""
    base_parts = make_parts(para(run("settled text")))
    base_parts["customXml/item1.xml"] = (
        b'<b:Sources xmlns:b="http://schemas.openxmlformats.org'
        b'/officeDocument/2006/bibliography"/>')
    base_parts["docProps/app.xml"] = b"<Properties/>"
    baseline_path = write(tmp_path / "prev.docx", base_parts)

    without = {k: v for k, v in base_parts.items()
               if not k.startswith(("customXml/", "docProps/"))}
    batch = write(tmp_path / "batch.docx", without)
    report = revision.validate(batch, baseline_path, use_word=False)
    # docProps is Word's own bookkeeping and says nothing
    assert report.lost_parts == ["customXml/item1.xml"]
    assert report.reject_matches_baseline is True, "the TEXT is intact"
    assert not report.ok


def test_validate_reject_all_counts_the_LINKS(tmp_path):
    """Rejecting a batch that deleted linked text gives the words back
    as PLAIN TEXT: Word's Compare does not rebuild a hyperlink inside a
    rejected deletion. Parental Style T4(3) came back 227 links against
    the baseline's 229 with reject-all reporting OK, `citations` ALL
    CHECKS PASSED (later mentions, so nothing dangled), and the author
    two links short with nothing anywhere saying so (2026-08-12)."""
    linked = ('<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
              "</w:r></w:hyperlink>")
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("see"), linked, run("for detail"))))
    # the same words, the link gone: every existing arm of the gate is
    # satisfied, because paragraphs and glyphs both compare TEXT
    unlinked = write(tmp_path / "batch.docx", make_parts(
        para(run("see"), run("Table 5"), run("for detail"))))
    report = revision.validate(unlinked, baseline_path, use_word=False)
    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.reject_detail["links"] is False
    assert not report.ok
    assert report.lost_links and "Table5" in report.lost_links[0]


def test_a_link_the_baseline_never_had_is_also_a_mismatch(tmp_path):
    """`was == now`, not `was <= now`. The multiset comparison has to
    fail in BOTH directions. `link_crossrefs` writes its hyperlinks
    UNTRACKED, so a batch run through it comes back from reject-all with
    links the baseline never had — same words, same paragraphs, and a
    document that is no longer the accepted truth. Under `<=` the gate
    calls the extra links fine and the batch becomes the new baseline
    with the untracked edit inside it."""
    plain = write(tmp_path / "prev.docx", make_parts(
        para(run("see"), run("Table 5"), run("for detail"))))
    # the same words, now linked, and nothing marking the change
    linked = write(tmp_path / "batch.docx", make_parts(
        para(run("see"),
             '<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
             "</w:r></w:hyperlink>",
             run("for detail"))))
    report = revision.validate(linked, plain, use_word=False)
    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.reject_detail["links"] is False
    assert not report.ok


def test_the_link_count_is_blind_to_which_FORM_a_link_takes(tmp_path):
    """Word rewrites a field into an element on every author save, so a
    gate that told the two apart would fail on a document nobody
    changed."""
    from docxkit.citations import hyperlink_field

    element = ('<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5</w:t>'
               "</w:r></w:hyperlink>")
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("see"), element)))
    as_field = write(tmp_path / "batch.docx", make_parts(
        para(run("see"), hyperlink_field("Table5", "Table 5"))))
    report = revision.validate(as_field, baseline_path, use_word=False)
    assert report.reject_detail["links"] is True, report.reject_detail


def test_validate_checks_footnotes_too(tmp_path):
    """A batch may be faithful in the body and lossy in a footnote."""
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("note")))))
    lossy = write(tmp_path / "batch.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("nope")))))
    report = revision.validate(lossy, baseline_path, use_word=False)
    assert report.reject_detail["footnotes"] is False
    assert not report.ok


# ----------------------------------- what gate 5 disagreed about --------
#
# `{'paragraphs': False, 'glyphs': False, 'footnotes': False} -> MISMATCH`
# is three booleans, and the decision waiting on them is whether the
# batch is salvageable or has to ship clean. Finding that out cost a
# bespoke difflib script on Parental Style, 2026-08-10.


def test_gate_5_names_the_paragraphs_it_disagrees_on(tmp_path):
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("settled one")) + para(run("settled two"))))
    lossy = write(tmp_path / "lossy.docx", make_parts(
        para(run("settled one")) + para(run("quietly rewritten"))))
    report = revision.validate(lossy, baseline_path, use_word=False)
    assert not report.ok
    got = report.reject_diff
    assert len(got) == 1, got
    assert got[0].part == "body" and got[0].index == 1
    assert got[0].baseline == "settled two"
    assert got[0].batch == "quietly rewritten"
    assert "quietly rewritten" in str(got[0])


def test_a_faithful_batch_is_asked_for_no_diagnosis(tmp_path):
    """The work only happens on failure — the gate runs on every batch."""
    baseline_path = write(tmp_path / "prev.docx",
                          make_parts(para(run("settled text"))))
    faithful = write(tmp_path / "batch.docx", make_parts(
        para(run("settled text"), ins("added"))))
    report = revision.validate(faithful, baseline_path, use_word=False)
    assert report.reject_diff == [] and report.moved_footnotes == []


def _notes(body: str, baseline_body: str):
    """(batch parts, baseline parts) differing only in footnote 2."""
    return (make_parts(para(run("body")), footnotes=footnotes_part(body)),
            make_parts(para(run("body")),
                       footnotes=footnotes_part(baseline_body)))


def test_a_moved_footnote_anchor_is_named(tmp_path):
    """Compare treats a re-anchored footnote as brand new: one w:ins over
    the whole body with no w:del. Accepting is right, rejecting empties
    it — and gate 5 could only say `footnotes: False`."""
    batch, base = _notes(para(ins("the note text")),
                         para(run("the note text")))
    assert revision.moved_footnotes(batch, base) == [2]
    # and the gate carries it through
    report = revision.validate(
        write(tmp_path / "batch.docx", batch),
        write(tmp_path / "prev.docx", base), use_word=False)
    assert report.reject_detail["footnotes"] is False
    assert report.moved_footnotes == [2], report.moved_footnotes
    # and it is the MEASURED one too, which is what gets warned about
    assert report.emptied_footnotes == [2], report.emptied_footnotes


def test_a_note_reject_all_RESTORES_is_not_warned_about(tmp_path):
    """The shape is necessary and not sufficient. `moved_footnotes`
    flags any definition carrying an insertion and no deletion — which
    includes a note the batch merely ADDED to, whose words rejecting
    puts back exactly.

    Warning on the shape printed "rejecting empties the note, so gate 5
    will fail on it" beside `'footnotes': True` in the same report, two
    lines apart. Measured twice on Aging_Well: 2026-09-03 footnote 2,
    when a batch added a note and pushed the later definitions down,
    and 2026-09-07 (R108) footnote 12, where no note was added at all —
    reference order `2..13` before and after, the note byte-identical,
    reject-all restoring it. Printed next to a genuine LINKS mismatch it
    reads as a second blocking finding, and the batch gets thrown away.

    The body edit here is untracked ON PURPOSE: gate 5 has to be red for
    a DIFFERENT reason, or the footnote lines are never reached."""
    batch, base = _notes(para(run("the note text"), ins("See also Kok.")),
                         para(run("the note text")))
    batch["word/document.xml"] = make_parts(
        para(run("body edited")))["word/document.xml"]

    report = revision.validate(write(tmp_path / "batch.docx", batch),
                               write(tmp_path / "prev.docx", base),
                               use_word=False)

    assert report.reject_matches_baseline is False, "gate 5 must be red"
    assert report.reject_detail["footnotes"] is True
    assert report.moved_footnotes == [2], "the shape is still reported"
    # the warning is raised from THIS, and the two cannot disagree
    assert report.emptied_footnotes == []


def test_the_footnote_warning_never_contradicts_the_footnotes_LAYER(tmp_path):
    """The invariant behind the entry, stated once: a report may not say
    a note will be emptied while its own reject-all measurement says
    every note came back."""
    for note_body, baseline_body in (
            (para(run("the note text"), ins("See also Kok.")),
             para(run("the note text"))),          # added to  -> restored
            (para(ins("the note text")),
             para(run("the note text")))):         # re-emitted -> emptied
        batch, base = _notes(note_body, baseline_body)
        batch["word/document.xml"] = make_parts(
            para(run("body edited")))["word/document.xml"]
        report = revision.validate(write(tmp_path / "b.docx", batch),
                                   write(tmp_path / "p.docx", base),
                                   use_word=False)

        if report.reject_detail["footnotes"]:
            assert report.emptied_footnotes == [], report.reject_detail
        else:
            assert report.emptied_footnotes, report.reject_detail


def test_a_moved_footnote_numbered_ONE_is_named_too():
    """`nid < 1` — the separator notes Word writes carry ids 0 and -1,
    and note 1 is a real footnote. Under `<= 1` a paper's FIRST note is
    the one finding this check cannot make, and it is the note most
    likely to move: the one on the title page or the first page of the
    text."""
    one = ('<?xml version="1.0"?><w:footnotes xmlns:w="http://schemas.'
           'openxmlformats.org/wordprocessingml/2006/main" xmlns:w14='
           '"http://schemas.microsoft.com/office/word/2010/wordml">'
           '<w:footnote w:id="1">{body}</w:footnote></w:footnotes>')
    batch = make_parts(para(run("body")),
                       footnotes=one.format(body=para(ins("the note text"))))
    base = make_parts(para(run("body")),
                      footnotes=one.format(body=para(run("the note text"))))

    assert revision.moved_footnotes(batch, base) == [1]


def test_an_ordinary_footnote_edit_is_not_called_a_moved_anchor():
    """Insertions AND deletions is someone editing the note, which
    rejects cleanly. Naming it would send a reader hunting for a moved
    reference that never moved."""
    batch, base = _notes(para(dele("old text") + ins("new text")),
                         para(run("old text")))
    assert revision.moved_footnotes(batch, base) == []


def test_a_genuinely_new_footnote_is_not_called_a_moved_anchor():
    """A note this batch ADDED is all insertion and no deletion too, and
    rejecting it is supposed to remove it. The baseline is what tells
    the two apart."""
    batch, base = _notes(para(ins("a brand new note")), para(run("")))
    assert revision.moved_footnotes(batch, base) == []


@pytest.mark.parametrize("baseline,batch", [
    ("body", "aaaa"),          # the batch sorts BEFORE the baseline
    ("body", "zzzz"),          # and after it
])
def test_gate_5_compares_for_EQUALITY_not_for_order(tmp_path, baseline,
                                                    batch):
    """`_paras(rejected) == _paras(base)` read as `>=` is True whenever
    the batch happens to sort later, so half of all lossy batches pass.
    The existing fixtures all sorted one way. This gate is what proves a
    batch is reviewable at all — a false OK here ships something the
    author cannot reject."""
    base = write(tmp_path / f"prev_{batch}.docx",
                 make_parts(para(run(baseline))))
    lossy = write(tmp_path / f"batch_{batch}.docx",
                  make_parts(para(run(batch))))
    report = revision.validate(lossy, base, use_word=False)
    assert report.reject_detail["paragraphs"] is False
    assert report.reject_detail["glyphs"] is False
    assert not report.ok


def test_gate_5_compares_the_FOOTNOTES_for_equality_too(tmp_path):
    base = write(tmp_path / "prev.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("aaa")))))
    lossy = write(tmp_path / "batch.docx", make_parts(
        para(run("body")), footnotes=footnotes_part(para(run("zzz")))))
    report = revision.validate(lossy, base, use_word=False)
    assert report.reject_detail["footnotes"] is False


def test_the_main_story_walk_does_not_stop_at_a_text_box(tmp_path,
                                                         monkeypatch):
    """The `continue` that skips a text box, read as `break`, ends the
    walk there — so every word AFTER the box vanishes from the stream
    and gate 6 reports a mismatch on a document with nothing wrong. The
    existing fixture put the box last, where the two are the same."""
    body = (para(run("Before the box."))
            + para(f"<w:r><w:pict><w:txbxContent>{para(run('BOXED'))}"
                   f"</w:txbxContent></w:pict></w:r>")
            + para(run("After the box.")))
    path = write(tmp_path / "box.docx", make_parts(body))
    rendered = _FakeDoc(revisions=0,
                        text="Before the box.\rAfter the box.\r")
    monkeypatch.setattr(revision._validate, "_word", _FakeWord(rendered))
    assert revision.validate(path).accept_paths_agree is True


def test_lint_catches_a_shell_that_already_exists(tmp_path):
    """The cheap gate gets there first, and aborts before Word."""
    body = f'<w:p><m:oMath {NS_M}><m:r><m:t></m:t></m:r></m:oMath></w:p>'
    report = revision.validate(write(tmp_path / "shell.docx",
                                     make_parts(body)), use_word=False)
    assert any("oMath" in problem for problem in report.lint)
    assert not report.ok


def test_validate_flags_shells_that_ACCEPTING_would_create(tmp_path,
                                                           monkeypatch):
    """The regression guard for a fix that has already been made once.

    A manuscript shipped visibly broken equations because the XML accept
    left empty OMML shells where Word's own accept prunes them. docxkit
    fixed that, and `revisions.accept` now prunes — so the only way to
    reach this branch is to break the fix, which is exactly what the
    fake below does. Lint cannot cover this: the shell does not exist in
    the file being linted, only in what accepting it would produce.
    """
    body = (f'<w:p><m:oMath {NS_M}>'
            f'<w:del w:id="77" w:author="R" w:date="2026-08-07T00:00:00Z">'
            f"<m:r><m:t>x</m:t></m:r></w:del></m:oMath></w:p>")
    path = write(tmp_path / "regressed.docx", make_parts(body))
    assert not revision.validate(path, use_word=False).lint

    def _accept_without_pruning(xml: str, **_kw: object) -> str:
        # the pre-fix behaviour: drop the deleted run, keep its parent
        return re.sub(r"<w:del\b.*?</w:del>", "", xml, flags=re.DOTALL)

    monkeypatch.setattr(revision.revisions, "accept",
                        _accept_without_pruning)
    report = revision.validate(path, use_word=False)
    assert report.empty_shells == 1
    assert not report.ok


def test_validate_compares_the_two_accept_paths(tmp_path, monkeypatch):
    """Accept can be simulated in XML or performed by Word, and the
    manuscript that shipped broken equations is what they disagreed on."""
    path = write(tmp_path / "x.docx", make_parts(
        para(run("kept", preserve=True), ins("added"))))
    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(text="keptadded")))
    report = revision.validate(path)
    assert report.accept_paths_agree is True
    assert report.ok

    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(text="something else")))
    disagree = revision.validate(path)
    assert disagree.accept_paths_agree is False
    assert not disagree.ok


def test_validate_folds_presentational_differences(tmp_path, monkeypatch):
    """Word returns U+2212 for the math minus and math letters from the
    Mathematical Italic block; the XML holds a hyphen and ASCII. Folding
    those is what stops every equation reporting a mismatch."""
    path = write(tmp_path / "m.docx", make_parts(para(run("a-b"))))
    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="a−b\r")))
    report = revision.validate(path)
    assert report.accept_paths_agree is True


def test_validate_folds_the_math_asterisk(tmp_path, monkeypatch):
    """Word sets an asterisk inside math as U+2217 ASTERISK OPERATOR, and
    NFKC leaves it alone — the two are distinct characters, not
    compatibility variants. LI7 writes "T*" eighteen times, so gate 6
    failed there on a file holding ZERO revisions."""
    path = write(tmp_path / "t.docx", make_parts(para(run("T* is the age"))))
    rendered = _FakeDoc(revisions=0, text="T∗ is the age\r")
    monkeypatch.setattr(revision._validate, "_word", _FakeWord(rendered))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_folds_the_derivative_prime(tmp_path, monkeypatch):
    """Word returns U+2032 PRIME where the XML stores U+0027 APOSTROPHE in
    derivative notation. Parental_style writes V', S' and a^E'(x) through
    its theory section, so gate 6 failed there on a file holding ZERO
    revisions — the same shape as the T* case."""
    path = write(tmp_path / "p.docx", make_parts(para(run("V' is the value"))))
    rendered = _FakeDoc(revisions=0, text="V′ is the value\r")
    monkeypatch.setattr(revision._validate, "_word", _FakeWord(rendered))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_still_sees_a_real_difference_in_math(tmp_path, monkeypatch):
    """The folds must not blind the gate: a character Word did not merely
    RENDER differently is still a mismatch."""
    path = write(tmp_path / "t.docx", make_parts(para(run("T* is the age"))))
    different = _FakeDoc(revisions=0, text="T+ is the age\r")
    monkeypatch.setattr(revision._validate, "_word", _FakeWord(different))
    assert revision.validate(path).accept_paths_agree is False


NS_WP = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
         'wordprocessingDrawing"')


def picture(kind: str = "inline") -> str:
    """A figure, inline (in the text stream) or anchored (floating)."""
    return (f"<w:r><w:drawing {NS_WP}><wp:{kind}>"
            f'<wp:extent cx="457200" cy="457200"/>'
            f"</wp:{kind}></w:drawing></w:r>")


def test_validate_counts_an_inline_figure_as_word_does(tmp_path,
                                                       monkeypatch):
    """Word's Range.Text puts a SOLIDUS where an inline drawing sits —
    measured, on a package whose only content was a picture and two
    letters. `_glyph` collected `w:t`/`m:t` and contributed nothing
    there, so gate 6 reported one difference per figure on a document
    holding ZERO revisions."""
    path = write(tmp_path / "fig.docx",
                 make_parts(para(run("A"), picture(), run("B"))))
    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="A/B\r")))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_gives_a_floating_figure_no_character(tmp_path,
                                                       monkeypatch):
    """The other half of the same measurement: an ANCHORED drawing is
    not in the text stream, and Word returns nothing for it. Emitting a
    placeholder for every `w:drawing` alike would fail here."""
    path = write(tmp_path / "float.docx",
                 make_parts(para(run("E"), picture("anchor"), run("F"))))
    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="EF\r")))
    assert revision.validate(path).accept_paths_agree is True


def test_validate_still_sees_a_slash_the_author_typed(tmp_path,
                                                      monkeypatch):
    """Why this is a placeholder and not a `_FOLD` entry: folding the
    solidus away would blind the gate to every "and/or" and every URL in
    the manuscript."""
    path = write(tmp_path / "s.docx", make_parts(para(run("and/or"))))
    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="and or\r")))
    assert revision.validate(path).accept_paths_agree is False


def test_validate_does_not_compare_a_text_box_against_the_body(tmp_path,
                                                               monkeypatch):
    """A text box is a separate STORY: its prose sits in document.xml
    like any other paragraph, and `doc.Paragraphs` does not walk it. Left
    in the stream, the gate reports a difference for every text box."""
    body = para(run("Body prose."),
                f"<w:r><w:pict><w:txbxContent>{para(run('BOXED'))}"
                f"</w:txbxContent></w:pict></w:r>")
    path = write(tmp_path / "box.docx", make_parts(body))
    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text="Body prose.\r")))
    assert revision.validate(path).accept_paths_agree is True


def test_reject_all_notices_a_figure_the_batch_dropped(tmp_path):
    """Gate 5 compares paragraph text and the glyph stream, and a lost
    figure changes neither — until the stream counts figures. The
    reject-all gate is what proves a batch is fully reviewable."""
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("A"), picture(), run("B"))))
    lost = write(tmp_path / "batch.docx", make_parts(para(run("A"), run("B"))))
    report = revision.validate(lost, baseline_path, use_word=False)
    assert report.reject_detail["paragraphs"] is True, "text alone is blind"
    assert report.reject_detail["glyphs"] is False
    assert not report.ok


@pytest.mark.parametrize("rendered", ["T+ is the age", "T( is the age"])
def test_gate_6_compares_for_EQUALITY_not_for_order(tmp_path, monkeypatch,
                                                    rendered):
    """`_norm(...) == _norm(...)` read as `>=` is True whenever the XML
    side happens to sort later, so half of all real disagreements pass.
    The one existing mismatch fixture sorted the other way — these two
    put the XML on both sides of Word's answer."""
    path = write(tmp_path / "t.docx", make_parts(para(run("T* is the age"))))
    monkeypatch.setattr(revision._validate, "_word",
                        _FakeWord(_FakeDoc(revisions=0, text=rendered)))
    assert revision.validate(path).accept_paths_agree is False


def test_validate_skips_word_when_asked(tmp_path, monkeypatch):
    path = write(tmp_path / "x.docx", make_parts(para(run("x"))))
    monkeypatch.setattr(revision._validate, "_word", _FakeWord(explode=True))
    report = revision.validate(path, use_word=False)
    assert report.word_opened is None
    assert report.ok


def test_validate_does_not_accept_in_a_file_word_has_open(tmp_path,
                                                          monkeypatch):
    """AcceptAllRevisions on the author's own open window would rewrite
    what they are looking at."""
    path = write(tmp_path / "x.docx", make_parts(para(run("x"))))
    doc = _FakeDoc()
    monkeypatch.setattr(revision._validate, "_word", _FakeWord(doc))
    monkeypatch.setattr(revision.package, "is_locked", lambda _p: True)
    revision.validate(path)
    assert not doc.accepted


def test_exit_codes_are_distinct():
    """A caller must be able to tell WHICH refusal it hit without
    parsing English.

    These five numbers are a contract with things outside this package:
    the paper projects' scripts branch on them, `docxkit revision
    status` documents 1 for pending and 4 for a stale baseline in its
    own `--help`, and `cli.main` exits with whatever the exception
    carries. A renumbering is invisible here and wrong out there.
    """
    from docxkit.errors import HandbackLoss

    assert ProtocolError.exit_code == 1
    assert MathResolved.exit_code == 2
    assert BaselinePending.exit_code == 3
    assert StaleBatch.exit_code == 4
    assert HandbackLoss.exit_code == 5

    codes = [cls.exit_code for cls in (ProtocolError, MathResolved,
                                       BaselinePending, StaleBatch,
                                       HandbackLoss)]
    assert len(set(codes)) == len(codes), "two refusals cannot share one"
    assert 0 not in codes, "0 is success; a refusal that exits 0 is silent"


def test_document_helper_is_used():
    """conftest.document is the fixture builder these tests lean on."""
    assert "<w:body>" in document("")


def test_a_rescue_that_did_not_land_stops_the_promote(project,
                                                      monkeypatch):
    """The guard that makes the undo real. If the rescue copy is not
    what it was copied from, overwriting the manuscript would leave
    nothing to undo it with — so the promote refuses instead."""
    write(project.batch, make_parts(para(run("the batch"))))
    live_before = project.working.read_bytes()

    def truncating_copy(src, dst, *a, **kw):
        Path(dst).write_bytes(b"truncated")
        return dst

    monkeypatch.setattr(revision.shutil, "copy2", truncating_copy)
    with pytest.raises(ProtocolError, match="nothing to undo it"):
        revision.promote(project)
    assert project.working.read_bytes() == live_before, \
        "the manuscript was overwritten despite a bad rescue"


def test_rescue_names_cannot_be_exhausted_silently(project, monkeypatch):
    """Bounded, and it says so rather than looping forever. Forced here
    by coarsening the stamp so every candidate collides."""
    project.rescue_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(revision._promote, "_RESCUE_STAMP", "%Y%m%d")
    taken = revision.rescue_path(project, datetime(2026, 8, 7))
    taken.write_bytes(b"x")
    with pytest.raises(ProtocolError, match="no free rescue name"):
        revision.rescue_path(project, datetime(2026, 8, 7))


# ------------------------- what a redline cannot carry, and what it is not

def test_a_bookmark_the_clean_edit_removed_is_reported_as_restored():
    """Compare carries bookmarks over from the ORIGINAL side, so a
    deletion made in the clean copy is silently undone — and nothing in
    the counts shows it, because a bookmark is not tracked content. The
    orphan `Lari2023` survived two full rounds that way."""
    marked = ('<w:bookmarkStart w:id="4" w:name="Lari2023"/>'
              '<w:bookmarkEnd w:id="4"/>')
    baseline = make_parts(para(marked + run("Lari, A. (2023). Title.")))
    clean = make_parts(para(run("Lari, A. (2023). Title.")))
    built = make_parts(para(marked + run("Lari, A. (2023). Title.")))
    assert revision.restored_bookmarks(baseline, clean, built) == ["Lari2023"]


def test_a_bookmark_the_clean_edit_kept_is_not_reported():
    marked = ('<w:bookmarkStart w:id="4" w:name="Lari2023"/>'
              '<w:bookmarkEnd w:id="4"/>')
    parts = make_parts(para(marked + run("Lari, A. (2023). Title.")))
    assert revision.restored_bookmarks(parts, parts, parts) == []


def test_words_own_navigation_bookmarks_are_not_reported():
    """`_Toc` and `_Heading` names are Word's, they come and go on every
    save, and a report full of them is a report nobody reads."""
    tocd = ('<w:bookmarkStart w:id="4" w:name="_Toc12345"/>'
            '<w:bookmarkEnd w:id="4"/>')
    baseline = make_parts(para(tocd + run("A heading")))
    clean = make_parts(para(run("A heading")))
    assert revision.restored_bookmarks(baseline, clean, baseline) == []


def test_build_refuses_to_read_the_path_it_writes(project, monkeypatch):
    """`build/batch.docx` is where a batch is STAGED, and the provenance
    stamp beside it is how `guard.check` tells "docxkit wrote this" from
    "someone edited it in Word". A hand-built clean edit written there
    made the build refuse its own output as modified, and the message
    named a Word session that never happened."""
    write(project.batch, make_parts(para(run("a hand-built clean edit"))))
    monkeypatch.setattr(revision.tracked, "build", _FakeBuild())
    with pytest.raises(ProtocolError, match="STAGES its output"):
        revision.build(project, project.batch)


def test_build_says_which_bookmark_compare_put_back(project, monkeypatch):
    """The build-time half: said before the handback, where the author
    can still be told the deletion has to wait for the promote."""
    marked = ('<w:bookmarkStart w:id="4" w:name="Lari2023"/>'
              '<w:bookmarkEnd w:id="4"/>')
    base = make_parts(para(marked + run("Lari, A. (2023).")))
    write(project.prev, base)
    write(project.working, base)        # at build time the two agree
    clean = project.build_dir / "clean.docx"
    write(clean, make_parts(para(run("Lari, A. (2023)."))))
    # the fake stands in for Compare, and Compare's behaviour here IS
    # the bug: it writes the baseline's bookmarks back out
    monkeypatch.setattr(
        revision.tracked, "build",
        _FakeBuild(out_text="Lari, A. (2023).", extra=marked))
    seen: list[str] = []
    revision.build(project, clean, progress=seen.append)
    said = "\n".join(seen)
    assert "Lari2023" in said and "AFTER the promote" in said


def test_a_bookmark_the_BUILD_invented_is_not_the_authors_deletion():
    """"in the build, not in the clean edit" also describes a name Word
    minted during the compare. Reporting that as a deletion the author
    made sends them looking for an edit that never happened, so the
    baseline is what decides."""
    minted = ('<w:bookmarkStart w:id="4" w:name="Compare_Mint1"/>'
              '<w:bookmarkEnd w:id="4"/>')
    baseline = make_parts(para(run("Lari, A. (2023). Title.")))
    clean = make_parts(para(run("Lari, A. (2023). Title.")))
    built = make_parts(para(minted + run("Lari, A. (2023). Title.")))
    assert revision.restored_bookmarks(baseline, clean, built) == []


# ------------------------------------- the gate that could not be passed --

#: LI7 2026-08-15, BLOCKING. Gate D4 split section 6 in two, so footnote
#: 13's cross-reference "throughout Sections 4-6" became "4-7" — one
#: character in a 489-character note. The loss check compared note TEXT,
#: so the old wording had "vanished"; `baseline` refused to record a
#: manuscript that had lost nothing, and every documented form of
#: --accept-loss came back "has NOT lost" about the same string. The
#: refusal path and the exemption path were computing "lost" differently
#: and between them there was no way through.

_NOTE = ("For interpretability, empirical LII and LBI values throughout "
         "Sections 4{}6 are reported on the same scale as the headline "
         "index, so a reader comparing two panels is comparing like with "
         "like rather than two normalisations of the same quantity.")


def _with_note(text: str) -> dict[str, bytes]:
    return make_parts(para(run("body "), _ref(13)),
                      footnotes=notes("footnotes", note(text, nid=13)))


def _ref(nid: int) -> str:
    return f'<w:r><w:footnoteReference w:id="{nid}"/></w:r>'


def test_an_EDITED_footnote_is_not_a_lost_one(project):
    """A note is prose an author edits. Its identity is its REFERENCE,
    which is still in the body — not its text, which is the thing that
    changed."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, _with_note(_NOTE.format("–7")))

    assert revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev)) == []
    revision.baseline(project)          # the whole point: it goes through
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_a_note_that_really_went_is_still_caught(project):
    """The fix must not switch the gate off: fewer notes than before,
    with a reference gone, is still a loss."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))
    assert [loss.kind for loss in lost] == ["footnote"]
    with pytest.raises(HandbackLoss):
        revision.baseline(project)


def test_the_exemption_accepts_the_words_the_refusal_PRINTED(project):
    """A hatch that will not accept the message's own words is not a
    hatch. The refusal truncates for readability; the flag must take
    that truncation."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))

    with pytest.raises(HandbackLoss) as exc:
        revision.baseline(project)
    shown = re.search(r"--accept-loss '([^']+)'", str(exc.value))
    assert shown is not None, str(exc.value)

    revision.baseline(project, accept_loss=(shown.group(1),))
    assert project.prev.read_bytes() == project.working.read_bytes()


def test_a_PREFIX_of_the_loss_identifies_it(project):
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))
    revision.baseline(project, accept_loss=("footnote:For interpretability",))
    assert project.prev.read_bytes() == project.working.read_bytes()



# ---------------------------------------------- naming the glyph that moved --
#
# The glyph gate compared two streams of 68,829 characters and answered
# `glyphs: False`. On AFI the answer was TWO characters — a minus sign
# Word's Compare had rewritten as a hyphen inside an Appendix equation —
# and finding them took a bespoke difflib script over private imports,
# three builds after the gate first went red.

def test_two_identical_streams_have_nothing_to_report():
    """Built at run time, not written twice: two equal literals in one
    module are ONE object, and `before == after` read as `is` passes on
    a fixture like that while sending every clean build of a real
    manuscript through difflib over tens of thousands of characters to
    be told nothing."""
    before = " ".join(["the", "same"])
    after = " ".join(["the", "same"])
    assert before is not after and before == after

    assert glyph_runs(before, after) == []


def test_two_identical_streams_are_not_DIFFED_at_all(monkeypatch):
    """`before == after` read as `is` gives the same ANSWER — difflib
    over two identical strings reports nothing either way — so the count
    is the assertion, as it is for `_Layout.find`'s empty range.

    What it costs: the glyph gate compares two streams of 68,829
    characters, and it runs on every clean build. The streams come out
    of two documents, so they are never one object."""
    calls: list[int] = []
    real = revision._losses.SequenceMatcher

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(revision._losses, "SequenceMatcher", spy)
    before = " ".join(["the", "same"])
    after = " ".join(["the", "same"])

    assert glyph_runs(before, after) == []
    assert calls == [], "the equal streams were diffed anyway"

    assert glyph_runs(before, after + "!") != []
    assert calls == [1], "and a real difference still is"


def test_a_config_at_the_project_ROOT_roots_where_it_stands(tmp_path):
    """`config.parent.name == _DIR`, and this is its `else`. `init`
    writes `revision/paper.toml`, so every fixture in this file takes
    the first branch — but `find_config` looks for `paper.toml` at the
    top of the project too, and a paper that keeps it there is rooted
    where it stands rather than one level up.

    Read as `is not`, the two branches swap: the ordinary layout
    survives it by accident, because `Path.name` is a slice of the path
    string and never the module's own literal, so identity answers the
    same as equality there. This layout is where the accident runs
    out — the root comes back as the directory ABOVE the project, and
    every path in the config resolves outside it."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "manuscript.docx",
                make_parts(para(run("The paper."))))
    paper = revision.init(tmp_path / "proj", src)
    assert paper.config.parent.name == "revision", "the default layout"

    at_root = paper.root / "paper.toml"
    at_root.write_text(paper.config.read_text(encoding="utf-8"),
                       encoding="utf-8")
    paper.config.unlink()

    moved = revision.load_paper(at_root)

    assert moved.root == paper.root
    assert moved.working == paper.working
    assert moved.working.exists()


def test_a_swapped_MINUS_is_named_with_its_code_points():
    """The finding, exactly as it happened: a hyphen-minus and a minus
    sign print identically at 10pt, so the characters have to be spelled
    out or the reader learns nothing they did not already know."""
    was = "AFIi,2020 − AFIi,1990"
    now = "AFIi,2020 - AFIi,1990"

    run, = glyph_runs(was, now)

    assert "U+2212" in run and "U+002D" in run
    assert run.startswith("at 10: ")


def test_the_offset_is_the_BASELINE_stream_not_the_batch():
    """One number, and it has to mean one document: the baseline is the
    reference the batch is being held against, so it is the side both
    the offset and the quoted context come from."""
    was = "the estimator is − 0.15"
    now = "in fact the estimator is - 0.15"

    _inserted, swapped = glyph_runs(was, now)

    # 17 in the baseline, 25 in the batch, which now opens with 8 more
    # characters — and the reader is holding the baseline
    assert swapped.startswith("at 17: ")
    assert swapped.endswith("after ...the estimator is ")


def test_a_run_says_WHERE_it_is_by_quoting_what_precedes_it():
    """An offset into a 68,000-character stream is not a location a
    reader can act on; the words before it are."""
    was = "in the pooled sample the estimator is − 0.15 everywhere"
    now = "in the pooled sample the estimator is - 0.15 everywhere"

    run, = glyph_runs(was, now)

    lead = run.split("after ...")[1]
    assert lead == "he pooled sample the estimator is "[-24:]
    assert len(lead) == 24              # twenty-four characters of it


def test_the_quoted_CONTEXT_reads_as_one_line():
    """The glyph stream is the whole document run together, so the
    characters before a run routinely include a paragraph break; left
    raw it breaks the report into pieces that no longer line up."""
    was = "para one\nthe value is − 0.15"
    now = "para one\nthe value is - 0.15"

    run, = glyph_runs(was, now)

    assert "\n" not in run
    assert run.endswith("after ...para one the value is ")


def test_a_LONG_changed_run_is_cut_not_dumped():
    """A batch that really did lose a paragraph would otherwise print
    the paragraph, once per gate, above the instruction that matters."""
    was = "keep " + "a long stretch of prose that vanished " * 3 + "keep"
    now = "keep keep"

    run, = glyph_runs(was, now)

    assert run.count("...") >= 1
    assert len(run) < 120


def test_the_number_of_runs_is_CAPPED_and_the_rest_counted():
    was = "".join(f"{i}x" for i in range(20))
    now = "".join(f"{i}y" for i in range(20))

    runs = glyph_runs(was, now, limit=3)

    assert len(runs) == 4
    assert runs[-1] == "... and 17 more run(s)"


def test_a_CHARACTER_COUNT_is_not_printed_for_a_long_run():
    """Code points are printed for short runs only — four or fewer.
    Spelling out a hundred of them is the dump this avoids."""
    runs = glyph_runs("abcdefgh", "")

    assert "U+" not in runs[0]


def test_an_INSERTED_run_reports_an_empty_left_side():
    runs = glyph_runs("ab", "aXb")

    assert runs[0].startswith("at 1: '' -> 'X' U+0058")


# --- what the revision.py run of 2026-08-18 found -----------------------
#
# `_shown` had 4 survivors, all on its two thresholds. It is the half of
# a glyph report a reader acts on — the characters themselves, and their
# code points when the run is short enough for them to mean anything —
# and the tests above only ever gave it a one-character run, where every
# threshold agrees.


def test_a_run_is_quoted_whole_at_TWELVE_characters_and_cut_after():
    """Twelve is what fits beside the offset and the context on one
    line, and the cut has to be visible: a run quoted whole that is not
    whole tells a reader the difference is shorter than it is."""
    def quoted(n: int) -> str:
        was = "a" * n + " tail"
        return glyph_runs(was, was.upper())[0]

    assert "'" + "a" * 12 + "'" in quoted(12), "twelve is not cut"
    assert "'" + "a" * 12 + "...'" in quoted(13)
    assert "a" * 13 not in quoted(13)


def test_the_CODE_POINTS_are_printed_only_for_a_short_run():
    """A hyphen-minus and a MINUS SIGN print identically at 10pt, so for
    a run of one or two characters the code points ARE the finding. Past
    four they are a wall of hex either side of an arrow, and the
    characters are legible on their own."""
    four = glyph_runs("abcd tail", "wxyz tail")[0]
    five = glyph_runs("abcde tail", "vwxyz tail")[0]

    assert "U+0061 U+0062 U+0063 U+0064" in four
    assert "U+0077" in four, "and for the batch's side too"
    assert "U+" not in five


def test_nothing_is_spelled_out_for_a_run_with_no_characters():
    """`0 < len(cut)`: an insertion has an empty side, and `U+` with
    nothing after it is a report of a character that is not there."""
    (run,) = glyph_runs("the value is 0.15", "the value is − 0.15")

    assert "'' ->" in run, "the empty side spells out nothing at all"
    assert run.count("U+") == 2, "and the two characters added do"


def test_validate_reject_all_counts_the_STRUCTURE(tmp_path):
    """The fifth thing gate 5 compares, and the one it was blind to on
    the DSI round of 2026-08-19: a table DUPLICATED by a move (27 -> 28
    in the accepted and the rejected view alike), a moved paragraph's
    three citation bookmarks dropped on reject (127 -> 125), and a
    destroyed section break. None of them is a character, so paragraphs,
    glyphs, footnotes and links all said yes.

    The fixture is the same words in a different carrier: one paragraph
    of prose, wrapped in a table. Every text arm of the gate passes."""
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("The index rose to 0.35 in 2024."))))
    in_a_table = write(tmp_path / "batch.docx", make_parts(
        "<w:tbl><w:tr><w:tc>"
        + para(run("The index rose to 0.35 in 2024."))
        + "</w:tc></w:tr></w:tbl>"))

    report = revision.validate(in_a_table, baseline_path, use_word=False)

    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.reject_detail["links"] is True
    assert report.reject_detail["structure"] is False
    assert not report.ok
    assert report.structure_diff == ["tbl: 0 -> 1", "tr: 0 -> 1",
                                     "tc: 0 -> 1"]


def test_the_structure_gate_names_a_BOOKMARK_the_reject_dropped(tmp_path):
    """The second casualty of the same mechanism: a moved paragraph
    carrying three citation anchors comes back through Compare with the
    anchors gone. `reject-all == baseline` passed, and the paper's
    `require_reject_all_equals_baseline` was satisfied by a document
    that does not reproduce the baseline."""
    anchored = ('<w:bookmarkStart w:id="9" w:name="Moran1950"/>'
                + run("Moran (1950)") + '<w:bookmarkEnd w:id="9"/>')
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("As ", preserve=True), anchored,
             run(" showed.", preserve=True))))
    stripped = write(tmp_path / "batch.docx", make_parts(
        para(run("As ", preserve=True), run("Moran (1950)"),
             run(" showed.", preserve=True))))

    report = revision.validate(stripped, baseline_path, use_word=False)

    assert report.reject_detail["paragraphs"] is True
    assert report.reject_detail["glyphs"] is True
    assert report.structure_diff == ["bookmarkStart: 1 -> 0"]


def test_the_structure_gate_is_blind_to_which_FORM_a_link_takes(tmp_path):
    """`w:hyperlink` is deliberately NOT counted. Word rewrites a
    caption's HYPERLINK FIELD into an element on an ordinary edit — DSI
    saw 16 -> 17 with nothing lost — and a gate that counted elements
    would fail on that. `_links` compares (anchor, label) across both
    forms, which is the comparison that means something."""
    from docxkit.citations import hyperlink_field
    baseline_path = write(tmp_path / "prev.docx", make_parts(
        para(run("see ", preserve=True),
             hyperlink_field("Table5", "Table 5"))))
    as_element = write(tmp_path / "batch.docx", make_parts(
        para(run("see ", preserve=True),
             '<w:hyperlink w:anchor="Table5">' + run("Table 5")
             + "</w:hyperlink>")))

    report = revision.validate(as_element, baseline_path, use_word=False)

    assert report.reject_detail["structure"] is True
    assert report.reject_detail["links"] is True


# --- what the loss walk COUNTS (2026-08-19) -----------------------------
#
# `losses` is the gate between a hand-back and the baseline, and its
# arithmetic had 11 survivors across `losses` and `_lost_notes`. The
# tests above ask whether the gate fires, which is the right question
# and answers only half of it: a gate that fires on the right document
# and says the wrong thing about it sends a person looking for a note
# that never went.

def _notes_doc(*texts: str, refs: int = 0) -> dict[str, bytes]:
    """A body carrying `refs` markers and one footnote per text."""
    body = "".join(_ref(i + 13) for i in range(refs or len(texts)))
    return make_parts(
        para(run("body "), body),
        footnotes=notes("footnotes", *(note(t, nid=i + 13)
                                       for i, t in enumerate(texts))))


def test_two_notes_gone_and_one_of_them_UNNAMEABLE_says_so(project):
    """`len(named) < gone`, and the count in the sentence. Two notes of
    the same wording — "Ibid." is the ordinary one — cannot be told
    apart by text, so when one of them goes the walk can name the OTHER
    loss and only count this one. Saying "1 more, unnamed" and giving
    both totals is what lets a person check by hand; naming a note that
    is still there sends them looking for it."""
    write(project.prev, _notes_doc("Ibid.", "Ibid.", "A note that went."))
    write(project.working, _notes_doc("Ibid."))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [loss.what for loss in lost] == [
        "A note that went.",
        "1 more, unnamed — 3 footnotes before, 1 now"]


# --- a RE-LABELLED link is not a lost one (BACKLOG S3, 2026-08-19) ------
#
# `_links` keys a link by the (anchor, label) pair, which is right for
# finding a link Word ate and wrong for an author's own edit of the
# visible text. DSI's R24.1 re-labelled four back-link fields on purpose
# and `baseline` refused four legitimate edits; the paper passed
# --accept-loss four times after checking each anchor by hand. A gate
# that refuses a correct edit teaches the person to wave it through.


def _linked(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}">' + run(label)
            + "</w:hyperlink>")


def test_editing_a_links_VISIBLE_TEXT_is_not_a_loss(tmp_path):
    """The anchor is untouched and still linked, so nothing was lost —
    and `baseline` must not refuse. What changed is reported in its own
    right, because a label that moved is worth seeing."""
    before = write(tmp_path / "prev.docx", make_parts(
        para(run("As "), _linked("UnitedNations2026", "UN 2026"),
             run(" reports."))))
    after = write(tmp_path / "working.docx", make_parts(
        para(run("As "),
             _linked("UnitedNations2026", "United Nations 2026"),
             run(" reports."))))

    lost = revision.losses(package.read_parts(after),
                           package.read_parts(before))
    (change,) = revision.relabelled_links(package.read_parts(after),
                                          package.read_parts(before))

    assert lost == [], lost
    assert change.anchor == "UnitedNations2026"
    assert (change.was, change.now) == ("UN 2026", "United Nations 2026")
    assert "->" in str(change)


def test_a_link_whose_ANCHOR_stopped_being_linked_is_still_a_loss(tmp_path):
    """The half the gate was built for, and the half that still blocks:
    Word collapsed a paragraph to make an edit and the hyperlink went
    with it. Nothing links that anchor any more, so there is no
    re-labelling to explain it."""
    before = write(tmp_path / "prev.docx", make_parts(
        para(run("As "), _linked("UnitedNations2026", "UN 2026"),
             run(" reports."))))
    after = write(tmp_path / "working.docx", make_parts(
        para(run("As UN 2026 reports."))))

    lost = revision.losses(package.read_parts(after),
                           package.read_parts(before))

    assert [loss.kind for loss in lost] == ["link"]
    assert "UnitedNations2026" in lost[0].what
    assert revision.relabelled_links(package.read_parts(after),
                                     package.read_parts(before)) == []
    # and the words ARE still there, which is what makes it repairable
    assert lost[0].words is True


def test_a_link_whose_WORDS_went_too_is_marked_apart_from_one_Word_ate(
        tmp_path):
    """The two causes a lost link has, and they need opposite actions.
    Word collapsing a paragraph strips the hyperlink and keeps the
    words, so the link can be rebuilt. An author deleting the sentence
    takes the words with it, and there is nothing to put back.

    Reported as one list under one explanation — "the words all survive,
    so no content layer above shows it" — every clause of which is false
    of the second kind, while the deletion sits in the same report's own
    text section a few lines up. Measured 2026-09-08 on Aging_Well: 4 of
    each kind and 5 of the other in one ingest, indistinguishable."""
    before = write(tmp_path / "prev.docx", make_parts(
        para(run("As "), _linked("UnitedNations2026", "UN 2026"),
             run(" reports, and "), _linked("Cox1987", "Cox (1987)"),
             run(" agrees."))))
    after = write(tmp_path / "working.docx", make_parts(
        para(run("As UN 2026 reports."))))

    lost = revision.losses(package.read_parts(after),
                           package.read_parts(before))
    words = {loss.what.split(" (")[0]: loss.words for loss in lost}

    assert words["UnitedNations2026"] is True    # link eaten, words kept
    assert words["Cox1987"] is False             # the clause was cut


def test_a_link_LOST_beside_one_re_labelled_is_still_counted(tmp_path):
    """Paired off one for one. An anchor linked TWICE that comes back
    once has lost a link, however the survivor is now labelled — read
    the other way, a re-label would absorb the loss and the paragraph
    Word ate would go unreported."""
    before = write(tmp_path / "prev.docx", make_parts(
        para(run("As "), _linked("Table5", "Table 5"), run(" and "),
             _linked("Table5", "the table"), run(" show."))))
    after = write(tmp_path / "working.docx", make_parts(
        para(run("As "), _linked("Table5", "Table 5 (revised)"),
             run(" shows."))))

    lost = revision.losses(package.read_parts(after),
                           package.read_parts(before))
    relabelled = revision.relabelled_links(package.read_parts(after),
                                           package.read_parts(before))

    assert len(relabelled) == 1, relabelled
    assert [loss.kind for loss in lost] == ["link"], lost


def test_baseline_does_not_refuse_a_re_labelled_link(project):
    """The refusal is the whole point of the split: this is the run DSI
    had to talk past with --accept-loss."""
    write(project.prev, make_parts(
        para(run("As "), _linked("UnitedNations2026", "UN 2026"),
             run(" reports."))))
    write(project.working, make_parts(
        para(run("As "),
             _linked("UnitedNations2026", "United Nations 2026"),
             run(" reports."))))

    assert revision.baseline(project).prev == project.prev


def test_notes_ADDED_while_others_are_reworded_are_not_losses(project):
    """`gone <= 0` — the walk runs only when there are FEWER notes than
    before. An author who rewords three notes and adds a fourth has lost
    nothing, and every reworded note matches nothing by text: under
    `== 0` the walk proceeds on a negative count and reports two of the
    three rewordings as vanished notes, which refuses the baseline."""
    write(project.prev, _notes_doc("First note.", "Second note.",
                                   "Third note."))
    write(project.working, _notes_doc("First note, edited.",
                                      "Second note, edited.",
                                      "Third note, edited.", "A fourth."))

    assert revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev)) == []


def test_a_bookmark_that_SURVIVED_is_not_reported_as_lost(project):
    """`_bookmarks(prev) - _bookmarks(working)`, not `&`: the difference
    is what went, the intersection is what stayed, and the two are the
    same size whenever exactly one of two bookmarks goes."""
    def _marked(*names: str) -> dict[str, bytes]:
        marks = "".join(f'<w:bookmarkStart w:id="{i}" w:name="{n}"/>'
                        f'<w:bookmarkEnd w:id="{i}"/>'
                        for i, n in enumerate(names, start=20))
        return make_parts(para(marks, run("body")))

    write(project.prev, _marked("Kept2020", "Gone2019"))
    write(project.working, _marked("Kept2020"))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [(loss.kind, loss.what) for loss in lost] == [
        ("bookmark", "Gone2019")]


def test_the_number_of_comments_lost_is_the_DIFFERENCE(project):
    """`before - after`, and the message carries the number. Three
    comments against one is two gone; `^` makes it 2 as well on some
    pairs and 4 on others, and nothing but the sentence says which."""
    def _commented(n: int) -> dict[str, bytes]:
        return make_parts(
            para(run("body")),
            comment_items=tuple(comment(i, f"note {i}",
                                        para_id=f"AAAA{i:04d}")
                                for i in range(1, n + 1)))

    write(project.prev, _commented(3))
    write(project.working, _commented(1))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [(loss.kind, loss.what) for loss in lost] == [
        ("comment", "2 comment(s) gone")]


def test_ONE_comment_lost_is_a_loss(project):
    """`> 0`, not `> 1`. One is the ordinary number to lose — a comment
    Word drops while its anchor is being edited — and a threshold of two
    lets it through the gate that makes the baseline permanent."""
    def _commented(n: int) -> dict[str, bytes]:
        return make_parts(
            para(run("body")),
            comment_items=tuple(comment(i, f"note {i}",
                                        para_id=f"AAAA{i:04d}")
                                for i in range(1, n + 1)))

    write(project.prev, _commented(2))
    write(project.working, _commented(1))

    lost = revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev))

    assert [(loss.kind, loss.what) for loss in lost] == [
        ("comment", "1 comment(s) gone")]


def test_comments_ADDED_are_not_a_loss(project):
    """`> 0`, not `!= 0`: an author who answers a query by adding a
    comment would otherwise be told "-1 comment(s) gone" and refused."""
    def _commented(n: int) -> dict[str, bytes]:
        return make_parts(
            para(run("body")),
            comment_items=tuple(comment(i, f"note {i}",
                                        para_id=f"AAAA{i:04d}")
                                for i in range(1, n + 1)))

    write(project.prev, _commented(1))
    write(project.working, _commented(3))

    assert revision.losses(package.read_parts(project.working),
                           package.read_parts(project.prev)) == []


def test_a_loss_PRINTS_the_first_seventy_characters_of_what_went():
    """The refusal lists them one per line, and the exemption flag takes
    the message's own words — so the cut is part of the contract with
    the person reading it, not a display detail."""
    long_note = ("The normalisation is by the sample mean rather than by "
                 "the base year, so the two panels are comparable.")

    printed = str(revision.Loss("footnote", long_note))

    assert printed == (
        "footnote 'The normalisation is by the sample mean rather than by "
        "the base year, '")


def test_the_printed_token_is_the_first_SIXTY_characters_of_the_key(project):
    """The refusal prints a token a person can paste back, and it has to
    be short enough to read on the line it shares with the loss. The
    test above reads the token out of the message and feeds it back,
    which is self-consistent whatever the cut is — this one says where
    the cut is."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))

    with pytest.raises(HandbackLoss) as exc:
        revision.baseline(project)

    shown = re.search(r"--accept-loss '([^']+)'", str(exc.value))
    assert shown is not None, str(exc.value)
    assert shown.group(1) == (
        "footnote:For interpretability, empirical LII and LBI values ")


@pytest.mark.parametrize("token", ["aaa-not-this-loss", "zzz-not-this-loss"])
def test_an_exemption_that_names_NOTHING_does_not_pass_a_real_loss(
        project, token):
    """`token == candidate or candidate.startswith(token) or
    token.startswith(candidate)` — three ways of matching, and the first
    is subsumed by the other two. What it must never be is an ORDER
    comparison: under `>=` any token sorting above the loss's key names
    it and under `<=` any token below does, so `--accept-loss` with a
    typo in it acknowledges a lost footnote and the baseline goes
    through. Both directions, because one wrong token can only be on one
    side of the key.

    A stale exemption that reads as a live one is the failure this
    refusal exists to prevent, in its worst form: the flag is misspelled
    and the gate opens."""
    write(project.prev, _with_note(_NOTE.format("–6")))
    write(project.working, make_parts(para(run("body")),
                                      footnotes=notes("footnotes")))
    before = project.prev.read_bytes()

    with pytest.raises(HandbackLoss):
        revision.baseline(project, accept_loss=(token,))

    assert project.prev.read_bytes() == before

# --- the eye gate over a BATCH (BACKLOG S4, 2026-08-19) -----------------


def _pdf_of(text: str, path: Path) -> Path:
    """A one-page PDF carrying `text` — what Word would have rendered."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 200), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def test_render_accepted_renders_the_ACCEPTED_view(tmp_path, monkeypatch):
    """Accepted, never the redline: the page a reader will see is the
    accepted one, and a redline's pagination is not the deliverable's.
    The fake stands in for Word and renders whatever it was handed, so
    what reaches it is the assertion — the insertion's words, with no
    deletion left in."""
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("Employment rises "), ins("sharply"), dele("a little"))))
    seen: dict[str, str] = {}

    def fake_export(path, out_pdf, **kw):
        seen["text"] = "".join(
            re.findall(r"<w:t[^>]*>([^<]*)</w:t>",
                       package.read_parts(path)["word/document.xml"]
                       .decode("utf-8")))
        return _pdf_of(seen["text"], Path(out_pdf))

    monkeypatch.setattr("docxkit.word.export_pdf", fake_export)

    made = revision.render_accepted(batch, ["Employment rises sharply"],
                                    dpi=40)

    assert seen["text"] == "Employment rises sharply", seen
    (png,) = made.values()
    assert png is not None and png.exists()
    assert png.parent == tmp_path, "beside the batch by default"
    assert png.name.startswith("batch__p"), png.name


def test_render_accepted_cleans_up_after_itself(tmp_path, monkeypatch):
    """The accepted copy and the PDF are scratch; the PNGs are the
    answer. A gate that leaves two files per run beside a paper's batch
    is one somebody turns off."""
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("Employment rises "), ins("sharply"))))

    def fake_export(path, out_pdf, **kw):
        return _pdf_of("Employment rises sharply", Path(out_pdf))

    monkeypatch.setattr("docxkit.word.export_pdf", fake_export)

    revision.render_accepted(batch, ["Employment rises"], dpi=40)

    left = sorted(p.name for p in tmp_path.iterdir())
    assert [n for n in left if n.endswith(".pdf")] == []
    assert [n for n in left if "accepted" in n] == []
    assert any(n.endswith(".png") for n in left), left


# --- the pages the batch's equations land on, rendered by DEFAULT --------
#
# BACKLOG, "nothing renders by default": four defects only a page can
# show went through a green ladder, every one in an equation the batch
# had just written. `math_anchors` names the pages of exactly those.

def _eq(text: str) -> str:
    return f"<m:oMath {NS_M}><m:r><m:t>{text}</m:t></m:r></m:oMath>"


def test_every_equation_is_new_when_there_is_no_baseline():
    accepted = make_parts(para(run("Let the model be "), _eq("y=a+bx"))
                          + para(run("and the error "), _eq("e~N(0,1)")))

    assert revision.math_anchors(accepted, None) == [
        "Let the model be", "and the error"]


def test_an_equation_the_baseline_carries_is_NOT_rendered_again():
    """Tokens, not markup: Word re-serialises every equation through
    Compare, so the OMML differs on every round and the symbol stream
    does not. A changed stream is a changed equation."""
    base = make_parts(para(run("Let the model be "), _eq("y=a+bx"))
                      + para(run("and the error "), _eq("e~N(0,1)")))
    accepted = make_parts(
        para(run("Let the model be "), _eq("y=a+bx"))          # unchanged
        + para(run("and the error "), _eq("e~N(0,s)")))        # changed

    assert revision.math_anchors(accepted, base) == ["and the error"]


def test_a_DISPLAY_equation_is_found_by_its_lead_in():
    """A paragraph holding nothing but maths has no prose to search
    for, and the page draws its characters from the Mathematical
    Alphanumeric block — so the nearest prose above it is the anchor,
    which is the lead-in a reader finds it by."""
    accepted = make_parts(para(run("The first-order condition is:"))
                          + para(_eq("dU/dc=0"))
                          + para(run("(3)"))                    # a label
                          + para(_eq("dU/dl=w")))

    assert revision.math_anchors(accepted, None) == [
        "The first-order condition is"]        # edge punctuation dropped


def test_the_anchor_is_the_paragraphs_FIRST_LINE_cut_at_a_word():
    """`render_anchors` matches the phrase inside one extracted line,
    and a paragraph starts a line: forty characters, whole words."""
    long = ("Consider the household that maximises utility over "
            "consumption and leisure subject to ")
    accepted = make_parts(para(run(long), _eq("c+wl=wT")))

    (anchor,) = revision.math_anchors(accepted, None)

    assert anchor == "Consider the household that maximises"
    assert len(anchor) <= 40 and long.startswith(anchor)


def test_no_equation_means_nothing_to_render():
    accepted = make_parts(para(run("Prose only, as it stands.")))

    assert revision.math_anchors(accepted, None) == []


def test_the_anchor_never_reaches_ACROSS_an_inline_equation():
    """Joining the runs gives "where is employment of workers", which
    is on no page: the symbol sits in that hole. A third of the
    equation paragraphs on AFI, HCW and LE open on "where <symbol>"
    (measured 2026-09-11), so the phrase is the first prose SEGMENT
    between equations that is a phrase and not a label."""
    accepted = make_parts(
        para(run("where "), _eq("E"), run(" is employment of workers "
                                          "aged 50 and over, and "),
             _eq("N"), run(" the workforce."))
        + para(run("(3)"), _eq("y=1")))                  # a label only

    assert revision.math_anchors(accepted, None) == [
        "is employment of workers aged 50 and",
        # the labelled display falls back to the phrase above it
    ]


# The two length boundaries of the anchor phrase, found by the mutation
# run of 2026-09-11. LITERAL lengths, not the constants: a boundary test
# that reads the constant it pins moves with it, and stays green when
# forty becomes thirty-nine.


def test_a_first_line_of_EXACTLY_forty_characters_is_kept_whole():
    """At forty the phrase is the whole first line; past it, cut at a
    word. `<=` read as `<` cut a forty-character line back to its last
    space — a shorter phrase, and on a narrow page a different page."""
    forty = "x" * 19 + " " + "y" * 20
    forty_one = "x" * 20 + " " + "y" * 20
    assert (len(forty), len(forty_one)) == (40, 41)

    assert revision.math_anchors(
        make_parts(para(run(forty), _eq("a"))), None) == [forty]
    assert revision.math_anchors(
        make_parts(para(run(forty_one), _eq("a"))), None) == ["x" * 20]


def test_a_segment_of_EXACTLY_twelve_characters_is_a_phrase_not_a_label():
    """Twelve is a phrase; eleven is a label, and the equation is found
    by the lead-in above it instead. `>=` read as `>` sent a twelve-
    character segment to the lead-in too."""
    lead = "The model is set out below"
    twelve = "a" * 5 + " " + "b" * 6
    eleven = "a" * 5 + " " + "b" * 5
    assert (len(twelve), len(eleven)) == (12, 11)

    assert revision.math_anchors(make_parts(
        para(run(lead)) + para(run(twelve), _eq("a"))), None) == [twelve]
    assert revision.math_anchors(make_parts(
        para(run(lead)) + para(run(eleven), _eq("a"))), None) == [lead]


def test_the_phrase_is_cut_at_the_LAST_space_within_forty_one_characters():
    """`rfind(" ", 0, 41)`: a space AT index 40 still ends the phrase at
    forty — the whole first line — and a space at 41 does not. Read as a
    bound of 40 or 42, the cut moved a word one way or the other, and the
    forty/forty-one test above passes both, since its only space sits at
    twenty."""
    at_forty = "x" * 19 + " " + "y" * 20 + " " + "z" * 5
    at_forty_one = "x" * 19 + " " + "y" * 21 + " " + "z" * 5
    assert (at_forty.index(" ", 20), at_forty_one.index(" ", 20)) == (40, 41)

    assert revision.math_anchors(make_parts(
        para(run(at_forty), _eq("a"))), None) == ["x" * 19 + " " + "y" * 20]
    assert revision.math_anchors(make_parts(
        para(run(at_forty_one), _eq("a"))), None) == ["x" * 19]


def test_a_cut_that_would_leave_a_LABEL_takes_the_first_forty_instead():
    """A word boundary is worth cutting at only if what it leaves is a
    phrase: a space at twelve is, a space at five is not, and the phrase
    is then the first forty characters as they come."""
    at_twelve = "a" * 12 + " " + "b" * 40
    at_five = "a" * 5 + " " + "b" * 45

    assert revision.math_anchors(make_parts(
        para(run(at_twelve), _eq("a"))), None) == ["a" * 12]
    assert revision.math_anchors(make_parts(
        para(run(at_five), _eq("a"))), None) == [at_five[:40]]


@pytest.mark.parametrize("stamped", ["0" * 64, "f" * 64])
def test_validate_aborts_on_a_stamp_for_ANY_other_baseline(tmp_path,
                                                          stamped):
    """High and low. The stale-stamp test used a hash of zeros, which
    sorts below every real one, and `==` read as `>=` passed it — a batch
    stamped with a hash that sorts HIGH would have run the whole ladder
    against a baseline it was not built on."""
    from docxkit import guard
    base = write(tmp_path / "prev.docx", make_parts(para(run("the truth"))))
    batch = write(tmp_path / "batch.docx",
                  make_parts(para(run("the truth"))))
    guard.stamp(batch, base_sha256=stamped)

    report = revision.validate(batch, base, use_word=False)

    assert report.aborted == "baseline"
    assert report.built_on == stamped


def test_the_error_Word_gave_is_quoted_at_200_characters(tmp_path,
                                                         monkeypatch):
    """The width `revision validate` prints on its one `== Word ==` line.
    Found by mutation, 2026-09-11: 199 and 201 both passed."""
    long = "Word could not open the file. " * 20

    class _Refusing:
        def session(self, **_kw):
            raise OSError(long)

    monkeypatch.setattr(revision._validate, "_word", _Refusing())
    base = write(tmp_path / "prev.docx", make_parts(para(run("the truth"))))
    batch = write(tmp_path / "batch.docx",
                  make_parts(para(run("the truth"))))

    report = revision.validate(batch, base)

    assert report.aborted == "word"
    assert report.word_error == long[:200]


def test_render_accepted_survives_a_render_still_held_open(tmp_path,
                                                          monkeypatch):
    """`ignore_errors=True` on the staging sweep — the flag `pages.sheets`
    and `page_texts` hold, for the same reason: on Windows a file with a
    handle on it cannot be removed, and a sweep that raised would throw
    away the PNGs already made."""
    import shutil
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("Employment rises "), ins("sharply"))))
    held: list[Any] = []

    def fake_export(path, out_pdf, **kw):
        made = _pdf_of("Employment rises sharply", Path(out_pdf))
        held.append(open(made, "rb"))      # noqa: SIM115 — held on purpose
        return made

    monkeypatch.setattr("docxkit.word.export_pdf", fake_export)
    try:
        (png,) = revision.render_accepted(batch, ["Employment rises"],
                                          dpi=40).values()
        assert png is not None and png.exists()
    finally:
        for handle in held:
            handle.close()
            shutil.rmtree(Path(handle.name).parent, ignore_errors=True)


_FOOTNOTE_REF = '<w:r><w:footnoteReference w:id="2"/></w:r>'


@pytest.mark.parametrize(("was", "now", "note_was", "note_now", "math_only"), [
    # the substitution and nothing else, beside a note that did not move:
    # equal notes that are not the same OBJECT — `is` read as `==`
    ("gap − 0.15", "gap - 0.15", "a note that stays", "a note that stays",
     True),
    # a real edit whose downgraded text sorts BELOW the baseline's — `>=`
    ("gap − 0.19", "gap - 0.15", None, None, False),
    # and one that sorts ABOVE it — `<=`. The mirror of the line above,
    # and the only case that tells `==` from `<=` on the BODY: the
    # 2026-09-17 replay found it alive here and killed only by
    # `test_cli_revision.py::test_a_REAL_edit_is_not_called_a_math_
    # downgrade`, which is the CLI's rendering of this same decision.
    ("gap − 0.15", "gap - 0.19", None, None, False),
    # the body is only the substitution and the NOTE really changed, in
    # both orders — `>=` and `<=` on the notes
    ("gap − 0.15", "gap - 0.15", "note b", "note a", False),
    ("gap − 0.15", "gap - 0.15", "note a", "note b", False),
])
def test_a_glyph_mismatch_is_MATH_ONLY_only_when_both_views_agree(
        tmp_path, was, now, note_was, note_now, math_only):
    """`glyph_math_only` tells the reader every glyph difference is Word
    downgrading an equation — nothing to fix. Wrongly True, it excuses a
    real edit. The existing tests held it with no footnotes (both note
    streams empty, so `<=`, `>=` and `is` all agree with `==`) and with a
    real edit that happened to sort upward. Found by mutation, 2026-09-11."""
    def parts(body: str, note_text: str | None) -> dict[str, bytes]:
        if note_text is None:
            return make_parts(para(run(body)))
        return make_parts(para(run(body), _FOOTNOTE_REF),
                          footnotes=notes("footnotes",
                                          note(note_text, nid=2)))

    base = write(tmp_path / "prev.docx", parts(was, note_was))
    batch = write(tmp_path / "batch.docx", parts(now, note_now))

    report = revision.validate(batch, base, use_word=False)

    assert report.lint == [], report.lint
    assert report.reject_matches_baseline is False
    assert report.glyph_math_only is math_only, report.glyph_diff


def test_validate_names_the_equation_pages_the_batch_adds(tmp_path):
    """On the report, so the CLI renders them without being asked."""
    base = write(tmp_path / "prev.docx",
                 make_parts(para(run("The paper as it stands."))))
    # `preserve`: an unpreserved edge space is what `lint` refuses, and
    # the ladder would abort before any anchor was named
    batch = write(tmp_path / "batch.docx", make_parts(
        para(run("The paper as it stands."))
        + para(f'<w:ins w:id="92" w:author="R" w:date="2026-08-07T00:00:00Z">'
               f'{run("We assume throughout that ", preserve=True)}</w:ins>',
               f'<w:ins w:id="93" w:author="R" w:date="2026-08-07T00:00:00Z">'
               f'{_eq("a>0")}</w:ins>')))

    report = revision.validate(batch, base, use_word=False)

    assert report.lint == [], report.lint
    assert report.math_anchors == ["We assume throughout that"]


def test_render_accepted_asks_WORD_for_nothing_when_no_anchor_is_given(
        tmp_path, monkeypatch):
    """`--render` with nothing after it must not start Word: the whole
    step costs a session, a render and a PDF, and the answer is
    empty."""
    batch = write(tmp_path / "batch.docx", make_parts(para(run("prose"))))

    def refuse(*a, **kw):                       # pragma: no cover
        raise AssertionError("Word was started for no anchors")

    monkeypatch.setattr("docxkit.word.export_pdf", refuse)

    assert revision.render_accepted(batch, []) == {}
    assert revision.render_accepted(batch, ["", "  "]) == {}


# --- the run of 2026-08-20: 8.8 %, and the report a hand-back gets ------

_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
       ' xmlns:r="r"')
_LONG_WAS = "United Nations Children's Fund report of 2024, second edition"
_LONG_NOW = "UNICEF, the Children's Fund of the United Nations, 2024 edition"


def _doc(*paragraphs: str) -> dict[str, bytes]:
    body = "".join(paragraphs)
    return {"word/document.xml":
            f"<w:document {_NS}><w:body>{body}</w:body></w:document>".encode()}


def _link(anchor: str, label: str) -> str:
    return (f'<w:p><w:hyperlink w:anchor="{anchor}"><w:r><w:t>{label}</w:t>'
            "</w:r></w:hyperlink></w:p>")


def test_a_RELABELLED_link_is_reported_with_both_labels_cut_to_forty():
    """Two cuts in one line, and the line is the whole product of this
    check: a person deciding whether an author's re-labelling was
    deliberate reads the old text against the new. A citation label runs
    past forty characters as a matter of course — "United Nations
    Children's Fund report of 2024" is sixty.

    The new label is the FIRST of the fresh ones for that anchor, and
    the fixture gives the anchor a second, later mention so that "first"
    is a choice: sorted, "UNICEF…" comes before "zzz…", and the last
    would report the wrong half of the pair."""
    prev = _doc(_link("Ref1", _LONG_WAS))
    working = _doc(_link("Ref1", _LONG_NOW), _link("Ref1", "zzz later"))

    lost, relabelled = _link_changes(working, prev)

    assert lost == []
    assert [str(r) for r in relabelled] == [
        'link Ref1: "United Nations Children\'s Fund report of" -> '
        '"UNICEF, the Children\'s Fund of the Unite"']


def test_a_LOST_link_is_reported_with_its_label_cut_to_forty():
    """`label[:40]` again, in the message that BLOCKS. A loss names the
    anchor and the words the reader has to go and find; the whole label
    of a swallowed citation is a line of prose in a refusal."""
    prev = _doc(_link("Ref2", _LONG_WAS))
    working = _doc("<w:p><w:r><w:t>plain text now</w:t></w:r></w:p>")

    lost, relabelled = _link_changes(working, prev)

    assert relabelled == []
    assert str(lost[0]) == ('link "Ref2 (United Nations Children\'s Fund '
                            'report of)"')


def test_the_glyph_report_stops_at_SIX_runs_and_counts_the_rest():
    """`limit: int = 6` — a default no caller passes, so nothing pinned
    it. The docstring says why it exists: a batch that really did lose a
    paragraph would otherwise print the paragraph. Both neighbours of
    six are wrong in a way a reader cannot see — five prints less than
    the gate promises, seven prints one run more and never says how many
    it kept back."""
    before = "".join(f"word{i} " for i in range(20))
    after = before
    for i in (3, 5, 7, 9, 11, 13, 15):
        after = after.replace(f"word{i} ", f"WORD{i} ")

    runs = glyph_runs(before, after)

    assert len(runs) == 7, runs
    assert runs[-1] == "... and 1 more run(s)", runs[-1]


def test_a_SEPARATOR_note_is_not_a_moved_footnote():
    """`nid < 1`: Word's separator and continuation-separator notes are
    ids 0 and -1, and they carry the same `w:ins` a moved note does
    after Compare has been through the part. Admitted, every build
    reports a footnote nobody wrote as one Compare emitted unmatched —
    and `build` refuses on it."""
    notes = (f"<w:footnotes {_NS}>"
             '<w:footnote w:id="0"><w:p><w:r><w:ins w:id="9" w:author="W">'
             "<w:t>sep</w:t></w:ins></w:r></w:p></w:footnote>"
             '<w:footnote w:id="2"><w:p><w:r><w:ins w:id="8" w:author="W">'
             "<w:t>a moved note</w:t></w:ins></w:r></w:p></w:footnote>"
             "</w:footnotes>")
    baseline = (f"<w:footnotes {_NS}>"
                '<w:footnote w:id="0"><w:p><w:r><w:t>sep</w:t></w:r></w:p>'
                "</w:footnote>"
                '<w:footnote w:id="2"><w:p><w:r><w:t>a moved note</w:t>'
                "</w:r></w:p></w:footnote></w:footnotes>")

    assert moved_footnotes({"word/footnotes.xml": notes.encode()},
                           {"word/footnotes.xml": baseline.encode()}) == [2]


def test_two_relabelled_mentions_of_one_anchor_pair_off_ONE_FOR_ONE():
    """The docstring's promise: each gone label consumes one gained
    label for the same anchor. The consumption is a separate line from
    the report, and a fixture with ONE relabelled link cannot tell them
    apart — the second pairing is where consuming the wrong entry shows,
    as a link reported against a label already spoken for."""
    prev = _doc(_link("Ref1", "AAA first mention"),
                _link("Ref1", "BBB second mention"))
    working = _doc(_link("Ref1", "CCC first now"),
                   _link("Ref1", "DDD second now"))

    lost, relabelled = _link_changes(working, prev)

    assert lost == []
    assert [str(r) for r in relabelled] == [
        "link Ref1: 'AAA first mention' -> 'CCC first now'",
        "link Ref1: 'BBB second mention' -> 'DDD second now'"]


def test_a_relabelling_takes_its_new_label_from_its_OWN_anchor():
    """`if a == anchor`. Two anchors relabelled in one hand-back is the
    ordinary case — an author who rewrites one citation label usually
    rewrites the neighbouring one — and identity there makes every
    anchor's fresh labels the OTHER anchors' labels: Ref1 is reported as
    renamed to the text that belongs to Ref2, and the pair reads as two
    edits nobody made.

    Ref2's new label sorts first on purpose: sorted() is what picks
    between them."""
    prev = _doc(_link("Ref1", "ZZZ old one"), _link("Ref2", "YYY old two"))
    working = _doc(_link("Ref1", "NNN new one"), _link("Ref2", "AAA new two"))

    _lost, relabelled = _link_changes(working, prev)

    assert [str(r) for r in relabelled] == [
        "link Ref1: 'ZZZ old one' -> 'NNN new one'",
        "link Ref2: 'YYY old two' -> 'AAA new two'"]


def test_a_bookmark_the_author_ADDED_is_not_a_loss():
    """`_bookmarks(prev) - _bookmarks(working)`, written as a symmetric
    difference. An author who adds a cross-reference target adds a
    bookmark, and the hand-back gate would then refuse their own new
    anchor as something Word destroyed — the shape of refusal that
    teaches a person to pass `--accept-loss` without reading it."""
    def bm(name: str, i: int) -> str:
        return (f'<w:p><w:bookmarkStart w:id="{i}" w:name="{name}"/>'
                f'<w:r><w:t>t</w:t></w:r><w:bookmarkEnd w:id="{i}"/></w:p>')

    prev = _doc(bm("Kept", 1))
    working = _doc(bm("Kept", 1), bm("BrandNew", 2))

    assert losses(working, prev) == []


def test_two_EQUAL_glyph_streams_report_nothing():
    """Two streams read out of two documents are never the same object,
    so `before == after` is a fast path rather than a decision — and
    `is` there is equivalent, because difflib answers "no changed
    opcodes" for equal strings anyway. Pinned as behaviour, not as a
    mutant: the report for a clean build is empty."""
    before = "".join(["a", "b", "c"])
    after = "".join(["a", "b", "c"])
    assert before is not after and before == after

    assert glyph_runs(before, after) == []


# Argued rather than pinned, from the same run:
#
# * `before == after` in `glyph_runs`, written `is`: it saves a difflib
#   pass over two long strings and cannot change the answer, because
#   equal strings produce no changed opcodes.
# * `token == candidate` in `_names`, written `is`: the two `startswith`
#   tests beside it answer True for equal strings, so the equality is
#   redundant however it is spelled.
# * `self.word_opened is not False` written `!=`. The field is a bool or
#   None, and the two readings part company only on values (0, 0.0) that
#   nothing puts there.


def test_the_lost_link_line_names_the_anchor_and_forty_of_its_LABEL(tmp_path):
    """`(was - now)` and `label[:40]`, in the report `validate` prints
    when reject-all does not reproduce the baseline. The union reading
    lists every link the batch KEPT beside the one it lost, which is a
    reader's whole afternoon; the label is how they find the sentence.

    The surviving link is in the fixture for exactly that reason."""
    def link(anchor: str, label: str) -> str:
        return (f'<w:hyperlink w:anchor="{anchor}"><w:r><w:t>{label}</w:t>'
                "</w:r></w:hyperlink>")

    long_label = "United Nations Children's Fund report of 2024, second ed"
    baseline_path = write(tmp_path / "prev-links.docx", make_parts(
        f"<w:p>{link('Kept', 'a surviving link label')}</w:p>"
        f"<w:p>{link('Gone', long_label)}</w:p>"))
    batch = write(tmp_path / "batch-links.docx", make_parts(
        f"<w:p>{link('Kept', 'a surviving link label')}</w:p>"
        "<w:p><w:r><w:t>quietly rewritten</w:t></w:r></w:p>"))

    report = revision.validate(batch, baseline_path, use_word=False)

    assert report.reject_matches_baseline is False
    assert report.lost_links == [
        '-> Gone ("United Nations Children\'s Fund report of")']


@pytest.fixture
def migrated(tmp_path):
    """A migrated project, for the declaration reader below."""
    source = tmp_path / "Report" / "afi_v14.docx"
    source.parent.mkdir(parents=True)
    write(source, make_parts(para(run("The paper."))))
    return revision.init(tmp_path, source)


@pytest.mark.parametrize("declared", [
    "Report/*.docx",            # relative: `Path.match` reads from the right
    "**/afi_v14.docx",
    "/Report/*.docx",           # ROOTED: only the "**/" reading finds it
    "/Report/afi_v14.docx",
])
def test_a_GLOB_selects_the_manuscript_by_either_reading(declared, migrated):
    """`target.match(text) or target.match(f"**/{text}")` — two ways of
    asking whether a pattern reaches the paper.

    A relative pattern is matched from the right, so the first reading
    answers it; a ROOTED one ("/Report/*.docx", which is how a config
    written against the repository root spells it) is absolute to
    `Path.match` and matches nothing, and only the stripped-and-prefixed
    form finds the file. Read as `and`, every rooted declaration goes
    unreported — which is the class `doctor` exists to find: a pattern
    that stops matching after a migration does not fail, it picks up an
    older generation sitting on disk."""
    assert _selects_declared(declared, migrated) is True


def test_a_declaration_naming_ANOTHER_file_is_not_the_manuscript(
        migrated):
    """`candidate.name != target.name`, and the skip it guards. Read as
    `<`, every declared name that sorts ABOVE the manuscript's falls
    through to the bare-name branch and is reported as selecting the
    paper — `zzz_appendix.docx` and half the alphabet with it. A doctor
    that names innocent files is one nobody reads twice."""
    assert _selects_declared("zzz_appendix.docx", migrated) is False
    assert _selects_declared("aaa_appendix.docx", migrated) is False
    assert _selects_declared("afi_v14.docx", migrated) is True


def test_state_counts_an_ENDNOTE_when_the_paper_has_no_footnotes():
    """`if not blob: continue` over the three text parts. A journal that
    takes endnotes produces a package with no `footnotes.xml` at all —
    LI and DSI both — and `break` there stops the walk at the missing
    part, so every pending change in the endnotes reads as settled.

    "0 pending -> TRUTH" is the answer this function exists to be
    trusted on."""
    import tempfile
    from pathlib import Path

    D = 'w:id="1" w:author="Reviewer" w:date="2026-07-30T00:00:00Z"'
    endnotes = (f"<w:endnotes {NS}><w:endnote w:id=\"2\"><w:p>"
                f"<w:ins {D}><w:r><w:t>added in a note</w:t></w:r>"
                f"</w:ins></w:p></w:endnote></w:endnotes>")
    parts = make_parts(para(run("plain prose")),
                       extra={"word/endnotes.xml": endnotes})
    assert "word/footnotes.xml" not in parts

    tmp = Path(tempfile.mkdtemp())
    st = revision.state(write(tmp / "working.docx", parts))

    assert st.by_part == {"word/endnotes.xml": 1}
    assert st.pending == 1 and not st.is_truth


def test_the_stale_message_quotes_SIXTEEN_characters_of_each_hash(project):
    """`live_hash[:16]`. The prefix is what a person compares by eye
    against `git hash-object` or a previous run's message, and sixteen
    hex characters is the width that identifies a file. Any shorter and
    two builds of the same paper can share it."""
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run("the author's own edit"))))

    with pytest.raises(StaleBatch) as exc:
        revision.promote(project)

    quoted = re.findall(r"[0-9a-f]{8,}", str(exc.value))
    assert quoted, str(exc.value)
    assert [len(h) for h in quoted] == [16, 16], quoted


def test_the_stale_guard_fires_when_the_live_hash_sorts_BELOW(project,
                                                              tmp_path):
    """The other half of the parametrised test above, which reads `<`
    and could not see `>`: five fixed contents all landed on one side of
    the baseline. The content here is SEARCHED for, so the fixture
    cannot drift back onto the comfortable side."""
    import shutil

    from docxkit import guard
    a = write(tmp_path / "a.docx", make_parts(para(run("one edit"))))
    b = write(tmp_path / "b.docx", make_parts(para(run("another edit"))))
    # COPIED, not rewritten: a docx carries the time it was zipped, so
    # writing the same content twice gives two different hashes and a
    # search for one that sorts below drifts with the clock. Two
    # candidates, sorted, copied byte for byte.
    low, high = sorted([a, b], key=guard.sha256)
    shutil.copy2(low, project.working)
    shutil.copy2(high, project.prev)
    assert guard.sha256(project.working) < guard.sha256(project.prev)

    write(project.batch, make_parts(para(run("the batch"))))
    before = project.working.read_bytes()

    with pytest.raises(StaleBatch):
        revision.promote(project)
    assert project.working.read_bytes() == before


def test_baseline_creates_a_build_directory_SEVERAL_LEVELS_down(tmp_path):
    """`mkdir(parents=True)`. The build directory is the parent of
    whatever `prev` the paper declares, so a paper that files its
    baseline deeper than the default gets a path with no intermediate
    directory on disk — and `parents=False` is a FileNotFoundError on
    the first baseline of a fresh project."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "manuscript.docx",
                make_parts(para(run("The paper."))))
    paper = revision.init(tmp_path / "proj", src)
    config = paper.config.read_text(encoding="utf-8")
    deep = "revision/build/deep/nested/prev.docx"
    paper.config.write_text(
        config.replace('prev     = "revision/build/prev.docx"',
                       f'prev = "{deep}"'),
        encoding="utf-8")
    deeper = revision.load_paper(paper.config)
    assert not deeper.build_dir.exists()

    revision.baseline(deeper, force=True)

    assert deeper.prev.exists()


# --- the run of 2026-08-20: 4.7 % (16/340) -----------------------------
#
# Down from 8.8 % and then 6.2 %, and the partial round is now closed.
# Seven of the sixteen are the tests above; the rest are argued, and
# each was put through kill_check:
#
# * `render_accepted`'s `dpi: int = 150` as 149 or 151. A rendering
#   resolution is a choice, not a contract: any of the three renders
#   the same page, and the callers that care pass their own.
# * `_shown`'s `0 < len(cut) <= 4` as `0 is not len(cut) <= 4`. A
#   length is never negative, so "not zero" and "greater than zero" are
#   the same question, and CPython caches the 0 that identity compares
#   against.
# * `_glyph`'s `tag == W + "drawing"` as `<=`. Every tag that sorts
#   below it — `w:body`, `w:br`, `w:bookmarkStart` — is then asked for
#   a `wp:inline` CHILD, which only a `w:drawing` has, so the branch
#   appends nothing and the walk continues either way.
# * `doctor`'s sort key `d.kind != "pattern"` as `is not`. Both kinds
#   are literals in this module and the comparison is against one of
#   them.
# * the four already argued in the note above, unchanged: the
#   `word_opened is not False` flag, `_names`' token identity, and the
#   two on the glob reader.
#
# NOT worked: `build`'s `for note in moved_footnotes(...)` mutated to
# an empty loop — no fixture in the suite has a footnote whose
# REFERENCE moved, so nothing sees the sentence it prints. That is a
# test worth writing and it needs a package built the way Word's
# Compare emits one, which is half a day.


# --------------------------------------------- the glyph Word eats on save --
#
# Word rewrites OMML on accept-and-save as readily as on Compare, and
# downgrades U+2212 to a hyphen while it is there. AFI lost all four of
# its minus signs that way, twice, and `baseline` copied the result over
# `prev.docx` both times -- after which the hyphens ARE the truth.

_EQ = "<w:p><m:oMath><m:r><m:t>{}</m:t></m:r></m:oMath></w:p>"


def _paper_at(tmp_path, prev, work):
    """A migrated paper whose baseline and hand-back are these parts."""
    (tmp_path / "proj").mkdir(exist_ok=True)
    src = write(tmp_path / "proj" / "m.docx", prev)
    paper = revision.init(tmp_path / "proj", src, attic=tmp_path / "attic")
    write(paper.working, work)
    return paper


def _math_pair(was: str, now: str):
    """A baseline and a hand-back differing only in that one run."""
    return (make_parts(_EQ.format(was) + para(run("prose"))),
            make_parts(_EQ.format(now) + para(run("prose"))))


def test_a_downgraded_equation_glyph_is_a_LOSS():
    """No text gate sees it: the paper still renders, the links are all
    there, and the equation now says what the author did not type."""
    prev, work = _math_pair("\u22120.398", "-0.398")

    found = revision.losses(work, prev)

    assert [str(x) for x in found] == ["glyph '\u22120.398 -> -0.398'"]
    assert found[0].kind == "glyph"


def test_an_equation_the_AUTHOR_changed_is_not_a_glyph_loss():
    """The two texts have to correspond as the same run with its glyphs
    flattened. A rewritten equation does not, and reporting one would
    make the gate a thing to switch off."""
    prev, work = _math_pair("\u22120.398", "\u22120.487")

    assert revision.losses(work, prev) == []


def test_an_equation_the_author_UNDOWNGRADED_is_not_a_loss():
    """The other direction: a hyphen that became a minus sign is the
    author fixing the house style, not Word breaking it."""
    prev, work = _math_pair("-0.398", "\u22120.398")

    assert revision.losses(work, prev) == []


def test_baseline_REFUSES_a_hand_back_whose_equations_were_flattened(
        tmp_path):
    """It is the step that makes the loss permanent."""
    paper = _paper_at(tmp_path, *_math_pair("\u22120.398", "-0.398"))

    with pytest.raises(revision.HandbackLoss, match="glyph"):
        revision.baseline(paper)


def test_baseline_REPAIRS_the_glyph_when_told_to(tmp_path):
    """The one loss this tool may put back itself, because it is not an
    author's decision: `build` already restores the same glyph on the
    redline it produces, and this is that repair on the other side of
    the hand-back."""
    prev, work = _math_pair("\u22120.398", "-0.398")
    paper = _paper_at(tmp_path, prev, work)

    written = revision.baseline(paper, repair_math=True)

    assert written.prev.exists()
    after = package.read_parts(
        paper.working)["word/document.xml"].decode("utf-8")
    assert "\u22120.398" in after and ">-0.398<" not in after
    assert revision.losses(package.read_parts(paper.working),
                           package.read_parts(paper.prev)) == []


def test_repair_math_does_not_forgive_the_losses_it_cannot_reach(tmp_path):
    """The gate runs afterwards, not instead. A repair that reached one
    thing must not wave through the others."""
    mark = ('<w:bookmarkStart w:id=\"1\" w:name=\"Table1\"/>'
            '<w:bookmarkEnd w:id=\"1\"/>')
    prev = make_parts(_EQ.format("\u22120.398") + mark
                      + para(run("prose")))
    work = make_parts(_EQ.format("-0.398") + para(run("prose")))

    paper = _paper_at(tmp_path, prev, work)
    before = paper.working.read_bytes()

    with pytest.raises(revision.HandbackLoss):
        revision.baseline(paper, repair_math=True)

    assert paper.working.read_bytes() == before, "the repair was written"


def test_repair_math_writes_NOTHING_while_a_revision_is_pending(tmp_path):
    """The repair used to be written before either gate ran, so
    `baseline --repair-math` on a manuscript with a revision still
    pending refused — correctly — having already changed the author's
    live file, and with no backup of it. The gates read the repair in
    memory; the file waits until they have all passed."""
    prev = make_parts(_EQ.format("−0.398") + para(run("prose")))
    work = make_parts(_EQ.format("-0.398") + para(run("prose"))
                      + para(run("x "), ins("pending")))
    paper = _paper_at(tmp_path, prev, work)
    before = paper.working.read_bytes()

    with pytest.raises(revision.BaselinePending):
        revision.baseline(paper, repair_math=True)

    assert paper.working.read_bytes() == before, "the repair was written"
    assert not list(paper.working.parent.glob("*pre_math_repair*"))


def test_repair_math_BACKS_UP_the_file_it_rewrites(tmp_path):
    """It is a write to `working.docx`, which is the file the author
    edits — and every other write to it in this package takes a numbered
    backup first."""
    prev, work = _math_pair("−0.398", "-0.398")
    paper = _paper_at(tmp_path, prev, work)
    before = paper.working.read_bytes()

    revision.baseline(paper, repair_math=True)

    kept = list(paper.working.parent.glob("*pre_math_repair*.docx"))
    assert len(kept) == 1, kept
    assert kept[0].read_bytes() == before



# --- the config writer's helpers ----------------------------------------

def test_a_HASH_inside_a_quoted_value_is_not_a_comment():
    """A Windows path cannot hold a `#`; a paper's NAME can — "Health #2",
    a journal's issue number. Cutting at the first `#` would eat half
    the value, call the rest a comment, and rewrite the key with the
    truncation."""
    from docxkit.revision import _value_end

    tail = '"Health #2 — capacity to work"  # the paper\'s own name'

    cut = _value_end(tail)

    assert tail[:cut] == '"Health #2 — capacity to work"'
    assert "#" in tail[:cut], "the one inside the quotes survived"


def test_a_manuscript_OUTSIDE_the_project_root_is_declared_absolute(
        tmp_path):
    """A relative declaration is what makes a project movable — copy the
    folder to another machine and the config still resolves. A paper
    that genuinely lives elsewhere has to say so instead, because a
    relative path to somewhere above the root resolves differently the
    moment the folder moves, which is the failure the relative form
    exists to prevent."""
    from docxkit.revision import _declare

    root = tmp_path / "project"
    root.mkdir()
    inside = root / "sub" / "paper.docx"
    outside = tmp_path / "elsewhere" / "paper.docx"

    assert _declare(inside, root) == "sub/paper.docx"
    declared = _declare(outside, root)
    assert Path(declared).is_absolute(), declared
    assert "\\" not in declared, "forward slashes either way"


def test_re_init_giving_NO_keys_rewrites_only_the_paper_path(tmp_path):
    """`init --force` with nothing else is how a paper that MOVED is
    corrected. Every other key the author set — name, language, author —
    has to survive it, and the three that are absent must not be written
    as empty strings over what is there."""
    from docxkit import revision

    root = tmp_path / "proj"
    root.mkdir()
    src = write(root / "HCW.docx", make_parts(para(run("body"))))
    revision.init(root, src, name="Health Capacity", language="en",
                  author="M. Lokshin")

    revision.init(root, src, force=True)

    text = (root / "revision" / "paper.toml").read_text(encoding="utf-8")
    assert "Health Capacity" in text, "the name the author set survived"
    assert "M. Lokshin" in text
    assert 'language = "en"' in text



# --- a link inside a DELETION (backlog S3, 2026-08-24) ------------------

_DEL_STAMP = 'w:id="90" w:author="R" w:date="2026-08-24T00:00:00Z"'


def _deleted(inner: str) -> str:
    return f"<w:del {_DEL_STAMP}>{inner}</w:del>"


def _linked_run(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}">'
            f"<w:r><w:delText>{label}</w:delText></w:r></w:hyperlink>")


def test_a_link_inside_a_deletion_is_reported_with_its_anchor():
    """Compare does not track an anchor. Rejecting the deletion restores
    its words as plain text and does not rebuild the link, so a batch
    whose accept-all is perfect fails reject-all — and no author sees it
    in Word, because a lost link is blue text that stays blue until
    somebody clicks it."""
    from docxkit.revision import links_in_deletions

    body = para(run("Kept. ")) + para(_deleted(
        _linked_run("ref_Barr2010", "Barr (2010)")))

    found = links_in_deletions(make_parts(body))

    assert [a for a, _ in found] == ["ref_Barr2010"], found


def test_a_link_OUTSIDE_a_deletion_is_not_reported():
    """The ordinary case is every other link in the manuscript. A check
    that named them all would fire on every batch and be switched off."""
    from docxkit.revision import links_in_deletions

    body = (para('<w:hyperlink w:anchor="ref_Kept"><w:r><w:t>Kept</w:t>'
                 "</w:r></w:hyperlink>")
            + para(_deleted("<w:r><w:delText>gone</w:delText></w:r>")))

    assert links_in_deletions(make_parts(body)) == []


def test_TWO_deletions_in_one_paragraph_are_two_spans():
    """Non-greedy, so the walk does not swallow the text between them
    and report a link that is staying put."""
    from docxkit.revision import links_in_deletions

    body = para(_deleted(_linked_run("ref_A", "A"))
                + '<w:hyperlink w:anchor="ref_SAFE"><w:r><w:t>safe</w:t>'
                  "</w:r></w:hyperlink>"
                + _deleted(_linked_run("ref_B", "B")))

    anchors = {a for a, _ in links_in_deletions(make_parts(body))}

    assert anchors == {"ref_A", "ref_B"}, anchors


def test_a_deletion_in_a_FOOTNOTE_counts_too():
    """`text_parts`, not `document.xml`: several journals take the whole
    apparatus as endnotes, and a citation link there is the one a reader
    is most likely to follow."""
    from docxkit.revision import links_in_deletions

    parts = make_parts(para(run("Body.")),
                       footnotes=footnotes_part(para(_deleted(
                           _linked_run("ref_Note", "Note")))))

    assert [a for a, _ in links_in_deletions(parts)] == ["ref_Note"]


# ------------------------------------------ the protocol times itself

def test_a_promote_RECORDS_how_long_it_took(project):
    """Every paper, with no per-paper line to add.

    The alternative was measured on Aging_Well on 2026-09-07 by
    watching file mtimes from outside: two rounds, ±20s per step,
    unable to tell a rewrite from a touch or name the command that
    caused either. From inside it is exact and costs a `perf_counter`.
    """
    import dataclasses

    from docxkit import timings
    write(project.batch, make_parts(para(run("the batch"))))

    revision.promote(project)

    runs = timings.read(project.root / timings.FOLDER, kind="promote")
    assert len(runs) == 1
    assert runs[0]["outcome"] == "ok"
    assert [s["name"] for s in runs[0]["steps"]][-1] == "total"
    assert runs[0]["steps"][-1]["seconds"] >= 0
    assert dataclasses.is_dataclass(project)


def test_a_REFUSED_command_records_the_refusal_as_its_outcome(project):
    """A build that refused still took time, and the refusal is the
    interesting row — a history of only the happy path would say the
    protocol never fails."""
    from docxkit import timings
    write(project.batch, make_parts(para(run("the batch"))))
    write(project.working, make_parts(para(run("the author moved on"))))

    with pytest.raises(StaleBatch):
        revision.promote(project)

    runs = timings.read(project.root / timings.FOLDER, kind="promote")
    assert [r["outcome"] for r in runs] == ["StaleBatch"]


def test_a_paper_can_turn_the_recording_OFF(project):
    """`repkit` ships a replication package out of a paper tree, and a
    folder of JSON nobody declared is what rides along into one."""
    import dataclasses

    from docxkit import timings
    write(project.batch, make_parts(para(run("the batch"))))

    revision.promote(dataclasses.replace(project, timings=False))

    assert not (project.root / timings.FOLDER).exists()


def test_the_ENV_switch_silences_a_whole_MACHINE(project, monkeypatch):
    from docxkit import timings
    from docxkit.revision import _timing
    write(project.batch, make_parts(para(run("the batch"))))
    monkeypatch.setenv(_timing.ENV, "0")

    revision.promote(project)

    assert not (project.root / timings.FOLDER).exists()


def test_mark_is_a_NO_OP_outside_a_session():
    """`mark` reaches its session through a ContextVar, so a direct
    library caller — and every test that never opted in — needs no
    special case."""
    from docxkit.revision import _timing

    _timing.mark("nothing is timing")            # must not raise


def test_a_mark_names_a_PHASE_within_the_command(tmp_path):
    from docxkit import timings
    from docxkit.revision import _timing

    with _timing.session("probe", None, root=tmp_path):
        _timing.mark("first")
        _timing.mark("second")

    got = timings.read(tmp_path / timings.FOLDER)
    assert [s["name"] for s in got[0]["steps"]] == ["first", "second",
                                                    "total"]


def test_an_unwritable_root_does_not_break_the_ROUND(tmp_path):
    """A round that fell over because it could not write a performance
    note would be the tail wagging the dog."""
    from docxkit.revision import _timing
    wall = tmp_path / "a-file"
    wall.write_text("not a directory", encoding="utf-8")

    with _timing.session("probe", None, root=wall / "under"):
        pass                                     # must not raise


def test_a_mark_and_the_total_are_ELAPSED_seconds_to_the_hundredth(
        monkeypatch):
    """Found by the first mutation sweep, 2026-09-13: every timing test
    read the names of the steps and none of them their seconds."""
    import types

    from docxkit.revision import _timing
    clock = iter([1.0, 3.25678, 5.51234])
    monkeypatch.setattr(_timing, "time", types.SimpleNamespace(
        perf_counter=lambda: next(clock)))

    live = _timing.Session()

    assert live.mark("first") == 2.26
    assert live.finish() == [("first", 2.26), ("total", 4.51)]


def test_nothing_is_TIMED_without_a_root_or_with_the_switch_off(
        tmp_path, monkeypatch):
    """Both, not either: a session with nowhere to write, or on a machine
    that said no, hands `mark` nothing to record into."""
    from docxkit.revision import _timing

    with _timing.session("probe", None) as nowhere:
        _timing.mark("unrecorded")
    monkeypatch.setenv(_timing.ENV, "0")
    with _timing.session("probe", None, root=tmp_path) as switched_off:
        _timing.mark("unrecorded")

    assert nowhere.steps == [] and switched_off.steps == []


def test_timed_keeps_the_VERBs_name_and_docstring():
    """`revision.build` and the others are what `help()` and the CLI's
    own docs are read off."""
    from docxkit.revision import _timing

    def build(paper):
        """Build it."""

    wrapped = _timing.timed("build")(build)

    assert wrapped.__name__ == "build" and wrapped.__doc__ == "Build it."
    assert wrapped.__wrapped__ is build  # type: ignore[attr-defined]


def test_timed_takes_the_paper_from_the_FIRST_argument_only(project):
    """The paper beside a second argument is still recorded; a first
    argument that is not a paper is no paper, and no crash."""
    from docxkit import timings
    from docxkit.revision import _timing

    @_timing.timed("probe")
    def verb(*args):
        return "done"

    assert verb(project, "a second argument") == "done"
    assert timings.read(project.root / timings.FOLDER, kind="probe")
    assert verb("not a paper") == "done"


def test_baseline_is_TIMED_like_the_other_verbs(project):
    """`build` and `promote` record how long they took, and so does the
    step that closes a round. Found by mutation, 2026-09-11: the
    decorator could be deleted and nothing noticed, because every timing
    test drove `promote` or `_timing` directly."""
    from docxkit import timings
    write(project.working, make_parts(para(run("Accepted and settled."))))

    revision.baseline(project)

    got = timings.read(project.root / timings.FOLDER)
    assert [(r["kind"], r["name"], r["outcome"]) for r in got] == [
        ("baseline", project.name, "ok")]
