"""Put THIS checkout's `src` in front of the editable install.

The package is installed editable, so `import docxkit` resolves through
a plain-path `.pth` to whichever checkout the install points at — for
every process, in every directory. A worktree therefore ran its own
tests against ANOTHER checkout's source and said they passed. Measured
2026-09-18: with a worktree's own `wordcount.py` renamed out from under
its tests, a bare `pytest` there reported `18 passed`.

`tools/gates.py` closes that for the gate chain by setting `PYTHONPATH`
for every gate it spawns (see `_child_env`). This closes it for
everything else — a bare `pytest`, a single test file, an editor's test
runner — because the trap is not the chain, it is the import.

It bites twice over, and the second bite is why this file exists rather
than a line in the gate runner: a test that resolves `tools/` through
`docxkit.__file__` — which several do, since `tools` is not a package
and is not installed — then loads the OTHER checkout's tools too. So a
new flag's tests could pass in a worktree before the flag existed there.

sys.path[0] wins over a `.pth`, which is the whole mechanism.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent / "src")
if _SRC in sys.path:
    sys.path.remove(_SRC)
sys.path.insert(0, _SRC)
