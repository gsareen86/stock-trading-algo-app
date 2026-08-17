"""Portfolio health scoring and acting on insights.

The line this increment is defined by: **health scores the book's structure, never the stocks
in it.** Blending strategy verdicts is the confluence scorecard; measuring concentration,
deployment and broken theses is a measurement of the portfolio.

And for actions: quantity is re-derived from the ledger at execution, never trusted from an
insight that may be days old.
"""

from __future__ import annotations

import pytest

from app.books.ledger import Ledger
from app.domain.position import Book, Position, Side
from app.health import components as comp
from app.health import score as health_score
from app.insights.actions import Action, ActionRefused, actions_for, execute, plan
from app.insights.kinds import Kind
from tests.conftest import authed_client


def _code_only(source: str) -> str:
    """Strip comments and docstrings so a guard cannot match its own explanation."""
    import io
    import tokenize

    kept: list[str] = []
    previous = tokenize.INDENT
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and previous in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.DEDENT,
            tokenize.NL,
        ):
            continue  # a docstring
        kept.append(token.string)
        if token.type not in (tokenize.NL, tokenize.COMMENT):
            previous = token.type
    return " ".join(kept)


def _pos(ticker: str, qty: int, cost: float) -> Position:
    return Position(Book.SWING, ticker, qty, cost, 0.0)


CAPITAL = 10_00_000.0


class TestComponentsMeasureStructure:
    def test_concentration_penalises_a_single_dominant_name(self) -> None:
        # Five equal names is 20% each — inside the 25% target.
        balanced = comp.concentration([_pos(f"S{i}", 10, 1000.0) for i in range(5)])
        lopsided = comp.concentration([_pos("A", 90, 1000.0), _pos("B", 10, 1000.0)])

        assert balanced.score == 100
        assert lopsided.score < balanced.score
        assert lopsided.measurement == pytest.approx(90.0)

    def test_concentration_is_measured_on_cost_not_market_value(self) -> None:
        """A number that moves because a position appreciated describes the market, not a
        decision."""
        component = comp.concentration([_pos("A", 10, 100.0), _pos("B", 10, 100.0)])

        assert component.measurement == pytest.approx(50.0)

    def test_empty_book_is_not_penalised(self) -> None:
        assert comp.concentration([]).score == 100
        assert comp.thesis_integrity([], set()).score == 100

    def test_diversification_scales_to_the_target(self) -> None:
        assert comp.diversification([_pos("A", 1, 100.0)]).score < 100
        assert comp.diversification([_pos(f"S{i}", 1, 100.0) for i in range(5)]).score == 100

    def test_deployment_penalises_both_idle_and_full(self) -> None:
        idle = comp.deployment([_pos("A", 1, 1000.0)], CAPITAL)
        working = comp.deployment([_pos("A", 700, 1000.0)], CAPITAL)
        stuffed = comp.deployment([_pos("A", 1000, 1000.0)], CAPITAL)

        assert idle.score < working.score
        assert stuffed.score < working.score

    def test_thesis_integrity_weights_by_committed_capital(self) -> None:
        positions = [_pos("BROKEN", 90, 1000.0), _pos("FINE", 10, 1000.0)]

        component = comp.thesis_integrity(positions, {"BROKEN"})

        assert component.measurement == pytest.approx(90.0)
        assert component.score == 10

    def test_every_component_publishes_its_threshold(self) -> None:
        report = health_score.build([_pos("A", 10, 1000.0)], CAPITAL, set())

        for component in report.components:
            payload = component.as_dict()
            assert payload["threshold"] is not None
            assert payload["measurement"] is not None
            assert payload["detail"]


class TestHealthNeverBlendsVerdicts:
    def test_health_module_never_reads_a_conviction_or_verdict(self) -> None:
        """If a portfolio score ever needs a `Verdict`, it has become the wrong thing."""
        import inspect

        from app.health import components, score

        for module in (components, score):
            # Checked against *code*, not prose: both modules' docstrings say "conviction"
            # and "Verdict" repeatedly, explaining why they never touch one.
            code = _code_only(inspect.getsource(module))
            assert "conviction" not in code
            assert "Verdict" not in code
            assert "stance" not in code

    def test_no_per_instrument_score_exists(self) -> None:
        """A per-instrument health number could be sorted, which is the scorecard."""
        import inspect
        import re

        from app.health import components, score

        banned = re.compile(r"def\s+(rank|sort_by|best|score_instrument|score_position)\w*", re.I)
        for module in (components, score):
            assert banned.search(inspect.getsource(module)) is None

    def test_headline_is_never_published_without_components(self) -> None:
        body = health_score.build([_pos("A", 10, 1000.0)], CAPITAL, set()).as_dict()

        assert "score" in body
        assert body["components"], "headline shipped without its breakdown"
        assert len(body["components"]) == 4

    def test_score_is_the_weighted_mean_of_components(self) -> None:
        report = health_score.build([_pos("A", 10, 1000.0)], CAPITAL, set())

        expected = round(
            sum(c.score * c.weight for c in report.components)
            / sum(c.weight for c in report.components)
        )
        assert report.score == expected


