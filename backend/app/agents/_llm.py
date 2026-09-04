"""LLMProvider abstraction (spec 17).

Three implementations behind one interface:

* :class:`AnthropicProvider` -- ``claude-opus-5`` / ``claude-sonnet-5`` through
  ``client.messages.parse(..., output_format=PydanticModel)``,
  ``thinking={"type": "adaptive"}``, and a cached byte-stable system prompt.
  ``budget_tokens`` is **never** passed: it 400s on Opus 5 and Sonnet 5.
* :class:`GroqProvider` -- the OpenAI-compatible Groq chat-completions endpoint
  with JSON-schema response formatting.
* :class:`FixtureProvider` -- deterministic, offline, no key.  It does *not*
  know the labels; it applies published rules to the artifact content, so an
  offline eval measures a real pipeline.  Every report states which provider
  produced its numbers.

This module MUST NOT import ``app.settlement``, ``app.rails`` or ``app.payments``
(I2), and the CI import-lint fails the build if it ever does.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.attest.canonical import payload_hash
from app.common.errors import LLMOutputRejected, ServiceUnavailable
from app.common.logging import get_logger
from app.config.settings import settings

log = get_logger("agents.llm")

T = TypeVar("T", bound=BaseModel)

# Report E pricing, USD per million tokens (spec 17).
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
GROQ_PRICING_DEFAULT = (0.59, 0.79)  # llama-3.3-70b-versatile, published rate


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(slots=True)
class LLMResult:
    parsed: BaseModel
    usage: Usage
    model_id: str
    model_version: str
    provider: str
    latency_ms: int
    prompt_hash: str
    raw_text: str = ""


class LLMProvider(Protocol):
    name: str

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        output_format: type[T],
        model: str,
        purpose: str,
    ) -> LLMResult: ...


def cost_micro_usd(model: str, usage: Usage, provider: str) -> int:
    rate_in, rate_out = PRICING.get(
        model, GROQ_PRICING_DEFAULT if provider == "groq" else (0.0, 0.0)
    )
    billed_in = usage.input_tokens + usage.cache_creation_input_tokens
    # Cached reads bill at 10% on Anthropic; Groq has no prompt cache.
    cached = usage.cache_read_input_tokens * (0.10 if provider == "anthropic" else 1.0)
    usd = ((billed_in + cached) * rate_in + usage.output_tokens * rate_out) / 1_000_000
    return round(usd * 1_000_000)


def compute_prompt_hash(system_prompt: str, user_content: str, model: str) -> str:
    """sha256 of the exact rendered system + user content.  This is what makes a
    decision reproducible six months later."""
    return payload_hash({"model": model, "system": system_prompt, "user": user_content})


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class AnthropicProvider:
    name: str = "anthropic"
    api_key: str = field(default_factory=lambda: settings.AI_API_KEY)
    last_cache_read: int = 0

    def __post_init__(self) -> None:
        import anthropic

        if not self.api_key:
            raise ServiceUnavailable(code="AI_KEY_MISSING", message="AI_API_KEY is not configured.")
        self._client = anthropic.Anthropic(api_key=self.api_key, timeout=settings.AI_TIMEOUT_S)

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        output_format: type[T],
        model: str,
        purpose: str,
    ) -> LLMResult:
        started = time.perf_counter()
        response = self._client.messages.parse(
            model=model,
            max_tokens=settings.AI_MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    # The byte-stable system prompt sits behind the cache breakpoint;
                    # the volatile case payload goes in the user turn after it.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
            output_format=output_format,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_usage = response.usage
        usage = Usage(
            input_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
            output_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(raw_usage, "cache_creation_input_tokens", 0) or 0,
        )
        self.last_cache_read = usage.cache_read_input_tokens
        parsed = response.parsed_output
        if parsed is None:
            raise LLMOutputRejected(message="The model returned no structured output.")
        return LLMResult(
            parsed=parsed,
            usage=usage,
            model_id=model,
            model_version=getattr(response, "model", model),
            provider=self.name,
            latency_ms=latency_ms,
            prompt_hash=compute_prompt_hash(system_prompt, user_content, model),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Groq (OpenAI-compatible)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GroqProvider:
    name: str = "groq"
    api_key: str = field(default_factory=lambda: settings.GROQ_API_KEY or settings.AI_API_KEY)
    base_url: str = field(default_factory=lambda: settings.GROQ_BASE_URL)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ServiceUnavailable(
                code="AI_KEY_MISSING", message="GROQ_API_KEY is not configured."
            )

    def model_for(self, purpose: str) -> str:
        return {
            "clause_evaluation": settings.GROQ_MODEL_VERIFIER,
            "arbitration": settings.GROQ_MODEL_ARBITER,
            "extraction": settings.GROQ_MODEL_EXTRACTION,
        }.get(purpose, settings.GROQ_MODEL_VERIFIER)

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        output_format: type[T],
        model: str,
        purpose: str,
    ) -> LLMResult:
        import httpx

        # Groq models are named differently from the Anthropic ids in settings, so
        # the purpose selects the Groq model rather than passing the Claude id through.
        groq_model = self.model_for(purpose)
        schema = output_format.model_json_schema()
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": groq_model,
                    "temperature": 0,
                    "max_tokens": min(settings.AI_MAX_TOKENS, 8000),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": output_format.__name__,
                            "schema": schema,
                            "strict": False,
                        },
                    },
                },
                timeout=settings.AI_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise ServiceUnavailable(
                code="AI_UNREACHABLE", message="The AI provider could not be reached."
            ) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise ServiceUnavailable(
                code="AI_CALL_FAILED",
                message="The AI provider rejected the request.",
                details={"status": response.status_code, "body": response.text[:300]},
            )
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        try:
            parsed = output_format.model_validate_json(content)
        except Exception as exc:
            raise LLMOutputRejected(
                message="The model output did not satisfy the required schema.",
                details={"error": str(exc)[:300]},
            ) from exc
        raw_usage = body.get("usage", {})
        usage = Usage(
            input_tokens=int(raw_usage.get("prompt_tokens", 0)),
            output_tokens=int(raw_usage.get("completion_tokens", 0)),
        )
        return LLMResult(
            parsed=parsed,
            usage=usage,
            model_id=groq_model,
            model_version=body.get("model", groq_model),
            provider=self.name,
            latency_ms=latency_ms,
            prompt_hash=compute_prompt_hash(system_prompt, user_content, groq_model),
            raw_text=content,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fixture (deterministic, offline)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FixtureProvider:
    """A deterministic local adapter for tests and offline eval runs.

    It receives the same rendered prompt as the real providers and answers from
    the *content* of that prompt, using the published clause rubric.  It is not a
    lookup of expected labels: it has no access to the eval labels, and Suite A
    scores it exactly as it scores a live model.  Its answers are reproducible,
    which is what makes ``make eval`` deterministic without a network.
    """

    name: str = "fixture"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def parse(
        self,
        *,
        system_prompt: str,
        user_content: str,
        output_format: type[T],
        model: str,
        purpose: str,
    ) -> LLMResult:
        from app.agents.fixture_brain import answer

        started = time.perf_counter()
        payload = answer(purpose, user_content, output_format)
        latency_ms = max(1, int((time.perf_counter() - started) * 1000))
        try:
            parsed = output_format.model_validate(payload)
        except Exception as exc:  # pragma: no cover - the brain is schema-aware
            raise LLMOutputRejected(details={"error": str(exc)[:300]}) from exc
        self.calls.append({"purpose": purpose, "model": model})
        approx_in = max(1, len(system_prompt) // 4 + len(user_content) // 4)
        approx_out = max(1, len(json.dumps(payload)) // 4)
        return LLMResult(
            parsed=parsed,
            usage=Usage(input_tokens=approx_in, output_tokens=approx_out),
            model_id=f"fixture:{model}",
            model_version="deterministic-1",
            provider=self.name,
            latency_ms=latency_ms,
            prompt_hash=compute_prompt_hash(system_prompt, user_content, model),
        )


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        effective = settings.ai_effective_provider
        if effective == "anthropic":
            _provider = AnthropicProvider()
        elif effective == "groq":
            _provider = GroqProvider()
        else:
            _provider = FixtureProvider()
        log.info(
            "llm provider selected",
            extra={"configured": settings.AI_PROVIDER, "effective": _provider.name},
        )
    return _provider


def set_provider(provider: LLMProvider | None) -> None:
    global _provider
    _provider = provider


def provider_name() -> str:
    return get_provider().name
