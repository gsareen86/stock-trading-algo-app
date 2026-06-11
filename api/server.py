import os
import sys
import math
import logging
import threading
import io
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

import pandas as pd
import numpy as np

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

# Allow importing from root directory
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    INITIAL_CAPITAL,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    MAX_OPEN_POSITIONS,
    RISK_PER_TRADE_PCT,
    MIN_COMPOSITE_SCORE,
    SIGNAL_POLL_INTERVAL_SEC,
    LOG_DIR,
    IST
)
from db.models import BACKEND, get_conn, init_db, query_df, insert_returning_id
from analytics.metrics import (
    benchmark_series,
    closed_positions_report,
    portfolio_summary,
    strategy_breakdown,
    trade_stats,
)
from data.fetcher import latest_price, latest_price_with_ts, market_is_open
from data.fundamentals import is_bank, screener_url
from data.news_scraper import (
    news_db_stats,
    recent_news_for_ticker,
    retag_existing_news,
    scrape_all as scrape_all_news,
)
from data.universe import load_universe
from nlp.sentiment import score_news_items
from engine.portfolio import close_position, open_positions, snapshots_df, trades_df
from scheduler import runner as runner_mod

# Positional imports
from positional.market_regime import get_latest_regime, compute_market_regime
from positional.runner import run_exit_checks, run_eod_scan, run_regime_check
from positional.universe import process_screener_csv, _COL_MAP, _find_col

log = logging.getLogger("api_server")

app = FastAPI(title="Virtual Trading Bot API", version="2.0.0")

# CORS Middleware for local React frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins locally
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# PYDANTIC SCHEMAS
# -------------------------------------------------------------
class BotControlInput(BaseModel):
    status: Optional[str] = None
    mode: Optional[str] = None

class BotParametersInput(BaseModel):
    max_open_positions: int
    risk_per_trade_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    min_composite_score: float

class DecisionInput(BaseModel):
    action: str  # APPROVE / REJECT
    note: Optional[str] = ""

class PositionalControlInput(BaseModel):
    llm_research_enabled: bool
    swap_enabled: bool

# Helper to convert UTC timestamp to IST strings
def to_ist_str(ts_iso: Any) -> str:
    if not ts_iso:
        return "—"
    try:
        t = pd.to_datetime(ts_iso)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return t.tz_convert("Asia/Kolkata").strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception:
        return str(ts_iso)

# -------------------------------------------------------------
# BOT STATE & CONTROL ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/bot/status")
def get_bot_status():
    """Retrieve active status, mode, parameter limits, market state, and last scheduler loop results."""
    try:
        bot_state = runner_mod.get_bot_state()
        now_ist = datetime.now(IST)
        m_open = market_is_open(now_ist)
        
        # Get latest cycle run summary
        last_cycle = runner_mod.last_cycle_summary()
        if last_cycle:
            last_cycle = dict(last_cycle)
            if last_cycle.get("summary"):
                try:
                    last_cycle["summary"] = json.loads(last_cycle["summary"])
                except Exception:
                    pass
            last_cycle["started_at_ist"] = to_ist_str(last_cycle.get("started_at"))
            last_cycle["finished_at_ist"] = to_ist_str(last_cycle.get("finished_at"))

        return {
            "status": bot_state.get("status", "STOPPED"),
            "mode": bot_state.get("mode", "auto"),
            "market_open": m_open,
            "market_time_ist": now_ist.strftime("%H:%M:%S IST"),
            "is_weekday": now_ist.weekday() < 5,
            "last_cycle": last_cycle,
            "params": {
                "max_open_positions": bot_state.get("max_open_positions", 5),
                "risk_per_trade_pct": bot_state.get("risk_per_trade_pct", 0.04),
                "stop_loss_pct": bot_state.get("stop_loss_pct", 0.05),
                "take_profit_pct": bot_state.get("take_profit_pct", 0.10),
                "min_composite_score": bot_state.get("min_composite_score", 60.0),
            }
        }
    except Exception as e:
        log.error("Error in get_bot_status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bot/control")
def control_bot(input_data: BotControlInput):
    """Start, pause, or square-off the bot scheduler engine."""
    try:
        runner_mod.set_bot_state(status=input_data.status, mode=input_data.mode)
        return {"success": True, "status": input_data.status, "mode": input_data.mode}
    except Exception as e:
        log.error("Error in control_bot: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/bot/parameters")
def update_bot_parameters(input_data: BotParametersInput):
    """Dynamically modify risk constraints, max holdings, and target triggers."""
    try:
        with get_conn() as conn:
            conn.execute(
                """UPDATE bot_control
                      SET max_open_positions = ?,
                          risk_per_trade_pct = ?,
                          stop_loss_pct = ?,
                          take_profit_pct = ?,
                          min_composite_score = ?,
                          updated_at = ?
                    WHERE id = 1""",
                (
                    input_data.max_open_positions,
                    input_data.risk_per_trade_pct,
                    input_data.stop_loss_pct,
                    input_data.take_profit_pct,
                    input_data.min_composite_score,
                    datetime.utcnow().isoformat()
                )
            )
        return {"success": True, "message": "Parameters updated successfully"}
    except Exception as e:
        log.error("Error in update_bot_parameters: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def run_cycle_task(force: bool):
    try:
        log.info("Starting background cycle task [force=%s]...", force)
        runner_mod.run_cycle(force=force, triggered_by="manual_api")
        log.info("Background cycle task completed.")
    except Exception as e:
        log.error("Error running background cycle task: %s", e)

@app.post("/api/bot/cycle/run")
def trigger_cycle(background_tasks: BackgroundTasks, force: bool = Query(True)):
    """Force run an intraday scan cycle immediately in a background task."""
    try:
        background_tasks.add_task(run_cycle_task, force)
        return {"success": True, "message": "Intraday cycle triggered in background"}
    except Exception as e:
        log.error("Error triggering cycle: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# PORTFOLIO & ANALYTICS ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/portfolio/summary")
def get_portfolio_summary():
    """Retrieve real-time asset summary, risk indexes, and general metrics."""
    try:
        summary = portfolio_summary()
        # Add dynamic live valuations
        ops = open_positions()
        live_unrealized_pnl = 0.0
        for p in ops:
            try:
                px = latest_price(p["ticker"])
            except Exception:
                px = None
            if px is None:
                px = p["entry_price"]
            
            side_str = (p.get("side") or "LONG").upper()
            if side_str == "SHORT":
                pnl = (p["entry_price"] - px) * p["quantity"]
            else:
                pnl = (px - p["entry_price"]) * p["quantity"]
            live_unrealized_pnl += pnl

        summary["live_unrealized_pnl"] = round(live_unrealized_pnl, 2)
        summary["live_total_value"] = round(summary["cash"] + summary["equity"] + live_unrealized_pnl, 2)
        return summary
    except Exception as e:
        log.error("Error in get_portfolio_summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/portfolio/capacity")
def get_portfolio_capacity():
    """Get active/max portfolio capacity slot ratios."""
    try:
        bot_state = runner_mod.get_bot_state()
        max_slots = bot_state.get("max_open_positions", 5)
        ops = open_positions()
        active_slots = len(ops)
        return {
            "active_slots": active_slots,
            "max_slots": max_slots,
            "remaining_slots": max(0, max_slots - active_slots),
            "ratio": round(active_slots / max_slots, 2) if max_slots > 0 else 0
        }
    except Exception as e:
        log.error("Error in get_portfolio_capacity: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/portfolio/equity-curve")
def get_equity_curve(days: int = Query(60)):
    """Fetch synchronized time-series data for both bot portfolio and Nifty 50 benchmark."""
    try:
        snaps = snapshots_df()
        data_points = []
        if not snaps.empty:
            snaps_local = snaps.copy()
            snaps_local["ts_ist"] = snaps_local["ts"].apply(to_ist_str)
            for idx, r in snaps_local.iterrows():
                data_points.append({
                    "ts": r["ts"],
                    "ts_ist": r["ts_ist"],
                    "portfolio_value": round(float(r["total_value"]), 2),
                    "cash": round(float(r["cash"]), 2),
                    "equity": round(float(r["equity"]), 2),
                    "unrealized_pnl": round(float(r["unrealized_pnl"]), 2),
                    "realized_pnl": round(float(r["realized_pnl"]), 2),
                })
        
        # Benchmark scaling
        bench_points = []
        try:
            bench = benchmark_series(days=days)
            if bench is not None and not bench.empty:
                first_px = float(bench.iloc[0])
                for ts, val in bench.items():
                    bench_scaled = (val / first_px) * INITIAL_CAPITAL
                    bench_points.append({
                        "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                        "ts_ist": to_ist_str(ts),
                        "benchmark_value": round(bench_scaled, 2),
                        "raw_close": round(float(val), 2)
                    })
        except Exception as bench_err:
            log.warning("Could not fetch benchmark series: %s", bench_err)

        return {
            "portfolio": data_points,
            "benchmark": bench_points,
            "initial_capital": INITIAL_CAPITAL
        }
    except Exception as e:
        log.error("Error in get_equity_curve: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/portfolio/drawdown")
def get_portfolio_drawdown():
    """Calculate and return a time series of portfolio drawdown levels."""
    try:
        snaps = snapshots_df()
        dd_points = []
        if not snaps.empty:
            equity = snaps["total_value"]
            cummax = equity.cummax()
            dd = (equity - cummax) / cummax.replace(0, np.nan)
            
            for idx, r in snaps.iterrows():
                dd_val = dd.iloc[idx]
                dd_points.append({
                    "ts": r["ts"],
                    "ts_ist": to_ist_str(r["ts"]),
                    "value": round(float(r["total_value"]), 2),
                    "drawdown_pct": round(float(dd_val) * 100, 2)
                })
        return dd_points
    except Exception as e:
        log.error("Error in get_portfolio_drawdown: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# OPEN POSITIONS & CLOSED TRADES ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/positions/open")
def get_open_positions(force_refresh: bool = Query(False)):
    """Fetch all active open trades, pulling dynamic yfinance prices to calculate live unrealized margins."""
    try:
        ops = open_positions()
        results = []
        for p in ops:
            try:
                px, px_ts = latest_price_with_ts(p["ticker"], use_cache=not force_refresh)
            except Exception:
                px, px_ts = None, None
            
            if px is None:
                px = p["entry_price"]
            
            side_str = (p.get("side") or "LONG").upper()
            if side_str == "SHORT":
                pnl = (p["entry_price"] - px) * p["quantity"]
                pnl_pct = (1 - px / p["entry_price"]) * 100 if p["entry_price"] else 0.0
            else:
                pnl = (px - p["entry_price"]) * p["quantity"]
                pnl_pct = (px / p["entry_price"] - 1) * 100 if p["entry_price"] else 0.0
            
            # Additional metadata formatting
            results.append({
                "id": p["id"],
                "ticker": p["ticker"],
                "side": side_str,
                "quantity": p["quantity"],
                "entry_price": round(float(p["entry_price"]), 2),
                "current_price": round(float(px), 2),
                "price_as_of": to_ist_str(px_ts),
                "stop_loss": round(float(p["stop_loss"]), 2) if p["stop_loss"] else None,
                "take_profit": round(float(p["take_profit"]), 2) if p["take_profit"] else None,
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl_pct, 2),
                "strategy": p["strategy"] or "—",
                "composite_score": p["composite_score"],
                "entered_at": to_ist_str(p["entry_ts"]),
                "entered_at_raw": p["entry_ts"],
                "high_water_mark": round(float(p["high_water_mark"]), 2) if p.get("high_water_mark") else None,
                "atr_at_entry": p.get("atr_at_entry"),
                "t1_target": p.get("t1_target"),
                "t1_taken": p.get("t1_taken", 0)
            })
        return results
    except Exception as e:
        log.error("Error in get_open_positions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/positions/closed")
