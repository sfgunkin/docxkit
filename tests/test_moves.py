"""`docxkit.moves.tracked_move` — Word moves a block as a tracked change.

The two traps are LFP_Inflows' (2026-11-08): revisions credited to the
signed-in Office account whatever `UserName` said, and a caption carrying
a pending deletion copied as live text ("Figure 12."). The gates read the
package, so they are tested on packages; the Word step is tested once,
for real, under `-m word`, and otherwise replaced by a function that
edits the saved file the way Word would — or the way Word did wrong.
"""
from __future__ import annotations

import contextlib
import pathlib

import pytest
from conftest import make_parts, para, run

from docxkit import moves
from docxkit._xml import DOCUMENT
from docxkit.package import read_parts, write_docx

CO = "Co-author"
ME = "Claude (round C)"


def _ins(text: str, author: str = CO, rid: int = 901) -> str:
    return (f'<w:ins w:id="{rid}" w:author="{author}" '
            f'w:date="2026-11-01T00:00:00Z">{run(text)}</w:ins>')


def _del(text: str, author: str = CO, rid: int = 902) -> str:
    return (f'<w:del w:id="{rid}" w:author="{author}" '
            f'w:date="2026-11-01T00:00:00Z"><w:r><w:delText '
            f'xml:space="preserve">{text}</w:delText></w:r></w:del>')


#: the caption Word flattened: "Figure [del 1][ins 2]. Wages" — the
#: real-Word test's; the gate tests hand-write the redline, so theirs is
#: plain and the co-author's revision sits in the body
LFP_CAPTION = para(run("Figure ", preserve=True), _del("1"),
                   _ins("2", rid=903), run(". Wages"))
CAPTION = para(run("Figure 2. Wages"))


def _body(caption: str) -> str:
    return (para(run("Intro paragraph."))
            + caption
            + para(run("Note: from the survey."))
            + para(run("Body paragraph ", preserve=True), _del("B", rid=902),
                   _ins("A", rid=904), run("."))
            + para(run("Target paragraph."))
            + para(run("End paragraph.")))


BODY = _body(CAPTION)


def _texts(parts: dict[str, bytes], view) -> list[str]:
    return moves._texts(view(parts[DOCUMENT].decode("utf-8")))


# ---------------------------------------------------------------- pure --

def test_the_expected_order_moves_the_block_BELOW_or_ABOVE_its_target():
    texts = ["a", "b", "c", "d", "e", "f", "g"]

    assert moves.expected_after_move(texts, "b", "c", "e") == [
        "a", "d", "e", "b", "c", "f", "g"]
    assert moves.expected_after_move(texts, "e", "f", "a") == [
        "a", "e", "f", "b", "c", "d", "g"]
    assert moves.expected_after_move(texts, "d", None, "g") == [
        "a", "b", "c", "e", "f", "g", "d"]


@pytest.mark.parametrize(("block", "through", "after", "said"), [
    ("omega", None, "alpha", "block 'omega': 0 paragraphs"),
    ("beta", "alpha", "eps", "comes before block"),
    ("beta", "delta", "gamma", "inside the block"),
    ("beta", None, "twice", "after 'twice': 2 paragraphs"),
], ids=["missing", "backwards", "inside", "ambiguous"])
def test_an_anchor_that_does_not_pin_ONE_paragraph_is_refused(
        block, through, after, said):
    texts = ["alpha", "beta", "gamma", "delta", "eps twice", "zeta twice",
             "eta"]
    with pytest.raises(moves.MoveRefused, match=said):
        moves.expected_after_move(texts, block, through, after)


def _moved_by_hand(xml: str, author: str = ME, *, caption: str = "Figure 2. "
                   "Wages") -> str:
    """The redline a CORRECT move writes: the caption and note deleted
    where they were, re-inserted after the target as `caption`."""
    rid = iter(range(1, 20))
    mark = (f'w:author="{author}" w:date="2026-11-09T00:00:00Z"')

    def gone(text: str) -> str:
        return (f'<w:del w:id="{next(rid)}" {mark}><w:r><w:delText '
                f'xml:space="preserve">{text}</w:delText></w:r></w:del>')

    def gone_mark() -> str:
        # the paragraph MARK deleted too, so the emptied paragraph goes
        return (f'<w:pPr><w:rPr><w:del w:id="{next(rid)}" {mark}/>'
                "</w:rPr></w:pPr>")
    old = (CAPTION + para(run("Note: from the survey.")))
    new_old = (f"<w:p>{gone_mark()}{gone('Figure 2. Wages')}</w:p>"
               f"<w:p>{gone_mark()}{gone('Note: from the survey.')}</w:p>")
    target = para(run("Target paragraph."))
    inserted = (para(_ins(caption, author, next(rid)))
                + para(_ins("Note: from the survey.", author, next(rid))))
    assert old in xml and target in xml
    return xml.replace(old, new_old).replace(target, target + inserted)


