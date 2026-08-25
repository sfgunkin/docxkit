r"""Manuscript tables: their values, and how they look.

Every paper's value tests read tables and several build them, so
this had been written five or six ways: AFI's ``export_tables``,
Parental Style's five ``build_table*.py``, Life Expectancy's
``read_table4``, DSI's ``check_table4_18``, Loneliness Index's
``inspect_tables``.

Two concerns live beneath this module, sharing the ``Table`` type
and nothing else:

===================  ================================================
:mod:`_table_core`    locate a table, read its cells, rewrite VALUES
:mod:`_table_layout`  column widths, borders, superscript stars
===================  ================================================

The split is why the font-metric tables for Times and Arial no
longer sit next to the code that reads a cell. Both halves are
re-exported here, so ``from docxkit.tables import ...`` keeps
working for every name it ever offered.
"""
from __future__ import annotations

# reached through this module by the papers and the tests
from ._table_core import _TC_RE as _TC_RE
from ._table_core import _TR_RE as _TR_RE

# re-exported from _table_core: `as` marks it deliberate, or
# ruff --fix strips it and the papers stop importing
from ._table_core import CellChange as CellChange
from ._table_core import RowsReport as RowsReport
from ._table_core import Table as Table
from ._table_core import _cell_text as _cell_text
from ._table_core import _render_value as _render_value
from ._table_core import _table_spans as _table_spans
from ._table_core import by_caption as by_caption
from ._table_core import cells_of as cells_of
from ._table_core import clone_row as clone_row
from ._table_core import find as find
from ._table_core import parse_number as parse_number
from ._table_core import read_all as read_all
from ._table_core import reorder_rows as reorder_rows
from ._table_core import row_signature as row_signature
from ._table_core import rows_of as rows_of
from ._table_core import rows_preserved as rows_preserved
from ._table_core import set_cell as set_cell
from ._table_core import set_row as set_row
from ._table_core import tables_after as tables_after
from ._table_core import to_frame as to_frame
from ._table_core import tolerance_for as tolerance_for
from ._table_core import update as update
from ._table_layout import _ARIAL as _ARIAL
from ._table_layout import _ARIAL_NARROW as _ARIAL_NARROW
from ._table_layout import _RUN_RE as _RUN_RE
from ._table_layout import _SPAN_RE as _SPAN_RE

# re-exported from _table_layout: `as` marks it deliberate, or
# ruff --fix strips it and the papers stop importing
from ._table_layout import BooktabsPlan as BooktabsPlan
from ._table_layout import ColumnFit as ColumnFit
from ._table_layout import FitReport as FitReport
from ._table_layout import HouseReport as HouseReport
from ._table_layout import RegridReport as RegridReport
from ._table_layout import _bump as _bump
from ._table_layout import _const as _const
from ._table_layout import _round_to as _round_to
from ._table_layout import booktabs as booktabs
from ._table_layout import bottom_border as bottom_border
from ._table_layout import drop_blank_rows as drop_blank_rows
from ._table_layout import fit_columns as fit_columns
from ._table_layout import house as house
from ._table_layout import house_ppr as house_ppr
from ._table_layout import house_rpr as house_rpr
from ._table_layout import plan_booktabs as plan_booktabs
from ._table_layout import regrid as regrid
from ._table_layout import superscript_stars as superscript_stars

__all__ = [
    "BooktabsPlan",
    "CellChange",
    "ColumnFit",
    "FitReport",
    "HouseReport",
    "RegridReport",
    "RowsReport",
    "Table",
    "booktabs",
    "bottom_border",
    "by_caption",
    "clone_row",
    "drop_blank_rows",
    "find",
    "fit_columns",
    "house",
    "house_ppr",
    "house_rpr",
    "parse_number",
    "plan_booktabs",
    "read_all",
    "regrid",
    "reorder_rows",
    "row_signature",
    "rows_preserved",
    "set_cell",
    "set_row",
    "superscript_stars",
    "tables_after",
    "to_frame",
    "tolerance_for",
    "update",
]