def get_closed_positions(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Retrieve full-cycle round-trip trade data with realized return stats."""
    try:
        report = closed_positions_report(start_date=start_date, end_date=end_date)
        if report.empty:
            return []
        
        results = []
        for idx, r in report.iterrows():
            results.append({
                "position_id": int(r["position_id"]),
                "ticker": r["ticker"],
                "side": r["direction"],
                "quantity": int(r["qty"]),
                "entry_price": round(float(r["entry_price"]), 2),
                "exit_price": round(float(r["exit_price"]), 2) if pd.notna(r["exit_price"]) else None,
                "opened_at": to_ist_str(r["opened_at"]),
                "closed_at": to_ist_str(r["closed_at"]),
                "pnl": round(float(r["pnl"]), 2),
                "pnl_pct": round((r["exit_price"] / r["entry_price"] - 1 if r["direction"] == "LONG" else 1 - r["exit_price"] / r["entry_price"]) * 100, 2) if pd.notna(r["exit_price"]) and r["entry_price"] else 0,
                "strategy": r["strategy"] or "—"
            })
        return results
    except Exception as e:
        log.error("Error in get_closed_positions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/trades/raw")
def get_raw_trades():
    """Retrieve the raw transaction logs database ledger (individual fills)."""
    try:
        df = trades_df()
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            results.append({
                "id": int(r["id"]),
                "ts": to_ist_str(r["ts"]),
                "ticker": r["ticker"],
                "side": r["side"],
                "quantity": int(r["quantity"]),
                "price": round(float(r["price"]), 2),
                "value": round(float(r["value"]), 2),
                "costs": round(float(r["costs"]), 2),
                "net_value": round(float(r["net_value"]), 2),
                "strategy": r["strategy"] or "—",
                "reason": r["reason"] or "—",
                "composite_score": r["composite_score"],
                "mode": r["mode"],
                "position_id": int(r["position_id"]) if pd.notna(r["position_id"]) else None
            })
        return results
    except Exception as e:
        log.error("Error in get_raw_trades: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# SIGNALS & APPROVAL QUEUES
# -------------------------------------------------------------
@app.get("/api/signals")
def get_signals(limit: int = Query(50)):
    """Fetch history of scans and signal generation metrics."""
    try:
        df = query_df(f"SELECT * FROM signals ORDER BY ts DESC LIMIT {limit}")
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            results.append({
                "id": int(r["id"]),
                "ts": to_ist_str(r["ts"]),
                "ticker": r["ticker"],
                "action": r["action"],
                "strategy": r["strategy"],
                "technical_score": r["technical_score"],
                "fundamental_score": r["fundamental_score"],
                "sentiment_score": r["sentiment_score"],
                "composite_score": r["composite_score"],
                "price": round(float(r["price"]), 2) if pd.notna(r["price"]) else None,
                "reason": r["reason"] or "—",
                "taken": bool(r["taken"]),
                "threshold_at_time": r.get("threshold_at_time"),
                "mode_at_time": r.get("mode_at_time")
            })
        return results
    except Exception as e:
        log.error("Error in get_signals: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/approvals")
def get_pending_approvals():
    """Fetch all pending signals currently waiting for manual approval."""
    try:
        df = query_df("SELECT * FROM pending_approvals WHERE status = 'PENDING' ORDER BY created_at DESC")
        if df.empty:
            return []
        
        results = []
        now = datetime.utcnow()
        for idx, r in df.iterrows():
            expires_at = pd.to_datetime(r["expires_at"])
            remaining_secs = max(0, int((expires_at.replace(tzinfo=None) - now).total_seconds()))
            
            results.append({
                "id": int(r["id"]),
                "created_at": to_ist_str(r["created_at"]),
                "expires_at": to_ist_str(r["expires_at"]),
                "remaining_seconds": remaining_secs,
                "ticker": r["ticker"],
                "side": r.get("side", "LONG"),
                "action": r["action"],
                "quantity": int(r["quantity"]),
                "price": round(float(r["price"]), 2),
                "stop_loss": round(float(r["stop_loss"]), 2) if r["stop_loss"] else None,
                "take_profit": round(float(r["take_profit"]), 2) if r["take_profit"] else None,
                "strategy": r["strategy"] or "—",
                "composite_score": r["composite_score"],
                "reason": r["reason"] or "—",
                "status": r["status"]
            })
        return results
    except Exception as e:
        log.error("Error in get_pending_approvals: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/approvals/{id}/decide")
def decide_approval(id: int, decision: DecisionInput):
    """Manually approve or reject a queued buy/sell order signal."""
    try:
        action = decision.action.upper().strip()
        if action not in ("APPROVE", "REJECT"):
            raise HTTPException(status_code=400, detail="Invalid decision action; use 'APPROVE' or 'REJECT'")
        
        with get_conn() as conn:
            # Check current status
            r = conn.execute("SELECT * FROM pending_approvals WHERE id=?", (id,)).fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Signal queue record not found")
            if r["status"] != "PENDING":
                raise HTTPException(status_code=400, detail=f"Cannot decide on signal with status '{r['status']}'")
            
            now_iso = datetime.utcnow().isoformat()
            if action == "REJECT":
                conn.execute(
                    "UPDATE pending_approvals SET status='REJECTED', decided_at=?, decision_note=? WHERE id=?",
                    (now_iso, decision.note, id)
                )
                return {"success": True, "message": "Signal successfully rejected"}
            
            # APPROVE path: Transition to APPROVED state
            conn.execute(
                "UPDATE pending_approvals SET status='APPROVED', decision_note=? WHERE id=?",
                (decision.note or "Manual approval", id)
            )

        # Trigger execution immediately (races against background loop, but contains internal locks)
        pos_id = runner_mod.execute_single_approval(id)
        if pos_id:
            return {"success": True, "message": "Signal approved and executed immediately", "position_id": pos_id}
        else:
            # Check updated state to see what happened
            with get_conn() as conn:
                updated = conn.execute("SELECT * FROM pending_approvals WHERE id=?", (id,)).fetchone()
            return {
                "success": False,
                "message": f"Approved state updated but execution deferred or preempted. Status: {updated['status']}"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error deciding approval: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# NEWS & SENTIMENT ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/news/stats")
def get_news_stats():
    """Retrieve general database scrape volumes and last refresh times."""
    try:
        stats = news_db_stats()
        return stats
    except Exception as e:
        log.error("Error in get_news_stats: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def run_news_scrape():
    try:
        log.info("Starting background news scraping...")
        scrape_all_news()
        score_news_items()
        log.info("Background news scraping completed.")
    except Exception as e:
        log.error("Error in background news scraping: %s", e)

@app.post("/api/news/scrape")
def trigger_news_scrape(background_tasks: BackgroundTasks):
    """Trigger background scraper to fetch RSS/API news and run VADER/FinBERT models."""
    try:
        background_tasks.add_task(run_news_scrape)
        return {"success": True, "message": "News scraping triggered in background"}
    except Exception as e:
        log.error("Error in news scrape trigger: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def run_news_retag():
    try:
        log.info("Starting background news retagging...")
        retag_existing_news()
        log.info("Background news retagging completed.")
    except Exception as e:
        log.error("Error in background news retagging: %s", e)

@app.post("/api/news/retag")
def trigger_news_retag(background_tasks: BackgroundTasks):
    """Re-run tickers extraction parser over previously downloaded headlines."""
    try:
        background_tasks.add_task(run_news_retag)
        return {"success": True, "message": "News retagging triggered in background"}
    except Exception as e:
        log.error("Error in news retag trigger: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/news/leaderboard")
def get_news_leaderboard(
    hours: int = Query(24),
    scope: str = Query("universe_with_news"),
    sort_by: str = Query("n_desc")
):
    """Calculate recency-decay weighted sentiment rankings for NSE symbols."""
    try:
        lb_cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Pull news & sector maps
        with get_conn() as conn:
            news_rows = conn.execute(
                """SELECT ts, source, title, summary, url, tickers, sentiment
                     FROM news
                    WHERE tickers IS NOT NULL
                      AND tickers <> ''
                      AND ts >= ?""",
                (lb_cutoff,),
            ).fetchall()
            sector_rows = conn.execute(
                "SELECT ticker, sector FROM fundamentals"
            ).fetchall()
            
        sector_map = {r["ticker"]: (r["sector"] or "") for r in sector_rows}
        lb_open_tickers = [p["ticker"] for p in open_positions()]

        agg: dict[str, dict] = {}
        for r in news_rows:
            if r["sentiment"] is None:
                continue
            tickers = [t for t in (r["tickers"] or "").split(",") if t.strip()]
            for tk in tickers:
                d = agg.setdefault(tk, {
                    "scored": [],
                    "latest_ts": None,
                    "latest_title": "",
                    "latest_url": "",
                    "latest_sentiment": None,
                })
                d["scored"].append((float(r["sentiment"]), r["ts"] or ""))
                if d["latest_ts"] is None or (r["ts"] or "") > d["latest_ts"]:
                    d["latest_ts"] = r["ts"]
                    d["latest_title"] = r["title"] or ""
                    d["latest_url"] = r["url"] or ""
                    d["latest_sentiment"] = float(r["sentiment"])

        if not agg:
            return []

        # Scope filters
        if scope == "open_positions":
            agg = {k: v for k, v in agg.items() if k in lb_open_tickers}
        elif scope == "min_three":
            agg = {k: v for k, v in agg.items() if len(v["scored"]) >= 3}

        half_life_h = max(1.0, float(hours) / 4.0)
        cutoff_dt = pd.to_datetime(lb_cutoff)

        rows = []
        for tk, d in agg.items():
            scored = d["scored"]
            scores_only = [s for s, _ in scored]
            n_pos = sum(1 for s in scores_only if s >= 0.05)
            n_neg = sum(1 for s in scores_only if s <= -0.05)
            n_neu = len(scores_only) - n_pos - n_neg
            avg = sum(scores_only) / len(scores_only)

            # Recency-weighted average
            wsum = 0.0
            wtot = 0.0
            for s, ts_iso in scored:
                try:
                    age_h = (pd.to_datetime(ts_iso) - cutoff_dt).total_seconds() / 3600.0
                except Exception:
                    age_h = 0.0
                w = math.pow(0.5, max(0.0, (hours - age_h)) / half_life_h)
                wsum += s * w
                wtot += w
            wavg = (wsum / wtot) if wtot else avg

            rows.append({
                "ticker": tk,
                "is_open_position": tk in lb_open_tickers,
                "sector": sector_map.get(tk, "—") or "—",
                "articles": len(scored),
                "breakdown": f"{n_pos}/{n_neu}/{n_neg}",
                "avg_sentiment": round(avg, 3),
                "weighted_sentiment": round(wavg, 3),
                "latest_sentiment": round(d["latest_sentiment"], 3) if d["latest_sentiment"] is not None else 0.0,
                "latest_headline": d["latest_title"],
                "latest_url": d["latest_url"],
                "last_update": to_ist_str(d["latest_ts"]),
                "_ts": d["latest_ts"] or "",
            })

        # Sorting logic
        if sort_by == "n_desc":
            rows.sort(key=lambda r: (-r["articles"], -r["weighted_sentiment"]))
        elif sort_by == "avg_desc":
            rows.sort(key=lambda r: -r["weighted_sentiment"])
        elif sort_by == "avg_asc":
            rows.sort(key=lambda r: r["weighted_sentiment"])
        elif sort_by == "ts_desc":
            rows.sort(key=lambda r: r["_ts"], reverse=True)

        return rows
    except Exception as e:
        log.error("Error in get_news_leaderboard: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/news/ticker/{ticker}")
def get_ticker_news(ticker: str, hours: int = Query(24), limit: int = Query(20)):
    """Recent tagged articles for one ticker (window/limit configurable)."""
    try:
        tk_upper = ticker.upper().strip()
        feed = recent_news_for_ticker(tk_upper, hours=min(int(hours), 24 * 14),
                                      limit=min(int(limit), 50))
        
        results = []
        for r in feed:
            results.append({
                "ts": to_ist_str(r["ts"]),
                "source": r["source"],
                "title": r["title"],
                "summary": r["summary"] or "",
                "url": r["url"],
                "sentiment": round(float(r["sentiment"]), 3) if r["sentiment"] is not None else None
            })
        return results
    except Exception as e:
        log.error("Error in get_ticker_news: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# FUNDAMENTALS ENDPOINTS
# -------------------------------------------------------------
def clean_float(v, round_digits=None, multiplier=1.0) -> Optional[float]:
    """Helper to convert and sanitize float values for JSON compliance."""
    if v is None or pd.isna(v):
        return None
    try:
        val = float(v)
        if np.isinf(val) or np.isnan(val):
            return None
        val = val * multiplier
        if round_digits is not None:
            return round(val, round_digits)
        return val
    except (TypeError, ValueError):
        return None


def clean_str(v, default="—") -> str:
    """Helper to convert and sanitize string values for JSON compliance, avoiding float('nan')."""
    if v is None or pd.isna(v):
        return default
    val = str(v).strip()
    if val.lower() in ("nan", "none", "null", ""):
        return default
    return val


# Tickers stored elsewhere can carry a yfinance suffix (".NS"/".BO"). The
# fundamentals table and screener URLs use the bare NSE symbol, so we strip
# the suffix when building the union universe.
def _bare(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return t[:-3]
    return t


_FUNDAMENTALS_TOP_SCANS = 30


def _build_fundamentals_universe(top_scans: int = _FUNDAMENTALS_TOP_SCANS) -> Dict[str, List[str]]:
    """Return mapping of bare ticker -> sorted list of source-tags.

    Tags (in order of importance for display):
      * ``intraday_open``   - in the intraday positions table, status=OPEN
      * ``positional_open`` - in pos_positions, status=OPEN
      * ``lt_universe``     - shortlisted for long-term tracking
      * ``pos_scan_top``    - top N from latest positional scan
      * ``pinned``          - user-pinned via the Fundamentals tab
    """
    from collections import defaultdict
    sources: Dict[str, set] = defaultdict(set)
    with get_conn() as conn:
        for r in conn.execute("SELECT DISTINCT ticker FROM positions WHERE status='OPEN'").fetchall():
            sources[_bare(r["ticker"])].add("intraday_open")
        for r in conn.execute("SELECT DISTINCT ticker FROM pos_positions WHERE status='OPEN'").fetchall():
            sources[_bare(r["ticker"])].add("positional_open")
        for r in conn.execute("SELECT ticker FROM lt_universe WHERE in_universe=1").fetchall():
            sources[_bare(r["ticker"])].add("lt_universe")
        # Top N from the most recent scan — composite_score may be NULL on
        # pre-migration rows, so COALESCE keeps the ordering stable.
        for r in conn.execute(
            """SELECT ticker FROM pos_scans
                ORDER BY scanned_at DESC,
                         COALESCE(composite_score, 0) DESC,
                         COALESCE(score, 0) DESC
                LIMIT ?""",
            (top_scans,),
        ).fetchall():
            sources[_bare(r["ticker"])].add("pos_scan_top")
        for r in conn.execute("SELECT ticker FROM fundamentals_pins").fetchall():
            sources[_bare(r["ticker"])].add("pinned")
    return {t: sorted(s) for t, s in sources.items() if t}


@app.get("/api/fundamentals/universe")
def get_fundamentals_universe():
    """List of tickers in the auto-built fundamentals universe with sources."""
    try:
        uni = _build_fundamentals_universe()
        return [{"ticker": t, "sources": s} for t, s in sorted(uni.items())]
    except Exception as e:
        log.error("Error in get_fundamentals_universe: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fundamentals")
def get_fundamentals_table(scope: str = Query("universe")):
    """Retrieve fundamental scorecards with financial warnings flags.

    ``scope`` defaults to ``universe`` — tickers held in any book, in the
    long-term watchlist, in the top-30 of the latest positional scan, or
    manually pinned. ``scope=all`` returns the legacy full-table view.
    """
    try:
        df = query_df("SELECT * FROM fundamentals")
        existing = {r["ticker"]: r for _, r in df.iterrows()} if not df.empty else {}

        if scope == "all":
            ordered_tickers = list(existing.keys())
            universe: Dict[str, List[str]] = {}
        else:
            universe = _build_fundamentals_universe()
            # Include every ticker in the universe even if we don't yet have a
            # fundamentals row for it - the UI surfaces a "needs fetch" badge.
            ordered_tickers = list(universe.keys())

        results = []
        for ticker in ordered_tickers:
            r = existing.get(ticker)
            sources = universe.get(ticker, [])
            if r is not None:
                is_bank_flag = is_bank(
                    clean_str(r.get("sector"), ""),
                    clean_str(r.get("industry"), "")
                )
                results.append({
                    "ticker": ticker,
                    "screener_url": screener_url(ticker),
                    "is_bank": is_bank_flag,
                    "sources": sources,
                    "fetched_at": to_ist_str(r["fetched_at"]),
                    "pe_ratio": clean_float(r["pe_ratio"], round_digits=2),
                    "peg_ratio": clean_float(r["peg_ratio"], round_digits=2),
                    "eps": clean_float(r["eps"], round_digits=2),
                    "revenue_growth": clean_float(r["revenue_growth"], round_digits=2, multiplier=100.0),
                    "earnings_growth": clean_float(r["earnings_growth"], round_digits=2, multiplier=100.0),
                    "debt_to_equity": clean_float(r["debt_to_equity"], round_digits=2),
                    "roe": clean_float(r["roe"], round_digits=2, multiplier=100.0),
                    "profit_margin": clean_float(r["profit_margin"], round_digits=2, multiplier=100.0),
                    "market_cap": clean_float(r["market_cap"], round_digits=2),
                    "dividend_yield": clean_float(r["dividend_yield"], round_digits=2, multiplier=100.0),
                    "sector": clean_str(r["sector"]),
                    "industry": clean_str(r["industry"]),
                    "fundamental_score": r["fundamental_score"],
                })
            else:
                # Universe ticker with no fundamentals row yet — sparse stub
                # so the UI can still render it and offer a refresh button.
                results.append({
                    "ticker": ticker,
                    "screener_url": screener_url(ticker),
                    "is_bank": False,
                    "sources": sources,
                    "fetched_at": "—",
                    "pe_ratio": None, "peg_ratio": None, "eps": None,
                    "revenue_growth": None, "earnings_growth": None,
                    "debt_to_equity": None, "roe": None, "profit_margin": None,
                    "market_cap": None, "dividend_yield": None,
                    "sector": "—", "industry": "—",
                    "fundamental_score": None,
                })

        # Sort: open positions first, then by fundamental_score desc, then ticker
        def _rank(item) -> tuple:
            srcs = set(item.get("sources") or [])
            priority = 0
            if "intraday_open" in srcs:    priority -= 8
            if "positional_open" in srcs:  priority -= 8
            if "pinned" in srcs:           priority -= 4
            if "lt_universe" in srcs:      priority -= 2
            score = item.get("fundamental_score")
            score = -float(score) if score is not None else 0.0
            return (priority, score, item.get("ticker") or "")

        results.sort(key=_rank)
        return results
    except Exception as e:
        log.error("Error in get_fundamentals_table: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fundamentals/detail/{ticker}")
def get_fundamentals_detail(ticker: str, refresh: bool = Query(False)):
    """Deep Screener.in fundamentals view for one ticker.

    Returns multi-year P&L, balance sheet, cash flow, ratios, quarterly
    results, shareholding pattern, pros/cons and recent announcements. The
    underlying scraper has a 24h on-disk cache - first call on a cold ticker
    can take 5-10 seconds (rate-limited HTTP); subsequent calls are cheap.
    Pass ``refresh=true`` to bypass the cache.
    """
    try:
        from longterm.screener_scraper import fetch_company
        tk = _bare(ticker)
        parsed = fetch_company(tk, force=bool(refresh))
        if not parsed:
            raise HTTPException(status_code=404, detail=f"Screener.in returned no data for {tk}")

        # Light sanitisation: cast Nones / pandas-NA-ish to plain JSON.
        def _scrub_series(rows):
            out = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                out.append({
                    "period": clean_str(row.get("period"), default=""),
                    "value": clean_float(row.get("value")),
                })
            return out

        def _scrub_shareholding(rows):
            out = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                out.append({
                    "period": clean_str(row.get("period"), default=""),
                    "promoter_pct": clean_float(row.get("promoter_pct"), round_digits=2),
                    "fii_pct":      clean_float(row.get("fii_pct"), round_digits=2),
                    "dii_pct":      clean_float(row.get("dii_pct"), round_digits=2),
                    "govt_pct":     clean_float(row.get("govt_pct"), round_digits=2),
                    "public_pct":   clean_float(row.get("public_pct"), round_digits=2),
                    "pledged_pct":  clean_float(row.get("pledged_pct"), round_digits=2),
                    "shareholders": clean_float(row.get("shareholders")),
                })
            return out

        return {
            "ticker": tk,
            "screener_url": parsed.get("url") or screener_url(tk),
            "view": parsed.get("view") or "—",
            "fetched_at": to_ist_str(parsed.get("fetched_at")),
            "warnings": parsed.get("warnings") or [],
            "top_ratios": {
                "market_cap_cr":      clean_float(parsed.get("market_cap_cr"), round_digits=2),
                "pe":                 clean_float(parsed.get("pe"), round_digits=2),
                "industry_pe":        clean_float(parsed.get("industry_pe"), round_digits=2),
                "roe_pct":            clean_float(parsed.get("roe_pct"), round_digits=2),
                "roce_pct":           clean_float(parsed.get("roce_pct"), round_digits=2),
                "debt_equity":        clean_float(parsed.get("debt_equity"), round_digits=2),
                "dividend_yield_pct": clean_float(parsed.get("dividend_yield_pct"), round_digits=2),
                "book_value":         clean_float(parsed.get("book_value"), round_digits=2),
                "face_value":         clean_float(parsed.get("face_value"), round_digits=2),
            },
            "profit_loss": {
                "revenue":          _scrub_series(parsed.get("revenue_yearly")),
                "operating_profit": _scrub_series(parsed.get("operating_profit_yearly")),
                "net_profit":       _scrub_series(parsed.get("net_profit_yearly")),
                "eps":              _scrub_series(parsed.get("eps_yearly")),
                "interest":         _scrub_series(parsed.get("interest_yearly")),
                "depreciation":     _scrub_series(parsed.get("depreciation_yearly")),
            },
            "balance_sheet": {
                "equity_capital":   _scrub_series(parsed.get("equity_capital_yearly")),
                "reserves":         _scrub_series(parsed.get("reserves_yearly")),
                "borrowings":       _scrub_series(parsed.get("borrowings_yearly")),
                "other_liabilities":_scrub_series(parsed.get("other_liab_yearly")),
                "total_liabilities":_scrub_series(parsed.get("total_liab_yearly")),
                "fixed_assets":     _scrub_series(parsed.get("fixed_assets_yearly")),
                "cwip":             _scrub_series(parsed.get("cwip_yearly")),
                "investments":      _scrub_series(parsed.get("investments_yearly")),
                "other_assets":     _scrub_series(parsed.get("other_assets_yearly")),
                "total_assets":     _scrub_series(parsed.get("total_assets_yearly")),
            },
            "cash_flow": {
                "cfo":      _scrub_series(parsed.get("cfo_yearly")),
                "cfi":      _scrub_series(parsed.get("cfi_yearly")),
                "cff":      _scrub_series(parsed.get("cff_yearly")),
                "net_cash": _scrub_series(parsed.get("net_cash_yearly")),
            },
            "ratios": {
                "roe":         _scrub_series(parsed.get("roe_yearly")),
                "roce":        _scrub_series(parsed.get("roce_yearly")),
                "opm":         _scrub_series(parsed.get("opm_yearly")),
                "debtor_days": _scrub_series(parsed.get("debtor_days_yearly")),
            },
            "quarterly_results": {
                "revenue":          _scrub_series(parsed.get("quarterly_revenue")),
                "operating_profit": _scrub_series(parsed.get("quarterly_operating_profit")),
                "net_profit":       _scrub_series(parsed.get("quarterly_net_profit")),
                "eps":              _scrub_series(parsed.get("quarterly_eps")),
                "opm":              _scrub_series(parsed.get("quarterly_opm")),
            },
            "shareholding": _scrub_shareholding(parsed.get("shareholding_quarterly")),
            "pros": parsed.get("pros") or [],
            "cons": parsed.get("cons") or [],
            "concalls": parsed.get("concalls") or [],
            "annual_reports": parsed.get("annual_reports") or [],
            "announcements": parsed.get("announcements") or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error in get_fundamentals_detail(%s): %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


# Dedicated cache for the Fundamentals price chart. The trading-engine
# parquet cache in data.fetcher holds only a year-ish at a time (whatever
# the most recent strategy fetch needed), so reusing it silently capped
# this endpoint's window - that's why "5Y" only showed ~17 months. This
# cache holds the FULL daily history we get from yfinance period="max"
# and is refreshed every 6 hours.
_PH_CACHE_DIR = Path(ROOT) / "cache" / "price_history_fundamentals"
_PH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_PH_CACHE_TTL_HOURS = 6


def _ph_full_history(ticker: str) -> "pd.DataFrame":
    """Fetch (or read from cache) the maximum available daily OHLCV for one
    ticker. Returns an empty DataFrame on any failure."""
    import time as _time
    from data.universe import to_yf_ticker
    yf_t = to_yf_ticker(ticker) if not ticker.endswith((".NS", ".BO")) else ticker
    cache_path = _PH_CACHE_DIR / f"{yf_t.replace('/', '_')}.parquet"

    if cache_path.exists():
        age_h = (_time.time() - cache_path.stat().st_mtime) / 3600.0
        if age_h < _PH_CACHE_TTL_HOURS:
            try:
                return pd.read_parquet(cache_path)
            except Exception as e:
                log.debug("price-history cache read failed for %s: %s", yf_t, e)

    import yfinance as yf
    try:
        df = yf.download(
            yf_t, period="max", interval="1d",
            progress=False, auto_adjust=False, threads=False,
        )
    except Exception as e:
        log.warning("price-history fetch failed for %s: %s", yf_t, e)
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance returns a MultiIndex when called with a single ticker - flatten.
    if hasattr(df.columns, "levels"):
        try:
            if any(yf_t in str(col) for col in df.columns.get_level_values(0)):
                df = df[yf_t]
            else:
                df.columns = df.columns.get_level_values(0)
        except Exception:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df[keep].copy()
    df.dropna(inplace=True)

    try:
        df.to_parquet(cache_path)
    except Exception as e:
        log.debug("price-history cache write failed for %s: %s", yf_t, e)

    return df


# Display window per period. ``None`` means "show everything in cache".
_PH_PERIOD_DAYS = {
    "1M":  30,
    "6M":  183,
    "1Y":  365,
    "3Y":  3 * 365,
    "5Y":  5 * 365,
    "10Y": 10 * 365,
    "Max": None,
}
# Periods that should be displayed at weekly granularity.
_PH_WEEKLY_PERIODS = {"3Y", "5Y", "10Y", "Max"}


@app.get("/api/fundamentals/price-history/{ticker}")
def get_fundamentals_price_history(
    ticker: str,
    period: str = Query("5Y"),
    years: int = Query(0),  # legacy back-compat
):
    """Daily/weekly Close + Volume + 50/200 DMA for the Fundamentals chart.

    Behaviour:
      * Always reads the *maximum* available daily history (cached per
        ticker), so changing timeframe in the UI actually shows the
        requested window instead of being capped by whatever the trading
        engine had previously cached.
      * 50/200 DMA are computed on the FULL history before slicing, so the
        moving-average lines have proper warmup even when the displayed
        window is shorter than 200 trading days.
      * 1M / 6M / 1Y render at daily resolution. 3Y / 5Y / 10Y / Max
        render at weekly resolution. Weekly rows keep the **real** last
        trading day timestamp in each week (we groupby ISO week and pick
        the tail row); we avoid resample("W").last() because that snaps
        each row's label to week-ending-Sunday and produced future-dated
        ticks (the bug from the previous iteration).
    """
    try:
        tk = _bare(ticker)
        period = (period or "5Y").upper()
        if period not in _PH_PERIOD_DAYS:
            period = "5Y"
        if years > 0 and period == "5Y":
            # Honour the legacy ?years=N query for any pre-existing callers.
            period = "Max" if years >= 10 else f"{int(years)}Y"
            if period not in _PH_PERIOD_DAYS:
                period = "5Y"

        full = _ph_full_history(tk)
        if full.empty or "Close" not in full.columns:
            return {"ticker": tk, "period": period, "series": []}

        # Compute the moving averages on the entire history so the displayed
        # window always carries valid SMA values from its first day.
        full = full.copy()
        full["sma50"]  = full["Close"].rolling(50,  min_periods=50).mean()
        full["sma200"] = full["Close"].rolling(200, min_periods=200).mean()

        # Slice to the requested display window.
        days_back = _PH_PERIOD_DAYS[period]
        if days_back is not None and len(full) > 0:
            cutoff = full.index.max() - pd.Timedelta(days=days_back)
            full = full[full.index >= cutoff]

        # Down-sample to weekly for long windows. Group by ISO week ending
        # Friday and take the last row - that keeps the actual trading-day
        # timestamp (Wed/Thu/Fri depending on holidays) rather than relabeling
        # to Sunday.
        if period in _PH_WEEKLY_PERIODS and len(full) > 0:
            try:
                week_id = full.index.to_period("W-FRI")
                full = full.assign(_w=week_id).groupby("_w").tail(1).drop(columns="_w")
            except Exception as e:
                log.debug("weekly resample failed for %s: %s", tk, e)

        series = []
        for ts, row in full.iterrows():
            try:
                close = float(row["Close"])
            except Exception:
                continue
            if np.isnan(close) or np.isinf(close):
                continue
            try:
                vol = float(row.get("Volume", 0))
                volume = 0 if (np.isnan(vol) or np.isinf(vol)) else int(vol)
            except Exception:
                volume = 0
            entry: Dict[str, Any] = {
                "ts": ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10],
                "close": round(close, 2),
                "volume": volume,
            }
            sma50 = row.get("sma50")
            sma200 = row.get("sma200")
            if sma50 is not None and not (isinstance(sma50, float) and (np.isnan(sma50) or np.isinf(sma50))):
                entry["sma50"] = round(float(sma50), 2)
            if sma200 is not None and not (isinstance(sma200, float) and (np.isnan(sma200) or np.isinf(sma200))):
                entry["sma200"] = round(float(sma200), 2)
            series.append(entry)

        return {"ticker": tk, "period": period, "series": series}
    except Exception as e:
        log.error("Error in get_fundamentals_price_history(%s): %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


class PinInput(BaseModel):
    ticker: str
    notes: Optional[str] = ""


@app.get("/api/fundamentals/pins")
def list_fundamentals_pins():
    """List user-pinned tickers in the Fundamentals tab."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT ticker, added_at, notes FROM fundamentals_pins ORDER BY added_at DESC"
            ).fetchall()
        return [
            {"ticker": r["ticker"], "added_at": to_ist_str(r["added_at"]), "notes": r["notes"] or ""}
            for r in rows
        ]
    except Exception as e:
        log.error("Error in list_fundamentals_pins: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fundamentals/pin")
