"""Stage 1: read an RBI PDF into clean body lines, footnotes and tables (ADR-006).

Why line/span level and not page.get_text():
- headings are only recognisable by BOLD (same font size as body text);
- footnote markers are tiny spans glued into words ("112Updation" = marker 112 + "Updation");
- footnotes themselves are small-font lines at the bottom of the page.
Plain text extraction throws all of that information away.
"""

import re
from collections import Counter
from pathlib import Path

import pymupdf

from .models import Footnote, Line, RawDocument, Table

BODY_MIN_SIZE = 10.5     # body text is 11-12 pt; footnotes 8-9 pt; superscript markers 5-8 pt
MARKER = re.compile(r"^\d{1,3}[A-Z]?$")                  # footnote markers: "1", "112", "34"
TOC_LINE = re.compile(r"\.{6,}\s*\d*\s*$")               # "Chapter I – Preliminary ........ 4"
TOC_TITLE = re.compile(r"^(table of contents|contents)$", re.IGNORECASE)
PAGE_NUMBER = re.compile(r"^\d{1,3}$")
NON_LATIN_MASTHEAD = re.compile(r"[ऀ-ॿ]|[įǐ]")  # Hindi masthead (often mis-encoded)
BOILERPLATE = (
    re.compile(r"^RESERVE BANK OF INDIA$", re.IGNORECASE),
    re.compile(r"^www\.rbi\.org\.in$", re.IGNORECASE),
    re.compile(r'^"?Caution: RBI never sends mails'),
    re.compile(r"^Please do not respond in any manner to such offers"),
)
WITHDRAWN = re.compile(r"^Withdrawn$", re.IGNORECASE)    # stamp RBI puts on repealed circulars


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16)  # PyMuPDF flag bit 4 (value 16) = bold


def _inside(bbox, rect) -> bool:
    """True if a line's bbox centre lies inside a table rectangle."""
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1


def _clean_cell(cell: str | None) -> str:
    return re.sub(r"\s+", " ", cell or "").strip(" .,")


def read_pdf(path: str | Path) -> RawDocument:
    doc = pymupdf.open(path)
    lines: list[Line] = []
    footnotes: list[Footnote] = []
    tables: list[Table] = []
    dropped: Counter = Counter()

    for pno, page in enumerate(doc, start=1):
        # --- tables first, so their text isn't also read as body lines ---
        table_rects = []
        for t in page.find_tables().tables:
            rows = [[_clean_cell(c) for c in row] for row in t.extract()]
            rows = [r for r in rows if any(r)]
            if rows:
                tables.append(Table(page=pno, rows=rows))
                table_rects.append(pymupdf.Rect(t.bbox))

        page_lines: list[Line] = []
        for block in page.get_text("dict")["blocks"]:
            for raw in block.get("lines", []):
                spans = [s for s in raw["spans"] if s["text"].strip()]
                if not spans:
                    continue
                if any(_inside(raw["bbox"], r) for r in table_rects):
                    dropped["table_text"] += 1
                    continue

                body = [s for s in spans if s["size"] >= BODY_MIN_SIZE]
                small = [s for s in spans if s["size"] < BODY_MIN_SIZE]

                if not body:
                    # whole line is small font -> footnote text (or a footnote's continuation)
                    text = "".join(s["text"] for s in raw["spans"]).strip()
                    if any(p.search(text) for p in BOILERPLATE):
                        dropped["boilerplate"] += 1
                        continue
                    first = small[0]["text"].strip()
                    if MARKER.match(first) and len(small) > 1:
                        rest = " ".join(s["text"] for s in small[1:])  # spans may lack spaces
                        footnotes.append(Footnote(page=pno, marker=first, text=rest))
                    elif footnotes and footnotes[-1].page == pno:
                        footnotes[-1].text = f"{footnotes[-1].text} {text}".strip()
                    elif m := re.match(r"^(\d{1,3})\s+(.+)$", text):
                        footnotes.append(Footnote(page=pno, marker=m.group(1), text=m.group(2)))
                    else:
                        dropped["small_text"] += 1
                    continue

                # body line: drop tiny superscript markers but remember them
                refs = [s["text"].strip() for s in small if MARKER.match(s["text"].strip())]
                text = "".join(s["text"] for s in raw["spans"] if s["size"] >= BODY_MIN_SIZE)
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    continue
                page_lines.append(Line(
                    page=pno, text=text,
                    size=round(max(s["size"] for s in body), 1),
                    bold=all(_is_bold(s) for s in body),
                    x0=round(raw["bbox"][0], 1), y0=round(raw["bbox"][1], 1),
                    footnote_refs=refs,
                ))

        page_lines = _drop_page_noise(page_lines, dropped)
        lines.extend(page_lines)

    for f in footnotes:
        f.text = re.sub(r"\s+", " ", f.text).strip()
    return RawDocument(path=str(path), page_count=doc.page_count, lines=lines,
                       footnotes=footnotes, tables=tables, dropped=dict(dropped))


def _drop_page_noise(page_lines: list[Line], dropped: Counter) -> list[Line]:
    """Remove page numbers, the masthead, boilerplate, and table-of-contents lines."""
    kept = []
    for ln in page_lines:
        # 1) page numbers: a line that is only a number (wherever extraction order puts it)
        if PAGE_NUMBER.match(ln.text):
            dropped["page_number"] += 1
        # 2) masthead, address footer and boilerplate
        elif NON_LATIN_MASTHEAD.search(ln.text) or any(p.search(ln.text) for p in BOILERPLATE):
            dropped["masthead"] += 1
        # 3) "Withdrawn" stamp: drop from the text, but count it. It's a version-graph signal.
        elif WITHDRAWN.match(ln.text):
            dropped["withdrawn_stamp"] += 1
        else:
            kept.append(ln)
    page_lines = kept

    # 4) table of contents: on a page with several dot-leader lines, drop everything from the
    #    "Contents" title (or first dot-leader line) through the LAST dot-leader line.
    #    This also catches TOC entries that wrap onto a second line without dots.
    toc_idx = [i for i, ln in enumerate(page_lines) if TOC_LINE.search(ln.text)]
    if len(toc_idx) >= 3:
        start = next((i for i, ln in enumerate(page_lines) if TOC_TITLE.match(ln.text)), toc_idx[0])
        start = min(start, toc_idx[0])
        end = toc_idx[-1]
        dropped["toc"] += end - start + 1
        page_lines = page_lines[:start] + page_lines[end + 1:]
    # stray single TOC lines on other pages
    before = len(page_lines)
    page_lines = [ln for ln in page_lines if not TOC_LINE.search(ln.text)]
    dropped["toc"] += before - len(page_lines)

    return page_lines
