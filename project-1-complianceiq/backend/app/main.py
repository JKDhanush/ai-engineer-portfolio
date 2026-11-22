"""ComplianceIQ API entrypoint."""

import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from .config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("complianceiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after).

    We open ONE connection pool and ONE Redis client for the whole app and share them.
    Opening a new DB connection per request costs tens of ms and can exhaust Postgres
    under load; a pool keeps a few connections warm and hands them out.
    """
    app.state.db = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        command_timeout=10,
    )
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    log.info("startup complete: db pool + redis ready")
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.db.close()
        log.info("shutdown complete")


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Checks every dependency. Returns 200 if all OK, 503 if anything is down.

    Load balancers (Nginx/ALB in M9) call this to decide whether to send traffic here,
    so it must reflect real dependency health, not just "the process is alive".
    """
    checks: dict[str, str] = {}

    try:
        async with request.app.state.db.acquire() as conn:
            await conn.fetchval("SELECT 1")
            pgvector = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        checks["postgres"] = "ok"
        checks["pgvector"] = pgvector or "missing"
    except Exception as exc:  # report, don't crash the health endpoint
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        checks["redis"] = "ok" if await request.app.state.redis.ping() else "error"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    # pgvector missing means the schema never loaded, so the app can't do retrieval: report unhealthy
    healthy = (
        checks.get("postgres") == "ok"
        and checks.get("pgvector", "missing") != "missing"
        and checks.get("redis") == "ok"
    )
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "version": app.version, "checks": checks},
    )
