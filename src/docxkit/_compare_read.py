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

import hashlib
import html
import posixpath
import re
import zipfile
from difflib import SequenceMatcher
from typing import TypedDict

from ._xml import (
    COMMENTS,
    INSTR_RE,
    MT_RE,
    OMML_STRUCT_RE,
    SEPARATE_RE,
    T_PARTS_RE,
    WT_RE,
    field_spans,
    printed_text,
)
from .comments import read_all as _read_comments
from .equations import tokens
from .styles import Cascade

# ------------------------------------------------------------- extraction
P_RE = re.compile(r"<w:p[ >].*?</w:p>", re.DOTALL)
OMATH_RE = re.compile(r"<m:oMath>.*?</m:oMath>", re.DOTALL)
# `(?<!/)>`: a self-closing `<w:r/>` is an EMPTY run, and pairing it
# with the next close merged it with the real run after it, so this
# layer read the EMPTY run's properties as that run's. See `_xml.RUN_RE`
# — 28 of 899 manuscripts carry one.
RUN_RE = re.compile(r"<w:r\b[^>]*(?<!/)>(.*?)</w:r>", re.DOTALL)
RPR_RE = re.compile(r"<w:rPr>(.*?)</w:rPr>", re.DOTALL)
PARAID_RE = re.compile(r'w14:paraId="([0-9A-Fa-f]+)"')

#: `OMML_STRUCT_RE` is imported, not defined: `equations.skeleton` reads
#: the same structural elements, and this layer decides whether an
#: equation was rewritten by comparing exactly that skeleton. Two copies
#: agreed on the day they were merged; the next element added to one of
#: them would have split the answer from its own definition.
#:
#: `OMATH_RE` above stays local, and that difference is real rather than
#: drift: this layer reads document PARTS, where Word writes the tag
#: bare, while `equations` also reads harvested elements, which carry
#: xmlns:m when serialized alone. Measured over 282 manuscripts holding
#: OMML: not one writes an attribute on `m:oMath` inside a part.


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


#: Properties reported as a resolved VALUE rather than as on/off, and
#: only when a `Cascade` can resolve them. Both were invisible to every
#: layer until 2026-08-10: `--expect-clean` printed OK on a pair whose
#: whole difference was 25 runs' size and colour.
#:
#: They are resolved rather than read off the run because Word deletes a
#: direct property equal to the inherited one, so comparing what is
#: STATED reports a difference on documents that render identically —
#: which is how a check that cries wolf gets written. See
#: :class:`docxkit.styles.Cascade`.
_VALUED = (("sz", "size"), ("color", "colour"))


def _valued(cascade: Cascade, rpr: str | None,
            pstyle: str | None) -> frozenset[str]:
    if not cascade.known:
        return frozenset()              # no styles part: no honest answer
    rstyle = cascade.style_of(rpr)
    out: set[str] = set()
    for prop, label in _VALUED:
        value = cascade.of(prop, rpr=rpr, rstyle=rstyle, pstyle=pstyle)
        # `auto` and "nothing" are the same claim about colour, and Word
        # writes each in different years of the same document
        if value in (None, "auto"):
            continue
        out.add(f"{label} {value}")
    return frozenset(out)


def _char_fmt(p_xml: str, cascade: Cascade | None = None
              ) -> tuple[str, list[frozenset[str]]]:
    """Per-character formatting over the prose (``<w:t>``) text.

    Hyperlink-styled runs contribute no EMPHASIS: their underline is
    structural, not an author's emphasis, and counting it makes every
    link a formatting difference. Their size and colour are compared
    like anything else's — resolved through the Hyperlink style, so the
    ordinary case is equal on both sides and a link that really changed
    colour is not waved through. One manuscript's citation links sat in
    Word's default blue while every other link in the paper was the
    house navy, and nothing said so.
    """
    cascade = cascade if cascade is not None else Cascade()
    pstyle = Cascade.paragraph_style(p_xml)
    text: list[str] = []
    fmt: list[frozenset[str]] = []
    for run in RUN_RE.finditer(p_xml):
        body = run.group(1)
        rpr_m = RPR_RE.search(body)
        rpr = rpr_m.group(1) if rpr_m else None
        is_hyper = rpr is not None and 'w:val="Hyperlink"' in rpr
        flags = (frozenset[str]() if is_hyper else _flags(rpr)) \
            | _valued(cascade, rpr, pstyle)
        for t in WT_RE.findall(body):
            for ch in html.unescape(t):
                text.append(ch)
                fmt.append(flags)
    return "".join(text), fmt


MATH_RUN_RE = re.compile(r"<m:r\b[^>]*(?<!/)>.*?</m:r>", re.DOTALL)

