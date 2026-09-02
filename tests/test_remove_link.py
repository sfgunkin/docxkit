r"""`edit.remove_link` — the inverse of linking, in both forms.

This package could create a link and not undo one. `crossrefs.unlink`
looks like the exception and is not: it is document-wide, finds its
targets through the exhibit captions, and REFUSES a field-form link
rather than remove half of one — measured on Parental_style, where
removing the bookmarks and leaving the fields said "24 removed" over a
document whose caption links were all still live.

So Aging_Well wrote its own for citations, `_unwrap_wide`: 38 lines
re-deriving the two-form scan `edit._label_spans` had done all along,
private. The house wants one link per YEAR in "Rowe and Kahn (1987,
1997)" where `link_all` tiles the group, and the narrowing has to be
re-applied on every pass — a tiled link is a CORRECT link, so no gate
has an opinion about it and `link_all` re-tiles on the next run.

What the paper needed is here: remove ONE link, by anchor, in whichever
form the last save left, keeping the words. The convention — which span
a group citation should have — stays with the paper.
"""
from __future__ import annotations

import pytest
from conftest import field, para, run

from docxkit.edit import relabel_link, remove_link, remove_links
from docxkit.errors import AnchorError

LINKED = ('<w:hyperlink w:anchor="Sen1985"><w:r><w:rPr>'
          '<w:rStyle w:val="Hyperlink"/></w:rPr>'
          "<w:t>Sen (1985)</w:t></w:r></w:hyperlink>")
MARK = '<w:bookmarkStart w:id="9" w:name="Sen1985txt"/>'
MARK_END = '<w:bookmarkEnd w:id="9"/>'


def _element(before: str = "See ", after: str = ".") -> str:
    return para(run(before), MARK + LINKED + MARK_END, run(after))


def _fielded(anchor: str = "Sen1985", label: str = "Sen (1985)") -> str:
    """The same link as Word writes it after a save."""
    return para(run("See "), field(f'HYPERLINK \\l "{anchor}"', label),
                run("."))


# ------------------------------------------------------------ both forms


def test_an_element_form_link_comes_off_and_the_words_stay():
    out, label = remove_link(_element(), "Sen1985")

    assert label == "Sen (1985)"
    assert "w:hyperlink" not in out
    assert "Sen (1985)" in out, "the words are what a reader keeps"
    assert 'w:val="Hyperlink"' not in out, "and they stop looking clickable"


def test_a_FIELD_form_link_comes_off_too(capsys):
    """The half `crossrefs.unlink` refuses. Which form a paragraph holds
    depends on who saved the file last, so a routine that reads one of
    them works until the author opens the document."""
    out, label = remove_link(_fielded(), "Sen1985")

    assert label == "Sen (1985)"
    assert "fldChar" not in out and "instrText" not in out
    assert "Sen (1985)" in out


def test_the_field_runs_go_WITH_the_field():
    """A field is four runs — begin, instruction, separate, end — and
    `_FIELD_RE` matches between the first and last fldChar, INSIDE the
    runs holding them. Cutting at the match leaves two empty `w:r`
    shells around the words."""
    out, _ = remove_link(_fielded(), "Sen1985")

    assert "<w:r></w:r>" not in out and "<w:r/>" not in out
    assert out.count("<w:r") == 3, out       # See , the label, the stop


def test_the_two_forms_leave_the_same_paragraph():
    """The point of handling both: a caller cannot tell which one it has
    and must not need to."""
    from docxkit._xml import visible_text

    element, _ = remove_link(_element(), "Sen1985")
    fielded, _ = remove_link(_fielded(), "Sen1985")

    assert visible_text(element) == visible_text(fielded) == "See Sen (1985)."


# ------------------------------------------------------- the twin bookmark


def test_the_in_text_twin_bookmark_goes_with_the_link():
    """`<anchor>txt` is this package's own convention for the in-text end
    of a link. Left behind, `wrap_link_in_bookmark` adds a second one on
    the next re-wire."""
    out, _ = remove_link(_element(), "Sen1985")

    assert "Sen1985txt" not in out
    assert "bookmarkEnd" not in out, "the pair goes, not just the start"


def test_the_bookmark_can_be_KEPT_on_purpose():
    """An anchor a REF field still reaches is a bookmark wanted without
    the link."""
    out, _ = remove_link(_element(), "Sen1985", drop_twin=False)

    assert 'w:name="Sen1985txt"' in out and "bookmarkEnd" in out
    assert "w:hyperlink" not in out


def test_a_bookmark_that_is_not_there_is_not_an_error():
    out, _ = remove_link(para(run("See "), LINKED, run(".")), "Sen1985")

    assert "w:hyperlink" not in out


# ------------------------------------------------------------- refusals


