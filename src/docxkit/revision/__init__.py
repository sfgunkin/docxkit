r"""The single-file revision protocol: one manuscript, two states.

Every paper on this protocol revises through ONE file — **the author's
own file, under its own name, wherever they keep it** — and its state is
readable from the file itself, so nobody has to remember which copy is
current:

======================  ==========================================
``revisions == 0``      **truth**: this is the paper, and an agent
                        may start a batch on it
``revisions > 0``       a **proposal** awaiting the author's verdict
======================  ==========================================

The cycle is: truth -> checkpoint -> apply the batch to a clean copy in
``build/`` -> Word Compare -> the tracked result *is* the new manuscript
-> the author adjudicates in Word -> accept-all -> truth again.
``build/prev.docx`` is the last accepted truth and the compare
reference. The manuscript is never shadowed by a "current" copy under
another name — what ``build/`` holds is the baseline, the staged batch,
the rescue copies and, since 2026-08-23, the redlines kept for the
record (:attr:`Paper.redline_dir`), none of which is a second place to
edit the paper.

**Which file is the paper is the author's choice, not this module's.**
``revision/paper.toml`` says so in one line (``working = ...``) and every
command reads it from there. The first shape of this protocol imposed
one name on every project — ``revision/working.docx`` — and it cost the
thing it was meant to buy: with nine papers on it, Explorer, the Word
title bar and the taskbar all say ``working.docx``, and the author
cannot tell which paper is open (author, 2026-08-23). So :func:`init`
adopts the manuscript IN PLACE by default: no copy is made, the name
stays the author's, and there is no second file to go stale. Papers
scaffolded under the old default keep their configured path and are not
touched — the declaration is what matters, never the spelling.

This module is the engine. What stays with the paper is
``revision/`` — its config, its log, ``build/prev.docx``, its own gates
and notes. That folder is MACHINERY; the manuscript does not have to
live in it and by default does not. The protocol itself is identical in
every project, which is why it is here: it was copied verbatim into a
second paper within a day of being written, and a third copy would have
been the point where they started to disagree with each other.

Four operations, in the order a batch meets them::

    ingest    what the author changed while I was away   (read-only)
    build     clean edit -> redline, via Word Compare
    validate  the gate ladder, fast to slow, failing early
    promote   put a validated batch onto the manuscript

plus ``state`` (which of the two states is this file in?),
``baseline`` (the author accepted — this is the new truth), ``withdraw``
(take back a promoted proposal nobody has opened) and ``init`` (scaffold
the layout for a paper that has not migrated yet).

Every refusal in here was a real incident. They are worth reading as a
list, because each one is silent if you skip it:

* a batch built on a baseline that still carries pending revisions
  flattens those revisions into plain text — the author's open verdicts
  are decided for them, and nothing says so;
* Word's Compare cannot serialize tracked math, so a batch that touches
  equations bakes them in with nothing to reject;
* a copy made while Word holds the file is overwritten the moment Word
  saves, and the promotion silently vanishes;
* a batch promoted onto a manuscript the author has edited since
  destroys those edits;
* an accept the author made in Word leaves NOTHING pending on either
  side, so a pending count alone calls a baseline the paper has already
  outgrown "the truth" — see :func:`drift`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------
# The facade. `revision.py` was one 3,118-line module until 2026-08-30,
# and every name it defined was reachable as `docxkit.revision.<name>`;
# so every name is re-exported here, private helpers included. The
# import path callers use does not change, which is the whole point of
# splitting into a package rather than into modules beside it.
#
# `from x import y as y` is the PEP 484 signal for a deliberate
# re-export — the same spelling `citations`, `tables` and `compare` use.
# Without it `ruff --fix` strips the names the tests import through it.
#
# The halves may only import DOWNWARDS. The order is NOT readable here —
# ruff's isort sorts this block alphabetically, and a layering written
# where a formatter can rewrite it is a layering that lasts until the
# next `--fix`. It is declared in `tests/test_layering.py`
# (`SUBPACKAGE_HALVES`, bottom first) and enforced from there.
#
# The MODULE aliases come first, and they are not decoration: the suite
# fakes Word, lint and Compare by setting an attribute on the module
# object — `monkeypatch.setattr(revision.tracked, "build", ...)`, 27
# times — and `tests/test_revision.py` says so in its own docstring:
# "Word is faked at the module attribute `revision._word`, the same seam
# tracked.py uses". Those names were attributes of the 3,118-line module
# and the seam is the same object either way, so they are carried here
# rather than repointed test by test at whichever layer now holds the
# call. A split that quietly narrowed the test seam would be a
# behaviour change wearing a refactor's clothes.
import shutil as shutil

from .. import footnotes as footnotes
from .. import guard as _guard  # noqa: F401  (seam; see above)
from .. import lint as _lint  # noqa: F401  (seam; see above)
from .. import package as package
from .. import revisions as revisions
from .. import tracked as tracked
from .. import word as _word  # noqa: F401  (seam; see above)
from .._xml import internal_links as internal_links
from ..errors import BaselinePending as BaselinePending
from ..errors import DocumentLocked as DocumentLocked
from ..errors import HandbackLoss as HandbackLoss
from ..errors import MathResolved as MathResolved
from ..errors import ProtocolError as ProtocolError
from ..errors import StaleBatch as StaleBatch
from ..errors import WorkingPending as WorkingPending
from ._baseline import BaselineReport as BaselineReport
from ._baseline import baseline as baseline
from ._build import build as build
from ._common import _CONFIG as _CONFIG
from ._common import _DIR as _DIR
from ._common import _DOCTOR_SPENT as _DOCTOR_SPENT
from ._common import _RESCUE_GLOB as _RESCUE_GLOB
from ._common import _RESCUE_STAMP as _RESCUE_STAMP
from ._common import RESCUE_KEEP as RESCUE_KEEP
from ._common import SAVE_NOISE as SAVE_NOISE
from ._common import TEXT_PARTS as TEXT_PARTS
from ._common import WP as WP
from ._common import M as M
from ._common import W as W
from ._common import _today as _today
from ._config import Paper as Paper
from ._config import find_config as find_config
from ._config import load_paper as load_paper
from ._doctor import _DOCTOR_SKIP as _DOCTOR_SKIP
from ._doctor import _DOCTOR_SUFFIXES as _DOCTOR_SUFFIXES
from ._doctor import _DOCX_LITERAL_RE as _DOCX_LITERAL_RE
from ._doctor import _DOCX_PATTERN_RE as _DOCX_PATTERN_RE
from ._doctor import Doubt as Doubt
from ._doctor import _selects_declared as _selects_declared
from ._doctor import doctor as doctor
from ._gates import GateResult as GateResult
from ._gates import _kill_tree as _kill_tree
from ._gates import _run_one as _run_one
from ._gates import run_gates as run_gates
from ._ingest import IngestReport as IngestReport
from ._ingest import ingest as ingest
from ._init import _LOG_TEMPLATE as _LOG_TEMPLATE
from ._init import _SECTION_RE as _SECTION_RE
from ._init import _TOML_TEMPLATE as _TOML_TEMPLATE
from ._init import _declare as _declare
from ._init import _set_key as _set_key
from ._init import _toml_str as _toml_str
from ._init import _value_end as _value_end
from ._init import init as init
from ._losses import _DRAWING_GLYPH as _DRAWING_GLYPH
from ._losses import _FOLD as _FOLD
from ._losses import _MOVED_NOTE_RE as _MOVED_NOTE_RE
from ._losses import Loss as Loss
from ._losses import Relabelled as Relabelled
from ._losses import _bookmarks as _bookmarks
from ._losses import _counts as _counts
from ._losses import _downgraded_math as _downgraded_math
from ._losses import _glyph as _glyph
from ._losses import _link_changes as _link_changes
from ._losses import _links as _links
from ._losses import _lost_notes as _lost_notes
from ._losses import _names as _names
from ._losses import _norm as _norm
from ._losses import _notes as _notes
from ._losses import _shown as _shown
from ._losses import _unmet as _unmet
from ._losses import emptied_footnotes as emptied_footnotes
from ._losses import glyph_runs as glyph_runs
from ._losses import links_in_deletions as links_in_deletions
from ._losses import losses as losses
from ._losses import moved_footnotes as moved_footnotes
from ._losses import relabelled_links as relabelled_links
from ._losses import restored_bookmarks as restored_bookmarks
from ._promote import PromoteReport as PromoteReport
from ._promote import WithdrawReport as WithdrawReport
from ._promote import _stamped as _stamped
from ._promote import promote as promote
from ._promote import prune_rescues as prune_rescues
from ._promote import redline_path as redline_path
from ._promote import redlines as redlines
from ._promote import rescue_path as rescue_path
from ._promote import rescues as rescues
from ._promote import withdraw as withdraw
from ._registry import REGISTRY_ENV as REGISTRY_ENV
from ._registry import Survey as Survey
from ._registry import register as register
from ._registry import registered as registered
from ._registry import registry_path as registry_path
from ._registry import scan as scan
from ._registry import survey as survey
from ._registry import survey_exit_code as survey_exit_code
from ._state import _AUTHOR_RE as _AUTHOR_RE
from ._state import State as State
from ._state import StatusReport as StatusReport
from ._state import _drifted as _drifted
from ._state import _state as _state
from ._state import drift as drift
from ._state import state as state
from ._state import status as status
from ._validate import ValidateReport as ValidateReport
from ._validate import math_anchors as math_anchors
from ._validate import render_accepted as render_accepted
from ._validate import validate as validate
from ._verdict import _BATCH_HEADING as _BATCH_HEADING
from ._verdict import _ROW_RE as _ROW_RE
from ._verdict import Verdict as Verdict
from ._verdict import _para_counts as _para_counts
from ._verdict import _proposal as _proposal
from ._verdict import log_batch as log_batch
from ._verdict import verdict as verdict

__all__ = [
    "REGISTRY_ENV",
    "RESCUE_KEEP",
    "SAVE_NOISE",
    "TEXT_PARTS",
    "BaselinePending",
    "BaselineReport",
    "DocumentLocked",
    "Doubt",
    "GateResult",
    "HandbackLoss",
    "IngestReport",
    "Loss",
    "MathResolved",
    "Paper",
    "PromoteReport",
    "ProtocolError",
    "Relabelled",
    "StaleBatch",
    "State",
    "StatusReport",
    "Survey",
    "ValidateReport",
    "Verdict",
    "WithdrawReport",
    "WorkingPending",
    "baseline",
    "build",
    "doctor",
    "drift",
    "emptied_footnotes",
    "find_config",
    "glyph_runs",
    "ingest",
    "init",
    # re-exported like TEXT_PARTS and ProtocolError beside it: the
    # reports here talk about links, so the callers of this module ask
    # about them, and `from docxkit._xml import ...` is a private
    # spelling Pyright is right to refuse. `docxkit.find` is the home
    # for a new caller; this is where the existing ones already look.
    "internal_links",
    "links_in_deletions",
    "load_paper",
    "log_batch",
    "losses",
    "math_anchors",
    "moved_footnotes",
    "promote",
    "prune_rescues",
    "redline_path",
    "redlines",
    "register",
    "registered",
    "registry_path",
    "relabelled_links",
    "render_accepted",
    "rescue_path",
    "rescues",
    "restored_bookmarks",
    "run_gates",
    "scan",
    "state",
    "status",
    "survey",
    "survey_exit_code",
    "validate",
    "verdict",
    "withdraw",
]
