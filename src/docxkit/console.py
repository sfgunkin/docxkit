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
import sys

__all__ = ["utf8_console", "utf8_stdout"]


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
    """Both streams. Returns whether stdout was reconfigured.

    What a command prints and what it fails with belong to the same
    console, and every caller that wanted one wanted the other — which
    is why there is no `utf8_stderr` beside this. There was one, reached
    by nothing in four trees and bypassed by this function, which called
    `_reconfigure` directly rather than going through it.
    """
    err = _reconfigure(sys.stderr, line_buffering)
    return _reconfigure(sys.stdout, line_buffering) or err
