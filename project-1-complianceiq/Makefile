# Shortcuts for daily commands. Run from project-1-complianceiq/:  make up, make health, ...
.PHONY: up down logs health psql redis reset ps

up:        ## build and start everything in the background
	docker compose up --build -d

down:      ## stop containers (data is kept)
	docker compose down

reset:     ## stop AND delete data volumes, so init.sql runs again on next `make up`
	docker compose down -v

ps:        ## show container status
	docker compose ps

logs:      ## follow api logs
	docker compose logs -f api

health:    ## call the health endpoint
	curl -s localhost:8000/health | jq

psql:      ## open a SQL shell inside the postgres container
	docker compose exec postgres psql -U $${POSTGRES_USER:-complianceiq} -d $${POSTGRES_DB:-complianceiq}

redis:     ## open a redis shell
	docker compose exec redis redis-cli
