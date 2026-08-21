"""Reading JSON out of what a local model actually sends.

A 12B model asked for eight structured items routinely emits six and a half and stops. Strict
parsing throws away the six because of the half, which on a slow local model means paying
minutes for a response and discarding it.

**Salvage is right for independent items and wrong for structures.** Six concepts out of eight
is six true things a document said. Two tiers out of a four-tier supply chain is not most of a
chain — a missing tier changes what the remaining ones mean — which is why `theme_chain`
refuses partial output and the extractors here accept it. The distinction lives at the call
site, deliberately: this module reports what arrived and never decides whether that is enough.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def strip_fence(payload: str) -> str:
    """Remove a markdown code fence, which local models add whatever the prompt says."""
    text = (payload or "").strip()
    if not text.startswith("```"):
        return text
    text = text.split("```")[1] if "```" in text[3:] else text[3:]
    return text.removeprefix("json").strip()


def objects(text: str) -> list[dict[str, Any]]:
    """Every complete JSON object in a string, at any nesting depth.

    A **stack**, not a depth counter. Items arrive nested inside a wrapper —
    ``{"concepts": [...]}`` — so a scanner that only closes regions at depth zero never sees a
    single item. The first version of this did exactly that and salvaged nothing while looking
    like it worked, which is the kind of bug that survives because its symptom is silence.
    """
    found: list[dict[str, Any]] = []
    stack: list[int] = []
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append(index)
        elif char == "}" and stack:
            opened = stack.pop()
            try:
                parsed = json.loads(text[opened : index + 1])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                found.append(parsed)

    return found


def items_from(payload: str, key: str, required_field: str) -> tuple[list[dict[str, Any]], bool]:
    """Items under ``key``, and whether the response parsed cleanly.

    The second value is what stops a truncated response being mistaken for a considered one.
    A caller that treats "nothing parsed" the same as "the model returned an empty list" will
    report a failure as a decision — which is exactly what a merge step did before this
    existed, quietly declaring every concept distinct because its response had been cut off.
    """
    text = strip_fence(payload)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        found = parsed.get(key) if isinstance(parsed, dict) else None
        if isinstance(found, list):
            return [item for item in found if isinstance(item, dict)], True

    salvaged = [obj for obj in objects(text) if required_field in obj]
    if salvaged:
        log.info("model response was truncated; salvaged %d item(s)", len(salvaged))
    return salvaged, False
