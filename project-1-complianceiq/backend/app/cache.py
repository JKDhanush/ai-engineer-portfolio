"""Answer cache in Redis (M7): exact match first, then semantic match.

Compliance teams ask the same questions over and over ("re-KYC period for high-risk customers?"). A cache hit
skips retrieval AND the LLM: ~5 ms instead of seconds, and ₹0 instead of a paid API call.

- Exact: key = hash of the normalised question + filters + corpus version.
- Semantic: the question's embedding is compared with recently cached questions; cosine >= 0.95 means "same
  question in different words" ("how often re-KYC high risk" ~ "periodic updation for high-risk customers").
- The corpus version (number of chunks + last ingest time) is part of every key, so re-ingesting documents
  automatically invalidates stale answers.
- Follow-up questions (with chat history) are not cached: their meaning depends on the conversation.
"""

import hashlib
import json
import re

import numpy as np
from redis.asyncio import Redis

INDEX = "cache:semantic"      # Redis hash: key -> JSON {vec, scope}
MAX_SEMANTIC = 2000           # entries scanned for a semantic match (kept small: it's a linear scan)


def normalise(question: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9₹]+", " ", question.lower()).split())   # "Re-KYC?" == "re kyc"


def make_key(question: str, scope: str) -> str:
    return "cache:answer:" + hashlib.sha256(f"{scope}|{normalise(question)}".encode()).hexdigest()


class AnswerCache:
    def __init__(self, redis: Redis, ttl_s: int, threshold: float):
        self.redis, self.ttl, self.threshold = redis, ttl_s, threshold

    async def get(self, question: str, scope: str, vec: list[float] | None) -> tuple[dict | None, str]:
        try:
            if raw := await self.redis.get(make_key(question, scope)):
                return json.loads(raw), "exact"
            if vec is None:
                return None, "miss"
            entries = await self.redis.hgetall(INDEX)
            best_key, best = None, 0.0
            q = np.asarray(vec, dtype=np.float32)
            for key, meta in list(entries.items())[-MAX_SEMANTIC:]:
                m = json.loads(meta)
                if m["scope"] != scope:
                    continue
                sim = float(np.dot(q, np.asarray(m["vec"], dtype=np.float32)))   # vectors are normalised
                if sim > best:
                    best_key, best = key, sim
            if best_key and best >= self.threshold and (raw := await self.redis.get(best_key)):
                return json.loads(raw), "semantic"
        except Exception:
            pass   # the cache must never break a request: on any Redis problem, just answer normally
        return None, "miss"

    async def put(self, question: str, scope: str, vec: list[float] | None, payload: dict) -> None:
        try:
            key = make_key(question, scope)
            await self.redis.set(key, json.dumps(payload, ensure_ascii=False, default=str), ex=self.ttl)
            if vec is not None:
                await self.redis.hset(INDEX, key, json.dumps({"vec": [round(x, 5) for x in vec], "scope": scope}))
        except Exception:
            pass
