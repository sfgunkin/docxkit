"""Recognising the anchors an earlier round wrote, and tearing out old ones.

`_own_bookmark` decides whether a bookmark already on an entry IS that
entry's, `_entry_names_from_document` reads the names back for the
second pass, and `unlink_by_anchor` removes a legacy scheme wholesale.
All three answer the same kind of question — is this marker mine? — and
all three were asserted only where the answer was yes.

The failures behind them are in their docstrings and none was loud. A
name not recognised is minted again, so a second run silently doubles
the scheme; a name recognised too eagerly points every link at another
work; a hoisted bookmark not found makes `link_rest` decline nine
mentions across six works, which the author noticed before any tool
did.
"""
from __future__ import annotations

from conftest import make_parts, para, run

from docxkit._xml import BOOKMARK_NAME_RE, internal_links
from docxkit.citations import link_all, link_rest, unlink_by_anchor

ENTRY = "Kanbur, R. (2007). Poverty and distribution. Journal."


def _names(parts: dict[str, bytes]) -> list[str]:
    return BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8"))


def _anchors(parts: dict[str, bytes]) -> list[str]:
    return [a for a, _ in internal_links(
        parts["word/document.xml"].decode("utf-8"))]


def _marked(name: str, text: str, bid: int = 9) -> str:
    """An entry paragraph already carrying a bookmark."""
    return (f'<w:p><w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
            + run(text) + f'<w:bookmarkEnd w:id="{bid}"/></w:p>')


# ------------------------------------------- is this bookmark mine? ------

def test_running_link_all_TWICE_changes_nothing():
    """Idempotence is the property `_own_bookmark` exists for. Fail to
    recognise the name written last round and the pass mints a second
    one — `Kanbur2007_2` beside `Kanbur2007`, both marking the same
    entry, and every link written afterwards pointing at whichever Word
    finds first.
    """
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References")) + para(run(ENTRY)))
    link_all(parts)
    once = parts["word/document.xml"]

    report = link_all(parts)

    assert parts["word/document.xml"] == once, report.format()
    assert not report.backlinked, report.format()
    assert sorted(_names(parts)) == ["Kanbur2007", "Kanbur2007txt"]


def test_a_bookmark_from_ANOTHER_YEAR_is_not_taken_as_this_entry_s():
    """Both the surname and the year have to match. A stray `Kanbur2005`
    left on the paragraph by an earlier scheme is a different work, and
    reusing it points every "(Kanbur 2007)" at that one instead —
    reported as a success while it happens.
    """
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References")) + _marked("Kanbur2005", ENTRY))

    link_all(parts)

    assert "Kanbur2007" in _anchors(parts), _anchors(parts)
    assert "Kanbur2005" not in _anchors(parts), "the stray anchor was reused"


def test_a_TXT_bookmark_on_the_entry_is_not_taken_as_the_entry_s_own():
    """`Kanbur2007txt` is the IN-TEXT end of the pair. Reusing it as the
    entry's own name collapses the two ends into one, and the back-link
    then points at itself."""
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References")) + _marked("Kanbur2007txt", ENTRY))

    link_all(parts)

    entry_anchors = [a for a in _anchors(parts) if not a.endswith("txt")]
    assert entry_anchors and all(a != "Kanbur2007txt" for a in entry_anchors)


def test_a_NON_matching_bookmark_first_does_not_stop_the_scan():
    """Word leaves several markers on a paragraph — a heading anchor, a
    comment range, the entry's own. The scan reads them all, so the
    entry's own is found wherever in the list it sits.
    """
    marked = ('<w:p><w:bookmarkStart w:id="8" w:name="_Toc12345"/>'
              '<w:bookmarkStart w:id="9" w:name="Kanbur2007"/>'
              + run(ENTRY)
              + '<w:bookmarkEnd w:id="9"/><w:bookmarkEnd w:id="8"/></w:p>')
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("References")) + marked)

    link_all(parts)

    assert "Kanbur2007" in _anchors(parts), _anchors(parts)
    assert "Kanbur2007_2" not in _names(parts), "the entry was renamed"


