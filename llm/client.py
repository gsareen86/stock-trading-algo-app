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
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import (
    CACHE_DIR,
    LLM_DEFAULT_MODEL,
    LLM_MAX_RETRIES,
    LLM_PROVIDER,
    LLM_REQUEST_TIMEOUT_S,
)

# ── Circuit breaker ───────────────────────────────────────────────────────────
# After _CB_THRESHOLD consecutive 429 failures the breaker opens and all
# call_json() calls return None immediately for _CB_COOLDOWN_S seconds.
# This stops the bot wasting 8-10 seconds per cycle on doomed API attempts
# and prevents burning whatever little rate-limit budget remains.
# The breaker resets automatically after the cooldown window passes.
import threading as _threading

_CB_THRESHOLD  = 3     # consecutive 429s before opening the breaker
_CB_COOLDOWN_S = 600   # 10-minute cooldown once opened

_cb_lock              = _threading.Lock()
_cb_consecutive_429s  = 0
_cb_open_until        = 0.0   # monotonic timestamp; 0 = breaker closed
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
    if LLM_PROVIDER == "ollama":
        return "ollama_placeholder"
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


def _cb_is_open() -> bool:
    """True if the circuit breaker is currently open (skip all calls)."""
    global _cb_open_until
    with _cb_lock:
        if _cb_open_until and time.monotonic() < _cb_open_until:
            return True
        if _cb_open_until and time.monotonic() >= _cb_open_until:
            # Auto-reset after cooldown
            _cb_open_until = 0.0
            log.info("LLM circuit breaker RESET — will attempt calls again")
        return False


def _cb_record_429(model: str) -> None:
    global _cb_consecutive_429s, _cb_open_until
    with _cb_lock:
        _cb_consecutive_429s += 1
        if _cb_consecutive_429s >= _CB_THRESHOLD and not _cb_open_until:
            _cb_open_until = time.monotonic() + _CB_COOLDOWN_S
            resume = datetime.fromtimestamp(time.time() + _CB_COOLDOWN_S).strftime("%H:%M:%S")
            log.warning(
                "LLM circuit breaker OPEN after %d consecutive 429s on %s — "
                "skipping all LLM calls for %d min (until ~%s). "
                "Bot falls back to FinBERT/VADER/technical regime.",
                _cb_consecutive_429s, model, _CB_COOLDOWN_S // 60, resume,
            )


def _cb_record_success() -> None:
    global _cb_consecutive_429s, _cb_open_until
    with _cb_lock:
        if _cb_consecutive_429s:
            log.info("LLM circuit breaker: consecutive failures reset after success")
        _cb_consecutive_429s = 0
        _cb_open_until = 0.0


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

    # Circuit breaker: skip API call entirely when in cooldown
    if _cb_is_open():
        _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                    status="circuit_open", latency_ms=0,
                    error_msg="circuit breaker open — skipping API call")
        return None

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
        elif LLM_PROVIDER == "ollama":
            result, prompt_tokens, completion_tokens = _call_ollama(
                prompt=prompt, schema=schema,
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
        is_429 = "429" in (error_msg or "")
        if is_429:
            _cb_record_429(model)
        # Classify the failure type for cleaner stats
        status = "rate_limited" if is_429 else "error"
        _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                    status=status, prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms, error_msg=error_msg)
        return None

    _cb_record_success()
    log.debug("LLM ok %.0fms %s/%s pt=%s ct=%s",
              latency_ms, LLM_PROVIDER, model, prompt_tokens, completion_tokens)
    _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                status="ok", prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens, latency_ms=latency_ms)

    if cache_key:
        _cache_put(cache_key, result)
    return result


def call_text(
    *,
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 512,
    caller: str = "",
) -> Optional[str]:
    """Free-form text completion (no JSON, no schema). Returns the string or None.

    Use this for "map" steps — e.g. summarising a long concall transcript — where
    we want the model's natural prose output. Asking a local model for JSON on a
    very large input makes it lapse into prose; produce text here, then run a small
    JSON-extraction call (call_json) on the compact result.
    """
    from llm.observability import record as _obs_record
    model = model or LLM_DEFAULT_MODEL

    if _cb_is_open():
        _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                    status="circuit_open", latency_ms=0,
                    error_msg="circuit breaker open — skipping API call")
        return None
    client = get_client()
    if client is None and LLM_PROVIDER != "ollama":
        return None

    t0 = time.monotonic()
    text = None
    pt = ct = None
    error_msg = None
    try:
        if LLM_PROVIDER == "ollama":
            text, pt, ct = _text_ollama(prompt=prompt, system=system, model=model, max_tokens=max_tokens)
        elif LLM_PROVIDER == "anthropic":
            text, pt, ct = _text_anthropic(client, prompt=prompt, system=system, model=model, max_tokens=max_tokens)
        else:
            text, pt, ct = _text_openrouter(client, prompt=prompt, system=system, model=model, max_tokens=max_tokens)
    except Exception as e:
        text = None
        error_msg = str(e)

    latency_ms = int((time.monotonic() - t0) * 1000)
    if text is None:
        is_429 = "429" in (error_msg or "")
        if is_429:
            _cb_record_429(model)
        _obs_record(provider=LLM_PROVIDER, model=model, caller=caller,
                    status="rate_limited" if is_429 else "error",
                    latency_ms=latency_ms, error_msg=error_msg)
        return None
    _cb_record_success()
    _obs_record(provider=LLM_PROVIDER, model=model, caller=caller, status="ok",
                prompt_tokens=pt, completion_tokens=ct, latency_ms=latency_ms)
    return text


