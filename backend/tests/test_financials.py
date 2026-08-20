"""Company financials, and the allowance that governs asking for them.

Every test runs offline against payloads captured once from the live provider. **No test here
may spend a request** — the free tier is 500 a month and a suite that consumed them would take
the capability down within a day of anyone running it twice.

The fixtures are real responses, which is the point: the provider publishes no OpenAPI spec, so
a model shaped against documentation would have been shaped against prose. Two of the
behaviours asserted below exist only because the real payload had them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.data.financials_cache import FinancialsCache
from app.data.indian_api import IndianApiFinancialsSource, parse_statements, parse_stock
from app.data.protocols import CompanyFinancialsSource
from app.data.provider_budget import MonthlyRequestBudget
from app.domain.financials import normalise_key, parse_period
from app.domain.instrument import Instrument

FIXTURES = Path(__file__).parent / "fixtures" / "indianapi"
TCS = Instrument("TCS")


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))


@pytest.fixture
def stock_payload() -> dict[str, Any]:
    return _fixture("stock")


@pytest.fixture
def source(stock_payload: dict[str, Any]) -> IndianApiFinancialsSource:
    return IndianApiFinancialsSource(
        api_key="test-key", fetcher=lambda path, params: stock_payload
    )


class TestFixturesAreReal:
    def test_captured_from_the_provider(self, stock_payload: dict[str, Any]) -> None:
        assert stock_payload["companyName"]
        assert "keyMetrics" in stock_payload
        assert "shareholding" in stock_payload

    def test_statement_fixtures_have_the_documented_shape(self) -> None:
        """`{metric: {period: value}}`, which is not what the docs describe."""
        quarterly = _fixture("quarter_results")
        assert isinstance(quarterly["Sales"], dict)
        assert "Jun 2026" in quarterly["Sales"]


class TestKeyNormalisation:
    def test_a_stray_parenthesis_does_not_hide_a_metric(self) -> None:
        """The real payload carries `returnOnAverageEquityMostRecentFiscalYear)`.

        Observed, not hypothesised. Matching raw keys would drop that metric silently for
        every company whose payload carries the typo — a partial, unannounced gap.
        """
        assert normalise_key("returnOnAverageEquityMostRecentFiscalYear)") == normalise_key(
            "returnOnAverageEquityMostRecentFiscalYear"
        )

    def test_parentheses_inside_a_key_are_handled(self) -> None:
        assert normalise_key("revenuePerShare(5yrGrowth)") == "revenuepershare5yrgrowth"

    def test_a_quirky_key_is_reachable_from_the_clean_name(
        self, source: IndianApiFinancialsSource
    ) -> None:
        financials = source.financials(TCS)

        assert financials.metric("returnOnAverageEquityMostRecentFiscalYear") is not None


class TestParsingTheStockPayload:
    def test_metrics_are_extracted_with_their_category(
        self, source: IndianApiFinancialsSource
    ) -> None:
        financials = source.financials(TCS)

        roe = financials.metric("returnOnAverageEquityTrailing12Month")
        assert roe is not None
        assert roe.value > 0
        assert roe.category == "mgmtEffectiveness"
        assert roe.source == "indianapi"

    def test_the_quality_metrics_a_screen_needs_are_present(
        self, source: IndianApiFinancialsSource
    ) -> None:
        """The filter is buildable from one request — that is what makes the quota workable."""
        financials = source.financials(TCS)

        for key in (
            "returnOnAverageEquityTrailing12Month",
            "totalDebtPerTotalEquityMostRecentQuarter",
            "operatingMarginTrailing12Month",
            "growthRatePercentRevenue3Year",
            "freeCashFlowtrailing12Month",
        ):
            assert financials.metric(key) is not None, key

    def test_a_null_metric_is_unavailable_not_zero(
        self, source: IndianApiFinancialsSource
    ) -> None:
        """Interest coverage is null for a company with no debt.

        Reading that as 0.0 would rank the least indebted business in the index as the most
        fragile one.
        """
        financials = source.financials(TCS)
        coverage = financials.metric("netInterestCoverageTrailing12Month")

        assert coverage is not None
        assert coverage.value is None
        assert coverage.available is False

    def test_company_identity_and_peers_are_carried(
        self, source: IndianApiFinancialsSource
    ) -> None:
        financials = source.financials(TCS)

        assert financials.company_name
        assert financials.industry
        assert len(financials.peers) > 0

    def test_peers_are_names_not_provider_identifiers(
        self, source: IndianApiFinancialsSource
    ) -> None:
        """`tickerId` is an internal id like `S0003032` — neither an NSE symbol nor
        resolvable to one, so a peer list built from it matches nothing downstream."""
        peers = source.financials(TCS).peers

        assert all(not p.startswith("S000") for p in peers)
        assert any(" " in p or p.isalpha() for p in peers)

    def test_reported_metrics_are_not_marked_derived(
        self, source: IndianApiFinancialsSource
    ) -> None:
        financials = source.financials(TCS)

        assert all(not m.is_derived for m in financials.metrics.values())

    def test_an_empty_payload_is_empty_with_a_reason(self) -> None:
        result = parse_stock("TCS", {})

        assert result.is_empty
        assert result.unavailable_reason


class TestShareholding:
    def test_ownership_is_returned_newest_first(
        self, source: IndianApiFinancialsSource
    ) -> None:
        financials = source.financials(TCS)
        holdings = financials.shareholding

        assert len(holdings) > 1
        assert holdings[0].as_of > holdings[-1].as_of

    def test_each_pattern_carries_its_own_date(
        self, source: IndianApiFinancialsSource
    ) -> None:
        latest = source.financials(TCS).latest_shareholding()

        assert latest is not None
        assert latest.as_of is not None
        assert latest.promoter_pct is not None

    def test_mutual_funds_are_not_reported_as_domestic_institutions(
        self, source: IndianApiFinancialsSource
    ) -> None:
        """The two endpoints bucket ownership differently and the difference is large.

        The company endpoint's "MF" row read 5.68 for a company whose "DIIs" row on the
        shareholding-history endpoint read 13.41 — mutual funds are a subset of domestic
        institutions. Filling `dii_pct` from the MF row would understate institutional
        ownership by more than half, and every consumer would inherit it silently.
        """
        latest = source.financials(TCS).latest_shareholding()

        assert latest.mutual_fund_pct is not None
        assert latest.dii_pct is None

    def test_the_company_endpoint_buckets_sum_to_a_whole(
        self, source: IndianApiFinancialsSource
    ) -> None:
        latest = source.financials(TCS).latest_shareholding()
        parts = [latest.promoter_pct, latest.fii_pct, latest.mutual_fund_pct, latest.other_pct]

        assert sum(p for p in parts if p is not None) == pytest.approx(100.0, abs=0.5)

    def test_the_residual_bucket_is_not_called_public(
        self, source: IndianApiFinancialsSource
    ) -> None:
        """"Other" excludes non-MF domestic institutions; "public" does not. Not the same."""
        latest = source.financials(TCS).latest_shareholding()

        assert latest.other_pct is not None
        assert latest.public_pct is None

    def test_pledge_is_absent_rather_than_zero(
        self, source: IndianApiFinancialsSource
    ) -> None:
        """This provider does not report pledge. `None` is "nobody told us", not "none".

        Defaulting to 0.0 would let a governance gate pass a fully pledged promoter holding.
        """
        latest = source.financials(TCS).latest_shareholding()

        assert latest.pledge_pct is None


class TestStatementSeries:
    def test_periods_are_ordered_newest_first(self) -> None:
        """The provider returns oldest first; every comparison made is latest-versus-older."""
        series = parse_statements(_fixture("quarter_results"))["Sales"]

        assert series.points[0].period_end > series.points[-1].period_end

    def test_each_point_keeps_the_provider_label(self) -> None:
        series = parse_statements(_fixture("balancesheet"))["Borrowings"]

        assert " " in series.points[0].period  # e.g. "Mar 2026"

    def test_period_labels_parse_to_period_ends(self) -> None:
        assert parse_period("Mar 2026").isoformat() == "2026-03-31"
        assert parse_period("Dec 2025").isoformat() == "2025-12-31"

    def test_an_unparseable_label_resolves_to_nothing(self) -> None:
        assert parse_period("whenever") is None

    def test_a_non_series_value_is_skipped(self) -> None:
        assert parse_statements({"note": "unavailable"}) == {}


class TestDegradation:
    def test_a_missing_key_disables_only_this_seam(self) -> None:
        result = IndianApiFinancialsSource(api_key=None).financials(TCS)

        assert result.is_empty
        assert "INDIAN_API_KEY" in result.unavailable_reason

    def test_a_provider_failure_is_empty_not_an_exception(self) -> None:
        def boom(path, params):
            raise RuntimeError("gateway timeout")

        result = IndianApiFinancialsSource(api_key="k", fetcher=boom).financials(TCS)

        assert result.is_empty
        assert "provider error" in result.unavailable_reason

    def test_an_unknown_statement_mode_is_a_programming_error(self) -> None:
        """A typo'd mode is caught here, not spent as a request that returns nothing."""
        with pytest.raises(ValueError, match="unknown stats mode"):
            IndianApiFinancialsSource(api_key="k").statement(TCS, "made_up")


