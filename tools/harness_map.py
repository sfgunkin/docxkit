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
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

#: What every `revision/` half ran until 2026-09-17, kept because the
#: figures recorded against it are only comparable with it, and because
#: the narrowing below is a claim ABOUT it: each half's entry is the
#: subset of these twelve files that covers what they cover of it and
#: kills what they kill of it. Re-measure against this list, not against
#: today's superset of the entries.
REVISION_SUPERSET = ["tests/test_revision.py",
                     "tests/test_revision_doctor.py",
                     "tests/test_revision_state.py",
                     "tests/test_revision_survey.py",
                     "tests/test_revision_verdict.py",
                     "tests/test_revision_gates.py",
                     "tests/test_revision_ledger.py",
                     "tests/test_revision_status.py",
                     "tests/test_cli_revision.py",
                     "tests/test_workflow_states.py",
                     "tests/test_rescue_pruning.py",
                     "tests/test_value_types.py"]

#: module file name -> the test files that exercise it
HARNESS: dict[str, list[str]] = {
    "_compare_read.py": ["tests/test_compare.py",
                         "tests/test_compare_paragraph.py",
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
    # `test_note_orphans.py` joined on 2026-09-16, measured: of the 95
    # replayable survivors the whole sweep of 2026-09-15 left, that file
    # alone kills 44, nearly all of them in `orphans` and `prune_orphans`.
    # It is where a note whose reference is gone is tested.
    "footnotes.py": ["tests/test_footnotes.py", "tests/test_footnote_ids.py",
                     "tests/test_parts_gaps.py",
                     "tests/test_value_types.py",
                     "tests/test_note_orphans.py"],
    # `revision.py` became `revision/` on 2026-08-30, and until
    # 2026-09-17 each of the sixteen halves ran the harness the whole
    # module had — the twelve files of `REVISION_SUPERSET` above, 737
    # tests, 27-29 s single-process on a QUIET machine. A mutant gets 30 s
    # (`mutation_session.MUTANT_SECONDS`) and a mutant that SURVIVES is
    # the one whose tests all had to run, so every survivor crossed the
    # deadline and was graded KILLED: `revision/_promote.py` read "killed
    # 24, survived 0 (0.0% survive)" on 2026-09-17 and had measured
    # nothing. No half could be measured at all, which is what the
    # superset cost and why it is gone.
    #
    # Each entry is MEASURED, twice over (2026-09-17):
    #
    #   COVERAGE — `pytest --cov=docxkit.revision --cov-branch <file>`
    #   per file, less a `--collect-only` run over all twelve (the
    #   import-only baseline). Every file kept covers a line or branch of
    #   that half that the others do not; every file dropped covers none.
    #   The counts below are lines+branches BEYOND import.
    #
    #   KILLS — every mutant the half's stored session graded KILLED,
    #   replayed against the narrowed harness (`replay_survivors` is the
    #   survivor half of the same question; this is the other half, and
    #   it is the one narrowing can break). A session TIMEOUT is not a
    #   kill — it is the artefact this narrowing exists to end — so those
    #   are counted apart. Where a mutant the superset really killed got
    #   away, the file that kills it is back in the entry, and the note
    #   says which mutant put it there.
    #
    # Coverage alone would have been wrong in both directions, so neither
    # measurement is optional. It cannot see a line executed at IMPORT —
    # `@dataclass(frozen=True)`, a default argument, `RESCUE_KEEP = 5` —
    # which is what `test_value_types.py` and `_common`'s whole entry
    # hold; and a file can cover nothing the others do not and still be
    # the only one that ASSERTS on what it covers:
    # `test_revision_ledger.py` covers no line of `_baseline` that
    # `test_revision.py` misses, and is the only file in the package that
    # kills `L200 or -> and`.
    #
    # The per-half figures are NOT comparable with the `revision.py` line
    # in CONTRIBUTING's calibration table (3,118 lines against the
    # superset), nor with any figure measured against the superset
    # before today.
    #
    # WAS 4 mutants, all import-level constants (`RESCUE_KEEP`,
    # `WORD_DEADLINE`) that coverage cannot attribute: `test_revision.py`
    # killed 4 of 4, `test_cli_revision.py` 4 (dearer),
    # `test_revision_doctor.py` 2.
    #
    # It is 31 now. `f856e4d` moved `_stamp_of` and `_written_at` here so
    # `rescues()` and `Paper.redlines()` could share one reading of a
    # stamp — and the tests that exercise them stayed in
    # `test_rescue_pruning.py`, their old home. This entry was not
    # updated, so the module was measured against a harness that barely
    # touched its new half: 12.9 % survival, every survivor of it on the
    # ONE line `m.group(1) == kind`. Code that moves house leaves its
    # tests behind, and this map is the only place that shows.
    "revision/_common.py": ["tests/test_revision.py",
                            "tests/test_rescue_pruning.py"],
    # 39 lines+branches, all of them in test_revision.py; the other ten
    # files reach at most 37 and add none. 133 session-KILLED replayed:
    # 92 killed, 41 were session TIMEOUTS. value_types: `Paper` is frozen.
    "revision/_config.py": ["tests/test_revision.py",
                            "tests/test_value_types.py"],
    # 12 lines+branches, all here; six other files cover 9-10 and add
    # none. 35 session-KILLED replayed, all 35 still killed.
    "revision/_ledger.py": ["tests/test_revision_ledger.py"],
    # 177 lines+branches: 175 in test_revision.py (25 of them nowhere
    # else), 152 in test_cli_revision.py (2 nowhere else). 523
    # session-KILLED replayed: 489 killed, 34 were session TIMEOUTS.
    # value_types: `Loss` and `Relabelled` are frozen.
    "revision/_losses.py": ["tests/test_revision.py",
                            "tests/test_cli_revision.py",
                            "tests/test_value_types.py"],
    # 71 lines+branches: 63 in test_revision_status.py (21 nowhere else),
    # 50 in test_revision_state.py (8 nowhere else). 78 session-KILLED
    # replayed: 24 killed, 36 session TIMEOUTS — and 18 that the superset
    # does kill got away, every one of them `L107` (the `+` and the
    # numbers of the age arithmetic) plus `L55` and `L97`.
    # `test_revision.py` kills all 18 and nothing cheaper kills any
    # (test_cli_revision.py kills 13), so it stays. value_types: `State`
    # and `StatusReport` are frozen.
    "revision/_state.py": ["tests/test_revision_state.py",
                           "tests/test_revision_status.py",
                           "tests/test_revision.py",
                           "tests/test_value_types.py"],
    # 147 lines+branches, all in test_revision_verdict.py;
    # test_workflow_states.py reaches 119 and adds none — and kills
    # `L129 ins + dele -> <<` in the summary line, which nothing else
    # does. 376 session-KILLED replayed: 371 killed, 3 session TIMEOUTS,
    # and that one plus `L333 AddNot` on the log row, which
    # test_revision_ledger.py kills (the cheapest of the four files that
    # do). value_types: `Verdict` is frozen.
    "revision/_verdict.py": ["tests/test_revision_verdict.py",
                             "tests/test_workflow_states.py",
                             "tests/test_revision_ledger.py",
                             "tests/test_value_types.py"],
    # 36 lines+branches, all here; seven other files reach 18-32 and add
    # none. 44 session-KILLED replayed, all 44 still killed.
    "revision/_timing.py": ["tests/test_revision.py"],
    # 43 lines+branches: 41 in test_revision.py (25 nowhere else), 18 in
    # test_revision_state.py (2 nowhere else). 45 session-KILLED
    # replayed and TEN got away — the verdict written into the log:
    # `test_revision_verdict.py` kills 9 of them (`L52`, `L183-L199`) and
    # `test_revision_ledger.py` the tenth (`L200 or -> and`), and NEITHER
    # covers a line of this half the kept files miss. The clearest case
    # in the package for replaying kills rather than trusting coverage.
    # value_types: `BaselineReport` is frozen.
    "revision/_baseline.py": ["tests/test_revision.py",
                              "tests/test_revision_state.py",
                              "tests/test_revision_verdict.py",
                              "tests/test_revision_ledger.py",
                              "tests/test_value_types.py"],
    # 90 lines+branches: 88 in test_revision.py (80 nowhere else), 10 in
    # test_workflow_states.py (2 nowhere else). 91 session-KILLED
    # replayed, all 91 still killed.
    "revision/_build.py": ["tests/test_revision.py",
                           "tests/test_workflow_states.py"],
    # 100 lines+branches, all in test_revision_doctor.py;
    # test_cli_revision.py reaches 86 and adds none. 105 session-KILLED
    # replayed and one got away: `L72 or -> and`, the glob reading of
    # `[paper] working`, killed by `test_revision.py::test_a_GLOB_selects
    # _the_manuscript_by_either_reading` and by no other file.
    "revision/_doctor.py": ["tests/test_revision_doctor.py",
                            "tests/test_revision.py"],
    # 53 lines+branches, all here; test_cli_revision.py reaches 4 and
    # adds none. 88 session-KILLED replayed: 77 killed, 11 were session
    # TIMEOUTS — and two of those eleven (`code == 0 -> <= 0`,
    # `code == -1 -> <= -1`) survive the SUPERSET today, so the session
    # recorded kills that were never made. value_types: `GateResult` is
    # frozen.
    "revision/_gates.py": ["tests/test_revision_gates.py",
                           "tests/test_value_types.py"],
    # 11 lines+branches, all here; test_cli_revision.py covers the same
    # 11 and adds none. 27 of its 30 graded mutants replayed (three
    # anchors could not be placed): the 5 the session killed still
    # killed, its 22 survivors still alive.
    # value_types: `IngestReport` is frozen.
    "revision/_ingest.py": ["tests/test_revision.py",
                            "tests/test_value_types.py"],
    # 95 lines+branches, all in test_revision_survey.py;
    # test_cli_revision.py reaches 79 and adds none. 131 session-KILLED
    # replayed, all 131 still killed. value_types: `Survey` is frozen.
    "revision/_registry.py": ["tests/test_revision_survey.py",
                              "tests/test_value_types.py"],
    # 132 lines+branches, all in test_revision.py; test_cli_revision.py
    # reaches 105 and adds none. 244 session-KILLED replayed and one got
    # away: `L351 language or "en" -> and`, the default written into a
    # new paper's config, killed by `test_revision_doctor.py` — which
    # reads that key back — and by no other file.
    "revision/_init.py": ["tests/test_revision.py",
                          "tests/test_revision_doctor.py"],
    # 133 lines+branches: 105 in test_workflow_states.py (43 nowhere
    # else), 88 in test_revision.py (18), 72 in test_rescue_pruning.py
    # (2). 42 session-KILLED replayed: 29 killed, 12 session TIMEOUTS,
    # and `L339 != -> <` — two sha256 hexes, so its kill is a coin flip
    # on the digest — killed on all six re-runs, in both file orders.
    # value_types: `PromoteReport` and `WithdrawReport` are frozen.
    "revision/_promote.py": ["tests/test_workflow_states.py",
                             "tests/test_rescue_pruning.py",
                             "tests/test_revision.py",
                             "tests/test_value_types.py"],
    # 157 lines+branches: 143 in test_revision.py (51 nowhere else), 106
    # in test_revision_gates.py (14 nowhere else — the `--run-gates`
    # ladder). 255 session-KILLED replayed and one got away: `L453
    # == -> <=`, the body half of the math-downgrade comparison, which
    # only `test_cli_revision.py` killed. The engine-level test of that
    # decision is in test_revision.py and carried the `>=` direction but
    # not the `<=` one, so the missing case joined it there rather than
    # the 4.8 s file joining this entry — a kill kept where the decision
    # is made.
    "revision/_validate.py": ["tests/test_revision.py",
                              "tests/test_revision_gates.py"],
    # `test_cell_revisions.py` joined on 2026-09-16, measured: the whole
    # sweep of 2026-09-15 left 155 replayable survivors in the cell and
    # table walks, and that file alone killed 68 of them. It is where a
    # revision inside a table is tested, and the module is what it tests.
    "revisions.py": ["tests/test_revisions.py",
                     "tests/test_revisions_marks.py",
                     "tests/test_revisions_selective.py",
                     "tests/test_revision_state.py", "tests/test_comments.py",
                     "tests/test_value_types.py",
                     "tests/test_cell_revisions.py"],
    # `test_refstyle_layout.py` is where `paragraph_property` is tested,
    # because that is where the question comes up — refstyle asks "would
    # writing this value be redundant?". Leaving it out read the function
    # as almost entirely unpinned: 26 of styles.py's 36 real survivors
    # were in it, including `for sid, body in []`, which says no test
    # walks the basedOn chain at all. Adding this one line took the
    # module from 36 real survivors to 10, no test written. Same shape
    # as `errors.py`, which read 100% survival for the same reason (see
    # CONTRIBUTING).
    # The last two joined on 2026-09-18, each for a REGION the first
    # three never execute: `_toggle_on` (the toggle-property reader) and
    # the raised-prose part walk. Five mutants were built across the two
    # and all five SURVIVED the map as it stood; all five die with these
    # added, and the narrowing says which file does the killing in each
    # region. So the map was short in the way that matters — not "these
    # files touch the module" but "nothing else can kill here".
    #
    # `tests/test_compare_paragraph.py` was deliberately NOT added,
    # although it executes MORE of `styles.py` than any other candidate
    # (+52 lines, against test_compare's +48). It kills nothing in
    # either region. Coverage without assertions is not a harness, and
    # this is that sentence demonstrated inside one module: the file
    # with the biggest coverage number was the one that could not kill.
    # `tests/test_cli.py` is out for the other reason — it kills region
    # B, but so does the dedicated file, at a fraction of the cost on
    # every kill_check and replay.
    "styles.py": ["tests/test_styles.py",
                  "tests/test_refstyle_layout.py",
                  "tests/test_value_types.py",
                  "tests/test_compare.py",
                  "tests/test_raised_prose.py"],
    "tracked.py": ["tests/test_tracked_build.py",
                   "tests/test_tracked_gates.py",
                   "tests/test_tracked_edges.py",
                   "tests/test_tracked_guard.py",
                   "tests/test_cli_revision.py", "tests/test_parts_gaps.py",
                   "tests/test_value_types.py"],
    # `tracked.py` grew two halves on 2026-09-11, and each gets the
    # harness the whole module had — a SUPERSET, for the reason the
    # `revision/` entry below gives. Narrow once a run says which files
    # reach which half.
    **{f"{half}.py": ["tests/test_tracked_build.py",
                      "tests/test_tracked_gates.py",
                      "tests/test_tracked_edges.py",
                      "tests/test_tracked_guard.py",
                      "tests/test_cli_revision.py",
                      "tests/test_parts_gaps.py",
                      "tests/test_value_types.py"]
       for half in ("_tracked_gates", "_tracked_report")},
    "_cite_audit.py": ["tests/test_citations.py", "tests/test_crossrefs.py",
                       "tests/test_link_convention.py",
                       "tests/test_cite_audit_edges.py"],
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
                        "tests/test_cite_anchor_reuse.py",
                        "tests/test_cite_repair_edges.py"],
    "_compare_diff.py": ["tests/test_compare.py",
                         "tests/test_compare_paragraph.py"],
    "_compare_render.py": ["tests/test_compare.py",
                           "tests/test_compare_paragraph.py"],
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
    "compare.py": ["tests/test_compare.py",
                   "tests/test_compare_paragraph.py",
                   "tests/test_cli.py"],
    "console.py": ["tests/test_console.py", "tests/test_cli_guards.py"],
    "timings.py": ["tests/test_timings.py"],
    # `test_remove_link.py` and `test_insert_spans.py` are named after
    # FUNCTIONS of this module rather than after the module, so nothing
    # pulled them in and the sweep of 2026-09-17 measured `edit.py`
    # without the tests written for its link removal and its inserts.
    # Measured that day, replaying the sweep's 389 survivors against
    # these two files added: 158 of them die — 152 by
    # `test_remove_link.py`, 6 by `test_insert_spans.py` — every one to
    # a test that already existed. A harness gap does not read as a gap;
    # it reads as a module nobody tested.
    "edit.py": ["tests/test_find_edit.py", "tests/test_edit_boundaries.py",
                "tests/test_edit_branches.py",
                "tests/test_normalize_anchors.py",
                "tests/test_locate_spans.py", "tests/test_replace_spans.py",
                "tests/test_edit_links_replace.py",
                "tests/test_remove_link.py", "tests/test_insert_spans.py"],
    # The exit CODES are this module's contract with the paper
    # projects' scripts, and the tests that read them live with the
    # protocol they belong to. Without them `errors.py` measured
    # 100 % survival — ten mutants, all of them an `exit_code`, and
    # not one reachable from the two files below.
    "errors.py": ["tests/test_api_surface.py",
                  "tests/test_cli_guards.py",
                  "tests/test_revision.py",
                  "tests/test_cli_revision.py"],
    "exhibits.py": ["tests/test_exhibits.py", "tests/test_exhibits_edges.py",
                    "tests/test_placement.py"],
    "export.py": ["tests/test_export_md.py"],
    "figures.py": ["tests/test_figures.py", "tests/test_alt_text.py",
                   "tests/test_value_types.py"],
    # Checked by COVERAGE CONTEXT (`--cov-context=test`), so this is what
    # executes the module, not what mentions it. The suite runs 92 lines
    # of find.py; the six files listed here ran 51. The four added below
    # are where the other 41 come from, and `test_probe.py` and
    # `test_wordcount.py` ran ZERO — they named the module and never
    # reached it, so every kill_check and replay paid for them.
    #
    # The shortfall was real and small: of 21 survivors, applying the 11
    # that only the unmapped files reach, ONE dies with them added
    # (`if self.matches > 2`, the "(and N more match)" threshold, killed
    # by test_cli). The other eight testable that way survive the
    # extended harness too — the CLI and snapshot tests EXECUTE those
    # lines and assert nothing about what they produce. Coverage without
    # assertions is not a harness, which is why a map cannot be built
    # from a coverage number alone.
    "find.py": ["tests/test_find_edit.py", "tests/test_body.py",
                "tests/test_crossrefs.py", "tests/test_export_md.py",
                "tests/test_cli.py", "tests/test_cli_guards.py",
                "tests/test_snapshot.py", "tests/test_note_parts.py"],
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
    # the numbering property: a module that changes HOW MANY paragraphs
    # there are is the one most able to break what ¶N points at
    "paragraph.py": ["tests/test_paragraph.py",
                     "tests/test_paragraph_numbering.py"],
    "placement.py": ["tests/test_placement.py"],
    "repack.py": ["tests/test_repack.py"],
    "sections.py": ["tests/test_sections.py", "tests/test_sections_edges.py"],
    "snapshot.py": ["tests/test_snapshot.py"],
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
          "_compare_read.py": "compare",
          "_tracked_gates.py": "tracked", "_tracked_report.py": "tracked"}
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


