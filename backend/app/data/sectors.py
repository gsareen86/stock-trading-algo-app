"""Resolving an instrument's sector to an index.

Two vocabularies describe the same thing — the NSE constituent CSV's `Industry` column and
yfinance's `sector` string — so matching is by substring against a data file holding both.

**An unrecognised industry resolves to nothing, never to a guess.** Attributing a stock to the
wrong sector index would make its relative-strength criterion confidently wrong, which is worse
than recording that the sector is unknown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.domain.instrument import Instrument

RESOURCES = Path(__file__).parent / "resources"
SECTORS_FILE = RESOURCES / "sector_indices.json"


@dataclass(frozen=True, slots=True)
class SectorIndex:
    key: str
    ticker: str

    def as_instrument(self) -> Instrument:
        # Index tickers already carry their provider form (^CNXIT); Instrument requires
        # upper-case, which they are.
        return Instrument(self.ticker)


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, str], tuple[tuple[str, str], ...]]:
    payload = json.loads(SECTORS_FILE.read_text("utf-8"))
    indices: dict[str, str] = payload.get("indices", {})
    terms: dict[str, str] = payload.get("industry_terms", {})
    # Longest first so "financial services" wins over "financial", and "information
    # technology" over "it" — a short term matching inside a longer one is the classic way
    # this kind of map goes quietly wrong.
    ordered = tuple(sorted(terms.items(), key=lambda kv: len(kv[0]), reverse=True))
    return indices, ordered


def all_sector_indices() -> tuple[SectorIndex, ...]:
    indices, _ = _tables()
    return tuple(SectorIndex(key=k, ticker=v) for k, v in sorted(indices.items()))


def resolve(industry: str | None) -> SectorIndex | None:
    """Map an industry description to its sector index, or None when unrecognised."""
    if not industry:
        return None
    indices, ordered = _tables()
    needle = industry.strip().lower()
    for term, key in ordered:
        if term in needle:
            ticker = indices.get(key)
            return SectorIndex(key=key, ticker=ticker) if ticker else None
    return None


def for_instrument(instrument: Instrument) -> SectorIndex | None:
    return resolve(instrument.sector)
