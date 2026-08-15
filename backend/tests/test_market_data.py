"""Price sources, caching and the universe.

Every test here runs offline. A suite that depends on a third-party endpoint fails for reasons
unrelated to the code, and market data changes daily, so any assertion about real fetched
values would be non-deterministic by construction.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from app.data.cache import CachingPriceSource
from app.data.fake import FakePriceSource, StaticPriceSource
from app.data.protocols import PriceSource, UniverseSource
from app.data.universe import NseUniverseSource, blocked_symbols
from app.data.yfinance_source import YFinancePriceSource
from app.domain.instrument import Instrument

RELIANCE = Instrument("RELIANCE")
TCS = Instrument("TCS")


def _frame(rows: int = 3) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "Open": [10.0 + i for i in range(rows)],
            "High": [12.0 + i for i in range(rows)],
            "Low": [9.0 + i for i in range(rows)],
            "Close": [11.0 + i for i in range(rows)],
            "Volume": [100 * (i + 1) for i in range(rows)],
        }
    )
    frame.index = pd.date_range("2026-08-01", periods=rows, freq="D")
    return frame


class RecordingDownloader:
    """Stands in for yfinance.download, recording how it was called."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, *, ticker: str, period: str, interval: str):
        self.calls.append({"ticker": ticker, "period": period, "interval": interval})
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else _frame()


class TestYFinanceSource:
    def test_returns_a_validated_series(self) -> None:
        source = YFinancePriceSource(downloader=RecordingDownloader())

        series = source.history(RELIANCE)

        assert not series.is_empty
        assert series.source == "yfinance"
        assert list(series.frame.columns) == ["open", "high", "low", "close", "volume"]

    def test_symbol_mapped_to_provider_form(self) -> None:
        downloader = RecordingDownloader()

        YFinancePriceSource(downloader=downloader).history(RELIANCE)

        assert downloader.calls[0]["ticker"] == "RELIANCE.NS"

    def test_provider_failure_returns_empty_and_never_raises(self) -> None:
        source = YFinancePriceSource(downloader=RecordingDownloader(error=RuntimeError("boom")))

        series = source.history(RELIANCE)

        assert series.is_empty

    def test_empty_provider_result_returns_empty(self) -> None:
        source = YFinancePriceSource(downloader=RecordingDownloader(result=pd.DataFrame()))

        assert source.history(RELIANCE).is_empty

    def test_none_provider_result_returns_empty(self) -> None:
        source = YFinancePriceSource(downloader=RecordingDownloader(result=None))
        source._downloader = lambda **_: None  # type: ignore[assignment]

        assert source.history(RELIANCE).is_empty

    def test_unusable_shape_returns_empty_rather_than_raising(self) -> None:
        """A provider contract change should degrade a scan, not crash it."""
        broken = _frame().drop(columns=["Volume"])
        source = YFinancePriceSource(downloader=RecordingDownloader(result=broken))

        assert source.history(RELIANCE).is_empty

    def test_lookback_floor_applied(self) -> None:
        """Short windows return too few bars for a 200-day moving average."""
        downloader = RecordingDownloader()

        YFinancePriceSource(downloader=downloader).history(RELIANCE, lookback_days=30)

        assert downloader.calls[0]["period"] == "400d"

    def test_weekly_interval_passed_through(self) -> None:
        downloader = RecordingDownloader()

        YFinancePriceSource(downloader=downloader).history(RELIANCE, interval="1wk")

        assert downloader.calls[0]["interval"] == "1wk"

    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(YFinancePriceSource(downloader=RecordingDownloader()), PriceSource)


class TestCachingLayer:
    def test_first_call_delegates_and_writes(self, tmp_path: Path) -> None:
        downloader = RecordingDownloader()
        cached = CachingPriceSource(YFinancePriceSource(downloader=downloader), cache_dir=tmp_path)

        series = cached.history(RELIANCE)

        assert not series.is_empty
        assert len(downloader.calls) == 1
        assert list(tmp_path.glob("*.parquet"))

    def test_fresh_entry_served_without_calling_the_source(self, tmp_path: Path) -> None:
        downloader = RecordingDownloader()
        cached = CachingPriceSource(YFinancePriceSource(downloader=downloader), cache_dir=tmp_path)
        cached.history(RELIANCE)

        second = cached.history(RELIANCE)

        assert len(downloader.calls) == 1  # not called again
        assert second.source == "cache"

    def test_expired_entry_refetched(self, tmp_path: Path) -> None:
        downloader = RecordingDownloader()
        cached = CachingPriceSource(
            YFinancePriceSource(downloader=downloader),
            cache_dir=tmp_path,
            ttl_seconds={"1d": 0},
        )
        cached.history(RELIANCE)
        time.sleep(0.01)

        second = cached.history(RELIANCE)

        assert len(downloader.calls) == 2
        assert second.source == "yfinance"

    def test_stale_entry_served_when_the_provider_fails(self, tmp_path: Path) -> None:
        """An expired bar is information; an empty frame is not."""
        good = CachingPriceSource(
            YFinancePriceSource(downloader=RecordingDownloader()), cache_dir=tmp_path
        )
        good.history(RELIANCE)

        broken = CachingPriceSource(
            YFinancePriceSource(downloader=RecordingDownloader(error=RuntimeError("down"))),
            cache_dir=tmp_path,
            ttl_seconds={"1d": 0},
        )
        series = broken.history(RELIANCE)

        assert not series.is_empty
        assert series.source == "cache"

    def test_provider_fails_with_nothing_cached(self, tmp_path: Path) -> None:
        cached = CachingPriceSource(
            YFinancePriceSource(downloader=RecordingDownloader(error=RuntimeError("down"))),
            cache_dir=tmp_path,
        )

        assert cached.history(RELIANCE).is_empty

    def test_disabled_cache_touches_no_filesystem(self, tmp_path: Path) -> None:
        target = tmp_path / "unused"
        downloader = RecordingDownloader()
        cached = CachingPriceSource(
            YFinancePriceSource(downloader=downloader), cache_dir=target, enabled=False
        )

        cached.history(RELIANCE)
        cached.history(RELIANCE)

        assert len(downloader.calls) == 2
        assert not target.exists()

    def test_intervals_cached_separately(self, tmp_path: Path) -> None:
        downloader = RecordingDownloader()
        cached = CachingPriceSource(YFinancePriceSource(downloader=downloader), cache_dir=tmp_path)

        cached.history(RELIANCE, interval="1d")
        cached.history(RELIANCE, interval="1wk")

        assert len(downloader.calls) == 2
        assert len(list(tmp_path.glob("*.parquet"))) == 2

    def test_corrupt_entry_treated_as_a_miss(self, tmp_path: Path) -> None:
        (tmp_path / "RELIANCE_1d.parquet").write_text("not parquet at all")
        downloader = RecordingDownloader()
        cached = CachingPriceSource(YFinancePriceSource(downloader=downloader), cache_dir=tmp_path)

        series = cached.history(RELIANCE)

        assert not series.is_empty
        assert len(downloader.calls) == 1


