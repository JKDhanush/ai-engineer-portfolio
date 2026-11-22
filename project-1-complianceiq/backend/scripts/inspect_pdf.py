"""Look at real RBI PDFs before designing the parser.

Run from backend/ with the venv active:
    python scripts/inspect_pdf.py --all                        # one-line summary of every PDF in data/raw
    python scripts/inspect_pdf.py ../data/raw/<file>.pdf       # deep dive into one PDF
    python scripts/inspect_pdf.py ../data/raw/<file>.pdf --page 31   # also print one page's raw text

Each section of the deep dive answers one design question for the ingestion pipeline.
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"

# Patterns we expect in RBI documents
CIRCULAR_NO = re.compile(r"\b(RBI/[\w/.-]+\d{2}|(?:DOR|DBR|DPSS|CO\.DPSS|DNBR|DoR)[\w.()/ -]*?/\d{2}\.\d{2}\.\d{3}/\d{4}-\d{2})")
DATE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b")
TOC_LINE = re.compile(r"\.{8,}\s*\d*\s*$")              # "Chapter I – Preliminary ........ 4"
HEADING = re.compile(r"^(Chapter\s+[IVXLC]+\b|[A-H]\.\d?\s|[A-H]\.\s|Annex|Introduction)", re.IGNORECASE)
PARA_TOP = re.compile(r"^(\d{1,3})\.\s")                  # "27. The bank opting ..."
PARA_SUB = re.compile(r"^\((\d{1,2})\)\s")                # "(1) V-CIP Infrastructure"
PARA_ROMAN = re.compile(r"^\(([ivxl]{1,5})\)\s")          # "(ii) The bank shall ..."
PARA_ALPHA = re.compile(r"^\(([a-z])\)\s")                # "(a) ..."
BODY_MIN_SIZE = 10.5                                      # below this = footnotes / superscripts


def lines_of(page):
    """Yield (text, size, is_bold) for each visual line on a page."""
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            size = max(s["size"] for s in spans)
            bold = all(s["flags"] & 16 for s in spans)  # flag bit 16 = bold
            yield text, size, bold


def summary_row(path: Path) -> dict:
    doc = pymupdf.open(path)
    chars = sum(len(p.get_text()) for p in doc)
    tables = sum(len(p.find_tables().tables) for p in doc)
    return {
        "file": path.name, "pages": doc.page_count, "chars": chars,
        "chars/page": chars // max(doc.page_count, 1), "tables": tables,
        "scanned?": "YES" if chars // max(doc.page_count, 1) < 200 else "no",
    }


def print_all() -> None:
    rows = [summary_row(p) for p in sorted(RAW.glob("*.pdf"))]
    cols = ["file", "pages", "chars", "chars/page", "tables", "scanned?"]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))
    print(f"\n{len(rows)} PDFs, {sum(r['pages'] for r in rows)} pages, {sum(r['chars'] for r in rows):,} characters")


def deep_dive(path: Path, show_page: int | None) -> None:
    doc = pymupdf.open(path)
    all_lines = [(pno + 1, *ln) for pno, page in enumerate(doc) for ln in lines_of(page)]

    print(f"\n=== {path.name} ===  {doc.page_count} pages")

    print("\n[1] HEADER BLOCK (top of page 1): where do circular no., date and title live?")
    for text in doc[0].get_text().splitlines()[:12]:
        if text.strip():
            print("   |", text.rstrip()[:110])

    first_page_text = doc[0].get_text()
    print("\n[2] METADATA CANDIDATES found by regex on page 1")
    print("   circular numbers:", CIRCULAR_NO.findall(first_page_text)[:4] or "none")
    print("   dates:           ", [m.group(0) for m in DATE.finditer(first_page_text)][:4] or "none")

    print("\n[3] FONT SIZES (size, bold) by number of characters: what is body text vs footnotes?")
    sizes = Counter()
    for _, text, size, bold in all_lines:
        sizes[(round(size, 1), "bold" if bold else "regular")] += len(text)
    for (size, style), n in sizes.most_common(8):
        print(f"   {size:>5} {style:<8} {n:>8,} chars")

    print("\n[4] TABLE-OF-CONTENTS lines (dot leaders): noise to skip, but a free outline")
    toc = [(p, t) for p, t, *_ in all_lines if TOC_LINE.search(t)]
    toc_pages = sorted({p for p, _ in toc})
    print(f"   {len(toc)} TOC lines on pages {toc_pages}")

    print("\n[5] HEADINGS: bold lines matching Chapter / A. / F.1 / Annex (TOC pages excluded)")
    heads = [(p, t) for p, t, size, bold in all_lines
             if bold and p not in toc_pages and HEADING.match(t) and size >= BODY_MIN_SIZE]
    for p, t in heads[:25]:
        print(f"   p{p:<4} {t[:95]}")
    if len(heads) > 25:
        print(f"   ... {len(heads) - 25} more")

    print("\n[6] PARAGRAPH NUMBERING: the skeleton for section-level citations")
    body = [t for p, t, size, _ in all_lines if size >= BODY_MIN_SIZE and p not in toc_pages]
    tops = [int(m.group(1)) for t in body if (m := PARA_TOP.match(t))]
    print(f"   top-level '27.'  : {len(tops)} found, range {min(tops, default=0)}–{max(tops, default=0)}")
    print(f"   sub-level '(1)'  : {sum(bool(PARA_SUB.match(t)) for t in body)}")
    print(f"   roman '(ii)'     : {sum(bool(PARA_ROMAN.match(t)) for t in body)}")
    print(f"   alpha '(a)'      : {sum(bool(PARA_ALPHA.match(t)) for t in body)}")

    print("\n[7] FOOTNOTES (small font): often say WHEN and BY WHICH circular a para changed")
    notes = [(p, t) for p, t, size, _ in all_lines if size < BODY_MIN_SIZE and len(t) > 3]
    for p, t in notes[:10]:
        print(f"   p{p:<4} {t[:100]}")
    print(f"   total small-font lines: {len(notes)}")

    print("\n[8] REPEATED PAGE FURNITURE: first/last line of each page (digits shown as #)")
    furniture = Counter()
    for page in doc:
        ls = [x.strip() for x in page.get_text().splitlines() if x.strip()]
        if ls:
            furniture[re.sub(r"\d+", "#", ls[0])[:60]] += 1
            furniture[re.sub(r"\d+", "#", ls[-1])[:60]] += 1
    for text, n in furniture.most_common(4):
        print(f"   {n:>4}x  {text!r}")

    print("\n[9] TABLES")
    for pno, page in enumerate(doc):
        for t in page.find_tables().tables:
            rows = t.extract()
            print(f"   p{pno + 1}: {t.row_count} rows x {t.col_count} cols | first row: {[c for c in rows[0] if c][:4]}")

    if show_page:
        print(f"\n[10] RAW TEXT OF PAGE {show_page}")
        print(doc[show_page - 1].get_text())


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect RBI PDFs before designing the parser")
    ap.add_argument("pdf", nargs="?", type=Path, help="path to one PDF")
    ap.add_argument("--all", action="store_true", help="summary table of every PDF in data/raw")
    ap.add_argument("--page", type=int, help="also print the raw text of this page")
    args = ap.parse_args()
    if args.all:
        print_all()
    elif args.pdf:
        deep_dive(args.pdf, args.page)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
