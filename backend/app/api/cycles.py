"""Running a cycle, and publishing the agent card.

`POST /cycles/run` is the orchestrated path: regime is read once, research gathers context, the
four strategies fan out in parallel and narration is optional. `POST /verdicts/evaluate`
remains the direct path for evaluating a symbol without any of that — a cycle is not the only
way to get a verdict, and making it so would put a model in front of a deterministic answer.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.card import CARD_PATH, build_card
from app.agents.graph import build_graph, run_cycle
from app.agents.toolbelt import Toolbelt
from app.api.deps import get_gateway, get_session_factory, get_settings
from app.api.screening import _universe_source
from app.api.verdicts import _fundamentals_source, _price_source, _serialise
from app.books.ledger import Ledger
from app.core.clock import now_utc
from app.core.settings import Settings
from app.data.surveillance import load as load_surveillance
from app.domain.instrument import Instrument
from app.domain.position import Book
from app.llm.types import LLMGateway
from app.persistence.verdicts import VerdictRepository
from app.risk.rules import RiskLimits
from app.screening.screener import ScreenCriteria, Screener
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext

router = APIRouter(tags=["cycles"])


class RunCycleRequest(BaseModel):
    #: Omit to screen the universe instead. Supplying symbols asks about *those* names and
    #: skips screening entirely — including for a name that would not have survived one.
    symbols: list[str] | None = Field(default=None, max_length=25)
    narrate: bool = False
    persist: bool = False
    #: Off by default: research calls a model and external servers, and a cycle is useful
    #: without it. The verdicts are identical either way.
    research: bool = True
    #: Cap on screened names, applied in universe order. Four strategies over a 500-name
    #: universe is two thousand evaluations; a default keeps an unqualified request survivable.
    screen_limit: int = Field(default=10, ge=1, le=100)
    #: Which book risk sizes against. Risk decides whether to *act*; it never alters a verdict.
    book: Book = Book.SWING
    #: Skip the risk pass entirely — verdicts are complete without it.
    assess_risk: bool = True


@router.post("/cycles/run")
async def run(
    request: Request,
    payload: RunCycleRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    gateway: Annotated[LLMGateway, Depends(get_gateway)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    strategies: StrategyRegistry = request.app.state.strategies
    tools: ToolRegistry = request.app.state.tools

    price_source = _price_source(request, settings)
    strategy_context = StrategyContext(
        price_source=price_source,
        fundamentals_source=_fundamentals_source(request),
    )

    toolbelt = Toolbelt(
        registry=tools,
        context=ToolContext(price_source=price_source),
        mcp_servers=dict(settings.mcp_server) if payload.research else {},
    )
    if payload.research:
        await toolbelt.connect()

    # A screen only runs when the caller did not name symbols. Naming them asks about those
    # names, which is a different question from "what is worth looking at today".
    screening = not payload.symbols
    try:
        compiled = build_graph(
            registry=strategies,
            strategy_context=strategy_context,
            price_source=price_source,
            toolbelt=toolbelt,
            gateway=gateway,
            max_tool_rounds=settings.research_max_tool_rounds if payload.research else 0,
            screener=Screener(price_source, load_surveillance()) if screening else None,
            universe_source=_universe_source(request) if screening else None,
            screen_criteria=ScreenCriteria(limit=payload.screen_limit) if screening else None,
            ledger=Ledger(session_factory) if payload.assess_risk else None,
            risk_limits=RiskLimits() if payload.assess_risk else None,
            book=payload.book if payload.assess_risk else None,
        )
    except ImportError as exc:
        # The `agents` extra is not installed. A 503 rather than a 500: the platform is fine,
        # this one capability is not present.
        raise HTTPException(
            status_code=503, detail=f"agent graph unavailable: {exc}"
        ) from exc

    result = await run_cycle(
        compiled,
        {
            "cycle_id": uuid.uuid4().hex[:12],
            "as_of": now_utc(),
            "instruments": [Instrument(s.strip().upper()) for s in (payload.symbols or [])],
            "narrate": payload.narrate,
            "verdicts": [],
            "notes": [],
        },
    )

    verdicts = result.pop("verdicts", [])
    persisted = VerdictRepository(session_factory).save_many(verdicts) if payload.persist else 0

    return {
        **result,
        # One entry per strategy per symbol, exactly as the direct path returns them.
        "verdicts": [_serialise(v) for v in verdicts],
        "count": len(verdicts),
        "persisted": persisted,
        "screened": screening,
        "book": payload.book.value,
        "mcp": [s.as_dict() for s in toolbelt.mcp_status],
        "tools_available": toolbelt.names(),
    }


@router.get(CARD_PATH)
async def agent_card(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    return build_card(request.app.state.tools, settings, str(request.base_url))
