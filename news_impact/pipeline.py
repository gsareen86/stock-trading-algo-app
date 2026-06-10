"""Orchestration for the news-impact pipeline.

Public entry points:
  * :func:`maybe_run` — called every scheduler tick. Short-circuits when
    inside the throttle window (default 240 min) or when the world is empty.
  * :func:`run_for_all` — the full pass. Tags untagged recent news for
    sectors, then for every (holding + LT) ticker computes candidate
    articles, deterministically clusters them, calls the LLM per cluster,
    persists unique-content alerts, and fires Telegram for critical
    HOLDING alerts (capped per run).

All LLM calls go through :mod:`news_impact.llm_tasks` which wraps
:func:`llm.client.call_json` for observability + cache.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Config. The pass throttle is configurable (NEWS_IMPACT_THROTTLE_MIN); the
# per-ticker new-article gate below keeps the lower throttle cheap — tickers
# with no fresh news since the previous pass are skipped entirely, and
# re-analysed clusters resolve from the LLM disk cache anyway.
try:
    from config import NEWS_IMPACT_THROTTLE_MIN as DEFAULT_THROTTLE_MIN
except ImportError:
    DEFAULT_THROTTLE_MIN = 240
DEFAULT_WINDOW_HOURS = 48
DEFAULT_SECTOR_TAG_BATCH = 200
DEFAULT_TELEGRAM_CAP = 5

# In-process lock so two scheduler ticks can't both run the heavy pass.
_RUN_LOCK = threading.Lock()
# In-process sentinel — backed by bot_control.last_news_impact_at for
# cross-process visibility.
_last_run_at_iso: Optional[str] = None


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _within_throttle(last_iso: Optional[str], minutes: int) -> bool:
    last = _parse_iso(last_iso)
    if last is None:
        return False
    return (_now_utc() - last) < timedelta(minutes=minutes)


def _news_in_window(window_hours: int) -> int:
    from db.models import get_conn
    cutoff = (_now_utc() - timedelta(hours=window_hours)).isoformat()
    try:
        with get_conn() as conn:
            r = conn.execute(
                "SELECT COUNT(*) AS n FROM news WHERE ts >= ?", (cutoff,)
            ).fetchone()
        return int(r["n"] or 0)
    except Exception:
        return 0


def _should_run(force: bool, window_hours: int, throttle_min: int) -> Tuple[bool, str]:
    if force:
        return True, "force"
    global _last_run_at_iso
    from news_impact.store import get_last_run_at

    last_iso = _last_run_at_iso or get_last_run_at()
    if _within_throttle(last_iso, throttle_min):
        return False, f"throttle ({throttle_min}m window not elapsed)"

    from news_impact.linkage import holdings_set, lt_set
    if not holdings_set() and not lt_set():
        return False, "no holdings and empty LT watchlist"

    if _news_in_window(window_hours) == 0:
        return False, f"no news in last {window_hours}h"

    return True, "ok"


# ---------------------------------------------------------------------------
# Clustering — deterministic, no LLM
# ---------------------------------------------------------------------------


_WORD_RE = re.compile(r"[a-z0-9]+")


def _canonical_title(title: str) -> str:
    """Lowercase + first 8 word tokens, joined by space. Strips punctuation /
    digits so e.g. "Tata Motors Q4 results beat estimates by 12%" and "Tata
    Motors Q4 results beat estimates 12pct" collapse to the same key."""
    words = _WORD_RE.findall((title or "").lower())
    words = [w for w in words if not w.isdigit()]
    return " ".join(words[:8])


def _topic_label(canonical_key: str) -> str:
    return " ".join(w.capitalize() for w in (canonical_key or "").split())[:80] or "Untitled cluster"


def cluster_articles(articles: List[Dict]) -> List[Tuple[str, List[Dict]]]:
    """Group articles by canonical title key. Returns ``[(topic_label, [articles])]``
    in arbitrary but deterministic order (sorted by topic label)."""
    by_key: Dict[str, List[Dict]] = defaultdict(list)
    for a in articles:
        key = _canonical_title(a.get("title") or "")
        by_key[key or "_misc"].append(a)
    out: List[Tuple[str, List[Dict]]] = []
    for key in sorted(by_key.keys()):
        out.append((_topic_label(key), by_key[key]))
    return out


# ---------------------------------------------------------------------------
# Candidate article assembly per ticker
# ---------------------------------------------------------------------------


