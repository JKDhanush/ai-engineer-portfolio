"""The question-answering pipeline: one place that runs every stage in order.

    understand  -> entity, version intent, follow-up rewrite                  (router.py, M5)
    embed       -> question vector (bge-m3), optionally expanded (multi-query / HyDE)
    cache       -> exact / semantic hit returns immediately                   (cache.py, M7)
    retrieve    -> vector + rerank, ACL-filtered, active copies preferred     (retrieval.py, M3)
    refuse?     -> nothing relevant enough: fixed refusal, no LLM call
    generate    -> streamed from the provider chain (Ollama -> hosted -> Bedrock) (providers.py, M7)
    check       -> citation self-check                                        (citations.py, M4)
    record      -> query_log row (latency, tokens, cost, quality) + cache write

It's an async generator of (event, data) pairs. /ask/stream forwards them as Server-Sent Events; /ask collects
them into one JSON response. Same logic, two transports.
"""

import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import asdict

import numpy as np

from . import router
from .auth import User
from .cache import AnswerCache
from .citations import REFUSAL, check_citations
from .llm import build_prompt
from .providers import ProviderChain, Usage, cost_usd
from .querylog import log_query
from .retrieval import RERANK_MODES, Hit, search

SUPERSEDED_NOTE = ("{n} of the sources {verb} from documents that are no longer in force "
                   "(the 2016 KYC Master Direction family was repealed on 28 Nov 2025). Prefer the active sources.")


def _sources(hits: list[Hit], cited: set[int]) -> list[dict]:
    return [{"id": f"S{i}", "cited": i in cited, **{k: v for k, v in asdict(h).items() if k != "parent_text"},
             "text": h.parent_text} for i, h in enumerate(hits, 1)]


