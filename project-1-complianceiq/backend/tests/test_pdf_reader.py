"""Integration tests for ingest.pdf_reader against the real RBI PDFs in data/raw/.
Skipped automatically if a PDF isn't present (e.g. on a fresh clone or in CI)."""

from pathlib import Path

import pytest

from ingest.pdf_reader import read_pdf

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
pytestmark = pytest.mark.slow  # every test in this file reads real PDFs


def load(name: str):
    path = RAW / name
    if not path.exists():
        pytest.skip(f"{name} not downloaded (see scripts/import_downloads.py)")
    return read_pdf(path)


@pytest.fixture(scope="module")
def cb_2025():
    return load("2025-11-28_cb-kyc-directions-2025.pdf")


@pytest.fixture(scope="module")
def md_2016():
    return load("2016-02-25_md-kyc-2016.pdf")


def test_header_survives_and_masthead_is_gone(cb_2025):
    texts = [ln.text for ln in cb_2025.lines[:3]]
    assert texts[0] == "RBI/DOR/2025-26/169"
    assert not any("RESERVE BANK OF INDIA" in t for t in texts)


def test_no_page_numbers_or_toc_left(cb_2025):
    assert not [ln for ln in cb_2025.lines if ln.text.isdigit()]
    assert not [ln for ln in cb_2025.lines if "......" in ln.text]
    assert cb_2025.dropped["toc"] >= 20


def test_headings_are_bold(cb_2025):
    heading = next(ln for ln in cb_2025.lines if ln.text.startswith("Chapter VI –"))
    assert heading.bold


def test_footnotes_capture_amendment_history(cb_2025):
    assert [f.marker for f in cb_2025.footnotes] == ["1", "2", "3"]
    assert "December 29, 2025" in cb_2025.footnotes[2].text


def test_tables_extracted_separately(cb_2025):
    assert len(cb_2025.tables) == 3
    assert any("Eligible Foreign Investors" in cell for t in cb_2025.tables for row in t.rows for cell in row)


def test_glued_footnote_marker_is_removed_and_recorded(md_2016):
    line = next(ln for ln in md_2016.lines if ln.text.startswith("38. Updation"))
    assert line.text == "38. Updation / Periodic Updation of KYC"
    assert line.footnote_refs == ["112"]


def test_withdrawn_stamp_is_counted_not_kept(md_2016):
    assert md_2016.dropped.get("withdrawn_stamp", 0) > 50
    assert not [ln for ln in md_2016.lines if ln.text == "Withdrawn"]
