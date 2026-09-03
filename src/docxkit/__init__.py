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
from ._xml import DOCUMENT, PARA_RE, RUN_RE, visible_text
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
    edit_in_place,
    is_locked,
    read_parts,
    write_docx,
)

__version__ = "1.0.0"

__all__ = [
    "DOCUMENT",
    "PARA_RE",
    "RUN_RE",
    "Parts",
    "assert_unlocked",
    "backup",
    "edit_in_place",
    "edit_para",
    "is_locked",
    "para_slice",
    "para_text_at",
    "paragraphs",
    "preserve_space",
    "read_parts",
    "rep",
    "replace_in_para",
    "table_spans",
    "text_of",
    "utf8_stdout",
    "visible_text",
    "write_docx",
]
