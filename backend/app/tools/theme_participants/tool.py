"""Which Indian listed companies participate in this, according to what pages said.

**The one place in this platform where a model proposes a name**, and everything about the
design follows from how much more dangerous that is than proposing a category.

Chain expansion and tier decomposition are safe by construction: a category cannot be bought,
so resolution against the platform's own universe is what turns anything into a name, and that
step belongs to the platform. Here the model reads search excerpts and says "Kaynes Technology".
That removes the structural safety, so it is replaced with three explicit rules:

* **Search first, then summarise.** The model is not asked what it knows. It is given pages and
  asked what they say. The citation then comes from the result rather than from a model's
  recollection, which is the difference between a claim and a memory.
* **A proposal without a citation is discarded.** Not shown with a caveat -- discarded. An
  uncited proposal is a recollection wearing the clothes of a finding.
* **A proposal is inert.** Nothing here produces a candidate. It produces a *name*, which
  `app/themes/propose.py` resolves against the universe, where ambiguity produces nothing at
  all. Bharat Electronics and Bharat Dynamics are different companies; several Tata entities
  are separately listed; a plausible-sounding company may be unlisted, delisted, BSE-only or
  renamed.

**Why it is needed at all.** Kaynes Technology is building a semiconductor assembly plant. Its
published business description says "integrated electronics manufacturer" and stops there,
because that is what the company was when the description was written. No granularity of
description matching reaches it -- decomposition, better prompts and a larger model all fail
for the same reason, which is that the fact is not in the data. It is in the news.

Names, never tickers. Deciding that "Kaynes Technology" means `KAYNES` is symbol resolution and
it is the platform's job, not the model's.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.clock import now_utc
from app.llm.parsing import items_from
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "theme_participants"

#: Proposals per sub-category. Small on purpose: this is the narrow, risky half, and a long
#: list is a sign the model is listing an industry rather than reading the pages it was given.
MAX_PROPOSALS = 6

#: Search excerpts shown. Enough that a real participant appears in more than one, which is
#: what lets the model distinguish a reported fact from a single stray mention.
MAX_EXCERPTS = 8

#: Characters per excerpt. The claim is usually in the first sentence or two.
EXCERPT_CHARS = 700

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sub_category": {"type": "string", "description": "The business to find participants in"},
        "reasoning": {"type": "string", "description": "What this business contributes"},
        "excerpts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    "required": ["sub_category", "excerpts"],
    "additionalProperties": False,
}

MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "participants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "rationale": {"type": "string"},
                    "source_indices": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["company", "rationale", "source_indices"],
            },
        }
    },
    "required": ["participants"],
}

ITEM_SCHEMA = item_schema(
    {
        "sub_category": {"type": "string"},
        #: A company *name*. Never a symbol -- resolving one is the platform's step.
        "company": {"type": "string"},
        "rationale": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
        "proposed_by": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["sub_category", "company", "rationale", "sources", "proposed_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "sub_category": {"type": "string"},
        "considered": {"type": "integer"},
        "discarded_uncited": {"type": "integer"},
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

PROMPT = """You are reading search results to find Indian listed companies in one business.

Business: {sub_category}
{reasoning}

Search results:
{excerpts}

Name up to {limit} companies **listed on an Indian stock exchange** that these results say \
participate in this business.

For each give:
- company: the company's name as the results give it
- rationale: at most 20 words on what the results say it does here
- source_indices: the numbers of the results that say so

Rules:
- **Only what these results say.** Do not add companies from your own knowledge, however \
certain you are. A company you know about that is not in these results does not belong here.
- Every company must have at least one source index. A company with no source is not an answer.
- Indian listed companies only. Leave out foreign companies, unlisted companies, subsidiaries \
that are not separately listed, and joint ventures.
- Give the company's own name, not a stock symbol and not a parent's name.
- If the results name no Indian listed company in this business, return an empty list. **That \
is a correct and useful answer** -- some businesses genuinely have no Indian listed presence, \
and saying so precisely is worth as much as a name.
- Say nothing about whether any of them is worth owning.