class TestUniverse:
    CSV = (
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        "Reliance Industries,Oil Gas,RELIANCE,EQ,INE002A01018\n"
        "Tata Consultancy,IT,TCS,EQ,INE467B01029\n"
        "Vedanta,Metals,VEDL,EQ,INE205A01025\n"
    )

    def test_live_snapshot_labelled_and_parsed(self) -> None:
        source = NseUniverseSource(fetcher=lambda url: self.CSV)

        snapshot = source.snapshot()

        assert snapshot.origin == "live"
        assert "RELIANCE" in snapshot.symbols
        assert snapshot.instruments[0].sector == "Oil Gas"

    def test_blocklisted_symbol_removed_from_live_list(self) -> None:
        source = NseUniverseSource(fetcher=lambda url: self.CSV)

        snapshot = source.snapshot()

        assert "VEDL" in blocked_symbols()
        assert "VEDL" not in snapshot.symbols
        assert "VEDL" in snapshot.excluded

    def test_fetch_failure_falls_back_and_says_so(self) -> None:
        """A universe that silently shrank is indistinguishable from an index change."""

        def explode(url: str) -> str:
            raise RuntimeError("NSE said 403")

        snapshot = NseUniverseSource(fetcher=explode).snapshot()

        assert snapshot.origin == "fallback"
        assert len(snapshot) > 100

    def test_empty_csv_treated_as_failure(self) -> None:
        snapshot = NseUniverseSource(fetcher=lambda url: "Company Name,Symbol\n").snapshot()

        assert snapshot.origin == "fallback"

    def test_blocklist_applied_to_the_fallback_too(self) -> None:
        def explode(url: str) -> str:
            raise RuntimeError("down")

        snapshot = NseUniverseSource(fetcher=explode).snapshot()

        assert not (set(snapshot.symbols) & blocked_symbols())

    def test_header_casing_tolerated(self) -> None:
        odd = "COMPANY NAME,INDUSTRY,SYMBOL\nReliance,Oil,RELIANCE\n"

        snapshot = NseUniverseSource(fetcher=lambda url: odd).snapshot()

        assert snapshot.origin == "live"
        assert snapshot.symbols == ("RELIANCE",)

    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(NseUniverseSource(fetcher=lambda url: self.CSV), UniverseSource)


class TestFakeSource:
    def test_deterministic_for_the_same_instrument(self) -> None:
        a = FakePriceSource().history(RELIANCE)
        b = FakePriceSource().history(RELIANCE)

        pd.testing.assert_frame_equal(a.frame, b.frame)

    def test_different_instruments_differ(self) -> None:
        a = FakePriceSource().history(RELIANCE)
        b = FakePriceSource().history(TCS)

        assert not a.frame["close"].equals(b.frame["close"])

    def test_produces_a_valid_series(self) -> None:
        series = FakePriceSource(bars=250).history(RELIANCE)

        assert len(series) == 250
        assert series.source == "fake"
        assert (series.frame["high"] >= series.frame["low"]).all()
        assert (series.frame["volume"] > 0).all()

    def test_unknown_symbol_returns_empty_when_restricted(self) -> None:
        source = FakePriceSource(known={"RELIANCE"})

        assert source.history(RELIANCE).is_empty is False
        assert source.history(TCS).is_empty is True

    def test_static_source_serves_supplied_frames(self) -> None:
        source = StaticPriceSource({"RELIANCE": _frame(5)})

        assert len(source.history(RELIANCE)) == 5
        assert source.history(TCS).is_empty

    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(FakePriceSource(), PriceSource)
        assert isinstance(StaticPriceSource({}), PriceSource)


class TestOfflineGuarantee:
    def test_no_data_module_imports_a_network_client_at_module_scope(self) -> None:
        """requests and yfinance are imported inside functions so importing app.data is cheap
        and offline — and so tests cannot accidentally reach the network via an import."""
        import ast

        root = Path(__file__).resolve().parents[1] / "app" / "data"
        offenders = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in tree.body:  # module level only
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                if {"yfinance", "requests"} & set(names):
                    offenders.append(path.name)

        assert offenders == []
