"""The gateway's public surface.

Application code depends on **these types only** — never on ``litellm``. That indirection is
what keeps the routing library swappable and, more importantly, what lets callers name a
*task* rather than a model so routing stays configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


class CallStatus(StrEnum):
    """Outcome of one call attempt.

    A closed set rather than a boolean: these fail in different ways and have different
    fixes, and collapsing them would throw away the diagnosis. "Narratives stopped
    appearing" is answered by *which* of these is filling the log.
    """

    OK = "ok"
    CACHED = "cached"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    BREAKER_OPEN = "breaker_open"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool the model asked to run.

    ``arguments`` is already parsed. A provider hands them over as a JSON *string*, and every
    caller would otherwise repeat the same parse-and-guard — including the guard for the case
    that matters, which is a model emitting something that is not JSON at all. Parsed once,
    here, so an unparseable call never reaches a tool.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResult:
    """A successful completion, plus what observability needs to account for it."""

    text: str
    #: The model that actually **answered**, which is not necessarily the one configured —
    #: with fallbacks, "which model produced this?" stops being knowable from settings, and a
    #: narrative that claims an origin it did not have is worse than one with no origin.
    model: str
    provider: str

    #: What configuration asked for. Differs from ``model`` exactly when a fallback served it.
    requested_model: str = ""
    used_fallback: bool = False

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    #: Provider-reported cost where available. None when the provider does not report one
    #: (local models, typically).
    cost_usd: float | None = None
    latency_ms: int | None = None

    #: Langfuse trace, when observability is configured. A ``Verdict`` persists this so a
    #: rendered narrative links back to the exact trace that produced it.
    trace_id: str | None = None

    #: True when served from the content-hash cache without a network request.
    cached: bool = False

    #: Parsed object when the caller supplied a JSON schema.
    parsed: Any | None = None

    #: Tools the model asked to run. Empty when it asked for none — which is a valid answer,
    #: not a failure: "nothing here is worth looking up" is a real conclusion.
    tool_calls: tuple[ToolCall, ...] = ()

    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMGateway(Protocol):
    """The only way application code reaches a language model.

    ``complete`` returns ``None`` on *any* failure — provider error, timeout, rate limit,
    open circuit breaker, or missing credentials — and never raises. Callers are expected to
    always have a non-LLM path; a cycle must not crash because a provider is down.
    """

    async def complete(
        self,
        *,
        task: str,
        messages: list[Message],
        schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult | None: ...
