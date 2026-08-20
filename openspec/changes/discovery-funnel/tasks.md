# Tasks: discovery-funnel

Depends on `research-data-sources` for financials, Nifty 500 and the widened sector set, and on
`progress-visibility` for reporting a scan that takes minutes.

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: discovery (new), decision-model (ADDED), web-shell (ADDED + MODIFIED),
      platform-api (ADDED)
- [ ] `openspec/specs/discovery/` created on archive; `project.md` surface table updated

## Persistence
- [ ] Migration `0007` — `scan_runs`, `scan_entries`; run carries trigger, universe origin,
      outcome, timestamps
- [ ] Unevaluable instruments recorded on the run with their reason
- [ ] Runs are append-only; no run is ever overwritten

## Discovery module — `app/discovery/`
- [ ] `sectors.py` — relative strength and its change per sector index, quadrant placement
- [ ] Insufficient history → unplaced with reason, never a defaulted quadrant
- [ ] Benchmark named on every placement; `^CRSLDX` and `^NSEI` both selectable
- [ ] `movers.py` — declared thresholds, each mover carrying measurement and threshold
- [ ] `ranking.py` — order by max conviction from one strategy, that strategy named;
      ties keep universe order
- [ ] `quality.py` — per-measure assessment from `CompanyFinancialsSource`, sector-aware
      applicability, no composite score
- [ ] Assert no function anywhere in `app/discovery/` computes across verdicts
- [ ] Nothing added to `app/screening/` — its no-ranking test must still pass

## Strategy plans
- [ ] `Plan` in `app/domain/` — entry, stop, target, holding condition, evidence refs
- [ ] Risk and reward distances in rupees and percent, with ratio where a target exists
- [ ] `minervini` — pivot from the VCP base high, stop at base low, 10-week average exit
- [ ] `young_momentum` — continuation level, pause low, higher-high failure
- [ ] `brahma_vishnu_mahesh` — base breakout, base floor, sector/regime exit condition
- [ ] `fun_tech_momentum` — breakout, base low, growth-confirmation exit
- [ ] No plan on AVOID; no plan where the method implies none — absence stated
- [ ] Plans identical with narration off

## Scan
- [ ] Runner over the eligible universe, all four strategies, persisted as one run
- [ ] Narration confined to the ranked head, after ranking
- [ ] On-demand trigger; scheduled weekly trigger; trigger recorded on the run
- [ ] A second concurrent scan is refused, naming the run in progress
- [ ] A failed scan is recorded failed; the previous success stays latest-successful

## API
- [ ] `GET /discovery/sectors`
- [ ] `GET /discovery/movers?sector=`
- [ ] `POST /discovery/scan`, `GET /discovery/runs`, `GET /discovery/runs/{id}`
- [ ] Result filters: minimum BUY count, quality measure — ordering rule unchanged
- [ ] Plans served with verdicts wherever verdicts are served

## Web
- [ ] Ideas rebuilt: market panel → sector quadrants → candidates from the latest run
- [ ] `DEFAULT_SYMBOLS` deleted from Ideas; Stock's `"RELIANCE"` default deleted
- [ ] Stock with no symbol asks for one
- [ ] Candidate rows link to Stock; ranking strategy named on every row
- [ ] Plans rendered inside their own strategy's card, levels reaching their evidence
- [ ] "No scan yet" and "scan is N days old" are distinct from an empty result
- [ ] Symbol autocomplete on Stock, from the universe snapshot

## Tests
- [ ] Strong + rising → leading; strong + falling → weakening; weak + rising → improving
- [ ] Insufficient history → unplaced, not defaulted
- [ ] Placement carries no stance or conviction
- [ ] A sector with no threshold crossings returns no movers
- [ ] **Ranking figure is attributable to exactly one named strategy**
- [ ] **Grep `app/discovery/` for mean/sum/count over verdicts used to order — none**
- [ ] Agreement filter selects without changing the ordering rule
- [ ] Ties keep universe order
- [ ] **A name failing every quality measure is still evaluated by all four strategies**
- [ ] Quality measures individually visible; no composite
- [ ] Leverage measure not applicable to a bank rather than failed
- [ ] Unavailable financials → unavailable measure, not a failed one
- [ ] A scan is reproducible with narration off
- [ ] Runs are append-only; unevaluable names recorded with reasons
- [ ] Concurrent scan refused
- [ ] **Every plan level cites an evidence row from its own verdict**
- [ ] No plan on AVOID; absence stated rather than defaulted
- [ ] Plans identical with narration on and off
- [ ] No merged plan across strategies exists
- [ ] Web: no hard-coded symbol list in any surface source
- [ ] Web: existing no-aggregation grep extended to the candidate list
