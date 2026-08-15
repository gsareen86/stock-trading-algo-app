"""FastAPI dependencies.

Everything is read off ``app.state``, populated once by the application factory. No
module-level singletons: that is what lets a test override settings without patching imports,
and it keeps the configuration precedence chain genuinely testable.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import Engine

from app.core.settings import Settings
from app.llm.types import LLMGateway


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_gateway(request: Request) -> LLMGateway:
    return request.app.state.gateway
