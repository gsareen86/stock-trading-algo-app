# Investment Engine — Design Document

Status: **proposal** (no behaviour change yet) · Scope: swing positional + long-term books
Companion fixes already merged on this branch: news ticker-matching precision, live LLM
observability, grouped dashboard UI.

This document turns the current collection of modules (`positional/`, `longterm/`,
`news_impact/`, `llm/`) into one coherent **Conviction Engine**: a single funnel that
scores every stock on two axes and routes it into two books with explicit entry/exit
rules, horizons, and a review loop.

---

## 1. Guiding principles

1. **Technicals decide *when*. Fundamentals + management decide *what* and *how much*.
   News/LLM decide *whether today is safe* and *whether the thesis changed*.**
2. **Gates for risk, scores for ranking.** Governance, liquidity, surveillance-list and
   event risks are binary gates that can never be averaged away by a strong chart.
   Weighted scores rank only the survivors.
3. **The LLM is a reader and a tripwire, not an alpha source.** It converts concalls,
   guidance and news into structured fields and flags thesis changes. It never invents
   the numbers that size a position.
4. **Every signal must be auditable against forward returns.** No threshold gets tuned
   until the outcome-tracking loop (§7) says it helps.
5. **Precision over recall in data.** A missed headline or a skipped trade is
   recoverable; a wrongly attributed one silently poisons sentiment, alerts and the
   scorecard (this is why the OIL/PERSISTENT matcher fix shipped first).

---

## 2. Architecture: one funnel, two books

```
STAGE 0  Universe hygiene (weekly, HARD GATES)
         │  liquidity ≥ ₹5 Cr median daily traded value
         │  market cap ≥ ₹1,000 Cr · not on ASM/GSM · pledge < 30%
         │  ≥ 5y listed history · no audit/SEBI red flag
         ▼
STAGE 1  Quant screens (weekly)
         │  lt_quality 5-bucket score      → Durability (raw)
         │  RS vs NIFTY (3M+6M) + sector RS → Timing (raw)
         ▼  ranked watchlist ≈ 50–100 names
STAGE 2  Technical timing (daily EOD)               → TIMING AXIS (0–100)
         │  trend template · VCP · BVM · young momentum · fun-tech
         │  confluence ≥ 2 strategies OR 1 high-conviction + durability ≥ 60
         ▼
STAGE 3  News + LLM overlay (event-driven)
         │  news-impact severity · time-decayed sentiment · event calendar
         │  critical DIRECT news can freeze a name for the day
         ▼
STAGE 4  Deep research (event-driven)               → DURABILITY AXIS (0–100)
         │  concall summary + GUIDANCE LEDGER (§6) + management credibility
         ▼
STAGE 5  Routing
         │  Timing ≥ 60 & Durability ≥ 60 → BOTH   (swing entry, convert later)
         │  Timing ≥ 60 & Durability < 60 → SWING book only
         │  Timing < 60 & Durability ≥ 70 → LONG-TERM accumulation list
         │  else                          → watchlist / drop
         ▼
STAGE 6  Portfolio construction
            risk-based sizing · sector cap · correlation cap
            regime dial scales gross exposure (existing pos_market_regime)
```

The Timing/Durability scorecard already exists in `positional/scorer.py`; this design
promotes it from a swing-module detail to the engine's core and adds the missing
Stage 0 gates and Stage 6 portfolio layer.

### What each input is for

| Input | Role | Change vs today |
|---|---|---|
| Technicals | Timing axis only | Confluence becomes mandatory, not a bonus |
| Quality score (`lt_quality`) | Durability axis + universe gate | Add per-bucket minimums (a 0/20 governance bucket fails even if total ≥ 70) |
| Valuation (PEG pillar) | Sizing/tilt for LT; mild filter for swing | Unchanged — cheapness must not veto momentum |
| News + sentiment | Tripwire + entry-day safety | Time-decay (half-life ≈ 3 days); per-ticker throttle in news-impact |
| LLM insights | Reader + triage + thesis-change detection | Strong model for low-frequency research; cheap model for high-frequency triage |
| Management commentary | Management score on Durability axis | Persist guidance as structured data (§6) |
| Guidance | Guidance ledger → credibility score | **New** — highest-ROI addition |

