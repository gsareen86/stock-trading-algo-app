"""
IPO track — how recent listings enter the swing book safely.

A name listed less than IPO_TRACK_MONTHS ago can't satisfy the 220-day
trend template (no 200 DMA, no real 52-week high), so the standard scanner
silently drops it — which is exactly where the biggest CANSLIM-style
winners are born. This module gives young names their own path:

  1. Seasoning   — no entries during the first IPO_MIN_SEASONING_SESSIONS
                   sessions (price discovery + flipper supply).
  2. IPO base    — the O'Neil playbook: a ≥3-week consolidation with depth
                   under 25%, price above the 10/21 EMA, breakout above the
                   base high on ≥1.5× average volume.
  3. Lock-in calendar — anchor lock-ins expire at 30/90 days, promoter at
                   6/18 months. Deterministic supply events: entries are
                   blocked within IPO_LOCKIN_GUARD_DAYS of an expiry (rows
                   land in event_calendar like results dates do).

Names graduate to the mature track automatically once they have 220+
sessions of history — the standard scanner simply takes over.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


def _bare(ticker: str) -> str:
    return ticker.split(".")[0].strip().upper()


# ── Listing-date resolution ──────────────────────────────────────────────────

def listing_date(ticker: str) -> Optional[str]:
    """ISO listing date from pos_universe (synced) or the NSE equity master."""
    base = _bare(ticker)
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT listing_date FROM pos_universe WHERE ticker=? OR ticker=?",
                (base, base + ".NS"),
            ).fetchone()
        if row and row["listing_date"]:
            return str(row["listing_date"])
    except Exception:
        pass
    try:
        from data.universe import listing_dates
        return listing_dates().get(base)
    except Exception:
        return None


def is_ipo_track(ticker: str) -> bool:
    """Listed within the last IPO_TRACK_MONTHS?"""
    from config import IPO_TRACK_MONTHS
    d = listing_date(ticker)
    if not d:
        return False
    try:
        age = (date.today() - date.fromisoformat(d)).days
        return age <= IPO_TRACK_MONTHS * 30
    except ValueError:
        return False


# ── Lock-in calendar ─────────────────────────────────────────────────────────

def lockin_expiry_dates(listing_iso: str) -> list[str]:
    """Deterministic lock-in expiries from the listing date (SEBI: anchor
    30/90 days, promoter 6/18 months)."""
    from config import IPO_LOCKIN_OFFSETS_DAYS
    try:
        listed = date.fromisoformat(listing_iso)
    except (ValueError, TypeError):
        return []
    return [(listed + timedelta(days=off)).isoformat()
            for off in IPO_LOCKIN_OFFSETS_DAYS]


def sync_lockin_events() -> int:
    """Insert upcoming lock-in expiries for IPO-track names into
    event_calendar (event_type='ipo_lockin_expiry'). Returns new rows."""
    try:
        from data.universe import recent_ipos
        from db.models import get_conn
    except Exception:
        return 0

    today = date.today().isoformat()
    horizon = (date.today() + timedelta(days=120)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    inserted = 0
    try:
        ipos = recent_ipos(months=19)  # cover the 18-month promoter expiry too
    except Exception:
        return 0
    try:
        with get_conn() as conn:
            for r in ipos:
                for d in lockin_expiry_dates(r.get("listing_date") or ""):
                    if today <= d <= horizon:
                        cur = conn.execute(
                            """INSERT INTO event_calendar
                               (ticker, event_type, event_date, source, fetched_at)
                               VALUES (?,?,?,?,?)
                               ON CONFLICT (ticker, event_type, event_date) DO NOTHING""",
                            (r["symbol"], "ipo_lockin_expiry", d,
                             "computed_lockin", now_iso),
                        )
                        if getattr(cur, "rowcount", 0):
                            inserted += 1
    except Exception as e:
        log.debug("[ipo] lockin sync failed: %s", e)
        return inserted
    if inserted:
        log.info("[ipo] lock-in calendar: %d expiry events added", inserted)
    return inserted


# ── IPO-base scanner ─────────────────────────────────────────────────────────

def scan_ipo_base(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    """O'Neil-style first-base breakout detection for a young listing.

    Returns a scan-result dict shaped like scanner.scan_ticker's output
    (so it flows through the same scorecard/persist path), or None when the
    name isn't actionable (still seasoning / no base / data too thin).
    """
    from config import (IPO_MIN_SEASONING_SESSIONS, IPO_BASE_MIN_SESSIONS,
                        IPO_BASE_MAX_DEPTH_PCT, IPO_BASE_BREAKOUT_VOL_MULT)

    if df is None or df.empty:
        return None
    close = df["Close"].astype(float).dropna()
    n = len(close)
    if n < IPO_MIN_SEASONING_SESSIONS:
        return None  # still in price discovery — no entries

    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    vol = df["Volume"].astype(float)
    price = float(close.iloc[-1])
    if price <= 0:
        return None

    ema10 = close.ewm(span=10, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()

    # Base = everything after the seasoning window, at least IPO_BASE_MIN_SESSIONS
    base = df.iloc[IPO_MIN_SEASONING_SESSIONS - 1:]
    if len(base) < IPO_BASE_MIN_SESSIONS:
        return None
    base_high = float(base["High"].iloc[:-1].max())   # exclude today (the breakout bar)
    base_low = float(base["Low"].iloc[:-1].min())
    if base_high <= 0:
        return None
    depth_pct = (base_high - base_low) / base_high * 100

    avg_vol = float(vol.tail(21).iloc[:-1].mean()) if len(vol) > 21 else float(vol.iloc[:-1].mean())
    vol_today = float(vol.iloc[-1])
    vol_mult = vol_today / avg_vol if avg_vol > 0 else 0.0

    above_emas = price > float(ema10.iloc[-1]) and price > float(ema21.iloc[-1])
    tight_base = depth_pct <= IPO_BASE_MAX_DEPTH_PCT
    breakout = price > base_high
    vol_confirm = vol_mult >= IPO_BASE_BREAKOUT_VOL_MULT

    score = 40.0
    reasons = [f"IPO base: {len(base)} sessions, depth {depth_pct:.1f}%"]
    if tight_base:
        score += 15
        reasons.append("tight base (<25%)")
    else:
        reasons.append(f"base too deep (> {IPO_BASE_MAX_DEPTH_PCT:.0f}%)")
    if above_emas:
        score += 15
        reasons.append("above 10/21 EMA")
    if breakout:
        score += 15
        reasons.append(f"breakout above base high {base_high:.2f}")
    if vol_confirm:
        score += 15
        reasons.append(f"volume {vol_mult:.1f}× avg")

    is_buy = tight_base and above_emas and breakout and vol_confirm
    alert_type = "BUY" if is_buy else ("WATCH" if tight_base and above_emas else "HOLD")
    if alert_type == "HOLD":
        return None  # nothing actionable, don't pollute the scan table

    atr_pct = 0.0
    try:
        tr = pd.concat([(high - low),
                        (high - close.shift()).abs(),
                        (low - close.shift()).abs()], axis=1).max(axis=1)
        atr_pct = float(tr.ewm(alpha=1 / 10, adjust=False).mean().iloc[-1]) / price * 100
    except Exception:
        pass

    return {
        "ticker": ticker,
        "price": round(price, 2),
        "trend_template": int(is_buy),       # IPO-base equivalent of the template
        "vcp_detected": 0,
        "vcp_strength": 0.0,
        "proximity_52w_pct": round((base_high - price) / base_high * 100, 2),
        "ema21": round(float(ema21.iloc[-1]), 2),
        "ema50": 0.0,
        "ema200": 0.0,
        "atr_pct": round(atr_pct, 3),
        "score": round(min(score, 100.0), 1),
        "alert_type": alert_type,
        "reason": ("[IPO_BASE] " + " | ".join(reasons))[:400],
        "strategies_fired": "ipo_base" if is_buy else "",
        "horizon": "SWING",
        "conviction": "medium" if is_buy else "low",
        "est_hold_days": 10,
        "composite_score": round(min(score, 100.0), 1),
        "confluence": 1 if is_buy else 0,
        "timing_score": round(min(score, 100.0), 1),
    }
