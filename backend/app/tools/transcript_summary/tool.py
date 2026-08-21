"""What management actually said, in the shape an analyst reads.

Concept extraction answers "what themes does this describe" for counting. This answers a
different question — "what did management say and where are they pointing" — and the two are
kept apart because they are read at different times. Concepts are swept weekly across many
companies; a summary is produced when somebody opens one company and wants to understand it.

**Five categories, adapted from a framework that works.** Financial performance, operational
drivers, strategy, outlook, and risks. Three things changed for this platform:

*Structured, not markdown.* The default local model is a thinking model and returns nothing at
all unless constrained by a schema, so the model fills fields and the surface renders them.
Asking a 12B model for a formatted report produces prose it then fails to emit.

*Quoted, never measured.* "Revenue rose 21% to ₹829 crore" is a thing a chief executive said,
not a measurement this platform made — the same distinction that keeps a transcript out of an
`Evidence` row. Every figure here carries its speaker, and none may move a conviction.

*"Not discussed" is a first-class answer.* Kept from the original framework and reinforced,
because it is the same rule as "unavailable is never zero" that runs through this codebase: a
model that fills an empty section with plausible generalities has invented the most dangerous
kind of content, one that reads exactly like reporting.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.clock import now_utc
from app.llm.parsing import items_from
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "transcript_summary"

#: The framework, in the order an analyst reads it. Each is asked for separately so a truncated
#: response loses the last section rather than corrupting all five.
SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "financial_performance",
        "Revenue, profit and margins with their direction and the reasons given; debt, cash "
        "and capital allocation",
    ),
    (
        "operational_drivers",
        "Whether growth came from volume or price; distribution, capacity, utilisation; how "
        "each business segment performed",
    ),
    (
        "strategy_and_investment",
        "New products, markets or segments; capital expenditure and what it buys; "
        "integration, partnerships and acquisitions",
    ),
    (
        "outlook_and_guidance",
        "Explicit targets and timeframes; what management expects to convert this year versus "
        "what is a multi-year play",
    ),
    (
        "risks_and_drags",
        "Segments declining; losses and when they are expected to end; input costs, currency, "
        "regulation, base effects and demand weakness",
    ),
)

NOT_DISCUSSED = "Not discussed by management"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "company": {"type": "string"},
        "period": {"type": "string"},
        "text": {"type": "string", "description": "Transcript text, or a section of it"},
        "source_ref": {"type": "string"},
    },
    "required": ["symbol", "period", "text", "source_ref"],
    "additionalProperties": False,
}

MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["headline", "detail"],
            },
        }
    },
    "required": ["points"],
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "period": {"type": "string"},
        "section": {"type": "string"},
        #: A few words a reader scans; the detail carries the figures.
        "headline": {"type": "string"},
        "detail": {"type": "string"},
        "summarised_by": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["symbol", "section", "headline", "detail", "summarised_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "symbol": {"type": "string"},
        "period": {"type": "string"},
        "sections_covered": {"type": "array", "items": {"type": "string"}},
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

PROMPT = """You are an equity research analyst reading a management conference call.

Company: {company} ({symbol})
Period: {period}

Transcript:
\"\"\"
{text}
\"\"\"

Report only what management said about **{section_name}**:
{section_about}

Give up to {limit} points. For each:
- headline: 3-6 words naming the point
- detail: one or two sentences, using management's own figures where they gave any

Rules:
- Quote the figures management actually used, with their units. Do not write that something
  grew strongly when a number was given, and do not supply a number when none was given.
- **Never invent a figure.** If this text carries no numbers for this heading, describe what
  was said without them.
- If this text does not cover {section_name} at all, return a single point with headline
  "Not discussed" and detail "{not_discussed}".
- Skip pleasantries, thanks and procedural remarks. No marketing language.

