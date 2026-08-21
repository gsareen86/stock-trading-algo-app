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
        # Suppression asks "was this key raised since T" — this index is that question.
        Index("ix_insights_dedupe_created", "dedupe_key", "created_at"),
        Index("ix_insights_severity", "severity"),
        # The default feed is "not withdrawn, newest first".
        Index("ix_insights_withdrawn_created", "withdrawn_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: What produced this item, e.g. "verdict", "exit", "alert", "cycle_summary".
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Structured detail backing the rendered item.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    #: `kind:ticker:qualifier`. Keeps a daily cycle from raising the same observation every
    #: morning until the feed is something to scroll past.
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    #: A property of the *kind*, declared up front and stored — never a per-item score, which
    #: compared across kinds would be a ranking.
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")

    #: Null until the reader marks it seen in the app.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: When the figures this insight carries were last established — distinct from when it was
    #: first raised. A standing observation whose number moved is refreshed here, so "true
    #: since the 17th, measured today" is expressible. Without it, every figure in the feed is
    #: as of a creation date that says nothing about whether it was ever re-checked.
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Set when the rule that raised this, re-evaluated, would no longer raise it. Not a
    #: delete: the row and its original `created_at` stay, because "this was true for eleven
    #: days and then stopped" is the history the feed exists to carry.
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


#: Which book a row belongs to. A parameter, never a separate table or module — swing and
#: long-term differ in holding period, not in what a position is.
BOOKS = ("swing", "longterm")
SIDES = ("buy", "sell")
FILL_SOURCES = ("manual", "risk", "backtest")


class Trade(Base):
    """One paper fill — the unit of record.

    Positions are *derived* from these rows rather than stored alongside them. Storing a
    position independently is what makes duplicate ledgers unreconcilable: a
    directly-written position that no sequence of trades explains gives no way to tell which of
    the two is wrong.
    """

    __tablename__ = "book_trades"
    __table_args__ = (
        CheckConstraint("book IN ('swing', 'longterm')", name="ck_book_trades_book"),
        CheckConstraint("side IN ('buy', 'sell')", name="ck_book_trades_side"),
        CheckConstraint("quantity > 0", name="ck_book_trades_quantity"),
        CheckConstraint("price > 0", name="ck_book_trades_price"),
        Index("ix_book_trades_book_ticker", "book", "ticker"),
        Index("ix_book_trades_executed_at", "executed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    book: Mapped[str] = mapped_column(String(16), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Gross of brokerage, STT, stamp duty and GST — see `app/domain/position.py`.
    price: Mapped[float] = mapped_column(Float, nullable=False)

    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: What caused this fill, so a position's provenance stays answerable.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    #: Which strategy's verdict prompted it, when one did. Never a claim that the strategy
    #: decided — something still had to act.
    strategy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    """A person who may use the platform.

    One row per human. There is deliberately no role column: one person owns this book, and a
    permission system with nothing to permit is machinery that has to be maintained without
    ever being exercised. Roles arrive with a change that has a second kind of user.
    """

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_username", "username", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: Argon2id. The only representation of a password this platform stores, and it never
    #: leaves the database — no endpoint returns this column.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefreshToken(Base):
    """A refresh token that can actually be revoked.

    A JWT cannot be un-issued. Storing the `jti` and checking it on every use is what makes
    logout mean something — without this row, "log out" would delete a cookie and leave a
    credential valid for a fortnight.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_jti", "jti", unique=True),
        Index("ix_refresh_tokens_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The token's own identifier, not the token: possessing this row must not let anyone
    #: reconstruct a usable credential.
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderRequest(Base):
    """One request spent against a metered external data provider.

    A row per request, rather than a counter that is incremented. A count is derivable from
    rows and rows are not derivable from a count: when a month's allowance runs out
    unexpectedly, "which calls did that" is the only question worth asking, and a single
    integer cannot answer it.

    Written *before* the call rather than after it — a request that was made and then failed
    still consumed the allowance.
    """

    __tablename__ = "provider_requests"
    __table_args__ = (
        # The only question asked of this table: how many for this provider since a moment.
        Index("ix_provider_requests_provider_at", "provider", "requested_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: What the request was for, so an exhausted allowance can be explained rather than
    #: merely reported. Never a credential.
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ThemeRun(Base):
    """One pass over the sources, and what it could actually read.

    `sources_unavailable` is the column that stops a quiet failure looking like a quiet
    market. Commentary is scrape-only and fails often; a run that found three themes instead
    of eight because the documents would not download must be distinguishable from a run that
    genuinely found three.
    """

    __tablename__ = "theme_runs"
    __table_args__ = (Index("ix_theme_runs_started", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: `requested` or `scheduled`.
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    #: `running`, `complete`, `failed`, or `no_reading` when every source was unavailable.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    #: Source kinds this run could not read, so degraded detection is visible rather than
    #: inferred from a thin result.
    sources_unavailable: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    documents_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Theme(Base):
    """A concept the market is talking about, with the counts that evidence it.

    The counts are stored rather than recomputed on read, because they are the claim: a reader
    is being told "three companies, two periods", and that has to be the figure the run
    actually measured, not one re-derived later from a different set of rows.

    Carries the same lifecycle `insights` gained in `feed-freshness-and-run-control` and for
    the same reason — a theme that stops being evidenced must stop being displayed without
    losing the record that it was once true.
    """

    __tablename__ = "themes"
    __table_args__ = (
        Index("ix_themes_key", "key", unique=True),
        Index("ix_themes_withdrawn", "withdrawn_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)

    breadth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persistence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sector_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_kinds: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    #: When this was first evidenced — never reset by a later run, so "emerging since March"
    #: stays readable.
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: When its counts were last established.
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ThemeReference(Base):
    """One company saying one thing in one period, traceable to its document."""

    __tablename__ = "theme_references"
    __table_args__ = (
        Index("ix_theme_references_theme", "theme_key"),
        # A company saying the same thing in the same period twice is one reference.
        Index(
            "ix_theme_references_unique",
            "theme_key",
            "symbol",
            "period",
            "source_ref",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_key: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChainLink(Base):
    """One tier of what a theme consumes, why, and who proposed it.

    Stored rather than consumed as a transient prompt result. That is what makes the model's
    contribution auditable: a reader can see why a cable manufacturer is on their screen, and
    reject the link if the reasoning is wrong.

    `rejected` survives later runs deliberately. Without that, every run re-proposes the same
    wrong link and the reader re-rejects it forever, which is how a review surface becomes one
    people stop reading.
    """

    __tablename__ = "chain_links"
    __table_args__ = (
        Index("ix_chain_links_theme_tier", "theme_key", "tier"),
        Index("ix_chain_links_identity", "theme_key", "tier", "label", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    #: What this tier supplies; null for the first tier, which supplies the theme itself.
    supplies: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    #: The model that proposed it. Attribution is what keeps this from reading as a
    #: measurement the platform made.
    proposed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    supplier_descriptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ThemeCandidate(Base):
    """An instrument a tier resolved to, and how well its exposure is established.

    `exposure` is a named grade and never a number. A number would be sortable, and sorting
    candidates by theme exposure is a ranking this platform does not permit.
    """

    __tablename__ = "theme_candidates"
    __table_args__ = (
        Index("ix_theme_candidates_theme", "theme_key"),
        Index("ix_theme_candidates_identity", "theme_key", "tier", "symbol", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme_key: Mapped[str] = mapped_column(String(64), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exposure: Mapped[str] = mapped_column(String(16), nullable=False)
    exposure_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentConcept(Base):
    """One theme a model read out of one document.

    **Persisted so the counts can be arithmetic.** Extraction is a model call and a model
    answers differently each time, so breadth and persistence would drift on every run if they
    were recomputed from scratch — and thresholds over drifting numbers mean nothing. Storing
    what was read makes re-reading a document a deliberate act rather than something that
    happens by accident, which is how open vocabulary and stable counting coexist.

    The label here is **not a theme**. It is whatever words that company used; the placement
    that turns it into a theme lives in `concept_placements`, separately, so re-merging never
    requires re-reading.
    """

    __tablename__ = "document_concepts"
    __table_args__ = (
        Index("ix_document_concepts_label", "label"),
        Index("ix_document_concepts_symbol_period", "symbol", "period"),
        # Re-reading the same document must not double a company's contribution to breadth.
        Index("ix_document_concepts_identity", "source_ref", "label", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Free-form, in the company's own words.
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="commentary")
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    #: The model that read it. Attribution is what keeps this from reading as a measurement.
    extracted_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConceptPlacement(Base):
    """Which theme a freely-worded concept belongs to.

    Separate from the extraction it came from, because the two change for different reasons: a
    document is read once and never differently, while a placement may be revised as more
    themes stand or rejected by a reader who disagrees.

    A rejected placement survives later runs, for the same reason a rejected chain link does.
    Re-proposing a merge somebody already threw out is how a review surface becomes one people
    stop reading — and a wrong merge is worse than a wrong chain link, because it silently
    combines unrelated evidence into the counts that decide what surfaces.
    """

    __tablename__ = "concept_placements"
    __table_args__ = (Index("ix_concept_placements_label", "label", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    theme_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
