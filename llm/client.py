"""
Shared Anthropic client + helpers for all LLM-powered features.

Centralises:
  - Lazy client init (so missing API key doesn't break imports / tests)
  - JSON-only structured output via output_config.format
  - Per-call retry budget (SDK already retries 429/5xx with backoff)
  - Tiny disk cache for stable inputs (sentiment-by-text-hash, events-by-day)

We intentionally do NOT raise on API errors — every call returns None on
failure and lets the caller fall back to its existing path. A trading cycle
must never crash because the LLM gateway is down.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from config import (
    CACHE_DIR,
    LLM_DEFAULT_MODEL,
    LLM_MAX_RETRIES,
    LLM_REQUEST_TIMEOUT_S,
)

log = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()
_LLM_CACHE_DIR = Path(CACHE_DIR) / "llm"
_LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_client():
    """Lazy-initialised anthropic client. Returns None if SDK or key missing."""
    global _client
    if _client is not None:
        return _client if _client is not False else None
    with _client_lock:
        if _client is None:
            try:
                import anthropic  # lazy import — keeps optional dependency optional
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    log.warning("ANTHROPIC_API_KEY not set — LLM features disabled")
                    _client = False
                    return None
                _client = anthropic.Anthropic(
                    api_key=api_key,
                    timeout=LLM_REQUEST_TIMEOUT_S,
                    max_retries=LLM_MAX_RETRIES,
                )
            except ImportError:
                log.warning("anthropic package not installed — LLM features disabled")
                _client = False
                return None
    return _client if _client is not False else None


def call_json(
    *,
    prompt: str,
    schema: dict,
    system: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 512,
    cache_key: Optional[str] = None,
) -> Optional[dict]:
    """One-shot Claude call constrained to a JSON schema.

    Returns the parsed dict, or None on any failure (caller falls back).

    `cache_key`: if given, response is cached on disk. Use stable hashes only —
    e.g. sha256(text) for sentiment. Don't cache time-sensitive inputs.
    """
    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    client = get_client()
    if client is None:
        return None

    model = model or LLM_DEFAULT_MODEL
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {
            "format": {"type": "json_schema", "schema": schema},
        },
    }
    if system:
        kwargs["system"] = system

    try:
        t0 = time.monotonic()
        response = client.messages.create(**kwargs)
    except Exception as e:
        log.warning("LLM call failed (%s) — caller will fall back", e)
        return None

    try:
        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
    except (StopIteration, json.JSONDecodeError, AttributeError) as e:
        log.warning("LLM response parse failed: %s", e)
        return None

    log.debug("LLM call ok in %.2fs (%s, %d output tokens)",
              time.monotonic() - t0, model,
              getattr(response.usage, "output_tokens", -1))

    if cache_key:
        _cache_put(cache_key, parsed)
    return parsed


def hash_text(text: str) -> str:
    """Stable cache key for arbitrary text input."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return _LLM_CACHE_DIR / f"{key}.json"


def _cache_get(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(key: str, value: dict) -> None:
    try:
        _cache_path(key).write_text(json.dumps(value), encoding="utf-8")
    except Exception as e:
        log.debug("LLM cache write failed: %s", e)
