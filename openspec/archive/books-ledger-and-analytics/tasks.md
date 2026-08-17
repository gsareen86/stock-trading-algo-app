# Tasks: books-ledger-and-analytics

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: books-ledger (new), risk-management (new), platform-api (ADDED),
      data-persistence (ADDED), agent-graph (ADDED)

## Domain
- [x] `app/domain/position.py` — `Book`, `Side`, `Trade`, `Position`
- [x] Position derived from trades; average cost; gross P&L only

## Persistence
- [x] `trading.trades`, `trading.positions` — migration `0003`, RLS + service_role policy
- [x] `app/books/ledger.py` — one `Ledger`, book as a parameter
- [x] `fill()` is the only thing that creates a trade

## Analytics
- [x] `app/books/analytics.py` — exposure, concentration, realised/unrealised, win rate
- [x] Every P&L figure gross, and labelled

## Risk
- [x] `app/risk/rules.py` — portfolio gates: held, count, concentration, sector, capital
- [x] `app/risk/sizing.py` — size one verdict against portfolio state
- [x] Never ranks or allocates between verdicts
- [x] `risk` node in the graph, after the fan-in

## API
- [x] `GET /books/{book}/positions`, `/trades`, `/analytics`
- [x] `POST /books/{book}/fill`

## Tests
- [x] Position derived from trades, never stored independently
- [x] Buy then partial sell leaves the right quantity and average cost
- [x] Full exit realises P&L and closes the position
- [x] Adding a book is an enum member and nothing else
- [x] Risk vetoes without altering any verdict field
- [x] Risk never compares two verdicts
- [x] Concentration and count gates block as specified
- [x] P&L excludes charges and is documented as gross
