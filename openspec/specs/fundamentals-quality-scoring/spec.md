# Fundamentals & Quality Scoring

Status: **full baseline** — written to full depth because this is where the earlier
"Stock Fundamental Analyzer" enhancement request lands. Scoped to the paths relevant to
that enhancement (moat/qualitative read, management guidance-vs-delivery, promoter
pledging, FII/DII trend, peer comparison, sector framing); not an exhaustive line-by-line
re-derivation of all three source files.

## Overview

Two **independent, never-reconciled** fundamental scorers exist in this codebase, feeding
different books:

- `data/fundamentals.py::score_fundamentals` — yfinance-based, feeds the **intraday**
  composite (`scoring/composite.py`) at a 5% weight.
- `longterm/quality.py::score_company` — Screener.in-scraped (`longterm/screener_scraper.py`),
  5-bucket rule-based, feeds the **positional/long-term** quality pillar
  (`positional/pillars.py::quality_pillar`) via the `lt_quality` table.

They score conceptually similar things ("how good is this business") with different
inputs, different weights, and disagree by design — this is documented current behavior,
not a bug to silently fix.

## Requirements

### Requirement: Intraday fundamental score (`data/fundamentals.py`)
The system MUST compute a 0–100 `fundamental_score` for a ticker from yfinance data,
weighted across ROE, debt/equity, self-computed earnings growth, self-computed revenue
growth, P/E, and profit margin, and MUST cache the result for `CACHE_TTL_HOURS` (24h) in
the `fundamentals` table before refetching.

#### Scenario: Non-bank weighting
- GIVEN a ticker whose yfinance `industry` does not match a bank/credit-services pattern
- WHEN `score_fundamentals` runs
- THEN the composite is `ROE×0.25 + D/E×0.15 + earnings_growth×0.15 + revenue_growth×0.15 + PE×0.15 + margin×0.15`

#### Scenario: Bank weighting suppresses D/E
- GIVEN a ticker whose `industry` contains "bank" or starts with "credit services"
- WHEN `score_fundamentals` runs
- THEN `debt_to_equity` is set to `None` (a bank's borrowings are deposits, not leverage
  in the conventional sense) and the composite instead uses
  `ROE×0.30 + earnings_growth×0.20 + revenue_growth×0.15 + PE×0.20 + margin×0.15`

#### Scenario: Missing input scores neutral, not zero
- GIVEN any of the six inputs is unavailable from yfinance
- WHEN its bucket score is computed
- THEN that input contributes `50` (neutral), not `0` — a missing figure is not treated
  as a bad one

