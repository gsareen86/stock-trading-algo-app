"""The tool discovery endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import authed_client


class TestSkillsEndpoint:
    def test_lists_seed_tools_with_their_contracts(self, client: TestClient) -> None:
        body = client.get("/tools").json()

        names = {s["name"] for s in body["tools"]}
        assert names == {"news_research", "event_calendar", "filings_scan", "peer_compare"}
        assert body["count"] == 4
        for tool in body["tools"]:
            assert tool["summary"]
            assert tool["input_schema"]["type"] == "object"

    def test_no_load_failures(self, client: TestClient) -> None:
        assert client.get("/tools").json()["load_failures"] == []

    def test_handler_is_not_exposed(self, client: TestClient) -> None:
        """An import path tells a reader how to reach code this API never meant to expose."""
        raw = client.get("/tools").text

        assert "handler" not in raw
        assert "app.tools." not in raw

    def test_load_failures_are_surfaced(self, migrated_url: str, monkeypatch) -> None:
        import importlib

        from app.core.settings import Settings
        from app.main import create_app

        real = importlib.import_module

        def explode(name, *args, **kwargs):
            if name.endswith("filings_scan.tool"):
                raise ImportError("simulated breakage")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", explode)
        app = create_app(Settings(app_env="test", database_url=migrated_url))

        body = authed_client(app).get("/tools").json()

        assert body["count"] == 3
        assert any("filings_scan" in f["module"] for f in body["load_failures"])
