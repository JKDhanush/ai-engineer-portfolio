"""Generation evaluation (M6): are the ANSWERS right, not just the retrieved paragraphs?

Sends golden questions to the running API (/ask) and measures:

  deterministic (no judge needed)
    refusal accuracy    out-of-scope questions refused, answerable ones answered
    citation pass rate  the API's own citation self-check passed (valid refs, numbers found in sources...)
    cited-source hit    at least one CITED source is a paragraph the golden set marks as relevant
  LLM-as-judge (scored against the golden expected_answer and the cited source text)
    correctness  0 wrong / 1 partly right / 2 fully right
    faithfulness every claim is supported by the cited sources (no hallucination)
    relevance    the answer addresses the question asked

A judge is itself a model and can be wrong, so `--labels` writes a CSV of sampled answers for a human to grade;
evals/judge_agreement.py then reports how often the judge agrees with the human (Cohen's kappa).
Use a STRONGER model as judge than the one answering when you can (JUDGE_PROVIDERS=openai_compat or bedrock).

Run from backend/ with the API running (make api) in another terminal:
    python ../evals/run_generation_eval.py --limit 40            # quick
    python ../evals/run_generation_eval.py --labels 30           # + human-label sheet
    python ../evals/run_generation_eval.py --gate                # exit 1 if below the quality bar (CI / pre-release)
"""

import argparse
import asyncio
import csv
import json
import os
import random
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))

from app.config import get_settings  # noqa: E402
from app.providers import build_chain  # noqa: E402

from metrics import is_relevant, percentile  # noqa: E402

RESULTS = HERE / "results"
GATES = {"refusal_accuracy": 0.85, "citation_pass_rate": 0.80, "cited_source_hit": 0.80, "correct_rate": 0.70,
         "faithfulness": 0.85}

JUDGE_PROMPT = """You are grading an answer from a compliance assistant about Indian RBI KYC/AML rules.

Question: {question}
Reference answer (ground truth): {expected}
Sources the assistant cited:
{sources}

Assistant's answer:
{answer}

Grade strictly. Reply with JSON only, no other text:
{{"correctness": 0|1|2, "faithful": true|false, "relevant": true|false, "reason": "<one short sentence>"}}
- correctness: 2 = same facts as the reference (numbers, periods, conditions), 1 = partly right or missing a key
  condition, 0 = wrong or contradicts the reference.
- faithful: every claim in the answer is supported by the cited sources.
- relevant: the answer addresses the question that was asked."""


def load(limit: int | None, seed: int) -> list[dict]:
    rows = [json.loads(line) for line in (HERE / "golden_set.jsonl").open(encoding="utf-8") if line.strip()]
    pos, neg = [r for r in rows if r["answerable"]], [r for r in rows if not r["answerable"]]
    if limit:                                     # stratified sample: keep the category mix, always all negatives
        random.Random(seed).shuffle(pos)
        pos = sorted(pos[:limit], key=lambda r: r["id"])
    return pos + neg