def test_a_CORRECT_move_passes_every_gate():
    before = make_parts(BODY)
    after = dict(before)
    after[DOCUMENT] = _moved_by_hand(
        before[DOCUMENT].decode("utf-8")).encode("utf-8")

    assert moves.verify_move(before, after, block="Wages",
                             through="Note: from", where="Target",
                             author=ME) == []


def test_the_FLATTENED_caption_Word_copies_fails_the_accept_gate():
    """"Figure [del 1][ins 2]." arriving as the live text "Figure 12."."""
    before = make_parts(BODY)
    after = dict(before)
    after[DOCUMENT] = _moved_by_hand(
        before[DOCUMENT].decode("utf-8"),
        caption="Figure 12. Wages").encode("utf-8")

    (said,) = moves.verify_move(before, after, block="Wages",
                                through="Note: from", where="Target",
                                author=ME)
    assert "accepted text is not the input's" in said


def test_a_move_credited_to_SOMEONE_ELSE_fails_and_names_who():
    before = make_parts(BODY)
    after = dict(before)
    after[DOCUMENT] = _moved_by_hand(
        before[DOCUMENT].decode("utf-8"), author="Office Account"
    ).encode("utf-8")

    said = moves.verify_move(before, after, block="Wages",
                             through="Note: from", where="Target", author=ME)
    assert any("rejecting 'Claude (round C)'" in s for s in said)
    assert any("other authors' revisions changed: Office Account" in s
               for s in said)
    assert any("no revision is credited" in s for s in said)


def test_a_NEW_name_is_reassigned_and_an_OLD_one_refused():
    before = make_parts(BODY)
    after = dict(before)
    after[DOCUMENT] = _moved_by_hand(
        before[DOCUMENT].decode("utf-8"), author="Office Account"
    ).encode("utf-8")

    grew = moves._attribute(before, after, ME, "CRC")

    assert set(grew) == {"Office Account"} and grew["Office Account"] >= 3
    assert moves.verify_move(before, after, block="Wages",
                             through="Note: from", where="Target",
                             author=ME) == []
    shared = dict(before)
    shared[DOCUMENT] = _moved_by_hand(
        before[DOCUMENT].decode("utf-8"), author=CO).encode("utf-8")
    with pytest.raises(moves.MoveRefused, match="already carries"):
        moves._attribute(before, shared, ME, "CRC")


# ------------------------------------------------- the whole call, faked --

def _core(who: str) -> bytes:
    return ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
            'package/2006/metadata/core-properties" xmlns:dc="http://purl.org'
            f'/dc/elements/1.1/"><dc:creator>{who}</dc:creator>'
            "</cp:coreProperties>").encode()


class _FakeOptions:
    UseLocalUserInfo = False


class _FakeWord:
    def __init__(self) -> None:
        self.UserName, self.UserInitials = "Office Account", "OA"
        self.Options = _FakeOptions()
        self.CheckLanguage = True
        self.seen: tuple[str, str, bool] | None = None


def _fake_session(monkeypatch, word: _FakeWord) -> None:
    from docxkit import word as word_mod

    @contextlib.contextmanager
    def session(**_kw):
        yield word

    @contextlib.contextmanager
    def open_doc(_word, path, **_kw):
        yield pathlib.Path(path)

    monkeypatch.setattr(word_mod, "session", session)
    monkeypatch.setattr(word_mod, "open_doc", open_doc)


def test_tracked_move_writes_OUT_reassigns_restores_and_resets_Word(
        monkeypatch, tmp_path):
    src = tmp_path / "paper.docx"
    parts = make_parts(BODY)
    parts["docProps/core.xml"] = _core("input")
    write_docx(src, parts)
    word = _FakeWord()
    _fake_session(monkeypatch, word)

    def as_word_did(w, doc_path, **_kw):
        # Word: revisions under the ACCOUNT, and its name in core.xml
        w.seen = (w.UserName, w.UserInitials, w.Options.UseLocalUserInfo)
        p = read_parts(doc_path)
        p[DOCUMENT] = _moved_by_hand(p[DOCUMENT].decode("utf-8"),
                                     author="Office Account").encode()
        p["docProps/core.xml"] = _core("Office Account")
        write_docx(doc_path, p)
        return 2

    rep = moves.tracked_move(src, tmp_path / "moved.docx", block="Wages",
                             through="Note: from", after="Target", author=ME,
                             initials="CRC", _move=as_word_did)

    assert word.seen == (ME, "CRC", True)
    assert (word.UserName, word.Options.UseLocalUserInfo) == (
        "Office Account", False)
    out = read_parts(tmp_path / "moved.docx")
    assert out["docProps/core.xml"] == parts["docProps/core.xml"]
    assert rep.restored == ["docProps/core.xml"]
    assert set(rep.reassigned) == {"Office Account"} and rep.revisions >= 3
    assert rep.block == ["Figure 2. Wages", "Note: from the survey."]
    assert "2 paragraph(s) moved" in rep.format()
    assert read_parts(src)[DOCUMENT] == parts[DOCUMENT]


