"""The decisions `word` makes, faked at the COM boundary.

`cli.py` went 60% -> 100% on this argument and `tracked.py` 0% -> 99%:
which verdict a set of counts earns is a decision the module makes, and
none of them need Word running to be wrong. `word.py` is the boundary
itself, so the fake goes one level lower — into `sys.modules`, because
`session` imports pythoncom and win32com inside the function.

What is worth pinning here is not that Word was called. It is the four
promises the module makes about HOW:

  * a private instance, so an interactive Word is neither reused nor
    closed;
  * the options it switches off for speed are put back, including when
    the body raises — otherwise a crashed build leaves the user's Word
    with spell-check off and no way to know why;
  * a font Word would SUBSTITUTE is refused, because a measurement of a
    substituted face describes the wrong font while looking fine;
  * points become twips by 20, which is the number the whole width model
    is denominated in.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

from docxkit import word as W
from docxkit.errors import AnchorError, DocxKitError, FontMissing, WordTimeout

# ------------------------------------------------------------ fakes ----


class FakeOptions:
    """Word's Options, with one that can be made to fail on write."""

    def __init__(self, *, refuse: str | None = None) -> None:
        object.__setattr__(self, "_refuse", refuse)
        for name in W._FAST_OPTIONS:
            object.__setattr__(self, name, True)

    def __setattr__(self, name: str, value: object) -> None:
        if name == object.__getattribute__(self, "_refuse"):
            raise RuntimeError(f"Word refuses to set {name}")
        object.__setattr__(self, name, value)


class FakeWord:
    def __init__(self, *, refuse: str | None = None,
                 quit_raises: bool = False) -> None:
        self.Options = FakeOptions(refuse=refuse)
        self.Visible: object = "unset"
        self.DisplayAlerts: object = "unset"
        self.ScreenUpdating: object = "unset"
        self.quits = 0
        self._quit_raises = quit_raises

    def Quit(self) -> None:
        self.quits += 1
        if self._quit_raises:
            raise RuntimeError("Word died on the way out")


@pytest.fixture
def com(monkeypatch):
    """`import pythoncom` / `import win32com.client` land on fakes."""
    made: dict[str, object] = {}

    def install(word: FakeWord) -> FakeWord:
        calls: list[str] = []

        client = types.ModuleType("win32com.client")

        def DispatchEx(prog_id: str) -> FakeWord:
            calls.append(prog_id)
            return word

        def Dispatch(prog_id: str) -> FakeWord:
            raise AssertionError(
                "Dispatch reuses the user's open Word; session promises "
                "DispatchEx")

        client.DispatchEx = DispatchEx                 # type: ignore[attr-defined]
        client.Dispatch = Dispatch                     # type: ignore[attr-defined]

        parent = types.ModuleType("win32com")
        parent.client = client                         # type: ignore[attr-defined]

        pythoncom = types.ModuleType("pythoncom")
        inits: list[int] = []
        pythoncom.CoInitialize = lambda: inits.append(1)  # type: ignore[attr-defined]

        monkeypatch.setitem(sys.modules, "win32com", parent)
        monkeypatch.setitem(sys.modules, "win32com.client", client)
        monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
        made["dispatched"] = calls
        made["inits"] = inits
        return word

    install.made = made                                # type: ignore[attr-defined]
    return install


# ---------------------------------------------------------- session ----


def test_a_session_is_private_and_invisible(com):
    word = com(FakeWord())
    with W.session() as got:
        assert got is word
    assert com.made["dispatched"] == ["Word.Application"]
    assert word.Visible is False
    assert word.DisplayAlerts == 0


def test_the_fast_options_are_switched_off_and_put_back(com):
    # `fast` is not named: its DEFAULT is what every entry point in this
    # module gets, and a default of False makes a book-length redline
    # repaginate and spell-check between every edit
    word = com(FakeWord())
    with W.session():
        for name, value in W._FAST_OPTIONS.items():
            assert getattr(word.Options, name) == value
        assert word.ScreenUpdating is False
    for name in W._FAST_OPTIONS:
        assert getattr(word.Options, name) is True     # restored


def test_the_options_are_left_alone_when_fast_is_off(com):
    word = com(FakeWord())
    with W.session(fast=False):
        assert word.ScreenUpdating == "unset"
    for name in W._FAST_OPTIONS:
        assert getattr(word.Options, name) is True


