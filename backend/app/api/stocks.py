"""Single-stock workstation data & Universe autocomplete endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.api.deps import get_session_factory, get_settings
from app.api.discovery import _financials_source
from app.api.screening import _universe_source
from app.api.verdicts import _price_source
from app.core.settings import Settings
from app.data.sectors import for_instrument
from app.discovery.quality import evaluate_quality
from app.domain.instrument import Instrument
from app.persistence.models import DocumentConcept, Theme, ThemeCandidate
from app.strategies.indicators import sma_series
from app.tools.types import ToolContext

log = logging.getLogger(__name__)

router = APIRouter(tags=["stocks"])

RANGE_BARS = {
    "3M": 66,
    "6M": 132,
    "1Y": 252,
    "3Y": 756,
}


@router.get("/universe/symbols")
async def universe_symbols(
    request: Request,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 750,
) -> dict[str, Any]:
    """Return Nifty Total Market symbols for instant ⌘K & stock lookup."""
    snap = _universe_source(request).snapshot()
    needle = (q or "").strip().upper()
    items = []
    for inst in snap.instruments:
        sec_idx = for_instrument(inst)
        if needle and needle not in inst.symbol.upper() and needle not in (inst.name or "").upper():
            continue
        items.append(
            {
                "symbol": inst.symbol,
                "name": inst.name or inst.symbol,
                "sector": inst.sector,
                "sector_key": sec_idx.key if sec_idx else None,
            }
        )
        if len(items) >= limit:
            break
    return {
        "symbols": items,
        "count": len(items),
        "total_universe": len(snap.instruments),
        "index_name": snap.index_name,
        "origin": snap.origin,
    }


@router.get("/stocks/{symbol}/chart")
async def stock_chart(
    symbol: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    range: Annotated[str, Query(pattern=r"^(3M|6M|1Y|3Y)$")] = "1Y",
) -> dict[str, Any]:
    """OHLCV candles plus 20 EMA and 50/150/200 DMAs."""
    sym = symbol.strip().upper()
    range_key = range.upper()
    display_bars = RANGE_BARS.get(range_key, 252)
    lookback_days = max(500, int(display_bars * 1.6) + 260)

    series = _price_source(request, settings).history(
        Instrument(sym), interval="1d", lookback_days=lookback_days
    )
    if series.is_empty:
        return {
            "symbol": sym,
            "range": range_key,
            "available": False,
            "reason": "price history unavailable",
            "last_price": None,
            "prev_close": None,
            "change_pct": None,
            "bars": [],
        }

    frame = series.frame.copy()
    closes = frame["close"]
    frame["ema20"] = closes.ewm(span=20, adjust=False, min_periods=20).mean()
    frame["sma50"] = sma_series(frame, 50)
    frame["sma150"] = sma_series(frame, 150)
    frame["sma200"] = sma_series(frame, 200)

    view = frame.tail(display_bars)
    last_px = round(float(frame["close"].iloc[-1]), 2)
    prev_px = round(float(frame["close"].iloc[-2]), 2) if len(frame) >= 2 else None
    change_pct = round((last_px / prev_px - 1.0) * 100.0, 2) if prev_px and prev_px > 0 else None

    def _opt(val: Any) -> float | None:
        if val is None or val != val:  # NaN check
            return None
        return round(float(val), 2)

    bars = []
    for idx, row in view.iterrows():
        dt_str = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        bars.append(
            {
                "time": dt_str,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": int(float(row["volume"])) if row["volume"] == row["volume"] else 0,
                "ema20": _opt(row["ema20"]),
                "sma50": _opt(row["sma50"]),
                "sma150": _opt(row["sma150"]),
                "sma200": _opt(row["sma200"]),
            }
        )

    return {
        "symbol": sym,
        "range": range_key,
        "available": True,
        "last_price": last_px,
        "prev_close": prev_px,
        "change_pct": change_pct,
        "bars": bars,
    }


@router.get("/stocks/{symbol}/quality")
async def stock_quality(
    symbol: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Business quality facets, quarterly trends, and shareholding."""
    sym = symbol.strip().upper()
    snap = _universe_source(request).snapshot()
    inst = next((i for i in snap.instruments if i.symbol == sym), None) or Instrument(sym)
    sec_idx = for_instrument(inst)
    sec_key = sec_idx.key if sec_idx else None

    fin = _financials_source(request, settings).financials(inst)
    report = evaluate_quality(fin, symbol=sym, sector_key=sec_key)

    shareholding = (
        {
            "as_of": fin.shareholding[0].as_of.isoformat(),
            "promoter_pct": fin.shareholding[0].promoter_pct,
            "fii_pct": fin.shareholding[0].fii_pct,
            "dii_pct": fin.shareholding[0].dii_pct,
            "pledge_pct": fin.shareholding[0].pledge_pct,
            "source": fin.shareholding[0].source,
        }
        if fin.shareholding
        else None
    )
    statements = {
        key: [
            {"period": pt.period, "value": pt.value}
            for pt in series.points[:6]
        ]
        for key, series in fin.statements.items()
    }

    return {
        **report.as_dict(),
        "company_name": fin.company_name or inst.name or sym,
        "sector": inst.sector,
        "industry": fin.industry or inst.sector,
        "description": fin.description,
        "shareholding": shareholding,
        "statements": statements,
    }


