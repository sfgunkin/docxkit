"""Switching the console to UTF-8, which every paper script opens with.

Windows consoles default to cp1252 and cannot encode what these
documents are full of — the typographic minus, curly quotes, Cyrillic.
The unguarded one-liner every script used to carry crashes when stdout
is not a real console stream (under pytest capture, piped through a
wrapper, from a scheduled task).

Measured for the first time on 2026-08-17 at 24.1 % real survival with
no direct test of its own: the module was reached only through the CLI,
which calls it and ignores the answer.
"""
from __future__ import annotations

import io

from docxkit.console import _reconfigure, utf8_console, utf8_stdout


def _stream(*, line_buffering: bool = False) -> io.TextIOWrapper:
    """A real TextIOWrapper, as a console stream is."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252",
                            line_buffering=line_buffering)


def test_a_real_stream_is_switched_to_utf8():
    stream = _stream()

    assert _reconfigure(stream, None) is True
    assert stream.encoding == "utf-8"


def test_what_cannot_be_encoded_is_REPLACED_rather_than_raised():
    """`errors="replace"`. A build that dies printing its own report is
    worse than one whose report has a question mark in it — and the
    stream this is protecting is often the one carrying the error."""
    stream = _stream()
    _reconfigure(stream, None)

    stream.write("a minus − and a dash —")     # must not raise

    assert stream.errors == "replace"


def test_a_stream_that_is_NOT_a_console_is_left_alone():
    """The whole reason this exists: under pytest capture, piped, or
    from a scheduled task, stdout can be an object with no
    `reconfigure` at all, and the unguarded call crashes the script
    before it prints anything."""
    captured = io.StringIO()

    assert _reconfigure(captured, None) is False


def test_line_buffering_is_LEFT_as_it_was_unless_asked():
    """Two calls, one flag: passing None must not quietly turn off a
    stream's line buffering, which is what makes a long build's log
    appear as it happens."""
    stream = _stream(line_buffering=True)

    _reconfigure(stream, None)

    assert stream.line_buffering is True


def test_line_buffering_is_SET_when_asked():
    stream = _stream(line_buffering=False)

    _reconfigure(stream, True)

    assert stream.line_buffering is True


def test_utf8_stdout_reports_whether_it_did_anything(monkeypatch):
    stream = _stream()
    monkeypatch.setattr("sys.stdout", stream)

    assert utf8_stdout() is True
    assert stream.encoding == "utf-8"


def test_utf8_console_switches_STDERR_too(monkeypatch):
    """Errors here quote the document — an anchor that did not match, a
    paragraph of a Russian manuscript — and the CLI prints them to
    stderr. Left at cp1252 that is where an em dash arrives as `?`, in
    the one message whose job is to explain what went wrong."""
    out, err = _stream(), _stream()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)

    utf8_console()

    assert (out.encoding, err.encoding) == ("utf-8", "utf-8")


def test_utf8_console_answers_for_STDOUT(monkeypatch):
    """The name of the sibling function is the contract: a caller asking
    "can I print a curly quote" is asking about stdout. This returned
    `stdout or stderr`, so a captured stdout beside a real stderr
    answered yes."""
    monkeypatch.setattr("sys.stdout", io.StringIO())      # not a console
    monkeypatch.setattr("sys.stderr", _stream())

    assert utf8_console() is False


def test_utf8_console_still_fixes_stderr_when_stdout_cannot_be(monkeypatch):
    """...and the answer being no does not mean it did nothing."""
    err = _stream()
    monkeypatch.setattr("sys.stdout", io.StringIO())
    monkeypatch.setattr("sys.stderr", err)

    utf8_console()

    assert err.encoding == "utf-8"