def pin_fundamentals(input_data: PinInput):
    """Pin a ticker into the Fundamentals universe so it always shows up."""
    try:
        tk = _bare(input_data.ticker)
        if not tk:
            raise HTTPException(status_code=400, detail="ticker is required")
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO fundamentals_pins (ticker, added_at, notes)
                   VALUES (?, ?, ?)
                   ON CONFLICT (ticker) DO UPDATE SET
                       added_at = excluded.added_at,
                       notes    = excluded.notes""",
                (tk, datetime.now(timezone.utc).isoformat(), input_data.notes or ""),
            )
        return {"success": True, "ticker": tk}
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error in pin_fundamentals: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/fundamentals/pin/{ticker}")
def unpin_fundamentals(ticker: str):
    """Remove a ticker from the user-pinned set."""
    try:
        tk = _bare(ticker)
        with get_conn() as conn:
            conn.execute("DELETE FROM fundamentals_pins WHERE ticker = ?", (tk,))
        return {"success": True, "ticker": tk}
    except Exception as e:
        log.error("Error in unpin_fundamentals(%s): %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# LONG-TERM RESEARCH ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/research/candidates")
def get_research_candidates():
    """Retrieve high-conviction pipeline filters."""
    try:
        # Join quality scoring table with the universe limits table
        df = query_df(
            """SELECT q.*, u.sector, u.industry, u.market_cap
                 FROM lt_quality q
                 JOIN lt_universe u ON q.ticker = u.ticker
                ORDER BY q.total_score DESC"""
        )
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            results.append({
                "ticker": r["ticker"],
                "scored_at": to_ist_str(r["scored_at"]),
                "profitability_score": clean_float(r["profitability_score"]),
                "cash_quality_score": clean_float(r["cash_quality_score"]),
                "solvency_score": clean_float(r["solvency_score"]),
                "growth_score": clean_float(r["growth_score"]),
                "governance_score": clean_float(r["governance_score"]),
                "total_score": clean_float(r["total_score"]),
                "sector": clean_str(r["sector"]),
                "market_cap": clean_float(r["market_cap"], round_digits=2),
            })
        return results
    except Exception as e:
        log.error("Error in get_research_candidates: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/research/failures")
def get_research_failures():
    """Get candidate fail reason checklists."""
    try:
        df = query_df("SELECT ticker, sector, filter_reason FROM lt_universe WHERE in_universe = 0")
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            results.append({
                "ticker": r["ticker"],
                "sector": clean_str(r["sector"]),
                "reason": clean_str(r["filter_reason"], "Filtered out by fundamental rules")
            })
        return results
    except Exception as e:
        log.error("Error in get_research_failures: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# TELEMETRY & SYSTEM LOGS ENDPOINTS
# -------------------------------------------------------------
def tail_file(file_path: Path, num_lines: int = 500) -> list[str]:
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            file_size = f.tell()
            buffer_size = 8192
            lines: list[str] = []
            pos = file_size
            while pos > 0 and len(lines) <= num_lines:
                pos = max(0, pos - buffer_size)
                f.seek(pos, 0)
                chunk = f.read(buffer_size)
                lines = chunk.splitlines() + lines
            return lines[-num_lines:]
    except Exception:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.readlines()[-num_lines:]
        except Exception:
            return ["Log file read error."]

@app.get("/api/system/logs")
def get_system_logs(limit: int = Query(500), level: Optional[str] = Query(None)):
    """Fetch scrolling cycle activity telemetry files in real time."""
    try:
        log_file = Path(LOG_DIR) / "bot.log"
        lines = tail_file(log_file, limit)
        
        if level:
            lvl_upper = level.upper().strip()
            lines = [line for line in lines if lvl_upper in line]
            
        return {"lines": lines}
    except Exception as e:
        log.error("Error in get_system_logs: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/system/logs/download")
def download_system_logs():
    """Download full log report for deep system diagnostics."""
    try:
        log_file = Path(LOG_DIR) / "bot.log"
        if not log_file.exists():
            raise HTTPException(status_code=404, detail="Log file bot.log not found")
        return FileResponse(path=log_file, filename="trading_bot.log", media_type="text/plain")
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error downloading logs: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bot/cycles")
def get_bot_cycles(limit: int = Query(100)):
    """Query scheduled execution cycle metrics logs."""
    try:
        df = query_df(f"SELECT * FROM cycle_log ORDER BY id DESC LIMIT {limit}")
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            summary_dict = {}
            if r["summary"]:
                try:
                    summary_dict = json.loads(r["summary"])
                except Exception:
                    summary_dict = {"raw": str(r["summary"])}
            
            results.append({
                "id": int(r["id"]),
                "started_at": to_ist_str(r["started_at"]),
                "finished_at": to_ist_str(r["finished_at"]) if r["finished_at"] else None,
                "status": r["status"],
                "triggered_by": r["triggered_by"],
                "summary": summary_dict
            })
        return results
    except Exception as e:
        log.error("Error in get_bot_cycles: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# CORE ANALYTICS (KPIs & STRATEGIES)
# -------------------------------------------------------------
@app.get("/api/analytics/summary")
def get_analytics_summary():
    """Aggregate primary metrics (Profit Factor, win rate) of closed trades."""
    try:
        return trade_stats()
    except Exception as e:
        log.error("Error in get_analytics_summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/strategies")
def get_strategy_performance():
    """Retrieve performance statistics divided by specific trading strategy triggers."""
    try:
        df = strategy_breakdown()
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            results.append({
                "strategy": r["strategy"],
                "trades": int(r["trades"]),
                "total_pnl": round(float(r["total_pnl"]), 2),
                "avg_pnl": round(float(r["avg_pnl"]), 2),
                "wins": int(r["wins"]),
                "win_rate_pct": round(float(r["win_rate_pct"]), 2)
            })
        return results
    except Exception as e:
        log.error("Error in get_strategy_performance: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# LLM OBSERVABILITY ENDPOINTS
# -------------------------------------------------------------
# All data comes live from the llm_call_log table, which llm/client.py
# writes for every LLM request (success, cache hit, rate-limit, error).

@app.get("/api/llm/observability/totals")
def get_llm_observability_totals():
    """Today's LLM usage totals plus the currently configured provider/model."""
    from llm.observability import today_totals
    from config import LLM_PROVIDER, LLM_DEFAULT_MODEL

    t = today_totals() or {}
    calls = int(t.get("calls") or 0)
    ok = int(t.get("ok") or 0)
    cached = int(t.get("cached") or 0)
    errors = int(t.get("errors") or 0)
    attempted = max(calls - cached, 0)  # cache hits never fail
    return {
        "provider": LLM_PROVIDER,
        "model": LLM_DEFAULT_MODEL,
        "calls_today": calls,
        "ok_today": ok,
        "cached_today": cached,
        "errors_today": errors,
        "prompt_tokens_today": int(t.get("prompt_tokens") or 0),
        "completion_tokens_today": int(t.get("completion_tokens") or 0),
        "tokens_today": int(t.get("tokens") or 0),
        "success_rate_pct": round(100.0 * ok / attempted, 1) if attempted else 100.0,
    }


