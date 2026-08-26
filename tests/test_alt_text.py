"""Figure alt text: audit and setter, per drawing not per image part."""
from __future__ import annotations

import dataclasses

import pytest

from docxkit.errors import AnchorError, PackageError
from docxkit.figures import alt_texts, set_alt_text


def para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def drawing(rid: str, *, name: str = "Picture 1",
            descr: str | None = None) -> str:
    d = f' descr="{descr}"' if descr is not None else ""
    return (f'<w:p><w:r><w:drawing><wp:inline>'
            f'<wp:docPr id="1" name="{name}"{d}/>'
            f'<a:blip r:embed="{rid}"/>'
            f"</wp:inline></w:drawing></w:r></w:p>")


DOC = (para("Figure 1. First exhibit")
       + drawing("rId4", name="Chart 1", descr="A described chart")
       + para("Figure 2. Second exhibit")
       + drawing("rId5", name="Chart 2")
       + drawing("rId6", name="Chart 3", descr="  ")
       + para("Some prose between."))


def test_audit_attributes_drawings_to_their_captions():
    found = alt_texts(DOC)
    assert [(d.caption or "")[:8] for d in found] == \
        ["Figure 1", "Figure 2", "Figure 2"]
    assert [d.missing for d in found] == [False, True, True]


def test_blank_descr_counts_as_missing():
    found = alt_texts(DOC)
    assert found[2].descr == "  " and found[2].missing


def test_a_drawing_outside_any_caption_window_is_still_listed():
    doc = para("No captions here.") + drawing("rId9", name="Logo")
    (d,) = alt_texts(doc)
    assert d.caption is None
    assert d.missing


def test_a_drawing_in_the_CAPTION_PARAGRAPH_belongs_to_no_caption():
    """`range(caption_index + 1, …)` — the window opens AFTER the
    caption, and the arithmetic that says so is invisible while no
    fixture puts a drawing in the caption's own paragraph. A caption
    typed above an inline image, in one paragraph, is an ordinary Word
    layout, and this is the limit it meets: the drawing is listed and
    reported for its alt text, with no caption beside it.

    Pinned as the current answer rather than argued for. What it must
    not do is quietly attribute the image to the caption ABOVE it, which
    is what a window opening one paragraph early would do to every
    figure in the document."""
    # the caption sits at an ODD index, where `i | 1` is `i` and not
    # `i + 1` — at index 0 the two agree and the fixture proves nothing
    doc = (para("Prose before the exhibits.")
           + '<w:p><w:r><w:t>Figure 1. In one paragraph</w:t>'
           + '<w:drawing><wp:inline><wp:docPr id="1" name="Chart"/>'
           + '<a:blip r:embed="rId7"/></wp:inline></w:drawing></w:r></w:p>'
           + para("Figure 2. The next exhibit"))

    (d,) = alt_texts(doc)

    assert d.caption is None, "not its own caption's, and not Figure 2's"
    assert d.missing


def test_set_alt_text_adds_the_attribute():
    out = set_alt_text(DOC, "Figure 2.", "Two lines crossing")
    found = alt_texts(out)
    assert found[1].descr == "Two lines crossing"
    assert not found[1].missing
    assert found[2].missing               # only the addressed drawing


def test_set_alt_text_changes_NOTHING_ELSE_in_the_document():
    """The setter splices at `p.start() + dm.start()` — the drawing's
    offset in the document, from its paragraph's — and every assertion
    above reads the attribute back through `alt_texts`, which finds it
    wherever the splice landed. A wrong offset overwrites the six
    characters before the drawing and the alt text still reads correctly.

    Written as "the document, plus one attribute": `+` against `^` and
    `-` is only visible from the parts that did NOT change."""
    out = set_alt_text(DOC, "Figure 2.", "Two lines crossing")

    assert out.replace(' descr="Two lines crossing"', "", 1) == DOC


