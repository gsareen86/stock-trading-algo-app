"""Search the open web and return what pages said, with their URLs.

**Excerpts, not answers.** Everything returned here is something a page said, attributed to
that page. Nothing is a measurement, nothing is a claim the platform makes, and nothing may
become an `Evidence` row. The tool that reads these excerpts and proposes participants is
separate, and the step that turns a proposed name into a candidate is separate again and runs
against the platform's own universe.

That separation is the safety argument in full. A model may propose a name; only the universe
may confirm one.

**Three empties that mean different things.** Unconfigured, exhausted and unavailable are
reported distinctly, because a reader looking at a tier with no Indian exposure has to know
whether the platform looked and found nothing or never looked at all. Collapsing them into an
empty list would turn "nobody set this up" into "there is nothing there", which is the most
misleading answer this platform could give.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.clock import now_utc
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

TASK = "web_search"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 2, "description": "What to search for"},
    },
    "required": ["query"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "title": {"type": "string"},
        "url": {"type": "string"},
        "excerpt": {"type": "string"},
        "measured_by_platform": {"type": "boolean"},
    },
    required=["title", "url"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "query": {"type": "string"},
        #: `ok`, `unconfigured`, `exhausted` or `unavailable`. The distinction is the point.
        "outcome": {"type": "string"},
        "available": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
)


def handle(arguments: dict, context: ToolContext) -> dict:
    query = " ".join(str(arguments["query"]).split())
    now = (context.now() if context.now else now_utc()).isoformat()

    searcher = context.fetchers.get("web_search")
    if searcher is None:
        return {
            "query": query,
            "outcome": "unconfigured",
            "available": False,
            "reason": "no search provider is configured",
            "items": [],
        }

    try:
        results = searcher(query)
    except Exception as exc:
        # A search that raises is a search that did not happen. Reported as unavailable
        # rather than as an empty result, which would read as "the web says nothing".
        log.warning("web search failed for %r: %s", query, exc)
        return {
            "query": query,
            "outcome": "unavailable",
            "available": False,
            "reason": f"search failed: {exc}",
            "items": [],
        }

    payload: dict[str, Any] = results.as_dict() if hasattr(results, "as_dict") else dict(results)

    items = []
    for hit in payload.get("hits") or []:
        url = str(hit.get("url") or "").strip()
        if not url:
            continue
        items.append(
            {
                # The page itself is the source. A citation a reader cannot open is not one.
                "source_ref": url,
                "observed_at": now,
                "title": str(hit.get("title") or "").strip()[:300],
                "url": url,
                "excerpt": str(hit.get("excerpt") or "").strip()[:1200],
                "measured_by_platform": False,
            }
        )

    return {
        "query": query,
        "outcome": str(payload.get("outcome") or "ok"),
        "available": bool(payload.get("available", True)),
        "reason": payload.get("reason"),
        "items": items,
    }


TOOL = ToolManifest(
    name="web_search",
    version="1.0.0",
    summary=(
        "Searches the open web and returns page excerpts with their URLs. Use when the answer "
        "is not in the platform's own data — a plant announced after a company's description "
        "was written, or who participates in a business nobody's filings describe."
    ),
    description=(
        "Runs one web search and returns titles, URLs and excerpts. Metered by a monthly "
        "allowance and rate-limited, and reports unconfigured, exhausted and unavailable "
        "distinctly so an empty tier can be told apart from a search that never ran. "
        "Everything returned is something a page said, attributed to that page: nothing here "
        "is a measurement, nothing may become evidence, and nothing may move a conviction. "
        "Proposing companies from these excerpts and confirming a proposed name against the "
        "platform's universe are separate steps, deliberately."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("search", "research", "web"),
)
