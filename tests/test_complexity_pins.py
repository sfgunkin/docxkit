"""`tools/complexity_pins.py` — the re-measurement, held to what it claims.

The tool exists for ONE state the gate in `test_complexity_debt.py`
cannot see: a pin that SHRANK. `test_the_pinned_functions_have_not_grown`
is one-directional by design, so a function simplified under its pin
stays green while the recorded number overstates it — which is how three
of five entries came to be wrong on 2026-09-03, one of them for ten days.

So the tests that matter here are the SHRANK line, and the exit code:
this tool must not become the exact-equality gate that was considered
and rejected, and a `return 1` added in passing is exactly how it would.
"""
from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

import docxkit

ROOT = pathlib.Path(docxkit.__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PINS = _load("complexity_pins", ROOT / "tools" / "complexity_pins.py")
GATE = _load("complexity_debt", ROOT / "tests" / "test_complexity_debt.py")
Pin = GATE.Pin

TODAY = "2026-09-05"


def _report(now, debt):
    return "\n".join(PINS.report(now, debt, TODAY))


def test_a_pin_that_SHRANK_is_named_as_overstating_its_function():
    """The finding the tool is for. Nothing else in the repository
    reports it: the gate is green on a shrunken pin by design."""
    out = _report({"edit.replace_in_para": 24},
                  {"edit.replace_in_para": Pin(26, "2026-08-23")})

    assert "SHRANK" in out
    assert "26 -> 24" in out
    assert "2026-08-23" in out, "the reader needs the pin's age to judge it"
    assert "OVERSTATES" in out


def test_a_pin_that_GREW_is_reported_as_the_gate_being_red():
    """The opposite direction is already gated, so the tool's job is to
    say so rather than to look like a second, disagreeing verdict."""
    out = _report({"lint.lint": 31}, {"lint.lint": Pin(28, "2026-08-23")})

    assert "GREW" in out
    assert "28 -> 31" in out
    assert "red" in out


def test_an_unpinned_function_over_the_threshold_reads_as_NEW():
    out = _report({"body.table": 22}, {})

    assert "NEW" in out and "body.table" in out


def test_a_function_no_longer_over_the_threshold_reads_as_PAID():
    out = _report({}, {"refstyle.audit": Pin(25, "2026-09-03")})

    assert "PAID" in out
    assert "delete the pin" in out


def test_an_unchanged_number_is_reported_as_CONFIRMED_not_as_unmeasured():
    """A number re-measured today is a fresher fact than the same number
    pinned in the spring, and the line says which."""
    out = _report({"lint.lint": 28}, {"lint.lint": Pin(28, "2026-08-23")})

    assert "same" in out
    assert "confirmed today" in out
    assert "2026-08-23" in out


def test_the_dict_it_prints_PARSES_BACK_to_what_it_measured():
    """The paste-ready block is the tool's only output that gets copied
    into code, so its format is a contract with `DEBT` — and with the
    `Pin` in the gate, which is the one imported here to evaluate it."""
    now = {"edit.replace_in_para": 24, "lint.lint": 28}

    block = PINS.paste(now, TODAY)
    namespace = {"Pin": Pin, "dict": dict, "str": str}
    exec(compile(block, "<paste>", "exec"), namespace)

    assert namespace["DEBT"] == {"edit.replace_in_para": Pin(24, TODAY),
                                 "lint.lint": Pin(28, TODAY)}


def test_every_pasted_date_is_the_day_of_the_WALK_not_the_pin():
    """Including the ones whose number did not move. The field records
    when the measurement was taken; carrying an old date forward on an
    unchanged number would re-create the staleness the tool is for."""
    block = PINS.paste({"lint.lint": 28}, TODAY)

    assert f'Pin(28, "{TODAY}")' in block
    assert "2026-08-23" not in block


def test_an_empty_measurement_prints_the_EMPTY_literal():
    """So the paste is valid in the state the file is actually in."""
    assert PINS.paste({}, TODAY) == "DEBT: dict[str, Pin] = {}"


def test_it_exits_0_on_STALE_pins_because_it_is_not_a_gate(monkeypatch,
                                                           capsys):
    """The deliberate non-gate. A non-zero exit here is one line in
    `tools/gates.py` away from becoming the exact-equality gate the
    complexity note rejected — red on every incidental simplification,
    which teaches people to edit the number without reading it."""
    monkeypatch.setattr(PINS, "_gate", lambda: SimpleNamespace(
        _over_threshold=lambda: {"edit.replace_in_para": 24},
        DEBT={"edit.replace_in_para": Pin(26, "2026-08-23")},
        MAX_COMPLEXITY=20))

    code = PINS.main()

    out = capsys.readouterr().out
    assert code == 0, "reporting staleness must not fail a build"
    assert "SHRANK" in out
    assert "overstate" in out, "and it must still SAY the pins are stale"


def test_it_reports_rather_than_crashes_when_ruff_will_not_run(monkeypatch,
                                                              capsys):
    """`_over_threshold` skips the test when ruff cannot run, and a skip
    outside a test is an exception that would otherwise be a traceback."""
    def _skipping():
        pytest.skip("ruff did not run: no such module")

    monkeypatch.setattr(PINS, "_gate", lambda: SimpleNamespace(
        _over_threshold=_skipping, DEBT={}, MAX_COMPLEXITY=20))

    code = PINS.main()

    assert code == 0
    assert "could not measure" in capsys.readouterr().out


def test_the_empty_state_says_why_that_is_the_STRONGEST_reading(monkeypatch,
                                                                capsys):
    """With DEBT empty the gate reads "no function exceeds 20" rather
    than "no NEW one does" — a reader meeting an empty report should not
    conclude the tool found nothing to say."""
    monkeypatch.setattr(PINS, "_gate", lambda: SimpleNamespace(
        _over_threshold=dict, DEBT={}, MAX_COMPLEXITY=20))

    PINS.main()

    assert "nothing over the threshold" in capsys.readouterr().out
