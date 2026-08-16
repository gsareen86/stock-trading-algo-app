"""Boundary validation for price data.

yfinance is an unofficial interface that changes shape without notice. These assert that
whatever it produces, what crosses the seam has one known shape — so no strategy has to
re-derive it, and none silently works on a frame it misread.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.domain.instrument import Instrument, from_provider_ticker, to_provider_ticker
from app.domain.prices import (
    REQUIRED_COLUMNS,
    PriceSeriesError,
    build_series,
    empty_series,
)

RELIANCE = Instrument("RELIANCE")


def _raw(index=None, **columns) -> pd.DataFrame:
    base = {
        "Open": [10.0, 11.0],
        "High": [12.0, 13.0],
        "Low": [9.0, 10.0],
        "Close": [11.0, 12.0],
        "Volume": [100, 200],
    }
    base.update(columns)
    frame = pd.DataFrame(base)
    frame.index = pd.DatetimeIndex(index or ["2026-08-11", "2026-08-12"])
    return frame


class TestSymbolMapping:
    def test_nse_symbol_suffixed(self) -> None:
        assert to_provider_ticker("RELIANCE") == "RELIANCE.NS"

    def test_already_suffixed_not_double_suffixed(self) -> None:
        assert to_provider_ticker("RELIANCE.NS") == "RELIANCE.NS"
        assert to_provider_ticker("RELIANCE.BO") == "RELIANCE.BO"

    def test_round_trip(self) -> None:
        assert from_provider_ticker(to_provider_ticker("TCS")) == "TCS"

    def test_instrument_exposes_provider_form(self) -> None:
        assert Instrument("TCS").yf_ticker == "TCS.NS"

    def test_index_ticker_is_not_suffixed(self) -> None:
        """Found live: an unsuffixed benchmark resolved to NIFTY50.NS, which does not exist.

        Every fixture before real data used a fake source keyed by the raw symbol string, so
        nothing exercised this translation until it ran against yfinance for the first time.
        """
        assert to_provider_ticker("^NSEI") == "^NSEI"
        assert to_provider_ticker("^nsei") == "^NSEI"
        assert Instrument("^NSEI").yf_ticker == "^NSEI"

    def test_sector_index_tickers_are_not_suffixed(self) -> None:
        for ticker in ("^CNXIT", "^NSEBANK", "^CNXFMCG", "^CNXPHARMA", "^CNXAUTO"):
            assert to_provider_ticker(ticker) == ticker

    def test_is_index_flag(self) -> None:
        assert Instrument("^NSEI").is_index is True
        assert Instrument("RELIANCE").is_index is False

    def test_index_round_trip_is_a_no_op(self) -> None:
        """Indices have no suffix to strip — the round trip must not invent one."""
        assert from_provider_ticker(to_provider_ticker("^NSEI")) == "^NSEI"

    def test_lowercase_symbol_rejected(self) -> None:
        """Normalising silently would make two spellings distinct dict keys that compare unequal."""
        with pytest.raises(ValueError, match="upper-case"):
            Instrument("reliance")

    def test_padded_symbol_rejected(self) -> None:
        with pytest.raises(ValueError):
            Instrument(" TCS ")

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValueError):
            Instrument("")


class TestSchemaNormalisation:
    def test_provider_capitalisation_lowercased(self) -> None:
        series = build_series(RELIANCE, "1d", _raw(), source="yfinance")

        assert list(series.frame.columns) == list(REQUIRED_COLUMNS)

    def test_multiindex_columns_flattened(self) -> None:
        """yfinance returns MultiIndex columns even for a single symbol."""
        frame = _raw()
        frame.columns = pd.MultiIndex.from_product([frame.columns, ["RELIANCE.NS"]])

        series = build_series(RELIANCE, "1d", frame, source="yfinance")

        assert list(series.frame.columns) == list(REQUIRED_COLUMNS)

    def test_rows_with_nulls_dropped(self) -> None:
        frame = _raw(Close=[11.0, None])

        series = build_series(RELIANCE, "1d", frame, source="yfinance")

        assert len(series) == 1

    def test_index_sorted_ascending(self) -> None:
        frame = _raw(index=["2026-08-12", "2026-08-11"])

        series = build_series(RELIANCE, "1d", frame, source="yfinance")

        assert series.frame.index.is_monotonic_increasing

    def test_duplicate_timestamps_collapsed(self) -> None:
        frame = _raw(index=["2026-08-11", "2026-08-11"])

        series = build_series(RELIANCE, "1d", frame, source="yfinance")

        assert len(series) == 1

    def test_naive_index_read_as_utc(self) -> None:
        """Guessing a zone would shift every Indian bar by 5h30m with nothing to catch it."""
        series = build_series(RELIANCE, "1d", _raw(), source="yfinance")

        assert str(series.frame.index.tz) == "UTC"

    def test_aware_index_converted_to_utc(self) -> None:
        frame = _raw()
        frame.index = frame.index.tz_localize("Asia/Kolkata")

        series = build_series(RELIANCE, "1d", frame, source="yfinance")

        assert str(series.frame.index.tz) == "UTC"

    def test_extra_columns_dropped(self) -> None:
        frame = _raw()
        frame["Adj Close"] = [10.5, 11.5]

        series = build_series(RELIANCE, "1d", frame, source="yfinance")

        assert "adj close" not in series.frame.columns


class TestRejectedFrames:
    def test_missing_column_names_it(self) -> None:
        frame = _raw().drop(columns=["Volume"])

        with pytest.raises(PriceSeriesError, match="volume"):
            build_series(RELIANCE, "1d", frame, source="yfinance")

    def test_intraday_interval_rejected(self) -> None:
        """Intraday was dropped from this platform; it should not be constructible."""
        with pytest.raises(PriceSeriesError, match="intraday"):
            build_series(RELIANCE, "15m", _raw(), source="yfinance")  # type: ignore[arg-type]


class TestProvenance:
    def test_source_recorded(self) -> None:
        assert build_series(RELIANCE, "1d", _raw(), source="cache").source == "cache"

    def test_empty_series_is_usable(self) -> None:
        series = empty_series(RELIANCE, "1d")

        assert series.is_empty
        assert len(series) == 0
        assert series.last_close is None
        assert series.last_bar_at is None
        assert list(series.frame.columns) == list(REQUIRED_COLUMNS)

    def test_last_close_and_bar(self) -> None:
        series = build_series(RELIANCE, "1d", _raw(), source="yfinance")

        assert series.last_close == pytest.approx(12.0)
        assert series.last_bar_at is not None
