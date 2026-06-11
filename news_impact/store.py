"""SQL reads + writes for the news_impact_alerts and news_sector_tags tables.

All SQL uses ``?`` placeholders so the existing SQLite/Postgres translator
in :mod:`db.models` handles both backends. JSON-ish columns are serialised
via :func:`json.dumps` into TEXT (SQLite) or stored natively as JSONB
(Postgres) — both round-trip identically through the wrapper.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


SEVERITY_RANK: Dict[str, int] = {"critical": 3, "watch": 2, "info": 1}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    if isinstance(obj, str):
        # Already JSON text (Postgres JSONB will accept).
        return obj
    return json.dumps(obj, default=str)


def _loads(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Content hashing for supersede / dedup logic
# ---------------------------------------------------------------------------


def content_hash(
    *,
    ticker: str,
    severity: str,
    recommended_action: str,
    news_ids: List[int],
    impact_summary: str,
) -> str:
    """SHA1 over the inputs that define an alert's "content". Two alerts with
    the same hash represent the same finding and the second is dropped.
    """
    payload = "|".join([
        (ticker or "").upper(),
        severity or "",
        recommended_action or "",
        ",".join(str(i) for i in sorted(news_ids or [])),
        (impact_summary or "").strip().lower(),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# news_sector_tags
# ---------------------------------------------------------------------------


def upsert_sector_tag(
    news_id: int,
    primary_sector: Optional[str],
    ancillary_sectors: List[str],
    why_note: Optional[str],
    model: Optional[str],
    confidence: Optional[float],
) -> None:
    from db.models import get_conn
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO news_sector_tags
                 (news_id, tagged_at, primary_sector, ancillary_sectors,
                  why_note, model, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (news_id) DO UPDATE SET
                   tagged_at         = excluded.tagged_at,
                   primary_sector    = excluded.primary_sector,
                   ancillary_sectors = excluded.ancillary_sectors,
                   why_note          = excluded.why_note,
                   model             = excluded.model,
                   confidence        = excluded.confidence""",
            (
                int(news_id),
                _now_iso(),
                primary_sector,
                _dumps(list(ancillary_sectors or [])),
                why_note,
                model,
                float(confidence) if confidence is not None else None,
            ),
        )


def fetch_sector_tag(news_id: int) -> Optional[Dict[str, Any]]:
    from db.models import get_conn
    with get_conn() as conn:
        r = conn.execute(
            """SELECT news_id, tagged_at, primary_sector, ancillary_sectors,
                      why_note, model, confidence
                 FROM news_sector_tags
                WHERE news_id = ?""",
            (int(news_id),),
        ).fetchone()
    if not r:
        return None
    return {
        "news_id": r["news_id"],
        "tagged_at": r["tagged_at"],
        "primary_sector": r["primary_sector"],
        "ancillary_sectors": _loads(r["ancillary_sectors"]) or [],
        "why_note": r["why_note"],
        "model": r["model"],
        "confidence": r["confidence"],
    }


