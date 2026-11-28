"""Tests for the Phase B modules: query router, provider fallback, auth, cache keys, rate limit, version handling.
No database, GPU or network needed: fake providers and a tiny in-memory Redis stand in."""

import asyncio
import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app import router
from app.auth import ANONYMOUS, User, create_token, decode_token, hash_password, verify_password
from app.cache import AnswerCache, make_key
from app.providers import Completion, Provider, ProviderChain, Usage, cost_usd
from app.ratelimit import check_rate_limit
from app.retrieval import _group


# ---------------------------------------------------------------- router (M5)
@pytest.mark.parametrize("q,entity", [
    ("What is the re-KYC period for NBFCs?", "nbfcs"),
    ("Does this apply to a non-banking financial company?", "nbfcs"),
    ("CDD rules for small finance banks", "small_finance_banks"),
    ("Are UCBs covered?", "urban_coop_banks"),
    ("periodic updation for high-risk customers", None),
])
def test_detect_entity(q, entity):
    assert router.detect_entity(q) == entity


def test_history_intent_only_for_questions_about_the_past():
    assert router.wants_history("What changed from the 2016 Master Direction?")
    assert router.wants_history("Which circulars were repealed?")
    assert not router.wants_history("Must KYC be done before opening an account?")
    assert not router.wants_history("Can a customer 17 years old open an account?")


def test_followup_detection():
    assert router.looks_like_followup("what about NBFCs?")
    assert router.looks_like_followup("and for small finance banks")
    assert router.looks_like_followup("Does this also apply to them when the account is dormant for a long time?")
    assert not router.looks_like_followup("What is the periodic updation period for high-risk customers?")
    assert not router.looks_like_followup("Which documents are acceptable as proof of address that a bank accepts?")


# ---------------------------------------------------------------- provider chain (M7)
class Fake(Provider):
    def __init__(self, name, fail=False, fail_mid_stream=False):
        super().__init__("m-" + name, 1)
        self.name, self.fail, self.fail_mid = name, fail, fail_mid_stream

    async def complete(self, messages, temperature=0.1):
        if self.fail:
            raise ConnectionError("down")
        return Completion("ok", self.name, self.model, Usage(10, 2))

    async def stream(self, messages, usage, temperature=0.1):
        if self.fail:
            raise ConnectionError("down")
        yield "hello "
        if self.fail_mid:
            raise TimeoutError("cut off")
        yield "world"


async def collect(chain):
    used, out = {}, []
    async for piece in chain.stream([], Usage(), used):
        out.append(piece)
    return "".join(out), used


def test_chain_falls_back_to_next_provider():
    chain = ProviderChain([Fake("local", fail=True), Fake("hosted")])
    assert asyncio.run(chain.complete([])).provider == "hosted"
    assert asyncio.run(collect(chain)) == ("hello world", {"provider": "hosted", "model": "m-hosted"})


def test_chain_does_not_switch_models_mid_answer():
    chain = ProviderChain([Fake("local", fail_mid_stream=True), Fake("hosted")])
    with pytest.raises(TimeoutError):
        asyncio.run(collect(chain))


def test_chain_reports_when_everything_is_down():
    with pytest.raises(RuntimeError, match="all LLM providers failed"):
        asyncio.run(ProviderChain([Fake("a", fail=True), Fake("b", fail=True)]).complete([]))


def test_cost_uses_price_per_million_tokens():
    class S:
        llm_prices_json = '{"bedrock": [0.25, 1.25], "ollama": [0, 0]}'
    assert cost_usd(S, "bedrock", Usage(4000, 400)) == pytest.approx(0.0015)
    assert cost_usd(S, "ollama", Usage(4000, 400)) == 0


# ---------------------------------------------------------------- auth (M7)
def test_password_hashing():
    h = hash_password("correct horse")
    assert h != "correct horse" and verify_password("correct horse", h) and not verify_password("wrong", h)


def test_token_roundtrip_and_tampering():
    user = User("u1", "a@b.com", "admin", ["public", "internal"], "nbfcs")
    token = create_token(user, "secret", 5)
    assert decode_token(token, "secret") == user
    with pytest.raises(HTTPException):
        decode_token(token, "another-secret")       # signed with a different key
    with pytest.raises(HTTPException):
        decode_token(create_token(user, "secret", -1), "secret")   # expired
    assert ANONYMOUS.access_levels == ["public"]


