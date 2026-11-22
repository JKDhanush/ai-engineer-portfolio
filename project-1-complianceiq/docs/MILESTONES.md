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

## M1 — Ingestion pipeline ⏳
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
- [~] Version status: simple rule (pre-repeal 2016 MD family / 'Withdrawn' stamp = superseded). Full graph in M5

**MVP slice (pulled forward):** hybrid search (pgvector + full-text, RRF) `/search`, grounded answers with
citations via local Ollama `/ask`, and a minimal web page at `/`. Evals (M2) come next to measure it.

## M2 — Golden eval set + vector baseline
## M3 — Hybrid + RRF + rerank + ablation table
## M4 — Grounded generation + SSE streaming
## M5 — Query intelligence + versioning
## M6 — Generation evals in CI
## M7 — Auth, cache, rate limits, Bedrock + fallback, cost tracking
## M8 — Next.js UI
## M9 — EC2 deploy + CI/CD + Langfuse
## M10 — Load test, capacity plan, cost model, demo, README
