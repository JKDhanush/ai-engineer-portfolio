"""Download the RBI corpus listed in data/manifest.csv into data/raw/.

Run from backend/ with the venv active:
    python scripts/download_corpus.py

Design choices:
- The manifest (committed to git) is the source of truth. The PDFs themselves are
  not committed: anyone can rebuild the exact same corpus from the manifest.
- Idempotent: files that already exist are skipped, so it's safe to re-run.
- Polite: one request at a time with a short pause, and a browser-like User-Agent
  (some government sites reject the default Python one).
- Verified: each file must start with the PDF magic bytes "%PDF", so an HTML error
  page saved as .pdf is caught. A SHA-256 per file is logged to detect changes later.
"""

import csv
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]  # .../project-1-complianceiq
MANIFEST = PROJECT / "data" / "manifest.csv"
RAW = PROJECT / "data" / "raw"
LOG = RAW / "_download_log.csv"  # git-ignored along with the PDFs

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def download(url: str, dest: Path) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF"):
        raise ValueError(f"not a PDF (got {data[:40]!r})")
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.rename(dest)  # write to a temp name, then rename: never leaves a half-written .pdf behind
    return data


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    ok, skipped, failed = 0, 0, []
    log_rows = []
    for i, row in enumerate(rows, 1):
        dest = RAW / row["filename"]
        label = f"[{i:>2}/{len(rows)}] {row['doc_id']}"
        if dest.exists():
            data = dest.read_bytes()
            skipped += 1
            print(f"{label}: already there, skipping")
        else:
            try:
                data = download(row["pdf_url"], dest)
                ok += 1
                print(f"{label}: downloaded {len(data) / 1024:,.0f} KB")
                time.sleep(1.0)
            except Exception as exc:  # keep going; report all failures at the end
                failed.append((row["doc_id"], str(exc)))
                print(f"{label}: FAILED: {exc}")
                continue
        log_rows.append({"doc_id": row["doc_id"], "filename": row["filename"],
                         "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    with LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["doc_id", "filename", "bytes", "sha256"])
        w.writeheader()
        w.writerows(log_rows)

    print(f"\nDone: {ok} downloaded, {skipped} skipped, {len(failed)} failed -> {RAW}")
    for doc_id, err in failed:
        print(f"  FAILED {doc_id}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