def test_set_alt_text_replaces_an_existing_one():
    out = set_alt_text(DOC, "Figure 1.", 'Say "new" & <better>')
    (first, *_) = alt_texts(out)
    assert first.descr == "Say &quot;new&quot; &amp; &lt;better&gt;"
    # and nothing else moved — Figure 1's drawing is the one whose
    # paragraph offset and drawing END share no bits, so `p.start() |
    # dm.end()` is only visible here
    assert out.replace('descr="Say &quot;new&quot; &amp; &lt;better&gt;"',
                       'descr="A described chart"', 1) == DOC


def test_multi_image_figures_address_by_index():
    out = set_alt_text(DOC, "Figure 2.", "The third chart",
                       image_index=1)
    found = alt_texts(out)
    assert found[2].descr == "The third chart"
    assert found[1].missing


def test_an_index_past_the_drawings_refuses():
    with pytest.raises(AnchorError, match="no image_index"):
        set_alt_text(DOC, "Figure 1.", "x", image_index=5)


# --- what the first mutation run found (2026-08-17, figures.py 30.8 %) ---
#
# `set_alt_text` carried 49 survivors, seventeen of them on the branch
# that inserts the attribute into a docPr WITH CHILDREN — which no
# fixture here had, because the drawing helper writes a self-closing
# one. The attribute was only ever read back through `alt_texts`, so
# the markup it produced was never looked at.

def docpr_with_children(rid: str, *, descr: str | None = None) -> str:
    """A docPr Word writes when the picture carries a hyperlink or a
    non-visual property — an open tag with children, not `<... />`."""
    d = f' descr="{descr}"' if descr is not None else ""
    return (f'<w:p><w:r><w:drawing><wp:inline>'
            f'<wp:docPr id="4" name="Chart 4"{d}>'
            '<a:hlinkClick r:id="rIdLink"/></wp:docPr>'
            f'<a:blip r:embed="{rid}"/>'
            "</wp:inline></w:drawing></w:r></w:p>")


def test_the_attribute_lands_in_a_SELF_CLOSING_docPr_as_markup():
    """Read back through `alt_texts` this looks the same however it was
    written; read as XML, one character off is a document Word refuses
    to open."""
    out = set_alt_text(DOC, "Figure 2.", "Two lines crossing")

    assert ('<wp:docPr id="1" name="Chart 2" descr="Two lines crossing"/>'
            in out)


def test_the_attribute_lands_in_a_docPr_WITH_CHILDREN():
    """The branch seventeen mutants were living in. The closing `>` is
    the only difference from the self-closing case, and cutting the
    wrong number of characters either eats it or leaves the children
    orphaned outside the element."""
    doc = para("Figure 3. A linked chart") + docpr_with_children("rId9")

    out = set_alt_text(doc, "Figure 3.", "A described chart")

    assert ('<wp:docPr id="4" name="Chart 4" descr="A described chart">'
            '<a:hlinkClick r:id="rIdLink"/></wp:docPr>' in out)


def test_a_docPr_with_children_keeps_them_when_the_descr_is_REPLACED():
    doc = para("Figure 3. A linked chart") + docpr_with_children(
        "rId9", descr="the old text")

    out = set_alt_text(doc, "Figure 3.", "the new text")

    assert '<a:hlinkClick r:id="rIdLink"/></wp:docPr>' in out
    assert "the old text" not in out
    assert out.count("descr=") == 1


def test_the_replaced_docPr_keeps_every_other_attribute():
    """`descr` is one attribute among several — id, name, and whatever
    Word added. Rewriting the element rather than the attribute would
    drop them, and `name` is what an accessibility checker lists."""
    out = set_alt_text(DOC, "Figure 1.", "Replacement text")

    assert ('<wp:docPr id="1" name="Chart 1" descr="Replacement text"/>'
            in out)


def test_only_the_ADDRESSED_drawing_is_rewritten():
    """One `replace`, once: the two drawings under Figure 2 differ only
    by their name and embed, and a document-wide substitution would
    describe both."""
    out = set_alt_text(DOC, "Figure 2.", "Two lines crossing")

    assert out.count('descr="Two lines crossing"') == 1


def test_an_image_index_EXACTLY_past_the_last_drawing_is_refused():
    """`>=`, not `>`: index 2 of two drawings is one past the end, and
    `>` lets it through to an IndexError from inside the builder."""
    with pytest.raises(AnchorError, match="has 2 drawing"):
        set_alt_text(DOC, "Figure 2.", "x", image_index=2)