def test_an_anchor_this_paragraph_does_not_link_to_is_refused():
    """A removal that quietly does nothing is how a batch reports
    success and ships the link — the same refusal `relabel_link` makes."""
    with pytest.raises(AnchorError, match="no link to 'Rowe1987'"):
        remove_link(_element(), "Rowe1987")


def test_the_refusal_names_the_links_the_paragraph_DOES_have():
    with pytest.raises(AnchorError, match="Sen1985"):
        remove_link(_element(), "Rowe1987")


def test_a_paragraph_with_no_links_at_all_says_so():
    with pytest.raises(AnchorError, match="it has no links"):
        remove_link(para(run("Plain prose.")), "Sen1985")


def test_TWO_links_to_one_anchor_are_refused():
    """Nothing in the arguments says which, and picking the first is how
    the wrong one goes."""
    twice = para(run("See "), LINKED, run(" and "), LINKED, run("."))

    with pytest.raises(AnchorError, match="2 times"):
        remove_link(twice, "Sen1985")


# ------------------------------------------------------------- the sweep


def _mixed() -> str:
    """Two links to unwrap and one to keep, one of each form."""
    keep = ('<w:hyperlink w:anchor="Keep"><w:r><w:rPr>'
            '<w:rStyle w:val="Hyperlink"/></w:rPr>'
            "<w:t>Table 2</w:t></w:r></w:hyperlink>")
    return para(run("See "), MARK + LINKED + MARK_END, run(", "),
                field('HYPERLINK \\l "Fig2"', "Figure 2"),
                run(" and "), keep, run("."))


def test_the_sweep_unwraps_what_is_not_KEPT_and_leaves_the_rest():
    """Splitting a manuscript into a main file and a supplement leaves
    links whose bookmark is now in the OTHER file. Every one has to lose
    the link and keep the words; the ones still reachable must not."""
    out, gone = remove_links(_mixed(), keep={"Keep"})

    assert gone == ["Sen1985", "Fig2"], "document order, both forms"
    assert 'w:anchor="Keep"' in out and "Table 2" in out
    assert 'w:anchor="Sen1985"' not in out and "instrText" not in out


def test_the_sweep_keeps_every_word_on_the_page():
    from docxkit._xml import visible_text

    before = _mixed()
    out, _ = remove_links(before, keep={"Keep"})

    assert visible_text(out) == visible_text(before)


def test_the_sweep_leaves_no_orphan_link_STYLING():
    """The words are prose now and must stop looking clickable — and the
    `w:rPr` shell the style leaves behind goes with it."""
    out, _ = remove_links(_mixed(), keep={"Keep"})

    assert out.count('w:val="Hyperlink"') == 1, "only the kept link's"
    assert "<w:rPr></w:rPr>" not in out


def test_the_sweep_keeps_bookmarks_ALONE():
    """The inverse of `remove_link`'s default, and deliberate: the
    anchors a sweep unwraps are ones being kept somewhere else, so
    deleting their in-text twins would take the targets with the
    links."""
    out, _ = remove_links(_mixed(), keep={"Keep"})

    assert 'w:name="Sen1985txt"' in out


def test_keeping_everything_changes_nothing():
    same = _mixed()

    out, gone = remove_links(same, keep={"Sen1985", "Fig2", "Keep"})

    assert gone == [] and out == same


def test_keeping_NOTHING_unwraps_them_all():
    out, gone = remove_links(_mixed(), keep=())

    assert gone == ["Sen1985", "Fig2", "Keep"]
    assert "w:hyperlink" not in out and "instrText" not in out


# ----------------------------------------------------- the shared reader


def test_relabel_and_remove_read_the_same_links():
    """`_label_spans` is `_links_to` now. The two operations must agree
    about what a link IS, or one of them is addressing something the
    other cannot see — which is how the paper came to re-derive the
    scan privately in the first place."""
    for shape in (_element(), _fielded()):
        relabelled = relabel_link(shape, "Sen1985", "Sen (1985a)")
        assert "Sen (1985a)" in relabelled

        removed, label = remove_link(shape, "Sen1985")
        assert label == "Sen (1985)" and "Sen (1985)" in removed


def test_the_link_STYLE_is_stripped_whatever_the_attribute_order():
    """CONTRIBUTING's second trap: an element written in another
    attribute order is the same element. Spelled one way, the blue
    underline stays on words that link nowhere."""
    odd = LINKED.replace('<w:rStyle w:val="Hyperlink"/>',
                         '<w:rStyle w:themeColor="hyperlink" '
                         'w:val="Hyperlink"/>')

    out, _ = remove_link(para(run("See "), odd, run(".")), "Sen1985")

    assert "Hyperlink" not in out
