"""Retrieval: keyword search, vector search, Reciprocal Rank Fusion, optional cross-encoder reranking.

Modes (compared in the ablation table, evals/run_retrieval_eval.py):
  "bm25"            keyword search only (Postgres full-text; ts_rank_cd, BM25-like)
  "vector"          semantic search only (pgvector HNSW, cosine)
  "hybrid"          both, merged with equal-weight RRF
  "hybrid_weighted" both, RRF with keyword results down-weighted (BM25_WEIGHT)
  "vector_rerank"   vector candidates re-scored by a cross-encoder (bge-reranker-v2-m3)
  "hybrid_rerank"   hybrid candidates re-scored by the cross-encoder

First ablation on the RTX 3050 (165 questions): vector beat equal-weight hybrid (MRR 0.873 vs 0.761): keyword
search is weak here because questions are phrased differently from regulations, and equal-weight RRF lets weak
keyword hits push good vector hits down. The reranker recovered it (MRR 0.908). Hence the weighted variants.

Why both searches: vector search finds MEANING ("periodic updation" ~ "update KYC every 2 years"); keyword
search finds EXACT terms (circular numbers, "V-CIP", "Section 51A") that embeddings blur.
RRF merges ranked lists without comparing their incompatible scores:
    score(chunk) = sum over lists of 1 / (k + rank)        (k = 60, the standard constant)
A cross-encoder reads the question and a passage TOGETHER, so it judges relevance far better than
comparing two separately computed vectors, but it's too slow to run over the whole corpus. So it only
re-orders the ~30 best hybrid candidates.
"""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import asyncpg

RRF_K = 60
CANDIDATES = 40       # children each search returns before fusion
RERANK_TOP = 20       # fused candidates the cross-encoder re-scores (latency grows linearly with this)
BM25_WEIGHT = 0.3     # keyword list weight in "hybrid_weighted" (vector list = 1.0)
NEAR_DUP = 0.85       # word-shingle Jaccard above which two paragraphs count as the same rule

_ENTITY_FILTER = "($2::text IS NULL OR d.metadata->>'entity_type' IN ($2, 'all_REs', 'payment_systems'))"
_STATUS_FILTER = "($4::bool OR d.status = 'active')"
_ACL_FILTER = "($5::text[] IS NULL OR d.access_level = ANY($5::text[]))"   # document access control (M7)

VECTOR_SQL = f"""
SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE c.chunk_level = 'child' AND {_ENTITY_FILTER} AND {_STATUS_FILTER} AND {_ACL_FILTER}
ORDER BY c.embedding <=> $1::vector
LIMIT $3"""

# OR-of-terms full-text query: plainto_tsquery ANDs every word, which is too strict for questions.
KEYWORD_SQL = f"""
WITH q AS (SELECT NULLIF(replace(plainto_tsquery('english', $1)::text, '&', '|'), '') AS t)
SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id, q
WHERE q.t IS NOT NULL AND c.chunk_level = 'child' AND c.tsv @@ to_tsquery('english', q.t)
  AND {_ENTITY_FILTER} AND {_STATUS_FILTER} AND {_ACL_FILTER}
ORDER BY ts_rank_cd(c.tsv, to_tsquery('english', q.t)) DESC
LIMIT $3"""

DETAILS_SQL = """
SELECT c.id AS child_id, c.content AS child_text, c.context_header AS child_header, c.content_hash,
       p.id AS parent_id, p.content AS parent_text, p.section_path, p.page_start, p.page_end,
       d.title, d.circular_no, d.issued_on, d.status, d.source_file,
       d.metadata->>'doc_id' AS doc_id, d.metadata->>'entity_type' AS entity_type,
       d.metadata->>'status_reason' AS status_reason, d.metadata->>'pdf_url' AS pdf_url
FROM chunks c JOIN chunks p ON p.id = c.parent_id JOIN documents d ON d.id = c.document_id
WHERE c.id = ANY($1::uuid[])"""

MODES = ("bm25", "vector", "hybrid", "hybrid_weighted", "vector_rerank", "hybrid_rerank")
RERANK_MODES = ("vector_rerank", "hybrid_rerank")


@dataclass
class Hit:
    parent_id: str
    score: float
    doc_id: str
    title: str
    circular_no: str | None
    issued_on: str | None
    status: str
    status_reason: str | None
    entity_type: str | None
    section_path: str
    pages: str
    pdf_url: str | None
    parent_text: str
    matched_text: str
    also_in: list[str] = field(default_factory=list)


