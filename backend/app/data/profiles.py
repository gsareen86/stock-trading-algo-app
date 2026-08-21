"""What a company actually does, in prose.

**This exists because classifying by company name is wrong**, and the platform was doing it.
Resolution matched supplier descriptions against `name + NSE industry`, which meant a tier for
defence manufacturing found companies with "Defence" in their name and missed Hindustan
Aeronautics, Bharat Dynamics and Mazagon Dock. Measured against the exchange's own
NIFTY INDIA DEFENCE membership it found three of nineteen.

A company's *name* is branding and its NSE *industry* is a filing bucket — seventeen of those
nineteen defence companies file as "Capital Goods", alongside cement plants and pump makers.
Neither describes what a business does.

Two fields here do:

* **`description`** — several hundred words of what the company makes, sells and operates,
  usually naming its divisions and end markets.
* **`industry`** — a granular classification. The same three companies that NSE files as
  "Capital Goods" appear here as `Aerospace & Defense`.

Both come from the price provider already in use, which charges nothing and has no quota, so
the whole universe can be profiled and kept. The metered financials provider has a richer
description still, and is reserved for the candidates a reader actually opens — this is the
one that can be run across five hundred names.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.instrument import Instrument

log = logging.getLogger(__name__)

#: Business descriptions change when a company changes what it does, which is rarely. Months,
#: not hours — and a stale description is still a description.
DEFAULT_TTL_DAYS = 90


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    """What one company does, and how it is classified by someone who looked."""

    symbol: str
    description: str | None = None
    #: Granular — `Aerospace & Defense`, `Electronic Components` — not a filing bucket.
    industry: str | None = None
    sector: str | None = None
    source: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.description and not self.industry

    @property
    def searchable(self) -> str:
        """Everything that describes the business, for matching against.

        Deliberately **excludes the company name**. A name is branding: matching on it is what
        produced a defence tier containing "Paras Defence" and missing Hindustan Aeronautics,
        and including it here would quietly reintroduce that.
        """
        return " ".join(p for p in (self.description, self.industry, self.sector) if p).lower()


class YFinanceProfileSource:
    """Profiles from the price provider, cached to disk.

    ``fetcher`` is injectable so every test runs offline. The cache is one file for the whole
    universe rather than one per symbol: it is read on every resolution pass and a single load
    beats five hundred stats.
    """

    def __init__(
        self,
        cache_path: str | Path,
        fetcher=None,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> None:
        self._path = Path(cache_path)
        self._fetcher = fetcher
        self._ttl_seconds = ttl_days * 86400
        self._loaded: dict[str, CompanyProfile] | None = None

    # ── cache ─────────────────────────────────────────────────────────────────
    def _load(self) -> dict[str, CompanyProfile]:
        if self._loaded is not None:
            return self._loaded
        if not self._path.exists():
            self._loaded = {}
            return self._loaded
        try:
            payload = json.loads(self._path.read_text("utf-8"))
        except Exception as exc:
            log.warning("unreadable profile cache: %s", exc)
            self._loaded = {}
            return self._loaded

        self._loaded = {
            symbol: CompanyProfile(
                symbol=symbol,
                description=row.get("description"),
                industry=row.get("industry"),
                sector=row.get("sector"),
                source=row.get("source", "cache"),
            )
            for symbol, row in (payload.get("profiles") or {}).items()
        }
        return self._loaded

    def _save(self) -> None:
        profiles = self._loaded or {}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {
                        "built_at": time.time(),
                        "profiles": {
                            symbol: {
                                "description": p.description,
                                "industry": p.industry,
                                "sector": p.sector,
                                "source": p.source,
                            }
                            for symbol, p in profiles.items()
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            # A cache that cannot be written is a slow platform, not a broken one.
            log.warning("profile cache write failed: %s", exc)

    @property
    def is_stale(self) -> bool:
        if not self._path.exists():
            return True
        return (time.time() - self._path.stat().st_mtime) >= self._ttl_seconds

    # ── fetching ──────────────────────────────────────────────────────────────
    def _fetch(self, symbol: str) -> dict[str, Any]:
        if self._fetcher is not None:
            return self._fetcher(symbol) or {}

        import yfinance as yf

        return yf.Ticker(Instrument(symbol).yf_ticker).info or {}

    def profile(self, symbol: str) -> CompanyProfile:
        """One company's profile, from cache when present."""
        cached = self._load().get(symbol)
        if cached is not None:
            return cached

        try:
            info = self._fetch(symbol)
        except Exception as exc:
            log.debug("profile fetch failed for %s: %s", symbol, exc)
            return CompanyProfile(symbol=symbol)

        profile = CompanyProfile(
            symbol=symbol,
            description=(info.get("longBusinessSummary") or None),
            industry=(info.get("industry") or None),
            sector=(info.get("sector") or None),
            source="yfinance",
        )
        if not profile.is_empty:
            self._load()[symbol] = profile
            self._save()
        return profile

    def build(self, symbols: list[str], progress=None) -> int:
        """Profile a whole universe. Returns how many were newly fetched.

        Roughly a second per name, so around nine minutes for the NIFTY 500 — once, and then
        cached for months. Symbols already cached are skipped, so an interrupted build resumes
        where it stopped rather than starting over.
        """
        loaded = self._load()
        fetched = 0
        for index, symbol in enumerate(symbols, start=1):
            if symbol in loaded:
                continue
            try:
                info = self._fetch(symbol)
            except Exception as exc:
                log.debug("profile fetch failed for %s: %s", symbol, exc)
                continue

            profile = CompanyProfile(
                symbol=symbol,
                description=(info.get("longBusinessSummary") or None),
                industry=(info.get("industry") or None),
                sector=(info.get("sector") or None),
                source="yfinance",
            )
            if profile.is_empty:
                continue
            loaded[symbol] = profile
            fetched += 1
            # Saved as it goes: nine minutes is long enough that losing the lot to an
            # interruption would be genuinely annoying.
            if fetched % 25 == 0:
                self._save()
            if progress is not None:
                progress(index, len(symbols), symbol)

        self._save()
        return fetched

    def all(self) -> dict[str, CompanyProfile]:
        return dict(self._load())

    def coverage(self, symbols: list[str]) -> float:
        """Share of a universe that has a usable profile. Resolution quality tracks this."""
        if not symbols:
            return 0.0
        loaded = self._load()
        known = sum(1 for s in symbols if s in loaded and not loaded[s].is_empty)
        return known / len(symbols)
