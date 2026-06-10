"""
Guidance ledger — management commentary turned into an accountable record.

The Phase-3 research engine already restates management's forward guidance
as free text (pos_research.guidance). This module makes that compounding:

  1. extract_guidance_items()  — one small LLM call turns the guidance text
     into structured rows {metric, guided_value, band, horizon} stored in
     ``guidance_ledger``.
  2. reconcile_guidance()      — when the next quarterly actuals are
     available on Screener, each row is stamped MET / BEAT / MISSED /
     UNVERIFIABLE.
  3. credibility_score()       — rolling, recency-weighted hit-rate (0-100)
     written to pos_research.guidance_credibility; it is the objective
     "does management deliver what it promises?" input to the durability
     axis, and a miss streak raises a review alert.

Everything here is fail-open: an LLM or scrape failure leaves the ledger
unchanged and never breaks the EOD scan that calls run_guidance_jobs().
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

log = logging.getLogger(__name__)

# Metrics the reconciler can verify from Screener quarterly data. Everything
# else stays UNVERIFIABLE (still useful: the ledger documents the promise).
_VERIFIABLE_METRICS = {"revenue_growth", "net_profit_growth", "margin"}

# Wait this long after extraction before attempting reconciliation, so the
# next quarter's results have actually been published.
_RECONCILE_AFTER_DAYS = 70
# Give up trying to verify after this long.
_UNVERIFIABLE_AFTER_DAYS = 220

# Relative tolerance for MET on growth metrics; absolute (pp) for margins.
_GROWTH_TOLERANCE_REL = 0.15
_MARGIN_TOLERANCE_PP = 2.0

GUIDANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": ("one of: revenue_growth, net_profit_growth, margin, "
                                        "capex, order_book, volume_growth, other"),
                    },
                    "guided_value": {
                        "type": "string",
                        "description": "verbatim guidance, e.g. '18-20% YoY revenue growth'",
                    },
                    "guided_low": {"type": ["number", "null"],
                                   "description": "numeric lower bound if parseable (% or value)"},
                    "guided_high": {"type": ["number", "null"],
                                    "description": "numeric upper bound if parseable"},
                    "horizon": {"type": "string",
                                "description": "next_quarter | FY | multi_year"},
                },
                "required": ["metric", "guided_value"],
            },
        },
    },
    "required": ["items"],
}

_SYSTEM = (
    "You extract structured guidance items from an Indian listed company's "
    "management commentary. Only include FORWARD-looking commitments by "
    "management (numbers, bands, targets). Never invent values; leave "
    "guided_low/guided_high null when no number is stated. Use percent "
    "values as plain numbers (18-20% -> 18 and 20)."
)


def fy_quarter_from_date(iso_or_text: Optional[str]) -> Optional[str]:
    """Date -> Indian fiscal-year quarter label, e.g. 2025-08-07 -> 'FY26Q2'.
    Indian FY runs Apr-Mar; Q1 = Apr-Jun."""
    if not iso_or_text:
        return None
    raw = str(iso_or_text).strip()
    dt = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%b %Y", "%B %Y"):
        try:
            dt = datetime.strptime(raw[:10] if fmt == "%Y-%m-%d" else raw, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    fy = dt.year + 1 if dt.month >= 4 else dt.year
    q = (dt.month - 4) // 3 + 1 if dt.month >= 4 else (dt.month + 8) // 3 + 1
    return f"FY{fy % 100:02d}Q{q}"


def _research_row(ticker: str) -> Optional[dict]:
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pos_research WHERE ticker = ?", (ticker,)
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def extract_guidance_items(ticker: str) -> int:
    """Turn pos_research.guidance into structured ledger rows. Returns the
    number of NEW rows inserted (existing ticker+quarter+metric rows are
    kept — guidance is extracted once per concall)."""
    from config import GUIDANCE_EXTRACTION_ENABLED
    if not GUIDANCE_EXTRACTION_ENABLED:
        return 0

    r = _research_row(ticker)
    if not r:
        return 0
    guidance_text = (r.get("guidance") or "").strip()
    if not guidance_text or guidance_text.lower().startswith("none"):
        return 0

    source_quarter = fy_quarter_from_date(r.get("concall_date")) or \
        fy_quarter_from_date(r.get("researched_at"))

    # Skip if this concall's guidance was already extracted.
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM guidance_ledger WHERE ticker=? AND source_quarter=?",
                (ticker, source_quarter),
            ).fetchone()
        if int(row["n"] or 0) > 0:
            return 0
    except Exception:
        return 0

    from llm.client import call_json, hash_text
    payload = call_json(
        prompt=(f"Company: {ticker}\nManagement guidance (restated from the latest "
                f"concall):\n{guidance_text[:4000]}\n\nExtract the guidance items."),
        schema=GUIDANCE_SCHEMA,
        system=_SYSTEM,
        max_tokens=600,
        cache_key="guidance_" + hash_text(f"{ticker}|{guidance_text}"),
        caller="guidance_extract",
    )
    if not payload or not isinstance(payload.get("items"), list):
        return 0

    inserted = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            for item in payload["items"][:10]:
                metric = str(item.get("metric") or "other").strip().lower()
                guided_value = str(item.get("guided_value") or "").strip()
                if not guided_value:
                    continue
                conn.execute(
                    """INSERT INTO guidance_ledger
                       (ticker, source_quarter, metric, guided_value,
                        guided_low, guided_high, horizon, extracted_at, source_url)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (ticker, source_quarter, metric, guided_value,
                     item.get("guided_low"), item.get("guided_high"),
                     str(item.get("horizon") or "next_quarter"), now_iso, None),
                )
                inserted += 1
    except Exception as e:
        log.debug("[guidance] insert failed for %s: %s", ticker, e)
        return 0

    if inserted:
        log.info("[guidance] %s: %d guidance items recorded (%s)",
                 ticker, inserted, source_quarter)
    return inserted


