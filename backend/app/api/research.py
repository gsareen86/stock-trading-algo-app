"""Ad-hoc research over HTTP.

One endpoint, and it researches rather than advises. The distinction is enforced by what this
module can reach rather than by what it refuses to say: it holds no strategy, no ledger and no
verdict writer, so there is nothing here that could produce a stance however the question is
phrased. See `app/agents/conversation.py` for why that is the boundary instead of a blocklist
of phrasings.

Every answer comes back with the tool calls that produced it, so a reader can open what it read.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.conversation import ask
from app.agents.toolbelt import Toolbelt
from app.api.deps import get_settings
from app.core.settings import Settings
from app.tools.types import ToolContext

router = APIRouter(prefix="/research", tags=["research"])


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


@router.post("/ask")
async def ask_research(
    request: Request,
    payload: AskRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Answer one research question by calling the declared tools.

    Bounded by `research_max_tool_rounds`, the same bound the cycle's research node uses. An
    unbounded loop against a local model is an afternoon, and a model that has misunderstood
    the question will keep calling tools about the wrong thing until something stops it.
    """
    gateway = getattr(request.app.state, "gateway", None)
    registry = getattr(request.app.state, "tools", None)
    if gateway is None or registry is None:
        raise HTTPException(status_code=503, detail="research is not available")

    # The declared registry and nothing else. No MCP servers: those carry no output schema,
    # and the broker's tools in particular can place orders.
    toolbelt = Toolbelt(registry=registry, context=_context(request, settings))

    answer = await ask(
        payload.question,
        toolbelt=toolbelt,
        gateway=gateway,
        max_rounds=settings.research_max_tool_rounds,
        model=settings.model_for_task("research"),
    )
    return answer.as_dict()


def _context(request: Request, settings: Settings) -> ToolContext:
    """The fetchers the research tools need, each absent rather than fabricated.

    A tool whose fetcher is missing reports that it is unconfigured, which is the answer a
    reader needs — not an empty result that reads as "there is nothing there".
    """
    fetchers: dict[str, Any] = {}

    searcher = getattr(request.app.state, "search_source", None)
    if searcher is not None:
        fetchers["web_search"] = searcher.search

    gateway = getattr(request.app.state, "gateway", None)
    if gateway is not None:
        fetchers.update(_model_fetchers(gateway, settings))

    return ToolContext(fetchers=fetchers)


def _model_fetchers(gateway, settings: Settings) -> dict[str, Any]:
    """Adapt the gateway to the `(prompt, task, schema)` shape the tools expect."""
    from app.themes.assembly import _caller

    call = _caller(gateway, settings.model_for_task("research"))
    return {
        name: call
        for name in (
            "tier_decomposer",
            "participant_proposer",
            "concept_extractor",
            "theme_merger",
            "policy_classifier",
            "chain_expander",
            "tier_matcher",
            "transcript_summariser",
        )
    }
