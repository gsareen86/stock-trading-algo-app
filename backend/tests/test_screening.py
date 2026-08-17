"""Eligibility screening.

The distinction under test: a screen decides **whether to look at a name at all**. It is not
a strategy's assessability gate and emphatically not a quality score — and it never ranks.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app.data.protocols import UniverseSnapshot
from app.data.surveillance import STALE_AFTER_DAYS, SurveillanceList
from app.domain.instrument import Instrument
from app.domain.prices import build_series, empty_series
from app.screening import filters
from app.screening.screener import ScreenCriteria, Screener

TODAY = date(2026, 8, 17)
RELIANCE = Instrument("RELIANCE")


def _series(instrument: Instrument, closes: list[float], volumes: list[int]):
    index = pd.DatetimeIndex(
        [datetime(2026, 1, 1, tzinfo=UTC) + pd.Timedelta(days=i) for i in range(len(closes))]
    )
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": volumes,
        },
        index=index,
    )
    return build_series(instrument, "1d", frame, source="test")


def _flat(instrument: Instrument, close: float, volume: int, n: int = 250):
    return _series(instrument, [close] * n, [volume] * n)


class StaticPrices:
    """Serves a fixed series per symbol; anything unseeded is empty."""

    def __init__(self, mapping: dict[str, object]) -> None:
        self._mapping = mapping

    def history(self, instrument, *, interval="1d", lookback_days=400):
        return self._mapping.get(instrument.symbol) or empty_series(instrument, interval)


EMPTY_LIST = SurveillanceList(frozenset(), frozenset(), TODAY, "test")


class TestTurnoverNotVolume:
    def test_thin_stock_fails_the_turnover_floor(self) -> None:
        """`volume > 0` passes a stock that traded eleven shares; turnover is the real unit."""
        series = _flat(RELIANCE, close=50.0, volume=11)

        result = filters.check_turnover(RELIANCE, series, minimum=5_00_00_000.0)

        assert result.passed is False
        assert "below" in result.reason

    def test_liquid_stock_passes(self) -> None:
        series = _flat(RELIANCE, close=1400.0, volume=1_000_000)

        result = filters.check_turnover(RELIANCE, series, minimum=5_00_00_000.0)

        assert result.passed is True

    def test_median_resists_a_single_block_deal(self) -> None:
        """A mean would let one huge day qualify a name that is otherwise untradeable."""
        closes = [100.0] * 20
        volumes = [1_000] * 19 + [500_000_000]
        series = _series(RELIANCE, closes, volumes)

        turnover = filters.median_turnover(series)

        assert turnover == pytest.approx(100_000.0)
        assert filters.check_turnover(RELIANCE, series).passed is False

    def test_same_share_count_different_prices_differ(self) -> None:
        """A hundred thousand shares of a ₹3 stock is not the same position as of a ₹3,000 one."""
        cheap = filters.median_turnover(_flat(RELIANCE, 3.0, 100_000))
        dear = filters.median_turnover(_flat(RELIANCE, 3000.0, 100_000))

        assert dear == pytest.approx(cheap * 1000)

    def test_no_history_is_not_a_pass(self) -> None:
        result = filters.check_turnover(RELIANCE, empty_series(RELIANCE, "1d"))

        assert result.passed is False
        assert result.evidence.value is None


class TestOtherFilters:
    def test_short_history_fails(self) -> None:
        series = _flat(RELIANCE, 100.0, 1_000_000, n=50)

        assert filters.check_history(RELIANCE, series, min_bars=200).passed is False

    def test_sufficient_history_passes(self) -> None:
        series = _flat(RELIANCE, 100.0, 1_000_000, n=250)

        assert filters.check_history(RELIANCE, series, min_bars=200).passed is True

    def test_penny_stock_fails_the_price_floor(self) -> None:
        series = _flat(RELIANCE, 3.0, 1_000_000)

        assert filters.check_price(RELIANCE, series, minimum=20.0).passed is False

    def test_evidence_carries_value_threshold_and_source(self) -> None:
        """An exclusion is a claim about a stock; an unexplained claim is not reviewable."""
        series = _flat(RELIANCE, 3.0, 1_000_000)

        row = filters.check_price(RELIANCE, series, minimum=20.0).evidence

        assert row.value == pytest.approx(3.0)
        assert row.threshold == pytest.approx(20.0)
        assert row.source_ref.startswith("price://RELIANCE")
        assert row.unit == "INR"


class TestSurveillance:
    def test_listed_name_is_excluded(self) -> None:
        listed = SurveillanceList(frozenset({"YESBANK"}), frozenset(), TODAY, "t")

        result = filters.check_surveillance(Instrument("YESBANK"), listed, TODAY)

        assert result.passed is False
        assert "ASM" in result.reason

    def test_gsm_is_reported_distinctly(self) -> None:
        listed = SurveillanceList(frozenset(), frozenset({"SINTEX"}), TODAY, "t")

        assert listed.measure_for("SINTEX") == "GSM"

    def test_unlisted_name_passes(self) -> None:
        assert filters.check_surveillance(RELIANCE, EMPTY_LIST, TODAY).passed is True

    def test_stale_list_is_reported(self) -> None:
        """A stale list under-excludes silently unless its age is visible."""
        old = SurveillanceList(frozenset(), frozenset(), date(2020, 1, 1), "t")

        assert old.is_stale(TODAY) is True
        assert old.as_dict(TODAY)["stale"] is True

    def test_unknown_age_counts_as_stale(self) -> None:
        """It cannot be shown to be current, so it is not treated as current."""
        unknown = SurveillanceList(frozenset(), frozenset(), None, "t")

        assert unknown.is_stale(TODAY) is True

    def test_fresh_list_is_not_stale(self) -> None:
        fresh = SurveillanceList(frozenset(), frozenset(), TODAY, "t")

        assert fresh.is_stale(TODAY) is False

    def test_staleness_boundary(self) -> None:
        from datetime import timedelta

        edge = SurveillanceList(
            frozenset(), frozenset(), TODAY - timedelta(days=STALE_AFTER_DAYS), "t"
        )

        assert edge.is_stale(TODAY) is False

    def test_bundled_file_loads(self) -> None:
        from app.data.surveillance import load

        listed = load()

        assert listed.symbols
        assert listed.as_of is not None


class TestScreener:
    def _snapshot(self, *symbols: str) -> UniverseSnapshot:
        return UniverseSnapshot(
            instruments=tuple(Instrument(s) for s in symbols),
            origin="fallback",
            index_name="TEST",
        )

    def test_eligible_and_excluded_are_both_reported(self) -> None:
        prices = StaticPrices(
            {
                "LIQUID": _flat(Instrument("LIQUID"), 1400.0, 1_000_000),
                "THIN": _flat(Instrument("THIN"), 50.0, 11),
            }
        )
        result = Screener(prices, EMPTY_LIST).run(self._snapshot("LIQUID", "THIN"), today=TODAY)

        assert result.symbols == ["LIQUID"]
        assert [e.symbol for e in result.excluded] == ["THIN"]
        assert result.excluded[0].filter_id == "turnover"

    def test_every_exclusion_names_its_filter_and_value(self) -> None:
        prices = StaticPrices({"THIN": _flat(Instrument("THIN"), 50.0, 11)})

        result = Screener(prices, EMPTY_LIST).run(self._snapshot("THIN"), today=TODAY)

        payload = result.excluded[0].as_dict()
        assert payload["filter"] == "turnover"
        assert payload["evidence"]["threshold"] is not None
        assert payload["evidence"]["source_ref"]

    def test_per_filter_counts_make_a_small_result_diagnosable(self) -> None:
        prices = StaticPrices(
            {
                "THIN": _flat(Instrument("THIN"), 50.0, 11),
                "PENNY": _flat(Instrument("PENNY"), 3.0, 100_000_000),
            }
        )
        result = Screener(prices, EMPTY_LIST).run(self._snapshot("THIN", "PENNY"), today=TODAY)

        assert result.excluded_by() == {"turnover": 1, "price": 1}

    def test_missing_history_is_an_exclusion_not_a_crash(self) -> None:
        result = Screener(StaticPrices({}), EMPTY_LIST).run(self._snapshot("GHOST"), today=TODAY)

        assert result.symbols == []
        assert result.excluded[0].filter_id == "history"

    def test_surveillance_costs_no_price_fetch(self) -> None:
        """Checked first because it needs no data — a flagged name should cost nothing."""

        class CountingPrices(StaticPrices):
            def __init__(self):
                super().__init__({})
                self.calls = 0

            def history(self, instrument, *, interval="1d", lookback_days=400):
                self.calls += 1
                return super().history(instrument, interval=interval)

        prices = CountingPrices()
        listed = SurveillanceList(frozenset({"YESBANK"}), frozenset(), TODAY, "t")

        Screener(prices, listed).run(self._snapshot("YESBANK"), today=TODAY)

        assert prices.calls == 0

    def test_screen_preserves_universe_order(self) -> None:
        """A screen decides eligibility, not merit — reordering would be a score by stealth."""
        prices = StaticPrices(
            {s: _flat(Instrument(s), 1400.0, 1_000_000) for s in ("CCC", "AAA", "BBB")}
        )

        result = Screener(prices, EMPTY_LIST).run(self._snapshot("CCC", "AAA", "BBB"), today=TODAY)

        assert result.symbols == ["CCC", "AAA", "BBB"]

    def test_limit_truncates_without_ranking(self) -> None:
        prices = StaticPrices(
            {s: _flat(Instrument(s), 1400.0, 1_000_000) for s in ("CCC", "AAA", "BBB")}
        )

        result = Screener(prices, EMPTY_LIST).run(
            self._snapshot("CCC", "AAA", "BBB"), ScreenCriteria(limit=2), today=TODAY
        )

        assert result.symbols == ["CCC", "AAA"]
        assert result.excluded_by() == {"limit": 1}

    def test_result_reports_universe_origin(self) -> None:
        """A universe that silently fell back is otherwise invisible."""
        result = Screener(StaticPrices({}), EMPTY_LIST).run(self._snapshot("X"), today=TODAY)

        assert result.universe_origin == "fallback"

    def test_no_ranking_function_exists(self) -> None:
        """Guard: ordering survivors by quality would rebuild the scorecard one layer up."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app" / "screening"
        pattern = re.compile(r"def\s+(rank|score|sort_by_quality|best)\w*", re.I)
        offenders = [p.name for p in root.rglob("*.py") if pattern.search(p.read_text("utf-8"))]

        assert offenders == []


