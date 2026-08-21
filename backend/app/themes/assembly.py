"""Building a theme runner out of the pieces the application already has.

Everything here exists and is tested in isolation; this is the wiring, kept in one place so the
application factory stays a list of what exists rather than a description of how themes work.

**Every model-backed step degrades to absent.** No key, no local model, no `agents` extra — each
produces a runner that reads what it can and reports what it could not, rather than one that
raises at startup. A platform that refuses to boot because a scraper is down is worse than one
that says a source was unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.settings import Settings
from app.llm.types import LLMGateway, Message
from app.themes.extraction import ConceptStore
from app.themes.runner import Gathered, ThemeRunner
from app.themes.store import ThemeStore
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext

log = logging.getLogger(__name__)

#: Documents a scheduled run reads. Reading is minutes of local model time each, and already-read
#: documents are skipped, so a weekly run works through the universe over months rather than
#: attempting it in one night.
DEFAULT_DOCUMENT_BUDGET = 20


def _caller(gateway: LLMGateway, model: str):
    """Adapt the gateway to the `(prompt, task, schema) -> (text, model)` shape tools expect.

    The schema is not optional in practice. The default local model is a thinking model and
    returns an empty string unconstrained — a silent failure that looks exactly like a document
    with nothing to say.
    """
    import asyncio

    def call(prompt: str, task: str, schema: dict | None = None) -> tuple[str, str]:
        result = asyncio.run(
            gateway.complete(
                task=task, messages=[Message(role="user", content=prompt)], schema=schema
            )
        )
        if result is None:
            raise RuntimeError(f"no model available for {task}")
        return result.text, model

    return call


def build_runner(
    settings: Settings,
    session_factory,
    gateway: LLMGateway,
    tools: ToolRegistry,
    universe_source,
    profile_source=None,
    document_budget: int = DEFAULT_DOCUMENT_BUDGET,
) -> ThemeRunner:
    """A runner wired to the live sources, models and stores."""
    themes = ThemeStore(session_factory)
    concepts = ConceptStore(session_factory)
    model = settings.model_for_task("research")
    call = _caller(gateway, model)

    def gather() -> Gathered:
        from app.domain.themes import SourceKind
        from app.themes import sources

        period = _current_period()
        symbols = [i.symbol for i in universe_source.snapshot().instruments]
        sectors = {i.symbol: i.sector for i in universe_source.snapshot().instruments if i.sector}
        unavailable: list[SourceKind] = []
        references: list[Any] = []
        documents = 0

        commentary = sources.read_documents(
            symbols,
            reader=_commentary_reader(tools),
            extractor=_extractor(tools, call),
            store=concepts,
            period=period,
            kind=SourceKind.COMMENTARY,
            sectors=sectors,
            limit=document_budget,
        )
        references.extend(commentary.references)
        documents += commentary.documents_read
        if not commentary.available:
            unavailable.append(SourceKind.COMMENTARY)

        policy = sources.policy_references(classifier=_classifier(tools, call), period=period)
        references.extend(policy.references)
        if not policy.available:
            unavailable.append(SourceKind.POLICY)

        # Merge before counting, or nothing counts. "demand in data centers", "data center
        # demand" and "demand for data centers" arrived from three companies in one real run;
        # left apart they are three themes of one company each and every threshold rejects
        # them. This is the step that turns faithful reading into a countable theme, so it runs
        # on every pass over whatever is still unplaced.
        _merge_unplaced(concepts, tools, call, themes)

        return Gathered(
            # Re-read after merging: the references a run counts must carry the theme keys the
            # merge just decided, not the raw wordings they were stored under.
            references=concepts.references() + [r for r in references if not r.symbol],
            documents_read=documents,
            unavailable=tuple(unavailable),
        )

    return ThemeRunner(
        store=themes,
        gatherer=gather,
        universe_source=universe_source,
        expander=_expander(tools, call),
        profile_source=profile_source,
    )


def _merge_unplaced(concepts: ConceptStore, tools: ToolRegistry, call, themes: ThemeStore) -> int:
    """Place every concept not yet assigned to a theme. Returns how many were placed.

    Only the unplaced ones: a placement already made is a decision, and re-deciding it every
    run would let a merge somebody rejected quietly return by another route.
    """
    unplaced = concepts.labels(placed=False)
    if not unplaced:
        return 0

    standing = [t["key"] for t in themes.standing(limit=200)]
    placed = 0
    from app.tools.theme_merge.tool import MAX_CONCEPTS

    for start in range(0, len(unplaced), MAX_CONCEPTS):
        batch = unplaced[start : start + MAX_CONCEPTS]
        result = tools.invoke(
            "theme_merge",
            {"concepts": batch, "standing": standing},
            ToolContext(fetchers={"theme_merger": call}),
        )
        if not result.ok or not (result.data or {}).get("available"):
            log.warning("theme merge unavailable; concepts stay unplaced this run")
            continue
        written, _ = concepts.place(result.items)
        placed += written
        # Later batches see what earlier ones established, so three wordings of one theme
        # arriving in different batches still converge.
        standing = sorted({*standing, *(i["theme"] for i in result.items)})

    return placed


def _current_period() -> str:
    """The reporting period a run attributes what it reads to, e.g. `Jun 2026`."""
    from app.core.clock import now_ist

    now = now_ist()
    quarter_end_month = ((now.month - 1) // 3) * 3 + 3
    return f"{['Mar', 'Jun', 'Sep', 'Dec'][quarter_end_month // 3 - 1]} {now.year}"


def _commentary_reader(tools: ToolRegistry):
    """Yield `(text, source_ref)` for a symbol's most recent commentary."""

    def read(symbol: str) -> list[tuple[str, str]]:
        result = tools.invoke("commentary", {"symbol": symbol, "max_sections": 3}, ToolContext())
        if not result.ok:
            return []
        url = (result.data or {}).get("document_url") or f"commentary://{symbol}"
        return [(item["text"], f"{url}#section={item['section_index']}") for item in result.items]

    return read


