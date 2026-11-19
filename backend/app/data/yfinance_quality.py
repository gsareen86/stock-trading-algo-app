"""Free company quality, ratios, growth, and profile adapter backed by yfinance.

Implements :class:`app.data.protocols.CompanyFinancialsSource` without requiring any paid
API key, caching results on disk via :class:`app.data.financials_cache.FinancialsCache`.

Honest gaps:
* Fields Yahoo Finance does not carry for NSE stocks — notably Indian promoter pledge %,
  exact FII vs DII splits, and detailed segment breakdowns — are left ``None`` / absent
  rather than guessed or zeroed.
* When ``INDIAN_API_KEY`` is configured, :class:`CompositeCompanyFinancialsSource` tries
  ``IndianApiFinancialsSource`` first and falls back here when unconfigured or throttled.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any

from app.core.clock import now_utc
from app.data.protocols import CompanyFinancialsSource
from app.domain.financials import (
    CompanyFinancials,
    Metric,
    PeriodValue,
    Shareholding,
    StatementSeries,
    empty,
    normalise_key,
)
from app.domain.instrument import Instrument

log = logging.getLogger(__name__)

SOURCE = "yfinance"


def _clean_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _metric(
    key: str,
    label: str,
    value: float | None,
    category: str,
    *,
    derived_from: tuple[str, ...] = (),
    source: str = SOURCE,
) -> tuple[str, Metric]:
    norm = normalise_key(key)
    return norm, Metric(
        key=norm,
        label=label,
        value=value,
        category=category,
        source=source,
        derived_from=derived_from,
    )


def _extract_statement_series(
    frame: Any, candidates: tuple[str, ...], name: str
) -> StatementSeries | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    labels = {str(i).strip().lower(): i for i in frame.index}
    for candidate in candidates:
        key = labels.get(candidate.lower())
        if key is None:
            continue
        row = frame.loc[key]
        points: list[PeriodValue] = []
        for col, raw in row.items():
            val = _clean_float(raw)
            if val is None:
                continue
            try:
                period_end = (
                    col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
                )
            except ValueError:
                period_end = None
            label = period_end.strftime("%b %Y") if period_end else str(col)
            points.append(PeriodValue(period=label, value=round(val, 4), period_end=period_end))
        points.sort(key=lambda p: (p.period_end is not None, p.period_end), reverse=True)
        if points:
            return StatementSeries(metric=name, points=tuple(points))
    return None


def _yoy_growth_pct(series: StatementSeries | None) -> float | None:
    """Compare latest quarter (index 0) vs same quarter one year earlier (index 4)."""
    if series is None or len(series.points) <= 4:
        return None
    latest = series.at(0)
    year_ago = series.at(4)
    if latest is None or year_ago is None or year_ago <= 0:
        return None
    return round((latest / year_ago - 1.0) * 100.0, 2)


class YFinanceQualitySource:
    """Implements :class:`app.data.protocols.CompanyFinancialsSource` via yfinance."""

    def __init__(self, fetcher=None, cache=None) -> None:
        """``fetcher`` is injectable for offline tests: ``(yf_ticker) -> dict``."""
        self._fetcher = fetcher
        self._cache = cache

    def _fetch(self, yf_ticker: str) -> dict[str, Any]:
        if self._fetcher is not None:
            return self._fetcher(yf_ticker) or {}

        import yfinance as yf

        ticker = yf.Ticker(yf_ticker)
        info = ticker.info or {}
        q_income = None
        balance = None
        cashflow = None
        try:
            q_income = ticker.quarterly_income_stmt
        except Exception as exc:
            log.debug("quarterly_income_stmt unavailable for %s: %s", yf_ticker, exc)
        try:
            balance = ticker.balance_sheet
        except Exception as exc:
            log.debug("balance_sheet unavailable for %s: %s", yf_ticker, exc)
        try:
            cashflow = ticker.cashflow
        except Exception as exc:
            log.debug("cashflow unavailable for %s: %s", yf_ticker, exc)
        return {
            "info": info,
            "quarterly_income_stmt": q_income,
            "balance_sheet": balance,
            "cashflow": cashflow,
        }

    def financials(self, instrument: Instrument) -> CompanyFinancials:
        symbol = instrument.symbol
        if self._cache is not None:
            cached = self._cache.get(symbol)
            if cached is not None:
                return cached

        try:
            payload = self._fetch(instrument.yf_ticker)
        except Exception as exc:
            log.warning("yfinance quality fetch failed for %s: %s", symbol, exc)
            stale = self._cache.get(symbol, ignore_age=True) if self._cache else None
            return stale if stale is not None else empty(symbol, f"yfinance error: {exc}")

        info = payload.get("info") if isinstance(payload, dict) and "info" in payload else payload
        if not isinstance(info, dict):
            info = {}

        q_income = payload.get("quarterly_income_stmt") if isinstance(payload, dict) else None
        balance = payload.get("balance_sheet") if isinstance(payload, dict) else None
        cashflow = payload.get("cashflow") if isinstance(payload, dict) else None

        if not info and q_income is None and balance is None and cashflow is None:
            stale = self._cache.get(symbol, ignore_age=True) if self._cache else None
            return (
                stale
                if stale is not None
                else empty(symbol, "yfinance returned no company data")
            )

        metrics: dict[str, Metric] = {}

        def add(
            key: str,
            label: str,
            val: float | None,
            category: str,
            *,
            derived_from: tuple[str, ...] = (),
        ) -> None:
            norm, m = _metric(key, label, val, category, derived_from=derived_from)
            metrics[norm] = m

        # ── Ratios from info ──────────────────────────────────────────────────
        roe = _clean_float(info.get("returnOnEquity"))
        add(
            "returnOnAverageEquityTrailing12Month",
            "Return on Equity (TTM %)",
            round(roe * 100.0, 2) if roe is not None else None,
            "mgmtEffectiveness",
        )

        op_margin = _clean_float(info.get("operatingMargins"))
        add(
            "operatingMarginTrailing12Month",
            "Operating Margin (TTM %)",
            round(op_margin * 100.0, 2) if op_margin is not None else None,
            "profitability",
        )

        net_margin = _clean_float(info.get("profitMargins"))
        add(
            "netProfitMarginTrailing12Month",
            "Net Profit Margin (TTM %)",
            round(net_margin * 100.0, 2) if net_margin is not None else None,
            "profitability",
        )

        # Leverage: prefer latest balance sheet ratio, else convert Yahoo's % D/E to ratio.
        de_val: float | None = None
        de_derived: tuple[str, ...] = ()
        debt_series = _extract_statement_series(
            balance, ("Total Debt", "Long Term Debt"), "Total Debt"
        )
        eq_series = _extract_statement_series(
            balance, ("Stockholders Equity", "Common Stock Equity"), "Stockholders Equity"
        )
        if debt_series and eq_series:
            d0 = debt_series.latest()
            e0 = eq_series.latest()
            if d0 is not None and e0 is not None and e0 > 0:
                de_val = round(d0 / e0, 3)
                de_derived = ("Total Debt", "Stockholders Equity")
        if de_val is None:
            yf_de = _clean_float(info.get("debtToEquity"))
            if yf_de is not None:
                de_val = round(yf_de / 100.0, 3)
        add(
            "totalDebtPerTotalEquityMostRecentQuarter",
            "Debt to Equity",
            de_val,
            "financialStrength",
            derived_from=de_derived,
        )

        # Valuation & size
        mkt_cap = _clean_float(info.get("marketCap"))
        add(
            "marketCapCr",
            "Market Cap (INR Cr)",
            round(mkt_cap / 1e7, 2) if mkt_cap is not None else None,
            "valuation",
            derived_from=("marketCap",) if mkt_cap is not None else (),
        )
        pe = _clean_float(info.get("trailingPE"))
        add("peTrailing", "Trailing P/E", round(pe, 2) if pe is not None else None, "valuation")
        pb = _clean_float(info.get("priceToBook"))
        add("priceToBook", "Price to Book", round(pb, 2) if pb is not None else None, "valuation")

        # Cash flow
        fcf = _clean_float(info.get("freeCashflow"))
        fcf_derived: tuple[str, ...] = ()
        if fcf is None:
            fcf_series = _extract_statement_series(cashflow, ("Free Cash Flow",), "Free Cash Flow")
            if fcf_series is not None:
                fcf = fcf_series.latest()
                fcf_derived = ("cashflow.Free Cash Flow",)
        add(
            "freeCashFlowtrailing12Month",
            "Free Cash Flow (TTM INR Cr)",
            round(fcf / 1e7, 2) if fcf is not None else None,
            "cashFlow",
            derived_from=fcf_derived,
        )

        # Statements & growth
        statements: dict[str, StatementSeries] = {}
        rev_series = _extract_statement_series(
            q_income, ("Total Revenue", "Operating Revenue"), "Quarterly Revenue"
        )
        if rev_series is not None:
            statements["quarterly_revenue"] = rev_series
        eps_series = _extract_statement_series(
            q_income, ("Basic EPS", "Diluted EPS"), "Quarterly EPS"
        )
        if eps_series is not None:
            statements["quarterly_eps"] = eps_series
        ni_series = _extract_statement_series(
            q_income, ("Net Income", "Net Income Common Stockholders"), "Quarterly Net Income"
        )
        if ni_series is not None:
            statements["quarterly_net_income"] = ni_series

        rev_yoy = _yoy_growth_pct(rev_series)
        rev_derived: tuple[str, ...] = ("quarterly_revenue",) if rev_yoy is not None else ()
        if rev_yoy is None:
            rg = _clean_float(info.get("revenueGrowth"))
            if rg is not None:
                rev_yoy = round(rg * 100.0, 2)
        add("revenueGrowthYoY", "Sales Growth (YoY %)", rev_yoy, "growth", derived_from=rev_derived)

        eps_yoy = _yoy_growth_pct(eps_series)
        eps_derived: tuple[str, ...] = ("quarterly_eps",) if eps_yoy is not None else ()
        if eps_yoy is None:
            eg = _clean_float(info.get("earningsQuarterlyGrowth")) or _clean_float(
                info.get("earningsGrowth")
            )
            if eg is not None:
                eps_yoy = round(eg * 100.0, 2)
        add("earningsGrowthYoY", "EPS Growth (YoY %)", eps_yoy, "growth", derived_from=eps_derived)

        # Ownership (honest: promoter pledge & Indian DII/FII breakdown are unavailable in yfinance)
        insiders = _clean_float(info.get("heldPercentInsiders"))
        institutions = _clean_float(info.get("heldPercentInstitutions"))
        add(
            "insiderHeldPct",
            "Insider / Promoter Group Held (%)",
            round(insiders * 100.0, 2) if insiders is not None else None,
            "ownership",
        )
        add(
            "institutionalHeldPct",
            "Institutional Held (%)",
            round(institutions * 100.0, 2) if institutions is not None else None,
            "ownership",
        )

        shareholding: tuple[Shareholding, ...] = ()
        if insiders is not None or institutions is not None:
            shareholding = (
                Shareholding(
                    as_of=now_utc().date(),
                    promoter_pct=round(insiders * 100.0, 2) if insiders is not None else None,
                    # Institutional bucket combines FII + DII in Yahoo, so keep granular fields None
                    # and pledge strictly None rather than guessing.
                    fii_pct=None,
                    dii_pct=None,
                    pledge_pct=None,
                    source=SOURCE,
                ),
            )

        has_any_value = (
            any(m.available for m in metrics.values()) or bool(statements) or bool(shareholding)
        )
        if not has_any_value and not info.get("longBusinessSummary"):
            return empty(symbol, "yfinance returned no usable financial metrics")

        result = CompanyFinancials(
            symbol=symbol,
            metrics=metrics,
            statements=statements,
            shareholding=shareholding,
            industry=info.get("industry") or instrument.sector,
            company_name=info.get("longName") or info.get("shortName") or instrument.name,
            description=info.get("longBusinessSummary") or None,
            peers=(),
            source=SOURCE,
            fetched_at=now_utc(),
        )
        if self._cache is not None and not result.is_empty:
            self._cache.put(symbol, result)
        return result


class CompositeCompanyFinancialsSource:
    """Tries primary source (e.g. IndianAPI when configured) and falls back to free yfinance."""

    def __init__(
        self,
        primary: CompanyFinancialsSource | None,
        fallback: CompanyFinancialsSource,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def financials(self, instrument: Instrument) -> CompanyFinancials:
        if self._primary is not None:
            res = self._primary.financials(instrument)
            if not res.is_empty:
                return res
        return self._fallback.financials(instrument)


def build_company_financials_source(
    settings: Any, session_factory: Any = None
) -> CompositeCompanyFinancialsSource:
    """Build the composite company financials source with local JSON caching."""
    from pathlib import Path

    from app.data.financials_cache import FinancialsCache
    from app.data.indian_api import IndianApiFinancialsSource

    cache_root = Path(settings.llm_cache_dir).parent / "financials"
    ttl_days = int(getattr(settings, "financials_cache_days", 30))
    enabled = bool(getattr(settings, "llm_cache_enabled", True))
    yf_cache = FinancialsCache(
        cache_dir=cache_root / "yfinance",
        ttl_days=ttl_days,
        enabled=enabled,
    )
    fallback = YFinanceQualitySource(cache=yf_cache)

    primary = None
    indian_key = getattr(settings, "indian_api_key", None)
    if indian_key:
        budget = None
        if session_factory is not None:
            from app.data.provider_budget import MonthlyRequestBudget

            budget = MonthlyRequestBudget(
                session_factory,
                "indianapi",
                getattr(settings, "indian_api_monthly_request_limit", 500),
            )
        ia_cache = FinancialsCache(
            cache_dir=cache_root / "indianapi",
            ttl_days=ttl_days,
            enabled=enabled,
        )
        primary = IndianApiFinancialsSource(
            api_key=indian_key,
            budget=budget,
            cache=ia_cache,
        )
    return CompositeCompanyFinancialsSource(primary=primary, fallback=fallback)

