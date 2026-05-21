"""
Positional LLM Research & Analysis Module.

Runs candidate stocks from the EOD scan through the local Ollama LLM provider
(or OpenRouter/Anthropic if configured) for comprehensive fundamental, technical,
and market volatility (India VIX) analysis. 

Acts as a pre-trade veto gate to filter out false breakouts and high-risk setups.
"""
from __future__ import annotations

import logging
from typing import Optional

from config import (
    POSITIONAL_LLM_RESEARCH_ENABLED,
    LLM_VETO_MODEL,
)
from llm.client import call_json
from db.models import get_conn

log = logging.getLogger(__name__)

# Strict JSON Schema for LLM Response
_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["PROCEED", "REDUCE", "SKIP"],
            "description": "PROCEED: strong breakout and safe; REDUCE: high-risk/marginal (50% size); SKIP: high probability of failure (do not buy)"
        },
        "reason": {
            "type": "string",
            "description": "Short justification (<= 25 words) of the verdict based on VCP base quality, growth metrics, and India VIX context."
        },
        "confidence": {
            "type": "number",
            "description": "Confidence level between 0.0 (low) and 1.0 (high)"
        }
    },
    "required": ["verdict", "reason", "confidence"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are a strict, senior positional equity research officer specializing in "
    "Mark Minervini's Volatility Contraction Pattern (VCP) strategy for Indian equities.\n"
    "Your job is to veto low-probability breakouts, not generate them. Be conservative.\n\n"
    "Trade Rules:\n"
    "  • PROCEED: Strong structural base tightening (VCP), solid growth, low debt, stable market.\n"
    "  • REDUCE: Plausible setup but has a minor issue (e.g. slightly high PE, high VIX, or moderate growth). Capital risk is buffered by taking 50% size.\n"
    "  • SKIP: High-risk setup (e.g. excessive leverage D/E > 1, no sales growth, no clear VCP contraction, or extremely high VIX > 20 triggering broad market false breakouts).\n"
    "Default to PROCEED only if both technical base structure and fundamentals are robust. Veto if VIX is high."
)


