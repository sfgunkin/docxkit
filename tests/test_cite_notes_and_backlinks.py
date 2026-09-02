r"""Two blind spots in one gate, both live in one manuscript.

Measured on Aging_Well, 31 August and 1 September. Each left
`citations` exiting 0 with a clean-looking count while the convention it
exists to protect was broken.

**A mention in a footnote was not counted.** A round added "(World Bank
2026)" to footnote 2 as plain text and the audit printed `Mentions: 103
of 103 linked` — before the link was made and after. The counter read
the body alone, so the mention was never in the denominator and its
being unlinked could not be reported. `_read_notes` had folded the
notes' bookmarks and links in since 2026-08-20; the mention scan was the
one place still stopping at `document.xml`. Six of that paper's works
are cited only in footnotes.

**An entry with no link home was not reported.** One entry of 87 lost
its `Lokshin2022txt` bookmark. The back-link was then broken — which
this file's BROKEN LINK check would have said — and the paper's repair
removed the dead link instead, leaving an entry pointing nowhere, which
nothing could see. It is self-perpetuating: `link_all` skips a mention
that already carries a forward link, so the marker is never re-minted.
The same warning printed at three consecutive close-outs.
"""
from __future__ import annotations

from conftest import make_parts, notes, para, run

from docxkit._cite_audit import audit_links

ENTRIES = [
    ("Halliday2020", "Halliday, S. (2020). A paper. Journal, 1(1), 1-10."),
    ("Mitra2019", "Mitra, S. (2019). Another paper. Review, 2(2), 11-20."),
    ("Sen1985", "Sen, A. (1985). Commodities and Capabilities. NH."),
    ("Rowe1987", "Rowe, J. (1987). Human aging. Science, 3(3), 21-30."),
]


def _entry(key: str, text: str, *, home: bool = True) -> str:
    """A reference entry: its own bookmark, and a link back to the
    mention that owns it."""
    head, tail = text.split(" ", 1)
    home_link = (f'<w:hyperlink w:anchor="{key}txt">{run(head)}</w:hyperlink>'
                 if home else run(head))
    return para(f'<w:bookmarkStart w:id="{abs(hash(key)) % 900}" '
                f'w:name="{key}"/>', home_link, run(" " + tail),
                f'<w:bookmarkEnd w:id="{abs(hash(key)) % 900}"/>')


def _mention(key: str, text: str, *, linked: bool = True) -> str:
    if not linked:
        return para(run(f"As {text} shows, the point holds."))
    return para(run("As "),
                f'<w:bookmarkStart w:id="{abs(hash(key)) % 800}" '
                f'w:name="{key}txt"/>'
                f'<w:hyperlink w:anchor="{key}">{run(text)}</w:hyperlink>'
                f'<w:bookmarkEnd w:id="{abs(hash(key)) % 800}"/>',
                run(" shows, the point holds."))


def _paper(*, note: str = "", home_for_all: bool = True,
           body_mentions: bool = True) -> dict[str, bytes]:
    """A small manuscript with four works, all linked both ways."""
    body = "".join(para(run(f"Filler paragraph {i}.")) for i in range(5))
    for key, text in ENTRIES:
        cite = f"{text.split(',')[0]} ({key[-4:]})"
        body += _mention(key, cite, linked=body_mentions)
    body += para(run("References"))
    for i, (key, text) in enumerate(ENTRIES):
        body += _entry(key, text, home=home_for_all or i > 0)

    parts = make_parts(body)
    if note:
        parts["word/footnotes.xml"] = notes(
            "footnotes",
            f'<w:footnote w:id="2">{para(run(note))}</w:footnote>'
        ).encode("utf-8")
    return parts


# ------------------------------------------------ a mention in a NOTE


def test_a_mention_in_a_FOOTNOTE_is_counted():
    """`Mentions: 103 of 103 linked` printed the same before and after
    the link was made, because the note's mention was never in the
    denominator."""
    without = audit_links(_paper())[1]
    with_note = audit_links(_paper(note="See Sen (1985) for the argument."))[1]

    assert with_note["mentions"] == without["mentions"] + 1, (
        "the footnote's mention is not in the count")


def test_an_UNLINKED_mention_in_a_footnote_is_reported():
    """`later_mentions=True`, because this work IS linked in the body and
    whether later mentions link is the paper's house style. What the
    entry is about is that the note's mention reaches the check at all —
    before this it was not in the denominator, so no setting could have
    reported it."""
    issues, _ = audit_links(
        _paper(note="A later claim Halliday (2020) needs support."),
        later_mentions=True)

    said = [i for i in issues if "LATER-MENTION" in i and "Halliday" in i]
    assert said, issues
    assert "fn" in said[0], "and it says WHICH part to look in"


def test_a_note_mention_does_not_report_as_a_body_paragraph():
    """"¶2" sends a reader to the body. The note sentinel is what
    `where()` already had for links and bookmarks."""
    issues, _ = audit_links(
        _paper(note="A later claim Halliday (2020) needs support."),
        later_mentions=True)

    said = [i for i in issues if "Halliday" in i]
    assert said and "¶" not in said[0], said


# --------------------------------------------- an entry with no home


def test_an_entry_that_links_nowhere_is_reported_when_the_others_do():
    issues, _ = audit_links(_paper(home_for_all=False))

    said = [i for i in issues if "REF WITHOUT BACKLINK" in i]
    assert said, issues
    assert "Halliday2020" in said[0] and "Halliday2020txt" in said[0]


def test_a_list_where_NO_entry_links_home_is_a_convention_not_a_fault():
    """Whether entries link home at all is the paper's house style. A
    rule would report every entry of such a paper; the list's own
    majority reports the one that differs from the rest."""
    parts = _paper()
    xml = parts["word/document.xml"].decode("utf-8")
    for key, _ in ENTRIES:                    # strip every back-link
        xml = xml.replace(f'<w:hyperlink w:anchor="{key}txt">', "").replace(
            "</w:hyperlink>", "", 1)
    parts["word/document.xml"] = xml.encode("utf-8")

    issues, _ = audit_links(parts)

    assert not [i for i in issues if "REF WITHOUT BACKLINK" in i], issues


def test_an_entry_nobody_cites_is_not_also_reported_for_its_backlink():
    """It is already REF WITHOUT CITE, and that is the half a reader can
    act on. Saying it twice is the noise this file's own comments warn
    about."""
    issues, _ = audit_links(_paper(body_mentions=False))

    kinds = {i.split(":")[0] for i in issues}
    assert "REF WITHOUT BACKLINK" not in kinds, issues


def test_a_healthy_manuscript_reports_neither():
    issues, stats = audit_links(_paper(note="See Sen (1985) again."))

    assert not [i for i in issues if "REF WITHOUT BACKLINK" in i], issues
    assert stats["mentions"] == stats["mentions_linked"] + \
        stats["later_unlinked"] + stats["unlinked"]
