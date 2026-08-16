"""Verdict persistence and the evaluation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.data.fake import FakePriceSource
from app.data.fundamentals import StaticFundamentalsSource
from app.domain.verdict import Evidence, GateResult, Operator, Stance, Verdict
from app.main import create_app
from app.persistence.verdicts import VerdictRepository

AS_OF = datetime(2026, 8, 14, tzinfo=UTC)


def _verdict(ticker: str = "TCS", strategy: str = "minervini", **overrides) -> Verdict:
    base = {
        "strategy_id": strategy,
        "ticker": ticker,
        "as_of": AS_OF,
        "stance": Stance.WATCH,
        "conviction": 55,
        "evidence": (
            Evidence(
                id="e1",
                label="Close above the 50-day",
                value=101.5,
                threshold=99.0,
                operator=Operator.GT,
                passed=True,
                unit="INR",
                source_ref="price://TCS",
            ),
        ),
        "gates": (
            GateResult(
                id="sufficient_history",
                label="History",
                passed=True,
                reason="300 bars",
                evidence_ids=("e1",),
            ),
        ),
    }
    return Verdict(**{**base, **overrides})


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """App wired to deterministic sources, so evaluation never touches a provider."""
    app = create_app(settings)
    app.state.price_source = FakePriceSource(bars=400)
    # Empty rather than absent: fun_tech_momentum then fails its fundamentals gate
    # deterministically instead of reaching for yfinance.
    app.state.fundamentals_source = StaticFundamentalsSource({})
    return TestClient(app)


class TestPersistence:
    def test_round_trip(self, session_factory) -> None:
        repo = VerdictRepository(session_factory)
        repo.save_many([_verdict()])

        (loaded,) = repo.recent()

        assert loaded.ticker == "TCS"
        assert loaded.stance is Stance.WATCH
        assert loaded.conviction == 55
        assert loaded.evidence[0].id == "e1"
        assert loaded.evidence[0].threshold == pytest.approx(99.0)
        assert loaded.gates[0].evidence_ids == ("e1",)

    def test_filter_by_ticker(self, session_factory) -> None:
        repo = VerdictRepository(session_factory)
        repo.save_many([_verdict("TCS"), _verdict("INFY")])

        found = repo.recent(ticker="INFY")

        assert [v.ticker for v in found] == ["INFY"]

    def test_filter_by_strategy(self, session_factory) -> None:
        repo = VerdictRepository(session_factory)
        repo.save_many([_verdict(strategy="minervini"), _verdict(strategy="other")])

        assert [v.strategy_id for v in repo.recent(strategy_id="other")] == ["other"]

    def test_newest_first(self, session_factory) -> None:
        repo = VerdictRepository(session_factory)
        repo.save_many([_verdict("FIRST")])
        repo.save_many([_verdict("SECOND")])

        assert [v.ticker for v in repo.recent()] == ["SECOND", "FIRST"]

    def test_two_strategies_on_one_ticker_both_kept(self, session_factory) -> None:
        """Disagreement is the normal case; collapsing it would be the scorecard again."""
        repo = VerdictRepository(session_factory)
        repo.save_many(
            [
                _verdict("TCS", "minervini", stance=Stance.WATCH),
                _verdict("TCS", "young_momentum", stance=Stance.AVOID, conviction=10),
            ]
        )

        found = repo.recent(ticker="TCS")

        assert len(found) == 2
        assert {v.strategy_id for v in found} == {"minervini", "young_momentum"}

    def test_empty_save_is_a_noop(self, session_factory) -> None:
        assert VerdictRepository(session_factory).save_many([]) == 0


class TestStrategiesEndpoint:
    def test_lists_all_four(self, client: TestClient) -> None:
        body = client.get("/strategies").json()

        assert body["count"] == 4
        assert {s["id"] for s in body["strategies"]} == {
            "minervini",
            "brahma_vishnu_mahesh",
            "fun_tech_momentum",
            "young_momentum",
        }
        assert body["load_failures"] == []

    def test_description_explains_the_rs_substitution(self, client: TestClient) -> None:
        body = client.get("/strategies").json()
        minervini = next(s for s in body["strategies"] if s["id"] == "minervini")

        assert "benchmark" in minervini["description"]


class TestEvaluateEndpoint:
    def test_returns_a_verdict_with_evidence(self, client: TestClient) -> None:
        body = client.post("/verdicts/evaluate", json={"symbols": ["RELIANCE"]}).json()

        # One per strategy, never merged.
        assert body["count"] == 4
        for verdict in body["verdicts"]:
            assert verdict["stance"] in {"BUY", "WATCH", "AVOID"}
            assert verdict["evidence"]
            assert all(row["source_ref"] for row in verdict["evidence"])

    def test_no_combined_stance_in_the_response(self, client: TestClient) -> None:
        """Cross-strategy agreement is displayed, never computed."""
        raw = client.post("/verdicts/evaluate", json={"symbols": ["RELIANCE"]}).text

        for banned in ("combined", "consensus", "composite", "overall_stance", "blended"):
            assert banned not in raw

    def test_one_verdict_per_strategy_per_symbol(self, client: TestClient) -> None:
        body = client.post("/verdicts/evaluate", json={"symbols": ["RELIANCE", "TCS"]}).json()

        assert body["count"] == 8  # 2 symbols x 4 strategies
        assert {v["ticker"] for v in body["verdicts"]} == {"RELIANCE", "TCS"}
        for ticker in ("RELIANCE", "TCS"):
            per_ticker = [v for v in body["verdicts"] if v["ticker"] == ticker]
            assert len({v["strategy_id"] for v in per_ticker}) == 4

    def test_does_not_persist_by_default(self, client: TestClient) -> None:
        client.post("/verdicts/evaluate", json={"symbols": ["RELIANCE"]})

        assert client.get("/verdicts").json()["count"] == 0

    def test_persisting_is_explicit(self, client: TestClient) -> None:
        body = client.post(
            "/verdicts/evaluate", json={"symbols": ["RELIANCE"], "persist": True}
        ).json()

        assert body["persisted"] == 4
        assert client.get("/verdicts").json()["count"] == 4

    def test_unknown_strategy_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/verdicts/evaluate",
            json={"symbols": ["RELIANCE"], "strategy_ids": ["nope"]},
        )

        assert response.status_code == 422
        assert "nope" in response.text

    def test_empty_symbol_list_rejected(self, client: TestClient) -> None:
        assert client.post("/verdicts/evaluate", json={"symbols": []}).status_code == 422

    def test_symbol_batch_is_bounded(self, client: TestClient) -> None:
        response = client.post("/verdicts/evaluate", json={"symbols": [f"S{i}" for i in range(60)]})

        assert response.status_code == 422


class TestVerdictsEndpoint:
    def test_filtered_by_ticker(self, client: TestClient, session_factory) -> None:
        VerdictRepository(session_factory).save_many([_verdict("TCS"), _verdict("INFY")])

        body = client.get("/verdicts?ticker=INFY").json()

        assert [v["ticker"] for v in body["verdicts"]] == ["INFY"]

    def test_limit_bounded(self, client: TestClient) -> None:
        assert client.get("/verdicts?limit=5000").status_code == 422
        assert client.get("/verdicts?limit=0").status_code == 422

    def test_gates_and_evidence_survive_the_api(self, client: TestClient, session_factory) -> None:
        VerdictRepository(session_factory).save_many([_verdict()])

        verdict = client.get("/verdicts").json()["verdicts"][0]

        assert verdict["gates"][0]["evidence_ids"] == ["e1"]
        assert verdict["evidence"][0]["operator"] == ">"
        assert verdict["gates_passed"] is True
