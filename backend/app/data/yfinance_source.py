"""Prices from yfinance.

Keeps the hard-won provider knowledge and drops the
entanglement: no module-level config, no intraday intervals, no cache logic interleaved with
the download, and the frame validated before it leaves.

yfinance is an unofficial interface that changes shape without notice — hence validating
what comes back rather than trusting it, and hence returning an empty series rather than
raising when it misbehaves.
"""

from __future__ import annotations

import logging

import pandas as pd

from app.domain.instrument import Instrument
from app.domain.prices import Interval, PriceSeries, PriceSeriesError, build_series, empty_series

log = logging.getLogger(__name__)


class YFinancePriceSource:
    """Implements :class:`app.data.protocols.PriceSource`."""

    #: yfinance needs a `period` string; a generous floor avoids short windows returning
    #: too few bars for a 200-day moving average, which every strategy here needs.
    MIN_DAILY_LOOKBACK = 400

    def __init__(self, downloader=None) -> None:
        """``downloader`` is injectable so tests can replay a recorded frame offline."""
        self._downloader = downloader

    def _download(self, ticker: str, period: str, interval: str) -> pd.DataFrame:
        if self._downloader is not None:
            return self._downloader(ticker=ticker, period=period, interval=interval)

        import yfinance as yf

        return yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=False,
        )

    def history(
        self,
        instrument: Instrument,
        *,
        interval: Interval = "1d",
        lookback_days: int = 400,
    ) -> PriceSeries:
        ticker = instrument.yf_ticker
        days = max(lookback_days, self.MIN_DAILY_LOOKBACK)
        period = f"{days}d"

        try:
            raw = self._download(ticker=ticker, period=period, interval=interval)
        except Exception as exc:
            log.warning("price fetch failed for %s (%s): %s", instrument.symbol, interval, exc)
            return empty_series(instrument, interval)

        if raw is None or getattr(raw, "empty", True):
            log.debug("no price data returned for %s (%s)", instrument.symbol, interval)
            return empty_series(instrument, interval)

        try:
            return build_series(instrument, interval, raw, source="yfinance")
        except PriceSeriesError as exc:
            # A shape we cannot repair means the provider's contract changed. Loud in the log,
            # empty to the caller — a scan should degrade, not crash.
            log.warning("unusable price frame for %s: %s", instrument.symbol, exc)
            return empty_series(instrument, interval)
