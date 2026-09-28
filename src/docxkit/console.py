r"""Terminal output for scripts that print manuscript text.

Windows consoles default to cp1252, which cannot encode the glyphs these
documents and reports are full of — the typographic minus, curly quotes,
arrows, Cyrillic. Every paper script therefore opens with a call to
reconfigure stdout, and every one of them wrote it unguarded.

That crashes when stdout is not a real console stream: under pytest
capture, piped through a wrapper, or from a scheduled task, it can be an
object with no ``reconfigure`` at all.

**stderr needs the same treatment**, and for a sharper reason. Errors
here quote the document — an anchor that did not match, a reference
entry, a paragraph of a Russian manuscript — and the CLI prints them to
stderr. Left at cp1252 that is where an em dash arrives as ``?`` in the
one message whose job is to explain what went wrong.
"""
from __future__ import annotations

import io
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

__all__ = ["json_default", "utf8_console", "utf8_stdout", "write_json"]


def json_default(value: object) -> object:
    """Last-resort encoder, so a finished comparison is never lost.

    The reports here sort their sets before storing them, but the cost
    of one that does not is losing the whole run at the final step —
    the comparison already done, the report never written. In CI that
    is the worst possible moment to fail.
    """
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json(path: str | Path, payload: object) -> None:
    """A report as JSON, through :func:`json_default` — the one writer.

    It lived in ``cli`` as ``_write_json`` until 2026-09-29, and that
    was the package's only import cycle: ``compare.main``, a second entry
    point, reached UP into the CLI for it (REVIEW_2026-09-28 §3). Output
    for a terminal or a file belongs in this bottom layer.
    """
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2,
                   default=json_default),
        encoding="utf-8")


def _reconfigure(stream: object, line_buffering: bool | None) -> bool:
    if not isinstance(stream, io.TextIOWrapper):
        return False
    if line_buffering is None:
        stream.reconfigure(encoding="utf-8", errors="replace")
    else:
        stream.reconfigure(encoding="utf-8", errors="replace",
                           line_buffering=line_buffering)
    return True


def utf8_stdout(*, line_buffering: bool | None = None) -> bool:
    """Switch stdout to UTF-8 if it is a stream that supports it.

    Returns whether it was reconfigured, so a caller that cares can tell.
    `line_buffering=True` also makes output appear as it happens, which
    matters for a long build whose log is being watched.
    """
    return _reconfigure(sys.stdout, line_buffering)


def utf8_console(*, line_buffering: bool | None = None) -> bool:
    """Both streams. Returns whether STDOUT was reconfigured.

    What a command prints and what it fails with belong to the same
    console, and every caller that wanted one wanted the other — which
    is why there is no `utf8_stderr` beside this. There was one, reached
    by nothing in four trees and bypassed by this function, which called
    `_reconfigure` directly rather than going through it.

    The answer is stdout's, as the name of the sibling function says:
    this used to return `stdout or stderr`, so a caller asking "can I
    print a curly quote" was told yes when only the ERROR stream had
    been fixed. Nothing read it, which is why the two disagreed
    unnoticed until a mutation run asked what the `or` was for.
    """
    _reconfigure(sys.stderr, line_buffering)
    return _reconfigure(sys.stdout, line_buffering)
