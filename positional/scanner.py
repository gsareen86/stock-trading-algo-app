"""
EOD Technical Scanner — Minervini Trend Template + VCP Detection.

Runs daily at 4:00 PM IST after market close. Scans every ticker in
the fundamental universe (pos_universe) for:

1. Minervini Trend Template (all 4 conditions must pass):
   a. Current price > 21-day EMA
   b. 21-day EMA > 50-day EMA
   c. 50-day EMA > 200-day EMA  (confirmed uptrend at all time-frames)
   d. Current price within 15% of 52-week high

2. VCP (Volatility Contraction Pattern) proxy:
   - Compute weekly ATR% (ATR / price × 100) for last 3 weeks
   - Each successive week's ATR% must be smaller than the previous
     (supply drying up, volatility contracting = base tightening)
   - On down-days, volume must be < 80% of 20-day average volume
     (confirming supply absorption)

Each ticker gets a composite score (0-100):
  50 pts max from Trend Template (10 each for EMA alignment, 10 for 52W proximity)
  50 pts max from VCP strength

Score ≥ 60 → BUY ALERT
Score 40-59 → WATCH (not alerted, recorded for tracking)
Score < 40 → skip

Results written to pos_scans table and returned as list of dicts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    IST,
    POSITIONAL_52W_PROXIMITY_PCT,
    POSITIONAL_VCP_ATR_PERIOD,
    POSITIONAL_VCP_CONTRACTION_RATIO,
    POSITIONAL_VCP_CONTRACTION_WEEKS,
    POSITIONAL_VCP_VOLUME_DRY_PCT,
    POSITIONAL_MIN_TREND_SCORE,
)

log = logging.getLogger(__name__)

_LOOKBACK_DAYS = 300   # ~14 months of daily data needed for 200-day EMA


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _compute_indicators(df: pd.DataFrame) -> Optional[dict]:
    """
    Compute all indicators needed for Trend Template + VCP.
    Returns dict of indicator values or None if data insufficient.
    """
    if df is None or len(df) < 220:
        return None

    close = df["Close"].astype(float)
    high  = df["High"].astype(float)
    low   = df["Low"].astype(float)
    vol   = df["Volume"].astype(float)

    ema21  = _ema(close, 21)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)

    price       = float(close.iloc[-1])
    ema21_val   = float(ema21.iloc[-1])
    ema50_val   = float(ema50.iloc[-1])
    ema200_val  = float(ema200.iloc[-1])

    # 52-week high (last 252 trading days)
    high_52w = float(high.tail(252).max())
    proximity_52w_pct = (high_52w - price) / high_52w * 100  # how far below 52W high

    # ATR (10-day) for VCP
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr10 = tr.ewm(span=POSITIONAL_VCP_ATR_PERIOD, adjust=False).mean()
    atr_pct = float(atr10.iloc[-1]) / price * 100 if price > 0 else 0.0

    # Weekly ATR% for VCP contraction check (last 3 weeks = 15 trading days)
    weekly_atr_pcts = []
    for i in range(POSITIONAL_VCP_CONTRACTION_WEEKS, 0, -1):
        start = -(i * 5)
        end   = -((i - 1) * 5) if i > 1 else None
        slice_close = close.iloc[start:end]
        slice_atr   = atr10.iloc[start:end]
        if len(slice_close) < 3 or len(slice_atr) < 3:
            continue
        slice_price = float(slice_close.mean())
        slice_atr_v = float(slice_atr.mean())
        weekly_atr_pcts.append(slice_atr_v / slice_price * 100 if slice_price > 0 else 0.0)

    # 20-day average volume
    avg_vol_20d = float(vol.tail(20).mean())

    # Down-day volume ratio for last 10 days
    ret = close.pct_change()
    last10_close = close.tail(10)
    last10_vol   = vol.tail(10)
    last10_ret   = ret.tail(10)
    down_day_vols = last10_vol[last10_ret < 0]
    down_day_vol_ratio = (
        float(down_day_vols.mean()) / avg_vol_20d
        if avg_vol_20d > 0 and len(down_day_vols) > 0 else 1.0
    )

    return {
        "price":             price,
        "ema21":             ema21_val,
        "ema50":             ema50_val,
        "ema200":            ema200_val,
        "high_52w":          high_52w,
        "proximity_52w_pct": proximity_52w_pct,
        "atr_pct":           atr_pct,
        "weekly_atr_pcts":   weekly_atr_pcts,
        "avg_vol_20d":       avg_vol_20d,
        "down_day_vol_ratio":down_day_vol_ratio,
        "ema21_series":      ema21,          # for trailing stop use
    }


def _score_trend_template(ind: dict) -> tuple[bool, float, str]:
    """
    Check Minervini Trend Template. Returns (passes, score_0_to_50, reason).
    Scoring:
      +15 if price > 21 EMA
      +15 if 21 EMA > 50 EMA
      +10 if 50 EMA > 200 EMA
      +10 if within 15% of 52W high (max score at <5%)
    """
    score = 0.0
    reasons = []

    p   = ind["price"]
    e21 = ind["ema21"]
    e50 = ind["ema50"]
    e200= ind["ema200"]
    prox= ind["proximity_52w_pct"]

    # Condition a: price > 21 EMA
    if p > e21:
        score += 15
        reasons.append(f"P>{e21:.0f}")
    else:
        reasons.append(f"P<EMA21({e21:.0f})")

    # Condition b: 21 EMA > 50 EMA
    if e21 > e50:
        score += 15
        reasons.append("EMA21>EMA50")
    else:
        reasons.append(f"EMA21({e21:.0f})<EMA50({e50:.0f})")

    # Condition c: 50 EMA > 200 EMA
    if e50 > e200:
        score += 10
        reasons.append("EMA50>EMA200")
    else:
        reasons.append(f"EMA50({e50:.0f})<EMA200({e200:.0f})")

    # Condition d: within 15% of 52W high (score degrades with distance)
    if prox <= POSITIONAL_52W_PROXIMITY_PCT:
        # Linear: 10 pts at prox=0, 0 pts at prox=15
        score += max(0, 10 * (1 - prox / POSITIONAL_52W_PROXIMITY_PCT))
        reasons.append(f"{prox:.1f}% below 52Wh")
    else:
        reasons.append(f"{prox:.1f}% below 52Wh (too far)")

    passes = (p > e21) and (e21 > e50) and (e50 > e200) and (prox <= POSITIONAL_52W_PROXIMITY_PCT)
    return passes, round(score, 1), " | ".join(reasons)


def _score_vcp(ind: dict) -> tuple[bool, float, str]:
    """
    Check VCP (Volatility Contraction Pattern). Returns (detected, score_0_to_50, reason).
    Scoring:
      +30 for ATR% contracting over last 3 weeks
      +20 for down-day volume below 80% of average
    """
    score = 0.0
    reasons = []

    weekly_atr = ind["weekly_atr_pcts"]
    down_vol_r = ind["down_day_vol_ratio"]

    # VCP contraction: each week ATR% < prev * contraction_ratio
    contracting = False
    if len(weekly_atr) >= POSITIONAL_VCP_CONTRACTION_WEEKS:
        contracting = all(
            weekly_atr[i] < weekly_atr[i - 1] * POSITIONAL_VCP_CONTRACTION_RATIO
            for i in range(1, len(weekly_atr))
        )
        if contracting:
            # Stronger if contraction is larger
            total_contraction = weekly_atr[0] / weekly_atr[-1] if weekly_atr[-1] > 0 else 1
            extra = min(10, (total_contraction - 1) * 10)
            score += 20 + extra
            reasons.append(f"VCP contracting ({weekly_atr[0]:.1f}→{weekly_atr[-1]:.1f}%ATR)")
        else:
            reasons.append(f"No VCP (ATR%: {[round(x,1) for x in weekly_atr]})")
    else:
        reasons.append("Insufficient weeks for VCP")

    # Volume dry-up on down days
    if down_vol_r < POSITIONAL_VCP_VOLUME_DRY_PCT:
        score += 20
        reasons.append(f"Vol dry-up on down days ({down_vol_r:.0%} of avg)")
    else:
        reasons.append(f"Down-day vol={down_vol_r:.0%} (no dry-up)")

    return contracting, round(min(score, 50.0), 1), " | ".join(reasons)


def scan_ticker(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    """
    Run Trend Template + VCP on a single ticker.
    Returns None if data insufficient.
    Returns scan result dict otherwise.
    """
    ind = _compute_indicators(df)
    if ind is None:
        log.debug("[scan] %s: insufficient data (need 220+ days)", ticker)
        return None

    trend_passes, trend_score, trend_reason = _score_trend_template(ind)
    vcp_detected, vcp_score, vcp_reason = _score_vcp(ind)

    composite = trend_score + vcp_score  # 0-100

    if composite >= POSITIONAL_MIN_TREND_SCORE and trend_passes:
        alert_type = "BUY"
    elif composite >= 40:
        alert_type = "WATCH"
    else:
        alert_type = "HOLD"

    reason = f"Trend: {trend_reason} || VCP: {vcp_reason}"

    return {
        "ticker":           ticker,
        "price":            round(ind["price"], 2),
        "trend_template":   int(trend_passes),
        "vcp_detected":     int(vcp_detected),
        "vcp_strength":     vcp_score,
        "proximity_52w_pct":round(ind["proximity_52w_pct"], 2),
        "ema21":            round(ind["ema21"], 2),
        "ema50":            round(ind["ema50"], 2),
        "ema200":           round(ind["ema200"], 2),
        "atr_pct":          round(ind["atr_pct"], 3),
        "score":            round(composite, 1),
        "alert_type":       alert_type,
        "reason":           reason[:400],
    }


def run_eod_scan(tickers: Optional[list[str]] = None) -> list[dict]:
    """
    Run the full EOD scan on the fundamental universe (or a provided list).
    Results are written to pos_scans and returned sorted by score desc.

    Returns list of scan result dicts (only BUY and WATCH alerts).
    """
    from positional.universe import get_fundamental_universe

    if tickers is None:
        tickers = get_fundamental_universe()

    if not tickers:
        log.warning("[scan] No tickers in fundamental universe. Upload Screener.in CSV first.")
        return []

    log.info("[scan] EOD scan starting — %d tickers from fundamental universe", len(tickers))

    scanned_at = datetime.now(IST).isoformat()
    results: list[dict] = []
    errors = 0

    try:
        import yfinance as yf
        tickers_yf = [t if t.endswith((".NS", ".BO")) else t + ".NS" for t in tickers]

        # Batch download for speed (yfinance group download)
        log.info("[scan] Downloading %d tickers (batch)...", len(tickers_yf))
        data = yf.download(
            tickers_yf,
            period="14mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        log.error("[scan] yfinance batch download failed: %s", e)
        return []

    for ticker in tickers_yf:
        try:
            # Extract ticker data from the multi-ticker download
            if len(tickers_yf) == 1:
                df = data
            elif ticker in data.columns.get_level_values(0):
                df = data[ticker].dropna(how="all")
            else:
                log.debug("[scan] %s: not in downloaded data", ticker)
                continue

            if df is None or df.empty or len(df) < 220:
                log.debug("[scan] %s: only %d rows — need 220+",
                          ticker, len(df) if df is not None else 0)
                continue

            result = scan_ticker(ticker, df)
            if result is None:
                continue

            # Skip HOLD — don't clutter the DB
            if result["alert_type"] == "HOLD":
                continue

            results.append(result)

            # Persist to DB
            try:
                from db.models import get_conn, insert_returning_id
                with get_conn() as conn:
                    insert_returning_id(
                        conn,
                        """INSERT INTO pos_scans
                           (scanned_at, ticker, price, trend_template, vcp_detected,
                            vcp_strength, proximity_52w_pct, ema21, ema50, ema200,
                            atr_pct, score, alert_type, reason)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (scanned_at, ticker,
                         result["price"], result["trend_template"], result["vcp_detected"],
                         result["vcp_strength"], result["proximity_52w_pct"],
                         result["ema21"], result["ema50"], result["ema200"],
                         result["atr_pct"], result["score"],
                         result["alert_type"], result["reason"]),
                    )
            except Exception as e:
                log.debug("[scan] DB write failed for %s: %s", ticker, e)

            log.info("[scan] %s score=%.0f alert=%s prox=%.1f%% VCP=%s",
                     ticker, result["score"], result["alert_type"],
                     result["proximity_52w_pct"], bool(result["vcp_detected"]))

        except Exception as e:
            log.warning("[scan] Error scanning %s: %s", ticker, e)
            errors += 1

    results.sort(key=lambda x: x["score"], reverse=True)
    buy_alerts = [r for r in results if r["alert_type"] == "BUY"]
    watch_alerts = [r for r in results if r["alert_type"] == "WATCH"]

    log.info("[scan] EOD scan complete: %d BUY alerts, %d WATCH, %d errors",
             len(buy_alerts), len(watch_alerts), errors)

    return results


def get_latest_scan_results(limit: int = 50) -> list[dict]:
    """Read the most recent scan results from DB for dashboard display."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            latest_date = conn.execute(
                "SELECT substr(MAX(scanned_at),1,10) AS d FROM pos_scans"
            ).fetchone()
            if not latest_date:
                return []
            scan_date = dict(latest_date)["d"]
            # If two scans ran on the same calendar date, GROUP BY ticker with
            # MAX(scanned_at) deduplicates to the most recent result per ticker.
            rows = conn.execute(
                """SELECT *, MAX(scanned_at) AS scanned_at
                   FROM pos_scans
                   WHERE substr(scanned_at,1,10) = ?
                   GROUP BY ticker
                   ORDER BY score DESC LIMIT ?""",
                (scan_date, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("[scan] get_latest_scan_results failed: %s", e)
        return []
