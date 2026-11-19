"""The replay trades each strategy's plan, and measures it honestly.

Most of these run a *scripted* strategy: one whose stance and plan on each session are written
down in the test, so every fill and exit can be checked against bars built by hand. The real
strategies are exercised at the end, where the question is only whether splitting the work
across processes changes the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.backtest.asof import (
    AsOfFundamentalsSource,
    ReplayPriceSource,
    filed_by,
    session_dates,
)
from app.backtest.exits import EXIT_RULES
from app.backtest.runner import BacktestConfig, run
from app.data.fake import FakePriceSource, StaticPriceSource
from app.data.fundamentals import QuarterlyFundamentals, QuarterPoint, StaticFundamentalsSource
from app.domain.instrument import Instrument
from app.domain.prices import build_series
from app.domain.verdict import Evidence, Operator, Plan, Stance, Verdict
from app.strategies.protocols import StrategyDefinition
from app.strategies.registry import StrategyRegistry

DAYS = list(pd.bdate_range("2025-03-03", periods=40).date)  # Mondays to Fridays


class Weekdays:
    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.DatetimeIndex([datetime.combine(d, datetime.min.time(), tzinfo=UTC) for d in DAYS])
    full = rows + [(100.0, 100.0, 100.0, 100.0)] * (len(DAYS) - len(rows))
    return pd.DataFrame(
        {
            "open": [r[0] for r in full],
            "high": [r[1] for r in full],
            "low": [r[2] for r in full],
            "close": [r[3] for r in full],
            "volume": [1_000_000.0] * len(full),
        },
        index=index,
    )


FLAT = (100.0, 100.0, 100.0, 100.0)


@dataclass
class Scripted:
    """BUY/AVOID on the sessions it is told to, WATCH otherwise."""

    script: dict[int, tuple[str, float | None, float | None]]
    seen: list[dict] = field(default_factory=list)

    def evaluate(self, instrument: Instrument, context) -> Verdict:
        now = context.now()
        day = now.date()
        series = context.price_source.history(instrument, lookback_days=400)
        quarters = (
            context.fundamentals_source.quarterly(instrument)
            if context.fundamentals_source is not None
            else None
        )
        self.seen.append(
            {
                "day": day,
                "sector": instrument.sector,
                "last_bar": session_dates(series)[-1] if not series.is_empty else None,
                "quarters": len(quarters.eps) if quarters is not None else None,
            }
        )
        k = DAYS.index(day)
        stance, entry, stop = self.script.get(k, ("WATCH", None, None))
        evidence = [
            Evidence(id="e", label="x", value=1.0, operator=Operator.INFO, source_ref="price://x")
        ]
        plan = None
        if entry is not None and stop is not None:
            plan = Plan(entry=entry, stop=stop, holding_horizon="test", exit_rule="test",
                        evidence_ids=("e",))
        return Verdict(
            strategy_id="scripted", ticker=instrument.symbol, as_of=now,
            stance=Stance(stance), conviction=80 if stance == "BUY" else 30,
            evidence=tuple(evidence), plan=plan,
        )


def _registry(*strategies: tuple[str, Scripted]) -> StrategyRegistry:
    return StrategyRegistry(
        {
            sid: StrategyDefinition(id=sid, name=sid, description=sid, strategy=strategy)
            for sid, strategy in strategies
        }
    )


def _replay(rows, script, *, bench=None, registry=None, fundamentals=None, **overrides):
    strategy = Scripted(script)
    prices = StaticPriceSource(
        {"ACME": _frame(rows), "^CRSLDX": bench if bench is not None else _frame([]),
         "^NSEI": _frame([])}
    )
    config = BacktestConfig(
        **{
            "start": DAYS[0], "end": DAYS[-1], "symbols": ("ACME",), "step_sessions": 1,
            "position_inr": 10_000.0, "slippage_bps": 0.0, "round_trip_cost_pct": 0.25,
            "sectors": {"ACME": "Information Technology"}, **overrides,
        }
    )
    report = run(config, prices, registry or _registry(("scripted", strategy)), Weekdays(),
                 fundamentals_source=fundamentals)
    return report, strategy


def _only_trade(report, sid="scripted"):
    [trade] = report.results[sid].trades
    return trade


class TestEntryIsThePlansBuyStop:
    def test_fills_at_the_entry_when_the_session_trades_through_it(self) -> None:
        rows = [FLAT, (100, 103, 99, 102), (104, 106, 103, 105.5)]
        report, _ = _replay(rows, {0: ("BUY", 105.0, 95.0)})
        trade = _only_trade(report)
        assert trade.entry_date == DAYS[2]
        assert trade.entry_price == pytest.approx(105.0)

    def test_a_gap_within_the_chase_limit_fills_at_the_open(self) -> None:
        report, _ = _replay([FLAT, (107, 108, 106, 107)], {0: ("BUY", 105.0, 95.0)})
        assert _only_trade(report).entry_price == pytest.approx(107.0)

    def test_a_gap_beyond_the_chase_limit_is_skipped(self) -> None:
        report, _ = _replay([FLAT, (112, 113, 111, 112)], {0: ("BUY", 105.0, 95.0)})
        result = report.results["scripted"]
        assert result.skipped_extended == 1
        assert result.trades == []

    def test_an_order_whose_stop_breaks_first_is_withdrawn(self) -> None:
        report, _ = _replay([FLAT, (99, 104, 94, 96)], {0: ("BUY", 105.0, 95.0)})
        result = report.results["scripted"]
        assert result.orders_invalidated == 1
        assert result.trades == []

    def test_an_order_that_never_triggers_expires(self) -> None:
        report, _ = _replay([], {0: ("BUY", 105.0, 95.0)}, order_valid_sessions=3)
        result = report.results["scripted"]
        assert result.orders_expired == 1
        assert result.orders_filled == 0

    def test_a_buy_without_a_plan_is_counted_and_not_traded(self) -> None:
        report, _ = _replay([], {0: ("BUY", None, None)})
        result = report.results["scripted"]
        assert result.buy_without_plan == 1
        assert result.trades == []

    def test_next_open_mode_buys_any_buy_at_the_next_open(self) -> None:
        report, _ = _replay([FLAT, (101, 102, 100, 101)], {0: ("BUY", None, None)},
                            entry_mode="next_open")
        trade = _only_trade(report)
        assert trade.entry_date == DAYS[1]
        assert trade.entry_price == pytest.approx(101.0)


class TestExits:
    FILL = [FLAT, (105, 106, 104, 105)]  # fills at the 105 open on session 1

    def test_a_stop_traded_through_exits_at_the_stop(self) -> None:
        rows = [*self.FILL, (104, 104, 103, 103), (100, 101, 94, 96)]
        trade = _only_trade(_replay(rows, {0: ("BUY", 105.0, 95.0)})[0])
        assert trade.exit_date == DAYS[3]
        assert trade.exit_price == pytest.approx(95.0)
        assert trade.exit_reason.startswith("stop: traded through")
        assert trade.r_multiple == pytest.approx(-1.0)

    def test_a_gap_below_the_stop_exits_at_the_open(self) -> None:
        rows = [*self.FILL, (104, 104, 103, 103), (90, 92, 89, 91)]
        trade = _only_trade(_replay(rows, {0: ("BUY", 105.0, 95.0)})[0])
        assert trade.exit_price == pytest.approx(90.0)
        assert trade.exit_reason.startswith("stop: gapped")

    def test_the_entry_session_low_is_assumed_to_come_after_the_fill(self) -> None:
        rows = [FLAT, (104, 106, 94, 100)]
        trade = _only_trade(_replay(rows, {0: ("BUY", 105.0, 95.0)})[0])
        assert trade.entry_date == trade.exit_date == DAYS[1]
        assert trade.exit_reason == "stop: entry session"

    def test_the_buying_strategy_turning_avoid_exits_at_the_next_open(self) -> None:
        rows = [*self.FILL, FLAT, FLAT, FLAT, (98, 99, 97, 98)]
        trade = _only_trade(_replay(rows, {0: ("BUY", 105.0, 95.0), 4: ("AVOID", None, None)})[0])
        assert trade.exit_date == DAYS[5]
        assert trade.exit_price == pytest.approx(98.0)
        assert trade.exit_reason.startswith("thesis broken")

    def test_the_hold_limit_exits_at_the_next_open(self) -> None:
        trade = _only_trade(
            _replay(self.FILL, {0: ("BUY", 105.0, 95.0)}, max_hold_sessions=3)[0]
        )
        assert trade.exit_reason.startswith("max hold")
        assert trade.exit_date == DAYS[5]  # held sessions 1-4, judged after the 4th close

    def test_an_open_position_is_closed_at_the_end_and_said_to_be(self) -> None:
        report, _ = _replay(self.FILL, {0: ("BUY", 105.0, 95.0)}, max_hold_sessions=200)
        trade = _only_trade(report)
        assert trade.exit_date == DAYS[-1]
        assert trade.exit_reason.startswith("end of window")
        assert any("end of the window" in n for n in report.notes)


class TestMeasurement:
    def test_net_return_deducts_the_round_trip_cost(self) -> None:
        rows = [FLAT, (105, 106, 104, 105), (110, 111, 109, 110)]
        trade = _only_trade(
            _replay(rows, {0: ("BUY", 105.0, 95.0), 1: ("AVOID", None, None)})[0]
        )
        assert trade.return_pct == pytest.approx((110 / 105 - 1) * 100, abs=1e-3)
        assert trade.net_return_pct == pytest.approx(trade.return_pct - 0.25, abs=1e-3)

    def test_slippage_worsens_both_fills(self) -> None:
        rows = [FLAT, (105, 106, 104, 105), (110, 111, 109, 110)]
        trade = _only_trade(
            _replay(rows, {0: ("BUY", 105.0, 95.0), 1: ("AVOID", None, None)},
                    slippage_bps=100.0)[0]
        )
        assert trade.entry_price == pytest.approx(105 * 1.01)
        assert trade.exit_price == pytest.approx(110 * 0.99)

    def test_excess_is_against_the_benchmark_over_the_same_sessions(self) -> None:
        bench = _frame([FLAT, (100, 100, 100, 100), (104, 104, 104, 104)])
        rows = [FLAT, (105, 106, 104, 105), (110, 111, 109, 110)]
        trade = _only_trade(
            _replay(rows, {0: ("BUY", 105.0, 95.0), 1: ("AVOID", None, None)}, bench=bench)[0]
        )
        assert trade.benchmark_return_pct == pytest.approx(4.0)
        assert trade.excess_pp == pytest.approx(trade.return_pct - 4.0, abs=1e-3)

    def test_pnl_comes_from_the_ledger_one_book_per_strategy(self) -> None:
        """Two strategies holding the same name are two positions, not one average cost."""
        rows = [FLAT, (105, 111, 104, 110), (120, 121, 119, 120)]
        first = Scripted({0: ("BUY", 105.0, 95.0), 1: ("AVOID", None, None)})
        second = Scripted({0: ("BUY", 110.0, 100.0), 1: ("AVOID", None, None)})
        report, _ = _replay(rows, {}, registry=_registry(("one", first), ("two", second)))
        one, two = _only_trade(report, "one"), _only_trade(report, "two")
        assert one.gross_pnl_inr == pytest.approx(one.quantity * (120 - 105))
        assert two.gross_pnl_inr == pytest.approx(two.quantity * (120 - 110))

    def test_results_are_broken_down_by_conviction_band(self) -> None:
        rows = [FLAT, (105, 106, 104, 105), (110, 111, 109, 110)]
        body = _replay(rows, {0: ("BUY", 105.0, 95.0), 1: ("AVOID", None, None)})[0].as_dict()
        bands = {b["band"]: b for b in body["results"]["scripted"]["by_conviction"]}
        assert bands["75-84"]["closed"] == 1
        assert bands["85-100"]["closed"] == 0
        assert body["results"]["scripted"]["performance"]["thin"] is True


class TestWhatAStrategySees:
    def test_never_a_bar_after_the_session_being_judged(self) -> None:
        _, strategy = _replay([], {})
        assert all(s["last_bar"] <= s["day"] for s in strategy.seen)
        assert any(s["last_bar"] == s["day"] for s in strategy.seen)

    def test_the_instrument_carries_its_sector(self) -> None:
        _, strategy = _replay([], {})
        assert {s["sector"] for s in strategy.seen} == {"Information Technology"}

    def test_no_sector_is_reported_as_a_limitation(self) -> None:
        report, _ = _replay([], {}, sectors={})
        assert any("brahma_vishnu_mahesh cannot rank" in n for n in report.notes)

    def test_quarters_appear_only_after_their_filing_deadline(self) -> None:
        # Quarter ending 31 Jan 2025 is due by 17 Mar 2025 (45 days): DAYS[10] is 17 Mar.
        quarters = QuarterlyFundamentals(
            symbol="ACME",
            eps=(QuarterPoint(date(2025, 1, 31), 2.0), QuarterPoint(date(2024, 10, 31), 1.0)),
        )
        _, strategy = _replay([], {}, fundamentals=StaticFundamentalsSource({"ACME": quarters}))
        by_day = {s["day"]: s["quarters"] for s in strategy.seen}
        assert by_day[date(2025, 3, 14)] == 1
        assert by_day[date(2025, 3, 17)] == 2


class TestReplaySource:
    def test_midnight_ist_bars_are_cut_at_the_ist_session(self) -> None:
        index = pd.bdate_range("2025-03-03", periods=10).tz_localize("Asia/Kolkata")
        frame = _frame([])[:10].set_axis(index)
        series = build_series(Instrument("ACME"), "1d", frame, "fake")
        source = ReplayPriceSource({"ACME": series}).at(date(2025, 3, 5))
        served = source.history(Instrument("ACME"))
        assert session_dates(served)[-1] == date(2025, 3, 5)

    def test_serves_at_least_the_live_minimum_window(self) -> None:
        long = FakePriceSource(bars=1500).history(Instrument("ACME"), lookback_days=1500)
        dates = session_dates(long)
        as_of = dates[1200]
        served = ReplayPriceSource({"ACME": long}).at(as_of).history(
            Instrument("ACME"), lookback_days=100
        )
        first = session_dates(served)[0]
        assert (as_of - first).days >= 819
        assert session_dates(served)[-1] == as_of

    def test_filing_deadlines(self) -> None:
        assert filed_by(date(2025, 6, 30)) == date(2025, 8, 14)
        assert filed_by(date(2025, 3, 31)) == date(2025, 5, 30)  # year end: 60 days

    def test_as_of_fundamentals_hides_unfiled_quarters(self) -> None:
        quarters = QuarterlyFundamentals(
            symbol="ACME", eps=(QuarterPoint(date(2025, 6, 30), 3.0),),
            revenue=(QuarterPoint(date(2025, 6, 30), 30.0),),
        )
        inner = StaticFundamentalsSource({"ACME": quarters})
        early = AsOfFundamentalsSource(inner=inner, as_of=date(2025, 8, 13))
        late = AsOfFundamentalsSource(inner=inner, as_of=date(2025, 8, 14))
        assert early.quarterly(Instrument("ACME")).is_empty
        assert len(late.quarterly(Instrument("ACME")).eps) == 1


class TestExitRules:
    def test_every_registered_strategy_has_an_exit_rule(self) -> None:
        assert set(StrategyRegistry.discover().ids()) <= set(EXIT_RULES)

    def _closes(self, values: list[float], end: str = "2025-06-06") -> pd.DataFrame:
        index = pd.bdate_range(end=end, periods=len(values), tz="UTC")
        return pd.DataFrame({"open": values, "high": values, "low": values, "close": values,
                             "volume": [1.0] * len(values)}, index=index)

    def test_minervini_checks_only_at_the_week_end(self) -> None:
        falling = [200.0] * 60 + [100.0]
        friday = self._closes(falling, end="2025-06-06")
        thursday = self._closes(falling, end="2025-06-05")
        assert EXIT_RULES["minervini"].check(friday, None)
        assert EXIT_RULES["minervini"].check(thursday, None) is None

    def test_young_momentum_exits_below_its_20_day_ema(self) -> None:
        assert EXIT_RULES["young_momentum"].check(self._closes([100.0] * 30 + [90.0]), None)
        assert EXIT_RULES["young_momentum"].check(self._closes([100.0] * 31), None) is None

    def test_bvm_reads_the_benchmark_not_the_stock(self) -> None:
        stock = self._closes([100.0] * 150)
        weak_market = self._closes([200.0] * 140 + [100.0] * 10)
        assert EXIT_RULES["brahma_vishnu_mahesh"].check(stock, weak_market)
        assert EXIT_RULES["brahma_vishnu_mahesh"].check(stock, None) is None

    def test_every_rule_states_what_it_does_not_model(self) -> None:
        for rule in EXIT_RULES.values():
            body = rule.describe()
            assert body["plan_rule"] and body["checked"]
            assert isinstance(body["not_modelled"], list)


class TestParallelReplayIsTheSameReplay:
    def test_two_workers_give_the_same_trades_as_one(self) -> None:
        source = FakePriceSource(bars=900, drift=0.0012, volatility=0.018)
        today = datetime.now(UTC).date()
        base = {
            "start": today - timedelta(days=200), "end": today - timedelta(days=5),
            "symbols": ("AAA", "BBB", "CCC"), "step_sessions": 5,
            "sectors": {"AAA": "Information Technology"},
        }
        registry = StrategyRegistry.discover()
        single = run(BacktestConfig(**base), source, registry, Weekdays()).as_dict()
        double = run(BacktestConfig(**base, workers=2), source, registry, Weekdays()).as_dict()
        assert single["evaluations"] == double["evaluations"] > 0
        for sid in registry.ids():
            a, b = single["results"][sid], double["results"][sid]
            assert a["verdicts"] == b["verdicts"]
            assert sorted(map(str, a["trade_log"])) == sorted(map(str, b["trade_log"]))


class TestSessionsWhereTheCalendarIsSilent:
    def test_uncovered_years_use_the_days_the_market_traded(self) -> None:
        from app.data.protocols import CalendarNotCovered

        class Uncovered:
            def is_trading_day(self, day: date) -> bool:
                raise CalendarNotCovered(day.year, (2026,))

        market = _frame([]).drop(index=_frame([]).index[3])  # the index skipped DAYS[3]
        prices = StaticPriceSource({"ACME": _frame([]), "^NSEI": market, "^CRSLDX": market})
        strategy = Scripted({})
        report = run(
            BacktestConfig(start=DAYS[0], end=DAYS[-1], symbols=("ACME",), step_sessions=1,
                           sectors={"ACME": "IT"}),
            prices, _registry(("scripted", strategy)), Uncovered(),
        )
        assert report.sessions == len(DAYS) - 1
        assert DAYS[3] not in {s["day"] for s in strategy.seen}
        assert any("does not cover 2025" in n for n in report.notes)


class TestBacktestApiOptions:
    def test_sectors_and_options_reach_the_run(self, client) -> None:
        today = datetime.now(UTC).date()
        response = client.post(
            "/backtest/run",
            json={
                "symbols": ["RELIANCE", "TCS"],
                "start": (today - timedelta(days=90)).isoformat(),
                "step_sessions": 20,
                "entry_mode": "next_open",
                "round_trip_cost_pct": 0.3,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["config"]["sectors_known"] == 2
        assert body["config"]["entry_mode"] == "next_open"
        assert body["cost_model"]["round_trip_cost_pct"] == 0.3
        assert {r["strategy_id"] for r in body["exit_rules"]} == set(body["results"])

    def test_an_interactive_window_is_bounded(self, client) -> None:
        response = client.post(
            "/backtest/run",
            json={"symbols": ["RELIANCE"], "start": "2019-01-01", "end": "2026-01-01"},
        )
        assert response.status_code == 422