def _quarterly_actuals(ticker: str) -> dict:
    """Latest verifiable actuals from Screener quarterly data:
    {revenue_growth: % YoY, net_profit_growth: % YoY, margin: latest OPM %}."""
    out: dict = {}
    try:
        from longterm.screener_scraper import fetch_company
        data = fetch_company(ticker)
        if not data:
            return out

        def _yoy(series_key: str) -> Optional[float]:
            # records are {"period","value"} most-recent-first; YoY compares
            # the latest quarter with the one 4 quarters back.
            vals = [v.get("value") for v in (data.get(series_key) or [])
                    if v.get("value") is not None]
            if len(vals) >= 5 and vals[4] not in (0, None):
                return round((float(vals[0]) - float(vals[4])) / abs(float(vals[4])) * 100, 2)
            return None

        rev = _yoy("quarterly_revenue")
        npf = _yoy("quarterly_net_profit")
        opm_vals = [v.get("value") for v in (data.get("quarterly_opm") or [])
                    if v.get("value") is not None]
        if rev is not None:
            out["revenue_growth"] = rev
        if npf is not None:
            out["net_profit_growth"] = npf
        if opm_vals:
            out["margin"] = float(opm_vals[0])
    except Exception as e:
        log.debug("[guidance] actuals fetch failed for %s: %s", ticker, e)
    return out


def _verdict(metric: str, low: Optional[float], high: Optional[float],
             actual: float) -> str:
    lo = low if low is not None else high
    hi = high if high is not None else low
    if lo is None or hi is None:
        return "UNVERIFIABLE"
    if lo > hi:
        lo, hi = hi, lo
    if metric == "margin":
        tol_lo, tol_hi = lo - _MARGIN_TOLERANCE_PP, hi + _MARGIN_TOLERANCE_PP
    else:
        tol_lo = lo - abs(lo) * _GROWTH_TOLERANCE_REL
        tol_hi = hi + abs(hi) * _GROWTH_TOLERANCE_REL
    if actual > tol_hi:
        return "BEAT"
    if actual < tol_lo:
        return "MISSED"
    return "MET"