---

## 3. Swing positional book

**Horizon:** 10–60 trading days. The time stop keys off each strategy's stored
`hold_days` (10 young-momentum / 15 fun-tech / 30 BVM) instead of a flat 15 days.

**Entry — ordered gates (all must pass):**
1. Stage-0 hygiene + quality ≥ 60 *(exists)*
2. Stage-2 uptrend: price > 21 EMA > 50 EMA > 200 EMA, within 15% of 52-week high *(exists)*
3. Setup trigger with confluence: ≥ 2 strategies firing, OR 1 high-conviction signal
   **and** Durability ≥ 60
4. Volume confirmation on the trigger bar (universal, not per-strategy)
5. Regime allows entry: BVM market filter + VIX-tightened threshold *(exists)*
6. **Deterministic event guard:** no entry within 3 trading days of a known results
   date (exception: PEAD-style fun-tech entries which trade *after* results).
   Source: NSE corporate-actions calendar (§8), not LLM-inferred dates.
7. News/LLM veto clean *(exists; keep fail-open, log every veto for §7)*

**Sizing — risk-based (replaces equal-weight):**
```
risk_amount = POSITIONAL_RISK_PCT (0.75–1.0%) × pool
qty         = risk_amount / (entry − stop)
cap         = 20% of pool per position · sector cap 30% · regime multiplier (exists)
```
Tight VCP pivots naturally size larger than loose 8%-risk entries — the Minervini
logic the scanner already encodes but the sizer ignores.

**Exit stack (priority order):**
1. Hard stop: structural (below pivot/base low), capped at 8% *(cap exists)*
2. **Partial de-risk at +2R: sell ⅓–½, stop to breakeven** *(new for positional)*
3. 21-EMA double-close trail on the remainder *(exists)*
4. Time stop: < 1R progress after 1× the strategy's expected hold *(generalised)*
5. Event exits: news-impact `REVIEW_EXIT` on critical DIRECT linkage → same-day
   review, default-to-exit; management score < 35 on a held name → halve at minimum
   (`POSITIONAL_MANAGEMENT_AUTO_EXIT` upgraded from alert-only)
6. Re-entry window 14 days *(exists)* · opportunity swap kept but hurdle raised until
   §7 measures swap P&L net of ~0.3% round-trip delivery cost

---

## 4. Long-term book

**Horizon:** 1–3+ years. No time stop — only thesis stops. Reviewed quarterly +
event-driven.

**Selection (Durability-first):**
- quality ≥ 70 **and** every bucket ≥ 50% of its max
- management credibility ≥ 60 (from guidance ledger once it has ≥ 2 quarters of data)
- FII/DII trend flat-to-rising over 4 quarters; pledge < 10% and falling
- valuation sanity: PEG pillar + earnings-yield-vs-growth check
- Timing **not** required — that is the point of the second book

**Entry — staggered tranches of ⅓:**
1. on classification into the book
2. on a higher-low / RS turn, or a 10–15% drawdown with thesis intact
3. after the next quarterly results confirm guidance delivery

**Conversion channel:** a `BOTH`-classified swing trade that reaches +2R with
Durability ≥ 70 takes the swing partial and moves the runner into this book —
compounders sourced by momentum.

**Exit — thesis-driven only:**
- 2 consecutive quarters of guidance miss, or ROCE/margin deterioration beyond band → exit/halve
- Governance tripwires (auto): pledge +10pp, auditor resignation, promoter stake sale
  > 2–3pp in a quarter, SEBI action → immediate review, default-exit bias
- Valuation extreme (PEG > 4 **and** RS rolling over) → trim
- Swap only with a large hurdle (candidate durability ≥ holding + 15)
- Optional crash protection: halve if close < 40-week MA **and** monthly regime is
  DEFENSIVE (reuses `pos_market_regime`)

**Sizing:** conviction-weighted; max 10% per name, 25–30% per sector.

---

## 5. Review & research loop (event-driven > timer-driven)

