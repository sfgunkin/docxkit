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
    _REVISION_KINDS,
    WD_FIND_STOP,
    WD_INFO_ADJUSTED_PAGE,
    WD_INFO_LINE,
    WD_INFO_PAGE,
    Location,
    _Layout,
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
        self.cleared = 0

    def ClearFormatting(self) -> None:
        self.cleared += 1

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
        self._find: FakeFind | None = None

    @property
    def Find(self) -> FakeFind:
        # ONE per range, the way Word's is: the code configures it once
        # and re-aims the range, so a fresh object on every access would
        # hide a setting that never reached the search
        if self._find is None:
            self._find = FakeFind(self)
        return self._find

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
    # `break` there rather than `continue` is argued equivalent, not
    # tested (`tools/kill_check.py`, expect_kill=False): the budget only
    # ever goes down, so once one piece has overrun it no later piece
    # can fit either, and skipping the rest one at a time builds the
    # same string.


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


# --- how the search itself is set up ----------------------------------

def test_the_find_is_configured_before_it_is_ever_used():
    """Nine settings on Word's Find, and not one of them had a witness.

    They are not preferences. Word's Find object carries whatever the
    last search left on it, and every one of these turns off a way of
    matching that would answer with the WRONG place rather than with
    nothing:

    * `Wrap = wdFindStop` — with wrapping on, a forward search that
      finds nothing ahead restarts at the top and reports a hit
      BEHIND the cursor, which is exactly what `ordered=True` exists to
      prevent;
    * `MatchCase = True` — an anchor is quoted text, and "the Table"
      and "the table" are two different sentences in a paper;
    * `MatchWildcards = False` — `search_text` escapes `^` for Word's
      literal syntax, which is the wrong escaping under wildcards;
    * `MatchSoundsLike` and `MatchAllWordForms` — a fuzzy match lands on
      a place that only sounds like the one asked for;
    * `MatchWholeWord = False` — an anchor is a phrase and may start
      mid-word;
    * `Format = False` — formatting criteria left over from an earlier
      search would filter this one silently.
    """
    layout = _Layout(make_doc((250, "alpha")))

    find = layout._find
    assert find.Forward is True
    assert find.Wrap == WD_FIND_STOP
    assert find.Format is False
    assert find.MatchCase is True
    assert find.MatchWholeWord is False
    assert find.MatchWildcards is False
    assert find.MatchSoundsLike is False
    assert find.MatchAllWordForms is False
    assert find.cleared == 1, "and the leftovers are cleared first"


def test_a_search_that_starts_AT_the_end_asks_Word_nothing():
    """`start >= self.end`, decided by VALUE. The uniqueness check
    searches on from the end of the hit, so an anchor that ends the
    document hands it exactly `self.end` — and the two are ints computed
    apart, one from `len()` through `Content.End` and one from the
    Range the Find rewrote, so past 256 they are two objects and
    identity says the guard does not apply. Word is then asked to Find
    inside a range collapsed at the end of the document: a COM round
    trip per anchor to be told what the guard already knew."""
    doc = FakeDoc("." * 300 + "alpha")

    (loc,) = locate_in(doc, ["alpha"])

    assert loc.repeats is False
    assert doc.finds == 1, "the second Find was never worth attempting"


@pytest.mark.parametrize("count,cut", [(2, False), (6, True)])
def test_the_missing_ANCHORS_say_there_are_more_only_when_there_are(count,
                                                                    cut):
    """`len(missing) > 5`: five are named and the trailing " ..." says
    the list was cut short. `!= 5` prints it for two missing anchors as
    well — a refusal that sends the author looking for anchors it has
    already shown them in full."""
    doc = make_doc((250, "alpha"))
    anchors = [f"missing {i}" for i in range(count)]

    with pytest.raises(AnchorError) as refused:
        locate_in(doc, anchors)

    assert ("..." in str(refused.value)) is cut, str(refused.value)


