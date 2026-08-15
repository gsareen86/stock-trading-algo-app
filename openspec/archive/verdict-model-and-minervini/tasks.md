# Tasks: verdict-model-and-minervini

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: decision-model, strategies, platform-api

## Domain
- [x] `app/domain/verdict.py` — `Stance`, `Evidence`, `GateResult`, `Verdict`
- [x] Invariants at construction: failed gate forces AVOID, unique evidence ids, gates cite
      existing rows, evidence non-empty, conviction in range, source_ref non-empty

## Strategy framework
- [x] `app/strategies/protocols.py` — `Strategy`, `StrategyContext`, `StrategyDefinition`
- [x] `app/strategies/registry.py` — discovery by convention, load failures recorded
- [x] `app/strategies/indicators.py` — SMA, slope, 52-week range position, benchmark relative
      strength, swing pivots and contractions

## Minervini
- [x] `minervini/trend_template.py` — all eight criteria, one evidence row each
- [x] `minervini/vcp.py` — contraction count, depths, volume dry-up
- [x] `minervini/strategy.py` — gates, conviction formula, stance thresholds

## Persistence
- [x] `app/persistence/verdicts.py` — save and query over `trading.verdicts` (no migration)

## API
- [x] `GET /strategies`, `POST /verdicts/evaluate`, `GET /verdicts`

## Tests (offline)
- [x] Every verdict invariant, each rejected case
- [x] No cross-strategy aggregation exists on the public surface
- [x] Indicators against hand-built series with known values
- [x] Trend Template: full pass on an uptrend, failures on a downtrend
- [x] Criteria reduce conviction rather than gating
- [x] Gates: short history, no data, zero volume
- [x] RS against benchmark, incl. benchmark missing; field not named as a rating
- [x] VCP: tightening base, no base, single contraction
- [x] Conviction reproducible and in range
- [x] Verdict round-trip through storage
- [x] API shapes, persist flag, unknown strategy, bounds

## Verify & ship
- [x] `pytest`, `ruff`; endpoints live
- [x] Archive deltas into `openspec/specs/`, move change to `openspec/archive/`
- [x] Commit, push
