# ComplianceIQ — Milestones

## M0 — Setup ⏳
- [x] Linux dev environment: Docker Engine + Compose, Git + GitHub SSH, uv + Python 3.12, VS Code, AWS CLI
- [x] Repo structure (monorepo), .gitignore, .gitattributes
- [x] docker-compose: Postgres 17 + pgvector, Redis 7, api (healthchecks, hot reload)
- [x] Schema: `documents`, `chunks` (HNSW cosine index, weighted tsvector + GIN)
- [x] FastAPI skeleton: lifespan, asyncpg pool, async Redis, `/health`
- [x] ADR-001…004
- [ ] `docker compose up --build`, then `/health` returns postgres ok + redis ok
- [ ] First commits pushed to GitHub

## M1 — Ingestion pipeline
- [ ] ~50 RBI KYC/AML circulars in `data/raw/` + committed `manifest.csv`
- [ ] Layout-aware PDF + table parsing
- [ ] Metadata extraction (circular no., date, department, supersedes)
- [ ] Parent-child chunking + contextual headers
- [ ] Dedupe (file hash + chunk hash)
- [ ] Embeddings + load into Postgres
- [ ] Version graph (active / amended / superseded)

## M2 — Golden eval set + vector baseline
## M3 — Hybrid + RRF + rerank + ablation table
## M4 — Grounded generation + SSE streaming
## M5 — Query intelligence + versioning
## M6 — Generation evals in CI
## M7 — Auth, cache, rate limits, Bedrock + fallback, cost tracking
## M8 — Next.js UI
## M9 — EC2 deploy + CI/CD + Langfuse
## M10 — Load test, capacity plan, cost model, demo, README
