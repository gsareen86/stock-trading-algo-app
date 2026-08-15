# Scheduling & Orchestration

Status: baseline — not yet exercised through a change under `openspec/changes/`.

Process entry, the two always-on daemon threads, and the auto-arm-on-boot logic. Flagged
for extra care because this area has a documented history of behavior bugs.

## Requirements

### Requirement: One process, argparse-selected mode, two daemon threads
The system MUST start, by default (`python main.py` with no flags), both the intraday
runner thread and the positional runner thread plus the FastAPI server in one process.
Alternate modes (`--init`, `--runner-only`, `--dashboard-only`, `--positional-only`,
`--reset`) MUST run only the corresponding subset, selected via `argparse`, not a
scheduler library — despite `APScheduler` being declared in `requirements.txt`, it is
never imported; both runners are hand-rolled `while True: sleep(N)` polling loops.

#### Scenario: `--dashboard-only` mode
- GIVEN the operator runs `python main.py --dashboard-only`
- WHEN the process starts
- THEN only the FastAPI server starts — neither daemon thread runs, so no trading
  activity happens even though the dashboard is reachable and can display existing data

### Requirement: Intraday polling cadence adapts to time of day
The system MUST poll every ~15 minutes (`SIGNAL_POLL_INTERVAL_SEC`, 900s) under normal
conditions, switch to a 5-minute cadence after `NEAR_CLOSE_START` (15:00 IST) so the
15:10 square-off fires within 5 minutes of its cutoff, and poll on a longer (~30 min)
cadence when the market is closed.

#### Scenario: Poll tick at 15:12 IST
- GIVEN the time is 15:12 IST (past `NEAR_CLOSE_START` and past `SQUARE_OFF_TIME`)
- WHEN the intraday loop wakes for its next tick
- THEN it is on the 5-minute near-close cadence, not the normal 15-minute cadence — this
  is what keeps square-off from slipping more than ~5 minutes past its 15:10 cutoff

### Requirement: Positional runner is time-of-day scheduled, not interval-polled
The system MUST check wall-clock time against fixed IST targets inside its polling loop —
research refresh (~08:30), EOD scan (`POSITIONAL_SCAN_TIME`, 16:00), exit check
(`POSITIONAL_EXIT_TIME`, 15:20), Telegram summary (`POSITIONAL_ALERT_TIME`, 16:30), plus
a Saturday universe refresh (`UNIVERSE_REFRESH_WEEKDAY=5`, `UNIVERSE_REFRESH_TIME=10:00`)
and a monthly regime check — rather than firing on a fixed interval.

#### Scenario: Saturday at 10:00 IST
- GIVEN it is Saturday (`UNIVERSE_REFRESH_WEEKDAY=5`) at 10:00 IST
- WHEN the positional loop's tick lands at or after that time for the first time that day
- THEN the weekly universe refresh (full Screener pipeline sync) runs once — the loop
  tracks whether it already ran today to avoid re-triggering on every subsequent tick

### Requirement: Bot auto-arms on startup, but only on a trading day
The system MUST set bot status to `RUNNING` automatically at process start when the
current day is a weekday and not an NSE holiday (per
`specs/market-data-ingestion`'s holiday set), and MUST leave it `STOPPED` on a
non-trading-day boot. A user can always manually override via the dashboard regardless of
this auto-arm behavior.

#### Scenario: Restart during market hours on a trading day
- GIVEN the process restarts mid-session on a trading weekday
- WHEN `main()` runs its startup sequence
- THEN bot status is set to `RUNNING` automatically — this specific behavior (arming even
  on a late/mid-day restart, not only if the market was already open at the *previous*
  boot) was itself a past bug, fixed per an in-code comment describing the earlier,
  incorrect behavior

### Requirement: Auto-arm does not, by itself, re-trigger research/universe scans on restart
The system MUST NOT automatically re-run the positional research refresh or universe scan
solely because the process restarted late in the day — commit history shows this was
fixed after being a real problem (a server restart used to trigger a full re-scan/re-research
pass regardless of whether one had already run that day).

#### Scenario: Server restarts at 12:00 IST, after the 08:30 research-refresh time
- GIVEN the process restarts mid-day, after `POSITIONAL_RESEARCH_REFRESH_TIME` (08:30)
  has already passed for today
- WHEN the positional runner's boot logic initializes its per-day tracking variables
  (e.g. `_last_refresh_date`)
- THEN it seeds today's date into that tracker immediately at boot (since the current
  time is already past the target), so the research refresh does not fire again later
  that day purely because the process restarted

## Known gaps / gotchas

- This area has the most concrete, documented bug history in the codebase — multiple
  recent commits fix auto-arm/late-boot behavior specifically. Treat "what happens on
  restart" as needing direct verification against current `main.py`/`positional/runner.py`
  code before relying on any single comment in isolation, including the ones cited above.
- FinBERT is pre-warmed in a background thread at startup (if `ENABLE_FINBERT`) so the
  first news-sentiment cycle doesn't block for the ~3 minutes the ~400MB model takes to
  download/load — this is a startup-performance detail, not a scheduling rule, but lives
  in the same `main()` function.

## Source modules

`main.py`, `scheduler/runner.py`, `positional/runner.py`.
