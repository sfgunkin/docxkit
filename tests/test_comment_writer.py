"""One writer for every balloon (review of 2026-10-24).

The classified `tracked.build` path (`annotate` via `_comment_pass`) and
`annotate_in_place` (`annotate_blocks`) each held guards the other
lacked; the 2026-10-14 fixes added guards to one path or the other, and
the next review found them apart again. `comments._write` holds them all
now. Each test here is one numbered case of that BACKLOG entry, and each
failed before the writer was one.
"""
from __future__ import annotations

import re

import pytest
from conftest import comment, dele, ins, make_parts, para, run

from docxkit import comments as C
from docxkit import hygiene, tracked
from docxkit.errors import AnchorError, ScaffoldMissing

OURS = "5A000001"
M_NS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
_STAMP = 'w:author="Revision" w:date="2026-10-24T00:00:00Z"'


def _com(parts: dict[str, bytes]) -> str:
    return parts["word/comments.xml"].decode("utf-8")


def _doc(parts: dict[str, bytes]) -> str:
    return parts["word/document.xml"].decode("utf-8")


def _n(parts) -> int:
    return len(re.findall(r"<w:comment w:id=", _com(parts)))


def always(text):
    return lambda _ctx: text


def _equation(*inserted: str) -> str:
    """A paragraph holding one inline equation with an insertion per
    `inserted` inside it — the 446-of-1,759 shape of LI7."""
    runs = "".join(f'<m:r><w:ins w:id="{70 + i}" {_STAMP}><m:t>{t}</m:t>'
                   f"</w:ins></m:r>" for i, t in enumerate(inserted))
    return para(run("Where "), f"<m:oMath {M_NS}><m:r><m:t>x</m:t></m:r>"
                f"{runs}</m:oMath>", run(" holds."))


# 1 ------------------------------------------------------------ maths


def test_a_balloon_round_an_EQUATION_is_found_again_on_a_rerun():
    """Case 1. Widened when written, looked for unwidened: re-running
    `annotate` on a copy of LI7 added 949, 133, 133."""
    parts = make_parts(_equation("+1") + para(run("a "), ins("b")),
                       comment_items=(comment(1, "seed", OURS),))

    first = C.annotate(parts, always("R1: why"))[0]
    again = C.annotate(parts, always("R1: why"))[0]

    assert (first, again) == (2, 0)


def test_a_rerun_over_a_coalesced_TABLE_adds_nothing():
    """Case 1, found measuring the fix on LI7: the cell carrying the
    table's balloon was skipped, the NEXT cell was then the first of its
    kind, and each re-run gave the table one more (10, then 4)."""
    cells = "".join(f"<w:tc>{para(ins(f'c{i}', rid=80 + i))}</w:tc>"
                    for i in range(3))
    parts = make_parts(f"<w:tbl><w:tr>{cells}</w:tr></w:tbl>",
                       comment_items=(comment(1, "seed", OURS),))

    runs = [C.annotate(parts, always("R2: the table"))[0] for _ in range(3)]

    assert runs == [1, 0, 0]


def test_spans_of_ONE_equation_share_one_balloon_per_reason():
    """Case 1, the stack: every span of an equation is anchored round
    the whole of it, and each wrote its own balloon there — 3 to 25
    identical ones on 20 of LI7's equations."""
    parts = make_parts(_equation("+1", "+2", "+3"),
                       comment_items=(comment(1, "seed", OURS),))

    added = C.annotate(parts, always("R1: the same reason"))[0]

    assert added == 1
    assert _n(parts) == 2


def test_a_second_annotate_blocks_on_an_all_MATHS_proposal_is_refused():
    """Case 1, the other path: its re-run guard read the raw span too."""
    parts = make_parts(_equation("+1", "+2"),
                       comment_items=(comment(1, "seed", OURS),))
    blocks = [([0, 1], "why the maths changed")]
    C.annotate_blocks(parts, blocks, author="A", initials="A")

    with pytest.raises(AnchorError, match="annotated before"):
        C.annotate_blocks(parts, blocks, author="A", initials="A")


