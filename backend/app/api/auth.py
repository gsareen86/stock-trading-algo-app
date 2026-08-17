"""Login, refresh, logout.

The access token comes back in the body for the client to hold in memory. The refresh token
goes into an **httpOnly** cookie so script running on the page cannot read it — the reason not
to put either in `localStorage`, which any injected script can read.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import get_settings
from app.auth.guard import REFRESH_COOKIE
from app.auth.service import AuthenticationFailed, AuthService
from app.core.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        # Unreadable to page script — the whole reason this is a cookie and not a JSON field.
        httponly=True,
        secure=settings.auth_cookie_secure,
        # `lax` still sends the cookie on the top-level navigations a login flow needs, while
        # withholding it from cross-site sub-requests.
        samesite="lax",
        max_age=settings.auth_refresh_token_days * 24 * 3600,
        path="/",
    )


@router.post("/login")
async def login(
    payload: LoginRequest,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth)],
) -> dict[str, Any]:
    try:
        session = service.login(payload.username, payload.password)
    except AuthenticationFailed as exc:
        # One message for both "no such user" and "wrong password": distinguishing them turns
        # this endpoint into a username directory.
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _set_refresh_cookie(response, session.refresh_token, settings)
    return {
        "access_token": session.access_token,
        "token_type": "bearer",
        "expires_in": session.expires_in,
        "username": session.username,
    }


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[AuthService, Depends(get_auth)],
) -> dict[str, Any]:
    """Exchange the refresh cookie for a new pair. The presented token is revoked."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="no refresh token")

    try:
        session = service.refresh(token)
    except AuthenticationFailed as exc:
        # Clear the cookie: keeping a token the server has rejected only produces a client
        # that retries forever.
        response.delete_cookie(REFRESH_COOKIE, path="/")
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _set_refresh_cookie(response, session.refresh_token, settings)
    return {
        "access_token": session.access_token,
        "token_type": "bearer",
        "expires_in": session.expires_in,
        "username": session.username,
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth)],
) -> dict[str, Any]:
    """Revoke the refresh token and clear the cookie.

    Revocation is real: the stored row is marked, so the token stops working immediately rather
    than merely being forgotten by the browser. The access token remains valid until it expires,
    which is why it is short-lived.
    """
    revoked = service.logout(request.cookies.get(REFRESH_COOKIE))
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return {"revoked": revoked}


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    """Who the current token belongs to. Never returns a password hash."""
    return {"username": getattr(request.state, "username", None)}
