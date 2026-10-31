r"""An equation OBJECT Word tracks by a flag in its own `m:ctrlPr`.

Measured 2026-10-31 while processing the latent shapes of the 2026-10-24
review. A math object an author types with tracking on — a subscript, a
fraction, a delimiter — is recorded by Word as ONE flag,
``<m:sSubPr><m:ctrlPr><w:ins …><w:rPr/></w:ins></m:ctrlPr></m:sSubPr>``,
and its runs carry no mark of their own (HPPA2.docx: 104 runs inside
flagged objects, none marked). Word's Reject All removes the object with
everything in it. The engine treated the flag as a wrapper round the
`w:rPr` it holds, removed the flag, and kept the object: on AFI's
`afi_v11_ABLA.docx` the rejected view held 66 subscripts, 11 n-ary
operators and 15 equations that Word's does not. 5,640 such flags sit in
104 of this machine's redlines; Word was the oracle on a sample of them.

The kept side is unchanged and was already right: the flag is unwrapped
and the properties it held become the control character's own.
"""
from __future__ import annotations

import re

from docxkit.revisions import accept, by_author, reject

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
      '2006/main" xmlns:m="http://schemas.openxmlformats.org/'
      'officeDocument/2006/math"')


def flag(kind: str, author: str = "A", rid: int = 1) -> str:
    return (f'<m:ctrlPr><w:{kind} w:id="{rid}" w:author="{author}" '
            f'w:date="2026-10-31T00:00:00Z"><w:rPr><w:i/></w:rPr>'
            f"</w:{kind}></m:ctrlPr>")


def mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def sub(base: str, index: str, kind: str = "", author: str = "A",
        rid: int = 1) -> str:
    """A subscript, flagged in its own properties when `kind` is given —
    and its runs left UNMARKED, which is how Word writes it."""
    props = f"<m:sSubPr>{flag(kind, author, rid)}</m:sSubPr>" if kind else ""
    return (f"<m:sSub>{props}<m:e>{mr(base)}</m:e>"
            f"<m:sub>{mr(index)}</m:sub></m:sSub>")


def doc(*maths: str) -> str:
    paras = "".join(f"<w:p><m:oMath>{m}</m:oMath></w:p>" for m in maths)
    return f"<w:document {NS}><w:body>{paras}</w:body></w:document>"


def glyphs(xml: str) -> list[str]:
    return re.findall(r"<m:t>([^<]*)</m:t>", xml)


def test_REJECT_removes_an_object_whose_ctrlPr_flags_it_INSERTED():
    """The HPPA2 shape: three inserted subscripts among five original
    runs. Word rejects the three whole; the five stay."""
    eq = (mr("x") + sub("p", "1", "ins") + mr("+") + sub("p", "2", "ins")
          + mr("+") + sub("p", "3", "ins") + mr("=") + mr("y"))

    out = reject(doc(eq))

    assert "<m:sSub" not in out and "w:ins" not in out
    assert glyphs(out) == ["x", "+", "+", "=", "y"]


def test_ACCEPT_keeps_an_inserted_object_and_its_properties_unflagged():
    eq = mr("x") + sub("p", "1", "ins") + sub("p", "2", "ins") \
        + sub("p", "3", "ins")

    out = accept(doc(eq))

    assert out.count("<m:sSub>") == 3 and "w:ins" not in out
    assert out.count("<m:ctrlPr><w:rPr><w:i/></w:rPr></m:ctrlPr>") == 3
    assert glyphs(out) == ["x", "p", "1", "p", "2", "p", "3"]


def test_ACCEPT_removes_an_object_whose_ctrlPr_flags_it_DELETED():
    """The same rule from the other side: accept is where a deleted
    object goes. Five plain runs survive, three flagged objects do not."""
    eq = (mr("a") + sub("q", "1", "del") + mr("b") + sub("q", "2", "del")
          + mr("c") + sub("q", "3", "del") + mr("d") + mr("e"))

    out = accept(doc(eq))

    assert "<m:sSub" not in out and "w:del" not in out
    assert glyphs(out) == ["a", "b", "c", "d", "e"]

    kept = reject(doc(eq))
    assert kept.count("<m:sSub>") == 3 and "w:del" not in kept


def test_an_equation_that_WAS_only_the_inserted_object_goes_whole():
    """Nothing left to show: the emptied `m:oMath` is pruned, as it is
    when the runs themselves were tracked."""
    out = reject(doc(sub("p", "1", "ins"), sub("p", "2", "ins"),
                     mr("z") + sub("p", "3", "ins")))

    assert out.count("<m:oMath>") == 1 and glyphs(out) == ["z"]


def test_a_SELECTIVE_reject_removes_only_the_objects_it_chose():
    """Three objects by A, five by B: rejecting A's leaves B's five
    standing, still flagged, for a person to decide."""
    eq = "".join(sub("a", str(i), "ins", "A", rid=i) for i in range(3)) \
        + "".join(sub("b", str(i), "ins", "B", rid=10 + i) for i in range(5))

    out = reject(doc(eq), where=by_author("A"))

    assert out.count("<m:sSub>") == 5
    assert out.count('w:author="B"') == 5 and 'w:author="A"' not in out
    assert "a" not in glyphs(out)


def test_an_inserted_object_INSIDE_an_inserted_object_goes_with_it():
    inner = sub("p", "i", "ins", rid=2)
    outer = (f"<m:f><m:fPr>{flag('ins', rid=1)}</m:fPr>"
             f"<m:num>{inner}</m:num><m:den>{mr('n')}</m:den></m:f>")

    out = reject(doc(mr("s") + outer + mr("t") + mr("u")))

    assert "<m:f>" not in out and "<m:sSub" not in out
    assert glyphs(out) == ["s", "t", "u"]
