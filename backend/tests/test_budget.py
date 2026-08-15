"""The daily spend guardrail."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from app.core.clock import IST, to_utc
from app.llm.budget import DailyBudget
from app.llm.types import CallStatus
from app.persistence.models import LlmCall
from app.persistence.session import make_session_factory


@pytest.fixture
def factory(session_factory):
    return session_factory


def _insert(factory, cost: float | None, when: datetime | None = None) -> None:
    with factory() as session:
        session.add(
            LlmCall(
                task="narrative",
                provider="anthropic",
                model="anthropic/claude-sonnet-5",
                requested_model="anthropic/claude-sonnet-5",
                status=CallStatus.OK.value,
                cost_usd=cost,
                created_at=when or datetime.now(UTC),
            )
        )
        session.commit()


class TestCapDisabled:
    def test_unset_cap_is_never_exhausted(self, factory) -> None:
        budget = DailyBudget(factory, None)
        _insert(factory, 1000.0)

        assert budget.is_exhausted() is False
        assert budget.remaining() is None
        assert budget.enabled is False


class TestCapEnforcement:
    def test_not_exhausted_below_cap(self, factory) -> None:
        _insert(factory, 0.25)

        budget = DailyBudget(factory, 1.0)

        assert budget.spent_today() == pytest.approx(0.25)
        assert budget.remaining() == pytest.approx(0.75)
        assert budget.is_exhausted() is False

    def test_exhausted_at_cap(self, factory) -> None:
        _insert(factory, 1.0)

        assert DailyBudget(factory, 1.0).is_exhausted() is True

    def test_exhausted_above_cap(self, factory) -> None:
        _insert(factory, 2.5)

        budget = DailyBudget(factory, 1.0)

        assert budget.is_exhausted() is True
        assert budget.remaining() == 0.0  # clamped, never negative

    def test_add_accumulates_without_a_reread(self, factory) -> None:
        budget = DailyBudget(factory, 1.0)
        assert budget.spent_today() == pytest.approx(0.0)

        budget.add(0.4)
        budget.add(0.4)

        assert budget.spent_today() == pytest.approx(0.8)
        assert budget.is_exhausted() is False
        budget.add(0.3)
        assert budget.is_exhausted() is True


class TestUnpricedCalls:
    def test_none_cost_contributes_nothing(self, factory) -> None:
        """Local models are free — that is why they stay usable after the cap is hit."""
        budget = DailyBudget(factory, 1.0)

        budget.add(None)
        budget.add(0.0)

        assert budget.spent_today() == pytest.approx(0.0)

    def test_null_cost_rows_ignored_on_load(self, factory) -> None:
        _insert(factory, None)
        _insert(factory, 0.5)

        assert DailyBudget(factory, 1.0).spent_today() == pytest.approx(0.5)


class TestDayBoundary:
    def test_yesterdays_spend_does_not_count(self, factory) -> None:
        yesterday_ist = datetime.now(IST) - timedelta(days=1)
        _insert(factory, 5.0, when=to_utc(yesterday_ist))

        assert DailyBudget(factory, 1.0).spent_today() == pytest.approx(0.0)

    def test_spend_just_after_ist_midnight_counts_today(self, factory) -> None:
        just_after_midnight = datetime.now(IST).replace(hour=0, minute=15, second=0)
        _insert(factory, 0.5, when=to_utc(just_after_midnight))

        assert DailyBudget(factory, 1.0).spent_today() == pytest.approx(0.5)


class TestFailureModes:
    def test_unreadable_ledger_fails_open(self, migrated_url: str) -> None:
        """An unreadable ledger must not block every LLM call in the platform."""
        broken = create_engine("sqlite+pysqlite:///:memory:")  # no llm_calls table
        budget = DailyBudget(make_session_factory(broken), 1.0)

        assert budget.spent_today() == pytest.approx(0.0)
        assert budget.is_exhausted() is False

    def test_no_session_factory_reports_zero(self) -> None:
        budget = DailyBudget(None, 1.0)

        assert budget.spent_today() == pytest.approx(0.0)
        assert budget.is_exhausted() is False
