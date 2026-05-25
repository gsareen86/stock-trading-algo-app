"""
Phase-3 positional research — a buy-side-analyst pass over each candidate.

For every shortlisted stock (BUY setups + LONG_TERM watch candidates) we:
  1. Gather management material from Screener.in (Pros/Cons, announcements,
     latest concall transcript + investor presentation — see positional/concalls.py).
  2. Have the local LLM judge management outlook → a 0-100 ``management`` pillar
     score + a written thesis + a PROCEED/REDUCE/SKIP verdict.
  3. Fold the management score back into the scorecard (composite / durability /
     horizon) via positional.scorer.recompute, and persist the thesis.

Long transcripts are map-reduced: each chunk is summarised, then the digests +
HTML signals feed one final analyst call.

Fails open everywhere — if Screener, the PDF host, or the LLM is unavailable the
candidate keeps its technical scorecard and a PROCEED verdict.
"""
import json
import logging
from datetime import datetime, timedelta

import config
from config import (
    IST,
    LLM_VETO_MODEL,
    POSITIONAL_CONCALL_CACHE_DAYS,
    POSITIONAL_MANAGEMENT_VETO_SCORE,
    POSITIONAL_RESEARCH_CHUNK_CHARS,
    POSITIONAL_RESEARCH_LIMIT,
)
from db.models import get_conn
from llm.client import call_json
from positional import scorer
from positional.concalls import gather_management_material

log = logging.getLogger(__name__)

_MAX_CHUNKS = 6   # cap transcript chunks summarised per stock (bounds LLM cost)

# Final analyst verdict schema
_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["PROCEED", "REDUCE", "SKIP"],
            "description": "PROCEED: outlook supports a position; REDUCE: proceed at half size due to a concern; SKIP: management/outlook red flags — do not buy.",
        },
        "outlook": {
            "type": "string",
            "enum": ["POSITIVE", "NEUTRAL", "MIXED", "NEGATIVE"],
            "description": "Overall management/business outlook from the commentary.",
        },
        "management_score": {
            "type": "number",
            "description": "0-100 score for management credibility, execution vs past guidance, growth outlook and capital allocation. 50 = neutral.",
        },
        "thesis": {
            "type": "string",
            "description": "<=120 word investment thesis grounded in the management commentary.",
        },
        "key_positives": {"type": "array", "items": {"type": "string"},
                          "description": "Up to 4 concrete positives."},
        "key_risks": {"type": "array", "items": {"type": "string"},
                      "description": "Up to 4 concrete risks / red flags."},
        "guidance": {"type": "string",
                     "description": "<=40 word gist of forward guidance, or 'none given'."},
        "confidence": {"type": "number", "description": "0.0-1.0 confidence in this read."},
    },
    "required": ["verdict", "outlook", "management_score", "thesis", "confidence"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are a senior buy-side equity analyst covering Indian listed companies. "
    "You read management commentary (concall transcript, investor presentation, "
    "Screener.in pros/cons, recent announcements) to judge MANAGEMENT OUTLOOK for a "
    "swing/positional or long-term holding.\n"
    "Assess: credibility and execution vs prior guidance, demand/order-book and growth "
    "outlook, margins and capital allocation, balance-sheet/leverage commentary, and any "
    "governance red flags (pledging, related-party, accounting, promoter conduct).\n"
    "Score management_score 0-100 (50=neutral). Reserve SKIP for genuine red flags or a "
    "clearly deteriorating outlook; REDUCE for a real but survivable concern; otherwise PROCEED. "
    "Be specific and grounded in the material — do not invent facts."
)

_CHUNK_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string",
                    "description": "Concise bullet digest of management commentary in this excerpt: guidance, growth drivers, margins, capital allocation, risks, red flags."}
    },
    "required": ["summary"],
    "additionalProperties": False,
}


