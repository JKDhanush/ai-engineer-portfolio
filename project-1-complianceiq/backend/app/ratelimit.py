"""Fixed-window rate limiting in Redis (M7): at most N requests per user (or IP) per minute.

Protects the GPU / paid API from one client hogging it. INCR is atomic, so this stays correct with many API
replicas. A fixed window is simple; a sliding window or token bucket smooths bursts and is the next step.
"""

import time

from fastapi import HTTPException
from redis.asyncio import Redis


async def check_rate_limit(redis: Redis, identity: str, limit: int) -> None:
    if limit <= 0:
        return
    window = int(time.time() // 60)
    key = f"ratelimit:{identity}:{window}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 70)
    except Exception:
        return   # fail open: a Redis outage shouldn't take the whole API down
    if count > limit:
        raise HTTPException(429, f"rate limit: {limit} requests per minute", headers={"Retry-After": "60"})
