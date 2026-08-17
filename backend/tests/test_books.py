"""The ledger, portfolio analytics and risk.

Two invariants carry this increment: a position is *derived* from trades and never stored
independently, and risk decides about acting without ever altering a verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.books import analytics as analytics_module
from app.books.ledger import InsufficientQuantity, Ledger
from app.domain.position import (
    Book,
    Position,
    Side,
    Trade,
    derive_position,
)
from app.domain.verdict import Evidence, Stance, Verdict
from app.risk.rules import PortfolioState, RiskLimits, RiskOutcome, assess

T0 = datetime(2026, 8, 1, tzinfo=UTC)


def _trade(side: Side, qty: int, price: float, days: int = 0, **kw) -> Trade:
    return Trade(
        book=Book.SWING,
        ticker="RELIANCE",
        side=side,
        quantity=qty,
        price=price,
        executed_at=T0 + timedelta(days=days),
        **kw,
    )


def _verdict(stance: Stance = Stance.BUY, conviction: int = 80, ticker: str = "RELIANCE"):
    return Verdict(
        strategy_id="minervini",
        ticker=ticker,
        as_of=T0,
        stance=stance,
        conviction=conviction,
        evidence=(Evidence(id="e1", label="l", value=1.0, source_ref="price://x"),),
    )


class TestPositionIsDerived:
    def test_single_buy(self) -> None:
        pos = derive_position(Book.SWING, "RELIANCE", [_trade(Side.BUY, 10, 100.0)])

        assert pos.quantity == 10
        assert pos.average_cost == pytest.approx(100.0)
        assert pos.is_open

    def test_averaging_up(self) -> None:
        trades = [_trade(Side.BUY, 10, 100.0), _trade(Side.BUY, 10, 120.0, days=1)]

        pos = derive_position(Book.SWING, "RELIANCE", trades)

        assert pos.quantity == 20
        assert pos.average_cost == pytest.approx(110.0)

    def test_partial_sell_realises_and_keeps_average_cost(self) -> None:
        trades = [_trade(Side.BUY, 10, 100.0), _trade(Side.SELL, 4, 130.0, days=1)]

        pos = derive_position(Book.SWING, "RELIANCE", trades)

        assert pos.quantity == 6
        assert pos.average_cost == pytest.approx(100.0)
        assert pos.realised_pnl == pytest.approx(120.0)

    def test_full_exit_closes_the_position(self) -> None:
        trades = [_trade(Side.BUY, 10, 100.0), _trade(Side.SELL, 10, 130.0, days=1)]

        pos = derive_position(Book.SWING, "RELIANCE", trades)

        assert pos.quantity == 0
        assert pos.is_open is False
        assert pos.realised_pnl == pytest.approx(300.0)
        assert pos.first_acquired is None

    def test_reentry_after_exit(self) -> None:
        trades = [
            _trade(Side.BUY, 10, 100.0),
            _trade(Side.SELL, 10, 130.0, days=1),
            _trade(Side.BUY, 5, 140.0, days=2),
        ]

        pos = derive_position(Book.SWING, "RELIANCE", trades)

        assert pos.quantity == 5
        assert pos.average_cost == pytest.approx(140.0)
        assert pos.realised_pnl == pytest.approx(300.0)

    def test_order_is_by_execution_time_not_insertion(self) -> None:
        """Trades arriving out of order must still fold to the same position."""
        forward = [_trade(Side.BUY, 10, 100.0), _trade(Side.BUY, 10, 200.0, days=1)]
        backward = list(reversed(forward))

        assert derive_position(Book.SWING, "R", forward).average_cost == pytest.approx(
            derive_position(Book.SWING, "R", backward).average_cost
        )

    def test_oversell_is_clamped_not_shorted(self) -> None:
        """This platform is long-only; a negative quantity would be a short nobody opened."""
        trades = [_trade(Side.BUY, 5, 100.0), _trade(Side.SELL, 50, 130.0, days=1)]

        pos = derive_position(Book.SWING, "RELIANCE", trades)

        assert pos.quantity == 0

    def test_unrealised_is_none_without_a_price(self) -> None:
        """Unknown and nothing are different facts; zero would enter a portfolio total."""
        pos = derive_position(Book.SWING, "RELIANCE", [_trade(Side.BUY, 10, 100.0)])

        assert pos.unrealised_pnl(None) is None
        assert pos.unrealised_pnl(120.0) == pytest.approx(200.0)

    def test_trade_rejects_nonsense_quantities(self) -> None:
        with pytest.raises(ValueError):
            _trade(Side.BUY, 0, 100.0)
        with pytest.raises(ValueError):
            _trade(Side.BUY, 10, 0.0)


class TestLedger:
    @pytest.fixture
    def ledger(self, session_factory) -> Ledger:
        return Ledger(session_factory)

    def test_fill_records_and_derives(self, ledger: Ledger) -> None:
        ledger.fill(Book.SWING, "RELIANCE", Side.BUY, 10, 100.0)

        pos = ledger.position(Book.SWING, "RELIANCE")
        assert pos.quantity == 10
        assert pos.average_cost == pytest.approx(100.0)

    def test_books_are_independent(self, ledger: Ledger) -> None:
        ledger.fill(Book.SWING, "RELIANCE", Side.BUY, 10, 100.0)
        ledger.fill(Book.LONGTERM, "RELIANCE", Side.BUY, 5, 200.0)

        assert ledger.position(Book.SWING, "RELIANCE").quantity == 10
        assert ledger.position(Book.LONGTERM, "RELIANCE").quantity == 5

    def test_one_ledger_serves_every_book(self) -> None:
        """Principle 2: the book is a parameter. Adding one must be an enum member, no more."""
        import inspect

        from app.books import ledger as module

        classes = [
            name
            for name, _ in inspect.getmembers(module, inspect.isclass)
            if name.endswith("Ledger")
        ]

        assert classes == ["Ledger"]

    def test_selling_more_than_held_is_refused(self, ledger: Ledger) -> None:
        ledger.fill(Book.SWING, "RELIANCE", Side.BUY, 5, 100.0)

        with pytest.raises(InsufficientQuantity):
            ledger.fill(Book.SWING, "RELIANCE", Side.SELL, 50, 120.0)

    def test_positions_lists_only_open_by_default(self, ledger: Ledger) -> None:
        ledger.fill(Book.SWING, "OPEN", Side.BUY, 10, 100.0)
        ledger.fill(Book.SWING, "CLOSED", Side.BUY, 10, 100.0)
        ledger.fill(Book.SWING, "CLOSED", Side.SELL, 10, 120.0)

        assert [p.ticker for p in ledger.positions(Book.SWING)] == ["OPEN"]
        assert len(ledger.positions(Book.SWING, open_only=False)) == 2

    def test_ticker_is_normalised(self, ledger: Ledger) -> None:
        ledger.fill(Book.SWING, " reliance ", Side.BUY, 1, 100.0)

        assert ledger.position(Book.SWING, "RELIANCE").quantity == 1

    def test_fill_is_the_only_trade_constructor(self) -> None:
        """Principle 7: no broker class that looks like it executes and silently does not."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        pattern = re.compile(r"class\s+\w*(Broker|Executor)\w*\b")
        offenders = [
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if pattern.search(p.read_text("utf-8"))
        ]

        assert offenders == []


