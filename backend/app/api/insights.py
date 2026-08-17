"""The insight feed.

**In-app only.** `project.md` has said since `0001` that there is deliberately no email, push
or messaging channel, and that none should be added without a change specifying it. There is
no notifier here, no webhook and no outbound anything — a feed nobody has read yet is a
feature; a notification nobody asked for is a habit that is hard to remove.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.deps import get_session_factory, get_settings
from app.books.ledger import Ledger
from app.core.settings import Settings
from app.domain.instrument import Instrument
from app.domain.position import Book
from app.insights.actions import Action, ActionRefused, actions_for, execute
from app.insights.feed import MAX_PAGE, InsightFeed
from app.insights.kinds import SPECS, Kind

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
async def list_insights(
    session_factory: Annotated[Any, Depends(get_session_factory)],
    unread_only: bool = False,
    kind: Kind | None = None,
    ticker: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> dict[str, Any]:
    feed = InsightFeed(session_factory)
    items = feed.recent(limit=limit, unread_only=unread_only, kind=kind, ticker=ticker)
    for item in items:
        # Declared by kind, so the reader never has to work out what an insight allows.
        item["actions"] = list(actions_for(item["kind"]))
    return {"insights": items, "count": len(items), "unread": feed.unread_count()}


@router.get("/unread-count")
async def unread_count(
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, int]:
    return {"unread": InsightFeed(session_factory).unread_count()}


@router.get("/kinds")
async def kinds() -> dict[str, Any]:
    """What the platform can raise, and how loud each kind is.

    Severity is a property of the kind and is published as such — it is never computed per item
    and compared across kinds, which would be a ranking.
    """
    return {
        "kinds": [
            {
                "kind": kind.value,
                "severity": spec.severity.value,
                "suppress_days": spec.suppress_days,
                # True when the body is quoted from a tool rather than measured here.
                "from_research": spec.from_research,
            }
            for kind, spec in SPECS.items()
        ]
    }


@router.post("/{insight_id}/read")
async def mark_read(
    insight_id: int,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    if not InsightFeed(session_factory).mark_read(insight_id):
        raise HTTPException(status_code=404, detail=f"no insight with id {insight_id}")
    return {"id": insight_id, "read": True}


@router.post("/read-all")
async def mark_all_read(
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, int]:
    return {"marked": InsightFeed(session_factory).mark_all_read()}


class ActRequest(BaseModel):
    action: Action
    book: Book = Book.SWING
    #: Runs the identical derivation and returns before writing.
    preview: bool = False


@router.post("/{insight_id}/act")
async def act(
    insight_id: int,
    payload: ActRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    """Act on an insight, through the same `Ledger.fill()` every other fill uses."""
    feed = InsightFeed(session_factory)
    insight = next((i for i in feed.recent(limit=MAX_PAGE) if i["id"] == insight_id), None)
    if insight is None:
        raise HTTPException(status_code=404, detail=f"no insight with id {insight_id}")

    if payload.action.value not in actions_for(insight["kind"]):
        raise HTTPException(
            status_code=422,
            detail=f"{payload.action.value} is not available for a {insight['kind']} insight",
        )

    ledger = Ledger(session_factory)
    try:
        plan, trade = execute(
            payload.action,
            insight,
            ledger,
            payload.book,
            _last_price(request, settings, insight.get("ticker")),
            preview=payload.preview,
        )
    except ActionRefused as exc:
        # A stale insight is a normal outcome, not a server fault.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not payload.preview:
        feed.mark_read(insight_id)

    return {
        "insight_id": insight_id,
        "preview": payload.preview,
        "plan": plan.as_dict(),
        "trade": trade,
        "position": (
            ledger.position(payload.book, insight["ticker"]).as_dict()
            if insight.get("ticker")
            else None
        ),
    }


def _last_price(request: Request, settings: Settings, ticker: str | None) -> float | None:
    if not ticker:
        return None
    from app.api.verdicts import _price_source

    try:
        series = _price_source(request, settings).history(
            Instrument(ticker), interval="1d", lookback_days=30
        )
    except Exception:  # pragma: no cover - sources are contracted not to raise
        return None
    return series.last_close