### Requirement: Growth figures are smoothed, not passed through raw
The system MUST NOT use yfinance's `info.earningsGrowth`/`info.revenueGrowth` directly as
the primary growth input, because these are single-quarter YoY snapshots that swing
wildly off a low prior-year base (documented example in-code: Bank of Maharashtra showed
172.9% on yfinance's raw figure vs. a realistic ~27–65% multi-year CAGR on Screener). It
MUST instead compute quarterly TTM-vs-prior-TTM growth (last 4 quarters summed vs. the 4
before that) when ≥8 quarters of data exist, clipped to `[-100%, +500%]`.

#### Scenario: Quarterly data insufficient, falls back to annual CAGR
- GIVEN fewer than 8 quarters of quarterly financials are available
- WHEN growth is computed
- THEN the system falls back to a 3-year annual CAGR (≥3 years of annual data required)

#### Scenario: Neither quarterly nor annual data available
- GIVEN both the quarterly and annual computation fail
- WHEN growth is computed
- THEN the system falls back to yfinance's raw `earningsGrowth`/`revenueGrowth` only as a
  last resort (the noisy figure is better than nothing, but never preferred)

### Requirement: Long-term quality score (`longterm/quality.py`)
The system MUST compute a 0–100 `total_score` for a ticker as the sum of five
independently-capped buckets: Profitability (max 25), Cash Quality (max 20), Solvency
(max 15), Growth (max 20), Governance (max 20), using data scraped by
`longterm/screener_scraper.py`.

#### Scenario: Profitability bucket composition
- GIVEN 5 years of ROE, ROCE, and net-margin history
- WHEN the Profitability bucket is scored
- THEN it awards up to 8 points for 5y-avg ROE (≥20% → 8, ≥15% → 6, ≥12% → 4, ≥8% → 2),
  up to 8 for 5y-avg ROCE on the same bands, up to 5 for 5y-avg net margin (≥15% → 5,
  ≥10% → 4, ≥5% → 2, >0% → 1), and a 4-point bonus if all of the last ≥3 years of net
  profit were positive

#### Scenario: Loan-book businesses get a different Cash Quality path
- GIVEN a company classified as a loan-book business (industry string contains "bank",
  "credit services", "housing finance", "mortgage", "consumer finance", "nbfc",
  "non-banking", or "asset management")
- WHEN the Cash Quality bucket (max 20) is scored
- THEN the system does NOT penalize structurally-negative operating cash flow (a healthy,
  growing lender's new loans show up as negative CFO); it instead scores positive-net-profit
  years (0–10), YoY net-profit growth years (0–6), and net-profit volatility via
  coefficient of variation (0–4)

#### Scenario: Non-loan-book Cash Quality path
- GIVEN a company not classified as a loan-book business
- WHEN the Cash Quality bucket is scored
- THEN it scores years of positive operating cash flow in the last 5 (0–10) and the
  average OCF/Net-Profit ratio over the last 5 years (0–10, ≥1.1 → full 10)

#### Scenario: Solvency bucket is bank-aware
- GIVEN a company classified as a bank (loan-book)
- WHEN the Solvency bucket (max 15) is scored
- THEN D/E is not used at all; instead the bucket scores years with ROE ≥ 12% in the last
  5 (a sustainable-spread proxy), capped at the same 15-point max
- GIVEN a non-bank company
- WHEN the Solvency bucket is scored
- THEN it awards up to 8 points for D/E (≤0.3 → 8, ≤0.7 → 6, ≤1.0 → 4, ≤2.0 → 2) and up
  to 7 for latest interest coverage (≥8× → 7, ≥5× → 6, ≥3× → 4, ≥1.5× → 2)

#### Scenario: Growth bucket composition
- GIVEN 5–6 years of revenue and EPS history
- WHEN the Growth bucket (max 20) is scored
- THEN it awards up to 8 points for 5y revenue CAGR (≥20% → 8, ≥12% → 6, ≥8% → 4, ≥4% →
  2), up to 8 for 5y EPS CAGR on the same bands, and up to 4 for zero YoY revenue decline
  years in the last 5 (0 declines → 4, 1 decline → 2)

#### Scenario: Governance bucket composition (promoter holding, pledge, stability)
- GIVEN the latest quarterly shareholding record and up to 8 quarters of history
- WHEN the Governance bucket (max 20) is scored
- THEN it awards up to 8 points for latest promoter holding % (≥50 → 8, ≥35 → 6, ≥20 →
  3, else → 1), up to 6 for latest promoter pledge % — **lower is better** (0% → 6, <5% →
  5, <15% → 3, <30% → 1, ≥30% → 0), and up to 6 for 8-quarter promoter-holding stability
  (stddev ≤1.0 → 6, ≤3.0 → 4, ≤6.0 → 2)
- Note: pledge is not currently cross-checked against the ">10% pledge" flag threshold
  the earlier Fundamental Analyzer request called for — the closest existing signal is
  this bucket's pledge sub-score, which uses different breakpoints (5/15/30%, not 10%).
  An enhancement adding an explicit ">10% pledge" flag would be new behavior, not
  something this scorer already does.

#### Scenario: Missing governance data scores neutral
- GIVEN promoter holding or pledge data is unavailable from the scraper
- WHEN the corresponding sub-score is computed
- THEN it awards a neutral mid-range value (4/8 for missing holding, 3/6 for missing
  pledge) rather than zero or a full score

### Requirement: Peer comparison, sector framing, and moat/qualitative assessment are not implemented today
The system does not currently compute peer comparisons (P/E, P/B, ROE, growth, D/E vs. N
closest peers), sector-relative valuation framing, or any qualitative moat/pricing-power/
market-share assessment anywhere in `data/fundamentals.py` or `longterm/quality.py`. This
is stated explicitly as a gap (not silently assumed to exist) because it's squarely in
scope for the earlier fundamental-analysis enhancement request.

#### Scenario: No peer data is fetched or scored
- GIVEN a ticker is scored by either scorer
- WHEN the score is computed
- THEN no peer-relative metric (P/E-vs-peers, ROE-vs-peers, etc.) is read, stored, or
  used anywhere in either scoring path

### Requirement: Management guidance-vs-delivery exists, but only in the positional pipeline
The system MUST NOT be assumed to lack a guidance-vs-delivery mechanism outright — one
exists, but it lives in `positional/guidance.py` (the `guidance_ledger` table, extracted
via LLM from concall research and reconciled against next-quarter actuals as
`MET`/`BEAT`/`MISSED`/`UNVERIFIABLE`), feeding a management **credibility** score into the
positional scorecard's management pillar — not into either fundamental scorer in this
capability. See `specs/concall-research-and-guidance-ledger/spec.md` for the full
mechanism. A fundamental-analysis enhancement that wants "management track record" should
reuse/surface this existing ledger rather than build a second one.

## Known gaps / gotchas

- Two scorers, never reconciled — see Overview. `docs/INVESTMENT_ENGINE_DESIGN.md`
  itself lists "single fundamental source of truth" as an unresolved item.
- No peer comparison, no sector-relative framing, no qualitative moat assessment (see
  Requirement above) — the main net-new surface area for the fundamental-analysis
  enhancement.
- Governance bucket's pledge scoring uses 5/15/30% breakpoints, not a discrete ">10%"
  flag — an explicit pledge-threshold flag would be new behavior.
- `data/fundamentals.py`'s D/E normalization (`if debt_to_equity > 5: /= 100`) is a
  heuristic guess at whether yfinance returned a percentage or a ratio for a given
  ticker — stated here since it's a plausible source of occasional bad D/E readings.

## Source modules

`data/fundamentals.py` (361 lines), `longterm/quality.py` (650 lines),
`longterm/screener_scraper.py` (940 lines, not scenario-covered in detail above — it's
the scrape/parse layer feeding `quality.py`'s inputs).
