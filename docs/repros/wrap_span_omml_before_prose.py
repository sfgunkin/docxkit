"""Is `fs <= at` really always true?

The prediction's claim 2 rests on it: "`fs` is the start of the run
holding `at`". But `covered[0]` is the first run whose END is past `at`,
and the module's own comment says the offsets come from `visible_text`,
which includes OMML, while `RUN_RE` matches `w:r` only. So a span
starting inside MATHS should have no `w:r` holding it, and the first
covered run should start AFTER `at`.
"""
import sys

sys.path.insert(0, "src")
from docxkit._cite_grammar import wrap_visible_span  # noqa: E402
from docxkit._xml import run_spans, visible_text  # noqa: E402

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')
PARA = (f"<w:p {NS}>"
        "<m:oMath><m:r><m:t>xy</m:t></m:r></m:oMath>"
        "<w:r><w:t>Smith 2020</w:t></w:r>"
        "</w:p>")

print("visible text:", repr(visible_text(PARA)))
runs, spans, cursor = run_spans(PARA)
print("w:r spans    :", spans, "cursor:", cursor)

for at, end in ((0, 4), (1, 5), (2, 12)):
    covered = [(sp, r) for sp, r in zip(spans, runs, strict=True)
               if sp[1] > at and sp[0] < end]
    if not covered:
        print(f"at={at} end={end}: no covered run (AnchorError)")
        continue
    (fs, _fe), _first = covered[0]
    print(f"at={at} end={end}: fs={fs}  fs <= at is {fs <= at}")
    try:
        out = wrap_visible_span(PARA, at, end, anchor="Ref1", style="Link")
        print(f"    wrapped -> {out[:160]}")
    except Exception as exc:                       # noqa: BLE001
        print(f"    {type(exc).__name__}: {exc}")
