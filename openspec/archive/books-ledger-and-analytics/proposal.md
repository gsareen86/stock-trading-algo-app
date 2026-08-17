# books-ledger-and-analytics

## Intent

One position ledger, parameterised by book — and the `risk` node that has been missing from the
cycle since `agent-graph-and-a2a`.

## Why

The predecessor kept **three duplicate position ledgers**, one per trading book. They drifted,
and reconciling them was impossible because none of them was authoritative. That is design
principle 2, and this is the increment that honours it: *one* ledger abstraction, with the book
as a parameter rather than as a reason to copy the code.

Everything downstream is currently blocked on there being no positions:

- **`risk` cannot exist.** The cycle fans four strategies into `narrate` and stops. A risk node
  applies portfolio gates and sizing, and both are questions about what you already hold.
- **A verdict has no consequence.** `BUY` on a name already held at full size is a different
  statement from `BUY` on a name you own none of, and the platform cannot currently tell them
  apart.
- **`insights-feed` and `backtesting` both read positions**, and neither can start.

## In scope

- **`app/books/`** — one `Ledger`, parameterised by book (`swing`, `longterm`)
- **`Position` and `Trade`** as domain types, with realised/unrealised P&L
- **`trading.positions` and `trading.trades`** — migration `0003`, same posture as `0001`/`0002`
- **One explicit paper-execution boundary** — a single `fill()` that records a trade and moves a
  position, with no broker class anywhere that silently does nothing
- **Portfolio analytics** — exposure, concentration, open risk, realised and unrealised P&L
- **The `risk` node** — portfolio gates and position sizing that may *veto* a verdict but never
  rewrite one
- **`GET /books/{book}/positions`**, **`/trades`**, **`/analytics`**, **`POST /books/{book}/fill`**

## Out of scope

- **Live order routing.** Principle 7 is paper-only with one explicit execution boundary. This
  change builds that boundary; connecting it to a broker is a separate decision with a separate
  spec, and Kite's mutating tools are already refused at the MCP seam.
- **Importing the predecessor's 472 trades and 206 positions.** They are real history and worth
  reading, but an import is a data-migration change with its own reconciliation questions —
  and `backtesting` is the increment that actually needs them. The legacy tables stay
  untouched, as they have since `0001`.
- **Tax lots and charges.** Indian STCG/LTCG treatment, STT, brokerage and stamp duty change
  what a "realised P&L" number means. Modelling them badly is worse than not modelling them, so
  P&L here is explicitly gross, and labelled as such.
- **Automatic fills from verdicts.** A `BUY` verdict does not become a position. Something has
  to decide, and that decision is the user's until an increment specifies otherwise.

## Risks

- **A ledger that silently loses a fill is worse than no ledger.** Every mutation is a recorded
  trade, and a position is derived from its trades rather than stored as an independently
  editable number.
- **Sizing is where a "score" would come back.** Risk sizes a *single* verdict against portfolio
  state; it never compares two strategies' verdicts to pick between them. Asserted by test.
