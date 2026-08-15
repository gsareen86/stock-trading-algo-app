# Outcome Tracking & Backtesting

Status: baseline — not yet exercised through a change under `openspec/changes/`.

Infrastructure meant to eventually validate the many hand-tuned thresholds elsewhere in
the system with evidence rather than intuition. Explicitly advisory — nothing here
auto-applies a change to trading behavior.

## Requirements

### Requirement: Every signal type gets forward returns attached automatically
The system MUST attach forward 5/20/60-day returns (`OUTCOME_HORIZONS_DAYS`) to every
scan score, LLM research verdict, veto decision, news-impact alert, and management-score
snapshot via a daily EOD job joining against cached prices, capped at
`OUTCOME_JOB_MAX_TICKERS` (25) tickers per run.

#### Scenario: More eligible signals than the daily cap
- GIVEN more than 25 tickers are eligible for forward-return computation on a given day
- WHEN the daily outcome job runs
- THEN it processes at most 25 that run — 🚩 the exact selection/carry-over behavior for
  the remainder (whether it's prioritized, and whether uncomputed tickers are picked up
  on a later run or simply re-evaluated fresh next day) is not yet verified against
  `analytics/outcomes.py`'s implementation; confirm before relying on completeness of
  historical outcome coverage

### Requirement: Backtester covers positional/swing timing only, and is explicitly optimistic
The system's walk-forward backtester (`backtest/engine.py`) MUST be understood as
validating the positional/swing technical-timing/exit/sizing layer only — it has no
historical snapshot of quality/sentiment/management pillars or the LLM veto (those are
live-computed today, not stored historically), and stops fill at the candle close, which
the module's own docstring documents as optimistic during crash periods. **No backtester
exists for the intraday book.**

#### Scenario: Backtest result interpretation
- GIVEN a walk-forward backtest reports a Sharpe ratio and win rate for the positional
  strategies
- WHEN those results are used to judge overall system quality
- THEN they should be read as a lower/optimistic bound on technical-layer performance
  only — not as validation of the full scoring pipeline (quality/sentiment/management
  pillars are untested by this backtester)

### Requirement: Calibration is advisory-only and refuses to recommend below a sample floor
The system's calibration report (`analytics/calibration.py`) MUST refuse to recommend any
threshold change below `MIN_OUTCOMES_FOR_CALIBRATION` (200) collected outcomes, and MUST
NOT auto-apply any recommendation it does produce — it is a report for human review only.

#### Scenario: Fewer than 200 outcomes collected
- GIVEN the `signal_outcomes` table has 120 rows
- WHEN the calibration report is generated
- THEN it declines to recommend threshold changes, stating the sample size is
  insufficient, rather than producing a recommendation anyway

## Known gaps / gotchas

- The gap between "a backtester exists" and "the full scoring pipeline is backtested" is
  easy to overstate when discussing this system informally — worth being precise about
  which layer is actually validated.
- `ENABLE_ML_META_MODEL`/`ENABLE_ADAPTIVE_WEIGHTS` (see
  `specs/llm-platform-and-feature-toggles`) are explicitly designed to hand off from this
  outcome data once ≥200 closed trades exist, per README — but no such model exists yet.

## Source modules

`analytics/outcomes.py`, `analytics/calibration.py`, `backtest/engine.py`.