# 2 ---------------------------------------------------- coverage


def test_a_person_s_comment_round_a_change_does_not_SKIP_it():
    """Case 2. A referee's query whose range happened to bracket a
    revision made the pass skip the revision as already anchored."""
    body = para('<w:commentRangeStart w:id="1"/>', ins("added"),
                '<w:commentRangeEnd w:id="1"/>')
    parts = make_parts(body, comment_items=(comment(1, "Referee: why?"),))

    assert C.annotate(parts, always("R1: because"))[0] == 1


def test_a_classified_build_SAYS_what_no_balloon_reaches():
    """Case 2. Moves, property-only changes and note revisions got no
    balloon and the build printed "unclassified: 0"."""
    body = (para(run("a "), ins("b"))
            + para('<w:r><w:rPr><w:b/><w:rPrChange w:id="5" '
                   f'{_STAMP}><w:rPr/></w:rPrChange></w:rPr>'
                   "<w:t>bold now</w:t></w:r>"))
    notes = (f'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
             f'wordprocessingml/2006/main"><w:footnote w:id="1">'
             f'{para(ins("in a note", rid=95))}</w:footnote></w:footnotes>')
    parts = make_parts(body, comment_items=(comment(0, "seed"),),
                       footnotes=notes)
    report, said = tracked.BuildReport(), list[str]()

    tracked._comment_pass(parts, always("R1"), generic=None,
                          tables="coalesce", author="A",
                          inputs=(make_parts(para(run("a"))),),
                          report=report, say=said.append)

    joined = " ".join(report.uncommented)
    assert "word/footnotes.xml" in joined and "rPrChange" in joined
    assert any("no balloon can reach" in line for line in said)
    assert any(f.code == "UNCOMMENTED" for f in report.findings())


# 3 --------------------------------------------------- reclassify


def test_reclassify_with_an_EMPTY_marker_touches_nothing():
    """Case 3. As a substring, '' matched every comment in the package."""
    parts = make_parts(para(run("x ")),
                       comment_items=(comment(1, "Referee: clarify"),))
    before = _com(parts)

    assert C.reclassify(parts, always("R9"), generic="") == (0, [])
    assert _com(parts) == before


def test_reclassify_leaves_a_comment_that_QUOTES_the_marker():
    """Case 3. A referee's query quoting "Revision (unclassified)" was
    rewritten with the markers."""
    quoted = f"Why does it say {C.GENERIC} here?"
    body = para('<w:commentRangeStart w:id="1"/>', ins("added"),
                '<w:commentRangeEnd w:id="1"/>')
    parts = make_parts(body, comment_items=(comment(1, quoted),))

    assert C.reclassify(parts, always("R9")) == (0, [])
    assert quoted in _com(parts)


def test_reclassify_shows_the_classifier_the_RANGE():
    """Case 3/4. The context was built from the marker tag: no text, and
    a window ending before the revision."""
    body = para('<w:commentRangeStart w:id="1"/>', ins("inflation"),
                '<w:commentRangeEnd w:id="1"/>')
    parts = make_parts(body, comment_items=(comment(1, C.GENERIC),))
    seen: list[str] = []

    def rule(ctx: C.RevisionContext) -> str:
        seen.append(ctx.text)
        return "R4"

    C.reclassify(parts, rule)

    assert seen == ["inflation"]


def test_a_classified_build_with_an_empty_GENERIC_ships_no_marker():
    """Case 3, the build: `generic=''` rewrote the referee's comment and
    shipped Word's SCAFFOLD balloon."""
    referee = comment(2, "Referee: clarify the sample.", "AAAA0002")
    body = (para('<w:commentRangeStart w:id="0"/>', ins("added"),
                 '<w:commentRangeEnd w:id="0"/>')
            + para(run("Sample."), ins("more", rid=91)))
    parts = make_parts(body, comment_items=(comment(0, C.SCAFFOLD),
                                            referee))
    report = tracked.BuildReport()

    tracked._comment_pass(parts, lambda ctx: "", generic="",
                          tables="coalesce", author="A",
                          inputs=(make_parts(para(run("Sample.")),
                                             comment_items=(referee,)),),
                          report=report, say=lambda _line: None)

    com = _com(parts)
    assert "Referee: clarify the sample." in com
    assert C.SCAFFOLD not in com and C.GENERIC not in com


