# Tasks: feed-freshness-and-run-control

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: insights-feed (ADDED + MODIFIED), platform-api (ADDED),
      web-shell (ADDED + MODIFIED)

## Persistence
- [x] Migration `0006` — `withdrawn_at`, `withdrawal_reason`, `measured_at` on `insights`
- [x] Backfill `measured_at` from `created_at` for existing rows
- [x] Index on `withdrawn_at` so the default feed query stays one scan
- [x] **Rewrite the banded dedupe keys** — `concentration:TCS:60` → `concentration:TCS`,
      `book_full:8` → `book_full`. Not anticipated by the proposal; found against live data,
      where a banded row failed to match its own unbanded candidate and was withdrawn as
      though the observation had ended

## Insights
- [x] `rules.Assessed` — what the cycle re-checked, and the licence to withdraw
- [x] Dedupe keys unbanded; the band was a workaround for having no refresh
- [x] `feed.reconcile()` — withdraw where the key is absent, refresh where the figure moved,
      leave everything else untouched
- [x] Refresh writes `title`, `body`, `payload`, `measured_at` only — never `created_at`
      or `read_at`
- [x] Reconciliation scoped to the kinds and tickers whose rules actually ran
- [x] A changed label mints a new insight; a moved figure does not
- [x] Suppression distinguishes standing from withdrawn — a standing row is never duplicated
      by age, a withdrawn one may recur once its window has passed

## Graph
- [x] `insights` node reconciles before recording
- [x] Per-kind `Assessed` scopes: book-wide for concentration and book_full, verdict-scoped
      for thesis_broken, risk-scoped for opportunity, research-scoped for news and events,
      absent entirely when the regime could not be read
- [x] Cycle result reports written / suppressed / truncated / refreshed / withdrawn

## API
- [x] `GET /insights?include_withdrawn=` — default false
- [x] Withdrawn rows carry reason and time; unread count ignores them
- [x] Acting on a withdrawn insight is refused as stale — 409, not 404

## Web
- [x] Today: "Run scan" control posting to `/cycles/run`, disabled while in flight
- [x] Outcome reported inline by named counts; a failure leaves the existing feed on screen
- [x] Seam report Feed card reads the real feed state
- [x] Observability renders as **off by configuration** — a fourth `StatusDot` state, neither
      green nor amber, because a service nobody chose to use is not a fault
- [x] Every insight shows when its figures were last measured

## Tests — 772 passing, ruff clean
- [x] A closed position withdraws its concentration insight, with the reason
- [x] A repaired thesis withdraws its `thesis_broken` insight
- [x] A standing insight is never withdrawn for age alone
- [x] A symbol-scoped cycle withdraws nothing about names it did not evaluate
- [x] A rule that did not run withdraws nothing
- [x] An empty assessment withdraws nothing
- [x] A refreshed insight keeps `created_at` and `read_at`
- [x] A still-constructive regime reports the newer benchmark level
- [x] A regime that flips mints a new insight
- [x] Withdrawal writes no trade
- [x] Default listing omits withdrawn; `include_withdrawn` returns them with reasons
- [x] Unread count ignores withdrawn
- [x] Suppression: standing never duplicated by age; recurrence after withdrawal is raised
- [x] Migration: banded keys rewritten, unbanded ones left alone, `measured_at` backfilled
- [x] **Test isolation** — `import litellm` calls `load_dotenv()`, which copies `backend/.env`
      onto `os.environ` and defeats `Settings(_env_file=None)`. Ten tests began failing by
      collection order the moment a real `.env` existed. conftest now forces that import at
      collection and strips every settings-derived key per test

## Cleanup
- [x] The four rows standing in `trading.db` reconciled by running the real code path, not by
      editing the table: RELIANCE's concentration insight withdrew itself as "position is
      closed", TCS refreshed in place from 64.9% to 100.0% keeping its original age

## Not done — for the next change
- [ ] **Restatement.** `thesis_broken` had `suppress_days=7` meaning "worth restating weekly",
      which worked by writing a second row. Standing rows are no longer duplicated, so a
      broken thesis marked read three weeks ago stays read and quiet. Re-opening a standing
      insight after its window (clearing `read_at` rather than writing a row) would restore
      the intent — it needs a sixth count on the cycle report and its own scenarios, so it is
      deliberately not smuggled in here
