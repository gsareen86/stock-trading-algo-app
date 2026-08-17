"""The A2A agent card.

A document, not a server. It renders from the same manifests that produce tool definitions, via
`to_a2a_skill`, so the card and the callable surface cannot drift apart — the drift being
invisible until an outside agent calls something that no longer exists.

A full A2A task server (endpoints, task lifecycle, streaming) is deliberately absent: it has no
caller. This repo has already paid once for building a binding ahead of its consumer, and
`to_a2a_skill` was that binding. Publishing the card exercises the renderer against a real HTTP
response and makes the platform discoverable; the protocol server waits for an agent that wants
to talk to it.

Note the vocabulary: A2A calls these entries **skills**. That is the format's word, not this
platform's — see `openspec/project.md`.
"""

from __future__ import annotations

from typing import Any

from app.core.settings import Settings
from app.tools.bindings import to_a2a_skill
from app.tools.registry import ToolRegistry

#: Where an A2A client looks. Fixed by the protocol, not a choice.
CARD_PATH = "/.well-known/agent-card.json"


def build_card(registry: ToolRegistry, settings: Settings, base_url: str) -> dict[str, Any]:
    """The agent card for this platform."""
    return {
        "protocolVersion": "0.2.9",
        "name": "Indian equity research agent",
        "description": (
            "Evaluates NSE-listed stocks against four independent swing and long-term "
            "strategies, returning one traceable verdict per strategy. Verdicts are never "
            "blended."
        ),
        "version": settings.app_version,
        "url": base_url.rstrip("/"),
        "preferredTransport": "JSONRPC",
        "capabilities": {
            # Honest about what is not built: no streaming, no push, no task history.
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [to_a2a_skill(manifest) for manifest in registry.manifests()],
    }
