"""Page/line lookup, without needing Word.

The COM object model is faked here on purpose. The Word-backed half of
:mod:`docxkit.word` is validated against real manuscripts, but the logic
worth pinning is ours, not Word's: which occurrence an ordered scan picks,
that a range is collapsed before it is asked for a page, and that a missing
anchor is reported rather than silently skipped. The fake is a flat string
with a fixed number of characters per page, so every expected page and line
in here can be worked out by hand.
"""
from __future__ import annotations

import pytest

from docxkit.errors import AnchorError
from docxkit.word import (
    WD_INFO_ADJUSTED_PAGE,
    WD_INFO_LINE,
    WD_INFO_PAGE,
    locate_in,
    revision_locations,
    search_text,
)

PAGE_CHARS = 100        # characters per laid-out page in the fake
LINE_CHARS = 10         # characters per line
FRONT_MATTER = 1        # unnumbered pages, so printed page = file page - 1


class FakeFind:
    def __init__(self, rng: FakeRange) -> None:
        self._rng = rng
        self.Text = ""

    def ClearFormatting(self) -> None:
        pass

    def Execute(self) -> bool:
        rng = self._rng
        rng.doc.finds += 1              # attempts, so tests can count cost
        window = rng.doc.text[rng.Start:rng.End]
        at = window.find(self.Text)
        if at < 0:
            return False
        # Word rewrites the range in place to the match it found.
        rng.Start += at
        rng.End = rng.Start + len(self.Text)
        return True


class FakeRange:
    def __init__(self, doc: FakeDoc, start: int, end: int,
                 text: str | None = None) -> None:
        self.doc = doc
        self.Start = start
        self.End = end
        self.Text = text

    @property
    def Find(self) -> FakeFind:
        return FakeFind(self)

    def SetRange(self, start: int, end: int) -> None:
        self.Start, self.End = start, end

    def Collapse(self, direction: int) -> None:
        if direction == 1:
            self.End = self.Start
        else:
            self.Start = self.End

    def Information(self, key: int) -> int:
        if not self.doc.repaginated:
            # Word answers from a stale layout instead of failing; the fake
            # makes that visible as an absurd number rather than a crash.
            return -1
        # Word reports for the range's ACTIVE END. Asking a spanning range
        # therefore reports the wrong end, so the fake refuses outright:
        # the code under test must always collapse (or SetRange to a
        # point) before it asks.
        assert self.Start == self.End, \
            "Information asked of a spanning range - collapse first"
        page = self.End // PAGE_CHARS + 1
        if key == WD_INFO_PAGE:
            return page
        if key == WD_INFO_ADJUSTED_PAGE:
            return page - FRONT_MATTER
        if key == WD_INFO_LINE:
            return self.End % PAGE_CHARS // LINE_CHARS + 1
        raise AssertionError(f"unexpected Information key {key}")


class FakeRevision:
    def __init__(self, doc: FakeDoc, kind: int, start: int,
                 text: str | None) -> None:
        self.Type = kind
        self._doc = doc
        self._start = start
        self._text = text

    @property
    def Range(self) -> FakeRange:
        # Word hands back a FRESH Range object on every access; the code
        # under test relies on that when it collapses its copy in place.
        return FakeRange(self._doc, self._start,
                         self._start + len(self._text or ""), self._text)


class FakeView:
    def __init__(self) -> None:
        self.Type = 1                   # draft: page numbers are meaningless


class FakeWindow:
    def __init__(self) -> None:
        self.View = FakeView()


class FakeDoc:
    def __init__(self, text: str, revisions: list[FakeRevision] | None = None
                 ) -> None:
        self.text = text
        self.repaginated = False
        self.finds = 0
        self.ActiveWindow = FakeWindow()
        self.Revisions = revisions or []

    @property
    def Content(self) -> FakeRange:
        return FakeRange(self, 0, len(self.text))

    def Range(self, start: int, end: int) -> FakeRange:
        return FakeRange(self, start, end)

    def Repaginate(self) -> None:
        self.repaginated = True


def make_doc(*chunks: tuple[int, str]) -> FakeDoc:
    """A document with each `text` planted at each offset."""
    size = max(at + len(text) for at, text in chunks)
    buf = ["."] * (size + PAGE_CHARS)
    for at, text in chunks:
        buf[at:at + len(text)] = list(text)
    return FakeDoc("".join(buf))


# --- search_text -----------------------------------------------------------

def test_caret_is_escaped():
    # An unescaped caret is not a miss - Word raises "not a valid special
    # character" and the whole run dies.
    assert search_text("a ^ b") == "a ^^ b"


def test_over_long_anchor_is_trimmed_after_escaping():
    text = search_text("^" * 200)
    assert len(text) <= 255
    assert text.count("^") % 2 == 0      # never a half-escaped caret


def test_plain_anchor_trimmed_to_the_find_limit():
    assert len(search_text("x" * 400)) == 255


def test_anchor_stops_at_the_first_paragraph_mark():
    # Find cannot match across a paragraph mark, so only one line can be
    # searched for.
    assert search_text("first line\rsecond line") == "first line"


def test_anchor_starting_with_a_paragraph_mark_is_still_searchable():
    # A revision's text often STARTS with the paragraph mark it inserted;
    # taking the first line literally would search for nothing and raise.
    assert search_text("\rNew paragraph text") == "New paragraph text"


def test_empty_anchor_is_refused():
    # An empty Find matches formatting, not text: it would report a page
    # for nothing at all.
    with pytest.raises(AnchorError):
        search_text("   ")


# --- locate_in -------------------------------------------------------------

