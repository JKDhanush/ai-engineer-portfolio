"""Tests for the pure parts of app/retrieval.py: RRF fusion and duplicate collapsing."""

import uuid
from datetime import date

from app.retrieval import _group, rrf


def row(parent: str, title: str, text: str, doc: str = "cb") -> dict:
    return {"child_id": uuid.uuid4(), "child_text": text[:50], "child_header": "", "content_hash": parent,
            "parent_id": parent, "parent_text": text, "section_path": f"Para {parent}", "page_start": 1,
            "page_end": 2, "title": title, "circular_no": "X", "issued_on": date(2025, 11, 28), "status": "active",
            "source_file": "f.pdf", "doc_id": doc, "entity_type": "commercial_banks", "status_reason": None,
            "pdf_url": None}


def test_rrf_rewards_items_ranked_high_in_both_lists():
    scores = rrf(["a", "b", "c"], ["c", "a"])
    assert max(scores, key=scores.get) == "a" and scores["c"] > scores["b"]


def test_weighted_rrf_lets_the_stronger_list_win():
    equal = rrf(["v1", "v2"], ["k1", "v2"])
    weighted = rrf(["v1", "v2"], ["k1", "v2"], weights=[1.0, 0.3])
    assert weighted["v1"] > weighted["k1"] and equal["v1"] == equal["k1"]


RULE = ("The bank shall carry out periodic updation at least once in every two years for high-risk customers, "
        "once in every eight years for medium risk customers and once in every ten years for low-risk customers.")


def test_same_rule_in_other_entity_directions_collapses_into_also_in():
    rows = [row("p1", "CB Directions", RULE), row("p2", "NBFC Directions", RULE.replace("bank", "NBFC"), "nbfc"),
            row("p3", "CB Directions", "Small accounts have a balance limit of fifty thousand rupees at any time.")]
    ranked = [r["child_id"] for r in rows]
    hits = _group(ranked, {r["child_id"]: r for r in rows}, {c: 1.0 for c in ranked}, k=5)
    assert [h.parent_id for h in hits] == ["p1", "p3"]
    assert hits[0].also_in == ["NBFC Directions"]


def test_k_limits_distinct_paragraphs():
    rows = [row(f"p{i}", "CB", f"Distinct rule number {i} about topic {i * 7} with unique words {i * 13}.")
            for i in range(8)]
    ranked = [r["child_id"] for r in rows]
    assert len(_group(ranked, {r["child_id"]: r for r in rows}, {c: 1.0 for c in ranked}, k=3)) == 3
