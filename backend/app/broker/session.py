"""Holding one authorised Zerodha session.

Kite's MCP server authorises a **session**, not a credential: `login` returns a browser URL
tied to a session id, and that session becomes authorised when the user completes the login.

The session is resumed by **id, not by connection**. Each call is an ordinary JSON-RPC POST
carrying `Mcp-Session-Id`; there is no socket to keep open and nothing held across requests.

That took three attempts, and the wrong turns are recorded because each looked correct:

* Holding an SDK client across requests **hangs** — its anyio task groups are bound to the task
  that entered them.
* Owning the client in a long-lived task fixes the hang, and then the connection ends by itself:
  the server closes the stream after each call.
* Reconnecting with the SDK **appears** not to resume — but `ClientSession.initialize()`
  *creates* a session by protocol, so re-initialising per call mints a new, unauthorised one
  every time. That is a client mistake, not a server limitation. Resumption works exactly as
  the specification says once you stop re-initialising.

So: initialise once, keep the id, speak JSON-RPC directly. No SDK client, no long-lived task,
no reconnection logic.

**Read-only.** Nothing here can place, modify or cancel an order — mutating tools are refused at
discovery (`app.agents.mcp_client.is_read_only`) and again on the way in here. The platform
stays paper-only; holdings are observed, never traded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.clock import now_utc

log = logging.getLogger(__name__)

DEFAULT_KITE_MCP_URL = "https://mcp.kite.trade/mcp"
PROTOCOL_VERSION = "2025-06-18"
CALL_TIMEOUT = 45.0

#: Kite's login reply is prose aimed at a chat client; the authorise URL is the only part a
#: program needs.
#:
#: The URL is given twice — once inside a markdown link and once bare — so the terminating
#: characters must exclude `)`, or the extracted link carries the markdown's closing bracket
#: and 404s. Found by opening one.
_AUTH_URL = re.compile(r"https://[^\s\"\\)]*?/authorize\?session_id=[^\s\"\\)]+")

_HEADERS = {
    "Content-Type": "application/json",
    # The server may answer either way; both are parsed.
    "Accept": "application/json, text/event-stream",
}


class BrokerUnavailable(Exception):
    """The broker could not be reached, or the session is not authorised."""


@dataclass
class KiteSession:
    """One Zerodha session, identified rather than held open."""

    url: str = DEFAULT_KITE_MCP_URL
    session_id: str | None = None
    authorised: bool = False
    connected_at: datetime | None = None
    last_ok_at: datetime | None = None
    last_error: str | None = None

    #: Holdings change slowly and each read costs a round trip. Refreshed on this cadence
    #: rather than per request — a portfolio stale by minutes is not a wrong one.
    refresh_minutes: int = 15
    _cache: dict[str, tuple[datetime, str]] = field(default_factory=dict, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _next_id: int = field(default=0, repr=False)

    @property
    def connected(self) -> bool:
        return self.session_id is not None

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            # Connected but unauthorised is the normal state between opening a session and the
            # browser login completing.
            "authorised": self.authorised,
            "url": self.url,
            "session_id": self.session_id,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_ok_at": self.last_ok_at.isoformat() if self.last_ok_at else None,
            "refresh_minutes": self.refresh_minutes,
            "cached": sorted(self._cache),
            "last_error": self.last_error,
            "read_only": True,
        }

    # ── transport ─────────────────────────────────────────────────────────────
    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One JSON-RPC call, carrying the session id when there is one."""
        import httpx2

        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params

        headers = dict(_HEADERS)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        try:
            async with httpx2.AsyncClient(timeout=CALL_TIMEOUT) as client:
                response = await client.post(self.url, headers=headers, json=payload)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise BrokerUnavailable(f"could not reach Kite: {exc}") from exc

        assigned = response.headers.get("mcp-session-id")
        if assigned:
            if self.session_id and assigned != self.session_id:
                # A replaced session means the authorised one is gone.
                log.info("Kite issued a new session; the previous one is no longer valid")
                self.authorised = False
            self.session_id = assigned

        if response.status_code >= 400:
            self.last_error = f"HTTP {response.status_code}"
            raise BrokerUnavailable(f"Kite returned HTTP {response.status_code}")

        return _decode(response.text)

    async def _call_tool(self, tool: str, arguments: dict[str, Any]) -> str:
        message = await self._rpc("tools/call", {"name": tool, "arguments": arguments})

        if "error" in message:
            detail = str(message["error"].get("message", message["error"]))
            self.last_error = detail
            raise BrokerUnavailable(f"Kite call {tool} failed: {detail}")

        result = message.get("result") or {}
        text = "\n".join(
            block.get("text", "")
            for block in (result.get("content") or [])
            if isinstance(block, dict)
        ).strip()

        lowered = text.lower()
        if result.get("isError") or "log in first" in lowered or "failed to execute" in lowered:
            # Kite reports an unauthorised session as a tool-level error, not a transport one.
            self.authorised = False
            self.last_error = text or "not authorised"
            raise BrokerUnavailable(
                "Kite session is not authorised — open the login link, or start a new session "
                "if it has expired (Zerodha expires sessions daily)"
            )

        if tool != "login":
            self.authorised = True
            self.last_ok_at = now_utc()
        return text

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def begin_login(self) -> str:
        """Start a session and return the URL to open in a browser.

        Initialising is what *creates* a session, so it happens exactly once per login. Calling
        it again would silently abandon an authorised session for a fresh unauthorised one —
        which is the bug that made this look impossible.
        """
        async with self._lock:
            self.session_id = None
            self.authorised = False
            self._cache.clear()

            await self._rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "swing-longterm-platform", "version": "1"},
                },
            )
            if not self.session_id:
                raise BrokerUnavailable("Kite did not assign a session")

            self.connected_at = now_utc()
            await self._rpc("notifications/initialized")
            text = await self._call_tool("login", {})

        found = _AUTH_URL.search(text)
        if not found:
            raise BrokerUnavailable("Kite did not return a login link")
        return found.group(0)

    async def disconnect(self) -> None:
        async with self._lock:
            self.session_id = None
            self.authorised = False
            self._cache.clear()

    # ── calling ───────────────────────────────────────────────────────────────
    async def call(
        self, tool: str, arguments: dict[str, Any] | None = None, use_cache: bool = True
    ) -> str:
        """Invoke a read-only Kite tool, serving a recent answer when there is one."""
        from app.agents.mcp_client import is_read_only

        if not is_read_only(tool):
            # Belt and braces: discovery already filters these, but this module must not become
            # the way an order reaches a broker.
            raise BrokerUnavailable(f"{tool} changes state and this integration is read-only")
        if not self.connected:
            raise BrokerUnavailable("not connected to Kite — start a login first")

        key = f"{tool}:{json.dumps(arguments or {}, sort_keys=True)}"
        if use_cache:
            cached = self._fresh(key)
            if cached is not None:
                return cached

        async with self._lock:
            text = await self._call_tool(tool, arguments or {})
            self._cache[key] = (now_utc(), text)
            return text

    def _fresh(self, key: str) -> str | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        stamp, text = entry
        if now_utc() - stamp > timedelta(minutes=self.refresh_minutes):
            return None
        return text

    def invalidate(self) -> None:
        """Drop cached answers — used by an end-of-day refresh."""
        self._cache.clear()


def _decode(body: str) -> dict[str, Any]:
    """Read a JSON-RPC reply from either a plain body or an SSE stream.

    Streamable HTTP may answer either way for the same request, so both are handled rather than
    depending on which one Kite happens to choose today.
    """
    text = (body or "").strip()
    if not text:
        return {}

    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    for line in text.splitlines():
        if line.startswith("data:"):
            candidate = line[5:].strip()
            if candidate.startswith("{"):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    return {}