def _summarise_long_text(body: str) -> str:
    """Map step: summarise each transcript chunk, then concatenate the digests."""
    chunk = POSITIONAL_RESEARCH_CHUNK_CHARS
    chunks = [body[i:i + chunk] for i in range(0, len(body), chunk)][:_MAX_CHUNKS]
    summaries = []
    for idx, ch in enumerate(chunks):
        res = call_json(
            prompt=("Summarise the management commentary in this concall/presentation excerpt "
                    "as concise bullet points (guidance, growth drivers, margins, capital "
                    f"allocation, risks, red flags):\n\n{ch}"),
            schema=_CHUNK_SCHEMA,
            model=LLM_VETO_MODEL,
            max_tokens=400,
            caller="research_chunk",
        )
        if res and res.get("summary"):
            summaries.append(f"[part {idx + 1}] {res['summary']}")
    return "\n".join(summaries)[:POSITIONAL_RESEARCH_CHUNK_CHARS]


def _build_digest(material: dict) -> str:
    """Assemble the management material into one prompt-ready digest, map-reducing
    the transcript/presentation if it exceeds the single-pass char budget."""
    parts = []
    if material.get("pros"):
        parts.append("SCREENER PROS:\n- " + "\n- ".join(material["pros"][:8]))
    if material.get("cons"):
        parts.append("SCREENER CONS:\n- " + "\n- ".join(material["cons"][:8]))
    if material.get("announcements"):
        parts.append("RECENT ANNOUNCEMENTS:\n- " + "\n- ".join(material["announcements"][:8]))

    body = "\n\n".join(p for p in (material.get("concall_text", ""),
                                   material.get("ppt_text", "")) if p)
    if body:
        if len(body) <= POSITIONAL_RESEARCH_CHUNK_CHARS:
            parts.append("CONCALL / PRESENTATION:\n" + body)
        else:
            digest = _summarise_long_text(body)
            if digest:
                parts.append("CONCALL / PRESENTATION (summarised):\n" + digest)
    return "\n\n".join(parts).strip()


def _fundamentals(ticker: str) -> dict:
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT company_name, sector, roce, roe, sales_growth,
                          debt_to_equity, pe_ratio, market_cap
                   FROM pos_universe WHERE ticker = ?""",
                (ticker.replace(".NS", "").replace(".BO", ""),),
            ).fetchone()
            return dict(row) if row else {}
    except Exception:
        return {}


def _cached_research(ticker: str, concall_date) -> dict | None:
    """Reuse a stored analyst result if it's for the same concall and still fresh."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pos_research WHERE ticker = ?",
                (ticker.replace(".NS", "").replace(".BO", ""),),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    r = dict(row)
    if concall_date and r.get("concall_date") != concall_date:
        return None
    try:
        researched = datetime.fromisoformat(r["researched_at"])
        if datetime.now(IST) - researched > timedelta(days=POSITIONAL_CONCALL_CACHE_DAYS):
            return None
    except Exception:
        pass
    return {
        "verdict": r.get("verdict", "PROCEED"),
        "outlook": r.get("outlook", "NEUTRAL"),
        "management_score": r.get("management_score"),
        "thesis": r.get("thesis", ""),
        "key_positives": json.loads(r.get("key_positives") or "[]"),
        "key_risks": json.loads(r.get("key_risks") or "[]"),
        "guidance": r.get("guidance", ""),
        "confidence": r.get("confidence", 1.0),
    }


def _persist_research(ticker: str, material: dict, res: dict) -> None:
    try:
        from db.models import upsert_pos_research
        upsert_pos_research(
            ticker=ticker.replace(".NS", "").replace(".BO", ""),
            researched_at=datetime.now(IST).isoformat(),
            concall_date=material.get("concall_date"),
            management_score=res.get("management_score"),
            verdict=res.get("verdict"),
            outlook=res.get("outlook"),
            thesis=res.get("thesis", ""),
            key_positives=json.dumps(res.get("key_positives") or []),
            key_risks=json.dumps(res.get("key_risks") or []),
            guidance=res.get("guidance", ""),
            sources=json.dumps(material.get("sources") or []),
            confidence=res.get("confidence"),
        )
    except Exception as e:
        log.debug("[research] persist failed for %s: %s", ticker, e)


def _update_scan_row(ticker: str, management: float, composite: float,
                     durability: float, horizon: str) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                """UPDATE pos_scans
                   SET management_pillar = ?, composite_score = ?, score = ?,
                       durability_score = ?, horizon = ?
                   WHERE id = (SELECT MAX(id) FROM pos_scans WHERE ticker = ?)""",
                (management, composite, composite, durability, horizon, ticker),
            )
    except Exception as e:
        log.debug("[research] scan-row update failed for %s: %s", ticker, e)


