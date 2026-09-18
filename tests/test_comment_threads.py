"""Comment threads: replies, done flags, anchors, and resolving.

The chain under test is the one removal already walks: comment id in
comments.xml, done/reply flags in commentsExtended keyed by the LAST
body paragraph's paraId, anchor range in document.xml.
"""
from __future__ import annotations

import pytest
from conftest import NS, para, run

from docxkit.comments import set_done, threads
from docxkit.errors import PackageError


def comment(cid: int, text: str, para_id: str, author: str = "Referee",
            date: str | None = None) -> str:
    stamp = date or f"2026-07-30T0{cid}:00:00Z"
    return (f'<w:comment w:id="{cid}" w:author="{author}" '
            f'w:initials="R" w:date="{stamp}">'
            f'<w:p w14:paraId="{para_id}"><w:r><w:t>{text}</w:t></w:r>'
            f"</w:p></w:comment>")


def ext(para_id: str, *, done: int = 0, parent: str | None = None) -> str:
    par = f' w15:paraIdParent="{parent}"' if parent else ""
    return f'<w15:commentEx w15:paraId="{para_id}"{par} w15:done="{done}"/>'


def anchored(cid: int, *runs_: str) -> str:
    return (f'<w:commentRangeStart w:id="{cid}"/>' + "".join(runs_)
            + f'<w:commentRangeEnd w:id="{cid}"/>'
            f'<w:r><w:commentReference w:id="{cid}"/></w:r>')


def make_parts() -> dict[str, bytes]:
    # comment 2 anchors EARLIER in the document than comment 1, and
    # comment 3 is a reply to comment 1; comment 2 is already resolved
    body = (para(run("Alpha "), anchored(2, run("first anchored bit")))
            + para(run("Beta "), anchored(1, run("second anchored bit"))))
    doc = f"<w:document {NS}><w:body>{body}</w:body></w:document>"
    return {
        "word/document.xml": doc.encode("utf-8"),
        "word/comments.xml": (
            f"<w:comments {NS}>"
            + comment(1, "Please clarify.", "AAAA0001")
            + comment(2, "Fixed typo?", "AAAA0002")
            + comment(3, "Done in r2.", "AAAA0003", author="Author")
            + "</w:comments>").encode("utf-8"),
        "word/commentsExtended.xml": (
            f"<w15:commentsEx {NS}>"
            + ext("AAAA0001")
            + ext("AAAA0002", done=1)
            + ext("AAAA0003", parent="AAAA0001")
            + "</w15:commentsEx>").encode("utf-8"),
    }


def test_threads_group_replies_under_their_root():
    found = threads(make_parts())
    assert [t.comment.cid for t in found] == ["2", "1"]   # document order
    root = found[1]
    assert [r.cid for r in root.replies] == ["3"]
    assert root.replies[0].author == "Author"


def test_done_is_the_roots_flag():
    by_cid = {t.comment.cid: t for t in threads(make_parts())}
    assert by_cid["2"].done
    assert not by_cid["1"].done


def test_an_anchor_closed_WITH_A_SPACE_still_gives_the_anchor_and_order():
    """The range was found as the exact strings `<w:commentRangeStart
    w:id="2"/>` and its end; closed ` />` by another producer, comment 2
    read back with no anchor text and sorted LAST, past the comment
    whose anchor follows it."""
    parts = make_parts()
    doc = parts["word/document.xml"].decode("utf-8")
    for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
        doc = doc.replace(f'<w:{tag} w:id="2"/>', f'<w:{tag} w:id="2" />')
    assert doc.count(" />") == 3
    parts["word/document.xml"] = doc.encode("utf-8")

    found = threads(parts)

    assert [t.comment.cid for t in found] == ["2", "1"]
    assert found[0].comment.anchor == "first anchored bit"


def test_an_EMPTY_comment_is_a_thread_and_the_next_keeps_its_own_flag():
    """`<w:comment .../>` opens nothing. Read as an open tag it ran on to
    comment 2's close, so comment 1 carried comment 2's text, paraId and
    done flag, and the RESOLVED comment 2 was not listed at all."""
    parts = make_parts()
    com = parts["word/comments.xml"].decode("utf-8")
    full = comment(1, "Please clarify.", "AAAA0001")
    assert full in com
    parts["word/comments.xml"] = com.replace(
        full, '<w:comment w:id="1" w:author="Referee" w:initials="R" '
              'w:date="2026-07-30T01:00:00Z"/>').encode("utf-8")

    by_cid = {t.comment.cid: t.comment for t in threads(parts)}

    assert (by_cid["1"].text, by_cid["1"].done) == ("", False)
    assert (by_cid["2"].text, by_cid["2"].done) == ("Fixed typo?", True)


