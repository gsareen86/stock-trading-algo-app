"""Persisted models.

Only the two tables the skeleton needs. Strategies, evidence extraction and the agent cycle
land in later changes; the columns here are limited to what ``openspec/project.md`` already
fixes about the decision model, so nothing is invented ahead of its spec.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base

#: A strategy's independent opinion. Never blended across strategies — cross-strategy
#: agreement may be displayed, never computed into a decision.
STANCES = ("BUY", "WATCH", "AVOID")


class Verdict(Base):
    """One strategy's independent opinion on one ticker at one point in time.

    ``stance`` and ``conviction`` are produced by deterministic Python and must be
    reproducible with the LLM switched off. ``narrative`` is the only LLM-authored column,
    and every number in it must trace to a row in ``evidence``.
    """

    __tablename__ = "verdicts"
    __table_args__ = (
        CheckConstraint(
            "stance IN ('BUY', 'WATCH', 'AVOID')",
            name="ck_verdicts_stance",
        ),
        CheckConstraint(
            "conviction >= 0 AND conviction <= 100",
            name="ck_verdicts_conviction_range",
        ),
        Index("ix_verdicts_ticker_as_of", "ticker", "as_of"),
        Index("ix_verdicts_strategy_as_of", "strategy_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: Which strategy formed this opinion. Conviction is scoped to this strategy alone
    #: and is not comparable across strategies.
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    stance: Mapped[str] = mapped_column(String(8), nullable=False)
    conviction: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Hard pass/fail checks, recorded separately from conviction. A failed gate is never
    #: outweighed by a high score.
    gates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    #: The unit of traceability: {id, metric, value, threshold, passed, source_ref}.
    #: Produced entirely by deterministic Python.
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    #: LLM plain-English findings and recommendation. Nullable — a verdict is complete
    #: without it, which is what keeps the LLM explanatory rather than decisive.
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Langfuse trace for the narrative call, so a rendered explanation links back to the
    #: exact trace that produced it.
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LlmCall(Base):
    """One LLM call attempt, recorded regardless of outcome.

    Deliberately local rather than only in Langfuse: Langfuse is optional and absent in most
    local setups, and "what did today cost?" must be answerable with no external service. This
    table is for *accounting*; Langfuse is for trace depth. They answer different questions.

    Contains no prompt or completion text — this is a ledger, not a transcript, and a
    trading platform's prompts will carry position and thesis detail.
    """

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'cached', 'failed', 'rate_limited', "
            "'breaker_open', 'budget_exceeded')",
            name="ck_llm_calls_status",
        ),
        Index("ix_llm_calls_created_at", "created_at"),
        Index("ix_llm_calls_task_created", "task", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: The job the caller named, e.g. "narrative" or "research".
    task: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Provider and model that actually served the attempt.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    #: What configuration asked for. Differs from ``model`` when a fallback answered.
    requested_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    used_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Position in the chain; 0 is the primary rung.
    rung_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(24), nullable=False)

    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Nullable on purpose. Local providers report no cost, and recording 0.0 would make
    #: SUM(cost_usd) silently mean "cost of the paid subset" while looking like a total.
    #: Unknown stays unknown.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Langfuse trace, when observability is configured.
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: Truncated failure reason. No prompt content.
    error_msg: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Insight(Base):
    """One item in the in-app feed.

    Insights are delivered in-app only — there is deliberately no email, push or messaging
    channel, and none should be added without a change that specifies it.
    """

    __tablename__ = "insights"
    __table_args__ = (
        Index("ix_insights_created_at", "created_at"),
        Index("ix_insights_ticker", "ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: What produced this item, e.g. "verdict", "exit", "alert", "cycle_summary".
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Structured detail backing the rendered item.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    #: Null until the reader marks it seen in the app.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
