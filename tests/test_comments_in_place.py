"""Commenting a PENDING proposal in the author's own file.

HPPA_Index, 2026-10-10: the author, mid-adjudication, asked for a
comment on every change saying why. The paper did it with a script
over this module's private functions, and met the trap this is built
around: Word's save of the seeded COPY dropped six parts (docProps
core, app and custom, and the customXml store) while its text,
revisions and counts were all perfect. So the package written is the
author's, and only the comment machinery comes from Word's copy.

The fake seed below behaves like Word's: it adds the comment parts and
their styles, and loses `docProps/custom.xml` and the data store.
"""
from __future__ import annotations

import re

import pytest
from conftest import comment, make_parts, para, run, write

from docxkit import comments as C
from docxkit import package, revisions, tracked
from docxkit.errors import (
    AnchorError,
    DocumentLocked,
    PackageError,
    ScaffoldMissing,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PKG = "http://schemas.openxmlformats.org/package/2006"
REL = ("http://schemas.openxmlformats.org/officeDocument/2006/"
       "relationships")
_STAMP = 'w:author="Revision" w:date="2026-10-10T00:00:00Z"'

CUSTOM = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          b'<Properties xmlns="http://schemas.openxmlformats.org/'
          b'officeDocument/2006/custom-properties"><property '
          b'name="Paper">HPPA</property></Properties>')
STORE = b'<b:Sources xmlns:b="urn:bib">one source</b:Sources>'
AUTHOR = "Michael Lokshin"


def _styles(*ids: str) -> str:
    body = "".join(f'<w:style w:type="paragraph" w:styleId="{i}">'
                   f'<w:name w:val="{i}"/></w:style>' for i in ids)
    return f'<w:styles xmlns:w="{W_NS}">{body}</w:styles>'


def _proposal(n: int, *, with_comment: str | None = None,
              ) -> dict[str, bytes]:
    """`n` revision spans, alternating insertions and deletions, in a
    package that carries custom properties and a customXml data store."""
    body = "".join(
        para(run(f"Kept {i}. "),
             f'<w:ins w:id="{10 + i}" {_STAMP}>{run(f"added {i}")}</w:ins>'
             if i % 2 == 0 else
             f'<w:del w:id="{10 + i}" {_STAMP}><w:r><w:delText>cut {i}'
             f"</w:delText></w:r></w:del>")
        for i in range(n))
    parts = make_parts(
        body, comment_items=((comment(1, with_comment),)
                             if with_comment else ()),
        extra={"word/styles.xml": _styles("Normal"),
               "word/_rels/document.xml.rels": (
                   f'<Relationships xmlns="{PKG}/relationships">'
                   f'<Relationship Id="rId1" Type="{REL}/styles" '
                   f'Target="styles.xml"/></Relationships>'),
               "_rels/.rels": (
                   f'<Relationships xmlns="{PKG}/relationships">'
                   f'<Relationship Id="rId1" Type="{REL}/officeDocument" '
                   f'Target="word/document.xml"/><Relationship Id="rId2" '
                   f'Type="{REL}/custom-properties" '
                   f'Target="docProps/custom.xml"/></Relationships>')})
    parts["docProps/custom.xml"] = CUSTOM
    parts["customXml/item1.xml"] = STORE
    parts["[Content_Types].xml"] = (
        f'<Types xmlns="{PKG}/content-types">'
        '<Override PartName="/word/document.xml" ContentType="doc"/>'
        '<Override PartName="/docProps/custom.xml" ContentType="custom"/>'
        "</Types>").encode()
    return parts


_SEED_PARTS = ("word/comments.xml", "word/commentsExtended.xml",
               "word/commentsIds.xml", "word/commentsExtensible.xml")


