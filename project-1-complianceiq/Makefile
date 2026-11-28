# Shortcuts for daily commands. Run from project-1-complianceiq/:  make up, make api, ...

.PHONY: models up down reset ps logs health psql redis api ingest ingest-force test test-all lint golden eval eval-quick eval-gen eval-gate user stats docker-api

VENV := backend/.venv/bin
# Models are already in ~/.cache/huggingface: don't phone home on every start (faster, works offline).
# First run on a new machine: `make models` (downloads them once).
OFFLINE := HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

up:           ## start Postgres + Redis in Docker
	docker compose up -d postgres redis

down:         ## stop containers (data is kept)
	docker compose --profile docker-api down

reset:        ## stop AND delete data volumes, so init.sql runs again on next `make up` (DELETES THE DATABASE)
	docker compose --profile docker-api down -v

ps:           ## show container status
	docker compose --profile docker-api ps

logs:         ## follow Postgres logs
	docker compose logs -f postgres

health:       ## call the health endpoint
	curl -s localhost:8000/health | jq

psql:         ## open a SQL shell inside the postgres container
	docker compose exec postgres psql -U $${POSTGRES_USER:-complianceiq} -d $${POSTGRES_DB:-complianceiq}

redis:        ## open a redis shell
	docker compose exec redis redis-cli

api:          ## run the API on the host (GPU models), auto-reload on code changes. Ctrl+C to stop.
	cd backend && $(OFFLINE) .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app

ingest:       ## load all PDFs into Postgres (skips ones already loaded)
	cd backend && $(OFFLINE) .venv/bin/python scripts/ingest.py

ingest-force: ## re-ingest everything (after changing the parser/chunker)
	cd backend && $(OFFLINE) .venv/bin/python scripts/ingest.py --force

test:         ## fast tests (no PDFs, no GPU)
	cd backend && .venv/bin/pytest -m "not slow" -q

test-all:     ## all tests, including real PDFs (~1 min)
	cd backend && .venv/bin/pytest -q

lint:         ## ruff lint
	cd backend && .venv/bin/ruff check . ../evals

golden:       ## rebuild evals/golden_set.jsonl from golden_questions.py
	cd backend && .venv/bin/python ../evals/build_golden.py

eval:         ## retrieval ablation: bm25 / vector / hybrid / hybrid+rerank (stop `make api` first to free VRAM)
	cd backend && $(OFFLINE) .venv/bin/python ../evals/run_retrieval_eval.py

eval-quick:   ## first 30 questions, the two rerank modes
	cd backend && $(OFFLINE) .venv/bin/python ../evals/run_retrieval_eval.py --modes vector_rerank,hybrid_rerank --limit 30

eval-gen:     ## generation eval on 40 questions + LLM judge (needs `make api` running in another terminal)
	cd backend && $(OFFLINE) .venv/bin/python ../evals/run_generation_eval.py --limit 40 --labels 30

eval-gate:    ## full generation eval, exits non-zero if quality drops below the gates (run before a release)
	cd backend && $(OFFLINE) .venv/bin/python ../evals/run_generation_eval.py --gate

user:         ## create a login: make user EMAIL=you@example.com ROLE=admin (asks for the password)
	cd backend && .venv/bin/python scripts/create_user.py $(EMAIL) --role $(or $(ROLE),analyst)

stats:        ## usage / latency / cost / cache stats for the last 24 h
	curl -s localhost:8000/admin/stats | jq

models:       ## download / refresh the embedding + reranker models (needs internet)
	cd backend && .venv/bin/python -c "from ingest.embedder import get_model; from app.rerank import get_reranker; get_model(); get_reranker(); print('models ready')"

docker-api:   ## optional: the API in Docker (health only, no GPU)
	docker compose --profile docker-api up -d --build api
