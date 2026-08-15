"""The gateway's public surface.

Application code depends on **these types only** — never on ``litellm``. That indirection is
what keeps the routing library swappable and, more importantly, what lets callers name a
*task* rather than a model so routing stays configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMResult:
    """A successful completion, plus what observability needs to account for it."""

    text: str
    #: Full ``<provider>/<model>`` the request was dispatched to.
    model: str
    provider: str

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
    ) -> LLMResult | None: ...
