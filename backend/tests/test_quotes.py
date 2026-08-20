"""Live index quotes, and the boundary that keeps them out of a verdict.

Carries the quote half of `research-data-sources`. Every test runs offline against a payload
recorded from NSE's own `/api/allIndices` — the same injectable-fetcher contract the universe
source and the tool handlers use.

The tests that matter most here are not the parsing ones. They are the two asserting that a
quote cannot reach a strategy: verdicts are required to reproduce with the model switched off,
and a live reading leaking into a price series would break that with nothing in the evidence
to explain the change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.data.nse_quotes import INDEX_NAME_BY_SYMBOL, NseIndexQuoteSource
from app.data.protocols import PriceSource, QuoteSource
from app.domain.instrument import Instrument

FIXTURE = Path(__file__).parent / "fixtures" / "nse" / "all_indices.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text("utf-8"))


@pytest.fixture
def source(payload: dict[str, Any]) -> NseIndexQuoteSource:
    return NseIndexQuoteSource(fetcher=lambda url: payload)


class TestRecordedPayloadIsReal:
    def test_fixture_came_from_the_exchange(self, payload: dict[str, Any]) -> None:
        """Recorded, not invented — the field names are NSE's own."""
        row = payload["data"][0]
        for field in ("index", "last", "previousClose", "perChange30d", "advances"):
            assert field in row


class TestParsing:
    def test_an_index_resolves_to_its_level(self, source: NseIndexQuoteSource) -> None:
        nifty = source.index_quote("NIFTY 50")

        assert nifty is not None
        assert nifty.quote.last > 0
        assert nifty.quote.source == "nse"

    def test_the_broad_market_index_is_available(self, source: NseIndexQuoteSource) -> None:
        """NIFTY 500 is the point of reading NSE directly — no provider served it before."""
        assert source.index_quote("NIFTY 500") is not None

    def test_change_is_derived_from_the_previous_close(
        self, source: NseIndexQuoteSource
    ) -> None:
        nifty = source.index_quote("NIFTY 50")

        expected = nifty.quote.last - nifty.quote.previous_close
        assert nifty.quote.change == pytest.approx(expected)
        assert nifty.quote.change_pct == pytest.approx(expected / nifty.quote.previous_close * 100)

    def test_breadth_is_carried_through(self, source: NseIndexQuoteSource) -> None:
        """An index up 0.6% on 39 advances is a different fact from one up 0.6% on 8."""
        nifty = source.index_quote("NIFTY 50")

        assert nifty.advances is not None
        assert nifty.declines is not None

    def test_lookup_is_case_and_space_insensitive(self, source: NseIndexQuoteSource) -> None:
        assert source.index_quote("nifty 50") is not None
        assert source.index_quote("  NIFTY 50  ") is not None

    def test_an_unknown_index_is_none_not_an_error(self, source: NseIndexQuoteSource) -> None:
        assert source.index_quote("NIFTY NONEXISTENT") is None

    def test_a_row_without_a_level_is_skipped(self) -> None:
        source = NseIndexQuoteSource(
            fetcher=lambda url: {"data": [{"index": "BROKEN", "last": None}]}
        )
        assert source.all_indices() == {}


class TestSymbolTranslation:
    def test_the_platform_symbol_resolves(self, source: NseIndexQuoteSource) -> None:
        """`^NSEI` and `NIFTY 50` name the same index; the translation lives at the seam."""
        quote = source.quote(Instrument("^NSEI"))

        assert quote is not None
        assert quote.symbol == "NIFTY 50"

    def test_an_equity_is_not_quotable_and_says_so(self, source: NseIndexQuoteSource) -> None:
        """NSE refuses per-stock quotes to a plain client — an honest None, never a guess."""
        assert source.quote(Instrument("RELIANCE")) is None

    def test_every_mapped_symbol_is_an_index_symbol(self) -> None:
        for symbol in INDEX_NAME_BY_SYMBOL:
            assert Instrument(symbol).is_index


