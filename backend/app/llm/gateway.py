"""The LiteLLM-backed gateway.

The only place in the codebase that imports ``litellm``. Everything else depends on the
``LLMGateway`` protocol in :mod:`app.llm.types`.

Invariants, all load-bearing:

* **Callers name a task, not a model.** The task→chain mapping is configuration, which is what
  lets narratives run on a local model while research runs on a frontier one with no code
  change.
* **``complete`` returns ``None`` on total failure and never raises.** A cycle must not crash
  because a provider is down, rate-limited, unconfigured or over budget.
* **Every attempt is recorded**, whatever its outcome — that is what makes cost and failure
  modes answerable without an external service.
* **LiteLLM types never escape.** A gateway that leaked them would make replacing the router a
  rewrite rather than a swap.

The chain is walked here rather than delegated to ``litellm.Router`` because Router's failover
happens inside one call and is opaque from outside; this gateway needs a row per attempt. See
the change's ``design.md`` §1.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.settings import Settings
from app.llm import observability, parsing
from app.llm.breaker import CircuitBreaker
from app.llm.budget import DailyBudget
from app.llm.cache import DiskCache, cache_key
from app.llm.recorder import CallRecord, CallRecorder
from app.llm.routing import Chain, Rung, SkipReason, resolve_chain
from app.llm.types import CallStatus, LLMResult, Message, ToolCall

log = logging.getLogger(__name__)

#: Providers LiteLLM has no native prefix for. They are OpenAI-compatible servers, so they
#: are dispatched as ``openai/<model>`` against their own base URL — a routing translation,
#: not an adapter.
_OPENAI_COMPATIBLE: frozenset[str] = frozenset({"llama_cpp", "lemonade"})

#: Providers whose base URL may be overridden but which LiteLLM already knows by name.
_BASE_URL_AWARE: frozenset[str] = frozenset({"ollama", "lm_studio", "openai"})

_SKIP_STATUS = {
    SkipReason.BREAKER_OPEN: CallStatus.BREAKER_OPEN,
    SkipReason.BUDGET_EXCEEDED: CallStatus.BUDGET_EXCEEDED,
}


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

    def __init__(
        self,
        settings: Settings,
        breaker: CircuitBreaker | None = None,
        recorder: CallRecorder | None = None,
        budget: DailyBudget | None = None,
    ) -> None:
        self._settings = settings
        self._breaker = breaker or CircuitBreaker(
            threshold=settings.llm_breaker_threshold,
            cooldown_seconds=settings.llm_breaker_cooldown_seconds,
        )
        self._cache = DiskCache(settings.llm_cache_dir, enabled=settings.llm_cache_enabled)
        self._recorder = recorder or CallRecorder(None)
        self._budget = budget or DailyBudget(None, settings.daily_budget_usd)
        self._tracing = observability.configure(settings)

    # ── routing ───────────────────────────────────────────────────────────────
    def _dispatch_target(self, rung: Rung) -> tuple[str, str | None]:
        """Translate a rung into what LiteLLM expects: ``(litellm_model, api_base)``."""
        if rung.provider in _OPENAI_COMPATIBLE:
            return f"openai/{rung.model}", rung.api_base
        if rung.provider in _BASE_URL_AWARE:
            return rung.target, rung.api_base
        return rung.target, None

    # ── public API ────────────────────────────────────────────────────────────
    async def complete(
        self,
        *,
        task: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult | None:
        settings = self._settings
        requested = settings.model_for_task(task)

        # Cache first: a hit costs nothing, so neither the breaker nor the budget should be
        # able to withhold an answer the platform already has. Keyed on the *requested*
        # target, not the serving one — the cache answers "this prompt for this task", and a
        # result that arrived via fallback is still that answer.
        key = cache_key(
            task=task, model=requested, messages=messages, schema=schema, tools=tools
        )
        started = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None:
            self._recorder.record(
                CallRecord(
                    task=task,
                    provider=hit.provider,
                    model=hit.model,
                    requested_model=requested,
                    status=CallStatus.CACHED,
                    prompt_tokens=hit.prompt_tokens,
                    completion_tokens=hit.completion_tokens,
                    total_tokens=hit.total_tokens,
                    # No cost: a cache hit spent nothing, and attributing the original
                    # call's price to it again would double-count the day's spend.
                    cost_usd=None,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            )
            return hit

        chain = resolve_chain(
            settings,
            task,
            is_breaker_open=self._breaker.is_open,
            budget_exhausted=self._budget.is_exhausted(),
        )

        if chain.is_empty:
            self._record_unavailable(task, chain, requested)
            return None

        try:
            import litellm
        except ImportError:
            log.warning("litellm not installed; task=%s cannot run", task)
            return None

        for rung in chain.rungs:
            result = await self._attempt(litellm, task, rung, requested, messages, schema, tools)
            if result is not None:
                self._cache.put(key, result)
                return result

        return None

    # ── one rung ──────────────────────────────────────────────────────────────
    async def _attempt(
        self,
        litellm,
        task: str,
        rung: Rung,
        requested: str,
        messages: list[Message],
        schema: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult | None:
        settings = self._settings
        litellm_model, api_base = self._dispatch_target(rung)
        trace_id = observability.new_trace_id() if self._tracing else None

        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            # Local rungs get their own budget: same signal as the cost rule, same reason —
            # a local model is slow but free, so the trade a timeout makes is different.
            "timeout": (
                settings.llm_local_timeout_seconds
                if rung.is_local
                else settings.llm_timeout_seconds
            ),
            "num_retries": settings.llm_max_retries,
        }
        if api_base:
            kwargs["api_base"] = api_base
        if tools:
            kwargs["tools"] = tools
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
            latency_ms = int((time.monotonic() - started) * 1000)
            rate_limited = _looks_like_rate_limit(exc)
            if rate_limited:
                self._breaker.record_rate_limit(rung.provider)
                log.warning("rate limited by %s on task=%s", rung.provider, task)
            else:
                log.warning("LLM call failed (task=%s, model=%s): %s", task, rung.target, exc)
            self._recorder.record(
                CallRecord(
                    task=task,
                    provider=rung.provider,
                    model=rung.target,
                    requested_model=requested,
                    used_fallback=rung.is_fallback,
                    rung_index=rung.index,
                    status=(CallStatus.RATE_LIMITED if rate_limited else CallStatus.FAILED),
                    latency_ms=latency_ms,
                    trace_id=trace_id,
                    error_msg=f"{type(exc).__name__}: {exc}",
                )
            )
            return None

        self._breaker.record_success(rung.provider)
        latency_ms = int((time.monotonic() - started) * 1000)
        return self._to_result(
            response,
            task=task,
            rung=rung,
            requested=requested,
            trace_id=trace_id,
            latency_ms=latency_ms,
            schema=schema,
        )

    def _record_unavailable(self, task: str, chain: Chain, requested: str) -> None:
        """No rung was usable — record *why*, so the gap in output is explainable."""
        reason = chain.dominant_skip_reason
        if reason is None:
            return  # no rungs configured at all; nothing meaningful to record
        primary = chain.skipped[0][0]
        self._recorder.record(
            CallRecord(
                task=task,
                provider=primary.provider,
                model=primary.target,
                requested_model=requested,
                rung_index=primary.index,
                status=_SKIP_STATUS[reason],
                error_msg=(
                    f"all {len(chain.skipped)} rung(s) unavailable: "
                    + ", ".join(f"{r.target}={s.value}" for r, s in chain.skipped)
                ),
            )
        )

    # ── result assembly ───────────────────────────────────────────────────────
    def _to_result(
        self,
        response: Any,
        *,
        task: str,
        rung: Rung,
        requested: str,
        trace_id: str | None,
        latency_ms: int,
        schema: dict[str, Any] | None,
    ) -> LLMResult | None:
        try:
            message = response.choices[0].message
            text = message.content or ""
        except (AttributeError, IndexError, TypeError):
            log.warning("unexpected response shape from %s", rung.provider)
            self._recorder.record(
                CallRecord(
                    task=task,
                    provider=rung.provider,
                    model=rung.target,
                    requested_model=requested,
                    used_fallback=rung.is_fallback,
                    rung_index=rung.index,
                    status=CallStatus.FAILED,
                    latency_ms=latency_ms,
                    trace_id=trace_id,
                    error_msg="unexpected response shape",
                )
            )
            return None

        parsed: Any | None = None
        if schema and text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # Not every unparseable response is prose, and the difference decides whether
                # the call was wasted. A **truncated** response is structured output that ran
                # out of budget — its complete objects are usable, and a local model asked for
                # eight items routinely sends six and a half. **Prose** is a model that ignored
                # the schema, and nothing downstream can do anything with it.
                #
                # So a truncated response is handed back for the caller to salvage, and only a
                # genuinely unstructured one is a failure. Rejecting both was throwing away
                # answers that had already been paid for in minutes of local model time.
                if parsing.objects(parsing.strip_fence(text)):
                    log.info("task=%s response was truncated; returned for salvage", task)
                else:
                    log.warning(
                        "task expected JSON matching a schema; provider returned prose"
                    )
                    self._recorder.record(
                        CallRecord(
                            task=task,
                            provider=rung.provider,
                            model=rung.target,
                            requested_model=requested,
                            used_fallback=rung.is_fallback,
                            rung_index=rung.index,
                            status=CallStatus.FAILED,
                            latency_ms=latency_ms,
                            trace_id=trace_id,
                            error_msg="response was not valid JSON for the requested schema",
                        )
                    )
                    return None

        tool_calls = self._tool_calls_of(message)
        usage = getattr(response, "usage", None)
        cost = self._cost_of(response)

        result = LLMResult(
            text=text,
            # Which rung answered *is* the serving model — stronger than parsing it back out
            # of the response, and correct even when a provider echoes an alias.
            model=rung.target,
            provider=rung.provider,
            requested_model=requested,
            used_fallback=rung.is_fallback,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            cost_usd=cost,
            latency_ms=latency_ms,
            trace_id=trace_id,
            cached=False,
            parsed=parsed,
            tool_calls=tool_calls,
        )

        self._budget.add(cost)
        self._recorder.record(
            CallRecord(
                task=task,
                provider=rung.provider,
                model=rung.target,
                requested_model=requested,
                used_fallback=rung.is_fallback,
                rung_index=rung.index,
                status=CallStatus.OK,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                trace_id=trace_id,
            )
        )
        return result

    @staticmethod
    def _tool_calls_of(message: Any) -> tuple[ToolCall, ...]:
        """Tool calls the model made, with arguments already parsed.

        A call whose arguments are not valid JSON is dropped rather than passed on: it names a
        tool but says nothing usable about how to run it, and handing that to a registry would
        turn a model's malformed output into a confusing validation error one layer further
        from the cause.
        """
        raw = getattr(message, "tool_calls", None) or []
        calls: list[ToolCall] = []
        for item in raw:
            function = getattr(item, "function", None)
            name = getattr(function, "name", None)
            if not name:
                continue
            arguments = getattr(function, "arguments", None) or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    log.warning("dropping tool call %s: arguments were not valid JSON", name)
                    continue
            if not isinstance(arguments, dict):
                continue
            calls.append(
                ToolCall(id=str(getattr(item, "id", "") or name), name=name, arguments=arguments)
            )
        return tuple(calls)

    @staticmethod
    def _cost_of(response: Any) -> float | None:
        """LiteLLM populates a cost for every call, including free/local ones — where it
        reports exactly 0.0 rather than omitting the field (confirmed live against Ollama).
        Treated as unpriced (None), not zero-cost, so SUM(cost) over recorded calls means "the
        priced subset" and never silently drifts to mean "the total" once a free call lands.
        """
        hidden = getattr(response, "_hidden_params", None) or {}
        cost = hidden.get("response_cost") if isinstance(hidden, dict) else None
        if not isinstance(cost, int | float) or isinstance(cost, bool):
            return None
        return float(cost) if cost > 0 else None