@app.get("/api/llm/observability/callers")
def get_llm_observability_callers():
    """Today's LLM usage broken down by feature (veto, sentiment, regime, ...)."""
    from llm.observability import today_by_caller

    rows = today_by_caller()
    total_tokens = sum(int(r.get("total_tokens") or 0) for r in rows) or 1
    return [
        {
            "caller": r.get("caller") or "(untagged)",
            "calls": int(r.get("calls") or 0),
            "ok": int(r.get("ok") or 0),
            "cached": int(r.get("cached") or 0),
            "errors": int(r.get("errors") or 0),
            "tokens": int(r.get("total_tokens") or 0),
            "avg_latency_ms": int(r.get("avg_latency_ms") or 0),
            "pct": round(100.0 * int(r.get("total_tokens") or 0) / total_tokens, 1),
        }
        for r in rows
    ]


@app.get("/api/llm/observability/models")
def get_llm_observability_models(days: int = 7):
    """Provider/model usage breakdown (calls, tokens, latency) for last N days."""
    from llm.observability import by_model

    return by_model(days=days)


@app.get("/api/llm/observability/daily")
def get_llm_observability_daily(days: int = 7):
    """Daily calls/tokens/errors for the trend chart (last N days)."""
    from llm.observability import daily_summary

    rows = daily_summary(days=days)
    out = []
    for r in rows:
        pt = int(r.get("prompt_tokens") or 0)
        ct = int(r.get("completion_tokens") or 0)
        out.append({
            "date": r.get("date"),
            "calls": int(r.get("calls") or 0),
            "ok": int(r.get("ok") or 0),
            "cached": int(r.get("cached") or 0),
            "errors": int(r.get("errors") or 0),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "tokens": pt + ct,
        })
    # Chronological order for the chart (daily_summary returns DESC)
    return sorted(out, key=lambda r: r["date"] or "")