def test_the_layout_measures_the_document_it_was_given():
    """`self.end = int(doc.Content.End)` is the bound every forward
    search is capped by; read from anywhere else it either cuts the
    document short or runs past it."""
    doc = make_doc((250, "alpha"))

    layout = _Layout(doc)

    assert layout.end == len(doc.text)
    assert doc.repaginated, "and the layout is real before anything is asked"
    # The two `doc.Range(0, 0)` calls beside it are NOT pinned, and are
    # argued equivalent instead: both objects are re-aimed with SetRange
    # before anything reads them — the search range on every find, the
    # probe on every page question — so the offsets they are born with
    # cannot reach an answer.
    #
    # THAT PREMISE IS PINNED BY THIS TEST, which is what makes the
    # argument safe to leave standing. Measured with
    # `tools/can_it_fail.py` on 2026-09-18: replacing either
    # `SetRange` in `word._Layout` with `pass` turns this test red. An
    # edit that stopped re-aiming would therefore be caught here rather
    # than turning six parked survivors into six real ones in silence.


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


@pytest.mark.parametrize("page,doc_page,shown", [
    (7, 7, False),      # no front matter: the two agree
    # and again past 256, where `is` stops agreeing with `==`: small
    # ints are cached objects and large ones are not. The two are
    # written differently on purpose — one literal and one built at
    # run time, which is what a caller has, since both numbers reach
    # `Location` from separate `int()` calls on Word's answers
    (300, int("300"), False),
    (2, 3, True),       # one unnumbered page in front — the ordinary case
    (101, 3, True),     # a section that restarts at 101: printed > file
])
def test_the_file_page_is_shown_exactly_when_it_DIFFERS(page, doc_page,
                                                        shown):
    """`self.page == self.doc_page`, and the two can differ in EITHER
    direction. Front matter puts the printed number below the file
    number; a section that restarts numbering — an appendix at 101, a
    reprint keeping the journal's own pages — puts it above. An
    ordering test passes the common case and then either prints
    "(file page 7)" for a document that has no front matter, or drops
    the file page from the one place it is needed: telling an editor
    which page of the FILE to scroll to."""
    loc = Location(anchor="alpha", page=page, line=4,
                        doc_page=doc_page, repeats=False)

    assert str(loc).startswith(f"p. {page}, line 4")
    assert (f"file page {doc_page}" in str(loc)) is shown, str(loc)


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


def test_the_strict_failure_names_five_misses_and_says_there_are_more():
    """The message a run dies on, in full.

    It is the only thing the caller gets — a bulk locate over a
    manuscript's anchors ends here, and what it says is the whole
    diagnosis. Three numbers have to be right: how many were missed,
    how many were ASKED for (found plus missing, not either alone), and
    the five it quotes, each cut to 60 characters so the list stays
    readable when the anchors are sentences. Six missing is one past
    the cut, which is what the trailing ellipsis is for."""
    # no comma inside an anchor: the message joins with ", " and the
    # test reads the join back
    quoted = "Table 5 reports the coefficient on the interaction term "
    long_misses = [f"{quoted}{i} which is absent from the document."
                   for i in range(6)]
    for anchor in long_misses:
        assert len(anchor) > 60, "the cut has to have something to cut"
    doc = make_doc((250, "alpha"), (1040, "omega"), (2050, "psi"))

    with pytest.raises(AnchorError) as exc:
        locate_in(doc, [*long_misses, "alpha", "omega", "psi"])

    message = str(exc.value)
    assert message.startswith(
        "6 of 9 anchors not found in the laid-out document: ")
    assert message.endswith(" ...")
    quotes = message.split(": ", 1)[1].removesuffix(" ...").split(", ")
    assert len(quotes) == 5, quotes
    assert quotes[0] == repr(long_misses[0][:60])
    assert long_misses[4][:60] in quotes[4]
    assert long_misses[5][:60] not in message, "the sixth is the ellipsis"


def test_exactly_five_misses_are_all_shown_and_nothing_is_elided():
    """`> 5`, at the boundary: five is the whole list, and an ellipsis
    after it says a miss was withheld that was not — the reader goes
    looking for a sixth anchor that does not exist."""
    misses = [f"missing anchor number {i}" for i in range(5)]
    doc = make_doc((250, "alpha"))

    with pytest.raises(AnchorError) as exc:
        locate_in(doc, [*misses, "alpha"])

    message = str(exc.value)
    assert message.startswith("5 of 6 anchors not found")
    assert not message.endswith("...")
    for anchor in misses:
        assert repr(anchor) in message, message


