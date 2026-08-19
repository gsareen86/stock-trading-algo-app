"""Typed application settings.

**One precedence chain**, highest priority first:

1. Explicit constructor arguments (tests only)
2. Process environment variables
3. The ``.env`` file
4. Field defaults declared here

This ordering is pydantic-settings' native one; it is stated explicitly because the
single worst configuration failure is a setting that can arrive from code, ``.env``
or a live database row with no documented winner.

**Nothing here is read from the database.** If a value needs to change at runtime it becomes
an explicit domain concept with its own table and its own spec, not a config knob.

Settings are *injected* (see ``app.api.deps.get_settings``), never imported as a
module-level singleton — that is what makes the precedence chain testable.
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.money import DEFAULT_USD_INR_RATE, inr_to_usd

#: RFC 7518 §3.2 — an HS256 key below the hash output length weakens the signature.
MIN_SECRET_KEY_LENGTH = 32

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

    # ── Money ─────────────────────────────────────────────────────────────────
    #: Rupees to the dollar, used to report LLM vendor costs in the platform's own currency.
    #: Operator-set rather than fetched: see ``app.core.money`` for why a live rate would be
    #: false precision on a figure this small.
    usd_inr_rate: Annotated[float, Field(gt=0)] = DEFAULT_USD_INR_RATE

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

    #: Spend cap for the current IST day, in **rupees**. Unset means unlimited. Only calls
    #: whose provider reports a cost count against it — local models are free and stay
    #: available after the cap is reached.
    #:
    #: Rupees, not dollars, because this is a number the operator chooses rather than one a
    #: provider hands us. It is converted to the ledger's currency for comparison; see
    #: ``daily_budget_usd`` and ``app.core.money``.
    llm_daily_budget_inr: Annotated[float | None, Field(gt=0)] = None

    #: Per-call timeout for **hosted** providers. Generous for a frontier model answering over
    #: the network; a request still running after this is a hung one, not a slow one.
    llm_timeout_seconds: Annotated[float, Field(gt=0)] = 30.0

    #: Per-call timeout for **local** providers, which are an order of magnitude slower and
    #: cost nothing to wait for. A 12B model writing a narrative from a dozen evidence rows
    #: takes minutes on consumer hardware — under the hosted timeout every such call failed,
    #: and the feature looked broken rather than slow. Waiting is the right default when the
    #: alternative is no answer and the wait is free.
    llm_local_timeout_seconds: Annotated[float, Field(gt=0)] = 300.0
    llm_max_retries: Annotated[int, Field(ge=0)] = 2

    #: Consecutive rate-limit failures before the breaker opens for one provider.
    llm_breaker_threshold: Annotated[int, Field(ge=1)] = 3
    llm_breaker_cooldown_seconds: Annotated[float, Field(gt=0)] = 600.0

    #: Content-hash disk cache for prompts that are stable by construction.
    llm_cache_enabled: bool = True
    llm_cache_dir: str = "./.cache/llm"

    # ── Agents ────────────────────────────────────────────────────────────────
    #: External MCP servers whose tools the research step may call, as
    #: ``MCP_SERVER__KITE=https://mcp.kite.trade/mcp``. Their tools are offered to the model
    #: alongside the local registry but are never registered in it: this platform cannot
    #: promise an output schema or an evidence-shaped result for someone else's server.
    mcp_server: dict[str, str] = Field(default_factory=dict)

    #: Bound on the research step's tool-calling loop. An agent that calls tools until it feels
    #: finished is one that occasionally never finishes.
    research_max_tool_rounds: Annotated[int, Field(ge=0, le=10)] = 3

    # ── Authentication ────────────────────────────────────────────────────────
    #: JWT signing key. **There is deliberately no usable default.** A platform that boots with
    #: a well-known signing key is one where every token is forgeable by anyone who has read
    #: this repository. In prod, absence is a startup failure; in dev and test a random secret
    #: is generated per process, so tokens do not survive a restart — mildly annoying, and
    #: impossible to mistake for a production configuration.
    auth_secret_key: str | None = None

    #: Short, because a JWT cannot be un-issued: this is the window during which a logged-out
    #: session still works.
    auth_access_token_minutes: Annotated[int, Field(gt=0, le=1440)] = 30

    #: Long, because it is revocable — checked against a stored row on every use.
    auth_refresh_token_days: Annotated[int, Field(gt=0, le=90)] = 14

    #: Set only when serving the web app over HTTPS. The refresh cookie is httpOnly either way.
    auth_cookie_secure: bool = False

    # ── Observability ─────────────────────────────────────────────────────────
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @field_validator(
        "llm_route", "llm_provider_base_url", "llm_fallback", "mcp_server", mode="after"
    )
    @classmethod
    def _lowercase_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Normalise keys so ``LLM_ROUTE__NARRATIVE`` and ``llm_route={'narrative':...}``
        resolve identically regardless of how they were supplied."""
        return {k.lower(): v for k, v in value.items()}

    #: Retired keys whose old value would be silently misread under the current meaning.
    #: ``extra="ignore"`` would drop them without a word, so they are rejected by name.
    _RETIRED_KEYS = {
        # Deliberately ASCII: this surfaces on a console at startup, and a Windows codepage
        # renders an em-dash as a replacement character in the one message meant to be clear.
        "LLM_DAILY_BUDGET_USD": (
            "LLM_DAILY_BUDGET_INR. The cap is now in rupees; a value set in dollars would "
            "otherwise be read as rupees and cut your real cap by roughly the exchange rate."
        ),
    }

    @model_validator(mode="after")
    def _reject_retired_keys(self) -> Settings:
        for old, guidance in self._RETIRED_KEYS.items():
            if old in os.environ:
                raise ValueError(f"{old} is no longer supported; use {guidance}")
        return self

    @model_validator(mode="after")
    def _require_a_real_signing_key(self) -> Settings:
        """No usable default, ever — and a loud failure in prod rather than a quiet one.

        Generating a key in dev is safe precisely because it does not persist: a restart
        invalidates every token, which is impossible to mistake for a working production
        configuration. Falling back to a constant would be the opposite.
        """
        if self.auth_secret_key:
            if len(self.auth_secret_key) < MIN_SECRET_KEY_LENGTH:
                # RFC 7518 §3.2: an HS256 key shorter than the hash output weakens the
                # signature. PyJWT warns; refusing is better than a warning nobody reads.
                raise ValueError(
                    f"AUTH_SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters"
                )
            return self
        if self.app_env == "prod":
            raise ValueError(
                "AUTH_SECRET_KEY must be set in prod. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        object.__setattr__(self, "auth_secret_key", secrets.token_urlsafe(48))
        return self

    # ── Derived accessors ─────────────────────────────────────────────────────
    @property
    def daily_budget_usd(self) -> float | None:
        """The rupee cap in the ledger's currency.

        `DailyBudget` sums a dollar column, so the comparison happens in dollars; converting
        the threshold once here is cheaper and clearer than converting every sum.
        """
        return inr_to_usd(self.llm_daily_budget_inr, self.usd_inr_rate)

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
