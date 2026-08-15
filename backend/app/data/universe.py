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
BLOCKLIST_FILE = RESOURCES / "blocked_tickers.json"

NSE_NIFTY500_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

#: NSE returns 403 to clients that do not look like a browser.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*",
}


@lru_cache(maxsize=2)
def _load_symbols(path_str: str) -> tuple[str, ...]:
    payload = json.loads(Path(path_str).read_text("utf-8"))
    return tuple(payload.get("symbols", ()))


def blocked_symbols() -> frozenset[str]:
    """Symbols excluded from every snapshot, live or fallback."""
    return frozenset(_load_symbols(str(BLOCKLIST_FILE)))


class NseUniverseSource:
    """Implements :class:`app.data.protocols.UniverseSource`."""

    def __init__(
        self,
        index_name: str = "NIFTY500",
        csv_url: str = NSE_NIFTY500_CSV_URL,
        fetcher=None,
        timeout: float = 10.0,
    ) -> None:
        """``fetcher`` is injectable so tests replay a recorded CSV rather than calling NSE."""
        self._index_name = index_name
        self._csv_url = csv_url
        self._fetcher = fetcher
        self._timeout = timeout

    def _fetch_csv(self) -> str | None:
        if self._fetcher is not None:
            return self._fetcher(self._csv_url)

        import requests

        response = requests.get(self._csv_url, headers=_HEADERS, timeout=self._timeout)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse(text: str) -> list[tuple[str, str | None, str | None]]:
        """-> [(symbol, company name, industry)] from the NSE constituent CSV."""
        rows = csv.DictReader(io.StringIO(text))
        parsed: list[tuple[str, str | None, str | None]] = []
        for row in rows:
            # NSE's header casing has changed before; match case-insensitively.
            lowered = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            symbol = lowered.get("symbol", "")
            if not symbol:
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
        blocked = blocked_symbols()

        try:
            text = self._fetch_csv()
            entries = self._parse(text or "")
            if not entries:
                raise ValueError("constituent CSV parsed to zero rows")
        except Exception as exc:
            log.warning("NSE constituent fetch failed (%s); using the bundled fallback list", exc)
            return self._fallback_snapshot(blocked)

        kept, excluded = [], []
        for symbol, name, sector in entries:
            if symbol in blocked:
                excluded.append(symbol)
                continue
            kept.append(Instrument(symbol=symbol, name=name, sector=sector))

        return UniverseSnapshot(
            instruments=tuple(kept),
            origin="live",
            index_name=self._index_name,
            excluded=tuple(sorted(excluded)),
        )

    def _fallback_snapshot(self, blocked: frozenset[str]) -> UniverseSnapshot:
        symbols = _load_symbols(str(FALLBACK_FILE))
        kept = [Instrument(symbol=s) for s in symbols if s not in blocked]
        excluded = sorted(s for s in symbols if s in blocked)
        return UniverseSnapshot(
            instruments=tuple(kept),
            origin="fallback",
            index_name=self._index_name,
            excluded=tuple(excluded),
        )
