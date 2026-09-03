"""The vocabulary the rest of the protocol shares.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import re
from datetime import date

from .._xml import DOCUMENT, ENDNOTES, FOOTNOTES

#: A `[section]` header on a line of its own, which is how every config
#: this package writes spells one. A key written in dotted form
#: (`paper.working = …`) or an inline table would not be seen — and is
#: not silently ignored either: `_set_key` inserts the key it was asked
#: for, and `load_paper` then reads the LAST definition, so the intended
#: value wins rather than a duplicate being written into a file that
#: already said something else. Here rather than in `_init` because
#: `doctor` reads the config by line too, and sits below `_init`.
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


#: Parts that carry revisable text. ``document.xml`` is not the whole
#: manuscript: Word's Review > Next button walks the body only, and both
#: Simple Markup and No Markup hide footnote balloons entirely, so a
#: revision left in a footnote is invisible from the author's chair
#: while still making the file a proposal rather than the truth. Any
#: count that reads only the body will call such a file "truth" and let
#: the next batch flatten it.
TEXT_PARTS = (DOCUMENT, FOOTNOTES,
              ENDNOTES)


#: Parts a Word save rewrites whether or not anything was edited —
#: rsids, the editing-time total, the namespace prefix order. Reporting
#: these as author edits cried wolf on every round-trip.
SAVE_NOISE = ("docProps/app.xml", "docProps/core.xml", "word/settings.xml")


_CONFIG = "paper.toml"


_DIR = "revision"


#: Directories a paper keeps SPENT builders in, skipped unless
#: ``[doctor] skip`` says otherwise. "applied" is already the protocol's
#: word for a batch that has been used, and under the forward-only rule
#: a spent script naming an old generation is the record rather than a
#: defect. AFI reported 134 selections with three worth reading, and
#: about 130 of the rest were an archive of exactly this kind.
_DOCTOR_SPENT = ("scripts/applied",)


#: How many rescue copies survive a promote, newest first. Five covers
#: "undo the last few promotes", which is all a rescue is for: anything
#: older is better served by the safekit vault, the attic and git, none
#: of which sit in the author's working folder.
RESCUE_KEEP = 5


#: Seconds one Word session may take for a build or a validate before
#: its hidden instance is killed and the step fails (``[batch]
#: word_deadline``; 0 means no ceiling). Word's save path can hang
#: indefinitely and a Compare can too; a batch that waits forever is a
#: batch nobody notices. Ten minutes is generous: a one-edit AFI batch
#: measured 95 s for build and validate together, cold starts included.
WORD_DEADLINE = 600.0


#: Rescue copies are named by TIME, not by a counter, and that is not a
#: cosmetic choice. The counter form takes the first FREE number, so the
#: moment pruning removes 1 to 3 the next promote writes a *new* file
#: called ``_rescue1``, older than the ``_rescue5`` beside it. Numbering and
#: pruning cannot both be right. A timestamp sorts correctly no matter
#: what has been deleted.
#:
#: **Every name is the same width, down to the microsecond**, which is
#: what makes sorting them as strings give chronological order. The first
#: version stamped whole seconds and appended ``-2``, ``-3`` on collision,
#: and that inverted the order it existed to preserve: ``-`` (0x2D) sorts
#: before ``.`` (0x2E), so ``…224455-2.docx`` came before
#: ``…224455.docx`` and the OLDEST copy read as the newest. Seven promotes
#: inside one second on a real paper is how that surfaced — prune then
#: deletes from the wrong end, which for an undo file is the whole game.
#:
#: Sorting by mtime instead is not an option either: `shutil.copy2`
#: carries the SOURCE's timestamp onto the copy, so every rescue would
#: claim the manuscript's mtime rather than its own.
_RESCUE_STAMP = "%Y%m%d-%H%M%S-%f"


_RESCUE_GLOB = "*_rescue_*"


WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def _today() -> str:
    return date.today().isoformat()
