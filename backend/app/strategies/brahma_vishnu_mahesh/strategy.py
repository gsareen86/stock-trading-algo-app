"""Brahma-Vishnu-Mahesh — top-down, weekly.

Three legs, evaluated in the order the method reasons:

* **BRAHMA** — is the *market* in a condition worth trading? Nifty weekly close above a
  rising 20-week average.
* **VISHNU** — is the *sector* leading? The instrument's sector index ranked against the
  other seven on relative strength versus the Nifty.
* **MAHESH** — is the *stock* breaking out? Emergence from a horizontal base of at least
  1.5 years, confirmed by weekly volume well above its average.

**The regime is a criterion, not a gate.** The predecessor had a flag to halt entirely on a
bearish reading. Here a hostile market carries dominant weight in conviction instead: a bear
market does not make a stock unassessable, it makes it unattractive — and gating on it would
force every BVM verdict in the market to AVOID at once, leaving conviction carrying no
information at all.
"""

from __future__ import annotations

from app.core.clock import now_utc
from app.data import sectors
from app.domain.instrument import Instrument
from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, Operator, Verdict
from app.strategies import gates
from app.strategies.indicators import (
    horizontal_range_breakout,
    sma,
    to_weekly,
    window_return_pct,
)
from app.strategies.protocols import StrategyContext, StrategyDefinition

STRATEGY_ID = "brahma_vishnu_mahesh"

REGIME_SMA_WEEKS = 20
REGIME_RISING_WEEKS = 4
#: 1.5 years of daily sessions — the shortest base the method calls "multi-year".
MIN_BASE_BARS = 375
LOOKBACK_DAYS = 800
MIN_BARS = MIN_BASE_BARS + 30
#: Weekly breakout volume must be a multiple of its own average.
VOLUME_MULTIPLE = 3.0
#: Sector must rank inside the leading three of eight.
TOP_SECTORS = 3
SECTOR_RS_SHORT_BARS = 63  # ~3 months
SECTOR_RS_LONG_BARS = 126  # ~6 months

BUY_CONVICTION = 70
WATCH_CONVICTION = 35

#: The market condition dominates: a leading sector inside a bear market is still a bear market.
WEIGHT_REGIME = 40
WEIGHT_SECTOR = 25
WEIGHT_BREAKOUT = 35


