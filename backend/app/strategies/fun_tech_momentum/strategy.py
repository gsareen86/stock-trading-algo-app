"""Fundamental-Technical Momentum — CANSLIM-style, tuned for Indian results seasonality.

Earnings surprises drive institutional accumulation; the technical side only decides *when*.
So the fundamental screen runs first, and a failure there is a low score rather than a
different kind of signal.

**Fundamentals are a gate here, uniquely.** A fundamental-screen strategy with no fundamentals
is not a weak signal, it is no signal — unlike the other three, for which fundamentals are
simply irrelevant.
"""

from __future__ import annotations

from app.core.clock import now_utc
from app.data.fundamentals import QuarterlyFundamentals
from app.domain.instrument import Instrument
from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, GateResult, Operator, Stance, Verdict
from app.strategies import gates
from app.strategies.indicators import (
    consolidation_tightness,
    fifty_two_week_range,
    pct_below_high,
)
from app.strategies.protocols import StrategyContext, StrategyDefinition

STRATEGY_ID = "fun_tech_momentum"

LOOKBACK_DAYS = 400
MIN_BARS = 260

#: The published thresholds.
SURPRISE_MULTIPLE = 1.5  # latest quarter vs the same quarter a year earlier
SEQUENTIAL_MULTIPLE = 1.1  # latest quarter vs the one before it
MAX_PCT_BELOW_HIGH = 15.0
#: A tight base is 2–6 weeks; tightness is the high-low range across it.
BASE_BARS = 25
MAX_BASE_WIDTH_PCT = 15.0
VOLUME_EXPANSION = 2.0  # breakout volume vs the 20-day average

BUY_CONVICTION = 75
WATCH_CONVICTION = 40

WEIGHT_SURPRISE = 30
WEIGHT_SEQUENTIAL = 15
WEIGHT_NEAR_HIGH = 20
WEIGHT_TIGHT_BASE = 20
WEIGHT_VOLUME = 15

#: Index 4 is the same quarter one year back. Indian results are seasonal — comparing the
#: latest quarter with the previous one would read seasonality as growth.
YEAR_AGO_INDEX = 4


