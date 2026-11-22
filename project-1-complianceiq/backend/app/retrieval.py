"""Hybrid retrieval: vector search + keyword search, merged with Reciprocal Rank Fusion (RRF).

Why both:
- vector search finds MEANING ("periodic updation" ~ "update KYC every 2 years"),
- keyword search finds EXACT terms (circular numbers, "V-CIP", "Section 51A") that embeddings blur.
RRF merges the two ranked lists without having to compare their incompatible scores:
    score(chunk) = sum over lists of 1 / (k + rank)      (k = 60, the standard constant)
"""

from dataclasses import dataclass

import asyncpg

RRF_K = 60
CANDIDATES = 40  # how many children each search returns before fusion

# Optional entity filter: documents for that entity, plus documents that apply to all regulated entities.
_ENTITY_FILTER = "($2::text IS NULL OR d.metadata->>'entity_type' IN ($2, 'all_REs', 'payment_systems'))"
_STATUS_FILTER = "($4::bool OR d.status = 'active')"

VECTOR_SQL = f"""
SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE c.chunk_level = 'child' AND {_ENTITY_FILTER} AND {_STATUS_FILTER}
ORDER BY c.embedding <=> $1::vector
LIMIT $3"""

# OR-of-terms full-text query: plainto_tsquery ANDs every word, which is too strict for questions.
KEYWORD_SQL = f"""
WITH q AS (SELECT NULLIF(replace(plainto_tsquery('english', $1)::text, '&', '|'), '') AS t)
SELECT c.id FROM chunks c JOIN documents d ON d.id = c.document_id, q
WHERE q.t IS NOT NULL AND c.chunk_level = 'child' AND c.tsv @@ to_tsquery('english', q.t)
  AND {_ENTITY_FILTER} AND {_STATUS_FILTER}
ORDER BY ts_rank_cd(c.tsv, to_tsquery('english', q.t)) DESC
LIMIT $3"""

DETAILS_SQL = """
SELECT c.id AS child_id, c.content AS child_text, c.content_hash, c.section_path AS child_path,
       p.id AS parent_id, p.content AS parent_text, p.section_path, p.page_start, p.page_end,
       d.title, d.circular_no, d.issued_on, d.status, d.source_file,
       d.metadata->>'entity_type' AS entity_type, d.metadata->>'status_reason' AS status_reason
FROM chunks c JOIN chunks p ON p.id = c.parent_id JOIN documents d ON d.id = c.document_id
WHERE c.id = ANY($1::uuid[])"""


@dataclass
class Hit:
    parent_id: str
    score: float
    title: str
    circular_no: str | None
    issued_on: str | None
    status: str
    status_reason: str | None
    entity_type: str | None
    section_path: str
    pages: str
    parent_text: str
    matched_text: str
    also_in: list[str]


def rrf(*ranked_lists: list) -> dict:
    scores: dict = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (RRF_K + rank)
    return scores


async def hybrid_search(pool: asyncpg.Pool, query: str, query_vec: str, *, k: int = 5,
                        entity: str | None = None, include_superseded: bool = True) -> list[Hit]:
    async with pool.acquire() as conn:
        vec_ids = [r["id"] for r in await conn.fetch(VECTOR_SQL, query_vec, entity, CANDIDATES, include_superseded)]
        kw_ids = [r["id"] for r in await conn.fetch(KEYWORD_SQL, query, entity, CANDIDATES, include_superseded)]
        fused = rrf(vec_ids, kw_ids)
        ranked = sorted(fused, key=fused.get, reverse=True)
        rows = {r["child_id"]: r for r in await conn.fetch(DETAILS_SQL, ranked)}

    # Walk children best-first. Identical text in several entity directions -> keep the best one and
    # note where else it appears. Several children of one paragraph -> one parent.
    hits: dict = {}
    seen_text: dict = {}
    for cid in ranked:
        r = rows.get(cid)
        if r is None:
            continue
        label = f"{r['title']} ({r['entity_type']})"
        if r["content_hash"] in seen_text:
            first = hits.get(seen_text[r["content_hash"]])
            if first and label not in first.also_in and label != f"{first.title} ({first.entity_type})":
                first.also_in.append(label)
            continue
        seen_text[r["content_hash"]] = r["parent_id"]
        if r["parent_id"] in hits:
            hits[r["parent_id"]].score += fused[cid]
            continue
        if len(hits) >= k:
            continue
        pages = f"{r['page_start']}" if r["page_start"] == r["page_end"] else f"{r['page_start']}-{r['page_end']}"
        hits[r["parent_id"]] = Hit(
            parent_id=str(r["parent_id"]), score=fused[cid], title=r["title"], circular_no=r["circular_no"],
            issued_on=r["issued_on"].isoformat() if r["issued_on"] else None, status=r["status"],
            status_reason=r["status_reason"], entity_type=r["entity_type"], section_path=r["section_path"],
            pages=pages, parent_text=r["parent_text"], matched_text=r["child_text"], also_in=[],
        )
    return sorted(hits.values(), key=lambda h: h.score, reverse=True)
