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
    if df is None:
        return None

    # Drop any row where any of Close, High, Low is NaN to avoid incomplete/empty rows
    df = df.dropna(subset=["Close", "High", "Low"])

    if len(df) < 220:
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
    
    if pd.isna(price) or pd.isna(high_52w) or high_52w <= 0:
        proximity_52w_pct = 0.0
    else:
        proximity_52w_pct = (high_52w - price) / high_52w * 100  # how far below 52W high

    # ATR (10-day) for VCP
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr10 = tr.ewm(span=POSITIONAL_VCP_ATR_PERIOD, adjust=False).mean()
    
    atr_val = float(atr10.iloc[-1])
    if pd.isna(atr_val) or pd.isna(price) or price <= 0:
        atr_pct = 0.0
    else:
        atr_pct = atr_val / price * 100

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
        
        if pd.isna(slice_price) or pd.isna(slice_atr_v) or slice_price <= 0:
            weekly_atr_pcts.append(0.0)
        else:
            weekly_atr_pcts.append(slice_atr_v / slice_price * 100)

    # 20-day average volume
    avg_vol_20d = float(vol.tail(20).mean())
    if pd.isna(avg_vol_20d):
        avg_vol_20d = 0.0

    # Down-day volume ratio for last 10 days
    ret = close.pct_change()
    last10_close = close.tail(10)
    last10_vol   = vol.tail(10)
    last10_ret   = ret.tail(10)
    down_day_vols = last10_vol[last10_ret < 0]
    
    mean_down_vol = float(down_day_vols.mean()) if len(down_day_vols) > 0 else 0.0
    if pd.isna(mean_down_vol) or pd.isna(avg_vol_20d) or avg_vol_20d <= 0:
        down_day_vol_ratio = 1.0
    else:
        down_day_vol_ratio = mean_down_vol / avg_vol_20d

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


def _minervini_to_signal(ticker: str, m: dict):
    """Wrap a Minervini scan_ticker() dict as a PositionalSignal for the scorer."""
    from positional.strategies.base import PositionalSignal
    action = "BUY" if m["alert_type"] == "BUY" else "HOLD"
    strong = bool(m["trend_template"]) and bool(m["vcp_detected"]) and m["score"] >= 80
    return PositionalSignal(
        ticker=ticker,
        action=action,
        strategy="minervini_vcp",
        score=float(m["score"]),
        price=float(m["price"]),
        reason=m["reason"],
        hold_days=18,
        conviction="high" if strong else "medium",
        meta={"trend_template": m["trend_template"], "vcp_detected": m["vcp_detected"]},
    )


def _basic_technicals(df: pd.DataFrame) -> dict:
    """Fallback technical fields when the Minervini scan returns None."""
    close = df["Close"].astype(float)
    price = float(close.iloc[-1])
    high_52w = float(df["High"].tail(252).max())
    prox = (high_52w - price) / high_52w * 100 if high_52w > 0 else 0.0
    ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(df) >= 200 else ema50
    atr_pct = (
        float(close.diff().abs().ewm(span=14, adjust=False).mean().iloc[-1]) / price * 100
        if len(df) > 15 and price else 0.0
    )
    return {
        "price": round(price, 2), "proximity_52w_pct": round(prox, 2),
        "ema21": round(ema21, 2), "ema50": round(ema50, 2),
        "ema200": round(ema200, 2), "atr_pct": round(atr_pct, 3),
        "trend_template": 0, "vcp_detected": 0, "vcp_strength": 0.0,
    }


def _scorecard_to_result(card, minervini: Optional[dict], df: pd.DataFrame) -> dict:
    """Flatten a Scorecard + backward-compatible technical fields into a row dict."""
    tech = minervini if minervini is not None else _basic_technicals(df)
    return {
        # backward-compatible technical fields (consumed by runner/research/API)
        "ticker":           card.ticker,
        "price":            card.price,
        "trend_template":   tech["trend_template"],
        "vcp_detected":     tech["vcp_detected"],
        "vcp_strength":     tech["vcp_strength"],
        "proximity_52w_pct":tech["proximity_52w_pct"],
        "ema21":            tech["ema21"],
        "ema50":            tech["ema50"],
        "ema200":           tech["ema200"],
        "atr_pct":          tech["atr_pct"],
        "score":            card.composite_score,   # composite drives entry threshold
        "alert_type":       card.action,
        "reason":           card.reason[:400],
        # confluence scorecard fields
        "composite_score":  card.composite_score,
        "confluence":       card.confluence,
        "strategies_fired": ",".join(card.strategies_fired),
        "horizon":          card.horizon,
        "conviction":       card.conviction,
        "timing_score":     card.timing_score,
        "durability_score": card.durability_score,
        "quality_pillar":   card.pillars.get("quality"),
        "valuation_pillar": card.pillars.get("valuation"),
        "momentum_pillar":  card.pillars.get("momentum"),
        "sentiment_pillar": card.pillars.get("sentiment"),
        "est_hold_days":    card.est_hold_days,
    }


def _get_ticker_quality_score(ticker: str) -> float:
    # Strip suffix if present
    tk = ticker.replace(".NS", "").replace(".BO", "").strip()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT total_score FROM lt_quality WHERE ticker = ?", (tk,)
            ).fetchone()
            if row and row["total_score"] is not None:
                return float(row["total_score"])
    except Exception:
        pass
    return 50.0


