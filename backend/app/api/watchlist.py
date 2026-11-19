"""Watchlist CRUD + live scan pivot/drift enrichment."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.api.deps import get_session_factory, get_settings
from app.api.screening import _universe_source
from app.api.verdicts import _price_source
from app.core.clock import now_utc
from app.core.settings import Settings
from app.domain.instrument import Instrument
from app.persistence.models import ScanEntry, ScanRun, WatchlistItem

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistCreateRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    book_intent: str = Field(default="swing", pattern=r"^(swing|longterm)$")
    target_strategy_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


class WatchlistUpdateRequest(BaseModel):
    book_intent: str | None = Field(default=None, pattern=r"^(swing|longterm)$")
    target_strategy_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


def _current_price(symbol: str, request: Request, settings: Settings) -> float | None:
    try:
        series = _price_source(request, settings).history(
            Instrument(symbol), interval="1d", lookback_days=10
        )
        if not series.is_empty:
            return round(float(series.frame["close"].iloc[-1]), 2)
    except Exception:
        pass
    return None


@router.get("")
async def list_watchlist(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    book_intent: Annotated[str | None, Query(pattern=r"^(swing|longterm)$")] = None,
) -> dict[str, Any]:
    with session_factory() as session:
        stmt = select(WatchlistItem).order_by(desc(WatchlistItem.updated_at))
        if book_intent:
            stmt = stmt.where(WatchlistItem.book_intent == book_intent)
        rows = session.execute(stmt).scalars().all()

        latest_run = session.execute(
            select(ScanRun)
            .where(ScanRun.outcome == "complete")
            .order_by(desc(ScanRun.id))
            .limit(1)
        ).scalar_one_or_none()
        entries = (
            session.execute(
                select(ScanEntry).where(
                    ScanEntry.run_id == latest_run.id,
                    ScanEntry.symbol.in_([r.symbol for r in rows]),
                )
            )
            .scalars()
            .all()
            if latest_run is not None and rows
            else []
        )
    entry_map = {e.symbol: e for e in entries}

    items: list[dict[str, Any]] = []
    for row in rows:
        entry = entry_map.get(row.symbol)
        last_px = _current_price(row.symbol, request, settings)
        verdicts = list(entry.verdicts or []) if entry else []
        current_stances = {
            v["strategy_id"]: v["stance"] for v in verdicts if "strategy_id" in v and "stance" in v
        }
        prev_stances = dict(row.last_known_stances or {})
        flipped_strategies = [
            sid
            for sid, st in current_stances.items()
            if prev_stances.get(sid) == "WATCH" and st == "BUY"
        ]

        selected_verdict = None
        if verdicts:
            if row.target_strategy_id:
                selected_verdict = next(
                    (v for v in verdicts if v.get("strategy_id") == row.target_strategy_id),
                    None,
                )
            if selected_verdict is None:
                selected_verdict = next(
                    (v for v in verdicts if v.get("plan") is not None),
                    verdicts[0],
                )

        plan = selected_verdict.get("plan") if selected_verdict else None
        distance_to_entry_pct: float | None = None
        if plan and last_px and last_px > 0 and plan.get("entry"):
            distance_to_entry_pct = round((plan["entry"] - last_px) / last_px * 100.0, 2)

        items.append(
            {
                "id": row.id,
                "symbol": row.symbol,
                "name": row.name or (entry.name if entry else row.symbol),
                "sector": row.sector or (entry.sector if entry else None),
                "sector_key": entry.sector_key if entry else None,
                "book_intent": row.book_intent,
                "target_strategy_id": row.target_strategy_id,
                "notes": row.notes,
                "added_price": row.added_price,
                "last_price": last_px,
                "distance_to_entry_pct": distance_to_entry_pct,
                "last_known_stances": prev_stances,
                "current_stances": current_stances,
                "flipped_buy": bool(flipped_strategies),
                "flipped_strategies": flipped_strategies,
                "plan": plan,
                "verdicts": verdicts,
                "themes": list(entry.themes or []) if entry else [],
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
        )

    return {"items": items, "count": len(items)}


@router.post("", status_code=201)
async def add_watchlist_item(
    payload: WatchlistCreateRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    sym = payload.symbol.strip().upper()
    name = sym
    sector = None
    try:
        snap = _universe_source(request).snapshot()
        match = next((i for i in snap.instruments if i.symbol == sym), None)
        if match:
            name = match.name or sym
            sector = match.sector
    except Exception:
        pass

    last_px = _current_price(sym, request, settings)

    with session_factory() as session:
        latest_run = session.execute(
            select(ScanRun)
            .where(ScanRun.outcome == "complete")
            .order_by(desc(ScanRun.id))
            .limit(1)
        ).scalar_one_or_none()
        stances: dict[str, str] = {}
        if latest_run is not None:
            entry = session.execute(
                select(ScanEntry).where(
                    ScanEntry.run_id == latest_run.id, ScanEntry.symbol == sym
                )
            ).scalar_one_or_none()
            if entry:
                name = entry.name or name
                sector = entry.sector or sector
                stances = {
                    v["strategy_id"]: v["stance"]
                    for v in (entry.verdicts or [])
                    if "strategy_id" in v and "stance" in v
                }

        existing = session.execute(
            select(WatchlistItem).where(WatchlistItem.symbol == sym)
        ).scalar_one_or_none()
        stamp = now_utc()
        if existing is not None:
            existing.book_intent = payload.book_intent
            if payload.target_strategy_id is not None:
                existing.target_strategy_id = payload.target_strategy_id
            if payload.notes is not None:
                existing.notes = payload.notes
            existing.updated_at = stamp
            row = existing
        else:
            row = WatchlistItem(
                symbol=sym,
                name=name,
                sector=sector,
                book_intent=payload.book_intent,
                target_strategy_id=payload.target_strategy_id,
                notes=payload.notes,
                added_price=last_px,
                last_known_stances=stances,
                created_at=stamp,
                updated_at=stamp,
            )
            session.add(row)
        session.commit()
        session.refresh(row)

    return {
        "id": row.id,
        "symbol": row.symbol,
        "name": row.name,
        "sector": row.sector,
        "book_intent": row.book_intent,
        "target_strategy_id": row.target_strategy_id,
        "notes": row.notes,
        "added_price": row.added_price,
        "last_known_stances": row.last_known_stances,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.patch("/{symbol}")
async def update_watchlist_item(
    symbol: str,
    payload: WatchlistUpdateRequest,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    sym = symbol.strip().upper()
    with session_factory() as session:
        row = session.execute(
            select(WatchlistItem).where(WatchlistItem.symbol == sym)
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"{sym} is not on the watchlist")
        if payload.book_intent is not None:
            row.book_intent = payload.book_intent
        if payload.target_strategy_id is not None:
            row.target_strategy_id = payload.target_strategy_id or None
        if payload.notes is not None:
            row.notes = payload.notes
        row.updated_at = now_utc()
        session.commit()
        session.refresh(row)

    return {
        "id": row.id,
        "symbol": row.symbol,
        "book_intent": row.book_intent,
        "target_strategy_id": row.target_strategy_id,
        "notes": row.notes,
        "updated_at": row.updated_at.isoformat(),
    }


@router.delete("/{symbol}")
async def delete_watchlist_item(
    symbol: str,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    sym = symbol.strip().upper()
    with session_factory() as session:
        row = session.execute(
            select(WatchlistItem).where(WatchlistItem.symbol == sym)
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"{sym} is not on the watchlist")
        session.delete(row)
        session.commit()
    return {"symbol": sym, "deleted": True}