| Cadence | Actions |
|---|---|
| Daily (EOD) | exit checks, stop/trail updates *(exists)* · news-impact pass with per-ticker throttle · RS refresh on holdings + watchlist |
| Weekly | universe hygiene + quality re-score (`run_phase_a` finally scheduled — currently manual) · watchlist re-rank · stale-data audit (quality score > 30 days old on a holding → flag) |
| Event-driven | **results announced** → ingest same day, diff vs guidance ledger · **new concall published** → full re-research, emit *thesis-drift alert* if verdict/outlook changed · **shareholding pattern released** → FII/DII/pledge delta alerts · **bulk/block deal or SAST disclosure** → tripwire review |
| Quarterly | guidance ledger reconciliation → credibility score update · portfolio-level review (sector concentration, regime, book balance) |

---

## 6. Guidance ledger (new)

The highest-value use of management commentary: store each guidance item as structured
data, then automatically compare against delivery next quarter.

```sql
CREATE TABLE IF NOT EXISTS guidance_ledger (
    id              INTEGER PRIMARY KEY,
    ticker          TEXT NOT NULL,
    source_quarter  TEXT NOT NULL,      -- e.g. 'FY26Q1' (concall it came from)
    metric          TEXT NOT NULL,      -- 'revenue_growth' | 'margin' | 'capex' | 'order_book' | ...
    guided_value    TEXT NOT NULL,      -- verbatim ('18-20% YoY', '~₹500 Cr capex')
    guided_low      REAL,               -- parsed numeric band (nullable)
    guided_high     REAL,
    horizon         TEXT NOT NULL,      -- 'next_quarter' | 'FY' | 'multi_year'
    extracted_at    TEXT NOT NULL,
    source_url      TEXT,
    -- reconciliation (filled when actuals arrive)
    actual_value    REAL,
    delivered       TEXT,               -- 'MET' | 'BEAT' | 'MISSED' | 'UNVERIFIABLE'
    reconciled_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_guidance_ticker ON guidance_ledger(ticker);
```

- **Extraction:** add a structured `guidance_items[]` field to the Stage-3 research
  JSON in `positional/research.py` (the concall summariser already isolates a
  "Forward Outlook & Management Guidance" section — today it is free text only).
- **Reconciliation:** when the next quarterly results land (Screener quarterly section,
  already scraped), compare actuals to the band and stamp `delivered`.
- **Credibility score:** rolling 8-quarter hit-rate, weighted recent-first → feeds the
  management pillar of the Durability axis. Two consecutive `MISSED` on the same
  metric = long-term-book thesis stop (§4).

---

## 7. Outcome tracking & backtesting (prerequisite for all tuning)

Every threshold in the system (score 60, 8% stop, 15-day time stop, pillar weights,
veto behaviour) is currently a guess that nothing validates.

**`signal_outcomes` table:** for every scan score, LLM verdict, veto, news alert and
management score snapshot, attach forward 5/20/60-day returns automatically (a small
EOD job joining against cached prices).

```sql
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id            INTEGER PRIMARY KEY,
    signal_type   TEXT NOT NULL,   -- 'pos_scan' | 'research_verdict' | 'veto' | 'news_alert' | 'mgmt_score'
    signal_id     INTEGER NOT NULL,
    ticker        TEXT NOT NULL,
    signal_ts     TEXT NOT NULL,
    ref_price     REAL,
    fwd_ret_5d    REAL, fwd_ret_20d  REAL, fwd_ret_60d  REAL,
    computed_at   TEXT
);
```

**Walk-forward EOD backtester** for the 4 positional strategies + scoring thresholds,
reusing the existing parquet price cache. Adaptive weights / ML meta-model stay off
(as `config.py` already intends) until ≥ 200 outcomes exist and the backtest shows the
pillar weights earn their keep.

After one quarter this answers, empirically: does the management score predict? does
the LLM veto save or cost money? what is the real optimal stop and time stop?

---

## 8. Data-layer upgrades

