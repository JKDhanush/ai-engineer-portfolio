# ComplianceIQ — Regulatory compliance copilot for Indian banks & NBFCs

Ask questions about RBI/SEBI circulars and get grounded answers with **circular- and section-level citations**, aware of which circulars are active, amended or superseded.

> Headline numbers (Recall@k, faithfulness, p95 latency, cost per query) will go here once evals and load tests run.

## Run locally
```bash
cp .env.example .env
make up          # docker compose up --build -d
make health      # {"status":"ok", "checks": {"postgres":"ok","pgvector":"…","redis":"ok"}}
```

## Docs
- [Architecture](docs/ARCHITECTURE.md)
- [Milestones](docs/MILESTONES.md)
- [Eval set format](evals/README.md)
- [Decisions log](../docs/decisions-log.md)
