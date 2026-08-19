"""Configuration precedence and validation.

These map directly onto the ``platform-configuration`` spec. The precedence chain is the
single most-repeated source of confusion in the predecessor, so it is asserted rather than
assumed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def _write_env(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


class TestPrecedence:
    def test_environment_overrides_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = _write_env(tmp_path, "LLM_DEFAULT_TASK_MODEL=anthropic/claude-sonnet-5\n")
        monkeypatch.setenv("LLM_DEFAULT_TASK_MODEL", "openai/gpt-4o")

        settings = Settings(_env_file=env_file)

        assert settings.llm_default_task_model == "openai/gpt-4o"

    def test_constructor_overrides_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENV", "prod")

        assert Settings(app_env="test").app_env == "test"

    def test_env_file_used_when_environment_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = _write_env(tmp_path, "LLM_DEFAULT_TASK_MODEL=gemini/gemini-2.0-flash\n")
        monkeypatch.delenv("LLM_DEFAULT_TASK_MODEL", raising=False)

        assert Settings(_env_file=env_file).llm_default_task_model == "gemini/gemini-2.0-flash"

    def test_default_applies_when_nothing_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("APP_ENV", raising=False)

        assert Settings(_env_file=None).app_env == "dev"


class TestValidation:
    def test_malformed_number_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "not-a-number")

        with pytest.raises(ValidationError, match="llm_timeout_seconds"):
            Settings(_env_file=None)

    def test_unknown_environment_rejected_and_lists_permitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_ENV", "production")

        with pytest.raises(ValidationError) as excinfo:
            Settings(_env_file=None)

        message = str(excinfo.value)
        assert "dev" in message and "test" in message and "prod" in message

    def test_non_positive_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(llm_timeout_seconds=0)


class TestTaskRouting:
    def test_nested_route_override_leaves_other_tasks_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_DEFAULT_TASK_MODEL", "anthropic/claude-sonnet-5")
        monkeypatch.setenv("LLM_ROUTE__NARRATIVE", "ollama/llama3.1")

        settings = Settings(_env_file=None)

        assert settings.model_for_task("narrative") == "ollama/llama3.1"
        assert settings.model_for_task("research") == "anthropic/claude-sonnet-5"

    def test_route_lookup_is_case_insensitive(self) -> None:
        settings = Settings(llm_route={"NARRATIVE": "ollama/llama3.1"}, _env_file=None)

        assert settings.model_for_task("narrative") == "ollama/llama3.1"
        assert settings.model_for_task("NaRrAtIvE") == "ollama/llama3.1"

    def test_provider_for_task_strips_model(self) -> None:
        settings = Settings(llm_route={"narrative": "lemonade/qwen3-8b"}, _env_file=None)

        assert settings.provider_for_task("narrative") == "lemonade"

    def test_nested_base_url_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER_BASE_URL__LEMONADE", "http://localhost:9000/v1")

        assert Settings(_env_file=None).base_url_for("lemonade") == "http://localhost:9000/v1"


class TestNoRuntimeMutableConfig:
    def test_settings_resolve_without_a_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Construction must not depend on the database being reachable."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody@203.0.113.1:5432/none")

        settings = Settings(_env_file=None)

        assert settings.database_url.startswith("postgresql")
        assert settings.app_version  # every field resolved without a connection

    def test_observability_requires_both_halves(self) -> None:
        assert not Settings(langfuse_public_key="pk", _env_file=None).observability_configured
        assert not Settings(langfuse_secret_key="sk", _env_file=None).observability_configured
        assert Settings(
            langfuse_public_key="pk", langfuse_secret_key="sk", _env_file=None
        ).observability_configured


class TestLocalModelLatency:
    def test_local_timeout_defaults_higher_than_hosted(self) -> None:
        """Tuning for hosted latency must not make local providers unusable."""
        settings = Settings(app_env="test", _env_file=None)

        assert settings.llm_local_timeout_seconds > settings.llm_timeout_seconds

    def test_non_positive_local_timeout_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(app_env="test", llm_local_timeout_seconds=0, _env_file=None)


class TestPowerShellScriptsAreReadableByPowerShell:
    """PowerShell 5.1 reads a BOM-less file as ANSI, not UTF-8.

    A UTF-8 em-dash then arrives as three cp1252 characters, one of which is a smart quote —
    which unbalances the next string literal and fails the whole script with a parse error
    pointing at an unrelated line. `run-local.ps1` shipped broken exactly this way.
    """

    @staticmethod
    def _scripts() -> list:
        from pathlib import Path

        return list((Path(__file__).resolve().parents[2]).glob("*.ps1"))

    def test_scripts_exist_to_check(self) -> None:
        assert self._scripts(), "no PowerShell scripts found — has the layout changed?"

    def test_no_script_contains_a_non_ascii_character(self) -> None:
        for script in self._scripts():
            body = script.read_bytes()
            if body.startswith(b"\xef\xbb\xbf"):
                body = body[3:]
            offenders = [b for b in body if b > 127]
            assert not offenders, f"{script.name} has {len(offenders)} non-ASCII bytes"

    def test_every_script_carries_a_utf8_bom(self) -> None:
        """Belt and braces: the BOM makes a future non-ASCII edit survive rather than break."""
        for script in self._scripts():
            assert script.read_bytes().startswith(b"\xef\xbb\xbf"), f"{script.name} has no BOM"