def reconcile_guidance(ticker: str) -> int:
    """Stamp delivered MET/BEAT/MISSED on rows whose next-quarter actuals
    should now exist. Returns rows reconciled this call."""
    from db.models import get_conn
    now = datetime.now(timezone.utc)
    try:
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT * FROM guidance_ledger
                   WHERE ticker = ? AND reconciled_at IS NULL""",
                (ticker,),
            ).fetchall()]
    except Exception:
        return 0
    if not rows:
        return 0

    actuals: Optional[dict] = None
    done = 0
    for row in rows:
        try:
            extracted = datetime.fromisoformat(str(row["extracted_at"]))
            if extracted.tzinfo is None:
                extracted = extracted.replace(tzinfo=timezone.utc)
            age_days = (now - extracted).days
        except ValueError:
            age_days = 0
        if age_days < _RECONCILE_AFTER_DAYS:
            continue

        metric = row["metric"]
        delivered = None
        actual_value = None
        if metric in _VERIFIABLE_METRICS and str(row.get("horizon")) in ("next_quarter", "FY"):
            if actuals is None:
                actuals = _quarterly_actuals(ticker)
            actual_value = actuals.get(metric)
            if actual_value is not None:
                delivered = _verdict(metric, row.get("guided_low"),
                                     row.get("guided_high"), float(actual_value))
        if delivered is None and age_days >= _UNVERIFIABLE_AFTER_DAYS:
            delivered = "UNVERIFIABLE"
        if delivered is None:
            continue

        try:
            with get_conn() as conn:
                conn.execute(
                    """UPDATE guidance_ledger
                       SET actual_value=?, delivered=?, reconciled_at=?
                       WHERE id=?""",
                    (actual_value, delivered, now.isoformat(), row["id"]),
                )
            done += 1
        except Exception as e:
            log.debug("[guidance] reconcile update failed for %s: %s", ticker, e)
    if done:
        log.info("[guidance] %s: reconciled %d guidance rows", ticker, done)
    return done


def credibility_score(ticker: str) -> Optional[float]:
    """Recency-weighted guidance hit-rate, 0-100. MET/BEAT count as hits,
    MISSED as misses; UNVERIFIABLE rows are ignored. None until at least
    two rows are reconciled."""
    from db.models import get_conn
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT delivered FROM guidance_ledger
                   WHERE ticker=? AND delivered IN ('MET','BEAT','MISSED')
                   ORDER BY reconciled_at DESC LIMIT 16""",
                (ticker,),
            ).fetchall()
    except Exception:
        return None
    verdicts = [r["delivered"] for r in rows]
    if len(verdicts) < 2:
        return None
    w, total_w, hits_w = 1.0, 0.0, 0.0
    for v in verdicts:
        total_w += w
        if v in ("MET", "BEAT"):
            hits_w += w
        w *= 0.8  # older quarters matter less
    return round(100.0 * hits_w / total_w, 1)


def miss_streak(ticker: str) -> int:
    """Consecutive MISSED verdicts, most recent first."""
    from db.models import get_conn
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT delivered FROM guidance_ledger
                   WHERE ticker=? AND delivered IN ('MET','BEAT','MISSED')
                   ORDER BY reconciled_at DESC LIMIT 8""",
                (ticker,),
            ).fetchall()
    except Exception:
        return 0
    streak = 0
    for r in rows:
        if r["delivered"] == "MISSED":
            streak += 1
        else:
            break
    return streak


def run_guidance_jobs(tickers: Optional[List[str]] = None) -> dict:
    """Daily pass: extract new guidance, reconcile due rows, refresh
    credibility on pos_research, and raise a review alert on a miss streak.
    Called from the positional EOD scan; fail-open throughout."""
    from config import GUIDANCE_MISS_STREAK_REVIEW
    from db.models import get_conn

    if tickers is None:
        tickers = []
        try:
            with get_conn() as conn:
                held = [r["ticker"] for r in conn.execute(
                    "SELECT DISTINCT ticker FROM pos_positions WHERE status='OPEN'"
                ).fetchall()]
                researched = [r["ticker"] for r in conn.execute(
                    "SELECT ticker FROM pos_research ORDER BY researched_at DESC LIMIT 50"
                ).fetchall()]
            tickers = list(dict.fromkeys(held + researched))
        except Exception:
            return {"tickers": 0}

    extracted = reconciled = alerts = 0
    for ticker in tickers:
        try:
            extracted += extract_guidance_items(ticker)
            reconciled += reconcile_guidance(ticker)
            cred = credibility_score(ticker)
            if cred is not None:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE pos_research SET guidance_credibility=? WHERE ticker=?",
                        (cred, ticker),
                    )
            streak = miss_streak(ticker)
            if streak >= GUIDANCE_MISS_STREAK_REVIEW:
                alerts += 1
                msg = (f"GUIDANCE REVIEW: {ticker} has missed its own guidance "
                       f"{streak} quarters in a row (credibility="
                       f"{cred if cred is not None else 'n/a'})")
                log.warning("[guidance] %s", msg)
                try:
                    from positional.alerts import send_sell_alert
                    send_sell_alert(ticker, 0.0, msg)
                except Exception:
                    pass
        except Exception as e:
            log.debug("[guidance] job failed for %s: %s", ticker, e)

    summary = {"tickers": len(tickers), "extracted": extracted,
               "reconciled": reconciled, "review_alerts": alerts}
    log.info("[guidance] pass done: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_guidance_jobs())
