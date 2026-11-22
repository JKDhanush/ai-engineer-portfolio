# Shortcuts for daily commands. Run from project-1-complianceiq/:  make up, make api, ...
.PHONY: up down reset ps logs health psql redis api ingest ingest-force test test-all docker-api

VENV := backend/.venv/bin

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

api:          ## run the API on the host (GPU embeddings), auto-reload on code changes. Ctrl+C to stop.
	cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app

ingest:       ## load all PDFs into Postgres (skips ones already loaded)
	cd backend && .venv/bin/python scripts/ingest.py

ingest-force: ## re-ingest everything (after changing the parser/chunker)
	cd backend && .venv/bin/python scripts/ingest.py --force

test:         ## fast tests (no PDFs)
	cd backend && .venv/bin/pytest -m "not slow" -q

test-all:     ## all tests, including real PDFs (~1 min)
	cd backend && .venv/bin/pytest -q

docker-api:   ## optional: the API in Docker (health only, no GPU)
	docker compose --profile docker-api up -d --build api
