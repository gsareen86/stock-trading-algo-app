"""The currency boundary.

LLM vendors are the one place a foreign currency enters this platform. These assert the two
properties that make that survivable: unpriced never becomes zero on the way out, and the
stored dollar amount is recoverable from the reported rupee one.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.core.money import (
    DEFAULT_USD_INR_RATE,
    PAISA,
    inr_to_usd,
    round_inr,
    usd_to_inr,
)
from app.core.settings import Settings


def _settings(**overrides) -> Settings:
    return Settings(**{"app_env": "test", "_env_file": None, **overrides})


class TestConversion:
    def test_dollars_become_rupees(self) -> None:
        assert usd_to_inr(1.0, 88.0) == pytest.approx(88.0)

    def test_rupees_become_dollars(self) -> None:
        assert inr_to_usd(88.0, 88.0) == pytest.approx(1.0)

    def test_round_trips_within_paise(self) -> None:
        """Recovery is exact only to the paisa the rupee figure was rounded to.

        That is the deliberate cost of reporting a currency people count in; the exact amount
        remains in the stored dollars, which are never converted on write.
        """
        recovered = inr_to_usd(usd_to_inr(0.25, 83.5), 83.5)

        assert abs(recovered - 0.25) < (PAISA / 83.5)

    def test_reported_amounts_round_to_paise(self) -> None:
        """A paisa is the smallest unit anyone counts in."""
        assert usd_to_inr(0.001234, 88.0) == round_inr(0.001234 * 88.0)

    def test_zero_is_zero_not_none(self) -> None:
        """A genuine zero is a fact; only *absence* of a price is None."""
        assert usd_to_inr(0.0, 88.0) == 0.0


class TestUnpricedStaysUnpriced:
    def test_none_does_not_become_zero(self) -> None:
        """The ledger's whole distinction is priced vs. unpriced. Zero would erase it."""
        assert usd_to_inr(None, 88.0) is None

    def test_none_cap_stays_none(self) -> None:
        assert inr_to_usd(None, 88.0) is None


class TestRateSetting:
    def test_default_rate_needs_no_configuration(self) -> None:
        assert _settings().usd_inr_rate == DEFAULT_USD_INR_RATE

    def test_operator_can_override(self) -> None:
        assert _settings(usd_inr_rate=90.5).usd_inr_rate == pytest.approx(90.5)

    def test_zero_rate_rejected(self) -> None:
        """A zero rate would silently report every cost as free."""
        with pytest.raises(ValidationError):
            _settings(usd_inr_rate=0)

    def test_negative_rate_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _settings(usd_inr_rate=-1)


class TestBudgetIsRupeeDenominated:
    def test_cap_converts_to_the_ledger_currency(self) -> None:
        settings = _settings(llm_daily_budget_inr=880.0, usd_inr_rate=88.0)

        assert settings.daily_budget_usd == pytest.approx(10.0)

    def test_unset_cap_stays_unlimited(self) -> None:
        assert _settings().daily_budget_usd is None


class TestRetiredKey:
    def test_retired_budget_key_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`extra="ignore"` would drop it silently, cutting a real cap by ~88x.

        A config change that looks like it did nothing is the worst available outcome, so the
        old key is rejected by name rather than ignored or reinterpreted.
        """
        monkeypatch.setitem(os.environ, "LLM_DAILY_BUDGET_USD", "5.00")

        with pytest.raises(ValidationError, match="LLM_DAILY_BUDGET_INR"):
            _settings()

    def test_absent_retired_key_is_fine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_DAILY_BUDGET_USD", raising=False)

        assert _settings().llm_daily_budget_inr is None
