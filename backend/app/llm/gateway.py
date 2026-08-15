"""The LiteLLM-backed gateway.

The only place in the codebase that imports ``litellm``. Everything else depends on the
``LLMGateway`` protocol in :mod:`app.llm.types`.

Three invariants, all load-bearing:

* **Callers name a task, not a model.** The task→model mapping is configuration, which is
  what lets narratives run on a local model while research runs on a frontier one with no
  code change.
* **``complete`` returns ``None`` on any failure and never raises.** A cycle must not crash
  because a provider is down, rate-limited or unconfigured.
* **LiteLLM types never escape.** A gateway that leaked them would make replacing the router
  a rewrite rather than a swap.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.settings import Settings
from app.llm import observability
from app.llm.breaker import CircuitBreaker
from app.llm.cache import DiskCache, cache_key
from app.llm.providers import resolve_base_url
from app.llm.types import LLMResult, Message

log = logging.getLogger(__name__)

#: Providers LiteLLM has no native prefix for. They are OpenAI-compatible servers, so they
#: are dispatched as ``openai/<model>`` against their own base URL — a routing translation,
#: not an adapter.
_OPENAI_COMPATIBLE: frozenset[str] = frozenset({"llama_cpp", "lemonade"})

#: Providers whose base URL may be overridden but which LiteLLM already knows by name.
_BASE_URL_AWARE: frozenset[str] = frozenset({"ollama", "lm_studio", "openai"})


def _looks_like_rate_limit(exc: BaseException) -> bool:
    """Classify without importing LiteLLM's exception hierarchy.

    Only rate limits trip the breaker — a prompt that fails repeatedly is a bug to fix, not a
    provider to back off from, and one counter for both would hide it.
    """
    if type(exc).__name__ == "RateLimitError":
        return True
    return getattr(exc, "status_code", None) == 429


class LiteLLMGateway:
    """Implements :class:`app.llm.types.LLMGateway`."""

    def __init__(self, settings: Settings, breaker: CircuitBreaker | None = None) -> None:
        self._settings = settings
        self._breaker = breaker or CircuitBreaker(
            threshold=settings.llm_breaker_threshold,
            cooldown_seconds=settings.llm_breaker_cooldown_seconds,
        )
        self._cache = DiskCache(settings.llm_cache_dir, enabled=settings.llm_cache_enabled)
        self._tracing = observability.configure(settings)

    # ── routing ───────────────────────────────────────────────────────────────
    def _dispatch_target(self, model: str) -> tuple[str, str | None]:
        """Translate a configured ``<provider>/<model>`` into what LiteLLM expects.

        Returns ``(litellm_model, api_base)``.
        """
        provider, _, rest = model.partition("/")
        if provider in _OPENAI_COMPATIBLE:
            return f"openai/{rest}", resolve_base_url(self._settings, provider)
        if provider in _BASE_URL_AWARE:
            return model, resolve_base_url(self._settings, provider)
        return model, None

    # ── public API ────────────────────────────────────────────────────────────
    async def complete(
        self,
        *,
        task: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
    ) -> LLMResult | None:
        settings = self._settings
        model = settings.model_for_task(task)
        provider = model.partition("/")[0]

        if self._breaker.is_open(provider):
            log.debug("circuit breaker open for %s; skipping task=%s", provider, task)
            return None

        key = cache_key(task=task, model=model, messages=messages, schema=schema)
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        try:
            import litellm
        except ImportError:
            log.warning("litellm not installed; task=%s cannot run", task)
            return None

        litellm_model, api_base = self._dispatch_target(model)
        trace_id = observability.new_trace_id() if self._tracing else None

        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "timeout": settings.llm_timeout_seconds,
            "num_retries": settings.llm_max_retries,
        }
        if api_base:
            kwargs["api_base"] = api_base
        if schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": task, "schema": schema, "strict": True},
            }
        if trace_id:
            kwargs["metadata"] = {"trace_id": trace_id, "generation_name": task}

        started = time.monotonic()
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            if _looks_like_rate_limit(exc):
                self._breaker.record_rate_limit(provider)
                log.warning("rate limited by %s on task=%s", provider, task)
            else:
                log.warning("LLM call failed (task=%s, model=%s): %s", task, model, exc)
            return None

        self._breaker.record_success(provider)
        latency_ms = int((time.monotonic() - started) * 1000)
        return self._to_result(
            response,
            model=model,
            provider=provider,
            trace_id=trace_id,
            latency_ms=latency_ms,
            schema=schema,
            cache_key_=key,
        )

    # ── result assembly ───────────────────────────────────────────────────────
    def _to_result(
        self,
        response: Any,
        *,
        model: str,
        provider: str,
        trace_id: str | None,
        latency_ms: int,
        schema: dict[str, Any] | None,
        cache_key_: str,
    ) -> LLMResult | None:
        try:
            text = response.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError):
            log.warning("unexpected response shape from %s", provider)
            return None

        usage = getattr(response, "usage", None)
        parsed: Any | None = None
        if schema and text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # The caller asked for structured output and did not get it. Surface as a
                # failure rather than handing back text that will break downstream parsing.
                log.warning("task expected JSON matching a schema; provider returned prose")
                return None

        result = LLMResult(
            text=text,
            model=model,
            provider=provider,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            cost_usd=self._cost_of(response),
            latency_ms=latency_ms,
            trace_id=trace_id,
            cached=False,
            parsed=parsed,
        )
        self._cache.put(cache_key_, result)
        return result

    @staticmethod
    def _cost_of(response: Any) -> float | None:
        """LiteLLM attaches a computed cost for hosted providers; local models have none."""
        hidden = getattr(response, "_hidden_params", None) or {}
        cost = hidden.get("response_cost") if isinstance(hidden, dict) else None
        return float(cost) if isinstance(cost, int | float) else None
