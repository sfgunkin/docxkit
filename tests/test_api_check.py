"""`tools/api_check.py` — the gate that asks what a CALLER would notice.

What is tested here is the JUDGEMENT, not griffe: which baseline it
picks, which findings it treats as breaking, and that a comparison
against nothing says so instead of printing the word a clean one prints.
Loading two versions of the package through git is griffe's job and it
has its own suite; doing it here would spend two worktrees per test to
re-check somebody else's code.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import api_check  # pyright: ignore[reportMissingImports]

#: `(kind, explanation, is-consumed)` — the third is the tier added on
#: 2026-09-01: a breakage in a name `tools/consumers.txt` says a paper
#: imports fails the gate; the same breakage elsewhere in the 626-name
#: public surface is reported so an internal rename does not cost a
#: release. Both axes have to say "break" before the exit code does.
BREAKING = ("PARAMETER_REMOVED", "src/docxkit/x.py:1: f(a): Parameter "
                                 "was removed: a", True)
UNUSED = ("PARAMETER_REMOVED", "src/docxkit/y.py:1: g(a): Parameter "
                               "was removed: a", False)
VALUE = ("ATTRIBUTE_CHANGED_VALUE", "src/docxkit/x.py:1: GATED: Attribute "
                                    "value was changed: (1,) -> (1, 2)",
         True)


@pytest.fixture
def found(monkeypatch):
    """Let a test say what griffe returned, without running it."""
    def use(*findings):
        monkeypatch.setattr(api_check, "compare",
                            lambda _ref: list(findings))
        monkeypatch.setattr(api_check, "baseline",
                            lambda _explicit=None: ("v1.0.0", "the tag"))
        monkeypatch.setattr(sys, "argv", ["api_check.py"])
    return use


def test_a_removed_parameter_FAILS_the_gate(found, capsys):
    found(BREAKING)

    code = api_check.main()

    out = capsys.readouterr().out
    assert code == 1
    assert "BREAKING" in out and "Parameter was removed" in out
    assert "1 breaking, 0 in names no paper imports, 0 value" in out


def test_a_changed_CONSTANT_is_reported_and_does_not_fail(found, capsys):
    """The measurement this gate was designed around: 21 findings over
    fourteen commits, every one of them a constant's value, none of them
    breaking. Failing on those would have made the gate red on half of
    that history for the ordinary act of adding a member to a data
    table — and this package's public constants ARE data tables."""
    found(VALUE)

    code = api_check.main()

    out = capsys.readouterr().out
    assert code == 0, "a data table gaining a member is not a break"
    assert "value" in out and "GATED" in out, "and it is still SHOWN"
    assert "0 breaking, 0 in names no paper imports, 1 value" in out


def test_the_kinds_are_counted_apart_when_all_are_present(found, capsys):
    found(BREAKING, UNUSED, VALUE)

    assert api_check.main() == 1
    assert ("1 breaking, 1 in names no paper imports, 1 value"
            in capsys.readouterr().out)


def test_the_same_breakage_in_an_UNCONSUMED_name_does_not_fail(found,
                                                               capsys):
    """The tier, and the reason it is derived from the papers rather
    than chosen: `edit.replace_in_para` losing a parameter exits 1 and
    `footnotes.orphans` losing one exits 0 — measured by breaking both
    on 2026-09-01. Guarding all 626 names equally makes an internal
    rename cost a release, and a gate that costs that is one people
    learn to push past."""
    found(UNUSED)

    code = api_check.main()

    out = capsys.readouterr().out
    assert code == 0, "no paper imports it; the break reaches nobody"
    assert "unused" in out and "was removed" in out, "and it is still SHOWN"
    assert "Refresh that snapshot" in out


def test_a_clean_comparison_says_so_and_names_the_baseline(found, capsys):
    found()

    assert api_check.main() == 0
    out = capsys.readouterr().out
    assert "no API differences at all" in out
    assert "v1.0.0" in out, "a reader cannot judge an answer without it"


def test_with_no_baseline_it_SKIPS_rather_than_inventing_one(monkeypatch,
                                                             capsys):
    """The `sweep` lesson in the gate beside it: a comparison against
    nothing and a comparison against the last release must not print the
    same word. Exit 3 is what `tools/gates.py` renders as `skip`."""
    monkeypatch.setattr(api_check, "baseline", lambda _explicit=None: None)
    monkeypatch.setattr(sys, "argv", ["api_check.py"])

    code = api_check.main()

    assert code == api_check.SKIPPED == 3
    out = capsys.readouterr().out
    assert "no baseline" in out and "git tag" in out


# --------------------------------------------------- choosing a baseline


def test_an_explicit_ref_wins(monkeypatch):
    monkeypatch.setattr(api_check, "_git", lambda *a: "should not be asked")

    assert api_check.baseline("abc1234") == ("abc1234", "asked for")


def test_a_TAG_is_preferred_to_the_upstream_branch(monkeypatch):
    """A release is what a consumer would have pinned."""
    monkeypatch.setattr(api_check, "_git",
                        lambda *a: "v2.0" if "describe" in a else "origin/x")

    chosen = api_check.baseline()

    assert chosen is not None
    ref, why = chosen
    assert ref == "v2.0" and "tag" in why


def test_the_upstream_branch_is_the_fallback(monkeypatch):
    """This repo has no tags, and the papers import the TIP from an
    editable install — so "does my tree break what is already pushed?"
    is the live form of the question here."""
    monkeypatch.setattr(api_check, "_git",
                        lambda *a: "" if "describe" in a else "origin/master")

    chosen = api_check.baseline()

    assert chosen is not None
    ref, why = chosen
    assert ref == "origin/master" and "upstream" in why


def test_with_neither_there_is_no_baseline(monkeypatch):
    monkeypatch.setattr(api_check, "_git", lambda *a: "")

    assert api_check.baseline() is None


def test_the_colour_codes_griffe_writes_are_stripped():
    """The gate's output is read in a CI log as often as in a terminal,
    and `tools/gates.py` captures it either way."""
    assert api_check._plain("\x1b[1msrc/x.py\x1b[0m: \x1b[33mgone\x1b[39m") \
        == "src/x.py: gone"
