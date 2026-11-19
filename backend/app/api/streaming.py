"""Shared Server-Sent Events (SSE) progress helper.

Emits honest counted-work progress events (`step`, `label`, `completed`, `total`,
`elapsed_seconds`) and a single terminal `complete` or `error` event. Never emits a
synthetic ETA or percent-of-time forecast.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from fastapi.responses import StreamingResponse


def format_sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def sse_stream_response(
    runner: Callable[
        [Callable[[str, str, int | None, int | None], None]],
        Coroutine[Any, Any, dict[str, Any]],
    ],
) -> StreamingResponse:
    """Wrap an async runner ``(emit) -> result_dict`` as a live SSE StreamingResponse."""
    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
    started = time.monotonic()
    loop_holder: list[asyncio.AbstractEventLoop] = []

    def _enqueue(item: tuple[str, dict[str, Any]] | None) -> None:
        if loop_holder:
            loop_holder[0].call_soon_threadsafe(queue.put_nowait, item)
        else:
            queue.put_nowait(item)

    def emit(
        step: str,
        label: str,
        completed: int | None = None,
        total: int | None = None,
    ) -> None:
        pct: float | None = None
        if completed is not None and total is not None and total > 0:
            pct = round(min(100.0, max(0.0, completed / total * 100.0)), 1)
        _enqueue(
            (
                "progress",
                {
                    "step": step,
                    "label": label,
                    "completed": completed,
                    "total": total,
                    "percent": pct,
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                },
            )
        )

    async def drive() -> None:
        try:
            result = await runner(emit)
            _enqueue(
                (
                    "complete",
                    {
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                        "result": result,
                    },
                )
            )
        except Exception as exc:  # pragma: no cover - surfaced cleanly as SSE error
            _enqueue(
                (
                    "error",
                    {
                        "error": str(exc),
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                    },
                )
            )
        finally:
            _enqueue(None)

    async def generate() -> AsyncIterator[str]:
        loop_holder.append(asyncio.get_running_loop())
        task = asyncio.create_task(drive())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                ev_name, data = item
                yield format_sse(ev_name, data)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
