"""Index levels from NSE's own API.

**Why this and not a wrapper library.** `nsepython` was evaluated against the two endpoints
that matter and earns nothing here: its index call is byte-for-byte what `requests` with the
right headers already returns, and `nse_eq("TCS")` — the per-stock quote — comes back as an
**empty dict** rather than an error, which is the worst failure a data source can have. It also
pulls scipy in for arithmetic this module does not do. The header-and-session pattern it exists
to provide is already in this codebase, in `data/universe.py`, and has been since the NSE
constituent CSV started returning 403 to non-browser clients.

**Indices only, and that is a finding rather than a decision.** `/api/allIndices` answers a
plain request. `/api/quote-equity` answers 403 even behind a full browser-like session with the
Akamai cookies its own landing page sets — the per-stock endpoint wants their JS challenge
solved. So live per-stock marks come from the broker session (Zerodha, user-present and already
authorised) or from the last settled close, and this module does not pretend otherwise.

That trade is better than it sounds: **one call returns every index NSE publishes** — 139 of
them, including NIFTY 500 and 21 sectoral indices against the 8 the platform knew about — each
with its level, previous close, trailing returns and advance/decline breadth. The sector view
costs a single request.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.clock import now_utc
from app.core.rate_limit import RateLimiter
from app.domain.instrument import Instrument
from app.domain.quotes import IndexQuote, Quote

log = logging.getLogger(__name__)

ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
BOOTSTRAP_URL = "https://www.nseindia.com"

#: NSE answers 403 to anything that does not look like a browser. Same reason, same fix, as
#: `data/universe.py` — kept separate rather than shared because one is a CSV archive host and
#: the other an API, and merging them would couple two things that fail differently.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

#: Index levels move continuously while the market is open and not at all when it is closed.
#: Short enough to be live, long enough that a page with six panels costs one request.
DEFAULT_TTL_SECONDS = 60.0

#: Floor between requests to the exchange. The documented hazard with reading NSE directly is
#: being blocked for asking too often, and one payload already answers every index question,
#: so there is no reason to go faster than this.
DEFAULT_MIN_INTERVAL_SECONDS = 1.0


class NseIndexQuoteSource:
    """Live index levels, cached and rate-limited.

    ``fetcher`` is injectable so every test runs offline against a recorded payload — the same
    contract `NseUniverseSource` and the tool handlers use.
    """

    def __init__(
        self,
        fetcher=None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        timeout: float = 15.0,
    ) -> None:
        self._fetcher = fetcher
        self._ttl = ttl_seconds
        self._timeout = timeout
        self._limiter = RateLimiter(min_interval_seconds)
        self._session: Any = None
        self._cache: dict[str, IndexQuote] = {}
        self._cached_at: float | None = None

    # ── fetching ──────────────────────────────────────────────────────────────
    def _fetch(self) -> dict[str, Any] | None:
        if self._fetcher is not None:
            return self._fetcher(ALL_INDICES_URL)

        import requests

        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
            try:
                # Establishes whatever cookies the host wants to set. It answers 403 as often
                # as not and the API call succeeds regardless, so this is best-effort by
                # design — failing here would refuse to fetch data that is available.
                self._session.get(BOOTSTRAP_URL, timeout=self._timeout)
            except Exception as exc:
                log.debug("NSE bootstrap did not complete: %s", exc)

        self._limiter.wait()
        response = self._session.get(ALL_INDICES_URL, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _refresh(self) -> bool:
        """Repopulate the cache. False when the provider gave us nothing usable."""
        try:
            payload = self._fetch()
        except Exception as exc:
            # Blocked, throttled or down. Logged and degraded — never raised, the same rule
            # every other source in this package follows.
            log.warning("NSE index fetch failed: %s", exc)
            return False

        rows = (payload or {}).get("data") or []
        parsed = {}
        for row in rows:
            quote = _parse(row)
            if quote is not None:
                parsed[quote.symbol] = quote

        if not parsed:
            log.warning("NSE index fetch returned no usable rows")
            return False

        self._cache = parsed
        self._cached_at = time.monotonic()
        return True

    def _fresh_enough(self) -> bool:
        return self._cached_at is not None and (time.monotonic() - self._cached_at) < self._ttl

    def _ensure(self) -> bool:
        """Make the cache as current as it can be. False when serving a failed refresh.

        The return value is what decides the `cache` label, and it deliberately is **not**
        "has the TTL elapsed". A reading fetched a microsecond ago is a live reading whatever
        the TTL says; what makes a reading stale is that we *tried* to replace it and could
        not. Keying the label on TTL instead marked every reading as cached under a zero TTL,
        which is precisely backwards.
        """
        if self._fresh_enough():
            return True
        if self._refresh():
            return True
        # A stale reading beats no reading, and it is labelled — the same judgement
        # `CachingPriceSource` makes, for the same reason: a strategy can decide staleness is
        # unacceptable, but it can decide nothing at all from nothing.
        if self._cache:
            log.info("serving cached NSE index levels — provider unavailable")
        return False

    # ── reading ───────────────────────────────────────────────────────────────
    def all_indices(self) -> dict[str, IndexQuote]:
        """Every index NSE publishes, keyed by its own name. Empty when unavailable."""
        if self._ensure():
            return dict(self._cache)
        return {name: _as_cached(q) for name, q in self._cache.items()}

    def index_quote(self, name: str) -> IndexQuote | None:
        return self.all_indices().get(name.strip().upper())

    def quote(self, instrument: Instrument) -> Quote | None:
        """The `QuoteSource` seam. Indices resolve; equities do not, and say so by returning
        nothing rather than by raising."""
        name = INDEX_NAME_BY_SYMBOL.get(instrument.symbol)
        if name is None:
            return None
        found = self.index_quote(name)
        return found.quote if found else None


def _as_cached(quote: IndexQuote) -> IndexQuote:
    """Relabel a reading as served from cache, so the age of a number is never implicit."""
    from dataclasses import replace

    return replace(quote, quote=replace(quote.quote, source="cache"))


def _number(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count(row: dict[str, Any], key: str) -> int | None:
    value = _number(row, key)
    return int(value) if value is not None else None


def _parse(row: dict[str, Any]) -> IndexQuote | None:
    name = (row.get("index") or "").strip().upper()
    last = _number(row, "last")
    if not name or last is None:
        return None

    return IndexQuote(
        quote=Quote(
            symbol=name,
            last=last,
            previous_close=_number(row, "previousClose"),
            observed_at=now_utc(),
            source="nse",
        ),
        name=name,
        change_30d_pct=_number(row, "perChange30d"),
        change_365d_pct=_number(row, "perChange365d"),
        advances=_count(row, "advances"),
        declines=_count(row, "declines"),
        unchanged=_count(row, "unchanged"),
        year_high=_number(row, "yearHigh"),
        year_low=_number(row, "yearLow"),
    )


#: Bridge between the two vocabularies for the same index. yfinance addresses the Nifty 50 as
#: `^NSEI` and NSE calls it `NIFTY 50`; both names are real and neither is wrong, so the
#: translation lives here — at the seam — rather than leaking into callers. Same rule as
#: `Instrument.yf_ticker`.
INDEX_NAME_BY_SYMBOL: dict[str, str] = {
    "^NSEI": "NIFTY 50",
    "^CRSLDX": "NIFTY 500",
    "^NSEBANK": "NIFTY BANK",
    "^CNXIT": "NIFTY IT",
    "^CNXFMCG": "NIFTY FMCG",
    "^CNXPHARMA": "NIFTY PHARMA",
    "^CNXAUTO": "NIFTY AUTO",
    "^CNXMETAL": "NIFTY METAL",
    "^CNXENERGY": "NIFTY ENERGY",
    "^CNXREALTY": "NIFTY REALTY",
    "^CNXMEDIA": "NIFTY MEDIA",
    "^CNXPSUBANK": "NIFTY PSU BANK",
    "^CNXINFRA": "NIFTY INFRASTRUCTURE",
    "^CNXCONSUM": "NIFTY INDIA CONSUMPTION",
}
