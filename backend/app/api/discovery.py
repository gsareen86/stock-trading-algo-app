"""Discovery Funnel API: NSE sector RRG rotation, notable movers, Nifty 750 scans & filters."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.api.deps import get_gateway, get_session_factory, get_settings
from app.api.screening import _universe_source
from app.api.streaming import sse_stream_response
from app.api.verdicts import _fundamentals_source, _price_source
from app.core.clock import IST, now_utc
from app.core.settings import Settings
from app.data.sectors import for_instrument
from app.data.yfinance_quality import build_company_financials_source
from app.discovery.briefing import record_scan_transitions
from app.discovery.movers import find_movers
from app.discovery.quality import QualityFacet, QualityReport
from app.discovery.ranking import CandidateEntry, filter_candidates, rank_candidates
from app.discovery.scanner import (
    DiscoveryScanner,
    ScanInProgressError,
    _verdict_to_dict,
    verdict_from_dict,
)
from app.discovery.scoreboard import build_scoreboard, normalise_horizons
from app.discovery.sectors import BENCHMARK_NIFTY50, BENCHMARK_NIFTY500, compute_sector_rrg
from app.persistence.models import ScanEntry as ScanEntryRow
from app.persistence.models import ScanRun as ScanRunRow
from app.strategies.registry import StrategyRegistry
from app.themes.store import ThemeStore

log = logging.getLogger(__name__)

router = APIRouter(prefix="/discovery", tags=["discovery"])


def _financials_source(request: Request, settings: Settings, session_factory: Any = None):
    existing = getattr(request.app.state, "company_financials_source", None)
    if existing is not None:
        return existing
    sf = session_factory or getattr(request.app.state, "session_factory", None)
    return build_company_financials_source(settings, sf)


def _theme_labeller(session_factory):
    def label(symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
        store = ThemeStore(session_factory)
        standing = store.standing(limit=100)
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for theme in standing:
            tkey = theme["key"]
            for cand in store.candidates(tkey):
                sym = cand.get("symbol")
                if sym in symbols:
                    by_symbol.setdefault(sym, []).append(
                        {
                            "key": tkey,
                            "label": theme.get("label") or tkey,
                            "exposure": cand.get("exposure"),
                        }
                    )
        return by_symbol

    return label


def _build_scanner(
    request: Request,
    settings: Settings,
    session_factory,
    gateway,
) -> DiscoveryScanner:
    existing = getattr(request.app.state, "discovery_scanner", None)
    if existing is not None:
        return existing
    strategies: StrategyRegistry = request.app.state.strategies
    return DiscoveryScanner(
        session_factory=session_factory,
        universe_source=_universe_source(request),
        price_source=_price_source(request, settings),
        strategies=strategies,
        fundamentals_source=_fundamentals_source(request),
        company_financials_source=_financials_source(request, settings, session_factory),
        gateway=gateway,
        theme_labeller=_theme_labeller(session_factory),
    )


def _entry_from_row(row: ScanEntryRow) -> CandidateEntry:
    verdicts = tuple(verdict_from_dict(v) for v in (row.verdicts or []))
    q_raw = row.quality or {}
    facets = tuple(
        QualityFacet(
            key=f["key"],
            label=f["label"],
            status=f["status"],
            value=f.get("value"),
            threshold=f.get("threshold"),
            unit=f.get("unit", ""),
            source=f.get("source"),
            reason=f.get("reason"),
        )
        for f in (q_raw.get("facets") or [])
    )
    quality = QualityReport(
        symbol=row.symbol,
        sector_key=row.sector_key,
        source=q_raw.get("source", ""),
        unavailable_reason=q_raw.get("unavailable_reason"),
        facets=facets,
        summary=dict(q_raw.get("summary") or {}),
    )
    return CandidateEntry(
        symbol=row.symbol,
        name=row.name,
        sector=row.sector,
        sector_key=row.sector_key,
        universe_index=row.universe_index,
        ranked_by=row.ranked_by,
        ranked_conviction=row.ranked_conviction,
        ranked_stance=row.ranked_stance,
        verdicts=verdicts,
        quality=quality,
        themes=tuple(row.themes or []),
    )


def _serialise_entry(entry: CandidateEntry) -> dict[str, Any]:
    return {
        "symbol": entry.symbol,
        "name": entry.name,
        "sector": entry.sector,
        "sector_key": entry.sector_key,
        "universe_index": entry.universe_index,
        "ranked_by": entry.ranked_by,
        "ranked_conviction": entry.ranked_conviction,
        "ranked_stance": entry.ranked_stance,
        "buy_count": entry.buy_stances,
        "verdicts": [_verdict_to_dict(v) for v in entry.verdicts],
        "quality": entry.quality.as_dict() if entry.quality else {},
        "themes": list(entry.themes),
    }


def _serialise_run(run: ScanRunRow) -> dict[str, Any]:
    return {
        "id": run.id,
        "trigger": run.trigger,
        "universe_origin": run.universe_origin,
        "index_name": run.index_name,
        "benchmark": run.benchmark,
        "outcome": run.outcome,
        "considered_count": run.considered_count,
        "eligible_count": run.eligible_count,
        "unevaluable_count": len(run.unevaluable or []),
        "error": run.error,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.get("/sectors")
async def list_sectors(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    benchmark: Annotated[str, Query(pattern=r"^\^(CRSLDX|NSEI)$")] = BENCHMARK_NIFTY500,
) -> dict[str, Any]:
    """Compute (or return cached) NSE sector RRG quadrants against benchmark."""
    import asyncio

    from app.data.sectors import all_sector_indices
    from app.domain.instrument import Instrument

    bench = benchmark.strip().upper()
    price_source = _price_source(request, settings)

    def _compute():
        prefetch_fn = getattr(price_source, "prefetch", None)
        if prefetch_fn is not None:
            targets = [s.as_instrument() for s in all_sector_indices()] + [Instrument(bench)]
            prefetch_fn(targets, interval="1d", lookback_days=820, chunk_size=20)
        return compute_sector_rrg(price_source, benchmark=bench)

    placements = await asyncio.to_thread(_compute)
    sectors = [p.as_dict() for p in placements]
    placed_count = sum(1 for s in sectors if s["quadrant"] != "unplaced")
    source_mode = "live"

    if placed_count == 0:
        with session_factory() as session:
            latest = session.execute(
                select(ScanRunRow)
                .where(ScanRunRow.outcome == "complete")
                .order_by(desc(ScanRunRow.id))
                .limit(1)
            ).scalar_one_or_none()
            if (
                latest
                and latest.sectors_snapshot
                and (latest.benchmark or BENCHMARK_NIFTY500) == bench
            ):
                sectors = list(latest.sectors_snapshot)
                source_mode = "latest_scan"

    return {
        "benchmark": bench,
        "benchmark_options": [
            {"symbol": BENCHMARK_NIFTY500, "label": "Nifty 500"},
            {"symbol": BENCHMARK_NIFTY50, "label": "Nifty 50"},
        ],
        "source_mode": source_mode,
        "measured_at": now_utc().isoformat(),
        "sectors": sectors,
        "count": len(sectors),
    }


@router.get("/movers")
async def sector_movers(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    sector: Annotated[str, Query(min_length=1, max_length=64)],
    benchmark: Annotated[str, Query(pattern=r"^\^(CRSLDX|NSEI)$")] = BENCHMARK_NIFTY500,
) -> dict[str, Any]:
    """Flag notable sector constituents with exact measured thresholds."""
    import asyncio

    from app.domain.instrument import Instrument

    price_source = _price_source(request, settings)
    snap = await asyncio.to_thread(_universe_source(request).snapshot)
    target_sector = sector.strip().lower()
    sector_instruments = [
        inst
        for inst in snap.instruments
        if (mapped := for_instrument(inst)) is not None and mapped.key.lower() == target_sector
    ]
    bench = benchmark.strip().upper()

    def _compute_movers():
        prefetch_fn = getattr(price_source, "prefetch", None)
        if prefetch_fn is not None and sector_instruments:
            prefetch_fn(
                [*sector_instruments, Instrument(bench)],
                interval="1d",
                lookback_days=820,
                chunk_size=75,
            )
        return find_movers(sector.strip(), sector_instruments, price_source, benchmark=bench)

    movers = await asyncio.to_thread(_compute_movers)
    return {
        "sector": sector.strip(),
        "benchmark": bench,
        "checked_instruments": len(sector_instruments),
        "movers": [m.as_dict() for m in movers],
        "count": len(movers),
    }


class RunScanRequest(BaseModel):
    trigger: str = Field(default="requested", max_length=16)
    benchmark: str = Field(default=BENCHMARK_NIFTY500, pattern=r"^\^(CRSLDX|NSEI)$")
    narrate: bool = True
    narrate_head: int = Field(default=10, ge=0, le=50)


@router.post("/scan")
async def run_scan(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    gateway: Annotated[Any, Depends(get_gateway)],
    payload: RunScanRequest | None = None,
) -> dict[str, Any]:
    """Run a full discovery scan synchronously and persist append-only results."""
    req = payload or RunScanRequest()
    scanner = _build_scanner(request, settings, session_factory, gateway)
    try:
        summary = await scanner.run(
            trigger=req.trigger,
            benchmark=req.benchmark,
            narrate=req.narrate,
            narrate_head=req.narrate_head,
        )
    except ScanInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    transitions = record_scan_transitions(
        session_factory, run_id=summary.run_id, price_source=_price_source(request, settings)
    )
    return {**summary.as_dict(), "transitions": transitions}


@router.post("/scan/stream")
async def run_scan_stream(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    gateway: Annotated[Any, Depends(get_gateway)],
    payload: RunScanRequest | None = None,
):
    """Run a discovery scan with live counted-work SSE progress events."""
    req = payload or RunScanRequest()
    scanner = _build_scanner(request, settings, session_factory, gateway)
    price_source = _price_source(request, settings)

    async def drive(emit):
        summary = await scanner.run(
            trigger=req.trigger,
            benchmark=req.benchmark,
            narrate=req.narrate,
            narrate_head=req.narrate_head,
            on_progress=emit,
        )
        transitions = record_scan_transitions(
            session_factory, run_id=summary.run_id, price_source=price_source
        )
        return {**summary.as_dict(), "transitions": transitions}

    return sse_stream_response(drive)


@router.get("/runs")
async def list_runs(
    session_factory: Annotated[Any, Depends(get_session_factory)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    with session_factory() as session:
        rows = (
            session.execute(select(ScanRunRow).order_by(desc(ScanRunRow.id)).limit(limit))
            .scalars()
            .all()
        )
    return {"runs": [_serialise_run(r) for r in rows], "count": len(rows)}


def _load_filtered_run(
    session_factory,
    run_id: int | None,
    *,
    sector: str | None,
    strategy_id: str | None,
    stance: str | None,
    min_buy_count: int | None,
    roe_min: float | None,
    sales_yoy_min: float | None,
    low_debt: bool,
    theme_backed: bool,
    limit: int,
) -> dict[str, Any]:
    with session_factory() as session:
        if run_id is None:
            run = session.execute(
                select(ScanRunRow)
                .where(ScanRunRow.outcome == "complete")
                .order_by(desc(ScanRunRow.id))
                .limit(1)
            ).scalar_one_or_none()
        else:
            run = session.get(ScanRunRow, run_id)
        if run is None:
            return {
                "run": None,
                "sectors": [],
                "candidates": [],
                "total_candidates": 0,
                "filtered_candidates": 0,
                "unevaluable": [],
                "rank_policy": "Ordered by highest single-strategy conviction (unblended)",
            }
        rows = (
            session.execute(
                select(ScanEntryRow).where(ScanEntryRow.run_id == run.id).order_by(ScanEntryRow.id)
            )
            .scalars()
            .all()
        )

    all_entries = rank_candidates([_entry_from_row(r) for r in rows])
    filtered = filter_candidates(
        all_entries,
        sector_key=sector,
        strategy_id=strategy_id,
        stance=stance,
        min_buy_count=min_buy_count,
        roe_min=roe_min,
        sales_yoy_min=sales_yoy_min,
        low_debt=low_debt,
        theme_backed_only=theme_backed,
    )
    return {
        "run": _serialise_run(run),
        "sectors": list(run.sectors_snapshot or []),
        "candidates": [_serialise_entry(e) for e in filtered[:limit]],
        "total_candidates": len(all_entries),
        "filtered_candidates": len(filtered),
        "unevaluable": list(run.unevaluable or [])[:100],
        "rank_policy": (
            f"Ordered by {strategy_id} conviction (unblended)"
            if strategy_id
            else "Ordered by single highest-conviction named strategy (unblended)"
        ),
    }


@router.get("/runs/latest")
async def latest_run(
    session_factory: Annotated[Any, Depends(get_session_factory)],
    sector: str | None = None,
    strategy_id: str | None = None,
    stance: str | None = None,
    min_buy_count: Annotated[int | None, Query(ge=1, le=4)] = None,
    roe_min: float | None = None,
    sales_yoy_min: float | None = None,
    low_debt: bool = False,
    theme_backed: bool = False,
    limit: Annotated[int, Query(ge=1, le=750)] = 200,
) -> dict[str, Any]:
    return _load_filtered_run(
        session_factory,
        None,
        sector=sector,
        strategy_id=strategy_id,
        stance=stance,
        min_buy_count=min_buy_count,
        roe_min=roe_min,
        sales_yoy_min=sales_yoy_min,
        low_debt=low_debt,
        theme_backed=theme_backed,
        limit=limit,
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    session_factory: Annotated[Any, Depends(get_session_factory)],
    sector: str | None = None,
    strategy_id: str | None = None,
    stance: str | None = None,
    min_buy_count: Annotated[int | None, Query(ge=1, le=4)] = None,
    roe_min: float | None = None,
    sales_yoy_min: float | None = None,
    low_debt: bool = False,
    theme_backed: bool = False,
    limit: Annotated[int, Query(ge=1, le=750)] = 200,
) -> dict[str, Any]:
    payload = _load_filtered_run(
        session_factory,
        run_id,
        sector=sector,
        strategy_id=strategy_id,
        stance=stance,
        min_buy_count=min_buy_count,
        roe_min=roe_min,
        sales_yoy_min=sales_yoy_min,
        low_debt=low_debt,
        theme_backed=theme_backed,
        limit=limit,
    )
    if payload["run"] is None:
        raise HTTPException(status_code=404, detail=f"no scan run with id {run_id}")
    return payload


#: One computed scoreboard per (latest completed scan, IST day, parameters). Forward returns only
#: change when a new session closes or a new scan lands, and the computation reads every scanned
#: name's history — recomputing it on each page view would be the slow path for no new answer.
_SCOREBOARD_MEMO: dict[tuple, dict[str, Any]] = {}
_SCOREBOARD_MEMO_LIMIT = 16


@router.get("/scoreboard")
async def scoreboard(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    signals: Annotated[str, Query(pattern="^(new|all)$")] = "new",
    strategy_id: str | None = None,
    horizons: Annotated[str | None, Query(max_length=40)] = None,
    max_runs: Annotated[int, Query(ge=1, le=520)] = 104,
    refresh: bool = False,
) -> dict[str, Any]:
    """Forward returns of every published verdict, per strategy — did the signals work?"""
    try:
        parsed = normalise_horizons(
            int(h) for h in (horizons.split(",") if horizons else []) if h.strip()
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="horizons must be comma-separated integers"
        ) from exc

    with session_factory() as session:
        latest_id = session.execute(
            select(ScanRunRow.id)
            .where(ScanRunRow.outcome == "complete")
            .order_by(desc(ScanRunRow.id))
            .limit(1)
        ).scalar_one_or_none()

    key = (latest_id, now_utc().astimezone(IST).date(), signals, strategy_id, parsed, max_runs)
    if not refresh and key in _SCOREBOARD_MEMO:
        return _SCOREBOARD_MEMO[key]

    price_source = _price_source(request, settings)
    result = await asyncio.to_thread(
        build_scoreboard,
        session_factory,
        price_source,
        horizons=parsed,
        signals=signals,  # type: ignore[arg-type]
        strategy_id=strategy_id,
        max_runs=max_runs,
    )
    if len(_SCOREBOARD_MEMO) >= _SCOREBOARD_MEMO_LIMIT:
        _SCOREBOARD_MEMO.clear()
    _SCOREBOARD_MEMO[key] = result
    return result
