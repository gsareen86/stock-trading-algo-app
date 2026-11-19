"""Inspect company fundamentals and sector-aware quality facets for an NSE equity."""

from __future__ import annotations

from app.core.clock import now_utc
from app.data.sectors import for_instrument
from app.data.yfinance_quality import YFinanceQualitySource
from app.discovery.quality import evaluate_quality
from app.domain.instrument import Instrument
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "NSE symbol, e.g. TCS"},
        "sector_key": {
            "type": "string",
            "description": "Optional NSE sector key (e.g. PrivateBank) for leverage applicability",
        },
    },
    "required": ["symbol"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "facet": {"type": "string"},
        "label": {"type": "string"},
        "status": {"type": "string"},
        "value": {"type": ["number", "null"]},
        "threshold": {"type": ["string", "null"]},
        "unit": {"type": "string"},
        "reason": {"type": ["string", "null"]},
    },
    required=["facet", "label", "status"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "symbol": {"type": "string"},
        "sector_key": {"type": ["string", "null"]},
        "source": {"type": "string"},
        "unavailable_reason": {"type": ["string", "null"]},
        "summary": {"type": "object"},
        "company_name": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
    },
)


def _resolve_sector_key(symbol: str, explicit: str | None, context: ToolContext) -> str | None:
    if explicit:
        return explicit.strip()
    if context.universe_source is not None:
        try:
            snap = context.universe_source.snapshot()
            inst = next((i for i in snap.instruments if i.symbol == symbol), None)
            if inst is not None:
                mapped = for_instrument(inst)
                if mapped is not None:
                    return mapped.key
        except Exception:
            pass
    return None


def handle(arguments: dict, context: ToolContext) -> dict:
    symbol = arguments["symbol"].strip().upper()
    observed_at = (context.now() if context.now else now_utc()).isoformat()
    sector_key = _resolve_sector_key(symbol, arguments.get("sector_key"), context)

    fetcher = context.fetchers.get("company_quality")
    if fetcher is not None:
        source = YFinanceQualitySource(fetcher=fetcher)
    elif context.company_financials_source is not None:
        source = context.company_financials_source
    else:
        source = YFinanceQualitySource()

    inst = Instrument(symbol=symbol)
    fin = source.financials(inst)
    report = evaluate_quality(fin, symbol=symbol, sector_key=sector_key)

    items = [
        {
            "source_ref": f"financials://{symbol}/{f.key}",
            "observed_at": observed_at,
            "facet": f.key,
            "label": f.label,
            "status": f.status,
            "value": f.value,
            "threshold": f.threshold,
            "unit": f.unit,
            "reason": f.reason,
        }
        for f in report.facets
    ]

    desc = fin.description[:500] if fin.description else None
    return {
        "symbol": symbol,
        "sector_key": sector_key,
        "source": report.source,
        "unavailable_reason": report.unavailable_reason,
        "summary": report.summary,
        "company_name": fin.company_name,
        "description": desc,
        "items": items,
    }


TOOL = ToolManifest(
    name="company_quality",
    version="1.0.0",
    summary=(
        "Reads company fundamentals and quality facets (ROE, operating margin, Debt/Equity, "
        "YoY sales/EPS growth, market cap, P/E) for an NSE stock. Use when checking business "
        "quality, growth acceleration, or balance-sheet leverage."
    ),
    description=(
        "Retrieves company fundamentals from the active financials source (yfinance/IndianAPI "
        "with disk cache) and evaluates sector-aware quality facets, keeping unavailable metrics "
        "explicit and marking bank leverage not_applicable."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("fundamentals", "quality", "yfinance"),
)
