"""Assessability gates, shared by every strategy.

A gate answers one question: **can this instrument be assessed at all by this strategy?** Not
enough bars, or never trades — those make an assessment impossible, and a failed one forces
`AVOID`.

Deliberately *not* here: anything about whether the setup is attractive. A hostile market, a
lagging sector, a weak base — those are criteria that lower conviction. A bear market does not
make a stock unassessable; it makes it unattractive, which is what a low conviction says.

Shared because four strategies asking the same two questions in four places is how they drift
apart, and the answer to "is this tradable" should not depend on who is asking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.instrument import Instrument
from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, GateResult, Operator, Stance, Verdict

LIQUIDITY_BARS = 20


@dataclass(frozen=True, slots=True)
class GateCheck:
    """Evidence and gates from the shared checks, plus a blocking verdict when one failed."""

    evidence: tuple[Evidence, ...]
    gates: tuple[GateResult, ...]
    blocked: Verdict | None


def _history_row(instrument: Instrument, bars: int, min_bars: int) -> Evidence:
    return Evidence(
        id="bars_available",
        label="Daily bars available",
        value=bars,
        threshold=min_bars,
        operator=Operator.GTE,
        passed=bars >= min_bars,
        source_ref=f"price://{instrument.symbol}?interval=1d",
    )


def check(
    strategy_id: str,
    instrument: Instrument,
    series: PriceSeries,
    as_of: datetime,
    min_bars: int,
    requirement: str = "the strategy's longest lookback",
) -> GateCheck:
    """Run the shared gates.

    When one fails, ``blocked`` carries a complete verdict explaining why — because "I could
    not assess this, and here is why" is information a scan should not lose to a silent skip.
    """
    bars = len(series)
    history = _history_row(instrument, bars, min_bars)

    if bars < min_bars:
        reason = (
            "no price data returned"
            if series.is_empty
            else f"{bars} bars available, {min_bars} needed for {requirement}"
        )
        gate = GateResult(
            id="sufficient_history",
            label="Sufficient price history",
            passed=False,
            reason=reason,
            evidence_ids=("bars_available",),
        )
        return GateCheck(
            evidence=(history,),
            gates=(gate,),
            blocked=Verdict(
                strategy_id=strategy_id,
                ticker=instrument.symbol,
                as_of=as_of,
                stance=Stance.AVOID,
                conviction=0,
                evidence=(history,),
                gates=(gate,),
            ),
        )

    traded = float(series.frame["volume"].tail(LIQUIDITY_BARS).sum())
    volume_row = Evidence(
        id="recent_volume",
        label=f"Traded volume over the last {LIQUIDITY_BARS} sessions",
        value=traded,
        threshold=0,
        operator=Operator.GT,
        passed=traded > 0,
        source_ref=f"price://{instrument.symbol}?interval=1d&bars={LIQUIDITY_BARS}",
    )

    if traded <= 0:
        gate = GateResult(
            id="tradable_liquidity",
            label="Instrument actually trades",
            passed=False,
            reason=f"no traded volume in the last {LIQUIDITY_BARS} sessions",
            evidence_ids=("recent_volume",),
        )
        return GateCheck(
            evidence=(history, volume_row),
            gates=(gate,),
            blocked=Verdict(
                strategy_id=strategy_id,
                ticker=instrument.symbol,
                as_of=as_of,
                stance=Stance.AVOID,
                conviction=0,
                evidence=(history, volume_row),
                gates=(gate,),
            ),
        )

    return GateCheck(
        evidence=(history, volume_row),
        gates=(
            GateResult(
                id="sufficient_history",
                label="Sufficient price history",
                passed=True,
                reason=f"{bars} bars available",
                evidence_ids=("bars_available",),
            ),
            GateResult(
                id="tradable_liquidity",
                label="Instrument actually trades",
                passed=True,
                reason=f"{traded:,.0f} shares over {LIQUIDITY_BARS} sessions",
                evidence_ids=("recent_volume",),
            ),
        ),
        blocked=None,
    )


def stance_from(conviction: int, buy_at: int, watch_at: int, all_criteria: bool = True) -> Stance:
    """Shared stance thresholds.

    ``all_criteria`` lets a strategy insist its core criteria all passed before a BUY —
    conviction alone can be pushed over the line by bonuses, and a strategy whose defining
    test failed should not reach BUY on peripheral strength.
    """
    if all_criteria and conviction >= buy_at:
        return Stance.BUY
    if conviction >= watch_at:
        return Stance.WATCH
    return Stance.AVOID