# 4 -------------------------------------------- Word's seeded comment


def test_Word_s_SEED_is_decided_with_the_XML_context():
    """Case 4. Revision 1's comment was skipped as anchored, and its only
    second chance read the marker tag: a classifier keyed on the
    revision's own words left it bare."""
    body = (para('<w:commentRangeStart w:id="0"/>', dele("very sharply"),
                 '<w:commentRangeEnd w:id="0"/>', run(" rose."))
            + para(run("Core "), ins("inflation", rid=92)))
    parts = make_parts(body, comment_items=(comment(0, C.SCAFFOLD),))
    rules = C.match([("very sharply", "R1: hedged"),
                     ("inflation", "R4: add inflation")])

    tracked._comment_pass(parts, rules, generic=None, tables="coalesce",
                          author="A", inputs=(make_parts(para(run("x"))),),
                          report=tracked.BuildReport(),
                          say=lambda _line: None)

    texts = re.findall(r"<w:t>([^<]*)</w:t>", _com(parts))
    assert sorted(texts) == ["R1: hedged", "R4: add inflation"], texts


def test_a_seed_over_TWO_spans_leaves_each_in_ONE_balloon():
    """Case 4. Word's revision 1 can be several XML spans; each sat
    inside the seed's range AND a balloon of its own."""
    body = para('<w:commentRangeStart w:id="0"/>', ins("one"), run(" "),
                dele("two"), '<w:commentRangeEnd w:id="0"/>')
    parts = make_parts(body, comment_items=(comment(0, "seed reason"),))
    report = tracked.BuildReport()

    tracked._comment_pass(parts, always("R1"), generic=None,
                          tables="coalesce", author="A",
                          inputs=(make_parts(para(run("x"))),),
                          report=report, say=lambda _line: None)

    doc = _doc(parts)
    assert doc.count("commentRangeStart") == 2
    assert report.comments_added == 1, "one new, and the seed reused"


# 5 -------------------------------------------------------- the ids


def test_a_new_balloon_takes_no_paraId_or_durableId_already_USED():
    """Case 5. `BASE + id`, and Word renumbers ids on save while keeping
    paraIds: a later round's clone took a kept balloon's paraId."""
    kept_pid = f"{C._PARA_ID_BASE + 2:08X}"
    parts = make_parts(para(run("a "), ins("b")),
                       comment_items=(comment(1, "kept", kept_pid),))
    parts["word/commentsIds.xml"] = parts["word/commentsIds.xml"].replace(
        b'w16cid:paraId="AAAA0001" w16cid:durableId="0000AAAA"',
        f'w16cid:paraId="{kept_pid}" w16cid:durableId='
        f'"{C._DURABLE_ID_BASE + 2:08X}"'.encode())

    C.annotate(parts, always("R1"))

    pids = re.findall(r'w14:paraId="([0-9A-F]+)"', _com(parts))
    durables = re.findall(r'durableId="([0-9A-F]+)"',
                          parts["word/commentsIds.xml"].decode())
    assert len(pids) == len(set(pids)) == 2
    assert len(durables) == len(set(durables))


# 6 -------------------------------------------------------- de-dup


def test_the_same_reason_in_THREE_paragraphs_is_three_notes():
    """Case 6. Kept through a baseline, next round's de-dup cut them to
    one per reason, anchors and all."""
    body = "".join(para(f'<w:commentRangeStart w:id="{i}"/>', run(f"p{i}"),
                        f'<w:commentRangeEnd w:id="{i}"/>')
                   for i in (1, 2, 3))
    parts = make_parts(body, comment_items=tuple(
        comment(i, "R1: hedged the claim", f"AAAA000{i}") for i in (1, 2, 3)))

    assert hygiene.dedupe_comments(parts) == []
    assert _n(parts) == 3