def test_tracked_move_REFUSES_a_result_that_fails_a_gate(monkeypatch,
                                                         tmp_path):
    src = tmp_path / "paper.docx"
    write_docx(src, make_parts(BODY))
    _fake_session(monkeypatch, _FakeWord())

    def flattened(_w, doc_path, **_kw):
        p = read_parts(doc_path)
        p[DOCUMENT] = _moved_by_hand(p[DOCUMENT].decode("utf-8"),
                                     caption="Figure 12. Wages").encode()
        write_docx(doc_path, p)
        return 2

    with pytest.raises(moves.MoveRefused, match="left in place"):
        moves.tracked_move(src, tmp_path / "moved.docx", block="Wages",
                           through="Note: from", after="Target", author=ME,
                           _move=flattened)
    assert (tmp_path / "moved.docx").exists()


# ------------------------------------------- the Word step, against fakes --

class _Range:
    def __init__(self, doc: _Doc, start: int, end: int) -> None:
        self.doc, self.Start, self.End = doc, start, end

    @property
    def Revisions(self) -> list[_Rev]:
        return [r for r in self.doc.revisions
                if r.Range.Start < self.End and r.Range.End > self.Start]

    def Delete(self) -> None:
        self.doc.deleted.append((self.Start, self.End))


class _Rev:
    def __init__(self, doc: _Doc, kind: int, start: int, end: int) -> None:
        self.Type, self.Range = kind, _Range(doc, start, end)


class _Doc:
    def __init__(self) -> None:
        self.revisions: list[_Rev] = []
        self.deleted: list[tuple[int, int]] = []

    def Range(self, start: int, end: int) -> _Range:
        return _Range(self, start, end)


def test_only_the_LIVE_stretches_are_deleted_last_first():
    """Another author's pending deletion inside the block is stepped
    over, not taken over; their insertion is deleted with the rest."""
    doc = _Doc()
    doc.revisions = [_Rev(doc, 2, 7, 8),       # their deletion of "1"
                     _Rev(doc, 1, 8, 9),       # their insertion of "2"
                     _Rev(doc, 2, 20, 26),     # a deletion running past
                     _Rev(doc, 2, 40, 45)]     # one outside the block

    moves._delete_live(doc, doc.Range(0, 24))

    assert doc.deleted == [(8, 20), (0, 7)]


class _StepFind:
    def __init__(self, doc: _StepDoc, rng: _StepRange) -> None:
        self.doc, self.rng = doc, rng

    def ClearFormatting(self) -> None:
        pass

    def Execute(self, FindText: str, **_kw) -> bool:
        at = self.doc.text.find(FindText)
        if at < 0:
            return False
        self.rng.Start, self.rng.End = at, at + len(FindText)
        return True


class _StepRange:
    def __init__(self, doc: _StepDoc, start: int, end: int) -> None:
        self.doc, self.Start, self.End = doc, start, end
        self.Find = _StepFind(doc, self)
        self.Revisions: list[object] = []

    @property
    def Range(self) -> _StepRange:
        return self

    @property
    def Paragraphs(self) -> _StepParas:
        return _StepParas(self)

    @property
    def FormattedText(self) -> str:
        return self.doc.text[self.Start:self.End]

    @FormattedText.setter
    def FormattedText(self, value: str) -> None:
        self.doc.log.append(("insert", self.Start, value,
                             self.doc.TrackRevisions))
        if self.doc.scratch:
            self.doc.text = value + "\r"

    def Delete(self) -> None:
        self.doc.log.append(("delete", self.Start, self.End))


class _StepParas:
    """COM's `Paragraphs`: callable for one, and a `Count`."""

    def __init__(self, rng: _StepRange) -> None:
        self.rng = rng
        self.Count = rng.doc.text.count("\r", rng.Start, rng.End)

    def __call__(self, _n: int) -> _StepRange:
        doc, lo = self.rng.doc, self.rng.doc.text.rfind("\r", 0,
                                                        self.rng.Start) + 1
        return _StepRange(doc, lo, doc.text.index("\r", lo) + 1)


