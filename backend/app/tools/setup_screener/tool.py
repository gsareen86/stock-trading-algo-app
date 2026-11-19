"""Query persisted Nifty 750 discovery scan setups, quality facets, and Trade Plans.

Read-only view over the latest completed `scan_runs` / `scan_entries` rows. Does not execute
strategies, rank stocks subjectively, or produce advisory recommendations.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from app.core.clock import now_utc
from app.persistence.models import ScanEntry, ScanRun
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sector_key": {"type": "string", "description": "Filter by NSE sector key, e.g. IT"},
        "strategy_id": {
            "type": "string",
            "description": "Optional strategy id filter (e.g. minervini, young_momentum)",
        },
        "has_plan_only": {
            "type": "boolean",
            "default": True,
            "description": "When true, only return stocks with a deterministic entry/stop plan",
        },
        "roe_min": {"type": "number", "description": "Minimum trailing ROE %"},
        "sales_yoy_min": {"type": "number", "description": "Minimum YoY sales growth %"},
        "low_debt": {"type": "boolean", "default": False},
        "theme_backed_only": {"type": "boolean", "default": False},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15},
    },
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "company_name": {"type": "string"},
        "sector_key": {"type": ["string", "null"]},
        "primary_strategy": {"type": ["string", "null"]},
        "active_strategies": {"type": "array", "items": {"type": "string"}},
        "plan": {"type": ["object", "null"]},
        "quality_summary": {"type": "object"},
        "themes": {"type": "array", "items": {"type": "string"}},
    },
    required=["symbol", "active_strategies"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "scan_run_id": {"type": ["integer", "null"]},
        "scan_at": {"type": ["string", "null"]},
        "available": {"type": "boolean"},
    },
)


def handle(arguments: dict, context: ToolContext) -> dict:
    observed_at = (context.now() if context.now else now_utc()).isoformat()
    if context.session_factory is None:
        return {"scan_run_id": None, "scan_at": None, "available": False, "items": []}

    sector_filter = (arguments.get("sector_key") or "").strip() or None
    strategy_filter = (arguments.get("strategy_id") or "").strip() or None
    has_plan_only = bool(arguments.get("has_plan_only", True))
    roe_min = arguments.get("roe_min")
    sales_min = arguments.get("sales_yoy_min")
    low_debt = bool(arguments.get("low_debt", False))
    theme_only = bool(arguments.get("theme_backed_only", False))
    limit = int(arguments.get("limit", 15))

    with context.session_factory() as session:
        run = session.execute(
            select(ScanRun)
            .where(ScanRun.outcome == "complete")
            .order_by(desc(ScanRun.id))
            .limit(1)
        ).scalar_one_or_none()
        if run is None:
            return {"scan_run_id": None, "scan_at": None, "available": False, "items": []}

        stmt = select(ScanEntry).where(ScanEntry.run_id == run.id)
        if sector_filter:
            stmt = stmt.where(ScanEntry.sector_key == sector_filter)
        rows = session.execute(stmt.order_by(ScanEntry.id)).scalars().all()

    items: list[dict[str, Any]] = []
    for row in rows:
        verdicts = list(row.verdicts or [])
        plan_strategies = [v.get("strategy_id") for v in verdicts if v.get("plan") is not None]
        if strategy_filter and strategy_filter not in plan_strategies:
            continue
        if has_plan_only and not plan_strategies:
            continue

        quality = dict((row.quality or {}).get("summary") or {})
        if roe_min is not None:
            val = quality.get("roe")
            if val is None or val < roe_min:
                continue
        if sales_min is not None:
            val = quality.get("sales_yoy")
            if val is None or val < sales_min:
                continue
        if low_debt:
            de = quality.get("debt_to_equity")
            facets = (row.quality or {}).get("facets") or []
            de_status = next(
                (f.get("status") for f in facets if f.get("key") == "debt_to_equity"), None
            )
            if de_status != "not_applicable" and (de is None or de > 1.0):
                continue

        themes_raw = list(row.themes or [])
        themes = [
            t.get("key", "") if isinstance(t, dict) else str(t) for t in themes_raw if t
        ]
        if theme_only and not themes:
            continue

        chosen = None
        if strategy_filter:
            chosen = next(
                (v.get("plan") for v in verdicts if v.get("strategy_id") == strategy_filter),
                None,
            )
        if chosen is None:
            chosen = next((v.get("plan") for v in verdicts if v.get("plan") is not None), None)

        items.append(
            {
                "source_ref": f"scan://{run.id}/{row.symbol}",
                "observed_at": observed_at,
                "symbol": row.symbol,
                "company_name": row.name or row.symbol,
                "sector_key": row.sector_key,
                "primary_strategy": strategy_filter or row.ranked_by,
                "active_strategies": [str(s) for s in plan_strategies if s],
                "plan": chosen,
                "quality_summary": quality,
                "themes": themes,
            }
        )
        if len(items) >= limit:
            break

    return {
        "scan_run_id": run.id,
        "scan_at": run.finished_at.isoformat() if run.finished_at else run.started_at.isoformat(),
        "available": True,
        "items": items,
    }


TOOL = ToolManifest(
    name="setup_screener",
    version="1.0.0",
    summary=(
        "Reads persisted Nifty 750 scan setups, deterministic Trade Plans, and quality facets "
        "from the latest completed scan. Use when finding stocks with technical bases matching "
        "sector, strategy, quality, or theme criteria."
    ),
    description=(
        "Queries the latest completed discovery scan in the database by sector, strategy, "
        "ROE/sales/debt quality filters, and theme linkage without modifying stances."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("discovery", "plans", "screener"),
)
