"""Parquet caching, as a layer over any price source.

Interleaving TTL logic with the download makes the fetch untestable
without a filesystem and put cache policy in the same function as the HTTP call. Here the
cache implements the same `PriceSource` protocol and wraps another one, so either can be
tested — and used — without the other.

**A stale entry beats no data.** If the provider is down and a two-day-old daily file exists,
returning it labelled `cache` is more useful than an empty frame: a strategy can decide
staleness is unacceptable, but it can decide nothing at all from nothing. This is a
deliberate: discarding expired entries regardless of whether
a refetch was even possible.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

from app.data.protocols import PriceSource
from app.domain.instrument import Instrument
from app.domain.prices import (
    Interval,
    PriceSeries,
    PriceSeriesError,
    build_series,
    empty_series,
)

log = logging.getLogger(__name__)

#: Daily bars settle after the close; weekly after Friday. Refreshing more often than this
#: buys nothing and costs a provider call per instrument per scan.
DEFAULT_TTL_SECONDS: dict[str, int] = {
    "1d": 6 * 60 * 60,
    "1wk": 24 * 60 * 60,
}

#: Avoid hammering Yahoo repeatedly within one scan for a delisted or missing ticker.
NEGATIVE_CACHE_TTL_SECONDS = 15 * 60


class CachingPriceSource:
    """Wraps a :class:`app.data.protocols.PriceSource` with an on-disk parquet cache."""

    def __init__(
        self,
        inner: PriceSource,
        cache_dir: str | Path,
        ttl_seconds: dict[str, int] | None = None,
        enabled: bool = True,
    ) -> None:
        self._inner = inner
        self._dir = Path(cache_dir)
        self._ttl = ttl_seconds or DEFAULT_TTL_SECONDS
        self._enabled = enabled
        self._empty_until: dict[tuple[str, str], float] = {}
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, instrument: Instrument, interval: Interval) -> Path:
        return self._dir / f"{instrument.symbol.replace('.', '_')}_{interval}.parquet"

    def _age_seconds(self, path: Path) -> float | None:
        if not path.exists():
            return None
        return time.time() - path.stat().st_mtime

    def _read(self, path: Path, instrument: Instrument, interval: Interval) -> PriceSeries | None:
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:
            log.debug("unreadable cache entry %s: %s", path.name, exc)
            return None
        try:
            return build_series(instrument, interval, frame, source="cache")
        except PriceSeriesError as exc:
            log.debug("cache entry for %s failed validation: %s", instrument.symbol, exc)
            return None

    def _write(self, path: Path, series: PriceSeries) -> None:
        try:
            series.frame.to_parquet(path)
        except Exception as exc:
            # Never fatal: a cache that cannot be written is a slow platform, not a broken one.
            log.debug("cache write failed for %s: %s", series.instrument.symbol, exc)

    def _is_fresh(self, instrument: Instrument, interval: Interval) -> bool:
        path = self._path(instrument, interval)
        age = self._age_seconds(path)
        ttl = self._ttl.get(interval, 6 * 60 * 60)
        return age is not None and age < ttl

    def prefetch(
        self,
        instruments: list[Instrument] | tuple[Instrument, ...],
        *,
        interval: Interval = "1d",
        lookback_days: int = 820,
        chunk_size: int = 75,
        on_progress=None,
    ) -> int:
        """Warm the parquet cache in multi-ticker batches for any uncached instruments."""
        if not self._enabled or not instruments:
            return 0
        batch_fn = getattr(self._inner, "download_batch", None)
        if batch_fn is None:
            return 0

        deduped: list[Instrument] = []
        seen: set[str] = set()
        for inst in instruments:
            if inst.symbol not in seen:
                seen.add(inst.symbol)
                deduped.append(inst)

        now = time.time()
        missing = [
            inst
            for inst in deduped
            if not self._is_fresh(inst, interval)
            and self._empty_until.get((inst.symbol, interval), 0.0) <= now
        ]
        total = len(deduped)
        done = total - len(missing)
        if on_progress is not None:
            on_progress(done, total)
        if not missing:
            return 0

        written = 0
        for start in range(0, len(missing), max(1, chunk_size)):
            chunk = missing[start : start + chunk_size]
            batch = batch_fn(chunk, interval=interval, lookback_days=lookback_days)
            ts = time.time()
            for inst in chunk:
                series = batch.get(inst.symbol)
                if series is not None and not series.is_empty:
                    self._write(self._path(inst, interval), series)
                    self._empty_until.pop((inst.symbol, interval), None)
                    written += 1
                else:
                    self._empty_until[(inst.symbol, interval)] = ts + NEGATIVE_CACHE_TTL_SECONDS
            done = min(total, done + len(chunk))
            if on_progress is not None:
                on_progress(done, total)
        return written

    def history(
        self,
        instrument: Instrument,
        *,
        interval: Interval = "1d",
        lookback_days: int = 400,
    ) -> PriceSeries:
        if not self._enabled:
            return self._inner.history(instrument, interval=interval, lookback_days=lookback_days)

        path = self._path(instrument, interval)
        age = self._age_seconds(path)
        ttl = self._ttl.get(interval, 6 * 60 * 60)

        if age is not None and age < ttl:
            cached = self._read(path, instrument, interval)
            if cached is not None and not cached.is_empty:
                needs_longer = interval == "1d" and lookback_days > 900 and len(cached.frame) < 650
                if not needs_longer:
                    return cached

        if self._empty_until.get((instrument.symbol, interval), 0.0) > time.time():
            if age is not None:
                stale = self._read(path, instrument, interval)
                if stale is not None and not stale.is_empty:
                    return stale
            return empty_series(instrument, interval)

        fresh = self._inner.history(instrument, interval=interval, lookback_days=lookback_days)

        if not fresh.is_empty:
            self._write(path, fresh)
            self._empty_until.pop((instrument.symbol, interval), None)
            return fresh

        self._empty_until[(instrument.symbol, interval)] = time.time() + NEGATIVE_CACHE_TTL_SECONDS

        # The fetch produced nothing. Fall back to whatever is on disk, however old — an
        # expired bar is information; an empty frame is not.
        if age is not None:
            stale = self._read(path, instrument, interval)
            if stale is not None and not stale.is_empty:
                log.info(
                    "serving stale cache for %s (%s, %.0fh old) — provider returned nothing",
                    instrument.symbol,
                    interval,
                    age / 3600,
                )
                return stale

        return fresh
