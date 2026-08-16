r"""Citations and their bidirectional links — the public face.

The convention these papers use: the reference entry carries a bookmark
named for the work (``Halliday2020``) and the first in-text mention
carries the same name plus ``txt``, each hyperlinking to the other. So a
reader clicks a citation to reach the entry, and the entry to get back
to where it was discussed.

This module is the API. The work is layered beneath it, bottom-up, and
each layer imports only from the ones below:

===================  =====================================================
:mod:`_cite_grammar`  what a citation and a reference LOOK like
:mod:`_cite_repair`   bookmark and hyperlink surgery
:mod:`_cite_audit`    what is wrong with a document (reports, never fixes)
:mod:`_cite_build`    link_all / link_rest / unlink_by_anchor
===================  =====================================================

Everything those layers export is re-exported here, so
``from docxkit.citations import ...`` keeps working for every name it
ever offered — the papers' build scripts import from this path on every
run, and a split that moved a name would be a split that broke a build.
"""
from __future__ import annotations

from pathlib import Path

# re-exported from _cite_audit: `as` form marks it deliberate
from ._cite_audit import _BOOKMARK_NAME_RE as _BOOKMARK_NAME_RE
from ._cite_audit import _KEY_SHAPE_RE as _KEY_SHAPE_RE
from ._cite_audit import _LINK_TOKEN_RE as _LINK_TOKEN_RE
from ._cite_audit import _audit_findings as _audit_findings
from ._cite_audit import _doubled_links as _doubled_links
from ._cite_audit import _Finding as _Finding
from ._cite_audit import audit_links as audit_links
from ._cite_build import _ACRONYM_RE as _ACRONYM_RE

# re-exported from _cite_build: `as` form marks it deliberate
from ._cite_build import LinkAllReport as LinkAllReport
from ._cite_build import LinkRestReport as LinkRestReport
from ._cite_build import _dedup_name as _dedup_name
from ._cite_build import _entry_keys as _entry_keys
from ._cite_build import (
    _entry_names_from_document as _entry_names_from_document,
)
from ._cite_build import _own_bookmark as _own_bookmark
from ._cite_build import _own_bookmarks as _own_bookmarks
from ._cite_build import link_all as link_all
from ._cite_build import link_rest as link_rest
from ._cite_build import unlink_by_anchor as unlink_by_anchor
from ._cite_grammar import _AUTHORS as _AUTHORS
from ._cite_grammar import _CAPTION_START_RE as _CAPTION_START_RE
from ._cite_grammar import _CONTINUATION_RE as _CONTINUATION_RE
from ._cite_grammar import _DEFAULT_HEADINGS as _DEFAULT_HEADINGS
from ._cite_grammar import _DEFAULT_STOPS as _DEFAULT_STOPS
from ._cite_grammar import _LEAD as _LEAD
from ._cite_grammar import _LEAD_ADVERB_RE as _LEAD_ADVERB_RE
from ._cite_grammar import _NAME as _NAME
from ._cite_grammar import _NAME_CHAR as _NAME_CHAR
from ._cite_grammar import _NARRATIVE_RE as _NARRATIVE_RE
from ._cite_grammar import _PAREN_RE as _PAREN_RE
from ._cite_grammar import _PARTICLE as _PARTICLE
from ._cite_grammar import _PREFIX as _PREFIX
from ._cite_grammar import _REF_YEAR_RE as _REF_YEAR_RE
from ._cite_grammar import _SEGMENT_RE as _SEGMENT_RE
from ._cite_grammar import _SURNAME as _SURNAME
from ._cite_grammar import _YEAR as _YEAR
from ._cite_grammar import _YEAR_HINT_RE as _YEAR_HINT_RE
from ._cite_grammar import _ZOTERO_RE as _ZOTERO_RE