class TestScreenNode:
    """The screen inside a cycle."""

    @staticmethod
    def _graph(prices, universe, criteria=None):
        from app.agents.graph import build_graph
        from app.agents.toolbelt import Toolbelt
        from app.data.fundamentals import StaticFundamentalsSource
        from app.strategies.protocols import StrategyContext
        from app.strategies.registry import StrategyRegistry
        from app.tools.registry import ToolRegistry

        class Silent:
            async def complete(self, *, task, messages, schema=None, tools=None):
                return None

        return build_graph(
            registry=StrategyRegistry.discover(),
            strategy_context=StrategyContext(
                price_source=prices, fundamentals_source=StaticFundamentalsSource({})
            ),
            price_source=prices,
            toolbelt=Toolbelt(registry=ToolRegistry.discover()),
            gateway=Silent(),
            max_tool_rounds=0,
            screener=Screener(prices, EMPTY_LIST),
            universe_source=universe,
            screen_criteria=criteria or ScreenCriteria(),
        )

    @staticmethod
    def _universe(*symbols):
        class Source:
            def snapshot(self):
                return UniverseSnapshot(
                    instruments=tuple(Instrument(s) for s in symbols),
                    origin="fallback",
                    index_name="TEST",
                )

        return Source()

    async def test_screen_narrows_what_the_strategies_evaluate(self) -> None:
        from app.agents.graph import run_cycle
        from app.data.fake import FakePriceSource

        prices = FakePriceSource(bars=400)
        graph = self._graph(prices, self._universe("RELIANCE", "TCS"))

        result = await run_cycle(
            graph,
            {"cycle_id": "c", "as_of": datetime(2026, 8, 17, tzinfo=UTC),
             "instruments": [], "narrate": False, "verdicts": [], "notes": []},
        )

        assert result["screen"] is not None
        assert result["screen"]["considered"] == 2
        # Four strategies over however many names survived — the screen decides the breadth.
        eligible = result["screen"]["eligible_count"]
        assert eligible > 0
        assert len(result["verdicts"]) == 4 * eligible
        assert {v.ticker for v in result["verdicts"]} == set(result["screen"]["eligible"])

    async def test_explicit_symbols_bypass_the_screen(self) -> None:
        """Asking about a name should answer about it, even if it would not have survived."""
        from app.agents.graph import run_cycle
        from app.data.fake import FakePriceSource

        prices = FakePriceSource(bars=400)
        graph = self._graph(prices, self._universe("RELIANCE"))

        result = await run_cycle(
            graph,
            {"cycle_id": "c", "as_of": datetime(2026, 8, 17, tzinfo=UTC),
             "instruments": [Instrument("YESBANK")], "narrate": False,
             "verdicts": [], "notes": []},
        )

        assert result["screen"] is None
        assert any("skipped" in n for n in result["notes"])
        assert {v.ticker for v in result["verdicts"]} == {"YESBANK"}


