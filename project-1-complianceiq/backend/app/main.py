"""ComplianceIQ API entrypoint."""

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from .citations import REFUSAL, check_citations
from .config import get_settings
from .llm import generate, generate_stream, ollama_status
from .retrieval import MODES, RERANK_MODES, Hit, search

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("complianceiq")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after).

    One DB pool and one Redis client are shared by all requests: opening a DB connection per request costs
    tens of ms and can exhaust Postgres under load. The embedding model (~1.1 GB on the GPU) and the reranker
    (~1.1 GB) are also loaded once here, not per request.
    """
    app.state.db = await asyncpg.create_pool(dsn=settings.database_url, min_size=settings.db_pool_min_size,
                                             max_size=settings.db_pool_max_size, command_timeout=30)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.embedder_ready = app.state.reranker_ready = False
    if settings.load_embedder:
        try:
            from ingest.embedder import get_model  # needs torch: only installed in the local venv

            await asyncio.to_thread(get_model, settings.embed_device)
            app.state.embedder_ready = True
            log.info("embedding model loaded")
            if settings.use_reranker:
                from .rerank import get_reranker

                await asyncio.to_thread(get_reranker, settings.embed_device)
                app.state.reranker_ready = True
                log.info("reranker loaded")
        except Exception as exc:  # the API still starts; /health reports what's missing
            log.warning("model loading incomplete: %s", exc)
    log.info("startup complete")
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.db.close()
        log.info("shutdown complete")


app = FastAPI(title=settings.app_name, version="0.3.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """200 if the core dependencies are up, 503 if not (load balancers use this to route traffic).
    Models and the LLM are reported too, but don't fail the check."""
    checks: dict[str, str] = {}
    try:
        async with request.app.state.db.acquire() as conn:
            await conn.fetchval("SELECT 1")
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
    checks["llm"] = await ollama_status(settings.ollama_url, settings.llm_model)
    healthy = checks["postgres"] == "ok" and checks.get("pgvector") != "missing" and checks["redis"] == "ok"
    return JSONResponse(status_code=200 if healthy else 503,
                        content={"status": "ok" if healthy else "degraded", "version": app.version, "checks": checks})


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


async def _retrieve(request: Request, body: AskRequest) -> list[Hit]:
    if not request.app.state.embedder_ready:
        raise HTTPException(503, "Embedding model not loaded: run the API from the venv (make api)")
    from ingest.embedder import embed, to_pgvector

    mode = body.mode or (settings.retrieval_mode if request.app.state.reranker_ready else "vector")
    if mode not in MODES or (mode in RERANK_MODES and not request.app.state.reranker_ready):
        raise HTTPException(400, f"mode '{mode}' not available")
    reranker = None
    if mode in RERANK_MODES:
        from .rerank import rerank

        def reranker(q: str, ps: list[str]) -> list[float]:
            return rerank(q, ps, settings.embed_device)

    vec = (await asyncio.to_thread(embed, [body.question], 1, settings.embed_device))[0]

    hits = await search(request.app.state.db, body.question, to_pgvector(vec), mode=mode, k=body.k,
                        entity=body.entity, include_superseded=body.include_superseded, reranker=reranker)
    if mode in RERANK_MODES and hits and hits[0].score < settings.min_rerank_score:
        return []          # nothing relevant enough: refuse rather than let the LLM improvise
    return hits


def _sources(hits: list[Hit], cited: set[int]) -> list[dict]:
    return [{"id": f"S{i}", "cited": i in cited, **{k: v for k, v in asdict(h).items() if k != "parent_text"},
             "text": h.parent_text} for i, h in enumerate(hits, 1)]


def _cited(answer: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[S(\d+)\]", answer)}


@app.post("/search")
async def search_endpoint(request: Request, body: AskRequest) -> dict:
    """Retrieval only: the paragraphs the LLM would see. Used for debugging and the retrieval evals."""
    t0 = time.perf_counter()
    hits = await _retrieve(request, body)
    return {"results": [asdict(h) for h in hits], "retrieval_ms": round((time.perf_counter() - t0) * 1000)}


@app.post("/ask")
async def ask(request: Request, body: AskRequest) -> dict:
    """Retrieve, generate a grounded answer, then self-check its citations. Non-streaming (used by evals)."""
    t0 = time.perf_counter()
    hits = await _retrieve(request, body)
    t1 = time.perf_counter()
    if not hits:
        answer = REFUSAL
    else:
        try:
            answer = await generate(body.question, hits, base_url=settings.ollama_url, model=settings.llm_model,
                                    timeout=settings.llm_timeout_s, history=[t.model_dump() for t in body.history])
        except Exception as exc:
            raise HTTPException(503, f"LLM unavailable ({type(exc).__name__}): is Ollama running with "
                                     f"'{settings.llm_model}' pulled?") from exc
    t2 = time.perf_counter()
    report = check_citations(answer, [h.parent_text for h in hits])
    return {"answer": answer, "sources": _sources(hits, _cited(answer)), "citation_check": asdict(report),
            "model": settings.llm_model,
            "timings_ms": {"retrieval": round((t1 - t0) * 1000), "generation": round((t2 - t1) * 1000)}}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/ask/stream")
async def ask_stream(request: Request, body: AskRequest) -> StreamingResponse:
    """Server-Sent Events: `sources` first, then `token` pieces as the LLM writes, then `done` with the
    citation check and timings. The user sees the answer start in ~1 s instead of waiting for all of it."""
    t0 = time.perf_counter()
    hits = await _retrieve(request, body)
    t1 = time.perf_counter()

    async def events():
        yield _sse("sources", _sources(hits, set()))
        answer, first_token_ms = "", None
        if not hits:
            answer = REFUSAL
            yield _sse("token", answer)
        else:
            try:
                async for piece in generate_stream(body.question, hits, base_url=settings.ollama_url,
                                                   model=settings.llm_model, timeout=settings.llm_timeout_s,
                                                   history=[t.model_dump() for t in body.history]):
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - t1) * 1000)
                    answer += piece
                    yield _sse("token", piece)
            except Exception as exc:
                yield _sse("error", f"LLM unavailable ({type(exc).__name__}): is Ollama running?")
                return
        report = check_citations(answer, [h.parent_text for h in hits])
        yield _sse("done", {"citation_check": asdict(report), "cited": sorted(_cited(answer)),
                            "model": settings.llm_model,
                            "timings_ms": {"retrieval": round((t1 - t0) * 1000), "first_token": first_token_ms,
                                           "total": round((time.perf_counter() - t0) * 1000)}})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
