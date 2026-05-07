"""
LLM-based news sentiment scoring.

Replaces FinBERT when LLM_ENABLE_SENTIMENT is True. Claude is materially
better than FinBERT at financial nuance:

  - "Reliance Q4 earnings flat" — FinBERT scores neutral. Claude knows that
    "flat" after a tough quarter for the segment is mildly bullish vs analyst
    expectations.
  - "Hostile takeover bid for Cipla" — FinBERT sees "takeover" → positive.
    Claude knows hostile bids are typically negative for the target's price.
  - "Bharti Airtel cuts capex guidance" — FinBERT sees "cut" → negative.
    Claude knows lower capex with stable subscriber growth is positive for
    free cash flow.

Score range matches the existing engine: [-1.0, +1.0]. Multiplied by the
model's confidence, so low-conviction calls move the aggregate sentiment
less than high-conviction ones.

Caching: sentiment is a function of headline text, so we cache by sha256(text).
Same article scored across cycles costs nothing after the first call.
"""
from __future__ import annotations

import logging
from typing import Optional

from config import LLM_SENTIMENT_MODEL
from llm.client import call_json, hash_text

log = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "number",
            "description": "-1.0 (very bearish) to +1.0 (very bullish)",
        },
        "confidence": {
            "type": "number",
            "description": "0.0 (uncertain) to 1.0 (very certain)",
        },
        "reason": {
            "type": "string",
            "description": "Short reasoning (≤ 15 words)",
        },
    },
    "required": ["score", "confidence", "reason"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a senior Indian-equities analyst scoring intraday news sentiment. "
    "Consider direction (bullish/bearish for the named ticker), magnitude "
    "(big surprise vs incremental), and time-horizon (today's price action vs "
    "long-term fundamentals — favour short-term). Be calibrated: most routine "
    "news is mildly positive or mildly negative; reserve |score| > 0.7 for "
    "genuine catalysts."
)


def score_text_llm(ticker: Optional[str], title: str, summary: str = "") -> Optional[float]:
    """Score one news item with Claude. Returns [-1, +1] or None on failure.

    Caller falls back to FinBERT/VADER on None. The score is already weighted
    by confidence, so a score of 0.0 can mean either neutral OR uncertain —
    semantically equivalent for downstream aggregation.
    """
    body = f"{title}".strip()
    if summary:
        body = f"{body}\n\n{summary}"
    if not body:
        return 0.0

    cache_key = "sent_" + hash_text(f"{ticker or ''}|{body}")
    prompt = (
        f"Ticker: {ticker or '(unspecified)'}\n"
        f"Headline + summary:\n{body[:1200]}\n\n"
        "Output ONLY the JSON object."
    )

    result = call_json(
        prompt=prompt,
        schema=_SCHEMA,
        system=_SYSTEM,
        model=LLM_SENTIMENT_MODEL,
        max_tokens=200,
        cache_key=cache_key,
    )
    if result is None:
        return None

    score = float(result.get("score", 0.0))
    confidence = float(result.get("confidence", 0.5))
    return max(-1.0, min(1.0, score * confidence))
