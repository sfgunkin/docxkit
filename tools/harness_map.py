"""Which test files exercise a module — the HARNESS a mutation run needs.

`tools/mutation_session.py` takes `--tests`, and that choice bounds
everything the run can say: a suite that is too narrow INVENTS survivors
(`comments.py` came back as the worst module in the package because
`test_parts_gaps.py`, which tests `remove` exhaustively, was not in the
run), and one that is too broad costs wall clock on every mutant.

So the mapping is recorded rather than re-derived each time, and the
figures in CONTRIBUTING's calibration table are only comparable against
the same entry. Quote the harness beside any number this produces.

Entries are hand-checked. When a module has none, `harness_for` falls
back to scanning `tests/` for files that import it — enough to get a
first run out of a new module, and worth replacing with a checked entry
once the run says which files actually reach it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

#: module file name -> the test files that exercise it
HARNESS: dict[str, list[str]] = {
    "_compare_read.py": ["tests/test_compare.py",
                         "tests/test_pathological.py"],
    # the last three joined on 2026-08-18, measured rather than argued:
    # importing the module alone covers 13 % of it, and these three take
    # it to 22, 40 and 26 — they were in EXCLUDED as "the DATA half's
    # files", which is true of `test_tables.py` and
    # `test_tables_update.py` (13 %, an import and nothing more) and was
    # never true of these. `drop_blank_rows` IS this module.
    "_table_layout.py": ["tests/test_booktabs_plan.py",
                         "tests/test_booktabs_rules.py",
                         "tests/test_table_layout_branches.py",
                         "tests/test_table_measure_divide.py",
                         "tests/test_tables_api.py",
                         "tests/test_tables_blank_rows.py",
                         "tests/test_tables_fit.py",
                         "tests/test_tables_fit_edges.py",
                         "tests/test_tables_house.py",
                         "tests/test_tables_nested.py",
                         "tests/test_tables_decimals.py",
                         "tests/test_tables_pin_stub.py",
                         "tests/test_tables_regrid.py",
                         "tests/test_width_model.py"],
    "cli.py": ["tests/test_cli.py", "tests/test_cli_guards.py",
               "tests/test_cli_revision.py"],
    "comments.py": ["tests/test_comments.py", "tests/test_comment_threads.py",
                    "tests/test_classify_match.py",
                    "tests/test_parts_gaps.py",
                    "tests/test_value_types.py"],
    "crossrefs.py": ["tests/test_crossrefs.py",
                     "tests/test_crossrefs_field_form.py",
                     "tests/test_link_convention.py",
                     "tests/test_value_types.py"],
    "equations.py": ["tests/test_equations.py",
                     "tests/test_equations_fragments.py",
                     "tests/test_prose_math.py", "tests/test_to_latex.py",
                     "tests/test_value_types.py",
                      "tests/test_equations_typography.py"],
    "footnotes.py": ["tests/test_footnotes.py", "tests/test_footnote_ids.py",
                     "tests/test_parts_gaps.py",
                     "tests/test_value_types.py"],
    "revision.py": ["tests/test_revision.py", "tests/test_revision_doctor.py",
                    "tests/test_revision_state.py",
                    "tests/test_revision_survey.py",
                    "tests/test_revision_verdict.py",
                    "tests/test_revision_gates.py",
                    "tests/test_cli_revision.py",
                    "tests/test_value_types.py"],
    "revisions.py": ["tests/test_revisions.py",
                     "tests/test_revisions_marks.py",
                     "tests/test_revisions_selective.py",
                     "tests/test_revision_state.py", "tests/test_comments.py",
                     "tests/test_value_types.py"],
    # `test_refstyle_layout.py` is where `paragraph_property` is tested,
    # because that is where the question comes up — refstyle asks "would
    # writing this value be redundant?". Leaving it out read the function
    # as almost entirely unpinned: 26 of styles.py's 36 real survivors
    # were in it, including `for sid, body in []`, which says no test
    # walks the basedOn chain at all. Adding this one line took the
    # module from 36 real survivors to 10, no test written. Same shape
    # as `errors.py`, which read 100% survival for the same reason (see
    # CONTRIBUTING).
    "styles.py": ["tests/test_styles.py",
                  "tests/test_refstyle_layout.py",
                  "tests/test_value_types.py"],
    "tracked.py": ["tests/test_tracked_build.py", "tests/test_tracked_guard.py",
                   "tests/test_cli_revision.py", "tests/test_parts_gaps.py",
                   "tests/test_value_types.py"],
    "_cite_audit.py": ["tests/test_citations.py", "tests/test_crossrefs.py",
                       "tests/test_link_convention.py"],
    # the five CONTRIBUTING records for the paired runs, plus the four
    # files written since to pin what those runs found
    "_cite_build.py": ["tests/test_citations.py",
                       "tests/test_link_convention.py",
                       "tests/test_cite_build_paths.py",
                       "tests/test_link_rest_paths.py",
                       "tests/test_cite_scan_paths.py",
                       "tests/test_cite_rebuild_paths.py",
                       "tests/test_cite_link_all_paths.py",
                       "tests/test_cite_names.py",
                       "tests/test_cite_anchor_reuse.py"],
    "_cite_grammar.py": ["tests/test_citations.py", "tests/test_cite_names.py",
                         "tests/test_reference_bounds.py",
                         "tests/test_wrap_span.py",
                         "tests/test_xml_primitives.py",
                         "tests/test_value_types.py"],
    "_cite_repair.py": ["tests/test_citations.py", "tests/test_pathological.py",
                        "tests/test_cite_anchor_reuse.py"],
    "_compare_diff.py": ["tests/test_compare.py"],
    "_compare_render.py": ["tests/test_compare.py"],
    # test_tables_update and test_tables were MISSING here on the first
    # sweep, and the run came back at 44.9 % with 216 survivors in
    # `update` — a module reported as the worst in the package because
    # the file that tests it was not in the harness. Exactly the trap
    # CONTRIBUTING records for `comments` and `_table_layout`, walked
    # into again with a map that was supposed to prevent it.
    "_table_core.py": ["tests/test_tables_api.py",
                       "tests/test_tables.py",
                       "tests/test_tables_update.py",
                       "tests/test_tables_house.py",
                       "tests/test_tables_nested.py",
                       "tests/test_tables_blank_rows.py",
                       "tests/test_booktabs_plan.py",
                       "tests/test_booktabs_rules.py",
                       "tests/test_table_measure_divide.py",
                       "tests/test_table_spacing.py",
                       "tests/test_rows_preserved.py",
                       "tests/test_value_types.py"],
    "_xml.py": ["tests/test_xml_primitives.py", "tests/test_span_membership.py",
                "tests/test_field_walk.py", "tests/test_find_edit.py",
                "tests/test_locate_spans.py"],
    "authors.py": ["tests/test_authors.py", "tests/test_authors_parts.py"],
    # Neither of these had an entry until 2026-08-24, and the cost was
    # not that they were unmeasurable — `harness_for` falls back to the
    # files that NAME a module — but that they were INVISIBLE.
    # `stale_figures` walks this dict, so the table a round is planned
    # from could not see them: `placement.py` is the largest module in
    # the package and its recorded 20.2% is the worst figure in it, and
    # `batch.py` had never been measured at all.
    "batch.py": ["tests/test_batch.py"],
    "body.py": ["tests/test_body.py", "tests/test_booktabs_plan.py"],
    "citations.py": ["tests/test_citations.py",
                     "tests/test_cite_anchor_reuse.py",
                     "tests/test_cite_names.py"],
    "compare.py": ["tests/test_compare.py", "tests/test_cli.py"],
    "console.py": ["tests/test_console.py", "tests/test_cli_guards.py"],
    "edit.py": ["tests/test_find_edit.py", "tests/test_edit_boundaries.py",
                "tests/test_edit_branches.py",
                "tests/test_normalize_anchors.py",
                "tests/test_locate_spans.py", "tests/test_replace_spans.py"],
    # The exit CODES are this module's contract with the paper
    # projects' scripts, and the tests that read them live with the
    # protocol they belong to. Without them `errors.py` measured
    # 100 % survival — ten mutants, all of them an `exit_code`, and
    # not one reachable from the two files below.
    "errors.py": ["tests/test_api_surface.py",
                  "tests/test_cli_guards.py",
                  "tests/test_revision.py",
                  "tests/test_cli_revision.py"],
    "export.py": ["tests/test_export_md.py"],
    "figures.py": ["tests/test_figures.py", "tests/test_alt_text.py",
                   "tests/test_value_types.py"],
    "find.py": ["tests/test_find_edit.py", "tests/test_body.py",
                "tests/test_probe.py", "tests/test_crossrefs.py",
                "tests/test_export_md.py", "tests/test_wordcount.py"],
    "guard.py": ["tests/test_tracked_guard.py", "tests/test_cli_guards.py"],
    "hygiene.py": ["tests/test_smarten.py", "tests/test_properties.py",
                   "tests/test_parts_gaps.py", "tests/test_pathological.py",
                   "tests/test_table_spacing.py"],
    "ingest.py": ["tests/test_ingest.py", "tests/test_revision.py"],
    "lint.py": ["tests/test_lint.py", "tests/test_cli_guards.py",
                "tests/test_crossrefs.py"],
    "package.py": ["tests/test_package.py", "tests/test_parts_gaps.py",
                   "tests/test_pathological.py"],
    "pages.py": ["tests/test_pages.py", "tests/test_locate.py"],
    "placement.py": ["tests/test_placement.py"],
    "probe.py": ["tests/test_probe.py", "tests/test_probe_report.py"],
    "refstyle.py": ["tests/test_refstyle.py",
                    "tests/test_refstyle_layout.py",
                    "tests/test_paragraph_numbering.py",
                    "tests/test_value_types.py"],
    "renumber.py": ["tests/test_renumber.py", "tests/test_footnote_ids.py",
                    "tests/test_footnote_audit.py"],
    "tables.py": ["tests/test_tables_api.py", "tests/test_tables.py",
                  "tests/test_tables_update.py", "tests/test_tables_nested.py",
                  "tests/test_booktabs_plan.py"],
    "testing.py": ["tests/test_testing_helpers.py"],
    "word.py": ["tests/test_word_session_ruler.py",
                "tests/test_word_open.py", "tests/test_locate.py",
                "tests/test_tracked_build.py", "tests/test_revision.py",
                "tests/test_flatopc.py", "tests/test_equations.py"],
    "wordcount.py": ["tests/test_wordcount.py",
                     "tests/test_value_types.py"],
}


#: A module's tests are conventionally named after it or after the
#: facade it sits behind, so `tests/test_<name>*.py` is a claim about
#: coverage that a harness entry must answer. Anything deliberately left
#: out belongs here with its reason — `test_tables_fit*` exercises the
#: LAYOUT half, not the core, and putting it in every core run would
#: cost wall clock on every mutant for nothing.
#:
#: MEASURE the reason before writing it here. An exclusion is the one
#: claim in this file the gate cannot check, and a wrong one invents
#: survivors in whatever the file covered — `_table_core` reported 216
#: in `update` that way, and `_table_layout` carried three misfiled
#: exclusions from 2026-08-16 until they were measured on the 18th.
#:
#: MARGINAL coverage is the measurement, not the file's own. Run the
#: harness, then run it with the candidate added, and compare:
#:
#:     python -m pytest -q --cov=docxkit._table_core \
#:            --cov-report=term <the harness>
#:     python -m pytest -q --cov=docxkit._table_core \
#:            --cov-report=term <the harness> tests/test_tables_fit.py
#:
#: A file's coverage ON ITS OWN answers a different question and gets
#: the answer wrong in both directions. Measured 2026-08-18:
#: `test_tables_fit.py` covers 32 % of `_table_core` alone — well past
#: the 23 % that merely importing it costs — and adds NOTHING to the
#: harness, which sits at 97 % with and without it. Those lines are
#: `read_all` and `Table` used as fixtures for what the file really
#: tests. `test_tables_blank_rows.py` looked the same at 26 % of
#: `_table_layout` and was not the same at all: it was the only file
#: covering `drop_blank_rows`, whose survivors went 12 -> 1 when it
#: joined that run.
FACADE = {"_table_core.py": "tables", "_table_layout.py": "tables",
          "_compare_diff.py": "compare", "_compare_render.py": "compare",
          "_compare_read.py": "compare"}
EXCLUDED: dict[str, tuple[str, ...]] = {
    "_table_core.py": ("tests/test_tables_fit.py",
                       "tests/test_tables_fit_edges.py",
                       # regrid and set_decimals are the layout half
                       # too: they rewrite the grid, the spans and the
                       # printed precision, and reach _table_core only
                       # through rows_of/cells_of/_cell_text
                       "tests/test_tables_decimals.py",
                       "tests/test_tables_pin_stub.py",
                       "tests/test_tables_regrid.py"),
    # the DATA half's files: they read cells and rewrite values, which
    # the layout module has no part in, and each costs wall clock on
    # every one of its 2,217 mutants. MEASURED, on 2026-08-18, after
    # three of the five turned out to exercise it after all — see the
    # note above EXCLUDED for the one-liner.
    "_table_layout.py": ("tests/test_tables.py",
                         "tests/test_tables_update.py"),
    "tables.py": ("tests/test_tables_fit.py",
                  "tests/test_tables_fit_edges.py",
                  "tests/test_tables_house.py",
                  "tests/test_tables_decimals.py",
                  "tests/test_tables_pin_stub.py",
                  "tests/test_tables_regrid.py",
                  "tests/test_tables_blank_rows.py"),
}


def named_after(module: str) -> list[str]:
    """Test files whose NAME claims to be about this module.

    The stem must be followed by `_` or end the name: `test_word.py` and
    `test_word_open.py` are claims about `word.py`, and
    `test_wordcount.py` is not — it is a claim about `wordcount.py`,
    which has an entry of its own.
    """
    stem = FACADE.get(module, module.removesuffix(".py").lstrip("_"))
    return [f"tests/{p.name}" for p in sorted(TESTS.glob(f"test_{stem}*.py"))
            if p.stem == f"test_{stem}" or p.stem.startswith(f"test_{stem}_")]


def _imports(path: Path, stem: str) -> bool:
    """Does this test file reach `stem`, by any of the import spellings?"""
    text = path.read_text(encoding="utf-8")
    return bool(re.search(rf"\bdocxkit\.{stem}\b|import .*\b{stem}\b", text))


def harness_for(module: str) -> list[str]:
    """The recorded harness, or every test file that imports the module.

    The fallback is a starting point, not an entry: it finds the files
    that NAME the module, which is neither everything that exercises it
    (a facade hides its halves) nor only what does.
    """
    if module in HARNESS:
        return HARNESS[module]
    stem = module.removesuffix(".py")
    found = [f"tests/{p.name}" for p in sorted(TESTS.glob("test_*.py"))
             if _imports(p, stem)]
    if not found:
        raise SystemExit(
            f"no harness for {module}: add one to HARNESS in {__file__}, "
            f"or pass --tests yourself")
    return found


#: Files outside ``src/`` and ``tests/`` that the SUITE ITSELF reads.
#: Both private checkouts — the mutation worktree and kill_check's — are
#: created at HEAD and then refreshed from the live tree file by file, so
#: anything else a test opens is whatever HEAD had.
#:
#: Measured 2026-08-19: the README's command gate (it holds the written
#: lists to the argparse parser) failed inside the worktree against a
#: README from an older commit, the unmutated baseline came back red, and
#: `cli.py` could not be measured at all. A test that reads a repo
#: document belongs on this list.
REPO_FILES = ("README.md", "pyproject.toml")


if __name__ == "__main__":                      # pragma: no cover
    import sys
    for name in sys.argv[1:]:
        print(name, harness_for(name))
