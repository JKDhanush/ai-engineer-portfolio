"""Tests for ingest.structure: Part 1 = numbering markers, Part 2 = the tree (hand-made lines + a real PDF)."""

from pathlib import Path

import pytest

from ingest.models import Line, RawDocument
from ingest.pdf_reader import read_pdf
from ingest.structure import Marker, build_tree, classify_marker

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


# ================================================================ Part 1: classify_marker
@pytest.mark.parametrize(
    "text, expected",
    [
        ("38. Updation / Periodic Updation of KYC", Marker("para", "38", "Updation / Periodic Updation of KYC")),
        ("45A. Money Laundering risk assessment", Marker("para", "45A", "Money Laundering risk assessment")),
        ("(1) V-CIP Infrastructure", Marker("paren_num", "1", "V-CIP Infrastructure")),
        ("2) the account holder", Marker("num_paren", "2", "the account holder")),
        ("(ii) The bank shall ensure", Marker("paren_roman", "ii", "The bank shall ensure")),
        ("(xiv) a person", Marker("paren_roman", "xiv", "a person")),
        ("(a) V-CIP Infrastructure", Marker("paren_alpha", "a", "V-CIP Infrastructure")),
        ("(c) the trustee", Marker("paren_alpha", "c", "the trustee")),
        ("xv. Shell Bank means", Marker("dot_roman", "xv", "Shell Bank means")),
        ("d. Where the customer is a trust", Marker("dot_alpha", "d", "Where the customer is a trust")),
    ],
)
def test_marker_styles(text, expected):
    assert classify_marker(text) == expected


def test_marker_lone_paragraph_number():
    assert classify_marker("61.") == Marker("para", "61", "")


@pytest.mark.parametrize("letter", ["i", "v", "x"])
def test_marker_ambiguous_letters_default_to_roman(letter):
    assert classify_marker(f"({letter}) text").style == "paren_roman"
    assert classify_marker(f"{letter}. text").style == "dot_roman"


@pytest.mark.parametrize("letter, before", [("i", "h"), ("v", "u"), ("x", "w")])
def test_marker_ambiguous_letters_after_their_alphabet_neighbour_are_alpha(letter, before):
    assert classify_marker(f"({letter}) text", last_alpha=before).style == "paren_alpha"
    assert classify_marker(f"{letter}. text", last_alpha=before).style == "dot_alpha"


def test_marker_roman_ii_is_roman_even_after_h():
    # only the single letters i/v/x are ambiguous; "ii" is always roman
    assert classify_marker("(ii) text", last_alpha="h").style == "paren_roman"


@pytest.mark.parametrize(
    "text",
    ["The bank shall", "2025 (Updated as on October 1, 2026)", "Reserve Bank of India", "", "Chapter VI"],
)
def test_marker_none_for_plain_text(text):
    assert classify_marker(text) is None


# ================================================================ Part 2: the tree
def lines(*specs) -> RawDocument:
    """(text, bold) or (text, bold, x0) tuples -> RawDocument, all on page 1, left margin x0=72."""
    ls = [Line(page=1, text=s[0], size=12.0, bold=s[1], x0=s[2] if len(s) > 2 else 72.0) for s in specs]
    return RawDocument(path="t.pdf", page_count=1, lines=ls, footnotes=[], tables=[])


SAMPLE = lines(
    ("Chapter VI – Customer Due Diligence (CDD) Procedure", True),
    ("E. On-going Due Diligence", True),
    ("38. Banks shall carry out periodic updation of KYC as under:", False),
    ("(1) Individuals:", False),
    ("(i) no change in KYC information: a self-declaration", False),
    ("from the customer shall suffice.", False),
    ("(ii) change in address: a self-declaration of the new", False),
    ("address shall be obtained.", False),
    ("(2) Customers other than individuals:", False),
    ("39. Next paragraph", False),
)


def test_tree_shape_and_citations():
    tree = build_tree(SAMPLE)
    cites = [n.citation() for n in tree.walk() if n.kind != "root"]
    assert "Chapter VI > E. On-going Due Diligence > Para 38(1)(ii)" in cites
    assert "Chapter VI > E. On-going Due Diligence > Para 38(2)" in cites
    assert "Chapter VI > E. On-going Due Diligence > Para 39" in cites


def test_wrapped_lines_join_into_one_text():
    tree = build_tree(SAMPLE)
    node = next(n for n in tree.walk() if n.citation().endswith("38(1)(i)"))
    assert node.text == "no change in KYC information: a self-declaration from the customer shall suffice."


def test_lone_marker_is_glued_to_next_line():
    tree = build_tree(lines(("4.", False), ("These directions shall also apply", False)))
    para = next(n for n in tree.walk() if n.kind == "para")
    assert (para.label, para.text) == ("4", "These directions shall also apply")


def test_out_of_sequence_number_is_text_not_a_paragraph():
    tree = build_tree(lines(
        ("28. Notwithstanding anything contained in paragraph 23,", False),
        ("the bank shall establish identity as per paragraphs 26 and", False),
        ("27.", False),
        ("(ix) The bank shall not allow foreign remittance", False),
    ))
    assert [n.label for n in tree.walk() if n.kind == "para"] == ["28"]


def test_indented_numbered_list_nests_inside_paragraph():
    tree = build_tree(lines(
        ("3. Definitions", True),
        ("1. Controlling ownership interest means ...", False, 118.0),
        ("2. Control shall include ...", False, 118.0),
        ("4. Next paragraph", False),
    ))
    assert [n.label for n in tree.walk() if n.kind == "para"] == ["3", "4"]
    assert [n.citation() for n in tree.walk() if n.kind == "dot_num"] == ["Para 3(1)", "Para 3(2)"]


def test_chapter_title_on_next_bold_line():
    tree = build_tree(lines(("CHAPTER  I", True), ("PRELIMINARY", True), ("1. Short Title", True)))
    chapter = tree.children[0]
    assert (chapter.label, chapter.title) == ("I", "PRELIMINARY")


# ---------------------------------------------------------------- real document (slow)
@pytest.fixture(scope="module")
def cb_tree():
    path = RAW / "2025-11-28_cb-kyc-directions-2025.pdf"
    if not path.exists():
        pytest.skip("PDF not downloaded")
    return build_tree(read_pdf(path))


@pytest.mark.slow
def test_real_chapters(cb_tree):
    labels = [c.label for c in cb_tree.children if c.kind == "chapter" and c.label]
    assert labels == ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"]


@pytest.mark.slow
def test_real_paragraphs_are_in_sequence(cb_tree):
    nums = [int(n.label.rstrip("ABCDEFGH")) for n in cb_tree.walk() if n.kind == "para"]
    main = nums[: nums.index(83) + 1]              # main body; annexes restart their own numbering
    assert main == list(range(1, 84))


@pytest.mark.slow
def test_real_citation(cb_tree):
    cites = {n.citation() for n in cb_tree.walk()}
    assert "Chapter VI > D. Identification of Beneficial Owner > Para 38(1)(ii)" in cites