class TestAnalytics:
    def test_exposure_and_concentration(self) -> None:
        positions = [
            Position(Book.SWING, "A", 10, 100.0, 0.0),
            Position(Book.SWING, "B", 10, 300.0, 0.0),
        ]
        report = analytics_module.build(Book.SWING, positions, [], {"A": 110.0, "B": 310.0})

        assert report.cost_basis == pytest.approx(4000.0)
        assert report.concentration()["B"] == pytest.approx(75.0)
        assert report.largest_position_pct() == pytest.approx(75.0)

    def test_market_value_is_none_when_a_price_is_missing(self) -> None:
        """A partial total is a misleading one."""
        positions = [
            Position(Book.SWING, "A", 10, 100.0, 0.0),
            Position(Book.SWING, "B", 10, 300.0, 0.0),
        ]
        report = analytics_module.build(Book.SWING, positions, [], {"A": 110.0})

        assert report.market_value is None
        assert report.unrealised_pnl_gross is None

    def test_pnl_is_labelled_gross(self) -> None:
        """A P&L that quietly omits STT and brokerage is one someone will find wrong later."""
        report = analytics_module.build(Book.SWING, [], [], {}).as_dict()

        assert report["charges_included"] is False
        assert "realised_pnl_gross" in report
        assert "unrealised_pnl_gross" in report

    def test_win_rate_counts_only_closed_positions(self) -> None:
        """Counting unrealised gains as wins is how a strategy looks good until it is closed."""
        positions = [
            Position(Book.SWING, "OPEN", 10, 100.0, 0.0, trade_count=1),
            Position(Book.SWING, "WIN", 0, 0.0, 500.0, trade_count=2),
            Position(Book.SWING, "LOSS", 0, 0.0, -200.0, trade_count=2),
        ]

        stats = analytics_module.closed_trade_stats(positions)

        assert stats["closed"] == 2
        assert stats["win_rate_pct"] == pytest.approx(50.0)

    def test_attribution_reports_without_ranking(self) -> None:
        trades = [
            _trade(Side.BUY, 10, 100.0, strategy_id="minervini"),
            _trade(Side.BUY, 5, 200.0, days=1, strategy_id="young_momentum"),
        ]

        report = analytics_module.attribution(trades)

        assert report["minervini"]["trades"] == 1
        assert "rank" not in report and "best" not in report


