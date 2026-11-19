"""Idea & Macro Scout Agent: dynamic top-down funnel planner.

Replaces hardcoded ``symbols[:20]`` iteration in theme & research runs with live triage
across four signals:

1. **Portfolio & Watchlist:** Open paper positions and tracked watchlist names come first.
2. **Sector Rotation (RRG):** Sectors currently ``Improving`` or ``Leading`` vs Nifty 500.
3. **Persisted Scan Setups:** Stocks with deterministic Trade Plans in those strong sectors.
4. **Proactive Macro & Corporate Catalyst Sweep:** Tavily internet search + RSS + NSE filings
   (all degrading cleanly when unconfigured or offline).

The Scout **never modifies strategy verdicts** — it decides where limited concall-reading
and local LLM research attention goes today.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import desc, select

from app.domain.themes import Reference, SourceKind
from app.persistence.models import ScanEntry, ScanRun, WatchlistItem
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext

log = logging.getLogger(__name__)

DEFAULT_DISCOVERY_QUERIES = (
    "India NSE sector tailwind capex order book PLI 2025 2026",
    "Indian equities fastest growing sectors power defence railways EMS chemicals",
)


@dataclass(frozen=True, slots=True)
class ScoutPlan:
    """What the Scout prioritized for concall, filing, and theme research."""

    prioritized_symbols: tuple[str, ...]
    priority_sectors: tuple[str, ...] = ()
    web_references: tuple[Reference, ...] = ()
    rationale: tuple[str, ...] = ()
    sources_checked: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "prioritized_symbols": list(self.prioritized_symbols),
            "priority_sectors": list(self.priority_sectors),
            "web_references_count": len(self.web_references),
            "rationale": list(self.rationale),
            "sources_checked": list(self.sources_checked),
            "metadata": self.metadata,
        }


class IdeaScout:
    """Builds a prioritized target list and proactive catalyst references."""

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        session_factory=None,
        universe_source=None,
        price_source=None,
        search_source=None,
        period: str | None = None,
    ) -> None:
        self._tools = tools
        self._session_factory = session_factory
        self._universe_source = universe_source
        self._price_source = price_source
        self._search_source = search_source
        self._period = period

    def plan(
        self,
        *,
        limit: int = 30,
        include_web_discovery: bool = True,
    ) -> ScoutPlan:
        """Assemble prioritized symbols + proactive catalyst hints."""
        ordered: list[str] = []
        seen: set[str] = set()
        rationale: list[str] = []
        sources_checked: list[str] = []
        priority_sectors: list[str] = []

        def add_symbol(sym: str) -> None:
            s = sym.strip().upper()
            if s and s not in seen:
                seen.add(s)
                ordered.append(s)

        ctx = ToolContext(
            price_source=self._price_source,
            session_factory=self._session_factory,
            universe_source=self._universe_source,
        )

        # 1. Holdings & Watchlist via declared tool
        if self._session_factory is not None:
            pw = self._tools.invoke(
                "portfolio_and_watchlist",
                {"book": "all", "include_watchlist": True},
                ctx,
            )
            sources_checked.append("portfolio_and_watchlist")
            if pw.ok:
                for item in pw.items:
                    add_symbol(item["symbol"])
                if pw.items:
                    rationale.append(
                        f"Prioritized {len(pw.items)} open holding/watchlist names"
                    )

        # 2. Sector Rotation (Leading & Improving sectors)
        sec_res = self._tools.invoke("sector_rotation", {}, ctx)
        sources_checked.append("sector_rotation")
        if sec_res.ok and sec_res.items:
            for item in sec_res.items:
                if item.get("quadrant") in ("Improving", "Leading"):
                    priority_sectors.append(item["sector_key"])
            if priority_sectors:
                rationale.append(
                    f"Strong/improving sectors: {', '.join(priority_sectors[:5])}"
                )

        # 3. Persisted Scan Setups inside Leading / Improving sectors (then remaining plans)
        if self._session_factory is not None:
            added_from_scan = 0
            for sec_key in priority_sectors[:4]:
                res = self._tools.invoke(
                    "setup_screener",
                    {"sector_key": sec_key, "has_plan_only": True, "limit": 8},
                    ctx,
                )
                if res.ok:
                    for item in res.items:
                        if item["symbol"] not in seen:
                            add_symbol(item["symbol"])
                            added_from_scan += 1
            if added_from_scan:
                rationale.append(
                    f"Added {added_from_scan} setups from Leading/Improving sectors"
                )
            sources_checked.append("setup_screener")

        # 4. Watchlist direct fallback if tool returned partial & scan exists
        universe_symbols: list[str] = []
        sector_by_symbol: dict[str, str] = {}
        if self._universe_source is not None:
            try:
                snap = self._universe_source.snapshot()
                for inst in snap.instruments:
                    universe_symbols.append(inst.symbol)
                    if inst.sector:
                        sector_by_symbol[inst.symbol] = inst.sector
            except Exception as exc:
                log.debug("scout failed loading universe snapshot: %s", exc)

        # Add sector-matched names if scan hasn't run yet
        if len(ordered) < limit and priority_sectors and universe_symbols:
            from app.data.sectors import for_instrument
            from app.domain.instrument import Instrument

            target_set = set(priority_sectors[:4])
            for sym in universe_symbols:
                mapped = for_instrument(Instrument(sym, sector=sector_by_symbol.get(sym)))
                if mapped is not None and mapped.key in target_set:
                    add_symbol(sym)
                    if len(ordered) >= limit:
                        break

        # Top up cleanly to limit in universe order
        for sym in universe_symbols:
            if len(ordered) >= limit:
                break
            add_symbol(sym)

        # 5. Proactive web search sweep for macro/theme catalysts
        web_refs: list[Reference] = []
        if include_web_discovery and self._search_source is not None:
            sources_checked.append("tavily_web_search")
            queries = list(DEFAULT_DISCOVERY_QUERIES)
            if priority_sectors:
                top_secs = " ".join(priority_sectors[:3])
                queries.insert(0, f"NSE India {top_secs} sector order book capex catalyst")
            period = self._period or "current"
            for q in queries[:2]:
                try:
                    excerpts = self._search_source.search(q, max_results=4)
                    for ex in excerpts:
                        title = (ex.get("title") or "").strip()
                        url = (ex.get("url") or "").strip()
                        snippet = (ex.get("excerpt") or ex.get("content") or "").strip()
                        if title:
                            web_refs.append(
                                Reference(
                                    symbol="",
                                    concept=title[:120].lower(),
                                    period=period,
                                    kind=SourceKind.POLICY,
                                    source_ref=url or f"tavily://{q[:40]}",
                                    excerpt=f"{title} — {snippet}"[:400],
                                )
                            )
                except Exception as exc:
                    log.debug("scout web search failed for %r: %s", q, exc)
            if web_refs:
                rationale.append(
                    f"Collected {len(web_refs)} macro/sector excerpts from web search"
                )

        # Also surface raw watchlist count metadata for observability
        wl_count = 0
        latest_scan_id: int | None = None
        if self._session_factory is not None:
            with self._session_factory() as session:
                wl_count = len(session.execute(select(WatchlistItem.id)).scalars().all())
                latest_scan_id = session.execute(
                    select(ScanRun.id)
                    .where(ScanRun.outcome == "complete")
                    .order_by(desc(ScanRun.id))
                    .limit(1)
                ).scalar_one_or_none()

        return ScoutPlan(
            prioritized_symbols=tuple(ordered[:limit]),
            priority_sectors=tuple(priority_sectors),
            web_references=tuple(web_refs),
            rationale=tuple(rationale),
            sources_checked=tuple(sources_checked),
            metadata={
                "watchlist_count": wl_count,
                "latest_scan_id": latest_scan_id,
                "candidate_pool": len(ordered),
                "scan_entries_checked": (
                    self._count_scan_entries(latest_scan_id) if latest_scan_id else 0
                ),
            },
        )

    def _count_scan_entries(self, run_id: int | None) -> int:
        if self._session_factory is None or run_id is None:
            return 0
        with self._session_factory() as session:
            return len(
                session.execute(
                    select(ScanEntry.id).where(ScanEntry.run_id == run_id)
                )
                .scalars()
                .all()
            )
