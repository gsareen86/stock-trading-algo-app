"""LLM accounting endpoints.

These exist so cost and failure modes are answerable **inside the app**, with no Langfuse
account configured. Langfuse remains the place for trace depth — nested spans, prompt and
response payloads. This is the ledger.

Neither endpoint returns prompt or completion text. A trading platform's prompts carry
position and thesis detail, and an accounting endpoint has no business exposing it.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_budget, get_session_factory
from app.llm import usage as usage_module
from app.llm.budget import DailyBudget

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/usage")
async def llm_usage(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    budget: Annotated[DailyBudget, Depends(get_budget)],
    days: Annotated[
        int,
        Query(
            ge=usage_module.MIN_DAYS,
            le=usage_module.MAX_DAYS,
            description="Number of IST days to report, most recent first",
        ),
    ] = usage_module.DEFAULT_DAYS,
) -> dict[str, Any]:
    report = usage_module.collect_usage(session_factory, days=days).as_dict()
    report["budget"] = {
        "cap_usd": budget.cap_usd,
        "spent_today_usd": round(budget.spent_today(), 6),
        "remaining_usd": (
            None if budget.remaining() is None else round(budget.remaining() or 0.0, 6)
        ),
        "exhausted": budget.is_exhausted(),
    }
    return report


@router.get("/calls")
async def llm_calls(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    calls = usage_module.recent_calls(session_factory, limit=limit)
    return {"calls": calls, "count": len(calls)}
