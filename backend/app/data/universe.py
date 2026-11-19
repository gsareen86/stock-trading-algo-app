"""Which instruments exist.

NSE publishes index constituents as a CSV. When that fetch fails — and it does, NSE rate-limits
and occasionally blocks non-browser clients — the bundled snapshot is used instead.

Every snapshot records **which path was taken**. A universe that silently shrank from 500
names to the 247 in the bundled list is otherwise indistinguishable from a real index
reconstitution, and a scan over the wrong universe produces plausible, wrong results.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from functools import lru_cache
from pathlib import Path

from app.data.protocols import UniverseSnapshot
from app.domain.instrument import Instrument

log = logging.getLogger(__name__)

RESOURCES = Path(__file__).parent / "resources"
FALLBACK_FILE = RESOURCES / "nse_fallback_universe.json"
TOTAL_MARKET_FALLBACK_FILE = RESOURCES / "nse_nifty_total_market_fallback.json"
BLOCKLIST_FILE = RESOURCES / "blocked_tickers.json"

NSE_NIFTY500_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
NIFTYINDICES_NIFTY500_CSV_URL = (
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
)
NSE_NIFTY_TOTAL_MARKET_CSV_URL = (
    "https://archives.nseindia.com/content/indices/ind_niftytotalmarketlist.csv"
)
NIFTYINDICES_TOTAL_MARKET_CSV_URL = (
    "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"
)

INDEX_CSV_URLS: dict[str, tuple[str, ...]] = {
    "NIFTY_TOTAL_MARKET": (NIFTYINDICES_TOTAL_MARKET_CSV_URL, NSE_NIFTY_TOTAL_MARKET_CSV_URL),
    "NIFTY500": (NIFTYINDICES_NIFTY500_CSV_URL, NSE_NIFTY500_CSV_URL),
}

INDEX_FALLBACK_FILES: dict[str, Path] = {
    "NIFTY_TOTAL_MARKET": TOTAL_MARKET_FALLBACK_FILE,
    "NIFTY500": FALLBACK_FILE,
}

#: NSE returns 403 to clients that do not look like a browser.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
}


@lru_cache(maxsize=4)
def _load_symbols(path_str: str) -> tuple[str, ...]:
    payload = json.loads(Path(path_str).read_text("utf-8"))
    return tuple(payload.get("symbols", ()))


@lru_cache(maxsize=4)
def _load_fallback_instruments(path_str: str) -> tuple[Instrument, ...]:
    payload = json.loads(Path(path_str).read_text("utf-8"))
    raw_instruments = payload.get("instruments")
    if isinstance(raw_instruments, list) and raw_instruments:
        return tuple(
            Instrument(
                symbol=str(row["symbol"]).strip().upper(),
                name=row.get("name") or None,
                sector=row.get("industry") or row.get("sector") or None,
            )
            for row in raw_instruments
            if row.get("symbol")
        )
    return tuple(Instrument(symbol=s) for s in payload.get("symbols", ()))


def blocked_symbols() -> frozenset[str]:
    """Symbols excluded from every snapshot, live or fallback."""
    return frozenset(_load_symbols(str(BLOCKLIST_FILE)))


class NseUniverseSource:
    """Implements :class:`app.data.protocols.UniverseSource`."""

    def __init__(
        self,
        index_name: str = "NIFTY_TOTAL_MARKET",
        csv_url: str | None = None,
        fetcher=None,
        timeout: float = 10.0,
        cache_ttl_seconds: float = 6 * 3600.0,
    ) -> None:
        """``fetcher`` is injectable so tests replay a recorded CSV rather than calling NSE."""
        self._index_name = index_name.strip().upper()
        if csv_url is not None:
            self._csv_urls: tuple[str, ...] = (csv_url,)
        else:
            self._csv_urls = INDEX_CSV_URLS.get(
                self._index_name,
                (NIFTYINDICES_TOTAL_MARKET_CSV_URL, NSE_NIFTY_TOTAL_MARKET_CSV_URL),
            )
        self._csv_url = self._csv_urls[0]
        self._fetcher = fetcher
        self._timeout = timeout
        self._cache_ttl = cache_ttl_seconds
        self._cached_snapshot: UniverseSnapshot | None = None
        self._cached_at: float = 0.0

    def _fetch_csv(self) -> str | None:
        if self._fetcher is not None:
            return self._fetcher(self._csv_url)

        import requests

        last_exc: Exception | None = None
        for url in self._csv_urls:
            try:
                response = requests.get(url, headers=_HEADERS, timeout=self._timeout)
                response.raise_for_status()
                if response.text and "symbol" in response.text[:200].lower():
                    return response.text
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        return None

    @staticmethod
    def _parse(text: str) -> list[tuple[str, str | None, str | None]]:
        """-> [(symbol, company name, industry)] from the NSE constituent CSV."""
        rows = csv.DictReader(io.StringIO(text))
        parsed: list[tuple[str, str | None, str | None]] = []
        for row in rows:
            # NSE's header casing has changed before; match case-insensitively.
            lowered = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            symbol = lowered.get("symbol", "")
            if not symbol or symbol.upper().startswith("DUMMY"):
                continue
            parsed.append(
                (
                    symbol.upper(),
                    lowered.get("company name") or None,
                    lowered.get("industry") or None,
                )
            )
        return parsed

    def snapshot(self) -> UniverseSnapshot:
        import time

        if (
            self._fetcher is None
            and self._cached_snapshot is not None
            and (time.monotonic() - self._cached_at) < self._cache_ttl
        ):
            return self._cached_snapshot

        blocked = blocked_symbols()

        try:
            text = self._fetch_csv()
            entries = self._parse(text or "")
            if not entries:
                raise ValueError("constituent CSV parsed to zero rows")
        except Exception as exc:
            log.warning(
                "NSE constituent fetch failed for %s (%s); using the bundled fallback list",
                self._index_name,
                exc,
            )
            return self._fallback_snapshot(blocked)

        kept, excluded = [], []
        for symbol, name, sector in entries:
            if symbol in blocked:
                excluded.append(symbol)
                continue
            kept.append(Instrument(symbol=symbol, name=name, sector=sector))

        snap = UniverseSnapshot(
            instruments=tuple(kept),
            origin="live",
            index_name=self._index_name,
            excluded=tuple(sorted(excluded)),
        )
        if self._fetcher is None:
            self._cached_snapshot = snap
            self._cached_at = time.monotonic()
        return snap

    def _fallback_snapshot(self, blocked: frozenset[str]) -> UniverseSnapshot:
        fallback_path = INDEX_FALLBACK_FILES.get(self._index_name, TOTAL_MARKET_FALLBACK_FILE)
        instruments = _load_fallback_instruments(str(fallback_path))
        kept = [inst for inst in instruments if inst.symbol not in blocked]
        excluded = sorted(inst.symbol for inst in instruments if inst.symbol in blocked)
        return UniverseSnapshot(
            instruments=tuple(kept),
            origin="fallback",
            index_name=self._index_name,
            excluded=tuple(excluded),
        )


def bundled_sectors() -> dict[str, str]:
    """Symbol -> industry from the bundled Total Market list, which carries industries.

    The Nifty 500 fallback lists symbols only, so a universe that fell back to it knows no
    sectors. The Total Market list is a superset with industries, and filling gaps from it lets
    sector-aware strategies place a name even when the live constituent file was unreachable.
    """
    return {
        inst.symbol: inst.sector
        for inst in _load_fallback_instruments(str(TOTAL_MARKET_FALLBACK_FILE))
        if inst.sector
    }
