"""The LLM accounting endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.llm.recorder import CallRecord, CallRecorder
from app.llm.types import CallStatus
from app.main import create_app


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def _seed(factory, **overrides) -> None:
    base = {
        "task": "narrative",
        "provider": "anthropic",
        "model": "anthropic/claude-sonnet-5",
        "status": CallStatus.OK,
    }
    CallRecorder(factory).record(CallRecord(**{**base, **overrides}))


class TestUsageEndpoint:
    def test_reports_totals_and_breakdowns(self, client: TestClient, session_factory) -> None:
        _seed(session_factory, cost_usd=0.02, total_tokens=100)
        _seed(session_factory, task="research", provider="openai", cost_usd=0.03)

        body = client.get("/llm/usage").json()

        assert body["totals"]["calls"] == 2
        assert body["totals"]["spend_inr"] == pytest.approx(0.05 * body["usd_inr_rate"])
        assert set(body["by_task"]) == {"narrative", "research"}
        assert set(body["by_provider"]) == {"anthropic", "openai"}

    def test_empty_log_returns_zeroes_not_absence(self, client: TestClient) -> None:
        response = client.get("/llm/usage")
        body = response.json()

        assert response.status_code == 200
        assert body["totals"]["calls"] == 0
        assert body["totals"]["spend_inr"] == 0.0
        assert body["by_day"] == {}

    def test_window_is_bounded(self, client: TestClient) -> None:
        response = client.get("/llm/usage?days=400")

        assert response.status_code == 422
        assert "90" in response.text  # the limit is named

    def test_minimum_window_enforced(self, client: TestClient) -> None:
        assert client.get("/llm/usage?days=0").status_code == 422

    def test_unpriced_calls_reported_separately(self, client: TestClient, session_factory) -> None:
        _seed(session_factory, provider="lemonade", model="lemonade/q", cost_usd=None)

        body = client.get("/llm/usage").json()

        assert body["totals"]["unpriced_calls"] == 1
        assert body["totals"]["priced_calls"] == 0


class TestBudgetReporting:
    def test_budget_absent_when_unconfigured(self, client: TestClient) -> None:
        body = client.get("/llm/usage").json()

        assert body["budget"]["cap_inr"] is None
        assert body["budget"]["remaining_inr"] is None
        assert body["budget"]["exhausted"] is False

    def test_budget_reported_when_configured(self, migrated_url: str, session_factory) -> None:
        _seed(session_factory, cost_usd=0.25)
        settings = Settings(
            app_env="test",
            database_url=migrated_url,
            llm_daily_budget_inr=88.0,
            usd_inr_rate=88.0,
        )

        body = _client(settings).get("/llm/usage").json()

        assert body["budget"]["cap_inr"] == pytest.approx(88.0)
        assert body["budget"]["spent_today_inr"] == pytest.approx(22.0)
        assert body["budget"]["remaining_inr"] == pytest.approx(66.0)
        assert body["budget"]["exhausted"] is False

    def test_exhausted_reported(self, migrated_url: str, session_factory) -> None:
        """A rupee cap is enforced at the equivalent dollar spend, not the rupee number."""
        _seed(session_factory, cost_usd=2.0)
        settings = Settings(
            app_env="test",
            database_url=migrated_url,
            llm_daily_budget_inr=88.0,  # == $1.00
            usd_inr_rate=88.0,
        )

        body = _client(settings).get("/llm/usage").json()

        assert body["budget"]["exhausted"] is True
        assert body["budget"]["remaining_inr"] == 0.0


class TestCurrencyReporting:
    def test_spend_reported_in_rupees_with_its_rate(
        self, migrated_url: str, session_factory
    ) -> None:
        _seed(session_factory, cost_usd=0.50)
        settings = Settings(app_env="test", database_url=migrated_url, usd_inr_rate=90.0)

        body = _client(settings).get("/llm/usage").json()

        assert body["usd_inr_rate"] == pytest.approx(90.0)
        assert body["totals"]["spend_inr"] == pytest.approx(45.0)

    def test_reported_rupees_invert_to_the_stored_dollars(
        self, migrated_url: str, session_factory
    ) -> None:
        """The rate is returned precisely so a reported figure is never unattributable.

        Recovery is exact only to the paise the figure was rounded to — half a paisa back in
        dollars is the tightest honest bound, and that is the cost of reporting a currency
        people actually count in.
        """
        _seed(session_factory, cost_usd=0.25)
        settings = Settings(app_env="test", database_url=migrated_url, usd_inr_rate=83.5)

        body = _client(settings).get("/llm/usage").json()

        rate = body["usd_inr_rate"]
        assert abs(body["totals"]["spend_inr"] / rate - 0.25) < (0.01 / rate)

    def test_call_records_carry_both_currencies(
        self, migrated_url: str, session_factory
    ) -> None:
        _seed(session_factory, cost_usd=0.10)
        settings = Settings(app_env="test", database_url=migrated_url, usd_inr_rate=88.0)

        record = _client(settings).get("/llm/calls").json()["calls"][0]

        assert record["cost_usd"] == pytest.approx(0.10)
        assert record["cost_inr"] == pytest.approx(8.80)

    def test_unpriced_call_is_null_in_both_currencies(
        self, client: TestClient, session_factory
    ) -> None:
        """Zero rupees would read as "a paid call that was free" — it is neither."""
        _seed(session_factory, provider="ollama", model="ollama/gemma4:12b", cost_usd=None)

        record = client.get("/llm/calls").json()["calls"][0]

        assert record["cost_usd"] is None
        assert record["cost_inr"] is None

    def test_stored_amount_is_never_converted_on_write(
        self, migrated_url: str, session_factory
    ) -> None:
        """The ledger holds what the vendor bills, so a row reconciles against an invoice."""
        _seed(session_factory, cost_usd=0.25)
        rows = _client(
            Settings(app_env="test", database_url=migrated_url, usd_inr_rate=88.0)
        ).get("/llm/calls").json()["calls"]

        assert rows[0]["cost_usd"] == pytest.approx(0.25)


class TestCallsEndpoint:
    def test_newest_first(self, client: TestClient, session_factory) -> None:
        _seed(session_factory, task="first")
        _seed(session_factory, task="second")

        body = client.get("/llm/calls").json()

        assert [c["task"] for c in body["calls"]] == ["second", "first"]
        assert body["count"] == 2

    def test_failures_included(self, client: TestClient, session_factory) -> None:
        _seed(session_factory, status=CallStatus.FAILED, error_msg="boom")

        (call,) = client.get("/llm/calls").json()["calls"]

        assert call["status"] == "failed"
        assert call["error_msg"] == "boom"

    def test_limit_bounded(self, client: TestClient) -> None:
        assert client.get("/llm/calls?limit=5000").status_code == 422
        assert client.get("/llm/calls?limit=0").status_code == 422

    def test_fallback_visible(self, client: TestClient, session_factory) -> None:
        _seed(
            session_factory,
            model="anthropic/claude-sonnet-5",
            requested_model="ollama/llama3.1",
            used_fallback=True,
        )

        (call,) = client.get("/llm/calls").json()["calls"]

        assert call["used_fallback"] is True
        assert call["requested_model"] == "ollama/llama3.1"


class TestNoLeakage:
    def test_neither_endpoint_returns_prompt_content(
        self, client: TestClient, session_factory
    ) -> None:
        _seed(session_factory, cost_usd=0.01)

        usage_text = client.get("/llm/usage").text
        calls_text = client.get("/llm/calls").text

        for field in ("prompt", "messages", "completion"):
            assert field not in usage_text
            assert f'"{field}"' not in calls_text
