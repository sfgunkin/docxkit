"""`tools/mutate.py` — the curated mutations, and the tree it borrows.

This file did not exist until 2026-08-27, which is most of the story.
The tool applies a known defect to a real source file, runs the suite,
and puts the file back; nothing tested the putting back, and nothing
tested that its anchors still match the code they name.

Both failed, in the same sitting:

* a run that was KILLED left `_set_borders` in `_table_layout.py`
  carrying the nested-borders defect, through an hour of unrelated work
  and into a batch about to be committed — reading, all the while, as
  "my change broke five tests";
* three anchors had drifted, so three curated defects had no regression
  cover. The tool said so and exited 1 on every run, and nothing runs it.

What is tested here is the borrowing: that the tree comes back exactly as
it was, and that a run which cannot come back says which file it left.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the path insert above
# is how its scripts are reached, here and by each other.
import mutate  # noqa: E402  # pyright: ignore[reportMissingImports]

ROOT = Path(docxkit.__file__).resolve().parents[2]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A miniature SRC and stash, so nothing here touches the real tree."""
    src = tmp_path / "src" / "docxkit"
    src.mkdir(parents=True)
    monkeypatch.setattr(mutate, "ROOT", tmp_path)
    monkeypatch.setattr(mutate, "SRC", src)
    monkeypatch.setattr(mutate, "STASH", tmp_path / ".mutate-in-flight")
    return tmp_path, src


# --- the tree comes back EXACTLY -----------------------------------------


def test_the_restore_is_byte_for_byte_with_line_endings(tree, monkeypatch):
    """`read_text` decodes through universal newlines, and the restore
    wrote back with `newline=""` — so every module a run touched came
    back LF in a CRLF checkout. Twelve of them, from one run. Invisible
    here because `core.autocrlf=true` normalises it away; a twelve-file
    whole-file diff on a checkout without it."""
    _root, src = tree
    crlf = b'x = 1\r\ndef f():\r\n    return 2\r\n'
    (src / "thing.py").write_bytes(crlf)
    monkeypatch.setattr(mutate, "MUTATIONS", [mutate.Mutation(
        "thing.py", "the answer changes", "    return 2", "    return 3")])
    monkeypatch.setattr(mutate, "run", lambda tests: (True, "1 failed"))
    monkeypatch.setattr(sys, "argv", ["mutate.py"])

    assert mutate.main() == 0
    assert (src / "thing.py").read_bytes() == crlf


def test_a_CRLF_file_is_still_MUTATED_correctly(tree, monkeypatch):
    """The other half of reading bytes: the anchors are written with
    `\\n`, so a CRLF file has to be matched in LF and written back in
    CRLF. Getting only the first half right would make every multi-line
    anchor drift on a Windows checkout."""
    _root, src = tree
    (src / "thing.py").write_bytes(b'def f():\r\n    return 2\r\n')
    seen: list[bytes] = []

    def _watch(_tests: str) -> tuple[bool, str]:
        """What the suite would have been handed."""
        seen.append((src / "thing.py").read_bytes())
        return True, "1 failed"

    monkeypatch.setattr(mutate, "MUTATIONS", [mutate.Mutation(
        "thing.py", "the answer changes",
        "def f():\n    return 2", "def f():\n    return 3")])
    monkeypatch.setattr(mutate, "run", _watch)
    monkeypatch.setattr(sys, "argv", ["mutate.py"])
    mutate.main()

    assert seen == [b'def f():\r\n    return 3\r\n'], \
        "the mutant keeps the file's own line endings"


# --- a run that cannot come back -----------------------------------------


def test_a_KILLED_run_leaves_the_ORIGINAL_where_the_next_one_finds_it(tree):
    """The stash is written BEFORE the mutation is applied, because the
    whole point is the case where nothing after it runs."""
    _root, src = tree
    (src / "thing.py").write_bytes(b"the original\n")

    mutate.stash(src / "thing.py", b"the original\n")
    (src / "thing.py").write_bytes(b"the MUTANT\n")     # then killed

    assert mutate.in_flight() == [
        (src / "thing.py", mutate.STASH / "thing.py")]


def test_the_next_run_REFUSES_and_names_the_file(tree):
    """Not a warning printed on the way past. A sabotage mutation is by
    construction one the suite can catch, so a leftover reads as a real
    failure — and the run that would tell you otherwise is the one being
    started."""
    _root, src = tree
    (src / "thing.py").write_bytes(b"the MUTANT\n")
    mutate.stash(src / "thing.py", b"the original\n")
    said: list[str] = []

    assert mutate.refuse_if_in_flight(said.append) is True

    told = "\n".join(said)
    assert "thing.py" in told
    assert "Do not commit" in told
    assert "--restore" in told, "a refusal has to name the way through"


def test_a_clean_tree_is_not_refused(tree):
    """The ordinary case, and the one that decides whether this guard
    survives its first week."""
    assert mutate.refuse_if_in_flight(lambda _: None) is False


def test_restore_puts_the_file_back_and_clears_the_stash(tree):
    _root, src = tree
    (src / "thing.py").write_bytes(b"the MUTANT\n")
    mutate.stash(src / "thing.py", b"the original\n")

    mutate.restore(lambda _: None)

    assert (src / "thing.py").read_bytes() == b"the original\n"
    assert mutate.in_flight() == []
    assert not mutate.STASH.exists(), "an empty stash is not a state"


def test_the_stash_is_cleared_on_the_ORDINARY_path_too(tree, monkeypatch):
    """Or the next run refuses on a tree that is perfectly fine, which is
    how a guard gets deleted."""
    _root, src = tree
    (src / "thing.py").write_bytes(b"    return 2\n")
    monkeypatch.setattr(mutate, "MUTATIONS", [mutate.Mutation(
        "thing.py", "the answer changes", "    return 2", "    return 3")])
    monkeypatch.setattr(mutate, "run", lambda tests: (True, "1 failed"))
    monkeypatch.setattr(sys, "argv", ["mutate.py"])

    mutate.main()

    assert mutate.in_flight() == []


# --- the anchors still name the code -------------------------------------


def test_EVERY_anchor_matches_its_module_exactly_once():
    """The gate on the drift itself, over the real tree.

    A curated mutation re-introduces a defect this package has really
    shipped, so a drifted anchor is a defect whose regression cover has
    silently gone. Three had by 2026-08-27 — one because the code changed
    indentation, one because a regex gained a guard, and one because the
    function MOVED to another module, which no amount of reading the
    anchor text would have shown.

    Run here rather than only inside `mutate.py` because this suite is
    what people actually run.
    """
    drifted = []
    for m in mutate.MUTATIONS:
        path = ROOT / "src" / "docxkit" / m.module
        if not path.exists():
            drifted.append(f"{m.label}: no module {m.module}")
            continue
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        found = text.count(m.old)
        if found != 1:
            drifted.append(f"{m.label}: anchor appears {found}x in {m.module}")

    assert not drifted, "\n".join(drifted)


def test_no_two_mutations_share_a_label():
    """The label is how a survivor is reported and how `-k` selects one,
    so two of them are two things nobody can tell apart."""
    labels = [m.label for m in mutate.MUTATIONS]

    assert len(labels) == len(set(labels))
