"""`tools/oracle_reach.py` — does an oracle reach what a change changed?

The case that made it: e84596f rewrote `tables.house`, `crossrefs.link`
and `citations.link_all`, and the writer oracle of the day probed
`set_cell` and `insert_before` only. Run as CONTRIBUTING said, it would
have reported "0 differ" about writers the batch never touched. These
tests hold the gate to that case with BOTH sides read from git, so a
later edit to `src` cannot move them, and pin the rules on synthetic
packages.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import oracle_reach as reach  # noqa: E402  # pyright: ignore[reportMissingImports]

BEFORE = "c9b2081"      # the commit before the batch
BATCH = "e84596f"       # the batch: house, crossrefs, link_all, renumber


def _oracle_at(rev: str, tmp_path: Path) -> Path:
    """`tools/writer_oracle.py` as it stood at `rev`."""
    out = tmp_path / f"writer_oracle_{rev}.py"
    blob = subprocess.run(
        ["git", "-C", str(reach.ROOT), "show",
         f"{rev}:tools/writer_oracle.py"],
        capture_output=True, check=True).stdout
    out.write_bytes(blob)
    return out


@pytest.fixture(scope="module")
def sides() -> tuple[dict[str, reach.Module], dict[str, reach.Module]]:
    return reach.load_rev(BEFORE), reach.load_rev(BATCH)


def test_the_gate_FAILS_on_the_batch_when_the_writers_had_no_probe(
        sides, tmp_path):
    """The oracle of the day: two probes. Every helper of the new `house`
    and the first-mention fix in `link_all` is unmeasured, and each names
    the PUBLIC writer a probe goes on — `tables.house`, not the private
    module it is defined in, and the engine ahead of the CLI command."""
    base, head = sides
    old = _oracle_at(BEFORE, tmp_path)

    v = reach.check(base, head, oracles=(old, reach.HERE / "sweep.py"))

    unmeasured = dict(v.unmeasured)
    for helper in ("_house_cell", "_house_run", "_house_para",
                   "_header_rows"):
        node = f"docxkit._table_layout:{helper}"
        assert node in unmeasured, sorted(unmeasured)
        assert "docxkit.tables:house" in unmeasured[node]
    first_plain = unmeasured["docxkit._cite_build:_link_first_plain"]
    assert first_plain[0] == "docxkit.citations:link_all", first_plain
    assert "docxkit.renumber:<_CONTINUATION>" in unmeasured
    assert "docxkit.crossrefs:_past_leading_breaks" in unmeasured


def test_the_probes_added_since_MEASURE_the_same_batch(sides):
    """Today's oracles: what the old one could not see is reached — the
    house helpers through `probe_house`, the renumber constant through
    `probe_renumber`, `house_rpr` through `probe_builders`."""
    base, head = sides

    v = reach.check(base, head)

    reached = set(v.reached)
    for node in ("docxkit._table_layout:_house_cell",
                 "docxkit._table_layout:house_rpr",
                 "docxkit._cite_build:_link_first_plain",
                 "docxkit.crossrefs:_past_leading_breaks",
                 "docxkit.renumber:<_CONTINUATION>"):
        assert node in reached, node
    # the CLI half of the batch is exempt, with its reason, not unmeasured
    assert any(n.startswith("docxkit.cli:") for n, _ in v.exempt)
    assert v.unmeasured == [], v.unmeasured


# --- the rules, on synthetic packages ------------------------------------


def _package(**modules: str) -> dict[str, reach.Module]:
    return {f"docxkit.{name}": reach.parse(f"docxkit.{name}", src)
            for name, src in modules.items()}


WRITER = '''
def tidy(xml):
    """Public writer."""
    return _fix(xml)

def _fix(xml):
    return xml.strip()
'''


def _oracle(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "oracle.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_a_changed_helper_no_oracle_calls_is_UNMEASURED(tmp_path):
    base = _package(w=WRITER)
    head = _package(w=WRITER.replace("xml.strip()", "xml.rstrip()"))
    silent = _oracle(tmp_path, "from docxkit import other\n")

    v = reach.check(base, head, oracles=(silent,))

    assert v.unmeasured == [("docxkit.w:_fix", ["docxkit.w:tidy"])]


def test_the_same_change_is_REACHED_once_a_probe_calls_its_writer(tmp_path):
    base = _package(w=WRITER)
    head = _package(w=WRITER.replace("xml.strip()", "xml.rstrip()"))
    probe = _oracle(tmp_path, "def probe(xml):\n"
                              "    from docxkit.w import tidy\n"
                              "    return tidy(xml)\n")

    v = reach.check(base, head, oracles=(probe,))

    assert v.reached == ["docxkit.w:_fix"] and v.unmeasured == []


def test_a_writer_reached_through_a_REEXPORT_and_a_module_attribute(
        tmp_path):
    """`tables.house` is `_table_layout.house` re-exported, and probes
    call it as an attribute of the public module."""
    base = _package(_impl=WRITER, pub="from ._impl import tidy as tidy\n")
    head = _package(_impl=WRITER.replace("strip()", "rstrip()"),
                    pub="from ._impl import tidy as tidy\n")
    probe = _oracle(tmp_path, "from docxkit import pub\n"
                              "def p(x):\n    return pub.tidy(x)\n")

    assert reach.check(base, head, oracles=(probe,)).reached == [
        "docxkit._impl:_fix"]
    silent = _oracle(tmp_path, "")
    (node, callers), = reach.check(base, head, oracles=(silent,)).unmeasured
    assert (node, callers) == ("docxkit._impl:_fix", ["docxkit.pub:tidy"])


def test_a_changed_CONSTANT_is_reached_through_the_function_reading_it(
        tmp_path):
    """renumber's `_CONTINUATION` changed and no function body did."""
    src = 'PAT = "a"\ndef shift(x):\n    return x.split(PAT)\n'
    base = _package(r=src)
    head = _package(r=src.replace('"a"', '"b"'))

    reached = reach.check(base, head, oracles=(_oracle(
        tmp_path, "from docxkit.r import shift\n"),))
    unreached = reach.check(base, head, oracles=(_oracle(tmp_path, ""),))

    assert reached.reached == ["docxkit.r:<PAT>"]
    assert unreached.unmeasured == [("docxkit.r:<PAT>", ["docxkit.r:shift"])]


