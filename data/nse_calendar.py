"""
Deterministic NSE corporate-events calendar.

Replaces LLM-inferred earnings dates for the positional event guard: board
meetings (results) and corporate actions (ex-dividend/bonus/split dates) are
facts published by the exchange, so they are fetched from NSE's public JSON
endpoints and stored in the ``event_calendar`` table.

Fail-open by design: if NSE is unreachable or blocks the request, the
calendar is simply stale/empty and ``has_blocking_event`` returns None —
an entry is never blocked by missing data. (The intraday module keeps the
LLM news-based extractor in llm/events.py as a complementary heuristic.)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

_NSE_BASE = "https://www.nseindia.com"
_BOARD_MEETINGS_URL = _NSE_BASE + "/api/corporate-board-meetings?index=equities"
_CORPORATE_ACTIONS_URL = _NSE_BASE + "/api/corporates-corporateActions?index=equities"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NSE_BASE + "/companies-listing/corporate-filings-board-meetings",
}

_DATE_FORMATS = ("%d-%b-%Y", "%d-%m-%Y", "%d-%B-%Y", "%Y-%m-%d")

# Board-meeting purposes that imply a results announcement (gap risk).
_RESULTS_KEYWORDS = ("result", "financial results", "quarterly", "audited")


def _parse_nse_date(raw: str) -> Optional[str]:
    """NSE date string -> ISO date, or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _nse_get_json(url: str) -> Optional[list]:
    """GET an NSE API endpoint with a warmed-up session. None on any failure."""
    try:
        import requests
        s = requests.Session()
        s.headers.update(_HEADERS)
        # NSE requires the cookies set by the landing page before /api works.
        s.get(_NSE_BASE, timeout=10)
        res = s.get(url, timeout=15)
        if res.status_code != 200:
            log.warning("[nse_calendar] HTTP %d for %s", res.status_code, url)
            return None
        data = res.json()
        if isinstance(data, dict):  # some endpoints wrap rows in {"data": [...]}
            data = data.get("data") or data.get("rows") or []
        return data if isinstance(data, list) else None
    except Exception as e:
        log.warning("[nse_calendar] fetch failed for %s: %s", url, e)
        return None


def _last_fetched_at() -> Optional[str]:
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute("SELECT MAX(fetched_at) AS m FROM event_calendar").fetchone()
        return row["m"] if row else None
    except Exception:
        return None


def refresh_event_calendar(force: bool = False) -> dict:
    """Fetch board meetings + corporate actions from NSE and upsert into
    ``event_calendar``. Throttled by EVENT_CALENDAR_REFRESH_HOURS."""
    from config import EVENT_CALENDAR_REFRESH_HOURS

    if not force:
        last = _last_fetched_at()
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                if age_h < EVENT_CALENDAR_REFRESH_HOURS:
                    return {"refreshed": False, "reason": f"fresh ({age_h:.1f}h old)"}
            except ValueError:
                pass

    rows: list[tuple[str, str, str, str]] = []  # (ticker, event_type, event_date, source)

    bm = _nse_get_json(_BOARD_MEETINGS_URL) or []
    for item in bm:
        try:
            sym = (item.get("bm_symbol") or item.get("symbol") or "").strip().upper()
            d = _parse_nse_date(item.get("bm_date") or item.get("meetingDate") or "")
            purpose = (item.get("bm_purpose") or item.get("purpose") or "").lower()
            if not sym or not d:
                continue
            etype = "results" if any(k in purpose for k in _RESULTS_KEYWORDS) else "board_meeting"
            rows.append((sym, etype, d, "nse_board_meetings"))
        except Exception:
            continue

    ca = _nse_get_json(_CORPORATE_ACTIONS_URL) or []
    for item in ca:
        try:
            sym = (item.get("symbol") or "").strip().upper()
            d = _parse_nse_date(item.get("exDate") or item.get("exdate") or "")
            subject = (item.get("subject") or item.get("purpose") or "").lower()
            if not sym or not d:
                continue
            if "dividend" in subject:
                etype = "ex_dividend"
            elif "bonus" in subject:
                etype = "ex_bonus"
            elif "split" in subject:
                etype = "ex_split"
            elif "rights" in subject:
                etype = "ex_rights"
            else:
                etype = "corporate_action"
            rows.append((sym, etype, d, "nse_corporate_actions"))
        except Exception:
            continue

    if not rows:
        log.info("[nse_calendar] nothing fetched (NSE unreachable or empty) — calendar unchanged")
        return {"refreshed": False, "reason": "no data"}

    inserted = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            for ticker, etype, edate, source in rows:
                cur = conn.execute(
                    """INSERT INTO event_calendar (ticker, event_type, event_date, source, fetched_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT (ticker, event_type, event_date) DO NOTHING""",
                    (ticker, etype, edate, source, now_iso),
                )
                if getattr(cur, "rowcount", 0):
                    inserted += 1
            # prune events that are long past — keeps the table small
            cutoff = (date.today() - timedelta(days=30)).isoformat()
            conn.execute("DELETE FROM event_calendar WHERE event_date < ?", (cutoff,))
    except Exception as e:
        log.warning("[nse_calendar] DB write failed: %s", e)
        return {"refreshed": False, "reason": f"db error: {e}"}

    log.info("[nse_calendar] refreshed: %d rows fetched, %d new", len(rows), inserted)
    return {"refreshed": True, "fetched": len(rows), "new": inserted}


def upcoming_events(ticker: str, days: int = 7) -> list[dict]:
    """Known events for a ticker within the next N calendar days."""
    bare = ticker.split(".")[0].upper()
    today = date.today().isoformat()
    until = (date.today() + timedelta(days=days)).isoformat()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT ticker, event_type, event_date, source FROM event_calendar
                   WHERE ticker = ? AND event_date >= ? AND event_date <= ?
                   ORDER BY event_date""",
                (bare, today, until),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def has_blocking_event(ticker: str, days: int = 3) -> Optional[str]:
    """Reason string if a gap-risk event (results / board meeting / ex-date /
    IPO lock-in expiry) falls within the next N days, else None.
    Fail-open: empty calendar → None. Lock-in expiries are deterministic
    SUPPLY events (anchor 30/90d, promoter 6/18m) and use their own window."""
    blocking = {"results", "board_meeting", "ex_dividend", "ex_rights"}
    for ev in upcoming_events(ticker, days=days):
        if ev["event_type"] in blocking:
            return f"{ev['event_type']} on {ev['event_date']} (source: {ev['source']})"
    try:
        from config import IPO_LOCKIN_GUARD_DAYS
        for ev in upcoming_events(ticker, days=IPO_LOCKIN_GUARD_DAYS):
            if ev["event_type"] == "ipo_lockin_expiry":
                return f"IPO lock-in expiry on {ev['event_date']} (known supply event)"
    except Exception:
        pass
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(refresh_event_calendar(force=True))
