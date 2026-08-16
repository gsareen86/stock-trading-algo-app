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

from app.api.deps import get_budget, get_session_factory, get_settings
from app.core.money import usd_to_inr
from app.core.settings import Settings
from app.llm import usage as usage_module
from app.llm.budget import DailyBudget

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/usage")
async def llm_usage(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    budget: Annotated[DailyBudget, Depends(get_budget)],
    settings: Annotated[Settings, Depends(get_settings)],
    days: Annotated[
        int,
        Query(
            ge=usage_module.MIN_DAYS,
            le=usage_module.MAX_DAYS,
            description="Number of IST days to report, most recent first",
        ),
    ] = usage_module.DEFAULT_DAYS,
) -> dict[str, Any]:
    # This is the currency boundary: everything below stores and sums the dollars the vendor
    # actually bills, everything above reads rupees. See `app.core.money`.
    rate = settings.usd_inr_rate
    report = usage_module.collect_usage(session_factory, days=days).as_dict(rate)
    report["usd_inr_rate"] = rate
    report["budget"] = {
        "cap_inr": settings.llm_daily_budget_inr,
        "spent_today_inr": usd_to_inr(budget.spent_today(), rate),
        "remaining_inr": usd_to_inr(budget.remaining(), rate),
        "exhausted": budget.is_exhausted(),
    }
    return report


@router.get("/calls")
async def llm_calls(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    calls = usage_module.recent_calls(session_factory, limit=limit, rate=settings.usd_inr_rate)
    return {
        "calls": calls,
        "count": len(calls),
        "usd_inr_rate": settings.usd_inr_rate,
    }
