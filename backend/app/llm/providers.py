"""Provider configuration and status.

Seven providers, no adapter code. The three local servers — llama.cpp, LM Studio's raw
endpoint and AMD Lemonade — are OpenAI-compatible, so they are reached by pointing the
``openai`` provider at a base URL rather than by writing bespoke clients.

Status distinguishes **configured** (a credential or base URL is present) from **reachable**
(something answered). "The key is set" and "the server is up" fail differently, and a local
Ollama being down is not the same problem as an absent Anthropic key.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from app.core.settings import PROVIDER_CREDENTIAL_ENV, PROVIDERS, Settings

log = logging.getLogger(__name__)

#: Default endpoints for the local, OpenAI-compatible servers.
DEFAULT_LOCAL_BASE_URL: dict[str, str] = {
    "ollama": "http://localhost:11434",
    "lm_studio": "http://localhost:1234/v1",
    "llama_cpp": "http://localhost:8080/v1",
    "lemonade": "http://localhost:8000/api/v1",
}

#: Providers whose credential is a base URL rather than an API key.
LOCAL_PROVIDERS: frozenset[str] = frozenset(DEFAULT_LOCAL_BASE_URL)


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    name: str
    configured: bool
    #: ``None`` when no probe was performed — reachability costs a network round trip, so
    #: it is opt-in rather than charged to every health check.
    reachable: bool | None = None
    detail: str | None = None


def resolve_base_url(settings: Settings, provider: str) -> str | None:
    """Explicit configuration wins; local providers fall back to their default endpoint."""
    configured = settings.base_url_for(provider)
    if configured:
        return configured
    return DEFAULT_LOCAL_BASE_URL.get(provider)


def _is_routed(settings: Settings, provider: str) -> bool:
    """True when any task, or the default, dispatches to this provider."""
    targets = [settings.llm_default_task_model, *settings.llm_route.values()]
    return any(t.partition("/")[0] == provider for t in targets)


def is_configured(settings: Settings, provider: str) -> bool:
    """Whether someone actually told us about this provider.

    A hosted provider needs its API key. A local one counts as configured when its base URL
    was set explicitly *or* a task routes to it — deliberately **not** merely because
    :data:`DEFAULT_LOCAL_BASE_URL` supplies a fallback endpoint. That default exists so
    dispatch works without ceremony; treating it as configuration would report all four local
    providers as present on every machine and make ``any_configured`` permanently true, which
    would render the health status meaningless.
    """
    if provider in LOCAL_PROVIDERS:
        return settings.base_url_for(provider) is not None or _is_routed(settings, provider)
    env_var = PROVIDER_CREDENTIAL_ENV.get(provider)  # type: ignore[arg-type]
    return bool(env_var and os.environ.get(env_var))


async def probe(settings: Settings, provider: str, timeout: float = 2.0) -> bool | None:
    """Best-effort reachability check for a local provider.

    Returns ``None`` for hosted providers: probing them would mean a billable request, and an
    API key's validity is not something a health check should spend money to establish.
    """
    if provider not in LOCAL_PROVIDERS:
        return None
    base = resolve_base_url(settings, provider)
    if not base:
        return False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(base.rstrip("/") + "/models")
            return response.status_code < 500
    except Exception:
        return False


async def status_all(settings: Settings, *, do_probe: bool = False) -> list[ProviderStatus]:
    """Status for every supported provider, in a stable order."""
    out: list[ProviderStatus] = []
    for provider in PROVIDERS:
        configured = is_configured(settings, provider)
        reachable = await probe(settings, provider) if (do_probe and configured) else None
        detail = None
        if not configured:
            if provider in LOCAL_PROVIDERS:
                detail = "no base URL set and no task routed here"
            else:
                detail = f"{PROVIDER_CREDENTIAL_ENV.get(provider)} not set"  # type: ignore[arg-type]
        out.append(
            ProviderStatus(name=provider, configured=configured, reachable=reachable, detail=detail)
        )
    return out