def _extractor(tools: ToolRegistry, call):
    def extract(symbol: str, period: str, text: str, source_ref: str) -> list[dict]:
        result = tools.invoke(
            "concept_extract",
            {"symbol": symbol, "period": period, "text": text, "source_ref": source_ref},
            ToolContext(fetchers={"concept_extractor": call}),
        )
        return result.items if result.ok else []

    return extract


def _classifier(tools: ToolRegistry, call):
    def classify(headlines: list[str]) -> list[dict]:
        result = tools.invoke(
            "policy_classify",
            {"headlines": headlines},
            ToolContext(fetchers={"policy_classifier": call}),
        )
        if not result.ok or not (result.data or {}).get("available"):
            # Distinguishable from "no policy found": the caller marks the source unavailable.
            raise RuntimeError((result.data or {}).get("reason") or "classifier unavailable")
        return result.items

    return classify


def _expander(tools: ToolRegistry, call):
    def expand(theme: str) -> list[dict]:
        result = tools.invoke(
            "theme_chain",
            {"theme": theme},
            ToolContext(fetchers={"chain_expander": call}),
        )
        return result.items if result.ok else []

    return expand


def build_matcher(tools: ToolRegistry, gateway: LLMGateway, settings: Settings):
    """The precision half of resolution: which shortlisted companies supply a tier."""
    call = _caller(gateway, settings.model_for_task("research"))

    def match(tier: str, reasoning: str, candidates: list[dict]) -> dict[str, str] | None:
        if not candidates:
            return {}
        result = tools.invoke(
            "tier_match",
            {"tier": tier, "reasoning": reasoning, "candidates": candidates},
            ToolContext(fetchers={"tier_matcher": call}),
        )
        if not result.ok or not (result.data or {}).get("available"):
            # None, not empty: resolution falls back to the shortlist and says a matcher never
            # read it, rather than reporting an empty tier as a considered answer.
            return None
        return {item["symbol"]: item["why"] for item in result.items}

    return match