def test_two_copies_in_ONE_paragraph_are_still_one_note():
    """Case 6, the purpose kept: Compare's copy from each input lands on
    a different run of one paragraph."""
    body = para('<w:commentRangeStart w:id="1"/>', run("a"),
                '<w:commentRangeEnd w:id="1"/>',
                '<w:commentRangeStart w:id="2"/>', run("b"),
                '<w:commentRangeEnd w:id="2"/>')
    parts = make_parts(body, comment_items=(
        comment(1, "Please clarify.", "AAAA0001"),
        comment(2, "Please clarify.", "AAAA0002")))

    assert len(hygiene.dedupe_comments(parts)) == 1


# 7 ---------------------------------------------------- unreachable


def test_a_paragraph_holding_a_TEXT_BOX_is_measured_whole():
    """Case 7. The lazy paragraph pattern ended the host at the box's
    first inner `</w:p>`, so its span read as "no span"."""
    box = ("<w:r><w:drawing><w:txbxContent>" + para(run("in the box"))
           + "</w:txbxContent></w:drawing></w:r>")
    body = ('<w:p><w:pPr><w:rPr><w:b/><w:rPrChange w:id="5" '
            f'{_STAMP}><w:rPr/></w:rPrChange></w:rPr></w:pPr>{box}'
            f'{ins("after the box")}</w:p>')
    parts = make_parts(body, comment_items=(comment(1, "seed", OURS),))

    assert C._unreachable(parts) == []


def test_a_revision_in_a_HEADER_is_not_covered():
    """Case 7. Headers, footers and comments.xml were never read."""
    parts = make_parts(para(run("a "), ins("b")),
                       comment_items=(comment(1, "seed", OURS),),
                       extra={"word/header1.xml": (
                           '<w:hdr xmlns:w="http://schemas.openxmlformats.'
                           'org/wordprocessingml/2006/main">'
                           + para(ins("draft", rid=96)) + "</w:hdr>")})

    (said,) = C._unreachable(parts)
    assert "word/header1.xml" in said
    with pytest.raises(AnchorError, match="header1"):
        C.annotate_blocks(parts, [([0], "why")], author="A", initials="A")


# 8 ------------------------------------------------------- the advice


def test_the_coverage_refusal_does_not_send_you_round_in_a_CIRCLE():
    """Case 8. It said "comment those with add_at", which adds no span,
    so the same refusal came back after the advice was followed."""
    body = (para(run("a "), ins("b"))
            + para('<w:r><w:rPr><w:b/><w:rPrChange w:id="5" '
                   f'{_STAMP}><w:rPr/></w:rPrChange></w:rPr>'
                   "<w:t>bold now</w:t></w:r>"))
    parts = make_parts(body, comment_items=(comment(1, "seed", OURS),))

    with pytest.raises(AnchorError) as caught:
        C.annotate_blocks(parts, [([0], "why")], author="A", initials="A")

    said = str(caught.value)
    assert "partial=True" in said
    assert "Comment those with docxkit.comments.add_at" not in said


def test_add_at_on_a_package_with_NO_comments_says_why():
    """Case 8. A KeyError on 'word/comments.xml'."""
    parts = make_parts(para(run("Leave this alone.")))

    with pytest.raises(ScaffoldMissing, match="no comments part"):
        C.add_at(parts, "alone", "Look at this.")


def test_add_at_CREDITS_who_it_is_told():
    """Case 8. It credited the template comment's author, a referee."""
    parts = make_parts(para(run("Leave this alone.")),
                       comment_items=(comment(1, "Referee's query"),))
    credit = C.Credit("Michael Lokshin", "ML", "2026-10-24T00:00:00Z")

    cid = C.add_at(parts, "alone", "Look at this.", credit=credit)

    head = re.search(rf'<w:comment w:id="{cid}"[^>]*>', _com(parts))
    assert head is not None and 'w:author="Michael Lokshin"' in head.group(0)


