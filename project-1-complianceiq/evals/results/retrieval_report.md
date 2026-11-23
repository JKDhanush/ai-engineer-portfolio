# Retrieval evaluation (2026-11-23 21:42)

165 answerable golden questions, top-10 results, relevant = the rule or its copy in any entity's directions / the 2016 Master Direction.

## Ablation

| Mode | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@10 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|
| BM25 (keyword only) | 0.291 | 0.558 | 0.612 | 0.437 | 0.516 | 51 | 88 |
| Vector (bge-m3) | 0.812 | 0.933 | 0.958 | 0.873 | 0.879 | 22 | 31 |
| Hybrid (RRF) | 0.667 | 0.812 | 0.879 | 0.761 | 0.781 | 68 | 106 |
| Hybrid (weighted RRF) | 0.776 | 0.867 | 0.927 | 0.836 | 0.833 | 68 | 106 |
| Vector + rerank | 0.867 | 0.945 | 0.958 | 0.906 | 0.908 | 1042 | 1409 |
| Hybrid + rerank | 0.873 | 0.933 | 0.945 | 0.906 | 0.906 | 2169 | 3027 |

## By category (Vector + rerank)

| Category | n | Hit@5 | MRR |
|---|---|---|---|
| annex_wmd | 2 | 0.50 | 0.50 |
| applicability | 3 | 1.00 | 0.67 |
| acceptance | 6 | 0.67 | 0.67 |
| edd | 3 | 0.67 | 0.67 |
| cdd_individual | 7 | 0.86 | 0.68 |
| wire_transfer | 2 | 1.00 | 0.75 |
| identification | 4 | 1.00 | 0.83 |
| vcip | 5 | 1.00 | 0.85 |
| sanctions | 9 | 1.00 | 0.87 |
| definitions | 22 | 0.91 | 0.89 |
| periodic_updation | 9 | 1.00 | 0.89 |
| annex_uapa | 5 | 1.00 | 0.90 |
| policy | 12 | 1.00 | 0.90 |
| risk | 4 | 1.00 | 1.00 |
| otp_ekyc | 6 | 1.00 | 1.00 |
| small_account | 5 | 1.00 | 1.00 |
| legal_entity | 8 | 1.00 | 1.00 |
| beneficial_owner | 2 | 1.00 | 1.00 |
| monitoring | 3 | 1.00 | 1.00 |
| pep | 5 | 1.00 | 1.00 |
| intermediaries | 2 | 1.00 | 1.00 |
| sdd | 5 | 1.00 | 1.00 |
| records | 5 | 1.00 | 1.00 |
| reporting | 3 | 1.00 | 1.00 |
| secrecy | 2 | 1.00 | 1.00 |
| ckycr | 3 | 1.00 | 1.00 |
| fatca | 1 | 1.00 | 1.00 |
| instruments | 5 | 1.00 | 1.00 |
| money_mules | 1 | 1.00 | 1.00 |
| ucic | 2 | 1.00 | 1.00 |
| new_tech | 1 | 1.00 | 1.00 |
| correspondent | 1 | 1.00 | 1.00 |
| third_party | 1 | 1.00 | 1.00 |
| staff | 1 | 1.00 | 1.00 |
| fcra | 1 | 1.00 | 1.00 |
| versions | 9 | 1.00 | 1.00 |

## Refusal threshold (Vector + rerank)

Answerable top score p10/p50: 0.881 / 0.986 · out-of-scope p50/p90: 0.008 / 0.589

Suggested `MIN_RERANK_SCORE=0.310`: keeps 100% of answerable questions, refuses 80% of out-of-scope ones (only 10 negatives, so treat as a starting point).

## Refusal threshold (Hybrid + rerank)

Answerable top score p10/p50: 0.881 / 0.986 · out-of-scope p50/p90: 0.008 / 0.589

Suggested `MIN_RERANK_SCORE=0.310`: keeps 100% of answerable questions, refuses 80% of out-of-scope ones (only 10 negatives, so treat as a starting point).

## Misses at top-5 (Vector + rerank): 7

- `def-08` (definitions): got ['cb-kyc-2025 | Chapter VI > C. CDD Measures for Legal Entities > Para 37', 'sfb-kyc-2025 | Chapter VI > C. CDD Measures for Legal Entities > Para 34']
- `def-09` (definitions): got ['ucb-kyc-2025 | Chapter X > Para 64', 'md-kyc-2016 | Chapter X > Para 56']
- `cap-02` (acceptance): got ['ucb-kyc-2025 | Chapter V > Para 21', 'ucb-kyc-2025 | Chapter VI > E. On-going Due Diligence > Para 40']
- `cap-06` (acceptance): got ['cb-kyc-2025 | Chapter X > Para 65', 'cb-kyc-2025 | Chapter IV > Para 20']
- `cdd-02` (cdd_individual): got ['ucb-kyc-2025 | Chapter X > Para 75', 'cb-kyc-2025 | Chapter X > Para 76']
- `edd-02` (edd): got ['md-kyc-2016 | Chapter VI > Part I. Customer Due Diligence (CDD) Procedure in case of Individuals > Para 23', 'md-kyc-2016 | Chapter VI > Part I. Customer Due Diligence (CDD) Procedure in case of Individuals > Para 17']
- `anx-06` (annex_wmd): got ['md-kyc-2016 | Annex III > Para 5', 'md-kyc-2016 | Annex III > Para 4']