#: Typography inside an equation that changes what a symbol IS: upright
#: against math-italic, bold, script, size. A change to any of these was
#: invisible to every layer of the comparison — FORMULA compares the
#: token stream and the structural skeleton, neither of which moves when
#: a variable stops being italic, and FORMAT walks <w:t> runs, which an
#: equation has none of. An author's italics fix could be dropped by a
#: rebuild and --expect-clean would still say clean.
#:
#: Deliberately NOT here: w:rFonts (the Cambria Math declaration on all
#: 51,877 runs in this corpus — boilerplate), w:lang (Word rewrites it
#: unprompted), the *Cs complex-script mirrors of sz and b (one change
#: would report twice), and w:color/w:highlight (review decoration a
#: build is not expected to carry, not the symbol's identity).
MATH_FMT_RE = re.compile(
    r"<(m:nor|m:sty|m:scr|w:i|w:b|w:sz|w:vertAlign)\b[^>]*?"
    r'(?:\s[mw]:val="([^"]*)")?\s*/?>')


def _fmt_markers(run_xml: str) -> str:
    """One math run's typography, as a sorted comparable string."""
    marks: list[str] = []
    for m in MATH_FMT_RE.finditer(run_xml):
        tag, val = m.group(1).split(":")[1], m.group(2)
        if val in ("0", "false", "none"):    # explicitly switched OFF
            continue
        marks.append(tag if val is None else f"{tag}={val}")
    return ",".join(sorted(marks))


def _omml(p_xml: str) -> list[tuple[str, str, list[str]]]:
    """(skeleton, token stream, per-CHARACTER typography) per oMath.

    Per character, not per run, for the reason every anchor in this
    toolkit is: Word fragments runs at rsid boundaries, so the same
    equation is 45 runs in one save and 43 in the next. A positional
    per-run fingerprint shifts against itself and reports typography
    that nobody touched — measured on le2_expanded against le3, where
    19 runs "differed" and not one character's formatting had changed.
    `_char_fmt` takes the same per-character view of prose.
    """
    out: list[tuple[str, str, list[str]]] = []
    for m in OMATH_RE.finditer(p_xml):
        block = m.group(0)
        skel = "/".join(OMML_STRUCT_RE.findall(block))
        # `equations.tokens`, not a second copy of the same join: this
        # WAS the copy, and it went on reading the runs alone after the
        # shared one learned to read a delimiter's `m:sepChr` — the
        # character Word draws between two arguments and stores in an
        # attribute. `(a+b)` against `(a−b)` was clean on every layer.
        toks = tokens(block)
        marks: list[str] = []
        for r in MATH_RUN_RE.finditer(block):
            marker = _fmt_markers(r.group(0))
            text = html.unescape("".join(MT_RE.findall(r.group(0))))
            marks.extend([marker] * len(text))
        out.append((skel, toks, marks))
    return out


def _fields(p_xml: str) -> Fields:
    """Citation/cross-ref machinery present in the paragraph."""
    anchors = re.findall(r'w:anchor="([^"]+)"', p_xml)
    hl = re.findall(r'HYPERLINK[^"]*"([^"]+)"', p_xml)
    cites = re.findall(r'w:name="(cite_[^"]+)"', p_xml)
    return {"anchors": anchors + hl, "cites": cites,
            "footnotes": p_xml.count("w:footnoteReference")}


#: The container tags that give a paragraph an address. `\b` keeps
#: <w:tblPr>, <w:trPr>, <w:tcPr> and <w:pPr> out of it: after "tbl"
#: comes "P", both word characters, so there is no boundary to match.
#: `(?<!/)>` keeps an EMPTY `<w:p/>` out of the walk, matching the
#: reading `_xml.PARA_RE` has: an empty paragraph is not a paragraph a
#: report addresses. The close-tag form is unaffected — the character
#: before its `>` is the tag name, not a slash.
STRUCT_TAG_RE = re.compile(r"<(/?)w:(tbl|tr|tc|p)\b[^>]*?(?<!/)>")


def _addresses(xml: str) -> dict[int, str]:
    """Offset -> "table 3 r2c1" for every paragraph inside a table.

    A report that says "paragraph 145" makes a reader count paragraphs;
    one that says which cell of which table sends them straight there,
    and a results table is where the numbers that matter live. Tables
    are numbered in document order, so they agree with
    `tables.read_all`, and nested tables read outer > inner.
    """
    out: dict[int, str] = {}
    stack: list[list[int]] = []          # [table, row, cell] per nesting
    tables = 0
    for m in STRUCT_TAG_RE.finditer(xml):
        closing, tag = m.group(1), m.group(2)
        if tag == "tbl":
            if closing:
                if stack:
                    stack.pop()
            else:
                tables += 1
                stack.append([tables, 0, 0])
        elif closing or not stack:
            continue                     # </tr>, </tc>, </p>, or no table
        elif tag == "tr":
            stack[-1][1] += 1
            stack[-1][2] = 0
        elif tag == "tc":
            stack[-1][2] += 1
        elif tag == "p":
            out[m.start()] = " > ".join(f"table {t} r{r}c{c}"
                                        for t, r, c in stack)
    return out


