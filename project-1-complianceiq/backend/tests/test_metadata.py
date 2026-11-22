"""Unit tests for ingest.metadata. No PDFs needed: headers are rebuilt from real RBI documents
as Line objects, so these run anywhere (including CI later)."""

from datetime import date

from ingest.metadata import extract_metadata, parse_date
from ingest.models import Line, RawDocument


def doc(*specs) -> RawDocument:
    """Build a RawDocument from (text, bold) or (text, bold, page) tuples."""
    lines = [Line(page=s[2] if len(s) > 2 else 1, text=s[0], size=12.0, bold=s[1]) for s in specs]
    return RawDocument(path="test.pdf", page_count=1, lines=lines, footnotes=[], tables=[])


# ---------------------------------------------------------------- parse_date
def test_parse_date_finds_date_inside_a_line():
    assert parse_date("DOR.AML.REC.No.88/14.01.002/2025-26   November 28, 2025") == date(2025, 11, 28)


def test_parse_date_single_digit_day():
    assert parse_date("(Updated as on October 1, 2026)") == date(2026, 10, 1)


def test_parse_date_none_when_absent():
    assert parse_date("Reserve Bank of India") is None


# ---------------------------------------------------------------- new 2025 directions
NEW_DIRECTIONS = doc(
    ("RBI/DOR/2025-26/169", False),
    ("DOR.AML.REC.No.88/14.01.002/2025-26 November 28, 2025", False),
    ("Reserve Bank of India (Commercial Banks – Know Your Customer) Directions,", True),
    ("2025 (Updated as on October 1, 2026)", True),
    ("Introduction", True, 3),
    ("In order to prevent banks and other financial institutions from being used", False, 3),
)


def test_new_directions_circular_numbers():
    m = extract_metadata(NEW_DIRECTIONS)
    assert m.circular_nos == ["RBI/DOR/2025-26/169", "DOR.AML.REC.No.88/14.01.002/2025-26"]


def test_new_directions_date():
    assert extract_metadata(NEW_DIRECTIONS).issued_on == date(2025, 11, 28)


def test_new_directions_title_joins_lines_strips_updated_and_stops_at_page_change():
    assert extract_metadata(NEW_DIRECTIONS).title == (
        "Reserve Bank of India (Commercial Banks – Know Your Customer) Directions, 2025"
    )


# ---------------------------------------------------------------- 2016 master direction
OLD_MASTER_DIRECTION = doc(
    ("RBI/DBR/2015-16/18", True),
    ("Master Direction DBR.AML.BC.No.81/14.01.001/2015-16", True),
    ("February 25, 2016", True),
    ("(Updated as on August 14, 2025)", True),
    ("(Updated as on June 12, 2025)", True),
    ("Master Direction - Know Your Customer (KYC) Direction, 2016", True),
    ("INTRODUCTION", True, 3),
)


def test_old_md_date_is_issue_date_not_an_updated_date():
    assert extract_metadata(OLD_MASTER_DIRECTION).issued_on == date(2016, 2, 25)


def test_old_md_circular_numbers():
    assert extract_metadata(OLD_MASTER_DIRECTION).circular_nos == [
        "RBI/DBR/2015-16/18", "DBR.AML.BC.No.81/14.01.001/2015-16",
    ]


def test_old_md_title_skips_updated_lines():
    assert extract_metadata(OLD_MASTER_DIRECTION).title == (
        "Master Direction - Know Your Customer (KYC) Direction, 2016"
    )


# ---------------------------------------------------------------- circular letter
CIRCULAR_LETTER = doc(
    ("RBI/2025-26/53", False),
    ("DOR.AML.REC.31/14.01.001/2025-26", False),
    ("June 12, 2025", False),
    ("The Chairpersons/ CEOs of all the Regulated Entities", False),
    ("Dear Sir/ Madam,", False),
    ("Updation/ Periodic Updation of KYC – Revised Instructions", True),
    ("Please refer to instructions on updation/ periodic updation of KYC as contained in", False),
    ("2. The Reserve Bank has observed a large pendency", False),
)


def test_letter_title_skips_non_bold_salutation():
    assert extract_metadata(CIRCULAR_LETTER).title == "Updation/ Periodic Updation of KYC – Revised Instructions"


def test_letter_fields():
    m = extract_metadata(CIRCULAR_LETTER)
    assert m.circular_nos == ["RBI/2025-26/53", "DOR.AML.REC.31/14.01.001/2025-26"]
    assert m.issued_on == date(2025, 6, 12)


# ---------------------------------------------------------------- body references must be ignored
DPSS_LETTER = doc(
    ("RBI/2025-26/101", False),
    ("CO.DPSS.POLC.No. S-955/02-30-010/2025-26", False),
    ("November 28, 2025", False),
    ("Madam / Sir,", False),
    ("Compliance with Know Your Customer (KYC) norms", True),
    ("The Reserve Bank has, today, repealed the RBI Master Direction", False),
    ("DBR.AML.BC.No.81/14.01.001/2015-16 dated February 25, 2016 (as updated from time to time)", False),
)


def test_circular_numbers_after_the_date_line_are_references_not_ours():
    assert extract_metadata(DPSS_LETTER).circular_nos == [
        "RBI/2025-26/101", "CO.DPSS.POLC.No. S-955/02-30-010/2025-26",
    ]


def test_dpss_title():
    assert extract_metadata(DPSS_LETTER).title == "Compliance with Know Your Customer (KYC) norms"


# ---------------------------------------------------------------- not an RBI header
MHA_ANNEX = doc(
    ("Annex – I", True),
    ("File No. 14014/01/2019/CFT", True),
    ("Government of India", True),
    ("Dated: the 2nd February, 2021", False),
    ("(Amended vide corrigendum dated March 15, 2023)", False),
)


def test_non_rbi_document_returns_empty_metadata():
    # "March 15, 2023" is a date, but no RBI circular number precedes it: not an RBI header.
    m = extract_metadata(MHA_ANNEX)
    assert (m.circular_nos, m.issued_on, m.title) == ([], None, None)


def test_respects_max_lines():
    late = doc(*[("filler", False)] * 30, ("RBI/2025-26/53", False), ("June 12, 2025", False))
    m = extract_metadata(late, max_lines=25)
    assert (m.circular_nos, m.issued_on, m.title) == ([], None, None)
