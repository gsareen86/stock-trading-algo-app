"""Minervini SEPA — gates, conviction and stance.

The strategy's whole job is to turn measurements into one independent verdict, deterministically
and with every claim backed by an evidence row.

Two things are kept strictly apart, because merging them is what this rebuild exists to undo:

* **Gates** answer *may we assess and trade this at all* — enough history, actually traded.
  A failed gate forces `AVOID`, enforced by the `Verdict` constructor itself.
* **Conviction** answers *how strong is this setup within Minervini* — the share of Trend
  Template criteria passed, plus VCP quality. It is never comparable to another strategy's
  conviction.
"""

from __future__ import annotations

import logging

from app.core.clock import now_utc
from app.domain.instrument import Instrument
from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, GateResult, Operator, Stance, Verdict
from app.strategies.minervini import trend_template, vcp
from app.strategies.protocols import StrategyContext, StrategyDefinition

log = logging.getLogger(__name__)

STRATEGY_ID = "minervini"

#: 200-day average plus a month of slope needs this much history to mean anything.
MIN_BARS = 200 + trend_template.MA200_RISING_BARS
LOOKBACK_DAYS = 400

#: Stance thresholds. Named so a reader can find them rather than inferring them from
#: a comparison buried in a branch.
BUY_CONVICTION = 75
WATCH_CONVICTION = 40

#: Trend Template contributes at most this much; VCP and volume supply the rest.
TEMPLATE_WEIGHT = 70


class MinerviniStrategy:
    """Implements :class:`app.strategies.protocols.Strategy`."""

    def evaluate(self, instrument: Instrument, context: StrategyContext) -> Verdict:
        as_of = (context.now() if context.now else now_utc)()
        series = context.price_source.history(
            instrument, interval="1d", lookback_days=LOOKBACK_DAYS
        )

        blocked = self._gate_check(instrument, series, as_of)
        if blocked is not None:
            return blocked

        benchmark = self._benchmark_series(context)
        template_rows = trend_template.evaluate(series, benchmark)
        reading = vcp.analyse(series)
        vcp_rows = vcp.to_evidence(series, reading)

        context_rows = [
            Evidence(
                id="last_close",
                label="Most recent close",
                value=round(float(series.frame["close"].iloc[-1]), 4),
                operator=Operator.INFO,
                unit="INR",
                source_ref=f"price://{instrument.symbol}?interval=1d&bar=last",
            ),
            Evidence(
                id="bars_available",
                label="Daily bars available",
                value=len(series),
                operator=Operator.INFO,
                source_ref=f"price://{instrument.symbol}?interval=1d",
            ),
        ]

        evidence = [*context_rows, *template_rows, *vcp_rows]
        passed = trend_template.criteria_passed(template_rows)
        conviction = self._conviction(passed, reading)
        stance = self._stance(passed, conviction)

        return Verdict(
            strategy_id=STRATEGY_ID,
            ticker=instrument.symbol,
            as_of=as_of,
            stance=stance,
            conviction=conviction,
            evidence=tuple(evidence),
            gates=tuple(self._passing_gates(series)),
        )

    # ── gates ─────────────────────────────────────────────────────────────────
    def _gate_check(self, instrument: Instrument, series: PriceSeries, as_of) -> Verdict | None:
        """Return a blocking verdict when the instrument cannot be assessed, else None.

        "I could not assess this, and here is why" is information a reader wants — returning
        None or raising would throw it away and leave a silent hole in a scan.
        """
        bars = len(series)
        history_row = Evidence(
            id="bars_available",
            label="Daily bars available",
            value=bars,
            threshold=MIN_BARS,
            operator=Operator.GTE,
            passed=bars >= MIN_BARS,
            source_ref=f"price://{instrument.symbol}?interval=1d",
        )

        if bars < MIN_BARS:
            reason = (
                "no price data returned"
                if series.is_empty
                else f"{bars} bars available, {MIN_BARS} needed for a 200-day average plus slope"
            )
            return Verdict(
                strategy_id=STRATEGY_ID,
                ticker=instrument.symbol,
                as_of=as_of,
                stance=Stance.AVOID,
                conviction=0,
                evidence=(history_row,),
                gates=(
                    GateResult(
                        id="sufficient_history",
                        label="Sufficient price history",
                        passed=False,
                        reason=reason,
                        evidence_ids=("bars_available",),
                    ),
                ),
            )

        recent_volume = float(series.frame["volume"].tail(20).sum())
        if recent_volume <= 0:
            volume_row = Evidence(
                id="recent_volume",
                label="Traded volume over the last 20 sessions",
                value=recent_volume,
                threshold=0,
                operator=Operator.GT,
                passed=False,
                source_ref=f"price://{instrument.symbol}?interval=1d&bars=20",
            )
            return Verdict(
                strategy_id=STRATEGY_ID,
                ticker=instrument.symbol,
                as_of=as_of,
                stance=Stance.AVOID,
                conviction=0,
                evidence=(history_row, volume_row),
                gates=(
                    GateResult(
                        id="tradable_liquidity",
                        label="Instrument actually trades",
                        passed=False,
                        reason="no traded volume in the last 20 sessions",
                        evidence_ids=("recent_volume",),
                    ),
                ),
            )

        return None

    def _passing_gates(self, series: PriceSeries) -> list[GateResult]:
        return [
            GateResult(
                id="sufficient_history",
                label="Sufficient price history",
                passed=True,
                reason=f"{len(series)} bars available",
                evidence_ids=("bars_available",),
            )
        ]

    # ── scoring ───────────────────────────────────────────────────────────────
    def _conviction(self, criteria_passed: int, reading: vcp.VcpReading) -> int:
        """Stated formula, reproducible from the evidence alone — no model involved."""
        base = TEMPLATE_WEIGHT * (criteria_passed / trend_template.CRITERION_COUNT)
        vcp_points, volume_points = vcp.quality_points(reading)
        return int(round(min(100.0, base + vcp_points + volume_points)))

    def _stance(self, criteria_passed: int, conviction: int) -> Stance:
        """A BUY needs the full template *and* the conviction — a strong base under a broken
        trend is not a Minervini buy, however tight it looks."""
        if criteria_passed == trend_template.CRITERION_COUNT and conviction >= BUY_CONVICTION:
            return Stance.BUY
        if conviction >= WATCH_CONVICTION:
            return Stance.WATCH
        return Stance.AVOID

    # ── helpers ───────────────────────────────────────────────────────────────
    def _benchmark_series(self, context: StrategyContext) -> PriceSeries | None:
        try:
            series = context.price_source.history(
                context.benchmark, interval="1d", lookback_days=LOOKBACK_DAYS
            )
        except Exception as exc:  # pragma: no cover - source contract says it never raises
            log.debug("benchmark fetch failed: %s", exc)
            return None
        return None if series.is_empty else series


STRATEGY = StrategyDefinition(
    id=STRATEGY_ID,
    name="Minervini Trend Template + VCP",
    description=(
        "Mark Minervini's SEPA approach: the eight-criterion Trend Template establishes that "
        "a stock is in a confirmed Stage 2 uptrend, and Volatility Contraction Pattern "
        "analysis measures how tightly it has consolidated before a potential breakout. "
        "Criteria are scored rather than gated — a partial template is a watchlist candidate, "
        "not a rejection. Hard gates cover only whether the instrument can be assessed at all. "
        "The relative-strength criterion compares against a benchmark index rather than a "
        "cross-sectional percentile, which arrives with the universe screening change."
    ),
    strategy=MinerviniStrategy(),
    tags=("momentum", "breakout", "stage-2", "vcp"),
)
