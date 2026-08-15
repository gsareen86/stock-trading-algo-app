"""The skill discovery endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestSkillsEndpoint:
    def test_lists_seed_skills_with_their_contracts(self, client: TestClient) -> None:
        body = client.get("/skills").json()

        names = {s["name"] for s in body["skills"]}
        assert names == {"news_research", "event_calendar", "filings_scan", "peer_compare"}
        assert body["count"] == 4
        for skill in body["skills"]:
            assert skill["summary"]
            assert skill["input_schema"]["type"] == "object"

    def test_no_load_failures(self, client: TestClient) -> None:
        assert client.get("/skills").json()["load_failures"] == []

    def test_handler_is_not_exposed(self, client: TestClient) -> None:
        """An import path tells a reader how to reach code this API never meant to expose."""
        raw = client.get("/skills").text

        assert "handler" not in raw
        assert "app.skills." not in raw

    def test_load_failures_are_surfaced(self, migrated_url: str, monkeypatch) -> None:
        import importlib

        from app.core.settings import Settings
        from app.main import create_app

        real = importlib.import_module

        def explode(name, *args, **kwargs):
            if name.endswith("filings_scan.skill"):
                raise ImportError("simulated breakage")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", explode)
        app = create_app(Settings(app_env="test", database_url=migrated_url))

        body = TestClient(app).get("/skills").json()

        assert body["count"] == 3
        assert any("filings_scan" in f["module"] for f in body["load_failures"])
