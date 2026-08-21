"""Deciding which headlines are government action.

**Replaces twelve keywords.** The list read `scheme`, `ministry`, `cabinet`, `government`,
`policy`, `budget` and six more, and it was wrong in both directions: an incentive announcement
phrased without any of those words was invisible, and any company story mentioning "government"
was counted as policy. Whether a headline reports a state decision is a comprehension question
and a model answers it; a substring search only ever answered a different, easier one.

**Batched, because feeds are long and calls are slow.** A run sweeps several hundred headlines
and a local model takes seconds per call, so classification goes out in batches of headlines
and comes back as a list of which ones qualified. Roughly five calls per run rather than five
hundred.

Nothing here decides anything about a company. Policy corroborates a theme and can never
create one — it carries no symbol, so it cannot contribute to breadth.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.clock import now_utc
from app.llm.parsing import items_from
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "policy_classify"

#: Headlines per call. Enough to be worth a round trip, few enough that the response stays
#: inside a local model's output budget.
BATCH_SIZE = 25

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "headlines": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Headlines, optionally with a summary appended",
        }
    },
    "required": ["headlines"],
    "additionalProperties": False,
}

#: **Only the positives.** Asked to judge every headline the model returned one row for four
#: inputs — it reports what it found rather than what it rejected, and a schema demanding a
#: verdict per headline just produced silent omissions. Asking for the ones that qualify is
#: the shape it answers in, and the ones it leaves out are the ones it rejected.
MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "policies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "subject": {"type": "string"},
                },
                "required": ["index", "subject"],
            },
        }
    },
    "required": ["policies"],
}

ITEM_SCHEMA = item_schema(
    {
        "index": {"type": "integer"},
        "headline": {"type": "string"},
        #: What the policy is *about*, which is what a theme is counted from.
        "subject": {"type": "string"},
        "classified_by": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["index", "headline", "classified_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "considered": {"type": "integer"},
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

PROMPT = """You are finding government action in a list of news headlines.

Headlines:
{headlines}

List **every** headline that reports a decision, scheme, incentive, regulation, budget
allocation or tender by government. Leave out everything else.

For each one give:
- index: the number shown
- subject: 3-6 words naming the industry or activity it affects

Rules:
- Include every qualifying headline, not a sample. Several may qualify.
- A company's own results, deals or share price is not government action, even when it
  mentions government.
- A policy story qualifies whether or not a scheme is named.
- Judge the government action, not whether it is good news.

Reply with JSON only:
{{"policies": [{{"index": 0, "subject": "..."}}]}}"""


def handle(arguments: dict, context: ToolContext) -> dict:
    headlines = [str(h).strip() for h in arguments["headlines"] if str(h).strip()]
    now = (context.now() if context.now else now_utc()).isoformat()

    classifier = context.fetchers.get("policy_classifier")
    empty = {
        "considered": len(headlines),
        "model": None,
        "available": False,
        "reason": None,
        "items": [],
    }
    if classifier is None:
        return {**empty, "reason": "no model is configured for policy classification"}
    if not headlines:
        return {**empty, "available": True, "reason": "nothing to classify"}

    items: list[dict[str, Any]] = []
    model = None
    failures = 0
    batches = 0

    for start in range(0, len(headlines), BATCH_SIZE):
        batch = headlines[start : start + BATCH_SIZE]
        batches += 1
        numbered = "\n".join(f"{i}. {text[:220]}" for i, text in enumerate(batch))
        try:
            raw, model = classifier(PROMPT.format(headlines=numbered), TASK, MODEL_SCHEMA)
        except Exception as exc:
            log.warning("policy classification failed: %s", exc)
            failures += 1
            continue

        results, clean = items_from(raw, "policies", "index")
        if not results and not clean:
            failures += 1
            continue

        for result in results:
            index = result.get("index")
            if not isinstance(index, int) or not 0 <= index < len(batch):
                # An index nobody offered is the model inventing a headline. Dropped.
                continue
            items.append(
                {
                    "source_ref": f"model://{model}/{TASK}?index={start + index}",
                    "observed_at": now,
                    "index": start + index,
                    "headline": batch[index],
                    "subject": str(result.get("subject") or "").strip()[:120],
                    "classified_by": model or "",
                    "measured_by_platform": False,
                }
            )

    # Every batch failing is a source that is down. Some failing is a partial read, and the
    # caller is told which by `available` rather than left to infer it from a thin result.
    return {
        "considered": len(headlines),
        "model": model,
        "available": failures < batches,
        "reason": f"{failures} of {batches} batches could not be read" if failures else None,
        "items": items,
    }


TOOL = ToolManifest(
    name="policy_classify",
    version="1.0.0",
    summary=(
        "Sorts headlines into government action and everything else, in batches. Use when "
        "scanning news feeds for schemes, incentives, regulation or budget decisions that "
        "affect an industry, rather than for company news."
    ),
    description=(
        "Classifies headlines as government policy or not, and names the industry each policy "
        "affects. Replaces keyword matching, which missed announcements phrased without a "
        "listed word and counted any company story mentioning government. Batched because a "
        "run sweeps hundreds of headlines and a local model takes seconds per call. Reports "
        "how many batches could not be read, so a partial sweep is distinguishable from a "
        "quiet week. Nothing it returns is a measurement or concerns any company."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("policy", "news", "themes"),
)
