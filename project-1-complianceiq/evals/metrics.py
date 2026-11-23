"""Retrieval metrics. Pure functions, unit-tested in backend/tests/test_metrics.py.

For each question we know a SET of relevant paragraphs (the rule plus its copies in other entity directions).
A retrieved paragraph is relevant if (doc_id, paragraph key) is in that set, or the set lists the whole doc.

- Hit@k (a.k.a. Recall@k here): did ANY relevant paragraph appear in the top k? The number that decides
  whether the LLM even had a chance to answer correctly.
- MRR (Mean Reciprocal Rank): 1/rank of the first relevant result (1.0 = always first, 0.5 = usually 2nd).
- nDCG@k: rewards putting relevant results higher, with diminishing credit for lower ranks.
"""

import math
import re


def para_key(citation: str) -> str | None:
    """'Chapter VI > E. ... > Para 42(1)' -> '42';  'Annex I > Para 5' -> 'Annex I|5';  'Table 1 ...' -> None."""
    m = re.search(r"Para (\w+)", citation)
    if not m:
        return None
    first = citation.split(" > ")[0]
    return f"{first}|{m.group(1)}" if first.startswith("Annex") else m.group(1)


def is_relevant(doc_id: str, citation: str, relevant: list[dict]) -> bool:
    key = para_key(citation)
    for r in relevant:
        if r["doc_id"] == doc_id and (r["key"] == "*" or r["key"] == key):
            return True
    return False


def first_relevant_rank(flags: list[bool]) -> int | None:
    return next((i + 1 for i, f in enumerate(flags) if f), None)


def hit_at_k(flags: list[bool], k: int) -> float:
    return 1.0 if any(flags[:k]) else 0.0


def reciprocal_rank(flags: list[bool]) -> float:
    r = first_relevant_rank(flags)
    return 1.0 / r if r else 0.0


def ndcg_at_k(flags: list[bool], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, f in enumerate(flags[:k]) if f)
    ideal_hits = min(sum(flags), k) or 1          # ideal: all relevant results that were retrieved, at the top
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if any(flags[:k]) else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return s[idx]
