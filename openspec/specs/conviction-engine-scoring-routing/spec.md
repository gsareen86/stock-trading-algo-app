# Conviction Engine — Scoring & Routing

Status: **full baseline** — the architectural spine connecting fundamentals, technicals,
sentiment, and management research into one routing decision across the positional and
long-term books. Full depth because this is the seam most likely to confuse "what's
running" if left underspecified.

## Overview

`positional/scorer.py` and `positional/pillars.py` turn the four positional strategies
plus up to five contextual pillars (quality, valuation, momentum, sentiment, management)
into one **Scorecard** per ticker: a composite score, a two-axis Timing/Durability
classification, and a horizon label that determines which book(s) a candidate is routed
to. This spec does **not** cover intraday scoring (see `specs/intraday-trading`) — the
conviction engine is positional/long-term only.

## Requirements

### Requirement: Technical (timing) pillar blends strategy signals with a confluence bonus
The system MUST compute the technical pillar as the weight-normalized average of every
firing (`action == "BUY"`) positional strategy's score, using `POSITIONAL_STRATEGY_WEIGHTS`
(`minervini_vcp` 0.30, `brahma_vishnu_mahesh` 0.25, `fun_tech_momentum` 0.25,
`young_momentum` 0.20; an unrecognized strategy name defaults to weight 0.05), plus a
`POSITIONAL_CONFLUENCE_BONUS` (8.0 points) for each additional strategy beyond the first
that agrees, clipped to `[0, 100]`.

#### Scenario: No strategy fires
- GIVEN zero positional strategies return a BUY signal for a ticker
- WHEN the technical pillar is computed
- THEN the score is `0.0`, confluence is `0`, and `est_hold_days` defaults to `15`

#### Scenario: Two strategies agree
- GIVEN two strategies both fire BUY with scores 70 and 80
- WHEN the technical pillar is computed
- THEN the base score is the strategy-weighted average of 70 and 80, and one
  `POSITIONAL_CONFLUENCE_BONUS` (8 points) is added for the second agreeing strategy,
  then clipped to 100

### Requirement: Composite and Durability are weighted blends over present pillars only
The system MUST blend whichever of the six pillars (technical, quality, valuation,
momentum, sentiment, management) have a non-`None` value, using `POSITIONAL_PILLAR_WEIGHTS`
(technical 0.35, quality 0.18, valuation 0.10, momentum 0.13, sentiment 0.12, management
0.12) for the composite, and `POSITIONAL_DURABILITY_WEIGHTS` (quality 0.45, valuation
0.30, management 0.25) for Durability — renormalizing over whichever weights correspond
to present pillars, not treating a missing pillar as zero.

#### Scenario: Management pillar not yet researched
- GIVEN a ticker has no management score yet (Phase-3 research hasn't run)
- WHEN the composite and Durability are computed
- THEN both blends renormalize over the remaining present pillars — a missing management
  score does not drag the composite toward zero, nor does it block scoring entirely

#### Scenario: No pillars present at all
- GIVEN every pillar value is `None`
- WHEN `_blend` is called
- THEN it returns `50.0` (neutral midpoint), not zero and not an error

### Requirement: Horizon classification crosses Timing against Durability independently
The system MUST classify a ticker's horizon by comparing the technical (timing) score
against `POSITIONAL_TIMING_STRONG` (60.0) and Durability against
`POSITIONAL_DURABILITY_STRONG` (60.0) as two independent booleans:

#### Scenario: Both axes strong
- GIVEN timing ≥ 60 AND durability ≥ 60
- WHEN horizon is classified
- THEN the label is `BOTH`

#### Scenario: Timing strong, durability weak
- GIVEN timing ≥ 60 AND durability < 60
- WHEN horizon is classified
- THEN the label is `POSITIONAL`

#### Scenario: Timing weak, durability strong
- GIVEN timing < 60 AND durability ≥ 60
- WHEN horizon is classified
- THEN the label is `LONG_TERM` (a watch/accumulate candidate — not an immediate buy in
  either book; see Requirement below)

#### Scenario: Neither axis strong
- GIVEN timing < 60 AND durability < 60
- WHEN horizon is classified
- THEN the label is `AVOID`

### Requirement: A BUY action requires timing strength, not just a favorable horizon label
The system MUST gate the `BUY` action on the timing score alone (`timing >=
min_composite`, default `POSITIONAL_MIN_TREND_SCORE`) when the horizon is `BOTH` or
`POSITIONAL` — a strong chart with average fundamentals can still trigger a positional
buy. `LONG_TERM` horizon alone MUST NOT produce a `BUY` action.

#### Scenario: LONG_TERM horizon produces WATCH, not BUY
- GIVEN a ticker classifies as `LONG_TERM` horizon (durable business, no current setup)
- WHEN the action is determined
- THEN the action is `WATCH`, never `BUY` — durability alone never triggers an entry

#### Scenario: Weak-but-firing ticker still gets WATCH, not silently dropped
- GIVEN horizon is `AVOID` but at least one strategy fired (confluence ≥ 1)
- WHEN the action is determined
- THEN the action is `WATCH` (not `HOLD`) — a lone signal below the routing bar is still
  surfaced, not discarded

### Requirement: Conviction level is a separate signal from action/horizon
The system MUST compute a `conviction` of `high`/`medium`/`low` independently of the
action: `high` when confluence ≥ 2 AND durability ≥ `POSITIONAL_DURABILITY_STRONG`, OR
when ≥ 2 individual strategy signals are themselves marked high-conviction; `medium` when
confluence ≥ 1 (and high wasn't met); `low` otherwise.

#### Scenario: Single high-conviction strategy signal overrides confluence
- GIVEN only one strategy fires, but that signal is itself marked `conviction="high"`,
  and a second high-conviction signal also exists
- WHEN conviction is computed
- THEN the scorecard conviction is `high` even without 2-strategy confluence, because the
  `high_count >= 2` branch is independent of the confluence-and-durability branch

## Known gaps / gotchas

- This scoring/routing logic is positional/long-term only — the intraday book has an
  entirely separate composite (`scoring/composite.py`, see `specs/intraday-trading`) with
  no Timing/Durability concept at all.
- `recompute()` (used when Phase-3 research adds the management pillar after initial
  scoring) can change Durability and the horizon label but explicitly cannot change the
  Timing score — a POSITIONAL candidate can be upgraded to BOTH by new research, but a
  BUY decision already made on timing can't be un-made by a later durability change.
- The Durability threshold (`POSITIONAL_DURABILITY_STRONG`, 60.0) and the Long-Term book's
  own entry gate (`LT_DURABILITY_GATE`, 70.0, in `config.py`) are different numbers for a
  similar-sounding concept — routing to the `LONG_TERM` watch label uses 60, but actual
  entry into the Long-Term book (`specs/long-term-book`) requires 70. Not a bug, but easy
  to conflate.

## Source modules

`positional/scorer.py` (252 lines), `positional/pillars.py` (170 lines — quality/
valuation/momentum/sentiment pillar functions), `config.py` (weight/threshold constants).
