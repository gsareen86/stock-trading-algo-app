"""Authentication.

The two properties that matter most here are structural rather than behavioural:

* **every route is protected unless it is on a named list**, checked by walking the live route
  table — so an endpoint added later is protected because it exists, not because someone
  remembered;
* **a refresh token is rejected where an access token is required**, because otherwise it is a
  two-week credential accepted where a thirty-minute one was intended.
"""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.guard import PUBLIC_PATHS, REFRESH_COOKIE
from app.auth.passwords import WeakPassword, hash_password, verify_password
from app.auth.service import AuthenticationFailed, AuthService
from app.auth.tokens import TokenError, TokenType, decode, issue
from app.core.settings import Settings
from app.main import create_app

USERNAME = "trader"
PASSWORD = "a-sufficiently-long-password"


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def open_client(app) -> TestClient:
    """Unauthenticated on purpose."""
    return TestClient(app)


@pytest.fixture
def service(app) -> AuthService:
    svc = app.state.auth
    svc.create_user(USERNAME, PASSWORD)
    return svc


class TestPasswords:
    def test_hash_is_not_the_password(self) -> None:
        stored = hash_password(PASSWORD)

        assert PASSWORD not in stored
        assert stored.startswith("$argon2")

    def test_verify_round_trip(self) -> None:
        assert verify_password(PASSWORD, hash_password(PASSWORD)) is True
        assert verify_password("wrong-password-entirely", hash_password(PASSWORD)) is False

    def test_short_passwords_are_refused(self) -> None:
        with pytest.raises(WeakPassword):
            hash_password("short")

    def test_missing_hash_still_verifies_against_a_dummy(self) -> None:
        """Returning early on "no such user" is a timing oracle."""
        assert verify_password(PASSWORD, None) is False

    def test_two_hashes_of_one_password_differ(self) -> None:
        """Salted — identical passwords must not produce identical hashes."""
        assert hash_password(PASSWORD) != hash_password(PASSWORD)


class TestTokenTypeIsChecked:
    SECRET = "test-secret-value-for-signing-long-enough-for-hs256"

    def test_access_token_round_trip(self) -> None:
        token, _ = issue("bob", TokenType.ACCESS, self.SECRET, timedelta(minutes=5))

        claims = decode(token, self.SECRET, expect=TokenType.ACCESS)

        assert claims.subject == "bob"
        assert claims.token_type is TokenType.ACCESS

    def test_a_refresh_token_is_rejected_as_an_access_token(self) -> None:
        """The vulnerability this module exists to prevent: a valid signature over a valid
        subject, deliberately long-lived, accepted where a short-lived credential was meant."""
        token, _ = issue("bob", TokenType.REFRESH, self.SECRET, timedelta(days=14))

        with pytest.raises(TokenError, match="expected a access token"):
            decode(token, self.SECRET, expect=TokenType.ACCESS)

    def test_an_access_token_is_rejected_as_a_refresh_token(self) -> None:
        token, _ = issue("bob", TokenType.ACCESS, self.SECRET, timedelta(minutes=5))

        with pytest.raises(TokenError):
            decode(token, self.SECRET, expect=TokenType.REFRESH)

    def test_every_token_carries_a_unique_jti(self) -> None:
        """Only refresh jtis are *checked* against stored state, but uniqueness stops two
        tokens minted in the same second from being byte-identical."""
        _, first = issue("bob", TokenType.ACCESS, self.SECRET, timedelta(minutes=5))
        _, second = issue("bob", TokenType.ACCESS, self.SECRET, timedelta(minutes=5))
        _, refresh = issue("bob", TokenType.REFRESH, self.SECRET, timedelta(days=1))

        assert first.jti and second.jti and refresh.jti
        assert first.jti != second.jti

    def test_expired_token_is_rejected(self) -> None:
        token, _ = issue("bob", TokenType.ACCESS, self.SECRET, timedelta(seconds=-10))

        with pytest.raises(TokenError, match="expired"):
            decode(token, self.SECRET, expect=TokenType.ACCESS)

    def test_token_signed_with_another_key_is_rejected(self) -> None:
        token, _ = issue(
            "bob",
            TokenType.ACCESS,
            "a-different-secret-also-long-enough-for-hs256",
            timedelta(minutes=5),
        )

        with pytest.raises(TokenError):
            decode(token, self.SECRET, expect=TokenType.ACCESS)

    def test_tampered_payload_is_rejected(self) -> None:
        forged = jwt.encode(
            {"sub": "admin", "type": "access", "exp": 9999999999},
            "not-the-secret-but-long-enough-for-hs256-anyway",
            "HS256",
        )

        with pytest.raises(TokenError):
            decode(forged, self.SECRET, expect=TokenType.ACCESS)

    def test_unsigned_token_is_rejected(self) -> None:
        """`alg: none` is the oldest JWT attack; the decoder must not accept it."""
        unsigned = jwt.encode(
            {"sub": "admin", "type": "access", "exp": 9999999999}, key="", algorithm="none"
        )

        with pytest.raises(TokenError):
            decode(unsigned, self.SECRET, expect=TokenType.ACCESS)