class _StepDoc:
    def __init__(self, text: str, log: list[tuple[object, ...]], *,
                 scratch: bool = False) -> None:
        self.text, self.log, self.scratch = text, log, scratch
        self.TrackRevisions = False
        self.Revisions = self

    @property
    def Content(self) -> _StepRange:
        return _StepRange(self, 0, len(self.text))

    def Range(self, start: int = 0, end: int | None = None) -> _StepRange:
        return _StepRange(self, start, len(self.text) if end is None else end)

    def AcceptAll(self) -> None:
        self.log.append(("accept-all in scratch",))

    def Close(self, SaveChanges: int) -> None:
        self.log.append(("close scratch", SaveChanges))

    def Save(self) -> None:
        self.log.append(("save",))


def test_the_WORD_STEP_accepts_in_a_scratch_copy_then_inserts_tracked():
    """Order is the point: the copy is accepted BEFORE it is inserted, the
    insertion is made with Track Changes ON, the source is deleted after,
    and the scratch document is closed unsaved whatever happens."""
    log: list[tuple[object, ...]] = []
    doc = _StepDoc("Intro.\rFigure 2. Wages\rNote: x.\rTarget.\rEnd.\r", log)
    documents = type("D", (), {"Add": staticmethod(
        lambda: _StepDoc("\r", log, scratch=True))})()
    word = type("W", (), {"Documents": documents})()

    n = moves._word_move(word, doc, block="Wages", through="Note:",
                         after="Target")

    kinds = [e[0] for e in log]
    assert kinds == ["insert", "accept-all in scratch", "insert",
                     "close scratch", "delete", "save"]
    assert log[0][1:] == (0, "Figure 2. Wages\rNote: x.\r", False)
    assert log[2][1:] == (len("Intro.\rFigure 2. Wages\rNote: x.\r"
                              "Target.\r"), "Figure 2. Wages\rNote: x.\r",
                          True)
    assert log[3] == ("close scratch", 0)
    assert log[4] == ("delete", 7, 7 + len("Figure 2. Wages\rNote: x.\r"))
    assert n == 2                   # the caption and its note


def test_an_anchor_WORD_cannot_find_is_refused():
    doc = _StepDoc("Intro.\r", [])
    with pytest.raises(moves.MoveRefused, match="Word did not find"):
        moves._paragraph(doc, "Absent")


def test_a_block_with_no_pending_deletion_is_deleted_whole():
    doc = _Doc()
    doc.revisions = [_Rev(doc, 1, 3, 5)]

    moves._delete_live(doc, doc.Range(0, 30))

    assert doc.deleted == [(0, 30)]


# ------------------------------------------------------------ real Word --

@pytest.mark.word
def test_WORD_moves_a_caption_holding_a_pending_revision(tmp_path):
    """LFP_Inflows' Figure 2, end to end: Word does the move, the copy
    reads "Figure 2. Wages" (not "Figure 12."), the co-author's revisions
    are where they were, and rejecting the round gives back the input."""
    shell = next((p for p in pathlib.Path(r"F:\OneDrive\__Documents")
                  .glob("*.docx") if not p.name.startswith("~$")), None)
    if shell is None:
        pytest.skip("no real .docx available as a package shell")
    parts = read_parts(shell)
    for name in [n for n in parts if n.startswith(("word/comments",
                                                   "word/footnotes"))]:
        del parts[name]
    doc = parts[DOCUMENT].decode("utf-8")
    at = doc.index("<w:body>") + len("<w:body>")
    sect = doc.rindex("<w:sectPr")
    parts[DOCUMENT] = (doc[:at] + _body(LFP_CAPTION)
                       + doc[sect:]).encode("utf-8")
    src = tmp_path / "lfp_shape.docx"
    write_docx(src, parts)

    rep = moves.tracked_move(src, tmp_path / "moved.docx", block="Wages",
                             through="Note: from", after="Target", author=ME)

    out = read_parts(tmp_path / "moved.docx")
    from docxkit.revisions import accept
    texts = _texts(out, accept)
    assert texts.index("Target paragraph.") + 1 == texts.index(
        "Figure 2. Wages")
    assert "Figure 12. Wages" not in texts
    assert rep.revisions > 0 and not rep.reassigned
    # the co-author's four are theirs still: the moved-away caption held
    # their deleted "1", which `source.Delete()` took over (2026-11-09)
    from docxkit.authors import read_authors
    assert read_authors(out)[CO] == 4
    # and no "Formatted: English (US)" from language detection
    assert "<w:rPrChange" not in out[DOCUMENT].decode("utf-8")