def _word_like_seed(calls: list[int]):
    """What Word's seed-and-save does: one comment and its machinery
    added, the custom properties and the data store LOST."""
    def seed(src, dst):
        calls.append(1)
        parts = package.read_parts(src)
        seeded = make_parts("", comment_items=(comment(0, "seed"),))
        for name in _SEED_PARTS:
            parts[name] = seeded[name]
        parts["word/styles.xml"] = _styles(
            "Normal", "CommentText", "CommentReference").encode()
        types = parts["[Content_Types].xml"].decode().replace(
            "</Types>", "".join(
                f'<Override PartName="/{n}" ContentType="c"/>'
                for n in _SEED_PARTS) + "</Types>")
        parts["[Content_Types].xml"] = types.encode()
        rels = parts["word/_rels/document.xml.rels"].decode().replace(
            "</Relationships>", "".join(
                f'<Relationship Id="rId{9 + i}" Type="{REL}/comments" '
                f'Target="{n.removeprefix("word/")}"/>'
                for i, n in enumerate(_SEED_PARTS)) + "</Relationships>")
        parts["word/_rels/document.xml.rels"] = rels.encode()
        del parts["docProps/custom.xml"]
        del parts["customXml/item1.xml"]
        write(dst, parts)
    return seed


def _without_anchors(doc: str) -> str:
    doc = re.sub(r'<w:commentRange(?:Start|End) w:id="\d+"/>', "", doc)
    return re.sub(r'<w:r><w:rPr><w:rStyle w:val="CommentReference"/>'
                  r'</w:rPr><w:commentReference w:id="\d+"/></w:r>', "", doc)


def _blocks(n: int) -> list[tuple[list[int], str]]:
    """Span 0 alone, then pairs: the shape of grouped Compare fragments."""
    out = [([0], "why the first change")]
    out += [(list(range(i, min(i + 2, n))), f"why changes {i}+")
            for i in range(1, n, 2)]
    return out


@pytest.mark.parametrize("n", [3, 5, 7])
def test_a_proposal_is_commented_IN_PLACE_one_balloon_per_block(tmp_path,
                                                                n):
    path = write(tmp_path / "working.docx", _proposal(n))
    before = package.read_parts(path)
    calls: list[int] = []

    added = tracked.annotate_in_place(path, _blocks(n), author=AUTHOR,
                                      seed=_word_like_seed(calls))

    after = package.read_parts(path)
    assert calls == [1], "seeded once, because there was no scaffold"
    assert added == len(_blocks(n))
    # by id: `_write` appends back to front, as `annotate` always has
    assert [text for _id, _who, text in sorted(
        C.read_all(after), key=lambda c: int(c[0]))] == [
        text for _idx, text in _blocks(n)]
    # the author's package, not Word's copy
    assert after["docProps/custom.xml"] == CUSTOM
    assert after["customXml/item1.xml"] == STORE
    assert _without_anchors(after["word/document.xml"].decode()) == \
        before["word/document.xml"].decode()
    doc = after["word/document.xml"].decode()
    for view in (revisions.accept, revisions.reject):
        assert revisions.text(view(doc)) == revisions.text(
            view(before["word/document.xml"].decode()))


def test_Word_is_handed_a_COPY_never_the_author_s_file(tmp_path):
    """Review 2026-10-24 (unpinned): a mutant that seeded `path` itself
    survived every test here. Word's save of what it is handed is the
    one that drops parts, so it must never be the author's file."""
    from pathlib import Path

    path = Path(write(tmp_path / "working.docx", _proposal(3)))
    before, handed = path.read_bytes(), []
    real = _word_like_seed([])

    def seed(src, dst):
        handed.append(src)
        real(src, dst)

    tracked.annotate_in_place(path, _blocks(3), author=AUTHOR, seed=seed)

    (src,) = handed
    assert Path(src).resolve() != path.resolve()
    assert Path(src).parent.resolve() != path.parent.resolve()
    assert path.read_bytes() != before          # written, from OUR parts


