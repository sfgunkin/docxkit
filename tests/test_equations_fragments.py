"""Lifting an equation out of a manuscript, and reading one back.

`harvest` -> `standalone` -> `clone` is the documented way to reuse an
equation the document already renders, and `to_latex` is how one is read.
Both met the same shape and handled it differently: a redline wraps a
math run's own text in `w:ins`/`w:del` and stamps the revision with a
namespace nobody listed, so the fragment could be neither declared nor
fully read.

The numbers in the comments come from the corpus these papers live in —
15,816 equations across 400 documents.
"""
from __future__ import annotations

import pytest
from conftest import NS

from docxkit import equations
from docxkit.equations import M_NS, clone, harvest, standalone, to_latex
from docxkit.errors import AnchorError

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DU = "http://schemas.microsoft.com/office/word/2023/wordml/word16du"


def omath(inner: str) -> str:
    return f"<m:oMath>{inner}</m:oMath>"


def mrun(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def document(body: str, *, extra_ns: str = "") -> str:
    return (f'<?xml version="1.0"?><w:document {NS}{extra_ns}>'
            f"<w:body>{body}</w:body></w:document>")


# ------------------------------------------- namespaces the source knows --


def test_a_prefix_the_module_never_heard_of_resolves_from_the_source():
    """`w16du` appears in 158 equations across six of these manuscripts.

    The list in `_NS_URIS` can only ever hold the prefixes someone
    thought of, and Word keeps adding them — so `standalone` refused the
    very fragments `harvest` exists to lift. The document already says
    what the prefix means; asking it is correct and does not expire.
    """
    # As SLICED: a fragment cut out of document.xml inherits its
    # declarations from the part's root and carries none of its own,
    # which is the whole reason standalone exists.
    frag = omath('<m:r><w:ins w:id="1" '
                 'w16du:dateUtc="2024-07-01T22:23:00Z">'
                 "<m:t>a</m:t></w:ins></m:r>")
    doc = document(frag, extra_ns=f' xmlns:w16du="{DU}"')

    with pytest.raises(AnchorError, match="w16du"):
        standalone(frag)                       # nothing declares it

    got = standalone(frag, source=doc)
    assert f'xmlns:w16du="{DU}"' in got        # the REAL uri, not a stand-in
    assert "urn:docxkit:undeclared" not in got


def test_the_refusal_says_how_to_fix_it():
    frag = omath("<m:r><zz:x/><m:t>a</m:t></m:r>")
    with pytest.raises(AnchorError, match="pass source="):
        standalone(frag)


def test_a_fragment_that_declares_its_own_prefix_needs_no_source():
    """Which is what makes the output re-enterable: `standalone` puts the
    declarations ON the element, so feeding its own result back in — the
    `clone(harvest(...))` pair — has to be accepted, not refused for a
    prefix the fragment now carries itself."""
    frag = omath(f'<m:r><w:ins xmlns:w="{W_NS}" xmlns:w16du="{DU}" '
                 f'w:id="1" w16du:dateUtc="x"><m:t>a</m:t></w:ins></m:r>')
    assert standalone(frag)


def test_harvest_hands_the_source_over_for_you():
    """The caller has the document in hand; making them pass it twice is
    how the refusal above survives a fix to `standalone` alone."""
    frag = omath('<m:r><w:ins w:id="1" '
                 'w16du:dateUtc="2024-07-01T22:23:00Z">'
                 "<m:t>Q</m:t></w:ins></m:r>")
    doc = document(frag, extra_ns=f' xmlns:w16du="{DU}"')
    got = harvest(doc, "Q")
    assert f'xmlns:w16du="{DU}"' in got
    assert clone(got) == got                   # and it composes onward


def test_an_ordinary_equation_serialises_exactly_as_it_always_did():
    """Pinned, because these fragments are INSERTED into manuscripts and
    the papers' rebuilds are compared byte for byte. Verified unchanged
    across all 15,816 equations in the corpus."""
    got = standalone(omath(mrun("x")))
    assert got == (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
        'officeDocument/2006/math" xmlns:w="http://schemas.openxmlformats.'
        'org/wordprocessingml/2006/main" xmlns:w14="http://schemas.'
        'microsoft.com/office/word/2010/wordml" xmlns:w15="http://schemas.'
        'microsoft.com/office/word/2012/wordml" xmlns:w16cid="http://'
        'schemas.microsoft.com/office/word/2016/wordml/cid" xmlns:mc='
        '"http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships"><m:r><m:t>x</m:t></m:r></m:oMath>')


def test_a_source_adds_only_what_the_fragment_actually_uses():
    doc = document("", extra_ns=' xmlns:zz="urn:zz" xmlns:yy="urn:yy"')
    got = standalone(omath(mrun("x")), source=doc)
    assert "urn:zz" not in got and "urn:yy" not in got


# ------------------------------------------------- one element, no more ---


def test_two_equations_in_is_a_refusal_not_the_first_one():
    """`root[0]` returned the first and dropped the rest in silence."""
    with pytest.raises(AnchorError, match="one element"):
        standalone(omath(mrun("a")) + omath(mrun("b")))


def test_prose_around_the_equation_is_a_refusal_too():
    with pytest.raises(AnchorError, match="one element"):
        standalone(omath(mrun("a")) + " and some prose")
    with pytest.raises(AnchorError, match="one element"):
        standalone("lead-in " + omath(mrun("a")))


def test_whitespace_around_the_equation_is_fine():
    assert standalone("  " + omath(mrun("a")) + "\n  ")


# --------------------------------------------- reading an edited equation -


def _edited(kept: str, removed: str) -> str:
    return omath(
        f'<m:r><w:ins xmlns:w="{W_NS}" w:id="1"><m:t>{kept}</m:t>'
        f"</w:ins></m:r>"
        f'<m:r><w:del xmlns:w="{W_NS}" w:id="2"><m:t>{removed}</m:t>'
        f"</w:del></m:r>")


def test_text_inserted_inside_a_math_run_is_read():
    """`e_r` collected only DIRECT `m:t` children, so a run whose text
    Word had wrapped in `w:ins` contributed nothing.

    Measured over the corpus: 589 characters silently absent, and one
    fraction that rendered as `\\frac{}{{}_{}}` because every symbol it
    had sat inside a revision. The module's own rule is that a gap must
    be VISIBLE — `[?m:tag]` — never missing, and this was missing.
    """
    assert to_latex(_edited("a", "b")) == "a"


def test_deleted_text_stays_out_of_the_final_view():
    assert "b" not in to_latex(_edited("a", "b"))


def test_an_equation_that_is_entirely_an_insertion_still_reads():
    frag = omath(f'<m:r><w:ins xmlns:w="{W_NS}" w:id="1">'
                 f"<m:t>η</m:t></w:ins></m:r>")
    assert to_latex(frag).strip() == r"\eta"


def test_the_run_property_still_decides_upright_text():
    """The dispatch changed; the `m:nor` rule on top of it did not."""
    upright = omath("<m:r><m:rPr><m:nor/></m:rPr><m:t>max</m:t></m:r>")
    assert to_latex(upright) == r"\text{max}"


def test_an_ordinary_run_reads_the_same_way_it_did():
    assert to_latex(omath(mrun("x") + mrun("+") + mrun("y"))) == "x+y"


# --------------------------------------------------------------- clone ---


def test_clone_normalises_and_stays_equal_to_standalone():
    frag = omath(mrun("x"))
    assert clone(frag) == standalone(frag)


def test_clone_is_idempotent():
    once = clone(omath(mrun("x")))
    assert clone(once) == once


def test_a_cloned_equation_reads_back_as_the_same_maths():
    frag = omath(mrun("x") + f'<m:sSub><m:e>{mrun("y")}</m:e>'
                             f'<m:sub>{mrun("2")}</m:sub></m:sSub>')
    assert to_latex(clone(frag)) == to_latex(frag)
    assert equations.tokens(clone(frag)) == equations.tokens(frag)


def test_the_math_namespace_survives_a_round_trip():
    got = clone(omath(mrun("x")))
    assert f'xmlns:m="{M_NS}"' in got
