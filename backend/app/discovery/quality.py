"""Business quality as an inspectable facet (never a composite score or blind pre-filter).

Price-and-volume strategies must still see every liquid instrument. Quality metrics are
attached alongside verdicts as individual named measures with sector-aware applicability
(leverage is ``not_applicable`` for banks and financial services, never marked failed) and
honest ``unavailable`` states when a provider lacks a figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.domain.financials import CompanyFinancials

FacetStatus = Literal["pass", "fail", "unavailable", "not_applicable"]

LEVERAGE_EXEMPT_SECTORS = frozenset({"Bank", "PrivateBank", "PSUBank", "FinancialServices"})

ROE_MIN_PCT = 15.0
OP_MARGIN_MIN_PCT = 12.0
DEBT_EQUITY_MAX = 1.0
SALES_GROWTH_MIN_PCT = 15.0
EPS_GROWTH_MIN_PCT = 15.0


@dataclass(frozen=True, slots=True)
class QualityFacet:
    key: str
    label: str
    status: FacetStatus
    value: float | None
    threshold: str | None = None
    unit: str | None = None
    source: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "value": self.value,
            "threshold": self.threshold,
            "unit": self.unit,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    symbol: str
    sector_key: str | None
    source: str
    unavailable_reason: str | None
    facets: tuple[QualityFacet, ...]
    summary: dict[str, float | None]

    def facet(self, key: str) -> QualityFacet | None:
        return next((f for f in self.facets if f.key == key), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sector_key": self.sector_key,
            "source": self.source,
            "unavailable_reason": self.unavailable_reason,
            "facets": [f.as_dict() for f in self.facets],
            "summary": dict(self.summary),
        }


def _first_metric(fin: CompanyFinancials, *keys: str) -> tuple[float | None, str | None]:
    for key in keys:
        m = fin.metric(key)
        if m is not None and m.value is not None:
            return round(float(m.value), 2), m.source or fin.source
    return None, None


def evaluate_quality(
    fin: CompanyFinancials | None,
    *,
    symbol: str,
    sector_key: str | None = None,
) -> QualityReport:
    """Assess individual business quality facets without producing any composite score."""
    if fin is None or fin.is_empty:
        reason = (
            fin.unavailable_reason if fin and fin.unavailable_reason else "financials unavailable"
        )
        facets: list[QualityFacet] = [
            QualityFacet(
                "roe",
                "Return on Equity (TTM)",
                "unavailable",
                None,
                f">= {ROE_MIN_PCT}%",
                "%",
                reason=reason,
            ),
            QualityFacet(
                "operating_margin",
                "Operating Margin (TTM)",
                "unavailable",
                None,
                f">= {OP_MARGIN_MIN_PCT}%",
                "%",
                reason=reason,
            ),
            (
                QualityFacet(
                    "debt_to_equity",
                    "Debt / Equity",
                    "not_applicable",
                    None,
                    None,
                    "x",
                    reason=f"Leverage ratio not applicable for {sector_key}",
                )
                if sector_key in LEVERAGE_EXEMPT_SECTORS
                else QualityFacet(
                    "debt_to_equity",
                    "Debt / Equity",
                    "unavailable",
                    None,
                    f"<= {DEBT_EQUITY_MAX}",
                    "x",
                    reason=reason,
                )
            ),
            QualityFacet(
                "sales_yoy",
                "Sales Growth (YoY)",
                "unavailable",
                None,
                f">= {SALES_GROWTH_MIN_PCT}%",
                "%",
                reason=reason,
            ),
            QualityFacet(
                "eps_yoy",
                "EPS Growth (YoY)",
                "unavailable",
                None,
                f">= {EPS_GROWTH_MIN_PCT}%",
                "%",
                reason=reason,
            ),
        ]
        return QualityReport(
            symbol=symbol,
            sector_key=sector_key,
            source=fin.source if fin else "",
            unavailable_reason=reason,
            facets=tuple(facets),
            summary={
                "roe": None,
                "operating_margin": None,
                "debt_to_equity": None,
                "sales_yoy": None,
                "eps_yoy": None,
                "mkt_cap_cr": None,
                "pe": None,
                "fcf_cr": None,
            },
        )

    roe_val, roe_src = _first_metric(
        fin,
        "returnOnAverageEquityTrailing12Month",
        "returnOnAverageEquityMostRecentFiscalYear",
    )
    opm_val, opm_src = _first_metric(fin, "operatingMarginTrailing12Month")
    de_val, de_src = _first_metric(fin, "totalDebtPerTotalEquityMostRecentQuarter")
    sales_val, sales_src = _first_metric(
        fin,
        "revenueGrowthYoY",
        "growthRatePercentRevenue3Year",
    )
    eps_val, eps_src = _first_metric(
        fin,
        "earningsGrowthYoY",
        "growthRatePercentEps3Year",
    )
    mcap_val, _ = _first_metric(fin, "marketCapCr")
    pe_val, _ = _first_metric(
        fin, "peTrailing", "peExcludingExtraordinaryItemsMostRecentFiscalYear"
    )
    fcf_val, _ = _first_metric(fin, "freeCashFlowtrailing12Month")

    missing_msg = "not reported by provider"

    def _gte_status(val: float | None, threshold: float) -> str:
        if val is None:
            return "unavailable"
        return "pass" if val >= threshold else "fail"

    def _lte_status(val: float | None, threshold: float) -> str:
        if val is None:
            return "unavailable"
        return "pass" if val <= threshold else "fail"

    facets = [
        QualityFacet(
            "roe",
            "Return on Equity (TTM)",
            _gte_status(roe_val, ROE_MIN_PCT),  # type: ignore[arg-type]
            roe_val,
            f">= {ROE_MIN_PCT}%",
            "%",
            source=roe_src,
            reason=None if roe_val is not None else missing_msg,
        ),
        QualityFacet(
            "operating_margin",
            "Operating Margin (TTM)",
            _gte_status(opm_val, OP_MARGIN_MIN_PCT),  # type: ignore[arg-type]
            opm_val,
            f">= {OP_MARGIN_MIN_PCT}%",
            "%",
            source=opm_src,
            reason=None if opm_val is not None else missing_msg,
        ),
        (
            QualityFacet(
                "debt_to_equity",
                "Debt / Equity",
                "not_applicable",
                None,
                None,
                "x",
                source=de_src,
                reason=f"Leverage ratio not applicable for {sector_key}",
            )
            if sector_key in LEVERAGE_EXEMPT_SECTORS
            else QualityFacet(
                "debt_to_equity",
                "Debt / Equity",
                _lte_status(de_val, DEBT_EQUITY_MAX),  # type: ignore[arg-type]
                de_val,
                f"<= {DEBT_EQUITY_MAX}",
                "x",
                source=de_src,
                reason=None if de_val is not None else missing_msg,
            )
        ),
        QualityFacet(
            "sales_yoy",
            "Sales Growth (YoY)",
            _gte_status(sales_val, SALES_GROWTH_MIN_PCT),  # type: ignore[arg-type]
            sales_val,
            f">= {SALES_GROWTH_MIN_PCT}%",
            "%",
            source=sales_src,
            reason=None if sales_val is not None else missing_msg,
        ),
        QualityFacet(
            "eps_yoy",
            "EPS Growth (YoY)",
            _gte_status(eps_val, EPS_GROWTH_MIN_PCT),  # type: ignore[arg-type]
            eps_val,
            f">= {EPS_GROWTH_MIN_PCT}%",
            "%",
            source=eps_src,
            reason=None if eps_val is not None else missing_msg,
        ),
    ]

    return QualityReport(
        symbol=symbol,
        sector_key=sector_key,
        source=fin.source,
        unavailable_reason=fin.unavailable_reason,
        facets=tuple(facets),
        summary={
            "roe": roe_val,
            "operating_margin": opm_val,
            "debt_to_equity": None if sector_key in LEVERAGE_EXEMPT_SECTORS else de_val,
            "sales_yoy": sales_val,
            "eps_yoy": eps_val,
            "mkt_cap_cr": mcap_val,
            "pe": pe_val,
            "fcf_cr": fcf_val,
        },
    )
