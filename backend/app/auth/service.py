"""Login, refresh, logout.

Refresh tokens are checked against a stored row on every use, which is what makes logout mean
something: a JWT cannot be un-issued, so revocation has to be state the platform keeps rather
than a property of the token.

Refresh also **rotates** — using a refresh token revokes it and issues a new one. A refresh
token that stayed valid after use is a long-lived bearer credential that leaves no trace when
it is copied; rotation means a stolen token stops working as soon as the real session uses
its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.tokens import TokenError, TokenType, decode, issue
from app.core.clock import now_utc
from app.core.settings import Settings
from app.persistence.models import RefreshToken, User

log = logging.getLogger(__name__)


class AuthenticationFailed(Exception):
    """Credentials were not accepted. Deliberately says no more than that."""


@dataclass(frozen=True, slots=True)
class Session_:
    """A freshly issued pair."""

    access_token: str
    refresh_token: str
    expires_in: int
    username: str


class AuthService:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings) -> None:
        self._sessions = session_factory
        self._settings = settings

    @property
    def _secret(self) -> str:
        secret = self._settings.auth_secret_key
        if not secret:  # pragma: no cover - settings guarantee this
            raise RuntimeError("no signing key configured")
        return secret

    # ── users ─────────────────────────────────────────────────────────────────
    def create_user(self, username: str, password: str) -> int:
        name = username.strip().lower()
        if not name:
            raise ValueError("username must be non-empty")

        with self._sessions() as session:
            existing = session.execute(
                select(User).where(User.username == name)
            ).scalar_one_or_none()
            if existing is not None:
                raise ValueError(f"user {name!r} already exists")

            user = User(username=name, password_hash=hash_password(password), is_active=True)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user.id

    def set_password(self, username: str, password: str) -> bool:
        with self._sessions() as session:
            user = session.execute(
                select(User).where(User.username == username.strip().lower())
            ).scalar_one_or_none()
            if user is None:
                return False
            user.password_hash = hash_password(password)
            session.commit()
        # Every existing session is now stale; revoking is the point of changing a password.
        self.revoke_all(username)
        return True

    def user_count(self) -> int:
        with self._sessions() as session:
            return len(session.execute(select(User.id)).all())

    # ── login ─────────────────────────────────────────────────────────────────
    def login(self, username: str, password: str) -> Session_:
        """Authenticate, or fail in a way that reveals nothing.

        An unknown username and a wrong password take the same path and return the same error:
        returning early on "no such user" is a timing oracle that turns a login form into a
        username directory.
        """
        name = (username or "").strip().lower()
        with self._sessions() as session:
            user = session.execute(
                select(User).where(User.username == name)
            ).scalar_one_or_none()

            stored = user.password_hash if user else None
            if not verify_password(password or "", stored) or user is None or not user.is_active:
                raise AuthenticationFailed("invalid username or password")

            user.last_login_at = now_utc()
            if needs_rehash(user.password_hash):
                # Parameters were raised since this hash was made; upgrade it now that the
                # plaintext is momentarily available.
                user.password_hash = hash_password(password)
            user_id = user.id
            session.commit()

        return self._issue_pair(name, user_id)

    def refresh(self, refresh_token: str) -> Session_:
        """Exchange a refresh token for a new pair, revoking the one presented."""
        try:
            claims = decode(refresh_token, self._secret, expect=TokenType.REFRESH)
        except TokenError as exc:
            raise AuthenticationFailed(str(exc)) from exc

        with self._sessions() as session:
            record = session.execute(
                select(RefreshToken).where(RefreshToken.jti == claims.jti)
            ).scalar_one_or_none()

            if record is None or record.revoked_at is not None:
                # Either logged out, already rotated, or forged with a valid signature but a
                # jti we never issued.
                raise AuthenticationFailed("refresh token is no longer valid")

            user = session.get(User, record.user_id)
            if user is None or not user.is_active:
                raise AuthenticationFailed("refresh token is no longer valid")

            record.revoked_at = now_utc()
            username, user_id = user.username, user.id
            session.commit()

        return self._issue_pair(username, user_id)

    def logout(self, refresh_token: str | None) -> bool:
        """Revoke the presented refresh token. Missing or invalid is not an error."""
        if not refresh_token:
            return False
        try:
            claims = decode(refresh_token, self._secret, expect=TokenType.REFRESH)
        except TokenError:
            return False

        with self._sessions() as session:
            record = session.execute(
                select(RefreshToken).where(RefreshToken.jti == claims.jti)
            ).scalar_one_or_none()
            if record is None or record.revoked_at is not None:
                return False
            record.revoked_at = now_utc()
            session.commit()
            return True

    def revoke_all(self, username: str) -> int:
        with self._sessions() as session:
            user = session.execute(
                select(User).where(User.username == username.strip().lower())
            ).scalar_one_or_none()
            if user is None:
                return 0
            rows = (
                session.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
                    )
                )
                .scalars()
                .all()
            )
            stamp = now_utc()
            for row in rows:
                row.revoked_at = stamp
            session.commit()
            return len(rows)

    # ── reading ───────────────────────────────────────────────────────────────
    def user_for_access_token(self, token: str) -> str:
        """Username behind a valid access token.

        `expect=ACCESS` is the whole point: a refresh token is a valid signature over a valid
        subject and would otherwise be accepted here as a two-week credential.
        """
        try:
            claims = decode(token, self._secret, expect=TokenType.ACCESS)
        except TokenError as exc:
            raise AuthenticationFailed(str(exc)) from exc

        with self._sessions() as session:
            user = session.execute(
                select(User).where(User.username == claims.subject)
            ).scalar_one_or_none()
            if user is None or not user.is_active:
                raise AuthenticationFailed("user is no longer active")
            return user.username

    # ── internals ─────────────────────────────────────────────────────────────
    def _issue_pair(self, username: str, user_id: int) -> Session_:
        access_minutes = self._settings.auth_access_token_minutes
        access, _ = issue(
            username, TokenType.ACCESS, self._secret, timedelta(minutes=access_minutes)
        )
        refresh_days = self._settings.auth_refresh_token_days
        refresh, claims = issue(
            username, TokenType.REFRESH, self._secret, timedelta(days=refresh_days)
        )

        with self._sessions() as session:
            session.add(
                RefreshToken(
                    jti=claims.jti or "",
                    user_id=user_id,
                    expires_at=claims.expires_at,
                )
            )
            session.commit()

        return Session_(
            access_token=access,
            refresh_token=refresh,
            expires_in=access_minutes * 60,
            username=username,
        )


def purge_expired(session_factory: sessionmaker[Session]) -> int:
    """Drop refresh rows that can no longer authorise anything."""
    with session_factory() as session:
        rows = (
            session.execute(
                select(RefreshToken).where(RefreshToken.expires_at < datetime.now(UTC))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.delete(row)
        session.commit()
        return len(rows)
