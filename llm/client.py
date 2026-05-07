"""
Shared LLM client supporting multiple providers.

Supported providers (set LLM_PROVIDER in .env):
  anthropic   — Claude models via Anthropic SDK (requires ANTHROPIC_API_KEY)
  openrouter  — Any model via OpenRouter (requires OPENROUTER_API_KEY)
                Default model: google/gemma-3-27b-it:free (free tier)

Every call returns None on failure — callers always fall back to their
existing non-LLM path. A trading cycle must never crash because the LLM
gateway is down or rate-limited.

Disk cache for stable inputs (sentiment-by-text-hash, events-by-day) so
repeated identical prompts never hit the network.
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
    LLM_PROVIDER,
    LLM_REQUEST_TIMEOUT_S,
)
log = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()
_LLM_CACHE_DIR = Path(CACHE_DIR) / "llm"
_LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# OpenRouter endpoint — OpenAI-compatible
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_APP_TITLE = "IndianEquityBot"  # shown in OpenRouter usage dashboard


def get_client():
    """Lazy-initialised provider client. Returns None if SDK or key missing."""
    global _client
    if _client is not None:
        return _client if _client is not False else None
    with _client_lock:
        if _client is None:
            _client = _init_client()
    return _client if _client is not False else None


def _init_client():
    if LLM_PROVIDER == "anthropic":
        return _init_anthropic()
    return _init_openrouter()


def _init_anthropic():
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log.warning("ANTHROPIC_API_KEY not set — LLM features disabled")
            return False
        return anthropic.Anthropic(
            api_key=api_key,
            timeout=LLM_REQUEST_TIMEOUT_S,
            max_retries=LLM_MAX_RETRIES,
        )
    except ImportError:
        log.warning("anthropic package not installed — LLM features disabled")
        return False


def _init_openrouter():
    try:
        import openai
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            log.warning("OPENROUTER_API_KEY not set — LLM features disabled")
            return False
        return openai.OpenAI(
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            timeout=LLM_REQUEST_TIMEOUT_S,
            # 0 retries: on free-tier rate limits the reset window is 60s, so
            # retrying after <1s just burns 2 more slots and still fails.
            # Fail fast and let the caller use its non-LLM fallback instead.
            max_retries=0,
            default_headers={
                "X-Title": _OPENROUTER_APP_TITLE,
            },
        )
    except ImportError:
        log.warning("openai package not installed — LLM features disabled (needed for OpenRouter)")
        return False


def call_json(
    *,
    prompt: str,
    schema: dict,
    system: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 512,
    cache_key: Optional[str] = None,
    caller: str = "",               # feature name for observability (e.g. "sentiment")
) -> Optional[dict]:
    """One-shot LLM call constrained to a JSON schema.

    Returns the parsed dict, or None on any failure (caller falls back).

    `cache_key`: if given, response is cached on disk. Use stable hashes only
    (e.g. sha256(text) for sentiment). Don't cache time-sensitive inputs.
    `caller`: optional tag recorded in llm_call_log (e.g. "veto", "regime").
    """
    from llm.observability import record as _obs_record

    model = model or LLM_DEFAULT_MODEL

    if cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                        status="cached", latency_ms=0)
            return cached

    client = get_client()
    if client is None:
        return None

    t0 = time.monotonic()
    prompt_tokens = completion_tokens = None
    error_msg = None

    try:
        if LLM_PROVIDER == "anthropic":
            result, prompt_tokens, completion_tokens = _call_anthropic(
                client, prompt=prompt, schema=schema,
                system=system, model=model, max_tokens=max_tokens)
        else:
            result, prompt_tokens, completion_tokens = _call_openrouter(
                client, prompt=prompt, schema=schema,
                system=system, model=model, max_tokens=max_tokens)
    except Exception as e:
        result = None
        error_msg = str(e)

    latency_ms = int((time.monotonic() - t0) * 1000)

    if result is None:
        # Classify the failure type for cleaner stats
        status = "rate_limited" if "429" in (error_msg or "") else "error"
        _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                    status=status, prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms, error_msg=error_msg)
        return None

    log.debug("LLM ok %.0fms %s/%s pt=%s ct=%s",
              latency_ms, LLM_PROVIDER, model, prompt_tokens, completion_tokens)
    _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                status="ok", prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens, latency_ms=latency_ms)

    if cache_key:
        _cache_put(cache_key, result)
    return result


def _call_anthropic(client, *, prompt, schema, system, model, max_tokens):
    """Returns (parsed_dict_or_None, prompt_tokens, completion_tokens)."""
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
        response = client.messages.create(**kwargs)
        pt = getattr(getattr(response, "usage", None), "input_tokens", None)
        ct = getattr(getattr(response, "usage", None), "output_tokens", None)
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text), pt, ct
    except StopIteration:
        log.warning("Anthropic: no text block in response")
    except json.JSONDecodeError as e:
        log.warning("Anthropic: JSON parse failed: %s", e)
    except Exception as e:
        log.warning("Anthropic call failed: %s", e)
        raise
    return None, None, None


def _call_openrouter(client, *, prompt, schema, system, model, max_tokens):
    """Returns (parsed_dict_or_None, prompt_tokens, completion_tokens)."""
    schema_hint = _schema_to_prompt_hint(schema)
    sys_content = (system or "") + (
        f"\n\nRespond with a valid JSON object only — no markdown, no explanation.\n"
        f"Required structure:\n{schema_hint}"
    )
    messages = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": prompt},
    ]
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        usage = getattr(response, "usage", None)
        pt = getattr(usage, "prompt_tokens", None)
        ct = getattr(usage, "completion_tokens", None)
        text = response.choices[0].message.content or ""
        parsed = _extract_json(text)
        return parsed, pt, ct
    except Exception as e:
        log.warning("OpenRouter call failed (%s/%s): %s", LLM_PROVIDER, model, e)
        raise
    return None, None, None


def _schema_to_prompt_hint(schema: dict) -> str:
    """Convert JSON schema properties to a simple field list for the prompt."""
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines = []
    for field, meta in props.items():
        ftype = meta.get("type", "any")
        desc = meta.get("description", "")
        req = " (required)" if field in required else ""
        lines.append(f'  "{field}": {ftype}{req}  — {desc}' if desc else f'  "{field}": {ftype}{req}')
    return "{\n" + "\n".join(lines) + "\n}"


def _extract_json(text: str) -> Optional[dict]:
    """Parse JSON from model output, tolerating markdown code fences."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    log.warning("LLM: could not parse JSON from response: %.120s", text)
    return None


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