def rrf(*ranked_lists: list, weights: list[float] | None = None) -> dict:
    weights = weights or [1.0] * len(ranked_lists)
    scores: dict = {}
    for ranked, w in zip(ranked_lists, weights, strict=True):
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + w / (RRF_K + rank)
    return scores


def _shingles(text: str, n: int = 5) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    # Entity names differ between otherwise identical rules ("the bank" vs "the NBFC"): drop them.
    words = [w for w in words if w not in {"bank", "banks", "nbfc", "nbfcs", "sfb", "ucb", "re", "res"}]
    return {" ".join(words[i:i + n]) for i in range(max(len(words) - n + 1, 1))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


async def search(
    pool: asyncpg.Pool, query: str, query_vec: str | None, *, mode: str = "hybrid", k: int = 5,
    entity: str | None = None, include_superseded: bool = True,
    reranker: Callable[[str, list[str]], list[float]] | None = None, rerank_top: int = RERANK_TOP,
    access_levels: list[str] | None = None, prefer_active: bool = True,
) -> list[Hit]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    use_vector = mode != "bm25"
    use_keyword = mode in ("bm25", "hybrid", "hybrid_weighted", "hybrid_rerank")
    async with pool.acquire() as conn:
        lists, weights = [], []
        if use_vector:
            lists.append([r["id"] for r in await conn.fetch(VECTOR_SQL, query_vec, entity, CANDIDATES,
                                                            include_superseded, access_levels)])
            weights.append(1.0)
        if use_keyword:
            lists.append([r["id"] for r in await conn.fetch(KEYWORD_SQL, query, entity, CANDIDATES,
                                                            include_superseded, access_levels)])
            weights.append(BM25_WEIGHT if mode == "hybrid_weighted" else 1.0)
        fused = rrf(*lists, weights=weights)
        ranked = sorted(fused, key=fused.get, reverse=True)
        rows = {r["child_id"]: r for r in await conn.fetch(DETAILS_SQL, ranked)}

    ranked = [cid for cid in ranked if cid in rows]
    scores = dict(fused)
    if mode in RERANK_MODES and reranker is not None and ranked:
        top = ranked[:rerank_top]
        passages = [f"{rows[c]['child_header']}\n{rows[c]['child_text']}" for c in top]
        rerank_scores = await asyncio.to_thread(reranker, query, passages)  # GPU work off the event loop
        scores = {c: s for c, s in zip(top, rerank_scores, strict=True)}
        ranked = sorted(top, key=scores.get, reverse=True)
    return _group(ranked, rows, scores, k, prefer_active)


def _hit(r, score: float) -> Hit:
    pages = f"{r['page_start']}" if r["page_start"] == r["page_end"] else f"{r['page_start']}-{r['page_end']}"
    return Hit(parent_id=str(r["parent_id"]), score=float(score), doc_id=r["doc_id"], title=r["title"],
               circular_no=r["circular_no"], issued_on=r["issued_on"].isoformat() if r["issued_on"] else None,
               status=r["status"], status_reason=r["status_reason"], entity_type=r["entity_type"],
               section_path=r["section_path"], pages=pages, pdf_url=r["pdf_url"], parent_text=r["parent_text"],
               matched_text=r["child_text"])


def _group(ranked: list, rows: dict, scores: dict, k: int, prefer_active: bool = True) -> list[Hit]:
    """Children best-first -> distinct parents. The same rule repeated in several documents is kept once, with
    the other copies listed in `also_in`, so the LLM sees k DIFFERENT rules. With `prefer_active`, an active copy
    replaces a superseded one (the 2016 Master Direction's wording loses to the 2025 Directions' wording)."""
    hits: list[Hit] = []
    seen_parents: set = set()
    shingles: list[set] = []
    for cid in ranked:
        r = rows[cid]
        if r["parent_id"] in seen_parents:              # another child of a paragraph we already have
            continue
        seen_parents.add(r["parent_id"])
        sh = _shingles(r["parent_text"])
        idx = next((i for i, s in enumerate(shingles) if _jaccard(sh, s) >= NEAR_DUP), None)
        if idx is not None:
            dup = hits[idx]
            if prefer_active and dup.status != "active" and r["status"] == "active":
                new = _hit(r, dup.score)
                new.also_in = [t for t in [dup.title, *dup.also_in] if t != new.title]
                hits[idx], shingles[idx] = new, sh
            elif r["title"] != dup.title and r["title"] not in dup.also_in:
                dup.also_in.append(r["title"])
            continue
        if len(hits) >= k:
            continue
        hits.append(_hit(r, scores[cid]))
        shingles.append(sh)
    if prefer_active:      # current rules first; superseded ones stay for context (stable sort keeps score order)
        hits.sort(key=lambda h: h.status != "active")
    return hits