def test_a_body_that_raises_still_restores_and_quits(com):
    """The case that matters: a crashed build must not leave the user's
    Word with spell-check off and nothing to explain it."""
    word = com(FakeWord())
    with pytest.raises(ZeroDivisionError), W.session():
        raise ZeroDivisionError
    for name in W._FAST_OPTIONS:
        assert getattr(word.Options, name) is True
    assert word.quits == 1


def test_word_is_quit_on_the_way_out(com):
    word = com(FakeWord())
    with W.session():
        pass
    assert word.quits == 1


def test_an_option_word_refuses_does_not_abort_the_session(com):
    """`_suppress_com` — letting a refused option kill a 1,400-revision
    build would be the worse outcome."""
    word = com(FakeWord(refuse="BackgroundSave"))
    with W.session() as got:
        assert got is word
    assert word.quits == 1


def test_a_word_that_dies_on_quit_does_not_raise_at_the_caller(com):
    word = com(FakeWord(quit_raises=True))
    with W.session():
        pass
    assert word.quits == 1


# ------------------------------------------------------------ ruler ----

PT_PER_CHAR = 6.0


class FakeRange:
    def __init__(self, doc: FakeDoc, start: int, end: int) -> None:
        self.doc, self.Start, self.End = doc, start, end

    def Information(self, key: int) -> float:
        # Word answers for a range's ACTIVE END, so asking a SPANNING
        # range reports where it ends rather than where the caller
        # thinks it is pointing. The measuring code collapses both
        # probes to a point; the fake refuses anything else, the way
        # the locate fake does.
        assert self.Start == self.End, \
            "Information asked of a spanning range - collapse first"
        if key == W.WD_INFO_LINE:
            return self.doc.line_of(self.Start)
        if key == W.WD_HORIZ_POS_PAGE:
            return self.doc.column_of(self.Start) * PT_PER_CHAR
        raise AssertionError(f"unexpected Information key {key}")


class FakeContent:
    def __init__(self, doc: FakeDoc) -> None:
        self.doc = doc
        self.Font = types.SimpleNamespace(Name=None, Size=None)
        self.ParagraphFormat = types.SimpleNamespace(LeftIndent=None)

    @property
    def Text(self) -> str:
        return "\r".join(self.doc.paras)

    @Text.setter
    def Text(self, value: str) -> None:
        self.doc.paras = value.split("\r")

    def Delete(self) -> None:
        self.doc.paras = []


class FakeDoc:
    """One paragraph per line, unless `wraps` names one that does not."""

    def __init__(self, *, wraps: set[str] | None = None) -> None:
        self.paras: list[str] = []
        self.wraps = wraps or set()
        self.closed: dict[str, int] | None = None
        self.Content = FakeContent(self)
        self.PageSetup = types.SimpleNamespace(
            PageWidth=None, LeftMargin=None, RightMargin=None)
        self.ActiveWindow = types.SimpleNamespace(
            View=types.SimpleNamespace(Type=None))

    # positions: paragraph i starts at sum(len(p)+1 for earlier p)
    def _starts(self) -> list[int]:
        out, at = [], 0
        for p in self.paras:
            out.append(at)
            at += len(p) + 1
        return out

    def _index(self, pos: int) -> int:
        starts = self._starts()
        return max(i for i, s in enumerate(starts) if s <= pos)

    def line_of(self, pos: int) -> int:
        i = self._index(pos)
        # a wrapping paragraph puts its tail on the next line
        if self.paras[i] in self.wraps and pos > self._starts()[i]:
            return i + 2
        return i + 1

    #: characters of left margin. Not zero, because a real document's
    #: text does not begin at x=0 — the module sets LeftMargin itself —
    #: and a fake that puts it there makes `tail - head` and
    #: `tail + head` the same number.
    LEFT_MARGIN_CHARS = 3

    def column_of(self, pos: int) -> int:
        return (self.LEFT_MARGIN_CHARS
                + pos - self._starts()[self._index(pos)])

    def Paragraphs(self, i: int) -> types.SimpleNamespace:
        start = self._starts()[i - 1]
        return types.SimpleNamespace(
            Range=FakeRange(self, start, start + len(self.paras[i - 1]) + 1))

    def Range(self, a: int, b: int) -> FakeRange:
        return FakeRange(self, a, b)

    def Close(self, **kw: int) -> None:
        # the kwargs, not a flag: "closed" is not the promise —
        # "closed without saving" is
        self.closed = kw