def parse_judgement(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
        return {"correctness": int(j["correctness"]), "faithful": bool(j["faithful"]),
                "relevant": bool(j["relevant"]), "reason": str(j.get("reason", ""))[:300]}
    except (ValueError, KeyError, TypeError):
        return None


async def judge(chain, q: dict, out: dict) -> dict | None:
    cited = [s for s in out["sources"] if s["cited"]] or out["sources"][:3]
    sources = "\n\n".join(f"[{s['id']}] {s['section_path']}: {s['text'][:1500]}" for s in cited)
    prompt = JUDGE_PROMPT.format(question=q["question"], expected=q["expected_answer"], sources=sources,
                                 answer=out["answer"])
    for _ in range(2):                            # small models sometimes break the JSON format: retry once
        try:
            j = parse_judgement((await chain.complete([{"role": "user", "content": prompt}], 0.0)).text)
        except RuntimeError:
            return None
        if j:
            return j
    return None


async def run(args) -> dict:
    settings = get_settings()
    if os.environ.get("JUDGE_PROVIDERS"):
        settings = settings.model_copy(update={"llm_providers": os.environ["JUDGE_PROVIDERS"]})
    chain = build_chain(settings)
    questions = load(args.limit, args.seed)
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    rows = []
    async with httpx.AsyncClient(base_url=args.api, timeout=300, headers=headers) as client:
        for i, q in enumerate(questions, 1):
            r = await client.post("/ask", json={"question": q["question"], "entity": q["entity"]})
            r.raise_for_status()
            out = r.json()
            refused = out["citation_check"]["refused"]
            row = {"id": q["id"], "category": q["category"], "answerable": q["answerable"], "refused": refused,
                   "question": q["question"], "expected": q["expected_answer"], "answer": out["answer"],
                   "citation_ok": out["citation_check"]["ok"], "cache": out["cache"],
                   "total_ms": out["timings_ms"]["total"], "first_token_ms": out["timings_ms"]["first_token"],
                   "cost_usd": out["cost_usd"]}
            if q["answerable"] and not refused:
                row["cited_hit"] = any(is_relevant(s["doc_id"], s["section_path"], q["relevant"])
                                       for s in out["sources"] if s["cited"])
                if not args.no_judge:
                    row["judge"] = await judge(chain, q, out)
            rows.append(row)
            flag = "refused" if refused else ("ok" if row.get("cited_hit") else "--")
            print(f"[{i}/{len(questions)}] {q['id']:<8} {flag:<8} {row['total_ms']:>6} ms", flush=True)
    return {"rows": rows, "summary": summarize(rows), "judge": settings.llm_providers if not args.no_judge else None}


def rate(values) -> float | None:
    values = list(values)
    return round(sum(values) / len(values), 3) if values else None


def summarize(rows: list[dict]) -> dict:
    pos = [r for r in rows if r["answerable"]]
    neg = [r for r in rows if not r["answerable"]]
    answered = [r for r in pos if not r["refused"]]
    judged = [r["judge"] for r in answered if r.get("judge")]
    times = [r["total_ms"] for r in rows if r["cache"] == "miss"]
    return {
        "questions": len(rows), "answerable": len(pos), "out_of_scope": len(neg),
        "refusal_accuracy": rate([r["refused"] for r in neg] + [not r["refused"] for r in pos]),
        "false_refusals": sum(r["refused"] for r in pos), "missed_refusals": sum(not r["refused"] for r in neg),
        "citation_pass_rate": rate(r["citation_ok"] for r in answered),
        "cited_source_hit": rate(r["cited_hit"] for r in answered),
        "judged": len(judged),
        "correct_rate": rate(j["correctness"] == 2 for j in judged),
        "mean_correctness": round(statistics.mean(j["correctness"] for j in judged) / 2, 3) if judged else None,
        "faithfulness": rate(j["faithful"] for j in judged),
        "relevance": rate(j["relevant"] for j in judged),
        "p50_ms": percentile(times, 50) if times else None, "p95_ms": percentile(times, 95) if times else None,
        "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 4),
    }


def write_report(res: dict, args) -> Path:
    RESULTS.mkdir(exist_ok=True)
    s = res["summary"]
    (RESULTS / "generation_results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    lines = [f"# Generation evaluation ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"{s['answerable']} answerable + {s['out_of_scope']} out-of-scope questions · judge: {res['judge']}", "",
             "| Metric | Value | Gate |", "|---|---|---|"]
    for key in ("refusal_accuracy", "citation_pass_rate", "cited_source_hit", "correct_rate", "mean_correctness",
                "faithfulness", "relevance", "p50_ms", "p95_ms", "total_cost_usd"):
        lines.append(f"| {key} | {s[key]} | {GATES.get(key, '')} |")
    lines += ["", f"False refusals: {s['false_refusals']} · missed refusals: {s['missed_refusals']}", "",
              "## Lowest-scoring answers", ""]
    worst = sorted((r for r in res["rows"] if r.get("judge")), key=lambda r: r["judge"]["correctness"])[:10]
    for r in worst:
        lines.append(f"- **{r['id']}** ({r['judge']['correctness']}/2) {r['question']}  \n"
                     f"  judge: {r['judge']['reason']}")
    path = RESULTS / "generation_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.labels:
        sample = [r for r in res["rows"] if r.get("judge")]
        random.Random(args.seed).shuffle(sample)
        with (RESULTS / "human_labels.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "question", "expected", "answer", "judge_correctness", "human_correctness"])
            for r in sample[:args.labels]:
                w.writerow([r["id"], r["question"], r["expected"], r["answer"], r["judge"]["correctness"], ""])
    return path


def gate(summary: dict) -> list[str]:
    return [f"{k} {summary[k]} < {v}" for k, v in GATES.items() if summary.get(k) is not None and summary[k] < v]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token", help="JWT if the API has AUTH_REQUIRED=true")
    ap.add_argument("--limit", type=int, help="sample N answerable questions (all out-of-scope ones always run)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-judge", action="store_true", help="deterministic metrics only (fast, free)")
    ap.add_argument("--labels", type=int, default=0, help="write N judged answers to human_labels.csv")
    ap.add_argument("--gate", action="store_true", help="exit 1 if any metric is below its gate")
    args = ap.parse_args()
    res = asyncio.run(run(args))
    print(f"\nReport: {write_report(res, args)}")
    print(json.dumps(res["summary"], indent=2))
    if args.gate and (failed := gate(res["summary"])):
        print("QUALITY GATE FAILED:\n  " + "\n  ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
