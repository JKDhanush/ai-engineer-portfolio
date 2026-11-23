"""Citation self-check: does each cited sentence actually appear to be supported by the source it cites?

A cheap, deterministic guard that runs on every answer (an LLM-judge does the deeper check in the M6 evals):
  1. every [Sn] must point to a source that exists;
  2. every factual sentence should carry at least one citation;
  3. a cited sentence's key terms (numbers, amounts, content words) should mostly occur in the cited source.
Numbers matter most in compliance ("two years", "₹50,000"): a number in the answer that is in none of the
cited sources is the classic hallucination, so it's checked separately.
"""

import re
from dataclasses import dataclass, field

REFUSAL = "I could not find this in the loaded RBI documents."
STOP = set("""a an the of to in for and or on at by with from as is are be been was were shall should may must can
this that these those it its their there such any all each per under above below than then also not no only
which who whom whose what when where how into within upon about bank banks customer customers""".split())
_CITE = re.compile(r"\[S(\d+)\]")
_NUM = re.compile(r"₹?\d[\d,]*(?:\.\d+)?")
_WORDS = {"one": "1", "two": "2", "three": "3", "five": "5", "six": "6", "eight": "8", "ten": "10", "twelve": "12"}


@dataclass
class CitationReport:
    ok: bool
    invalid_refs: list[int] = field(default_factory=list)
    uncited_sentences: list[str] = field(default_factory=list)
    unsupported_sentences: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    refused: bool = False


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", text.lower())
    return {w[:6] for w in words if w not in STOP}          # crude stemming: first 6 letters


def _numbers(text: str) -> set[str]:
    lowered = text.lower()
    for word, digit in _WORDS.items():
        lowered = re.sub(rf"\b{word}\b", digit, lowered)
    return {n.replace(",", "").replace("₹", "") for n in _NUM.findall(lowered)}


def _sentences(answer: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", answer)
    return [p.strip(" -*•") for p in parts if len(p.strip(" -*•")) > 25]


def check_citations(answer: str, sources: list[str], min_overlap: float = 0.5) -> CitationReport:
    if REFUSAL.lower()[:40] in answer.lower():
        return CitationReport(ok=True, refused=True)
    report = CitationReport(ok=True)
    cited_any = False
    for sent in _sentences(answer):
        refs = [int(n) for n in _CITE.findall(sent)]
        clean = _CITE.sub("", sent)
        if not refs:
            if _terms(clean) and not clean.rstrip().endswith(":"):
                report.uncited_sentences.append(clean.strip())
            continue
        cited_any = True
        valid = [r for r in refs if 1 <= r <= len(sources)]
        report.invalid_refs += [r for r in refs if r not in valid]
        if not valid:
            continue
        support = " ".join(sources[r - 1] for r in valid)
        terms = _terms(clean)
        if terms and len(terms & _terms(support)) / len(terms) < min_overlap:
            report.unsupported_sentences.append(clean.strip())
        missing = _numbers(clean) - _numbers(support) - {str(r) for r in refs}
        report.unsupported_numbers += sorted(missing)
    report.invalid_refs = sorted(set(report.invalid_refs))
    report.ok = cited_any and not (report.invalid_refs or report.unsupported_sentences or report.unsupported_numbers)
    return report