def test_anchor_text_is_the_ranged_visible_text():
    by_cid = {t.comment.cid: t for t in threads(make_parts())}
    assert by_cid["2"].comment.anchor == "first anchored bit"
    assert by_cid["1"].comment.anchor == "second anchored bit"


def test_a_point_comment_reads_back_with_an_empty_anchor():
    parts = make_parts()
    doc = parts["word/document.xml"].decode("utf-8")
    doc = doc.replace('<w:commentRangeStart w:id="2"/>', "")
    doc = doc.replace('<w:commentRangeEnd w:id="2"/>', "")
    parts["word/document.xml"] = doc.encode("utf-8")
    by_cid = {t.comment.cid: t for t in threads(parts)}
    assert by_cid["2"].comment.anchor == ""


def test_set_done_flips_the_flag_word_reads():
    parts = make_parts()
    assert set_done(parts, ["1"]) == 1
    by_cid = {t.comment.cid: t for t in threads(parts)}
    assert by_cid["1"].done
    # and back
    assert set_done(parts, ["1"], done=False) == 1
    assert not {t.comment.cid: t for t in threads(parts)}["1"].done


def test_set_done_without_the_extended_part_refuses():
    parts = make_parts()
    del parts["word/commentsExtended.xml"]
    with pytest.raises(PackageError, match="commentsExtended"):
        set_done(parts, ["1"])


def test_no_comments_means_no_threads():
    assert threads({"word/document.xml": b"<w:document/>"}) == []


def test_a_comment_with_no_extended_entry_is_not_done():
    """`flags.get(para_id, (False, None))` — the default. As `(True,
    None)` every comment Word has not flagged reads as resolved, which
    is the wrong way for a work list to be wrong: `docxkit tasks
    --check` would pass a round with everything still open."""
    parts = make_parts()
    ext_part = parts["word/commentsExtended.xml"].decode("utf-8")
    parts["word/commentsExtended.xml"] = ext_part.replace(
        ext("AAAA0001"), "").encode("utf-8")
    found = {t.comment.cid: t.comment.done for t in threads(parts)}
    assert found["1"] is False, "an unflagged comment reads as resolved"
    assert found["2"] is True, "the flagged one must still read as done"


# --- the second comments round, from the complete run of 2026-08-18 -----
#
# 24.2 % over a full 460-sample (the first run stopped at 178), and the
# two largest clusters were the two rewrites: 13 on the element
# `set_done` builds when there is no flag to change, and 20 on the walk
# that drops a reference run.


def test_set_done_ADDS_the_flag_to_an_element_that_carries_none():
    """Word writes `w15:commentEx` both ways, and only one of them was
    tested. This branch rebuilds the element by hand —
    `el[:-2] + ' w15:done="1"/>'` — so an off-by-one in the slice leaves
    `.../ w15:done="1"/>` or eats the closing quote, and the part stops
    parsing. `threads` then reports no done flags at all, which reads
    exactly like a round nobody has resolved."""
    from lxml import etree
    parts = make_parts()
    bare = (f"<w15:commentsEx {NS}>"
            '<w15:commentEx w15:paraId="AAAA0001"/>'
            '<w15:commentEx w15:paraId="AAAA0002" w15:done="0"/>'
            "</w15:commentsEx>")
    parts["word/commentsExtended.xml"] = bare.encode("utf-8")

    assert set_done(parts, ["1"]) == 1

    out = parts["word/commentsExtended.xml"].decode("utf-8")
    assert '<w15:commentEx w15:paraId="AAAA0001" w15:done="1"/>' in out
    assert '<w15:commentEx w15:paraId="AAAA0002" w15:done="0"/>' in out
    etree.fromstring(out.encode("utf-8"))
    assert {t.comment.cid: t.done for t in threads(parts)}["1"]


def _ext_part(*elements: str) -> bytes:
    return (f"<w15:commentsEx {NS}>" + "".join(elements)
            + "</w15:commentsEx>").encode("utf-8")


@pytest.mark.parametrize("spelling,resolved", [
    ("1", True), ("true", True), ("on", True),
    ("0", False), ("false", False), ("off", False)])
