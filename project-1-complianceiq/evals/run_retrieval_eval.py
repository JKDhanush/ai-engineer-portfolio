"""Retrieval evaluation + ablation (M2/M3).

Runs every answerable golden question through each retrieval mode and reports Hit@1/3/5, MRR, nDCG@10 and
latency, overall and per category. Writes evals/results/retrieval_report.md (the ablation table for the
README) and a JSON file with per-question results for error analysis.

Run from backend/ with the venv active and the database loaded (`make ingest`):
    python ../evals/run_retrieval_eval.py                         # all modes
    python ../evals/run_retrieval_eval.py --modes vector_rerank,hybrid_rerank --rerank-top 30

For rerank modes it also runs the out-of-scope questions and suggests a refusal threshold (MIN_RERANK_SCORE):
the top reranker score separates "the corpus has the answer" from "it doesn't".
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))

from app.config import get_settings  # noqa: E402
from app.retrieval import MODES, RERANK_MODES, RERANK_TOP, search  # noqa: E402

from metrics import hit_at_k, is_relevant, ndcg_at_k, percentile, reciprocal_rank  # noqa: E402

K = 10
LABELS = {"bm25": "BM25 (keyword only)", "vector": "Vector (bge-m3)", "hybrid": "Hybrid (RRF)",
          "hybrid_weighted": "Hybrid (weighted RRF)", "vector_rerank": "Vector + rerank",
          "hybrid_rerank": "Hybrid + rerank"}


def load_questions(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


async def evaluate(modes: list[str], limit: int | None, rerank_top: int = RERANK_TOP) -> dict:
    from ingest.embedder import embed, to_pgvector

    settings = get_settings()
    all_q = load_questions(HERE / "golden_set.jsonl")
    questions = [q for q in all_q if q["answerable"]][:limit]
    negatives = [q for q in all_q if not q["answerable"]]
    print(f"Embedding {len(questions)} questions (+{len(negatives)} out-of-scope)...")
    vecs = [to_pgvector(v) for v in embed([q["question"] for q in questions + negatives],
                                          device=settings.embed_device)]
    neg_vecs, vecs = vecs[len(questions):], vecs[:len(questions)]

    reranker = None
    if any(m in RERANK_MODES for m in modes):
        from app.rerank import rerank
        print("Loading reranker...")
        reranker = lambda q, ps: rerank(q, ps, settings.embed_device)  # noqa: E731
        reranker("warm up", ["warm up"])

    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    results: dict = {}
    try:
        for mode in modes:
            per_q, latencies = [], []
            for q, vec in zip(questions, vecs, strict=True):
                t0 = time.perf_counter()
                hits = await search(pool, q["question"], vec, mode=mode, k=K, entity=q["entity"],
                                    reranker=reranker, rerank_top=rerank_top)
                latencies.append((time.perf_counter() - t0) * 1000)
                flags = [is_relevant(h.doc_id, h.section_path, q["relevant"]) for h in hits]
                per_q.append({
                    "id": q["id"], "category": q["category"], "difficulty": q["difficulty"],
                    "hit1": hit_at_k(flags, 1), "hit3": hit_at_k(flags, 3), "hit5": hit_at_k(flags, 5),
                    "rr": reciprocal_rank(flags), "ndcg10": ndcg_at_k(flags, K),
                    "top3": [f"{h.doc_id} | {h.section_path}" for h in hits[:3]],
                    "top_score": hits[0].score if hits else None,
                })
            neg_scores = []
            if mode in RERANK_MODES:                     # refusal calibration on out-of-scope questions
                for q, vec in zip(negatives, neg_vecs, strict=True):
                    hits = await search(pool, q["question"], vec, mode=mode, k=1, reranker=reranker,
                                        rerank_top=rerank_top)
                    neg_scores.append(hits[0].score if hits else 0.0)
            results[mode] = {"questions": per_q, "latency_ms": latencies, "negative_top_scores": neg_scores}
            s = summarize(per_q, latencies)
            print(f"{LABELS[mode]:<24} Hit@1 {s['hit1']:.3f}  Hit@3 {s['hit3']:.3f}  Hit@5 {s['hit5']:.3f}  "
                  f"MRR {s['mrr']:.3f}  nDCG@10 {s['ndcg10']:.3f}  p50 {s['p50']:.0f} ms")
    finally:
        await pool.close()
    return results


def summarize(per_q: list[dict], latencies: list[float]) -> dict:
    mean = lambda key: statistics.mean(q[key] for q in per_q) if per_q else 0.0  # noqa: E731
    return {"n": len(per_q), "hit1": mean("hit1"), "hit3": mean("hit3"), "hit5": mean("hit5"), "mrr": mean("rr"),
            "ndcg10": mean("ndcg10"), "p50": percentile(latencies, 50), "p95": percentile(latencies, 95)}


def calibrate(r: dict) -> str:
    """Pick the top-score threshold that best separates answerable from out-of-scope questions."""
    pos = [q["top_score"] for q in r["questions"] if q["top_score"] is not None and q["hit5"]]
    neg = r["negative_top_scores"]
    if not pos or not neg:
        return "Not enough data."
    best_t, best_acc = 0.0, 0.0
    for t in sorted(set(pos + neg)):
        acc = (sum(p >= t for p in pos) + sum(n < t for n in neg)) / (len(pos) + len(neg))
        if acc > best_acc:
            best_t, best_acc = t, acc
    kept = sum(p >= best_t for p in pos) / len(pos)
    refused = sum(n < best_t for n in neg) / len(neg)
    return (f"Answerable top score p10/p50: {percentile(pos, 10):.3f} / {percentile(pos, 50):.3f} · "
            f"out-of-scope p50/p90: {percentile(neg, 50):.3f} / {percentile(neg, 90):.3f}\n\n"
            f"Suggested `MIN_RERANK_SCORE={best_t:.3f}`: keeps {kept:.0%} of answerable questions, refuses "
            f"{refused:.0%} of out-of-scope ones (only {len(neg)} negatives, so treat as a starting point).")


def write_report(results: dict) -> Path:
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Retrieval evaluation ({stamp})", "",
             f"{next(iter(results.values()))['questions'].__len__()} answerable golden questions, top-{K} results, "
             "relevant = the rule or its copy in any entity's directions / the 2016 Master Direction.", "",
             "## Ablation", "",
             "| Mode | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@10 | p50 ms | p95 ms |",
             "|---|---|---|---|---|---|---|---|"]
    summaries = {m: summarize(r["questions"], r["latency_ms"]) for m, r in results.items()}
    for m, s in summaries.items():
        lines.append(f"| {LABELS[m]} | {s['hit1']:.3f} | {s['hit3']:.3f} | {s['hit5']:.3f} | {s['mrr']:.3f} | "
                     f"{s['ndcg10']:.3f} | {s['p50']:.0f} | {s['p95']:.0f} |")
    best = max(summaries, key=lambda m: summaries[m]["mrr"])
    lines += ["", f"## By category ({LABELS[best]})", "", "| Category | n | Hit@5 | MRR |", "|---|---|---|---|"]
    cats = defaultdict(list)
    for q in results[best]["questions"]:
        cats[q["category"]].append(q)
    for c, qs in sorted(cats.items(), key=lambda kv: statistics.mean(q["rr"] for q in kv[1])):
        lines.append(f"| {c} | {len(qs)} | {statistics.mean(q['hit5'] for q in qs):.2f} | "
                     f"{statistics.mean(q['rr'] for q in qs):.2f} |")
    for m, r in results.items():
        if r.get("negative_top_scores"):
            lines += ["", f"## Refusal threshold ({LABELS[m]})", "", calibrate(r)]
    misses = [q for q in results[best]["questions"] if not q["hit5"]]
    lines += ["", f"## Misses at top-5 ({LABELS[best]}): {len(misses)}", ""]
    lines += [f"- `{q['id']}` ({q['category']}): got {q['top3'][:2]}" for q in misses[:40]]
    report = out_dir / "retrieval_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "retrieval_results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--limit", type=int, help="only the first N questions (quick check)")
    ap.add_argument("--rerank-top", type=int, default=RERANK_TOP, help="candidates the reranker re-scores")
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    results = asyncio.run(evaluate(modes, args.limit, args.rerank_top))
    print(f"\nReport: {write_report(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
