# signal-scoreboard

## Intent

Measure what happened after every verdict a scan published, so a reader can tell whether a
strategy's BUY has meant anything before trusting the next one.

## Why

The platform publishes verdicts and plans every week and has never once checked them. Every
completed scan is already persisted whole (`scan_runs`, `scan_entries`), so the record needed to
answer "did the signals work?" exists and is unread.

The backtest cannot answer it either. It replays today's index members (survivorship), buys at
any BUY and exits after a fixed hold, ignores the strategies' own stops and exits, has no
benchmark, and reads current fundamentals at historical dates. A forward record of verdicts as
they were actually published has none of those problems: the verdicts are the real ones, made
with only the data that existed at the time.

## In scope

- **Forward returns per published verdict** at fixed holding periods (default 5, 20 and 60
  sessions), from the first tradable open after the scan to the Nth session's close.
- **Excess over the scan's own benchmark** over exactly the same sessions.
- **Whether the plan's stop was traded through** inside each window, where a plan exists.
- **Grouping by strategy, then stance, then conviction band** — the layout of a factor tear
  sheet (mean by bucket with its standard error), with stances in place of factor quantiles.
- **New signals by default.** A stance unchanged since the previous scan is a repeat, not a new
  decision; counting it again inflates the sample with overlapping windows. Every scan's verdict
  is available on request and labelled as overlapping.
- **Thin samples flagged**, below 30 measured signals.
- **The biases carried on the result**, as the backtest does.
- A **Signal Scoreboard** section on Performance, with the recent BUYs and how each went.

## Out of scope

- **Any figure across strategies.** Pooling one strategy's BUY with another's is the confluence
  scorecard measured after the fact. Strategies are listed alphabetically, never by results.
- **Changing any verdict, stance, conviction or ranking** because of a result. The scoreboard is
  read by a person; it feeds nothing back.
- **Charges.** Reported gross and labelled so; costs need their own change.
- **Fixing the backtest.** It remains a separate question with its own change.

## Risks

- **A few weeks of scans is anecdote.** Mitigated by the thin-sample flag, the standard error on
  every mean, and a note on the result while fewer than four scans exist.
- **Overlapping windows** make consecutive weekly signals dependent; the standard error is
  optimistic. Stated on the result; reduced by counting new signals only.
- **A delisted name has no forward bars** and shows as pending or unpriced, not as a loss.
