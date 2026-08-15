"""The health seam.

``/health`` is the only endpoint the web shell consumes in the bootstrap change, so these
tests are what stop a silently-broken seam from reaching the UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import PROVIDERS, Settings
from app.main import create_app


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


class TestHealthyState:
    def test_reports_every_seam(self, client: TestClient) -> None:
        body = client.get("/health").json()

        assert set(body) >= {"status", "app", "database", "llm", "observability"}
        assert body["database"]["connected"] is True
        assert body["database"]["migrations_current"] is True
        assert body["database"]["current_revision"] == body["database"]["head_revision"]
        assert [p["name"] for p in body["llm"]["providers"]] == list(PROVIDERS)

    def test_ok_when_database_current_and_a_provider_configured(
        self, migrated_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        response = _client(Settings(app_env="test", database_url=migrated_url)).get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestDegradedStatesAreReportedNotHidden:
    def test_unreachable_database_still_answers_200(self, tmp_path: Path) -> None:
        unreachable = f"sqlite+pysqlite:///{tmp_path / 'no-such-dir' / 'x.db'}"

        response = _client(Settings(app_env="test", database_url=unreachable)).get("/health")
        body = response.json()

        assert response.status_code == 200
        assert body["status"] == "degraded"
        assert body["database"]["connected"] is False
        assert body["database"]["reason"]

    def test_unmigrated_database_reports_both_revisions(self, sqlite_url: str) -> None:
        """Reachable, but migrations never ran."""
        response = _client(Settings(app_env="test", database_url=sqlite_url)).get("/health")
        body = response.json()

        assert response.status_code == 200
        assert body["database"]["connected"] is True
        assert body["database"]["migrations_current"] is False
        assert body["database"]["head_revision"] == "0001_initial"
        assert body["status"] == "degraded"

    def test_no_provider_configured_is_degraded(self, migrated_url: str) -> None:
        settings = Settings(
            app_env="test",
            database_url=migrated_url,
            llm_default_task_model="anthropic/claude-sonnet-5",  # routed, but no key
        )

        body = _client(settings).get("/health").json()

        assert body["llm"]["any_configured"] is False
        assert all(p["configured"] is False for p in body["llm"]["providers"])
        assert body["status"] == "degraded"

    def test_routing_a_task_to_a_local_provider_counts_as_configured(
        self, migrated_url: str
    ) -> None:
        settings = Settings(
            app_env="test",
            database_url=migrated_url,
            llm_route={"narrative": "lemonade/qwen3-8b"},
        )

        body = _client(settings).get("/health").json()
        lemonade = next(p for p in body["llm"]["providers"] if p["name"] == "lemonade")

        assert lemonade["configured"] is True
        assert body["llm"]["any_configured"] is True


class TestProbing:
    def test_reachability_is_null_without_probe(self, client: TestClient) -> None:
        body = client.get("/health").json()

        assert all(p["reachable"] is None for p in body["llm"]["providers"])

    def test_configured_but_unreachable_local_provider(self, migrated_url: str) -> None:
        settings = Settings(
            app_env="test",
            database_url=migrated_url,
            # Nothing is listening here.
            llm_provider_base_url={"lemonade": "http://127.0.0.1:9/v1"},
        )

        body = _client(settings).get("/health?probe=true").json()
        lemonade = next(p for p in body["llm"]["providers"] if p["name"] == "lemonade")

        assert lemonade["configured"] is True
        assert lemonade["reachable"] is False

    def test_hosted_providers_are_never_probed(
        self, migrated_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Probing a hosted provider would mean a billable request."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        body = (
            _client(Settings(app_env="test", database_url=migrated_url))
            .get("/health?probe=true")
            .json()
        )
        anthropic = next(p for p in body["llm"]["providers"] if p["name"] == "anthropic")

        assert anthropic["configured"] is True
        assert anthropic["reachable"] is None


class TestNoCredentialLeakage:
    def test_secrets_absent_from_response(
        self, migrated_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = "sk-ant-super-secret-value"
        monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
        settings = Settings(
            app_env="test",
            database_url=migrated_url,
            langfuse_public_key="pk-leak-me",
            langfuse_secret_key="sk-leak-me",
        )

        raw = _client(settings).get("/health").text

        assert secret not in raw
        assert "pk-leak-me" not in raw
        assert "sk-leak-me" not in raw
        assert migrated_url not in raw


class TestCors:
    def test_configured_origin_allowed(self, migrated_url: str) -> None:
        settings = Settings(
            app_env="test", database_url=migrated_url, web_origin="http://localhost:3000"
        )

        response = _client(settings).get("/health", headers={"Origin": "http://localhost:3000"})

        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_unconfigured_origin_not_allowed(self, migrated_url: str) -> None:
        settings = Settings(
            app_env="test", database_url=migrated_url, web_origin="http://localhost:3000"
        )

        response = _client(settings).get("/health", headers={"Origin": "http://evil.example"})

        assert response.headers.get("access-control-allow-origin") != "http://evil.example"
