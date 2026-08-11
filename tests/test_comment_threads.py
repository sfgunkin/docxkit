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