def _persist_scan_result(scanned_at: str, result: dict):
    try:
        from db.models import get_conn, insert_returning_id
        with get_conn() as conn:
            insert_returning_id(
                conn,
                """INSERT INTO pos_scans
                   (scanned_at, ticker, price, trend_template, vcp_detected,
                    vcp_strength, proximity_52w_pct, ema21, ema50, ema200,
                    atr_pct, score, alert_type, reason,
                    composite_score, confluence, strategies_fired, horizon,
                    conviction, timing_score, durability_score, quality_pillar,
                    valuation_pillar, momentum_pillar, sentiment_pillar, est_hold_days)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (scanned_at, result["ticker"],
                 result["price"], result["trend_template"], result["vcp_detected"],
                 result["vcp_strength"], result["proximity_52w_pct"],
                 result["ema21"], result["ema50"], result["ema200"],
                 result["atr_pct"], result["score"],
                 result["alert_type"], result["reason"],
                 result.get("composite_score"), result.get("confluence", 0),
                 result.get("strategies_fired"), result.get("horizon"),
                 result.get("conviction"), result.get("timing_score"),
                 result.get("durability_score"), result.get("quality_pillar"),
                 result.get("valuation_pillar"), result.get("momentum_pillar"),
                 result.get("sentiment_pillar"), result.get("est_hold_days")),
            )
    except Exception as e:
        log.debug("[scan] DB write failed for %s: %s", result["ticker"], e)


def run_eod_scan(tickers: Optional[list[str]] = None) -> list[dict]:
    """
    Run the full EOD scan on the fundamental universe (or a provided list).
    For each ticker it runs all four strategies (Minervini VCP, Brahma-Vishnu-Mahesh,
    Fundamental-Technical, Young Momentum) and folds their signals plus quality /
    valuation / momentum / sentiment pillars into ONE confluence scorecard with a
    horizon classification. Results are written to pos_scans, one row per ticker,
    sorted by composite score desc.

    Returns list of scan result dicts (only BUY and WATCH alerts).
    """
    from positional.universe import get_fundamental_universe
    from positional.scorer import build_scorecard
    from positional.strategies import all_positional_strategies
    from positional.pillars import (
        quality_pillar, valuation_pillar, relative_momentum_pillar,
        sentiment_pillar, nifty_returns,
    )

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

    # Context shared across the whole scan run.
    nifty_r3, nifty_r6 = nifty_returns()
    strategies = all_positional_strategies()   # BVM, FTM, YM (Minervini run separately)

    for ticker in tickers_yf:
        try:
            # Extract ticker data from the multi-ticker download
            if isinstance(data.columns, pd.MultiIndex) or hasattr(data.columns, "levels"):
                if ticker in data.columns.get_level_values(0):
                    df = data[ticker].dropna(how="all")
                elif ticker in data.columns.get_level_values(1):
                    df = data.xs(ticker, level=1, axis=1).dropna(how="all")
                else:
                    log.debug("[scan] %s: not in downloaded data", ticker)
                    continue
            else:
                df = data.dropna(how="all")

            if df is None or df.empty or len(df) < 220:
                log.debug("[scan] %s: only %d rows — need 220+",
                          ticker, len(df) if df is not None else 0)
                continue

            # Run all four strategies, collect their signals, fold into ONE scorecard.
            signals = []
            minervini = scan_ticker(ticker, df)
            if minervini is not None:
                signals.append(_minervini_to_signal(ticker, minervini))

            quality_score = _get_ticker_quality_score(ticker)
            for strategy in strategies:
                try:
                    sig = strategy.generate(ticker, df, quality_score=quality_score)
                    if sig is not None:
                        signals.append(sig)
                except Exception as strat_err:
                    log.warning("[scan] Strategy %s failed for %s: %s",
                                strategy.name, ticker, strat_err)

            if not signals:
                continue

            price = float(df["Close"].iloc[-1])
            card = build_scorecard(
                ticker, price, signals,
                quality=quality_pillar(ticker),
                valuation=valuation_pillar(ticker),
                momentum=relative_momentum_pillar(df, nifty_r3, nifty_r6),
                sentiment=sentiment_pillar(ticker),
                min_composite=POSITIONAL_MIN_TREND_SCORE,
            )
            if card.action == "HOLD":
                continue

            result = _scorecard_to_result(card, minervini, df)
            results.append(result)
            _persist_scan_result(scanned_at, result)
            log.info("[scan] %s composite=%.0f %s conf=%d fired=[%s] horizon=%s",
                     ticker, card.composite_score, card.action, card.confluence,
                     ",".join(card.strategies_fired), card.horizon)

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
            # Get the most recent scan date
            latest_date = conn.execute(
                "SELECT substr(scanned_at,1,10) AS d FROM pos_scans ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not latest_date:
                return []
            scan_date = dict(latest_date)["d"]
            rows = conn.execute(
                """SELECT * FROM pos_scans
                   WHERE id IN (
                       SELECT MAX(id) FROM pos_scans
                       WHERE substr(scanned_at,1,10) = ?
                       GROUP BY ticker
                   )
                   ORDER BY score DESC LIMIT ?""",
                (scan_date, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("[scan] get_latest_scan_results failed: %s", e)
        return []
