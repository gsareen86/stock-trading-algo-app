"""The insight feed.

**In-app only.** `project.md` has said since `0001` that there is deliberately no email, push
or messaging channel, and that none should be added without a change specifying it. There is
no notifier here, no webhook and no outbound anything — a feed nobody has read yet is a
feature; a notification nobody asked for is a habit that is hard to remove.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_session_factory
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
