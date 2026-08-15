# Broker Execution & Costs

Status: baseline — not yet exercised through a change under `openspec/changes/`.

Covers cost simulation for all books and the (stubbed) live-broker abstraction. Called out
as its own capability because "which books have any theoretical live-money path" is a
safety-relevant fact that would otherwise be buried inside per-book specs.

## Requirements

### Requirement: No live order routing exists anywhere in this codebase today
The system MUST NOT route any order to a real broker. All trading in every book is
paper/simulated.

#### Scenario: Positional broker set to a real-sounding value
- GIVEN `POSITIONAL_BROKER=sharekhan` or `POSITIONAL_BROKER=zerodha` is set (and the
  corresponding `.env.template`-documented API keys are filled in)
- WHEN a positional order would be placed
- THEN `SharekhanBroker`/`ZerodhaBroker` (`positional/broker.py`) unconditionally fail —
  their bodies are commented-out pseudocode (e.g. `# import sharekhan`,
  `# kite = KiteConnect(...)`) — and execution silently falls back to `PaperBroker`,
  logging a warning; no order is ever transmitted externally

### Requirement: Intraday has no broker abstraction at all, not even a stub
The system's intraday path (`engine/paper_broker.py`) MUST be understood as pure
cost-simulation code — it contains no broker classes, real or stubbed. There is no
`SharekhanBroker`/`ZerodhaBroker`-equivalent concept for the intraday book; a live-money
intraday path would need to be built from scratch, not toggled on from an existing stub.

#### Scenario: Looking for an intraday equivalent of `POSITIONAL_BROKER`
- GIVEN a developer wants to enable a real broker for intraday trading, expecting a
  config flag analogous to `POSITIONAL_BROKER`
- WHEN they search `config.py`/`engine/` for one
- THEN none exists — `engine/paper_broker.py::execute()` is the only execution path for
  intraday, and it only ever simulates a fill, per README's own "Expanding to live money"
  section

### Requirement: Intraday and delivery cost models differ
The system MUST apply Zerodha-style intraday costs (brokerage `min(₹20, 0.03%)`, STT
0.025% sell-leg-only, exchange 0.00322%, SEBI ₹10/crore, GST 18% on brokerage+exchange+SEBI,
stamp duty 0.003% buy-leg, 0.05% slippage) for intraday trades, and a distinct delivery
cost model for positional/swing trades (STT 0.1% on **both** legs, stamp duty 0.015% on
buy leg, other charges the same).

#### Scenario: Same trade value, different book
- GIVEN an identical trade value executed once intraday and once as a positional/delivery
  trade
- WHEN round-trip costs are compared
- THEN the positional trade's STT is 4× the intraday sell-leg-only STT rate, since it
  applies to both legs — the two books are not cost-equivalent per rupee traded

## Known gaps / gotchas

- `.env.template` documents `SHAREKHAN_API_KEY`/`ZERODHA_API_KEY` etc. as if they enable
  real functionality — setting them changes nothing observable except a log line.
- README's own "Expanding to live money" section correctly identifies
  `engine/paper_broker.py::execute()` as the boundary to replace for intraday — this spec
  extends that by making explicit that positional's stub classes are further along in
  *shape* (they exist) but equally non-functional in *substance*.

## Source modules

`engine/paper_broker.py` (96 lines), `positional/broker.py` (239 lines),
`positional/risk.py` (delivery cost constants).
