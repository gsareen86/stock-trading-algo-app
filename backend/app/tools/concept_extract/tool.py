"""Reading a document and saying what it is about.

**This replaces a hardcoded list of ten phrase groups**, and the list was wrong at exactly the
point the theme engine exists for. A fixed vocabulary can only surface themes somebody already
thought of, so the engine could never have found the case it was built for — a data-centre
buildout showing up in transformer makers' order books — unless that phrase had been typed in
first. Choosing reproducibility over the actual capability was the wrong trade.

What made the fixed list tempting is real and is handled elsewhere: breadth and persistence are
only meaningful if the same corpus yields the same counts. So extraction runs **once per
document and is persisted**, and counting is arithmetic over stored rows. Re-reading a document
becomes a deliberate act rather than something that happens on every run, which keeps the
counts stable without restricting what can be found.

**Labels here are free-form and are not themes yet.** One company says "data centre demand",
another "hyperscaler capex", a third "AI infrastructure buildout". Merging those into one theme
is `theme_merge`'s job; this tool's only duty is to report faithfully what a document says.
"""

from __future__ import annotations

import logging
import re

from app.core.clock import now_utc
from app.llm.parsing import items_from
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "concept_extract"

#: Concepts per document. A transcript that yields thirty "themes" has not been read, it has
#: been skimmed for nouns — and a cap keeps one voluble document from dominating a run.
MAX_CONCEPTS = 8

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "NSE symbol the document belongs to"},
        "period": {"type": "string", "description": "Reporting period, e.g. Jun 2026"},
        "text": {"type": "string", "description": "Document text, or one section of it"},
        "source_ref": {"type": "string"},
    },
    "required": ["symbol", "period", "text", "source_ref"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "period": {"type": "string"},
        #: Free-form. Canonicalisation happens later, deliberately.
        "label": {"type": "string", "minLength": 3},
        "excerpt": {"type": "string"},
        "extracted_by": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["symbol", "period", "label", "extracted_by"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "symbol": {"type": "string"},
        "model": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)

#: The shape the *model* is constrained to, distinct from this tool's own output schema.
#:
#: Passing it is not a nicety. The default local model is a thinking model, and left
#: unconstrained it spent 3,834 completion tokens reasoning and emitted an empty string — a
#: silent failure that looks exactly like a document with nothing to say. Constrained, the same
#: call answers in 42 tokens with clean JSON and no reasoning at all.
MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
                "required": ["label", "excerpt"],
            },
        }
    },
    "required": ["concepts"],
}

PROMPT = """You are reading a company's disclosure and naming the industry themes it describes.

Company: {symbol}
Period: {period}

Document:
\"\"\"
{text}
\"\"\"

List up to {limit} themes — commercial or industrial developments that would still make sense
if another company in the same industry described them.

For each:
- label: 2-5 words, lower case, naming the development in ordinary industry language
- excerpt: a short quotation from the document supporting it

These ARE themes:
  data centre demand · grid capacity expansion · import substitution · fleet electrification

These are NOT themes and must not be returned:
- this company's own results or outlook: "strong quarter", "margin improvement",
  "order book growth", "demand in 2024"
- this company's internal affairs: "management transition", "new ceo", "one company strategy"
- anything naming a year or a quarter
- generic business words alone: "growth", "expansion", "performance"

Rules:
- Report only what the document says. Add nothing from your own knowledge.
- Name the development, not the company and not the quarter.
- If the document describes no industry theme, return an empty list. That is a valid answer.

Reply with JSON only:
{{"concepts": [{{"label": "...", "excerpt": "..."}}]}}"""


#: Labels that describe a company rather than an industry, or a moment rather than a
#: development. The prompt asks for none of these and a 12B model produced them anyway --
#: "manufacturinger distribution growth", "demand in 2024" and "high performance for 2024" all
#: came out of one live run. A bad label is worse than a missing one: it becomes a theme of its
#: own, survives merging, and clutters every count downstream.
_YEAR = re.compile(r"\b(19|20)\d{2}\b|\bq[1-4]\b|\bfy\s?\d")

_COMPANY_SHAPED = (
    "management transition",
    "leadership",
    "new ceo",
    "our strategy",
    "company strategy",
    "quarterly performance",
    "strong quarter",
    "margin improvement",
    "cost optimisation",
    "cost optimization",
    "guidance",
)

