"""Management commentary — what the people running the company said about it.

Earnings-call transcripts are where the forward-looking half of a thesis lives. A balance sheet
records what happened; commentary is where "we are seeing unprecedented demand for X" appears,
often quarters before it shows in a price. That makes it the platform's earliest sensor for a
theme, and the reason this tool exists.

**It returns a document, never a judgement**, and this is the rule that matters most here.
A transcript is the strongest temptation in the whole platform to break `agent-graph`'s
"research produces context, never evidence": it is full of numbers, stated confidently by
people with authority, and they look exactly like measurements. They are not. A measurement
has a threshold, a comparison and a re-fetchable source. Guidance has a speaker and an
interest. So commentary can be quoted, attributed and read — and can never become an
`Evidence` row or move a `conviction`.

**Sections, not one blob.** A 40-page transcript does not fit a local 12B model's context, and
this platform's default routing is local. Returning the whole thing would be a tool that passes
its tests and cannot be used.
"""

from __future__ import annotations

import logging

from app.core.clock import now_utc
from app.tools.commentary.providers import (
    DEFAULT_SECTION_CHARS,
    Document,
    DocumentReader,
    ScreenerDocumentLocator,
)
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "NSE symbol, e.g. RELIANCE"},
        "kind": {
            "type": "string",
            "enum": ["transcript", "annual_report"],
            "default": "transcript",
            "description": "Which document to read. Transcripts carry management commentary.",
        },
        "section": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "Return only this section, zero-indexed. Omit for the first sections. "
                "Documents run to dozens of pages; ask for one part at a time."
            ),
        },
        "max_sections": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "default": 2,
            "description": "How many sections to return when no specific one is asked for",
        },
    },
    "required": ["symbol"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "kind": {"type": "string"},
        "period": {"type": ["string", "null"]},
        "section_index": {"type": "integer"},
        "section_count": {"type": "integer"},
        "text": {"type": "string"},
        "exchange_hosted": {"type": "boolean"},
        # Never a measurement this platform made. Carried on every item so a reader — or a
        # narrative validator — can tell a quotation from a measurement without inferring it.
        "measured_by_platform": {"type": "boolean"},
    },
    required=["symbol", "kind", "section_index", "text"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "symbol": {"type": "string"},
        "document_url": {"type": ["string", "null"]},
        "document_available": {"type": "boolean"},
        "provider": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
    },
)


def _pick(documents: list[Document], kind: str) -> Document | None:
    """The most recent document of the requested kind. Already ordered by the locator."""
    for document in documents:
        if document.kind == kind:
            return document
    return None


def handle(arguments: dict, context: ToolContext) -> dict:
    symbol = arguments["symbol"].strip().upper()
    kind = arguments.get("kind", "transcript")
    section = arguments.get("section")
    max_sections = int(arguments.get("max_sections", 2))
    now = (context.now() if context.now else now_utc()).isoformat()

    locator = context.fetchers.get("document_locator") or ScreenerDocumentLocator()
    reader = context.fetchers.get("document_reader") or DocumentReader(
        cache_dir="./.cache/documents", section_chars=DEFAULT_SECTION_CHARS
    )

    empty = {
        "symbol": symbol,
        "document_url": None,
        "document_available": False,
        "provider": None,
        "reason": None,
        "items": [],
    }

    documents = locator.locate(symbol)
    document = _pick(documents, kind)
    if document is None:
        # A company that has published nothing is an ordinary result, not a failure.
        return {**empty, "reason": f"no {kind} found for {symbol}"}

    sections = reader.sections(document.url)
    if not sections:
        # Reported with the URL, so a reader can open what the platform could not parse.
        # Never partial text: half a transcript read as though whole is worse than none.
        return {
            **empty,
            "document_url": document.url,
            "provider": "exchange" if document.is_exchange_hosted else "aggregator",
            "reason": f"document could not be read: {document.url}",
        }

    if section is not None:
        chosen = [(section, sections[section])] if section < len(sections) else []
    else:
        chosen = list(enumerate(sections[:max_sections]))

    return {
        "symbol": symbol,
        "document_url": document.url,
        "document_available": True,
        "provider": "exchange" if document.is_exchange_hosted else "aggregator",
        "reason": None,
        "items": [
            {
                "source_ref": f"{document.url}#section={index}",
                "observed_at": now,
                "symbol": symbol,
                "kind": document.kind,
                "period": document.period,
                "section_index": index,
                "section_count": len(sections),
                "text": text,
                "exchange_hosted": document.is_exchange_hosted,
                "measured_by_platform": False,
            }
            for index, text in chosen
        ],
    }


TOOL = ToolManifest(
    name="commentary",
    version="1.0.0",
    summary=(
        "Reads the latest earnings-call transcript or annual report for a stock, in sections. "
        "Use when you need what management actually said about demand, capacity, order books "
        "or guidance — the forward-looking context a balance sheet cannot give."
    ),
    description=(
        "Locates a company's most recent management commentary, downloads it once, and "
        "returns it as ordered, individually addressable sections — documents run to dozens "
        "of pages and do not fit a local model's context in one piece. Prefers the "
        "exchange-hosted copy of a document over an aggregator's link, and says which it "
        "used. Everything returned is quoted from the document and is never a measurement "
        "this platform made: no number from a transcript may become evidence or move a "
        "conviction. A company with no published transcript is an empty result, not an error."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("commentary", "transcripts", "research", "themes"),
)
