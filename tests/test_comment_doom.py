"""Which comments a view keeps: Word deletes a comment outright when its
whole range goes or its reference goes (backlog S2, measured 2026-11-02
against Word's Accept All and Reject All on every redline here that holds
comments). The engine kept every comment in both views."""
from __future__ import annotations

from docxkit.revisions import accept, by_author, reject

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
      '2006/main" xmlns:m="http://schemas.openxmlformats.org/'
      'officeDocument/2006/math"')


def body(*paras: str) -> str:
    return f"<w:document {NS}><w:body>{''.join(paras)}</w:body></w:document>"


def r(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def ins(inner: str, rid: int = 1, author: str = "A") -> str:
    return (f'<w:ins w:id="{rid}" w:author="{author}" '
            f'w:date="2026-11-02T00:00:00Z">{inner}</w:ins>')


def dele(text: str, rid: int = 2, author: str = "A") -> str:
    return (f'<w:del w:id="{rid}" w:author="{author}" '
            f'w:date="2026-11-02T00:00:00Z"><w:r><w:delText '
            f'xml:space="preserve">{text}</w:delText></w:r></w:del>')


def start(cid: int) -> str:
    return f'<w:commentRangeStart w:id="{cid}"/>'


def end(cid: int) -> str:
    return f'<w:commentRangeEnd w:id="{cid}"/>'


def ref(cid: int) -> str:
    return (f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
            f'<w:commentReference w:id="{cid}"/></w:r>')


def p(*inner: str) -> str:
    return f"<w:p>{''.join(inner)}</w:p>"


def markers(xml: str, cid: int) -> int:
    return xml.count(f'w:id="{cid}"/>')


# ---------------------------------------------------------------- range --


def test_a_comment_on_DELETED_text_goes_on_accept_and_stays_on_reject():
    xml = body(p(r("Kept. "), start(3), dele("cut words"), end(3), ref(3),
                 r(" after.")))

    acc = accept(xml)
    assert markers(acc, 3) == 0, acc
    assert "CommentReference" not in acc, "the reference's run goes too"
    assert "Kept. " in acc and " after." in acc
    assert markers(reject(xml), 3) == 3


def test_the_range_rule_drops_the_reference_even_where_it_STANDS():
    """The range is all deleted text and the reference sits in kept
    prose after it: Word deletes the comment, reference included."""
    xml = body(p(start(5), dele("gone"), end(5), r("stays "), ref(5)))

    out = accept(xml)

    assert markers(out, 5) == 0 and "stays " in out


def test_a_comment_whose_range_KEEPS_text_stays_in_both_views():
    xml = body(p(start(7), r("kept "), dele("cut"), ins(r("new")), end(7),
                 ref(7)))

    for view in (accept, reject):
        assert markers(view(xml), 7) == 3, view


def test_a_range_across_a_SURVIVING_paragraph_mark_is_kept():
    """`_doomed_bookmarks`' rule: a paragraph mark that stays between the
    two ends is content that stays."""
    xml = body(p(start(3), dele("first")), p(dele("second"), end(3), ref(3)))

    assert markers(accept(xml), 3) == 3


# ------------------------------------------------------------ reference --


def test_a_reference_TYPED_IN_goes_on_reject_with_its_range_of_kept_text():
    """sr1_12032023's shape: the range is untouched prose, the reference
    was inserted under tracking; Word's Reject All deletes the comment."""
    xml = body(p(start(5), r("Untouched prose that stays."), end(5),
                 ins(ref(5))))

    out = reject(xml)

    assert markers(out, 5) == 0, out
    assert "Untouched prose that stays." in out
    assert markers(accept(xml), 5) == 3


def test_a_reference_DELETED_goes_on_accept_with_its_range():
    xml = body(p(start(7), r("prose "), end(7),
                 '<w:del w:id="2" w:author="A" w:date="d">' + ref(7)
                 + "</w:del>"))

    assert markers(accept(xml), 7) == 0
    assert markers(reject(xml), 7) == 3


# ------------------------------------------------------- only that one --


def test_only_the_doomed_comment_goes_of_THREE():
    xml = body(p(start(3), r("kept "), end(3), ref(3),
                 start(5), dele("cut"), end(5), ref(5),
                 start(7), r("also kept"), end(7), ref(7)))

    out = accept(xml)

    assert [markers(out, c) for c in (3, 5, 7)] == [3, 0, 3]


def test_a_PREDICATE_that_declines_the_deletion_keeps_the_comment():
    xml = body(p(start(3), dele("cut", author="B"), end(3), ref(3),
                 start(5), dele("cut", rid=4, author="C"), end(5), ref(5)))

    out = accept(xml, where=by_author("C"))

    assert markers(out, 3) == 3 and markers(out, 5) == 0


def test_a_comment_on_text_a_MOVE_takes_away_goes_on_ACCEPT():
    """Charter_Cities_in_Exile, COL_chapter: Word's Accept All drops a
    comment whose range or reference is in the `moveFrom`. Five comments,
    the third on the moved text."""
    moved = (f'<w:moveFrom w:id="1" w:author="A" w:date="d">{start(5)}'
             f'{r("moved")}{end(5)}{ref(5)}</w:moveFrom>')
    others = [start(c) + r(f"kept {c}") + end(c) + ref(c)
              for c in (1, 3, 7, 9)]
    xml = body(p(others[0], others[1], moved, others[2], others[3]))

    out = accept(xml)

    assert [markers(out, c) for c in (1, 3, 5, 7, 9)] == [3, 3, 0, 3, 3]


def test_a_comment_in_a_rejected_MOVE_is_lifted_not_dropped():
    """On reject Word dropped one comment in a `moveTo` and kept others of
    the same shape (2026-11-02), so moves stay outside the rule there:
    the markers are lifted, as a bookmark's are."""
    moved = (f'<w:moveTo w:id="1" w:author="A" w:date="d">{start(3)}'
             f'{r("moved")}{end(3)}</w:moveTo>')
    xml = body(p(moved, ref(3)))

    out = reject(xml)

    assert out.count(start(3)) == out.count(end(3)) == 1
    assert markers(accept(xml), 3) == 3
