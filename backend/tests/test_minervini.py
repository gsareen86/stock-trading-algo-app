"""Indicators and the Minervini strategy.

Every series here is hand-built with a known shape. Generated data that happens to pass would
assert nothing — the point is that a stock in a confirmed uptrend passes and one in a
downtrend does not, for reasons a reader can check.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.fake import StaticPriceSource
from app.domain.instrument import Instrument
from app.domain.prices import build_series
from app.domain.verdict import Stance
from app.strategies.indicators import (
    find_contractions,
    is_rising,
    is_tightening,
    pct_above_low,
    pct_below_high,
    relative_strength_pct,
    sma,
    volume_dry_up_ratio,
    window_return_pct,
)
from app.strategies.minervini import trend_template, vcp
from app.strategies.minervini.strategy import BUY_CONVICTION, MIN_BARS, MinerviniStrategy
from app.strategies.protocols import StrategyContext

TCS = Instrument("TCS")
BENCH = Instrument("NIFTY50")


def frame_from_closes(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    vols = volumes or [1_000_000.0] * n
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": vols,
        },
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


def uptrend(n: int = 300, start: float = 100.0, daily: float = 0.004) -> pd.DataFrame:
    """A clean Stage 2 advance: steady compounding, finishing at its high."""
    return frame_from_closes([start * (1 + daily) ** i for i in range(n)])


def downtrend(n: int = 300, start: float = 300.0, daily: float = -0.004) -> pd.DataFrame:
    return frame_from_closes([start * (1 + daily) ** i for i in range(n)])


def flat(n: int = 300, level: float = 100.0) -> pd.DataFrame:
    return frame_from_closes([level] * n)


def series(frame: pd.DataFrame, instrument: Instrument = TCS):
    return build_series(instrument, "1d", frame, source="fake")


class TestIndicators:
    def test_sma_matches_a_hand_computation(self) -> None:
        frame = frame_from_closes([10.0, 20.0, 30.0, 40.0])

        assert sma(frame, 4) == pytest.approx(25.0)
        assert sma(frame, 2) == pytest.approx(35.0)

    def test_sma_needs_a_full_window(self) -> None:
        assert sma(frame_from_closes([1.0, 2.0]), 5) is None

    def test_is_rising_true_on_an_uptrend(self) -> None:
        assert is_rising(uptrend(), 200, 22) is True

    def test_is_rising_false_on_a_downtrend(self) -> None:
        assert is_rising(downtrend(), 200, 22) is False

    def test_is_rising_none_without_enough_history(self) -> None:
        assert is_rising(uptrend(n=100), 200, 22) is None

    def test_pct_above_low_and_below_high(self) -> None:
        assert pct_above_low(130.0, 100.0) == pytest.approx(30.0)
        assert pct_below_high(75.0, 100.0) == pytest.approx(25.0)

    def test_window_return(self) -> None:
        assert window_return_pct(frame_from_closes([100.0, 110.0]), 2) == pytest.approx(10.0)

    def test_relative_strength_is_the_difference_in_returns(self) -> None:
        stock = frame_from_closes([100.0 * 1.002**i for i in range(252)])
        bench = frame_from_closes([100.0 * 1.001**i for i in range(252)])

        rs = relative_strength_pct(stock, bench, 252)

        assert rs is not None and rs > 0

    def test_relative_strength_negative_when_lagging(self) -> None:
        stock = frame_from_closes([100.0] * 252)
        bench = frame_from_closes([100.0 * 1.002**i for i in range(252)])

        assert relative_strength_pct(stock, bench, 252) < 0

    def test_volume_dry_up_below_one_when_quiet(self) -> None:
        vols = [1_000_000.0] * 40 + [200_000.0] * 10
        ratio = volume_dry_up_ratio(frame_from_closes([100.0] * 50, vols), 10, 50)

        assert ratio is not None and ratio < 1.0


class TestContractions:
    def _base_with_contractions(self) -> pd.DataFrame:
        """Three pullbacks, each shallower than the last — the VCP signature."""
        closes = [100.0]
        for peak, trough in ((120.0, 96.0), (118.0, 104.0), (116.0, 110.0)):
            closes += list(np.linspace(closes[-1], peak, 12))
            closes += list(np.linspace(peak, trough, 12))
        closes += list(np.linspace(closes[-1], 118.0, 10))
        return frame_from_closes([float(c) for c in closes])

    def test_successive_contractions_detected(self) -> None:
        found = find_contractions(self._base_with_contractions())

        assert len(found) >= 2
        assert all(c.depth_pct > 0 for c in found)

    def test_tightening_recognised(self) -> None:
        found = find_contractions(self._base_with_contractions())

        assert is_tightening(found[-2:]) is True

    def test_no_base_yields_no_contractions(self) -> None:
        assert find_contractions(uptrend()) == []

    def test_flat_series_yields_no_contractions(self) -> None:
        assert find_contractions(flat()) == []

    def test_single_contraction_is_not_tightening(self) -> None:
        found = find_contractions(self._base_with_contractions())

        assert is_tightening(found[:1]) is False

    def test_short_series_returns_empty_rather_than_raising(self) -> None:
        assert find_contractions(frame_from_closes([100.0, 101.0])) == []


class TestTrendTemplate:
    def test_emits_one_row_per_criterion(self) -> None:
        rows = trend_template.evaluate(series(uptrend()), series(flat(), BENCH))

        assert len(rows) == trend_template.CRITERION_COUNT
        assert all(row.source_ref for row in rows)

    def test_confirmed_uptrend_passes_every_criterion(self) -> None:
        rows = trend_template.evaluate(series(uptrend()), series(flat(), BENCH))

        failed = [row.id for row in rows if not row.passed]
        assert failed == []

    def test_downtrend_fails_the_moving_average_criteria(self) -> None:
        rows = trend_template.evaluate(series(downtrend()), series(flat(), BENCH))
        by_id = {row.id: row for row in rows}

        assert by_id["price_above_150_200dma"].passed is False
        assert by_id["ma150_above_ma200"].passed is False
        assert by_id["ma200_rising"].passed is False

    def test_every_criterion_records_its_comparison(self) -> None:
        rows = trend_template.evaluate(series(uptrend()), series(flat(), BENCH))

        for row in rows:
            assert row.operator.value != "info"
            assert row.threshold is not None
            assert row.passed is not None

    def test_relative_strength_is_not_called_a_rating(self) -> None:
        """A field named rs_rating holding something else would be believed by every reader."""
        rows = trend_template.evaluate(series(uptrend()), series(flat(), BENCH))
        rs = next(r for r in rows if r.id == "rs_criterion")

        assert "rs_vs_benchmark_pct" in rs.label
        assert "rating" not in rs.label.lower()
        assert rs.unit == "pp"

    def test_missing_benchmark_fails_the_criterion_without_breaking_evaluation(self) -> None:
        rows = trend_template.evaluate(series(uptrend()), None)
        rs = next(r for r in rows if r.id == "rs_criterion")

        assert rs.passed is False
        assert rs.value is None
        assert len(rows) == trend_template.CRITERION_COUNT


class TestVcpReading:
    def test_no_base_reports_zero_contractions(self) -> None:
        reading = vcp.analyse(series(uptrend()))

        assert reading.count == 0
        assert reading.tightening is False

    def test_evidence_includes_count_and_tightening(self) -> None:
        rows = vcp.to_evidence(series(uptrend()), vcp.analyse(series(uptrend())))
        ids = {row.id for row in rows}

        assert {"vcp_contraction_count", "vcp_tightening", "vcp_volume_dry_up"} <= ids

    def test_quality_points_are_zero_without_a_base(self) -> None:
        vcp_points, _ = vcp.quality_points(vcp.analyse(series(uptrend())))

        assert vcp_points == 0

    def test_quality_points_bounded(self) -> None:
        reading = vcp.analyse(series(uptrend()))
        vcp_points, volume_points = vcp.quality_points(reading)

        assert 0 <= vcp_points <= vcp.MAX_VCP_POINTS
        assert 0 <= volume_points <= vcp.MAX_VOLUME_POINTS


class TestStrategyGates:
    def _context(self, frames: dict) -> StrategyContext:
        return StrategyContext(price_source=StaticPriceSource(frames), benchmark=BENCH)

    def test_short_history_yields_avoid_with_a_failing_gate(self) -> None:
        context = self._context({"TCS": uptrend(n=50)})

        verdict = MinerviniStrategy().evaluate(TCS, context)

        assert verdict.stance is Stance.AVOID
        assert verdict.gates_passed is False
        assert verdict.failed_gates[0].id == "sufficient_history"
        assert str(MIN_BARS) in verdict.failed_gates[0].reason

    def test_no_data_yields_a_verdict_not_an_exception(self) -> None:
        """'I could not assess this, and here is why' is information a reader wants."""
        verdict = MinerviniStrategy().evaluate(TCS, self._context({}))

        assert verdict.stance is Stance.AVOID
        assert verdict.conviction == 0
        assert "no price data" in verdict.failed_gates[0].reason

    def test_untraded_instrument_fails_the_liquidity_gate(self) -> None:
        frame = uptrend()
        frame["volume"] = 0.0
        context = self._context({"TCS": frame})

        verdict = MinerviniStrategy().evaluate(TCS, context)

        assert verdict.failed_gates[0].id == "tradable_liquidity"
        assert verdict.stance is Stance.AVOID

    def test_blocking_verdict_still_carries_evidence(self) -> None:
        verdict = MinerviniStrategy().evaluate(TCS, self._context({}))

        assert verdict.evidence
        assert verdict.evidence_by_id("bars_available") is not None


class TestStrategyScoring:
    def _context(self, frames: dict) -> StrategyContext:
        return StrategyContext(price_source=StaticPriceSource(frames), benchmark=BENCH)

    def test_uptrend_passes_gates_and_scores(self) -> None:
        context = self._context({"TCS": uptrend(), "NIFTY50": flat()})

        verdict = MinerviniStrategy().evaluate(TCS, context)

        assert verdict.gates_passed is True
        assert verdict.stance in (Stance.BUY, Stance.WATCH)
        assert verdict.conviction > 0

    def test_downtrend_scores_low(self) -> None:
        context = self._context({"TCS": downtrend(), "NIFTY50": flat()})

        verdict = MinerviniStrategy().evaluate(TCS, context)

        assert verdict.conviction < BUY_CONVICTION
        assert verdict.stance is not Stance.BUY

    def test_partial_template_is_watch_not_avoid(self) -> None:
        """Criteria reduce conviction; they do not gate."""
        context = self._context({"TCS": uptrend(), "NIFTY50": uptrend(daily=0.02)})

        verdict = MinerviniStrategy().evaluate(TCS, context)
        rs = verdict.evidence_by_id("rs_criterion")

        assert rs.passed is False  # lagging a hotter benchmark
        assert verdict.gates_passed is True
        assert verdict.stance is not Stance.AVOID

    def test_conviction_is_reproducible(self) -> None:
        context = self._context({"TCS": uptrend(), "NIFTY50": flat()})
        strategy = MinerviniStrategy()

        first = strategy.evaluate(TCS, context)
        second = strategy.evaluate(TCS, context)

        assert first.conviction == second.conviction
        assert first.stance == second.stance
        assert [e.value for e in first.evidence] == [e.value for e in second.evidence]

    @pytest.mark.parametrize(
        "frame_fn", [uptrend, downtrend, flat], ids=["uptrend", "downtrend", "flat"]
    )
    def test_conviction_always_in_range(self, frame_fn) -> None:
        context = self._context({"TCS": frame_fn(), "NIFTY50": flat()})

        verdict = MinerviniStrategy().evaluate(TCS, context)

        assert 0 <= verdict.conviction <= 100

    def test_narrative_is_left_for_a_later_change(self) -> None:
        context = self._context({"TCS": uptrend(), "NIFTY50": flat()})

        verdict = MinerviniStrategy().evaluate(TCS, context)

        assert verdict.narrative is None
        assert verdict.trace_id is None

    def test_every_evidence_row_is_traceable(self) -> None:
        context = self._context({"TCS": uptrend(), "NIFTY50": flat()})

        verdict = MinerviniStrategy().evaluate(TCS, context)

        assert all(row.source_ref.startswith("price://") for row in verdict.evidence)