def test_annotate_in_place_refuses_BEFORE_Word_is_paid_for(tmp_path):
    """Case 8. The coverage refusal came after the seed."""
    from conftest import write

    body = (para(run("a "), ins("b"))
            + para('<w:r><w:rPr><w:b/><w:rPrChange w:id="5" '
                   f'{_STAMP}><w:rPr/></w:rPrChange></w:rPr>'
                   "<w:t>bold now</w:t></w:r>"))
    path = write(tmp_path / "working.docx", make_parts(body))
    seeded = []

    with pytest.raises(AnchorError, match="no block can name"):
        tracked.annotate_in_place(path, [([0], "why")], author="A",
                                  seed=lambda *_a: seeded.append(1))

    assert seeded == []


# 9 -------------------------------------------------------- smaller


def test_the_AUTHOR_s_own_comment_on_a_change_is_not_a_RERUN():
    """Case 9. The author's name alone was the test, and an author
    annotating their own file had typed queries under it."""
    body = para('<w:commentRangeStart w:id="1"/>', ins("added"),
                '<w:commentRangeEnd w:id="1"/>')
    mine = comment(1, "my own query").replace('w:author="Tester"',
                                              'w:author="A"')
    parts = make_parts(body, comment_items=(mine,))

    assert C.annotate_blocks(parts, [([0], "why")], author="A",
                             initials="A")


def test_an_author_named_with_an_ENTITY_is_still_its_author():
    body = para(run("a "), ins("b"))
    parts = make_parts(body, comment_items=(comment(1, "seed", OURS),))
    C.annotate_blocks(parts, [([0], "why")], author="O'Brien", initials="O")
    xml = _com(parts).replace("O&apos;Brien", "O&#39;Brien")
    parts["word/comments.xml"] = xml.encode()

    with pytest.raises(AnchorError, match="annotated before"):
        C.annotate_blocks(parts, [([0], "why")], author="O'Brien",
                          initials="O")


def test_a_block_with_NO_reason_is_refused():
    parts = make_parts(para(run("a "), ins("b")),
                       comment_items=(comment(1, "seed", OURS),))

    with pytest.raises(AnchorError, match="gives no reason"):
        C.annotate_blocks(parts, [([0], "  ")], author="A", initials="A")


def test_a_text_box_only_build_says_WHY_Word_seeded_nothing():
    box = ("<w:r><w:drawing><w:txbxContent>" + para(run("x "), ins("y"))
           + "</w:txbxContent></w:drawing></w:r>")
    parts = make_parts(para(box))

    with pytest.raises(ScaffoldMissing, match="text box"):
        tracked._comment_pass(parts, always("R1"), generic=None,
                              tables="coalesce", author="A", inputs=(),
                              report=tracked.BuildReport(),
                              say=lambda _line: None)


def test_a_SINGLE_quoted_attribute_is_credited_once():
    element = ("<w:comment w:id='1' w:author='Word User' w:initials='W' "
               "w:date='2026-01-01T00:00:00Z'><w:p/></w:comment>")
    credit = C.Credit("A", "A", "2026-10-24T00:00:00Z")

    head = C._stamp(element, credit).split(">")[0]

    assert head.count("w:author=") == 1 and 'w:author="A"' in head


def test_has_scaffold_on_a_NEGATIVE_id_answers_a_bool():
    parts = make_parts(para(run("x")), comment_items=(
        comment(1, "seed").replace('w:id="1"', 'w:id="-1"'),))

    assert C.has_scaffold(parts) is True


def test_a_LOCALIZED_reference_style_is_the_one_used():
    """Case 9. `CommentReference` was hard-coded; Russian Word's id for
    the same style is `af`."""
    styles = ('<w:styles xmlns:w="http://schemas.openxmlformats.org/'
              'wordprocessingml/2006/main"><w:style w:type="character" '
              'w:styleId="af"><w:name w:val="annotation reference"/>'
              "</w:style></w:styles>")
    parts = make_parts(para(run("a "), ins("b")),
                       comment_items=(comment(1, "seed", OURS),),
                       extra={"word/styles.xml": styles})

    C.annotate(parts, always("R1"))

    assert '<w:rStyle w:val="af"/></w:rPr><w:commentReference' in _doc(parts)
    assert "CommentReference" not in _doc(parts)


