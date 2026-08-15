"""Application factory.

Settings, engine and gateway are constructed once here and hung off ``app.state``, so
dependencies read them rather than importing globals. Accepting an optional ``Settings``
makes the whole app constructible against a throwaway database in tests.

The factory deliberately does **not** create or migrate schema. Schema is owned by Alembic;
an app that quietly migrated on boot is how the predecessor ended up with a schema nobody
could reason about.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.llm.gateway import LiteLLMGateway
from app.persistence.session import make_engine

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Trading platform API",
        version=settings.app_version,
        description="Swing + long-term equity platform. Paper trading only.",
    )

    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.gateway = LiteLLMGateway(settings)

    # The browser is not a database client here; it reaches data only through this API, so
    # exactly one origin needs to be allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)

    log.info("app ready (env=%s, version=%s)", settings.app_env, settings.app_version)
    return app


app = create_app()
