"""What an equation keeps when a revision empties part of it — the review
of 2026-11-01 on the ctrlPr and reject-shell fixes.

Each of these lost something a reader or a gate needs:

* a bookmark or comment range starting inside a removed math object was
  lifted INTO its equation, and then the equation, left with no glyph,
  went with it: a lone ``bookmarkEnd``, a comment with no start (MDI's
  comment 97 on a real file), and the redline refused by the gates;
* a math run holding only a ``w:footnoteReference`` or a
  ``w:commentReference`` has no ``m:t``, so the prune called it an empty
  shell and deleted it from every equation a revision touched;
* under a ``where=`` predicate the prune removed an object that still
  held a revision the predicate had declined — a pending change, gone;
* a flag nested inside a flag (`m:ctrlPr/w:ins/w:del`), two flags on one
  object, a flag in an ARGUMENT's ``m:ctrlPr``, the text a predicate is
  shown, a comment reference lifted bare under ``m:oMath``, and a display
  block left holding no equation.
"""
from __future__ import annotations

import re

from docxkit.revisions import accept, by_author, reject

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
      '2006/main" xmlns:m="http://schemas.openxmlformats.org/'
      'officeDocument/2006/math"')


def body(*paras: str) -> str:
    return f"<w:document {NS}><w:body>{''.join(paras)}</w:body></w:document>"


def mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def wr(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def mark(kind: str, author: str = "A", rid: int = 1, inner: str = "") -> str:
    return (f'<w:{kind} w:id="{rid}" w:author="{author}" '
            f'w:date="2026-11-01T00:00:00Z">{inner}</w:{kind}>')


def flag(kind: str, author: str = "A", rid: int = 1) -> str:
    inner = mark(kind, author, rid, "<w:rPr><w:i/></w:rPr>")
    return f"<m:ctrlPr>{inner}</m:ctrlPr>"


def sub(base: str, index: str, kind: str = "", author: str = "A",
        rid: int = 1) -> str:
    props = f"<m:sSubPr>{flag(kind, author, rid)}</m:sSubPr>" if kind else ""
    return (f"<m:sSub>{props}<m:e>{base}</m:e>"
            f"<m:sub>{index}</m:sub></m:sSub>")


def eqp(*inner: str, after: str = "") -> str:
    return f"<w:p><m:oMath>{''.join(inner)}</m:oMath>{after}</w:p>"


def glyphs(xml: str) -> list[str]:
    return re.findall(r"<m:t>([^<]*)</m:t>", xml)


# ------------------------------------------------- markers in a dropped eq --


def test_a_bookmark_STARTING_in_a_dropped_equation_keeps_both_halves():
    """The subscript is the equation's only content; the bookmark runs on
    into kept prose, so Word keeps it. Its start must not go with the
    equation the rejection emptied."""
    eq = sub('<w:bookmarkStart w:id="7" w:name="eq"/>' + mr("p"),
             mr("1"), "ins")
    out = reject(body(eqp(eq, after=wr("kept prose")
                          + '<w:bookmarkEnd w:id="7"/>')))

    assert "<m:oMath" not in out
    assert out.count("<w:bookmarkStart") == out.count("<w:bookmarkEnd") == 1
    assert out.index("<w:bookmarkStart") < out.index("<w:bookmarkEnd")
    assert "kept prose" in out


def test_a_comment_range_STARTING_in_a_dropped_equation_keeps_its_start():
    eq = sub('<w:commentRangeStart w:id="3"/>' + mr("p"), mr("1"), "ins")
    after = (wr("kept") + '<w:commentRangeEnd w:id="3"/>'
             '<w:r><w:commentReference w:id="3"/></w:r>')
    out = reject(body(eqp(eq, after=after)))

    assert out.count("<w:commentRangeStart") == 1
    assert out.index("<w:commentRangeStart") < out.index("<w:commentRangeEnd")


def test_a_bookmark_WHOLLY_inside_a_removed_object_goes_with_it():
    """Everything it spans goes, so Word drops both halves — the flagged
    object's content is what decides, not the flag's empty `w:rPr`."""
    eq = sub('<w:bookmarkStart w:id="5" w:name="gone"/>' + mr("p")
             + '<w:bookmarkEnd w:id="5"/>', mr("1"), "ins")
    out = reject(body(eqp(mr("x"), eq, mr("y"), mr("z"))))

    assert "bookmark" not in out
    assert glyphs(out) == ["x", "y", "z"]


# ------------------------------------------------- runs that hold no m:t --


def test_a_FOOTNOTE_reference_in_a_touched_equation_survives_both_views():
    """Three glyph runs, a deleted one, an inserted one, and a run that
    holds only the footnote's reference."""
    ref = '<m:r><w:footnoteReference w:id="2"/></m:r>'
    eq = (mr("a") + mr("b") + mr("c") + mark("del", rid=1, inner=mr("d"))
          + mark("ins", rid=2, inner=mr("e")) + ref)

    for view in (accept, reject):
        out = view(body(eqp(eq)))
        assert out.count('<w:footnoteReference w:id="2"/>') == 1, view


def test_a_COMMENT_reference_in_an_emptied_equation_keeps_the_equation():
    ref = '<m:r><w:commentReference w:id="4"/></m:r>'
    out = reject(body(eqp(mark("ins", inner=mr("q")), ref)))

    assert out.count('<w:commentReference w:id="4"/>') == 1


# ------------------------------------------- pending under a predicate --


def test_SELECTIVE_accept_keeps_an_object_still_PENDING_for_another_author():
    """A typed the fraction; B deleted its runs. Accepting B's deletions
    empties it, but A's insertion is still undecided: it stays, flagged."""
    frac = (f"<m:f><m:fPr>{flag('ins', 'A', 1)}</m:fPr>"
            f"<m:num>{mark('del', 'B', 2, mr('1'))}</m:num>"
            f"<m:den>{mark('del', 'B', 3, mr('2'))}</m:den></m:f>")

    out = accept(body(eqp(mr("x"), frac)), where=by_author("B"))

    assert "<m:f>" in out and 'w:author="A"' in out
    assert 'w:author="B"' not in out


def test_SELECTIVE_reject_keeps_an_equation_whose_object_is_still_PENDING():
    frac = (f"<m:f><m:fPr>{flag('ins', 'A', 1)}</m:fPr>"
            f"<m:num>{mark('ins', 'B', 2, mr('1'))}</m:num>"
            f"<m:den>{mark('ins', 'B', 3, mr('2'))}</m:den></m:f>")

    out = reject(body(eqp(frac)), where=by_author("B"))

    assert "<m:oMath>" in out and "<m:f>" in out
    assert 'w:author="A"' in out and glyphs(out) == []


# ----------------------------------------------------- flags and owners --


def test_an_object_typed_by_A_and_DELETED_by_B_goes_on_accept():
    """`m:ctrlPr/w:ins/w:del`: the inner deletion removes the object."""
    nested = (f"<m:sSub><m:sSubPr><m:ctrlPr>"
              f"{mark('ins', 'A', 1, mark('del', 'B', 2, '<w:rPr/>'))}"
              f"</m:ctrlPr></m:sSubPr><m:e>{mr('p')}</m:e>"
              f"<m:sub>{mr('1')}</m:sub></m:sSub>")
    xml = body(eqp(mr("x"), nested, mr("y"), mr("z")))

    for out in (accept(xml), accept(xml, where=by_author("B")),
                reject(xml)):
        assert "<m:sSub" not in out
        assert glyphs(out) == ["x", "y", "z"]


def test_TWO_flags_on_one_object_remove_it_once_and_raise_nothing():
    twice = (f"<m:sSub><m:sSubPr><m:ctrlPr>"
             f"{mark('ins', rid=1, inner='<w:rPr/>')}"
             f"{mark('ins', rid=2, inner='<w:rPr/>')}</m:ctrlPr></m:sSubPr>"
             f"<m:e>{mr('p')}</m:e><m:sub>{mr('1')}</m:sub></m:sSub>")

    out = reject(body(eqp(mr("x"), twice, mr("y"))))

    assert "<m:sSub" not in out and glyphs(out) == ["x", "y"]


def test_a_flag_in_an_ARGUMENTS_ctrlPr_flags_no_object():
    """`m:num/m:ctrlPr` — the numerator's control character, not the
    fraction's: rejecting it removes the flag, and the fraction stays
    with every glyph. Beside an object flagged in its OWN properties,
    which goes."""
    frac = (f"<m:f><m:num>{mr('1')}{flag('ins', rid=1)}</m:num>"
            f"<m:den>{mr('2')}</m:den></m:f>")
    out = reject(body(eqp(mr("x"), frac, sub(mr("p"), mr("i"), "ins", rid=2),
                          mr("y"))))

    assert out.count("<m:f>") == 1 and "<m:sSub" not in out
    assert glyphs(out) == ["x", "1", "2", "y"]
    assert "w:ins" not in out


def test_a_predicate_is_shown_the_TEXT_of_the_object_its_flag_removes():
    seen: list[str] = []

    def pick(r):
        seen.append(r.text)
        return "p" in r.text

    out = reject(body(eqp(mr("x"), sub(mr("p"), mr("1"), "ins", rid=1),
                          sub(mr("q"), mr("2"), "ins", rid=2), mr("y"))),
                 where=pick)

    assert sorted(seen) == ["p1", "q2"]
    assert glyphs(out) == ["x", "q", "2", "y"]


def test_a_comment_reference_in_a_removed_object_stays_IN_A_MATH_RUN():
    eq = sub(mr("p") + '<m:r><w:commentReference w:id="4"/></m:r>',
             mr("1"), "ins")
    out = reject(body(eqp(mr("x"), eq, mr("y"))))

    assert re.search(r'<m:r><w:commentReference w:id="4"/></m:r>', out)
    assert not re.search(r'</m:r><w:commentReference', out)


def test_a_display_block_left_with_no_equation_goes_too():
    """`m:oMathPara` requires an `m:oMath`: three display equations,
    each nothing but a deleted object, accepted."""
    paras = [f"<w:p><m:oMathPara><m:oMath>"
             f"{sub(mr('q'), mr(str(i)), 'del', rid=i)}"
             f"</m:oMath></m:oMathPara></w:p>" for i in range(1, 4)]

    out = accept(body(*paras, f"<w:p>{wr('after')}</w:p>"))

    assert "<m:oMathPara" not in out and "<m:oMath" not in out
    assert "after" in out