class TestGuidance:
    def test_a_concentrated_book_is_told_to_trim(self) -> None:
        positions = [_pos("BIG", 90, 10_000.0), _pos("SMALL", 10, 1000.0)]

        report = health_score.build(positions, CAPITAL, set())
        trims = [s for s in report.steps if s.action == "trim"]

        assert trims and trims[0].ticker == "BIG"
        assert "target" in trims[0].detail

    def test_a_broken_thesis_is_told_to_exit(self) -> None:
        positions = [_pos("BROKEN", 90, 1000.0), _pos("FINE", 10, 1000.0)]

        report = health_score.build(positions, CAPITAL, {"BROKEN"})
        exits = [s for s in report.steps if s.action == "exit"]

        assert exits and exits[0].ticker == "BROKEN"

    def test_steps_are_ordered_by_component_weight(self) -> None:
        """Ordered by weight, not a per-step score — scoring steps would rank actions."""
        positions = [_pos("BROKEN", 90, 10_000.0)]

        report = health_score.build(positions, CAPITAL, {"BROKEN"})
        weights = {c.id: c.weight for c in report.components}
        ordered = [weights[s.component_id] for s in report.steps]

        assert ordered == sorted(ordered, reverse=True)

    def test_no_step_carries_a_score(self) -> None:
        report = health_score.build([_pos("BIG", 90, 10_000.0)], CAPITAL, set())

        for step in report.steps:
            assert "score" not in step.as_dict()

    def test_guidance_never_names_what_to_buy(self) -> None:
        """Choosing between names is a strategy's job; guidance about spread must not do it."""
        report = health_score.build([_pos("A", 1, 1000.0)], CAPITAL, set())
        spread = [s for s in report.steps if s.component_id == "diversification"]

        assert spread
        assert "does not name one" in spread[0].detail

    def test_a_healthy_book_needs_no_steps(self) -> None:
        positions = [_pos(f"S{i}", 30, 5000.0) for i in range(6)]

        report = health_score.build(positions, CAPITAL, set())

        assert report.band in ("healthy", "watch")
        assert report.steps == []


class TestActionsAreDeclaredByKind:
    def test_each_kind_has_its_actions(self) -> None:
        assert "exit" in actions_for(Kind.THESIS_BROKEN.value)
        assert "trim" in actions_for(Kind.CONCENTRATION.value)
        assert "buy" in actions_for(Kind.OPPORTUNITY.value)

    def test_review_is_always_available(self) -> None:
        """The honest option for "I looked and I am not acting"."""
        for kind in Kind:
            assert "review" in actions_for(kind.value)

    def test_an_unknown_kind_still_offers_review(self) -> None:
        assert actions_for("something_new") == ("review",)


class TestActionsReDeriveFromTheLedger:
    @pytest.fixture
    def ledger(self, session_factory) -> Ledger:
        led = Ledger(session_factory)
        led.fill(Book.SWING, "RELIANCE", Side.BUY, 10, 1000.0, strategy_id="minervini")
        return led

    def _insight(self, kind: Kind = Kind.THESIS_BROKEN, **payload) -> dict:
        return {
            "id": 1,
            "kind": kind.value,
            "ticker": "RELIANCE",
            "payload": payload,
        }

    def test_exit_sells_the_current_holding_not_the_remembered_one(
        self, ledger: Ledger
    ) -> None:
        """An insight saying "you hold 6" may be stale; the ledger is the truth."""
        ledger.fill(Book.SWING, "RELIANCE", Side.SELL, 4, 1100.0)

        prepared = plan(
            Action.EXIT, self._insight(quantity=10), ledger, Book.SWING, last_price=1100.0
        )

        assert prepared.quantity == 6

    def test_exit_is_refused_when_the_position_is_gone(self, ledger: Ledger) -> None:
        ledger.fill(Book.SWING, "RELIANCE", Side.SELL, 10, 1100.0)

        with pytest.raises(ActionRefused, match="no open"):
            plan(Action.EXIT, self._insight(), ledger, Book.SWING, last_price=1100.0)

    def test_trim_is_refused_when_no_longer_concentrated(self, session_factory) -> None:
        led = Ledger(session_factory)
        for i in range(8):
            led.fill(Book.SWING, f"S{i}", Side.BUY, 10, 1000.0)

        with pytest.raises(ActionRefused, match="concentration target"):
            plan(
                Action.TRIM,
                {"id": 1, "kind": Kind.CONCENTRATION.value, "ticker": "S0", "payload": {}},
                led,
                Book.SWING,
                last_price=1000.0,
            )

    def test_trim_reduces_toward_the_target(self, session_factory) -> None:
        led = Ledger(session_factory)
        led.fill(Book.SWING, "BIG", Side.BUY, 90, 1000.0)
        led.fill(Book.SWING, "SMALL", Side.BUY, 10, 1000.0)

        prepared = plan(
            Action.TRIM,
            {"id": 1, "kind": Kind.CONCENTRATION.value, "ticker": "BIG", "payload": {}},
            led,
            Book.SWING,
            last_price=1000.0,
        )

        assert 0 < prepared.quantity < 90
        assert prepared.side is Side.SELL

    def test_no_price_refuses_rather_than_guessing(self, ledger: Ledger) -> None:
        with pytest.raises(ActionRefused, match="no current price"):
            plan(Action.EXIT, self._insight(), ledger, Book.SWING, last_price=None)

    def test_review_does_nothing(self, ledger: Ledger) -> None:
        prepared, trade = execute(
            Action.REVIEW, self._insight(), ledger, Book.SWING, 1100.0
        )

        assert trade is None
        assert prepared.quantity == 0
        assert ledger.position(Book.SWING, "RELIANCE").quantity == 10


