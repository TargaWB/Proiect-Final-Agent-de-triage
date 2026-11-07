"""Fabrica de modele (LangChain) si contabilizarea consumului (FinOps).
Groq free tier pentru productie, Ollama local pentru modelele mici si LoRA."""

import os

from agent.config import GROQ_MODEL, LLM_PROVIDER, LOCAL_PRICE, OLLAMA_BASE_URL, OLLAMA_MODEL, PRICING
from agent.schemas import LLMUsage


def default_spec() -> tuple[str, str]:
    return LLM_PROVIDER, (GROQ_MODEL if LLM_PROVIDER == "groq" else OLLAMA_MODEL)


def get_chat_model(provider: str | None = None, model: str | None = None, temperature: float = 0.1):
    """Model de chat care raspunde in mod JSON. `provider` = groq | ollama."""
    provider = provider or LLM_PROVIDER
    if provider == "groq":
        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError("GROQ_API_KEY nu e setat (cheie gratuita pe console.groq.com).")
        from langchain_groq import ChatGroq
        name = model or GROQ_MODEL
        kwargs = {"reasoning_effort": "low"} if name.startswith("openai/gpt-oss") else {}
        return ChatGroq(model=name, temperature=temperature, max_retries=2, **kwargs).bind(
            response_format={"type": "json_object"})
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model or OLLAMA_MODEL, base_url=OLLAMA_BASE_URL,
                          temperature=temperature, format="json", num_ctx=4096)
    raise ValueError(f"Provider necunoscut: {provider}")


def cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price_in, price_out = LOCAL_PRICE if provider == "ollama" else PRICING.get(model, (0.0, 0.0))
    return round((prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000, 8)


def usage_from(message, provider: str, model: str, purpose: str, latency_ms: float) -> LLMUsage:
    meta = getattr(message, "usage_metadata", None) or {}
    p, c = int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0))
    return LLMUsage(provider=provider, model=model, purpose=purpose, prompt_tokens=p,
                    completion_tokens=c, latency_ms=round(latency_ms, 1),
                    cost_usd=cost_usd(provider, model, p, c))
