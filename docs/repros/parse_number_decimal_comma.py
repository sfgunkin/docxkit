"""DEFECT — a decimal COMMA is read as a thousands separator.

`parse_number` strips every comma before `float()`, so a number written
the way a Russian (or French, or German) table writes it comes back
multiplied by a power of ten — silently, as a number, with nothing for a
caller to check:

    "0,31"      ->  31.0        (0.31)
    "12,5"      -> 125.0        (12.5)
    "1 234,5"   -> 12345.0      (1234.5, and the space IS handled)

The module knows about the space separators — `_NUM_RE` carries both the
no-break and the plain one, and the docstring promises them — so this is
not a form the reader rejects; it is one it accepts and gets wrong.

`_render_value` then writes the cell back in that reading: it learns the
old cell's format from the same match, so a Russian cell updated with a
new value comes back in English thousands format and with the decimals
the misread implies. `update` over such a table rewrites every cell.

Where it bites: this package's own corpus. The DSI paper is Russian
throughout ("Таблицы 1-12"), and its tables are full of "0,31".

    python defect_1.py
"""
import sys

sys.path.insert(0, r"D:\docxkit\src")

from docxkit._table_core import _render_value, parse_number  # noqa: E402

print("parse_number:")
for text, want in (("0,31", 0.31), ("12,5", 12.5), ("1\u00a0234,5", 1234.5),
                   ("-0,623", -0.623)):
    got = parse_number(text)
    print(f"  {text!r:14} -> {got!r:10} (a Russian table means {want})")

print("\nthe separators that ARE right, for contrast:")
for text, want in (("1,234.5", 1234.5), ("1\u00a0234.5", 1234.5),
                   ("1 234.5", 1234.5)):
    print(f"  {text!r:14} -> {parse_number(text)!r:10} (means {want})")

print("\n_render_value, writing a new value into such a cell:")
for old, new in (("0,31", 0.4), ("1\u00a0234,5", 2345.6)):
    print(f"  old {old!r:14} new {new!r:8} -> {_render_value(old, new)!r}")
print("  (a Russian cell comes back in English format, and to the number "
      "of decimals the misreading implies)")