def run_positional_llm_research(candidates: list[dict], vix_value: float = 0.0) -> list[dict]:
    """
    Evaluate positional candidates using LLM-based VCP research.
    Filters out candidates that receive a "SKIP" verdict.
    Updates candidate dicts in-place with 'llm_verdict' and 'llm_reason' fields.
    
    Fails open: returns all candidates if LLM research is disabled or fails.
    """
    if not POSITIONAL_LLM_RESEARCH_ENABLED:
        log.info("[llm_research] Positional LLM research is disabled in config. Running in technical mode.")
        return candidates

    if not candidates:
        return []

    log.info("[llm_research] Running LLM VCP research on %d candidates (India VIX: %.1f)...", len(candidates), vix_value)
    
    # Cap research to top 10 candidates to keep cycle execution speed reasonable
    limit = 10
    research_candidates = candidates[:limit]
    remaining_candidates = candidates[limit:]

    final_candidates = []

    # Map VIX levels to qualitative regimes
    if vix_value <= 15.0:
        vix_regime = "LOW / AGGRESSIVE (ideal for breakouts)"
    elif vix_value <= 20.0:
        vix_regime = "MODERATE / NORMAL (caution on extensions)"
    else:
        vix_regime = "HIGH / VOLATILE (frequent false breakouts - be very strict!)"

    for cand in research_candidates:
        ticker = cand["ticker"]
        price = cand["price"]
        score = cand["score"]
        trend_template = cand.get("trend_template", 1)
        vcp_detected = cand.get("vcp_detected", 1)
        vcp_strength = cand.get("vcp_strength", 0.0)
        proximity = cand.get("proximity_52w_pct", 0.0)
        atr_pct = cand.get("atr_pct", 0.0)

        # 1. Fetch fundamental metrics from pos_universe
        fundamentals = {}
        try:
            with get_conn() as conn:
                row = conn.execute(
                    """SELECT company_name, sector, roce, roe, sales_growth, debt_to_equity, pe_ratio, market_cap 
                       FROM pos_universe WHERE ticker = ?""",
                    (ticker,)
                ).fetchone()
                if row:
                    fundamentals = dict(row)
        except Exception as e:
            log.warning("[llm_research] Could not fetch fundamentals for %s: %s", ticker, e)

        company_name = fundamentals.get("company_name", "Unknown")
        sector = fundamentals.get("sector", "Unknown")
        roce = fundamentals.get("roce")
        roe = fundamentals.get("roe")
        sales_growth = fundamentals.get("sales_growth")
        de = fundamentals.get("debt_to_equity")
        pe = fundamentals.get("pe_ratio")
        mcap = fundamentals.get("market_cap")

        # Format prompt
        prompt = (
            f"Evaluate ticker {ticker} ({company_name}) in sector {sector} for a positional VCP trade.\n\n"
            f"Market Context:\n"
            f"  - India VIX: {vix_value:.1f} ({vix_regime})\n\n"
            f"Technical Setup:\n"
            f"  - Current Price: ₹{price:,.2f}\n"
            f"  - Technical Score: {score:.1f}/100\n"
            f"  - Trend Template Passed: {'YES' if trend_template else 'NO'}\n"
            f"  - VCP Contraction Pattern Detected: {'YES' if vcp_detected else 'NO'} (Strength: {vcp_strength:.1f})\n"
            f"  - Proximity to 52W High: {proximity:.1f}% below high\n"
            f"  - Volatility (10-day ATR%): {atr_pct:.2f}%\n\n"
            f"Fundamental Metrics:\n"
            f"  - Market Cap: ₹{mcap:,.1f} Cr if available\n"
            f"  - ROCE: {f'{roce:.1f}%' if roce is not None else 'N/A'}\n"
            f"  - ROE: {f'{roe:.1f}%' if roe is not None else 'N/A'}\n"
            f"  - 3Y Sales Growth: {f'{sales_growth:.1f}%' if sales_growth is not None else 'N/A'}\n"
            f"  - Debt/Equity Ratio: {f'{de:.2f}' if de is not None else 'N/A'}\n"
            f"  - PE Ratio: {f'{pe:.1f}' if pe is not None else 'N/A'}\n\n"
            f"Assess structural breakout health: \n"
            f"1. Is the technical base well-tightened (high VCP strength)?\n"
            f"2. Are growth metrics solid and D/E low enough to protect capital?\n"
            f"3. Does the general market volatility (VIX) support opening this position?\n\n"
            f"Output ONLY the JSON object."
        )

        log.info("[llm_research] Calling LLM research for %s...", ticker)
        result = call_json(
            prompt=prompt,
            schema=_SCHEMA,
            system=_SYSTEM_PROMPT,
            model=LLM_VETO_MODEL,
            max_tokens=350,
            caller="veto"
        )

        if result is None:
            log.warning("[llm_research] LLM research failed or returned None for %s. Failing open.", ticker)
            cand["llm_verdict"] = "PROCEED"
            cand["llm_reason"] = "LLM unavailable; failed open"
            final_candidates.append(cand)
            continue

        verdict = result.get("verdict", "PROCEED")
        reason = result.get("reason", "Veto failed open")
        confidence = result.get("confidence", 1.0)
        
        log.info("[llm_research] Candidate %s verdict: %s (Reason: %s, Confidence: %.1f)", ticker, verdict, reason, confidence)
        
        cand["llm_verdict"] = verdict
        cand["llm_reason"] = reason

        if verdict == "SKIP":
            log.info("[llm_research] VETO / SKIPPED: Removing %s from buy candidate pool.", ticker)
            continue
        elif verdict == "REDUCE":
            log.info("[llm_research] RISK BUFFER: Candidate %s approved with REDUCED sizing (50%% allocation).", ticker)
            # Reduce score slightly so PROCEED candidates are prioritized first
            cand["score"] = max(40.0, cand["score"] - 5.0)
            final_candidates.append(cand)
        else:
            final_candidates.append(cand)

    # Re-sort finalized list by updated scores descending
    final_candidates.sort(key=lambda x: x["score"], reverse=True)
    
    # Re-attach the candidates that exceeded our research limit (processed without LLM)
    for c in remaining_candidates:
        c["llm_verdict"] = "PROCEED"
        c["llm_reason"] = "Exceeded EOD research cap; processed technically"
        final_candidates.append(c)

    log.info("[llm_research] Finished LLM research. Candidates available: %d → %d", len(candidates), len(final_candidates))
    return final_candidates