# re-exported from _cite_grammar: `as` form marks it deliberate
from ._cite_grammar import AUTHORS_PATTERN as AUTHORS_PATTERN
from ._cite_grammar import DISCOURSE_LEADS as DISCOURSE_LEADS
from ._cite_grammar import IGNORED_LEADS as IGNORED_LEADS
from ._cite_grammar import REF_HEADINGS as REF_HEADINGS
from ._cite_grammar import REF_STOPS as REF_STOPS
from ._cite_grammar import YEAR_PATTERN as YEAR_PATTERN
from ._cite_grammar import Citation as Citation
from ._cite_grammar import Reference as Reference
from ._cite_grammar import _add_style as _add_style
from ._cite_grammar import _styled_run as _styled_run
from ._cite_grammar import anchor_names as anchor_names
from ._cite_grammar import bookmark as bookmark
from ._cite_grammar import extend_to_name as extend_to_name
from ._cite_grammar import find_citations as find_citations
from ._cite_grammar import hyperlink_field as hyperlink_field
from ._cite_grammar import key_for as key_for
from ._cite_grammar import lead_surname as lead_surname
from ._cite_grammar import link_in_para as link_in_para
from ._cite_grammar import masked_visible_text as masked_visible_text
from ._cite_grammar import parse_reference as parse_reference
from ._cite_grammar import reference_head as reference_head
from ._cite_grammar import references as references
from ._cite_grammar import resolve_lead as resolve_lead
from ._cite_grammar import strip_lead as strip_lead
from ._cite_grammar import wrap_visible_span as wrap_visible_span

# re-exported from _cite_repair: `as` form marks it deliberate
from ._cite_repair import _BOOKMARK_ID_RE as _BOOKMARK_ID_RE
from ._cite_repair import _mark_para_head as _mark_para_head
from ._cite_repair import delete_bookmark as delete_bookmark
from ._cite_repair import marker_bookmark as marker_bookmark
from ._cite_repair import next_bookmark_id as next_bookmark_id
from ._cite_repair import remove_outer_field as remove_outer_field
from ._cite_repair import wrap_link_in_bookmark as wrap_link_in_bookmark
from ._xml import DOCUMENT, FOOTNOTES, PARA_RE, internal_links, visible_text
from ._xml import run_open_before as run_open_before
from .package import read_parts

__all__ = [
    "AUTHORS_PATTERN",
    "IGNORED_LEADS",
    "REF_HEADINGS",
    "REF_STOPS",
    "YEAR_PATTERN",
    "Citation",
    "LinkRestReport",
    "Reference",
    "anchor_names",
    "audit_links",
    "bookmark",
    "check_citations",
    "delete_bookmark",
    "extend_to_name",
    "find_citations",
    "hyperlink_field",
    "key_for",
    "link_all",
    "link_in_para",
    "link_rest",
    "marker_bookmark",
    "masked_visible_text",
    "next_bookmark_id",
    "parse_reference",
    "references",
    "remove_outer_field",
    "repair_plan",
    "unlink_by_anchor",
    "wrap_link_in_bookmark",
    "wrap_visible_span",
]


# --------------------------------------------- the repair-plan writer ---