def _analyse(cand: dict, vix_regime: str) -> dict | None:
    """Gather material + run the analyst (or reuse cache). Returns the verdict dict
    plus the gathered material under '_material', or None if no material at all."""
    ticker = cand["ticker"]
    material = gather_management_material(ticker)
    if not material.get("available"):
        return None

    cached = _cached_research(ticker, material.get("concall_date"))
    if cached is not None:
        log.info("[research] %s: reusing cached analyst read (concall %s)",
                 ticker, material.get("concall_date"))
        cached["_material"] = material
        return cached

    f = _fundamentals(ticker)
    digest = _build_digest(material)
    prompt = (
        f"Company: {ticker} ({f.get('company_name', 'Unknown')}), sector {f.get('sector', 'Unknown')}.\n"
        f"Market context — India VIX regime: {vix_regime}.\n\n"
        f"Fundamentals: ROCE={f.get('roce')}, ROE={f.get('roe')}, 3Y sales growth={f.get('sales_growth')}, "
        f"D/E={f.get('debt_to_equity')}, PE={f.get('pe_ratio')}.\n"
        f"Technical scorecard: composite={cand.get('composite_score')}, timing={cand.get('timing_score')}, "
        f"confluence={cand.get('confluence')} ({cand.get('strategies_fired', '')}), horizon={cand.get('horizon')}.\n\n"
        f"MANAGEMENT MATERIAL:\n{digest if digest else '(no concall/presentation text available — judge on pros/cons + fundamentals)'}\n\n"
        f"Judge management outlook and output the JSON verdict."
    )
    res = call_json(prompt=prompt, schema=_SCHEMA, system=_SYSTEM_PROMPT,
                    model=LLM_VETO_MODEL, max_tokens=600, caller="research")
    if res is None:
        return None
    res["_material"] = material
    return res


def _apply_research(cand: dict, res: dict) -> None:
    """Annotate the candidate with the verdict, fold the management pillar into
    the scorecard (only when the candidate carries real pillar values), and
    persist the thesis + the updated scan row."""
    material = res.pop("_material", {})
    mgmt = res.get("management_score")
    verdict = res.get("verdict", "PROCEED")
    outlook = res.get("outlook", "NEUTRAL")
    thesis = res.get("thesis", "")

    cand["llm_verdict"] = verdict
    cand["llm_reason"] = thesis or f"Management outlook: {outlook}"
    cand["management_pillar"] = mgmt
    cand["outlook"] = outlook
    cand["thesis"] = thesis

    # Only re-blend the scorecard when this candidate has a real technical pillar
    # (i.e. came from a scan row). Held/watchlist names refreshed without a scan
    # still get their thesis + management score persisted, just no composite edit.
    if mgmt is not None and cand.get("timing_score") is not None:
        rb = scorer.recompute(
            timing=cand.get("timing_score"),
            quality=cand.get("quality_pillar"),
            valuation=cand.get("valuation_pillar"),
            momentum=cand.get("momentum_pillar"),
            sentiment=cand.get("sentiment_pillar"),
            management=mgmt,
        )
        cand["composite_score"] = rb["composite"]
        cand["score"] = rb["composite"]
        cand["durability_score"] = rb["durability"]
        cand["horizon"] = rb["horizon"]
        _update_scan_row(cand["ticker"], mgmt, rb["composite"], rb["durability"], rb["horizon"])

    _persist_research(cand["ticker"], material, res)


def _research_and_apply(cand: dict, vix_regime: str) -> dict | None:
    """Run the analyst for one candidate and apply the result. Returns the
    verdict dict (without the internal material), or None when it failed open."""
    ticker = cand["ticker"]
    try:
        res = _analyse(cand, vix_regime)
    except Exception as e:
        log.warning("[research] analysis errored for %s: %s — failing open", ticker, e)
        res = None
    if res is None:
        cand.setdefault("llm_verdict", "PROCEED")
        cand.setdefault("llm_reason", "No management data / LLM unavailable; failed open")
        return None
    out = {k: v for k, v in res.items() if k != "_material"}
    _apply_research(cand, res)
    log.info("[research] %s verdict=%s outlook=%s mgmt=%s horizon=%s",
             ticker, out.get("verdict"), out.get("outlook"),
             out.get("management_score"), cand.get("horizon"))
    return out


