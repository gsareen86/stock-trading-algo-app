"""Langfuse wiring.

Observability attaches **at the gateway**, not at call sites, so no feature module ever
knows it exists. That is what makes it honest: nothing can quietly skip tracing by forgetting
a decorator.

With no credentials configured the callback is simply never registered — tracing degrades to
off and calls still work. That matters because most deployments of this app run entirely on
local models with no Langfuse account at all.
"""

from __future__ import annotations

import logging
import os
import uuid

from app.core.settings import Settings

log = logging.getLogger(__name__)

_registered = False


def new_trace_id() -> str:
    """Trace ids are minted here rather than read back from the provider.

    Generating our own means the id exists before the request is made, so it can be attached
    to a persisted ``Verdict`` even if the call subsequently fails — and it survives the
    provider not returning one at all, which is the norm for local models.
    """
    return uuid.uuid4().hex


def configure(settings: Settings) -> bool:
    """Register Langfuse as a LiteLLM callback. Returns whether tracing is active.

    Idempotent: LiteLLM's callback lists are module-global, so repeated registration would
    duplicate every span.
    """
    global _registered

    if not settings.observability_configured:
        return False
    if _registered:
        return True

    try:
        import litellm
    except ImportError:
        log.warning("litellm not installed; LLM tracing disabled")
        return False

    # LiteLLM's Langfuse integration reads credentials from the environment.
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key or "")
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key or "")
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)

    try:
        if "langfuse" not in (litellm.success_callback or []):
            litellm.success_callback = [*(litellm.success_callback or []), "langfuse"]
        if "langfuse" not in (litellm.failure_callback or []):
            litellm.failure_callback = [*(litellm.failure_callback or []), "langfuse"]
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("could not register Langfuse callback: %s", exc)
        return False

    _registered = True
    log.info("Langfuse tracing enabled (host=%s)", settings.langfuse_host)
    return True


def reset() -> None:
    """Test hook — clears the module-global registration latch."""
    global _registered
    _registered = False
