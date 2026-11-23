"""Build evals/golden_set.jsonl from golden_questions.py.

For each question target (a paragraph of the Commercial Banks directions), find the equivalent paragraph
in the other entity directions, the annex copies and the repealed 2016 Master Direction by text similarity,
so that retrieving the same rule from any of those documents counts as a correct hit.

Run from backend/ with the venv active:   python ../evals/build_golden.py
"""

import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest.chunker import _render  # noqa: E402
from ingest.pdf_reader import read_pdf  # noqa: E402
from ingest.structure import build_tree  # noqa: E402

from golden_questions import Q  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = Path(__file__).resolve().parent / "golden_set.jsonl"
BASE = "cb-kyc-2025"
ENTITY_DOCS = {"nbfc": "nbfc-kyc-2025", "sfb": "sfb-kyc-2025", "ucb": "ucb-kyc-2025"}
ENTITY_FILTER = {"nbfc": "nbfcs", "sfb": "small_finance_banks", "ucb": "urban_coop_banks"}
EQUIV_DOCS = ["nbfc-kyc-2025", "sfb-kyc-2025", "ucb-kyc-2025", "md-kyc-2016"]
ANNEX_DOCS = [f"{e}-kyc-2025-annex{i}" for e in ("cb", "nbfc", "sfb", "ucb") for i in (1, 2)]
MIN_SIMILARITY = 0.35


def para_key(citation: str) -> str | None:
    """'Chapter VI > E. ... > Para 42(1)' -> '42';  'Annex I > Para 5' -> 'Annex I|5'."""
    m = re.search(r"Para (\w+)", citation)
    if not m:
        return None
    first = citation.split(" > ")[0]
    return f"{first}|{m.group(1)}" if first.startswith("Annex") else m.group(1)


def doc_paragraphs(path: Path) -> dict[str, str]:
    tree = build_tree(read_pdf(path))
    paras: dict[str, str] = {}
    for n in tree.walk():
        if n.kind == "para":
            key = para_key(n.citation())
            if key and key not in paras:
                paras[key] = _render(n)
    return paras


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]{3,}", text.lower())


class Tfidf:
    def __init__(self, docs: list[str]):
        df = Counter(t for d in docs for t in set(tokens(d)))
        self.idf = {t: math.log(len(docs) / c) + 1 for t, c in df.items()}

    def vec(self, text: str) -> dict[str, float]:
        tf = Counter(tokens(text))
        v = {t: c * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    @staticmethod
    def cos(a: dict, b: dict) -> float:
        return sum(x * b.get(t, 0.0) for t, x in a.items())


def main() -> None:
    manifest = {r["doc_id"]: r["filename"] for r in csv.DictReader((ROOT / "data" / "manifest.csv").open())}
    corpus = {d: doc_paragraphs(RAW / manifest[d]) for d in [BASE, *EQUIV_DOCS, *ANNEX_DOCS] if d in manifest}
    tfidf = Tfidf([t for paras in corpus.values() for t in paras.values()])
    vecs = {d: {k: tfidf.vec(t) for k, t in paras.items()} for d, paras in corpus.items()}

    def best_match(doc: str, target_vec: dict, base_key: str) -> tuple[str, float] | None:
        """Best paragraph in `doc` for the target. Annex paragraphs only match the same annex (Annex I = UAPA
        order, Annex II = WMD order), except in the 2016 Master Direction, which numbers its annexes differently."""
        prefix = base_key.split("|")[0] if "|" in base_key else None

        def allowed(k: str) -> bool:
            if prefix is None:
                return not k.startswith("Annex")
            return k.startswith("Annex") if doc == "md-kyc-2016" else k.split("|")[0] == prefix

        cands = [(k, Tfidf.cos(target_vec, v)) for k, v in vecs[doc].items() if allowed(k)]
        if not cands:
            return None
        k, s = max(cands, key=lambda x: x[1])
        return (k, s) if s >= MIN_SIMILARITY else None

    rows, problems = [], []
    for qid, question, category, difficulty, targets, expected in Q:
        relevant: list[dict] = []
        entity = None
        for t in targets:
            if t.startswith("doc:"):
                relevant.append({"doc_id": t[4:], "key": "*"})
                continue
            if ":" in t:                                  # "nbfc:*42" -> NBFC's equivalent of CB para 42 only
                ent, base_key = t.split(":")
                entity, base_key = ent, base_key.lstrip("*")
                docs = [ENTITY_DOCS[ent]]
            else:
                base_key, docs = t, None
            annex = base_key.startswith("Annex")
            if base_key not in corpus[BASE]:
                problems.append(f"{qid}: CB has no paragraph {base_key}")
                continue
            target_vec = vecs[BASE][base_key]
            if docs is None:
                relevant.append({"doc_id": BASE, "key": base_key})
                docs = [d for d in (ANNEX_DOCS + EQUIV_DOCS if annex else EQUIV_DOCS) if d in corpus]
                if annex:
                    docs += [d for d in EQUIV_DOCS[:3]]   # main directions also contain the annex text
            for d in docs:
                if (m := best_match(d, target_vec, base_key)) is not None:
                    relevant.append({"doc_id": d, "key": m[0], "similarity": round(m[1], 2)})
        uniq = {(r["doc_id"], r["key"]): r for r in relevant}
        rows.append({
            "id": qid, "question": question, "category": category, "difficulty": difficulty,
            "entity": ENTITY_FILTER.get(entity) if entity else None,
            "answerable": bool(targets), "expected_answer": expected, "relevant": list(uniq.values()),
        })

    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    answerable = sum(r["answerable"] for r in rows)
    print(f"Wrote {len(rows)} questions ({answerable} answerable, {len(rows) - answerable} unanswerable) -> {OUT.name}")
    print(f"Average relevant paragraphs per answerable question: "
          f"{sum(len(r['relevant']) for r in rows if r['answerable']) / max(answerable, 1):.1f}")
    for p in problems:
        print("PROBLEM:", p)


if __name__ == "__main__":
    main()
