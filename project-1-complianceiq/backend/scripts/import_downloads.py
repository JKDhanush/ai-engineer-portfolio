"""Get the RBI corpus through your real browser, then file it into data/raw/.

RBI's document server sits behind a bot-protection layer (F5 "TSPD" JavaScript
challenge). Scripts like curl/urllib receive the challenge page, not the PDF.
We respect that rather than trying to defeat it: your browser passes the check
normally, and this script does the tedious parts around it.

Step 1, open every PDF link from the manifest in your browser (one tab each):
    python scripts/import_downloads.py --open
    (Set your browser to *save* PDFs instead of previewing them, see the README note.)

Step 2, find them in ~/Downloads, check them, and copy them in with clean names:
    python scripts/import_downloads.py
"""

import argparse
import csv
import hashlib
import re
import shutil
import sys
import time
import webbrowser
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]  # .../project-1-complianceiq
MANIFEST = PROJECT / "data" / "manifest.csv"
RAW = PROJECT / "data" / "raw"
LOG = RAW / "_download_log.csv"
DOWNLOADS = Path.home() / "Downloads"


def load_manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def open_all(rows: list[dict], delay: float) -> None:
    for i, row in enumerate(rows, 1):
        print(f"[{i:>2}/{len(rows)}] opening {row['doc_id']}")
        webbrowser.open_new_tab(row["pdf_url"])
        time.sleep(delay)  # human pace: kind to the server, and the browser keeps up
    print(f"\nOpened {len(rows)} tabs. Once they've all downloaded, run without --open.")


def find_download(url: str) -> Path | None:
    """Match the URL's file name in ~/Downloads, case-insensitively.
    Browsers may add ' (1)' or '(1)' for duplicates, so allow that too."""
    stem, _, ext = url.rsplit("/", 1)[-1].rpartition(".")
    pattern = re.compile(rf"^{re.escape(stem)}(\s?\(\d+\))?\.{re.escape(ext)}$", re.IGNORECASE)
    matches = [p for p in DOWNLOADS.iterdir() if p.is_file() and pattern.match(p.name)]
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None  # newest copy


def import_all(rows: list[dict]) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    imported, already, missing, bad = 0, 0, [], []
    log_rows = []
    for row in rows:
        dest = RAW / row["filename"]
        if dest.exists():
            already += 1
        else:
            src = find_download(row["pdf_url"])
            if src is None:
                missing.append(row["doc_id"])
                continue
            if not src.read_bytes()[:4] == b"%PDF":
                bad.append(f"{row['doc_id']} ({src.name} is not a real PDF)")
                continue
            shutil.copy2(src, dest)  # copy, not move: your Downloads stay untouched
            imported += 1
            print(f"  {src.name:<45} -> {dest.name}")
        data = dest.read_bytes()
        log_rows.append({"doc_id": row["doc_id"], "filename": row["filename"],
                         "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    with LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "filename", "bytes", "sha256"])
        w.writeheader()
        w.writerows(log_rows)

    print(f"\nImported {imported}, already present {already}, missing {len(missing)}, invalid {len(bad)}")
    print(f"Corpus: {len(log_rows)}/{len(rows)} files in {RAW}")
    for d in missing:
        print(f"  MISSING {d}")
    for b in bad:
        print(f"  INVALID {b}")
    return 0 if len(log_rows) == len(rows) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--open", action="store_true", help="open every manifest PDF link in the browser")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between tabs (default 3)")
    args = ap.parse_args()
    rows = load_manifest()
    if args.open:
        open_all(rows, args.delay)
        return 0
    return import_all(rows)


if __name__ == "__main__":
    sys.exit(main())
