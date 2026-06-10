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

from config import ENABLE_FINBERT, LLM_ENABLE_SENTIMENT, SENTIMENT_ENGINE
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
            # Newest first so the LLM budget is spent on the freshest articles.
            rows = conn.execute(
                "SELECT id, title, summary FROM news WHERE processed=0 ORDER BY id DESC"
            ).fetchall()

        if not rows:
            log.info("scored 0 news items")
            return 0

        texts = [f"{r['title']}. {r['summary'] or ''}" for r in rows]

        # LLM scoring runs in chunks of _LLM_BATCH_MAX items per call instead
        # of abandoning the LLM entirely when a big scrape lands (the old
        # behaviour silently downgraded 91 fresh articles to VADER). A per-run
        # cap bounds the worst-case token spend; anything beyond it — and any
        # chunk that fails (rate limit / circuit breaker) — falls back to
        # FinBERT/VADER so nothing is left unscored.
        _LLM_BATCH_MAX = 20
        try:
            from config import LLM_SENTIMENT_MAX_ITEMS_PER_RUN as _LLM_RUN_CAP
        except ImportError:
            _LLM_RUN_CAP = 120

        scores: list = [None] * len(rows)
        if LLM_ENABLE_SENTIMENT:
            from llm.sentiment import score_batch_llm  # lazy — keeps dep optional
            llm_budget = min(len(rows), _LLM_RUN_CAP)
            llm_failed = False
            for start in range(0, llm_budget, _LLM_BATCH_MAX):
                chunk = rows[start:start + _LLM_BATCH_MAX]
                llm_items = [
                    {"ticker": "", "title": r["title"], "summary": r["summary"] or ""}
                    for r in chunk
                ]
                chunk_scores = score_batch_llm(llm_items)
                if chunk_scores is None or len(chunk_scores) != len(chunk):
                    log.info("sentiment: LLM chunk %d-%d failed — remaining items "
                             "fall back to FinBERT/VADER", start, start + len(chunk))
                    llm_failed = True
                    break
                scores[start:start + len(chunk)] = chunk_scores
            llm_scored = sum(1 for s in scores if s is not None)
            if llm_scored:
                log.info("sentiment: LLM scored %d/%d items in %d-item chunks%s",
                         llm_scored, len(rows), _LLM_BATCH_MAX,
                         " (run cap reached)" if not llm_failed and llm_scored < len(rows) else "")

        # Fallback for whatever the LLM didn't cover.
        missing_idx = [i for i, s in enumerate(scores) if s is None]
        if missing_idx:
            fallback = _score_batch([texts[i] for i in missing_idx])
            for i, s in zip(missing_idx, fallback):
                scores[i] = s

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
    Rolling time-decayed sentiment for a ticker, clipped to [-1, 1].

    Each article's weight halves every SENTIMENT_HALF_LIFE_HOURS, so a fresh
    headline dominates a stale one instead of averaging equally with it
    (weight = 0.5 ** (age_hours / half_life)).
    """
    # Compute cutoff in Python so the WHERE clause is dialect-agnostic
    # (SQLite's datetime('now', '-X hours') is not valid Postgres).
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).isoformat()
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

    try:
        from config import SENTIMENT_HALF_LIFE_HOURS as _half_life
    except ImportError:
        _half_life = 72.0

    weighted_sum = 0.0
    weight_total = 0.0
    for r in rows:
        score = float(r["sentiment"])
        weight = 1.0
        try:
            ts = datetime.fromisoformat(str(r["ts"]))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = max(0.0, (now - ts).total_seconds() / 3600.0)
            weight = 0.5 ** (age_hours / max(_half_life, 1e-9))
        except (ValueError, TypeError):
            pass  # unparseable ts → full weight
        weighted_sum += score * weight
        weight_total += weight

    if weight_total <= 0:
        return 0.0
    avg = weighted_sum / weight_total
    return max(-1.0, min(1.0, avg))


if __name__ == "__main__":
    print(score_text("Reliance posts record profit beating estimates on strong retail."))
    print(score_text("TCS slips as weak outlook spooks investors amid macro concerns."))
