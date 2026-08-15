"""``GET /health`` — the seam report.

Not a liveness probe. In a stack with a database, seven possible LLM providers and an
external tracing service, wiring problems are otherwise invisible until some feature fails at
an inconvenient moment. This endpoint is the one thing the web shell consumes in the bootstrap
change, so a broken seam shows up in the UI immediately rather than in a log nobody reads.

It answers 200 even when degraded — a health check that fails outright tells you less than one
that explains precisely which seam is down.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine

from app.api.deps import get_engine, get_settings
from app.core.settings import Settings
from app.llm import providers
from app.persistence.status import database_status

router = APIRouter(tags=["platform"])


@router.get("/health")
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    engine: Annotated[Engine, Depends(get_engine)],
    probe: Annotated[
        bool,
        Query(description="Probe local LLM providers for reachability (costs a round trip)"),
    ] = False,
) -> dict[str, Any]:
    db = database_status(engine)
    provider_status = await providers.status_all(settings, do_probe=probe)

    any_configured = any(p.configured for p in provider_status)
    healthy = db.connected and bool(db.migrations_current) and any_configured

    return {
        "status": "ok" if healthy else "degraded",
        "app": {
            "version": settings.app_version,
            "env": settings.app_env,
        },
        "database": {
            "connected": db.connected,
            "migrations_current": db.migrations_current,
            "current_revision": db.current_revision,
            "head_revision": db.head_revision,
            "reason": db.reason,
        },
        "llm": {
            # Providers are named, never keyed — no credential material leaves this process.
            "providers": [
                {
                    "name": p.name,
                    "configured": p.configured,
                    "reachable": p.reachable,
                    "detail": p.detail,
                }
                for p in provider_status
            ],
            "any_configured": any_configured,
            "default_model": settings.llm_default_task_model,
            "routes": settings.llm_route,
        },
        "observability": {
            "provider": "langfuse",
            "configured": settings.observability_configured,
        },
    }
