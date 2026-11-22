"""Tests for ingest.chunker on a small hand-made document (fast, no PDFs)."""

from ingest.chunker import MAX_CHILD_WORDS, build_chunks
from ingest.models import Footnote, Line, RawDocument, Table
from ingest.structure import build_tree


def make_doc(specs, footnotes=(), tables=()) -> RawDocument:
    lines = [Line(page=s[2] if len(s) > 2 else 1, text=s[0], size=12.0, bold=s[1], x0=72.0,
                  footnote_refs=list(s[3]) if len(s) > 3 else []) for s in specs]
    return RawDocument("t.pdf", 2, lines, list(footnotes), list(tables))


DOC = make_doc(
    [
        ("Chapter VI – Customer Due Diligence", True),
        ("E. On-going Due Diligence", True),
        ("38. Banks shall carry out periodic updation of KYC as under:", False),
        ("(1) Individuals: a self-declaration shall suffice where there is no change.", False),
        ("(2) Legal entities: the bank shall obtain a self-declaration from the entity.", False, 2, ["7"]),
        ("39. Customers shall be informed in advance.", False, 2),
    ],
    footnotes=[Footnote(page=2, marker="7", text="Substituted w.e.f. June 12, 2025")],
    tables=[Table(page=2, rows=[["Category", "Eligible investors"], ["I", "Central banks"], ["II", "Mutual funds"]])],
)


def chunks():
    return build_chunks(DOC, build_tree(DOC), "KYC Directions | RBI/1 | 28 Nov 2025")


def test_one_parent_per_paragraph_plus_table():
    parents, _ = chunks()
    assert [p.section_path for p in parents] == [
        "Chapter VI > E. On-going Due Diligence > Para 38",
        "Chapter VI > E. On-going Due Diligence > Para 39",
        "Table 1 (page 2)",
    ]


def test_parent_contains_all_clauses_in_order():
    parents, _ = chunks()
    text = parents[0].content
    assert text.index("38.") < text.index("(1) Individuals") < text.index("(2) Legal entities")


def test_footnote_attached_as_amendment_note():
    parents, _ = chunks()
    assert "Substituted w.e.f. June 12, 2025" in parents[0].content
    assert parents[0].metadata["amendments"] == ["[7] Substituted w.e.f. June 12, 2025"]


def test_children_point_to_their_parent_and_carry_context_header():
    parents, children = chunks()
    for c in children:
        assert c.context_header.startswith("KYC Directions | RBI/1 | 28 Nov 2025 | ")
        assert parents[c.parent_index].section_path.split(" > Para")[0] in c.section_path or "Table" in c.section_path
        assert len(c.content.split()) <= MAX_CHILD_WORDS + 40


def test_pages_span_the_paragraph():
    parents, _ = chunks()
    assert (parents[0].page_start, parents[0].page_end) == (1, 2)


def test_table_rows_are_header_value_lines():
    parents, children = chunks()
    table = parents[-1]
    assert "Category: II; Eligible investors: Mutual funds" in table.content
    assert any(c.parent_index == table.index for c in children)


def test_identical_text_has_identical_hash():
    _, children = chunks()
    a = children[0]
    b = type(a)(**{**a.__dict__, "context_header": "Other document | X | Y"})
    assert a.content_hash == b.content_hash
