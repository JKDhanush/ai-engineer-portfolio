"""Load test (M10): how many users can one server handle, and where does it break?

Sends real golden-set questions to /ask/stream at increasing concurrency (simulated users asking at the same
time) and measures, per level:
  - time to first word (what a user feels) and full-answer latency: p50 / p95 / max
  - throughput (answers per minute) and errors (429 = rate limited, 5xx / timeouts = overloaded)
  - cache share: `--repeat 0.3` makes 30% of questions repeats, like real traffic

Run against a server with the API's own per-user limit switched off, or you'll mostly measure the limiter:
    RATE_LIMIT_PER_MINUTE=0 make api                       # terminal 1
    make load-test                                         # terminal 2 (levels 1,2,4,8)
    python ../evals/load_test.py --url https://<ip>.sslip.io/api --levels 1,4,8 --per-level 16
Writes evals/results/load_test.md.
"""

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from metrics import percentile  # noqa: E402


async def one(client: httpx.AsyncClient, question: str) -> dict:
    t0 = time.perf_counter()
    first = None
    cache, status = "miss", 0
    try:
        async with client.stream("POST", "/ask/stream", json={"question": question}) as r:
            status = r.status_code
            if status != 200:
                await r.aread()
                return {"status": status, "total": time.perf_counter() - t0}
            event = None
            async for line in r.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    if event == "token" and first is None:
                        first = time.perf_counter() - t0
                    elif event == "done":
                        cache = json.loads(line[6:]).get("cache", "miss")
                    elif event == "error":
                        status = 503
    except (httpx.TimeoutException, httpx.TransportError):
        status = 599
    return {"status": status, "first": first, "total": time.perf_counter() - t0, "cache": cache}


async def level(url: str, users: int, n: int, questions: list[str], repeat: float, token: str | None) -> dict:
    seen: list[str] = []
    batch = []
    for _ in range(n):
        if seen and random.random() < repeat:
            batch.append(random.choice(seen))
        else:
            q = questions.pop() if questions else random.choice(seen)
            seen.append(q)
            batch.append(q)
    queue: asyncio.Queue = asyncio.Queue()
    for q in batch:
        queue.put_nowait(q)
    results: list[dict] = []
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def user(client):
        while not queue.empty():
            results.append(await one(client, queue.get_nowait()))

    t0 = time.perf_counter()
    async with httpx.AsyncClient(base_url=url, timeout=300, headers=headers) as client:
        await asyncio.gather(*(user(client) for _ in range(users)))
    wall = time.perf_counter() - t0
    ok = [r for r in results if r["status"] == 200]
    firsts = [r["first"] for r in ok if r.get("first") is not None]
    totals = [r["total"] for r in ok]
    return {
        "users": users, "requests": len(results), "ok": len(ok),
        "rate_limited": sum(r["status"] == 429 for r in results),
        "errors": sum(r["status"] not in (200, 429) for r in results),
        "cache_hits": sum(r.get("cache") != "miss" for r in ok),
        "first_p50": percentile(firsts, 50), "first_p95": percentile(firsts, 95),
        "total_p50": percentile(totals, 50), "total_p95": percentile(totals, 95), "total_max": max(totals, default=0),
        "answers_per_min": round(len(ok) / wall * 60, 1), "wall_s": round(wall, 1),
    }


def report(rows: list[dict], url: str) -> str:
    lines = [f"# Load test ({datetime.now():%Y-%m-%d %H:%M}) against {url}", "",
             "| Users | Requests | OK | 429 | Errors | Cache hits | First word p50 / p95 | Full answer p50 / p95 / max "
             "| Answers/min |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['users']} | {r['requests']} | {r['ok']} | {r['rate_limited']} | {r['errors']} | "
                     f"{r['cache_hits']} | {r['first_p50']:.1f} s / {r['first_p95']:.1f} s | "
                     f"{r['total_p50']:.1f} / {r['total_p95']:.1f} / {r['total_max']:.1f} s | {r['answers_per_min']} |")
    lines += ["", "Read it like this: throughput stops growing when the bottleneck (GPU / CPU models, or the LLM "
              "provider's rate limit) is saturated; after that, extra users only add waiting time (p95 grows)."]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--levels", default="1,2,4,8", help="concurrent users per step")
    ap.add_argument("--per-level", type=int, default=12, help="requests per step")
    ap.add_argument("--repeat", type=float, default=0.3, help="share of repeated questions (cache hits)")
    ap.add_argument("--token", help="JWT if AUTH_REQUIRED=true")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    random.seed(args.seed)
    golden = [json.loads(line) for line in (HERE / "golden_set.jsonl").open(encoding="utf-8") if line.strip()]
    questions = [q["question"] for q in golden if q["answerable"]]
    random.shuffle(questions)
    rows = []
    for users in [int(x) for x in args.levels.split(",")]:
        print(f"{users} concurrent user(s), {args.per_level} requests...", flush=True)
        rows.append(asyncio.run(level(args.url, users, args.per_level, questions, args.repeat, args.token)))
        print(json.dumps(rows[-1]), flush=True)
    out = HERE / "results" / "load_test.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report(rows, args.url), encoding="utf-8")
    print(f"\n{out.read_text()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
