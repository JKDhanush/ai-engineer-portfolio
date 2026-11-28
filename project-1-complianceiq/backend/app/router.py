"""Query understanding (M5): turn what the user typed into the best search request.

- Entity detection: "...for an NBFC?" -> filter to the NBFC directions (+ rules for all entities).
- Version intent: questions about history ("old", "2016", "repealed", "what changed") keep superseded documents
  in play; otherwise active rules are preferred and superseded ones are flagged.
- Follow-up condensing: "what about NBFCs?" + chat history -> "How often must NBFCs update KYC for
  high-risk customers?" (an LLM rewrite, only when the question looks like a follow-up).
- Query expansion (optional, measured in the ablation): multi-query paraphrases, or HyDE (embed a
  hypothetical answer instead of the question).
"""

import re

ENTITY_PATTERNS = [
    ("nbfcs", r"\bnbfcs?\b|non[- ]banking financial"),
    ("small_finance_banks", r"\bsfbs?\b|small finance banks?"),
    ("urban_coop_banks", r"\bucbs?\b|urban co-?operative banks?"),
    ("commercial_banks", r"\bcommercial banks?\b|\bscheduled commercial\b|\bscbs?\b"),
]
# Deliberately NOT "before" or "old": "KYC before opening an account", "17 years old" aren't about history.
HISTORY = re.compile(r"\b(2016|previous|earlier|repeal\w*|supersed\w*|amend\w*|changed?|history|"
                     r"used to|old rules?|master direction|withdrawn)\b", re.IGNORECASE)
# Not "that"/"such": "documents that are required" is a complete question.
FOLLOWUP = re.compile(r"^(and|what about|how about|also|same for|what if|then|so)\b|\b(it|this|they|them|"
                      r"those|these|above)\b", re.IGNORECASE)


def detect_entity(question: str) -> str | None:
    for entity, pattern in ENTITY_PATTERNS:
        if re.search(pattern, question, re.IGNORECASE):
            return entity
    return None


def wants_history(question: str) -> bool:
    return bool(HISTORY.search(question))


def looks_like_followup(question: str) -> bool:
    """Needs the conversation to make sense: very short ("and NBFCs?") or leans on it ("what about", "it", "they").
    A complete question asked again in the same chat is NOT a follow-up, so it can be served from the cache."""
    return len(question.split()) <= 5 or bool(FOLLOWUP.search(question))


CONDENSE_PROMPT = """Rewrite the user's last message as ONE standalone question about Indian RBI KYC/AML rules,
using the conversation for missing context (subject, entity type, topic). Keep the user's meaning exactly.
Reply with the question only.

Conversation:
{history}

Last message: {question}
Standalone question:"""

MULTI_QUERY_PROMPT = """Write 2 different rephrasings of this question about RBI KYC/AML rules, using the
vocabulary a regulation would use. One per line, no numbering.

Question: {question}"""

HYDE_PROMPT = """Write a 2-3 sentence passage, in the style of an RBI KYC Master Direction paragraph, that
would answer this question. Do not mention that it is hypothetical.

Question: {question}"""


def format_history(history: list[dict]) -> str:
    return "\n".join(f"{t['role']}: {t['content'][:400]}" for t in history[-4:])


def clean_line(text: str) -> str:
    return text.strip().strip('"').strip()