class Para:
    """One paragraph, with every layer's view of it precomputed.

    ``__slots__`` on purpose: a manuscript is tens of thousands of these
    and they are built for every comparison. A reviewer proposed a
    dataclass for extensibility; the memory argument still holds, and a
    new field costs one line here.
    """

    __slots__ = (
        "at",
        "fields",
        "fmt",
        "mtext",
        "omml",
        "omml_fmt",
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
    omml_fmt: list[list[str]]
    fields: Fields
    pid: str | None
    at: str                 # "table 3 r2c1", or "" outside a table

    def __init__(self, xml: str, at: str = "",
                 cascade: Cascade | None = None) -> None:
        self.xml = xml
        self.at = at
        # `printed_text`, not a `w:t` walk: a no-break hyphen, a tab
        # and a line break are characters on the PAGE, and this is
        # the stream the TEXT layer compares. Walking `w:t` alone
        # made six hyphens deleted from Aging_Well's citations read
        # as no change at all (backlog S1).
        self.wtext = printed_text(xml)
        self.mtext = html.unescape("".join(MT_RE.findall(xml)))
        self.text = (self.wtext + self.mtext).strip()
        self.wtext_f, self.fmt = _char_fmt(xml, cascade)
        # The equation's identity and its typography are kept apart: a
        # report entry carries the (skeleton, tokens) pair it always
        # did, so the JSON shape papers read is unchanged.
        equations = _omml(xml)
        self.omml = [(skel, toks) for skel, toks, _ in equations]
        self.omml_fmt = [fmt for _, _, fmt in equations]
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
COMMENTS_PART = COMMENTS
#: Not compared itself — read so the FORMAT layer can RESOLVE size and
#: colour rather than compare what each run happens to state.
STYLES_PART = "word/styles.xml"

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


#: The binary parts a READER sees. Not compared until 2026-08-24, and
#: the STRUCTURE layer's own header said "part added / removed" the
#: whole time: a figure replaced with a different chart, overwritten
#: with a 48-byte stub, or deleted from the package outright all
#: reported as zero changes (found on HCW, whose entire deliverable that
#: round was four replaced images).
#:
#: `word/embeddings/` is here for the same reason as `word/media/`: an
#: embedded workbook behind a chart is content a reader can open.
MEDIA_PART_RE = re.compile(r"^word/(?:media|embeddings)/")

#: NOT compared, and the exclusion is measured rather than assumed.
#: Word regenerates the thumbnail from whatever the first page renders
#: to, so a document opened and saved with nothing changed comes back
#: with different bytes — a difference on every author round-trip is a
#: difference nobody reads.
_VOLATILE_MEDIA = re.compile(r"^docProps/thumbnail")


class Media:
    """One binary part: what it is called, how big, and what it holds."""

    __slots__ = ("digest", "label", "name", "size")

    name: str
    size: int
    digest: str
    label: str
    """The exhibit it belongs to, when the document says — "Figure 8.a.
    Mortality and LFP". Empty when nothing nearby names it."""

    def __init__(self, name: str, size: int, digest: str,
                 label: str = "") -> None:
        self.name, self.size, self.digest, self.label = (name, size, digest,
                                                         label)


_REL_RE = re.compile(r"<Relationship\b[^>]*>")
_ID_RE = re.compile(r'Id="([^"]+)"')
_TARGET_RE = re.compile(r'Target="([^"]+)"')
#: Every way a part points at a media part: DrawingML uses r:embed (and
#: r:link for a linked image), VML uses r:id on v:imagedata. A hyperlink
#: also carries r:id, which is why the id is resolved through the rels
#: and only kept when it lands on a media part.
_RID_RE = re.compile(r'r:(?:embed|link|id)="([^"]+)"')


def _rel_targets(rels: str, base: str) -> dict[str, str]:
    """rId -> the part it names, resolved against `base` ("word/")."""
    out: dict[str, str] = {}
    for element in _REL_RE.findall(rels):
        rid, target = _ID_RE.search(element), _TARGET_RE.search(element)
        if not rid or not target:
            continue
        path = target.group(1).replace("\\", "/")
        if path.startswith("/"):
            out[rid.group(1)] = path.lstrip("/")
            continue
        out[rid.group(1)] = posixpath.normpath(base + path)
    return out


def _media_labels(raw: dict[str, bytes]) -> dict[str, str]:
    """media part -> the caption of the exhibit that draws it.

    "word/media/image14.png" alone sends a reader to a folder; "Figure
    8.a" sends them to the page. The walk is the one `crossrefs`
    already does — a drawing carries an rId, the part's rels say which
    file that is — and the caption is the nearest paragraph with text,
    looking DOWN first because a figure's caption sits under it in
    every one of these manuscripts.
    """
    labels: dict[str, str] = {}
    for name in sorted(raw):
        if not TEXT_PART_RE.match(name):
            continue
        rels = raw.get(f"word/_rels/{name[len('word/'):]}.rels")
        if not rels:
            continue
        targets = _rel_targets(rels.decode("utf-8", "replace"), "word/")
        paras = [m.group(0) for m in P_RE.finditer(
            raw[name].decode("utf-8", "replace"))]
        texts = [printed_text(p).strip() for p in paras]
        for i, para in enumerate(paras):
            drawn = {targets.get(rid) for rid in _RID_RE.findall(para)}
            hit = {t for t in drawn if t and MEDIA_PART_RE.match(t)}
            if not hit:
                continue
            # the caption below first — that is where a figure's
            # sits in every one of these manuscripts — then above
            near = [texts[i], *texts[i + 1:i + 3],
                    *reversed(texts[max(0, i - 2):i])]
            caption = next((t for t in near if t), "")
            for target in hit:
                labels.setdefault(target, caption[:60])
    return labels


def _media_of(raw: dict[str, bytes]) -> dict[str, Media]:
    labels = _media_labels(raw)
    return {name: Media(name, len(blob),
                        hashlib.sha256(blob).hexdigest(), labels.get(name, ""))
            for name, blob in raw.items()
            if MEDIA_PART_RE.match(name) and not _VOLATILE_MEDIA.match(name)}


class Part:
    """One text-bearing part, with its paragraphs already extracted."""

    __slots__ = ("blob", "label", "name", "paras", "xml")

    name: str
    label: str
    xml: str
    paras: list[Para]
    blob: str

    def __init__(self, name: str, xml: str,
                 cascade: Cascade | None = None) -> None:
        self.name = name
        stem = name[len("word/"):-len(".xml")]
        # The body keeps an unlabelled report: a body-only document must
        # read exactly as it did before parts existed.
        self.label = "body" if stem == "document" else stem
        self.xml = mask_volatile_fields(xml)
        at = _addresses(self.xml)
        self.paras = [p for p in (Para(m.group(0), at.get(m.start(), ""),
                                       cascade)
                                  for m in P_RE.finditer(self.xml))
                      if p.text]
        self.blob = " ".join(p.text for p in self.paras)


class Doc:
    """A package as the comparison sees it: parts, comments, and media."""

    __slots__ = ("comments", "media", "parts", "path")

    path: str
    parts: list[Part]
    comments: list[tuple[str, str, str]]
    media: dict[str, Media]
    """The binary parts, by name. Empty when the caller passed a parts
    dict holding none — which is not the same as a document with no
    figures, and is why `compare_media` reports nothing when BOTH sides
    are empty rather than treating one side's absence as a deletion."""

    def __init__(self, path: str, parts: list[Part],
                 comments: list[tuple[str, str, str]],
                 media: dict[str, Media] | None = None) -> None:
        self.path = path
        self.parts = parts
        self.comments = comments
        self.media = media or {}


def _rank(name: str) -> tuple[int, str]:
    stem = name[len("word/"):-len(".xml")]
    for i, kind in enumerate(_PART_RANK):
        if stem.startswith(kind):
            return (i, name)
    return (len(_PART_RANK), name)


def load_parts(raw: dict[str, bytes], path: str = "") -> Doc:
    """The parts dict view, so a caller holding a package (the sweep, a
    build in memory) can diff without writing a file first.

    Include ``word/styles.xml`` if you have it: without it the FORMAT
    layer compares emphasis only, because size and colour cannot be
    resolved and comparing what a run merely STATES reports a difference
    on documents that render identically.
    """
    cascade = Cascade(raw[STYLES_PART].decode("utf-8")
                      if STYLES_PART in raw else None)
    parts = [Part(n, raw[n].decode("utf-8"), cascade)
             for n in sorted(raw, key=_rank) if TEXT_PART_RE.match(n)]
    return Doc(path, parts, _read_comments(raw), _media_of(raw))


def load(path: str) -> Doc:
    """Read the parts the comparison needs, and only those.

    The rels are read as well as the parts: without them a media part
    can be compared but not NAMED, and "word/media/image14.png changed"
    sends a reader to a folder where "Figure 8.a" sends them to the
    page.
    """
    with zipfile.ZipFile(path) as z:
        raw = {n: z.read(n) for n in z.namelist()
               if TEXT_PART_RE.match(n)
               or MEDIA_PART_RE.match(n)
               or n.startswith("word/_rels/")
               or n in (COMMENTS_PART, STYLES_PART)}
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
