"""ComplianceIQ API: routes only. The question-answering logic lives in pipeline.py."""

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from . import pipeline, querylog
from .auth import User, authenticate, create_token, current_user, require_admin
from .config import get_settings
from .migrate import migrate
from .providers import build_chain
from .ratelimit import check_rate_limit
from .retrieval import MODES, RERANK_MODES, search

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("complianceiq")
STATIC = Path(__file__).parent / "static"
CurrentUser = Annotated[User, Depends(current_user)]   # FastAPI dependency: who is calling


async def refresh_corpus_version(app: FastAPI) -> None:
    """Part of every cache key: re-ingesting documents changes it, so stale answers are never served."""
    while True:
        try:
            async with app.state.db.acquire() as conn:
                row = await conn.fetchrow("SELECT count(*) AS n, max(created_at) AS t FROM chunks")
            app.state.corpus_version = f"{row['n']}@{row['t'].timestamp() if row['t'] else 0:.0f}"
        except Exception:
            pass
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after): shared DB pool and Redis client,
    database migrations, the LLM provider chain, and the GPU models (loaded once, not per request)."""
    app.state.settings = settings
    if settings.jwt_secret == "dev-only-change-me" and (settings.auth_required or settings.environment != "local"):
        raise RuntimeError("Set a real JWT_SECRET (in .env or the secret manager) before enabling auth or deploying")
    app.state.db = await asyncpg.create_pool(dsn=settings.database_url, min_size=settings.db_pool_min_size,
                                             max_size=settings.db_pool_max_size, command_timeout=30)
    async with app.state.db.acquire() as conn:
        log.info("migrations applied: %s", await migrate(conn))
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.chain = build_chain(settings)
    app.state.corpus_version = "unknown"
    version_task = asyncio.create_task(refresh_corpus_version(app))
    app.state.embedder_ready = app.state.reranker_ready = False
    if settings.load_embedder:
        try:
            from ingest.embedder import get_model  # needs torch: only installed in the local venv

            await asyncio.to_thread(get_model, settings.embed_device)
            app.state.embedder_ready = True
            if settings.use_reranker:
                from .rerank import get_reranker

                await asyncio.to_thread(get_reranker, settings.embed_device)
                app.state.reranker_ready = True
        except Exception as exc:  # the API still starts; /health reports what's missing
            log.warning("model loading incomplete: %s", exc)
    log.info("startup complete: embedder=%s reranker=%s providers=%s", app.state.embedder_ready,
             app.state.reranker_ready, [p.name for p in app.state.chain.providers])
    try:
        yield
    finally:
        version_task.cancel()
        await app.state.redis.aclose()
        await app.state.db.close()


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan,
              description="RBI KYC/AML compliance copilot: grounded answers with circular- and paragraph-level "
                          "citations.")


# ---------------------------------------------------------------- pages & health
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """200 if core dependencies are up, 503 if not (load balancers use this). Models and the LLM are reported
    but don't fail the check."""
    checks: dict[str, str] = {}
    try:
        async with request.app.state.db.acquire() as conn:
            checks["pgvector"] = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname='vector'") \
                or "missing"
            checks["chunks"] = str(await conn.fetchval("SELECT count(*) FROM chunks"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"
    try:
        checks["redis"] = "ok" if await request.app.state.redis.ping() else "error"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    checks["embedder"] = "ok" if request.app.state.embedder_ready else "not loaded"
    checks["reranker"] = "ok" if request.app.state.reranker_ready else "off"
    primary = request.app.state.chain.primary
    checks["llm"] = f"{primary.name}: " + (await primary.status() if hasattr(primary, "status") else "configured")
    healthy = checks["postgres"] == "ok" and checks.get("pgvector") != "missing" and checks["redis"] == "ok"
    return JSONResponse(status_code=200 if healthy else 503,
                        content={"status": "ok" if healthy else "degraded", "version": app.version, "checks": checks})


# ---------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
async def login(request: Request, body: LoginRequest) -> dict:
    async with request.app.state.db.acquire() as conn:
        user = await authenticate(conn, body.email, body.password)
    if user is None:
        raise HTTPException(401, "wrong email or password")
    return {"access_token": create_token(user, settings.jwt_secret, settings.jwt_ttl_minutes),
            "token_type": "bearer", "user": asdict(user)}


@app.get("/auth/me")
async def me(user: CurrentUser) -> dict:
    return asdict(user) | {"auth_required": settings.auth_required}


# ---------------------------------------------------------------- questions
class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    entity: str | None = Field(None, description="commercial_banks | nbfcs | small_finance_banks | urban_coop_banks")
    include_superseded: bool = True
    k: int = Field(5, ge=1, le=10)
    mode: str | None = Field(None, description=f"one of {MODES}; default: RETRIEVAL_MODE setting")
    history: list[Turn] = Field(default_factory=list, max_length=10)


async def guard(request: Request, body: AskRequest, user: User) -> None:
    """Checks shared by every question endpoint: models loaded, valid mode, rate limit."""
    if not request.app.state.embedder_ready:
        raise HTTPException(503, "Embedding model not loaded: run the API from the venv (make api)")
    if body.mode and (body.mode not in MODES or (body.mode in RERANK_MODES and not request.app.state.reranker_ready)):
        raise HTTPException(400, f"mode '{body.mode}' not available")
    identity = user.id or (request.client.host if request.client else "unknown")
    await check_rate_limit(request.app.state.redis, identity, settings.rate_limit_per_minute)


def _events(request: Request, body: AskRequest, user: User):
    return pipeline.run(request.app, question=body.question, history=[t.model_dump() for t in body.history],
                        entity=body.entity, include_superseded=body.include_superseded, k=body.k, mode=body.mode,
                        user=user)


@app.post("/search")
async def search_endpoint(request: Request, body: AskRequest, user: CurrentUser) -> dict:
    """Retrieval only: the paragraphs the LLM would see (debugging, evals)."""
    await guard(request, body, user)
    from ingest.embedder import embed, to_pgvector

    t0 = time.perf_counter()
    mode = body.mode or (settings.retrieval_mode if request.app.state.reranker_ready else "vector")
    vec = (await asyncio.to_thread(embed, [body.question], 1, settings.embed_device))[0]
    reranker = None
    if mode in RERANK_MODES:
        from .rerank import rerank

        def reranker(q, ps):
            return rerank(q, ps, settings.embed_device)

    hits = await search(request.app.state.db, body.question, to_pgvector(vec), mode=mode, k=body.k,
                        entity=body.entity, include_superseded=body.include_superseded, reranker=reranker,
                        access_levels=user.access_levels)
    return {"mode": mode, "results": [asdict(h) for h in hits],
            "retrieval_ms": round((time.perf_counter() - t0) * 1000)}


@app.post("/ask")
async def ask(request: Request, body: AskRequest, user: CurrentUser) -> dict:
    """Full answer as one JSON response (used by evals and API clients)."""
    await guard(request, body, user)
    out: dict = {"answer": ""}
    try:
        async for event, data in _events(request, body, user):
            if event == "token":
                out["answer"] += data
            else:
                out[event] = data
    except RuntimeError as exc:                 # every LLM provider failed
        raise HTTPException(503, str(exc)) from exc
    done = out.pop("done")
    cited = set(done["cited"])
    for src in out["sources"]:
        src["cited"] = int(src["id"][1:]) in cited
    return out | done


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.post("/ask/stream")
async def ask_stream(request: Request, body: AskRequest, user: CurrentUser) -> StreamingResponse:
    """Server-Sent Events: meta, sources, token..., done. First words appear in ~1-2 s."""
    await guard(request, body, user)

    async def events():
        try:
            async for event, data in _events(request, body, user):
                yield _sse(event, data)
        except RuntimeError as exc:
            yield _sse("error", str(exc))

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- admin
@app.get("/admin/stats")
async def admin_stats(request: Request, user: CurrentUser, hours: int = 24) -> dict:
    """Usage, latency, cache hit rate, refusal rate, citation pass rate and cost over the last N hours."""
    if settings.auth_required or settings.environment != "local":   # public demo: stats stay admin-only
        require_admin(user)
    return await querylog.stats(request.app.state.db, hours)


@app.post("/admin/cache/clear")
async def clear_cache(request: Request, user: CurrentUser) -> dict:
    if settings.auth_required or settings.environment != "local":   # public demo: stats stay admin-only
        require_admin(user)
    keys = [k async for k in request.app.state.redis.scan_iter("cache:*")]
    if keys:
        await request.app.state.redis.delete(*keys)
    return {"deleted": len(keys)}