def test_EVERY_ST_OnOff_spelling_of_the_done_flag_is_read(spelling, resolved):
    """ST_OnOff has three spellings a side, and the reader holds three of
    them in a set — a set no mutant can reach, so `on` sat in it untested
    while `1` and `true` had a fixture each. A thread another producer
    resolved with `on` reads as OPEN: a settled query back on the work
    list, and `tasks --check` failing a round that is finished.

    Written out rather than parametrised over the set itself, which would
    lose its case with the member it is meant to hold."""
    parts = make_parts()
    parts["word/commentsExtended.xml"] = _ext_part(
        f'<w15:commentEx w15:paraId="AAAA0001" w15:done="{spelling}"/>')

    done = {t.comment.cid: t.done for t in threads(parts)}

    assert done["1"] is resolved


def test_a_done_flag_spelled_TRUE_is_read_as_done():
    """`w15:done` is ST_OnOff. Word writes 1 and 0; the schema also
    allows true/false and on/off, and a comment another producer
    resolved was read as OPEN — which puts a settled query back on the
    work list and fails `tasks --check` on a round that is finished."""
    parts = make_parts()
    parts["word/commentsExtended.xml"] = _ext_part(
        '<w15:commentEx w15:paraId="AAAA0001" w15:done="true"/>',
        '<w15:commentEx w15:paraId="AAAA0002" w15:done="false"/>')

    done = {t.comment.cid: t.done for t in threads(parts)}

    assert done["1"] is True
    assert done["2"] is False


def test_set_done_REPLACES_a_flag_spelled_the_other_way():
    """The worse half: the writer used the same narrow pattern, so it
    could not SEE a flag spelled `true` and added a second `w15:done`
    beside it. The part then stops parsing — "Attribute w15:done
    redefined" — and Word calls the document unreadable."""
    from lxml import etree
    parts = make_parts()
    parts["word/commentsExtended.xml"] = _ext_part(
        '<w15:commentEx w15:paraId="AAAA0001" w15:done="true"/>')

    assert set_done(parts, ["1"], done=False) == 1

    out = parts["word/commentsExtended.xml"].decode("utf-8")
    assert out.count("w15:done=") == 1
    assert 'w15:done="0"' in out
    etree.fromstring(out.encode("utf-8"))


def test_a_commentEx_with_NO_paraId_does_not_stop_the_scan():
    """`continue`, not `break`: an entry with nothing to key on is
    skipped, and the flags after it are still read. Under `break` every
    comment below it reads as open."""
    parts = make_parts()
    parts["word/commentsExtended.xml"] = _ext_part(
        '<w15:commentEx w15:done="1"/>',            # no paraId at all
        '<w15:commentEx w15:paraId="AAAA0001" w15:done="1"/>')

    assert {t.comment.cid: t.done for t in threads(parts)}["1"]


def test_set_done_counts_what_it_CHANGED_not_what_it_matched():
    """The number is printed back to the author as how many comments
    were resolved. Counting matches instead of moves made a re-run on a
    finished round report the whole round as freshly resolved — and a
    resolve pass IS re-run, because it is how a paper checks the job is
    done."""
    parts = make_parts()
    parts["word/commentsExtended.xml"] = _ext_part(
        '<w15:commentEx w15:paraId="AAAA0001" w15:done="1"/>',
        '<w15:commentEx w15:paraId="AAAA0002" w15:done="0"/>')

    assert set_done(parts, ["1"]) == 0, "already resolved"
    assert set_done(parts, ["2"]) == 1
    assert set_done(parts, ["1", "2"]) == 0, "both resolved now"


def test_TWO_replies_come_back_in_reply_order():
    """`key=(c.date, int(c.cid))`: two replies posted in the same minute
    is the ordinary case in a review round — Word stamps to the minute —
    and the id is what breaks the tie, in the order they were written.
    A thread read out of order reads as an author answering a question
    nobody asked yet."""
    parts = make_parts()
    parts["word/comments.xml"] = (
        f"<w:comments {NS}>"
        + comment(1, "Please clarify.", "AAAA0001")
        + comment(2, "Fixed typo?", "AAAA0002")
        # the SAME minute on both, which is what Word stamps when an
        # author answers two questions in one pass — the id is then the
        # only thing that orders them
        # …and DEFINED in the other order, because the order of the
        # part is Word's business and not the thread's
        + comment(4, "Second reply.", "AAAA0004", author="Author",
                  date="2026-07-30T09:00:00Z")
        + comment(3, "First reply.", "AAAA0003", author="Author",
                  date="2026-07-30T09:00:00Z")
        + "</w:comments>").encode("utf-8")
    parts["word/commentsExtended.xml"] = (
        f"<w15:commentsEx {NS}>"
        + ext("AAAA0001") + ext("AAAA0002", done=1)
        + ext("AAAA0003", parent="AAAA0001")
        + ext("AAAA0004", parent="AAAA0001")
        + "</w15:commentsEx>").encode("utf-8")

    by_cid = {t.comment.cid: t for t in threads(parts)}

    assert [r.cid for r in by_cid["1"].replies] == ["3", "4"]
    assert [r.text for r in by_cid["1"].replies] == ["First reply.",
                                                     "Second reply."]


