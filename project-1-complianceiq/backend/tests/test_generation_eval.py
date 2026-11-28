"""Tests for the generation-eval helpers: judge output parsing, summary maths, quality gate, Cohen's kappa."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals"))

from judge_agreement import cohens_kappa  # noqa: E402
from run_generation_eval import gate, parse_judgement, summarize  # noqa: E402


def test_parse_judgement_tolerates_chatter_around_json():
    j = parse_judgement('Sure! {"correctness": 2, "faithful": true, "relevant": true, "reason": "matches"} Done.')
    assert j == {"correctness": 2, "faithful": True, "relevant": True, "reason": "matches"}
    assert parse_judgement("I think it's correct") is None
    assert parse_judgement('{"correctness": "two"}') is None


def row(answerable, refused, ok=True, hit=True, correctness=2):
    r = {"answerable": answerable, "refused": refused, "citation_ok": ok, "cache": "miss", "total_ms": 100,
         "cost_usd": 0.001}
    if answerable and not refused:
        r |= {"cited_hit": hit, "judge": {"correctness": correctness, "faithful": True, "relevant": True}}
    return r


def test_summary_and_gate():
    rows = [row(True, False), row(True, False, ok=False, correctness=1), row(True, True), row(False, True),
            row(False, False)]
    s = summarize(rows)
    assert s["refusal_accuracy"] == 0.6 and s["false_refusals"] == 1 and s["missed_refusals"] == 1
    assert s["citation_pass_rate"] == 0.5 and s["correct_rate"] == 0.5 and s["mean_correctness"] == 0.75
    assert any(f.startswith("refusal_accuracy") for f in gate(s))


def test_kappa():
    assert cohens_kappa([2, 1, 0, 2], [2, 1, 0, 2]) == 1.0
    assert cohens_kappa([2, 2, 2, 2], [2, 2, 2, 1]) == 0.0      # agreement no better than chance