Reply with JSON only:
{{"participants": [{{"company": "...", "rationale": "...", "source_indices": [0]}}]}}"""


def handle(arguments: dict, context: ToolContext) -> dict:
    sub_category = str(arguments["sub_category"]).strip()
    reasoning = str(arguments.get("reasoning") or "").strip()
    excerpts = [e for e in arguments["excerpts"] if str(e.get("url") or "").strip()][:MAX_EXCERPTS]
    now = (context.now() if context.now else now_utc()).isoformat()

    proposer = context.fetchers.get("participant_proposer")
    empty: dict[str, Any] = {
        "sub_category": sub_category,
        "considered": len(excerpts),
        "discarded_uncited": 0,
        "model": None,
        "available": False,
        "reason": None,
        "items": [],
    }
    if proposer is None:
        return {**empty, "reason": "no model is configured for participant proposals"}
    if not excerpts:
        return {**empty, "reason": "no search results to read"}

    numbered = "\n\n".join(
        f"[{i}] {str(e.get('title') or '').strip()}\n{str(e.get('url'))}\n"
        f"{str(e.get('excerpt') or '').strip()[:EXCERPT_CHARS]}"
        for i, e in enumerate(excerpts)
    )

    try:
        raw, model = proposer(
            PROMPT.format(
                sub_category=sub_category,
                reasoning=reasoning or "",
                excerpts=numbered,
                limit=MAX_PROPOSALS,
            ),
            TASK,
            MODEL_SCHEMA,
        )
    except Exception as exc:
        log.warning("participant proposal failed for %r: %s", sub_category, exc)
        return {**empty, "reason": f"proposal failed: {exc}"}

    parsed, clean = items_from(raw, "participants", "company")
    if not parsed and not clean:
        # Never a partial list. A half-read set of proposals looks complete and would silently
        # omit whichever name the reader most needed.
        return {**empty, "model": model, "reason": "model output was not usable"}

    items: list[dict[str, Any]] = []
    uncited = 0
    seen: set[str] = set()

    for entry in parsed[:MAX_PROPOSALS]:
        company = str(entry.get("company") or "").strip()
        if not company or company.lower() in seen:
            continue

        sources: list[str] = []
        for index in entry.get("source_indices") or []:
            if isinstance(index, bool) or not isinstance(index, int):
                continue
            if 0 <= index < len(excerpts):
                url = str(excerpts[index].get("url") or "").strip()
                if url and url not in sources:
                    sources.append(url)
        if not sources:
            # Discarded, not caveated. Without a source this is the model's recollection, and
            # a recollection is precisely what search-then-summarise exists to avoid.
            log.info("discarded uncited proposal %r for %r", company, sub_category)
            uncited += 1
            continue

        seen.add(company.lower())
        items.append(
            {
                "source_ref": sources[0],
                "observed_at": now,
                "sub_category": sub_category,
                "company": company[:200],
                "rationale": str(entry.get("rationale") or "").strip()[:300],
                "sources": sources,
                "proposed_by": model,
                # A name a model read on a page. Never a measurement, and inert until the
                # platform's own universe confirms it.
                "measured_by_platform": False,
            }
        )

    return {
        "sub_category": sub_category,
        "considered": len(excerpts),
        "discarded_uncited": uncited,
        "model": model,
        "available": True,
        "reason": None if items else "results named no Indian listed participant",
        "items": items,
    }


TOOL = ToolManifest(
    name="theme_participants",
    version="1.0.0",
    summary=(
        "Reads search results and proposes Indian listed companies in one business. Use when "
        "description matching found nobody — a company whose published description predates "
        "the thing you are looking for."
    ),
    description=(
        "Proposes participants in a business from search excerpts, each with a rationale and "
        "the sources that support it. Reads only what it is given: a proposal with no source "
        "is discarded rather than shown, because an uncited proposal is a model's recollection "
        "rather than a finding. Returns company names, never symbols — resolving a name to a "
        "listed instrument happens separately against the platform's own universe, where an "
        "ambiguous name produces nothing at all. Nothing here is a candidate, a measurement, "
        "or evidence, and nothing it returns may move a conviction."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("search", "research", "themes"),
)
