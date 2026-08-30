"""A project's OWN test commands, run in subprocesses.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._config import Paper


@dataclass(frozen=True)
class GateResult:
    """One of the paper's own verification commands, and how it went."""

    command: str
    code: int
    """The process's exit code; -1 when it ran out of time."""
    seconds: float
    output: str
    """The tail of what it printed — enough to act on a failure."""

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def verdict(self) -> str:
        if self.code == -1:
            return "TIMED OUT"
        return "pass" if self.ok else f"FAIL ({self.code})"


def run_gates(paper: Paper, *, timeout: float = 900,
              progress: Any = None) -> Iterator[GateResult]:
    """Run ``[verify] commands`` from the paper's own config, streaming.

    **An iterator, so a caller reports each gate as it finishes.** The
    first version returned a list, which meant the CLI could only print
    after every gate had run: the `progress` heartbeat announced all of
    them up front and the verdicts arrived together at the end, which
    is precisely the "twelve silent minutes" the heartbeat was added to
    prevent. Consuming this drives the run — a caller that discards it
    runs nothing.

    **This module deliberately did not shell out**, and the reason is
    written into its docstring: what a paper checks is the paper's
    business, and a shared tool that runs per-project commands is a
    larger promise than the protocol makes. That reasoning holds for the
    DEFAULT and not for the capability. With nine papers on the
    protocol, "the gates are listed and you run them yourself" means
    they run when someone remembers, which is not what a gate is for.

    So: still not part of the ladder, still not run by `validate` unless
    asked (`--run-gates`), and when asked they run exactly as the config
    spells them, through the shell, from the project root. The commands
    are the author's own text in the author's own file; this neither
    parses nor sanitises them, and a caller who did not intend to run
    arbitrary commands should not pass the flag.

    A gate that hangs is a gate that fails: `timeout` bounds each one,
    and a timeout reports as code -1 rather than blocking a ladder that
    exists to be run before every hand-back.

    **`subprocess.run(..., timeout=)` does not deliver that on its own,
    and the first version of this shipped believing it did.** With
    `shell=True` the real gate is a GRANDCHILD — cmd.exe is the child —
    so the kill on timeout reaches the shell and not the process doing
    the work, and the surviving grandchild holds the stdout and stderr
    pipes open, which blocks the cleanup `run` performs before it
    re-raises. Measured on this machine: a `timeout=1` against a
    20-second sleep returned after **20.08s**. The same call without a
    shell returns in 1.03s. So the whole process TREE is killed here,
    and the reader is drained on a thread that cannot deadlock the
    parent.

    The test that certified the old behaviour passed for 30 seconds
    while asserting the exit code and never the clock — see
    `test_a_gate_that_HANGS`, which now asserts elapsed time.
    """
    import subprocess
    import threading
    import time

    for command in paper.gates:
        if progress:
            progress(f"gate: {command}")
        started = time.monotonic()
        code, text = _run_one(command, paper.root, timeout, subprocess,
                              threading)
        yield GateResult(command=command, code=code,
                         seconds=round(time.monotonic() - started, 1),
                         output="\n".join(text.splitlines()[-20:]))


def _kill_tree(proc: Any, subprocess: Any) -> None:
    """Kill the gate AND whatever the shell started for it.

    `proc.kill()` reaches cmd.exe and leaves the grandchild running with
    the pipes open. On Windows only `taskkill /T` walks the tree; on a
    POSIX box the session started by `start_new_session` is the handle.
    Best effort by construction — the point is to stop WAITING for it,
    and a kill that fails must not become a second hang.
    """
    import contextlib
    import sys
    # `sys.platform` rather than `os.name`: the type checker narrows on
    # it, and `os.killpg` / `signal.SIGKILL` do not exist on Windows at
    # all, so the branch has to be invisible there rather than merely
    # unreached.
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, check=False, timeout=10)
        else:                            # pragma: no cover - POSIX only
            import os
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(Exception):
        proc.kill()


def _run_one(command: str, cwd: Path, timeout: float,
             subprocess: Any, threading: Any) -> tuple[int, str]:
    """One gate: its exit code and the text it printed.

    The reader runs on a daemon thread rather than through
    `communicate(timeout=)`, because that call is the one that waits on
    the pipes the orphaned grandchild is holding.
    """
    if not cwd.is_dir():
        # NOT 127: "command not found" sends the author hunting for a
        # missing tool when the real problem is that the project root
        # moved or its drive is offline.
        return 126, (f"cannot run gates: {cwd} is not a directory — the "
                     f"project root moved, or its drive is offline")
    import sys
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:                                # pragma: no cover - POSIX only
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, shell=True, cwd=cwd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            **kwargs)
    chunks: list[str] = []

    def drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc, subprocess)
        reader.join(timeout=5)
        # What it printed BEFORE it hung is the whole diagnosis: a
        # pytest gate wedged on test 340 of 500 names that test here,
        # and the first version threw it away for the literal string
        # "no output within Ns".
        printed = "".join(chunks).rstrip()
        return -1, (f"{printed}\n[no further output within {timeout:g}s]"
                    if printed else f"no output within {timeout:g}s")
    reader.join(timeout=5)
    return proc.returncode, "".join(chunks)
