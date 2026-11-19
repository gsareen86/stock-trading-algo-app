"""Running a replay.

The response always carries what the run could not account for. That is deliberate: a backtest
number gets copied into a conversation, and the caveat travels with it or it does not travel.

A request is bounded more tightly than the runner itself: a replay that takes an hour belongs
on the command line (``python -m app.backtest.cli``), not in an HTTP request a browser will
abandon.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_settings
from app.backtest.runner import (
    DEFAULT_ROUND_TRIP_COST_PCT,
    DEFAULT_SLIPPAGE_BPS,
    BacktestConfig,
    run,
)
from app.core.settings import Settings
from app.data.calendar import NseCalendar

log = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])

#: Interactive bounds — see the module docstring.
API_MAX_SYMBOLS = 100
API_MAX_WINDOW_DAYS = 3 * 366


class BacktestRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=API_MAX_SYMBOLS)
    start: date
    end: date | None = None
    step_sessions: int = Field(default=5, ge=1, le=60)
    max_hold_sessions: int = Field(default=120, ge=1, le=500)
    position_inr: float = Field(default=1_00_000.0, gt=0)
    entry_mode: Literal["plan", "next_open"] = "plan"
    order_valid_sessions: int = Field(default=10, ge=1, le=60)
    max_chase_pct: float = Field(default=5.0, ge=0, le=50)
    round_trip_cost_pct: float = Field(default=DEFAULT_ROUND_TRIP_COST_PCT, ge=0, le=5)
    slippage_bps: float = Field(default=DEFAULT_SLIPPAGE_BPS, ge=0, le=200)
    benchmark: str = Field(default="^CRSLDX", max_length=20)

    @model_validator(mode="after")
    def _check_window(self) -> BacktestRequest:
        end = self.end or date.today()
        if end <= self.start:
            raise ValueError("end must be after start")
        if (end - self.start) > timedelta(days=API_MAX_WINDOW_DAYS):
            raise ValueError(
                "window is longer than an interactive replay allows; use the command line"
            )
        return self


def _sectors_for(request: Request, symbols: tuple[str, ...]) -> dict[str, str]:
    """Each symbol's sector from the universe list, so sector-aware strategies can place it."""
    from app.api.screening import _universe_source
    from app.data.universe import bundled_sectors

    wanted = set(symbols)
    known = {s: sector for s, sector in bundled_sectors().items() if s in wanted}
    try:
        snapshot = _universe_source(request).snapshot()
    except Exception as exc:  # the universe is a convenience here, never a reason to fail
        log.warning("universe unavailable for backtest sectors: %s", exc)
        return known
    live = {i.symbol: i.sector for i in snapshot.instruments if i.symbol in wanted and i.sector}
    return {**known, **live}


@router.post("/run")
async def run_backtest(
    request: Request,
    payload: BacktestRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    from app.api.verdicts import _fundamentals_source, _price_source

    symbols = tuple(dict.fromkeys(s.strip().upper() for s in payload.symbols))
    sectors = await asyncio.to_thread(_sectors_for, request, symbols)
    config = BacktestConfig(
        start=payload.start,
        end=payload.end or date.today(),
        symbols=symbols,
        step_sessions=payload.step_sessions,
        max_hold_sessions=payload.max_hold_sessions,
        position_inr=payload.position_inr,
        entry_mode=payload.entry_mode,
        order_valid_sessions=payload.order_valid_sessions,
        max_chase_pct=payload.max_chase_pct,
        round_trip_cost_pct=payload.round_trip_cost_pct,
        slippage_bps=payload.slippage_bps,
        benchmark=payload.benchmark.strip().upper(),
        sectors=sectors,
    )

    report = await asyncio.to_thread(
        run,
        config,
        _price_source(request, settings),
        request.app.state.strategies,
        NseCalendar(),
        fundamentals_source=_fundamentals_source(request),
    )
    return report.as_dict()