def test_the_SEED_comment_becomes_the_first_balloon_not_an_orphan(tmp_path):
    """Its anchor was in Word's copy, which is thrown away. Left as it
    was, it is a comment in comments.xml that nothing in the text holds."""
    path = write(tmp_path / "working.docx", _proposal(5))

    tracked.annotate_in_place(path, _blocks(5), author=AUTHOR,
                              seed=_word_like_seed([]))

    parts = package.read_parts(path)
    defined = re.findall(r'<w:comment [^>]*w:id="(\d+)"',
                         parts["word/comments.xml"].decode())
    anchored = re.findall(r'<w:commentReference w:id="(\d+)"/>',
                          parts["word/document.xml"].decode())
    assert sorted(defined) == sorted(anchored)
    assert len(defined) == 3


def test_every_new_comment_is_credited_to_the_AUTHOR_and_no_other(tmp_path):
    """A package that already has comments needs no seed, and the comment
    cloned is a referee's; the new ones must not be filed under them."""
    path = write(tmp_path / "working.docx",
                 _proposal(3, with_comment="A referee's point."))

    def no_seed(src, dst):
        raise AssertionError("a package with a scaffold needs no Word")

    tracked.annotate_in_place(path, _blocks(3), author=AUTHOR, seed=no_seed)

    com = package.read_parts(path)["word/comments.xml"].decode()
    authors = re.findall(r'<w:comment [^>]*w:id="(\d+)"[^>]*w:author="'
                         r'([^"]*)"', com)
    assert sorted(authors) == [("1", "Tester"), ("2", AUTHOR),
                               ("3", AUTHOR)]


@pytest.mark.parametrize("blocks, why", [
    ([([0], "a"), ([1], "b")], "span(s) in no block"),
    ([([0, 1], "a"), ([1, 2], "b")], "span 1 is in blocks 0 and 1"),
    ([([0, 1, 2], "a"), ([], "b")], "names no span"),
    ([([0, 1, 2, 3], "a")], "names span 3"),
])
def test_blocks_that_do_not_cover_each_span_ONCE_write_nothing(
        tmp_path, blocks, why):
    path = write(tmp_path / "working.docx", _proposal(3))
    was = (tmp_path / "working.docx").read_bytes()

    with pytest.raises(AnchorError, match=re.escape(why)):
        tracked.annotate_in_place(path, blocks, author=AUTHOR,
                                  seed=_word_like_seed([]))

    assert (tmp_path / "working.docx").read_bytes() == was


def test_a_change_beyond_the_anchors_is_REFUSED_and_nothing_written(
        tmp_path, monkeypatch):
    """The guard, asked directly: a write step that also touched a run's
    text is caught before the author's file is replaced."""
    path = write(tmp_path / "working.docx", _proposal(3))
    was = (tmp_path / "working.docx").read_bytes()
    real = C._write

    def leaky(parts, doc, decided, scaffold, **kw):
        return real(parts, doc.replace("Kept 1. ", "Kept one. "), decided,
                    scaffold, **kw)

    monkeypatch.setattr(C, "_write", leaky)

    with pytest.raises(PackageError, match=r"document\.xml"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))

    assert (tmp_path / "working.docx").read_bytes() == was


def test_a_PART_the_seed_rewrote_is_refused(tmp_path, monkeypatch):
    """Only the comment machinery may come from Word's copy. A seed that
    also rewrote the package rels — what a Word save does — must not
    reach the author's file."""
    from docxkit.hygiene import restore_parts

    path = write(tmp_path / "working.docx", _proposal(3))

    def greedy(parts, source, prefixes):
        parts["_rels/.rels"] = source["_rels/.rels"].replace(
            b"custom.xml", b"other.xml")
        return restore_parts(parts, source, prefixes=prefixes)

    monkeypatch.setattr("docxkit.hygiene.restore_parts", greedy)

    with pytest.raises(PackageError, match=r"_rels/\.rels"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))