class TestScreeningApi:
    @staticmethod
    def _client(settings):
        from fastapi.testclient import TestClient

        from app.data.fake import FakePriceSource
        from app.data.fundamentals import StaticFundamentalsSource
        from app.main import create_app

        app = create_app(settings)
        app.state.price_source = FakePriceSource(bars=400)
        app.state.fundamentals_source = StaticFundamentalsSource({})

        class Universe:
            def snapshot(self):
                return UniverseSnapshot(
                    instruments=(Instrument("RELIANCE"), Instrument("TCS")),
                    origin="fallback",
                    index_name="TEST",
                    excluded=("VEDL",),
                )

        app.state.universe_source = Universe()
        return TestClient(app)

    def test_universe_reports_origin_and_exclusions(self, settings) -> None:
        body = self._client(settings).get("/universe").json()

        assert body["origin"] == "fallback"
        assert body["excluded"] == ["VEDL"]
        assert body["count"] == 2

    def test_screen_returns_eligible_and_reasons(self, settings) -> None:
        body = self._client(settings).post("/screen", json={}).json()

        assert body["considered"] == 2
        assert "excluded_by" in body
        assert "surveillance" in body

    def test_exclusions_can_be_omitted_but_counts_remain(self, settings) -> None:
        body = self._client(settings).post(
            "/screen", json={"include_exclusions": False}
        ).json()

        assert "excluded" not in body
        assert "excluded_by" in body

    def test_screen_reports_surveillance_age(self, settings) -> None:
        body = self._client(settings).post("/screen", json={}).json()

        assert "stale" in body["surveillance"]
        assert "as_of" in body["surveillance"]
