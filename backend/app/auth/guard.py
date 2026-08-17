"""Requiring a login, application-wide.

The dangerous way to add auth to an existing API is to decorate the endpoints that need it,
because the failure mode is silent: a router added later is simply open, and nothing says so.
So this guard runs for **every** request and the exemptions are a named list — a new endpoint is
protected because it exists, not because someone remembered.

A test walks the live route table and fails on any path that is neither protected nor listed,
which is the only mechanism here that keeps working without anyone maintaining it.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.service import AuthenticationFailed, AuthService

log = logging.getLogger(__name__)

#: Paths reachable without a token.
#:
#: `/health` is public deliberately: a health check that needs a credential cannot tell a
#: monitor the difference between "down" and "misconfigured". It reports seam status and no
#: portfolio data.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/health",
        "/auth/login",
        "/auth/refresh",
        "/auth/logout",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
        # Discovery document for external agents. Advertises capabilities, never data.
        "/.well-known/agent-card.json",
    }
)

#: The refresh token travels in an httpOnly cookie so page script cannot read it.
REFRESH_COOKIE = "refresh_token"


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS


class AuthGuard(BaseHTTPMiddleware):
    """Rejects unauthenticated requests to anything not explicitly public."""

    async def dispatch(self, request: Request, call_next):
        # Browsers preflight cross-origin requests without credentials; rejecting those would
        # break the web app before it ever gets to send a token.
        if request.method == "OPTIONS" or is_public(request.url.path):
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return _unauthorised("missing bearer token")

        service: AuthService = request.app.state.auth
        try:
            username = service.user_for_access_token(token)
        except AuthenticationFailed as exc:
            return _unauthorised(str(exc))

        request.state.username = username
        return await call_next(request)


def _unauthorised(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        # Tells a client this is an auth failure rather than a permission one, which is what
        # the web app keys its single refresh attempt off.
        headers={"WWW-Authenticate": "Bearer"},
    )
