"""Company financials from Indian API.

**The quota is the design constraint, not a detail.** The free tier allows 500 requests a
*month* — about sixteen a day. A NIFTY 500 scan that fetched financials per name would spend
the entire month in one run and fail two-thirds of the way through it. Everything here follows
from that:

* **One call per company, not four.** `/stock?name=` returns 145 key metrics across eight
  categories, plus shareholding, peers and recent news. `/historical_stats` is four separate
  calls for long history and is used only when a *series* is actually needed. Discovering this
  turned the per-company cost from four requests into one.
* **The cache lifetime is measured in weeks.** These figures change when a company reports,
  four times a year. A day-scale TTL would spend the quota re-reading numbers that had not
  moved.
* **A hard budget that refuses rather than overspends.** The same posture as `DailyBudget` for
  model spend: when the cap is reached the seam returns empty with a reason, and the cycle
  around it keeps working. A quota silently exhausted mid-scan is worse than one that stops.

**Shaped against recorded responses, not documentation.** The provider publishes no OpenAPI
spec, and the shapes here came from real captured payloads — including a quirk that would
otherwise have caused silent partial gaps: metric keys arrive with stray closing parentheses
on some names (`returnOnAverageEquityMostRecentFiscalYear)`), so lookups normalise.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.core.clock import now_utc
from app.domain.financials import (
    CompanyFinancials,
    Metric,
    PeriodValue,
    Shareholding,
    StatementSeries,
    empty,
    normalise_key,
    parse_period,
)
from app.domain.instrument import Instrument

log = logging.getLogger(__name__)

BASE_URL = "https://stock.indianapi.in"
SOURCE = "indianapi"

#: Long-history statement modes. Each is its own request, so each is opt-in.
STATS_MODES = (
    "quarter_results",
    "balancesheet",
    "cashflow",
    "ratios",
    "shareholding_pattern_quarterly",
    "shareholding_pattern_yearly",
)


class IndianApiFinancialsSource:
    """Implements the `CompanyFinancialsSource` seam.

    ``fetcher`` is injectable so every test runs offline against captured payloads — no test in
    this repository may spend a request from a 500-a-month allowance.
    """

    def __init__(
        self,
        api_key: str | None,
        fetcher=None,
        budget=None,
        cache=None,
        timeout: float = 40.0,
    ) -> None:
        self._api_key = api_key
        self._fetcher = fetcher
        self._budget = budget
        self._cache = cache
        self._timeout = timeout
        self._session: Any = None

    # ── fetching ──────────────────────────────────────────────────────────────
    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any] | None:
        if self._fetcher is not None:
            return self._fetcher(path, params)

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(
                {"X-API-Key": self._api_key or "", "Accept": "application/json"}
            )

        response = self._session.get(BASE_URL + path, params=params, timeout=self._timeout)
        if response.status_code == 429:
            raise _Throttled(response.text[:200])
        response.raise_for_status()
        return response.json()

    def _spend(self, what: str) -> bool:
        """Ask the budget before spending. False means do not call the provider."""
        if self._budget is None:
            return True
        allowed = self._budget.allow(what)
        if not allowed:
            log.warning("Indian API request refused by budget: %s", what)
        return allowed

    # ── reading ───────────────────────────────────────────────────────────────
    def financials(self, instrument: Instrument) -> CompanyFinancials:
        """Everything one request can tell us about a company.

        Returns empty with a reason rather than raising, the same rule every source in this
        package follows: one unavailable provider must not end a scan.
        """
        symbol = instrument.symbol

        if not self._api_key:
            return empty(symbol, "INDIAN_API_KEY is not configured")

        if self._cache is not None:
            cached = self._cache.get(symbol)
            if cached is not None:
                return cached

        if not self._spend(f"stock:{symbol}"):
            stale = self._cache.get(symbol, ignore_age=True) if self._cache else None
            if stale is not None:
                return stale
            return empty(symbol, "monthly provider request budget reached")

        try:
            payload = self._get("/stock", {"name": symbol})
        except _Throttled as exc:
            log.warning("Indian API throttled for %s: %s", symbol, exc)
            stale = self._cache.get(symbol, ignore_age=True) if self._cache else None
            return stale if stale is not None else empty(symbol, "provider rate-limited")
        except Exception as exc:
            log.warning("Indian API failed for %s: %s", symbol, exc)
            stale = self._cache.get(symbol, ignore_age=True) if self._cache else None
            return stale if stale is not None else empty(symbol, f"provider error: {exc}")

        result = parse_stock(symbol, payload)
        if self._cache is not None and not result.is_empty:
            self._cache.put(symbol, result)
        return result

    def statement(
        self, instrument: Instrument, mode: str
    ) -> dict[str, StatementSeries]:
        """A long history series. **One request per mode** — ask only when a series is needed.

        `financials()` already carries the trailing and five-year figures most callers want;
        this exists for the cases that genuinely need twelve years of a line item.
        """
        if mode not in STATS_MODES:
            raise ValueError(f"unknown stats mode {mode!r}; expected one of {STATS_MODES}")
        if not self._api_key or not self._spend(f"{mode}:{instrument.symbol}"):
            return {}
        try:
            payload = self._get(
                "/historical_stats", {"stock_name": instrument.symbol, "stats": mode}
            )
        except Exception as exc:
            log.warning("Indian API statement %s failed for %s: %s", mode, instrument.symbol, exc)
            return {}
        return parse_statements(payload or {})


class _Throttled(RuntimeError):
    """The provider said slow down. Distinct from a failure — the data still exists."""


# ── parsing ───────────────────────────────────────────────────────────────────
def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def parse_statements(payload: dict[str, Any]) -> dict[str, StatementSeries]:
    """`{metric: {period: value}}` — the shape `/historical_stats` returns, newest first."""
    out: dict[str, StatementSeries] = {}
    for metric, periods in (payload or {}).items():
        if not isinstance(periods, dict):
            continue
        points = []
        for label, raw in periods.items():
            value = _to_float(raw)
            if value is None:
                continue
            points.append(PeriodValue(period=label, value=value, period_end=parse_period(label)))
        # Newest first, and by parsed date rather than by insertion order — the provider
        # returns oldest first, and depending on dict order for a financial series is how a
        # growth comparison silently inverts.
        points.sort(key=lambda p: (p.period_end is not None, p.period_end), reverse=True)
        out[metric] = StatementSeries(metric=metric, points=tuple(points))
    return out


def _parse_shareholding(rows: list[dict[str, Any]]) -> tuple[Shareholding, ...]:
    """`/stock`'s shareholding is category-major; the platform wants it date-major.

    **Matched on both of the provider's labels**, because they disagree and only one of them
    is recognisable. The domestic-institution row arrives as `displayName: "MF"` with
    `categoryName: "Mutual Fund/Insurance"` — matching the short label alone finds nothing
    resembling "domestic" or "institution", and the figure silently comes back as `None`.
    Found against a live response, not in the fixture.

    Note the bucketing is the provider's and it is coarser here than on `/historical_stats`,
    which reports promoters, FIIs, DIIs, government and public separately. Mutual funds and
    insurance are domestic institutions, so mapping that row to `dii` is right — but it is the
    provider's grouping, and the precise split costs its own request.
    """
    by_date: dict[date, dict[str, float | None]] = {}
    for row in rows or []:
        # Both labels, joined — either may carry the recognisable word.
        label = " ".join(
            part.strip().lower()
            for part in (row.get("displayName"), row.get("categoryName"))
            if part
        )
        for entry in row.get("categories") or []:
            raw_date = (entry.get("holdingDate") or "").strip()
            try:
                when = date.fromisoformat(raw_date[:10])
            except ValueError:
                continue
            by_date.setdefault(when, {})[label] = _to_float(entry.get("percentage"))

    def pick(bucket: dict[str, float | None], *needles: str) -> float | None:
        for needle in needles:
            for label, value in bucket.items():
                if needle in label:
                    return value
        return None

    out = [
        Shareholding(
            as_of=when,
            promoter_pct=pick(bucket, "promoter"),
            fii_pct=pick(bucket, "foreign", "fii"),
            # Deliberately NOT dii. This endpoint's "MF" row is mutual funds and insurance
            # only; the shareholding-history endpoint's "DIIs" is every domestic institution.
            # For one real company they read 5.68 and 13.41. Filling `dii_pct` from this row
            # would understate institutional ownership by more than half and nothing
            # downstream would be able to tell.
            mutual_fund_pct=pick(bucket, "mutual fund", "insurance", "mf"),
            other_pct=pick(bucket, "other"),
            dii_pct=None,
            government_pct=None,
            public_pct=None,
            # Deliberately never inferred. The provider does not report pledge, and guessing
            # zero would turn "nobody told us" into "nothing is pledged".
            pledge_pct=None,
            source=SOURCE,
        )
        for when, bucket in by_date.items()
    ]
    return tuple(sorted(out, key=lambda s: s.as_of, reverse=True))


def parse_stock(symbol: str, payload: dict[str, Any]) -> CompanyFinancials:
    """The `/stock` payload — 145 metrics in eight categories, plus ownership and peers."""
    if not payload:
        return empty(symbol, "provider returned nothing")

    metrics: dict[str, Metric] = {}
    for category, entries in (payload.get("keyMetrics") or {}).items():
        for entry in entries or []:
            raw_key = entry.get("key") or ""
            if not raw_key:
                continue
            key = normalise_key(raw_key)
            metrics[key] = Metric(
                key=key,
                label=entry.get("displayName") or raw_key,
                value=_to_float(entry.get("value")),
                category=category,
                source=SOURCE,
            )

    profile = payload.get("companyProfile") or {}
    # The company *name*, never `tickerId`. That field is a provider-internal identifier
    # (`S0003032`) that is neither an NSE symbol nor resolvable to one, so storing it would
    # produce a peer list nothing downstream could match against the universe.
    peers = tuple(
        (p.get("companyName") or "").strip()
        for p in (profile.get("peerCompanyList") or [])
        if isinstance(p, dict)
    )

    return CompanyFinancials(
        symbol=symbol,
        metrics=metrics,
        shareholding=_parse_shareholding(payload.get("shareholding") or []),
        industry=payload.get("industry"),
        company_name=payload.get("companyName"),
        description=(profile.get("companyDescription") or None),
        peers=tuple(p for p in peers if p),
        source=SOURCE,
        fetched_at=now_utc(),
    )