class BrahmaVishnuMaheshStrategy:
    def evaluate(self, instrument: Instrument, context: StrategyContext) -> Verdict:
        as_of = context.now() if context.now else now_utc()
        series = context.price_source.history(
            instrument, interval="1d", lookback_days=LOOKBACK_DAYS
        )

        check = gates.check(
            STRATEGY_ID, instrument, series, as_of, MIN_BARS, "a 1.5-year base plus a breakout"
        )
        if check.blocked is not None:
            return check.blocked

        benchmark = self._series(context, context.benchmark)
        regime = self._brahma(benchmark)
        sector = self._vishnu(instrument, context, benchmark)
        breakout = self._mahesh(instrument, series)

        evidence = (*check.evidence, *regime, *sector, *breakout)
        conviction = self._conviction(regime, sector, breakout)
        core_passed = bool(regime[0].passed and breakout[0].passed)

        return Verdict(
            strategy_id=STRATEGY_ID,
            ticker=instrument.symbol,
            as_of=as_of,
            stance=gates.stance_from(conviction, BUY_CONVICTION, WATCH_CONVICTION, core_passed),
            conviction=conviction,
            evidence=evidence,
            gates=check.gates,
        )

    # ── BRAHMA ────────────────────────────────────────────────────────────────
    def _brahma(self, benchmark: PriceSeries | None) -> tuple[Evidence, ...]:
        ref = "price://NIFTY50?interval=1wk&analysis=regime"
        if benchmark is None:
            return (
                Evidence(
                    id="brahma_regime",
                    label="Market above a rising 20-week average (benchmark unavailable)",
                    value=None,
                    threshold=True,
                    operator=Operator.EQ,
                    passed=False,
                    source_ref=ref,
                ),
            )

        weekly = to_weekly(benchmark.frame)
        ma = sma(weekly, REGIME_SMA_WEEKS)
        close = float(weekly["close"].iloc[-1]) if len(weekly) else None

        rising = None
        ma_series = weekly["close"].rolling(REGIME_SMA_WEEKS).mean().dropna()
        if len(ma_series) > REGIME_RISING_WEEKS:
            rising = bool(ma_series.iloc[-1] > ma_series.iloc[-(REGIME_RISING_WEEKS + 1)])

        above = bool(close is not None and ma is not None and close > ma)
        return (
            Evidence(
                id="brahma_regime",
                label="Nifty weekly close above a rising 20-week average",
                value=round(close, 4) if close is not None else None,
                threshold=round(ma, 4) if ma is not None else None,
                operator=Operator.GT,
                passed=bool(above and rising),
                unit="INR",
                source_ref=ref,
            ),
            Evidence(
                id="brahma_ma_rising",
                label=f"20-week average higher than {REGIME_RISING_WEEKS} weeks ago",
                value=rising,
                threshold=True,
                operator=Operator.EQ,
                passed=bool(rising),
                source_ref=ref,
            ),
        )

    # ── VISHNU ────────────────────────────────────────────────────────────────
    def _vishnu(
        self, instrument: Instrument, context: StrategyContext, benchmark: PriceSeries | None
    ) -> tuple[Evidence, ...]:
        own = sectors.for_instrument(instrument)
        ref = f"price://sector-indices?for={instrument.symbol}"

        if own is None or benchmark is None:
            # Recorded as failed with the reason, never silently skipped: a criterion that
            # quietly disappears inflates the proportion passed, and therefore conviction.
            reason = "sector unknown" if own is None else "benchmark unavailable"
            return (
                Evidence(
                    id="vishnu_sector_rank",
                    label=f"Sector among the top {TOP_SECTORS} by relative strength ({reason})",
                    value=None,
                    threshold=TOP_SECTORS,
                    operator=Operator.LTE,
                    passed=False,
                    source_ref=ref,
                ),
            )

        scored: list[tuple[str, float]] = []
        for candidate in sectors.all_sector_indices():
            index_series = self._series(context, candidate.as_instrument())
            if index_series is None:
                continue
            blended = self._blended_rs(index_series, benchmark)
            if blended is not None:
                scored.append((candidate.key, blended))

        if not scored or own.key not in dict(scored):
            return (
                Evidence(
                    id="vishnu_sector_rank",
                    label="Sector among the top sectors (index data unavailable)",
                    value=None,
                    threshold=TOP_SECTORS,
                    operator=Operator.LTE,
                    passed=False,
                    source_ref=ref,
                ),
            )

        scored.sort(key=lambda kv: kv[1], reverse=True)
        rank = [key for key, _ in scored].index(own.key) + 1
        return (
            Evidence(
                id="vishnu_sector_rank",
                label=f"{own.key} sector rank by 3/6-month relative strength",
                value=rank,
                threshold=TOP_SECTORS,
                operator=Operator.LTE,
                passed=rank <= TOP_SECTORS,
                source_ref=f"price://{own.ticker}?relative_to=NIFTY50",
            ),
            Evidence(
                id="vishnu_sectors_ranked",
                label="Sector indices with usable data",
                value=len(scored),
                operator=Operator.INFO,
                source_ref=ref,
            ),
        )

    @staticmethod
    def _blended_rs(index_series: PriceSeries, benchmark: PriceSeries) -> float | None:
        """Equal blend of 3- and 6-month relative return, as the method specifies."""
        parts = []
        for bars in (SECTOR_RS_SHORT_BARS, SECTOR_RS_LONG_BARS):
            own = window_return_pct(index_series.frame, bars)
            base = window_return_pct(benchmark.frame, bars)
            if own is not None and base is not None:
                parts.append(own - base)
        return round(sum(parts) / len(parts), 4) if parts else None

    # ── MAHESH ────────────────────────────────────────────────────────────────
    def _mahesh(self, instrument: Instrument, series: PriceSeries) -> tuple[Evidence, ...]:
        weekly = to_weekly(series.frame)
        ref = f"price://{instrument.symbol}?interval=1wk&analysis=multi_year_breakout"

        breakout = horizontal_range_breakout(series.frame, MIN_BASE_BARS)
        avg_volume = float(weekly["volume"].tail(50).mean()) if len(weekly) >= 10 else None
        last_volume = float(weekly["volume"].iloc[-1]) if len(weekly) else None
        multiple = (
            round(last_volume / avg_volume, 4)
            if avg_volume and last_volume is not None and avg_volume > 0
            else None
        )

        return (
            Evidence(
                id="mahesh_range_breakout",
                label=f"Close above a horizontal base of at least {MIN_BASE_BARS} sessions",
                value=round(breakout.close, 4) if breakout else None,
                threshold=round(breakout.range_high, 4) if breakout else None,
                operator=Operator.GT,
                passed=bool(breakout and breakout.broke_out),
                unit="INR",
                source_ref=ref,
            ),
            Evidence(
                id="mahesh_volume_expansion",
                label="Weekly breakout volume as a multiple of its 50-week average",
                value=multiple,
                threshold=VOLUME_MULTIPLE,
                operator=Operator.GTE,
                passed=bool(multiple is not None and multiple >= VOLUME_MULTIPLE),
                unit="x",
                source_ref=ref,
            ),
            Evidence(
                id="mahesh_base_width",
                label="Width of the base being broken",
                value=breakout.width_pct if breakout else None,
                operator=Operator.INFO,
                unit="%",
                source_ref=ref,
            ),
        )

    # ── scoring ───────────────────────────────────────────────────────────────
    def _conviction(
        self,
        regime: tuple[Evidence, ...],
        sector: tuple[Evidence, ...],
        breakout: tuple[Evidence, ...],
    ) -> int:
        """Weighted sum, stated: regime 40, sector 25, breakout 35 (range and volume equally)."""
        score = 0.0
        if regime[0].passed:
            score += WEIGHT_REGIME
        if sector[0].passed:
            score += WEIGHT_SECTOR
        if breakout[0].passed:
            score += WEIGHT_BREAKOUT * 0.6
        if breakout[1].passed:
            score += WEIGHT_BREAKOUT * 0.4
        return int(round(min(100.0, score)))

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _series(context: StrategyContext, instrument: Instrument) -> PriceSeries | None:
        series = context.price_source.history(
            instrument, interval="1d", lookback_days=LOOKBACK_DAYS
        )
        return None if series.is_empty else series


STRATEGY = StrategyDefinition(
    id=STRATEGY_ID,
    name="Brahma-Vishnu-Mahesh",
    description=(
        "A top-down weekly method. BRAHMA checks the market is above a rising 20-week average; "
        "VISHNU requires the stock's sector index to rank among the leading three on blended "
        "3- and 6-month relative strength; MAHESH looks for a breakout from a horizontal base "
        "of at least 1.5 years on weekly volume at least 3x its average. A hostile regime is "
        "scored with dominant weight rather than gated, because a bear market makes a stock "
        "unattractive, not unassessable."
    ),
    strategy=BrahmaVishnuMaheshStrategy(),
    tags=("top-down", "weekly", "sector-rotation", "breakout"),
)
