"""Backtesting.

The property this stands or falls on: **a strategy evaluated for a date cannot see a bar after
it.** Everything else in a backtest is arithmetic; lookahead is the thing that makes the
arithmetic a lie, and it is prevented at the seam rather than avoided by care.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.backtest.asof import AsOfPriceSource, first_bar_after, last_bar_on_or_before, truncate
from app.backtest.runner import BIASES, BacktestConfig, in_memory_ledger, run
from app.domain.instrument import Instrument
from app.domain.position import Book, Side
from app.domain.prices import build_series, empty_series
from app.strategies.registry import StrategyRegistry

RELIANCE = Instrument("RELIANCE")
START = date(2026, 1, 1)


def _series(instrument: Instrument, days: int = 400, start: date = START):
    index = pd.DatetimeIndex(
        [datetime.combine(start, datetime.min.time(), tzinfo=UTC) + timedelta(days=i)
         for i in range(days)]
    )
    closes = [100.0 + i * 0.5 for i in range(days)]
    frame = pd.DataFrame(
        {
            "Open": [c - 0.5 for c in closes],
            "High": [c * 1.02 for c in closes],
            "Low": [c * 0.98 for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * days,
        },
        index=index,
    )
    return build_series(instrument, "1d", frame, source="test")


class FullHistory:
    """Serves everything it has — the source a backtest must not be trusted with directly."""

    def __init__(self, days: int = 400) -> None:
        self.days = days
        self.requests: list[int] = []

    def history(self, instrument, *, interval="1d", lookback_days=400):
        self.requests.append(lookback_days)
        return _series(instrument, self.days)


class AlwaysOpen:
    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5


class TestLookaheadIsPrevented:
    """The one property a backtest cannot be wrong about."""

    def test_no_bar_after_the_as_of_date_is_returned(self) -> None:
        as_of = START + timedelta(days=100)
        source = AsOfPriceSource(inner=FullHistory(days=400), as_of=as_of)

        series = source.history(RELIANCE)

        assert not series.is_empty
        assert series.frame.index.max().date() <= as_of

    def test_truncation_is_inclusive_of_the_as_of_session(self) -> None:
        """A decision made after Tuesday's close may use Tuesday's bar — it may not act on it."""
        full = _series(RELIANCE, days=100)
        as_of = full.frame.index[50].date()

        truncated = truncate(full, as_of)

        assert truncated.frame.index.max().date() == as_of

    def test_truncation_applies_however_much_history_is_asked_for(self) -> None:
        as_of = START + timedelta(days=60)
        source = AsOfPriceSource(inner=FullHistory(days=400), as_of=as_of)

        for lookback in (30, 200, 1500):
            series = source.history(RELIANCE, lookback_days=lookback)
            assert series.frame.index.max().date() <= as_of

    def test_a_strategy_never_sees_the_future(self) -> None:
        """End to end: the strategy is unmodified and cannot opt out of the wrapper."""
        from app.strategies.protocols import StrategyContext

        as_of = START + timedelta(days=300)
        registry = StrategyRegistry.discover()
        context = StrategyContext(
            price_source=AsOfPriceSource(inner=FullHistory(days=400), as_of=as_of),
            now=lambda: datetime.combine(as_of, datetime.min.time()),
        )

        verdict = registry.get("minervini").strategy.evaluate(RELIANCE, context)

        # The last close on this ramp is a function of the bar index, so a value beyond the
        # as-of price proves the strategy read past the cutoff.
        highest_legal = 100.0 + 300 * 0.5
        for row in verdict.evidence:
            if isinstance(row.value, int | float) and row.unit == "INR":
                assert row.value <= highest_legal * 1.05

    def test_empty_history_stays_empty(self) -> None:
        class Nothing:
            def history(self, instrument, *, interval="1d", lookback_days=400):
                return empty_series(instrument, interval)

        source = AsOfPriceSource(inner=Nothing(), as_of=START)

        assert source.history(RELIANCE).is_empty

    def test_an_as_of_before_all_history_returns_nothing(self) -> None:
        source = AsOfPriceSource(inner=FullHistory(), as_of=date(2000, 1, 1))

        assert source.history(RELIANCE).is_empty

    def test_the_source_asks_for_padded_history(self) -> None:
        """Truncation removes the tail, so a window measured from today would come up short."""
        inner = FullHistory()
        AsOfPriceSource(inner=inner, as_of=START).history(RELIANCE, lookback_days=100)

        assert inner.requests[0] > 100


class TestFillTiming:
    def test_a_fill_uses_the_next_sessions_open(self) -> None:
        """The decision did not exist until the bar closed; acting on that close is lookahead."""
        series = _series(RELIANCE, days=100)
        signal_day = series.frame.index[50].date()

        fill = first_bar_after(series, signal_day)

        assert fill is not None
        fill_date, fill_price = fill
        assert fill_date > signal_day
        assert fill_price == pytest.approx(float(series.frame["open"].iloc[51]))

    def test_no_bar_after_the_last_session(self) -> None:
        series = _series(RELIANCE, days=10)

        assert first_bar_after(series, series.frame.index[-1].date()) is None

    def test_last_bar_on_or_before(self) -> None:
        series = _series(RELIANCE, days=100)
        when = series.frame.index[30].date()

        found = last_bar_on_or_before(series, when)

        assert found is not None and found[0] == when


class TestTheRealLedgerIsUsed:
    def test_backtest_positions_fold_like_the_live_book(self) -> None:
        """A fourth position ledger would be the one deciding whether a strategy looks good."""
        ledger = in_memory_ledger()

        ledger.fill(Book.SWING, "RELIANCE", Side.BUY, 10, 100.0)
        ledger.fill(Book.SWING, "RELIANCE", Side.SELL, 4, 130.0)
        position = ledger.position(Book.SWING, "RELIANCE")

        assert position.quantity == 6
        assert position.average_cost == pytest.approx(100.0)
        assert position.realised_pnl == pytest.approx(120.0)

    def test_it_is_the_same_class_as_the_live_ledger(self) -> None:
        from app.books.ledger import Ledger

        assert isinstance(in_memory_ledger(), Ledger)

    def test_the_oversell_guard_still_applies(self) -> None:
        from app.books.ledger import InsufficientQuantity

        ledger = in_memory_ledger()
        ledger.fill(Book.SWING, "RELIANCE", Side.BUY, 5, 100.0)

        with pytest.raises(InsufficientQuantity):
            ledger.fill(Book.SWING, "RELIANCE", Side.SELL, 50, 120.0)


class TestRunner:
    def _config(self, **kw) -> BacktestConfig:
        base = {
            "start": START + timedelta(days=250),
            "end": START + timedelta(days=380),
            "symbols": ("RELIANCE",),
            "step_sessions": 10,
            "max_hold_sessions": 5,
        }
        return BacktestConfig(**{**base, **kw})

    def test_a_run_reports_per_strategy_results(self) -> None:
        report = run(
            self._config(), FullHistory(days=400), StrategyRegistry.discover(), AlwaysOpen()
        )
        body = report.as_dict()

        assert set(body["results"]) == set(StrategyRegistry.discover().ids())
        for result in body["results"].values():
            assert "win_rate_pct" in result
            assert result["charges_included"] is False

    def test_there_is_no_combined_curve_across_strategies(self) -> None:
        """Four independent verdicts do not compose into one portfolio."""
        body = run(
            self._config(), FullHistory(days=400), StrategyRegistry.discover(), AlwaysOpen()
        ).as_dict()

        for banned in ("equity_curve", "total_pnl", "combined", "portfolio", "overall"):
            assert banned not in body

    def test_every_report_carries_its_biases(self) -> None:
        body = run(
            self._config(), FullHistory(days=400), StrategyRegistry.discover(), AlwaysOpen()
        ).as_dict()

        assert body["biases"] == list(BIASES)
        assert any("survivorship" in b for b in body["biases"])

    def test_only_trading_days_are_evaluated(self) -> None:
        class WeekdaysOnly:
            def __init__(self) -> None:
                self.asked: list[date] = []

            def is_trading_day(self, day: date) -> bool:
                self.asked.append(day)
                return day.weekday() < 5

        calendar = WeekdaysOnly()
        run(self._config(), FullHistory(days=400), StrategyRegistry.discover(), calendar)

        assert calendar.asked, "calendar was never consulted"

    def test_a_window_with_no_trading_days_is_reported_not_crashed(self) -> None:
        """A market closed for the whole window is a legitimate answer, not a failure."""

        class NeverOpen:
            def is_trading_day(self, day: date) -> bool:
                return False

        report = run(self._config(), FullHistory(), StrategyRegistry.discover(), NeverOpen())

        assert report.sessions == 0
        assert "nothing to replay" in report.notes[0]

    def test_no_symbols_is_reported_not_crashed(self) -> None:
        report = run(
            self._config(symbols=()), FullHistory(), StrategyRegistry.discover(), AlwaysOpen()
        )

        assert "nothing to replay" in report.notes[0]

    def test_evaluations_are_counted(self) -> None:
        report = run(
            self._config(), FullHistory(days=400), StrategyRegistry.discover(), AlwaysOpen()
        )

        assert report.evaluations > 0


class TestLegacyDataIsNeverRead:
    def test_the_backtest_package_touches_no_legacy_table(self) -> None:
        """Standing decision: the predecessor's rows came from the scoring system this rebuild
        removes, so measuring against them would measure the old engine's judgement."""
        from pathlib import Path

        from app.persistence.legacy import LEGACY_TABLES

        root = Path(__file__).resolve().parents[1] / "app" / "backtest"
        source = "\n".join(p.read_text("utf-8") for p in root.rglob("*.py"))

        for table in LEGACY_TABLES:
            assert f'"{table}"' not in source
            assert f"'{table}'" not in source
        assert "signal_outcomes" not in source
        assert "public." not in source


class TestBacktestApi:
    def test_a_run_returns_results_and_biases(self, client) -> None:
        response = client.post(
            "/backtest/run",
            json={
                "symbols": ["RELIANCE"],
                "start": (date.today() - timedelta(days=120)).isoformat(),
                "step_sessions": 20,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert "results" in body
        assert body["biases"]

    def test_an_inverted_window_is_rejected(self, client) -> None:
        response = client.post(
            "/backtest/run",
            json={
                "symbols": ["RELIANCE"],
                "start": "2026-06-01",
                "end": "2026-01-01",
            },
        )

        assert response.status_code == 422

    def test_it_requires_authentication(self, settings) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_app

        anonymous = TestClient(create_app(settings))

        assert anonymous.post("/backtest/run", json={}).status_code == 401
