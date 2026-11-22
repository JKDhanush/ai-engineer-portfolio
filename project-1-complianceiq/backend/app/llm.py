"""Grounded answer generation with a local LLM served by Ollama (http://localhost:11434)."""

import re

import httpx

from .retrieval import Hit

SYSTEM_PROMPT = """You are ComplianceIQ, an assistant for compliance officers at Indian banks and NBFCs.
Answer ONLY from the numbered sources provided. Rules:
- Cite every statement with its source number in square brackets, e.g. [S1] or [S2][S3].
- Quote paragraph references exactly as given (e.g. "Para 38(1)").
- If a source is marked SUPERSEDED, say so and prefer the active source when both cover the point.
- If the sources do not contain the answer, reply exactly: "I could not find this in the loaded RBI documents."
- Be concise: a short direct answer first, then key details as bullet points."""


def build_prompt(question: str, hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        status = "ACTIVE" if h.status == "active" else f"SUPERSEDED ({h.status_reason})"
        blocks.append(
            f"[S{i}] {h.title} | {h.circular_no} | issued {h.issued_on} | {h.section_path} | "
            f"pages {h.pages} | {status}\n{h.parent_text}"
        )
    return "Sources:\n\n" + "\n\n---\n\n".join(blocks) + f"\n\nQuestion: {question}\nAnswer:"


async def generate(question: str, hits: list[Hit], *, base_url: str, model: str, timeout: float) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": build_prompt(question, hits)}],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


def cited_sources(answer: str) -> list[int]:
    """Source numbers the answer actually cites: '[S1][S3]' -> [1, 3]."""
    return sorted({int(n) for n in re.findall(r"\[S(\d+)\]", answer)})


async def ollama_status(base_url: str, model: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            tags = (await client.get(f"{base_url}/api/tags")).json()
        names = {m["name"] for m in tags.get("models", [])}
        return "ok" if model in names or f"{model}:latest" in names else f"model '{model}' not pulled"
    except Exception:
        return "unreachable"
