"""Tests for the citation self-check (app/citations.py)."""

from app.citations import REFUSAL, check_citations

SOURCES = [
    "42. (1) The bank shall carry out periodic updation at least once in every two years for high-risk customers, "
    "once in every eight years for medium risk customers and once in every 10 years for low-risk customers.",
    "28. Small account: the balance at any point of time does not exceed ₹50,000.",
]


def test_supported_answer_passes():
    answer = ("High-risk customers must be re-KYCed at least once every two years [S1]. "
              "A small account balance cannot exceed ₹50,000 [S2].")
    assert check_citations(answer, SOURCES).ok


def test_wrong_number_is_flagged():
    report = check_citations("High-risk customers must update KYC every three years [S1].", SOURCES)
    assert not report.ok and "3" in report.unsupported_numbers


def test_citation_to_missing_source_is_flagged():
    report = check_citations("Small accounts are limited to a balance of ₹50,000 [S7].", SOURCES)
    assert not report.ok and report.invalid_refs == [7]


def test_uncited_answer_is_not_ok():
    assert not check_citations("Banks must update KYC for high-risk customers every two years.", SOURCES).ok


def test_unrelated_sentence_is_weakly_supported():
    report = check_citations("Cryptocurrency exchanges must register with the stock exchange regulator [S2].", SOURCES)
    assert report.unsupported_sentences


def test_refusal_is_ok():
    report = check_citations(REFUSAL, SOURCES)
    assert report.ok and report.refused
