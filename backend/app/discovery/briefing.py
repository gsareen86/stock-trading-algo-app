"""Daily transition insights & Morning Briefing aggregation.

Joins the latest discovery scan, sector RRG shifts, watchlist items, open paper books,
standing themes, and live index prices to power the Today morning briefing and emit
actionable transitions without fabricating recommendations.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, select

from app.books.ledger import Ledger
from app.core.clock import now_ist, now_utc
from app.data.protocols import PriceSource
from app.discovery.sectors import (
    BENCHMARK_NIFTY50,
    BENCHMARK_NIFTY500,
    SectorPlacement,
    detect_quadrant_shifts,
)
from app.domain.instrument import Instrument
from app.domain.position import Book
from app.insights.feed import InsightFeed
from app.insights.kinds import Kind
from app.insights.rules import Candidate
from app.persistence.models import ScanEntry, ScanRun, WatchlistItem
from app.strategies.indicators import sma
from app.themes.store import ThemeStore

log = logging.getLogger(__name__)

PIVOT_PROXIMITY_PCT = 2.0


def _last_price(symbol: str, price_source: PriceSource | None) -> float | None:
    if price_source is None:
        return None
    try:
        series = price_source.history(Instrument(symbol), interval="1d", lookback_days=10)
        if not series.is_empty:
            return float(series.frame["close"].iloc[-1])
    except Exception:
        return None
    return None


def _evidence_price(entry: ScanEntry) -> float | None:
    for v in entry.verdicts or []:
        for ev in v.get("evidence") or []:
            eid = str(ev.get("id") or "")
            if eid in ("close", "last_close", "current_price") or "close" in eid:
                val = ev.get("observed")
                if isinstance(val, (int, float)) and val > 0:
                    return float(val)
    return None


def _resolve_price(entry: ScanEntry | None, symbol: str, price_source: PriceSource | None):
    px = _last_price(symbol, price_source)
    if px is not None:
        return px
    if entry is not None:
        return _evidence_price(entry)
    return None


def record_scan_transitions(
    session_factory,
    *,
    run_id: int,
    price_source: PriceSource | None = None,
) -> dict[str, int]:
    """Compare the completed scan against watchlist, previous sector state, and holdings."""
    candidates: list[Candidate] = []
    with session_factory() as session:
        run = session.execute(select(ScanRun).where(ScanRun.id == run_id)).scalar_one_or_none()
        if run is None:
            return {"written": 0, "suppressed": 0}
        prev_run = session.execute(
            select(ScanRun)
            .where(ScanRun.outcome == "complete", ScanRun.id < run.id)
            .order_by(desc(ScanRun.id))
            .limit(1)
        ).scalar_one_or_none()
        entries = (
            session.execute(select(ScanEntry).where(ScanEntry.run_id == run.id)).scalars().all()
        )
        entry_by_symbol = {e.symbol: e for e in entries}
        watch_rows = session.execute(select(WatchlistItem)).scalars().all()

        # 1. Watchlist flips & <= 2% pivot proximity
        for w in watch_rows:
            entry = entry_by_symbol.get(w.symbol)
            if entry is None:
                continue
            verdicts = list(entry.verdicts or [])
            prev_stances = dict(w.last_known_stances or {})
            current_stances: dict[str, str] = {}
            last_px = _resolve_price(entry, w.symbol, price_source)

            for v in verdicts:
                sid = v.get("strategy_id")
                stance = v.get("stance")
                if not sid or not stance:
                    continue
                current_stances[sid] = stance
                if (
                    (not w.target_strategy_id or w.target_strategy_id == sid)
                    and prev_stances.get(sid) == "WATCH"
                    and stance == "BUY"
                ):
                    plan = v.get("plan") or {}
                    entry_px = plan.get("entry")
                    plan_str = (
                        f" Plan: Entry ₹{entry_px:,.2f} / Stop ₹{plan.get('stop'):,.2f}."
                        if entry_px and plan.get("stop")
                        else ""
                    )
                    candidates.append(
                        Candidate(
                            kind=Kind.WATCHLIST_FLIP,
                            ticker=w.symbol,
                            title=f"{w.symbol}: {sid} flipped WATCH → BUY",
                            body=(
                                f"Tracked on your {w.book_intent} watchlist. {sid} transitioned "
                                f"from WATCH to BUY in scan #{run.id}.{plan_str}"
                            ),
                            dedupe_key=f"{Kind.WATCHLIST_FLIP}:{w.symbol}:{sid}:{run.id}",
                            payload={
                                "strategy_id": sid,
                                "previous": "WATCH",
                                "current": "BUY",
                                "plan": plan or None,
                                "run_id": run.id,
                            },
                        )
                    )

                plan = v.get("plan")
                if (
                    plan
                    and last_px
                    and last_px > 0
                    and (not w.target_strategy_id or w.target_strategy_id == sid)
                ):
                    pivot = plan.get("entry")
                    if pivot and pivot > 0:
                        dist_pct = (pivot - last_px) / last_px * 100.0
                        if 0.0 <= dist_pct <= PIVOT_PROXIMITY_PCT:
                            candidates.append(
                                Candidate(
                                    kind=Kind.PIVOT_PROXIMITY,
                                    ticker=w.symbol,
                                    title=(
                                        f"{w.symbol} is {dist_pct:.1f}% below {sid} entry pivot"
                                    ),
                                    body=(
                                        f"Last ₹{last_px:,.2f} vs {sid} breakout entry "
                                        f"₹{pivot:,.2f} (stop ₹{plan.get('stop'):,.2f})."
                                    ),
                                    dedupe_key=f"{Kind.PIVOT_PROXIMITY}:{w.symbol}:{sid}",
                                    payload={
                                        "strategy_id": sid,
                                        "last_price": round(last_px, 2),
                                        "entry": pivot,
                                        "distance_pct": round(dist_pct, 2),
                                    },
                                )
                            )

            # 2. New themes surfaced on a watched symbol
            for theme in entry.themes or []:
                theme_key = theme.get("key") if isinstance(theme, dict) else str(theme)
                if not theme_key:
                    continue
                candidates.append(
                    Candidate(
                        kind=Kind.THEME_CATALYST,
                        ticker=w.symbol,
                        title=f"{w.symbol}: linked to emerging theme '{theme_key}'",
                        body=(
                            f"Watched name {w.symbol} appears in theme '{theme_key}' with "
                            f"strategy verdicts attached in scan #{run.id}."
                        ),
                        dedupe_key=f"{Kind.THEME_CATALYST}:{w.symbol}:{theme_key}",
                        payload={"theme_key": theme_key, "run_id": run.id},
                    )
                )

            if current_stances:
                w.last_known_stances = current_stances
                w.updated_at = now_utc()

        session.commit()

        # 3. Sector RRG quadrant shifts vs prior scan
        if prev_run is not None and run.sectors_snapshot and prev_run.sectors_snapshot:
            candidates.extend(
                _shift_candidates(run.sectors_snapshot, prev_run.sectors_snapshot, run.id)
            )

        # 4. Holding stop-level breach check across open positions
        ledger = Ledger(session_factory)
        for book in (Book.SWING, Book.LONGTERM):
            for pos in ledger.positions(book):
                if not pos.is_open:
                    continue
                entry = entry_by_symbol.get(pos.ticker)
                last_px = _resolve_price(entry, pos.ticker, price_source)
                if entry and last_px:
                    for v in entry.verdicts or []:
                        plan = v.get("plan") or {}
                        stop_px = plan.get("stop")
                        if stop_px and last_px < stop_px:
                            candidates.append(
                                Candidate(
                                    kind=Kind.THESIS_BROKEN,
                                    ticker=pos.ticker,
                                    title=(
                                        f"{pos.ticker} closed below {v.get('strategy_id')} "
                                        f"stop ₹{stop_px:,.2f}"
                                    ),
                                    body=(
                                        f"Held {pos.quantity} in {book.value} book at avg "
                                        f"₹{pos.average_cost:,.2f}; last close ₹{last_px:,.2f} "
                                        "is below the strategy stop."
                                    ),
                                    dedupe_key=(
                                        f"{Kind.THESIS_BROKEN}:{pos.ticker}:stop:"
                                        f"{v.get('strategy_id')}"
                                    ),
                                    payload={
                                        "strategy_id": v.get("strategy_id"),
                                        "stop": stop_px,
                                        "last_price": last_px,
                                        "book": book.value,
                                    },
                                )
                            )

    report = InsightFeed(session_factory).record(candidates)
    return {"written": report.written, "suppressed": report.suppressed}


def _shift_candidates(
    current_sectors: list[dict[str, Any]],
    previous_sectors: list[dict[str, Any]],
    run_id: int,
) -> list[Candidate]:
    def _to_placement(raw: dict[str, Any]) -> SectorPlacement:
        return SectorPlacement(
            key=raw.get("key", ""),
            nse_name=raw.get("nse_name", raw.get("key", "")),
            ticker=raw.get("ticker", ""),
            benchmark=raw.get("benchmark", BENCHMARK_NIFTY500),
            quadrant=raw.get("quadrant", "unplaced"),
            rs_pct=raw.get("rs_pct"),
            rs_momentum_pp=raw.get("rs_momentum_pp"),
            rs_ratio=raw.get("rs_ratio"),
            rs_momentum=raw.get("rs_momentum"),
        )

    prev_quadrants = {
        str(s["key"]): str(s["quadrant"])
        for s in previous_sectors
        if s.get("key") and s.get("quadrant")
    }
    shifts = detect_quadrant_shifts(
        [_to_placement(s) for s in current_sectors],
        prev_quadrants,
    )
    out: list[Candidate] = []
    for sh in shifts:
        to_q = sh["to_quadrant"]
        from_q = sh["from_quadrant"]
        if to_q in ("Improving", "Leading") or from_q == "Leading":
            out.append(
                Candidate(
                    kind=Kind.SECTOR_SHIFT,
                    ticker=None,
                    title=f"{sh['nse_name']} shifted {from_q} → {to_q}",
                    body=(
                        f"Sector {sh['nse_name']} rotated from {from_q} "
                        f"into {to_q} in scan #{run_id}."
                    ),
                    dedupe_key=f"{Kind.SECTOR_SHIFT}:{sh['sector_key']}:{to_q}",
                    payload=sh,
                )
            )
    return out


def _index_snapshot(price_source: PriceSource | None, symbol: str, label: str) -> dict[str, Any]:
    if price_source is None:
        return {"symbol": symbol, "label": label, "available": False}
    try:
        series = price_source.history(Instrument(symbol), interval="1d", lookback_days=280)
        if series.is_empty or len(series.frame) < 2:
            return {"symbol": symbol, "label": label, "available": False}
        frame = series.frame
        close = float(frame["close"].iloc[-1])
        prev = float(frame["close"].iloc[-2])
        change_pct = round((close / prev - 1.0) * 100.0, 2) if prev > 0 else 0.0
        sma50_val = sma(frame, 50)
        sma200_val = sma(frame, 200) if len(frame) >= 200 else None
        above_50 = bool(sma50_val is not None and close > float(sma50_val))
        above_200 = (
            bool(sma200_val is not None and close > float(sma200_val))
            if sma200_val is not None
            else None
        )
        posture = (
            "constructive"
            if (above_50 and (above_200 is not False))
            else ("cautious" if (above_50 or above_200) else "risk_off")
        )
        return {
            "symbol": symbol,
            "label": label,
            "available": True,
            "close": round(close, 2),
            "change_pct": change_pct,
            "above_50dma": above_50,
            "above_200dma": above_200,
            "posture": posture,
        }
    except Exception as exc:
        log.debug("index snapshot failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "label": label, "available": False}


def _market_session_label() -> dict[str, str]:
    now = now_ist()
    wd = now.weekday()
    hhmm = now.hour * 100 + now.minute
    if wd >= 5:
        session = "Weekend Closed"
    elif hhmm < 900:
        session = "Pre-Market"
    elif 900 <= hhmm < 915:
        session = "Pre-Open"
    elif 915 <= hhmm <= 1530:
        session = "NSE Live"
    else:
        session = "Post-Close"
    return {
        "session": session,
        "ist_timestamp": now.isoformat(),
        "ist_time_label": now.strftime("%d %b %Y · %H:%M IST"),
    }


def build_morning_briefing(
    session_factory,
    price_source: PriceSource | None = None,
) -> dict[str, Any]:
    """Assemble the complete Morning Briefing card state for Today (`/`)."""
    session_info = _market_session_label()
    nifty50 = _index_snapshot(price_source, BENCHMARK_NIFTY50, "Nifty 50")
    nifty500 = _index_snapshot(price_source, BENCHMARK_NIFTY500, "Nifty 500")

    with session_factory() as session:
        latest_run = session.execute(
            select(ScanRun)
            .where(ScanRun.outcome == "complete")
            .order_by(desc(ScanRun.id))
            .limit(1)
        ).scalar_one_or_none()
        prev_run = (
            session.execute(
                select(ScanRun)
                .where(ScanRun.outcome == "complete", ScanRun.id < latest_run.id)
                .order_by(desc(ScanRun.id))
                .limit(1)
            ).scalar_one_or_none()
            if latest_run is not None
            else None
        )
        entries = (
            session.execute(select(ScanEntry).where(ScanEntry.run_id == latest_run.id))
            .scalars()
            .all()
            if latest_run is not None
            else []
        )
        watch_rows = session.execute(select(WatchlistItem)).scalars().all()

    now = now_utc()
    scan_status: dict[str, Any] = {
        "has_scan": latest_run is not None,
        "run_id": latest_run.id if latest_run else None,
        "finished_at": (
            latest_run.finished_at.isoformat()
            if latest_run and latest_run.finished_at
            else (latest_run.started_at.isoformat() if latest_run else None)
        ),
        "age_hours": None,
        "age_days": None,
        "stale": latest_run is None,
        "universe_size": latest_run.considered_count if latest_run else 0,
        "eligible_count": latest_run.eligible_count if latest_run else 0,
        "buy_entries": sum(1 for e in entries if e.buy_count > 0),
    }
    if latest_run is not None:
        ref_dt = latest_run.finished_at or latest_run.started_at
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=now.tzinfo)
        delta_hours = max(0.0, (now - ref_dt).total_seconds() / 3600.0)
        scan_status["age_hours"] = round(delta_hours, 1)
        scan_status["age_days"] = int(delta_hours // 24)
        scan_status["stale"] = delta_hours >= 24.0

    sectors_list = list(latest_run.sectors_snapshot or []) if latest_run else []
    leading = [s for s in sectors_list if s.get("quadrant") == "Leading"]
    improving = [s for s in sectors_list if s.get("quadrant") == "Improving"]
    shifts: list[dict[str, Any]] = []
    if latest_run and prev_run and latest_run.sectors_snapshot and prev_run.sectors_snapshot:
        prev_map = {s.get("key"): s.get("quadrant") for s in prev_run.sectors_snapshot}
        for s in latest_run.sectors_snapshot:
            pq = prev_map.get(s.get("key"))
            cq = s.get("quadrant")
            if pq and cq and pq != cq:
                shifts.append(
                    {
                        "sector_key": s.get("key"),
                        "nse_name": s.get("nse_name"),
                        "from_quadrant": pq,
                        "to_quadrant": cq,
                    }
                )

    entry_map = {e.symbol: e for e in entries}
    near_pivot: list[dict[str, Any]] = []
    flipped_buy_count = 0
    for w in watch_rows:
        entry = entry_map.get(w.symbol)
        if entry is None:
            continue
        prev = w.last_known_stances or {}
        cur_stances = {
            v.get("strategy_id"): v.get("stance")
            for v in (entry.verdicts or [])
            if v.get("strategy_id")
        }
        flipped = any(
            prev.get(sid) == "WATCH" and st == "BUY"
            for sid, st in cur_stances.items()
            if not w.target_strategy_id or w.target_strategy_id == sid
        )
        if flipped:
            flipped_buy_count += 1
        last_px = _resolve_price(entry, w.symbol, price_source)
        best_dist: float | None = None
        best_plan: dict[str, Any] | None = None
        best_sid: str | None = None
        for v in entry.verdicts or []:
            plan = v.get("plan")
            if not plan or not last_px or last_px <= 0:
                continue
            sid = v.get("strategy_id")
            if w.target_strategy_id and w.target_strategy_id != sid:
                continue
            pivot = plan.get("entry")
            if pivot:
                d = round((pivot - last_px) / last_px * 100.0, 2)
                if best_dist is None or abs(d) < abs(best_dist):
                    best_dist = d
                    best_plan = plan
                    best_sid = sid
        if best_dist is not None and -3.0 <= best_dist <= 5.0:
            near_pivot.append(
                {
                    "symbol": w.symbol,
                    "book_intent": w.book_intent,
                    "strategy_id": best_sid,
                    "last_price": round(last_px, 2) if last_px else None,
                    "entry": best_plan.get("entry") if best_plan else None,
                    "stop": best_plan.get("stop") if best_plan else None,
                    "distance_pct": best_dist,
                    "flipped_buy": flipped,
                }
            )
    near_pivot.sort(key=lambda r: abs(r["distance_pct"]))

    ledger = Ledger(session_factory)
    swing_open = [p for p in ledger.positions(Book.SWING) if p.is_open]
    lt_open = [p for p in ledger.positions(Book.LONGTERM) if p.is_open]
    standing_themes = ThemeStore(session_factory).standing(limit=5)
    feed = InsightFeed(session_factory)

    return {
        "market": {
            **session_info,
            "nifty50": nifty50,
            "nifty500": nifty500,
        },
        "scan_status": scan_status,
        "sectors_summary": {
            "leading_count": len(leading),
            "improving_count": len(improving),
            "top_leading": leading[:3],
            "top_improving": improving[:3],
            "shifts": shifts,
        },
        "watchlist_pulse": {
            "total_watched": len(watch_rows),
            "flipped_buy_count": flipped_buy_count,
            "near_pivot_count": len(near_pivot),
            "items": near_pivot[:6],
        },
        "books": {
            "swing_open": len(swing_open),
            "longterm_open": len(lt_open),
            "total_open": len(swing_open) + len(lt_open),
            "swing_cost_basis": round(sum(p.cost_basis for p in swing_open), 2),
            "longterm_cost_basis": round(sum(p.cost_basis for p in lt_open), 2),
        },
        "top_themes": standing_themes[:4],
        "unread_insights": feed.unread_count(),
    }