def session_stem(module: str | Path) -> str:
    """The `.mutation-<stem>.*` name a session for this module uses.

    Accepts either spelling in use: a HARNESS key (`edit.py`,
    `revision/_build.py`) or a full path (`src/docxkit/revision/
    _build.py`). The leading underscore is dropped because a filename
    beginning with a dot and an underscore is awkward to type, and a
    top-level module keeps exactly the name its session has always had —
    49 of them exist on this machine and renaming them would orphan
    every recorded figure.

    **A module in a subpackage keeps its folder.** `revision/` arrived
    on 2026-08-30 and the basename rule stopped being unique the same
    day: `revision/_ingest.py` and `ingest.py` both reduced to `ingest`,
    so the second session to run would silently resume or overwrite the
    first's, and `mutation_survivors` would then pair that database with
    a `.pristine` holding the other module's source — line numbers
    indexing into a file the run never saw. Same shape as the coverage
    floor keys, and one folder deeper.

    Written here because three tools derived this independently —
    `mutation_session`, `measure_all` and `stale_figures` — in three
    slightly different spellings, one of which had no fallback for a
    name that is nothing but underscores. A rule with three copies is a
    rule with three chances to be fixed in two places.
    """
    parts = PurePosixPath(str(module).replace("\\", "/")).parts
    base = parts[-1].removesuffix(".py")
    base = base.lstrip("_") or base
    folder = parts[-2] if len(parts) >= 2 and parts[-2] != "docxkit" else ""
    return f"{folder}_{base}" if folder else base


