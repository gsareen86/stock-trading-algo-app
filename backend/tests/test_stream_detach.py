"""A streamed run belongs to the server, not to whoever is watching it.

Regression: closing the browser pane mid-scan cancelled a 26-minute Nifty 750 scan in its
final narration step, discarded everything it had computed, and left its row `running` —
which refused every later scan until the server restarted.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from pathlib import Path

import pandas as pd

from app.api import streaming
from app.api.streaming import sse_stream_response
from app.data.fake import StaticPriceSource
from app.data.fundamentals import StaticFundamentalsSource
from app.data.protocols import UniverseSnapshot
from app.data.yfinance_quality import YFinanceQualitySource
from app.discovery.scanner import DiscoveryScanner
from app.domain.instrument import Instrument
from app.persistence.models import ScanRun as ScanRunRow
from app.persistence.session import make_engine, make_session_factory
from app.screening.screener import ScreenCriteria
from app.strategies.registry import StrategyRegistry
from tests.conftest import Settings


async def test_run_finishes_after_viewer_disconnects() -> None:
    release = asyncio.Event()
    finished: list[str] = []

    async def runner(emit):
        emit("work", "started", 0, 1)
        await release.wait()
        finished.append("persisted")
        return {"ok": True}

    response = sse_stream_response(runner)
    events = response.body_iterator
    first = await events.__anext__()
    assert "started" in first

    # The viewer goes away while the run is still working.
    await events.aclose()

    release.set()
    for _ in range(50):
        if finished:
            break
        await asyncio.sleep(0.01)

    assert finished == ["persisted"], "the run was cancelled when its viewer left"
    await asyncio.sleep(0)
    assert not getattr(streaming, "_DETACHED", set()), "a finished run should not stay referenced"


async def test_run_that_finishes_while_watched_is_not_detached() -> None:
    async def runner(emit):
        emit("work", "only step", 1, 1)
        return {"ok": True}

    response = sse_stream_response(runner)
    body = [chunk async for chunk in response.body_iterator]

    assert any("event: complete" in chunk for chunk in body)
    assert not getattr(streaming, "_DETACHED", set())


def _df(closes: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range(end="2026-11-13", periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


class _BlockingPrices(StaticPriceSource):
    """Holds the scan inside its evaluation step until the test lets it go."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        super().__init__(frames)
        self.entered = threading.Event()
        self.release = threading.Event()

    def history(self, *args, **kwargs):
        self.entered.set()
        self.release.wait(timeout=10)
        return super().history(*args, **kwargs)


async def test_cancelled_scan_is_recorded_as_interrupted(migrated_url: str, tmp_path: Path) -> None:
    settings = Settings(database_url=migrated_url, llm_cache_dir=str(tmp_path), _env_file=None)
    sf = make_session_factory(make_engine(settings))
    snapshot = UniverseSnapshot(
        instruments=(Instrument("TCS", "Tata Consultancy Services", "Information Technology"),),
        origin="live",
        index_name="TEST",
    )

    class Universe:
        def snapshot(self):
            return snapshot

    prices = _BlockingPrices({"TCS": _df([100.0 * (1.002**i) for i in range(420)])})
    scanner = DiscoveryScanner(
        session_factory=sf,
        universe_source=Universe(),
        price_source=prices,
        strategies=StrategyRegistry.discover(),
        fundamentals_source=StaticFundamentalsSource({}),
        company_financials_source=YFinanceQualitySource(fetcher=lambda t: {}),
    )
    criteria = ScreenCriteria(min_turnover_inr=0, min_price_inr=0, exclude_surveillance=False)

    task = asyncio.create_task(scanner.run(criteria=criteria, narrate=False))
    try:
        assert await asyncio.to_thread(prices.entered.wait, 10)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        prices.release.set()

    with sf() as session:
        rows = session.query(ScanRunRow).all()
    assert [r.outcome for r in rows] == ["interrupted"]
    assert rows[0].finished_at is not None
