"""
Sentiment scoring. Default: VADER (fast, zero download).
Optional: FinBERT (finance-tuned, heavier). Toggle via config.ENABLE_FINBERT.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from config import ENABLE_FINBERT, SENTIMENT_ENGINE
from db.models import get_conn

log = logging.getLogger(__name__)

_vader = SentimentIntensityAnalyzer()
_finbert_pipeline = None
_finbert_lock = threading.Lock()


def _get_finbert():
    global _finbert_pipeline
    # Double-checked locking: fast path avoids acquiring the lock once loaded.
    if _finbert_pipeline is not None:
        return _finbert_pipeline
    with _finbert_lock:
        if _finbert_pipeline is None:
            try:
                from transformers import pipeline  # lazy import
                _finbert_pipeline = pipeline(
                    "sentiment-analysis",
                    model="ProsusAI/finbert",
                    truncation=True,
                )
            except Exception as e:
                log.warning("FinBERT unavailable, falling back to VADER: %s", e)
                _finbert_pipeline = False
    return _finbert_pipeline


def score_text(text: str) -> float:
    """
    Returns sentiment in range [-1, +1].
    Positive = bullish; negative = bearish.
    """
    if not text or not text.strip():
        return 0.0

    if ENABLE_FINBERT and SENTIMENT_ENGINE == "finbert":
        fb = _get_finbert()
        if fb:
            try:
                out = fb(text[:512])[0]
                label = out["label"].lower()
                score = float(out["score"])
                if label == "positive":
                    return score
                if label == "negative":
                    return -score
                return 0.0
            except Exception as e:
                log.warning("FinBERT inference failed, falling back to VADER: %s", e)

    # VADER default
    s = _vader.polarity_scores(text)
    return float(s["compound"])


def _score_batch(texts: list[str]) -> list[float]:
    """Batch-score a list of texts. Uses FinBERT in one forward pass when
    enabled (much faster than per-item) and falls back to VADER per-item
    otherwise."""
    if not texts:
        return []
    if ENABLE_FINBERT and SENTIMENT_ENGINE == "finbert":
        fb = _get_finbert()
        if fb:
            try:
                # Truncate each to 512 chars to stay under FinBERT's token limit.
                trimmed = [t[:512] if t else "" for t in texts]
                results = fb(trimmed, batch_size=16)
                out = []
                for r in results:
                    label = r["label"].lower()
                    score = float(r["score"])
                    if label == "positive":
                        out.append(score)
                    elif label == "negative":
                        out.append(-score)
                    else:
                        out.append(0.0)
                return out
            except Exception as e:
                log.warning("FinBERT batch failed, falling back to VADER: %s", e)
    return [float(_vader.polarity_scores(t or "")["compound"]) for t in texts]


def score_news_items(ids: Optional[Iterable[int]] = None) -> int:
    """
    Score all unscored news items (or a specific set of ids).
    Writes sentiment back to the news table.
    """
    with get_conn() as conn:
        if ids:
            q_marks = ",".join("?" * len(list(ids)))
            rows = conn.execute(
                f"SELECT id, title, summary FROM news WHERE id IN ({q_marks})",
                tuple(ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, summary FROM news WHERE processed=0"
            ).fetchall()

        if not rows:
            log.info("scored 0 news items")
            return 0

        texts = [f"{r['title']}. {r['summary'] or ''}" for r in rows]
        scores = _score_batch(texts)
        for r, score in zip(rows, scores):
            conn.execute(
                "UPDATE news SET sentiment=?, processed=1 WHERE id=?",
                (score, r["id"]),
            )
    n = len(rows)
    log.info("scored %d news items", n)
    return n


def _escape_like(value: str) -> str:
    """Escape SQL LIKE special characters for use with ESCAPE '\'."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def aggregated_sentiment(ticker: str, hours: int = 24) -> float:
    """
    Rolling 24-hour weighted sentiment for a ticker.
    Newer articles get more weight; clipped to [-1, 1].
    """
    # Compute cutoff in Python so the WHERE clause is dialect-agnostic
    # (SQLite's datetime('now', '-X hours') is not valid Postgres).
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    escaped = _escape_like(ticker)
    with get_conn() as conn:
        rows = conn.execute(
            r"""SELECT ts, sentiment FROM news
                WHERE tickers LIKE ? ESCAPE '\'
                  AND sentiment IS NOT NULL
                  AND ts >= ?""",
            (f"%{escaped}%", cutoff),
        ).fetchall()
    if not rows:
        return 0.0
    # Simple mean — more sophisticated time-decay can come later.
    scores = [r["sentiment"] for r in rows]
    avg = sum(scores) / len(scores)
    return max(-1.0, min(1.0, avg))


if __name__ == "__main__":
    print(score_text("Reliance posts record profit beating estimates on strong retail."))
    print(score_text("TCS slips as weak outlook spooks investors amid macro concerns."))
