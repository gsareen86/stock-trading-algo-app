"""Two LLM tasks used by the news-impact pipeline.

Both go through :func:`llm.client.call_json` so observability + circuit-
breaker behaviour are inherited for free. Both pass ``cache_key=`` for
natural request deduplication.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


def _h(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]


def tag_article_sector(article: Dict) -> Optional[Dict]:
    """LLM-classify one article into primary + ancillary sectors.

    Returns ``{primary_sector, ancillary_sectors, why_note, confidence}`` or
    ``None`` on any failure.
    """
    from llm.client import call_json
    from config import LLM_VETO_MODEL
    from news_impact.schemas import build_sector_prompt, SECTOR_TAG_SCHEMA

    system, prompt = build_sector_prompt(article)
    key = f"news_impact_sector::{_h(article.get('title') or '')}::{_h(article.get('summary') or '')}"

    result = call_json(
        prompt=prompt,
        schema=SECTOR_TAG_SCHEMA,
        system=system,
        model=LLM_VETO_MODEL,
        max_tokens=256,
        cache_key=key,
        caller="news_impact_sector",
    )
    if result is None:
        return None
    # Defensive shape check.
    if not isinstance(result, dict):
        log.debug("sector tagger returned non-dict: %r", result)
        return None
    return {
        "primary_sector": result.get("primary_sector"),
        "ancillary_sectors": [
            s for s in (result.get("ancillary_sectors") or []) if isinstance(s, str)
        ],
        "why_note": (result.get("why_note") or "")[:240],
        "confidence": result.get("confidence"),
    }


def analyse_impact(
    *,
    ticker: str,
    sector: Optional[str],
    last_close: Optional[float],
    position_ctx: Optional[Dict],
    research_ctx: Optional[Dict],
    linkage: str,
    cluster_topic: str,
    articles: List[Dict],
) -> Optional[Dict]:
    """LLM impact assessment for one (ticker, cluster). Returns the parsed
    dict or ``None`` on failure."""
    from llm.client import call_json
    from config import LLM_DEFAULT_MODEL
    from news_impact.schemas import build_impact_prompt, IMPACT_SCHEMA

    if not articles:
        # Should never get here — pipeline guards — but be defensive.
        return None

    system, prompt = build_impact_prompt(
        ticker=ticker,
        sector=sector,
        last_close=last_close,
        position_ctx=position_ctx,
        research_ctx=research_ctx,
        linkage=linkage,
        cluster_topic=cluster_topic,
        articles=articles,
    )

    # Cache key bundles ticker + the sorted news ids so identical inputs cache.
    ids = sorted(int(a.get("news_id") or 0) for a in articles)
    key = f"news_impact_assess::{ticker.upper()}::{linkage}::" + ",".join(str(i) for i in ids)

    result = call_json(
        prompt=prompt,
        schema=IMPACT_SCHEMA,
        system=system,
        model=LLM_DEFAULT_MODEL,
        max_tokens=768,
        cache_key=key,
        caller="news_impact_assess",
    )
    if result is None or not isinstance(result, dict):
        return None
    # Defensive: ensure required keys present + types coerced.
    sev = result.get("severity")
    act = result.get("recommended_action")
    if sev not in ("info", "watch", "critical") or act not in ("HOLD", "WATCH", "REVIEW_EXIT"):
        log.debug("impact analyser returned invalid enums: %r / %r", sev, act)
        return None
    reasons = [r for r in (result.get("reasons") or []) if isinstance(r, str)][:6]
    try:
        cited_ids = [int(x) for x in (result.get("cited_news_ids") or [])]
    except Exception:
        cited_ids = []
    return {
        "severity": sev,
        "recommended_action": act,
        "impact_summary": (result.get("impact_summary") or "").strip(),
        "reasons": reasons,
        "cited_news_ids": cited_ids,
        "confidence": result.get("confidence"),
    }
