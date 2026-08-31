r"""What `import docxkit` costs, asked in an interpreter that has not.

`tests/test_layering.py` states the invariant and could not check it:
*"`import docxkit` must not pay for lxml, pandas, pywin32 or the
comparison's chain, which is why several modules import inside their
functions."* Nothing did check it, and on 2026-08-31 it was measured
FALSE for lxml — `package.py` had `from lxml import etree` at module
level, and `package` is what `import docxkit` reaches. About 9 ms, on
every command the CLI runs and every paper script that imports the
toolkit at all.

The deferral was even written already: `malformed_parts` imports lxml
inside the function, four hundred lines below the module-level import
that made it pointless. That is the shape this file exists to catch —
an intention recorded in one place and contradicted in another, where
no test looks.

**Asked in a subprocess, because there is no other way to ask.** By the
time pytest runs, lxml, pandas and half the package are in
`sys.modules`, imported by other tests; an in-process check would pass
whatever the package does. Two interpreters, about half a second.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

#: Every module `import docxkit` is allowed to bring with it. Pinned as
#: a SET rather than a ceiling: the base import chain is an
#: architectural claim — these five modules and the two facades over
#: them — and a sixth arriving is a decision somebody should have to
#: make in this file. It is the same reason `test_layering` states its
#: layers as data rather than deriving a number.
BASE_CHAIN = {
    "docxkit", "docxkit._xml", "docxkit.console", "docxkit.edit",
    "docxkit.errors", "docxkit.find", "docxkit.package",
}

#: Third-party imports the base chain must not pay for, and what each
#: one costs if it creeps back in.
#:
#: `lxml` is a REQUIRED dependency and still belongs here: required
#: means "installed", not "parsed on startup", and it is 9 ms of import
#: for a parser that `read_parts`, `text_of` and every anchor helper
#: never touch.
#:
#: The other four are optional extras, where an eager import is worse
#: than slow — it is an ImportError on a machine that installed docxkit
#: without them. `win32com` and `pythoncom` would make the whole toolkit
#: Windows-only, which is the failure `docxkit.word`'s lazy import
#: exists to prevent.
FORBIDDEN = ("lxml", "pandas", "win32com", "pythoncom", "fitz",
             "latex2mathml")

PROBE = """
import json, sys
import {module}
print(json.dumps({{
    "docxkit": sorted(m for m in sys.modules if m.startswith("docxkit")),
    "third_party": sorted(m for m in {forbidden!r} if m in sys.modules),
}}))
"""


def _imported(module: str) -> dict[str, list[str]]:
    """What a fresh interpreter has loaded after importing `module`."""
    proc = subprocess.run(
        [sys.executable, "-c",
         PROBE.format(module=module, forbidden=FORBIDDEN)],
        capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    # The probe's own output, not an inference from it: a subprocess that
    # printed nothing would otherwise read as a module that imported
    # nothing, which is this file's failure mode in reverse.
    assert proc.stdout.strip(), f"the probe printed nothing: {proc.stderr}"
    loaded: dict[str, list[str]] = json.loads(proc.stdout)
    return loaded


@pytest.mark.parametrize("module", ["docxkit", "docxkit.cli"])
def test_the_base_import_pays_for_no_third_party_parser(module):
    """`docxkit.cli` is here beside the package because it is what a
    person actually runs: the CLI's startup is paid once per command,
    and it dropped from 55 ms to 43 when lxml came out of the chain."""
    loaded = _imported(module)

    assert loaded["third_party"] == [], (
        f"`import {module}` now pays for {loaded['third_party']} — "
        f"import it inside the function that needs it, as "
        f"`package.malformed_parts` does")


def test_importing_the_package_pulls_only_the_base_chain():
    """The comparison's chain is the other half of the claim. `compare`,
    `tracked`, `word` and the table layers are reached explicitly or not
    at all — a facade that imported them would put lxml, difflib and
    Word's COM surface behind `import docxkit`."""
    loaded = _imported("docxkit")

    assert set(loaded["docxkit"]) == BASE_CHAIN, (
        f"the base import chain moved: "
        f"+{sorted(set(loaded['docxkit']) - BASE_CHAIN)} "
        f"-{sorted(BASE_CHAIN - set(loaded['docxkit']))}")


def test_the_probe_would_notice_a_module_that_IS_imported():
    """The gate's own instrument. Every assertion above is a NEGATIVE —
    "this is absent" — and an absence is what a broken probe reports for
    everything. So: ask it about a module that is genuinely there."""
    loaded = _imported("docxkit.tracked")

    assert "lxml" in loaded["third_party"], (
        "tracked parses XML and imports lxml; a probe that cannot see "
        "that cannot see the imports the tests above are about")
    assert "docxkit.tracked" in loaded["docxkit"]