@app.get("/api/llm/observability/calls")
def get_llm_observability_calls(limit: int = 100):
    """Most recent LLM calls with provider, model, tokens, latency and status."""
    from llm.observability import recent_calls

    return recent_calls(limit=min(max(limit, 1), 500))


# -------------------------------------------------------------
# POSITIONAL TRADING ENDPOINTS
# -------------------------------------------------------------
@app.get("/api/positional/status")
def get_positional_status():
    """Fetch positional strategy capital pool stats (Minervini VCP)."""
    try:
        # Separate capital pool, standard 1 Lakh
        from config import POSITIONAL_CAPITAL
        import config
        
        # Get active positions cash value and bot control params
        with get_conn() as conn:
            open_pos = conn.execute("SELECT * FROM pos_positions WHERE status = 'OPEN'").fetchall()
            closed_pnl_rows = conn.execute(
                "SELECT pnl FROM pos_positions WHERE status = 'CLOSED' AND pnl IS NOT NULL"
            ).fetchall()
            control_row = conn.execute("SELECT * FROM bot_control WHERE id = 1").fetchone()

        # Filter out NaN pnl rows defensively — a single corrupted close (e.g.
        # a failed swap that stored NaN exit_price/pnl) would otherwise poison
        # SUM(pnl) and propagate NaN through every downstream field, breaking
        # the response with "Out of range float values are not JSON compliant".
        import math
        net_realized = sum(
            float(r["pnl"]) for r in closed_pnl_rows
            if r["pnl"] is not None and math.isfinite(float(r["pnl"]))
        )
        active_holdings_cost = 0.0
        for p in open_pos:
            q = float(p["quantity"]) if p["quantity"] is not None else 0.0
            ep = float(p["entry_price"]) if p["entry_price"] is not None else 0.0
            if math.isfinite(q) and math.isfinite(ep):
                active_holdings_cost += q * ep
        
        # Current active cash pool
        current_cash = POSITIONAL_CAPITAL + net_realized - active_holdings_cost
        
        # Pull max holdings rules from universe scanner settings
        from config import POSITIONAL_MAX_POSITIONS
        
        llm_research_enabled = config.POSITIONAL_LLM_RESEARCH_ENABLED
        swap_enabled = config.POSITIONAL_SWAP_ENABLED
        
        if control_row:
            control_dict = dict(control_row)
            if "positional_llm_research_enabled" in control_dict:
                llm_research_enabled = bool(control_dict["positional_llm_research_enabled"])
            if "positional_swap_enabled" in control_dict:
                swap_enabled = bool(control_dict["positional_swap_enabled"])
        
        return {
            "initial_capital": POSITIONAL_CAPITAL,
            "cash_balance": round(current_cash, 2),
            "allocated_value": round(active_holdings_cost, 2),
            "net_realized_pnl": round(net_realized, 2),
            "total_valuation": round(current_cash + active_holdings_cost, 2),
            "max_positions": POSITIONAL_MAX_POSITIONS,
            "active_positions_count": len(open_pos),
            "available_slots": max(0, POSITIONAL_MAX_POSITIONS - len(open_pos)),
            "llm_research_enabled": llm_research_enabled,
            "swap_enabled": swap_enabled
        }
    except Exception as e:
        log.error("Error in get_positional_status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/positional/control")
def control_positional(input_data: PositionalControlInput):
    """Enable/disable LLM VCP research or opportunity swaps dynamically."""
    try:
        with get_conn() as conn:
            conn.execute(
                """UPDATE bot_control
                      SET positional_llm_research_enabled = ?,
                          positional_swap_enabled = ?,
                          updated_at = ?
                    WHERE id = 1""",
                (
                    1 if input_data.llm_research_enabled else 0,
                    1 if input_data.swap_enabled else 0,
                    datetime.utcnow().isoformat()
                )
            )
        return {"success": True, "message": "Positional strategy parameters updated successfully"}
    except Exception as e:
        log.error("Error in control_positional: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/positional/regime")
