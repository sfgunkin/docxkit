r"""`tools/heredoc_guard.py` — the gate on the trap that keeps winning.

Seven occurrences across two agents sharing one tree, the worst of them
rewriting 387 real newlines in a file the other session was editing. The
rule was written down three times and walked into anyway, so what is
tested here is the thing the rule could not be: a refusal that does not
depend on anybody remembering.

The other half of the job is not blocking anything else. This
environment's commands are full of Windows paths, and a guard that
refuses `python "C:\Users\..."` would be turned off within the hour.
"""
from __future__ import annotations

import io
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the path insert above
# is how its scripts are reached, here and by each other.
from heredoc_guard import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    bodies,
    main,
    offending,
)


def _run(command: str, tool: str = "Bash") -> tuple[int, str]:
    """The hook, as the harness invokes it: JSON in, status out."""
    call = {"tool_name": tool, "tool_input": {"command": command}}
    stdin, stderr = sys.stdin, sys.stderr
    sys.stdin = io.StringIO(json.dumps(call))
    sys.stderr = io.StringIO()
    try:
        return main(), sys.stderr.getvalue()
    finally:
        sys.stdin, sys.stderr = stdin, stderr


HEREDOC = "python - <<'PY'\n{body}\nPY"


def test_a_backslash_in_a_heredoc_body_is_REFUSED():
    """The case that has cost the most: a `str.replace` payload
    rewriting escapes, where `\\\\n` arrives halved and the search
    string then matches every real newline instead of nothing."""
    code, said = _run(HEREDOC.format(
        body='s = s.replace("a\\\\nb", "c")'))

    assert code == 2, "2 is the status that BLOCKS the call"
    assert "must not contain a backslash" in said
    assert "Write tool" in said, "a refusal has to name the way through"


def test_the_QUOTED_form_is_refused_too_because_quoting_does_not_help():
    """`<<'PY'` is POSIX-quoted and specified to pass its body through
    untouched. Measured on this path, it halves doubled backslashes
    anyway — so the quoted form is the dangerous one, being the form
    that looks safe."""
    quoted, _ = _run("python - <<'PY'\nx = '\\\\n'\nPY")
    bare, _ = _run("python - <<PY\nx = '\\\\n'\nPY")

    assert quoted == 2 and bare == 2


def test_a_WINDOWS_PATH_in_the_command_is_not_a_heredoc_body():
    """The commands here are full of these, and a guard that blocks them
    is a guard that gets removed. Only text BETWEEN the delimiters is
    judged."""
    code, _ = _run(r'python "C:\Users\Ezhik\scratch\probe.py" && ls')

    assert code == 0


def test_a_heredoc_with_no_backslash_is_left_alone():
    """Commit messages, SQL, prose — the form is not the problem."""
    code, _ = _run("git commit -F - <<'MSG'\nA subject line\n\nA body.\nMSG")

    assert code == 0


def test_a_backslash_AFTER_the_heredoc_closes_is_not_the_body():
    """The delimiter ends the body, so a line continuation in the shell
    command that follows is nothing to do with the payload."""
    code, _ = _run("python - <<'PY'\nprint(1)\nPY\ncp a.txt \\\n  b.txt")

    assert code == 0


def test_the_SECOND_heredoc_is_judged_as_well_as_the_first():
    """One command, two payloads: the repair-with-another-heredoc shape
    that turned a three-line breakage into a 387-line one."""
    command = ("python - <<'PY'\nprint(1)\nPY\n"
               "python - <<'PY2'\nx = '\\\\n'\nPY2")

    assert _run(command)[0] == 2


def test_a_delimiter_that_only_STARTS_a_line_does_not_close_the_body():
    """`PY` closes; `PYTHON` does not, and neither does `PY` with
    anything after it. Reading the wrong line as the close would end the
    body early and let the rest through unjudged."""
    (body,) = bodies("python - <<'PY'\nPYTHON = 1\nPY_ALSO = 2\nPY\nrest")

    assert body == "PYTHON = 1\nPY_ALSO = 2"


def test_a_tool_that_is_not_BASH_is_not_this_hook_s_business():
    """The Write tool is the REMEDY. A guard that judged its content
    would refuse the way out of its own refusal."""
    code, _ = _run("x = '\\\\n'", tool="Write")

    assert code == 0


def test_malformed_input_does_not_block_the_session():
    """A hook that raises on unexpected stdin turns one bad frame into a
    shell that cannot be used. Staying out of the way is the safe
    default here, because the thing being guarded is a mistake and not
    an attack."""
    stdin = sys.stdin
    sys.stdin = io.StringIO("not json at all")
    try:
        assert main() == 0
    finally:
        sys.stdin = stdin


def test_offending_names_the_body_it_objected_to():
    """The reader has to be able to see WHICH payload, since the shape
    that caused the worst incident was two heredocs in one command."""
    assert offending("python - <<'PY'\nclean = 1\nPY") is None
    assert offending(HEREDOC.format(body="x = '\\\\'")) == "x = '\\\\'"


# --- the half the function cannot test: is it WIRED to anything? ---------
#
# Found 2026-08-27. The guard was written, tested, and registered nowhere
# that a session outside this repo would read — so the trap it exists to
# refuse was walked into twice while the entry about it was being closed,
# the eighth and ninth occurrences, one of them writing a file that would
# not parse at all. Every test above passed on both of those runs,
# because each of them measured a function nobody was calling.
#
# A green suite over a gate that cannot fire is the false confidence this
# package ranks above a wrong answer. So the registration is asserted as
# well as the behaviour.


