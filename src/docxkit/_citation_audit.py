#!/usr/bin/env python3
"""
check_citation_links.py — Verify citation cross-references in a generated .docx.

Checks:
1. Every in-text citation mention is hyperlinked to its reference bookmark
2. Every reference entry has a bookmark target for in-text links
3. Every reference has a back-link hyperlink to the in-text citation
4. No orphan bookmarks (bookmarks with no corresponding hyperlink)
5. No orphan hyperlinks (hyperlinks pointing to non-existent bookmarks)
6. Unlinked citation-like text that matches CITE_MAP but wasn't linked

Usage:
    python check_citation_links.py <docx_path>
"""

from __future__ import annotations

import io
import re
import sys
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _para_text(p_el):
    """Extract plain text from a paragraph element."""
    bits = []
    for node in p_el.iter():
        tag = etree.QName(node.tag).localname if isinstance(node.tag, str) else ""
        if tag == "t" and node.text:
            bits.append(node.text)
    return "".join(bits)


def check_citations(docx_path: str):
    doc = Document(docx_path)
    body = doc.element.body

    # Collect all bookmarks: name -> paragraph index
    bookmarks: dict[str, int] = {}
    # Collect all hyperlinks: anchor -> list of (para_index, display_text)
    hyperlinks: dict[str, list[tuple[int, str]]] = defaultdict(list)

    paras = list(body.findall(qn("w:p")))
    para_texts = []

    for i, p_el in enumerate(paras):
        para_texts.append(_para_text(p_el))

        # Find bookmarkStart elements
        for bm in p_el.iter(qn("w:bookmarkStart")):
            name = bm.get(qn("w:name"))
            if name and not name.startswith("_"):
                bookmarks[name] = i

        # Find hyperlink elements
        for hl in p_el.iter(qn("w:hyperlink")):
            anchor = hl.get(qn("w:anchor"))
            if anchor:
                # Get display text
                display = ""
                for t in hl.iter(qn("w:t")):
                    if t.text:
                        display += t.text
                hyperlinks[anchor].append((i, display))

    # Also discover bookmarks and hyperlinks inside table cells (e.g., display
    # equations, Table 2 source column) that body.findall("w:p") misses
    for bm in body.iter(qn("w:bookmarkStart")):
        name = bm.get(qn("w:name"))
        if name and not name.startswith("_") and name not in bookmarks:
            bookmarks[name] = -1  # no body-paragraph index for table-cell bookmarks
    for hl in body.iter(qn("w:hyperlink")):
        anchor = hl.get(qn("w:anchor"))
        if anchor:
            display = ""
            for t in hl.iter(qn("w:t")):
                if t.text:
                    display += t.text
            # Only add if not already captured from body-level paragraph scan
            existing = {d for _, d in hyperlinks.get(anchor, [])}
            if display not in existing:
                hyperlinks[anchor].append((-1, display))

    # Discover hyperlinks in footnotes
    for rel in doc.part.rels.values():
        if "footnotes" not in rel.reltype:
            continue
        ft_root = etree.fromstring(rel.target_part.blob)
        for hl in ft_root.iter(qn("w:hyperlink")):
            anchor = hl.get(qn("w:anchor"))
            if anchor:
                display = ""
                for t in hl.iter(qn("w:t")):
                    if t.text:
                        display += t.text
                hyperlinks[anchor].append((-1, display))

    # Categorize bookmarks
    cite_txt_bookmarks = {}  # key+"txt" bookmarks (in-text citation targets)
    ref_bookmarks = {}       # reference entry bookmarks (keys without "txt")
    eq_bookmarks = {}        # equation bookmarks

    for name, idx in bookmarks.items():
        if name.startswith("Eq"):
            eq_bookmarks[name] = idx
        elif name.endswith("txt"):
            cite_txt_bookmarks[name] = idx
        else:
            ref_bookmarks[name] = idx

    print(f"Document: {docx_path}")
    print(f"Paragraphs: {len(paras)}")
    print(f"Bookmarks: {len(bookmarks)} ({len(cite_txt_bookmarks)} in-text, "
          f"{len(ref_bookmarks)} reference, {len(eq_bookmarks)} equation)")
    print(f"Hyperlinks: {sum(len(v) for v in hyperlinks.values())} total")
    print()

    issues = []

    # --- Check 1: Every reference bookmark should have at least one
    #     in-text hyperlink pointing to it ---
    print("=== Reference bookmarks vs in-text hyperlinks ===")
    for key, idx in sorted(ref_bookmarks.items(), key=lambda x: x[1]):
        links_to_ref = hyperlinks.get(key, [])
        # Filter to only in-text links (not from reference section itself)
        # Reference section links point to "keytxt", not "key"
        if not links_to_ref:
            issues.append(f"ORPHAN REF: Bookmark '{key}' (¶{idx+1}) has no in-text hyperlink pointing to it")
    for key in ref_bookmarks:
        if key not in hyperlinks:
            pass  # already caught above
    print(f"  {len(ref_bookmarks)} reference bookmarks found")

    # --- Check 2: Every in-text citation bookmark should have a
    #     corresponding reference back-link ---
    print("\n=== In-text citation bookmarks vs reference back-links ===")
    for name, idx in sorted(cite_txt_bookmarks.items(), key=lambda x: x[1]):
        base_key = name[:-3]  # remove "txt" suffix
        back_links = hyperlinks.get(name, [])
        if not back_links:
            issues.append(f"NO BACK-LINK: In-text bookmark '{name}' (¶{idx+1}) "
                          f"has no reference back-link")
        if base_key not in ref_bookmarks:
            issues.append(f"MISSING REF: In-text citation '{name}' (¶{idx+1}) "
                          f"links to '{base_key}' but no reference bookmark exists")
    print(f"  {len(cite_txt_bookmarks)} in-text citation bookmarks found")

    # --- Check 3: Every hyperlink points to an existing bookmark ---
    print("\n=== Hyperlink targets vs bookmarks ===")
    orphan_links = 0
    for anchor, links in sorted(hyperlinks.items()):
        if anchor not in bookmarks:
            for para_idx, display in links:
                issues.append(f"BROKEN LINK: Hyperlink to '{anchor}' "
                              f"(¶{para_idx+1}, \"{display[:40]}\") — no such bookmark")
                orphan_links += 1
    print(f"  {orphan_links} broken hyperlinks")

    # --- Check 4: Scan for unlinked citation-like text ---
    # Look for patterns like "Author (Year)" or "Author Year" that aren't inside hyperlinks
    print("\n=== Unlinked citation-like text ===")
    # Citation pattern: Capitalized word(s) followed by (YYYY) or YYYY
    cite_pattern = re.compile(
        r'(?<!\w)([A-Z][a-z\u00E0-\u00FF]+(?:\s+(?:and|&|et\s+al\.?)\s+'
        r'[A-Z][a-z\u00E0-\u00FF]+)*)\s+\(?((?:19|20)\d{2})\)?(?!\w)'
    )

    # Build set of already-linked citation texts
    linked_texts = set()
    for anchor, links in hyperlinks.items():
        for _, display in links:
            linked_texts.add(display.strip())

    # Find references section start
    ref_section_start = None
    for i, txt in enumerate(para_texts):
        if txt.strip() == "References":
            ref_section_start = i
            break

    unlinked_count = 0
    for i, txt in enumerate(para_texts):
        # Skip reference section and beyond
        if ref_section_start and i >= ref_section_start:
            continue
        # Skip title area
        if i < 5:
            continue
        for m in cite_pattern.finditer(txt):
            full_match = m.group(0)
            # Check if this is already linked.  Two checks:
            # (a) exact full_match inside a linked text — catches narrative
            #     "Author (Year)" where the hyperlink includes the parens
            # (b) core "Author Year" (no parens) inside a linked text — catches
            #     parenthetical "(Author Year)" where regex grabs trailing ")"
            #     and partial-name matches like "Bank 2025" ⊂ "World Bank 2025"
            core_cite = f"{m.group(1)} {m.group(2)}"
            if (any(full_match.strip() in lt for lt in linked_texts) or
                    any(core_cite in lt for lt in linked_texts)):
                continue
            # Check common false positives
            author = m.group(1)
            if author in ("Section", "Table", "Figure", "Appendix", "Proposition",
                           "Corollary", "Equation", "Step", "Part", "Band",
                           "Index"):
                continue
            issues.append(f"UNLINKED: \"{full_match}\" (¶{i+1}) — "
                          f"looks like a citation but is not hyperlinked")
            unlinked_count += 1
    print(f"  {unlinked_count} unlinked citation-like mentions")

    # --- Check 5: Cross-reference completeness ---
    # For each reference, check it has: bookmark + back-link hyperlink to in-text
    # For each in-text cite, check it has: bookmark + forward hyperlink to reference
    print("\n=== Cross-reference completeness ===")
    # Get all unique citation keys from in-text bookmarks AND from
    # hyperlinks pointing to reference bookmarks (handles footnotes, tables)
    cite_keys_used = {name[:-3] for name in cite_txt_bookmarks}
    cite_keys_used |= {anchor for anchor in hyperlinks if anchor in ref_bookmarks}
    ref_keys = set(ref_bookmarks.keys())

    keys_in_text_not_in_refs = cite_keys_used - ref_keys
    keys_in_refs_not_in_text = ref_keys - cite_keys_used

    for key in sorted(keys_in_text_not_in_refs):
        issues.append(f"CITE WITHOUT REF: '{key}' cited in text but no reference bookmark")
    for key in sorted(keys_in_refs_not_in_text):
        idx = ref_bookmarks[key]
        issues.append(f"REF WITHOUT CITE: '{key}' (¶{idx+1}) in references but never cited in text")

    print(f"  {len(cite_keys_used)} unique citations in text")
    print(f"  {len(ref_keys)} unique references")
    print(f"  {len(keys_in_text_not_in_refs)} cited but not in references")
    print(f"  {len(keys_in_refs_not_in_text)} in references but not cited")

    # --- Summary ---
    print(f"\n{'='*60}")
    if not issues:
        print("ALL CHECKS PASSED — no issues found.")
    else:
        print(f"FOUND {len(issues)} ISSUE(S):\n")
        for issue in issues:
            print(f"  - {issue}")

    return len(issues)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <docx_path>", file=sys.stderr)
        sys.exit(1)
    n = check_citations(sys.argv[1])
    sys.exit(1 if n > 0 else 0)
