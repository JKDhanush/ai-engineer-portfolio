# Server-side commands. Run on the EC2 instance from project-1-complianceiq/deploy.
COMPOSE := docker compose --env-file ../.env -f docker-compose.prod.yml
.PHONY: up down logs ps restore user stats health

up:       ## build and start (or update) everything
	$(COMPOSE) up -d --build

down:     ## stop everything (data is kept)
	$(COMPOSE) down

logs:     ## follow the API logs
	$(COMPOSE) logs -f api

ps:
	$(COMPOSE) ps

restore:  ## load the database dump copied from the laptop (data/complianceiq.dump)
	$(COMPOSE) exec -T postgres sh -c 'pg_restore --clean --if-exists --no-owner -U $$POSTGRES_USER -d $$POSTGRES_DB /backup/complianceiq.dump'
	$(COMPOSE) exec -T redis redis-cli FLUSHALL

user:     ## make user EMAIL=you@example.com ROLE=admin
	$(COMPOSE) exec api python scripts/create_user.py $(EMAIL) --role $(or $(ROLE),analyst)

health:
	curl -s https://$$(grep ^SITE_ADDRESS ../.env | cut -d= -f2)/api/health

stats:
	$(COMPOSE) exec api python -c "import urllib.request,sys; print(urllib.request.urlopen('http://localhost:8000/admin/stats').read().decode())"
