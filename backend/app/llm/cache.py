"""Content-hash disk cache for stable prompts.

Some prompts are stable by construction — the same evidence list always deserves the same
explanation. Caching those by content hash means repeated identical calls never hit the
network, which is the difference between a cheap re-run and a billed one.

**Failures are never cached.** A ``None`` result means the provider was unavailable, not that
the answer is "nothing"; caching it would turn a transient outage into a persistent one.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.llm.types import LLMResult, Message

log = logging.getLogger(__name__)


def cache_key(
    *,
    task: str,
    model: str,
    messages: list[Message],
    schema: Any | None,
    tools: Any | None = None,
) -> str:
    """Stable hash over everything that could change the answer.

    ``tools`` is part of that: the same prompt with a different callable set is a different
    question, and serving a cached answer across the two would hand back tool calls naming
    tools that are not currently available.
    """
    payload = {
        "task": task,
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "schema": schema,
        "tools": tools,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DiskCache:
    """One JSON file per key. Unreadable or corrupt entries are treated as misses."""

    def __init__(self, directory: str | Path, enabled: bool = True) -> None:
        self._dir = Path(directory)
        self._enabled = enabled
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> LLMResult | None:
        if not self._enabled:
            return None
        path = self._dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            log.debug("discarding unreadable cache entry %s", key[:12])
            return None
        # trace_id belongs to the original call, not this one — a cache hit issued no
        # request and so has no trace of its own.
        data["trace_id"] = None
        data["cached"] = True
        try:
            return LLMResult(**data)
        except TypeError:
            # Entry written by an older LLMResult shape.
            return None

    def put(self, key: str, result: LLMResult) -> None:
        if not self._enabled:
            return
        try:
            (self._dir / f"{key}.json").write_text(
                json.dumps(asdict(result), sort_keys=True), encoding="utf-8"
            )
        except OSError as exc:
            log.debug("could not write cache entry %s: %s", key[:12], exc)
