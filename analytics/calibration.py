"""
Calibration report (Phase 7) — evidence-based threshold review, advisory only.

Joins signal_outcomes (forward returns attached by analytics/outcomes.py)
back to the scores that produced them and answers, empirically:

  * Do higher scan composite scores actually earn higher forward returns?
  * Which score band would have been the best entry threshold?
  * Do research verdicts (PROCEED/REDUCE/SKIP) separate outcomes?
  * Do news-alert severities (critical/watch/info) predict drawdowns?

NOTHING here changes config automatically. The report is a recommendation;
applying it is a human decision (and below MIN_OUTCOMES_FOR_CALIBRATION
samples the report says so and refuses to recommend at all).

    python -m analytics.calibration
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

_SCORE_BANDS = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 101))


def _outcome_count() -> int:
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM signal_outcomes WHERE fwd_ret_20d IS NOT NULL"
            ).fetchone()
        return int(row["n"] or 0)
    except Exception:
        return 0


def _band_stats(rows: list[dict], score_key: str) -> list[dict]:
    out = []
    for lo, hi in _SCORE_BANDS:
        sub = [r for r in rows
               if r.get(score_key) is not None and lo <= float(r[score_key]) < hi
               and r.get("fwd_ret_20d") is not None]
        if not sub:
            continue
        rets = [float(r["fwd_ret_20d"]) for r in sub]
        out.append({
            "band": f"{lo}-{hi - 1}",
            "n": len(sub),
            "avg_fwd_20d_pct": round(sum(rets) / len(rets), 2),
            "hit_rate_pct": round(100.0 * sum(1 for x in rets if x > 0) / len(rets), 1),
        })
    return out


def _scan_score_rows() -> list[dict]:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT s.composite_score, s.score, o.fwd_ret_5d, o.fwd_ret_20d, o.fwd_ret_60d
                   FROM signal_outcomes o
                   JOIN pos_scans s
                     ON o.signal_type='pos_scan' AND o.ticker=s.ticker
                    AND o.signal_ts=s.scanned_at
                   WHERE o.fwd_ret_20d IS NOT NULL"""
            ).fetchall()]
    except Exception:
        return []


def _verdict_rows() -> list[dict]:
    """Research-verdict outcomes. Caveat: pos_research keeps only the latest
    row per ticker, so the verdict is matched on (ticker, researched_at) and
    only joins for the most recent research per name."""
    from db.models import get_conn
    try:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT r.verdict, o.fwd_ret_20d
                   FROM signal_outcomes o
                   JOIN pos_research r
                     ON o.signal_type='research_verdict' AND o.ticker=r.ticker
                    AND o.signal_ts=r.researched_at
                   WHERE o.fwd_ret_20d IS NOT NULL"""
            ).fetchall()]
    except Exception:
        return []


def _alert_rows() -> list[dict]:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT a.severity, a.recommended_action, o.fwd_ret_20d
                   FROM signal_outcomes o
                   JOIN news_impact_alerts a
                     ON o.signal_type='news_alert' AND o.signal_id=a.id
                   WHERE o.fwd_ret_20d IS NOT NULL"""
            ).fetchall()]
    except Exception:
        return []


def _group_avg(rows: list[dict], key: str) -> list[dict]:
    groups: dict = {}
    for r in rows:
        k = str(r.get(key) or "?")
        groups.setdefault(k, []).append(float(r["fwd_ret_20d"]))
    return [
        {key: k, "n": len(v),
         "avg_fwd_20d_pct": round(sum(v) / len(v), 2),
         "hit_rate_pct": round(100.0 * sum(1 for x in v if x > 0) / len(v), 1)}
        for k, v in sorted(groups.items())
    ]


def _recommend_threshold(bands: list[dict]) -> Optional[dict]:
    """Lowest score band whose 20-day hit rate ≥55% AND avg return positive —
    everything from that band up would have been worth taking."""
    for band in bands:
        if band["hit_rate_pct"] >= 55.0 and band["avg_fwd_20d_pct"] > 0:
            return {"suggested_min_score": int(band["band"].split("-")[0]),
                    "based_on_band": band}
    return None


def calibration_report() -> dict:
    """Full advisory report. Always returns data; only recommends once the
    sample crosses MIN_OUTCOMES_FOR_CALIBRATION."""
    from config import MIN_OUTCOMES_FOR_CALIBRATION

    n = _outcome_count()
    scan_rows = _scan_score_rows()
    bands = _band_stats(scan_rows, "composite_score") or _band_stats(scan_rows, "score")

    report = {
        "outcomes_with_20d": n,
        "min_required": MIN_OUTCOMES_FOR_CALIBRATION,
        "status": "ok" if n >= MIN_OUTCOMES_FOR_CALIBRATION else "insufficient_data",
        "scan_score_bands": bands,
        "research_verdicts": _group_avg(_verdict_rows(), "verdict"),
        "news_alert_severity": _group_avg(_alert_rows(), "severity"),
        "recommendation": None,
        "notes": [
            "Advisory only — nothing is auto-applied.",
            "Verdict join covers only each ticker's most recent research row.",
        ],
    }
    if report["status"] == "ok":
        report["recommendation"] = _recommend_threshold(bands)
    else:
        report["notes"].insert(
            0,
            f"Only {n}/{MIN_OUTCOMES_FOR_CALIBRATION} outcomes — keep collecting "
            "before acting on any of these numbers.",
        )
    return report


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(calibration_report(), indent=2, default=str))
