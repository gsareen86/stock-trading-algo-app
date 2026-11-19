"""Offline tests for YFinanceQualitySource, FinancialsCache statements, and CompositeCompanyFinancialsSource."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.data.financials_cache import FinancialsCache
from app.data.indian_api import IndianApiFinancialsSource
from app.data.protocols import CompanyFinancialsSource
from app.data.yfinance_quality import CompositeCompanyFinancialsSource, YFinanceQualitySource
from app.domain.instrument import Instrument

TCS = Instrument("TCS", name="Tata Consultancy Services", sector="Information Technology")
HDFCBANK = Instrument("HDFCBANK", name="HDFC Bank", sector="Private Sector Bank")


def _sample_payload() -> dict:
    cols = pd.to_datetime(["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"])
    q_income = pd.DataFrame(
        [
            [65000.0, 62000.0, 60000.0, 58000.0, 50000.0],
            [35.0, 32.0, 31.0, 29.0, 25.0],
            [14000.0, 13000.0, 12500.0, 12000.0, 10000.0],
        ],
        index=["Total Revenue", "Basic EPS", "Net Income"],
        columns=cols,
    )
    balance = pd.DataFrame(
        [[5000.0], [100000.0]],
        index=["Total Debt", "Stockholders Equity"],
        columns=[pd.Timestamp("2026-03-31")],
    )
    cashflow = pd.DataFrame(
        [[420000000000.0]],
        index=["Free Cash Flow"],
        columns=[pd.Timestamp("2026-03-31")],
    )
    return {
        "info": {
            "longName": "Tata Consultancy Services Limited",
            "industry": "Information Technology Services",
            "longBusinessSummary": "IT consulting and technology services.",
            "returnOnEquity": 0.48,
            "operatingMargins": 0.245,
            "profitMargins": 0.19,
            "debtToEquity": 8.0,
            "marketCap": 14000000000000.0,
            "trailingPE": 28.5,
            "priceToBook": 12.2,
            "heldPercentInsiders": 0.717,
            "heldPercentInstitutions": 0.184,
        },
        "quarterly_income_stmt": q_income,
        "balance_sheet": balance,
        "cashflow": cashflow,
    }


class TestYFinanceQualitySource:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(YFinanceQualitySource(fetcher=lambda t: _sample_payload()), CompanyFinancialsSource)

    def test_extracts_ratios_statements_and_honest_ownership_gaps(self, tmp_path: Path) -> None:
        cache = FinancialsCache(tmp_path / "fin")
        src = YFinanceQualitySource(fetcher=lambda t: _sample_payload(), cache=cache)

        fin = src.financials(TCS)

        assert fin.source == "yfinance"
        assert fin.value("returnOnAverageEquityTrailing12Month") == pytest.approx(48.0)
        assert fin.value("operatingMarginTrailing12Month") == pytest.approx(24.5)
        assert fin.value("totalDebtPerTotalEquityMostRecentQuarter") == pytest.approx(0.05)
        assert fin.value("revenueGrowthYoY") == pytest.approx(30.0)
        assert fin.value("earningsGrowthYoY") == pytest.approx(40.0)
        assert fin.value("marketCapCr") == pytest.approx(1400000.0)
        assert fin.value("peTrailing") == pytest.approx(28.5)

        # Promoter pledge & granular FII/DII splits stay strictly None (unavailable)
        holding = fin.latest_shareholding()
        assert holding is not None
        assert holding.promoter_pct == pytest.approx(71.7)
        assert holding.pledge_pct is None
        assert holding.fii_pct is None
        assert holding.dii_pct is None

        # Cached second read skips fetcher
        src_no_net = YFinanceQualitySource(fetcher=lambda t: (_ for _ in ()).throw(RuntimeError("offline")), cache=cache)
        cached = src_no_net.financials(TCS)
        assert cached.value("returnOnAverageEquityTrailing12Month") == pytest.approx(48.0)
        assert "quarterly_revenue" in cached.statements
        assert cached.statements["quarterly_revenue"].latest() == pytest.approx(65000.0)

    def test_provider_failure_returns_empty_with_reason(self) -> None:
        src = YFinanceQualitySource(fetcher=lambda t: (_ for _ in ()).throw(RuntimeError("rate limited")))
        fin = src.financials(TCS)

        assert fin.is_empty
        assert fin.unavailable_reason and "rate limited" in fin.unavailable_reason

    def test_composite_falls_back_when_indian_api_unconfigured(self) -> None:
        primary = IndianApiFinancialsSource(api_key=None)
        fallback = YFinanceQualitySource(fetcher=lambda t: _sample_payload())
        comp = CompositeCompanyFinancialsSource(primary, fallback)

        fin = comp.financials(TCS)

        assert not fin.is_empty
        assert fin.source == "yfinance"