# ---------------------------------------------------------------- cache + rate limit (M7)
class MiniRedis:
    """The handful of Redis commands we use, in memory."""

    def __init__(self):
        self.kv, self.hashes = {}, {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None):
        self.kv[k] = v

    async def hset(self, name, k, v):
        self.hashes.setdefault(name, {})[k] = v

    async def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    async def incr(self, k):
        self.kv[k] = self.kv.get(k, 0) + 1
        return self.kv[k]

    async def expire(self, k, s):
        return True


def test_cache_key_ignores_case_and_punctuation_but_not_scope():
    assert make_key("Re-KYC period?", "nbfcs") == make_key("re kyc period", "nbfcs")
    assert make_key("Re-KYC period?", "nbfcs") != make_key("Re-KYC period?", "commercial_banks")


def test_cache_exact_and_semantic_hits():
    cache = AnswerCache(MiniRedis(), 60, threshold=0.95)
    v = [1.0, 0.0, 0.0]
    asyncio.run(cache.put("re-KYC period for high risk?", "s", v, {"answer": "2 years [S1]"}))
    assert asyncio.run(cache.get("Re-KYC period for high risk", "s", None)) == ({"answer": "2 years [S1]"}, "exact")
    assert asyncio.run(cache.get("how often update KYC, high risk?", "s", [0.99, 0.141, 0.0]))[1] == "semantic"
    assert asyncio.run(cache.get("how often update KYC, high risk?", "s", [0.6, 0.8, 0.0]))[1] == "miss"
    assert asyncio.run(cache.get("re-KYC period for high risk?", "other-scope", v))[1] == "miss"


def test_rate_limit_blocks_after_limit():
    redis = MiniRedis()
    for _ in range(3):
        asyncio.run(check_rate_limit(redis, "u1", 3))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_rate_limit(redis, "u1", 3))
    assert exc.value.status_code == 429
    asyncio.run(check_rate_limit(redis, "u2", 3))   # other users unaffected


# ---------------------------------------------------------------- versions (M5)
RULE = ("The Regulated Entity shall carry out periodic updation at least once in every two years for high-risk "
        "customers, once in every eight years for medium risk customers and once in every ten years for low risk.")


def row(parent, title, status):
    return {"child_id": uuid.uuid4(), "child_text": RULE[:50], "child_header": "", "parent_id": parent,
            "parent_text": RULE, "section_path": "Para 38", "page_start": 1, "page_end": 1, "title": title,
            "circular_no": "X", "issued_on": date(2025, 11, 28), "status": status, "doc_id": title,
            "entity_type": "all", "status_reason": None if status == "active" else "repealed", "pdf_url": None}


def test_active_copy_replaces_superseded_duplicate():
    rows = [row("old", "KYC Master Direction 2016", "superseded"), row("new", "KYC Directions 2025", "active")]
    ranked = [r["child_id"] for r in rows]
    scores = {ranked[0]: 0.9, ranked[1]: 0.8}
    hits = _group(ranked, {r["child_id"]: r for r in rows}, scores, k=5)
    assert [(h.title, h.status, h.score) for h in hits] == [("KYC Directions 2025", "active", 0.9)]
    assert hits[0].also_in == ["KYC Master Direction 2016"]
    kept = _group(ranked, {r["child_id"]: r for r in rows}, scores, k=5, prefer_active=False)
    assert kept[0].title == "KYC Master Direction 2016"     # history questions keep the original ranking


def test_active_documents_ranked_before_superseded_ones():
    other = RULE.replace("periodic updation", "a completely different obligation about wire transfers and records")
    rows = [row("old", "KYC Master Direction 2016", "superseded"), row("new", "NBFC KYC Directions 2025", "active")]
    rows[1]["parent_text"] = other
    ranked = [r["child_id"] for r in rows]
    scores = {ranked[0]: 0.95, ranked[1]: 0.90}
    hits = _group(ranked, {r["child_id"]: r for r in rows}, scores, k=5)
    assert [h.status for h in hits] == ["active", "superseded"]
    assert [h.status for h in _group(ranked, {r["child_id"]: r for r in rows}, scores, k=5,
                                     prefer_active=False)] == ["superseded", "active"]
