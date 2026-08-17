"""``GET /`` — what this service is and where to go next.

FastAPI answers 404 at the root by default, which is correct and useless: the first thing
anyone does with a new backend is open its base URL in a browser, and "Not Found" reads as
*the server is broken* rather than *you want a different path*. This costs one handler and
removes a whole class of false alarm.

Deliberately static — it lists routes rather than probing them. `GET /health` is the endpoint
that reports whether the seams are actually up, and duplicating that here would give two
answers to one question.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_settings
from app.core.settings import Settings

router = APIRouter(tags=["root"])


@router.get("/")
async def index(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    return {
        "service": "swing + long-term equity platform",
        "version": settings.app_version,
        "env": settings.app_env,
        "docs": "/docs",
        "endpoints": {
            "health": "GET /health?probe=true",
            "tools": "GET /tools",
            "strategies": "GET /strategies",
            "evaluate": "POST /verdicts/evaluate",
            "verdicts": "GET /verdicts",
            "llm_usage": "GET /llm/usage",
            "llm_calls": "GET /llm/calls",
        },
    }
