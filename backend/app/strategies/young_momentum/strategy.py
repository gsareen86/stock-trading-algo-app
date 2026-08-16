"""Young Momentum — the 1-2-3-4 continuation.

Buys the *first* meaningful pause after a young impulse, rather than waiting for the several
contractions Minervini requires. That difference is the whole point of running both: the same
stock is a Young Momentum entry weeks before it is a Minervini one, and blending the two would
average away exactly the timing distinction each is built on.

1. **Base breakout** — emergence from a multi-month base on heavy volume.
2. **Impulse leg** — a 20–50% advance compressed into 5–15 sessions.
3. **Healthy pause** — 2–6 days of consolidation that must *not* retrace past the 38.2%
   Fibonacci level of the impulse, on volume below the 20-day average.
4. **Continuation entry** — a trigger just above the pause high, stop below its low.

The retracement bound is genuinely binary: a deeper pullback does not mean a weaker signal, it
means the impulse failed.
"""

from __future__ import annotations

from app.core.clock import now_utc
from app.domain.instrument import Instrument
from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, Operator, Verdict
from app.strategies import gates
from app.strategies.indicators import (
    fib_retracement_pct,
    find_impulse_leg,
    horizontal_range_breakout,
)
from app.strategies.protocols import StrategyContext, StrategyDefinition

STRATEGY_ID = "young_momentum"

LOOKBACK_DAYS = 400
MIN_BARS = 160

#: Published parameters.
IMPULSE_MIN_PCT = 20.0
IMPULSE_MAX_PCT = 50.0
IMPULSE_MIN_BARS = 5
IMPULSE_MAX_BARS = 15
PAUSE_MIN_BARS = 2
PAUSE_MAX_BARS = 6
FIB_LIMIT_PCT = 38.2
BASE_BARS = 60
BASE_VOLUME_MULTIPLE = 1.5
#: Trigger sits fractionally above the pause high, as the method specifies.
TRIGGER_OFFSET_PCT = 0.1

BUY_CONVICTION = 70
WATCH_CONVICTION = 35

WEIGHT_BASE_BREAKOUT = 20
WEIGHT_IMPULSE = 30
WEIGHT_PAUSE = 30
WEIGHT_PAUSE_VOLUME = 20