def test_page_and_line_are_reported_for_each_anchor():
    doc = make_doc((250, "alpha"), (1040, "omega"))
    alpha, omega = locate_in(doc, ["alpha", "omega"])
    assert (alpha.doc_page, alpha.line) == (3, 6)
    assert (omega.doc_page, omega.line) == (11, 5)


def test_printed_page_differs_from_the_file_page():
    doc = make_doc((250, "alpha"))
    (loc,) = locate_in(doc, ["alpha"])
    assert (loc.page, loc.doc_page) == (2, 3)
    assert "file page 3" in str(loc)


def test_the_document_is_repaginated_before_anything_is_asked():
    # session(fast=True) turns background pagination off; without an
    # explicit Repaginate the answer comes from a stale layout.
    doc = make_doc((250, "alpha"))
    (loc,) = locate_in(doc, ["alpha"])
    assert doc.repaginated
    assert loc.page > 0


def test_print_layout_is_forced():
    doc = make_doc((250, "alpha"))
    locate_in(doc, ["alpha"])
    assert doc.ActiveWindow.View.Type == 3      # draft view does not paginate


def test_the_start_page_is_reported_not_the_end():
    # An anchor straddling a page break belongs to the page it starts on.
    doc = make_doc((95, "spanning the break"))
    (loc,) = locate_in(doc, ["spanning the break"])
    assert loc.doc_page == 1


def test_a_repeated_anchor_is_flagged():
    doc = make_doc((250, "alpha"), (1040, "alpha"))
    (loc,) = locate_in(doc, ["alpha"])
    assert loc.repeats
    assert loc.doc_page == 3          # the first hit, not the last


def test_uniqueness_check_can_be_skipped():
    doc = make_doc((250, "alpha"), (1040, "alpha"))
    before = doc.finds
    (loc,) = locate_in(doc, ["alpha"], unique=False)
    assert not loc.repeats
    assert doc.finds - before == 1     # the second search is what it costs


def test_a_missing_anchor_raises_by_default():
    doc = make_doc((250, "alpha"))
    with pytest.raises(AnchorError) as exc:
        locate_in(doc, ["alpha", "nowhere"])
    assert "nowhere" in str(exc.value)


def test_without_strict_the_misses_are_simply_absent():
    doc = make_doc((250, "alpha"))
    found = locate_in(doc, ["nowhere", "alpha"], strict=False)
    assert [loc.anchor for loc in found] == ["alpha"]


def test_an_unsearchable_anchor_is_a_miss_not_a_crash():
    # A bulk run over revision texts hits anchors with nothing to search
    # for (a pure paragraph-mark insertion, an NBSP-filled table cell).
    # Under strict=False one of those must not kill the whole run.
    doc = make_doc((250, "alpha"))
    found = locate_in(doc, [" ", "alpha"], strict=False)
    assert [loc.anchor for loc in found] == ["alpha"]


def test_an_unsearchable_anchor_still_fails_a_strict_run():
    doc = make_doc((250, "alpha"))
    with pytest.raises(AnchorError):
        locate_in(doc, ["", "alpha"])


def test_ordered_walks_forward_through_repeats():
    # Two revisions quoting the same phrase are two different places; a
    # from-the-top search would report the first one twice.
    doc = make_doc((250, "same phrase"), (1040, "same phrase"))
    first, second = locate_in(doc, ["same phrase", "same phrase"],
                              ordered=True)
    assert first.doc_page == 3
    assert second.doc_page == 11


def test_unordered_reports_the_first_hit_every_time():
    doc = make_doc((250, "same phrase"), (1040, "same phrase"))
    first, second = locate_in(doc, ["same phrase", "same phrase"])
    assert first.doc_page == second.doc_page == 3


def test_ordered_retries_over_the_whole_document():
    # One anchor out of order must cost speed, not a result.
    doc = make_doc((250, "alpha"), (1040, "omega"))
    omega, alpha = locate_in(doc, ["omega", "alpha"], ordered=True)
    assert omega.doc_page == 11
    assert alpha.doc_page == 3


# --- revision_locations ----------------------------------------------------

def test_revisions_are_located_without_searching():
    doc = make_doc((250, "inserted"), (1040, "removed"))
    doc.Revisions = [FakeRevision(doc, 1, 250, "inserted"),
                     FakeRevision(doc, 2, 1040, "removed")]
    before = doc.finds
    ins, dele = revision_locations(doc)
    assert doc.finds == before          # a revision knows its own range
    assert (ins.kind, ins.doc_page, ins.text) == ("insert", 3, "inserted")
    assert (dele.kind, dele.doc_page) == ("delete", 11)
    assert ins.number == 1


def test_a_property_level_revision_has_no_text():
    # A self-closing w:ins - an inserted paragraph mark - spans no text, and
    # Word hands back None rather than an empty string.
    doc = make_doc((250, "x"))
    doc.Revisions = [FakeRevision(doc, 10, 250, None)]
    (rev,) = revision_locations(doc)
    assert rev.text == ""
    assert rev.kind == "paragraph-property"


def test_an_unknown_revision_type_is_reported_not_dropped():
    doc = make_doc((250, "x"))
    doc.Revisions = [FakeRevision(doc, 99, 250, "x")]
    (rev,) = revision_locations(doc)
    assert rev.kind == "type-99"


def test_revisions_can_be_limited():
    doc = make_doc((250, "a"), (350, "b"), (450, "c"))
    doc.Revisions = [FakeRevision(doc, 1, at, t)
                     for at, t in ((250, "a"), (350, "b"), (450, "c"))]
    assert len(revision_locations(doc, limit=2)) == 2


def test_a_limit_below_one_returns_nothing():
    doc = make_doc((250, "a"))
    doc.Revisions = [FakeRevision(doc, 1, 250, "a")]
    assert revision_locations(doc, limit=0) == []
