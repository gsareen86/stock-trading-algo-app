# backtest-plans

## Intent

Replay each strategy the way its own plan says to trade it, and measure the result against the
market after costs, so a backtest answers "would following this strategy have worked?".

## Why

The replay that shipped with `backtesting` tested something no strategy describes. It bought at
the next open on any BUY and sold after a fixed 40 sessions, so:

* **The plans were never used.** Every actionable verdict now carries an entry (a breakout
  pivot), a stop and an exit rule (`discovery-funnel`). The replay ignored all three.
* **No stop, no exit rule.** A trade could fall through its stop and be held to day 40.
* **No benchmark.** A positive gross P&L in a rising market says nothing about the strategy.
* **No costs.** At swing frequency, STT alone is 0.2% of every round trip.
* **Conviction was never tested**, although "does conviction mean anything" is one of the three
  questions the backtesting spec says replay exists to answer.
* **Fundamentals leaked from the future.** `fun_tech_momentum` read today's quarterly results
  at every historical date.
* **Brahma-Vishnu-Mahesh could never pass.** Instruments were built from bare symbols with no
  sector, so its sector-rank criterion failed on every evaluation.
* **One shared book.** Two strategies holding the same name were folded into one average cost.
* **Nothing before 2026 could be replayed.** The bundled holiday calendar covers 2026 only and
  refuses other years; the replay had no other source of sessions.

## In scope

- **Entry as the plan's buy-stop**, live for a stated number of sessions: fill at the open on a
  gap through it, at the entry when the session trades through it; skip when the open is more
  than a stated percentage above it; withdraw when the stop trades first. A BUY without a plan
  is counted, not traded. The old next-open behaviour stays available as `entry_mode`.
- **Stops checked every session**; a gap fills at the open; an entry session that also trades
  through the stop is assumed stopped.
- **Each strategy's exit rule** restated on daily bars (`app/backtest/exits.py`), with what it
  cannot test stated; **thesis-broken exits** when the buying strategy says AVOID; a hold limit.
- **Per-trade measurement**: return, net of a declared round-trip cost and per-fill slippage,
  R-multiple, and excess over a benchmark over the same sessions; distribution per strategy and
  per conviction band, with thin samples flagged.
- **Point-in-time fundamentals** by SEBI LODR filing deadline (45 days; 60 for March).
- **Sectors** for every instrument, from the universe and the bundled Total Market list.
- **One ledger per strategy.**
- **Sessions from the market's own record** for years the calendar does not cover.
- **Parallel replay by symbol**, and a command line (`python -m app.backtest.cli`) for
  multi-year universe runs, writing the report and every trade to files.

## Out of scope

- **Any figure across strategies**, including a combined equity curve or capital allocation.
- **Survivorship.** The universe is still today's members; the bias stays on every result.
- **Exact charges.** A flat estimate, configurable, labelled as one.
- **A web surface for the replay.** The command line is the right home for an hour-long job.