class YoungMomentumStrategy:
    def evaluate(self, instrument: Instrument, context: StrategyContext) -> Verdict:
        as_of = context.now() if context.now else now_utc()
        series = context.price_source.history(
            instrument, interval="1d", lookback_days=LOOKBACK_DAYS
        )

        check = gates.check(
            STRATEGY_ID, instrument, series, as_of, MIN_BARS, "a multi-month base plus an impulse"
        )
        if check.blocked is not None:
            return check.blocked

        rows = self._sequence(instrument, series)
        evidence = (*check.evidence, *rows)
        conviction = self._conviction(rows)
        # The impulse and the pause are the signal; a base breakout alone is not this setup.
        core_passed = bool(rows[1].passed and rows[2].passed)

        return Verdict(
            strategy_id=STRATEGY_ID,
            ticker=instrument.symbol,
            as_of=as_of,
            stance=gates.stance_from(conviction, BUY_CONVICTION, WATCH_CONVICTION, core_passed),
            conviction=conviction,
            evidence=evidence,
            gates=check.gates,
        )

    def _sequence(self, instrument: Instrument, series: PriceSeries) -> tuple[Evidence, ...]:
        frame = series.frame
        ref = f"price://{instrument.symbol}?interval=1d&analysis=continuation"

        # 1 — base breakout on heavy volume
        base = horizontal_range_breakout(frame, BASE_BARS, exclude_recent=20)
        base_volume = float(frame["volume"].tail(60).mean())
        breakout_volume = float(frame["volume"].tail(20).max())
        base_multiple = round(breakout_volume / base_volume, 4) if base_volume > 0 else None
        base_row = Evidence(
            id="base_breakout",
            label=f"Emerged from a {BASE_BARS}-session base on volume above its average",
            value=base_multiple,
            threshold=BASE_VOLUME_MULTIPLE,
            operator=Operator.GTE,
            passed=bool(
                base is not None
                and base.broke_out
                and base_multiple is not None
                and base_multiple >= BASE_VOLUME_MULTIPLE
            ),
            unit="x",
            source_ref=ref,
        )

        # 2 — impulse leg
        impulse = find_impulse_leg(
            frame, IMPULSE_MIN_PCT, IMPULSE_MAX_PCT, IMPULSE_MIN_BARS, IMPULSE_MAX_BARS
        )
        impulse_row = Evidence(
            id="impulse_leg",
            label=f"A {IMPULSE_MIN_PCT:.0f}-{IMPULSE_MAX_PCT:.0f}% advance in "
            f"{IMPULSE_MIN_BARS}-{IMPULSE_MAX_BARS} sessions",
            value=impulse.gain_pct if impulse else None,
            threshold=IMPULSE_MIN_PCT,
            operator=Operator.GTE,
            passed=impulse is not None,
            unit="%",
            source_ref=ref,
        )

        # 3 — the pause, bounded by the 38.2% retracement
        pause_bars = 0
        retracement = None
        if impulse is not None:
            window = frame.tail(len(frame) - 1 - impulse.end_index) if impulse.end_index else frame
            pause_bars = min(len(window), PAUSE_MAX_BARS)
            if pause_bars:
                pause_low = float(window["low"].tail(pause_bars).min())
                retracement = fib_retracement_pct(impulse.low, impulse.high, pause_low)

        pause_row = Evidence(
            id="pause_within_fib",
            label=f"Pullback held above the {FIB_LIMIT_PCT}% retracement of the impulse",
            value=retracement,
            threshold=FIB_LIMIT_PCT,
            operator=Operator.LTE,
            passed=bool(
                impulse is not None
                and retracement is not None
                and retracement <= FIB_LIMIT_PCT
                and PAUSE_MIN_BARS <= pause_bars <= PAUSE_MAX_BARS
            ),
            unit="%",
            source_ref=ref,
        )

        # 4 — quiet pause volume
        pause_volume = (
            round(
                float(frame["volume"].tail(max(pause_bars, 1)).mean())
                / float(frame["volume"].tail(20).mean()),
                4,
            )
            if float(frame["volume"].tail(20).mean()) > 0
            else None
        )
        volume_row = Evidence(
            id="pause_volume_dry_up",
            label="Pause volume relative to the 20-day average",
            value=pause_volume,
            threshold=1.0,
            operator=Operator.LT,
            passed=bool(pause_volume is not None and pause_volume < 1.0),
            unit="x",
            source_ref=ref,
        )

        # Entry levels — informational. A level is not a decision, and sizing belongs to the
        # books increment.
        trigger = stop = None
        if impulse is not None and pause_bars:
            pause_window = frame.tail(pause_bars)
            trigger = round(float(pause_window["high"].max()) * (1 + TRIGGER_OFFSET_PCT / 100), 4)
            stop = round(float(pause_window["low"].min()), 4)

        return (
            base_row,
            impulse_row,
            pause_row,
            volume_row,
            Evidence(
                id="entry_trigger",
                label=f"Buy-stop {TRIGGER_OFFSET_PCT}% above the pause high",
                value=trigger,
                operator=Operator.INFO,
                unit="INR",
                source_ref=ref,
            ),
            Evidence(
                id="entry_stop",
                label="Stop below the pause low",
                value=stop,
                operator=Operator.INFO,
                unit="INR",
                source_ref=ref,
            ),
        )

    def _conviction(self, rows: tuple[Evidence, ...]) -> int:
        """Impulse and pause carry 60 of 100 — they are the setup; the rest is confirmation."""
        score = 0.0
        for row, weight in (
            (rows[0], WEIGHT_BASE_BREAKOUT),
            (rows[1], WEIGHT_IMPULSE),
            (rows[2], WEIGHT_PAUSE),
            (rows[3], WEIGHT_PAUSE_VOLUME),
        ):
            if row.passed:
                score += weight
        return int(round(min(100.0, score)))


STRATEGY = StrategyDefinition(
    id=STRATEGY_ID,
    name="Young Momentum 1-2-3-4",
    description=(
        "Buys the first meaningful pause after a young impulse, rather than waiting for the "
        "repeated contractions Minervini requires. Looks for a base breakout on heavy volume, "
        "a 20-50% advance compressed into 5-15 sessions, then a 2-6 day pause that holds above "
        "the 38.2% Fibonacci retracement of that impulse on quiet volume. The retracement bound "
        "is binary: a deeper pullback means the impulse failed, not that the signal is weaker. "
        "Entry trigger and stop levels are reported as information, not as a position."
    ),
    strategy=YoungMomentumStrategy(),
    tags=("momentum", "continuation", "swing"),
)