def fetch_sector_tags_bulk(news_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not news_ids:
        return {}
    from db.models import get_conn
    out: Dict[int, Dict[str, Any]] = {}
    placeholders = ",".join("?" for _ in news_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT news_id, primary_sector, ancillary_sectors, why_note,
                       model, confidence
                  FROM news_sector_tags
                 WHERE news_id IN ({placeholders})""",
            tuple(int(i) for i in news_ids),
        ).fetchall()
    for r in rows:
        out[int(r["news_id"])] = {
            "primary_sector": r["primary_sector"],
            "ancillary_sectors": _loads(r["ancillary_sectors"]) or [],
            "why_note": r["why_note"],
            "model": r["model"],
            "confidence": r["confidence"],
        }
    return out


def untagged_recent_news(window_hours: int = 72, limit: int = 200) -> List[Dict[str, Any]]:
    """Recent news rows that don't have a sector tag yet. LEFT JOIN avoids a
    subquery and works on both backends."""
    from datetime import timedelta
    from db.models import get_conn
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(window_hours))).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT n.id, n.ts, n.source, n.title, n.summary, n.url, n.tickers
                 FROM news n
            LEFT JOIN news_sector_tags t ON t.news_id = n.id
                WHERE t.news_id IS NULL
                  AND n.ts >= ?
             ORDER BY n.ts DESC
                LIMIT ?""",
            (cutoff, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# news_impact_alerts
# ---------------------------------------------------------------------------


def recent_hash_exists(content_hash_value: str, hours: int = 24) -> bool:
    """Return True if any non-superseded alert with the same content hash was
    created within ``hours`` — used to short-circuit duplicate inserts."""
    from datetime import timedelta
    from db.models import get_conn
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    with get_conn() as conn:
        r = conn.execute(
            """SELECT 1 FROM news_impact_alerts
                WHERE content_hash = ?
                  AND created_at >= ?
                  AND superseded_by IS NULL
                LIMIT 1""",
            (content_hash_value, cutoff),
        ).fetchone()
    return r is not None


def insert_alert(
    *,
    ticker: str,
    scope: str,
    sector: Optional[str],
    severity: str,
    recommended_action: str,
    linkage: str,
    linkage_sector: Optional[str],
    impact_summary: str,
    content_hash_value: str,
    model: Optional[str],
    meta: Dict[str, Any],
) -> int:
    """Insert a new alert and return its id."""
    from db.models import get_conn, insert_returning_id
    with get_conn() as conn:
        return insert_returning_id(
            conn,
            """INSERT INTO news_impact_alerts
                 (created_at, ticker, scope, sector, severity, recommended_action,
                  linkage, linkage_sector, impact_summary, content_hash,
                  delivered_telegram, model, meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (
                _now_iso(),
                (ticker or "").upper(),
                scope,
                sector,
                severity,
                recommended_action,
                linkage,
                linkage_sector,
                impact_summary,
                content_hash_value,
                model,
                _dumps(meta or {}),
            ),
        )


def mark_telegram_sent(alert_id: int) -> None:
    from db.models import get_conn
    with get_conn() as conn:
        conn.execute(
            "UPDATE news_impact_alerts SET delivered_telegram = 1 WHERE id = ?",
            (int(alert_id),),
        )


def fetch_alert(alert_id: int) -> Optional[Dict[str, Any]]:
    from db.models import get_conn
    with get_conn() as conn:
        r = conn.execute(
            """SELECT * FROM news_impact_alerts WHERE id = ?""",
            (int(alert_id),),
        ).fetchone()
    if not r:
        return None
    return _row_to_alert(r)


def feed_query(
    *,
    severity: Optional[List[str]] = None,
    scope: str = "BOTH",
    ticker: Optional[str] = None,
    hours: int = 72,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Filtered feed. Excludes superseded rows. Sort: severity desc then time desc."""
    from datetime import timedelta
    from db.models import get_conn

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    where = ["created_at >= ?", "superseded_by IS NULL"]
    params: List[Any] = [cutoff]

    if severity:
        sev_clean = [s for s in severity if s in ("info", "watch", "critical")]
        if sev_clean:
            placeholders = ",".join("?" for _ in sev_clean)
            where.append(f"severity IN ({placeholders})")
            params.extend(sev_clean)
    if scope in ("HOLDING", "LT_WATCH"):
        where.append("scope = ?")
        params.append(scope)
    if ticker:
        from news_impact.linkage import bare
        where.append("ticker = ?")
        params.append(bare(ticker))

    sql = (
        "SELECT * FROM news_impact_alerts "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY created_at DESC "
        "LIMIT ?"
    )
    params.append(int(limit))

    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    alerts = [_row_to_alert(r) for r in rows]
    # Secondary sort: severity desc (Python stable sort keeps time order within group).
    alerts.sort(key=lambda a: SEVERITY_RANK.get(a["severity"], 0), reverse=True)
    return alerts


def badges_query(hours: int = 72) -> Dict[str, int]:
    """Map of ``{bare_ticker: count_of_recent_non_superseded_alerts}``."""
    from datetime import timedelta
    from db.models import get_conn

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ticker, COUNT(*) AS n
                 FROM news_impact_alerts
                WHERE created_at >= ?
                  AND superseded_by IS NULL
             GROUP BY ticker""",
            (cutoff,),
        ).fetchall()
    return {r["ticker"]: int(r["n"]) for r in rows if r["ticker"]}


def _row_to_alert(r: Any) -> Dict[str, Any]:
    """Translate a DB row into the API alert dict."""
    meta = _loads(r["meta"]) or {}
    citations = meta.get("citations") or []
    reasons = meta.get("reasons") or []
    return {
        "id": int(r["id"]),
        "created_at": r["created_at"],
        "ticker": r["ticker"],
        "scope": r["scope"],
        "sector": r["sector"],
        "severity": r["severity"],
        "recommended_action": r["recommended_action"],
        "linkage": r["linkage"],
        "linkage_sector": r["linkage_sector"],
        "linkage_label": _format_linkage_label(r["linkage"], r["linkage_sector"]),
        "impact_summary": r["impact_summary"],
        "reasons": reasons,
        "citations": citations,
        "cluster_topic": meta.get("cluster_topic"),
        "confidence": meta.get("confidence"),
        "model": r["model"],
        "window_hours": meta.get("window_hours"),
        "delivered_telegram": bool(r["delivered_telegram"]),
        "meta": meta,
    }


def _format_linkage_label(linkage: Optional[str], linkage_sector: Optional[str]) -> str:
    if linkage == "DIRECT":
        return "Direct"
    if linkage == "SECTOR":
        return f"Sector: {linkage_sector}" if linkage_sector else "Sector"
    if linkage == "ANCILLARY":
        return f"Ancillary: {linkage_sector}" if linkage_sector else "Ancillary"
    return linkage or "—"


def fetch_recent_active_alerts(ticker: str, hours: int = 48) -> List[Dict[str, Any]]:
    """Fetch active (non-superseded) alerts for a ticker in the last window."""
    from datetime import timedelta
    from db.models import get_conn
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM news_impact_alerts
                WHERE ticker = ?
                  AND created_at >= ?
                  AND superseded_by IS NULL""",
            ((ticker or "").upper(), cutoff),
        ).fetchall()
    return [_row_to_alert(r) for r in rows]


def supersede_alert(old_id: int, new_id: int) -> None:
    """Mark an old alert as superseded by a new alert ID."""
    from db.models import get_conn
    with get_conn() as conn:
        conn.execute(
            "UPDATE news_impact_alerts SET superseded_by = ? WHERE id = ?",
            (int(new_id), int(old_id)),
        )


# ---------------------------------------------------------------------------
# Throttle marker in bot_control
# ---------------------------------------------------------------------------


def get_last_run_at() -> Optional[str]:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            r = conn.execute(
                "SELECT last_news_impact_at FROM bot_control WHERE id=1"
            ).fetchone()
        return r["last_news_impact_at"] if r else None
    except Exception:
        return None


def set_last_run_at_now() -> None:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE bot_control SET last_news_impact_at = ? WHERE id=1",
                (_now_iso(),),
            )
    except Exception as e:
        log.debug("[news_impact.store] set_last_run_at failed: %s", e)
