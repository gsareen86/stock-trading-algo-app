"""
Stage-0 universe hygiene — hard gates that are never blended away.

Two gates from the conviction-engine design:

  * Surveillance: names on NSE's ASM/GSM lists (Additional / Graded
    Surveillance Measures) are excluded — circuit-limit behaviour and
    margining make them untradeable for a systematic swing book.
  * Liquidity: 60-day median daily traded value must clear
    UNIVERSE_MIN_MEDIAN_TRADED_VALUE_CR (₹ Cr) — illiquid names gap
    through stops.

Fail-open philosophy, with a distinction:
  * A name KNOWN to be on ASM/GSM is always blocked.
  * Missing data (NSE unreachable, no price history) never blocks —
    hygiene_check() passes with the gap recorded in `notes`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

_ASM_URL = "https://www.nseindia.com/api/reportASM"
_GSM_URL = "https://www.nseindia.com/api/reportGSM"


def _bare(ticker: str) -> str:
    return ticker.split(".")[0].strip().upper()


# ── Surveillance lists (ASM / GSM) ───────────────────────────────────────────

def _extract_symbols(payload, list_type: str) -> list[tuple[str, str]]:
    """NSE ASM/GSM payloads vary in shape — pull (symbol, stage) tuples from
    any list-of-dicts found in the payload."""
    rows: list[tuple[str, str]] = []

    def _walk(node):
        if isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            sym = (node.get("symbol") or node.get("Symbol") or "").strip().upper()
            if sym:
                stage = str(node.get("asmSurvIndicator") or node.get("stage")
                            or node.get("gsmSurvIndicator") or "").strip()
                rows.append((sym, stage))
            else:
                for v in node.values():
                    _walk(v)

    _walk(payload)
    return rows


def _last_fetched_at() -> Optional[str]:
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute("SELECT MAX(fetched_at) AS m FROM surveillance_list").fetchone()
        return row["m"] if row else None
    except Exception:
        return None


def refresh_surveillance_lists(force: bool = False) -> dict:
    """Fetch ASM + GSM lists from NSE and replace the surveillance_list table.
    Throttled by SURVEILLANCE_REFRESH_HOURS; fail-open (table kept as-is)."""
    from config import SURVEILLANCE_REFRESH_HOURS

    if not force:
        last = _last_fetched_at()
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                if age_h < SURVEILLANCE_REFRESH_HOURS:
                    return {"refreshed": False, "reason": f"fresh ({age_h:.1f}h old)"}
            except ValueError:
                pass

    from data.nse_calendar import _nse_get_json
    rows: list[tuple[str, str, str]] = []  # (ticker, list_type, stage)
    for list_type, url in (("ASM", _ASM_URL), ("GSM", _GSM_URL)):
        payload = _nse_get_json(url)
        if payload is None:
            continue
        for sym, stage in _extract_symbols(payload, list_type):
            rows.append((sym, list_type, stage))

    if not rows:
        log.info("[hygiene] surveillance fetch returned nothing — lists unchanged")
        return {"refreshed": False, "reason": "no data"}

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            conn.execute("DELETE FROM surveillance_list")
            for ticker, list_type, stage in rows:
                conn.execute(
                    """INSERT INTO surveillance_list (ticker, list_type, stage, fetched_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT (ticker, list_type) DO NOTHING""",
                    (ticker, list_type, stage, now_iso),
                )
    except Exception as e:
        log.warning("[hygiene] surveillance DB write failed: %s", e)
        return {"refreshed": False, "reason": f"db error: {e}"}

    log.info("[hygiene] surveillance lists refreshed: %d entries", len(rows))
    return {"refreshed": True, "entries": len(rows)}


def surveillance_flag(ticker: str) -> Optional[str]:
    """'ASM stage X' / 'GSM ...' if the name is under surveillance, else None."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT list_type, stage FROM surveillance_list WHERE ticker = ? LIMIT 1",
                (_bare(ticker),),
            ).fetchone()
        if row:
            stage = f" stage {row['stage']}" if row["stage"] else ""
            return f"{row['list_type']}{stage}"
    except Exception:
        pass
    return None


# ── Liquidity ────────────────────────────────────────────────────────────────

def median_traded_value_cr(ticker: str, days: int = 60) -> Optional[float]:
    """Median daily traded value (close × volume) in ₹ Cr over the window.
    None when price data is unavailable (caller treats as unknown, not fail)."""
    try:
        from data.fetcher import fetch_candles
        df = fetch_candles(ticker, interval="1d", days=days + 10)
        if df is None or df.empty or "Close" not in df or "Volume" not in df:
            return None
        traded = (df["Close"].astype(float) * df["Volume"].astype(float)).dropna().tail(days)
        if traded.empty:
            return None
        return round(float(traded.median()) / 1e7, 2)  # 1 Cr = 1e7
    except Exception as e:
        log.debug("[hygiene] liquidity calc failed for %s: %s", ticker, e)
        return None


# ── Market-cap & shareholding lookups (microcap integrity) ──────────────────

