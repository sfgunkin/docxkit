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
import sys
from pathlib import Path

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
