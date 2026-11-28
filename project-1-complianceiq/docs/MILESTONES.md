# ComplianceIQ — Milestones

## M0 — Setup ✅ (2026-11-21)
- [x] Linux dev environment: Docker Engine + Compose, Git + GitHub SSH, uv + Python 3.12, VS Code, AWS CLI
- [x] Repo structure (monorepo), .gitignore, .gitattributes
- [x] docker-compose: Postgres 17 + pgvector, Redis 7, api (healthchecks, hot reload)
- [x] Schema: `documents`, `chunks` (HNSW cosine index, weighted tsvector + GIN)
- [x] FastAPI skeleton: lifespan, asyncpg pool, async Redis, `/health`
- [x] ADR-001…004
- [x] `docker compose up --build`, then `/health` returns postgres ok + pgvector 0.8.7 + redis ok
- [x] First commits pushed to GitHub: https://github.com/JKDhanush/ai-engineer-portfolio

**Lessons from M0**
- Docker's init scripts (`/docker-entrypoint-initdb.d`) run only on an **empty** volume. After a failed first boot, run `make reset` before retrying.
- Files mounted into containers must be readable by the container's user (`chmod 644`).
- A health check must test what the app actually needs (pgvector), not just "the DB answers".

## M1 — Ingestion pipeline ✅
- [x] Corpus: 22 RBI KYC documents (14 docs + 8 annexes) in `data/raw/`, listed in committed `data/manifest.csv`
  - Covers the full version story: KYC Master Direction 2016 and its 2024–25 amendments → repealed 28 Nov 2025 →
    entity-wise KYC Directions 2025 (Commercial Banks, NBFCs, SFBs, UCBs) → their Dec 2025 / Sep 2026 amendments
  - RBI's document server uses an F5 JavaScript bot challenge, so scripted downloads get HTML. We fetch through a
    real browser (`import_downloads.py --open`), then the script validates (`%PDF`), renames and fingerprints (SHA-256) each file.
- [x] Layout-aware PDF + table parsing (`ingest/pdf_reader.py`: bold/size/footnotes/tables; drops TOC, page numbers, masthead, "Withdrawn" stamps)
- [x] Metadata extraction from the header: circular nos., date, title (`ingest/metadata.py`)
- [x] Structure tree: Chapter > Section > Para > clauses, with citation paths like `Para 38(1)(ii)` (`ingest/structure.py`)
- [x] Parent-child chunking + contextual headers + tables + amendment footnotes (`ingest/chunker.py`)
- [x] Dedupe: file SHA-256 (idempotent ingest) + chunk content hash (collapsed at retrieval)
- [x] bge-m3 embeddings on GPU + transactional load into Postgres (`scripts/ingest.py`, `ingest/loader.py`)
- [x] Version status: pre-repeal 2016 MD family / 'Withdrawn' stamp = superseded; active copies preferred in M5

**MVP slice (pulled forward):** hybrid search (pgvector + full-text, RRF) `/search`, grounded answers with
citations via local Ollama `/ask`, and a minimal web page at `/`. Evals (M2) come next to measure it.

## M2 — Golden eval set + retrieval baseline ✅
- [x] 175 questions (165 answerable + 10 out-of-scope), paragraph-level labels (`evals/golden_questions.py`)
- [x] Cross-document equivalence: same rule in CB/NBFC/SFB/UCB directions + 2016 MD counts (`evals/build_golden.py`)
- [x] Metrics: Hit@1/3/5, MRR, nDCG@10, latency, per-category breakdown, misses list (`evals/run_retrieval_eval.py`)

## M3 — Hybrid + RRF + rerank + ablation ✅
- [x] Retrieval modes: bm25 / vector / hybrid (RRF) / hybrid + cross-encoder rerank (`app/retrieval.py`, `app/rerank.py`)
- [x] Near-duplicate collapse across entity directions ("same rule also in")
- [x] Ablation table: `evals/results/retrieval_report.md` (run `make eval` on the GPU machine)

## M4 — Grounded generation + streaming ✅
- [x] SSE streaming `/ask/stream` + streaming web UI (first words in ~1-2 s)
- [x] Citation self-check: invalid refs, uncited sentences, unsupported sentences, numbers not in sources
- [x] Refusal for out-of-scope questions (prompt rule + optional rerank-score threshold)
- [x] Source cards with PDF links, status badges, "same rule also in"

## M5 — Query intelligence + versioning ✅
- [x] Entity detection from the question (`app/router.py`), user default entity
- [x] Follow-up rewriting into a standalone question (only with chat history)
- [x] Version intent: history questions keep superseded docs; otherwise the active copy replaces a superseded duplicate + note
- [x] Optional multi-query / HyDE expansion (`QUERY_EXPANSION`, off by default)

## M6 — Generation evals in CI ✅
- [x] `evals/run_generation_eval.py`: refusal accuracy, citation pass rate, cited-source hit, LLM-judge correctness / faithfulness / relevance, `--gate`
- [x] Human-label sheet + judge agreement (Cohen's kappa): `evals/judge_agreement.py`
- [x] GitHub Actions: ruff + fast tests + golden-set validation + Docker build (`.github/workflows/complianceiq-ci.yml`)

## M7 — Auth, cache, rate limits, Bedrock + fallback, cost tracking ✅
- [x] Provider chain Ollama → OpenAI-compatible → Bedrock with fallback, token usage, cost per query (`app/providers.py`)
- [x] JWT login, users table, roles, document ACL inside the retrieval SQL (`app/auth.py`, `make user`)
- [x] Redis answer cache: exact + semantic, invalidated by corpus version (`app/cache.py`)
- [x] Redis rate limit per user/IP → 429 (`app/ratelimit.py`)
- [x] `query_log` table + `/admin/stats` (p50/p95, cache hit rate, refusal rate, citation pass rate, cost)
## M8 — Next.js UI ✅
- [x] Next.js 16 + TypeScript + Tailwind (`frontend/`): streaming chat with follow-ups, clickable citations → source panel
- [x] Citation badge, cache / provider / latency / cost line, superseded notes, entity filter, stop button
- [x] Login page (JWT), Usage & cost page over `/admin/stats`
- [x] Production Docker image (standalone output)

## M9 — EC2 deploy + CI/CD ✅ (code) · ⏳ (first deploy)
- [x] `deploy/`: Compose stack (Caddy HTTPS, Next.js, FastAPI CPU image, Postgres, Redis), EC2 setup script, server Makefile, step-by-step guide
- [x] GitHub Actions: frontend build job + SSH deploy + smoke test (enabled with `DEPLOY_ENABLED`)
- [x] Observability: query_log + Usage page (Langfuse deferred, ADR-016)
- [ ] First deploy on the AWS Free plan account

## M10 — Load test, capacity plan, cost model, demo, README ✅ (tools) · ⏳ (numbers)
- [x] `evals/load_test.py` (`make load-test`): concurrency levels, first-word / total p50/p95, throughput, 429s, cache share
- [x] `docs/COST_AND_CAPACITY.md`: cost per question by model, infra vs LLM cost, limits, scaling path
- [ ] Run the load test on laptop + server and paste the tables; generation eval numbers into the README
- [ ] Screenshots / short demo GIF in the README
