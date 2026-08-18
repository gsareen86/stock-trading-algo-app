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