def _hooked(settings: dict[str, Any], tool: str = "Bash") -> list[str]:
    """The PreToolUse commands that would run for `tool`.

    An entry with no matcher, or ``*``, runs for everything; anything
    else is a regex against the tool name, which is how the harness
    reads it.
    """
    out = []
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        pattern = entry.get("matcher", "")
        if pattern and pattern != "*" and not re.search(pattern, tool):
            continue
        out += [h.get("command", "") for h in entry.get("hooks", [])
                if h.get("type") == "command"]
    return out


def _settings(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} is not an object"
    return loaded


def _user_settings() -> list[Path]:
    home = Path.home() / ".claude"
    return [p for p in (home / "settings.json", home / "settings.local.json")
            if p.exists()]


def test_THIS_repo_registers_the_guard_for_sessions_rooted_here():
    """`.claude/settings.json` is committed, so this is a repo invariant
    rather than a fact about one machine: a session working on docxkit
    gets the refusal whether or not anybody remembered to install it."""
    path = TOOLS.parent / ".claude" / "settings.json"

    assert path.exists(), f"{path} is the repo's own harness config"
    commands = _hooked(_settings(path))

    assert any("heredoc_guard" in c for c in commands), \
        f"PreToolUse/Bash does not run the guard: {commands!r}"


def test_the_USER_harness_registers_it_TOO_because_that_is_where_it_bites():
    """A project-scoped hook only fires in sessions rooted at the
    project, and not one of the nine occurrences happened in such a
    session: they happened in paper directories and in the home
    directory, editing manuscripts with docxkit imported. The repo
    registration above could not have stopped any of them.

    Skipped where there is no user harness at all — CI, a clean
    machine — since there is then nothing to be wrong about. It FAILS
    when a settings file exists and does not carry the hook, which is
    the state to notice the next time one of them is rewritten.
    """
    present = _user_settings()
    if not present:
        pytest.skip("no user-level Claude settings on this machine")

    commands = [c for p in present for c in _hooked(_settings(p))]

    assert any("heredoc_guard" in c for c in commands), (
        "none of " + ", ".join(p.name for p in present) + " runs the guard "
        "before a Bash call; every occurrence so far was in a session "
        "rooted outside this repo")


def _guard_paths(command: str) -> list[Path]:
    """The script paths a hook command names, resolved.

    `shlex` with `posix=False` rather than `str.split`, because a hook
    command routinely names `C:\\Program Files\\...` and splitting on
    spaces turns one path into two words that are each not a file.
    `$env:CLAUDE_PROJECT_DIR` is the repo root by definition — expanded
    rather than skipped, since the committed registration uses it and
    skipping it is how this test came to assert nothing at all in CI.
    """
    root = TOOLS.parent.as_posix()
    out = []
    for word in shlex.split(command, posix=False):
        bare = word.strip("\"'")
        if "heredoc_guard" not in bare:
            continue
        bare = bare.replace("$env:CLAUDE_PROJECT_DIR", root)
        bare = bare.replace("${CLAUDE_PROJECT_DIR}", root)
        bare = bare.replace("$CLAUDE_PROJECT_DIR", root)
        if "$" not in bare:                  # any other variable: not ours
            out.append(Path(bare))
    return out


def test_a_registration_naming_a_path_that_is_not_THERE_is_not_one():
    """The other way this goes quietly dead: the file moves, the entry
    stays, and every session then fails the hook open.

    This SKIPPED any command containing `$` — which is exactly the form
    the repo's own committed registration uses, and on a CI runner there
    is no `~/.claude`, so the loop had one exempt entry and passed having
    checked no path whatsoever. A test that cannot fail on the only
    input it will ever see in CI is the dead gate this package ranks
    above a wrong answer.
    """
    here = TOOLS.parent / ".claude" / "settings.json"
    checked = 0
    for path in [here, *_user_settings()]:
        for command in _hooked(_settings(path)):
            for named in _guard_paths(command):
                assert named.exists(), f"{path.name} names {named}, absent"
                checked += 1

    assert checked, "no registration was actually checked — see above"


def test_the_REGISTERED_command_really_refuses_a_heredoc():
    """The claim every other test here only approximates.

    A substring match on `heredoc_guard` says the entry is present; it
    cannot say the interpreter starts, that the path resolves, or that
    the thing at the end of it is this guard. Review made exactly that
    point about the committed registration, which names a bare `python`
    where the entry in the backlog says an absolute path. So run it: the
    registered script, with the harness's own JSON on stdin, and the
    blocking status out.
    """
    here = TOOLS.parent / ".claude" / "settings.json"
    scripts = [p for command in _hooked(_settings(here))
               for p in _guard_paths(command)]
    if not scripts:
        pytest.skip("no registration to run")

    call = {"tool_name": "Bash",
            "tool_input": {"command": HEREDOC.format(body="x = '\\\\n'")}}
    out = subprocess.run([sys.executable, str(scripts[0])],
                         input=json.dumps(call), capture_output=True,
                         text=True, check=False)

    assert out.returncode == 2, "the registered script does not BLOCK"
    assert "must not contain a backslash" in out.stderr