class FakeApp:
    def __init__(self, doc: FakeDoc, fonts: tuple[str, ...]) -> None:
        self.FontNames = fonts
        self.Documents = types.SimpleNamespace(Add=lambda: doc)


def ruler_over(doc: FakeDoc, fonts=("Arial", "Times New Roman")):
    return W.ruler(FakeApp(doc, fonts))


def test_a_width_is_the_span_of_the_line_in_twips():
    """Points to twips by 20 — the unit the whole width model is
    denominated in, and a factor no other test here would notice."""
    doc = FakeDoc()
    with ruler_over(doc) as measure:
        assert measure("Arial", ["abc"]) == [3 * PT_PER_CHAR * 20.0]
        assert measure("Arial", ["abcdef"]) == [6 * PT_PER_CHAR * 20.0]


def test_several_texts_are_measured_in_one_pass():
    doc = FakeDoc()
    with ruler_over(doc) as measure:
        assert measure("Arial", ["a", "bb", "ccc"]) == [
            PT_PER_CHAR * 20.0, 2 * PT_PER_CHAR * 20.0,
            3 * PT_PER_CHAR * 20.0]


def test_a_font_word_would_substitute_is_refused():
    """The guard the width model depends on: Word substitutes silently,
    so the measurement would describe a different face and look fine."""
    doc = FakeDoc()
    with ruler_over(doc) as measure, pytest.raises(FontMissing,
                                                   match="not installed"):
        measure("Nonesuch Display", ["abc"])


def test_a_text_with_a_line_break_is_refused():
    doc = FakeDoc()
    with ruler_over(doc) as measure, pytest.raises(AnchorError,
                                                   match="line break"):
        measure("Arial", ["one\rtwo"])


def test_the_refusal_names_the_FIRST_text_that_carries_a_break():
    """`bad[0]`. A bulk ruler run measures a whole table's cells at
    once, so more than one can carry a paragraph mark — and the name in
    the message is where the caller goes to look. Naming the last one
    sends them to the wrong cell; naming the first is the one they meet
    reading down."""
    doc = FakeDoc()
    with ruler_over(doc) as measure, pytest.raises(AnchorError) as exc:
        measure("Arial", ["fine", "first\rbroken", "second\rbroken"])

    assert "'first\\rbroken'" in str(exc.value), str(exc.value)
    assert "second" not in str(exc.value)


def test_the_measuring_paragraphs_are_UNINDENTED():
    """`LeftIndent = 0`. The measuring document inherits Word's default
    template, and a template with an indented Normal style would put
    every measured line somewhere other than the margin. The width is a
    difference so it survives that — until a paragraph is indented far
    enough to wrap, which is the case this setting exists to stop."""
    doc = FakeDoc()
    with ruler_over(doc) as measure:
        measure("Arial", ["abc"])

    assert doc.Content.ParagraphFormat.LeftIndent == 0


def test_a_text_that_wraps_cannot_be_read_off_one_line():
    doc = FakeDoc(wraps={"a very long line"})
    with ruler_over(doc) as measure, pytest.raises(AnchorError,
                                                   match="wraps"):
        measure("Arial", ["a very long line"])


def test_the_measuring_document_is_closed_afterwards():
    doc = FakeDoc()
    with ruler_over(doc) as measure:
        measure("Arial", ["abc"])
    assert doc.closed


def test_the_measuring_document_is_closed_even_after_a_refusal():
    doc = FakeDoc()
    with pytest.raises(FontMissing), ruler_over(doc) as measure:
        measure("Nonesuch", ["abc"])
    assert doc.closed


def test_the_measuring_document_is_set_to_TEN_POINT():
    """`size_pt: float = 10.0`. Every width in the model is denominated
    at one size, and the default is the one the tables were built with —
    measure at eleven and every column comes back wider than the layout
    it is checked against, with nothing in the report to say why."""
    doc = FakeDoc()
    with ruler_over(doc) as measure:
        measure("Arial", ["abc"])

    assert doc.Content.Font.Size == 10.0
    assert doc.Content.Font.Name == "Arial"