@pytest.mark.parametrize("change, why", [
    (lambda parts: parts.pop("customXml/item1.xml"), "dropped customXml"),
    (lambda parts: parts.__setitem__("word/extra.xml", b"<x/>"),
     r"added \['word/extra.xml'\]"),
])
def test_a_part_DROPPED_or_ADDED_beside_the_graft_is_refused(
        tmp_path, monkeypatch, change, why):
    """The other two ways a package changes, besides a rewritten part."""
    from docxkit.hygiene import restore_parts

    path = write(tmp_path / "working.docx", _proposal(3))
    was = (tmp_path / "working.docx").read_bytes()

    def also(parts, source, prefixes):
        change(parts)
        return restore_parts(parts, source, prefixes=prefixes)

    monkeypatch.setattr("docxkit.hygiene.restore_parts", also)

    with pytest.raises(PackageError, match=why):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))

    assert (tmp_path / "working.docx").read_bytes() == was


def test_a_seed_that_made_TWO_comments_is_refused(tmp_path):
    """The seed is reused as the first balloon, so it has to be the ONE
    comment the copy was given; anything else is a copy that is not
    what this asked Word for."""
    path = write(tmp_path / "working.docx", _proposal(3))

    def twice(src, dst):
        parts = package.read_parts(src)
        seeded = make_parts("", comment_items=(comment(0, "seed"),
                                               comment(1, "again")))
        parts["word/comments.xml"] = seeded["word/comments.xml"]
        write(dst, parts)

    with pytest.raises(ScaffoldMissing, match="carries 2 comments"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=twice)


def test_a_package_with_NO_styles_part_still_takes_the_comments(tmp_path):
    """Nothing to graft the comment styles into is not a reason to
    refuse; Word supplies its defaults."""
    parts = _proposal(3)
    del parts["word/styles.xml"]
    path = write(tmp_path / "working.docx", parts)

    assert tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                     seed=_word_like_seed([])) == 2


def test_a_file_open_in_WORD_is_refused(tmp_path, monkeypatch):
    path = write(tmp_path / "working.docx", _proposal(3))
    monkeypatch.setattr(tracked, "is_locked", lambda _p: True)

    with pytest.raises(DocumentLocked):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))


class _FakeDoc:
    """The two things the seed asks of a Word document."""

    def __init__(self) -> None:
        self.added: list[tuple[object, str]] = []
        self.Comments = self

    def Add(self, where, text):
        self.added.append((where, text))

    def Revisions(self, i):
        return type("R", (), {"Range": f"revision {i}"})()


def test_the_default_seed_asks_WORD_for_one_comment_on_revision_1(
        tmp_path, monkeypatch):
    """`_seed_in_word`, through a fake at the `tracked._word` seam: one
    comment on revision 1 of the COPY, read back through Flat OPC."""
    import contextlib

    doc = _FakeDoc()
    seed_parts: list[dict[str, bytes]] = []

    class _FakeWord:
        @staticmethod
        @contextlib.contextmanager
        def session(**_kw):
            yield "word"

        @staticmethod
        @contextlib.contextmanager
        def open_doc(_app, src, **kw):
            assert kw == {"read_only": False, "local": False}
            seed_parts.append(package.read_parts(src))
            yield doc

        @staticmethod
        def extract_flat_opc(_doc, flat):
            flat.write_text("<pkg/>", encoding="utf-8")
            return flat

        @staticmethod
        def flat_opc_to_docx(_flat, dst):
            _word_like_seed([])(path, dst)
            return 1

    path = write(tmp_path / "working.docx", _proposal(3))
    monkeypatch.setattr(tracked, "_word", _FakeWord)

    assert tracked.annotate_in_place(path, _blocks(3), author=AUTHOR) == 2
    assert doc.added == [("revision 1", "seed")]
    assert seed_parts[0]["word/document.xml"] == _proposal(3)[
        "word/document.xml"], "Word was handed a copy of the file"