def test_ordered_walks_forward_through_repeats():
    # Two revisions quoting the same phrase are two different places; a
    # from-the-top search would report the first one twice.
    doc = make_doc((250, "same phrase"), (1040, "same phrase"))
    first, second = locate_in(doc, ["same phrase", "same phrase"],
                              ordered=True)
    assert first.doc_page == 3
    assert second.doc_page == 11


def test_an_anchor_at_the_very_START_costs_one_search():
    """`cursor = 0`. The walk begins at the top of the document, so the
    first anchor is searched for from character zero. Starting it at 1
    steps over an anchor that begins the document — the title, the
    running head, the first words of the abstract — and the miss is
    invisible, because the from-the-top retry finds it on a second COM
    round trip and answers correctly at twice the cost."""
    doc = make_doc((0, "alpha"), (1040, "omega"))

    (loc,) = locate_in(doc, ["alpha"], ordered=True, unique=False)

    assert loc.doc_page == 1
    assert doc.finds == 1, "no retry was needed"


def test_the_from_the_top_retry_reads_from_the_VERY_top():
    """`layout.find(text, 0)` — the retry for an anchor that is not
    ahead of the cursor. From 1 it cannot see an anchor at the start of
    the document, and an ordered run that has already walked past it
    reports the anchor as missing: a response letter loses the line for
    the paper's own title."""
    doc = make_doc((0, "alpha"), (1040, "omega"))

    first, second = locate_in(doc, ["omega", "alpha"], ordered=True,
                              unique=False)

    assert (first.doc_page, second.doc_page) == (11, 1)


def test_a_cursor_AT_the_end_of_the_document_costs_no_search():
    """`start >= self.end`, and the cost is the only thing that shows
    it. An ordered walk whose last anchor ends at the last character
    leaves the cursor ON the end, and the next anchor's forward search
    has nowhere to look. Word is still asked, under `>`: a Find over an
    empty range, which answers no and costs a COM round trip — the
    thing this class exists to avoid, on the anchor that comes after
    every ordered run's last hit.

    `==` in place of `>=` cannot be told apart, and not for want of a
    test: `start` is either 0 or a hit's end offset, so it never
    exceeds `self.end` and the two agree on every reachable input."""
    doc = FakeDoc("." * 40 + "omega")

    found = locate_in(doc, ["omega", "omega"], ordered=True, unique=False)

    assert [loc.doc_page for loc in found] == [1, 1]
    # one Find for the first hit; for the second, the forward search is
    # refused outright and only the from-the-top retry reaches Word
    assert doc.finds == 2, "an empty range was searched"


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



# WdRevisionType, in Word's own order. The numbers are Word's and the
# labels are ours, so the pairing is the thing to check: `rev.Type`
# arrives as a bare integer and an off-by-one prints a tracked deletion
# as an insertion — a report that reads perfectly and says the opposite
# of what the redline does.
WD_REVISION_TYPES = [
    (1, "wdRevisionInsert", "insert"),
    (2, "wdRevisionDelete", "delete"),
    (3, "wdRevisionProperty", "property"),
    (4, "wdRevisionParagraphNumber", "paragraph-number"),
    (5, "wdRevisionDisplayField", "display-field"),
    (6, "wdRevisionReconcile", "reconcile"),
    (7, "wdRevisionConflict", "conflict"),
    (8, "wdRevisionStyle", "style"),
    (9, "wdRevisionReplace", "replace"),
    (10, "wdRevisionParagraphProperty", "paragraph-property"),
    (11, "wdRevisionTableProperty", "table-property"),
    (12, "wdRevisionSectionProperty", "section-property"),
    (13, "wdRevisionStyleDefinition", "style-definition"),
    (14, "wdRevisionMovedFrom", "move-from"),
    (15, "wdRevisionMovedTo", "move-to"),
    (16, "wdRevisionCellInsertion", "cell-insertion"),
    (17, "wdRevisionCellDeletion", "cell-deletion"),
    (18, "wdRevisionCellMerge", "cell-merge"),
    (19, "wdRevisionCellSplit", "cell-split"),
]


