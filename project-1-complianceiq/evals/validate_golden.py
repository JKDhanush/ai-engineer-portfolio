"""Sanity-check the golden set (runs in CI, no database needed): unique ids, required fields, valid
categories, every answerable question has at least one relevant paragraph, negatives have none."""

import json
import sys
from pathlib import Path

REQUIRED = {"id", "question", "category", "difficulty", "entity", "answerable", "expected_answer", "relevant"}
ENTITIES = {None, "commercial_banks", "nbfcs", "small_finance_banks", "urban_coop_banks"}


def validate(path: Path) -> list[str]:
    errors, seen = [], set()
    for n, line in enumerate(path.open(encoding="utf-8"), 1):
        if not line.strip():
            continue
        q = json.loads(line)
        where = f"line {n} ({q.get('id')})"
        if missing := REQUIRED - q.keys():
            errors.append(f"{where}: missing {sorted(missing)}")
            continue
        if q["id"] in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(q["id"])
        if q["entity"] not in ENTITIES:
            errors.append(f"{where}: unknown entity {q['entity']}")
        if q["answerable"] and not q["relevant"]:
            errors.append(f"{where}: answerable but no relevant paragraphs")
        if not q["answerable"] and q["relevant"]:
            errors.append(f"{where}: out-of-scope question has relevant paragraphs")
        if len(q["question"]) < 10:
            errors.append(f"{where}: question too short")
        if q["answerable"] and len(q["expected_answer"] or "") < 2:
            errors.append(f"{where}: answerable question without an expected answer")
    if len(seen) < 150:
        errors.append(f"only {len(seen)} questions (expected >= 150)")
    return errors


if __name__ == "__main__":
    errs = validate(Path(__file__).resolve().parent / "golden_set.jsonl")
    print("\n".join(errs) or "golden set OK")
    sys.exit(1 if errs else 0)
