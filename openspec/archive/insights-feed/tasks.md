# Tasks: insights-feed

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: insights-feed (new), agent-graph (ADDED), platform-api (ADDED),
      data-persistence (ADDED)

## Persistence
- [x] Migration `0004` — `dedupe_key`, `severity` on `insights`, indexed
- [x] `app/insights/feed.py` — record with suppression, list, mark read, unread count

## Generators
- [x] `thesis_broken` — held name whose own strategy now says AVOID
- [x] `concentration` — holding above the cap
- [x] `event_due` — earnings or corporate action on a held name
- [x] `position_news` — news or filing on a held name, quoted not asserted
- [x] `opportunity` — a verdict risk assessed as actionable
- [x] `book_full`, `regime_change`
- [x] Severity declared per kind; no per-item score

## Graph
- [x] `insights` node, last, reading risk and narrate output
- [x] Cap per cycle, high severity first

## API
- [x] `GET /insights`, `GET /insights/unread-count`, `POST /insights/{id}/read`
- [x] No email, push or messaging channel anywhere

## Tests
- [x] A held name going AVOID raises `thesis_broken`
- [x] An unheld name going AVOID raises nothing
- [x] The same insight twice inside the window is suppressed
- [x] Suppression does not delete the original
- [x] Research-derived insights name their tool and source
- [x] The per-cycle cap is applied high severity first
- [x] Insights never fill, never alter a verdict
- [x] No delivery channel exists
