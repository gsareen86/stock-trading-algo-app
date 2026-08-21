"""Deciding which freely-worded concepts are the same theme.

**This is the crux of open-vocabulary extraction, not a tidying step.** Extraction reports what
each document says, so one company's "hyperscaler capex", another's "data centre demand" and a
third's "AI infrastructure buildout" arrive as three labels. Left unmerged, each has a breadth
of one, none clears a threshold, and the engine would surface *nothing* — strictly worse than
the hardcoded list it replaced. Merging is what turns faithful extraction into a countable
theme.

**Merged against the themes already standing**, not just within a run. A theme that has been
building for three quarters must keep accumulating breadth as new companies describe it in
their own words; comparing only within a run would restart it every time and persistence would
never grow past one.

Every merge is an artefact, for the same reason a chain link is: it is a model's judgement, a
reader may disagree, and a wrong merge is worse than a wrong chain link because it silently
inflates the counts that decide what surfaces. So each carries its reasoning and can be
rejected, and a rejected merge stays rejected.
"""

from __future__ import annotations

import logging

from app.core.clock import now_utc
from app.llm.parsing import items_from
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "theme_merge"

#: Concepts per call. Small, because the constraint is the *response*, not the prompt: a 12B
#: model spent six hundred completion tokens placing a single concept, so a long list overruns
#: its output budget and arrives truncated. Salvage recovers what did arrive, and batching
#: keeps there from being much to lose. The caller batches.
MAX_CONCEPTS = 10

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Free-form labels extracted from documents",
        },
        "standing": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Themes already established, which new concepts may belong to",
        },
    },
    "required": ["concepts"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "concept": {"type": "string"},
        #: The theme this concept belongs to. Equal to `concept` when it is its own theme.
        "theme": {"type": "string"},
        "merged": {"type": "boolean"},
        "reasoning": {"type": "string"},
        "decided_by": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["concept", "theme", "decided_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

#: What the model is constrained to emit. See `concept_extract.MODEL_SCHEMA` — unconstrained,
#: the local thinking model returns nothing at all.
MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "placements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string"},
                    "theme": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["concept", "theme", "reasoning"],
            },
        }
    },
    "required": ["placements"],
}

PROMPT = """You are grouping industry themes that different companies described in their own \
words.

Themes already established:
{standing}

New concepts to place:
{concepts}

For each new concept, decide whether it describes the same underlying commercial theme as one \
of the established themes, or is a distinct theme of its own.

For each give:
- concept: the new concept, copied exactly
- theme: the established theme it belongs to, or the concept itself if it is distinct
- reasoning: at most 12 words

Rules:
- Merge only when the same underlying development is being described. "data centre demand" and \
"hyperscaler capex" are one theme; "data centre demand" and "cloud software revenue" are not.
- Being in the same sector is not enough. Two different developments in one industry are two \
themes.
- When unsure, keep it distinct. A wrong merge silently combines unrelated evidence.

Reply with JSON only:
{{"placements": [{{"concept": "...", "theme": "...", "reasoning": "..."}}]}}"""


def handle(arguments: dict, context: ToolContext) -> dict:
    concepts = [str(c).strip().lower() for c in arguments["concepts"] if str(c).strip()]
    standing = [str(s).strip().lower() for s in (arguments.get("standing") or []) if str(s).strip()]
    now = (context.now() if context.now else now_utc()).isoformat()

    merger = context.fetchers.get("theme_merger")
    empty = {"model": None, "available": False, "reason": None, "items": []}
    if merger is None:
        return {**empty, "reason": "no model is configured for theme merging"}
    if not concepts:
        return {**empty, "available": True, "reason": "nothing to place"}

    try:
        raw, model = merger(
            PROMPT.format(
                standing="\n".join(f"- {s}" for s in standing) or "(none yet)",
                concepts="\n".join(f"- {c}" for c in concepts[:MAX_CONCEPTS]),
            ),
            TASK,
            MODEL_SCHEMA,
        )
    except Exception as exc:
        log.warning("theme merge failed: %s", exc)
        return {**empty, "reason": f"merge failed: {exc}"}

    placements, clean = items_from(raw, "placements", "concept")
    if not placements and not clean:
        # Every concept would otherwise fall through to "kept distinct", which reads as a
        # considered decision and is not one. A merge step that cannot be read must say so:
        # silently declaring everything distinct is how open-vocabulary extraction quietly
        # stops producing themes at all.
        return {**empty, "model": model, "reason": "merge output could not be read"}

    known = set(concepts)
    items = []
    for placement in placements:
        if not isinstance(placement, dict):
            continue
        concept = str(placement.get("concept") or "").strip().lower()
        theme = str(placement.get("theme") or "").strip().lower()
        # A placement for a concept nobody submitted is the model inventing work. Dropped
        # rather than trusted -- it would create a theme from nothing.
        if concept not in known or not theme:
            continue
        items.append(
            {
                "source_ref": f"model://{model}/{TASK}?concept={concept}",
                "observed_at": now,
                "concept": concept,
                "theme": theme,
                "merged": theme != concept,
                "reasoning": str(placement.get("reasoning") or "").strip()[:400],
                "decided_by": model,
                "measured_by_platform": False,
            }
        )

    placed = {item["concept"] for item in items}
    # Anything the model ignored stands on its own. Silently dropping a concept would lose a
    # theme; defaulting it to itself is the conservative reading and matches "when unsure,
    # keep it distinct".
    for concept in concepts:
        if concept not in placed:
            items.append(
                {
                    "source_ref": f"model://{model}/{TASK}?concept={concept}",
                    "observed_at": now,
                    "concept": concept,
                    "theme": concept,
                    "merged": False,
                    "reasoning": "not placed by the model; kept distinct",
                    "decided_by": model,
                    "measured_by_platform": False,
                }
            )

    return {"model": model, "available": True, "reason": None, "items": items}


TOOL = ToolManifest(
    name="theme_merge",
    version="1.0.0",
    summary=(
        "Groups freely-worded theme labels into single themes. Use when concepts extracted "
        "from different companies may describe the same development in different words, and "
        "counting them separately would understate every one of them."
    ),
    description=(
        "Places each extracted concept either onto a theme already standing or onto itself as "
        "a new one, comparing against established themes so a theme keeps accumulating breadth "
        "as new companies describe it in their own words. Every placement carries its reasoning "
        "and the model that decided it, because a wrong merge silently combines unrelated "
        "evidence and inflates the counts that decide what surfaces. A concept the model does "
        "not place is kept distinct rather than dropped."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("themes", "canonicalisation", "research"),
)
