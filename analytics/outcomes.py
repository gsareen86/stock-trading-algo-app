"""
Signal-outcome tracking — the feedback layer of the conviction engine.

Attaches forward 5/20/60-trading-day returns to every recorded signal so
thresholds (scan score, management score, alert severity, veto behaviour)
can be tuned on evidence instead of guesses:

  * pos_scans            (signal_type='pos_scan')      — EOD technical scans
  * pos_research         (signal_type='research_verdict') — LLM research reads
  * news_impact_alerts   (signal_type='news_alert')    — LLM news-impact alerts

Results land in ``signal_outcomes``, one row per (signal_type, ticker,
signal_ts). A horizon column stays NULL until enough trading days have
elapsed; the job re-visits incomplete rows on later runs. Price data comes
from the existing parquet-cached daily fetcher, so re-runs are cheap.

Run daily from the positional EOD scan, or manually:
    python -m analytics.outcomes
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


def _horizons() -> Tuple[int, ...]:
    try:
        from config import OUTCOME_HORIZONS_DAYS
        return tuple(OUTCOME_HORIZONS_DAYS)
    except ImportError:
        return (5, 20, 60)


def _max_tickers() -> int:
    try:
        from config import OUTCOME_JOB_MAX_TICKERS
        return int(OUTCOME_JOB_MAX_TICKERS)
    except ImportError:
        return 25


def _daily_closes(ticker: str):
    """Daily close series (DatetimeIndex → float) for ~9 months, or None."""
    try:
        from data.fetcher import fetch_candles
        df = fetch_candles(ticker, interval="1d", days=270)
        if df is None or df.empty or "Close" not in df:
            return None
        closes = df["Close"].astype(float).dropna()
        return closes if not closes.empty else None
    except Exception as e:
        log.debug("[outcomes] price fetch failed for %s: %s", ticker, e)
        return None


def forward_returns(closes, signal_ts: str) -> Optional[Dict[int, Optional[float]]]:
    """% returns over each horizon (in TRADING days) from the first close on
    or after the signal date. A horizon is None until enough bars exist."""
    sig_date = str(signal_ts)[:10]
    try:
        dates = [str(d)[:10] for d in closes.index]
    except Exception:
        return None

    ref_idx = next((i for i, d in enumerate(dates) if d >= sig_date), None)
    if ref_idx is None:
        return None
    ref_price = float(closes.iloc[ref_idx])
    if ref_price <= 0:
        return None

    out: Dict[int, Optional[float]] = {"ref_price": ref_price}  # type: ignore[assignment]
    for h in _horizons():
        j = ref_idx + h
        out[h] = (
            round((float(closes.iloc[j]) - ref_price) / ref_price * 100.0, 3)
            if j < len(closes) else None
        )
    return out


def _pending_signals(limit_per_source: int = 500) -> List[dict]:
    """Signals that have no outcome row yet, or whose row is incomplete."""
    from db.models import get_conn

    pending: List[dict] = []
    queries = (
        ("pos_scan",
         """SELECT s.id AS signal_id, s.ticker, s.scanned_at AS signal_ts
            FROM pos_scans s
            LEFT JOIN signal_outcomes o
              ON o.signal_type='pos_scan' AND o.ticker=s.ticker AND o.signal_ts=s.scanned_at
            WHERE o.id IS NULL OR o.fwd_ret_60d IS NULL
            ORDER BY s.scanned_at DESC LIMIT ?"""),
        ("research_verdict",
         """SELECT 0 AS signal_id, r.ticker, r.researched_at AS signal_ts
            FROM pos_research r
            LEFT JOIN signal_outcomes o
              ON o.signal_type='research_verdict' AND o.ticker=r.ticker AND o.signal_ts=r.researched_at
            WHERE o.id IS NULL OR o.fwd_ret_60d IS NULL
            ORDER BY r.researched_at DESC LIMIT ?"""),
        ("news_alert",
         """SELECT a.id AS signal_id, a.ticker, a.created_at AS signal_ts
            FROM news_impact_alerts a
            LEFT JOIN signal_outcomes o
              ON o.signal_type='news_alert' AND o.ticker=a.ticker AND o.signal_ts=a.created_at
            WHERE o.id IS NULL OR o.fwd_ret_60d IS NULL
            ORDER BY a.created_at DESC LIMIT ?"""),
    )
    try:
        with get_conn() as conn:
            for stype, sql in queries:
                for r in conn.execute(sql, (limit_per_source,)).fetchall():
                    d = dict(r)
                    d["signal_type"] = stype
                    pending.append(d)
    except Exception as e:
        log.warning("[outcomes] pending query failed: %s", e)
    return pending


def compute_outcomes() -> dict:
    """One incremental pass: fetch prices per ticker (capped per run) and
    upsert forward returns for every pending signal of those tickers."""
    from db.models import get_conn

    pending = _pending_signals()
    if not pending:
        return {"computed": 0, "tickers": 0, "pending": 0}

    by_ticker: Dict[str, List[dict]] = {}
    for sig in pending:
        by_ticker.setdefault(sig["ticker"], []).append(sig)

    computed = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    h5, h20, h60 = _horizons()

    for ticker in list(by_ticker)[:_max_tickers()]:
        closes = _daily_closes(ticker)
        if closes is None:
            continue
        for sig in by_ticker[ticker]:
            fr = forward_returns(closes, sig["signal_ts"])
            if not fr:
                continue
            try:
                with get_conn() as conn:
                    conn.execute(
                        """INSERT INTO signal_outcomes
                           (signal_type, signal_id, ticker, signal_ts, ref_price,
                            fwd_ret_5d, fwd_ret_20d, fwd_ret_60d, computed_at)
                           VALUES (?,?,?,?,?,?,?,?,?)
                           ON CONFLICT (signal_type, ticker, signal_ts) DO UPDATE SET
                             ref_price   = excluded.ref_price,
                             fwd_ret_5d  = excluded.fwd_ret_5d,
                             fwd_ret_20d = excluded.fwd_ret_20d,
                             fwd_ret_60d = excluded.fwd_ret_60d,
                             computed_at = excluded.computed_at""",
                        (sig["signal_type"], int(sig.get("signal_id") or 0),
                         ticker, sig["signal_ts"], fr["ref_price"],
                         fr.get(h5), fr.get(h20), fr.get(h60), now_iso),
                    )
                computed += 1
            except Exception as e:
                log.debug("[outcomes] upsert failed for %s/%s: %s",
                          sig["signal_type"], ticker, e)

    log.info("[outcomes] pass done: %d outcome rows updated across %d tickers "
             "(%d signals pending total)",
             computed, min(len(by_ticker), _max_tickers()), len(pending))
    return {"computed": computed,
            "tickers": min(len(by_ticker), _max_tickers()),
            "pending": len(pending)}


def outcome_summary(signal_type: Optional[str] = None) -> List[dict]:
    """Aggregate hit-rates per signal type for the dashboard / analysis.
    'Hit' = positive forward return at each horizon."""
    from db.models import get_conn

    where = "WHERE signal_type = ?" if signal_type else ""
    params = (signal_type,) if signal_type else ()
    sql = f"""
        SELECT signal_type,
               COUNT(*)                                    AS n,
               AVG(fwd_ret_5d)                             AS avg_5d,
               AVG(fwd_ret_20d)                            AS avg_20d,
               AVG(fwd_ret_60d)                            AS avg_60d,
               AVG(CASE WHEN fwd_ret_20d > 0 THEN 1.0 ELSE 0.0 END) AS hit_rate_20d
        FROM signal_outcomes
        {where}
        GROUP BY signal_type"""
    try:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(compute_outcomes())
    for row in outcome_summary():
        print(row)
