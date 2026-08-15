"""Persisting the call log.

Every attempt writes a row — successes, failures, cache hits, breaker short-circuits and
budget refusals alike. A log that only records successes cannot answer "why did narratives
stop appearing?", which is the question it exists for.

**Recording can never break a call.** Every write is wrapped, and a logging failure is warned
about rather than raised. An observability layer able to take down the thing it observes is
worse than none — and this one sits on the hot path of every LLM call in the platform.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.llm.types import CallStatus
from app.persistence.models import LlmCall

log = logging.getLogger(__name__)

#: Failure messages are truncated to the column width. Provider errors can embed entire
#: request bodies, which would put prompt content into a table that deliberately holds none.
_MAX_ERROR_CHARS = 500


@dataclass(slots=True)
class CallRecord:
    task: str
    provider: str
    model: str
    status: CallStatus
    requested_model: str = ""
    used_fallback: bool = False
    rung_index: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    trace_id: str | None = None
    error_msg: str | None = None


class CallRecorder:
    """Writes :class:`CallRecord` rows. Construct with ``None`` to disable recording."""

    def __init__(self, session_factory: sessionmaker[Session] | None) -> None:
        self._session_factory = session_factory

    @property
    def enabled(self) -> bool:
        return self._session_factory is not None

    def record(self, record: CallRecord) -> None:
        if self._session_factory is None:
            return
        try:
            with self._session_factory() as session:
                session.add(
                    LlmCall(
                        task=record.task,
                        provider=record.provider,
                        model=record.model,
                        requested_model=record.requested_model or record.model,
                        used_fallback=record.used_fallback,
                        rung_index=record.rung_index,
                        status=record.status.value,
                        prompt_tokens=record.prompt_tokens,
                        completion_tokens=record.completion_tokens,
                        total_tokens=record.total_tokens,
                        cost_usd=record.cost_usd,
                        latency_ms=record.latency_ms,
                        trace_id=record.trace_id,
                        error_msg=(record.error_msg or None)
                        and record.error_msg[:_MAX_ERROR_CHARS],
                    )
                )
                session.commit()
        except Exception as exc:
            # Deliberately swallowed: see the module docstring. The call itself has already
            # succeeded or failed on its own terms, and that outcome must not change here.
            log.warning("could not record LLM call (task=%s): %s", record.task, exc)
