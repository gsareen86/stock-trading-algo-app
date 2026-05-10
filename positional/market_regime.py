"""
Market Regime Engine — Minervini-style macro filter.

Computes:
  - 18-month Rate of Change (ROC) for Nifty 50
  - 20-month Rate of Change (ROC) for Nifty Smallcap 250
  - Nifty / Gold ratio (GOLDBEES.NS as proxy)

Regime flags:
  DEFENSIVE  — ROC overheated (Nifty ROC > 45% or Smallcap ROC > 80%)
               Reduce position size to 30-40%. High crash risk.
  AGGRESSIVE — ROC near zero (market bottoming, risk-reward favourable)
               Full position size.
  NEUTRAL    — Everything in between. Standard position size.

Run monthly via the positional scheduler. Stores result in pos_market_regime
table. Dashboard reads latest row for the regime banner.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


def _fetch_monthly_close(ticker: str, months: int) -> Optional[list[float]]:
    """Fetch monthly closing prices via yfinance. Returns list oldest→newest."""
    try:
        import yfinance as yf

        # Use 5y to ensure enough bars — some NSE indices have limited monthly history
        df = yf.download(ticker, period="5y", interval="1mo",
                         progress=False, auto_adjust=True)

        if df is None or df.empty:
            # Fallback: daily data resampled to month-end closes
            log.debug("market_regime: monthly data empty for %s — trying daily+resample", ticker)
            df_d = yf.download(ticker, period="5y", interval="1d",
                               progress=False, auto_adjust=True)
            if df_d is None or df_d.empty:
                log.warning("market_regime: no data for %s", ticker)
                return None
            import pandas as pd
            close_daily = df_d["Close"].squeeze()
            df = close_daily.resample("ME").last().to_frame("Close")

        # yfinance >=0.2.x may return multi-level columns; squeeze to Series
        close_col = df["Close"]
        if hasattr(close_col, "squeeze"):
            close_col = close_col.squeeze()
        closes = close_col.dropna().tolist()

        # Need at least months+1 data points to compute ROC
        if len(closes) < months + 1:
            log.warning("market_regime: insufficient data for %s — got %d months, need %d",
                        ticker, len(closes), months + 1)
            return None
        log.debug("market_regime: %s — %d monthly closes fetched", ticker, len(closes))
        return [float(c) for c in closes]
    except Exception as e:
        log.warning("market_regime: fetch failed for %s: %s", ticker, e)
        return None


def _roc(closes: list[float], months: int) -> Optional[float]:
    """Rate of Change: (current - N months ago) / N months ago * 100."""
    if not closes or len(closes) < months + 1:
        return None
    current = closes[-1]
    past = closes[-(months + 1)]
    if past <= 0:
        return None
    return (current - past) / past * 100.0


def compute_market_regime() -> dict:
    """
    Compute current market regime. Returns a dict with all metrics and the flag.
    Also persists the result to pos_market_regime table.

    Returns:
        {
            "flag": "DEFENSIVE" | "NEUTRAL" | "AGGRESSIVE",
            "nifty_roc_18m": float | None,
            "smallcap_roc_20m": float | None,
            "nifty_gold_ratio": float | None,
            "size_multiplier": float,
            "notes": str,
            "computed_at": str,
        }
    """
    from config import (
        POSITIONAL_NIFTY_ROC_MONTHS,
        POSITIONAL_SMALLCAP_ROC_MONTHS,
        POSITIONAL_NIFTY_ROC_DEFENSIVE,
        POSITIONAL_SMALLCAP_ROC_DEFENSIVE,
        POSITIONAL_DEFENSIVE_SIZE_MULT,
        POSITIONAL_NIFTY_TICKER,
        POSITIONAL_SMALLCAP_TICKER,
        POSITIONAL_GOLD_TICKER,
    )

    log.info("[regime] fetching market data for regime computation...")

    nifty_closes    = _fetch_monthly_close(POSITIONAL_NIFTY_TICKER,    POSITIONAL_NIFTY_ROC_MONTHS)
    smallcap_closes = _fetch_monthly_close(POSITIONAL_SMALLCAP_TICKER,  POSITIONAL_SMALLCAP_ROC_MONTHS)
    gold_closes     = _fetch_monthly_close(POSITIONAL_GOLD_TICKER,      1)

    nifty_roc   = _roc(nifty_closes,    POSITIONAL_NIFTY_ROC_MONTHS)    if nifty_closes    else None
    sc_roc      = _roc(smallcap_closes, POSITIONAL_SMALLCAP_ROC_MONTHS) if smallcap_closes else None
    gold_ratio  = None
    if nifty_closes and gold_closes and gold_closes[-1] > 0:
        gold_ratio = round(nifty_closes[-1] / gold_closes[-1], 4)

    # Determine flag
    notes_parts = []
    if nifty_roc is not None:
        notes_parts.append(f"Nifty 18M ROC={nifty_roc:.1f}%")
    if sc_roc is not None:
        notes_parts.append(f"Smallcap 20M ROC={sc_roc:.1f}%")
    if gold_ratio is not None:
        notes_parts.append(f"Nifty/Gold={gold_ratio:.2f}")

    defensive = False
    aggressive = False

    if nifty_roc is not None and nifty_roc > POSITIONAL_NIFTY_ROC_DEFENSIVE:
        defensive = True
        notes_parts.append(f"DEFENSIVE: Nifty ROC>{POSITIONAL_NIFTY_ROC_DEFENSIVE}")
    if sc_roc is not None and sc_roc > POSITIONAL_SMALLCAP_ROC_DEFENSIVE:
        defensive = True
        notes_parts.append(f"DEFENSIVE: Smallcap ROC>{POSITIONAL_SMALLCAP_ROC_DEFENSIVE}")

    if not defensive:
        # Near-zero ROC → aggressive (bottoming market)
        nifty_near_zero   = nifty_roc  is not None and abs(nifty_roc) < 5
        sc_near_zero      = sc_roc     is not None and abs(sc_roc)    < 10
        if nifty_near_zero or sc_near_zero:
            aggressive = True

    if defensive:
        flag = "DEFENSIVE"
        size_mult = POSITIONAL_DEFENSIVE_SIZE_MULT
    elif aggressive:
        flag = "AGGRESSIVE"
        size_mult = 1.0
    else:
        flag = "NEUTRAL"
        size_mult = 0.70

    notes = " | ".join(notes_parts) if notes_parts else "Insufficient data"
    computed_at = datetime.now(timezone.utc).isoformat()

    log.info("[regime] flag=%s size_mult=%.2f | %s", flag, size_mult, notes)

    # Persist
    try:
        from db.models import get_conn
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO pos_market_regime
                   (computed_at, nifty_roc_18m, smallcap_roc_20m,
                    nifty_gold_ratio, flag, size_multiplier, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (computed_at,
                 round(nifty_roc, 2) if nifty_roc is not None else None,
                 round(sc_roc, 2)    if sc_roc    is not None else None,
                 gold_ratio, flag, size_mult, notes),
            )
    except Exception as e:
        log.warning("[regime] DB write failed (non-fatal): %s", e)

    return {
        "flag":             flag,
        "nifty_roc_18m":    round(nifty_roc, 2)  if nifty_roc  is not None else None,
        "smallcap_roc_20m": round(sc_roc, 2)      if sc_roc     is not None else None,
        "nifty_gold_ratio": gold_ratio,
        "size_multiplier":  size_mult,
        "notes":            notes,
        "computed_at":      computed_at,
    }


def get_latest_regime() -> dict:
    """Read the most recent regime row from DB. Returns defaults if empty."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM pos_market_regime
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        if row:
            return dict(row)
    except Exception as e:
        log.debug("[regime] get_latest_regime failed: %s", e)
    return {
        "flag": "NEUTRAL",
        "nifty_roc_18m": None,
        "smallcap_roc_20m": None,
        "nifty_gold_ratio": None,
        "size_multiplier": 0.70,
        "notes": "No regime data — run a scan first",
        "computed_at": None,
    }


def current_size_multiplier() -> float:
    """Quick helper: return the position-size multiplier from latest regime."""
    regime = get_latest_regime()
    return float(regime.get("size_multiplier") or 0.70)
