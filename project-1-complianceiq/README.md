# ComplianceIQ — Regulatory compliance copilot for Indian banks & NBFCs

Ask questions about RBI KYC / AML rules and get grounded answers with **circular- and paragraph-level citations**, aware of which documents are active and which were repealed.

**Live demo:** _link after the first deploy_ · **Stack:** Next.js · FastAPI · Postgres/pgvector · Redis · bge-m3 + cross-encoder rerank · Ollama / Groq / Bedrock · Docker · GitHub Actions · AWS EC2

![CI](https://github.com/JKDhanush/ai-engineer-portfolio/actions/workflows/complianceiq-ci.yml/badge.svg)

## Results so far
Retrieval on a 175-question golden set (165 answerable, 10 out-of-scope), 22 RBI documents, RTX 3050 6 GB:

| Retrieval mode | Hit@1 | Hit@5 | MRR | p50 latency |
|---|---|---|---|---|
| BM25 (keyword only) | — | — | 0.437 | — |
| Vector (bge-m3) | 0.812 | 0.958 | 0.873 | 22 ms |
| Hybrid, equal-weight RRF | — | — | 0.761 | — |
| Hybrid, weighted RRF | — | — | 0.836 | — |
| **Vector + cross-encoder rerank (default)** | **0.867** | **0.958** | **0.906** | 1.0 s |
| Hybrid + rerank | 0.873 | 0.958 | 0.906 | 2.2 s |

Refusal: a rerank-score threshold of 0.31 keeps 100% of answerable questions and refuses 80% of out-of-scope ones before the LLM is called. Full table: `evals/results/retrieval_report.md`; reasoning in ADR-009.

> Generation quality (judge correctness, faithfulness), p95 under load and cost per query will be added after `make eval-gen` and the M10 load test.

## What's inside
- **Ingestion:** layout-aware PDF parsing (headings, nested clauses, footnotes, tables) → parent/child chunks → bge-m3 embeddings in Postgres + pgvector
- **Retrieval:** vector / BM25 / hybrid modes, cross-encoder reranking, near-duplicate collapse across entity directions, active-over-superseded preference
- **Query understanding:** entity detection, follow-up rewriting, version intent
- **Generation:** streamed answers (SSE), citation self-check (sources exist, numbers match), refusal when nothing relevant is found
- **Platform:** LLM provider chain with fallback (Ollama → OpenAI-compatible → Bedrock), JWT auth + document access control, Redis exact + semantic cache, rate limits, per-query cost and latency log, `/admin/stats`
- **UI:** Next.js with streamed answers, clickable citations that open the source paragraph, usage & cost page
- **Quality:** 89 unit tests, retrieval ablation, generation eval with LLM judge + human agreement, load test, GitHub Actions CI
- **Delivery:** Docker Compose stack with automatic HTTPS on one EC2 server, deployed from GitHub Actions ([guide](deploy/README.md))

Architecture diagram: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · cost per question and capacity: [docs/COST_AND_CAPACITY.md](docs/COST_AND_CAPACITY.md)

## Run locally
One-time: install [Ollama](https://ollama.com) and pull the model: `ollama pull phi4-mini`.
```bash
cp .env.example .env
make up          # Postgres + Redis in Docker
make ingest      # PDFs in data/raw -> chunks + embeddings in Postgres
make api         # API on http://localhost:8000 (runs on the host for GPU embeddings, ADR-007)
make web-install # one-time, then in a second terminal:
make web         # UI on http://localhost:3000
```
Open http://localhost:3000 (the simple built-in page at :8000 also works), or use the API: `POST /ask`, `POST /ask/stream`, `POST /search`, `POST /auth/login`, `GET /admin/stats`, `GET /health`, docs at `/docs`.

| Command | What it does |
|---|---|
| `make test` / `make lint` | fast tests / ruff |
| `make eval` | retrieval ablation (stop `make api` first to free VRAM) |
| `make eval-gen` | generation eval + LLM judge on 40 questions (with `make api` running) |
| `make user EMAIL=you@x.com ROLE=admin` | create a login (then set `AUTH_REQUIRED=true`) |
| `make stats` | usage, latency, cache hit rate and cost for the last 24 h |
| `make load-test` | concurrency test (start the API with `RATE_LIMIT_PER_MINUTE=0 make api`) |
| `make db-dump` | export the database for the server ([deploy guide](deploy/README.md)) |

## Docs
- [Architecture](docs/ARCHITECTURE.md)
- [Deploy to AWS](deploy/README.md)
- [Cost & capacity](docs/COST_AND_CAPACITY.md)
- [Milestones](docs/MILESTONES.md)
- [Eval set format](evals/README.md)
- [Decisions log](../docs/decisions-log.md)
