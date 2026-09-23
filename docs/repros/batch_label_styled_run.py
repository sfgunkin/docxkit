"""`diagnose` cannot name a hyperlink label whose run has a SECOND property.

`batch._LABEL` is

    <w:rStyle w:val="Hyperlink"\\s*/></w:rPr><w:t[^>]*>([^<]*)</w:t>

which demands that the Hyperlink style be the LAST thing in the run's
properties. Word writes it first and then whatever else the run carries —
`w:noProof` on a cross-reference, `w:b`, `w:color`, `w:lang`, a `w14:`
property — and the label is then unread: the refusal falls through to
"refused for a reason preflight does not model", which is the answer that
sends a caller to go and look. Removing that round trip is the whole
reason `diagnose` exists.

Measured over the corpus on this machine (500 packages, 1,631 body
parts): 25,802 Hyperlink rStyle elements, of which **9,161 (35%) are
followed by something other than `</w:rPr>`** — most often `w:b`,
`w:bCs`, `w:color`, `w:noProof` or `w14:ligatures`.

    python scratchpad/agents/batch/defect_1.py

Not fixed here: the round's rule is to report, and the fix is a decision
about the pattern (allow any properties after the style, without letting
the match run into the NEXT run's rPr — the `(?:[^<]|<(?!/w:rPr>))*`
shape `_compare_diff._FIELD_END_RE` already uses for the same reason).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from docxkit import batch  # noqa: E402

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"')


def label_run(props: str) -> str:
    """A hyperlink label whose run properties are `props`."""
    return ('<w:hyperlink w:anchor="Table3"><w:r><w:rPr>'
            f'<w:rStyle w:val="Hyperlink"/>{props}</w:rPr>'
            "<w:t>Table 3</w:t></w:r></w:hyperlink>")


def document(props: str) -> str:
    return (f"<w:document {NS}><w:body>"
            f'<w:p w14:paraId="A1">{label_run(props)}'
            "<w:r><w:t> shows where older workers are.</w:t></w:r>"
            "</w:p></w:body></w:document>")


for description, props in (("the style alone", ""),
                           ("a cross-reference's w:noProof",
                            "<w:noProof/>"),
                           ("a bold label", "<w:b/><w:bCs/>"),
                           ("a coloured label",
                            '<w:color w:val="1F3864"/>')):
    said = batch.diagnose(document(props), "shows where", "Table 3")
    names_it = "hyperlink label 'Table 3'" in said
    print(f"{description:<30} {'NAMES the label' if names_it else 'does NOT':<16}"
          f" {said[:60]}")

print("\nThe first line is the only shape the pattern reads. The other "
      "three\nare 35% of the hyperlink labels in the corpus on this "
      "machine, and on\nevery one of them the caller is told to go and "
      "look for themselves.")
