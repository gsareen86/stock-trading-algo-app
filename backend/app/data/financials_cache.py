"""On-disk cache for company financials.

Separate from `CachingPriceSource` because the two answer different questions and fail
differently. Prices are a frame and cache to parquet; financials are a nested document and
cache to JSON. More importantly the *policy* differs: a price cache exists to avoid a slow
call, and this one exists to avoid spending an allowance that runs out.

Hence `ignore_age`. When the budget refuses or the provider throttles, a figure from three
months ago is still the last reported figure — quarterly statements do not change between
reports. Serving it labelled is better than serving nothing, and it is exactly the judgement
`CachingPriceSource` already makes.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.domain.financials import (
    CompanyFinancials,
    Metric,
    Shareholding,
)

log = logging.getLogger(__name__)


class FinancialsCache:
    """Stores one document per symbol, keyed by symbol."""

    def __init__(self, cache_dir: str | Path, ttl_days: int = 30, enabled: bool = True) -> None:
        self._dir = Path(cache_dir)
        self._ttl_seconds = ttl_days * 86400
        self._enabled = enabled
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self._dir / f"{symbol.replace('/', '_')}.json"

    def get(self, symbol: str, ignore_age: bool = False) -> CompanyFinancials | None:
        """A cached document, or nothing. ``ignore_age`` serves an expired one, labelled."""
        if not self._enabled:
            return None
        path = self._path(symbol)
        if not path.exists():
            return None

        age = time.time() - path.stat().st_mtime
        expired = age >= self._ttl_seconds
        if expired and not ignore_age:
            return None

        try:
            payload = json.loads(path.read_text("utf-8"))
        except Exception as exc:
            log.debug("unreadable financials cache for %s: %s", symbol, exc)
            return None

        result = _from_dict(symbol, payload)
        if result is None:
            return None
        # Labelled whenever it is not a fresh read, so the age of a figure is never implicit.
        return replace(result, source=f"{result.source}:cache") if expired else result

    def put(self, symbol: str, financials: CompanyFinancials) -> None:
        if not self._enabled:
            return
        try:
            self._path(symbol).write_text(
                json.dumps(_to_dict(financials), indent=2), encoding="utf-8"
            )
        except Exception as exc:
            # Never fatal: a cache that cannot be written is a platform that spends more of
            # its allowance, not a broken one.
            log.debug("financials cache write failed for %s: %s", symbol, exc)


def _to_dict(f: CompanyFinancials) -> dict[str, Any]:
    return {
        "symbol": f.symbol,
        "company_name": f.company_name,
        "industry": f.industry,
        "description": f.description,
        "peers": list(f.peers),
        "source": f.source,
        "fetched_at": f.fetched_at.isoformat() if f.fetched_at else None,
        "metrics": [
            {
                "key": m.key,
                "label": m.label,
                "value": m.value,
                "category": m.category,
                "source": m.source,
                "derived_from": list(m.derived_from),
            }
            for m in f.metrics.values()
        ],
        "shareholding": [
            {
                "as_of": s.as_of.isoformat(),
                "promoter_pct": s.promoter_pct,
                "fii_pct": s.fii_pct,
                "dii_pct": s.dii_pct,
                "government_pct": s.government_pct,
                "public_pct": s.public_pct,
                "pledge_pct": s.pledge_pct,
                "source": s.source,
            }
            for s in f.shareholding
        ],
    }


def _from_dict(symbol: str, payload: dict[str, Any]) -> CompanyFinancials | None:
    try:
        metrics = {
            m["key"]: Metric(
                key=m["key"],
                label=m.get("label", ""),
                value=m.get("value"),
                category=m.get("category", ""),
                source=m.get("source", ""),
                derived_from=tuple(m.get("derived_from") or ()),
            )
            for m in payload.get("metrics") or []
        }
        holdings = tuple(
            Shareholding(
                as_of=date.fromisoformat(s["as_of"]),
                promoter_pct=s.get("promoter_pct"),
                fii_pct=s.get("fii_pct"),
                dii_pct=s.get("dii_pct"),
                government_pct=s.get("government_pct"),
                public_pct=s.get("public_pct"),
                pledge_pct=s.get("pledge_pct"),
                source=s.get("source", ""),
            )
            for s in payload.get("shareholding") or []
        )
        fetched = payload.get("fetched_at")
        return CompanyFinancials(
            symbol=payload.get("symbol") or symbol,
            metrics=metrics,
            shareholding=holdings,
            industry=payload.get("industry"),
            company_name=payload.get("company_name"),
            description=payload.get("description"),
            peers=tuple(payload.get("peers") or ()),
            source=payload.get("source", ""),
            fetched_at=datetime.fromisoformat(fetched) if fetched else None,
        )
    except Exception as exc:
        log.debug("unusable financials cache entry for %s: %s", symbol, exc)
        return None
