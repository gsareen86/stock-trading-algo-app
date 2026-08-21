"""Themes over HTTP.

Read-heavy by design. A theme run is expensive and deliberate, so it is one POST; everything
else reads what a run produced. The only other write is rejecting a chain link, which changes
what a reader is shown and nothing else — it records no trade and touches no position.

**Nothing here returns a stance, a conviction or an ordering.** A theme is a lens, and the four
strategies remain the only thing in the platform that forms an opinion about an instrument.
Candidates carry a named exposure grade and never a number, because a number would be sortable
and sorting candidates by theme exposure is a recommendation wearing a measurement's clothes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.deps import get_session_factory, get_settings
from app.core.settings import Settings
from app.themes.store import ThemeStore

router = APIRouter(prefix="/themes", tags=["themes"])


def _store(session_factory) -> ThemeStore:
    return ThemeStore(session_factory)


class RunThemesRequest(BaseModel):
    #: `requested` or `scheduled`. Recorded on the run so a surprising result can be traced to
    #: how it was started.
    trigger: str = Field(default="requested", max_length=16)


@router.post("/run")
async def run_themes(
    request: Request,
    payload: RunThemesRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    """Start a theme run.

    Refused rather than queued while one is in progress: two runs writing the same counts
    would interleave them, and a count that blends two passes is not a measurement.
    """
    runner = getattr(request.app.state, "theme_runner", None)
    if runner is None:
        # The sources this needs are optional extras. A 503 rather than a 500 — the platform
        # is fine, this one capability is not wired up.
        raise HTTPException(
            status_code=503,
            detail="theme runs are not configured on this instance",
        )

    result = runner.run(trigger=payload.trigger)
    if result.outcome == "refused":
        raise HTTPException(status_code=409, detail=result.reason)
    return result.as_dict()


@router.get("/runs")
async def list_runs(
    session_factory: Annotated[Any, Depends(get_session_factory)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    runs = _store(session_factory).runs(limit=limit)
    return {"runs": runs, "count": len(runs)}


@router.get("")
async def list_themes(
    session_factory: Annotated[Any, Depends(get_session_factory)],
    include_withdrawn: Annotated[
        bool,
        Query(
            description=(
                "Include themes that stopped being evidenced. Off by default: they are "
                "history, not attention."
            )
        ),
    ] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict[str, Any]:
    store = _store(session_factory)
    themes = store.standing(include_withdrawn=include_withdrawn, limit=limit)
    latest = store.runs(limit=1)
    return {
        "themes": themes,
        "count": len(themes),
        # The run's own state travels with the themes, so "nothing found" and "nothing could
        # be read" are never confused by a caller that forgot to ask.
        "latest_run": latest[0] if latest else None,
    }


@router.get("/{theme_key}")
async def read_theme(
    theme_key: str,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    store = _store(session_factory)
    themes = {t["key"]: t for t in store.standing(include_withdrawn=True, limit=200)}
    theme = themes.get(theme_key)
    if theme is None:
        raise HTTPException(status_code=404, detail=f"no theme with key {theme_key}")

    return {
        **theme,
        "chain": store.chain(theme_key),
        # What each coarse tier broke into. A sub-category carries whether it was searched,
        # so "searched and found nothing" is distinguishable from "never searched" — they
        # look identical on a screen and mean opposite things.
        "sub_categories": store.sub_categories(theme_key),
        # Every company a search proposed, **including the refusals**. A name the universe
        # could not confirm is published as `not_found` and an ambiguous one as `ambiguous`,
        # because the refusals are the safety property and a surface that showed only the
        # successes would give no sign they had happened.
        "proposals": store.proposals(theme_key),
        "candidates": store.candidates(theme_key),
        "references": [
            {
                "symbol": r.symbol,
                "period": r.period,
                "kind": r.kind.value,
                "source_ref": r.source_ref,
                "sector": r.sector,
                "excerpt": r.excerpt,
                # Quoted from a document, never measured here.
                "measured_by_platform": False,
            }
            for r in store.references(theme_key)
        ],
    }


class RejectLinkRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.post("/links/{link_id}/reject")
async def reject_link(
    link_id: int,
    payload: RejectLinkRequest,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    """Reject one chain link.

    Persists across later runs. Without that, every run re-proposes the same wrong link and
    the reader re-rejects it forever, which is how a review surface becomes one people stop
    reading. Writes no trade and changes no position.
    """
    if not _store(session_factory).reject_link(link_id, payload.reason):
        raise HTTPException(status_code=404, detail=f"no chain link with id {link_id}")
    return {"id": link_id, "rejected": True, "reason": payload.reason}