def repair_plan(parts: dict[str, bytes]) -> str:
    """Classify the audit's findings into PROPOSED repairs, for a human.

    The LE, API10 and LI7 rounds ran the same forensic loop three times;
    the damage classes repeat, so the classification is mechanical even
    though the REPAIR must never be: every proposal names the evidence
    and the helper call a per-paper script would make, and the header
    says what the three rounds proved — anchors get verified by a
    person, because two of three Lutz diagnoses were wrong before the
    right one.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    findings, _stats = _audit_findings(parts)
    bookmarks = set(_BOOKMARK_NAME_RE.findall(doc))
    foot = parts.get(FOOTNOTES, b"").decode("utf-8")
    bookmarks |= set(_BOOKMARK_NAME_RE.findall(foot))
    anchors = {a for a, _ in internal_links(doc)}
    anchors |= {a for a, _ in internal_links(foot)}
    paras = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in paras]
    cited_text = {c.key for t in texts for c in find_citations(t)}

    # Bookmarks a LIVE reference entry still owns. Nothing may be called
    # debris while its entry is in the list, and the citation key is the
    # wrong evidence for that: `BhlerNiederberger2022` was minted by an
    # older strip-only stem, while the citation "Bühler-Niederberger
    # (2022)" keys as `bühlerniederberger_2022` — the two never meet, so
    # a live reference was proposed for deletion (2026-08-09). Asking
    # the ENTRY is what the backlog entry demanded, and `_own_bookmark`
    # already knows both stems and reads the body-level gap Word hoists
    # a marker into.
    entries = references(texts)
    # the SET of names, not `_entry_names_from_document`'s mapping: two
    # entries under one key have two names and that dict keeps only one,
    # so the other would read as debris and be proposed for deletion
    live = {own for _, own in _own_bookmarks(doc, entries, paras)}

    buckets: dict[str, list[str]] = {
        "wrap": [], "relink": [], "debris": [], "moved": [], "nested": [],
        "investigate": []}
    for f in findings:
        issue, name = f.message, f.subject
        if f.kind == "BROKEN LINK":
            base = name.removesuffix("txt")
            if name.endswith("txt") and base in anchors:
                buckets["wrap"].append(
                    f'wrap_link_in_bookmark(doc, "{base}", "{name}", '
                    f"bid)   # {issue}")
            elif name.endswith("txt") and base in bookmarks:
                buckets["relink"].append(
                    f'link_in_para(para, CITE_TEXT, "{base}") + wrap '
                    f'"{name}"   # find the citation first; {issue}')
            else:
                buckets["investigate"].append(issue)
        elif f.kind == "STALE BOOKMARK":
            # No "VERIFY" hedge here: the audit checked the reference list and
            # the work is not in it. The other two kinds only guess at debris.
            buckets["debris"].append(
                f'delete_bookmark(doc, "{name}")   # {issue}')
        elif f.kind in ("ORPHAN REF", "REF WITHOUT CITE"):
            km = _KEY_SHAPE_RE.match(name)
            key = (key_for(km.group(1), km.group(2)) if km else "?")
            if km and key not in cited_text and name + "txt" not in \
                    bookmarks and name not in live:
                buckets["debris"].append(
                    f'delete_bookmark(doc, "{name}")   # VERIFY the entry '
                    f"text is truly gone; {issue}")
            elif name in live and f.kind == "REF WITHOUT CITE":
                buckets["relink"].append(
                    f'link_in_para(para, CITE_TEXT, "{name}")   # the ENTRY '
                    f"is still in the list, so this is a lost citation "
                    f"link, not debris; {issue}")
            elif f.kind == "ORPHAN REF":
                buckets["relink"].append(
                    f'link_in_para(para, CITE_TEXT, "{name}")   # first '
                    f"mention, then wrap {name}txt; {issue}")
        elif f.kind == "MISPLACED MARKER":
            buckets["moved"].append(
                f'delete_bookmark(doc, "{name}") then '
                f'marker_bookmark(doc, ENTRY_SIG, ...)   # {issue}')
        elif f.kind == "DOUBLED LINK":
            buckets["nested"].append(
                f'remove_outer_field(doc, "{f.extra}", "{name}")   '
                f"# VERIFY which target is the stale one first; {issue}")
        else:
            buckets["investigate"].append(issue)

    lines = [(f"REPAIR PLAN — {len(findings)} audit issue(s). Review EVERY "
              "anchor: the classification is mechanical, the repair is not."),
             ""]
    titles = {"wrap": "wrap the surviving link in its txt bookmark",
              "relink": "recreate the lost link (locate the citation)",
              "debris": "debris of a deleted entry — remove",
              "moved": "marker stranded by a paragraph move — re-place",
              "nested": "doubled link — untangle by hand",
              "investigate": "no mechanical reading — investigate"}
    for key, title in titles.items():
        if buckets[key]:
            lines.append(f"== {title} ({len(buckets[key])})")
            lines += [f"  {x}" for x in buckets[key]]
            lines.append("")
    if not findings:
        lines = ["nothing to repair — the audit is clean"]
    return "\n".join(lines).rstrip()


def check_citations(docx_path: str | Path) -> int:
    """Print the link audit for a manuscript; the count of issues found.

    The CLI entry (``docxkit citations``) and the drop-in replacement for
    the ported ``check_citation_links.py``: same contract (report to
    stdout, 0 issues means clean), same issue prefixes.
    """
    issues, stats = audit_links(read_parts(docx_path))
    print(f"Document: {docx_path}")
    print(f"Paragraphs: {stats['paragraphs']}")
    print(f"Bookmarks: {stats['bookmarks']} ({stats['cite_bookmarks']} "
          f"in-text, {stats['ref_bookmarks']} reference, "
          f"{stats['eq_bookmarks']} equation)")
    print(f"Hyperlinks: {stats['links']} total "
          f"({stats['broken']} broken, {stats['empty']} with no label, "
          f"{stats['unlinked']} unlinked citation-like mentions)")
    print("=" * 60)
    if not issues:
        print("ALL CHECKS PASSED — no issues found.")
    else:
        print(f"FOUND {len(issues)} ISSUE(S):\n")
        for issue in issues:
            print(f"  - {issue}")
    return len(issues)
