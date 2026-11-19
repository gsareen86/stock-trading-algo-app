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

    #: yfinance needs a `period` string; 820 calendar days (~550 trading sessions) satisfies
    #: every strategy's longest lookback including BVM's 1.5-year base + breakout requirement.
    MIN_DAILY_LOOKBACK = 820

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

    def download_batch(
        self,
        instruments: list[Instrument] | tuple[Instrument, ...],
        *,
        interval: Interval = "1d",
        lookback_days: int = 820,
    ) -> dict[str, PriceSeries]:
        """Download OHLCV frames for multiple instruments in a single yfinance batch call."""
        if not instruments:
            return {}
        if self._downloader is not None:
            return {
                inst.symbol: self.history(inst, interval=interval, lookback_days=lookback_days)
                for inst in instruments
            }

        import yfinance as yf

        days = max(lookback_days, self.MIN_DAILY_LOOKBACK)
        period = f"{days}d"
        by_yf = {inst.yf_ticker: inst for inst in instruments}
        tickers = list(by_yf.keys())

        try:
            raw = yf.download(
                tickers,
                period=period,
                interval=interval,
                group_by="ticker",
                progress=False,
                auto_adjust=False,
                threads=True,
            )
        except Exception as exc:
            log.warning("batch price download failed (%d tickers): %s", len(tickers), exc)
            return {}

        if raw is None or getattr(raw, "empty", True):
            return {}

        results: dict[str, PriceSeries] = {}
        is_multi = isinstance(raw.columns, pd.MultiIndex)

        for yf_ticker, inst in by_yf.items():
            try:
                if len(tickers) == 1 and not is_multi:
                    sub = raw
                elif is_multi and yf_ticker in raw.columns.get_level_values(0):
                    sub = raw[yf_ticker]
                elif is_multi and yf_ticker in raw.columns.get_level_values(-1):
                    sub = raw.xs(yf_ticker, axis=1, level=-1)
                else:
                    continue
                sub = sub.dropna(how="all")
                if sub.empty:
                    continue
                results[inst.symbol] = build_series(inst, interval, sub, source="yfinance")
            except (PriceSeriesError, KeyError, Exception) as exc:
                log.debug("batch frame unusable for %s: %s", inst.symbol, exc)
        return results

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