def test_the_measuring_document_is_closed_WITHOUT_saving():
    """`SaveChanges=0`. The measuring document is scratch — a page of
    the caller's own strings at 1584pt — and 1 is wdSaveChanges, which
    asks Word to write it somewhere. On an unattended run that is a
    Save As dialog nobody is there to answer."""
    doc = FakeDoc()
    with ruler_over(doc) as measure:
        measure("Arial", ["abc"])

    assert doc.closed == {"SaveChanges": 0}


def test_the_page_is_made_wide_enough_not_to_wrap_by_itself():
    """1584pt is Word's maximum. A narrow page would wrap the text and
    every measurement would raise instead of answering."""
    doc = FakeDoc()
    with ruler_over(doc):
        pass
    assert doc.PageSetup.PageWidth == 1584
    assert doc.PageSetup.LeftMargin == doc.PageSetup.RightMargin == 18
    assert doc.ActiveWindow.View.Type == W.WD_PRINT_VIEW


# ------------------------------------------- the thin wrappers' choices --


def test_draft_view_hides_the_markup_it_would_otherwise_lay_out():
    """Balloon layout is pure cost on a 1,400-revision redline."""
    doc = FakeDoc()
    W.draft_view(doc)
    assert doc.ActiveWindow.View.Type == W.WD_NORMAL_VIEW
    assert doc.ActiveWindow.View.ShowRevisionsAndComments is False


def test_draft_view_on_a_document_that_refuses_does_not_raise():
    class Stubborn:
        @property
        def ActiveWindow(self):
            raise RuntimeError("no window")

    W.draft_view(Stubborn())                           # must not raise


def test_extract_flat_opc_writes_what_word_serialised(tmp_path):
    doc = types.SimpleNamespace(
        Content=types.SimpleNamespace(WordOpenXML="<pkg>ünïcode</pkg>"))
    out = W.extract_flat_opc(doc, tmp_path / "flat.xml")
    assert out.read_text(encoding="utf-8") == "<pkg>ünïcode</pkg>"


class RecordingWord:
    def __init__(self) -> None:
        self.compare_kw: dict[str, object] = {}

    def CompareDocuments(self, original, revised, **kw):
        self.compare_kw = kw
        self.compare_args = (original, revised)
        return "redline"


def test_the_comparison_flags_that_change_the_deliverable_are_threaded():
    """`whitespace`, `formatting` and `moves` are exposed because two
    routes built with different settings produce different redlines from
    the same pair — the Life Expectancy recipe compares with whitespace
    OFF so respacing at an edit boundary is not shown to an editor."""
    word = RecordingWord()
    W.compare_documents(word, "a.docx", "b.docx",
                        author="Revision R2",
                        whitespace=False, formatting=False, moves=False)
    assert word.compare_kw["CompareWhitespace"] is False
    assert word.compare_kw["CompareFormatting"] is False
    assert word.compare_kw["CompareMoves"] is False
    assert word.compare_kw["RevisedAuthor"] == "Revision R2"
    assert word.compare_args == ("a.docx", "b.docx")


def test_the_comparison_flags_that_must_not_vary_do_not():
    """Tables, footnotes, headers and comments are always compared: a
    redline that silently omits one of them is a redline the author
    cannot rule on.

    `CompareMoves` was in this list and came out on 2026-08-31. It is
    not the same kind of flag: the others decide what Word LOOKS at,
    and move detection decides how it EXPLAINS what it found — a
    heuristic, and one measured getting it wrong, truncating the
    paragraph it scored as moved. Pinning it here read as "a move is
    always shown" and meant "a round that moves a passage cannot be
    built"."""
    word = RecordingWord()
    W.compare_documents(word, "a.docx", "b.docx")
    for flag in ("CompareTables", "CompareFootnotes",
                 "CompareHeaders", "CompareComments", "CompareTextboxes",
                 "CompareFields", "CompareCaseChanges"):
        assert word.compare_kw[flag] is True, flag
    assert word.compare_kw["Destination"] == W.WD_COMPARE_TO_NEW
    assert word.compare_kw["Granularity"] == 1          # word level
    # and the warning dialog is suppressed: a build runs unattended, and
    # Word's "this document contains tracked changes" prompt waits for a
    # click that nobody is there to give
    assert word.compare_kw["IgnoreAllComparisonWarnings"] is True


