# Cost model and capacity plan

All numbers trace back to something measured (`make stats`, `make load-test`, `evals/results/*`) or a published
price. Re-run those commands after changes and update this page.

## What one question costs
Measured on the laptop: **~4,750 tokens per answered question** (`make stats`: 9,502 tokens / 2 questions),
almost all of it prompt (5 source paragraphs) and ~300-400 tokens of answer.

| Answer model | Price per 1M tokens (in / out) | Cost per uncached question | 1,000 questions/day |
|---|---|---|---|
| phi4-mini on own GPU (Ollama) | 0 / 0 | $0 (electricity) | $0 |
| Groq `llama-3.1-8b-instant` (paid tier) | $0.05 / $0.08 | ≈ $0.00025 (₹0.02) | ≈ $0.25 |
| Bedrock Claude 3 Haiku | $0.25 / $1.25 | ≈ $0.0015 (₹0.13) | ≈ $1.55 |

Cost per question = (prompt tokens × input price + completion tokens × output price) / 1M × (1 − cache hit rate).
A cache hit costs nothing; at a 30% hit rate every line above drops by 30%.

**Infrastructure dominates at this scale:** the EC2 `m7i-flex.large` is ≈ $70/month (≈ $2.30/day) running 24/7,
roughly 10× the Groq bill at 1,000 questions/day. Levers: stop the server outside demo hours, or a smaller
instance with hosted embeddings (would need re-embedding the corpus with the hosted model).

## Where the limits are
| Component | Limit | Effect |
|---|---|---|
| Groq free tier, 8B model | ~30 requests/min, ~14,400/day, plus a tokens-per-minute cap (check console.groq.com) | At ~4,750 tokens/question the token cap, not requests, is the binding limit. Beyond it: 429 → the provider chain falls back (if configured) |
| CPU retrieval (bge-m3 + reranker on 2 vCPU) | measure with `make load-test` on the server | Rerank cost grows with `RERANK_TOP` (prod default 10) |
| Laptop GPU (RTX 3050, phi4-mini) | one answer at a time, ~5-8 s to first word | Requests queue; p95 grows with users |
| Redis cache | 256 MB, LRU eviction | ~thousands of cached answers |
| Per-user limit | `RATE_LIMIT_PER_MINUTE` (5 in the public demo) | protects the shared LLM quota from one visitor |

## Load test results
Fill in from `evals/results/load_test.md` after running `make load-test` (laptop) and
`python ../evals/load_test.py --url https://<ip>.sslip.io/api` (server).

## Scaling path (what I'd do next, in order)
1. Raise cache hit rate (pre-warm the top 100 questions) — free and the biggest lever.
2. Paid LLM tier or Bedrock: removes the tokens-per-minute ceiling.
3. Move retrieval models to a small GPU instance or a hosted embedding/rerank API; run 2+ API replicas behind
   a load balancer (JWT auth and Redis state already make the API stateless).
4. Managed Postgres (RDS) and Redis (ElastiCache) once the data or traffic outgrows one box.
