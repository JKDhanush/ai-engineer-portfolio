"""Tests for the retrieval metrics in evals/metrics.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))
from metrics import hit_at_k, is_relevant, ndcg_at_k, para_key, reciprocal_rank  # noqa: E402


@pytest.mark.parametrize("citation, key", [
    ("Chapter VI > E. On-going Due Diligence > Para 42(1)(ii)", "42"),
    ("Chapter I > Para 3", "3"),
    ("Annex I > Para 5(ii)", "Annex I|5"),
    ("Table 2 (page 49)", None),
    ("Preamble", None),
])
def test_para_key(citation, key):
    assert para_key(citation) == key


def test_is_relevant_matches_doc_and_paragraph():
    rel = [{"doc_id": "cb-kyc-2025", "key": "42"}, {"doc_id": "sfb-kyc-2025", "key": "43"}]
    assert is_relevant("sfb-kyc-2025", "Chapter VI > Para 43(3)", rel)
    assert not is_relevant("sfb-kyc-2025", "Chapter VI > Para 42", rel)   # right number, wrong document
    assert is_relevant("dpss", "Preamble", [{"doc_id": "dpss", "key": "*"}])


def test_rank_metrics():
    flags = [False, True, False, True]
    assert hit_at_k(flags, 1) == 0.0 and hit_at_k(flags, 3) == 1.0
    assert reciprocal_rank(flags) == 0.5
    assert reciprocal_rank([False, False]) == 0.0
    assert ndcg_at_k([True, False], 10) == 1.0
    assert 0 < ndcg_at_k(flags, 10) < 1
