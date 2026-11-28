"""Prompt construction for grounded answers. Calling a model is app/providers.py's job."""

from .citations import REFUSAL
from .retrieval import Hit

SYSTEM_PROMPT = f"""You are ComplianceIQ, an assistant for compliance officers at Indian banks and NBFCs.
Answer ONLY from the numbered sources provided. Rules:
- EVERY sentence and EVERY bullet must end with the number of the source it comes from, e.g. [S2] or [S2][S3].
  An answer without [S..] citations is invalid, even a one-line answer.
- Quote paragraph references exactly as given (e.g. "Para 38(1)").
- Copy numbers, amounts and time limits exactly as written in the sources.
- Prefer ACTIVE sources. Use a SUPERSEDED source only if no active source covers the point, and say it is superseded.
- If the sources do not contain the answer, reply exactly: "{REFUSAL}"
- Be concise: one direct sentence first, then up to 4 bullet points with key details.

Example of the required format:
Question: What is the limit for a small account?
Answer: A small account can hold an aggregate balance of up to ₹50,000 at any time [S2].
- Total credits in a financial year cannot exceed ₹1 lakh [S2].
- It can be opened without officially valid documents, subject to conditions [S3]."""


def build_prompt(question: str, hits: list[Hit], history: list[dict] | None = None) -> list[dict]:
    """System rules + numbered sources + question (+ the last few chat turns for follow-ups)."""
    blocks = []
    for i, h in enumerate(hits, 1):
        status = "ACTIVE" if h.status == "active" else f"SUPERSEDED ({h.status_reason})"
        blocks.append(f"[S{i}] {h.title} | {h.circular_no} | issued {h.issued_on} | {h.section_path} | "
                      f"pages {h.pages} | {status}\n{h.parent_text}")
    user = "Sources:\n\n" + "\n\n---\n\n".join(blocks) + f"\n\nQuestion: {question}\nAnswer:"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-4:]:            # a little conversation context for follow-ups
        messages.append({"role": turn["role"], "content": turn["content"][:1500]})
    messages.append({"role": "user", "content": user})
    return messages