def named_after(module: str) -> list[str]:
    """Test files whose NAME claims to be about this module.

    The stem must be followed by `_` or end the name: `test_word.py` and
    `test_word_open.py` are claims about `word.py`, and
    `test_wordcount.py` is not — it is a claim about `wordcount.py`,
    which has an entry of its own.

    **A subpackage half is named with its folder**, as its session is:
    `test_revision_gates.py` is the claim about `revision/_gates.py`.
    The stem was the key itself until 2026-09-17, `revision/_gates`, and
    a glob for `test_revision/_gates*.py` looks in a folder that does not
    exist — so the rule held nothing over the sixteen halves, which was
    harmless only while every half ran the same superset.
    """
    folder, _, name = module.rpartition("/")
    base = name.removesuffix(".py").lstrip("_")
    stem = FACADE.get(module, f"{folder}_{base}" if folder else base)
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

    **A bare stem that names a mapped module is REFUSED**, because the
    fallback is indistinguishable from a hit when the miss is only a
    dropped extension, and the difference is not always safe. Measured
    2026-09-18: `harness_for("lint")` scanned up 6 files where the entry
    names 3, `harness_for("edit")` 17 against 9 — harmless to a census,
    which a wider harness only makes stricter. But `harness_for("find")`
    scanned DOWN, 7 against the entry's 8, and a round measured that way
    is measured against a harness missing a mapped file: it INVENTS
    survivors. That is the instrument defect of `edit.py` and
    `revision/_common.py` arriving by a third road — not a wrong entry,
    but a caller who never reached the entry.

    Nothing in `tools/` is affected: every one of them passes a `.py`
    name. It bites the hand-written scripts a survivor round runs, which
    is where this was found.
    """
    if module in HARNESS:
        return HARNESS[module]
    if f"{module}.py" in HARNESS:
        raise SystemExit(
            f"no module {module!r}; did you mean {module}.py? "
            f"The map is keyed on the file name, and scanning for a "
            f"module that HAS an entry is never what the caller meant.")
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
