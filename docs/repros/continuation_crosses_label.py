"""S6 repro: a Table's continuation claims a FIGURE's number.

`continuation_re(label, number)` anchors the bare number of a range or
list to a nearby plural-capable label, with a 30-character window
between the label's own number and the target.  The window is not
bounded by ANOTHER label, so "Tables 1 and 2 with Figures 1 and 3"
lets the TABLE pattern reach the 3 that belongs to the FIGURE list —
and because `link_more` walks the captions in document order and the
first claimer wins, the "3" a reader sees inside "Figures 1 and 3" is
linked to Table 3.

Visible text is unchanged, so nothing downstream can notice: the reader
clicks a figure number and lands on a table.
"""
from docxkit import crossrefs


def para(*runs: str) -> str:
    return "<w:p>" + "".join(runs) + "</w:p>"


def run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def doc(*paras: str) -> str:
    return ('<?xml version="1.0"?><w:document '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
            '2006/main"><w:body>' + "".join(paras) + "</w:body></w:document>")


PROSE = "Compare Tables 1 and 2 with Figures 1 and 3, and see Figures 2 here."

xml = doc(
    para(run(PROSE)),
    para(run("Table 3. Employment by sector.")),
    para(run("Figure 3. Trends in employment.")),
)

out, counts = crossrefs.link_more(xml)
print("counts:", counts)

# which anchor did the "3" of "Figures 1 and 3" get?
where = out.index("Figures 1 and")
tail = out[where:where + 400]
print()
print(tail[:400])
print()
print("the figure list's 3 is linked to:",
      "Table3" if 'w:anchor="Table3"' in tail else "Figure3 (or nothing)")
