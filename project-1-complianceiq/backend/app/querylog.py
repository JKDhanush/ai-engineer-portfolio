"""Query log (M7): one row per question in Postgres, the source for cost / latency / quality stats."""

import asyncpg

FIELDS = ("user_id", "question", "standalone_question", "entity", "mode", "cache", "refused", "top_score",
          "provider", "model", "prompt_tokens", "completion_tokens", "cost_usd", "retrieval_ms", "first_token_ms",
          "total_ms", "citation_ok")

INSERT = f"INSERT INTO query_log ({', '.join(FIELDS)}) VALUES ({', '.join(f'${i}' for i in range(1, len(FIELDS) + 1))})"

STATS = """
SELECT count(*)                                                    AS queries,
       avg((cache <> 'miss')::int)                                 AS cache_hit_rate,
       avg(refused::int)                                           AS refusal_rate,
       avg(citation_ok::int) FILTER (WHERE NOT refused)            AS citation_ok_rate,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY total_ms)      AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms)      AS p95_ms,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY first_token_ms) AS p50_first_token_ms,
       sum(cost_usd)                                               AS total_cost_usd,
       avg(cost_usd)                                               AS avg_cost_usd,
       sum(prompt_tokens + completion_tokens)                      AS tokens
FROM query_log WHERE created_at > now() - make_interval(hours => $1)"""


DEFAULTS = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}   # NOT NULL columns


async def log_query(pool: asyncpg.Pool, **row) -> None:
    row = DEFAULTS | {k: v for k, v in row.items() if v is not None}
    try:
        async with pool.acquire() as conn:
            await conn.execute(INSERT, *[row.get(f) for f in FIELDS])
    except Exception:
        pass   # logging must never fail a user request


async def stats(pool: asyncpg.Pool, hours: int = 24) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(STATS, hours)
        by_provider = await conn.fetch(
            "SELECT coalesce(provider, 'cache/refusal') AS provider, count(*) AS n, sum(cost_usd) AS cost_usd "
            "FROM query_log WHERE created_at > now() - make_interval(hours => $1) GROUP BY 1 ORDER BY 2 DESC", hours)
    out = {k: (float(v) if v is not None and not isinstance(v, int) else v) for k, v in dict(row).items()}
    out["by_provider"] = [{**dict(r), "cost_usd": float(r["cost_usd"] or 0)} for r in by_provider]
    out["window_hours"] = hours
    return out
