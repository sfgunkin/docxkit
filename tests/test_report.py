"""`_report` — the shape every report shares (REVIEW_2026-09-28 §2)."""
from __future__ import annotations

import pytest

from docxkit._report import Finding, Report, Severity, blocking_of, no_truth


def test_a_finding_prints_as_its_code_then_its_message():
    finding = Finding("ANCHOR", "link LOST on accept: -> Smith2020")

    assert str(finding) == "ANCHOR link LOST on accept: -> Smith2020"
    assert finding.severity is Severity.BLOCKING, "blocking unless said"
    assert finding.part == "" and finding.where == ""


def test_only_BLOCKING_findings_block_and_their_order_is_kept():
    kept = [Finding("A", "1"), Finding("B", "2", Severity.WARNING),
            Finding("C", "3", Severity.NOTE), Finding("D", "4")]

    assert [f.code for f in blocking_of(kept)] == ["A", "D"]
    assert Severity.NOTE < Severity.WARNING < Severity.BLOCKING


def test_a_finding_is_a_VALUE():
    finding = Finding("A", "1")

    with pytest.raises(AttributeError):
        finding.code = "B"  # type: ignore[misc]


def test_the_protocol_is_checked_at_runtime_and_a_list_is_not_one():
    class Answers:
        def findings(self) -> list[Finding]:
            return []

        def blocking(self) -> list[Finding]:
            return []

        @property
        def ok(self) -> bool:
            return True

    assert isinstance(Answers(), Report)
    assert not isinstance([], Report)


def test_no_truth_names_the_report_and_the_attribute_to_ask():
    class Thing:
        pass

    refusal = no_truth(Thing(), "`.ok`")

    assert isinstance(refusal, TypeError)
    assert "Thing has no truth value" in str(refusal)
    assert str(refusal).endswith("Ask `.ok` instead.")
