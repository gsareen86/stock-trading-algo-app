"""Signal scoreboard: forward returns of published verdicts, measured honestly.

Prices here are hand-built so every expected figure can be checked with a calculator: the stock
opens at ``99.5 + i`` and closes at ``100 + i`` on session ``i``; the benchmark is flat at 1000,
so excess return equals the stock's own return.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app.data.fake import StaticPriceSource
from app.discovery.scoreboard import (
    THIN_SAMPLE,
    Signal,
    _Bars,
    build_scoreboard,
    collect_signals,
    entry_index,
    measure_signals,
    normalise_horizons,
    summarise,
)
from app.domain.instrument import Instrument
from app.domain.prices import build_series
from app.persistence.models import ScanEntry, ScanRun

SESSIONS = pd.bdate_range("2026-01-05", periods=80)  # Monday 5 January 2026 onward
BENCH = "^CRSLDX"


def _stock_frame(index=SESSIONS) -> pd.DataFrame:
    n = len(index)
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * n,
        },
        index=index,
    )


def _flat_frame(level: float = 1000.0, index=SESSIONS) -> pd.DataFrame:
    n = len(index)
    return pd.DataFrame(
        {"open": [level] * n, "high": [level] * n, "low": [level] * n,
         "close": [level] * n, "volume": [0.0] * n},
        index=index,
    )


def _signal(
    *,
    at: datetime,
    symbol: str = "UPCO",
    strategy_id: str = "minervini",
    stance: str = "BUY",
    conviction: int = 80,
    stop: float | None = None,
    is_new: bool = True,
) -> Signal:
    return Signal(
        run_id=1,
        strategy_id=strategy_id,
        symbol=symbol,
        stance=stance,
        conviction=conviction,
        signalled_at=at,
        benchmark=BENCH,
        is_new=is_new,
        plan_stop=stop,
    )


def _source(**frames: pd.DataFrame) -> StaticPriceSource:
    return StaticPriceSource({"UPCO": _stock_frame(), BENCH: _flat_frame(), **frames})


# Tuesday 6 January 2026, 17:30 IST — after the close, so Wednesday's open is the entry.
AFTER_CLOSE_TUE = datetime(2026, 1, 6, 12, 0, tzinfo=UTC)
# Tuesday 6 January 2026, 07:30 IST — before the open, so Tuesday's own open is the entry.
BEFORE_OPEN_TUE = datetime(2026, 1, 6, 2, 0, tzinfo=UTC)


class TestEntryHasNoLookahead:
    def _bars(self) -> _Bars:
        return _Bars.from_series(build_series(Instrument("UPCO"), "1d", _stock_frame(), "fake"))

    def test_a_scan_after_the_open_enters_at_the_next_session(self) -> None:
        bars = self._bars()
        i = entry_index(bars, AFTER_CLOSE_TUE)
        assert bars.dates[i] == date(2026, 1, 7)

    def test_a_scan_before_the_open_enters_the_same_day(self) -> None:
        bars = self._bars()
        i = entry_index(bars, BEFORE_OPEN_TUE)
        assert bars.dates[i] == date(2026, 1, 6)

    def test_a_weekend_scan_enters_on_monday(self) -> None:
        bars = self._bars()
        saturday = datetime(2026, 1, 10, 6, 0, tzinfo=UTC)
        assert bars.dates[entry_index(bars, saturday)] == date(2026, 1, 12)

    def test_bars_stamped_at_midnight_ist_keep_their_session_date(self) -> None:
        """Midnight IST is 18:30 UTC the day before; reading the UTC date would shift every
        session by one, and an entry would land on the bar the scan had already seen."""
        ist_index = SESSIONS.tz_localize("Asia/Kolkata")
        series = build_series(Instrument("UPCO"), "1d", _stock_frame(ist_index), "fake")
        assert series.frame.index[0].hour == 18  # stored in UTC, previous calendar day
        bars = _Bars.from_series(series)
        assert bars.dates[0] == date(2026, 1, 5)
        assert bars.dates[entry_index(bars, AFTER_CLOSE_TUE)] == date(2026, 1, 7)


class TestForwardReturns:
    def test_return_runs_from_entry_open_to_the_nth_close(self) -> None:
        [outcome] = measure_signals(
            [_signal(at=AFTER_CLOSE_TUE)], _source(), horizons=(5,), today=date(2026, 4, 30)
        )
        assert outcome.status == "measured"
        assert outcome.entry_date == date(2026, 1, 7)
        assert outcome.entry_price == pytest.approx(101.5)  # session 2 opens at 99.5 + 2
        h = outcome.horizon(5)
        assert h.exit_date == date(2026, 1, 13)  # entry session counts as the first of five
        assert h.exit_price == pytest.approx(106.0)
        assert h.return_pct == pytest.approx((106.0 / 101.5 - 1) * 100, abs=1e-3)
        assert h.benchmark_return_pct == pytest.approx(0.0)
        assert h.excess_pp == pytest.approx(h.return_pct)

    def test_excess_is_measured_against_the_benchmark_over_the_same_sessions(self) -> None:
        rising = _flat_frame()
        rising["close"] = [1000.0 * (1.01 ** (i + 1)) for i in range(len(rising))]
        rising["open"] = [1000.0 * (1.01**i) for i in range(len(rising))]
        [outcome] = measure_signals(
            [_signal(at=AFTER_CLOSE_TUE)],
            _source(**{BENCH: rising}),
            horizons=(5,),
            today=date(2026, 4, 30),
        )
        h = outcome.horizon(5)
        # Benchmark: open of session 2 to close of session 6 = 1.01^7 / 1.01^2.
        assert h.benchmark_return_pct == pytest.approx((1.01**5 - 1) * 100, abs=1e-3)
        assert h.excess_pp == pytest.approx(h.return_pct - h.benchmark_return_pct, abs=1e-3)

    def test_a_horizon_that_has_not_elapsed_is_pending_not_zero(self) -> None:
        late = datetime.combine(SESSIONS[-3].date(), datetime.min.time(), tzinfo=UTC) + timedelta(
            hours=12
        )
        [outcome] = measure_signals(
            [_signal(at=late)], _source(), horizons=(1, 20), today=date(2026, 4, 30)
        )
        assert outcome.status == "measured"
        assert outcome.horizon(1).measured
        assert not outcome.horizon(20).measured
        assert outcome.horizon(20).return_pct is None

    def test_a_signal_with_no_session_since_is_pending(self) -> None:
        after_last = datetime.combine(SESSIONS[-1].date(), datetime.min.time(), tzinfo=UTC)
        [outcome] = measure_signals(
            [_signal(at=after_last + timedelta(hours=12))], _source(), horizons=(5,)
        )
        assert outcome.status == "pending"
        assert outcome.entry_price is None

    def test_a_name_with_no_prices_is_unpriced_rather_than_a_loss(self) -> None:
        [outcome] = measure_signals(
            [_signal(at=AFTER_CLOSE_TUE, symbol="GONE")], _source(), horizons=(5,)
        )
        assert outcome.status == "unpriced"
        assert outcome.horizons == ()

    def test_the_plan_stop_is_checked_against_lows_inside_the_window(self) -> None:
        touched, clear = measure_signals(
            [
                _signal(at=AFTER_CLOSE_TUE, stop=101.0),  # entry-session low is 100.5
                _signal(at=AFTER_CLOSE_TUE, stop=90.0),
            ],
            _source(),
            horizons=(5,),
            today=date(2026, 4, 30),
        )
        assert touched.horizon(5).stop_touched is True
        assert clear.horizon(5).stop_touched is False

    def test_no_plan_stop_means_no_stop_reading(self) -> None:
        [outcome] = measure_signals([_signal(at=AFTER_CLOSE_TUE)], _source(), horizons=(5,))
        assert outcome.horizon(5).stop_touched is None


class TestSummaryStaysInsideOneStrategy:
    def _outcomes(self):
        signals = [
            _signal(at=AFTER_CLOSE_TUE, strategy_id="young_momentum", conviction=90),
            _signal(at=AFTER_CLOSE_TUE, strategy_id="minervini", conviction=78),
            _signal(at=AFTER_CLOSE_TUE, strategy_id="minervini", conviction=91),
            _signal(at=AFTER_CLOSE_TUE, strategy_id="minervini", stance="AVOID", conviction=10),
        ]
        return measure_signals(signals, _source(), horizons=(5,), today=date(2026, 4, 30))

    def test_strategies_are_alphabetical_and_never_pooled(self) -> None:
        report = summarise(self._outcomes(), horizons=(5,))
        assert [s["strategy_id"] for s in report] == ["minervini", "young_momentum"]
        young = report[1]
        # Only young_momentum's one BUY: Minervini's BUY did not leak into it.
        assert young["rows"][0]["signals"] == 1
        assert {r["stance"] for r in young["rows"]} == {"BUY"}

    def test_each_stance_has_a_total_row_and_bands_only_when_they_differ(self) -> None:
        minervini = summarise(self._outcomes(), horizons=(5,))[0]
        keys = [(r["stance"], r["band"]) for r in minervini["rows"]]
        # Two BUY bands are informative; a single AVOID band would repeat the total.
        assert keys == [("BUY", "all"), ("BUY", "75-84"), ("BUY", "85-100"), ("AVOID", "all")]

    def test_a_small_bucket_is_flagged_thin(self) -> None:
        row = summarise(self._outcomes(), horizons=(5,))[1]["rows"][0]
        stats = row["horizons"]["5"]
        assert stats["measured"] == 1 < THIN_SAMPLE
        assert stats["thin"] is True
        assert stats["excess_se_pp"] is None  # one observation has no spread

    def test_the_report_holds_no_figure_computed_across_strategies(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "app" / "discovery" / "scoreboard.py")
        text = source.read_text("utf-8").lower()
        for banned in ("consensus", "composite", "blended", "mean_conviction", "agreement"):
            assert banned not in text, banned


def _seed_runs(session_factory, stances_by_run: list[dict[str, str]]) -> list[int]:
    """One completed run per element: {symbol: minervini stance}, a week apart."""
    ids: list[int] = []
    with session_factory() as session:
        for week, stances in enumerate(stances_by_run):
            stamp = AFTER_CLOSE_TUE + timedelta(days=7 * week)
            run = ScanRun(
                trigger="scheduled",
                universe_origin="stub",
                benchmark=BENCH,
                outcome="complete",
                started_at=stamp - timedelta(minutes=5),
                finished_at=stamp,
            )
            session.add(run)
            session.flush()
            for symbol, stance in stances.items():
                session.add(
                    ScanEntry(
                        run_id=run.id,
                        symbol=symbol,
                        ranked_by="minervini",
                        ranked_conviction=80,
                        ranked_stance=stance,
                        verdicts=[
                            {
                                "strategy_id": "minervini",
                                "ticker": symbol,
                                "as_of": stamp.isoformat(),
                                "stance": stance,
                                "conviction": 80 if stance == "BUY" else 30,
                                "plan": {"entry": 120.0, "stop": 95.0} if stance == "BUY" else None,
                            }
                        ],
                    )
                )
            ids.append(run.id)
        # A failed run is never a source of signals.
        session.add(ScanRun(trigger="requested", outcome="failed", benchmark=BENCH))
        session.commit()
    return ids


class TestCollectingSignals:
    def test_a_repeated_stance_is_not_a_new_signal(self, session_factory) -> None:
        _seed_runs(
            session_factory,
            [{"UPCO": "BUY"}, {"UPCO": "BUY"}, {"UPCO": "WATCH"}, {}, {"UPCO": "BUY"}],
        )
        signals = collect_signals(session_factory)
        assert [(s.stance, s.is_new) for s in signals] == [
            ("BUY", True),
            ("BUY", False),  # unchanged from last week
            ("WATCH", True),
            ("BUY", True),  # absent the week before, so a fresh decision
        ]
        assert signals[0].plan_stop == 95.0
        assert signals[2].plan_stop is None

    def test_only_the_most_recent_runs_are_read(self, session_factory) -> None:
        _seed_runs(session_factory, [{"UPCO": "BUY"}, {"UPCO": "WATCH"}, {"UPCO": "AVOID"}])
        signals = collect_signals(session_factory, max_runs=2)
        assert [s.stance for s in signals] == ["WATCH", "AVOID"]


class TestBuildScoreboard:
    def test_no_scan_yet_says_so(self, session_factory) -> None:
        board = build_scoreboard(session_factory, _source())
        assert board["runs"]["count"] == 0
        assert board["strategies"] == []
        assert "No completed discovery scan" in board["notes"][0]

    def test_new_signals_by_default_and_all_on_request(self, session_factory) -> None:
        _seed_runs(session_factory, [{"UPCO": "BUY"}, {"UPCO": "BUY"}, {"UPCO": "BUY"}])
        new = build_scoreboard(session_factory, _source(), horizons=(5,), today=date(2026, 4, 30))
        every = build_scoreboard(
            session_factory, _source(), horizons=(5,), signals="all", today=date(2026, 4, 30)
        )
        assert new["totals"]["signals"] == 1
        assert every["totals"]["signals"] == 3
        assert any("overlap" in note for note in every["notes"])
        assert new["charges_included"] is False
        assert any("gross" in b for b in new["biases"])

    def test_recent_buys_carry_their_outcome(self, session_factory) -> None:
        _seed_runs(session_factory, [{"UPCO": "BUY", "OTHER": "AVOID"}])
        board = build_scoreboard(
            session_factory, _source(), horizons=(5, 20), today=date(2026, 4, 30)
        )
        [recent] = board["recent_buys"]
        assert recent["symbol"] == "UPCO"
        assert recent["entry_date"] == "2026-01-07"
        assert recent["horizons"]["5"]["return_pct"] == pytest.approx(
            (106.0 / 101.5 - 1) * 100, abs=1e-3
        )
        assert board["totals"]["unpriced"] == 1  # OTHER has no prices in the source


class TestHorizonParsing:
    def test_out_of_range_and_duplicate_horizons_are_dropped(self) -> None:
        assert normalise_horizons([60, 5, 5, 0, 999]) == (5, 60)

    def test_nothing_usable_falls_back_to_the_defaults(self) -> None:
        assert normalise_horizons([]) == (5, 20, 60)


class TestScoreboardApi:
    def test_endpoint_reports_per_strategy_outcomes(self, client) -> None:
        app = client.app
        _seed_runs(app.state.session_factory, [{"UPCO": "BUY"}])
        app.state.price_source = _source()

        response = client.get("/discovery/scoreboard?horizons=5,20&refresh=true")
        assert response.status_code == 200
        body = response.json()
        assert body["horizons"] == [5, 20]
        assert body["signal_filter"] == "new"
        [strategy] = body["strategies"]
        assert strategy["strategy_id"] == "minervini"
        assert strategy["rows"][0]["horizons"]["5"]["measured"] == 1

    def test_bad_parameters_are_refused(self, client) -> None:
        assert client.get("/discovery/scoreboard?signals=some").status_code == 422
        assert client.get("/discovery/scoreboard?horizons=a,b").status_code == 422
