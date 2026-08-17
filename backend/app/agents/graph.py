"""Wiring the cycle.

```
regime ─→ research ──┬─→ strategy.minervini ────┐
                     ├─→ strategy.bvm ──────────┤
                     ├─→ strategy.fun_tech ─────┼─→ narrate ─→ END
                     └─→ strategy.young_mom ────┘
```

`screen`, `risk` and `insights` from the cycle in `project.md` are absent deliberately: each
needs an increment that has not happened (`screening-universe-and-gates`,
`books-ledger-and-analytics`, `insights-feed`), and a placeholder node would be inventing
behaviour to be thrown away.

The strategy nodes are added by iterating the registry, so a new strategy joins the fan-out by
existing. There is no list here to forget to update — the same reasoning as discovery-by-
convention in the tool and strategy registries.

LangGraph is imported lazily. The API, the strategies and their tests all run without the
`agents` extra installed.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents import nodes
from app.agents.state import CycleState
from app.agents.toolbelt import Toolbelt
from app.data.protocols import PriceSource
from app.llm.types import LLMGateway
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry

log = logging.getLogger(__name__)

SCREEN = "screen"
REGIME = "regime"
RESEARCH = "research"
RISK = "risk"
NARRATE = "narrate"
INSIGHTS = "insights"
STRATEGY_PREFIX = "strategy."


def build_graph(
    *,
    registry: StrategyRegistry,
    strategy_context: StrategyContext,
    price_source: PriceSource,
    toolbelt: Toolbelt,
    gateway: LLMGateway,
    max_tool_rounds: int = nodes.DEFAULT_MAX_TOOL_ROUNDS,
    screener=None,
    universe_source=None,
    screen_criteria=None,
    ledger=None,
    risk_limits=None,
    book=None,
    feed=None,
):
    """Compile the cycle graph. Raises only if LangGraph is missing."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(CycleState)

    screening = screener is not None and universe_source is not None
    if screening:
        graph.add_node(SCREEN, nodes.make_screen_node(screener, universe_source, screen_criteria))
    graph.add_node(REGIME, nodes.make_regime_node(price_source))
    graph.add_node(RESEARCH, nodes.make_research_node(toolbelt, gateway, max_tool_rounds))
    risking = ledger is not None and risk_limits is not None and book is not None
    if risking:
        graph.add_node(RISK, nodes.make_risk_node(ledger, risk_limits, book, price_source))
    graph.add_node(NARRATE, nodes.make_narrate_node(gateway))
    surfacing = feed is not None and ledger is not None and book is not None
    if surfacing:
        graph.add_node(INSIGHTS, nodes.make_insights_node(feed, ledger, book, risk_limits))

    if screening:
        # Screening first: narrowing the universe before the regime read means the cheap
        # question is asked before any per-name work at all.
        graph.add_edge(START, SCREEN)
        graph.add_edge(SCREEN, REGIME)
    else:
        graph.add_edge(START, REGIME)
    graph.add_edge(REGIME, RESEARCH)

    strategy_ids = registry.ids()
    for strategy_id in strategy_ids:
        node_name = f"{STRATEGY_PREFIX}{strategy_id}"
        graph.add_node(
            node_name,
            nodes.make_strategy_node(strategy_id, registry, strategy_context),
        )
        # Fan out from research and back in to narrate. Every strategy node sees the same
        # inputs and none of them is downstream of another — that is the isolation, expressed
        # as topology rather than as a convention someone has to keep.
        graph.add_edge(RESEARCH, node_name)
        # Fan in to risk when it is present: risk needs every verdict, so it cannot run inside
        # the fan-out without seeing what a sibling produced.
        graph.add_edge(node_name, RISK if risking else NARRATE)

    if not strategy_ids:  # pragma: no cover - the registry always discovers four
        graph.add_edge(RESEARCH, NARRATE)

    if risking:
        graph.add_edge(RISK, NARRATE)
    if surfacing:
        # Last: it reads verdicts, narratives, risk decisions, research and the regime.
        graph.add_edge(NARRATE, INSIGHTS)
        graph.add_edge(INSIGHTS, END)
    else:
        graph.add_edge(NARRATE, END)
    return graph.compile()


async def run_cycle(
    compiled,
    state: CycleState,
) -> dict[str, Any]:
    """Execute one cycle and assemble its result.

    Narrated verdicts replace the raw ones when narration ran; otherwise the fan-in's output is
    the answer. Both come from the same run — nothing is re-evaluated to attach prose.
    """
    final: CycleState = await compiled.ainvoke(state)
    verdicts = final.get("narrated") or final.get("verdicts") or []
    summary = nodes.summarise(final)
    summary["verdicts"] = verdicts
    summary["screen"] = final.get("screen")
    summary["risk"] = final.get("risk")
    summary["insights"] = final.get("insights")
    return summary