# ------------------------------ the bookmark Word HOISTED out of the entry --

def test_a_bookmark_hoisted_ABOVE_the_entry_is_still_the_entry_s_name():
    """Parental Style, 2026-08-11. Word moves a collapsed bookmark out
    of the paragraph it marks on save, so a settled manuscript keeps
    `…</w:p><w:bookmarkStart/><w:bookmarkEnd/><w:p …>`. Reading the
    paragraph alone found nothing, and `link_rest` then declined every
    later mention of those works with "entry has no bookmark" — nine
    mentions across six works, quietly.
    """
    hoisted = ('<w:bookmarkStart w:id="9" w:name="Kanbur2007"/>'
               '<w:bookmarkEnd w:id="9"/>' + para(run(ENTRY)))
    parts = make_parts(
        para(run("First (Kanbur 2007) here."))
        + para(run("A sentence between."))
        + para(run("Again (Kanbur 2007) there."))
        + para(run("References")) + hoisted)

    report = link_rest(parts)

    assert not any("no bookmark" in note for note in report.skipped), \
        report.format()
    assert report.linked, report.format()


def test_the_gap_read_for_an_entry_is_ITS_OWN_and_not_the_one_before():
    """The window is the gap between the previous paragraph and this
    one. Widening it by a paragraph reaches into the previous entry's
    gap, and a stale marker left there by an earlier scheme is then
    read as this entry's name — which points every later mention at a
    bookmark that is not on the entry at all.
    """
    from docxkit._cite_build import _entry_names_from_document
    from docxkit._xml import PARA_RE, visible_text
    from docxkit.citations import references

    stale = ('<w:bookmarkStart w:id="7" w:name="Kanbur2007"/>'
             '<w:bookmarkEnd w:id="7"/>')
    own = ('<w:bookmarkStart w:id="9" w:name="Kanbur2007_2"/>'
           '<w:bookmarkEnd w:id="9"/>')
    parts = make_parts(
        para(run("First (Kanbur 2007) here."))
        + para(run("A sentence between."))
        + para(run("Another sentence."))
        + stale
        + para(run("References"))
        + own + para(run(ENTRY)))
    doc = parts["word/document.xml"].decode("utf-8")
    paras = list(PARA_RE.finditer(doc))
    entries = references([visible_text(m.group(0)) for m in paras],
                         heading=("References",))

    names = _entry_names_from_document(doc, entries, paras)

    assert names == {"kanbur_2007": "Kanbur2007_2"}, names


# ------------------------------------------- tearing out a legacy scheme --

