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
import types
from pathlib import Path

import pytest

from docxkit import word as W
from docxkit.errors import AnchorError, FontMissing

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
    word = com(FakeWord())
    with W.session(fast=True):
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
        self.closed = False
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

    def Close(self, SaveChanges: int = 0) -> None:
        self.closed = True


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
    """`whitespace` and `formatting` are exposed because two routes built
    with different settings produce different redlines from the same
    pair — the Life Expectancy recipe compares with whitespace OFF so
    respacing at an edit boundary is not shown to an editor."""
    word = RecordingWord()
    W.compare_documents(word, "a.docx", "b.docx",
                        author="Revision R2",
                        whitespace=False, formatting=False)
    assert word.compare_kw["CompareWhitespace"] is False
    assert word.compare_kw["CompareFormatting"] is False
    assert word.compare_kw["RevisedAuthor"] == "Revision R2"
    assert word.compare_args == ("a.docx", "b.docx")


def test_the_comparison_flags_that_must_not_vary_do_not():
    """Moves, tables, footnotes, headers and comments are always
    compared: a redline that silently omits one of them is a redline the
    author cannot rule on."""
    word = RecordingWord()
    W.compare_documents(word, "a.docx", "b.docx")
    for flag in ("CompareMoves", "CompareTables", "CompareFootnotes",
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
    assert word.compare_kw["RevisedAuthor"] == "Revision"


@pytest.fixture
def faked_word(monkeypatch):
    """`session` and `open_doc` replaced, for the wrappers built on them."""
    import contextlib as _c

    exports: list[tuple[object, ...]] = []
    doc = types.SimpleNamespace(
        exports=exports,
        ComputeStatistics=lambda key: 47,
        ExportAsFixedFormat=lambda *a: exports.append(a),
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