class TestTheAllowance:
    """500 requests a month is the design constraint, so it is enforced, not hoped for."""

    def test_requests_are_counted(self, session_factory) -> None:
        budget = MonthlyRequestBudget(session_factory, "indianapi", limit=3)

        assert budget.allow("stock:TCS") is True
        assert budget.allow("stock:INFY") is True
        assert budget.state().used == 2
        assert budget.state().remaining == 1

    def test_the_cap_refuses(self, session_factory) -> None:
        budget = MonthlyRequestBudget(session_factory, "indianapi", limit=2)
        budget.allow("one")
        budget.allow("two")

        assert budget.allow("three") is False
        assert budget.state().exhausted is True

    def test_a_refused_request_is_not_counted(self, session_factory) -> None:
        budget = MonthlyRequestBudget(session_factory, "indianapi", limit=1)
        budget.allow("one")
        budget.allow("two")

        assert budget.state().used == 1

    def test_no_limit_means_no_refusal(self, session_factory) -> None:
        budget = MonthlyRequestBudget(session_factory, "indianapi", limit=None)

        assert all(budget.allow(f"n{i}") for i in range(5))
        assert budget.state().remaining is None

    def test_providers_are_counted_separately(self, session_factory) -> None:
        MonthlyRequestBudget(session_factory, "other", limit=10).allow("x")
        budget = MonthlyRequestBudget(session_factory, "indianapi", limit=10)

        assert budget.state().used == 0

    def test_an_exhausted_budget_stops_the_provider_being_called(
        self, session_factory, stock_payload: dict[str, Any]
    ) -> None:
        calls: list[str] = []

        def counted(path, params):
            calls.append(path)
            return stock_payload

        budget = MonthlyRequestBudget(session_factory, "indianapi", limit=1)
        source = IndianApiFinancialsSource(api_key="k", fetcher=counted, budget=budget)

        source.financials(TCS)
        second = source.financials(Instrument("INFY"))

        assert len(calls) == 1
        assert second.is_empty
        assert "budget" in second.unavailable_reason


