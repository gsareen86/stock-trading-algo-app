"""Strategy listing and verdict evaluation.

`POST /verdicts/evaluate` returns **one verdict per strategy per instrument**. There is no
combined stance, no aggregate score and no ranking in the response — cross-strategy agreement
is something a reader sees, never something the platform computes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.deps import get_gateway, get_session_factory, get_settings
from app.core.settings import Settings
from app.data.cache import CachingPriceSource
from app.data.fundamentals import YFinanceFundamentalsSource
from app.data.yfinance_source import YFinancePriceSource
from app.domain.instrument import Instrument
from app.domain.verdict import Verdict
from app.llm.types import LLMGateway
from app.narratives.generator import narrate_all
from app.persistence.verdicts import MAX_PAGE, VerdictRepository
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry

router = APIRouter(tags=["verdicts"])


def get_strategies(request: Request) -> StrategyRegistry:
    return request.app.state.strategies


def _price_source(request: Request, settings: Settings):
    """The app's shared source, or a cached yfinance one when none was injected."""
    existing = getattr(request.app.state, "price_source", None)
    if existing is not None:
        return existing
    return CachingPriceSource(YFinancePriceSource(), cache_dir=settings.llm_cache_dir + "/prices")


def _fundamentals_source(request: Request):
    """Only the fundamental strategy uses this; the others ignore it entirely."""
    existing = getattr(request.app.state, "fundamentals_source", None)
    return existing if existing is not None else YFinanceFundamentalsSource()


def _serialise(verdict: Verdict) -> dict[str, Any]:
    return {
        "strategy_id": verdict.strategy_id,
        "ticker": verdict.ticker,
        "as_of": verdict.as_of.isoformat(),
        "stance": verdict.stance.value,
        # Scoped to its own strategy — never comparable to another's.
        "conviction": verdict.conviction,
        "gates_passed": verdict.gates_passed,
        "gates": verdict.gates_as_json(),
        "evidence": verdict.evidence_as_json(),
        "narrative": verdict.narrative,
        "trace_id": verdict.trace_id,
    }


class EvaluateRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=50)
    strategy_ids: list[str] | None = None
    persist: bool = False
    #: Off by default. A verdict is complete without prose, and narrating a fifty-symbol
    #: request means fifty model calls — that should be asked for, not arrived at.
    narrate: bool = False


@router.get("/strategies")
async def list_strategies(
    registry: Annotated[StrategyRegistry, Depends(get_strategies)],
) -> dict[str, Any]:
    return {
        "strategies": [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "tags": list(d.tags),
            }
            for d in registry.definitions()
        ],
        "count": len(registry.ids()),
        "load_failures": [{"module": f.module, "error": f.error} for f in registry.load_failures],
    }


@router.post("/verdicts/evaluate")
async def evaluate(
    request: Request,
    payload: EvaluateRequest,
    registry: Annotated[StrategyRegistry, Depends(get_strategies)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    gateway: Annotated[LLMGateway, Depends(get_gateway)],
) -> dict[str, Any]:
    selected = payload.strategy_ids or registry.ids()
    unknown = [s for s in selected if registry.get(s) is None]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown strategy id(s): {', '.join(sorted(unknown))}"
        )

    context = StrategyContext(
        price_source=_price_source(request, settings),
        fundamentals_source=_fundamentals_source(request),
    )
    verdicts: list[Verdict] = []
    for symbol in payload.symbols:
        instrument = Instrument(symbol.strip().upper())
        for strategy_id in selected:
            definition = registry.get(strategy_id)
            verdicts.append(definition.strategy.evaluate(instrument, context))

    # Narrate before persisting, so a stored verdict carries the prose that was shown for it.
    narration: list[dict] | None = None
    if payload.narrate:
        verdicts, narration = await narrate_all(verdicts, gateway)

    persisted = 0
    if payload.persist:
        persisted = VerdictRepository(session_factory).save_many(verdicts)

    body: dict[str, Any] = {
        # One entry per strategy per symbol. No merged stance appears anywhere.
        "verdicts": [_serialise(v) for v in verdicts],
        "count": len(verdicts),
        "persisted": persisted,
    }
    if narration is not None:
        # Reported rather than raised: one rejected narrative is not a failed request, and a
        # silent `null` narrative would be indistinguishable from one never asked for.
        body["narration"] = narration
    return body


@router.get("/verdicts")
async def list_verdicts(
    session_factory: Annotated[Any, Depends(get_session_factory)],
    ticker: str | None = None,
    strategy_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> dict[str, Any]:
    found = VerdictRepository(session_factory).recent(
        ticker=ticker, strategy_id=strategy_id, limit=limit
    )
    return {"verdicts": [_serialise(v) for v in found], "count": len(found)}