def _field_link(anchor: str, label: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l '
            f'"{anchor}" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            f"<w:t>{label}</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def test_only_the_MATCHING_field_link_is_unwrapped():
    """The non-matching one comes FIRST, so a scan that stopped at it
    would leave the legacy link in place — and a legacy link on an entry
    silently vetoes `link_all`'s back-link."""
    xml = ("<w:p>" + _field_link("Table3txt", "Table 3")
           + run(" and ") + _field_link("id.abc123", "Kanbur (2007)")
           + "</w:p>")

    out, links, marks = unlink_by_anchor(xml, r"^id\.")

    assert (links, marks) == (1, 0)
    assert "Table3txt" in out, "the clean scheme's link was unwrapped too"
    assert "id.abc123" not in out
    assert "<w:t>Kanbur (2007)</w:t>" in out, "the words went with it"


def test_TWO_matching_field_links_are_both_unwrapped():
    xml = ("<w:p>" + _field_link("id.aaa", "First")
           + run(" and ") + _field_link("id.bbb", "Second") + "</w:p>")

    out, links, _ = unlink_by_anchor(xml, r"^id\.")

    assert links == 2
    assert "fldChar" not in out and "instrText" not in out


def test_a_NON_matching_ghost_link_is_left_exactly_as_it_was():
    """A self-closing `<w:hyperlink/>` is pure junk and gets dropped
    when its anchor matches — but one that does not match has to come
    back UNTOUCHED, element and all. Returning the anchor instead of the
    element replaces markup with a bare word, which reads as prose and
    is invisible to a text diff of the paragraph's visible text.
    """
    xml = ('<w:p><w:hyperlink w:anchor="Table3txt"/>'
           + run("Table 3 sets it out.") + "</w:p>")

    out, links, marks = unlink_by_anchor(xml, r"^id\.")

    assert (links, marks) == (0, 0)
    assert out == xml


def test_a_MATCHING_ghost_link_is_dropped():
    xml = ('<w:p><w:hyperlink w:anchor="id.abc123"/>'
           + run("Table 3 sets it out.") + "</w:p>")

    out, links, _ = unlink_by_anchor(xml, r"^id\.")

    assert links == 1
    assert "<w:hyperlink" not in out
    assert "<w:t>Table 3 sets it out.</w:t>" in out


def test_only_the_MATCHING_bookmarks_are_dropped_and_BOTH_their_ends():
    """A bookmark is a pair, and leaving the end behind is what makes a
    document unopenable. The non-matching pair comes first, so a scan
    that stopped at it would drop nothing at all.
    """
    xml = ('<w:p><w:bookmarkStart w:id="1" w:name="_Toc999"/>'
           '<w:bookmarkStart w:id="2" w:name="id.abc123"/>'
           + run("Kanbur, R. (2007).")
           + '<w:bookmarkEnd w:id="2"/><w:bookmarkEnd w:id="1"/></w:p>')

    out, _, marks = unlink_by_anchor(xml, r"^id\.")

    assert marks == 1
    assert 'w:name="id.abc123"' not in out
    assert 'w:id="2"' not in out, "the bookmarkEnd was left behind"
    assert 'w:name="_Toc999"' in out and 'w:bookmarkEnd w:id="1"' in out


# `if s < 0 or e < 0 or s < pos:` in the field walk is marked
# `# pragma: no cover - defensive` in the source and its three mutants
# are permanent residue by that decision, not by oversight: reaching it
# needs a field whose opening run cannot be found or whose spans
# overlap, which the regex that produced them cannot emit.
#
# Two more are EQUIVALENT and left alive:
#
# * `INSTR_RE.findall(m.group(1))` -> `m.group(0)`. Group 0 is group 1
#   with the two `fldChar` markers around it, and neither holds an
#   `instrText` — so the same instructions come back either way;
# * `xml.replace(bm.group(0), "", 1)` -> `..., 2)`. The text being
#   replaced carries the bookmark's own `w:id`, so it occurs once and a
#   larger count has nothing to find.


def test_a_TRUNCATED_bookmark_is_still_the_entry_s_own():
    """`km.group(1)`, the ALPHA part of a key-shaped name, against the
    whole name. An institution's entry mints a truncated marker —
    `_NAME_BUDGET` is 37 characters and "Agency on Statistics under the
    President of the Republic" is not — so the name a later run finds on
    such an entry is a PREFIX of its surname rather than the whole of
    it, which is what the prefix-either-way test above it is for.

    Compared whole, "kanb2007" neither starts with "kanbur" nor is
    started by it: the entry reads as unmarked and the run mints a
    second bookmark beside the first. Two markers on one entry, and
    every link written in an earlier round points at whichever one Word
    finds first."""
    parts = make_parts(para(run("Poverty fell (Kanbur 2007)."))
                       + para(run("References"))
                       + _marked("Kanb2007", ENTRY))

    report = link_all(parts)

    assert set(_names(parts)) == {"Kanb2007", "Kanb2007txt"}, _names(parts)
    assert report.linked == ["Kanb2007 @ ¶1"], report.linked
