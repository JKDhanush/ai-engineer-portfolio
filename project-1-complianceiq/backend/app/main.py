"""ComplianceIQ API entrypoint."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from .config import get_settings
from .llm import cited_sources, generate, ollama_status
from .retrieval import hybrid_search

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("complianceiq")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after).

    One connection pool and one Redis client are shared by all requests: opening a DB connection
    per request costs tens of ms and can exhaust Postgres under load.
    The embedding model (~1 GB on the GPU) is also loaded once here, not per request.
    """
    app.state.db = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        command_timeout=30,
    )
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.embedder_ready = False
    if settings.load_embedder:
        try:
            from ingest.embedder import get_model  # needs torch: only installed in the local venv

            await asyncio.to_thread(get_model, settings.embed_device)
            app.state.embedder_ready = True
            log.info("embedding model loaded")
        except Exception as exc:  # the API still starts; /ask and /search report the problem
            log.warning("embedding model not loaded: %s", exc)
    log.info("startup complete")
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.db.close()
        log.info("shutdown complete")


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """200 if the core dependencies are up, 503 if not. Load balancers use this to route traffic.
    The embedder and LLM are reported too, but don't fail the check (the API can still serve /search)."""
    checks: dict[str, str] = {}
    try:
        async with request.app.state.db.acquire() as conn:
            await conn.fetchval("SELECT 1")
            pgvector = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            chunks = await conn.fetchval("SELECT count(*) FROM chunks")
        checks["postgres"] = "ok"
        checks["pgvector"] = pgvector or "missing"
        checks["chunks"] = str(chunks)
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"
    try:
        checks["redis"] = "ok" if await request.app.state.redis.ping() else "error"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    checks["embedder"] = "ok" if request.app.state.embedder_ready else "not loaded"
    checks["llm"] = await ollama_status(settings.ollama_url, settings.llm_model)

    healthy = (
        checks.get("postgres") == "ok"
        and checks.get("pgvector", "missing") != "missing"
        and checks.get("redis") == "ok"
    )
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "version": app.version, "checks": checks},
    )


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    entity: str | None = Field(None, description="commercial_banks | nbfcs | small_finance_banks | urban_coop_banks")
    include_superseded: bool = True
    k: int = Field(5, ge=1, le=10)


async def _retrieve(request: Request, body: AskRequest):
    if not request.app.state.embedder_ready:
        raise HTTPException(503, "Embedding model not loaded: run the API from the venv (make api)")
    from ingest.embedder import embed, to_pgvector

    vec = (await asyncio.to_thread(embed, [body.question], 1, settings.embed_device))[0]
    return await hybrid_search(request.app.state.db, body.question, to_pgvector(vec), k=body.k,
                               entity=body.entity, include_superseded=body.include_superseded)


@app.post("/search")
async def search(request: Request, body: AskRequest) -> dict:
    """Retrieval only: the chunks the LLM would see. Useful for debugging and for evals (M2)."""
    t0 = time.perf_counter()
    hits = await _retrieve(request, body)
    return {"results": [asdict(h) for h in hits], "retrieval_ms": round((time.perf_counter() - t0) * 1000)}


@app.post("/ask")
async def ask(request: Request, body: AskRequest) -> dict:
    """Retrieve, then generate a grounded answer with citations."""
    t0 = time.perf_counter()
    hits = await _retrieve(request, body)
    t1 = time.perf_counter()
    if not hits:
        answer = "I could not find this in the loaded RBI documents."
    else:
        try:
            answer = await generate(body.question, hits, base_url=settings.ollama_url, model=settings.llm_model,
                                    timeout=settings.llm_timeout_s)
        except Exception as exc:
            raise HTTPException(503, f"LLM unavailable ({type(exc).__name__}): is Ollama running with "
                                     f"'{settings.llm_model}' pulled?") from exc
    t2 = time.perf_counter()
    cited = cited_sources(answer)
    return {
        "answer": answer,
        "sources": [
            {"id": f"S{i}", "cited": i in cited, **{k: v for k, v in asdict(h).items() if k != "parent_text"},
             "text": h.parent_text}
            for i, h in enumerate(hits, 1)
        ],
        "model": settings.llm_model,
        "timings_ms": {"retrieval": round((t1 - t0) * 1000), "generation": round((t2 - t1) * 1000)},
    }