def test_a_method_is_reached_by_its_NAME_on_any_object(tmp_path):
    """`report.format()` names no class; over-approximating is the safe
    direction for a gate a false failure would get switched off."""
    src = ("class Report:\n    def format(self):\n        return 'a'\n"
           "def run():\n    return Report()\n")
    base = _package(m=src)
    head = _package(m=src.replace("'a'", "'b'"))
    probe = _oracle(tmp_path, "def p(rep):\n    return rep.format()\n")

    assert reach.check(base, head, oracles=(probe,)).reached == [
        "docxkit.m:Report.format"]


def test_a_DOCSTRING_or_comment_change_is_no_change():
    src = WRITER
    edited = WRITER.replace('"""Public writer."""',
                            '"""Public writer, reworded."""  # and noted')
    assert reach.changed(_package(w=src), _package(w=edited)) == []


def test_a_change_in_an_EXEMPT_module_says_why_and_does_not_fail(tmp_path):
    src = "def cmd(x):\n    return 1\n"
    base = {"docxkit.cli": reach.parse("docxkit.cli", src)}
    head = {"docxkit.cli": reach.parse("docxkit.cli",
                                       src.replace("1", "2"))}

    v = reach.check(base, head, oracles=(_oracle(tmp_path, ""),))

    assert v.unmeasured == []
    assert v.exempt == [("docxkit.cli:cmd", reach.EXEMPT["docxkit.cli"])]


def test_a_NEW_function_counts_as_changed():
    base = _package(w="def a():\n    return 1\n")
    head = _package(w="def a():\n    return 1\ndef b():\n    return 2\n")
    assert reach.changed(base, head) == ["docxkit.w:b"]


def test_main_exits_1_and_names_the_writer(monkeypatch, capsys, tmp_path):
    base = _package(w=WRITER)
    head = _package(w=WRITER.replace("strip()", "rstrip()"))
    monkeypatch.setattr(reach, "load_rev", lambda rev: base)
    monkeypatch.setattr(reach, "load_tree", lambda: head)
    monkeypatch.setattr(reach, "ORACLES", (_oracle(tmp_path, ""),))

    code = reach.main(["--base", "X"])

    out = capsys.readouterr().out
    assert code == 1
    assert "1 UNMEASURED" in out
    assert "UNMEASURED docxkit.w:_fix  (reached from: tidy)" in out