Reply with JSON only:
{{"points": [{{"headline": "...", "detail": "..."}}]}}"""


#: Points per section. A call asked for five headings at once returned one, and its single
#: detail was the example figure copied out of the prompt rather than anything from the
#: transcript. Asked for one heading it answers that heading — the same pattern as merging and
#: policy classification, where this model does one focused job well and a compound one badly.
#: A summary is therefore five calls, and the prompt now contains no figure to copy.
MAX_POINTS = 4


def echoes_the_prompt(headline: str, section_name: str, about: str) -> bool:
    """Whether a headline is the instruction repeated back rather than a finding.

    A small model under-engaged with a long document restates the question — "Report only what
    management said about operational drivers" arrived as a headline in a live run. It reads
    like a finding at a glance and contains nothing, which makes it worse than an absent
    section: a reader scanning headlines cannot tell it apart from a real one.
    """
    cleaned = " ".join(headline.lower().split())
    if cleaned.startswith(("report ", "list ", "give ", "for each", "summarise", "summarize")):
        return True
    if section_name.lower() in cleaned and len(cleaned.split()) > 4:
        return True
    # A headline that is just the section brief handed back.
    return cleaned in " ".join(about.lower().split())


def handle(arguments: dict, context: ToolContext) -> dict:
    symbol = arguments["symbol"].strip().upper()
    company = (arguments.get("company") or symbol).strip()
    period = arguments["period"].strip()
    text = arguments["text"]
    source_ref = arguments["source_ref"]
    now = (context.now() if context.now else now_utc()).isoformat()

    summariser = context.fetchers.get("transcript_summariser")
    empty = {
        "symbol": symbol,
        "period": period,
        "sections_covered": [],
        "model": None,
        "available": False,
        "reason": None,
        "items": [],
    }
    if summariser is None:
        return {**empty, "reason": "no model is configured for transcript summaries"}
    if not text or not text.strip():
        return {**empty, "reason": "no transcript text supplied"}

    items: list[dict[str, Any]] = []
    model = None
    failed = 0

    for name, about in SECTIONS:
        try:
            raw, model = summariser(
                PROMPT.format(
                    company=company,
                    symbol=symbol,
                    period=period,
                    text=text,
                    section_name=name.replace("_", " "),
                    section_about=about,
                    limit=MAX_POINTS,
                    not_discussed=NOT_DISCUSSED,
                ),
                TASK,
                MODEL_SCHEMA,
            )
        except Exception as exc:
            log.warning("transcript summary failed for %s/%s: %s", symbol, name, exc)
            failed += 1
            continue

        points, clean = items_from(raw, "points", "headline")
        if not points and not clean:
            failed += 1
            continue

        for point in points[:MAX_POINTS]:
            detail = str(point.get("detail") or "").strip()
            headline = str(point.get("headline") or "").strip()
            if not detail or not headline:
                continue
            if echoes_the_prompt(headline, name.replace("_", " "), about):
                continue
            items.append(
                {
                    "source_ref": source_ref,
                    "observed_at": now,
                    "symbol": symbol,
                    "period": period,
                    "section": name,
                    "headline": headline[:120],
                    "detail": detail[:800],
                    "summarised_by": model,
                    # Management's claim, read by a model. Never a platform measurement, and
                    # no figure here may reach an evidence row or move a conviction.
                    "measured_by_platform": False,
                }
            )

    if failed == len(SECTIONS):
        return {**empty, "model": model, "reason": "no section could be summarised"}

    covered = sorted({item["section"] for item in items})
    return {
        "symbol": symbol,
        "period": period,
        # Which headings this text actually spoke to. A transcript read in sections will cover
        # different ones each time, and a reader needs to know what they are not seeing.
        "sections_covered": covered,
        "model": model,
        "available": True,
        "reason": None if items else "no usable points in this text",
        "items": items,
    }


TOOL = ToolManifest(
    name="transcript_summary",
    version="1.0.0",
    summary=(
        "Summarises a management call under five analyst headings — performance, operations, "
        "strategy, outlook and risks. Use when you need to understand what management said "
        "and where they are pointing, rather than what themes the call describes."
    ),
    description=(
        "Reads a conference call and reports management's own statements under financial "
        "performance, operational drivers, strategy and investment, outlook and guidance, and "
        "risks and drags. Quantitative wherever management gave a figure, and explicit that a "
        "heading was not discussed rather than filling it with generalities — an invented "
        "section reads exactly like a reported one, which makes it the most dangerous content "
        "the tool could produce. Everything returned is attributed to management and is never "
        "a measurement this platform made: no figure here may become evidence or move a "
        "conviction."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("commentary", "transcripts", "research", "summary"),
)
