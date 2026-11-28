"""LLM provider abstraction with fallback (M7).

The rest of the app talks to `ProviderChain`, never to a vendor SDK, so swapping or adding a model is a
config change, not a code change:

    LLM_PROVIDERS=ollama                      local only (default, ₹0)
    LLM_PROVIDERS=ollama,openai_compat        local first; a hosted API if Ollama is down or times out
    LLM_PROVIDERS=bedrock,ollama              AWS Bedrock first (deployment), local as fallback

`openai_compat` works with any OpenAI-style chat API: Groq, Gemini's OpenAI endpoint, OpenRouter, Azure
OpenAI, vLLM... Every call reports token usage, so the pipeline can compute cost per query.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("complianceiq.providers")


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)


class Provider:
    name = "base"

    def __init__(self, model: str, timeout: float):
        self.model, self.timeout = model, timeout

    async def complete(self, messages: list[dict], temperature: float = 0.1) -> Completion:
        raise NotImplementedError

    async def stream(self, messages: list[dict], usage: Usage, temperature: float = 0.1) -> AsyncIterator[str]:
        """Yield text pieces; fill `usage` in place when the provider reports it at the end."""
        result = await self.complete(messages, temperature)   # default: no streaming support -> one chunk
        usage.prompt_tokens, usage.completion_tokens = result.usage.prompt_tokens, result.usage.completion_tokens
        yield result.text


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model: str, timeout: float, base_url: str):
        super().__init__(model, timeout)
        self.base_url = base_url

    def _payload(self, messages, stream, temperature):
        return {"model": self.model, "messages": messages, "stream": stream,
                "options": {"temperature": temperature, "num_ctx": 8192}}

    async def complete(self, messages, temperature=0.1):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=self._payload(messages, False, temperature))
            r.raise_for_status()
            data = r.json()
        return Completion(data["message"]["content"].strip(), self.name, self.model,
                          Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0)))

    async def stream(self, messages, usage, temperature=0.1):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat",
                                     json=self._payload(messages, True, temperature)) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if piece := chunk.get("message", {}).get("content"):
                        yield piece
                    if chunk.get("done"):
                        usage.prompt_tokens = chunk.get("prompt_eval_count", 0)
                        usage.completion_tokens = chunk.get("eval_count", 0)
                        break

    async def status(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                tags = (await client.get(f"{self.base_url}/api/tags")).json()
            names = {m["name"] for m in tags.get("models", [])}
            return "ok" if self.model in names or f"{self.model}:latest" in names else f"'{self.model}' not pulled"
        except Exception:
            return "unreachable"


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(self, model: str, timeout: float, base_url: str, api_key: str):
        super().__init__(model, timeout)
        self.base_url, self.api_key = base_url.rstrip("/"), api_key

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    async def complete(self, messages, temperature=0.1):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/chat/completions", headers=self._headers(),
                                  json={"model": self.model, "messages": messages, "temperature": temperature})
            r.raise_for_status()
            data = r.json()
        u = data.get("usage") or {}
        return Completion(data["choices"][0]["message"]["content"].strip(), self.name, self.model,
                          Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)))

    async def stream(self, messages, usage, temperature=0.1):
        body = {"model": self.model, "messages": messages, "temperature": temperature, "stream": True,
                "stream_options": {"include_usage": True}}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(),
                                     json=body) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])
                    if chunk.get("usage"):
                        usage.prompt_tokens = chunk["usage"].get("prompt_tokens", 0)
                        usage.completion_tokens = chunk["usage"].get("completion_tokens", 0)
                    for choice in chunk.get("choices", []):
                        if piece := (choice.get("delta") or {}).get("content"):
                            yield piece


class BedrockProvider(Provider):
    """Amazon Bedrock via the Converse API (boto3 is imported only if this provider is configured)."""

    name = "bedrock"

    def __init__(self, model: str, timeout: float, region: str):
        super().__init__(model, timeout)
        self.region = region

    async def complete(self, messages, temperature=0.1):
        import boto3  # optional dependency: `uv pip install boto3` when deploying with Bedrock

        system = [{"text": m["content"]} for m in messages if m["role"] == "system"]
        convo = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages if m["role"] != "system"]
        client = boto3.client("bedrock-runtime", region_name=self.region)

        def call():
            return client.converse(modelId=self.model, system=system, messages=convo,
                                   inferenceConfig={"temperature": temperature, "maxTokens": 1024})

        resp = await asyncio.wait_for(asyncio.to_thread(call), timeout=self.timeout)
        u = resp.get("usage", {})
        text = "".join(part.get("text", "") for part in resp["output"]["message"]["content"])
        return Completion(text.strip(), self.name, self.model, Usage(u.get("inputTokens", 0), u.get("outputTokens", 0)))


class ProviderChain:
    """Try providers in order; fall back to the next on any error (timeout, 5xx, connection refused)."""

    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError("at least one LLM provider is required")
        self.providers = providers

    @property
    def primary(self) -> Provider:
        return self.providers[0]

    async def complete(self, messages: list[dict], temperature: float = 0.1) -> Completion:
        errors = []
        for p in self.providers:
            try:
                return await p.complete(messages, temperature)
            except Exception as exc:
                log.warning("provider %s failed: %s", p.name, exc)
                errors.append(f"{p.name}: {type(exc).__name__}")
        raise RuntimeError("all LLM providers failed: " + "; ".join(errors))

    async def stream(self, messages: list[dict], usage: Usage, used: dict) -> AsyncIterator[str]:
        """Stream from the first provider that works. Falls back only if nothing was sent yet:
        switching models mid-answer would produce a garbled reply."""
        errors = []
        for p in self.providers:
            sent = False
            try:
                async for piece in p.stream(messages, usage):
                    if not sent:
                        used.update(provider=p.name, model=p.model)
                        sent = True
                    yield piece
                return
            except Exception as exc:
                if sent:
                    raise
                log.warning("provider %s failed before streaming: %s", p.name, exc)
                errors.append(f"{p.name}: {type(exc).__name__}")
        raise RuntimeError("all LLM providers failed: " + "; ".join(errors))


def build_chain(settings) -> ProviderChain:
    providers: list[Provider] = []
    for name in [n.strip() for n in settings.llm_providers.split(",") if n.strip()]:
        if name == "ollama":
            providers.append(OllamaProvider(settings.llm_model, settings.llm_timeout_s, settings.ollama_url))
        elif name == "openai_compat" and settings.openai_compat_api_key:
            providers.append(OpenAICompatProvider(settings.openai_compat_model, settings.llm_timeout_s,
                                                  settings.openai_compat_base_url, settings.openai_compat_api_key))
        elif name == "bedrock":
            providers.append(BedrockProvider(settings.bedrock_model_id, settings.llm_timeout_s, settings.aws_region))
        else:
            log.warning("LLM provider '%s' skipped (unknown or missing API key)", name)
    return ProviderChain(providers)


def cost_usd(settings, provider: str, usage: Usage) -> float:
    """Price per 1M tokens, from settings (local models cost nothing per token)."""
    prices = json.loads(settings.llm_prices_json).get(provider, [0.0, 0.0])
    return round((usage.prompt_tokens * prices[0] + usage.completion_tokens * prices[1]) / 1_000_000, 6)
