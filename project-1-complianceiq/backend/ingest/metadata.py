"""Stage 2: read circular numbers, issue date and title from a document's header block.

What RBI header blocks look like (after pdf_reader has removed the masthead):

  Master Direction (2016)                 New directions (2025)
  ---------------------------             ----------------------------------------------
  RBI/DBR/2015-16/18             (bold)   RBI/DOR/2025-26/169
  Master Direction DBR.AML...    (bold)   DOR.AML.REC.No.88/14.01.002/2025-26   November 28, 2025
  February 25, 2016              (bold)   Reserve Bank of India (Commercial Banks – ... (bold)
  (Updated as on August 14, 2025)(bold)   2025 (Updated as on October 1, 2026)          (bold)
  ...more (Updated as on ...)    (bold)   Introduction        <- next page
  Master Direction - KYC ..., 2016 (bold)

  Circular letter (amendments etc.)
  ---------------------------------
  RBI/2025-26/53
  DOR.AML.REC.31/14.01.001/2025-26
  June 12, 2025
  The Chairpersons/ CEOs of all the Regulated Entities      (not bold)
  Dear Sir/ Madam,                                          (not bold)
  Updation/ Periodic Updation of KYC – Revised Instructions (bold)  <- title
  Please refer to instructions on ...                       (not bold)

Rules (each one is covered by a test in tests/test_metadata.py):
  1. The ISSUE DATE is the first "Month D, YYYY" date in the first `max_lines` lines,
     ignoring lines that start with "(Updated as on". Call that line the DATE LINE.
     If there is no date line, it isn't an RBI header: return DocMetadata([], None, None).
  2. CIRCULAR NUMBERS are all CIRCULAR_NO matches in lines up to AND including the date line,
     in order of appearance, without duplicates. (Circular numbers *after* the date line are
     references to other circulars in the body, not this document's own numbers.)
     If none are found, return DocMetadata([], None, None).
  3. The TITLE is the first run of consecutive BOLD lines after the date line:
       - skip "(Updated as on ...)" lines entirely (bold or not);
       - skip non-bold lines until the first bold line ("Dear Sir/Madam," etc.);
       - then keep taking bold lines while they're on the SAME PAGE as the first title line;
       - stop at the first non-bold line (or page change);
       - join them with single spaces and strip a trailing "(Updated as on ...)".
     If no bold line is found, title is None.
"""

import re
from datetime import date, datetime

from .models import DocMetadata, RawDocument

CIRCULAR_NO = re.compile(
    r"\bRBI/[A-Z]*/?\d{4}-\d{2,4}/\d+"                                    # RBI/2025-26/53, RBI/DOR/2025-26/169
    r"|\b(?:DOR|DBR|DBOD|DNBR|DoR|CO\.DPSS)[A-Za-z.()]*\.(?:No\.\s?)?"    # DOR.AML.REC.No.  CO.DPSS.POLC.No.
    r"[A-Z]?-?\d+/[\d.-]+/\d{4}-\d{2}"            # 88/14.01.002/2025-26, S-955/02-30-010/2025-26
)
DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),\s+(\d{4})\b"
)
UPDATED = re.compile(r"^\(Updated as on", re.IGNORECASE)
TRAILING_UPDATED = re.compile(r"\s*\(Updated as on [^)]*\)\s*$", re.IGNORECASE)


def parse_date(text: str) -> date | None:
    """Return the first 'Month D, YYYY' date in `text` as a datetime.date, else None.

    parse_date("DOR.AML.REC.No.88/14.01.002/2025-26   November 28, 2025") -> date(2025, 11, 28)
    parse_date("no date here") -> None
    """
    m = DATE.search(text)  # .search finds the pattern ANYWHERE in the string (.match = only at the start)
    if m is None:
        return None
    month, day, year = m.groups()  # the three (...) capture groups in DATE: "November", "28", "2025"
    # strptime = "string parse time": %B = full month name, %d = day, %Y = 4-digit year
    return datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()


def extract_metadata(doc: RawDocument, max_lines: int = 25) -> DocMetadata:
    """Apply rules 1-3 from the module docstring to the first `max_lines` lines of `doc`."""
    empty = DocMetadata(circular_nos=[], issued_on=None, title=None)
    header = doc.lines[:max_lines]  # slicing never fails, even if the document has fewer lines

    # Rule 1: the first real date (not an "(Updated as on ...)" line) marks the date line
    issued_on, date_idx = None, None
    for i, line in enumerate(header):  # enumerate gives (index, item), we need the index later
        if UPDATED.match(line.text):
            continue
        found = parse_date(line.text)
        if found:
            issued_on, date_idx = found, i
            break  # first one wins
    if date_idx is None:
        return empty

    # Rule 2: circular numbers only from lines up to and including the date line
    circular_nos: list[str] = []
    for line in header[: date_idx + 1]:
        for m in CIRCULAR_NO.finditer(line.text):  # finditer: ALL matches in the line, in order
            if m.group(0) not in circular_nos:  # keep order, skip duplicates
                circular_nos.append(m.group(0))
    if not circular_nos:
        return empty  # a date but no RBI number above it, e.g. the MHA annex: not an RBI header

    # Rule 3: title = first run of bold lines after the date line, on one page
    parts: list[str] = []
    title_page = None
    for line in header[date_idx + 1 :]:
        if UPDATED.match(line.text):
            continue  # "(Updated as on ...)" is never part of the title
        if line.bold and (title_page is None or line.page == title_page):
            parts.append(line.text)
            title_page = line.page  # lock the title to the page of its first line
        elif parts:
            break  # a non-bold line (or a new page) AFTER the title started: title is complete
        # else: non-bold line BEFORE the title (e.g. "Dear Sir/ Madam,"): keep looking
    title = TRAILING_UPDATED.sub("", " ".join(parts)).strip() if parts else None

    return DocMetadata(circular_nos=circular_nos, issued_on=issued_on, title=title)
