r"""Reading a .docx into the units the comparison works on.

Layer 1 of :mod:`docxkit.compare`: paragraphs, the parts they live in,
and the masking that has to happen before either can be compared.
Nothing here knows what a difference IS — that is the next layer.

The reading is regex-based, deliberately and against the usual advice.
It is the standing design of this package: `lint`, the write gate, the
pathological corpus and the 347-document sweep exist because of it, and
an lxml rewrite has been proposed and declined more than once. What
changed the day this file was split out is that the reading is now
type-checked and linted like the rest of the toolkit.
"""
from __future__ import annotations

import html
import re
import zipfile
from difflib import SequenceMatcher
from typing import TypedDict

from ._cite_repair import field_spans
from ._xml import T_PARTS_RE
from .comments import read_all as _read_comments

# ------------------------------------------------------------- extraction
P_RE = re.compile(r"<w:p[ >].*?</w:p>", re.DOTALL)
WT_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
MT_RE = re.compile(r"<m:t[^>]*>([^<]*)</m:t>")
OMATH_RE = re.compile(r"<m:oMath>.*?</m:oMath>", re.DOTALL)
RUN_RE = re.compile(r"<w:r\b[^>]*>(.*?)</w:r>", re.DOTALL)
RPR_RE = re.compile(r"<w:rPr>(.*?)</w:rPr>", re.DOTALL)
PARAID_RE = re.compile(r'w14:paraId="([0-9A-Fa-f]+)"')

#: Structural OMML elements that change a formula's meaning or shape.
OMML_STRUCT = ("sSub", "sSup", "sSubSup", "nary", "f", "d", "rad", "func",
               "acc", "bar", "groupChr", "limLow", "limUpp", "m", "eqArr",
               "box")
OMML_STRUCT_RE = re.compile(r"<m:(" + "|".join(OMML_STRUCT) + r")\b")


class Fields(TypedDict):
    """The citation and cross-reference machinery a paragraph carries."""

    anchors: list[str]
    cites: list[str]
    footnotes: int


def _flags(rpr: str | None) -> frozenset[str]:
    if not rpr:
        return frozenset()
    found: set[str] = set()

    def on(tag: str) -> bool:
        m = re.search(rf'<w:{tag}(?:/>|\s+w:val="([^"]*)"\s*/>)', rpr)
        return m is not None and m.group(1) not in ("0", "false", "none")

    for tag, name in (("i", "italic"), ("b", "bold"), ("strike", "strike"),
                      ("smallCaps", "smallCaps")):
        if on(tag):
            found.add(name)
    va = re.search(r'<w:vertAlign w:val="([^"]+)"/>', rpr)
    if va:
        found.add(va.group(1))
    return frozenset(found)


def _char_fmt(p_xml: str) -> tuple[str, list[frozenset[str]]]:
    """Per-character formatting over the prose (``<w:t>``) text.

    Hyperlink-styled runs contribute EMPTY formatting: their underline
    and colour are structural, not an author's emphasis, and counting
    them makes every link a formatting difference.
    """
    text: list[str] = []
    fmt: list[frozenset[str]] = []
    for run in RUN_RE.finditer(p_xml):
        body = run.group(1)
        rpr_m = RPR_RE.search(body)
        rpr = rpr_m.group(1) if rpr_m else None
        is_hyper = rpr is not None and 'w:val="Hyperlink"' in rpr
        flags = frozenset[str]() if is_hyper else _flags(rpr)
        for t in WT_RE.findall(body):
            for ch in html.unescape(t):
                text.append(ch)
                fmt.append(flags)
    return "".join(text), fmt


def _omml(p_xml: str) -> list[tuple[str, str]]:
    """(structural skeleton, token stream) for each oMath in a paragraph."""
    out: list[tuple[str, str]] = []
    for m in OMATH_RE.finditer(p_xml):
        block = m.group(0)
        skel = "/".join(OMML_STRUCT_RE.findall(block))
        toks = html.unescape("".join(MT_RE.findall(block)))
        out.append((skel, toks))
    return out


def _fields(p_xml: str) -> Fields:
    """Citation/cross-ref machinery present in the paragraph."""
    anchors = re.findall(r'w:anchor="([^"]+)"', p_xml)
    hl = re.findall(r'HYPERLINK[^"]*"([^"]+)"', p_xml)
    cites = re.findall(r'w:name="(cite_[^"]+)"', p_xml)
    return {"anchors": anchors + hl, "cites": cites,
            "footnotes": p_xml.count("w:footnoteReference")}


