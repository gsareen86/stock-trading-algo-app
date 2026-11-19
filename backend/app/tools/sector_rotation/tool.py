"""Query the NSE sector Relative Rotation Graph (RRG) quadrant snapshot.

Returns RS-Ratio and RS-Momentum against Nifty 500 (^CRSLDX) or Nifty 50 (^NSEI),
plus each sector's quadrant (`Leading`, `Improving`, `Weakening`, `Lagging`, or `unplaced`).
Never attaches any stance or recommendation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from app.core.clock import now_utc
from app.discovery.sectors import BENCHMARK_NIFTY500, compute_sector_rrg
from app.persistence.models import ScanRun
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "benchmark": {
            "type": "string",
            "enum": ["^CRSLDX", "^NSEI"],
            "default": BENCHMARK_NIFTY500,
            "description": "Benchmark index ticker (^CRSLDX Nifty 500 or ^NSEI Nifty 50)",
        },
        "quadrant": {
            "type": "string",
            "enum": ["Leading", "Improving", "Weakening", "Lagging", "unplaced"],
            "description": "Optional filter to return sectors in one quadrant only",
        },
    },
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "sector_key": {"type": "string"},
        "nse_name": {"type": "string"},
        "ticker": {"type": "string"},
        "quadrant": {"type": "string"},
        "rs_pct": {"type": ["number", "null"]},
        "rs_momentum_pp": {"type": ["number", "null"]},
        "rs_ratio": {"type": ["number", "null"]},
        "rs_momentum": {"type": ["number", "null"]},
        "reason": {"type": ["string", "null"]},
    },
    required=["sector_key", "nse_name", "ticker", "quadrant"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "benchmark": {"type": "string"},
        "source_mode": {"type": "string"},
    },
)


def _from_snapshot(context: ToolContext, benchmark: str) -> list[dict[str, Any]] | None:
    if context.session_factory is None:
        return None
    with context.session_factory() as session:
        run = session.execute(
            select(ScanRun)
            .where(ScanRun.outcome == "complete")
            .order_by(desc(ScanRun.id))
            .limit(1)
        ).scalar_one_or_none()
        if run is None or not run.sectors_snapshot:
            return None
        if (run.benchmark or BENCHMARK_NIFTY500) != benchmark:
            return None
        return list(run.sectors_snapshot)


def handle(arguments: dict, context: ToolContext) -> dict:
    benchmark = (arguments.get("benchmark") or BENCHMARK_NIFTY500).strip().upper()
    quadrant_filter = arguments.get("quadrant")
    observed_at = (context.now() if context.now else now_utc()).isoformat()

    fetcher = context.fetchers.get("sector_rotation")
    source_mode = "live"
    raw_sectors: list[dict[str, Any]] = []

    if fetcher is not None:
        source_mode = "injected"
        raw_sectors = list(fetcher(benchmark) or [])
    elif context.price_source is not None:
        placements = compute_sector_rrg(context.price_source, benchmark=benchmark)
        raw_sectors = [p.as_dict() for p in placements]
    else:
        snap = _from_snapshot(context, benchmark)
        if snap is not None:
            source_mode = "latest_scan"
            raw_sectors = snap
        else:
            source_mode = "unavailable"

    items = []
    for sec in raw_sectors:
        q = sec.get("quadrant", "unplaced")
        if quadrant_filter and q != quadrant_filter:
            continue
        key = sec["key"]
        items.append(
            {
                "source_ref": f"rrg://{key}?benchmark={benchmark}",
                "observed_at": observed_at,
                "sector_key": key,
                "nse_name": sec.get("nse_name", key),
                "ticker": sec.get("ticker", ""),
                "quadrant": q,
                "rs_pct": sec.get("rs_pct"),
                "rs_momentum_pp": sec.get("rs_momentum_pp"),
                "rs_ratio": sec.get("rs_ratio"),
                "rs_momentum": sec.get("rs_momentum"),
                "reason": sec.get("reason"),
            }
        )

    return {
        "benchmark": benchmark,
        "source_mode": source_mode,
        "items": items,
    }


TOOL = ToolManifest(
    name="sector_rotation",
    version="1.0.0",
    summary=(
        "Reads Relative Rotation Graph (RRG) quadrants and relative strength across the 14 "
        "NSE sector indices. Use when deciding which sectors are Leading or Improving vs Nifty 500."
    ),
    description=(
        "Measures 3- and 6-month blended relative strength and 4-week relative momentum for all "
        "14 verified NSE sector indices. Useful for top-down idea discovery and sector triage."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("discovery", "sectors", "rrg"),
)
