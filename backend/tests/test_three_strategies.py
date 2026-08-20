"""The three strategies added alongside Minervini, and their shared seams.

Every series is hand-built with a known shape. The point of these is not that some data passes
— it is that a bearish regime lowers conviction without failing a gate, that a missing
fundamentals source blocks only the strategy that needs it, and that a pause retracing past
38.2% fails while a shallower one does not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from app.data.fake import StaticPriceSource
from app.data.fundamentals import (
    QuarterlyFundamentals,
    QuarterPoint,
    StaticFundamentalsSource,
    YFinanceFundamentalsSource,
)
from app.data.sectors import all_sector_indices, resolve
from app.domain.instrument import Instrument
from app.domain.verdict import Stance
from app.strategies.brahma_vishnu_mahesh.strategy import BrahmaVishnuMaheshStrategy
from app.strategies.fun_tech_momentum.strategy import FunTechMomentumStrategy
from app.strategies.indicators import (
    consolidation_tightness,
    fib_retracement_pct,
    find_impulse_leg,
    horizontal_range_breakout,
    to_weekly,
)
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry
from app.strategies.young_momentum.strategy import YoungMomentumStrategy

NOW = datetime(2026, 8, 14, tzinfo=UTC)
TCS = Instrument("TCS", sector="Information Technology")
BENCH = Instrument("NIFTY50")


def frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes or [1_000_000.0] * n,
        },
        index=pd.date_range("2023-01-01", periods=n, freq="D"),
    )


def trend(n: int, start: float = 100.0, daily: float = 0.003) -> list[float]:
    return [start * (1 + daily) ** i for i in range(n)]


def flat(n: int, level: float = 100.0) -> list[float]:
    return [level] * n


class TestFundamentalsSeam:
    def _quarters(self) -> QuarterlyFundamentals:
        return QuarterlyFundamentals(
            symbol="TCS",
            eps=tuple(
                QuarterPoint(date(2026, 6, 30), 30.0)
                if i == 0
                else QuarterPoint(date(2025, 9 - i, 30), 10.0)
                for i in range(5)
            ),
            revenue=(),
            source_ref="fundamentals://test/TCS",
        )

    def test_static_source_returns_what_it_was_given(self) -> None:
        source = StaticFundamentalsSource({"TCS": self._quarters()})

        result = source.quarterly(TCS)

        assert result.eps_at(0) == pytest.approx(30.0)
        assert result.source_ref == "fundamentals://test/TCS"

    def test_unseeded_symbol_is_empty(self) -> None:
        assert StaticFundamentalsSource({}).quarterly(TCS).is_empty

    def test_provider_failure_returns_empty_rather_than_raising(self) -> None:
        def explode(ticker: str):
            raise RuntimeError("blocked")

        assert YFinanceFundamentalsSource(lookup=explode).quarterly(TCS).is_empty

    def test_series_sorted_newest_first(self) -> None:
        """Ordering is part of the contract; a reversed list silently inverts growth tests."""
        statement = pd.DataFrame(
            {
                pd.Timestamp("2025-06-30"): [10.0],
                pd.Timestamp("2026-06-30"): [30.0],
            },
            index=["Basic EPS"],
        )

        result = YFinanceFundamentalsSource(lookup=lambda t: statement).quarterly(TCS)

        assert [p.value for p in result.eps] == [30.0, 10.0]

    def test_missing_rows_yield_empty(self) -> None:
        statement = pd.DataFrame({pd.Timestamp("2026-06-30"): [1.0]}, index=["Something Else"])

        assert YFinanceFundamentalsSource(lookup=lambda t: statement).quarterly(TCS).is_empty


class TestSectorResolution:
    def test_known_industry_maps_to_its_index(self) -> None:
        # "Financial Services" resolved to the banking index until `research-data-sources`,
        # because NIFTY BANK was the closest thing the table held. NSE publishes an actual
        # financial-services index; approximating it away was a lossy answer to a question
        # that now has a precise one.
        assert resolve("Financial Services").key == "FinancialServices"
        assert resolve("Information Technology").key == "IT"

    def test_bank_sub_sectors_resolve_separately(self) -> None:
        """Private and PSU banks trade differently enough that one index for both hides it."""
        assert resolve("Private Sector Bank").key == "PrivateBank"
        assert resolve("Public Sector Bank").key == "PSUBank"

    def test_longer_term_wins(self) -> None:
        """'financial services' must beat 'financial'; 'information technology' beat 'it'."""
        assert resolve("Information Technology").key == "IT"

    def test_unknown_industry_resolves_to_nothing(self) -> None:
        """A wrong sector index would make the RS criterion confidently wrong."""
        assert resolve("Interstellar Freight") is None

    def test_missing_industry_resolves_to_nothing(self) -> None:
        assert resolve(None) is None
        assert resolve("") is None

    def test_every_sector_index_is_completely_declared(self) -> None:
        """A count alone guards nothing useful — what matters is that each entry is usable.

        Every index in the table carries both a history ticker and NSE's own name for it, and
        each was verified against the live index list and 400 days of history before being
        added. `market-data` requires an index without usable history to be absent rather than
        present and broken, so an entry missing either half is the failure worth catching.
        """
        import json
        from pathlib import Path

        from app.data import sectors

        payload = json.loads(sectors.SECTORS_FILE.read_text("utf-8"))
        assert payload["indices"].keys() == payload["nse_names"].keys()
        assert len(all_sector_indices()) == len(payload["indices"])

        # Every industry term points at an index that exists.
        assert set(payload["industry_terms"].values()) <= set(payload["indices"])
        assert Path(sectors.SECTORS_FILE).exists()


class TestNewIndicators:
    def test_weekly_resample_aggregates_correctly(self) -> None:
        daily = frame(flat(21, 100.0))
        weekly = to_weekly(daily)

        assert len(weekly) < len(daily)
        # Volume sums rather than averages, and nothing is lost. Asserting on a specific
        # bucket would depend on which weekday the series happens to start.
        assert weekly["volume"].sum() == pytest.approx(daily["volume"].sum())
        assert weekly["volume"].max() > daily["volume"].max()

    def test_weekly_resample_preserves_extremes(self) -> None:
        daily = frame([100.0, 120.0, 90.0, 110.0, 105.0, 95.0, 100.0])
        weekly = to_weekly(daily)

        assert weekly["high"].max() == pytest.approx(daily["high"].max())
        assert weekly["low"].min() == pytest.approx(daily["low"].min())

    def test_range_breakout_detected(self) -> None:
        closes = flat(400, 100.0) + trend(10, 100.0, 0.02)
        result = horizontal_range_breakout(frame(closes), 375)

        assert result is not None
        assert result.broke_out is True

    def test_no_breakout_inside_the_range(self) -> None:
        result = horizontal_range_breakout(frame(flat(400, 100.0)), 375)

        assert result is not None
        assert result.broke_out is False

    def test_range_excludes_recent_bars(self) -> None:
        """Otherwise the breakout widens the range it is supposed to be breaking out of."""
        closes = flat(400, 100.0) + [200.0] * 5
        result = horizontal_range_breakout(frame(closes), 375, exclude_recent=5)

        assert result.range_high < 150.0

    def test_a_trend_is_not_a_base(self) -> None:
        result = horizontal_range_breakout(frame(trend(400, 100.0, 0.005)), 375)

        assert result is not None
        assert result.broke_out is False  # width exceeds the base limit

    def test_tightness_measures_the_window(self) -> None:
        assert consolidation_tightness(frame(flat(30, 100.0)), 25) == pytest.approx(2.02, abs=0.1)

    def test_impulse_leg_found(self) -> None:
        closes = flat(60, 100.0) + list(np.linspace(100.0, 130.0, 10))
        leg = find_impulse_leg(frame([float(c) for c in closes]), 20.0, 50.0, 5, 15)

        assert leg is not None
        assert 20.0 <= leg.gain_pct <= 50.0

    def test_no_impulse_in_a_flat_series(self) -> None:
        assert find_impulse_leg(frame(flat(80, 100.0)), 20.0, 50.0, 5, 15) is None

    def test_fib_retracement(self) -> None:
        assert fib_retracement_pct(100.0, 200.0, 150.0) == pytest.approx(50.0)
        assert fib_retracement_pct(100.0, 200.0, 190.0) == pytest.approx(10.0)


class TestBrahmaVishnuMahesh:
    def _context(self, frames: dict, **kwargs) -> StrategyContext:
        return StrategyContext(
            price_source=StaticPriceSource(frames), benchmark=BENCH, now=lambda: NOW, **kwargs
        )

    def _base_then_breakout(self) -> pd.DataFrame:
        closes = flat(400, 100.0) + trend(12, 100.0, 0.02)
        volumes = [1_000_000.0] * 400 + [9_000_000.0] * 12
        return frame(closes, volumes)

    def test_bullish_regime_scores_higher_than_bearish(self) -> None:
        """Regime carries dominant weight, so the same stock scores very differently."""
        stock = self._base_then_breakout()
        bull = self._context({"TCS": stock, "NIFTY50": frame(trend(420, 100.0, 0.002))})
        bear = self._context({"TCS": stock, "NIFTY50": frame(trend(420, 300.0, -0.002))})

        strong = BrahmaVishnuMaheshStrategy().evaluate(TCS, bull)
        weak = BrahmaVishnuMaheshStrategy().evaluate(TCS, bear)

        assert strong.conviction > weak.conviction
        assert strong.evidence_by_id("brahma_regime").passed is True
        assert weak.evidence_by_id("brahma_regime").passed is False

    def test_bearish_regime_does_not_fail_a_gate(self) -> None:
        """A bear market makes a stock unattractive, not unassessable."""
        context = self._context(
            {"TCS": self._base_then_breakout(), "NIFTY50": frame(trend(420, 300.0, -0.002))}
        )

        verdict = BrahmaVishnuMaheshStrategy().evaluate(TCS, context)

        assert verdict.gates_passed is True
        assert all(g.passed for g in verdict.gates)

    def test_unknown_sector_is_recorded_not_skipped(self) -> None:
        """A criterion that quietly disappears would inflate the proportion passed."""
        unknown = Instrument("TCS", sector="Interstellar Freight")
        context = self._context(
            {"TCS": self._base_then_breakout(), "NIFTY50": frame(trend(420, 100.0, 0.002))}
        )

        verdict = BrahmaVishnuMaheshStrategy().evaluate(unknown, context)
        row = verdict.evidence_by_id("vishnu_sector_rank")

        assert row is not None
        assert row.passed is False
        assert "sector unknown" in row.label

    def test_breakout_requires_volume_too(self) -> None:
        quiet = frame(flat(400, 100.0) + trend(12, 100.0, 0.02))  # ordinary volume throughout
        context = self._context({"TCS": quiet, "NIFTY50": frame(trend(420, 100.0, 0.002))})

        verdict = BrahmaVishnuMaheshStrategy().evaluate(TCS, context)

        assert verdict.evidence_by_id("mahesh_range_breakout").passed is True
        assert verdict.evidence_by_id("mahesh_volume_expansion").passed is False

    def test_short_history_blocks_with_a_gate(self) -> None:
        context = self._context({"TCS": frame(flat(100, 100.0))})

        verdict = BrahmaVishnuMaheshStrategy().evaluate(TCS, context)

        assert verdict.stance is Stance.AVOID
        assert verdict.failed_gates[0].id == "sufficient_history"


class TestFunTechMomentum:
    def _fundamentals(self, eps: list[float], revenue: list[float] | None = None):
        def points(values):
            return tuple(
                QuarterPoint(date(2026 - (i // 4), 12 - (i % 4) * 3, 28), v)
                for i, v in enumerate(values)
            )

        return StaticFundamentalsSource(
            {
                "TCS": QuarterlyFundamentals(
                    symbol="TCS",
                    eps=points(eps),
                    revenue=points(revenue) if revenue else (),
                    source_ref="fundamentals://test/TCS",
                )
            }
        )

    def _context(self, fundamentals=None, prices=None) -> StrategyContext:
        closes = flat(280, 100.0) + trend(20, 100.0, 0.004)
        volumes = [1_000_000.0] * 299 + [5_000_000.0]
        return StrategyContext(
            price_source=StaticPriceSource(prices or {"TCS": frame(closes, volumes)}),
            benchmark=BENCH,
            fundamentals_source=fundamentals,
            now=lambda: NOW,
        )

    def test_missing_fundamentals_fails_a_gate(self) -> None:
        """A fundamental screen with no fundamentals is no signal, not a weak one."""
        verdict = FunTechMomentumStrategy().evaluate(TCS, self._context(fundamentals=None))

        assert verdict.stance is Stance.AVOID
        assert verdict.failed_gates[0].id == "fundamentals_available"
        assert "earnings screen" in verdict.failed_gates[0].reason

    def test_too_few_quarters_fails_the_gate(self) -> None:
        context = self._context(fundamentals=self._fundamentals([30.0, 20.0]))

        verdict = FunTechMomentumStrategy().evaluate(TCS, context)

        assert verdict.failed_gates[0].id == "fundamentals_available"

    def test_eps_acceleration_alone_passes_the_surprise(self) -> None:
        context = self._context(fundamentals=self._fundamentals([30.0, 20.0, 12.0, 11.0, 10.0]))

        verdict = FunTechMomentumStrategy().evaluate(TCS, context)
        row = verdict.evidence_by_id("earnings_surprise")

        assert row.passed is True
        assert "EPS" in row.label

    def test_revenue_acceleration_alone_passes(self) -> None:
        flat_eps = [10.0, 10.0, 10.0, 10.0, 10.0]
        context = self._context(
            fundamentals=self._fundamentals(flat_eps, [200.0, 110.0, 105.0, 102.0, 100.0])
        )

        verdict = FunTechMomentumStrategy().evaluate(TCS, context)
        row = verdict.evidence_by_id("earnings_surprise")

        assert row.passed is True
        assert "revenue" in row.label

    def test_neither_accelerating_fails(self) -> None:
        context = self._context(fundamentals=self._fundamentals([10.0, 10.0, 10.0, 10.0, 10.0]))

        verdict = FunTechMomentumStrategy().evaluate(TCS, context)

        assert verdict.evidence_by_id("earnings_surprise").passed is False

    def test_year_ago_quarter_is_recorded(self) -> None:
        """Seasonality: the comparison must be quarter-on-same-quarter, and say which."""
        context = self._context(fundamentals=self._fundamentals([30.0, 20.0, 12.0, 11.0, 10.0]))

        verdict = FunTechMomentumStrategy().evaluate(TCS, context)

        assert verdict.evidence_by_id("eps_year_ago_quarter").value is not None

    def test_negative_base_is_unknown_not_infinite_growth(self) -> None:
        context = self._context(fundamentals=self._fundamentals([30.0, 20.0, 12.0, 11.0, -5.0]))

        verdict = FunTechMomentumStrategy().evaluate(TCS, context)
        row = verdict.evidence_by_id("earnings_surprise")

        assert row.value is None or row.passed is False

    def test_gates_pass_when_fundamentals_present(self) -> None:
        context = self._context(fundamentals=self._fundamentals([30.0, 20.0, 12.0, 11.0, 10.0]))

        verdict = FunTechMomentumStrategy().evaluate(TCS, context)

        assert verdict.gates_passed is True


class TestYoungMomentum:
    def _context(self, prices: dict) -> StrategyContext:
        return StrategyContext(
            price_source=StaticPriceSource(prices), benchmark=BENCH, now=lambda: NOW
        )

    def _impulse_then_pause(self, pause_low: float) -> pd.DataFrame:
        base = flat(160, 100.0)
        impulse = list(np.linspace(100.0, 130.0, 10))
        pause = list(np.linspace(130.0, pause_low, 4))
        volumes = [1_000_000.0] * 160 + [4_000_000.0] * 10 + [400_000.0] * 4
        return frame([float(c) for c in base + impulse + pause], volumes)

    def test_shallow_pause_passes(self) -> None:
        verdict = YoungMomentumStrategy().evaluate(
            TCS, self._context({"TCS": self._impulse_then_pause(126.0)})
        )
        row = verdict.evidence_by_id("pause_within_fib")

        assert verdict.evidence_by_id("impulse_leg").passed is True
        assert row.passed is True
        assert row.value <= 38.2

    def test_deep_retracement_fails_and_records_the_observation(self) -> None:
        """A deeper pullback means the impulse failed, not that the signal is weaker."""
        verdict = YoungMomentumStrategy().evaluate(
            TCS, self._context({"TCS": self._impulse_then_pause(105.0)})
        )
        row = verdict.evidence_by_id("pause_within_fib")

        assert row.passed is False
        assert row.value > 38.2
        assert row.threshold == 38.2

    def test_no_impulse_still_produces_a_verdict(self) -> None:
        verdict = YoungMomentumStrategy().evaluate(
            TCS, self._context({"TCS": frame(flat(200, 100.0))})
        )

        assert verdict.evidence_by_id("impulse_leg").passed is False
        assert verdict.stance in (Stance.AVOID, Stance.WATCH)

    def test_entry_levels_are_informational(self) -> None:
        """A level is not a decision, and no position size belongs in a verdict."""
        verdict = YoungMomentumStrategy().evaluate(
            TCS, self._context({"TCS": self._impulse_then_pause(126.0)})
        )

        trigger = verdict.evidence_by_id("entry_trigger")
        assert trigger.passed is None
        assert trigger.operator.value == "info"
        for banned in ("quantity", "position_size", "shares_to_buy"):
            assert verdict.evidence_by_id(banned) is None


class TestFourIndependentVerdicts:
    def test_all_four_registered(self) -> None:
        registry = StrategyRegistry.discover()

        assert registry.ids() == [
            "brahma_vishnu_mahesh",
            "fun_tech_momentum",
            "minervini",
            "young_momentum",
        ]
        assert registry.load_failures == []

    def test_one_ticker_yields_four_independent_verdicts(self) -> None:
        registry = StrategyRegistry.discover()
        closes = flat(400, 100.0) + trend(20, 100.0, 0.01)
        context = StrategyContext(
            price_source=StaticPriceSource(
                {"TCS": frame(closes), "NIFTY50": frame(trend(420, 100.0, 0.002))}
            ),
            benchmark=BENCH,
            fundamentals_source=StaticFundamentalsSource({}),
            now=lambda: NOW,
        )

        verdicts = [d.strategy.evaluate(TCS, context) for d in registry.definitions()]

        assert len(verdicts) == 4
        assert {v.strategy_id for v in verdicts} == set(registry.ids())
        # Each carries its own conviction on its own scale.
        assert all(0 <= v.conviction <= 100 for v in verdicts)
        assert all(v.evidence for v in verdicts)

    def test_strategies_can_disagree(self) -> None:
        """The whole reason for four: they see the same bars differently."""
        registry = StrategyRegistry.discover()
        closes = flat(160, 100.0) + list(np.linspace(100.0, 130.0, 10)) + [128.0] * 3
        context = StrategyContext(
            price_source=StaticPriceSource(
                {
                    "TCS": frame([float(c) for c in closes]),
                    "NIFTY50": frame(trend(180, 100.0, 0.002)),
                }
            ),
            benchmark=BENCH,
            fundamentals_source=StaticFundamentalsSource({}),
            now=lambda: NOW,
        )

        verdicts = [d.strategy.evaluate(TCS, context) for d in registry.definitions()]
        convictions = {v.strategy_id: v.conviction for v in verdicts}

        assert len(set(convictions.values())) > 1

    def test_no_strategy_module_exposes_aggregation(self) -> None:
        import app.strategies.gates as module

        names = [n.lower() for n in dir(module) if not n.startswith("_")]
        for banned in ("combine", "aggregate", "blend", "consensus", "composite"):
            assert not any(banned in name for name in names)

    @pytest.mark.parametrize(
        "strategy_id",
        ["brahma_vishnu_mahesh", "fun_tech_momentum", "minervini", "young_momentum"],
    )
    def test_conviction_reproducible_per_strategy(self, strategy_id: str) -> None:
        registry = StrategyRegistry.discover()
        context = StrategyContext(
            price_source=StaticPriceSource(
                {"TCS": frame(trend(420, 100.0, 0.003)), "NIFTY50": frame(trend(420, 100.0, 0.001))}
            ),
            benchmark=BENCH,
            fundamentals_source=StaticFundamentalsSource({}),
            now=lambda: NOW,
        )
        strategy = registry.get(strategy_id).strategy

        first = strategy.evaluate(TCS, context)
        second = strategy.evaluate(TCS, context)

        assert first.conviction == second.conviction
        assert first.stance == second.stance

    def test_price_only_strategies_need_no_fundamentals(self) -> None:
        registry = StrategyRegistry.discover()
        context = StrategyContext(
            price_source=StaticPriceSource(
                {"TCS": frame(trend(420, 100.0, 0.003)), "NIFTY50": frame(trend(420, 100.0, 0.001))}
            ),
            benchmark=BENCH,
            fundamentals_source=None,
            now=lambda: NOW,
        )

        for strategy_id in ("minervini", "brahma_vishnu_mahesh", "young_momentum"):
            verdict = registry.get(strategy_id).strategy.evaluate(TCS, context)
            assert verdict.gates_passed is True, strategy_id