class TestRiskVetoesButNeverRewrites:
    def test_a_blocked_verdict_is_unchanged(self) -> None:
        """`Verdict` is frozen and only narration mutates it — risk cannot downgrade a BUY."""
        verdict = _verdict(Stance.BUY, conviction=90)
        state = PortfolioState(
            book=Book.SWING,
            positions=(Position(Book.SWING, "RELIANCE", 10, 100.0, 0.0),),
        )

        decision = assess(verdict, state, RiskLimits(), last_price=120.0)

        assert decision.outcome is RiskOutcome.BLOCKED
        assert decision.gate_id == "already_held"
        assert verdict.stance is Stance.BUY
        assert verdict.conviction == 90

    def test_verdict_has_no_mutator_risk_could_use(self) -> None:
        verdict = _verdict()

        with pytest.raises((AttributeError, Exception)):
            verdict.stance = Stance.AVOID  # type: ignore[misc]

    def test_non_buy_is_not_actionable_rather_than_blocked(self) -> None:
        """Calling a WATCH "blocked" would misreport the strategy's own conclusion."""
        decision = assess(
            _verdict(Stance.WATCH), PortfolioState(book=Book.SWING), RiskLimits(), 100.0
        )

        assert decision.outcome is RiskOutcome.NOT_ACTIONABLE

    def test_position_count_gate(self) -> None:
        held = tuple(
            Position(Book.SWING, f"S{i}", 1, 100.0, 0.0) for i in range(3)
        )
        state = PortfolioState(book=Book.SWING, positions=held)

        decision = assess(_verdict(), state, RiskLimits(max_positions=3), 100.0)

        assert decision.gate_id == "position_count"

    def test_capital_gate(self) -> None:
        state = PortfolioState(
            book=Book.SWING,
            positions=(Position(Book.SWING, "OTHER", 100, 1000.0, 0.0),),
        )

        decision = assess(_verdict(), state, RiskLimits(capital_inr=50_000.0), 100.0)

        assert decision.gate_id == "capital"

    def test_missing_price_blocks_rather_than_guesses(self) -> None:
        decision = assess(_verdict(), PortfolioState(book=Book.SWING), RiskLimits(), None)

        assert decision.gate_id == "no_price"

    def test_proceed_sizes_against_conviction(self) -> None:
        limits = RiskLimits(capital_inr=10_00_000.0, target_position_pct=10.0)

        high = assess(_verdict(conviction=100), PortfolioState(book=Book.SWING), limits, 100.0)
        low = assess(_verdict(conviction=50), PortfolioState(book=Book.SWING), limits, 100.0)

        assert high.proceed and low.proceed
        assert high.quantity == 2 * low.quantity

    def test_position_cap_is_respected(self) -> None:
        limits = RiskLimits(
            capital_inr=10_00_000.0, target_position_pct=90.0, max_position_pct=15.0
        )

        decision = assess(_verdict(conviction=100), PortfolioState(book=Book.SWING), limits, 100.0)

        assert decision.notional <= 1_50_000.0

    def test_risk_never_compares_two_verdicts(self) -> None:
        """A portfolio layer is exactly where cross-strategy ranking would look reasonable.

        Checked against *definitions* rather than the word: the module's own docstrings say
        "rank" repeatedly, explaining why it does not.
        """
        import inspect
        import re

        from app.risk import rules

        source = inspect.getsource(rules)
        defined = re.compile(r"def\s+(rank|score|allocate|compare|prioriti[sz]e)\w*", re.I)
        assert defined.search(source) is None

        # No rule sorts or maxes over a collection of verdicts.
        for banned in ("sorted(verdicts", "max(verdicts", "for verdict in verdicts"):
            assert banned not in source

        signature = inspect.signature(rules.assess)
        assert "verdict" in signature.parameters
        # Singular: it sizes one verdict against portfolio state, never a set against each other.
        assert "verdicts" not in signature.parameters


class TestBooksApi:
    @staticmethod
    def _client(settings):
        from fastapi.testclient import TestClient

        from app.data.fake import FakePriceSource
        from app.main import create_app

        app = create_app(settings)
        app.state.price_source = FakePriceSource(bars=400)
        return TestClient(app)

    def test_fill_then_read_the_position(self, settings) -> None:
        client = self._client(settings)

        posted = client.post(
            "/books/swing/fill",
            json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "price": 1400.0},
        )

        assert posted.status_code == 200
        body = posted.json()
        assert body["position"]["quantity"] == 10
        assert body["trade"]["value"] == pytest.approx(14000.0)

    def test_overselling_is_a_422_not_a_500(self, settings) -> None:
        client = self._client(settings)
        client.post(
            "/books/swing/fill",
            json={"ticker": "RELIANCE", "side": "buy", "quantity": 5, "price": 100.0},
        )

        response = client.post(
            "/books/swing/fill",
            json={"ticker": "RELIANCE", "side": "sell", "quantity": 50, "price": 120.0},
        )

        assert response.status_code == 422

    def test_books_do_not_leak_into_each_other(self, settings) -> None:
        client = self._client(settings)
        client.post(
            "/books/swing/fill",
            json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "price": 100.0},
        )

        longterm = client.get("/books/longterm/positions").json()

        assert longterm["count"] == 0

    def test_analytics_declares_charges_absent(self, settings) -> None:
        body = self._client(settings).get("/books/swing/analytics").json()

        assert body["charges_included"] is False
        assert "attribution" in body
        assert "closed_trades" in body

    def test_unknown_book_is_rejected(self, settings) -> None:
        response = self._client(settings).get("/books/nonsense/positions")

        assert response.status_code == 422
