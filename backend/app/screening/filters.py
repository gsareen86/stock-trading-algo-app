"""Eligibility filters.

Each answers one question: **should the platform look at this name at all?** That is not the
same question as "can this strategy assess it" (`app/strategies/gates.py`) and emphatically not
"is the setup attractive" (a strategy's criteria). Keeping the three apart is most of the value
here — collapsing them into one number is how a failed hard check gets averaged away.

A filter never ranks. It admits or excludes, and when it excludes it says what it measured,
what the threshold was, and where the number came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.data.surveillance import SurveillanceList
from app.domain.instrument import Instrument
from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, Operator

#: Sessions the turnover median is taken over. Long enough that a quiet fortnight does not
#: disqualify a name, short enough to reflect how it trades now.
TURNOVER_WINDOW = 20

#: Default floors. Rupees of median daily turnover, and rupees per share.
#:
#: The turnover floor is the one that matters: it is roughly the level below which a retail
#: position cannot be entered or exited without moving the price. The price floor is a much
#: blunter instrument and is set low deliberately — cheap is not the same as bad, and a floor
#: high enough to be opinionated would be a quality judgement wearing an eligibility hat.
DEFAULT_MIN_TURNOVER_INR = 5_00_00_000.0  # ₹5 crore
DEFAULT_MIN_PRICE_INR = 20.0
DEFAULT_MIN_BARS = 200


@dataclass(frozen=True, slots=True)
class FilterResult:
    """Whether a name passed, and the measurement behind that."""

    filter_id: str
    passed: bool
    evidence: Evidence
    reason: str


def _ref(instrument: Instrument, detail: str) -> str:
    return f"price://{instrument.symbol}?{detail}"


def median_turnover(series: PriceSeries, window: int = TURNOVER_WINDOW) -> float | None:
    """Median daily turnover in rupees over the window.

    ``close × volume`` per session, then the **median** — a mean would let one block deal
    qualify a name that is otherwise untradeable, which is precisely the shape of data that
    gets a liquidity screen wrong.
    """
    if series.is_empty:
        return None
    frame = series.frame.tail(window)
    if frame.empty:
        return None
    return float((frame["close"] * frame["volume"]).median())


def check_history(
    instrument: Instrument, series: PriceSeries, min_bars: int = DEFAULT_MIN_BARS
) -> FilterResult:
    """Enough history to say anything at all."""
    bars = len(series)
    return FilterResult(
        filter_id="history",
        passed=bars >= min_bars,
        reason=(
            f"{bars} sessions available, {min_bars} required"
            if bars < min_bars
            else f"{bars} sessions available"
        ),
        evidence=Evidence(
            id="screen_bars",
            label="Daily sessions available",
            value=bars,
            threshold=min_bars,
            operator=Operator.GTE,
            passed=bars >= min_bars,
            source_ref=_ref(instrument, "interval=1d"),
        ),
    )


def check_turnover(
    instrument: Instrument,
    series: PriceSeries,
    minimum: float = DEFAULT_MIN_TURNOVER_INR,
    window: int = TURNOVER_WINDOW,
) -> FilterResult:
    """Tradable in rupees, not in share count.

    The pre-existing per-strategy gate asks ``volume > 0``, which passes a stock that traded
    eleven shares — and compares share counts across names whose prices differ by three orders
    of magnitude. Turnover is the unit a position is actually sized in.
    """
    turnover = median_turnover(series, window)
    passed = turnover is not None and turnover >= minimum
    return FilterResult(
        filter_id="turnover",
        passed=passed,
        reason=(
            "no price history to measure turnover"
            if turnover is None
            else f"median turnover ₹{turnover:,.0f} over {window} sessions "
            f"({'above' if passed else 'below'} ₹{minimum:,.0f})"
        ),
        evidence=Evidence(
            id="screen_turnover",
            label=f"Median daily turnover over {window} sessions",
            value=turnover,
            threshold=minimum,
            operator=Operator.GTE,
            passed=passed,
            unit="INR",
            source_ref=_ref(instrument, f"interval=1d&bars={window}&metric=turnover"),
        ),
    )


def check_price(
    instrument: Instrument, series: PriceSeries, minimum: float = DEFAULT_MIN_PRICE_INR
) -> FilterResult:
    """A floor low enough to exclude only what is structurally untradeable."""
    last = series.last_close
    passed = last is not None and last >= minimum
    return FilterResult(
        filter_id="price",
        passed=passed,
        reason=(
            "no last close available"
            if last is None
            else f"last close ₹{last:,.2f} ({'above' if passed else 'below'} ₹{minimum:,.2f})"
        ),
        evidence=Evidence(
            id="screen_price",
            label="Last close",
            value=last,
            threshold=minimum,
            operator=Operator.GTE,
            passed=passed,
            unit="INR",
            source_ref=_ref(instrument, "interval=1d&bar=last"),
        ),
    )


def check_surveillance(
    instrument: Instrument, listed: SurveillanceList, today: date
) -> FilterResult:
    """Under an NSE surveillance measure is a reason not to have a view.

    Not a judgement about the company — a statement that the exchange has flagged it and this
    platform has no business forming an opinion on it while that holds.
    """
    measure = listed.measure_for(instrument.symbol)
    passed = measure is None
    stale_note = " (surveillance list is stale)" if listed.is_stale(today) else ""
    return FilterResult(
        filter_id="surveillance",
        passed=passed,
        reason=(
            f"under NSE {measure}{stale_note}"
            if measure
            else f"not under NSE surveillance{stale_note}"
        ),
        evidence=Evidence(
            id="screen_surveillance",
            label="NSE surveillance measure",
            value=measure or "none",
            operator=Operator.INFO,
            source_ref=f"nse://surveillance?as_of={listed.as_of or 'unknown'}",
        ),
    )
