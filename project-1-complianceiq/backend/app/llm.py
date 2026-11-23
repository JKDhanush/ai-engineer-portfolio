"""Grounded answer generation with a local LLM served by Ollama (http://localhost:11434)."""

import json
from collections.abc import AsyncIterator

import httpx

from .citations import REFUSAL
from .retrieval import Hit

SYSTEM_PROMPT = f"""You are ComplianceIQ, an assistant for compliance officers at Indian banks and NBFCs.
Answer ONLY from the numbered sources provided. Rules:
- Cite every statement with its source number in square brackets, e.g. [S1] or [S2][S3].
- Quote paragraph references exactly as given (e.g. "Para 38(1)").
- Copy numbers, amounts and time limits exactly as written in the sources.
- If a source is marked SUPERSEDED, say so and prefer the ACTIVE source when both cover the point.
- If the sources do not contain the answer, reply exactly: "{REFUSAL}"
- Be concise: a short direct answer first, then key details as bullet points."""


def build_prompt(question: str, hits: list[Hit], history: list[dict] | None = None) -> list[dict]:
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


def _payload(messages: list[dict], model: str, stream: bool) -> dict:
    return {"model": model, "messages": messages, "stream": stream,
            "options": {"temperature": 0.1, "num_ctx": 8192}}


async def generate(question: str, hits: list[Hit], *, base_url: str, model: str, timeout: float,
                   history: list[dict] | None = None) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base_url}/api/chat",
                                 json=_payload(build_prompt(question, hits, history), model, False))
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


async def generate_stream(question: str, hits: list[Hit], *, base_url: str, model: str, timeout: float,
                          history: list[dict] | None = None) -> AsyncIterator[str]:
    """Yield the answer piece by piece as Ollama produces it (newline-delimited JSON chunks)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{base_url}/api/chat",
                                 json=_payload(build_prompt(question, hits, history), model, True)) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if piece := chunk.get("message", {}).get("content"):
                    yield piece
                if chunk.get("done"):
                    break


async def complete(prompt: str, *, base_url: str, model: str, timeout: float = 60.0) -> str:
    """One-shot completion for small helper tasks (query rewriting, LLM-as-judge)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base_url}/api/chat", json=_payload(
            [{"role": "user", "content": prompt}], model, False) | {"options": {"temperature": 0.0, "num_ctx": 8192}})
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


async def ollama_status(base_url: str, model: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            tags = (await client.get(f"{base_url}/api/tags")).json()
        names = {m["name"] for m in tags.get("models", [])}
        return "ok" if model in names or f"{model}:latest" in names else f"model '{model}' not pulled"
    except Exception:
        return "unreachable"