def get_positional_regime():
    """Retrieve EOD computed market macro state and portfolio size multipliers."""
    try:
        regime = get_latest_regime()
        return {
            "computed_at": to_ist_str(regime.get("computed_at")),
            "nifty_roc_18m": regime.get("nifty_roc_18m"),
            "smallcap_roc_20m": regime.get("smallcap_roc_20m"),
            "nifty_gold_ratio": regime.get("nifty_gold_ratio"),
            "flag": regime.get("flag", "NEUTRAL"),
            "size_multiplier": regime.get("size_multiplier", 0.70),
            "notes": regime.get("notes", "")
        }
    except Exception as e:
        log.error("Error in get_positional_regime: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def run_regime_check_task():
    try:
        log.info("Starting background manual regime check...")
        run_regime_check()
        log.info("Background manual regime check completed.")
    except Exception as e:
        log.error("Error in background regime check: %s", e)

@app.post("/api/positional/regime/run")
def trigger_regime_check(background_tasks: BackgroundTasks):
    """Manually recompute the monthly macro market regime in the background."""
    try:
        background_tasks.add_task(run_regime_check_task)
        return {"success": True, "message": "Market regime recomputation triggered in background"}
    except Exception as e:
        log.error("Error triggering regime check: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def merge_and_process_screener_csvs(file_a: bytes, file_b: bytes) -> dict:
    try:
        df_a = pd.read_csv(io.BytesIO(file_a))
    except Exception as e:
        return {"total_rows": 0, "passed": 0, "failed": 0, "financial_count": 0,
                "tickers": [], "errors": [f"Query A parsing failed: {e}"]}
    
    try:
        df_b = pd.read_csv(io.BytesIO(file_b))
    except Exception as e:
        return {"total_rows": 0, "passed": 0, "failed": 0, "financial_count": 0,
                "tickers": [], "errors": [f"Query B parsing failed: {e}"]}

    df_combined = pd.concat([df_a, df_b], ignore_index=True)
    
    # Identify the ticker column and drop duplicates
    cols = list(df_combined.columns)
    col_ticker = _find_col(cols, _COL_MAP["ticker"])
    if col_ticker:
        # Clean and uppercase ticker series for robust deduplication
        tickers_cleaned = df_combined[col_ticker].astype(str).str.strip().str.upper()
        df_combined = df_combined.loc[tickers_cleaned.drop_duplicates().index]
    
    out_buf = io.StringIO()
    df_combined.to_csv(out_buf, index=False)
    csv_str = out_buf.getvalue()
    
    return process_screener_csv(csv_str, filename="merged_screener_uploader.csv")

@app.post("/api/positional/universe/upload")
async def upload_positional_universe(
    query_a: Optional[UploadFile] = File(None),
    query_b: Optional[UploadFile] = File(None),
    single_query: Optional[UploadFile] = File(None)
):
    """
    Accept query_a (non-financials) and query_b (banks & NBFCs) simultaneously,
    combines and deduplicates symbols programmatically on the backend, 
    and updates EOD Whitelist table.
    """
    try:
        if single_query:
            content = await single_query.read()
            result = process_screener_csv(content, filename=single_query.filename)
            return {"success": True, "result": result}
        
        if not query_a or not query_b:
            raise HTTPException(
                status_code=400,
                detail="Provide both 'query_a' (non-financials) and 'query_b' (banks/NBFCs) OR upload 'single_query'"
            )
            
        content_a = await query_a.read()
        content_b = await query_b.read()
        
        result = merge_and_process_screener_csvs(content_a, content_b)
        return {"success": True, "result": result}
        
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error uploading universe CSVs: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/positional/scan-results")
def get_positional_scan_results():
    """Retrieve EOD Scan results (VCP/Minervini buy setups) from database."""
    try:
        df = query_df("SELECT * FROM pos_scans ORDER BY scanned_at DESC, score DESC LIMIT 100")
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            results.append({
                "id": int(r["id"]),
                "scanned_at": to_ist_str(r["scanned_at"]),
                "ticker": r["ticker"],
                "price": clean_float(r["price"], round_digits=2),
                "trend_template": bool(r["trend_template"]),
                "vcp_detected": bool(r["vcp_detected"]),
                "vcp_strength": clean_float(r["vcp_strength"], round_digits=2),
                "proximity_52w_pct": clean_float(r["proximity_52w_pct"], round_digits=2),
                "ema21": clean_float(r["ema21"], round_digits=2),
                "ema50": clean_float(r["ema50"], round_digits=2),
                "ema200": clean_float(r["ema200"], round_digits=2),
                "atr_pct": clean_float(r["atr_pct"], round_digits=2),
                "score": clean_float(r["score"]),
                "alert_type": r["alert_type"],
                "reason": clean_str(r["reason"]),
                # Confluence scorecard (NULL on pre-migration rows)
                "composite_score": clean_float(r.get("composite_score")),
                "confluence": int(clean_float(r.get("confluence")) or 0),
                "strategies_fired": clean_str(r.get("strategies_fired"), default=""),
                "horizon": clean_str(r.get("horizon"), default=""),
                "conviction": clean_str(r.get("conviction"), default=""),
                "timing_score": clean_float(r.get("timing_score")),
                "durability_score": clean_float(r.get("durability_score")),
                "quality_pillar": clean_float(r.get("quality_pillar")),
                "valuation_pillar": clean_float(r.get("valuation_pillar")),
                "momentum_pillar": clean_float(r.get("momentum_pillar")),
                "sentiment_pillar": clean_float(r.get("sentiment_pillar")),
                "management_pillar": clean_float(r.get("management_pillar")),
                "est_hold_days": int(clean_float(r.get("est_hold_days")) or 0),
            })
        return results
    except Exception as e:
        log.error("Error in get_positional_scan_results: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/positional/research")
def get_positional_research():
    """Latest management-outlook research (concall thesis) per ticker."""
    try:
        df = query_df("SELECT * FROM pos_research ORDER BY researched_at DESC LIMIT 100")
        if df.empty:
            return []
        results = []
        for _, r in df.iterrows():
            def _json_list(v):
                try:
                    return json.loads(v) if v else []
                except Exception:
                    return []
            results.append({
                "ticker": r["ticker"],
                "researched_at": to_ist_str(r["researched_at"]),
                "concall_date": clean_str(r.get("concall_date"), default=""),
                "management_score": clean_float(r.get("management_score")),
                "verdict": clean_str(r.get("verdict"), default=""),
                "outlook": clean_str(r.get("outlook"), default=""),
                "thesis": clean_str(r.get("thesis"), default=""),
                "key_positives": _json_list(r.get("key_positives")),
                "key_risks": _json_list(r.get("key_risks")),
                "guidance": clean_str(r.get("guidance"), default=""),
                "recommendation": clean_str(r.get("recommendation"), default=""),
                "recommendation_rationale": clean_str(r.get("recommendation_rationale"), default=""),
                "concall_summary": clean_str(r.get("concall_summary"), default=""),
                "fundamentals_summary": clean_str(r.get("fundamentals_summary"), default=""),
                "sources": _json_list(r.get("sources")),
                "confidence": clean_float(r.get("confidence")),
                "guidance_credibility": clean_float(r.get("guidance_credibility")),
            })
        return results
    except Exception as e:
        log.error("Error in get_positional_research: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/positional/positions")
def get_positional_positions():
    """Fetch currently active swing holdings and technical stop loss levels (21 EMA tracker)."""
    try:
        df = query_df("""
            SELECT p.*, t.reason AS trade_reason
            FROM pos_positions p
            LEFT JOIN pos_trades t ON p.id = t.position_id AND t.side = 'BUY'
            WHERE p.status = 'OPEN'
            ORDER BY p.entry_date DESC
        """)
        if df.empty:
            return []
        
        results = []
        for idx, r in df.iterrows():
            ticker = r["ticker"]
            entry_px = float(r["entry_price"])
            qty = int(r["quantity"])
            
            # Fetch latest price
            try:
                px = latest_price(ticker)
            except Exception:
                px = entry_px
            if px is None:
                px = entry_px
                
            pnl = (px - entry_px) * qty
            pnl_pct = (px / entry_px - 1) * 100 if entry_px else 0.0
            
            trade_reason = r["trade_reason"] if "trade_reason" in r and pd.notna(r["trade_reason"]) else ""
            strategy = "MINERVINI_VCP"
            if "[FUN_TECH_MOMENTUM]" in trade_reason:
                strategy = "FUN_TECH_MOMENTUM"
            elif "[BRAHMA_VISHNU_MAHESH]" in trade_reason:
                strategy = "BRAHMA_VISHNU_MAHESH"
            elif "[YOUNG_MOMENTUM]" in trade_reason:
                strategy = "YOUNG_MOMENTUM"
            
            results.append({
                "id": int(r["id"]),
                "ticker": ticker,
                "entry_date": to_ist_str(r["entry_date"]),
                "entry_price": round(entry_px, 2),
                "current_price": round(float(px), 2),
                "quantity": qty,
                "hard_stop": round(float(r["hard_stop"]), 2),
                "ema_trail_stop": round(float(r["ema_trail_stop"]), 2) if pd.notna(r["ema_trail_stop"]) else None,
                "target_price": round(float(r["target_price"]), 2) if pd.notna(r["target_price"]) else None,
                "peak_price": round(float(r["peak_price"]), 2) if pd.notna(r["peak_price"]) else None,
                "below_ema_consecutive": int(r["below_ema_consecutive"]),
                "days_held": int(r["days_held"]),
                "regime_at_entry": r["regime_at_entry"],
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl_pct, 2),
                "strategy": strategy,
                # Conviction-engine fields (NULL on pre-migration rows)
                "partial_taken": int(r["partial_taken"]) if "partial_taken" in r and pd.notna(r["partial_taken"]) else 0,
                "initial_quantity": int(r["initial_quantity"]) if "initial_quantity" in r and pd.notna(r["initial_quantity"]) else None,
                "time_stop_days": int(r["time_stop_days"]) if "time_stop_days" in r and pd.notna(r["time_stop_days"]) else None,
                "notes": r["notes"] or "—"
            })
        return results
    except Exception as e:
        log.error("Error in get_positional_positions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def run_exit_checks_task(force: bool = True):
    try:
        log.info("Starting background EOD exit checks and scan [force=%s]...", force)
        run_eod_scan(force=force)
        log.info("Background EOD exit checks and scan completed.")
    except Exception as e:
        log.error("Error in background EOD exit checks and scan: %s", e)

@app.post("/api/positional/exit-check")
def trigger_positional_exit_check(background_tasks: BackgroundTasks, force: bool = Query(True)):
    """Run EOD exit check and scan loop manually in a background task."""
    try:
        background_tasks.add_task(run_exit_checks_task, force)
        return {"success": True, "message": "EOD exit check and scan triggered in background"}
    except Exception as e:
        log.error("Error triggering exit check: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def run_eod_scan_task(force: bool = True):
    try:
        log.info("Starting background manual positional EOD scan [force=%s]...", force)
        run_eod_scan(force=force)
        log.info("Background manual positional EOD scan completed.")
    except Exception as e:
        log.error("Error in background manual positional EOD scan: %s", e)

@app.post("/api/positional/scan")
def trigger_positional_scan(background_tasks: BackgroundTasks, force: bool = Query(True)):
    """Run EOD sweep scan loop manually in a background task."""
    try:
        background_tasks.add_task(run_eod_scan_task, force)
        return {"success": True, "message": "EOD positional scan triggered in background"}
    except Exception as e:
        log.error("Error triggering positional scan: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

def run_research_refresh_task(force: bool = False):
    try:
        log.info("Starting background management-research refresh (force=%s)...", force)
        from positional.research import refresh_management_research
        result = refresh_management_research(force=force)
        log.info("Research refresh completed: %s", result)
    except Exception as e:
        log.error("Error in background research refresh: %s", e)

@app.post("/api/positional/research/refresh")
def trigger_research_refresh(background_tasks: BackgroundTasks, force: bool = Query(False)):
    """Manually run the decoupled management-research refresh (holdings + watchlist
    + recent shortlist) in the background — picks up new quarterly concalls.
    ``force=true`` bypasses the analyst cache and re-summarises every stock with
    the current prompts/logic."""
    try:
        background_tasks.add_task(run_research_refresh_task, force)
        msg = ("Full re-research (cache bypassed) triggered in background" if force
               else "Management-research refresh triggered in background")
        return {"success": True, "message": msg}
    except Exception as e:
        log.error("Error triggering research refresh: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/positional/research/ticker/{ticker}")
def trigger_single_ticker_research(ticker: str, force: bool = Query(True)):
    """Run the LLM analyst pipeline for ONE ticker on demand — refreshes concall
    summary, management guidance, recommendation, thesis and key positives/risks
    for that stock only. Runs synchronously so the caller can show fresh data on
    completion; expect 30-180s per call when using a local LLM."""
    bare = ticker.replace(".NS", "").replace(".BO", "").strip().upper()
    if not bare:
        raise HTTPException(status_code=400, detail="Ticker is required")
    try:
        from positional.research import research_single_ticker
        from positional.runner import _fetch_india_vix
        try:
            vix = _fetch_india_vix()
        except Exception:
            vix = 15.0
        res = research_single_ticker(bare, vix_value=vix, force=force)
        if res is None:
            return {
                "success": False,
                "ticker": bare,
                "message": ("No management material available for this ticker "
                            "(Screener concall/presentation missing), LLM research "
                            "disabled, or analyst failed open."),
            }
        return {
            "success": True,
            "ticker": bare,
            "research": res,
            "message": f"LLM research refreshed for {bare}.",
        }
    except Exception as e:
        log.error("Error in single-ticker research for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/positional/analytics")
def get_positional_analytics():
    """Retrieve closed positional metrics breakdown (avg winner/win rate)."""
    try:
        df = query_df("SELECT * FROM pos_positions WHERE status = 'CLOSED'")
        if df.empty:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_winner": 0.0,
                "avg_loser": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0
            }
            
        pnl = df["pnl"].astype(float)
        wins = df[pnl > 0]
        losses = df[pnl <= 0]
        
        win_rate = len(wins) / len(df) if len(df) else 0.0
        avg_win = wins["pnl"].mean() if len(wins) else 0.0
        avg_loss = losses["pnl"].mean() if len(losses) else 0.0
        total_pnl = pnl.sum()
        
        pf = (wins["pnl"].sum() / abs(losses["pnl"].sum())) if len(losses) and losses["pnl"].sum() != 0 else float("inf")
        
        return {
            "total_trades": len(df),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate * 100, 2),
            "avg_winner": round(float(avg_win), 2),
            "avg_loser": round(float(avg_loss), 2),
            "total_pnl": round(float(total_pnl), 2),
            "profit_factor": round(float(pf), 2) if pf != float("inf") else "∞"
        }
    except Exception as e:
        log.error("Error in get_positional_analytics: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/positional/alerts/test")
def test_telegram_connection():
    """Trigger connection test check alert on Telegram integration."""
    try:
        from positional.alerts import test_connection
        success = test_connection()
        return {"success": success, "message": "Telegram connection test trigger succeeded" if success else "Telegram notification error"}
    except Exception as e:
        log.error("Error testing Telegram alert connection: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------------------------------------
# ALERTS & INSIGHTS ENDPOINTS — LLM news-impact + sector linkage
# -------------------------------------------------------------
def _run_news_impact_task(force: bool, scope: str):
    """BackgroundTask wrapper for /api/alerts/run. Mirrors run_research_refresh_task."""
    try:
        from news_impact.pipeline import run_for_all
        result = run_for_all(force=bool(force), triggered_by="manual_api")
        log.info("[api] /api/alerts/run completed: %s", result)
    except Exception as e:
        log.error("[api] /api/alerts/run failed: %s", e)


@app.get("/api/alerts/feed")
def alerts_feed(
    severity: Optional[str] = Query(None),  # CSV: critical,watch,info
    scope: str = Query("BOTH"),             # HOLDING | LT_WATCH | BOTH
    ticker: Optional[str] = Query(None),
    hours: int = Query(72),
    limit: int = Query(100),
):
    """Filtered feed of news-impact alerts."""
    try:
        from news_impact.store import feed_query
        sev_list = None
        if severity:
            sev_list = [s.strip().lower() for s in severity.split(",") if s.strip()]
        alerts = feed_query(severity=sev_list, scope=scope, ticker=ticker,
                            hours=int(hours), limit=int(limit))
        # IST-format the created_at + citation timestamps for the UI.
        for a in alerts:
            a["created_at_ist"] = to_ist_str(a.get("created_at"))
            for c in (a.get("citations") or []):
                c["ts_ist"] = to_ist_str(c.get("ts"))
        return alerts
    except Exception as e:
        log.error("Error in alerts_feed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/alerts/badges")
def alerts_badges(hours: int = Query(72)):
    """Map of ticker -> open alert count, for sidebar + table badges."""
    try:
        from news_impact.store import badges_query
        return badges_query(hours=int(hours))
    except Exception as e:
        log.error("Error in alerts_badges: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/alerts/{alert_id}")
def alert_detail(alert_id: int):
    """Full single alert by id."""
    try:
        from news_impact.store import fetch_alert
        a = fetch_alert(alert_id)
        if a is None:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
        a["created_at_ist"] = to_ist_str(a.get("created_at"))
        for c in (a.get("citations") or []):
            c["ts_ist"] = to_ist_str(c.get("ts"))
        return a
    except HTTPException:
        raise
    except Exception as e:
        log.error("Error in alert_detail: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class AlertsRunInput(BaseModel):
    force: Optional[bool] = True
    scope: Optional[str] = "BOTH"


@app.post("/api/alerts/run")
def alerts_run(background_tasks: BackgroundTasks, body: Optional[AlertsRunInput] = None):
    """Manually trigger the news-impact LLM pass. Returns immediately; the
    heavy work runs in a background task."""
    try:
        force = True if (body is None or body.force is None) else bool(body.force)
        scope = "BOTH" if body is None or not body.scope else body.scope
        background_tasks.add_task(_run_news_impact_task, force, scope)
        return {"success": True, "message": "Analysis triggered in background"}
    except Exception as e:
        log.error("Error in alerts_run: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------
# ENGINE ROOM — guidance ledger, outcomes, calibration, calendars,
# hygiene, universe sync (conviction-engine surfaces)
# -------------------------------------------------------------

@app.get("/api/engine/guidance")
def engine_guidance(ticker: Optional[str] = None, limit: int = 200):
    """Guidance ledger rows (newest first) + per-ticker credibility scores."""
    try:
        with get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    """SELECT * FROM guidance_ledger WHERE ticker = ?
                       ORDER BY id DESC LIMIT ?""",
                    (ticker.upper(), min(limit, 500)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM guidance_ledger ORDER BY id DESC LIMIT ?",
                    (min(limit, 500),),
                ).fetchall()
            creds = conn.execute(
                """SELECT ticker, guidance_credibility FROM pos_research
                   WHERE guidance_credibility IS NOT NULL"""
            ).fetchall()
        return {
            "rows": [dict(r) for r in rows],
            "credibility": {r["ticker"]: r["guidance_credibility"] for r in creds},
        }
    except Exception as e:
        log.error("Error in engine_guidance: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/engine/outcomes/summary")
def engine_outcomes_summary():
    """Hit-rates and average forward returns per signal type."""
    try:
        from analytics.outcomes import outcome_summary
        with get_conn() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM signal_outcomes WHERE fwd_ret_60d IS NULL"
            ).fetchone()["n"]
            total = conn.execute("SELECT COUNT(*) AS n FROM signal_outcomes").fetchone()["n"]
        return {"summary": outcome_summary(), "total": int(total or 0),
                "incomplete": int(pending or 0)}
    except Exception as e:
        log.error("Error in engine_outcomes_summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/engine/outcomes")
def engine_outcomes(signal_type: Optional[str] = None, limit: int = 100):
    """Recent outcome rows, optionally filtered by signal type."""
    try:
        with get_conn() as conn:
            if signal_type:
                rows = conn.execute(
                    """SELECT * FROM signal_outcomes WHERE signal_type = ?
                       ORDER BY signal_ts DESC LIMIT ?""",
                    (signal_type, min(limit, 500)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM signal_outcomes ORDER BY signal_ts DESC LIMIT ?",
                    (min(limit, 500),),
                ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error("Error in engine_outcomes: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/engine/outcomes/run")
def engine_outcomes_run(background_tasks: BackgroundTasks):
    """Trigger an incremental forward-return computation pass."""
    def _task():
        try:
            from analytics.outcomes import compute_outcomes
            compute_outcomes()
        except Exception as e:
            log.error("outcomes run failed: %s", e)
    background_tasks.add_task(_task)
    return {"success": True, "message": "Outcome computation started in background"}


@app.get("/api/engine/calibration")
def engine_calibration():
    """Advisory calibration report (never auto-applied)."""
    try:
        from analytics.calibration import calibration_report
        return calibration_report()
    except Exception as e:
        log.error("Error in engine_calibration: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/engine/events")
def engine_events(days: int = 14, ticker: Optional[str] = None):
    """Upcoming NSE corporate events from the deterministic calendar."""
    try:
        from datetime import date as _date, timedelta as _td
        today = _date.today().isoformat()
        until = (_date.today() + _td(days=min(days, 60))).isoformat()
        with get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    """SELECT * FROM event_calendar
                       WHERE ticker=? AND event_date >= ? AND event_date <= ?
                       ORDER BY event_date""",
                    (ticker.upper().split(".")[0], today, until),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM event_calendar
                       WHERE event_date >= ? AND event_date <= ?
                       ORDER BY event_date LIMIT 500""",
                    (today, until),
                ).fetchall()
            last = conn.execute(
                "SELECT MAX(fetched_at) AS m FROM event_calendar"
            ).fetchone()["m"]
        return {"rows": [dict(r) for r in rows], "last_refreshed": last}
    except Exception as e:
        log.error("Error in engine_events: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/engine/events/refresh")
def engine_events_refresh(background_tasks: BackgroundTasks):
    """Force-refresh the NSE event calendar in the background."""
    def _task():
        try:
            from data.nse_calendar import refresh_event_calendar
            refresh_event_calendar(force=True)
        except Exception as e:
            log.error("event calendar refresh failed: %s", e)
    background_tasks.add_task(_task)
    return {"success": True, "message": "Event calendar refresh started"}


@app.get("/api/engine/surveillance")
def engine_surveillance():
    """Current ASM/GSM surveillance entries."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM surveillance_list ORDER BY list_type, ticker"
            ).fetchall()
            last = conn.execute(
                "SELECT MAX(fetched_at) AS m FROM surveillance_list"
            ).fetchone()["m"]
        return {"rows": [dict(r) for r in rows], "last_refreshed": last}
    except Exception as e:
        log.error("Error in engine_surveillance: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/engine/surveillance/refresh")
def engine_surveillance_refresh(background_tasks: BackgroundTasks):
    def _task():
        try:
            from data.hygiene import refresh_surveillance_lists
            refresh_surveillance_lists(force=True)
        except Exception as e:
            log.error("surveillance refresh failed: %s", e)
    background_tasks.add_task(_task)
    return {"success": True, "message": "Surveillance list refresh started"}


@app.get("/api/engine/hygiene/{ticker}")
def engine_hygiene(ticker: str, check_liquidity: bool = True, book: str = "swing"):
    """Stage-0 gate check for one ticker against a book's floors
    (surveillance + tiered liquidity + microcap integrity + events + IPO)."""
    try:
        from data.hygiene import hygiene_check, market_cap_cr
        from data.nse_calendar import upcoming_events
        from config import POSITIONAL_EVENT_GUARD_DAYS
        from positional.ipo import listing_date, is_ipo_track
        hc = hygiene_check(ticker, check_liquidity=check_liquidity, book=book)
        return {
            "ticker": ticker.upper(),
            "book": book,
            **hc,
            "market_cap_cr": market_cap_cr(ticker),
            "listing_date": listing_date(ticker),
            "ipo_track": is_ipo_track(ticker),
            "upcoming_events": upcoming_events(ticker, days=POSITIONAL_EVENT_GUARD_DAYS + 7),
        }
    except Exception as e:
        log.error("Error in engine_hygiene: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/universe/summary")
def universe_summary():
    """The funnel in numbers: NSE master -> mcap floor -> swing-eligible ->
    IPO track, plus the intraday pool. One place to see where stocks fall out."""
    try:
        from data.universe import load_equity_master, recent_ipos, load_universe
        from config import (UNIVERSE_SOURCE, UNIVERSE_MIN_MARKET_CAP_CR,
                            IPO_TRACK_MONTHS, MICROCAP_MCAP_THRESHOLD_CR)
        master = load_equity_master()
        ipos = recent_ipos()
        with get_conn() as conn:
            lt_total = conn.execute("SELECT COUNT(*) AS n FROM lt_universe").fetchone()["n"]
            lt_pass = conn.execute(
                "SELECT COUNT(*) AS n FROM lt_universe WHERE in_universe=1").fetchone()["n"]
            pos_total = conn.execute("SELECT COUNT(*) AS n FROM pos_universe").fetchone()["n"]
            pos_active = conn.execute(
                "SELECT COUNT(*) AS n FROM pos_universe WHERE in_universe=1").fetchone()["n"]
            pos_micro = conn.execute(
                "SELECT COUNT(*) AS n FROM pos_universe WHERE in_universe=1 AND market_cap IS NOT NULL AND market_cap < ?",
                (MICROCAP_MCAP_THRESHOLD_CR,)).fetchone()["n"]
            pos_ipo = conn.execute(
                "SELECT COUNT(*) AS n FROM pos_universe WHERE in_universe=1 AND listing_date >= ?",
                ((datetime.now(timezone.utc).date() - timedelta(days=IPO_TRACK_MONTHS * 30)).isoformat(),)
            ).fetchone()["n"]
            surveillance = conn.execute(
                "SELECT COUNT(DISTINCT ticker) AS n FROM surveillance_list").fetchone()["n"]
        return {
            "source": UNIVERSE_SOURCE,
            "mcap_floor_cr": UNIVERSE_MIN_MARKET_CAP_CR,
            "nse_master_eq": len(master),
            "recent_ipos": len(ipos),
            "intraday_pool": len(load_universe()),
            "lt_pipeline_scanned": int(lt_total or 0),
            "lt_pipeline_passed": int(lt_pass or 0),
            "swing_total": int(pos_total or 0),
            "swing_eligible": int(pos_active or 0),
            "swing_microcaps": int(pos_micro or 0),
            "swing_ipo_track": int(pos_ipo or 0),
            "surveillance_blocked": int(surveillance or 0),
        }
    except Exception as e:
        log.error("Error in universe_summary: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/positional/universe/sync")
def positional_universe_sync(background_tasks: BackgroundTasks):
    """Sync the scraped lt_universe/lt_quality survivors into pos_universe
    (Phase 4 unified universe). Runs in the background."""
    def _task():
        try:
            from positional.universe_sync import sync_lt_to_pos_universe
            res = sync_lt_to_pos_universe()
            log.info("manual universe sync done: %s", res)
        except Exception as e:
            log.error("universe sync failed: %s", e)
    background_tasks.add_task(_task)
    return {"success": True, "message": "Universe sync started (lt_universe → pos_universe)"}


# -------------------------------------------------------------
# LONG-TERM BOOK ENDPOINTS (Phase 6)
# -------------------------------------------------------------

@app.get("/api/longterm/book/status")
def longterm_book_status():
    """LT book pool status + open position count + enable flag."""
    try:
        from config import LT_BOOK_ENABLED, LT_CAPITAL, LT_MAX_POSITIONS
        with get_conn() as conn:
            open_rows = conn.execute(
                "SELECT quantity, avg_entry_price, sector FROM lt_positions WHERE status='OPEN'"
            ).fetchall()
            realized = conn.execute(
                """SELECT COALESCE(SUM(pnl),0) AS p FROM lt_positions
                   WHERE status='CLOSED' AND pnl IS NOT NULL"""
            ).fetchone()["p"]
        invested = sum(float(r["avg_entry_price"] or 0) * int(r["quantity"] or 0)
                       for r in open_rows)
        return {
            "enabled": bool(LT_BOOK_ENABLED),
            "capital": LT_CAPITAL,
            "invested": round(invested, 2),
            "cash": round(LT_CAPITAL - invested, 2),
            "open_positions": len(open_rows),
            "max_positions": LT_MAX_POSITIONS,
            "net_realized_pnl": round(float(realized or 0), 2),
        }
    except Exception as e:
        log.error("Error in longterm_book_status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/longterm/book/positions")
def longterm_book_positions(status: Optional[str] = None):
    try:
        with get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM lt_positions WHERE status=? ORDER BY id DESC",
                    (status.upper(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM lt_positions ORDER BY status, id DESC"
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("status") == "OPEN" and d.get("avg_entry_price"):
                try:
                    from data.fetcher import latest_price
                    px = latest_price(d["ticker"])
                    if px:
                        d["current_price"] = round(float(px), 2)
                        d["unrealized_pnl"] = round(
                            (float(px) - float(d["avg_entry_price"])) * int(d["quantity"] or 0), 2)
                        d["unrealized_pnl_pct"] = round(
                            (float(px) / float(d["avg_entry_price"]) - 1) * 100, 2)
                except Exception:
                    pass
            out.append(d)
        return out
    except Exception as e:
        log.error("Error in longterm_book_positions: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/longterm/book/trades")
def longterm_book_trades(limit: int = 100):
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM lt_trades ORDER BY id DESC LIMIT ?",
                (min(limit, 500),),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error("Error in longterm_book_trades: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/longterm/book/run")
def longterm_book_run(background_tasks: BackgroundTasks):
    """Trigger a manual LT-book daily pass (no-op unless LT_BOOK_ENABLED)."""
    def _task():
        try:
            from longterm.book import run_longterm_book
            res = run_longterm_book()
            log.info("manual LT book pass: %s", res)
        except Exception as e:
            log.error("LT book pass failed: %s", e)
    background_tasks.add_task(_task)
    return {"success": True, "message": "LT book pass started"}


# -------------------------------------------------------------
# BACKTEST ENDPOINTS (Phase 5)
# -------------------------------------------------------------
# One job at a time, tracked in memory. Results survive until restart.

_BACKTEST_JOB: dict = {"state": "idle"}
_BACKTEST_LOCK = threading.Lock()


class BacktestInput(BaseModel):
    tickers: Optional[str] = None        # comma-separated; default = pos_universe
    years: int = 2
    min_trend_score: float = 60.0
    walk_forward: bool = False
    max_tickers: int = 25


def _run_backtest_job(params: dict) -> None:
    global _BACKTEST_JOB
    try:
        from backtest.engine import load_price_data, run_backtest, walk_forward, BTConfig
        from dataclasses import asdict

        if params["tickers"]:
            tickers = [t.strip().upper() for t in params["tickers"].split(",") if t.strip()]
        else:
            from positional.universe import get_fundamental_universe
            tickers = get_fundamental_universe()
        tickers = tickers[: params["max_tickers"]]
        if not tickers:
            _BACKTEST_JOB = {"state": "error",
                             "error": "No tickers — pass some or populate the universe first."}
            return

        _BACKTEST_JOB["progress"] = f"loading {len(tickers)} tickers"
        data = load_price_data(tickers, years=params["years"])
        if not data:
            _BACKTEST_JOB = {"state": "error", "error": "No price data could be loaded."}
            return

        _BACKTEST_JOB["progress"] = f"simulating {len(data)} tickers"
        if params["walk_forward"]:
            result = walk_forward(data)
            payload = {"mode": "walk_forward", **result}
        else:
            res = run_backtest(data, cfg=BTConfig(min_trend_score=params["min_trend_score"]))
            payload = {
                "mode": "single",
                "config": res.config,
                "start": res.start, "end": res.end, "n_days": res.n_days,
                "metrics": res.metrics,
                "equity_curve": res.equity_curve[-500:],
                "trades": [asdict(t) for t in res.trades][-200:],
            }
        _BACKTEST_JOB = {"state": "done", "params": params,
                         "finished_at": datetime.now(timezone.utc).isoformat(),
                         "result": payload}
    except Exception as e:
        log.error("backtest job failed: %s", e)
        _BACKTEST_JOB = {"state": "error", "error": str(e)}


@app.post("/api/backtest/run")
def backtest_run(body: Optional[BacktestInput] = None):
    """Start a backtest in a background thread (one at a time)."""
    global _BACKTEST_JOB
    body = body or BacktestInput()
    with _BACKTEST_LOCK:
        if _BACKTEST_JOB.get("state") == "running":
            return {"success": False, "message": "A backtest is already running."}
        params = {"tickers": body.tickers, "years": max(1, min(body.years, 5)),
                  "min_trend_score": body.min_trend_score,
                  "walk_forward": bool(body.walk_forward),
                  "max_tickers": max(1, min(body.max_tickers, 50))}
        _BACKTEST_JOB = {"state": "running", "params": params,
                         "started_at": datetime.now(timezone.utc).isoformat(),
                         "progress": "starting"}
        threading.Thread(target=_run_backtest_job, args=(params,), daemon=True).start()
    return {"success": True, "message": "Backtest started"}


@app.get("/api/backtest/status")
def backtest_status():
    """Current backtest job state; includes the result when done."""
    return _BACKTEST_JOB


# -------------------------------------------------------------
# FRONTEND STATIC ASSETS MOUNT
# -------------------------------------------------------------
FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists() and FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    log.info("React built UI successfully mounted and served from: %s", FRONTEND_DIST)
else:
    log.warning("React dist folder not found at %s. Running API in headless backend-only mode.", FRONTEND_DIST)

if __name__ == "__main__":
    import uvicorn
    # When executed directly, run uvicorn server
    uvicorn.run(app, host="127.0.0.1", port=8000)

