# ComplianceIQ — Regulatory compliance copilot for Indian banks & NBFCs

Ask questions about RBI/SEBI circulars and get grounded answers with **circular- and section-level citations**, aware of which circulars are active, amended or superseded.

> Headline numbers (Recall@k, faithfulness, p95 latency, cost per query) will go here once evals and load tests run.

## Run locally
One-time: install [Ollama](https://ollama.com) and pull the model: `ollama pull phi4-mini`.
```bash
cp .env.example .env
make up          # Postgres + Redis in Docker
make ingest      # PDFs in data/raw -> chunks + embeddings in Postgres
make api         # API on http://localhost:8000 (runs on the host for GPU embeddings, ADR-007)
```
Open http://localhost:8000 and ask a question, or use the API: `POST /ask`, `POST /search`, `GET /health`, docs at `/docs`.

## Docs
- [Architecture](docs/ARCHITECTURE.md)
- [Milestones](docs/MILESTONES.md)
- [Eval set format](evals/README.md)
- [Decisions log](../docs/decisions-log.md)
