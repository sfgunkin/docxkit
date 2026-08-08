r"""docxkit — shared tooling for Word manuscripts.

Everything works on the package parts dict rather than through python-docx,
which drops what it does not model: saving through it loses comments, and
it cannot see text inside ``<w:ins>`` at all (a tracked insertion reads as
an empty paragraph).

    from docxkit import read_parts, write_docx, edit_in_place
    from docxkit.compare import compare, render      # multi-layer diff
    from docxkit.tracked import build                # redline deliverable
    from docxkit.ingest import build_overrides       # author-edit round
    from docxkit.crossrefs import link               # figure/table links

Word automation lives in :mod:`docxkit.word` and is imported lazily, so the
rest of the toolkit works anywhere; only the COM-backed features need
Windows and ``pip install docxkit[word]``.
"""
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
    assert_unlocked,
    backup,
    edit_in_place,
    is_locked,
    read_parts,
    write_docx,
)

__version__ = "1.0.0"

__all__ = [
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
    "write_docx",
]
