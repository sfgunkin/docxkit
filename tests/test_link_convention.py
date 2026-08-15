"""`link_all` under the PAPER's naming convention, and scoped to a repair.

The names this builder mints are its own — `UnitedNations2024`,
`Schunemann2017_2` — and LI7 wires all 79 of its existing pairs as
`Kanbur2007` / `Kanbur2007txt`. With no way to say so, its six new
citations were hand-wired from the field-form pattern read off an
existing pair (2026-08-15). And with no way to scope the pass, the dry
run offered to touch far more than the six: the same builder took that
paper's audit from 26 findings to 56 the one time it ran document-wide.
"""
from __future__ import annotations

from conftest import make_parts, para, run

from docxkit.citations import link_all


def SURNAME_YEAR(surname: str, year: str) -> str:
    """LI7's convention, used by all 79 of its wired pairs."""
    return f"{surname}{year}"


def _paper() -> dict[str, bytes]:
    body = (
        para(run("Loneliness rises with age (Kanbur 2007), and the "
                 "gradient steepens (Ravallion 2016).")),
        para(run("References")),
        para(run("Kanbur, R. (2007). Poverty and distribution. "
                 "Journal of Development Economics.")),
        para(run("Ravallion, M. (2016). The Economics of Poverty. "
                 "Oxford University Press.")),
    )
    return make_parts("".join(body))


def _bookmarks(parts: dict[str, bytes]) -> set[str]:
    from docxkit._xml import BOOKMARK_NAME_RE
    return set(BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8")))


def test_the_papers_convention_names_the_bookmarks():
    parts = _paper()
    report = link_all(parts, naming=SURNAME_YEAR)

    assert report.linked, report.format()
    names = _bookmarks(parts)
    assert "Kanbur2007" in names and "Kanbur2007txt" in names
    assert "Ravallion2016" in names


def test_without_a_convention_the_minted_names_are_unchanged():
    """The default is not a behaviour change: a paper that never states
    a convention gets exactly what it got before."""
    parts = _paper()
    link_all(parts)
    assert "Kanbur2007" in _bookmarks(parts)     # this one coincides
    parts2 = _paper()
    link_all(parts2, naming=SURNAME_YEAR)
    assert _bookmarks(parts) == _bookmarks(parts2)


def test_a_convention_name_over_words_CAP_falls_back_and_says_so():
    """Word truncates a bookmark ON SAVE and does not retarget the links
    that pointed at the full name — every anchor silently orphaned."""
    parts = _paper()
    report = link_all(parts, naming=lambda s, y: f"{s}_{'x' * 60}_{y}")

    assert any("cap" in note for note in report.skipped), report.skipped
    assert not any(len(n) > 40 for n in _bookmarks(parts))


def test_only_scopes_the_pass_to_the_works_named():
    parts = _paper()
    report = link_all(parts, naming=SURNAME_YEAR, only=["Kanbur"])

    names = _bookmarks(parts)
    assert "Kanbur2007" in names
    assert not any(n.startswith("Ravallion") for n in names), \
        "a work nobody asked for was wired"
    assert all("Ravallion" not in entry for entry in report.linked)


def test_only_accepts_a_key_or_a_bookmark_name_too():
    for token in ("kanbur_2007", "Kanbur2007", "kanbur"):
        parts = _paper()
        link_all(parts, naming=SURNAME_YEAR, only=[token])
        assert "Kanbur2007" in _bookmarks(parts), token


def test_only_still_reads_the_whole_reference_BLOCK():
    """`only` decides what is written, not what is understood: the block
    bounds are what tell an entry from a sentence, and narrowing them
    would set the builder loose inside the reference list."""
    parts = _paper()
    link_all(parts, naming=SURNAME_YEAR, only=["Kanbur"])
    doc = parts["word/document.xml"].decode("utf-8")
    tail = doc[doc.index("Ravallion, M. (2016)"):]
    assert "<w:hyperlink" not in tail, \
        "the reference entry itself was linked as if it were prose"
