# Evals

Evaluation comes **before** tuning: every retrieval or prompt change is judged against the same questions.

## Files
| File | What it is |
|---|---|
| `golden_questions.py` | 175 hand-written questions (165 answerable, 10 out-of-scope), each pointing at the paragraph that answers it |
| `build_golden.py` | expands each target to the equivalent paragraph in every entity's directions and the 2016 MD → `golden_set.jsonl` |
| `golden_set.jsonl` | the built set (committed) |
| `metrics.py` | Hit@k, MRR, nDCG@k (unit-tested in `backend/tests/test_metrics.py`) |
| `run_retrieval_eval.py` | runs the ablation and writes `results/retrieval_report.md` + per-question JSON |

## Run (from `project-1-complianceiq/`, venv active, DB loaded)
```bash
make golden      # only after editing golden_questions.py
make eval        # all four retrieval modes (~2-4 min on an RTX 3050); stop `make api` first to free VRAM
```

## Golden set format (`golden_set.jsonl`, one JSON object per line)
```json
{"id": "upd-01", "question": "How often must KYC be updated for high-risk customers?",
 "category": "periodic_updation", "difficulty": "easy", "entity": null, "answerable": true,
 "expected_answer": "At least once every two years.",
 "relevant": [{"doc_id": "cb-kyc-2025", "key": "42"}, {"doc_id": "sfb-kyc-2025", "key": "43", "similarity": 1.0},
              {"doc_id": "ucb-kyc-2025", "key": "41", "similarity": 1.0}, {"doc_id": "md-kyc-2016", "key": "38", "similarity": 0.93}]}
```
`key` is the paragraph number (`"Annex I|5"` for annex paragraphs, `"*"` for a whole short circular).

## Metrics
- **Hit@k**: is any relevant paragraph in the top k? (Whether the LLM had a chance to answer.)
- **MRR**: mean of 1/rank of the first relevant paragraph.
- **nDCG@10**: rank-weighted relevance.
- Generation quality (faithfulness, answer relevance, citation accuracy with an LLM judge) is added in M6.