@router.get("/stocks/{symbol}/research")
async def stock_research(
    symbol: str,
    request: Request,
    session_factory: Annotated[Any, Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
    summarize: bool = False,
) -> dict[str, Any]:
    """Single-stock qualitative research digest: concall concepts, themes, filings & news."""
    sym = symbol.strip().upper()
    with session_factory() as session:
        concept_rows = (
            session.execute(
                select(DocumentConcept).where(DocumentConcept.symbol == sym).limit(30)
            )
            .scalars()
            .all()
        )
        theme_links = session.execute(
            select(ThemeCandidate, Theme)
            .join(Theme, Theme.key == ThemeCandidate.theme_key)
            .where(ThemeCandidate.symbol == sym, Theme.withdrawn_at.is_(None))
        ).all()

    themes = [
        {
            "theme_key": th.key,
            "label": th.label,
            "tier": cand.tier,
            "matched_description": cand.matched_description,
            "exposure": cand.exposure,
            "exposure_basis": cand.exposure_basis,
            "breadth": th.breadth,
        }
        for cand, th in theme_links
    ]
    concepts = [
        {
            "concept": c.label,
            "period": c.period,
            "kind": c.kind,
            "source_ref": c.source_ref,
            "excerpt": c.excerpt,
            "extracted_by": c.extracted_by,
        }
        for c in concept_rows
    ]

    filings: list[dict[str, Any]] = []
    filings_available = False
    news: list[dict[str, Any]] = []
    news_available = False
    concall_sections: list[dict[str, Any]] = []

    tools = getattr(request.app.state, "tools", None)
    if tools is not None:
        f_res = tools.invoke("filings_scan", {"symbol": sym, "days": 45, "limit": 8}, ToolContext())
        if f_res.ok:
            filings = list(f_res.items)
            filings_available = bool((f_res.data or {}).get("source_available", True))

        n_res = tools.invoke(
            "news_research", {"symbol": sym, "hours": 168, "limit": 8}, ToolContext()
        )
        if n_res.ok:
            news = list(n_res.items)
            news_available = len((n_res.data or {}).get("feeds_failed", [])) < 7

        if summarize:
            c_res = tools.invoke("commentary", {"symbol": sym, "max_sections": 2}, ToolContext())
            gateway = getattr(request.app.state, "gateway", None)
            if c_res.ok and c_res.items and gateway is not None:
                from app.themes.assembly import _caller, _current_period

                call = _caller(gateway, settings.model_for_task("research"))
                url = (c_res.data or {}).get("document_url") or f"commentary://{sym}"
                joined = "\n\n".join(i.get("text", "") for i in c_res.items)[:8000]
                t_res = tools.invoke(
                    "transcript_summary",
                    {
                        "symbol": sym,
                        "period": _current_period(),
                        "text": joined,
                        "source_ref": url,
                    },
                    ToolContext(fetchers={"transcript_summariser": call}),
                )
                if t_res.ok:
                    concall_sections = list(t_res.items)

    return {
        "symbol": sym,
        "themes": themes,
        "concepts": concepts,
        "filings": {"available": filings_available, "items": filings},
        "news": {"available": news_available, "items": news},
        "concall_digest": concall_sections,
    }
