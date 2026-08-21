"""Deciding which companies genuinely participate in a chain tier.

**The precision half of retrieve-then-rerank.** Term overlap over five hundred business
descriptions is a cheap, instant recall step and a poor judge: it has no synonymy, so "OSAT"
never matches "assembly and test" and "electrolyser" never matches "hydrogen equipment". Asking
a model to read five hundred descriptions is the opposite problem — it does not fit, and would
not be affordable if it did.

So overlap casts wide and this decides. The model reads a tier and a shortlist of what those
companies actually do, and says which of them participate. Nothing outside the shortlist can be
selected, which keeps the platform's own universe as the only source of candidates.

**It cannot add a name.** A symbol not offered is dropped rather than trusted, so the worst a
confused model can do is return fewer companies than it should — never one that does not exist,
is not listed, or is listed somewhere else.
"""

from __future__ import annotations

import logging

from app.core.clock import now_utc
from app.llm.parsing import items_from
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "tier_match"

#: Candidates per call. A local model's context has to hold every description, and a long list
#: makes it careless rather than thorough. The caller batches.
BATCH_SIZE = 12

#: Characters of each business description shown. The first paragraph says what a company does;
#: the rest is usually subsidiaries and history.
DESCRIPTION_CHARS = 420

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tier": {"type": "string", "description": "What this tier of the chain supplies"},
        "reasoning": {"type": "string", "description": "Why the tier is needed"},
        "candidates": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["symbol", "description"],
            },
        },
    },
    "required": ["tier", "candidates"],
    "additionalProperties": False,
}

MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "participates": {"type": "boolean"},
                    "why": {"type": "string"},
                },
                "required": ["symbol", "participates", "why"],
            },
        }
    },
    "required": ["matches"],
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "tier": {"type": "string"},
        "why": {"type": "string"},
        "matched_by": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["symbol", "tier", "why", "matched_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "tier": {"type": "string"},
        "considered": {"type": "integer"},
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

PROMPT = """You are deciding which companies supply a particular part of a supply chain.

Tier: {tier}
{reasoning}

Companies, described by what they do:
{candidates}

For each company, say whether its own described business genuinely supplies this tier.

For each give:
- symbol: the symbol shown, copied exactly
- participates: true or false
- why: at most 12 words, quoting what the company does

Rules:
- Judge only from the description given. Do not use outside knowledge of the company.
- Being in a related industry is not participating. A power utility does not make transformers.
- Recognise the same activity under different words: assembly and test is OSAT; an \
electrolyser maker supplies hydrogen equipment.
- When the description does not say, answer false.

Reply with JSON only:
{{"matches": [{{"symbol": "...", "participates": true, "why": "..."}}]}}"""


def handle(arguments: dict, context: ToolContext) -> dict:
    tier = arguments["tier"].strip()
    reasoning = (arguments.get("reasoning") or "").strip()
    candidates = [
        c for c in arguments["candidates"] if c.get("symbol") and c.get("description")
    ]
    now = (context.now() if context.now else now_utc()).isoformat()

    matcher = context.fetchers.get("tier_matcher")
    empty = {
        "tier": tier,
        "considered": len(candidates),
        "model": None,
        "available": False,
        "reason": None,
        "items": [],
    }
    if matcher is None:
        return {**empty, "reason": "no model is configured for tier matching"}
    if not candidates:
        return {**empty, "available": True, "reason": "no candidates to consider"}

    items = []
    model = None
    failures = batches = 0

    for start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[start : start + BATCH_SIZE]
        batches += 1
        offered = {c["symbol"] for c in batch}
        listed = "\n".join(
            f"- {c['symbol']}: {c['description'][:DESCRIPTION_CHARS]}" for c in batch
        )
        try:
            raw, model = matcher(
                PROMPT.format(
                    tier=tier,
                    reasoning=f"Why it is needed: {reasoning}" if reasoning else "",
                    candidates=listed,
                ),
                TASK,
                MODEL_SCHEMA,
            )
        except Exception as exc:
            log.warning("tier matching failed for %r: %s", tier, exc)
            failures += 1
            continue

        matches, clean = items_from(raw, "matches", "symbol")
        if not matches and not clean:
            failures += 1
            continue

        for match in matches:
            if not match.get("participates"):
                continue
            symbol = str(match.get("symbol") or "").strip().upper()
            # A symbol nobody offered cannot become a candidate. This is the whole safety
            # property: the model narrows a list the platform supplied and can never extend it.
            if symbol not in offered:
                continue
            items.append(
                {
                    "source_ref": f"model://{model}/{TASK}?tier={tier}&symbol={symbol}",
                    "observed_at": now,
                    "symbol": symbol,
                    "tier": tier,
                    "why": str(match.get("why") or "").strip()[:200],
                    "matched_by": model or "",
                    "measured_by_platform": False,
                }
            )

    return {
        "tier": tier,
        "considered": len(candidates),
        "model": model,
        # Every batch failing is a matcher that is down; the caller falls back rather than
        # reporting an empty tier as a considered answer.
        "available": failures < batches,
        "reason": f"{failures} of {batches} batches could not be read" if failures else None,
        "items": items,
    }


TOOL = ToolManifest(
    name="tier_match",
    version="1.0.0",
    summary=(
        "Decides which of a shortlist of companies genuinely supply a part of a supply chain. "
        "Use when a tier needs turning into companies and word matching cannot tell that "
        "assembly and test is OSAT."
    ),
    description=(
        "Reads a chain tier and a shortlist of companies described by what they do, and "
        "returns those whose own business supplies that tier, each with a short reason. The "
        "shortlist comes from the platform's universe, and a symbol outside it is dropped "
        "rather than trusted — the model narrows a list it was given and can never extend it, "
        "so it cannot introduce a company that does not exist or is not listed here. Judges "
        "only from the descriptions supplied, and answers false when a description does not "
        "say. Nothing it returns is a measurement."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("themes", "supply-chain", "matching"),
)