class TestCaching:
    def test_a_cached_company_costs_no_request(
        self, tmp_path, stock_payload: dict[str, Any]
    ) -> None:
        calls: list[str] = []

        def counted(path, params):
            calls.append(path)
            return stock_payload

        cache = FinancialsCache(tmp_path / "fin", ttl_days=30)
        source = IndianApiFinancialsSource(api_key="k", fetcher=counted, cache=cache)

        source.financials(TCS)
        source.financials(TCS)

        assert len(calls) == 1

    def test_an_exhausted_budget_serves_an_expired_document(
        self, tmp_path, session_factory, stock_payload: dict[str, Any]
    ) -> None:
        """A quarterly figure from last month is still the last reported figure."""
        cache = FinancialsCache(tmp_path / "fin", ttl_days=30)
        seeded = IndianApiFinancialsSource(
            api_key="k", fetcher=lambda p, q: stock_payload, cache=cache
        )
        seeded.financials(TCS)

        # Age the document deliberately rather than setting a zero lifetime. A zero TTL makes
        # expiry depend on `time.time() - mtime` being non-negative, and Windows' filesystem
        # timestamp granularity can make that briefly negative right after a write — which
        # made this test pass or fail depending on how fast the disk was.
        import os
        import time

        document = next((tmp_path / "fin").glob("*.json"))
        old_enough = time.time() - 60 * 86400
        os.utime(document, (old_enough, old_enough))

        expired = FinancialsCache(tmp_path / "fin", ttl_days=30)
        budget = MonthlyRequestBudget(session_factory, "indianapi", limit=0)
        starved = IndianApiFinancialsSource(
            api_key="k", fetcher=lambda p, q: stock_payload, budget=budget, cache=expired
        )

        result = starved.financials(TCS)

        assert not result.is_empty
        assert result.source.endswith(":cache")

    def test_a_disabled_cache_stores_nothing(self, tmp_path) -> None:
        cache = FinancialsCache(tmp_path / "fin", enabled=False)
        assert cache.get("TCS") is None

    def test_a_cached_document_round_trips(
        self, tmp_path, source: IndianApiFinancialsSource
    ) -> None:
        cache = FinancialsCache(tmp_path / "fin", ttl_days=30)
        original = source.financials(TCS)
        cache.put("TCS", original)

        restored = cache.get("TCS")

        assert restored is not None
        assert restored.company_name == original.company_name
        assert len(restored.metrics) == len(original.metrics)
        assert restored.latest_shareholding().promoter_pct == pytest.approx(
            original.latest_shareholding().promoter_pct
        )


class TestSeamBoundaries:
    def test_the_source_satisfies_its_protocol(
        self, source: IndianApiFinancialsSource
    ) -> None:
        assert isinstance(source, CompanyFinancialsSource)

    def test_the_narrow_fundamentals_seam_is_untouched(self) -> None:
        """`fun_tech_momentum` must not acquire a hundred optional fields."""
        from app.data.fundamentals import QuarterlyFundamentals

        assert set(QuarterlyFundamentals.__dataclass_fields__) == {
            "symbol",
            "eps",
            "revenue",
            "source_ref",
        }

    def test_no_strategy_reads_company_financials(self) -> None:
        from tests.conftest import source_of

        assert "CompanyFinancialsSource" not in source_of("strategies")

    def test_analyst_targets_are_never_read(self) -> None:
        """The provider serves `/stock_target_price`. A plan level must derive from a verdict.

        `discovery-funnel` builds entry, stop and target from the strategy that produced the
        verdict, each citing an evidence row. A vendor consensus has no such derivation, so
        the client must not reach for one.
        """
        source = Path("app/data/indian_api.py").read_text("utf-8")

        assert "stock_target_price" not in source
        assert "stock_forecasts" not in source