def _text_ollama(*, prompt, system, model, max_tokens):
    import requests
    from config import OLLAMA_REQUEST_TIMEOUT_S
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    url = f"{base_url}/api/chat"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model, "messages": messages, "stream": False,
        "options": {"temperature": 0.0, "num_predict": max_tokens}, "think": False,
    }
    res = requests.post(url, json=payload, timeout=OLLAMA_REQUEST_TIMEOUT_S)
    if res.status_code != 200:
        log.warning("Ollama text call HTTP %d: %s", res.status_code, res.text[:200])
        return None, None, None
    data = res.json()
    content = (data.get("message", {}) or {}).get("content", "") or ""
    return (content.strip() or None), data.get("prompt_eval_count"), data.get("eval_count")


def _text_openrouter(client, *, prompt, system, model, max_tokens):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
    usage = getattr(resp, "usage", None)
    content = resp.choices[0].message.content or ""
    return (content.strip() or None), getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)


def _text_anthropic(client, *, prompt, system, model, max_tokens):
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                              "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    pt = getattr(getattr(resp, "usage", None), "input_tokens", None)
    ct = getattr(getattr(resp, "usage", None), "output_tokens", None)
    txt = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    return (txt.strip() if txt else None), pt, ct


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


def _first_json_object(text: str) -> Optional[dict]:
    """Return the first complete, balanced, parseable JSON object in ``text``,
    even when it's surrounded by prose or markdown. Brace-counting (string-aware)
    so a ``}`` inside prose after the object doesn't truncate it."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break  # malformed; advance to the next "{"
        start = text.find("{", start + 1)
    return None


def _extract_json(text: str) -> Optional[dict]:
    """Parse JSON from model output, tolerating markdown fences and prose
    preamble/epilogue that local models often add around the object."""
    if not text:
        return None
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences if present
    if "```" in text:
        import re
        text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    obj = _first_json_object(text)
    if obj is not None:
        return obj
    log.warning("LLM: could not parse JSON from response: %.160s", text)
    return None


def hash_text(text: str) -> str:
    """Stable cache key for arbitrary text input."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return _LLM_CACHE_DIR / f"{key}.json"


def _cache_ttl_hours(key: str) -> float:
    """TTL for a cache key, longest-matching prefix from LLM_CACHE_TTL_HOURS.
    0 (or a negative value) means the entry never expires."""
    try:
        from config import LLM_CACHE_TTL_HOURS as ttls
    except ImportError:
        return 0.0
    best = ttls.get("default", 0.0)
    best_len = -1
    for prefix, hours in ttls.items():
        if prefix != "default" and key.startswith(prefix) and len(prefix) > best_len:
            best, best_len = hours, len(prefix)
    return float(best or 0.0)


def _cache_get(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    ttl_h = _cache_ttl_hours(key)
    if ttl_h > 0:
        try:
            age_h = (time.time() - p.stat().st_mtime) / 3600.0
            if age_h > ttl_h:
                p.unlink(missing_ok=True)  # stale — refetch
                return None
        except OSError:
            pass
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(key: str, value: dict) -> None:
    try:
        _cache_path(key).write_text(json.dumps(value), encoding="utf-8")
    except Exception as e:
        log.debug("LLM cache write failed: %s", e)


def _call_ollama(*, prompt, schema, system, model, max_tokens):
    """Call local Ollama native chat endpoint, explicitly disabling thinking mode."""
    import requests
    from config import OLLAMA_REQUEST_TIMEOUT_S
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    # Clean and convert OpenAI v1 compatibility base URL to raw Ollama base URL
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    url = f"{base_url}/api/chat"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    schema_hint = _schema_to_prompt_hint(schema)
    instr = ("\n\nRespond with a JSON object ONLY — no prose, no markdown, no preamble. "
             f"Match this structure exactly:\n{schema_hint}")
    if messages and messages[0]["role"] == "system":
        messages[0]["content"] += instr
    else:
        messages.insert(0, {"role": "system", "content": instr.strip()})

    def _post(fmt):
        """POST once with a given Ollama ``format`` (a JSON schema dict, or "json")."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": fmt,
            "options": {"temperature": 0.0, "num_predict": max_tokens},
            "think": False,
        }
        res = requests.post(url, json=payload, timeout=OLLAMA_REQUEST_TIMEOUT_S)
        if res.status_code != 200:
            log.warning("Ollama call HTTP %d (format=%s): %s", res.status_code,
                        "schema" if isinstance(fmt, dict) else fmt, res.text[:200])
            return None, None, None
        data = res.json()
        content = data.get("message", {}).get("content", "") or ""
        return _extract_json(content), data.get("prompt_eval_count"), data.get("eval_count")

    try:
        # 1) Grammar-constrained structured output — the model is forced to emit
        #    schema-conforming JSON (strongest guarantee for local models).
        parsed, pt, ct = _post(schema)
        if parsed is not None:
            return parsed, pt, ct
        # 2) Fallback for older Ollama (or a rejected schema): plain JSON mode.
        log.info("Ollama: schema-constrained output unusable — retrying in plain json mode")
        return _post("json")
    except Exception as e:
        log.warning("Ollama native call exception (%s): %s", model, e)
        raise