def _vix_regime(vix_value: float) -> str:
    if vix_value <= 15.0:
        return "LOW / supportive"
    if vix_value <= 20.0:
        return "MODERATE / normal"
    return "HIGH / volatile — be stricter"


def run_positional_llm_research(candidates: list[dict], vix_value: float = 0.0) -> list[dict]:
    """Research candidates (BUY setups + LONG_TERM watch), fold the management
    pillar into each scorecard, persist the thesis, and return the buy pool.

    The returned list is the tradeable pool: candidates whose alert_type is BUY
    and that were not vetoed (SKIP / management below the veto floor), sorted by
    the updated composite. LONG_TERM candidates are researched and persisted for
    the dashboard but never returned for buying.

    Fails open: on disabled/empty/LLM-down it returns the BUY candidates as-is.
    """
    llm_enabled = config.POSITIONAL_LLM_RESEARCH_ENABLED and config.POSITIONAL_CONCALL_RESEARCH_ENABLED
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT positional_llm_research_enabled FROM bot_control WHERE id = 1"
            ).fetchone()
            if row and "positional_llm_research_enabled" in row.keys():
                llm_enabled = llm_enabled and bool(row["positional_llm_research_enabled"])
    except Exception as e:
        log.warning("[research] could not read bot_control flag: %s", e)

    buy_pool_passthrough = [c for c in candidates if c.get("alert_type") == "BUY"]
    if not llm_enabled:
        log.info("[research] management research disabled — technical mode.")
        return buy_pool_passthrough
    if not candidates:
        return []

    vix_regime = _vix_regime(vix_value)
    researched = candidates[:POSITIONAL_RESEARCH_LIMIT]
    overflow = candidates[POSITIONAL_RESEARCH_LIMIT:]
    log.info("[research] analysing %d candidates (VIX %.1f, %s)...",
             len(researched), vix_value, vix_regime)

    for cand in researched:
        _research_and_apply(cand, vix_regime)

    # Overflow beyond the research cap is processed technically.
    for c in overflow:
        c.setdefault("llm_verdict", "PROCEED")
        c.setdefault("llm_reason", "Beyond research cap; processed technically")

    # Build the tradeable buy pool: BUY setups not vetoed.
    buy_pool = []
    for c in (researched + overflow):
        if c.get("alert_type") != "BUY":
            continue
        mgmt = c.get("management_pillar")
        vetoed = c.get("llm_verdict") == "SKIP" or (
            mgmt is not None and mgmt <= POSITIONAL_MANAGEMENT_VETO_SCORE
        )
        if vetoed:
            log.info("[research] VETO %s (verdict=%s mgmt=%s)",
                     c["ticker"], c.get("llm_verdict"), mgmt)
            c["llm_verdict"] = "SKIP"
            continue
        if c.get("llm_verdict") == "REDUCE":
            c["score"] = max(40.0, c.get("score", 50.0) - 5.0)
        buy_pool.append(c)

    buy_pool.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    log.info("[research] done — %d BUY candidates cleared for entry", len(buy_pool))
    return buy_pool


# ── Decoupled daily refresh (holdings + watchlist + recent shortlist) ────────

