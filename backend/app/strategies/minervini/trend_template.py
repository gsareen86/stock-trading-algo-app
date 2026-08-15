"""Minervini's Trend Template — the eight criteria.

Each criterion emits exactly one `Evidence` row carrying the observed value, the threshold and
the operator. That is what makes the verdict explainable without an LLM: a reader can
reconstruct the whole argument from the rows.

**These are criteria, not gates.** Failing two makes a weaker setup, not an unassessable one,
so they reduce conviction rather than forcing `AVOID`. Gates answer *may we*; criteria answer
*how much*. Collapsing the two is exactly what the predecessor's confluence scorecard did.
"""

from __future__ import annotations

import pandas as pd

from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, Operator
from app.strategies.indicators import (
    fifty_two_week_range,
    is_rising,
    pct_above_low,
    pct_below_high,
    relative_strength_pct,
    sma,
)

#: Minervini's published thresholds.
MIN_PCT_ABOVE_52W_LOW = 30.0
MAX_PCT_BELOW_52W_HIGH = 25.0
MA200_RISING_BARS = 22  # roughly one month of sessions
RS_LOOKBACK_BARS = 252

CRITERION_COUNT = 8


def _ref(series: PriceSeries, note: str = "") -> str:
    suffix = f"&{note}" if note else ""
    return f"price://{series.instrument.symbol}?interval={series.interval}{suffix}"


def evaluate(series: PriceSeries, benchmark: PriceSeries | None) -> list[Evidence]:
    """One evidence row per criterion, in the book's order."""
    frame: pd.DataFrame = series.frame
    price = float(frame["close"].iloc[-1])
    ref = _ref(series)

    ma50 = sma(frame, 50)
    ma150 = sma(frame, 150)
    ma200 = sma(frame, 200)
    rising = is_rising(frame, 200, MA200_RISING_BARS)
    band = fifty_two_week_range(frame)

    rows: list[Evidence] = []

    # 1 — price above both long averages
    threshold_1 = max(v for v in (ma150, ma200) if v is not None) if (ma150 or ma200) else None
    rows.append(
        Evidence(
            id="price_above_150_200dma",
            label="Close above both the 150- and 200-day moving averages",
            value=round(price, 4),
            threshold=round(threshold_1, 4) if threshold_1 is not None else None,
            operator=Operator.GT,
            passed=bool(threshold_1 is not None and price > threshold_1),
            unit="INR",
            source_ref=ref,
        )
    )

    # 2 — 150-day above 200-day
    rows.append(
        Evidence(
            id="ma150_above_ma200",
            label="150-day moving average above the 200-day",
            value=round(ma150, 4) if ma150 is not None else None,
            threshold=round(ma200, 4) if ma200 is not None else None,
            operator=Operator.GT,
            passed=bool(ma150 is not None and ma200 is not None and ma150 > ma200),
            unit="INR",
            source_ref=ref,
        )
    )

    # 3 — 200-day trending up for at least a month
    rows.append(
        Evidence(
            id="ma200_rising",
            label=f"200-day moving average higher than {MA200_RISING_BARS} sessions ago",
            value=bool(rising) if rising is not None else None,
            threshold=True,
            operator=Operator.EQ,
            passed=bool(rising),
            source_ref=_ref(series, f"bars={MA200_RISING_BARS}"),
        )
    )

    # 4 — 50-day above both longer averages
    threshold_4 = max(v for v in (ma150, ma200) if v is not None) if (ma150 or ma200) else None
    rows.append(
        Evidence(
            id="ma50_above_ma150_ma200",
            label="50-day moving average above both the 150- and 200-day",
            value=round(ma50, 4) if ma50 is not None else None,
            threshold=round(threshold_4, 4) if threshold_4 is not None else None,
            operator=Operator.GT,
            passed=bool(ma50 is not None and threshold_4 is not None and ma50 > threshold_4),
            unit="INR",
            source_ref=ref,
        )
    )

    # 5 — price above the 50-day
    rows.append(
        Evidence(
            id="price_above_50dma",
            label="Close above the 50-day moving average",
            value=round(price, 4),
            threshold=round(ma50, 4) if ma50 is not None else None,
            operator=Operator.GT,
            passed=bool(ma50 is not None and price > ma50),
            unit="INR",
            source_ref=ref,
        )
    )

    # 6 — well clear of the 52-week low
    above_low = pct_above_low(price, band[0]) if band else None
    rows.append(
        Evidence(
            id="pct_above_52w_low",
            label="At least 30% above the 52-week low",
            value=above_low,
            threshold=MIN_PCT_ABOVE_52W_LOW,
            operator=Operator.GTE,
            passed=bool(above_low is not None and above_low >= MIN_PCT_ABOVE_52W_LOW),
            unit="%",
            source_ref=_ref(series, "bars=252"),
        )
    )

    # 7 — close to the 52-week high
    below_high = pct_below_high(price, band[1]) if band else None
    rows.append(
        Evidence(
            id="pct_below_52w_high",
            label="Within 25% of the 52-week high",
            value=below_high,
            threshold=MAX_PCT_BELOW_52W_HIGH,
            operator=Operator.LTE,
            passed=bool(below_high is not None and below_high <= MAX_PCT_BELOW_52W_HIGH),
            unit="%",
            source_ref=_ref(series, "bars=252"),
        )
    )

    # 8 — relative strength.
    # Minervini wants an IBD RS Rating >= 70: a percentile against every other stock, which
    # needs the whole universe ranked at once and arrives with screening-universe-and-gates.
    # Substituted here with return relative to a benchmark, and *named* for what it is — a
    # field called rs_rating holding something else would be believed by every later reader.
    rs = (
        relative_strength_pct(frame, benchmark.frame, RS_LOOKBACK_BARS)
        if benchmark is not None and not benchmark.is_empty
        else None
    )
    rows.append(
        Evidence(
            id="rs_criterion",
            label="Outperformed the benchmark over the trailing year (rs_vs_benchmark_pct)",
            value=rs,
            threshold=0.0,
            operator=Operator.GT,
            passed=bool(rs is not None and rs > 0),
            unit="pp",
            source_ref=(
                f"price://{series.instrument.symbol}"
                f"?relative_to={benchmark.instrument.symbol if benchmark else 'unavailable'}"
                f"&bars={RS_LOOKBACK_BARS}"
            ),
        )
    )

    return rows


def criteria_passed(rows: list[Evidence]) -> int:
    return sum(1 for row in rows if row.passed)


def all_passed(rows: list[Evidence]) -> bool:
    return criteria_passed(rows) == CRITERION_COUNT