@pytest.mark.word
def test_WORD_seeds_the_scaffold_and_the_author_s_parts_survive(tmp_path):
    """The real seed, through Word: the route HPPA took by hand. A real
    package as the shell, as the other Word tests do, since Word refuses
    the fixture's placeholder content types; one with no comments, so
    the seed has to run."""
    import pathlib

    shell = next((p for p in pathlib.Path(r"F:\OneDrive\__Documents")
                  .glob("*.docx") if not p.name.startswith("~$")
                  and "word/comments.xml" not in package.read_parts(p)),
                 None)
    if shell is None:
        pytest.skip("no real .docx without comments to use as a shell")
    parts = package.read_parts(shell)
    parts["word/document.xml"] = _proposal(5)["word/document.xml"]
    path = write(tmp_path / "working.docx", parts)
    before = package.read_parts(path)

    added = tracked.annotate_in_place(path, _blocks(5), author=AUTHOR)

    after = package.read_parts(path)
    assert added == 3
    assert len(C.read_all(after)) == 3
    kept = [n for n in before if n.startswith(("docProps/", "customXml/"))]
    assert kept, "the shell carries the parts Word's save drops"
    assert all(after[n] == before[n] for n in kept)


# ----------------------------------------- the review of 2026-10-14 ------


def test_a_save_made_WHILE_WORD_SEEDS_is_not_overwritten(tmp_path):
    """Finding 2. The seed can run 100 s cold; an accept the author saves
    in that window used to be replaced by the bytes read before it, the
    decision surviving only in the backup."""
    path = write(tmp_path / "working.docx", _proposal(3))
    seed = _word_like_seed([])
    saved = _proposal(3)
    saved["word/document.xml"] = saved["word/document.xml"].replace(
        b"Kept 0. ", b"Kept zero. ")

    def author_saves_meanwhile(src, dst):
        seed(src, dst)
        write(path, saved)

    with pytest.raises(PackageError, match="changed on disk"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=author_saves_meanwhile)

    assert package.read_parts(path)["word/document.xml"] == \
        saved["word/document.xml"], "the author's save stands"
    assert not list(tmp_path.glob("*pre_annotate*")), "nothing was begun"


def test_a_file_OPENED_while_Word_seeds_is_refused_as_locked(tmp_path,
                                                             monkeypatch):
    path = write(tmp_path / "working.docx", _proposal(3))
    asked = iter([False, True])
    monkeypatch.setattr(tracked, "is_locked", lambda _p: next(asked))

    with pytest.raises(DocumentLocked, match="opened in Word"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))


def test_a_write_REFUSED_by_the_system_is_a_locked_file(tmp_path,
                                                        monkeypatch):
    """Not a raw PermissionError, exit 70 "a bug in docxkit"."""
    path = write(tmp_path / "working.docx", _proposal(3))

    def denied(*_a, **_kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tracked, "write_docx", denied)

    with pytest.raises(DocumentLocked, match="could not be written"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))


_MATH_SPANS = (
    para(run("Kept. "),
         '<m:oMath><m:r><m:t>a</m:t></m:r>'
         f'<w:ins w:id="40" {_STAMP}><m:r><m:t>+b</m:t></m:r></w:ins>'
         '<m:f><m:fPr><m:ctrlPr>'
         f'<w:ins w:id="41" {_STAMP}><w:rPr><w:i/></w:rPr></w:ins>'
         "</m:ctrlPr></m:fPr><m:num><m:r><m:t>1</m:t></m:r></m:num>"
         "<m:den><m:r><m:t>2</m:t></m:r></m:den></m:f></m:oMath>"),
    para('<m:oMathPara><m:oMath><m:r><m:t>c</m:t></m:r>'
         f'<w:del w:id="42" {_STAMP}><m:r><m:t>d</m:t></m:r></w:del>'
         "</m:oMath></m:oMathPara>"))


