"""The universe, and what survives a screen.

`POST /screen` answers "what is worth looking at", which is a different question from
`POST /verdicts/evaluate`'s "what do the strategies think of this name". A screen decides
eligibility and never ranks — the response is in universe order, and every exclusion carries
the value that caused it.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_settings
from app.core.settings import Settings
from app.data.surveillance import load as load_surveillance
from app.data.universe import NseUniverseSource
from app.screening import filters
from app.screening.screener import ScreenCriteria, Screener

router = APIRouter(tags=["screening"])


def _universe_source(request: Request):
    existing = getattr(request.app.state, "universe_source", None)
    return existing if existing is not None else NseUniverseSource()


class ScreenRequest(BaseModel):
    min_turnover_inr: float = Field(default=filters.DEFAULT_MIN_TURNOVER_INR, ge=0)
    min_price_inr: float = Field(default=filters.DEFAULT_MIN_PRICE_INR, ge=0)
    min_bars: int = Field(default=filters.DEFAULT_MIN_BARS, ge=0)
    exclude_surveillance: bool = True
    #: A cap, applied in universe order after filtering. Not "the best N" — the screen has no
    #: notion of best, and inventing one would be a cross-strategy score by another name.
    limit: int | None = Field(default=None, ge=1, le=500)
    #: Exclusions are the point of a screen, but a 500-name universe makes a large response.
    include_exclusions: bool = True

    def to_criteria(self) -> ScreenCriteria:
        return ScreenCriteria(
            min_turnover_inr=self.min_turnover_inr,
            min_price_inr=self.min_price_inr,
            min_bars=self.min_bars,
            exclude_surveillance=self.exclude_surveillance,
            limit=self.limit,
        )


@router.get("/universe")
async def universe(request: Request) -> dict[str, Any]:
    snapshot = _universe_source(request).snapshot()
    return {
        "index": snapshot.index_name,
        # `live` vs `fallback` matters: a universe that silently shrank to the bundled list is
        # otherwise indistinguishable from a real index change.
        "origin": snapshot.origin,
        "count": len(snapshot),
        "symbols": list(snapshot.symbols),
        "excluded": list(snapshot.excluded),
    }


@router.post("/screen")
async def screen(
    request: Request,
    payload: ScreenRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    from app.api.verdicts import _price_source

    screener = Screener(_price_source(request, settings), load_surveillance())
    result = screener.run(_universe_source(request).snapshot(), payload.to_criteria())

    body = result.as_dict()
    if not payload.include_exclusions:
        # The per-filter counts stay either way — they are what make a small result
        # diagnosable without re-running the screen.
        body.pop("excluded", None)
    return body
