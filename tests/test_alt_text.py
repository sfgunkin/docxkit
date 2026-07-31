"""Figure alt text: audit and setter, per drawing not per image part."""
from __future__ import annotations

import pytest

from docxkit.errors import AnchorError
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


def test_set_alt_text_adds_the_attribute():
    out = set_alt_text(DOC, "Figure 2.", "Two lines crossing")
    found = alt_texts(out)
    assert found[1].descr == "Two lines crossing"
    assert not found[1].missing
    assert found[2].missing               # only the addressed drawing


def test_set_alt_text_replaces_an_existing_one():
    out = set_alt_text(DOC, "Figure 1.", 'Say "new" & <better>')
    (first, *_) = alt_texts(out)
    assert first.descr == "Say &quot;new&quot; &amp; &lt;better&gt;"


def test_multi_image_figures_address_by_index():
    out = set_alt_text(DOC, "Figure 2.", "The third chart",
                       image_index=1)
    found = alt_texts(out)
    assert found[2].descr == "The third chart"
    assert found[1].missing


def test_an_index_past_the_drawings_refuses():
    with pytest.raises(AnchorError, match="no image_index"):
        set_alt_text(DOC, "Figure 1.", "x", image_index=5)