def test_the_comparison_DEFAULTS_are_the_thorough_ones():
    """`whitespace` and `formatting` default to True, and the author to
    "Revision". A caller that names neither gets the comparison that
    shows the most — a default of False is a redline missing a class of
    change, and the only way to notice is to already know it was there.
    The test beside this one passes both explicitly, so the defaults
    themselves had no witness."""
    word = RecordingWord()

    W.compare_documents(word, "a.docx", "b.docx")

    assert word.compare_kw["CompareWhitespace"] is True
    assert word.compare_kw["CompareFormatting"] is True
    assert word.compare_kw["CompareMoves"] is True
    assert word.compare_kw["RevisedAuthor"] == "Revision"


@pytest.fixture
def faked_word(monkeypatch):
    """`session` and `open_doc` replaced, for the wrappers built on them."""
    import contextlib as _c

    exports: list[tuple[object, ...]] = []
    doc = types.SimpleNamespace(
        exports=exports,
        ComputeStatistics=lambda key: 47,
        ExportAsFixedFormat=lambda *a, **kw: exports.append(
            (*a, kw) if kw else a),
        ActiveWindow=types.SimpleNamespace(
            View=types.SimpleNamespace(Type=None)),
        Repaginate=lambda: None)

    @_c.contextmanager
    def fake_session(**kw):
        yield "the-word-app"

    @_c.contextmanager
    def fake_open(word, path, **kw):
        yield doc

    monkeypatch.setattr(W, "session", fake_session)
    monkeypatch.setattr(W, "open_doc", fake_open)
    return doc


def test_a_page_range_becomes_words_seven_argument_export(faked_word,
                                                          tmp_path):
    """From and To are inert unless Range says to read them.

    This asserted the call SHAPE -- seven arguments, (2, 5) on the end --
    and passed for as long as the fifth was `wdExportAllDocument`, which
    tells Word to export everything and ignore From/To. Every
    `--pages 1-3` render was the whole document, and the byte count
    printed underneath made it look like it had worked.
    """
    out = W.export_pdf("in.docx", tmp_path / "o.pdf", first=2, last=5)
    (args,) = faked_word.exports
    assert args[1] == W.WD_EXPORT_PDF
    assert args[4] == W.WD_EXPORT_FROM_TO
    assert args[-2:] == (2, 5)
    assert out == tmp_path / "o.pdf"
    # the two in the middle, which nothing named: third is
    # OpenAfterExport — a build runs unattended and must not put a PDF
    # viewer on the screen for every range — and fourth is OptimizeFor,
    # 0 being wdExportOptimizeForPrint. The point of rendering through
    # Word at all is to look at the equations, and the on-screen setting
    # downsamples what you came to read.
    assert args[2] is False
    assert args[3] == 0


def test_the_destination_reaches_word_as_an_absolute_path(faked_word,
                                                          monkeypatch,
                                                          tmp_path):
    """Word has its own working directory. Handed a relative path, it
    wrote the render into its default folder while this returned a path
    with no file at it, and the caller went looking for a PDF that was
    never there."""
    monkeypatch.chdir(tmp_path)
    out = W.export_pdf("in.docx", "o.pdf")
    (args,) = faked_word.exports
    assert Path(args[0]).is_absolute()
    assert Path(args[0]).parent == tmp_path.resolve()
    assert out == tmp_path.resolve() / "o.pdf"


def test_no_page_range_exports_the_whole_document(faked_word, tmp_path):
    W.export_pdf("in.docx", tmp_path / "o.pdf")
    (args,) = faked_word.exports
    assert len(args) == 2
    assert args[1] == W.WD_EXPORT_PDF


def test_HALF_a_page_range_exports_the_whole_document_too(faked_word,
                                                          tmp_path):
    """`first and last`, not `or`. A range needs both ends: given one,
    the seven-argument call hands Word a None it cannot read, and the
    render fails at the COM boundary instead of doing the obvious thing.
    Both fixtures beside this one give both ends or neither."""
    W.export_pdf("in.docx", tmp_path / "o.pdf", first=2)

    (args,) = faked_word.exports
    assert len(args) == 2, args


def test_the_page_count_is_read_after_repagination(faked_word):
    """Word answers about the layout it last computed, so the count of a
    document it has not repaginated is the previous document's."""
    assert W.page_count("in.docx") == 47


