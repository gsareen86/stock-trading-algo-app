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
from app.insights.feed import InsightFeed
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
    #: Write the cycle's findings to the in-app feed. Requires risk, which supplies the book.
    surface_insights: bool = True


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
        context=ToolContext(
            price_source=price_source,
            session_factory=session_factory,
            company_financials_source=getattr(
                request.app.state, "company_financials_source", None
            ),
            universe_source=_universe_source(request),
        ),
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
            feed=InsightFeed(session_factory) if payload.surface_insights else None,
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


@router.post("/cycles/run/stream")
async def run_stream(
    request: Request,
    payload: RunCycleRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    gateway: Annotated[LLMGateway, Depends(get_gateway)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
):
    """Execute one cycle and stream genuine LangGraph node + counted work progress over SSE."""
    from app.agents import nodes
    from app.api.streaming import sse_stream_response

    strategies: StrategyRegistry = request.app.state.strategies
    tools: ToolRegistry = request.app.state.tools
    price_source = _price_source(request, settings)
    strategy_context = StrategyContext(
        price_source=price_source,
        fundamentals_source=_fundamentals_source(request),
    )
    toolbelt = Toolbelt(
        registry=tools,
        context=ToolContext(
            price_source=price_source,
            session_factory=session_factory,
            company_financials_source=getattr(
                request.app.state, "company_financials_source", None
            ),
            universe_source=_universe_source(request),
        ),
        mcp_servers=dict(settings.mcp_server) if payload.research else {},
    )
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
            feed=InsightFeed(session_factory) if payload.surface_insights else None,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail=f"agent graph unavailable: {exc}"
        ) from exc

    async def drive(emit):
        if payload.research:
            await toolbelt.connect()

        universe_count = (
            len(_universe_source(request).snapshot().instruments)
            if screening
            else len(payload.symbols or [])
        )
        strategy_count = len(strategies.ids())
        initial_state = {
            "cycle_id": uuid.uuid4().hex[:12],
            "as_of": now_utc(),
            "instruments": [Instrument(s.strip().upper()) for s in (payload.symbols or [])],
            "narrate": payload.narrate,
            "verdicts": [],
            "notes": [],
        }

        if screening:
            emit("screen", f"Screening {universe_count} instruments", 0, None)
        else:
            emit("regime", "Reading benchmark market regime", 0, None)

        merged: dict[str, Any] = dict(initial_state)
        verdicts_acc: list[Any] = []
        notes_acc: list[str] = []
        eligible_count = len(initial_state["instruments"])
        evals_done = 0

        async for update in compiled.astream(initial_state, stream_mode="updates"):
            for node_name, delta in update.items():
                if not isinstance(delta, dict):
                    continue
                if "verdicts" in delta:
                    verdicts_acc.extend(delta["verdicts"] or [])
                if "notes" in delta:
                    notes_acc.extend(delta["notes"] or [])
                merged.update({k: v for k, v in delta.items() if k not in ("verdicts", "notes")})

                if node_name == "screen":
                    eligible_count = len(delta.get("instruments") or [])
                    emit(
                        "screen",
                        f"Screened {universe_count} instruments ({eligible_count} eligible)",
                        universe_count,
                        universe_count,
                    )
                elif node_name == "regime":
                    emit("regime", "Market regime measured", 1, 1)
                elif node_name == "research":
                    emit("research", "Qualitative research & tools complete", 1, 1)
                elif node_name.startswith("strategy."):
                    evals_done += eligible_count
                    total_evals = max(1, eligible_count * strategy_count)
                    emit(
                        "strategies",
                        f"Evaluated strategies ({evals_done} / {total_evals})",
                        evals_done,
                        total_evals,
                    )
                elif node_name == "risk":
                    emit("risk", "Checked portfolio risk limits", 1, 1)
                elif node_name == "narrate":
                    n_cnt = len(delta.get("narrated") or [])
                    emit("narrate", f"Narrated {n_cnt} verdicts", n_cnt, max(1, n_cnt))
                elif node_name == "insights":
                    emit("insights", "Updated insights feed", 1, 1)

        merged["verdicts"] = verdicts_acc
        merged["notes"] = notes_acc
        verdicts = merged.get("narrated") or verdicts_acc
        persisted = (
            VerdictRepository(session_factory).save_many(verdicts) if payload.persist else 0
        )
        summary = nodes.summarise(merged)
        return {
            **summary,
            "verdicts": [_serialise(v) for v in verdicts],
            "count": len(verdicts),
            "persisted": persisted,
            "screened": screening,
            "book": payload.book.value,
            "mcp": [s.as_dict() for s in toolbelt.mcp_status],
            "tools_available": toolbelt.names(),
        }

    return sse_stream_response(drive)


@router.get(CARD_PATH)
async def agent_card(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    return build_card(request.app.state.tools, settings, str(request.base_url))
