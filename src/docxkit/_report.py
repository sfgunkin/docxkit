"""What a check found, as one shape every report can share.

The package's most repeated lesson is "a report that reads as success",
and until 2026-09-29 the architecture did not help it: 108 result types,
no shared base, no severity, and truthiness that ran BOTH ways — a
`refstyle` report was truthy when something CHANGED, `RowsReport` when
the check PASSED. Which of `BuildReport`'s 17 lists block was known in
one refusal function, and `compare-probe` re-derived it wrong
(REVIEW_2026-09-28 §2).

So a report says what it found as :class:`Finding` values with a
:class:`Severity`, and whether it blocks is derived from them rather than
re-decided by each reader. :class:`Report` is the protocol; a report
adopts it when it is next touched, the ones the CLI prints first.

A report has NO truth value (:func:`no_truth`): `if report:` has meant
opposite things in two modules, and a reader should name the question —
``.ok``, ``.changed``, ``.moved`` — rather than guess it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol, runtime_checkable

__all__ = ["Finding", "Report", "Severity", "blocking_of", "no_truth"]


class Severity(IntEnum):
    """How much a finding matters to whoever acts on the report."""

    #: Worth saying; changes nothing. What a build repaired or carried.
    NOTE = 0
    #: Worth a person's look; the operation still went ahead.
    WARNING = 1
    #: The operation refused, or would have under its default switches.
    BLOCKING = 2


@dataclass(frozen=True)
class Finding:
    """One thing a check found.

    `code` is short and stable — what a script matches on, and the label
    a report prints in front of the message (``ANCHOR``, ``LINT``).
    `part` and `where` locate it when the check knows: the package part,
    and a paragraph, a table, a line.
    """

    code: str
    message: str
    severity: Severity = Severity.BLOCKING
    part: str = ""
    where: str = ""

    def __str__(self) -> str:
        return f"{self.code} {self.message}"


@runtime_checkable
class Report(Protocol):
    """A result whose verdict is derived from what it found."""

    def findings(self) -> list[Finding]:
        """Everything found, every severity, in the order it matters."""
        ...

    def blocking(self) -> list[Finding]:
        """The findings of :attr:`Severity.BLOCKING` severity."""
        ...

    @property
    def ok(self) -> bool:
        """Nothing blocks."""
        ...


def blocking_of(findings: list[Finding]) -> list[Finding]:
    """The blocking ones — the one place that rule is written."""
    return [f for f in findings if f.severity is Severity.BLOCKING]


def no_truth(report: object, instead: str) -> TypeError:
    """The refusal of `bool(report)`, naming the attribute that answers.

    A report's `__bool__` raises it: ``raise no_truth(self, "`.ok`")``.
    Raising, rather than removing the method: without it every report is
    simply truthy, and an `if report:` written against the old meaning
    would go on running with a new one, silently. This way it stops,
    once, and says what to write.
    """
    return TypeError(
        f"{type(report).__name__} has no truth value — `if report:` has "
        f"meant 'passed' in one module and 'changed' in another. Ask "
        f"{instead} instead.")