def test_locate_opens_the_file_and_passes_its_flags_through(faked_word,
                                                            monkeypatch):
    """The path form is a wrapper over the doc form. `ordered` in
    particular has to survive it: it picks the right occurrence of a
    repeated phrase, and dropping it silently returns the first."""
    seen: dict[str, object] = {}

    def spy(doc, anchors, **kw):
        seen.update(doc=doc, anchors=list(anchors), **kw)
        return ["located"]

    monkeypatch.setattr(W, "locate_in", spy)
    # `object`, because the spy stands in for a list[Location] and the
    # sentinel is what proves the wrapper returned what it delegated to
    got: object = W.locate("paper.docx", ["an anchor"], ordered=True,
                           strict=False, unique=False)

    assert got == ["located"]
    assert seen["anchors"] == ["an anchor"]
    assert seen["ordered"] is True
    assert seen["strict"] is False
    assert seen["unique"] is False

    # and the defaults, which a wrapper that hard-codes one of them
    # would answer the same way for every caller
    seen.clear()
    W.locate("paper.docx", ["an anchor"])
    assert (seen["ordered"], seen["strict"], seen["unique"]) == (
        False, True, True)


def test_locate_revisions_opens_the_file_and_passes_its_limit(faked_word,
                                                              monkeypatch):
    seen: dict[str, object] = {}

    def spy(doc, **kw):
        seen.update(doc=doc, **kw)
        return ["rev"]

    monkeypatch.setattr(W, "revision_locations", spy)
    got: object = W.locate_revisions("redline.docx", limit=12)
    assert got == ["rev"]
    assert seen["limit"] == 12


# ------------------------------------------------------ shared_session ----
#
# Word's cold start is the largest fixed cost a revision batch pays:
# `build` opens one for Compare and its in-Word verify, `validate`
# opens another, and they run back to back on every batch. Measured on
# a one-edit AFI batch, 2026-08-20: 13.5 s + 38.9 s of about 95.


def test_a_shared_session_opens_ONE_Word_for_every_session_inside(com):
    word = com(FakeWord())

    with W.shared_session(), W.session() as a, W.session() as b:
        assert a is b is word

    assert com.made["dispatched"] == ["Word.Application"]
    assert word.quits == 1


def test_a_session_OUTSIDE_the_block_opens_its_own_again(com):
    """The sharing is scoped, not a process-wide switch: what is inside
    the block shares, and the next caller is back to a private Word."""
    word = com(FakeWord())

    with W.shared_session(), W.session():
        pass
    with W.session():
        pass

    assert com.made["dispatched"] == ["Word.Application"] * 2
    assert word.quits == 2


def test_NESTING_a_shared_session_is_a_no_op(com):
    """A caller may wrap a ladder without knowing which steps open Word,
    and the inner block must not quit the outer one's instance."""
    word = com(FakeWord())
    shared = W.shared_session

    with shared() as outer:
        with shared() as inner:
            assert inner is outer
        assert word.quits == 0, "the inner block quit the shared Word"
        # and the sharing survives it: an inner block that RELEASED the
        # instance on its way out leaves every later session() in the
        # outer block opening a Word of its own
        with W.session() as after:
            assert after is outer

    assert word.quits == 1
    assert com.made["dispatched"] == ["Word.Application"]


def test_a_shared_session_yields_NONE_when_Word_cannot_START(monkeypatch):
    """No Word here must stay the same failure it always was, in the
    same place: this saves a start, it does not invent an error."""

    class Refuses:
        """What a machine with no COM does: the CALL builds a context
        manager like any other, and entering it is what fails."""

        def __enter__(self) -> None:
            raise RuntimeError("no COM on this machine")

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(W, "session", lambda **_kw: Refuses())

    with W.shared_session() as word:
        assert word is None
    assert not W._SHARED


def test_the_shared_instance_is_RELEASED_when_the_block_raises(com):
    """A held instance would be handed to the next caller in this
    process — an invisible Word nobody owns, and every session() after
    it quietly reusing a dead COM object."""
    word = com(FakeWord())

    with pytest.raises(ValueError, match="the batch failed"), \
            W.shared_session():
        raise ValueError("the batch failed")

    assert not W._SHARED
    assert word.quits == 1


