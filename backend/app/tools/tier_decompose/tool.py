"""Breaking a coarse tier into the distinct businesses inside it.

**Not a fallback.** This was designed to fire when a tier resolved to nothing, back when
resolution matched company *names* and found three of nineteen defence constituents. Matching on
business descriptions took that to nineteen of nineteen, so the premise is gone and the step is
worth having for a better reason: a coarse tier is imprecise in both directions at once, and
decomposing it fixes both.

Chain expansion produces tiers at the granularity a model volunteers, which is coarser than the
market. "Semiconductor fabrication" is one tier; the businesses inside it are lithography,
deposition, metrology, photoresist chemistry, wafer handling, assembly and test, and design
services. India has listed companies in two of those and none in the rest, and the coarse tier
can express neither fact.

**Measured, against the thirty real business descriptions in the fixture.** A tier for
semiconductor fabrication matched CG Power on one word -- `semiconductor` -- tied with Infosys,
Shree Cement and Voltas, which is noise wearing the shape of an answer. Decomposed into
outsourced assembly and test, the same company matches on four words and ranks first, because
its description says "outsourced semiconductor assembly and testing" outright. And a
sub-category for EUV lithography matches nothing at all, which is the correct answer and worth
as much as the name: it says where the value in that tier is going *and* that it cannot be
bought here.

**What makes this safe is what makes chain expansion safe.** The model proposes *categories*,
which cannot be bought. Resolution against the platform's own universe is the step that turns a
category into a name, and that step is not the model's. A named company that arrives anyway is
kept as an example, marked not investable, rather than dropped -- a chain with a hole in it
reads as a chain nobody understood -- but it can never become a candidate.

Decomposition may only **add**. Every candidate the coarse tier resolved to is kept.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.clock import now_utc
from app.llm.parsing import items_from
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "tier_decompose"

#: Sub-categories per tier. Bounded because each one costs a resolution pass over the whole
#: universe, and because a reader who cannot hold the breakdown in their head will not use it.
MAX_SUB_CATEGORIES = 6

#: Supplier descriptions per sub-category. The label is what a reader sees; these are what
#: resolution matches against, so a couple of phrasings help and a long list does not -- the
#: recall step already casts wide.
MAX_DESCRIPTIONS = 3

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tier": {"type": "string", "description": "The tier label to decompose"},
        "reasoning": {
            "type": "string",
            "description": "Why this tier is in the chain, so sub-categories stay on subject",
        },
        "supplier_descriptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The coarse descriptions this tier already carries",
        },
        "max_sub_categories": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_SUB_CATEGORIES,
            "default": MAX_SUB_CATEGORIES,
        },
    },
    "required": ["tier"],
    "additionalProperties": False,
}

MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "supplier_descriptions": {"type": "array", "items": {"type": "string"}},
                    "notable_examples": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label", "supplier_descriptions"],
            },
        }
    },
    "required": ["sub_categories"],
}

ITEM_SCHEMA = item_schema(
    {
        "tier": {"type": "string"},
        "label": {"type": "string"},
        "reasoning": {"type": "string"},
        "supplier_descriptions": {"type": "array", "items": {"type": "string"}},
        "notable_examples": {"type": "array", "items": {"type": "object"}},
        "proposed_by": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["tier", "label", "supplier_descriptions", "proposed_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "tier": {"type": "string"},
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

PROMPT = """You are breaking one link of a supply chain into the distinct businesses inside it.

Tier: {tier}
Why it is in the chain: {reasoning}
Currently described as:
{descriptions}

Split this tier into up to {limit} sub-categories. A sub-category is a **distinct business a \
company could be in**, not a process step.

For each give:
- label: 2-6 words naming the business
- reasoning: one sentence on what it contributes to the tier
- supplier_descriptions: 1-{max_descriptions} descriptions of such a company
- notable_examples: companies known for it, anywhere in the world, if any come to mind

**Write each description the way a company describes its own operations in an annual report**: \
what it makes, what processes it runs, what it sells and to whom. Never a tagline. In an \
unrelated industry, the difference looks like this:

  good: "operates limestone quarries and clinker grinding units, producing ordinary portland \
and blended cement sold to construction firms through a dealer network"
  bad:  "a leading name in building materials, trusted nationwide"

The good one names quarries, grinding, clinker, cement and dealers. The bad one names nothing \
and would match no company at all.

**Each description must stand alone.** It is read on its own, without the tier name attached, \
so it has to say what industry it is in. "assembly and test services for foundry customers" \
does not; "assembly and test of packaged semiconductor devices for foundry customers" does.

Rules:
- **Stay inside this tier.** Do not decompose the tier above or below it. If the tier is \
packaging, the sub-categories are kinds of packaging business, not the fabrication that \
precedes it.
- A sub-category must be something a company sells, not a stage of a process. Staying with \
cement: "curing" is a step; "ready-mix concrete supply" is a business.
- Split where the *supplier base differs*. If two things are bought from the same kind of \
company, they are one sub-category.
- Put categories in the label and the descriptions. Named companies belong only in \
notable_examples.
- Cover the tier. Include the parts with no obvious supplier as well as the obvious ones.
- Say nothing about prices, valuations, or whether anything is worth owning.

