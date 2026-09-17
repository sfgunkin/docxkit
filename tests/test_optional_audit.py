"""`tools/optional_audit.py` — the gate on an Optional nothing can make.

The defect it exists for is recorded in `revision/_promote.py`:
`PromoteReport.redline` was `Path | None = None` while `promote` either
raised or returned a real path, so `cmd_revision_promote` grew an
`if report.redline is not None:` that nothing could take. The second of
that shape was found in the same file the same afternoon.

What is tested here is the JUDGEMENT, not the walk: that the fake
Optional is named and the honest one beside it is not, that the six
things this codebase does which a reading by eye gets wrong are not
reported as findings, and that an Optional nobody reads is not a
failure — which is what keeps the gate off ordinary work.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the path insert above
# is what makes this import work, as it does in `test_backlog_refs.py`.
import optional_audit  # noqa: E402  # pyright: ignore[reportMissingImports]

#: The shape the tool exists for, and the honest Optional beside it —
#: `promote` either raises or returns the redline it made, while a batch
#: really can be unstamped.
PROMOTE = '''
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromoteReport:
    redline: Path | None = None
    stamp: Path | None = None


def _stamp_of(where: Path) -> Path | None:
    return where if where.exists() else None


def promote(out: Path) -> PromoteReport:
    return PromoteReport(redline=out / "r.docx", stamp=_stamp_of(out))


def cmd_promote(report: PromoteReport) -> str:
    said = ""
    if report.redline is not None:
        said = f"wrote {report.redline}"
    if report.stamp is not None:
        said += " stamped"
    return said
'''


def run(tmp_path: Path, source: str, *, tests: str = "",
        module: str = "thing.py") -> tuple[int, str]:
    """The tool over one synthetic package; its count and what it said."""
    src = tmp_path / "src" / "docxkit"
    src.mkdir(parents=True, exist_ok=True)
    (src / module).write_text(source, encoding="utf-8")
    callers = []
    if tests:
        folder = tmp_path / "tests"
        folder.mkdir(exist_ok=True)
        (folder / "test_it.py").write_text(tests, encoding="utf-8")
        callers = [folder / "test_it.py"]
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        count = optional_audit.audit(sorted(src.glob("*.py")),
                                     callers=callers)
    return count, said.getvalue()


def test_an_optional_NOTHING_constructs_is_the_finding(tmp_path):
    """The recorded defect, in miniature: every call passes a real path,
    so `redline is not None` is a branch that cannot be taken."""
    count, said = run(tmp_path, PROMOTE)

    assert count == 1
    assert "PromoteReport.redline" in said
    assert "report.redline is not None" in said, \
        "the dead branch is the point — name it, not just the field"


def test_the_HONEST_optional_beside_it_is_not(tmp_path):
    """`stamp` is `Path | None` because an unstamped batch is real, and
    `_stamp_of` is what makes one. A pass that cannot tell these two
    apart would be an allowlist with extra steps."""
    _count, said = run(tmp_path, PROMOTE)

    assert "PromoteReport.stamp" not in said.split(
        "and the ones something DOES make None")[0]


def test_an_optional_NOBODY_reads_is_listed_but_not_FAILED(tmp_path):
    """A field added today, with no test exercising it yet and no guard
    reading it: an annotation nobody has been misled by. Failing here
    would fail every Optional written before its first test, which is a
    toll on ordinary work rather than the defect."""
    fresh = PROMOTE.replace(
        "    stamp: Path | None = None",
        "    stamp: Path | None = None\n    fresh: int | None = None",
    ).replace("stamp=_stamp_of(out))", "stamp=_stamp_of(out), fresh=3)")

    count, said = run(tmp_path, fresh)

    assert count == 1, "the redline, and not the fresh field"
    assert "PromoteReport.fresh" in said
    assert "nothing has been misled yet" in said


def test_a_default_only_the_TESTS_omit_is_not_a_finding(tmp_path):
    """The suite is a caller like any other: a default no shipped code
    omits, omitted by one test, is a live branch. `--callers` is how the
    question "who can reach this" is asked of more than `src`."""
    alone, _said = run(tmp_path, PROMOTE)
    with_tests, _said = run(tmp_path, PROMOTE, tests=(
        "from docxkit.thing import PromoteReport\n\n\n"
        "def test_a_report_with_no_redline():\n"
        "    assert PromoteReport().redline is None\n"))

    assert (alone, with_tests) == (1, 0)


def test_a_RETURN_no_path_makes_None_is_a_finding(tmp_path):
    """The same claim one level along: the caller tests the result, and
    the test cannot fail."""
    count, said = run(tmp_path, '''
from __future__ import annotations


def only_name(x: str) -> str | None:
    return x.strip()


def read(x: str) -> str:
    found = only_name(x)
    if found is None:
        return "nothing"
    return found
''')

    assert count == 1
    assert "only_name" in said


#: The six things this package does that a reading by eye — and the
#: first six versions of this tool — get wrong the same way. Each of
#: these IS optional; none of them may be reported.
NOT_FINDINGS = {
    # no `return None` anywhere in it: the None comes back from lxml, and
    # a fixture that spells one out would pass with the rule removed
    "lxml_navigation": '''
from __future__ import annotations
from lxml import etree


def next_content(el: etree._Element) -> etree._Element | None:
    nxt = el.getnext()
    while nxt is not None and nxt.tag == "marker":
        nxt = nxt.getnext()
    return nxt


def paragraph_or_table(el: etree._Element | None) -> etree._Element | None:
    while el is not None and el.tag != "p":
        el = el.getnext()
    return el


def read(el: etree._Element) -> str:
    found = next_content(el)
    if found is None:
        return "nothing follows"
    return str(paragraph_or_table(found.getnext()))
''',
    "an_optional_property": '''
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Landing:
    first: int
    mention: int

    @property
    def drift(self) -> int | None:
        return None if self.first < 0 else self.first - self.mention


@dataclass(frozen=True)
class Move:
    drift_before: int | None


def move(z: Landing) -> Move:
    made = Move(drift_before=z.drift)
    if made.drift_before is None:
        return Move(drift_before=0)
    return made
''',
    "a_classmethod_constructor": '''
from __future__ import annotations
import re
from typing import NamedTuple


class Scaffold(NamedTuple):
    date_utc: str | None

    @classmethod
    def read(cls, xml: str) -> "Scaffold":
        found = re.search(r'dateUtc="([^"]+)"', xml)
        return cls(date_utc=found.group(1) if found else None)


def say(s: Scaffold) -> str:
    return "" if s.date_utc is None else s.date_utc
''',
    "a_tuple_unpacked": '''
from __future__ import annotations
from typing import NamedTuple


class Sheet(NamedTuple):
    printed: int | None


def printed_number(page: str) -> tuple[int | None, str | None]:
    return (None, None) if not page else (1, "lower right")


def read(page: str) -> Sheet:
    printed, _corner = printed_number(page)
    sheet = Sheet(printed=printed)
    if sheet.printed is None:
        return Sheet(printed=0)
    return sheet
''',
    "a_tuple_indexed": '''
from __future__ import annotations


def explain(prop: str) -> tuple[str | None, list[str]]:
    return (None, []) if not prop else (prop, [prop])


def of(prop: str) -> str | None:
    return explain(prop)[0]


def read(prop: str) -> str:
    got = of(prop)
    if got is None:
        return "unset"
    return got
''',
    "a_loop_over_optionals": '''
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Landing:
    mention: int | None


def sheet_of(index: int | None) -> int | None:
    if index is None:
        return None
    return index + 1


def land(mentions: list[int | None]) -> list[Landing]:
    out = []
    for index in mentions:
        out.append(Landing(mention=sheet_of(index)))
    return out
''',
}


@pytest.mark.parametrize("shape", sorted(NOT_FINDINGS))
def test_what_a_reading_by_EYE_gets_wrong_is_not_reported(shape, tmp_path):
    """Nine of the first ten candidates this tool produced were its own
    ignorance. Each of these is one of them, kept so the next rule added
    here cannot quietly lose one."""
    count, said = run(tmp_path, NOT_FINDINGS[shape])

    assert count == 0, said


def test_the_EXIT_code_is_one_and_never_the_count(tmp_path):
    """`gates.py` reads exit 3 as "I did not run", so a run that found
    exactly three findings must not report as a skip — a failure printed
    as a shrug is the one outcome a gate may not have."""
    src = tmp_path / "src" / "docxkit"
    src.mkdir(parents=True)
    three = "\n\n".join(
        PROMOTE.replace("PromoteReport", f"Report{n}")
               .replace("promote", f"promote{n}")
               .replace("_stamp_of", f"_stamp_of{n}")
               .replace("cmd_", f"cmd{n}_")
        for n in range(3))
    (src / "three.py").write_text(three, encoding="utf-8")

    assert optional_audit.main([str(src / "three.py")]) == 1