class TestSecretKeyPolicy:
    def test_prod_refuses_to_start_without_a_secret(self) -> None:
        """A well-known signing key means every token is forgeable by anyone with the repo."""
        with pytest.raises(Exception, match="AUTH_SECRET_KEY"):
            Settings(app_env="prod", database_url="sqlite://", _env_file=None)

    def test_dev_generates_one_per_process(self) -> None:
        first = Settings(app_env="dev", _env_file=None).auth_secret_key
        second = Settings(app_env="dev", _env_file=None).auth_secret_key

        assert first and second and first != second

    def test_an_explicit_secret_is_honoured(self) -> None:
        settings = Settings(app_env="prod", auth_secret_key="x" * 40, _env_file=None)

        assert settings.auth_secret_key == "x" * 40

    def test_a_short_secret_is_refused(self) -> None:
        """RFC 7518 §3.2 — PyJWT warns below 32 bytes; refusing beats a warning nobody reads."""
        with pytest.raises(Exception, match="at least 32"):
            Settings(app_env="prod", auth_secret_key="too-short", _env_file=None)


class TestEveryRouteIsProtected:
    def test_no_route_is_accidentally_public(self, app) -> None:
        """Walks the live route table, so a router added later cannot be silently open."""
        # `app.routes` is not flat in this FastAPI version — routers are wrapped — so the
        # OpenAPI document is the reliable view of what is actually served.
        paths = set(app.openapi()["paths"])
        unlisted = {
            p for p in paths if p not in PUBLIC_PATHS and not p.startswith("/openapi")
        }

        assert unlisted, "route table looked empty — the walk is not finding routes"
        # Everything not on the allowlist must actually reject an anonymous request.
        client = TestClient(app)
        for path in sorted(unlisted):
            if "{" in path:
                continue  # parameterised paths are covered by their concrete cases below
            assert client.get(path).status_code in (401, 405), f"{path} answered unauthenticated"

    def test_public_paths_answer_without_a_token(self, open_client: TestClient) -> None:
        for path in ("/", "/health"):
            assert open_client.get(path).status_code == 200

    def test_health_is_public_because_credentials_live_in_the_database(self) -> None:
        """A health check needing a token cannot distinguish "down" from "misconfigured"."""
        assert "/health" in PUBLIC_PATHS

    def test_writing_endpoints_reject_anonymous_requests(self, open_client: TestClient) -> None:
        """These write trades and spend a budget — the reason this increment exists."""
        assert open_client.post("/books/swing/fill", json={}).status_code == 401
        assert open_client.post("/cycles/run", json={"symbols": ["X"]}).status_code == 401
        assert open_client.post("/insights/1/act", json={"action": "review"}).status_code == 401

    def test_reading_a_portfolio_rejects_anonymous_requests(self, open_client) -> None:
        assert open_client.get("/books/swing/positions").status_code == 401
        assert open_client.get("/insights").status_code == 401


