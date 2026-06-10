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


# ── Combined gate ────────────────────────────────────────────────────────────

def hygiene_check(ticker: str, check_liquidity: bool = True) -> dict:
    """Stage-0 gate. Returns {passed: bool, reasons: [..], notes: [..]}.

    Known surveillance listing or known-poor liquidity fails; missing data
    only adds a note (fail-open on data gaps, fail-closed on known risk)."""
    from config import UNIVERSE_EXCLUDE_SURVEILLANCE, UNIVERSE_MIN_MEDIAN_TRADED_VALUE_CR

    reasons: list[str] = []
    notes: list[str] = []

    if UNIVERSE_EXCLUDE_SURVEILLANCE:
        flag = surveillance_flag(ticker)
        if flag:
            reasons.append(f"surveillance: {flag}")

    if check_liquidity:
        mtv = median_traded_value_cr(ticker)
        if mtv is None:
            notes.append("liquidity unknown (no price data)")
        elif mtv < UNIVERSE_MIN_MEDIAN_TRADED_VALUE_CR:
            reasons.append(
                f"illiquid: median traded value ₹{mtv:.1f} Cr/day "
                f"< ₹{UNIVERSE_MIN_MEDIAN_TRADED_VALUE_CR:.0f} Cr"
            )

    return {"passed": not reasons, "reasons": reasons, "notes": notes}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(refresh_surveillance_lists(force=True))
