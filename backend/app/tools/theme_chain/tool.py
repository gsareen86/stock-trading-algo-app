"""Expanding a theme into what it consumes, tier by tier.

This is the one step in the platform where a model influences **what gets looked at**, and it
is deliberate rather than incidental. Everything else is deterministic screen, deterministic
strategies, prose written afterwards.

**Why a model here and nowhere else.** Detection is arithmetic because "what is emerging" is a
question a model answers fluently whether or not anything is. This is the opposite kind of
question: a data centre draws continuous high load and needs step-down transformation,
switchgear and cabling, and that does not vary by who is asked or when. It is world knowledge,
not a market judgement — and it is precisely the question a reader missed when they bought the
GPU designer and the fab and never thought about the grid.

**The invariant that makes it safe:** a theme may widen attention and may never narrow it. What
comes out of here is a list of *supplier categories* — never instruments, never a stance, never
an ordering. Resolving categories to companies happens outside this tool, against the universe,
and every name that results is screened and evaluated exactly as any other.

**Every tier is an artefact.** Reasoning and the proposing model travel with each tier, so a
reader can see why a cable manufacturer reached their screen and reject the link if the
reasoning is wrong. A tier is never evidence and can never be cited by a verdict.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.clock import now_utc
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "theme_chain"

#: Bounded because a chain is only useful while a reader can hold it in their head, and because
#: every tier costs a resolution pass. Four is enough for theme → facility → equipment → input,
#: which is where the case this exists for lives.
MAX_TIERS = 4

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "theme": {
            "type": "string",
            "description": "The theme to expand, e.g. data centre buildout",
        },
        "max_tiers": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_TIERS,
            "default": MAX_TIERS,
        },
    },
    "required": ["theme"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "theme": {"type": "string"},
        "tier": {"type": "integer", "minimum": 1},
        "label": {"type": "string"},
        "supplies": {"type": ["string", "null"]},
        "reasoning": {"type": "string", "minLength": 1},
        "proposed_by": {"type": "string"},
        "supplier_descriptions": {"type": "array", "items": {"type": "string"}},
        # Never a platform measurement, and carried so nothing downstream has to infer it.
        "measured_by_platform": {"type": "boolean"},
    },
    required=["theme", "tier", "label", "reasoning", "proposed_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "theme": {"type": "string"},
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

PROMPT = """You are describing a physical and economic supply chain, not making an investment \
recommendation.

Theme: {theme}

List up to {max_tiers} tiers of what this theme consumes. Tier 1 is the activity itself. Each \
later tier supplies the tier above it.

For each tier give:
- label: a short name for the tier
- supplies: the label of the tier it supplies (null for tier 1)
- reasoning: one sentence on why this tier is required by the tier above
- supplier_descriptions: 2-6 categories of company that supply this tier, described by what \
they make or do

Rules:
- Describe categories of supplier, never named companies and never stock tickers.
- Say what is physically or economically required, not what might do well.
- Do not mention prices, valuations, or whether anything is a good investment.

Reply with JSON only, in this exact shape:
{{"tiers": [{{"label": "...", "supplies": null, "reasoning": "...", \
"supplier_descriptions": ["...", "..."]}}]}}"""


def _parse(payload: str) -> list[dict[str, Any]]:
    """The model's JSON, or nothing. A partial chain is never returned."""
    text = (payload or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()

    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        log.warning("chain expansion returned unparseable JSON: %s", exc)
        return []

    tiers = parsed.get("tiers")
    return tiers if isinstance(tiers, list) else []


def handle(arguments: dict, context: ToolContext) -> dict:
    theme = arguments["theme"].strip()
    max_tiers = int(arguments.get("max_tiers", MAX_TIERS))
    now = (context.now() if context.now else now_utc()).isoformat()

    expander = context.fetchers.get("chain_expander")
    empty = {"theme": theme, "model": None, "available": False, "reason": None, "items": []}
    if expander is None:
        return {**empty, "reason": "no model is configured for chain expansion"}

    try:
        raw, model = expander(PROMPT.format(theme=theme, max_tiers=max_tiers), TASK)
    except Exception as exc:
        log.warning("chain expansion failed for %r: %s", theme, exc)
        return {**empty, "reason": f"expansion failed: {exc}"}

    tiers = _parse(raw)
    if not tiers:
        # No chain rather than a partial one. A half-expanded chain looks complete and would
        # quietly omit the tier a reader most needed.
        return {**empty, "model": model, "reason": "model output was not a usable chain"}

    items = []
    for index, tier in enumerate(tiers[:max_tiers], start=1):
        if not isinstance(tier, dict):
            continue
        label = str(tier.get("label") or "").strip()
        reasoning = str(tier.get("reasoning") or "").strip()
        # A tier with no reasoning cannot be judged or rejected, so it is not a tier this
        # platform will show. Dropping it is better than displaying an unattributable claim.
        if not label or not reasoning:
            continue

        items.append(
            {
                "source_ref": f"model://{model}/{TASK}?theme={theme}&tier={index}",
                "observed_at": now,
                "theme": theme,
                "tier": index,
                "label": label,
                "supplies": (str(tier["supplies"]).strip() if tier.get("supplies") else None),
                "reasoning": reasoning,
                "proposed_by": model,
                "supplier_descriptions": [
                    str(d).strip()
                    for d in (tier.get("supplier_descriptions") or [])
                    if str(d).strip()
                ][:8],
                "measured_by_platform": False,
            }
        )

    if not items:
        return {**empty, "model": model, "reason": "no tier carried usable reasoning"}

    return {
        "theme": theme,
        "model": model,
        "available": True,
        "reason": None,
        "items": items,
    }


TOOL = ToolManifest(
    name="theme_chain",
    version="1.0.0",
    summary=(
        "Expands a theme into the tiers of physical and economic inputs it consumes. Use when "
        "you know what is happening and need to know who else gets paid by it — the suppliers "
        "two and three steps below the obvious beneficiary."
    ),
    description=(
        "Proposes a tiered supply chain for a theme: what the activity requires, what supplies "
        "that, and so on. Returns categories of supplier described by what they make, never "
        "named companies and never tickers — resolving categories to listed instruments "
        "happens separately, against the platform's own universe. Every tier carries its "
        "reasoning and the model that proposed it, so a reader can judge it and reject it. "
        "This is a proposal, not a measurement: nothing it returns may become evidence, move a "
        "conviction, or remove a candidate from consideration."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("themes", "supply-chain", "research"),
)
