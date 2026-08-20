# feed-freshness-and-run-control

## Intent

Make the feed describe the present, and let a person start a cycle from the application.

## Why

The feed currently shows observations that were true when a cycle wrote them and have never
been revisited. Two are on screen right now, from a cycle run on 17-Aug:

* *"RELIANCE is 35.1% of the book"* — the position was closed to zero 26 minutes after that
  cycle ran. The book holds no RELIANCE at all.
* *"benchmark weekly close 24366.00 above its 30-week average"* — correct on 14-Aug. The Nifty
  closed at 24078.30 on 19-Aug, and the cached price data has said so since 20:42 that day.

Neither is a data bug. `^NSEI` daily bars are fetched, cached and correct; the ledger is
correct. The insight rows are frozen, and **the suppression key is what freezes them**:
`regime_change:constructive` and `concentration:RELIANCE:35` both suppress every later
candidate, so the row that stands is permanently the first one ever written.

Suppression is right and stays. What is missing is its counterpart: an observation that is no
longer true must stop being displayed. `insights-feed` specified "repeated observations are
suppressed, not repeated" and never specified what happens when the observation ends.

The second half is smaller and related. `POST /cycles/run` has existed since
`agent-graph-and-a2a` and **no surface calls it**. There is no button anywhere in the web app
that runs a cycle, which is why nothing has refreshed since 17-Aug. A feed that can only be
refreshed with `curl` will go stale again the day after this change ships.

## In scope

- **Withdrawal** — a standing insight whose precondition no longer holds is withdrawn, with
  the reason recorded. Distinct from being read, and distinct from suppression.
- **Refreshing a standing measurement** — an insight that is still true but whose figure has
  moved updates that figure in place, without minting a new row or resetting its age.
- **`POST /cycles/run` reachable from Today**, with the run's outcome reported.
- **Seam report honesty** — the Feed card reports the feed's actual state; observability
  reports "off by configuration" rather than a degraded seam when no Langfuse key is set.

## Out of scope

- **Scheduling.** Nothing in this change runs a cycle on a timer. Ad-hoc and weekly scheduled
  runs arrive with `discovery-funnel`, which is the change that has something worth scheduling.
- **Progress reporting while a cycle runs.** `progress-visibility` covers it; this change makes
  the button exist, and it will be an honest button that blocks until the run finishes.
- **Deleting insights.** Withdrawal hides an observation from the feed and keeps the row —
  "this was true for eleven days and then stopped" is the history the feed exists to carry.
- **Re-ranking the feed.** Severity stays a property of the kind.

## Risks

- **Withdrawal could hide something a person still needs to see.** Mitigated by making it
  observable: a withdrawn insight is retrievable, carries why it was withdrawn, and withdrawal
  happens only when the generating rule's own precondition is re-evaluated as false — never on
  a timer, and never because a row is old.
- **Re-deriving on every cycle costs a ledger read per standing insight.** Bounded by the feed
  cap that already exists; a feed large enough for this to matter is already a broken feed.