#: Words that say nothing on their own. A label made only of these names no development.
_GENERIC = {
    "growth",
    "demand",
    "expansion",
    "performance",
    "revenue",
    "margins",
    "outlook",
    "strategy",
    "investment",
    "opportunity",
    "transition",
    "momentum",
    "recovery",
    "strong",
    "higher",
    "increase",
}


def is_theme_shaped(label: str) -> tuple[bool, str | None]:
    """Whether a label names an industry development. Returns ``(ok, why_not)``."""
    cleaned = " ".join(label.lower().split())
    if len(cleaned) < 6:
        return False, "too short to name a development"
    if _YEAR.search(cleaned):
        return False, "names a year or quarter rather than a development"

    words = cleaned.split()
    if len(words) < 2:
        return False, "a single word does not name a development"
    if len(words) > 6:
        return False, "too long to be a theme label"
    if all(word in _GENERIC for word in words):
        return False, "generic business words only"
    if any(phrase in cleaned for phrase in _COMPANY_SHAPED):
        return False, "describes this company rather than its industry"
    return True, None


def handle(arguments: dict, context: ToolContext) -> dict:
    symbol = arguments["symbol"].strip().upper()
    period = arguments["period"].strip()
    text = arguments["text"]
    source_ref = arguments["source_ref"]
    now = (context.now() if context.now else now_utc()).isoformat()

    extractor = context.fetchers.get("concept_extractor")
    empty = {"symbol": symbol, "model": None, "available": False, "reason": None, "items": []}
    if extractor is None:
        return {**empty, "reason": "no model is configured for concept extraction"}
    if not text or not text.strip():
        return {**empty, "reason": "document is empty"}

    try:
        raw, model = extractor(
            PROMPT.format(symbol=symbol, period=period, text=text, limit=MAX_CONCEPTS),
            TASK,
            MODEL_SCHEMA,
        )
    except Exception as exc:
        # A document that could not be read is not a company with nothing to say. The caller
        # records the difference, and a run reports it as a source that degraded.
        log.warning("concept extraction failed for %s: %s", symbol, exc)
        return {**empty, "reason": f"extraction failed: {exc}"}

    concepts, clean = items_from(raw, "concepts", "label")
    items = []
    rejected: list[str] = []
    for concept in concepts[:MAX_CONCEPTS]:
        if not isinstance(concept, dict):
            continue
        label = str(concept.get("label") or "").strip()
        shaped, why = is_theme_shaped(label)
        if not shaped:
            rejected.append(f"{label} ({why})")
            continue
        items.append(
            {
                "source_ref": source_ref,
                "observed_at": now,
                "symbol": symbol,
                "period": period,
                "label": label.lower(),
                "excerpt": str(concept.get("excerpt") or "").strip()[:400],
                "extracted_by": model,
                # Read from a document by a model. Never a measurement this platform made.
                "measured_by_platform": False,
            }
        )

    # An empty list here is a real answer -- a document describing no clear theme -- and is
    # distinct from `available: False`, which means the document could not be read at all.
    if not items and not clean:
        # Nothing parsed and the response was malformed. That is a read that failed, not a
        # document with nothing to say, and the caller records the two differently.
        return {**empty, "model": model, "reason": "model output could not be read"}

    return {
        "symbol": symbol,
        "model": model,
        "available": True,
        "reason": (
            None
            if items
            else f"no theme-shaped concept; {len(rejected)} rejected"
            if rejected
            else "document described no clear theme"
        ),
        "items": items,
    }


TOOL = ToolManifest(
    name="concept_extract",
    version="1.0.0",
    summary=(
        "Reads a company document and names the commercial themes it describes. Use when you "
        "need to know what a transcript or filing is actually about, rather than searching it "
        "for words you already suspected."
    ),
    description=(
        "Extracts free-form theme labels from a company's own disclosure, each with a "
        "supporting quotation. Labels are deliberately not canonical — one company's "
        "'hyperscaler capex' and another's 'data centre demand' are merged into a single theme "
        "later, by a step that can see the themes already standing. Reports only what the "
        "document says and adds nothing from the model's own knowledge; a document describing "
        "no clear theme returns an empty list, which is different from one that could not be "
        "read. Nothing returned is a measurement and none of it may become evidence."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("themes", "documents", "research"),
)