class TestDegradation:
    def test_a_failing_provider_returns_empty_rather_than_raising(self) -> None:
        def boom(url: str):
            raise RuntimeError("blocked")

        assert NseIndexQuoteSource(fetcher=boom).all_indices() == {}

    def test_a_blocked_provider_serves_cache_labelled_as_cache(
        self, payload: dict[str, Any]
    ) -> None:
        """A stale level is information; an empty frame is not. Labelled, so age is explicit."""
        state = {"fail": False}

        def flaky(url: str):
            if state["fail"]:
                raise RuntimeError("blocked")
            return payload

        source = NseIndexQuoteSource(fetcher=flaky, ttl_seconds=0.0)
        assert source.index_quote("NIFTY 50").quote.source == "nse"

        state["fail"] = True
        cached = source.index_quote("NIFTY 50")

        assert cached is not None
        assert cached.quote.source == "cache"

    def test_an_empty_payload_does_not_wipe_a_good_cache(
        self, payload: dict[str, Any]
    ) -> None:
        state = {"empty": False}

        def flaky(url: str):
            return {"data": []} if state["empty"] else payload

        source = NseIndexQuoteSource(fetcher=flaky, ttl_seconds=0.0)
        source.all_indices()
        state["empty"] = True

        assert source.index_quote("NIFTY 50") is not None


class TestCaching:
    def test_one_payload_answers_every_index(self, payload: dict[str, Any]) -> None:
        """The whole reason to read NSE this way: a six-panel page costs one request."""
        calls: list[str] = []

        def counted(url: str):
            calls.append(url)
            return payload

        source = NseIndexQuoteSource(fetcher=counted, ttl_seconds=600.0)
        for name in ("NIFTY 50", "NIFTY 500", "NIFTY IT", "NIFTY BANK", "NIFTY AUTO"):
            source.index_quote(name)

        assert len(calls) == 1

    def test_an_expired_cache_refetches(self, payload: dict[str, Any]) -> None:
        calls: list[str] = []

        def counted(url: str):
            calls.append(url)
            return payload

        source = NseIndexQuoteSource(fetcher=counted, ttl_seconds=0.0)
        source.index_quote("NIFTY 50")
        source.index_quote("NIFTY 50")

        assert len(calls) == 2


class TestRateLimiting:
    def test_requests_are_spaced(self, payload: dict[str, Any]) -> None:
        """The documented hazard of reading NSE directly is being blocked for asking often."""
        import time

        interval = 0.05
        source = NseIndexQuoteSource(
            fetcher=lambda url: payload, ttl_seconds=0.0, min_interval_seconds=interval
        )
        # The limiter guards the live path; drive it directly rather than sleeping a suite.
        started = time.monotonic()
        source._limiter.wait()
        source._limiter.wait()
        elapsed = time.monotonic() - started

        # Windows' monotonic clock ticks about every 15ms, so an exact floor comparison on a
        # 50ms sleep is a coin flip. The claim under test is "it waited", not "it waited to
        # the microsecond".
        assert elapsed >= interval * 0.8


class TestQuotesNeverReachAStrategy:
    """The boundary that makes verdicts reproducible. Two ways of asserting the same rule."""

    def test_the_quote_seam_is_not_a_price_seam(self, source: NseIndexQuoteSource) -> None:
        assert isinstance(source, QuoteSource)
        assert not isinstance(source, PriceSource)

    def test_no_strategy_imports_a_quote(self) -> None:
        """A strategy that wanted a live reading would have to import one. None does."""
        from tests.conftest import source_of

        strategies = source_of("strategies")
        assert "QuoteSource" not in strategies
        assert "quotes" not in strategies

    def test_a_price_series_cannot_be_built_from_a_quote(self) -> None:
        """`Quote` is deliberately not a bar: no OHLC, so nothing can fold it into a frame."""
        from app.domain.quotes import Quote

        fields = set(Quote.__dataclass_fields__)
        assert not fields & {"open", "high", "low", "close", "volume"}