def market_cap_cr(ticker: str) -> Optional[float]:
    """Market cap in ₹ Cr from pos_universe (preferred) or lt_universe."""
    base = _bare(ticker)
    try:
        from db.models import get_conn
        with get_conn() as conn:
            for sql, params in (
                ("SELECT market_cap FROM pos_universe WHERE ticker=? OR ticker=?",
                 (base, base + ".NS")),
                ("SELECT market_cap FROM lt_universe WHERE ticker=?", (base,)),
            ):
                row = conn.execute(sql, params).fetchone()
                if row and row["market_cap"] is not None:
                    return float(row["market_cap"])
    except Exception:
        pass
    return None


def is_microcap(ticker: str) -> bool:
    """True when the name sits below the microcap threshold. Unknown mcap on
    an expanded-universe name is treated as microcap (conservative)."""
    from config import MICROCAP_MCAP_THRESHOLD_CR
    mcap = market_cap_cr(ticker)
    if mcap is None:
        return True
    return mcap < MICROCAP_MCAP_THRESHOLD_CR


def _shareholding(ticker: str) -> dict:
    """{promoter_pct, pledge_pct} from lt_universe; {} when unknown."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                """SELECT promoter_holding_pct, promoter_pledge_pct
                   FROM lt_universe WHERE ticker=?""",
                (_bare(ticker),),
            ).fetchone()
        if row:
            return {"promoter_pct": row["promoter_holding_pct"],
                    "pledge_pct": row["promoter_pledge_pct"]}
    except Exception:
        pass
    return {}


def microcap_integrity_reasons(ticker: str) -> list[str]:
    """Extra hard gates for sub-threshold names: free float and pledge.
    The index did this vetting for free; below ₹3,000 Cr we must.
    Fail-open on missing data — only KNOWN bad values block."""
    from config import MICROCAP_MIN_FREE_FLOAT_PCT, MICROCAP_MAX_PLEDGE_PCT
    reasons: list[str] = []
    sh = _shareholding(ticker)
    promoter = sh.get("promoter_pct")
    if promoter is not None and (100.0 - float(promoter)) < MICROCAP_MIN_FREE_FLOAT_PCT:
        reasons.append(
            f"microcap free float {100.0 - float(promoter):.1f}% "
            f"< {MICROCAP_MIN_FREE_FLOAT_PCT:.0f}%"
        )
    pledge = sh.get("pledge_pct")
    if pledge is not None and float(pledge) > MICROCAP_MAX_PLEDGE_PCT:
        reasons.append(
            f"microcap pledge {float(pledge):.1f}% > {MICROCAP_MAX_PLEDGE_PCT:.0f}%"
        )
    return reasons


# ── Combined gate ────────────────────────────────────────────────────────────

def liquidity_floor_cr(book: str) -> float:
    """Book-specific liquidity floor: intraday must exit the same day,
    swing has days, long-term can scale out over weeks."""
    from config import (LIQUIDITY_FLOOR_INTRADAY_CR, LIQUIDITY_FLOOR_SWING_CR,
                        LIQUIDITY_FLOOR_LT_CR, UNIVERSE_MIN_MEDIAN_TRADED_VALUE_CR)
    return {
        "intraday": LIQUIDITY_FLOOR_INTRADAY_CR,
        "swing": LIQUIDITY_FLOOR_SWING_CR,
        "longterm": LIQUIDITY_FLOOR_LT_CR,
    }.get(book, UNIVERSE_MIN_MEDIAN_TRADED_VALUE_CR)


def hygiene_check(ticker: str, check_liquidity: bool = True,
                  book: str = "swing") -> dict:
    """Stage-0 gate. Returns {passed, reasons, notes, microcap, floor_cr,
    median_traded_value_cr}.

    Known surveillance listing, known-poor liquidity for the given book, or
    a failed microcap integrity gate fails; missing data only adds a note
    (fail-open on data gaps, fail-closed on known risk)."""
    from config import UNIVERSE_EXCLUDE_SURVEILLANCE

    reasons: list[str] = []
    notes: list[str] = []

    if UNIVERSE_EXCLUDE_SURVEILLANCE:
        flag = surveillance_flag(ticker)
        if flag:
            reasons.append(f"surveillance: {flag}")

    floor = liquidity_floor_cr(book)
    mtv: Optional[float] = None
    if check_liquidity:
        mtv = median_traded_value_cr(ticker)
        if mtv is None:
            notes.append("liquidity unknown (no price data)")
        elif mtv < floor:
            reasons.append(
                f"illiquid for {book}: median traded value ₹{mtv:.1f} Cr/day "
                f"< ₹{floor:.0f} Cr floor"
            )

    micro = is_microcap(ticker)
    if micro:
        reasons.extend(microcap_integrity_reasons(ticker))
        notes.append("microcap tier: halved risk, 0.4% slippage, book budget applies")

    return {"passed": not reasons, "reasons": reasons, "notes": notes,
            "microcap": micro, "floor_cr": floor,
            "median_traded_value_cr": mtv}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(refresh_surveillance_lists(force=True))