class FunTechMomentumStrategy:
    def evaluate(self, instrument: Instrument, context: StrategyContext) -> Verdict:
        as_of = context.now() if context.now else now_utc()
        series = context.price_source.history(
            instrument, interval="1d", lookback_days=LOOKBACK_DAYS
        )

        check = gates.check(
            STRATEGY_ID, instrument, series, as_of, MIN_BARS, "a year of daily history"
        )
        if check.blocked is not None:
            return check.blocked

        fundamentals = self._fundamentals(instrument, context)
        blocked = self._fundamentals_gate(instrument, as_of, check, fundamentals)
        if blocked is not None:
            return blocked

        fundamental_rows = self._screen(instrument, fundamentals)
        technical_rows = self._setup(instrument, series)

        evidence = (*check.evidence, *fundamental_rows, *technical_rows)
        conviction = self._conviction(fundamental_rows, technical_rows)
        core_passed = bool(fundamental_rows[0].passed and fundamental_rows[1].passed)

        return Verdict(
            strategy_id=STRATEGY_ID,
            ticker=instrument.symbol,
            as_of=as_of,
            stance=gates.stance_from(conviction, BUY_CONVICTION, WATCH_CONVICTION, core_passed),
            conviction=conviction,
            evidence=evidence,
            gates=check.gates,
        )

    # ── fundamentals gate ─────────────────────────────────────────────────────
    @staticmethod
    def _fundamentals(
        instrument: Instrument, context: StrategyContext
    ) -> QuarterlyFundamentals | None:
        if context.fundamentals_source is None:
            return None
        result = context.fundamentals_source.quarterly(instrument)
        return None if result.is_empty else result

    def _fundamentals_gate(
        self,
        instrument: Instrument,
        as_of,
        check: gates.GateCheck,
        fundamentals: QuarterlyFundamentals | None,
    ) -> Verdict | None:
        quarters = max(len(fundamentals.eps), len(fundamentals.revenue)) if fundamentals else 0
        if quarters > YEAR_AGO_INDEX:
            return None

        row = Evidence(
            id="quarters_available",
            label="Reported quarters available",
            value=quarters,
            threshold=YEAR_AGO_INDEX + 1,
            operator=Operator.GTE,
            passed=False,
            source_ref=(
                fundamentals.source_ref
                if fundamentals
                else f"fundamentals://unavailable/{instrument.symbol}"
            ),
        )
        return Verdict(
            strategy_id=STRATEGY_ID,
            ticker=instrument.symbol,
            as_of=as_of,
            stance=Stance.AVOID,
            conviction=0,
            evidence=(*check.evidence, row),
            gates=(
                *check.gates,
                GateResult(
                    id="fundamentals_available",
                    label="Quarterly fundamentals available",
                    passed=False,
                    reason=(
                        f"{quarters} quarters available; the earnings screen needs at least "
                        f"{YEAR_AGO_INDEX + 1} to compare with the same quarter a year earlier"
                    ),
                    evidence_ids=("quarters_available",),
                ),
            ),
        )

    # ── fundamental screen ────────────────────────────────────────────────────
    def _screen(
        self, instrument: Instrument, fundamentals: QuarterlyFundamentals
    ) -> tuple[Evidence, ...]:
        ref = fundamentals.source_ref or f"fundamentals://{instrument.symbol}"

        eps_now, eps_year = fundamentals.eps_at(0), fundamentals.eps_at(YEAR_AGO_INDEX)
        rev_now, rev_year = fundamentals.revenue_at(0), fundamentals.revenue_at(YEAR_AGO_INDEX)

        eps_ratio = self._ratio(eps_now, eps_year)
        rev_ratio = self._ratio(rev_now, rev_year)
        best = max((r for r in (eps_ratio, rev_ratio) if r is not None), default=None)

        # Kept as one criterion rather than split: the method accepts acceleration through
        # either line, and scoring them separately would let a stock pass "half" of a test
        # that has no half. Which side satisfied it is recorded in the label.
        satisfied_by = (
            "EPS"
            if eps_ratio is not None and eps_ratio >= SURPRISE_MULTIPLE
            else "revenue"
            if rev_ratio is not None and rev_ratio >= SURPRISE_MULTIPLE
            else "neither"
        )

        eps_prev = fundamentals.eps_at(1)
        sequential = self._ratio(eps_now, eps_prev)

        return (
            Evidence(
                id="earnings_surprise",
                label=f"EPS or revenue at least 1.5x the year-ago quarter (via {satisfied_by})",
                value=best,
                threshold=SURPRISE_MULTIPLE,
                operator=Operator.GTE,
                passed=bool(best is not None and best >= SURPRISE_MULTIPLE),
                unit="x",
                source_ref=ref,
            ),
            Evidence(
                id="sequential_eps_growth",
                label="EPS at least 1.1x the preceding quarter",
                value=sequential,
                threshold=SEQUENTIAL_MULTIPLE,
                operator=Operator.GTE,
                passed=bool(sequential is not None and sequential >= SEQUENTIAL_MULTIPLE),
                unit="x",
                source_ref=ref,
            ),
            Evidence(
                id="eps_year_ago_quarter",
                label="Year-ago quarter used for the comparison",
                value=(
                    fundamentals.eps[YEAR_AGO_INDEX].period_end.isoformat()
                    if len(fundamentals.eps) > YEAR_AGO_INDEX
                    else None
                ),
                operator=Operator.INFO,
                source_ref=ref,
            ),
        )

    @staticmethod
    def _ratio(latest: float | None, earlier: float | None) -> float | None:
        """Growth multiple, or None when it cannot be computed.

        A negative or zero base makes a ratio meaningless — 'infinite growth' from a loss is
        an artefact, not a surprise, so it is reported as unknown rather than as a pass.
        """
        if latest is None or earlier is None or earlier <= 0:
            return None
        return round(latest / earlier, 4)

    # ── technical setup ───────────────────────────────────────────────────────
    def _setup(self, instrument: Instrument, series: PriceSeries) -> tuple[Evidence, ...]:
        frame = series.frame
        ref = f"price://{instrument.symbol}?interval=1d&analysis=tight_base"
        price = float(frame["close"].iloc[-1])

        band = fifty_two_week_range(frame)
        below_high = pct_below_high(price, band[1]) if band else None
        tightness = consolidation_tightness(frame, BASE_BARS)

        avg_volume = float(frame["volume"].tail(20).mean())
        last_volume = float(frame["volume"].iloc[-1])
        multiple = round(last_volume / avg_volume, 4) if avg_volume > 0 else None

        return (
            Evidence(
                id="within_15pct_of_high",
                label="Within 15% of the 52-week high",
                value=below_high,
                threshold=MAX_PCT_BELOW_HIGH,
                operator=Operator.LTE,
                passed=bool(below_high is not None and below_high <= MAX_PCT_BELOW_HIGH),
                unit="%",
                source_ref=f"price://{instrument.symbol}?interval=1d&bars=252",
            ),
            Evidence(
                id="tight_consolidation",
                label=f"High-low range across the last {BASE_BARS} sessions",
                value=tightness,
                threshold=MAX_BASE_WIDTH_PCT,
                operator=Operator.LTE,
                passed=bool(tightness is not None and tightness <= MAX_BASE_WIDTH_PCT),
                unit="%",
                source_ref=ref,
            ),
            Evidence(
                id="volume_expansion",
                label="Latest volume as a multiple of the 20-day average",
                value=multiple,
                threshold=VOLUME_EXPANSION,
                operator=Operator.GTE,
                passed=bool(multiple is not None and multiple >= VOLUME_EXPANSION),
                unit="x",
                source_ref=f"price://{instrument.symbol}?interval=1d&bars=20",
            ),
        )

    # ── scoring ───────────────────────────────────────────────────────────────
    def _conviction(
        self, fundamental_rows: tuple[Evidence, ...], technical_rows: tuple[Evidence, ...]
    ) -> int:
        """Fundamentals carry 45 of 100 — the screen is what this method is built on."""
        score = 0.0
        weights = (
            (fundamental_rows[0], WEIGHT_SURPRISE),
            (fundamental_rows[1], WEIGHT_SEQUENTIAL),
            (technical_rows[0], WEIGHT_NEAR_HIGH),
            (technical_rows[1], WEIGHT_TIGHT_BASE),
            (technical_rows[2], WEIGHT_VOLUME),
        )
        for row, weight in weights:
            if row.passed:
                score += weight
        return int(round(min(100.0, score)))


STRATEGY = StrategyDefinition(
    id=STRATEGY_ID,
    name="Fundamental-Technical Momentum",
    description=(
        "A CANSLIM-style screen for Indian equities, where earnings surprises drive "
        "institutional accumulation. Requires EPS or revenue at least 1.5x the same quarter a "
        "year earlier — the same quarter, because Indian results are seasonal — plus EPS at "
        "least 1.1x the preceding quarter. The technical side then looks for a tight base "
        "within 15% of the 52-week high breaking out on expanding volume. Quarterly "
        "fundamentals are a hard gate: this screen cannot run without them."
    ),
    strategy=FunTechMomentumStrategy(),
    tags=("canslim", "earnings", "fundamental", "breakout"),
)
