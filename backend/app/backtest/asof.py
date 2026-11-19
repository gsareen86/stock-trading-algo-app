"""Point-in-time price data.

The usual way a backtest lies is that a strategy evaluated for 3 March reads a moving average
computed over bars up to today. Nothing in the strategy looks wrong — the data was simply too
generous.

`AsOfPriceSource` wraps any `PriceSource` and truncates every series to bars at or before its
as-of date. It implements the same protocol, so **strategies are unmodified and cannot opt
out**: a strategy asks for history and receives history that stops where the clock is.

That placement is the point. Threading a date through `evaluate`, or trusting each strategy to
slice its own frame, depends on four strategies and every future one getting it right forever.
Here there is one wrapper, and a strategy that wanted to see the future would have to reach
around its own injected source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.domain.instrument import Instrument
from app.domain.prices import Interval, PriceSeries, build_series, empty_series

log = logging.getLogger(__name__)


@dataclass
class AsOfPriceSource:
    """A `PriceSource` that cannot return a bar after ``as_of``.

    Implements :class:`app.data.protocols.PriceSource`.
    """

    inner: object
    as_of: date

    def history(
        self,
        instrument: Instrument,
        *,
        interval: Interval = "1d",
        lookback_days: int = 400,
    ) -> PriceSeries:
        try:
            # Ask the wrapped source for more than the caller wanted: truncation removes the
            # tail, so a window measured from *today* would leave too few bars once the future
            # is cut away. Padding keeps the usable history the strategy expects.
            padded = lookback_days + _days_since(self.as_of)
            series = self.inner.history(instrument, interval=interval, lookback_days=padded)
        except Exception as exc:  # pragma: no cover - sources are contracted not to raise
            log.warning("as-of fetch failed for %s: %s", instrument.symbol, exc)
            return empty_series(instrument, interval)

        return truncate(series, self.as_of)

    def with_date(self, as_of: date) -> AsOfPriceSource:
        """Same underlying source, a different moment. Cheap enough to make per session."""
        return AsOfPriceSource(inner=self.inner, as_of=as_of)


def truncate(series: PriceSeries, as_of: date) -> PriceSeries:
    """Drop every bar after ``as_of``.

    Inclusive of the as-of session: a decision made after Tuesday's close may use Tuesday's
    bar. What it may not do is *act* on Tuesday's close — that is the runner's rule, and the
    two together are what stop a backtest from buying at a price it only knew in hindsight.
    """
    if series.is_empty:
        return series

    cutoff = datetime.combine(as_of, datetime.max.time(), tzinfo=UTC)
    frame = series.frame[series.frame.index <= cutoff]
    if frame.empty:
        return empty_series(series.instrument, series.interval)

    return build_series(
        series.instrument,
        series.interval,
        frame.rename(columns=str.title),
        source=f"{series.source}@{as_of.isoformat()}",
    )


def _days_since(as_of: date) -> int:
    return max(0, (datetime.now(UTC).date() - as_of).days)


def last_bar_on_or_before(series: PriceSeries, when: date) -> tuple[date, float] | None:
    """The most recent session at or before a date, as ``(date, close)``."""
    truncated = truncate(series, when)
    if truncated.is_empty:
        return None
    stamp = truncated.frame.index[-1]
    return stamp.date(), float(truncated.frame["close"].iloc[-1])


def first_bar_after(series: PriceSeries, when: date) -> tuple[date, float] | None:
    """The next session's **open** after a date, as ``(date, open)``.

    This is what a fill costs. A verdict formed from data up to Tuesday's close could not have
    been acted on at Tuesday's close — the decision did not exist until the bar did — so the
    trade happens at Wednesday's open. It is the second-largest source of overstated backtest
    returns after lookahead, and it costs one bar in the honest direction.
    """
    if series.is_empty:
        return None
    cutoff = datetime.combine(when, datetime.max.time(), tzinfo=UTC)
    future = series.frame[series.frame.index > cutoff]
    if future.empty:
        return None
    return future.index[0].date(), float(future["open"].iloc[0])


# ── replay sources ─────────────────────────────────────────────────────────────────────────
#
# `AsOfPriceSource` above re-asks its inner source for every evaluation, which is right for a
# handful of names and far too slow for a multi-year universe replay. The replay instead loads
# each history once and serves slices of it. The guarantee is the same — nothing after the
# as-of session is ever returned — and is asserted by the same kind of test.

#: The live yfinance source never returns fewer than this many calendar days, so a strategy in
#: production always sees at least this much history. The replay serves the same window, so a
#: strategy is not shown more history in a backtest than it would have live.
LIVE_MIN_LOOKBACK_DAYS = 820


def session_dates(series: PriceSeries) -> list[date]:
    """IST session date of every bar.

    Keyed by IST rather than UTC date because NSE bars stamped at midnight IST are stored at
    18:30 UTC on the previous day: a UTC cutoff would hand a strategy the next session's bar.
    """
    from app.core.clock import IST

    if series.is_empty:
        return []
    index = series.frame.index
    if index.tz is None:
        index = index.tz_localize("UTC")
    return [ts.date() for ts in index.tz_convert(IST)]


class ReplayPriceSource:
    """Preloaded histories, served as of one session. Implements `PriceSource`.

    ``at(day)`` is cheap — it shares the loaded data — so a runner makes one per session.
    """

    def __init__(
        self,
        histories: dict[str, PriceSeries],
        *,
        as_of: date | None = None,
        min_lookback_days: int = LIVE_MIN_LOOKBACK_DAYS,
        _dates: dict[str, list[date]] | None = None,
    ) -> None:
        self._histories = histories
        self._dates = _dates if _dates is not None else {
            symbol: session_dates(series) for symbol, series in histories.items()
        }
        self.as_of = as_of
        self._min_lookback = min_lookback_days

    def at(self, as_of: date) -> ReplayPriceSource:
        return ReplayPriceSource(
            self._histories,
            as_of=as_of,
            min_lookback_days=self._min_lookback,
            _dates=self._dates,
        )

    def history(
        self,
        instrument: Instrument,
        *,
        interval: Interval = "1d",
        lookback_days: int = 400,
    ) -> PriceSeries:
        from bisect import bisect_left, bisect_right
        from datetime import timedelta

        series = self._histories.get(instrument.symbol)
        if series is None or series.is_empty or self.as_of is None:
            return empty_series(instrument, interval)
        dates = self._dates[instrument.symbol]
        end = bisect_right(dates, self.as_of)
        window = max(lookback_days, self._min_lookback)
        start = bisect_left(dates, self.as_of - timedelta(days=window))
        frame = series.frame.iloc[start:end]
        if frame.empty:
            return empty_series(instrument, interval)
        if interval == "1wk":
            from app.strategies.indicators import to_weekly

            frame = to_weekly(frame)
        return PriceSeries(
            instrument=instrument,
            interval=interval,
            frame=frame,
            source=series.source,
            fetched_at=series.fetched_at,
        )


#: SEBI LODR Regulation 33: quarterly results within 45 days of the quarter's end; the last
#: quarter of the financial year (March) with the annual results, within 60 days.
FILING_LAG_DAYS = 45
FILING_LAG_DAYS_YEAR_END = 60


def filed_by(period_end: date) -> date:
    """The latest date a quarter's results were due to be published."""
    from datetime import timedelta

    lag = FILING_LAG_DAYS_YEAR_END if period_end.month == 3 else FILING_LAG_DAYS
    return period_end + timedelta(days=lag)


@dataclass
class AsOfFundamentalsSource:
    """Quarterly fundamentals as they could have been known on ``as_of``.

    A quarter is visible only once its filing deadline has passed. Using the deadline rather
    than the actual announcement date is conservative — most companies file earlier — and it
    is the only date available without an announcements history. Implements
    `FundamentalsSource`.
    """

    inner: object
    as_of: date

    def quarterly(self, instrument: Instrument):
        from app.data.fundamentals import QuarterlyFundamentals, empty

        try:
            full = self.inner.quarterly(instrument)
        except Exception as exc:  # pragma: no cover - sources are contracted not to raise
            log.warning("as-of fundamentals failed for %s: %s", instrument.symbol, exc)
            return empty(instrument.symbol)
        eps = tuple(p for p in full.eps if filed_by(p.period_end) <= self.as_of)
        revenue = tuple(p for p in full.revenue if filed_by(p.period_end) <= self.as_of)
        return QuarterlyFundamentals(
            symbol=full.symbol,
            eps=eps,
            revenue=revenue,
            source_ref=f"{full.source_ref}&as_of={self.as_of.isoformat()}" if full.source_ref
            else "",
        )
