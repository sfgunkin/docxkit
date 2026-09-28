r"""docxkit — shared tooling for Word manuscripts.

Everything works on the package parts dict rather than through python-docx,
which drops what it does not model: saving through it loses comments, and
it cannot see text inside ``<w:ins>`` at all (a tracked insertion reads as
an empty paragraph).

    from docxkit import read_parts, write_docx, edit_in_place
    from docxkit.compare import compare, render      # multi-layer diff
    from docxkit.tracked import build                # redline deliverable
    from docxkit.ingest import build_part_overrides  # author-edit round
    from docxkit.ingest import apply_part_overrides #   …and its writer
    from docxkit.crossrefs import link               # figure/table links

Word automation lives in :mod:`docxkit.word` and is imported lazily, so the
rest of the toolkit works anywhere; only the COM-backed features need
Windows and ``pip install docxkit[word]``.
"""
# Four names from `_xml`, which is private by name and public by use:
# 274 paper scripts import from it directly — `visible_text` 75 times,
# `DOCUMENT` 52, `PARA_RE` 38, `RUN_RE` 7 (measured 2026-09-01). The
# underscore was a claim nobody honoured, and the `api` gate now protects
# those names as hard as any. Exported here so a paper can import them
# through a public path; `_xml` keeps its name, since 41 modules import
# it and it IS internal-shaped.
#
# Nine more on 2026-09-29, the plain-named primitives the refreshed
# consumer snapshot shows papers importing from `_xml` (REVIEW_2026-09-28
# §5): the note parts, the property writers, the field and link readers.
# The raw field regexes stay private — `field_spans` is their reading.
from ._xml import (
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    PARA_RE,
    RUN_RE,
    field_spans,
    internal_links,
    own_properties,
    run_open_before,
    set_para_property,
    set_run_property,
    set_run_text,
    visible_text,
)
from .console import utf8_stdout
from .edit import preserve_space, rep, replace_in_para
from .find import (
    edit_para,
    para_slice,
    para_text_at,
    paragraphs,
    table_spans,
    text_of,
)
from .package import (
    Parts,
    assert_unlocked,
    backup,
    is_locked,
    read_parts,
    write_docx,
)

# The SAFE one since 2026-09-29: edge spaces protected and the lint run
# before the write, as every CLI command already saved.
# `docxkit.package.edit_in_place` stays the raw write for the scripts
# that import it from there.
from .save import edit_in_place

__version__ = "2026.9.29.1"

__all__ = [
    "DOCUMENT",
    "ENDNOTES",
    "FOOTNOTES",
    "PARA_RE",
    "RUN_RE",
    "Parts",
    "assert_unlocked",
    "backup",
    "edit_in_place",
    "edit_para",
    "field_spans",
    "internal_links",
    "is_locked",
    "own_properties",
    "para_slice",
    "para_text_at",
    "paragraphs",
    "preserve_space",
    "read_parts",
    "rep",
    "replace_in_para",
    "run_open_before",
    "set_para_property",
    "set_run_property",
    "set_run_text",
    "table_spans",
    "text_of",
    "utf8_stdout",
    "visible_text",
    "write_docx",
]