def _fetch_recent_news(window_hours: int) -> List[Dict]:
    from db.models import get_conn
    cutoff = (_now_utc() - timedelta(hours=window_hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, ts, source, title, summary, url, tickers
                 FROM news
                WHERE ts >= ?
             ORDER BY ts DESC""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def _candidate_articles_for_ticker(
    ticker: str,
    ticker_sector: Optional[str],
    news_rows: List[Dict],
    sector_tags: Dict[int, Dict],
) -> List[Dict]:
    """Return article dicts with linkage attached. Filters out non-relevant rows."""
    from news_impact.linkage import classify_linkage, parse_tickers_csv

    out: List[Dict] = []
    for n in news_rows:
        article_tickers = parse_tickers_csv(n.get("tickers"))
        tag = sector_tags.get(int(n["id"])) if "id" in n else None
        primary_sec = tag["primary_sector"] if tag else None
        ancillary_secs = tag["ancillary_sectors"] if tag else []

        linkage, linkage_sector = classify_linkage(
            ticker, article_tickers, primary_sec, ancillary_secs, ticker_sector
        )
        if not linkage:
            continue
        out.append({
            "news_id": int(n["id"]),
            "ts": n.get("ts"),
            "source": n.get("source"),
            "title": n.get("title"),
            "summary": n.get("summary"),
            "url": n.get("url"),
            "linkage": linkage,
            "linkage_sector": linkage_sector,
        })
    return out


def _dominant_linkage(articles: List[Dict]) -> Tuple[str, Optional[str]]:
    """Pick the strongest linkage in a cluster for prompt/persistence purposes."""
    rank = {"DIRECT": 3, "SECTOR": 2, "ANCILLARY": 1}
    best = max(articles, key=lambda a: rank.get(a.get("linkage", ""), 0))
    return best["linkage"], best.get("linkage_sector")


# ---------------------------------------------------------------------------
# Sector tagging pass
# ---------------------------------------------------------------------------


def tag_untagged_news(limit: int = DEFAULT_SECTOR_TAG_BATCH) -> int:
    """Sector-tag recent news rows that lack a tag yet.

    Optimization: when an article already has a single resolvable ticker, we
    derive its primary sector from the ticker→sector map and SKIP the LLM
    call. Articles with zero / multiple / unresolvable tickers go through
    the LLM tagger.

    Returns the number of rows tagged this pass.
    """
    from news_impact.store import untagged_recent_news, upsert_sector_tag
    from news_impact.linkage import build_ticker_sector_map, parse_tickers_csv
    from news_impact.llm_tasks import tag_article_sector

    rows = untagged_recent_news(window_hours=72, limit=limit)
    if not rows:
        return 0

    sector_map = build_ticker_sector_map()
    tagged = 0

    for r in rows:
        article_tickers = parse_tickers_csv(r.get("tickers"))
        resolved = {sector_map.get(t) for t in article_tickers if sector_map.get(t)}
        resolved.discard(None)

        if len(resolved) == 1:
            # Trivial: single agreed sector → no LLM call.
            primary = next(iter(resolved))
            upsert_sector_tag(
                int(r["id"]), primary, [], "derived from sole tagged ticker",
                model=None, confidence=1.0,
            )
            tagged += 1
            continue

        # LLM path
        result = tag_article_sector(r)
        if result is None:
            continue
        from config import LLM_VETO_MODEL
        upsert_sector_tag(
            int(r["id"]),
            result.get("primary_sector"),
            result.get("ancillary_sectors") or [],
            result.get("why_note"),
            model=LLM_VETO_MODEL,
            confidence=result.get("confidence"),
        )
        tagged += 1
    return tagged


# ---------------------------------------------------------------------------
# Context helpers — position info, research read
# ---------------------------------------------------------------------------


def _position_context(ticker: str) -> Optional[Dict]:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            r = conn.execute(
                """SELECT entry_price, quantity, hard_stop, days_held, pnl_pct
                     FROM pos_positions
                    WHERE ticker = ? AND status='OPEN'
                    ORDER BY entry_date DESC
                    LIMIT 1""",
                (ticker.upper(),),
            ).fetchone()
        if not r:
            return None
        return {
            "entry_price": r["entry_price"],
            "quantity": r["quantity"],
            "hard_stop": r["hard_stop"],
            "days_held": r["days_held"],
            "pnl_pct": r["pnl_pct"],
        }
    except Exception:
        return None


def _research_context(ticker: str) -> Optional[Dict]:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            r = conn.execute(
                """SELECT verdict, outlook, thesis, recommendation
                     FROM pos_research
                    WHERE ticker = ?
                    ORDER BY researched_at DESC
                    LIMIT 1""",
                (ticker.upper(),),
            ).fetchone()
        if not r:
            return None
        return {
            "verdict": r["verdict"], "outlook": r["outlook"],
            "thesis": r["thesis"], "recommendation": r["recommendation"],
        }
    except Exception:
        return None


def _last_close(ticker: str) -> Optional[float]:
    try:
        from data.fetcher import latest_price
        return latest_price(ticker)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def maybe_run(triggered_by: str = "scheduler",
              window_hours: int = DEFAULT_WINDOW_HOURS,
              throttle_min: int = DEFAULT_THROTTLE_MIN) -> Dict:
    """Conditionally run the full pass. Safe to call every scheduler tick —
    most ticks bail in microseconds via the throttle."""
    ok, reason = _should_run(force=False, window_hours=window_hours, throttle_min=throttle_min)
    if not ok:
        log.debug("[news_impact] skip: %s", reason)
        return {"ran": False, "reason": reason}
    return run_for_all(force=True, triggered_by=triggered_by, window_hours=window_hours)


def run_for_all(force: bool = False,
                triggered_by: str = "manual",
                window_hours: int = DEFAULT_WINDOW_HOURS,
                throttle_min: int = DEFAULT_THROTTLE_MIN) -> Dict:
    """The heavy pass: sector-tag recent news, then assess impact per ticker."""
    if not _RUN_LOCK.acquire(blocking=False):
        log.info("[news_impact] another pass in flight — skipping")
        return {"ran": False, "reason": "another pass in flight"}

    try:
        if not force:
            ok, reason = _should_run(force=False, window_hours=window_hours, throttle_min=throttle_min)
            if not ok:
                return {"ran": False, "reason": reason}

        log.info("[news_impact] starting pass (triggered_by=%s, window=%dh)",
                 triggered_by, window_hours)

        # 1. Sector-tag recent news.
        try:
            tagged_count = tag_untagged_news()
            log.info("[news_impact] sector-tagged %d new articles", tagged_count)
        except Exception as e:
            log.warning("[news_impact] sector tagging failed: %s", e)
            tagged_count = 0

        # 2. Build universe.
        from news_impact.linkage import holdings_set, lt_set, build_ticker_sector_map
        holdings = holdings_set()
        lt = lt_set()
        union = holdings | lt
        sector_map = build_ticker_sector_map()

        if not union:
            log.info("[news_impact] no holdings / LT — done")
            _mark_complete()
            return {"ran": True, "alerts_created": 0, "tickers_scanned": 0,
                    "tagged": tagged_count, "reason": "no_universe"}

        # 3. Pull all candidate news once + bulk-load sector tags for it.
        news_rows = _fetch_recent_news(window_hours=window_hours)
        from news_impact.store import fetch_sector_tags_bulk, get_last_run_at
        sector_tags = fetch_sector_tags_bulk([int(n["id"]) for n in news_rows])

        # Per-ticker new-article gate: a ticker is only re-analysed when at
        # least one of its candidate articles is newer than the previous
        # completed pass. Manual runs bypass the gate (full re-pass).
        prev_pass_iso = None if triggered_by == "manual" else (
            _last_run_at_iso or get_last_run_at()
        )

        # 4. Per ticker.
        alerts_created = 0
        telegram_sent = 0
        tickers_skipped_no_new = 0
        for ticker in sorted(union):
            try:
                sector = sector_map.get(ticker)
                candidates = _candidate_articles_for_ticker(
                    ticker, sector, news_rows, sector_tags
                )
                if not candidates:
                    continue
                if prev_pass_iso and not any(
                    str(a.get("ts") or "") > prev_pass_iso for a in candidates
                ):
                    tickers_skipped_no_new += 1
                    continue
                scope = "HOLDING" if ticker in holdings else "LT_WATCH"
                pos_ctx = _position_context(ticker) if scope == "HOLDING" else None
                res_ctx = _research_context(ticker)
                last_px = _last_close(ticker)

                clusters = cluster_articles(candidates)
                for cluster_topic, cluster_articles_list in clusters:
                    n_new, n_telegram = _process_cluster(
                        ticker=ticker, scope=scope, sector=sector,
                        cluster_topic=cluster_topic, articles=cluster_articles_list,
                        position_ctx=pos_ctx, research_ctx=res_ctx,
                        last_close=last_px, window_hours=window_hours,
                        telegram_budget_left=DEFAULT_TELEGRAM_CAP - telegram_sent,
                    )
                    alerts_created += n_new
                    telegram_sent += n_telegram
            except Exception as e:
                log.warning("[news_impact] ticker %s failed: %s", ticker, e)

        _mark_complete()
        log.info("[news_impact] done: %d new alerts, %d telegram, %d tickers skipped (no new articles)",
                 alerts_created, telegram_sent, tickers_skipped_no_new)
        return {
            "ran": True,
            "alerts_created": alerts_created,
            "tickers_scanned": len(union),
            "tickers_skipped_no_new": tickers_skipped_no_new,
            "telegram_sent": telegram_sent,
            "tagged": tagged_count,
            "reason": "ok",
        }
    finally:
        _RUN_LOCK.release()


def _mark_complete() -> None:
    global _last_run_at_iso
    _last_run_at_iso = _now_utc().isoformat()
    from news_impact.store import set_last_run_at_now
    set_last_run_at_now()


def _process_cluster(
    *,
    ticker: str,
    scope: str,
    sector: Optional[str],
    cluster_topic: str,
    articles: List[Dict],
    position_ctx: Optional[Dict],
    research_ctx: Optional[Dict],
    last_close: Optional[float],
    window_hours: int,
    telegram_budget_left: int,
) -> Tuple[int, int]:
    """Run the LLM on one cluster, persist (de-duped), notify if critical.
    Returns ``(alerts_created, telegram_sent)``."""
    from news_impact.llm_tasks import analyse_impact
    from news_impact.store import (
        content_hash, insert_alert, recent_hash_exists, mark_telegram_sent,
    )
    from config import LLM_DEFAULT_MODEL

    linkage, linkage_sector = _dominant_linkage(articles)
    result = analyse_impact(
        ticker=ticker, sector=sector, last_close=last_close,
        position_ctx=position_ctx, research_ctx=research_ctx,
        linkage=linkage, cluster_topic=cluster_topic, articles=articles,
    )
    if not result:
        return (0, 0)

    citations = [{
        "news_id": a["news_id"], "title": a.get("title"), "url": a.get("url"),
        "source": a.get("source"), "ts": a.get("ts"),
    } for a in articles if a.get("news_id") in result["cited_news_ids"]] or [{
        "news_id": a["news_id"], "title": a.get("title"), "url": a.get("url"),
        "source": a.get("source"), "ts": a.get("ts"),
    } for a in articles]

    news_ids = [c["news_id"] for c in citations]
    h = content_hash(
        ticker=ticker, severity=result["severity"],
        recommended_action=result["recommended_action"],
        news_ids=news_ids, impact_summary=result["impact_summary"],
    )
    if recent_hash_exists(h, hours=24):
        return (0, 0)

    meta = {
        "reasons": result["reasons"],
        "citations": citations,
        "news_ids": news_ids,
        "cluster_topic": cluster_topic,
        "confidence": result.get("confidence"),
        "window_hours": window_hours,
    }
    alert_id = insert_alert(
        ticker=ticker, scope=scope, sector=sector,
        severity=result["severity"],
        recommended_action=result["recommended_action"],
        linkage=linkage, linkage_sector=linkage_sector,
        impact_summary=result["impact_summary"],
        content_hash_value=h,
        model=LLM_DEFAULT_MODEL,
        meta=meta,
    )

    telegram_sent = 0
    if (result["severity"] == "critical"
            and scope == "HOLDING"
            and telegram_budget_left > 0):
        try:
            from positional.alerts import send_news_impact_alert
            sent = send_news_impact_alert({
                "ticker": ticker,
                "severity": result["severity"],
                "recommended_action": result["recommended_action"],
                "impact_summary": result["impact_summary"],
                "linkage_label": (
                    f"Direct" if linkage == "DIRECT"
                    else f"{linkage.title()}: {linkage_sector or ''}".strip(": ")
                ),
            })
            if sent:
                mark_telegram_sent(alert_id)
                telegram_sent = 1
        except Exception as e:
            log.warning("[news_impact] telegram failed for %s: %s", ticker, e)

    return (1, telegram_sent)
