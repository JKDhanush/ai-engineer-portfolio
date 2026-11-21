# Evals

We build the eval set in **M2, before** any advanced retrieval. Otherwise there's no way to prove that hybrid search, reranking or query rewriting actually helped.

## Golden set format — `golden_set.jsonl` (one JSON object per line)
```json
{
  "id": "kyc-001",
  "question": "How often must high-risk customers' KYC be updated?",
  "category": "periodic_update",
  "difficulty": "easy",
  "expected_answer": "At least once every two years for high-risk customers.",
  "relevant_chunks": [
    {"circular_no": "…", "section_path": "Chapter VI > Para 38"}
  ],
  "answerable": true
}
```
- `answerable: false` questions test the "not found" refusal.
- `relevant_chunks` are identified by circular and section (not chunk IDs), so they survive re-chunking.

## Metrics
- **Retrieval:** Recall@k, MRR, nDCG@k
- **Generation:** faithfulness, answer relevance, citation accuracy (LLM judge calibrated against human labels)
- **Ablation:** BM25 vs vector vs hybrid vs +rerank vs +query rewrite