| Item | Why | Source |
|---|---|---|
| NSE corporate-actions / results calendar | Replace LLM-inferred earnings dates in `llm/events.py` with facts | NSE API/scrape, daily |
| Liquidity + ASM/GSM surveillance lists | Stage-0 gate; classic small-cap momentum killer | NSE daily files |
| Bulk/block deals + SAST insider disclosures | Thesis-change tripwires (§5) | NSE daily files |
| Time-decayed sentiment | Flat 14-day mean treats stale news as fresh | half-life ≈ 3 days in `nlp/sentiment.aggregated_sentiment` |
| Per-ticker news-impact throttle | Global 4-hour throttle lets stock A's news delay stock B's analysis | `news_impact/pipeline.py` |
| Single fundamental source of truth | `lt_universe` (scraped) vs `pos_universe` (CSV upload) disagree | Screener primary, yfinance fallback; one hygiene-gated universe |
| LLM cache TTL | Disk cache never expires; stale events/sentiment possible | TTL per cache class (events: 1 day, sentiment: 7 days, research: 25 days) |

**LLM model tiering:** research-grade analysis (concalls, guidance extraction, EOD
review) on a strong model (Sonnet-class) — it is low-frequency, so cost is bounded;
high-frequency triage (sentiment, veto, sector tagging) stays on the cheap/fast tier.
The rebuilt LLM Usage tab now shows exactly which model burned which tokens, so this
split is verifiable.

---

## 9. Proposed config additions

```python
# ----- Conviction engine -----
ENGINE_TIMING_STRONG          = 60.0   # exists as POSITIONAL_TIMING_STRONG
ENGINE_DURABILITY_STRONG      = 60.0   # exists as POSITIONAL_DURABILITY_STRONG
ENGINE_DURABILITY_LT_GATE     = 70.0   # long-term book admission
ENGINE_BUCKET_MIN_FRACTION    = 0.50   # every quality bucket ≥ 50% of its max

# ----- Stage-0 hygiene -----
UNIVERSE_MIN_MEDIAN_TRADED_VALUE_CR = 5.0    # ₹ Cr/day, 60-day median
UNIVERSE_EXCLUDE_SURVEILLANCE       = True   # ASM/GSM lists
UNIVERSE_MAX_PLEDGE_PCT             = 30.0

# ----- Swing book -----
POSITIONAL_RISK_PCT            = 0.01   # risk-based sizing (replaces equal-weight)
POSITIONAL_PARTIAL_AT_R        = 2.0    # +2R partial
POSITIONAL_PARTIAL_FRACTION    = 0.5
POSITIONAL_SECTOR_CAP_PCT      = 0.30
POSITIONAL_EVENT_GUARD_DAYS    = 3      # deterministic, NSE calendar

# ----- Long-term book -----
LT_MAX_POSITION_PCT            = 0.10
LT_SECTOR_CAP_PCT              = 0.30
LT_TRANCHE_FRACTIONS           = (0.34, 0.33, 0.33)
LT_GUIDANCE_MISS_STREAK_EXIT   = 2

# ----- News / sentiment -----
SENTIMENT_HALF_LIFE_DAYS       = 3.0
NEWS_IMPACT_PER_TICKER_THROTTLE_MIN = 240   # replaces global throttle

# ----- Feedback -----
OUTCOME_HORIZONS_DAYS          = (5, 20, 60)
```

---

## 10. Implementation roadmap

| Phase | Contents | Depends on |
|---|---|---|
| **1. Quick fixes** | ~~news matcher precision~~ ✅ · ~~LLM observability~~ ✅ · NSE earnings calendar · liquidity/ASM gate · sentiment time-decay · per-ticker news throttle | — |
| **2. Swing book mechanics** | risk-based sizing · +2R partial · strategy-scaled time stop | 1 |
| **3. Guidance ledger** | extraction in research.py · reconciliation job · credibility score → durability | 1 |
| **4. Unified universe** | one hygiene-gated universe; Screener as fundamental source of truth | 1 |
| **5. Feedback layer** | `signal_outcomes` + EOD join job · walk-forward backtester | 2 |
| **6. Long-term book execution** | tranche accumulation · swing→LT conversion · thesis stops · governance tripwires | 3, 4 |
| **7. Adaptive layer** | re-tune thresholds/weights from outcomes; consider ML meta-model (≥ 200 outcomes) | 5 |

Each phase is independently shippable and leaves the system in a working state.
