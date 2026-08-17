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
from app.api.verdicts import _fundamentals_source, _price_source, _serialise
from app.core.clock import now_utc
from app.core.settings import Settings
from app.domain.instrument import Instrument
from app.llm.types import LLMGateway
from app.persistence.verdicts import VerdictRepository
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext

router = APIRouter(tags=["cycles"])


class RunCycleRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=25)
    narrate: bool = False
    persist: bool = False
    #: Off by default: research calls a model and external servers, and a cycle is useful
    #: without it. The verdicts are identical either way.
    research: bool = True


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

    try:
        compiled = build_graph(
            registry=strategies,
            strategy_context=strategy_context,
            price_source=price_source,
            toolbelt=toolbelt,
            gateway=gateway,
            max_tool_rounds=settings.research_max_tool_rounds if payload.research else 0,
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
            "instruments": [Instrument(s.strip().upper()) for s in payload.symbols],
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
        "mcp": [s.as_dict() for s in toolbelt.mcp_status],
        "tools_available": toolbelt.names(),
    }


@router.get(CARD_PATH)
async def agent_card(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    return build_card(request.app.state.tools, settings, str(request.base_url))
