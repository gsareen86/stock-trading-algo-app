"""The cycle's nodes.

Every node returns a *partial* state update rather than mutating what it was given. That is
what lets four strategy nodes run concurrently against the same input without any of them
being able to observe another's output.

No node raises. A cycle that dies because one RSS feed timed out is a cycle nobody trusts to
run unattended.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.state import CycleState, Finding, RegimeRead
from app.agents.toolbelt import Toolbelt
from app.core.clock import now_utc
from app.data.protocols import PriceSource
from app.domain.instrument import Instrument
from app.domain.verdict import Verdict
from app.llm.types import LLMGateway, Message
from app.narratives.generator import narrate_all
from app.strategies.protocols import DEFAULT_BENCHMARK, StrategyContext
from app.strategies.registry import StrategyRegistry

log = logging.getLogger(__name__)

RESEARCH_TASK = "research"

#: Fallback bound when no setting is supplied. An agent that calls tools until it feels
#: finished is one that occasionally never finishes — bounded rather than trusted.
DEFAULT_MAX_TOOL_ROUNDS = 3

#: Roughly four years of daily history, resampled weekly — enough for a 30-week average with
#: room to spare, and the same window the BVM strategy reads the regime over.
REGIME_LOOKBACK_DAYS = 1500

#: Weeks in the moving average that defines "trending" for the benchmark.
REGIME_MA_WEEKS = 30


# ── regime ────────────────────────────────────────────────────────────────────
def make_regime_node(price_source: PriceSource):
    """Read the benchmark's weekly trend once, for every strategy to share.

    Shared *input*, never a cycle-wide veto: a hostile regime lowers conviction inside the
    strategies that care and is ignored by the ones that do not. A veto here would be a blended
    decision wearing a different hat.
    """

    async def regime(state: CycleState) -> dict[str, Any]:
        source_ref = f"price://{DEFAULT_BENCHMARK.symbol}?interval=1wk&analysis=regime"
        try:
            series = price_source.history(
                DEFAULT_BENCHMARK, interval="1wk", lookback_days=REGIME_LOOKBACK_DAYS
            )
        except Exception as exc:  # pragma: no cover - sources are contracted not to raise
            log.warning("regime read failed: %s", exc)
            series = None

        if series is None or series.is_empty or len(series) < REGIME_MA_WEEKS:
            return {
                "regime": RegimeRead(
                    trending=False,
                    label="unknown",
                    detail="benchmark history unavailable",
                    source_ref=source_ref,
                ),
                "notes": ["regime: benchmark unavailable, treated as unknown"],
            }

        closes = series.frame["close"]
        ma30 = float(closes.tail(REGIME_MA_WEEKS).mean())
        last = float(closes.iloc[-1])
        trending = last > ma30
        return {
            "regime": RegimeRead(
                trending=trending,
                label="constructive" if trending else "hostile",
                detail=(
                    f"benchmark weekly close {last:.2f} "
                    f"{'above' if trending else 'below'} its "
                    f"{REGIME_MA_WEEKS}-week average {ma30:.2f}"
                ),
                source_ref=source_ref,
            ),
            "notes": [f"regime: {'constructive' if trending else 'hostile'}"],
        }

    return regime


# ── screen ────────────────────────────────────────────────────────────────────
def make_screen_node(screener, universe_source, criteria):
    """Narrow the universe to names worth evaluating.

    Skipped entirely when the caller supplied instruments: asking about a specific stock should
    return an answer about that stock, including when it would not have survived a screen. A
    screen chooses *what to look at*; it never changes what a strategy concludes about a name
    it does look at.
    """

    async def screen(state: CycleState) -> dict[str, Any]:
        if state.get("instruments"):
            return {"notes": ["screen: skipped, symbols supplied by caller"]}

        try:
            snapshot = universe_source.snapshot()
        except Exception as exc:  # pragma: no cover - sources are contracted not to raise
            log.warning("screen: universe unavailable: %s", exc)
            return {"instruments": [], "notes": [f"screen: universe unavailable ({exc})"]}

        result = screener.run(snapshot, criteria)
        notes = [
            f"screen: {len(result.eligible)}/{result.considered} eligible "
            f"({result.excluded_by()})"
        ]
        if result.surveillance.get("stale"):
            # A stale list under-excludes silently; saying so is the whole point of tracking age.
            notes.append("screen: surveillance list is stale")

        return {
            "instruments": list(result.eligible),
            "screen": result.as_dict(),
            "notes": notes,
        }

    return screen


# ── research ──────────────────────────────────────────────────────────────────
def make_research_node(
    toolbelt: Toolbelt, gateway: LLMGateway, max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
):
    """A bounded tool-calling loop, producing context — never evidence.

    Nothing this node returns can pass a gate or move a conviction. If the model calls no
    tools, or every call fails, the strategies run exactly as they would have. That is what
    keeps "verdicts are reproducible with the LLM off" literally true rather than aspirational.
    """

    async def research(state: CycleState) -> dict[str, Any]:
        instruments: list[Instrument] = state.get("instruments") or []
        findings: dict[str, list[Finding]] = {}
        notes: list[str] = []

        if toolbelt.unreachable_servers:
            notes.append(f"research: MCP unavailable ({', '.join(toolbelt.unreachable_servers)})")

        for instrument in instruments:
            collected, note = await _research_one(instrument, toolbelt, gateway, max_rounds)
            findings[instrument.symbol] = collected
            if note:
                notes.append(note)

        return {"research": findings, "notes": notes}

    return research


async def _research_one(
    instrument: Instrument, toolbelt: Toolbelt, gateway: LLMGateway, max_rounds: int
) -> tuple[list[Finding], str | None]:
    tools = toolbelt.definitions()
    if not tools:
        return [], "research: no tools available"

    messages = [
        Message(
            role="system",
            content=(
                "You gather context about an Indian stock for an analyst. Call the tools that "
                "would tell you something useful, then stop. Do not analyse, do not recommend, "
                "do not state figures of your own — the tools' output is the answer. If nothing "
                "is worth looking up, call nothing."
            ),
        ),
        Message(
            role="user",
            content=f"Gather recent context for {instrument.symbol} (NSE).",
        ),
    ]

    findings: list[Finding] = []
    for _ in range(max_rounds):
        result = await gateway.complete(task=RESEARCH_TASK, messages=messages, tools=tools)
        if result is None:
            return findings, f"research: no model answered for {instrument.symbol}"

        calls = result.tool_calls or []
        if not calls:
            break

        for call in calls:
            ok, text = await toolbelt.invoke(call.name, call.arguments)
            findings.append(
                Finding(
                    tool=call.name,
                    ticker=instrument.symbol,
                    summary=text if ok else f"unavailable: {text}",
                    source_ref=f"tool://{call.name}?symbol={instrument.symbol}",
                )
            )
            messages.append(
                Message(role="assistant", content=f"[called {call.name}]")
            )
            messages.append(
                Message(role="user", content=f"Result of {call.name}: {text}")
            )

    return findings, None


# ── strategies ────────────────────────────────────────────────────────────────
def make_strategy_node(strategy_id: str, registry: StrategyRegistry, context: StrategyContext):
    """One node per strategy, fanned out in parallel.

    Reads `instruments`, `as_of` and `regime`. Writes only to `verdicts`, through an additive
    reducer. It cannot read another strategy's verdict because the state it is handed does not
    contain one.
    """

    async def run(state: CycleState) -> dict[str, Any]:
        definition = registry.get(strategy_id)
        if definition is None:  # pragma: no cover - the graph is built from the registry
            return {"notes": [f"{strategy_id}: not registered"]}

        produced: list[Verdict] = []
        for instrument in state.get("instruments") or []:
            try:
                produced.append(definition.strategy.evaluate(instrument, context))
            except Exception as exc:
                # One strategy failing on one name must not cost the other three their run.
                log.warning("strategy %s failed on %s: %s", strategy_id, instrument.symbol, exc)
                return {"notes": [f"{strategy_id}/{instrument.symbol}: {type(exc).__name__}"]}
        return {"verdicts": produced}

    return run


# ── risk ──────────────────────────────────────────────────────────────────────
def make_risk_node(ledger, limits, book, price_source: PriceSource):
    """Decide whether to act on each verdict, without touching any of them.

    `Verdict` is frozen and its only mutator sets a narrative, so this node structurally cannot
    downgrade a BUY to a WATCH — it can only decline to act on one. A strategy answers "is this
    a good setup"; risk answers "should this portfolio take it".
    """

    async def risk(state: CycleState) -> dict[str, Any]:
        verdicts = state.get("verdicts") or []
        if not verdicts:
            return {}

        from app.risk.rules import PortfolioState, assess

        portfolio = PortfolioState(book=book, positions=tuple(ledger.positions(book)))
        decisions = []
        for verdict in verdicts:
            last_price = _last_price(price_source, verdict.ticker)
            decisions.append(assess(verdict, portfolio, limits, last_price).as_dict())

        actionable = sum(1 for d in decisions if d["outcome"] == "proceed")
        return {
            "risk": decisions,
            "notes": [f"risk: {actionable}/{len(decisions)} actionable"],
        }

    return risk


def _last_price(price_source: PriceSource, ticker: str) -> float | None:
    try:
        series = price_source.history(Instrument(ticker), interval="1d", lookback_days=30)
    except Exception:  # pragma: no cover - sources are contracted not to raise
        return None
    return series.last_close


# ── narrate ───────────────────────────────────────────────────────────────────
def make_narrate_node(gateway: LLMGateway):
    """Attach prose to every verdict the fan-in collected. Optional by construction."""

    async def narrate(state: CycleState) -> dict[str, Any]:
        verdicts = state.get("verdicts") or []
        if not state.get("narrate") or not verdicts:
            return {}

        narrated, report = await narrate_all(list(verdicts), gateway)
        carried = sum(1 for r in report if r["outcome"] == "ok")
        notes = [f"narrate: {carried}/{len(narrated)} carried prose"]

        # Written to `narrated`, not back into `verdicts`: that key's reducer appends, so
        # returning the list there would duplicate every verdict instead of replacing it.
        return {"narrated": narrated, "notes": notes}

    return narrate


# ── insights ──────────────────────────────────────────────────────────────────
def make_insights_node(feed, ledger, book, limits):
    """Turn the cycle into the few things worth someone's attention.

    Runs last because it reads everything: verdicts (narrated, if narration ran), risk
    decisions, research findings, the regime and the book's positions. It writes to the feed and
    changes nothing else — an insight links to what would act and leaves the acting to
    `Ledger.fill()`.
    """

    async def insights(state: CycleState) -> dict[str, Any]:
        from app.insights import rules

        verdicts = state.get("narrated") or state.get("verdicts") or []
        positions = ledger.positions(book, open_only=False)
        bought_by = rules.strategies_by_ticker(ledger.trades(book))
        decisions = state.get("risk") or []

        blocked_by_count = sum(1 for d in decisions if d.get("gate") == "position_count")

        candidates = [
            *rules.thesis_broken(positions, list(verdicts), bought_by),
            *rules.concentration(positions, limits.max_position_pct),
            *rules.position_research(positions, state.get("research") or {}),
            *rules.opportunities(decisions),
            *rules.book_full(positions, limits.max_positions, blocked_by_count),
            *rules.regime_change(
                state["regime"].as_dict() if state.get("regime") else None, None
            ),
        ]

        report = feed.record(candidates)
        return {
            "insights": report.as_dict(),
            "notes": [
                f"insights: {report.written} written, {report.suppressed} suppressed"
                + (f", {report.truncated} truncated" if report.truncated else "")
            ],
        }

    return insights


def _finding_dicts(state: CycleState) -> dict[str, list[dict]]:
    return {
        ticker: [f.as_dict() for f in items]
        for ticker, items in (state.get("research") or {}).items()
    }


def summarise(state: CycleState) -> dict[str, Any]:
    """Terminal assembly — the cycle's result as plain data."""
    regime = state.get("regime")
    return {
        "cycle_id": state.get("cycle_id"),
        "as_of": (state.get("as_of") or now_utc()).isoformat(),
        "regime": regime.as_dict() if regime else None,
        "research": _finding_dicts(state),
        "notes": list(state.get("notes") or []),
    }
