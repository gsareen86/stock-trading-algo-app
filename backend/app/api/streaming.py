"""Shared Server-Sent Events (SSE) progress helper.

Emits honest counted-work progress events (`step`, `label`, `completed`, `total`,
`elapsed_seconds`) and a single terminal `complete` or `error` event. Never emits a
synthetic ETA or percent-of-time forecast.

The stream is a view of the run, not its owner. A viewer that goes away — a closed tab, a
navigation, the web server stopping — ends the stream and leaves the run to finish and
persist its own result. Cancelling on disconnect threw away a 26-minute Nifty 750 scan
in its final narration step, and left its row claiming to still be running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)

#: How long a stream may go without sending anything. One local-model narration takes
#: minutes and emits nothing until it ends, and the web proxy's fetch drops a response body
#: that is silent for 300 s (undici's default `bodyTimeout`) — which ended the progress view
#: of a scan mid-narration with "network error". Well under any proxy's idle limit.
HEARTBEAT_SECONDS = 15.0

#: Runs whose viewer disconnected. The event loop holds only weak references to tasks, so
#: an unwatched run with nothing else pointing at it could be collected mid-flight.
_DETACHED: set[asyncio.Task[None]] = set()


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
    # Cleared when the viewer goes away; events after that have no one to read them.
    listening = [True]

    def _enqueue(item: tuple[str, dict[str, Any]] | None) -> None:
        if not listening[0]:
            return
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
        except Exception as exc:
            if not listening[0]:
                # No viewer will see the error event, so the log is the only place it lands.
                log.warning("streamed run failed after its viewer disconnected: %s", exc)
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
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    # An SSE comment: ignored by every client, but bytes on the wire.
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                ev_name, data = item
                yield format_sse(ev_name, data)
        finally:
            listening[0] = False
            if not task.done():
                log.info("stream viewer disconnected; the run continues and persists its result")
                _DETACHED.add(task)
                task.add_done_callback(_DETACHED.discard)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
