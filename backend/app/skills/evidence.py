"""The shape every skill's output items share.

`verdict-narratives` will reject any narrative containing a number that does not trace to an
`Evidence` row, and `Evidence.source_ref` has to come from somewhere. Requiring a reference at
the skill boundary means the traceability chain cannot be broken later by a skill that simply
forgot — and because the requirement lives in the output schema, forgetting is a validation
failure rather than a convention nobody checks.
"""

from __future__ import annotations

from typing import Any

#: Fields every returned item carries, whatever the skill.
EVIDENCE_FIELDS: dict[str, Any] = {
    "source_ref": {
        "type": "string",
        "minLength": 1,
        "description": "URL or exchange identifier a reader can follow back to the source",
    },
    "observed_at": {
        "type": "string",
        "description": "ISO-8601 instant at which the platform saw this",
    },
}

EVIDENCE_REQUIRED: list[str] = ["source_ref", "observed_at"]


def item_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Build an item schema with the evidence fields folded in."""
    return {
        "type": "object",
        "properties": {**EVIDENCE_FIELDS, **properties},
        "required": [*EVIDENCE_REQUIRED, *required],
        "additionalProperties": True,
    }


def items_output_schema(
    item: dict[str, Any], extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The standard `{"items": [...]}` envelope."""
    properties: dict[str, Any] = {"items": {"type": "array", "items": item}}
    if extra:
        properties.update(extra)
    return {
        "type": "object",
        "properties": properties,
        "required": ["items"],
        "additionalProperties": True,
    }