class Para:
    """One paragraph, with every layer's view of it precomputed.

    ``__slots__`` on purpose: a manuscript is tens of thousands of these
    and they are built for every comparison. A reviewer proposed a
    dataclass for extensibility; the memory argument still holds, and a
    new field costs one line here.
    """

    __slots__ = (
        "fields",
        "fmt",
        "mtext",
        "omml",
        "pid",
        "text",
        "wtext",
        "wtext_f",
        "xml",
    )

    xml: str
    wtext: str
    wtext_f: str
    mtext: str
    text: str
    fmt: list[frozenset[str]]
    omml: list[tuple[str, str]]
    fields: Fields
    pid: str | None

    def __init__(self, xml: str) -> None:
        self.xml = xml
        self.wtext = html.unescape("".join(WT_RE.findall(xml)))
        self.mtext = html.unescape("".join(MT_RE.findall(xml)))
        self.text = (self.wtext + self.mtext).strip()
        self.wtext_f, self.fmt = _char_fmt(xml)
        self.omml = _omml(xml)
        self.fields = _fields(xml)
        m = PARAID_RE.search(xml)
        self.pid = m.group(1) if m else None


# ------------------------------------------------------------- the parts
#: Every part that carries prose a reader sees. Until 2026-08-06 this
#: comparison covered `word/document.xml` ALONE: footnotes.xml was read
#: and then dropped on the floor (its locals were never used), and
#: headers, footers and endnotes were never opened. Across the 507 real
#: manuscripts here that is 1,111 header/footer parts, 340 footnote parts
#: and 306 endnote parts the authoritative gate certified as "unchanged"
#: without ever looking at them — a false negative in the one tool whose
#: whole job is to certify that no edit was lost.
TEXT_PART_RE = re.compile(
    r"^word/(document|footnotes|endnotes|header\d*|footer\d*)\.xml$")
COMMENTS_PART = "word/comments.xml"

#: Report order, so two runs list their parts the same way.
_PART_RANK = ("document", "footnotes", "endnotes", "header", "footer")

#: Field types whose cached RESULT is a rendering artifact, not content.
#: Word stores the page an instance last happened to be laid out on, so
#: two copies of one document disagree: in this corpus DSI's footer1.xml
#: caches "2" in 34 files and "11" in 38, and LI's caches "2", "1",
#: "Page 1" and "Page  of" (that last from a field never rendered).
#: Diffing those raw would have failed every paper's --expect-clean on
#: the day headers were included. Only the RESULT is masked — the field
#: code is left alone, so a field the author replaced with typed text
#: still reports as a text change.
VOLATILE_FIELDS = frozenset({
    "PAGE", "NUMPAGES", "SECTIONPAGES", "PAGEREF", "DATE", "TIME",
    "CREATEDATE", "SAVEDATE", "PRINTDATE", "EDITTIME", "REVNUM",
    "FILENAME", "FILESIZE", "LASTSAVEDBY", "NUMCHARS", "NUMWORDS",
})

INSTR_RE = re.compile(r"<w:instrText[^>]*>([^<]*)</w:instrText>")
SEPARATE_RE = re.compile(r'<w:fldChar\b[^>]*w:fldCharType="separate"[^>]*/>')
FLDSIMPLE_RE = re.compile(
    r'<w:fldSimple\b[^>]*w:instr="([^"]*)"[^>]*>(?:(?!</?w:fldSimple).)*'
    r"</w:fldSimple>", re.DOTALL)


def _keyword(instr: str) -> str:
    """A field instruction's type: ``' PAGE  \\* MERGEFORMAT '`` -> PAGE."""
    words = html.unescape(instr).split()
    return words[0].upper() if words else ""


def _mask_text(xml: str, token: str) -> str:
    """Replace the ``<w:t>`` text in `xml` with `token`, once."""
    first = True

    def sub(m: re.Match[str]) -> str:
        nonlocal first
        keep = token if first else ""
        first = False
        return m.group(1) + keep + m.group(3)

    return T_PARTS_RE.sub(sub, xml)


