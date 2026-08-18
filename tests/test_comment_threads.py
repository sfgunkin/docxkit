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


def comment(cid: int, text: str, para_id: str, author: str = "Referee"
            ) -> str:
    return (f'<w:comment w:id="{cid}" w:author="{author}" '
            f'w:initials="R" w:date="2026-07-30T0{cid}:00:00Z">'
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