def test_the_LAST_drawing_of_a_figure_is_addressable():
    """...and the boundary holds from the other side: index 1 of two is
    the second drawing, not a refusal."""
    out = set_alt_text(DOC, "Figure 2.", "The second one", image_index=1)

    assert alt_texts(out)[2].descr == "The second one"


def test_a_drawings_NAME_is_read_back_with_it():
    """`name or ""` — an accessibility report lists the name Word shows
    in its own pane, and `and` would blank every one of them."""
    found = alt_texts(DOC)

    assert [d.name for d in found] == ["Chart 1", "Chart 2", "Chart 3"]


def test_the_EMBED_id_is_read_back_with_it():
    """Which image part the description belongs to, for a figure that
    shares its picture with another."""
    found = alt_texts(DOC)

    assert [d.embed for d in found] == ["rId4", "rId5", "rId6"]


def test_a_drawing_with_NO_docPr_reports_no_name_and_no_text():
    """Not a crash: a drawing Word wrote without one is still a drawing
    the audit has to list as undescribed."""
    doc = para("Figure 4. Bare") + (
        '<w:p><w:r><w:drawing><wp:inline>'
        '<a:blip r:embed="rIdBare"/></wp:inline></w:drawing></w:r></w:p>')

    (d,) = alt_texts(doc)

    assert (d.name, d.descr, d.embed) == ("", None, "rIdBare")
    assert d.missing


def test_setting_alt_text_on_a_drawing_with_no_docPr_is_refused():
    doc = para("Figure 4. Bare") + (
        '<w:p><w:r><w:drawing><wp:inline>'
        '<a:blip r:embed="rIdBare"/></wp:inline></w:drawing></w:r></w:p>')

    with pytest.raises(PackageError, match="no wp:docPr"):
        set_alt_text(doc, "Figure 4.", "x")


def test_an_AltText_row_cannot_be_edited_after_the_audit():
    """The audit's rows are the answer a submission check reads; a row
    assigned to somewhere downstream would make it agree with whoever
    wrote last."""
    (first, *_) = alt_texts(DOC)

    with pytest.raises(dataclasses.FrozenInstanceError):
        first.descr = "something else"      # type: ignore[misc]


# --- a caption BELOW its figure (2026-08-27, Aging_Well) ---------------
#
# The accessibility gate was permanently red on that paper and the only
# writer that could clear it refused: `set_alt_text` addressed its
# drawing through a forward-only window, so all three captions raised
# `AnchorError: has 0 drawing(s)`. A journal accessibility pass could
# not be done through docxkit at all.

GAP = "".join(para(f"body prose {i}") for i in range(9))

BELOW = (GAP
         + drawing("rId4", name="Diagram 1")
         + para("Figure 1. The capability space")
         + GAP
         + drawing("rId5", name="Diagram 2")
         + para("Figure 2. Freedom and functioning")
         + GAP)


def test_alt_texts_attributes_a_drawing_to_the_caption_BELOW_it():
    """`(no caption window)` read as "this drawing has no caption" for a
    caption sitting one paragraph away, on the other side."""
    found = [d for d in alt_texts(BELOW) if d.embed]

    assert [(d.caption or "")[:8] for d in found] == ["Figure 1", "Figure 2"]


def test_set_alt_text_reaches_a_figure_captioned_BELOW_it():
    """The gate could be read but never cleared."""
    out = set_alt_text(BELOW, "Figure 2.", "Freedom on one axis")

    (described,) = [d for d in alt_texts(out) if not d.missing]
    assert described.embed == "rId5"
    assert described.descr == "Freedom on one axis"


def test_alt_text_lands_on_the_RIGHT_figure_when_captions_sit_below():
    """Off by one on this side describes Figure 1's diagram under
    Figure 2 — and the check then reports both as done, which is the
    failure the forward window was written to prevent, mirrored."""
    out = set_alt_text(BELOW, "Figure 1.", "The capability space")

    described = {d.embed: d.descr for d in alt_texts(out) if not d.missing}
    assert described == {"rId4": "The capability space"}
