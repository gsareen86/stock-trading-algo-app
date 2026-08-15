"""One manifest, two representations.

An LLM consumes a tool definition; an external agent reads an A2A card. Maintaining those
separately would guarantee they drift, and the drift would be invisible until an outside agent
called something that no longer exists.

Nothing here imports LangGraph or an A2A SDK. Both renderers produce plain dicts, so the
shapes exist and are tested before `agent-graph-and-a2a` decides how to serve them.
"""

from __future__ import annotations

from typing import Any

from app.skills.types import SkillManifest


def to_tool_definition(manifest: SkillManifest) -> dict[str, Any]:
    """OpenAI-style function schema — what a model sees when choosing a tool.

    Uses ``summary`` rather than ``description``: this text competes for attention with every
    other tool in the prompt, and the long form belongs on the card, not here.
    """
    return {
        "type": "function",
        "function": {
            "name": manifest.name,
            "description": manifest.summary,
            "parameters": manifest.input_schema,
        },
    }


def to_a2a_skill(manifest: SkillManifest) -> dict[str, Any]:
    """An entry for an A2A agent card's `skills` array."""
    return {
        "id": manifest.name,
        "name": manifest.name.replace("_", " ").title(),
        "description": manifest.description,
        "tags": list(manifest.tags),
        "inputModes": ["application/json"],
        "outputModes": ["application/json"],
    }


def to_public_dict(manifest: SkillManifest) -> dict[str, Any]:
    """What `GET /skills` returns.

    Deliberately excludes the handler — an import path is an implementation detail, and
    publishing one tells a reader how to reach code the API never intended to expose.
    """
    return {
        "name": manifest.name,
        "version": manifest.version,
        "summary": manifest.summary,
        "description": manifest.description,
        "tags": list(manifest.tags),
        "input_schema": manifest.input_schema,
        "output_schema": manifest.output_schema,
    }
