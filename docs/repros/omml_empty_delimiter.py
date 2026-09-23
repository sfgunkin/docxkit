r"""DEFECT: a delimiter Word writes as EMPTY comes back as a bracket.

OMML says "no delimiter on this side" with an empty `m:val` —
`<m:endChr m:val=""/>` — and that is how Word writes the cases brace of
a piecewise function: an opening `{` and nothing on the right. LaTeX
spells the same thing `\right.`, which `_FENCES` has a member for (`"":
"."`).

The member is unreachable. `_Walker` reads the character with

    raw_beg = _mval(el, "dPr/begChr") or "("
    raw_end = _mval(el, "dPr/endChr") or ")"

and an empty string is falsy, so "no delimiter" is replaced by the
DEFAULT bracket before the table is asked. A piecewise function
therefore comes back with a closing parenthesis that is not on the page,
and the same happens on the left for a one-sided `\left.`.

Run from the worktree:  python <this file>
"""
import sys

from pathlib import Path

# the repo's own source, not a session's worktree: this file used to
# point at a scratchpad that is gone
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from docxkit.equations import _FENCES, to_latex  # noqa: E402

M = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
RUN = "<m:r><m:t>x</m:t></m:r>"


def delimiter(beg: str, end: str) -> str:
    return (f"<m:oMath {M}><m:d><m:dPr>"
            f'<m:begChr m:val="{beg}"/><m:endChr m:val="{end}"/></m:dPr>'
            f"<m:e>{RUN}</m:e></m:d></m:oMath>")


print(f'_FENCES has a member for the empty delimiter: {_FENCES[""]!r}\n')
for name, beg, end, want in (
        ("a cases brace (open left, nothing right)", "{", "",
         r"\left\{ x \right."),
        ("nothing left, closing brace right", "", "}",
         r"\left. x \right\}"),
        ("an ordinary pair, for contrast", "[", "]",
         r"\left[ x \right]")):
    got = to_latex(delimiter(beg, end))
    mark = "ok " if got == want else "WRONG"
    print(f"{mark} {name}:\n      want {want!r}\n      got  {got!r}")