def test_a_span_INSIDE_an_equation_is_anchored_round_the_equation(
        tmp_path):
    """Finding 3. `m:r` admits no range marker and `m:ctrlPr` only
    properties: LI7's 446 spans inside equations were anchored in place
    and the maths rendered as blank boxes, unlinted."""
    from lxml import etree

    from docxkit.lint import lint_parts

    parts = _proposal(1)
    doc = parts["word/document.xml"].decode()
    parts["word/document.xml"] = doc.replace(
        "</w:body>", "".join(_MATH_SPANS) + "</w:body>").encode()
    path = write(tmp_path / "working.docx", parts)
    n = len(revisions.spans(parts["word/document.xml"].decode()))
    assert n == 4

    added = tracked.annotate_in_place(
        path, [([0], "prose"), ([1, 2], "the fraction"), ([3], "display")],
        author=AUTHOR, seed=_word_like_seed([]))

    after = package.read_parts(path)
    doc = after["word/document.xml"].decode()
    assert added == 3
    etree.fromstring(doc.encode())
    for zone in re.findall(r"<m:oMath\b.*?</m:oMath>", doc, re.DOTALL):
        assert "commentRange" not in zone and "commentReference" not in zone
    assert re.search(r'<w:commentRangeStart w:id="\d+"/><m:oMath>', doc)
    assert re.search(r'<w:commentRangeStart w:id="\d+"/><m:oMathPara>', doc)
    assert lint_parts(after) == lint_parts(parts)


def test_a_finding_LINT_did_not_see_before_is_refused(tmp_path,
                                                      monkeypatch):
    path = write(tmp_path / "working.docx", _proposal(3))
    was = (tmp_path / "working.docx").read_bytes()
    monkeypatch.setattr(
        tracked, "lint_parts",
        lambda parts: (["1 empty math object"] if any(
            b"commentReference" in b for b in parts.values()) else []))

    with pytest.raises(PackageError, match="1 empty math object"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))
    assert (tmp_path / "working.docx").read_bytes() == was


def test_running_it_AGAIN_is_refused_not_doubled(tmp_path):
    """Finding 9. A corrected table on the same proposal put the stale and
    the corrected reason side by side on every change."""
    path = write(tmp_path / "working.docx", _proposal(3))
    tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                              seed=_word_like_seed([]))
    was = (tmp_path / "working.docx").read_bytes()

    with pytest.raises(AnchorError, match="already carry a comment"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))
    assert (tmp_path / "working.docx").read_bytes() == was


def test_a_change_NO_block_can_name_is_refused_unless_partial(tmp_path):
    """Finding 10. A formatting-only paragraph and a footnote revision
    have no span; the call promised full coverage over them."""
    parts = _proposal(3)
    doc = parts["word/document.xml"].decode()
    formatted = para('<w:r><w:rPr><w:b/><w:rPrChange w:id="60" '
                     f'{_STAMP}><w:rPr/></w:rPrChange></w:rPr>'
                     "<w:t>Bold now.</w:t></w:r>")
    parts["word/document.xml"] = doc.replace(
        "</w:body>", formatted + "</w:body>").encode()
    parts["word/footnotes.xml"] = (
        f'<w:footnotes xmlns:w="{W_NS}"><w:footnote w:id="2"><w:p>'
        f'<w:ins w:id="61" {_STAMP}><w:r><w:t>new</w:t></w:r></w:ins>'
        "</w:p></w:footnote></w:footnotes>").encode()
    path = write(tmp_path / "working.docx", parts)

    with pytest.raises(AnchorError) as exc:
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed([]))
    said = str(exc.value)
    assert "1 revision(s) in word/footnotes.xml (ins)" in said, said
    assert "1 paragraph(s) or row(s)" in said and "rPrChange" in said

    assert tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                     seed=_word_like_seed([]),
                                     partial=True) == 2


