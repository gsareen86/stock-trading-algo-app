"""Application factory.

Settings, engine and gateway are constructed once here and hung off ``app.state``, so
dependencies read them rather than importing globals. Accepting an optional ``Settings``
makes the whole app constructible against a throwaway database in tests.

The factory deliberately does **not** create or migrate schema. Schema is owned by Alembic;
an app that quietly migrates on boot is how a project ends up with a schema nobody
could reason about.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.backtest import router as backtest_router
from app.api.books import router as books_router
from app.api.broker import router as broker_router
from app.api.cycles import router as cycles_router
from app.api.health import router as health_router
from app.api.insights import router as insights_router
from app.api.llm import router as llm_router
from app.api.root import router as root_router
from app.api.screening import router as screening_router
from app.api.themes import router as themes_router
from app.api.tools import router as tools_router
from app.api.verdicts import router as verdicts_router
from app.auth.guard import AuthGuard
from app.auth.service import AuthService
from app.broker.session import DEFAULT_KITE_MCP_URL, KiteSession
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.llm.budget import DailyBudget
from app.llm.gateway import LiteLLMGateway
from app.llm.recorder import CallRecorder
from app.persistence.session import make_engine, make_session_factory
from app.strategies.registry import StrategyRegistry
from app.tools.registry import ToolRegistry

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
    app.state.session_factory = make_session_factory(app.state.engine)

    # The recorder and budget share the session factory: one writes the ledger, the other
    # reads it back to decide whether the platform may keep spending.
    app.state.recorder = CallRecorder(app.state.session_factory)
    app.state.budget = DailyBudget(app.state.session_factory, settings.daily_budget_usd)
    app.state.gateway = LiteLLMGateway(
        settings, recorder=app.state.recorder, budget=app.state.budget
    )
    # Discovered once at startup: importing every tool module per request would be wasteful,
    # and load failures should surface at boot rather than on first use.
    app.state.auth = AuthService(app.state.session_factory, settings)
    # One session per process: each would need its own browser login, which is a confusing
    # thing to ask of someone twice.
    app.state.broker = KiteSession(
        url=settings.mcp_server.get("kite", DEFAULT_KITE_MCP_URL),
        refresh_minutes=settings.broker_refresh_minutes,
    )
    app.state.tools = ToolRegistry.discover()
    app.state.strategies = StrategyRegistry.discover()

    # The browser is not a database client here; it reaches data only through this API, so
    # exactly one origin needs to be allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Added after CORS so CORS is the outer layer: a 401 still needs its headers, or the
    # browser reports a cross-origin error instead of an auth failure.
    app.add_middleware(AuthGuard)

    app.include_router(auth_router)
    app.include_router(root_router)
    app.include_router(health_router)
    app.include_router(llm_router)
    app.include_router(tools_router)
    app.include_router(verdicts_router)
    app.include_router(cycles_router)
    app.include_router(screening_router)
    app.include_router(books_router)
    app.include_router(insights_router)
    app.include_router(backtest_router)
    app.include_router(broker_router)
    app.include_router(themes_router)

    log.info("app ready (env=%s, version=%s)", settings.app_env, settings.app_version)
    return app


app = create_app()