def _cited(answer: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[S(\d+)\]", answer)}


def _normalise(v: np.ndarray) -> list[float]:
    return (v / (np.linalg.norm(v) or 1.0)).tolist()


async def run(app, *, question: str, history: list[dict], entity: str | None, include_superseded: bool,
              k: int, mode: str | None, user: User) -> AsyncIterator[tuple[str, object]]:
    s = app.state.settings
    chain: ProviderChain = app.state.chain
    t0 = time.perf_counter()
    log_row: dict = {"user_id": user.id, "question": question, "cache": "miss", "refused": False}

    # ---- 1. understand the question (M5) ----
    standalone = question
    followup = bool(history) and router.looks_like_followup(question)
    if not followup:
        history = []                            # a self-contained question: answer (and cache) it on its own
    if followup and s.condense_followups:
        try:
            prompt = router.CONDENSE_PROMPT.format(history=router.format_history(history), question=question)
            standalone = router.clean_line((await chain.complete([{"role": "user", "content": prompt}], 0.0)).text)
        except Exception:
            standalone = question               # rewriting is a nice-to-have: never fail the request on it
    entity = entity or user.entity_type or router.detect_entity(standalone)
    prefer_active = not router.wants_history(standalone)
    mode = mode or (s.retrieval_mode if app.state.reranker_ready else "vector")
    yield "meta", {"standalone_question": standalone, "entity": entity, "mode": mode,
                   "prefer_active": prefer_active}
    log_row.update(standalone_question=standalone if standalone != question else None, entity=entity, mode=mode)

    # ---- 2. embed (+ optional expansion) ----
    from ingest.embedder import embed, to_pgvector

    texts = [standalone]
    if s.query_expansion in ("multi_query", "hyde"):
        try:
            tpl = router.MULTI_QUERY_PROMPT if s.query_expansion == "multi_query" else router.HYDE_PROMPT
            extra = (await chain.complete([{"role": "user", "content": tpl.format(question=standalone)}], 0.3)).text
            texts += [router.clean_line(x) for x in extra.splitlines() if x.strip()][:2]
        except Exception:
            pass
    vecs = await asyncio.to_thread(embed, texts, 8, s.embed_device)
    qvec = _normalise(np.mean(np.asarray(vecs, dtype=np.float32), axis=0))   # one vector for all phrasings

    # ---- 3. cache (follow-ups excluded: their meaning depends on the conversation) ----
    cache = AnswerCache(app.state.redis, s.cache_ttl_s, s.semantic_cache_threshold)
    acl = ",".join(sorted(user.access_levels))
    scope = f"{entity}|{include_superseded}|{mode}|{k}|{acl}|{app.state.corpus_version}"
    if not history:
        cached, kind = await cache.get(standalone, scope, qvec)
        if cached:
            total = round((time.perf_counter() - t0) * 1000)
            yield "sources", cached["sources"]
            yield "token", cached["answer"]
            timings = {"retrieval": 0, "first_token": total, "total": total}
            yield "done", {**cached["done"], "cache": kind, "timings_ms": timings, "cost_usd": 0.0}
            log_row.update(cache=kind, refused=cached["answer"] == REFUSAL, total_ms=total, first_token_ms=total,
                           citation_ok=cached["done"]["citation_check"]["ok"])
            await log_query(app.state.db, **log_row)
            return

    # ---- 4. retrieve ----
    reranker = None
    if mode in RERANK_MODES:
        from .rerank import rerank

        def reranker(q: str, ps: list[str]) -> list[float]:
            return rerank(q, ps, s.embed_device)

    hits = await search(app.state.db, standalone, to_pgvector(qvec), mode=mode, k=k, entity=entity,
                        include_superseded=include_superseded, reranker=reranker,
                        access_levels=user.access_levels, prefer_active=prefer_active)
    top = hits[0].score if hits else None
    if mode in RERANK_MODES and hits and hits[0].score < s.min_rerank_score:
        hits = []                               # nothing relevant enough: refuse instead of improvising
    t_retrieval = time.perf_counter()
    yield "sources", _sources(hits, set())
    log_row.update(top_score=top, retrieval_ms=round((t_retrieval - t0) * 1000))

    # ---- 5. generate ----
    answer, first_token_ms, usage, used = "", None, Usage(), {"provider": None, "model": None}
    if not hits:
        answer = REFUSAL
        first_token_ms = round((time.perf_counter() - t0) * 1000)
        yield "token", answer
    else:
        messages = build_prompt(question if not history else standalone, hits, history)
        async for piece in chain.stream(messages, usage, used):
            if first_token_ms is None:
                first_token_ms = round((time.perf_counter() - t0) * 1000)
            answer += piece
            yield "token", piece

    # ---- 6. check + record ----
    report = check_citations(answer, [h.parent_text for h in hits])
    superseded = sum(h.status != "active" for h in hits)
    notes = []
    if superseded and prefer_active and not report.refused:
        notes.append(SUPERSEDED_NOTE.format(n=superseded, verb="is" if superseded == 1 else "are"))
    cost = cost_usd(s, used["provider"] or "", usage)
    total = round((time.perf_counter() - t0) * 1000)
    done = {"citation_check": asdict(report), "cited": sorted(_cited(answer)), "notes": notes,
            "provider": used["provider"], "model": used["model"], "cache": "miss",
            "usage": asdict(usage), "cost_usd": cost,
            "timings_ms": {"retrieval": log_row["retrieval_ms"], "first_token": first_token_ms, "total": total}}
    yield "done", done
    log_row.update(refused=report.refused, provider=used["provider"], model=used["model"],
                   prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens, cost_usd=cost,
                   first_token_ms=first_token_ms, total_ms=total, citation_ok=report.ok)
    await log_query(app.state.db, **log_row)
    if not history and report.ok:               # only cache answers that passed the citation check
        await cache.put(standalone, scope, qvec, {"answer": answer, "sources": _sources(hits, _cited(answer)),
                                                  "done": {k_: v for k_, v in done.items() if k_ != "timings_ms"}})