def test_an_anchor_whose_RANGE_never_closes_reads_as_empty():
    """`close != -1`. A `commentRangeStart` with no end is what a
    half-deleted comment leaves, and `str.find` answers -1 for it. Under
    `>= -1` the slice runs from the anchor to -1 — the whole rest of the
    document, minus its last character — and the checklist prints the
    paper from that comment down as the words it marks."""
    parts = make_parts()
    doc = parts["word/document.xml"].decode("utf-8")
    parts["word/document.xml"] = doc.replace(
        '<w:commentRangeEnd w:id="1"/>', "", 1).encode("utf-8")

    by_cid = {t.comment.cid: t for t in threads(parts)}

    assert by_cid["1"].comment.anchor == ""

def test_a_comment_with_only_a_REFERENCE_sorts_where_it_sits():
    """`position[cid] = ref.start()`. Threads come back in document
    order, which is the order a person works through them, and a
    comment whose RANGE Word dropped — an author editing across it does
    that — still has its reference mark to say where it is.

    Fall back to the end of the document for those and they all pile up
    after everything else: the checklist reads in an order the document
    does not have, and the first thing a reader meets is the comment
    furthest from where they are."""
    body = (para(run("early "),
                 '<w:r><w:commentReference w:id="1"/></w:r>')
            + para(run("later "), '<w:commentRangeStart w:id="2"/>',
                   run("the queried sentence"),
                   '<w:commentRangeEnd w:id="2"/>',
                   '<w:r><w:commentReference w:id="2"/></w:r>'))
    parts = {
        "word/document.xml":
            f"<w:document {NS}><w:body>{body}</w:body></w:document>"
            .encode(),
        "word/comments.xml": (
            f"<w:comments {NS}>"
            + comment(1, "the one whose range is gone", "AAAA0001")
            + comment(2, "the one that still has it", "AAAA0002")
            + "</w:comments>").encode("utf-8"),
        "word/commentsExtended.xml": (
            f"<w15:commentsEx {NS}>" + ext("AAAA0001") + ext("AAAA0002")
            + "</w15:commentsEx>").encode("utf-8"),
    }

    got = [t.comment.cid for t in threads(parts)]

    assert got == ["1", "2"], got


def test_set_done_with_NO_ids_reports_nothing_changed():
    """The count is what a caller prints. An empty selection changes
    nothing, and a 1 there is a report of work that did not happen —
    the same shape as `reclassify`'s early return."""
    parts = make_parts()

    assert set_done(parts, []) == 0
    assert set_done(parts, [], done=False) == 0

    from docxkit.comments import remove
    assert remove(parts, []) == 0, "the same early return, next door"


def test_a_reply_is_matched_to_its_root_by_VALUE_not_identity():
    """Every fixture here numbers its comments 1, 2, 3 — and CPython
    interns one-character strings, so `parent_cid is root.cid` passes on
    all of them and fails on the eleventh comment in a real manuscript.
    A referee round routinely has thirty.
    """
    body = para(run("Alpha "), anchored(11, run("an anchored bit")))
    doc = f"<w:document {NS}><w:body>{body}</w:body></w:document>"
    parts = {
        "word/document.xml": doc.encode("utf-8"),
        "word/comments.xml": (
            f"<w:comments {NS}>"
            + comment(11, "Please clarify.", "AAAA0011")
            + comment(12, "Done in r2.", "AAAA0012", author="Author")
            + "</w:comments>").encode("utf-8"),
        "word/commentsExtended.xml": (
            f"<w15:commentsEx {NS}>"
            + ext("AAAA0011")
            + ext("AAAA0012", parent="AAAA0011")
            + "</w15:commentsEx>").encode("utf-8"),
    }

    found = threads(parts)

    assert [t.comment.cid for t in found] == ["11"]
    assert [r.cid for r in found[0].replies] == ["12"]


# `threads`' `c.parent_cid == root.cid` is EQUIVALENT under `is` and
# left alive — and NOT because one-character cids are interned, which
# was the first guess and would have made it a fixture artefact. Both
# sides come from `by_para`, one dict, so a reply's `parent_cid` IS the
# object its root carries as `cid`. The test above stands anyway: no
# fixture here had a two-digit comment id, and a referee round has
# thirty.
