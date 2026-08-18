"""Running a replay.

The response always carries what the run could not account for. That is deliberate: a backtest
number gets copied into a conversation, and the caveat travels with it or it does not travel.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator

from app.api.deps import get_settings
from app.backtest.runner import MAX_SESSIONS, MAX_SYMBOLS, BacktestConfig, run
from app.core.settings import Settings
from app.data.calendar import NseCalendar

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=MAX_SYMBOLS)
    start: date
    end: date | None = None
    step_sessions: int = Field(default=5, ge=1, le=60)
    max_hold_sessions: int = Field(default=40, ge=1, le=250)
    position_inr: float = Field(default=1_00_000.0, gt=0)

    @model_validator(mode="after")
    def _check_window(self) -> BacktestRequest:
        end = self.end or date.today()
        if end <= self.start:
            raise ValueError("end must be after start")
        if (end - self.start) > timedelta(days=MAX_SESSIONS * 2):
            raise ValueError("window is longer than the replay bound allows")
        return self


@router.post("/run")
async def run_backtest(
    request: Request,
    payload: BacktestRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    from app.api.verdicts import _fundamentals_source, _price_source

    config = BacktestConfig(
        start=payload.start,
        end=payload.end or date.today(),
        symbols=tuple(s.strip().upper() for s in payload.symbols),
        step_sessions=payload.step_sessions,
        max_hold_sessions=payload.max_hold_sessions,
        position_inr=payload.position_inr,
    )

    report = run(
        config,
        _price_source(request, settings),
        request.app.state.strategies,
        NseCalendar(),
        fundamentals_source=_fundamentals_source(request),
    )
    return report.as_dict()