def test_a_shared_session_still_asks_Word_to_go_FAST(com):
    """The options are why `session` exists in the form it does — spell
    check, background save and screen updating off — and a shared one
    opens the instance every other caller then gets."""
    word = com(FakeWord())

    with W.shared_session():
        assert word.Options.CheckSpellingAsYouType is False
        assert word.ScreenUpdating is False


def test_a_shared_session_can_be_asked_NOT_to(com):
    word = com(FakeWord())

    with W.shared_session(fast=False):
        assert word.Options.CheckSpellingAsYouType != False    # noqa: E712

def test_a_REDLINE_is_rendered_WITH_its_markup(faked_word, tmp_path):
    """`Item` defaults to the document without revision marks, so a
    redline rendered by the old call came out as clean text — no
    strikethrough, no change bars, nothing saying the markup had been
    omitted. That is a false NEGATIVE in the check this module
    recommends for verifying a deliverable by eye, and it cost twenty
    minutes hunting a bug that did not exist (HCW, 2026-08-24)."""
    W.export_pdf("in.docx", tmp_path / "o.pdf", markup=True)

    (args,) = faked_word.exports

    assert args[-1] == {"Item": W.WD_EXPORT_WITH_MARKUP}, args


def test_the_ORDINARY_render_is_unchanged(faked_word, tmp_path):
    """The default stays the accepted view: the other caller of this is
    the equation check, where the page a reader gets is the point. The
    call keeps its two-argument shape rather than spelling out a
    default it already had."""
    W.export_pdf("in.docx", tmp_path / "o.pdf")

    (args,) = faked_word.exports

    assert len(args) == 2 and args[1] == W.WD_EXPORT_PDF, args


def test_a_page_RANGE_can_also_carry_markup(faked_word, tmp_path):
    W.export_pdf("in.docx", tmp_path / "o.pdf", first=2, last=5, markup=True)

    (args,) = faked_word.exports

    assert args[4] == W.WD_EXPORT_FROM_TO
    assert args[5:7] == (2, 5)
    assert args[-1] == {"Item": W.WD_EXPORT_WITH_MARKUP}, args


# ------------------------------------------------------------ deadline ----
#
# Row 6 of the 2026-09-03 review. Word's save path can hang indefinitely
# and a Compare can too; a COM call blocks the thread with no way to
# give up, and the only ceiling anywhere was pytest's. The mechanism:
# the session's own pid, found by the WINWORD list before and after
# `DispatchEx` (`Application.Hwnd` does not exist on this Word — both
# bindings say "unknown name"), a timer that kills THAT process, and
# the blocked call's failure renamed `WordTimeout`.


@pytest.fixture
def bounded(monkeypatch):
    """A process list that shows one WINWORD appearing, and a kill that
    records rather than kills."""
    lists = iter([frozenset({11}), frozenset({11, 42})])
    monkeypatch.setattr(W, "_winword_pids", lambda: next(lists))
    killed: list[int] = []
    monkeypatch.setattr(W, "_kill", killed.append)
    return killed


def test_a_deadline_records_the_new_pid_and_is_cancelled_on_exit(
        com, bounded):
    word = com(FakeWord())

    with W.session(deadline=5, doing="a probe") as app:
        assert app is word
        assert W._WATCHDOG[0].pid == 42
        assert W._WATCHDOG[0].fired is False

    assert bounded == []
    assert W._WATCHDOG == []
    assert word.quits == 1


def test_a_call_still_blocked_when_the_deadline_fires_is_a_WordTimeout(
        com, bounded):
    word = com(FakeWord())

    with pytest.raises(WordTimeout,
                       match=r"while comparing X; its process \(42\) was "
                             r"killed") as info, \
            W.session(deadline=0.05, doing="comparing X"):
        time.sleep(0.3)                            # the blocked COM call
        raise RuntimeError("RPC server is unavailable")  # what COM says

    assert bounded == [42]
    assert isinstance(info.value.__cause__, RuntimeError)
    assert "word_deadline" in str(info.value), "the remedy is in the message"
    assert word.quits == 1                         # tried, harmlessly
    assert W._WATCHDOG == []


def test_a_failure_BEFORE_the_deadline_keeps_its_own_name(com, bounded):
    com(FakeWord())

    with pytest.raises(RuntimeError, match="genuine"), \
            W.session(deadline=5, doing="x"):
        raise RuntimeError("a genuine failure")

    assert bounded == []


