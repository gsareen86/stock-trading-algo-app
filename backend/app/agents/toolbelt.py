"""What the research node may call.

Two sets, one prompt, honest about which is which: local tools from `ToolRegistry`, which
declare an output schema and return evidence-shaped items, and MCP tools from external servers,
which promise neither. They are presented to the model together and kept apart everywhere else
— see `design.md` §4.

Nothing here decides anything. A toolbelt looks things up.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents import mcp_client
from app.agents.mcp_client import McpServerStatus, McpTool
from app.tools.bindings import to_tool_definition
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext

log = logging.getLogger(__name__)

#: Remote output is untyped text of unknown length. Truncated before it reaches a prompt so one
#: chatty server cannot crowd out the evidence the model is meant to be reasoning about.
MAX_REMOTE_CHARS = 4000


@dataclass
class Toolbelt:
    """The callable surface for one cycle."""

    registry: ToolRegistry
    context: ToolContext = field(default_factory=ToolContext)
    mcp_servers: dict[str, str] = field(default_factory=dict)
    mcp_status: list[McpServerStatus] = field(default_factory=list)
    _mcp_tools: dict[str, McpTool] = field(default_factory=dict)

    async def connect(self) -> None:
        """Discover external tools. A server that cannot be reached is simply absent."""
        for name, url in self.mcp_servers.items():
            status = await mcp_client.discover(name, url)
            self.mcp_status.append(status)
            for tool in status.tools:
                self._mcp_tools[tool.qualified_name] = tool

    # ── what the model sees ───────────────────────────────────────────────────
    def definitions(self) -> list[dict[str, Any]]:
        """Every callable tool, as the model sees it when choosing."""
        local = [to_tool_definition(m) for m in self.registry.manifests()]
        remote = [tool.to_tool_definition() for tool in self._mcp_tools.values()]
        return local + remote

    def names(self) -> list[str]:
        return [d["function"]["name"] for d in self.definitions()]

    # ── invocation ────────────────────────────────────────────────────────────
    async def invoke(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Call a tool by the name the model used. Returns ``(ok, text)``; never raises."""
        remote = self._mcp_tools.get(name)
        if remote is not None:
            url = self.mcp_servers[remote.server]
            ok, text = await mcp_client.call(url, remote.name, arguments)
            return ok, text[:MAX_REMOTE_CHARS]

        # Local: the registry validates arguments against the manifest's own schema *before*
        # the handler runs, so a model producing malformed input gets a typed refusal rather
        # than a handler failing somewhere further from the cause.
        result = self.registry.invoke(name, arguments, self.context)
        if not result.ok:
            return False, f"{result.reason}: {result.error}"
        return True, json.dumps(result.data, default=str)[:MAX_REMOTE_CHARS]

    @property
    def unreachable_servers(self) -> list[str]:
        return [s.name for s in self.mcp_status if not s.reachable]