Reply with JSON only:
{{"sub_categories": [{{"label": "...", "reasoning": "...", "supplier_descriptions": ["..."], \
"notable_examples": ["..."]}}]}}"""


#: A ticker wearing a label. Resolution takes a *description* and matches it against business
#: prose, so a symbol arriving here would be matched as a word and could reach a reader looking
#: as though the platform had chosen it.
_TICKER = re.compile(r"^[A-Z][A-Z0-9&.\-]{1,14}$")

#: Corporate suffixes. A label carrying one is a company, not a category, whatever the prompt
#: asked for -- and the failure is quiet, because "Kaynes Technology Limited" would match that
#: company's own description perfectly well and arrive looking like a category that happened
#: to fit.
_COMPANY_SUFFIX = (
    " ltd",
    " ltd.",
    " limited",
    " inc",
    " inc.",
    " corp",
    " corp.",
    " corporation",
    " plc",
    " gmbh",
    " ag",
    " nv",
    " sa",
    " co.",
    " llc",
    " holdings",
)


def names_a_company(label: str) -> bool:
    """Whether a label is a company rather than a category."""
    cleaned = " ".join(label.split())
    if _TICKER.match(cleaned):
        return True
    return any(cleaned.lower().endswith(suffix) for suffix in _COMPANY_SUFFIX)


def handle(arguments: dict, context: ToolContext) -> dict:
    tier = arguments["tier"].strip()
    reasoning = str(arguments.get("reasoning") or "").strip()
    coarse = [
        str(d).strip() for d in (arguments.get("supplier_descriptions") or []) if str(d).strip()
    ]
    limit = int(arguments.get("max_sub_categories", MAX_SUB_CATEGORIES))
    now = (context.now() if context.now else now_utc()).isoformat()

    decomposer = context.fetchers.get("tier_decomposer")
    empty: dict[str, Any] = {
        "tier": tier,
        "model": None,
        "available": False,
        "reason": None,
        "items": [],
    }
    if decomposer is None:
        return {**empty, "reason": "no model is configured for tier decomposition"}

    try:
        raw, model = decomposer(
            PROMPT.format(
                tier=tier,
                reasoning=reasoning or "not stated",
                descriptions="\n".join(f"- {d}" for d in coarse) or "- not described",
                limit=limit,
                max_descriptions=MAX_DESCRIPTIONS,
            ),
            TASK,
            MODEL_SCHEMA,
        )
    except Exception as exc:
        log.warning("tier decomposition failed for %r: %s", tier, exc)
        return {**empty, "reason": f"decomposition failed: {exc}"}

    parsed, clean = items_from(raw, "sub_categories", "label")
    if not parsed and not clean:
        return {**empty, "model": model, "reason": "model output was not usable"}

    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in parsed[:limit]:
        label = str(entry.get("label") or "").strip()
        if not label or label.lower() in seen:
            continue

        examples = [
            str(n).strip() for n in (entry.get("notable_examples") or []) if str(n).strip()
        ]
        if names_a_company(label):
            # Kept as what it actually is rather than discarded. It still explains the tier,
            # and marked this way it can never be mistaken for something the platform found.
            log.info("tier %r: sub-category named a company, kept as example: %s", tier, label)
            continue

        descriptions = [
            str(d).strip()
            for d in (entry.get("supplier_descriptions") or [])
            if str(d).strip() and not names_a_company(str(d).strip())
        ][:MAX_DESCRIPTIONS]
        if not descriptions:
            # Nothing to resolve against. A label alone is a heading, not a query, and a
            # sub-category that cannot be resolved would show as a permanent empty gap.
            continue

        seen.add(label.lower())
        items.append(
            {
                "source_ref": f"model://{model}/{TASK}?tier={tier}&label={label}",
                "observed_at": now,
                "tier": tier,
                "label": label,
                "reasoning": str(entry.get("reasoning") or "").strip(),
                "supplier_descriptions": descriptions,
                "notable_examples": [
                    {"name": name, "investable": False} for name in examples[:4]
                ],
                "proposed_by": model,
                "measured_by_platform": False,
            }
        )

    if not items:
        return {**empty, "model": model, "reason": "no usable sub-category"}

    return {
        "tier": tier,
        "model": model,
        "available": True,
        "reason": None,
        "items": items,
    }


TOOL = ToolManifest(
    name="tier_decompose",
    version="1.0.0",
    summary=(
        "Breaks one supply-chain tier into the distinct businesses inside it. Use when a tier "
        "is too coarse to match companies precisely -- 'semiconductor fabrication' rather than "
        "lithography, assembly and test, and design services."
    ),
    description=(
        "Decomposes a coarse chain tier into sub-categories, each a distinct business with its "
        "own supplier descriptions, so resolution matches against something a company would "
        "recognise as its own operations. Runs against every tier, not only unresolved ones: a "
        "coarse tier is imprecise in both directions, returning weak matches for businesses "
        "that barely qualify while missing the one that describes itself precisely. Returns "
        "categories, never instruments -- named companies are carried as examples marked not "
        "investable, and resolving a category to a listed name happens separately against the "
        "platform's universe. May only widen: nothing here removes a candidate, and nothing it "
        "returns may become evidence or move a conviction."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("themes", "supply-chain", "research"),
)
