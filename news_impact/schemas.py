"""JSON schemas + prompt builders for the news-impact LLM tasks.

Two LLM calls live in :mod:`news_impact.llm_tasks`:

  1. ``tag_article_sector(article)`` — classify a single article into a
     primary sector and 0-3 ancillary sectors. Cheap model.
  2. ``analyse_impact(ticker, cluster_articles, ...)`` — for a single ticker
     (holding or LT_WATCH), assess severity / recommended action given the
     candidate articles. Default model.

This file is pure functions and constants — no LLM client import. That makes
it trivial to unit-test prompt construction.

Note: the LLM does NOT return a ``cluster_topic`` — that's computed
deterministically by :func:`news_impact.pipeline._dedup_cluster_topic`. Keeping
``cluster_topic`` out of the LLM output means we can supersede alerts purely
on the model's classification, not on stylistic topic-string drift.
"""
from __future__ import annotations

from typing import Iterable


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

SECTOR_TAG_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["primary_sector", "ancillary_sectors", "why_note", "confidence"],
    "properties": {
        "primary_sector": {
            "type": ["string", "null"],
            "description": "Canonical sector the article most directly concerns "
                           "(e.g. 'Auto OEM', 'Banks - Private', 'IT Services'). "
                           "Null if the article is macro-only / non-sector.",
        },
        "ancillary_sectors": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
            "description": "Other sectors materially exposed via supply chain, "
                           "demand linkage or input costs. Empty array if none.",
        },
        "why_note": {
            "type": "string",
            "maxLength": 240,
            "description": "One-sentence reason the classification was chosen.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
}


IMPACT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "severity",
        "recommended_action",
        "impact_summary",
        "reasons",
        "cited_news_ids",
        "confidence",
    ],
    "properties": {
        "severity": {
            "type": "string",
            "enum": ["info", "watch", "critical"],
        },
        "recommended_action": {
            "type": "string",
            "enum": ["HOLD", "WATCH", "REVIEW_EXIT"],
        },
        "impact_summary": {
            "type": "string",
            "maxLength": 600,
            "description": "2-4 sentence executive-style summary of how this "
                           "news bundle affects the ticker's thesis or risk.",
        },
        "reasons": {
            "type": "array",
            "items": {"type": "string", "maxLength": 200},
            "maxItems": 6,
            "description": "Bulleted causal reasons (each <= 200 chars).",
        },
        "cited_news_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "News IDs actually used in this assessment (subset "
                           "of the inputs).",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builders
# ─────────────────────────────────────────────────────────────────────────────

_SECTOR_SYSTEM = (
    "You classify Indian-equity news articles into sectors so a portfolio "
    "monitor can spot indirect (sector-level + ancillary) exposure to a "
    "shortlist of stocks. Output strict JSON only."
)


def build_sector_prompt(article: dict) -> tuple[str, str]:
    """Return (system, prompt) for the sector-tagger call.

    ``article`` is a dict with keys ``title``, ``summary``, ``source``,
    ``tickers`` (comma-string), ``ts``.
    """
    title = (article.get("title") or "").strip()
    summary = (article.get("summary") or "").strip()
    source = (article.get("source") or "").strip()
    tickers = (article.get("tickers") or "").strip()
    ts = (article.get("ts") or "").strip()

    prompt = (
        "Classify the article below.\n\n"
        f"Source: {source}\n"
        f"Published: {ts}\n"
        f"Mentioned tickers (raw): {tickers or '—'}\n\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n\n"
        "Return JSON with keys:\n"
        "  primary_sector      — single canonical Indian-equity sector name, "
        "or null if non-sector / pure-macro.\n"
        "  ancillary_sectors   — up to 4 sectors with material indirect exposure.\n"
        "  why_note            — one sentence, <=240 chars.\n"
        "  confidence          — 0.0-1.0.\n"
    )
    return _SECTOR_SYSTEM, prompt


_IMPACT_SYSTEM = (
    "You are a portfolio risk analyst monitoring an Indian-equity shortlist. "
    "For each ticker you receive a bundle of recent articles (possibly direct, "
    "sector-level or ancillary-sector linkage). Decide severity, recommended "
    "action and a concise summary tied to the position context. Output "
    "strict JSON only."
)


def build_impact_prompt(
    *,
    ticker: str,
    sector: str | None,
    last_close: float | None,
    position_ctx: dict | None,
    research_ctx: dict | None,
    linkage: str,
    cluster_topic: str,
    articles: Iterable[dict],
) -> tuple[str, str]:
    """Return (system, prompt) for the impact-analyser call.

    ``articles`` is a list of dicts (each ``{news_id, title, summary, source,
    ts, url, linkage, linkage_sector}``). Linkage on the prompt is informational
    only — the model must judge severity from the article content.
    """
    art_lines: list[str] = []
    for a in articles:
        art_lines.append(
            f"- id={a.get('news_id')} | linkage={a.get('linkage')} "
            f"| sector={a.get('linkage_sector') or '—'} | {a.get('ts') or '—'} "
            f"| {a.get('source') or '—'}\n"
            f"  title: {(a.get('title') or '').strip()}\n"
            f"  summary: {((a.get('summary') or '').strip())[:500]}"
        )
    articles_block = "\n".join(art_lines) if art_lines else "(no articles)"

    pos_block = "—"
    if position_ctx:
        pos_block = (
            f"entry={position_ctx.get('entry_price')}, "
            f"qty={position_ctx.get('quantity')}, "
            f"hard_stop={position_ctx.get('hard_stop')}, "
            f"days_held={position_ctx.get('days_held')}, "
            f"pnl_pct≈{position_ctx.get('pnl_pct')}"
        )

    research_block = "—"
    if research_ctx:
        research_block = (
            f"verdict={research_ctx.get('verdict')}, "
            f"outlook={research_ctx.get('outlook')}, "
            f"thesis={(research_ctx.get('thesis') or '')[:300]}"
        )

    prompt = (
        f"Ticker: {ticker}\n"
        f"Sector: {sector or '—'}\n"
        f"Last close: {last_close if last_close is not None else '—'}\n"
        f"Dominant linkage in this bundle: {linkage}\n"
        f"Cluster topic (deterministic): {cluster_topic}\n\n"
        f"Position context: {pos_block}\n"
        f"Research context: {research_block}\n\n"
        f"Recent articles (window-bounded, may include direct / sector / ancillary):\n"
        f"{articles_block}\n\n"
        "Decide:\n"
        "  severity            — info | watch | critical\n"
        "  recommended_action  — HOLD | WATCH | REVIEW_EXIT\n"
        "  impact_summary      — 2-4 sentences, executive-style.\n"
        "  reasons             — up to 6 short bullets explaining the call.\n"
        "  cited_news_ids      — subset of the article ids actually used.\n"
        "  confidence          — 0.0-1.0.\n\n"
        "Rules:\n"
        "  * Use REVIEW_EXIT only on critical thesis-breaking news for HOLDING.\n"
        "  * Ancillary-only bundles should rarely exceed 'watch'.\n"
        "  * If articles are weak / off-topic, return severity='info', action='HOLD'.\n"
    )
    return _IMPACT_SYSTEM, prompt
