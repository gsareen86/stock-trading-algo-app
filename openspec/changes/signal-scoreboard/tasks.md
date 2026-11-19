# Tasks: signal-scoreboard

Reads what `discovery-funnel` persists; adds no table and no migration.

## Spec
- [x] `proposal.md`, `tasks.md`
- [x] Deltas: discovery (ADDED), platform-api (ADDED), web-shell (ADDED)
- [ ] Merge deltas into `openspec/specs/` and move to `openspec/archive/` once a few weeks of
      real scans have been read through it

## Backend — `app/discovery/scoreboard.py`
- [x] Collect every verdict from the most recent completed scans; failed runs ignored
- [x] `is_new`: stance differs from the immediately preceding completed scan
- [x] Entry at the first session open after the scan; same-day open when the scan finished
      before 09:15 IST
- [x] Bars keyed by IST session date, correct for midnight-UTC and midnight-IST stamps
- [x] Return to the Nth session's close; benchmark over the same sessions; excess in pp
- [x] Stop traded through inside the window, when the verdict carried a plan stop
- [x] Pending (window open) and unpriced (no history) reported, never scored
- [x] Summary per strategy → stance → conviction band; bands shown only when more than one
- [x] Mean, median, standard error of excess, share beating the benchmark, thin flag
- [x] Biases and method carried on every result; `charges_included: false`
- [x] One price fetch per symbol, batch prefetch when the source supports it

## API
- [x] `GET /discovery/scoreboard` — `signals=new|all`, `strategy_id`, `horizons`, `max_runs`,
      `refresh`; computed off the event loop
- [x] Memoised per latest completed scan, IST day and parameters

## Web
- [x] Signal Scoreboard on Performance: horizon and new/all toggles, per-strategy tables,
      recent BUYs, method and biases
- [x] No cross-strategy figure and no ordering by results in the surface

## Tests — `tests/test_scoreboard.py`
- [x] Entry timing: after the open, before the open, weekend, midnight-IST bars
- [x] Return, benchmark and excess arithmetic against hand-built bars
- [x] Pending and unpriced paths
- [x] Stop touched / not touched / absent
- [x] Strategies never pooled; alphabetical; bands only when informative; thin flag
- [x] Repeat stances are not new; only the most recent runs are read
- [x] API happy path and parameter validation
