"""Talking to an external MCP server.

Kept behind the same contract as every other outside dependency in this platform: a server
being unreachable is a **normal outcome**, reported and moved past, never an exception. A
broker's MCP server going down must not stop four strategies evaluating a stock.

The `mcp` package is imported lazily for the same reason `litellm` is: the API, the strategies
and their tests all run without the `agents` extra installed.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: A remote call that has not answered by now is not going to help this cycle.
DEFAULT_TIMEOUT_SECONDS = 30.0


#: Verbs that mean a tool *changes something* at the broker. Any remote tool whose name
#: contains one is refused at discovery and never offered to a model.
#:
#: This platform is paper-only with one explicit execution boundary (principle 7), and a
#: research step is emphatically not that boundary. Zerodha's hosted server really does
#: advertise `place_order`, `cancel_order` and the GTT mutators; the fact that they currently
#: fail without a login is an accident of authentication, not a design we should lean on.
#: Read-only is enforced here, on our side, where it is our decision.
MUTATING_VERBS = ("place", "cancel", "modify", "delete", "exit", "square", "convert")


def is_read_only(tool_name: str) -> bool:
    """Whether a remote tool only reads. Conservative: unknown verbs are allowed, but any
    name containing a mutating verb is not."""
    lowered = tool_name.lower()
    return not any(verb in lowered for verb in MUTATING_VERBS)


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """First attribute present, by any of its spellings.

    The SDK renamed `inputSchema` to `input_schema` and `isError` to `is_error` between major
    versions. Reading both costs two lines and turns the next such rename from a silent
    `AttributeError` — which surfaced here as an unrelated-looking `ExceptionGroup` from inside
    a task group — into a no-op.
    """
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


@dataclass(frozen=True, slots=True)
class McpTool:
    """A tool defined by someone else's server.

    Deliberately *not* a `ToolManifest`. That type promises an output schema and evidence-shaped
    items carrying a `source_ref` — guarantees this platform makes about its own handlers and
    cannot make about a remote server. Keeping them separate is what stops the registry's
    contract from quietly weakening to whatever MCP happens to offer.
    """

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """Namespaced so a trace never leaves the origin of a tool ambiguous."""
        return f"{self.server}:{self.name}"

    def to_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


@dataclass
class McpServerStatus:
    """What happened when we tried to reach a server. Surfaced, never raised."""

    name: str
    url: str
    reachable: bool
    tool_count: int = 0
    error: str | None = None
    tools: list[McpTool] = field(default_factory=list)
    #: Mutating tools this server offered and we declined. Reported rather than silently
    #: dropped: "the broker exposes order placement and we refuse it" is worth being able to
    #: see, and a silently shorter tool list looks like a server problem.
    refused: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "reachable": self.reachable,
            "tool_count": self.tool_count,
            "refused": list(self.refused),
            "error": self.error,
        }


@asynccontextmanager
async def _session(url: str, timeout: float):
    """A connected MCP client over streamable HTTP.

    Uses the SDK's high-level `Client`, which takes a URL and handles transport and
    initialisation. Wiring the transport by hand is the older, lower-level API and buys nothing
    here — this platform lists tools and calls them.
    """
    from mcp import Client

    async with Client(url, read_timeout_seconds=timeout) as client:
        yield client


async def discover(
    name: str, url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> McpServerStatus:
    """List a server's tools, or report why we could not."""
    try:
        async with _session(url, timeout) as session:
            listed = await session.list_tools()
            tools = [
                McpTool(
                    server=name,
                    name=tool.name,
                    description=tool.description or tool.name,
                    input_schema=dict(_attr(tool, "input_schema", "inputSchema") or {}),
                )
                for tool in listed.tools
                if is_read_only(tool.name)
            ]
            refused = [t.name for t in listed.tools if not is_read_only(t.name)]
        if refused:
            log.info("MCP server %s: refused %d mutating tools: %s", name, len(refused), refused)
        return McpServerStatus(
            name=name,
            url=url,
            reachable=True,
            tool_count=len(tools),
            tools=tools,
            refused=tuple(refused),
        )
    except Exception as exc:
        # Includes the import failing when the `agents` extra is absent — which is the same
        # situation from the caller's point of view: these tools are not available.
        log.warning("MCP server %s (%s) unavailable: %s", name, url, exc)
        return McpServerStatus(
            name=name, url=url, reachable=False, error=f"{type(exc).__name__}: {exc}"
        )


async def call(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Invoke a remote tool. Returns ``(ok, text)`` and never raises.

    The result is returned as text rather than parsed into a shape of our choosing: we did not
    define this tool's output and inventing a structure for it would be asserting a contract
    the server never made.
    """
    try:
        async with _session(url, timeout) as session:
            result = await session.call_tool(tool_name, arguments)
            parts = [
                getattr(block, "text", "")
                for block in (_attr(result, "content", default=[]) or [])
                if getattr(block, "text", "")
            ]
            text = "\n".join(parts).strip()
            if _attr(result, "is_error", "isError", default=False):
                return False, text or "remote tool reported an error"
            return True, text
    except Exception as exc:
        log.warning("MCP call %s failed: %s", tool_name, exc)
        return False, f"{type(exc).__name__}: {exc}"