def _cand_from_scan(ticker: str) -> dict:
    """Build a candidate dict from a ticker's latest scan row (pillars for the
    scorecard re-blend). Falls back to just the ticker if it was never scanned."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pos_scans WHERE id = (SELECT MAX(id) FROM pos_scans WHERE ticker = ?)",
                (ticker,),
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return {"ticker": ticker}
    r = dict(row)
    return {
        "ticker": ticker,
        "alert_type": r.get("alert_type"),
        "horizon": r.get("horizon"),
        "score": r.get("score"),
        "composite_score": r.get("composite_score"),
        "timing_score": r.get("timing_score"),
        "confluence": r.get("confluence"),
        "strategies_fired": r.get("strategies_fired"),
        "quality_pillar": r.get("quality_pillar"),
        "valuation_pillar": r.get("valuation_pillar"),
        "momentum_pillar": r.get("momentum_pillar"),
        "sentiment_pillar": r.get("sentiment_pillar"),
    }


def _refresh_universe() -> tuple[list[str], set[str]]:
    """Tickers to refresh = open positions ∪ watchlist ∪ recent shortlist.
    Returns (ordered_tickers, held_set). Positions/watchlist come first so they
    always make the cap."""
    held: set[str] = set()
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(tk):
        if tk and tk not in seen:
            seen.add(tk)
            ordered.append(tk)

    try:
        with get_conn() as conn:
            for r in conn.execute("SELECT DISTINCT ticker FROM pos_positions WHERE status='OPEN'").fetchall():
                held.add(r["ticker"]); _add(r["ticker"])
            for r in conn.execute("SELECT ticker FROM pos_watchlist").fetchall():
                _add(r["ticker"])
            latest = conn.execute(
                "SELECT substr(scanned_at,1,10) AS d FROM pos_scans ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest:
                rows = conn.execute(
                    """SELECT ticker FROM pos_scans
                       WHERE id IN (SELECT MAX(id) FROM pos_scans
                                    WHERE substr(scanned_at,1,10) = ? GROUP BY ticker)
                       ORDER BY composite_score DESC LIMIT ?""",
                    (latest["d"], POSITIONAL_RESEARCH_LIMIT),
                ).fetchall()
                for r in rows:
                    _add(r["ticker"])
    except Exception as e:
        log.warning("[research] refresh universe build failed: %s", e)
    return ordered, held


def refresh_management_research(vix_value: float = 0.0) -> dict:
    """Daily decoupled pass: re-run the concall analyst over holdings + watchlist
    + recent shortlist. Cheap in steady state (cached by concall date) and the
    way held positions pick up new quarterly concalls. Raises advisory review
    alerts when a held stock's management read deteriorates.
    """
    if not (config.POSITIONAL_LLM_RESEARCH_ENABLED and config.POSITIONAL_CONCALL_RESEARCH_ENABLED):
        return {"skipped": True, "reason": "research disabled"}

    tickers, held = _refresh_universe()
    cap = POSITIONAL_RESEARCH_LIMIT * 3
    tickers = tickers[:cap]
    if not tickers:
        return {"researched": 0, "reviews": []}

    vix_regime = _vix_regime(vix_value)
    log.info("[research] refresh pass over %d tickers (%d held)...", len(tickers), len(held))

    reviews = []
    for tk in tickers:
        cand = _cand_from_scan(tk)
        res = _research_and_apply(cand, vix_regime)
        if not res or tk not in held:
            continue
        if _is_deteriorating(res):
            review = {
                "ticker": tk, "verdict": res.get("verdict"),
                "outlook": res.get("outlook"),
                "management_score": res.get("management_score"),
                "thesis": res.get("thesis", ""),
            }
            reviews.append(review)
            try:
                from positional.alerts import send_management_review
                send_management_review(review)
            except Exception:
                pass

    log.info("[research] refresh done — %d researched, %d holdings flagged for review",
             len(tickers), len(reviews))
    return {"researched": len(tickers), "reviews": reviews}


def _is_deteriorating(res: dict) -> bool:
    mgmt = res.get("management_score")
    return (
        res.get("verdict") == "SKIP"
        or res.get("outlook") == "NEGATIVE"
        or (mgmt is not None and mgmt <= config.POSITIONAL_MANAGEMENT_REVIEW_SCORE)
    )


def management_exit_reason(ticker: str) -> str | None:
    """If management auto-exit is enabled and the stored research for this held
    ticker has deteriorated, return an exit reason string; else None."""
    if not config.POSITIONAL_MANAGEMENT_AUTO_EXIT:
        return None
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT verdict, outlook, management_score FROM pos_research WHERE ticker = ?",
                (ticker.replace(".NS", "").replace(".BO", ""),),
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    r = dict(row)
    if _is_deteriorating({"verdict": r.get("verdict"), "outlook": r.get("outlook"),
                          "management_score": r.get("management_score")}):
        return (f"MANAGEMENT_EXIT: outlook {r.get('outlook')} / verdict {r.get('verdict')} "
                f"(mgmt {r.get('management_score')})")
    return None