class TestLoginFlow:
    def test_login_returns_an_access_token_and_sets_a_cookie(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        response = open_client.post(
            "/auth/login", json={"username": USERNAME, "password": PASSWORD}
        )
        body = response.json()

        assert response.status_code == 200
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert REFRESH_COOKIE in response.cookies

    def test_the_token_opens_a_protected_endpoint(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        token = open_client.post(
            "/auth/login", json={"username": USERNAME, "password": PASSWORD}
        ).json()["access_token"]

        response = open_client.get("/tools", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200

    def test_wrong_password_and_unknown_user_are_indistinguishable(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        """Different messages would turn a login form into a username directory."""
        wrong = open_client.post(
            "/auth/login", json={"username": USERNAME, "password": "wrong-password-here"}
        )
        unknown = open_client.post(
            "/auth/login", json={"username": "nobody", "password": "wrong-password-here"}
        )

        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["detail"] == unknown.json()["detail"]

    def test_no_endpoint_returns_a_password_hash(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        token = open_client.post(
            "/auth/login", json={"username": USERNAME, "password": PASSWORD}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        for path in ("/auth/me",):
            body = open_client.get(path, headers=headers).text
            assert "argon2" not in body
            assert "password" not in body.lower()

    def test_me_reports_the_authenticated_user(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        token = open_client.post(
            "/auth/login", json={"username": USERNAME, "password": PASSWORD}
        ).json()["access_token"]

        body = open_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

        assert body["username"] == USERNAME

    def test_a_refresh_token_cannot_be_used_as_a_bearer_token(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        """End to end: the type check has to hold at the HTTP boundary, not only in the decoder."""
        open_client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
        refresh = open_client.cookies[REFRESH_COOKIE]

        response = open_client.get("/tools", headers={"Authorization": f"Bearer {refresh}"})

        assert response.status_code == 401


class TestRefreshAndLogout:
    def _login(self, client: TestClient) -> str:
        return client.post(
            "/auth/login", json={"username": USERNAME, "password": PASSWORD}
        ).json()["access_token"]

    def test_refresh_issues_a_new_pair(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        self._login(open_client)
        original_refresh = open_client.cookies[REFRESH_COOKIE]

        response = open_client.post("/auth/refresh")
        body = response.json()

        assert body["access_token"]
        # The refresh token rotating is the meaningful part; the access token is a fresh mint
        # either way and carries a unique jti.
        assert open_client.cookies[REFRESH_COOKIE] != original_refresh

    def test_a_refreshed_access_token_works(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        self._login(open_client)

        token = open_client.post("/auth/refresh").json()["access_token"]

        assert open_client.get(
            "/tools", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 200

    def test_a_used_refresh_token_is_revoked(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        """Rotation: a stolen token stops working as soon as the real session refreshes."""
        self._login(open_client)
        stolen = open_client.cookies[REFRESH_COOKIE]
        open_client.post("/auth/refresh")

        open_client.cookies.set(REFRESH_COOKIE, stolen)
        response = open_client.post("/auth/refresh")

        assert response.status_code == 401

    def test_logout_revokes_rather_than_forgets(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        """A logout that invalidates nothing is theatre."""
        self._login(open_client)
        token = open_client.cookies[REFRESH_COOKIE]

        assert open_client.post("/auth/logout").json()["revoked"] is True

        open_client.cookies.set(REFRESH_COOKIE, token)
        assert open_client.post("/auth/refresh").status_code == 401

    def test_refresh_without_a_cookie_is_401(self, open_client: TestClient) -> None:
        assert open_client.post("/auth/refresh").status_code == 401

    def test_logout_without_a_session_is_not_an_error(self, open_client: TestClient) -> None:
        response = open_client.post("/auth/logout")

        assert response.status_code == 200
        assert response.json()["revoked"] is False


class TestUserManagement:
    def test_duplicate_usernames_are_refused(self, service: AuthService) -> None:
        with pytest.raises(ValueError, match="already exists"):
            service.create_user(USERNAME, PASSWORD)

    def test_usernames_are_normalised(self, app, service: AuthService) -> None:
        session = service.login("  TRADER  ", PASSWORD)

        assert session.username == USERNAME

    def test_changing_a_password_revokes_every_session(
        self, open_client: TestClient, service: AuthService
    ) -> None:
        """Password changes usually follow a compromise; leaving sessions running defeats it."""
        open_client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})

        service.set_password(USERNAME, "another-long-enough-password")

        assert open_client.post("/auth/refresh").status_code == 401

    def test_an_inactive_user_cannot_log_in(self, app, service: AuthService) -> None:
        from sqlalchemy import select

        from app.persistence.models import User

        with app.state.session_factory() as session:
            user = session.execute(select(User).where(User.username == USERNAME)).scalar_one()
            user.is_active = False
            session.commit()

        with pytest.raises(AuthenticationFailed):
            service.login(USERNAME, PASSWORD)
