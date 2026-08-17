"""Issuing and checking JWTs.

**The `type` claim is checked on every decode**, and that is the load-bearing line in this
module. Without it a refresh token — a valid signature over a valid subject, deliberately
long-lived — would be accepted wherever an access token is expected, handing out a two-week
credential where a thirty-minute one was intended. It is a real vulnerability class rather than
a hypothetical, and the only thing preventing it is that `decode` refuses a token whose type
does not match what the caller asked for.

Refresh tokens carry a `jti` so they can be revoked. A JWT cannot be un-issued; the honest way
to build logout is to check the identifier against stored state rather than to pretend the
token has gone away.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt

ALGORITHM = "HS256"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """A token was missing, malformed, expired, tampered with, or of the wrong type."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    token_type: TokenType
    expires_at: datetime
    jti: str | None = None


def issue(
    subject: str,
    token_type: TokenType,
    secret: str,
    lifetime: timedelta,
    jti: str | None = None,
) -> tuple[str, TokenClaims]:
    """Mint a token and return it with the claims it carries."""
    now = datetime.now(UTC)
    expires_at = now + lifetime
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    # Both types carry one. Only refresh tokens are *checked* against stored state, but a
    # unique id also stops two tokens minted in the same second from being byte-identical,
    # which is harmless and surprising enough to be worth removing.
    payload["jti"] = jti or uuid.uuid4().hex

    encoded = jwt.encode(payload, secret, algorithm=ALGORITHM)
    return encoded, TokenClaims(
        subject=subject,
        token_type=token_type,
        expires_at=expires_at,
        jti=payload.get("jti"),
    )


def decode(token: str, secret: str, expect: TokenType) -> TokenClaims:
    """Verify a token and assert it is the kind the caller asked for.

    ``expect`` is required rather than optional: making it a default would let a caller forget
    it, and forgetting it is exactly the bug this module exists to prevent.
    """
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        # Deliberately not echoed to the client in detail: "signature invalid" versus
        # "malformed" tells an attacker which half of their forgery to fix.
        raise TokenError("token is not valid") from exc

    actual = payload.get("type")
    if actual != expect.value:
        raise TokenError(f"expected a {expect.value} token, got {actual!r}")

    return TokenClaims(
        subject=str(payload["sub"]),
        token_type=TokenType(actual),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        jti=payload.get("jti"),
    )
