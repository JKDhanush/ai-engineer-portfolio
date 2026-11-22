"""Ingest the RBI corpus: PDF -> lines -> tree -> chunks -> embeddings -> Postgres.

Run from backend/ with the venv active and the database up (`make up`):
    python scripts/ingest.py                    # all documents in data/manifest.csv (skips unchanged ones)
    python scripts/ingest.py --force            # re-ingest everything (e.g. after changing the chunker)
    python scripts/ingest.py --only cb-kyc-2025 # one document by doc_id

Idempotent: a document whose file fingerprint (SHA-256) is already in the database is skipped.
"""

import argparse
import asyncio
import csv
import hashlib
import re
import sys
import time
from datetime import date
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `ingest` and `app` importable

from app.config import get_settings  # noqa: E402
from ingest.chunker import build_chunks  # noqa: E402
from ingest.embedder import embed  # noqa: E402
from ingest.loader import document_exists, load_document  # noqa: E402
from ingest.metadata import extract_metadata  # noqa: E402
from ingest.pdf_reader import read_pdf  # noqa: E402
from ingest.structure import build_tree  # noqa: E402

PROJECT = Path(__file__).resolve().parents[2]
MANIFEST = PROJECT / "data" / "manifest.csv"
RAW = PROJECT / "data" / "raw"
REPEAL_DATE = date(2025, 11, 28)  # RBI repealed the 2016 KYC Master Direction (and its amendments) on this day


def short_title(title: str) -> str:
    return re.sub(r"\s*\(Updated as on [^)]*\)\s*$", "", title).strip()


def status_for(row: dict, issued: date, withdrawn_stamps: int) -> tuple[str, str]:
    """Simple version rule for now (the full version graph comes in M5)."""
    if withdrawn_stamps:
        return "superseded", "PDF carries RBI's 'Withdrawn' stamp"
    if row["entity_type"] == "all_REs" and issued < REPEAL_DATE:
        return "superseded", "2016 KYC Master Direction and its amendments were repealed on 28 Nov 2025"
    return "active", ""


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-ingest even if already loaded")
    ap.add_argument("--only", help="ingest a single doc_id from the manifest")
    args = ap.parse_args()

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    if args.only:
        rows = [r for r in rows if r["doc_id"] == args.only]
        if not rows:
            print(f"No doc_id '{args.only}' in the manifest")
            return 1

    conn = await asyncpg.connect(get_settings().database_url)
    total_chunks, t_start = 0, time.perf_counter()
    try:
        for i, row in enumerate(rows, 1):
            path = RAW / row["filename"]
            label = f"[{i:>2}/{len(rows)}] {row['doc_id']:<28}"
            if not path.exists():
                print(f"{label} MISSING {path.name} (run scripts/import_downloads.py)")
                continue
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if not args.force and await document_exists(conn, file_hash):
                print(f"{label} already loaded, skipping")
                continue

            t0 = time.perf_counter()
            raw = read_pdf(path)
            tree = build_tree(raw)
            extracted = extract_metadata(raw)
            issued = date.fromisoformat(row["issued_on"])
            circular = row["circular_no"].split(";")[0].strip()
            title = short_title(row["title"])
            prefix = f"{title} | {circular} | {issued.strftime('%d %b %Y')}"
            parents, children = build_chunks(raw, tree, prefix)
            t_parse = time.perf_counter() - t0

            t1 = time.perf_counter()
            vectors = embed([c.embedding_text for c in children]) if children else []
            t_embed = time.perf_counter() - t1

            status, reason = status_for(row, issued, raw.dropped.get("withdrawn_stamp", 0))
            n = await load_document(
                conn,
                content_hash=file_hash, source_file=row["filename"], doc_type=row["doc_type"],
                circular_no=circular, title=title, issued_on=issued, status=status,
                metadata={
                    "doc_id": row["doc_id"], "entity_type": row["entity_type"], "regulator": row["regulator"],
                    "circular_nos": [c.strip() for c in row["circular_no"].split(";")],
                    "source_page": row["source_page"], "pdf_url": row["pdf_url"], "status_reason": reason,
                    "extracted": {"circular_nos": extracted.circular_nos,
                                  "issued_on": extracted.issued_on.isoformat() if extracted.issued_on else None,
                                  "title": extracted.title},
                    "pages": raw.page_count, "footnotes": len(raw.footnotes), "tables": len(raw.tables),
                },
                parents=parents, children=children, child_embeddings=vectors,
            )
            total_chunks += n
            print(f"{label} {raw.page_count:>3} pages -> {len(parents):>3} parents, {len(children):>3} children "
                  f"| parse {t_parse:4.1f}s embed {t_embed:4.1f}s | {status}")

        counts = await conn.fetchrow(
            """SELECT (SELECT count(*) FROM documents) AS docs,
                      (SELECT count(*) FROM chunks WHERE chunk_level = 'parent') AS parents,
                      (SELECT count(*) FROM chunks WHERE chunk_level = 'child') AS children""")
        print(f"\nDone in {time.perf_counter() - t_start:.0f}s. Wrote {total_chunks} chunks this run. "
              f"Database now has {counts['docs']} documents, {counts['parents']} parents, "
              f"{counts['children']} children.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
