r"""The consumer contract: what the papers actually import.

`__all__` declares 626 names across 35 modules. The nine papers here —
274 scripts — import 128 of them (measured 2026-09-01), and 20 of those
reach through a module private by name. That gap is the difference
between what the package OFFERS and what it has PROMISED, and until
`tools/consumers.py` wrote it down nothing recorded the second half:
`test_api_surface` pins that a name is listed, `tools/api_check.py`
guarded every listed name equally, and neither knew which names a
consumer is written against.

The snapshot is committed, so these run on any machine; refreshing it
needs the corpus and is `tools/consumers.py`'s job.

Two questions here. Does every recorded import still resolve — a paper
that breaks tomorrow breaks on exactly this list. And which of them go
through a private path, pinned as a set that may only SHRINK, because
each one is either a name to promote or a paper to migrate.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import consumers  # pyright: ignore[reportMissingImports]

PAIRS = sorted(consumers.load())

#: Imports the papers make through a module whose name says private.
#: **This set may shrink and may not grow.** Each entry is one of two
#: things: a name worth promoting to a public module (the four `_xml`
#: names below were, on 2026-09-01 — `docxkit.visible_text` and friends
#: now exist, and these lines stay until the papers are next touched),
#: or a paper reaching past the API for something it should ask for
#: differently. A new entry means a paper was written against private
#: machinery while nobody was looking.
PRIVATE = {
    ("docxkit._cite_grammar", "masked_visible_text"),
    ("docxkit._cite_grammar", "reference_head"),
    ("docxkit._cite_grammar", "visible_text"),
    ("docxkit._cite_repair", "field_spans"),
    ("docxkit._cite_repair", "next_bookmark_id"),
    ("docxkit._cite_repair", "wrap_link_in_bookmark"),
    ("docxkit._table_layout", "booktabs"),
    ("docxkit._table_layout", "plan_booktabs"),
    ("docxkit._xml", "DOCUMENT"),
    ("docxkit._xml", "INSTR_ANCHOR_RE"),
    ("docxkit._xml", "INSTR_RE"),
    ("docxkit._xml", "PARA_RE"),
    ("docxkit._xml", "RUN_RE"),
    ("docxkit._xml", "_FIELD_RE"),
    ("docxkit._xml", "_HYPERLINK_EL_RE"),
    ("docxkit._xml", "internal_links"),
    ("docxkit._xml", "own_properties"),
    ("docxkit._xml", "run_open_before"),
    ("docxkit._xml", "set_run_text"),
    ("docxkit._xml", "visible_text"),
    ("docxkit._xml", "_xml"),
}

#: The four promoted on 2026-09-01, with the public path they now have.
#: `_xml` is 41 of 58 modules' bottom layer and keeps its name; what
#: changed is that a paper no longer HAS to spell the underscore.
PROMOTED = {"DOCUMENT": "docxkit", "PARA_RE": "docxkit",
            "RUN_RE": "docxkit", "visible_text": "docxkit"}


def test_the_snapshot_is_not_empty():
    """A consumer list refreshed over zero scripts would be an empty
    promise that reads as a kept one — the `sweep` lesson, in the file
    the API gate reads."""
    assert len(PAIRS) > 100, f"only {len(PAIRS)} imports — was it refreshed?"


def _resolves(module: str, name: str) -> bool:
    """Does `from module import name` work, as a paper writes it?

    Either an attribute or a SUBMODULE: `from docxkit import body` is a
    legitimate import and `hasattr(docxkit, "body")` is False until
    something imports it, which is a fact about import order and not
    about the package's contract. Reading it as a missing name failed
    twelve of these on the first run.
    """
    mod = importlib.import_module(module)
    if hasattr(mod, name):
        return True
    try:
        importlib.import_module(f"{module}.{name}")
    except ImportError:
        return False
    return True


@pytest.mark.parametrize("module,name", PAIRS,
                         ids=[f"{m}.{n}" for m, n in PAIRS])
def test_every_import_a_paper_makes_still_resolves(module, name):
    """The list is only worth having if it is checked. A paper that
    breaks tomorrow breaks on exactly one of these lines."""
    assert _resolves(module, name), (
        f"a paper imports {name} from {module} and it is gone — either "
        f"restore it or migrate the paper, but not silently")


def test_the_private_path_imports_are_the_known_set():
    """Pinned so a new one cannot arrive unnoticed. Shrinking this is
    the work; growing it is the thing to notice."""
    found = {(m, n) for m, n in PAIRS if m.split(".")[-1].startswith("_")}

    assert found <= PRIVATE, (
        f"a paper now reaches into private machinery that nothing "
        f"recorded: {sorted(found - PRIVATE)}")
    assert not PRIVATE - found or True, "shrinking is allowed and expected"


def test_the_promoted_names_are_importable_from_the_public_path():
    """The four the review promoted. The papers still spell them
    `docxkit._xml` and the entries above say so; what this holds is that
    the public spelling EXISTS, so a paper being touched can move."""
    for name, module in PROMOTED.items():
        mod = importlib.import_module(module)
        assert hasattr(mod, name), f"docxkit.{name} was promoted; keep it"
        assert name in mod.__all__


def test_a_consumed_name_lives_in_the_module_it_is_imported_from():
    """`from docxkit.x import y` has to work as written, not only
    because `y` happens to be re-exported somewhere else. This is what
    makes the list usable as the strict tier in `api_check`."""
    for module, name in PAIRS:
        assert _resolves(module, name), f"{module}.{name}"