def test_the_template_s_OLD_paragraph_style_is_not_copied():
    """Case 9. A `pPrChange` snapshot's style was read as the live one."""
    template = ('<w:comment w:id="1" w:author="W" w:initials="W" '
                'w:date="2026-01-01T00:00:00Z"><w:p w14:paraId="AAAA0001">'
                '<w:pPr><w:pPrChange w:id="3" w:author="W" w:date="2026-01-'
                '01T00:00:00Z"><w:pPr><w:pStyle w:val="OldStyle"/></w:pPr>'
                "</w:pPrChange></w:pPr>" + run("seed") + "</w:p></w:comment>")

    assert "OldStyle" not in C._plain(template)


def test_a_restamped_Word_comment_s_DATEUTC_moves_with_it():
    """Case 9. `w:date` was restamped and `dateUtc` left as it was."""
    parts = make_parts(para(run("x")), comment_items=(comment(1, "math"),))
    credit = C.Credit("A", "A", "2026-10-24T12:00:00Z")

    assert tracked._credit_new(parts, (), credit) == 1

    utc = C._utc_of("2026-10-24T12:00:00Z")      # its UTC, on this machine
    assert f'w16cex:dateUtc="{utc}"' in parts[
        "word/commentsExtensible.xml"].decode()


def test_w_date_is_LOCAL_time_as_Word_writes_it_and_dateUtc_is_UTC():
    """Split out of case 9 and measured (2026-10-24): every Word-made
    comment in the papers reads `w:date` five hours ahead of its
    `dateUtc` on this UTC+5 machine — local time labelled Z. docxkit
    wrote true UTC, so its balloons showed five hours early."""
    from datetime import datetime

    parts = make_parts(para(run("a "), ins("b")),
                       comment_items=(comment(1, "seed", OURS),))
    (cid,) = C.annotate_blocks(parts, [([0], "why")], author="A",
                               initials="A")

    head = re.search(rf'<w:comment w:id="{cid}"[^>]*>', _com(parts))
    assert head is not None
    when = re.search(r'w:date="([^"]+)"', head.group(0))
    utc = re.findall(r'w16cex:dateUtc="([^"]+)"',
                     parts["word/commentsExtensible.xml"].decode())
    assert when is not None and utc
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    shift = (datetime.strptime(when.group(1), fmt)
             - datetime.strptime(utc[-1], fmt))
    offset = datetime.now().astimezone().utcoffset()
    assert offset is not None
    assert abs((shift - offset).total_seconds()) < 120


def test_an_EMPTY_style_does_not_swallow_the_next_one_in_the_graft():
    """Latent shape 5 (review of 2026-10-24): a self-closing `w:style`
    opened a match that ran to the next style's close, so the graft
    appended that style under the empty one's id as well."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    have = {"word/styles.xml": f"<w:styles {ns}></w:styles>".encode()}
    seeded = {"word/styles.xml": (
        f'<w:styles {ns}><w:style w:type="paragraph" w:styleId="Empty"/>'
        '<w:style w:type="paragraph" w:styleId="CommentText">'
        '<w:name w:val="annotation text"/></w:style></w:styles>').encode()}

    added = tracked._graft_styles(have, seeded)

    assert added == ["CommentText"]
    assert have["word/styles.xml"].decode().count("CommentText") == 1


def test_EMPTY_and_NONE_answers_in_one_table_are_one_balloon():
    """Case 9. '' and None coalesced as different texts."""
    cells = "".join(f"<w:tc>{para(ins(f'c{i}', rid=80 + i))}</w:tc>"
                    for i in range(4))
    parts = make_parts(f"<w:tbl><w:tr>{cells}</w:tr></w:tbl>",
                       comment_items=(comment(1, "seed", OURS),))
    answers = iter(["", None, "", None])

    added, unclassified = C.annotate(parts, lambda _ctx: next(answers))

    assert (added, unclassified) == (1, 1)