class TestPreviewMatchesExecution:
    @pytest.fixture
    def ledger(self, session_factory) -> Ledger:
        led = Ledger(session_factory)
        led.fill(Book.SWING, "RELIANCE", Side.BUY, 10, 1000.0)
        return led

    def test_preview_writes_nothing(self, ledger: Ledger) -> None:
        insight = {"id": 1, "kind": Kind.THESIS_BROKEN.value, "ticker": "RELIANCE", "payload": {}}

        prepared, trade = execute(
            Action.EXIT, insight, ledger, Book.SWING, 1100.0, preview=True
        )

        assert trade is None
        assert ledger.position(Book.SWING, "RELIANCE").quantity == 10
        assert prepared.quantity == 10

    def test_preview_and_execution_agree(self, ledger: Ledger) -> None:
        """One function with a flag — two implementations is how a preview starts lying."""
        insight = {"id": 1, "kind": Kind.THESIS_BROKEN.value, "ticker": "RELIANCE", "payload": {}}

        previewed, _ = execute(Action.EXIT, insight, ledger, Book.SWING, 1100.0, preview=True)
        executed, trade = execute(Action.EXIT, insight, ledger, Book.SWING, 1100.0)

        assert previewed.quantity == executed.quantity
        assert previewed.side == executed.side
        assert trade is not None

    def test_execution_goes_through_the_ledger(self, ledger: Ledger) -> None:
        insight = {"id": 1, "kind": Kind.THESIS_BROKEN.value, "ticker": "RELIANCE", "payload": {}}

        execute(Action.EXIT, insight, ledger, Book.SWING, 1100.0)

        assert ledger.position(Book.SWING, "RELIANCE").quantity == 0
        assert any("insight #1" in (t.note or "") for t in ledger.trades(Book.SWING))

    def test_no_second_execution_path_exists(self) -> None:
        """Every fill goes through `Ledger.fill()`; actions must not have their own."""
        import inspect

        from app.insights import actions

        source = inspect.getsource(actions)
        assert "ledger.fill(" in source
        assert "session.add" not in source
        assert "TradeRow" not in source


class TestHealthAndActionsApi:
    @staticmethod
    def _client(settings):

        from app.data.fake import FakePriceSource
        from app.main import create_app

        app = create_app(settings)
        app.state.price_source = FakePriceSource(bars=400)
        return authed_client(app)

    def test_health_publishes_components_and_guidance(self, settings) -> None:
        client = self._client(settings)
        client.post(
            "/books/swing/fill",
            json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "price": 1400.0},
        )

        body = client.get("/books/swing/health").json()

        assert 0 <= body["score"] <= 100
        assert len(body["components"]) == 4
        assert "guidance" in body
        assert body["charges_included"] is False

    def test_insights_list_their_available_actions(self, settings) -> None:
        body = self._client(settings).get("/insights").json()

        assert "insights" in body

    def test_acting_on_an_unknown_insight_is_404(self, settings) -> None:
        response = self._client(settings).post(
            "/insights/999/act", json={"action": "review"}
        )

        assert response.status_code == 404

    def test_an_action_not_available_for_the_kind_is_422(self, settings, session_factory) -> None:
        from app.insights.feed import InsightFeed
        from app.insights.rules import Candidate

        InsightFeed(session_factory).record(
            [Candidate(Kind.REGIME_CHANGE, "regime", "b", "regime_change:x")]
        )
        client = self._client(settings)
        insight_id = client.get("/insights").json()["insights"][0]["id"]

        response = client.post(f"/insights/{insight_id}/act", json={"action": "exit"})

        assert response.status_code == 422
