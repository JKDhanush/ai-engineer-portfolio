"""How far can we trust the LLM judge? Compare its grades with a human's (M6).

1. python ../evals/run_generation_eval.py --labels 30     -> evals/results/human_labels.csv
2. Open the CSV, read each answer against the expected answer, fill human_correctness with 0, 1 or 2.
3. python ../evals/judge_agreement.py

Reports exact agreement and Cohen's kappa (agreement corrected for chance: >0.6 substantial, >0.8 near perfect).
If kappa is low, fix the judge (stronger model, clearer rubric) before trusting its numbers.
"""

import csv
import sys
from collections import Counter
from pathlib import Path

PATH = Path(__file__).resolve().parent / "results" / "human_labels.csv"


def cohens_kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def main() -> int:
    rows = [r for r in csv.DictReader(PATH.open(encoding="utf-8")) if r["human_correctness"].strip()]
    if not rows:
        print(f"No human grades yet: fill the human_correctness column in {PATH}")
        return 1
    judge = [int(r["judge_correctness"]) for r in rows]
    human = [int(r["human_correctness"]) for r in rows]
    exact = sum(j == h for j, h in zip(judge, human, strict=True)) / len(rows)
    kappa = cohens_kappa(judge, human)
    print(f"{len(rows)} labelled answers · exact agreement {exact:.0%} · Cohen's kappa {kappa:.2f}")
    for r, j, h in zip(rows, judge, human, strict=True):
        if j != h:
            print(f"  {r['id']}: judge {j} vs human {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