def mask_volatile_fields(xml: str) -> str:
    """Neutralise cached PAGE/DATE/... results, leaving the field intact."""
    regions: list[tuple[int, int, str]] = []
    for start, end, body in field_spans(xml):
        kw = _keyword(" ".join(INSTR_RE.findall(body)))
        if kw not in VOLATILE_FIELDS:
            continue
        sep = SEPARATE_RE.search(body)
        if not sep:                      # no cached result to mask
            continue
        result_at = start + sep.end()
        # field_spans yields outermost-first, so a nested field inside a
        # region already claimed is covered by it.
        if regions and result_at < regions[-1][1]:
            continue
        regions.append((result_at, end, kw))
    out = xml
    for s, e, kw in reversed(regions):   # right to left: offsets stay valid
        out = out[:s] + _mask_text(out[s:e], f"«F:{kw}»") + out[e:]

    def simple(m: re.Match[str]) -> str:
        kw = _keyword(m.group(1))
        if kw not in VOLATILE_FIELDS:
            return m.group(0)
        return _mask_text(m.group(0), f"«F:{kw}»")

    return FLDSIMPLE_RE.sub(simple, out)


class Part:
    """One text-bearing part, with its paragraphs already extracted."""

    __slots__ = ("blob", "label", "name", "paras", "xml")

    name: str
    label: str
    xml: str
    paras: list[Para]
    blob: str

    def __init__(self, name: str, xml: str) -> None:
        self.name = name
        stem = name[len("word/"):-len(".xml")]
        # The body keeps an unlabelled report: a body-only document must
        # read exactly as it did before parts existed.
        self.label = "body" if stem == "document" else stem
        self.xml = mask_volatile_fields(xml)
        self.paras = [p for p in (Para(x) for x in P_RE.findall(self.xml))
                      if p.text]
        self.blob = " ".join(p.text for p in self.paras)


class Doc:
    """A package, as the comparison sees it: parts, and its comments."""

    __slots__ = ("comments", "parts", "path")

    path: str
    parts: list[Part]
    comments: list[tuple[str, str, str]]

    def __init__(self, path: str, parts: list[Part],
                 comments: list[tuple[str, str, str]]) -> None:
        self.path = path
        self.parts = parts
        self.comments = comments


def _rank(name: str) -> tuple[int, str]:
    stem = name[len("word/"):-len(".xml")]
    for i, kind in enumerate(_PART_RANK):
        if stem.startswith(kind):
            return (i, name)
    return (len(_PART_RANK), name)


def load_parts(raw: dict[str, bytes], path: str = "") -> Doc:
    """The parts dict view, so a caller holding a package (the sweep, a
    build in memory) can diff without writing a file first."""
    parts = [Part(n, raw[n].decode("utf-8"))
             for n in sorted(raw, key=_rank) if TEXT_PART_RE.match(n)]
    return Doc(path, parts, _read_comments(raw))


def load(path: str) -> Doc:
    with zipfile.ZipFile(path) as z:
        raw = {n: z.read(n) for n in z.namelist()
               if TEXT_PART_RE.match(n) or n == COMMENTS_PART}
    return load_parts(raw, path)


def pair_parts(a: list[Part],
               b: list[Part]) -> list[tuple[Part | None, Part | None]]:
    """(A part, B part) pairs; None on either side means it exists once.

    Name first — document/footnotes/endnotes are fixed names and always
    pair. Headers and footers are NOT: their numbering follows the
    section that references them, so a section edit renumbers header2 to
    header3 and a name-only pairing would report both as
    added-and-removed. Leftovers therefore pair on text similarity.
    """
    b_by_name = {p.name: p for p in b}
    pairs: list[tuple[Part | None, Part | None]] = []
    matched: set[str] = set()
    spare_a: list[Part] = []
    for pa in a:
        pb = b_by_name.get(pa.name)
        if pb is None:
            spare_a.append(pa)
        else:
            pairs.append((pa, pb))
            matched.add(pb.name)
    spare_b = [pb for pb in b if pb.name not in matched]

    for pa in list(spare_a):
        best: Part | None = None
        score = 0.0
        for pb in spare_b:
            r = SequenceMatcher(None, pa.blob, pb.blob,
                                autojunk=False).ratio()
            if r > score:
                best, score = pb, r
        if best is not None and score >= 0.6:
            pairs.append((pa, best))
            spare_a.remove(pa)
            spare_b.remove(best)
    pairs.extend((pa, None) for pa in spare_a)
    pairs.extend((None, pb) for pb in spare_b)
    return pairs