def test_no_deadline_never_reads_the_process_list(com, monkeypatch):
    """The library default — and `0`, which the config spells "no
    ceiling" as — must cost nothing: no `tasklist`, no timer."""
    com(FakeWord())

    def never():
        raise AssertionError("the process list was read")

    monkeypatch.setattr(W, "_winword_pids", never)
    with W.session():
        pass
    with W.session(deadline=0):
        pass
    assert W._WATCHDOG == []


def test_an_ambiguous_process_list_REFUSES_and_still_quits(com, monkeypatch):
    """Two Words started in the same second: the pid cannot be told, and
    a ceiling that might kill the wrong one is no ceiling. The instance
    already started is still quit — a refusal must not orphan it."""
    word = com(FakeWord())
    lists = iter([frozenset({11}), frozenset({11, 42, 43})])
    monkeypatch.setattr(W, "_winword_pids", lambda: next(lists))

    with pytest.raises(DocxKitError, match=r"cannot bound x: .*\[42, 43\]"), \
            W.session(deadline=5, doing="x"):
        pass                                         # pragma: no cover

    assert word.quits == 1
    assert W._WATCHDOG == []


def test_a_shared_session_renames_the_timeout_TOO(com, bounded):
    """`shared_session` exits the inner session with no exception, so the
    body's failure never reaches the generator that armed the watchdog;
    the rename has to happen where the exception passes."""
    word = com(FakeWord())

    with pytest.raises(WordTimeout, match="a ladder"), \
            W.shared_session(deadline=0.05, doing="a ladder"), \
            W.session() as inner:
        assert inner is word
        time.sleep(0.3)
        raise RuntimeError("RPC server is unavailable")

    assert bounded == [42]
    assert W._SHARED == []
    assert W._WATCHDOG == []


def test_a_shared_session_that_cannot_be_bounded_RAISES_not_None(
        com, monkeypatch):
    """"No Word here" yields None and every session inside carries on
    unbounded; a ceiling that cannot be honoured is not that, and
    turning it into None would be the silent downgrade."""
    com(FakeWord())
    lists = iter([frozenset(), frozenset({1, 2})])
    monkeypatch.setattr(W, "_winword_pids", lambda: next(lists))

    with pytest.raises(DocxKitError, match="cannot bound a ladder"), \
            W.shared_session(deadline=5, doing="a ladder"):
        pass                                         # pragma: no cover


def test_the_process_list_is_parsed_from_tasklist_CSV(monkeypatch):
    csv = ('"WINWORD.EXE","31952","Console","1","123,456 K"\n'
           '"WINWORD.EXE","11564","Console","1","98,304 K"\n')

    def listing(text: str):
        return lambda *_a, **_k: types.SimpleNamespace(stdout=text)

    monkeypatch.setattr(W.subprocess, "run", listing(csv))
    assert W._winword_pids() == frozenset({31952, 11564})

    none = "INFO: No tasks are running which match the specified criteria.\n"
    monkeypatch.setattr(W.subprocess, "run", listing(none))
    assert W._winword_pids() == frozenset()


def test_kill_asks_taskkill_for_the_TREE_by_pid(monkeypatch):
    calls: list[list[str]] = []

    def run(argv, **_k):
        calls.append(argv)
        return types.SimpleNamespace(stdout="")

    monkeypatch.setattr(W.subprocess, "run", run)

    W._kill(42)

    assert calls == [["taskkill", "/PID", "42", "/T", "/F"]]


@pytest.mark.word
def test_a_REAL_hidden_Word_is_killed_by_pid_on_expiry():
    """The mechanism against the real thing: the session's own process
    goes, no other Word does, and the next COM call fails into
    WordTimeout. Measured 2026-09-03: `Quit()` is asynchronous, so a
    process outliving the call by a moment is normal; a killed one is
    gone at once."""
    others = W._winword_pids()
    pid = -1

    with pytest.raises(WordTimeout, match="a probe"), \
            W.session(deadline=1.0, doing="a probe") as word:
        pid = W._WATCHDOG[0].pid
        assert pid not in others
        time.sleep(2.5)
        _ = word.Visible                 # the blocked call, once Word is gone

    assert pid > 0 and pid not in W._winword_pids()
    assert W._WATCHDOG == []