def test_each_revision_type_carries_the_name_word_gives_it():
    """The map is nineteen numbers nothing else checks. A wrong one is
    not an error anywhere: `rev.Type` is an integer, the lookup finds
    SOME label, and the report names a kind of change that did not
    happen."""
    assert {n: label
            for n, _, label in WD_REVISION_TYPES} == _REVISION_KINDS


def test_the_revision_types_are_a_run_with_no_holes():
    """1 to 19 with nothing missing. Two entries given the same number
    is the way this table breaks — the later one wins and the earlier
    number falls out entirely — and a dict comparison alone would have
    to be edited to match it. `wdNoRevision` is 0 and is deliberately
    absent: a range with no revision must not be labelled as one."""
    assert sorted(_REVISION_KINDS) == list(range(1, 20))
    assert 0 not in _REVISION_KINDS


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


def test_a_limit_of_ONE_returns_one_revision():
    """`limit < 1`, not `<= 1`. One is the limit a caller passes to ask
    "where does the redline start" — the cheapest question this
    function answers, and the one `<= 1` turns into an empty list that
    reads as a document with no revisions at all."""
    doc = make_doc((250, "a"), (350, "b"))
    doc.Revisions = [FakeRevision(doc, 1, at, t)
                     for at, t in ((250, "a"), (350, "b"))]

    (only,) = revision_locations(doc, limit=1)

    assert (only.number, only.text) == (1, "a")


def test_a_limit_below_one_returns_nothing():
    doc = make_doc((250, "a"))
    doc.Revisions = [FakeRevision(doc, 1, 250, "a")]
    assert revision_locations(doc, limit=0) == []


def test_an_anchor_that_occurs_ONCE_does_not_report_a_repeat():
    """The repeat search starts at the END of the hit — from its start
    it finds the same occurrence again and every anchor in the document
    comes back flagged. `repeats` is what tells a person their anchor is
    ambiguous, and one that is always true tells them nothing.

    The repeated case is pinned above; this is the other side, and the
    `unique=False` test cannot stand in for it because the `and` never
    reaches the search."""
    doc = make_doc((250, "alpha"))

    (loc,) = locate_in(doc, ["alpha"])

    assert loc.repeats is False


def test_a_limit_ABOVE_256_still_stops_the_walk():
    """`number == limit`, read as `is`. Small ints are cached and equal
    ones are the same object up to 256, so every fixture under that
    passes either way — and this module's own docstring measures a
    701-revision redline at ~62 seconds, which is the reason a caller
    passes a limit at all."""
    doc = FakeDoc("." * 4000)
    doc.Revisions = [FakeRevision(doc, 1, i * 4, "x") for i in range(400)]

    assert len(revision_locations(doc, limit=300)) == 300


# --- what the run of 2026-08-20 left in `word`, and why -----------------
#
# Thirteen real survivors, three of them the tests above. The other ten
# are equivalent by construction, each checked with `kill_check`:
#
# * `flat_opc_to_docx`'s `children[0]` as `children[-1]`. The line above
#   raises unless there is exactly one child.
# * the ruler's `head.Information(LINE) != tail.Information(LINE)` as
#   `<`. `head` sits at the paragraph's start and `tail` one character
#   before its end, so the second line number is the first or a later
#   one — the two spellings can only differ for a tail ABOVE its own
#   head.
# * `search_text`'s `ch == "^"` as `is`: a one-character string is
#   interned.
# * `search_text`'s `break` when the budget runs out, as `continue`.
#   The budget only ever decreases, so once it is negative every later
#   character is skipped too — the loop ends up appending exactly what
#   the break left it with.
# * the six on `doc.Range(0, 0)` in `_Layout.__init__`, for both the
#   search range and the probe. Neither extent is ever READ: `find`
#   calls `SetRange(start, self.end)` before every Execute and `at`
#   calls `SetRange(pos, pos)` before every Information. (Real Word
#   would reject a negative offset outright. The fake here does not,
#   which is why these survive rather than dying on the spot — and the
#   fake is the point: what is being pinned is our logic, not Word's.)
