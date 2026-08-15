"""Typed application settings.

**One precedence chain**, highest priority first:

1. Explicit constructor arguments (tests only)
2. Process environment variables
3. The ``.env`` file
4. Field defaults declared here

This ordering is pydantic-settings' native one; it is stated explicitly because the
predecessor's single worst tracking pain was a setting that could arrive from code, ``.env``
or a live database row with no documented winner.

**Nothing here is read from the database.** If a value needs to change at runtime it becomes
an explicit domain concept with its own table and its own spec, not a config knob.

Settings are *injected* (see ``app.api.deps.get_settings``), never imported as a
module-level singleton — that is what makes the precedence chain testable.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The seven providers the gateway supports. The last four are OpenAI-compatible local
# servers and need no adapter code — only a base URL.
Provider = Literal[
    "anthropic",
    "gemini",
    "openai",
    "ollama",
    "lm_studio",
    "llama_cpp",
    "lemonade",
]

PROVIDERS: tuple[Provider, ...] = (
    "anthropic",
    "gemini",
    "openai",
    "ollama",
    "lm_studio",
    "llama_cpp",
    "lemonade",
)

#: Environment variable holding each provider's credential. Local servers need none.
PROVIDER_CREDENTIAL_ENV: dict[Provider, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": None,
    "lm_studio": None,
    "llama_cpp": None,
    "lemonade": None,
}


class Settings(BaseSettings):
    """Every setting the platform reads. Validation failures raise at construction."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: Literal["dev", "test", "prod"] = "dev"
    app_version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    #: Origin allowed to call this API cross-origin. The browser is not a database
    #: client here — it reaches data only through this API.
    web_origin: str = "http://localhost:3000"

    # ── Persistence ───────────────────────────────────────────────────────────
    #: SQLAlchemy URL. SQLite for dev/test, Supabase Postgres for prod. The same
    #: models and migrations serve both.
    database_url: str = "sqlite+pysqlite:///./trading.db"

    # ── LLM gateway ───────────────────────────────────────────────────────────
    #: Model used for any task without an explicit route, as ``<provider>/<model>``.
    llm_default_task_model: str = "anthropic/claude-sonnet-5"

    #: Per-task overrides. ``LLM_ROUTE__NARRATIVE=ollama/llama3.1`` reroutes exactly one
    #: task, which is what lets narratives run locally while research runs on a frontier
    #: model — with no code change.
    llm_route: dict[str, str] = Field(default_factory=dict)

    #: Ordered fallback chain per task, comma-separated, e.g.
    #: ``LLM_FALLBACK__NARRATIVE=anthropic/claude-sonnet-5,openai/gpt-4o``. Tried in order
    #: after the primary route fails. A task with no entry keeps single-target behaviour.
    llm_fallback: dict[str, str] = Field(default_factory=dict)

    #: Base URLs for OpenAI-compatible servers, e.g.
    #: ``LLM_PROVIDER_BASE_URL__LEMONADE=http://localhost:8000/v1``.
    llm_provider_base_url: dict[str, str] = Field(default_factory=dict)

    #: Spend cap for the current IST day, in USD. Unset means unlimited. Only calls whose
    #: provider reports a cost count against it — local models are free and stay available
    #: after the cap is reached.
    llm_daily_budget_usd: Annotated[float | None, Field(gt=0)] = None

    llm_timeout_seconds: Annotated[float, Field(gt=0)] = 30.0
    llm_max_retries: Annotated[int, Field(ge=0)] = 2

    #: Consecutive rate-limit failures before the breaker opens for one provider.
    llm_breaker_threshold: Annotated[int, Field(ge=1)] = 3
    llm_breaker_cooldown_seconds: Annotated[float, Field(gt=0)] = 600.0

    #: Content-hash disk cache for prompts that are stable by construction.
    llm_cache_enabled: bool = True
    llm_cache_dir: str = "./.cache/llm"

    # ── Observability ─────────────────────────────────────────────────────────
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @field_validator("llm_route", "llm_provider_base_url", "llm_fallback", mode="after")
    @classmethod
    def _lowercase_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Normalise keys so ``LLM_ROUTE__NARRATIVE`` and ``llm_route={'narrative':...}``
        resolve identically regardless of how they were supplied."""
        return {k.lower(): v for k, v in value.items()}

    # ── Derived accessors ─────────────────────────────────────────────────────
    def model_for_task(self, task: str) -> str:
        """Resolve a task name to a ``<provider>/<model>`` string.

        Callers name the *job*, never the model — the mapping is configuration.
        """
        return self.llm_route.get(task.lower(), self.llm_default_task_model)

    def provider_for_task(self, task: str) -> str:
        """The provider prefix a task's *primary* rung dispatches to."""
        return self.model_for_task(task).split("/", 1)[0]

    def chain_for_task(self, task: str) -> list[str]:
        """Ordered ``<provider>/<model>`` targets for a task: primary first, then fallbacks.

        Duplicates are dropped while preserving order — repeating a target would mean
        retrying an already-failed rung, which the Router's own retries already cover.
        """
        chain = [self.model_for_task(task)]
        raw = self.llm_fallback.get(task.lower(), "")
        chain.extend(part.strip() for part in raw.split(",") if part.strip())

        seen: set[str] = set()
        return [target for target in chain if not (target in seen or seen.add(target))]

    def base_url_for(self, provider: str) -> str | None:
        """Configured base URL for an OpenAI-compatible provider, if any."""
        return self.llm_provider_base_url.get(provider.lower())

    @property
    def observability_configured(self) -> bool:
        """Langfuse tracing is on only when both halves of the credential are present."""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")