def test_a_paragraph_mark_BESIDE_a_span_is_that_span_s_change(tmp_path):
    """The mark of a paragraph whose text is inserted is explained by the
    balloon on that text; refusing it would refuse every real proposal."""
    parts = _proposal(3)
    doc = parts["word/document.xml"].decode()
    parts["word/document.xml"] = doc.replace(
        '<w:p w14:paraId="11111111" w14:textId="11111111">',
        '<w:p w14:paraId="11111111" w14:textId="11111111"><w:pPr><w:rPr>'
        f'<w:ins w:id="70" {_STAMP}/></w:rPr></w:pPr>', 1).encode()
    path = write(tmp_path / "working.docx", parts)

    assert tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                     seed=_word_like_seed([])) == 2


def test_an_EMPTY_comments_part_takes_the_seed(tmp_path):
    """Finding 14. `restore_parts` fills gaps only, so an empty
    `<w:comments/>` kept its place: a Word session paid for, then "the
    seed copy carries 0 comments", every time (RU Life_Expectancy)."""
    parts = _proposal(3)
    parts["word/comments.xml"] = (
        f'<w:comments xmlns:w="{W_NS}"/>').encode()
    path = write(tmp_path / "working.docx", parts)
    calls: list[int] = []

    assert tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                     seed=_word_like_seed(calls)) == 2
    assert calls == [1]
    assert len(C.read_all(package.read_parts(path))) == 2


def test_EMPTY_comments_are_refused_BEFORE_Word_is_paid_for(tmp_path):
    """One self-closing comment left: Word's save renumbers it, and the
    graft then gave a false "anchored ... has no definition"."""
    parts = _proposal(3)
    parts["word/comments.xml"] = (
        f'<w:comments xmlns:w="{W_NS}"><w:comment w:id="0" '
        f'w:author="A"/></w:comments>').encode()
    path = write(tmp_path / "working.docx", parts)
    calls: list[int] = []

    with pytest.raises(ScaffoldMissing, match="1 empty comment"):
        tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                                  seed=_word_like_seed(calls))
    assert calls == []


def test_the_blocks_may_be_a_GENERATOR(tmp_path):
    """Read twice — the coverage check, then the anchoring — a generator
    was spent by the first and the call wrote nothing."""
    path = write(tmp_path / "working.docx", _proposal(3))

    assert tracked.annotate_in_place(
        path, (b for b in _blocks(3)), author=AUTHOR,
        seed=_word_like_seed([])) == 2
    assert len(C.read_all(package.read_parts(path))) == 2


def test_the_backup_goes_where_it_is_TOLD_and_holds_the_file_as_it_was(
        tmp_path):
    """A protocol manuscript keeps prior generations in build/rescue/,
    not beside working.docx."""
    path = write(tmp_path / "working.docx", _proposal(3))
    was = (tmp_path / "working.docx").read_bytes()
    rescue = tmp_path / "build" / "rescue"

    tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                              seed=_word_like_seed([]), backup_into=rescue)

    kept = list(rescue.glob("*pre_annotate*"))
    assert len(kept) == 1 and kept[0].read_bytes() == was
    assert not list(tmp_path.glob("*pre_annotate*"))


def test_the_GRAFT_brings_the_comment_styles_and_the_author_s_initials(
        tmp_path):
    """What the review found no test reading: the styles Word added with
    the seed, appended to the author's styles; and every balloon's
    initials and date the author's, not the seed's."""
    path = write(tmp_path / "working.docx", _proposal(3))

    tracked.annotate_in_place(path, _blocks(3), author=AUTHOR,
                              seed=_word_like_seed([]))

    after = package.read_parts(path)
    styles = after["word/styles.xml"].decode()
    assert styles.index('w:styleId="Normal"') < styles.index(
        'w:styleId="CommentText"'), "appended, the author's kept first"
    assert 'w:styleId="CommentReference"' in styles
    com = after["word/comments.xml"].decode()
    heads = re.findall(r"<w:comment\b[^>]*>", com)
    assert len(heads) == 2
    for head in heads:
        assert 'w:initials="ML"' in head and 'w:author="Michael Lokshin"' \
            in head, head
        assert 'w:date="2026-07-29' not in head, "not the seed's date"
