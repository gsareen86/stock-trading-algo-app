# Tasks: portfolio-health-and-actions

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: portfolio-health (new), insights-feed (ADDED), platform-api (ADDED)
- [x] `project.md`: legacy data is never read; roadmap resequenced

## Health
- [x] `app/health/components.py` — concentration, diversification, deployment, thesis integrity
- [x] Each carries measurement, threshold, score and weight
- [x] `app/health/score.py` — weighted headline, components always published
- [x] Never reads a conviction; never ranks instruments

## Guidance
- [x] Steps attached to the component that produced them
- [x] Ordered by component weight, not by a per-step score
- [x] Deterministic — no model, every number from the ledger or a threshold

## Actions
- [x] `app/insights/actions.py` — actions declared per kind
- [x] `review` always available
- [x] Quantity re-derived from the ledger at execution, never from the insight payload
- [x] Refused when the position changed or the derived quantity is zero
- [x] Executes through `Ledger.fill()` — no second path
- [x] `preview: true` runs the same derivation without writing

## API
- [x] `GET /books/{book}/health`
- [x] `POST /insights/{id}/act`
- [x] Insight responses list their available actions

## Tests
- [x] Each component scores its own property against its threshold
- [x] Headline never appears without components
- [x] Health never reads a verdict or a conviction
- [x] Guidance is ordered by weight; no per-step score exists
- [x] `exit` sells the current holding, not the insight's remembered quantity
- [x] A stale insight whose position is gone is refused
- [x] Preview writes nothing and matches execution
- [x] Acting goes through `Ledger.fill()`
