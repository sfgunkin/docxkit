r"""Terminal output for scripts that print manuscript text.

Windows consoles default to cp1252, which cannot encode the glyphs these
documents and reports are full of — the typographic minus, curly quotes,
arrows, Cyrillic. Every paper script therefore opens with a call to
reconfigure stdout, and every one of them wrote it unguarded.

That crashes when stdout is not a real console stream: under pytest
capture, piped through a wrapper, or from a scheduled task, it can be an
object with no ``reconfigure`` at all.
"""
from __future__ import annotations

import io
import sys

__all__ = ["utf8_stdout"]


def utf8_stdout(*, line_buffering: bool | None = None) -> bool:
    """Switch stdout to UTF-8 if it is a stream that supports it.

    Returns whether it was reconfigured, so a caller that cares can tell.
    `line_buffering=True` also makes output appear as it happens, which
    matters for a long build whose log is being watched.
    """
    if not isinstance(sys.stdout, io.TextIOWrapper):
        return False
    if line_buffering is None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=line_buffering)
    return True
