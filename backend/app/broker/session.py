"""Holding one authorised Zerodha session.

Kite's MCP server authorises a **session**, not a credential: `login` returns a browser URL tied
to the session id of the connection that asked, and only that connection becomes authorised.
The SDK's transport takes a URL and nothing else — a session id can be read from a response but
never supplied — so a new connection is a new, unauthorised session.

**The hosted server at mcp.kite.trade cannot currently authorise a web backend.** This was
established empirically, and the sequence is worth recording so nobody repeats it:

1. Holding the client across requests via an `AsyncExitStack` **hangs** — the MCP client runs
   on anyio task groups, which are bound to the task that entered them.
2. Holding it in one long-lived owner task fixes the hang, and then the connection **ends by
   itself**: the server closes the stream after each call (`anyio.EndOfStream`), which is the
   streamable-HTTP design — sessions are meant to resume via an `Mcp-Session-Id` header.
3. Supplying that header on a fresh connection **does not resume**: the server issues a *new*
   session id and answers "please log in first".

So each connection is a new, unauthorised session with no way to rejoin the authorised one. The
hosted server is built for an interactive client that holds one connection for the length of a
conversation — a chat app, not a service.

This module is therefore complete and correct against a transport that keeps a session, and
does **not** work against `mcp.kite.trade` today. The two paths that do:

* a **self-hosted** `kite-mcp-server` with a personal API key, which holds its own session, or
* **Kite Connect REST**, which issues a real access token — ₹500/month, plus the daily login the
  exchange requires.

Neither changes anything above: both are read-only here, and the platform stays paper-only.

**Read-only.** Nothing here can place, modify or cancel an order: mutating tools are refused at
discovery (`app.agents.mcp_client.is_read_only`) and again on the way in here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.clock import now_utc

log = logging.getLogger(__name__)

DEFAULT_KITE_MCP_URL = "https://mcp.kite.trade/mcp"

#: Kite's login response is prose aimed at a chat client. The authorise URL is the only part a
#: program needs, so it is extracted rather than passed through.
_AUTH_URL = re.compile(r"https://\S*?/authorize\?session_id=\S+")

#: A remote call that has not answered by now will not help this request.
CALL_TIMEOUT = 45.0
CONNECT_TIMEOUT = 45.0


class BrokerUnavailable(Exception):
    """The broker could not be reached, or the session is not authorised."""


@dataclass
class _Request:
    tool: str
    arguments: dict[str, Any]
    future: asyncio.Future


@dataclass
class KiteSession:
    """One live, authorised MCP connection — or the absence of one.

    Deliberately a single instance per process: two would each need their own browser login,
    which is a confusing thing to ask of someone twice.
    """

    url: str = DEFAULT_KITE_MCP_URL
    authorised: bool = False
    connected_at: datetime | None = None
    last_ok_at: datetime | None = None
    last_error: str | None = None

    _task: asyncio.Task | None = field(default=None, repr=False)
    _queue: asyncio.Queue | None = field(default=None, repr=False)
    _ready: asyncio.Event | None = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def connected(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            # Connected but unauthorised is the normal state between opening a session and the
            # browser login completing — worth distinguishing from not connected at all.
            "authorised": self.authorised,
            "url": self.url,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "last_error": self.last_error,
            "read_only": True,
        }

    # ── the owner task ────────────────────────────────────────────────────────
    async def _own_connection(self) -> None:
        """Open the connection and service calls until cancelled.

        Everything touching the MCP client happens in this one task. That is the whole point:
        anyio task groups cannot be used from a task other than the one that entered them.
        """
        queue = self._queue
        ready = self._ready
        assert queue is not None and ready is not None

        try:
            from mcp import Client

            async with Client(self.url, read_timeout_seconds=CALL_TIMEOUT) as client:
                self.connected_at = now_utc()
                self.last_error = None
                ready.set()

                while True:
                    request: _Request = await queue.get()
                    try:
                        result = await client.call_tool(request.tool, request.arguments)
                        if not request.future.done():
                            request.future.set_result(result)
                    except Exception as exc:  # noqa: BLE001 - reported to the caller
                        if not request.future.done():
                            request.future.set_exception(exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("Kite session ended: %s", exc)
        finally:
            self.authorised = False
            if ready is not None and not ready.is_set():
                # Unblock a waiting connect rather than leaving it on the timeout.
                ready.set()

    async def _start(self) -> None:
        await self._stop()
        self._queue = asyncio.Queue()
        self._ready = asyncio.Event()
        self._task = asyncio.create_task(self._own_connection())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=CONNECT_TIMEOUT)
        except TimeoutError as exc:
            await self._stop()
            raise BrokerUnavailable("timed out opening a Kite session") from exc
        if not self.connected:
            raise BrokerUnavailable(self.last_error or "could not open a Kite session")

    async def _stop(self) -> None:
        task, self._task = self._task, None
        self._queue = None
        self._ready = None
        self.authorised = False
        if task is not None and not task.done():
            task.cancel()
            # Closing, not diagnosing: whatever the owner task raises on the way out is not
            # information a caller asking to disconnect can act on.
            with contextlib.suppress(Exception):
                await task

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def begin_login(self) -> str:
        """Open a session and return the URL the user must visit.

        Replaces any existing session: asking to log in while holding an authorised one almost
        always means the old one stopped working.
        """
        async with self._lock:
            await self._start()
            text = await self._send("login", {})

        found = _AUTH_URL.search(text)
        if not found:
            raise BrokerUnavailable("Kite did not return a login link")
        return found.group(0)

    async def disconnect(self) -> None:
        async with self._lock:
            await self._stop()

    # ── calling ───────────────────────────────────────────────────────────────
    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        """Invoke a read-only Kite tool on the held session."""
        from app.agents.mcp_client import is_read_only

        if not is_read_only(tool):
            # Belt and braces: discovery already filters these, but this module must not become
            # the way an order reaches a broker.
            raise BrokerUnavailable(f"{tool} changes state and this integration is read-only")
        if not self.connected:
            raise BrokerUnavailable("not connected to Kite — start a login first")
        return await self._send(tool, arguments or {})

    async def _send(self, tool: str, arguments: dict[str, Any]) -> str:
        from app.agents.mcp_client import _attr

        queue = self._queue
        if queue is None:
            raise BrokerUnavailable("not connected to Kite — start a login first")

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        await queue.put(_Request(tool=tool, arguments=arguments, future=future))

        try:
            result = await asyncio.wait_for(future, timeout=CALL_TIMEOUT)
        except TimeoutError as exc:
            self.last_error = f"{tool} timed out"
            raise BrokerUnavailable(f"Kite call {tool} timed out") from exc
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise BrokerUnavailable(f"Kite call {tool} failed: {exc}") from exc

        text = "\n".join(
            getattr(block, "text", "") for block in (_attr(result, "content", default=[]) or [])
        ).strip()

        if _attr(result, "is_error", "isError", default=False) or "log in first" in text.lower():
            # Kite reports an unauthorised session as a tool error, not a transport one.
            self.authorised = False
            self.last_error = text or "not authorised"
            raise BrokerUnavailable(
                "Kite session is not authorised — complete the login, or start a new one if it "
                "has expired (Zerodha expires sessions daily)"
            )

        if tool != "login":
            self.authorised = True
            self.last_ok_at = now_utc()
        return text
