# Design: backtesting

## 1. Lookahead is prevented by the seam, not by discipline

The usual way a backtest lies is that a strategy evaluated for 3 March reads a moving average
computed over bars up to today. Nothing in the strategy looks wrong; the data was simply too
generous.

`AsOfPriceSource` wraps any `PriceSource` and truncates every series to bars at or before its
`as_of` date. It implements the same protocol, so **strategies are unmodified and cannot opt
out** — a strategy asks for history and receives history that stops where the clock is.

That placement is the whole design. Any alternative — a date parameter threaded through
`evaluate`, a convention that strategies slice their own frames — depends on four strategies
and every future one getting it right forever. Here there is one wrapper, and a strategy that
wanted to cheat would have to reach around its own injected source.

It is asserted directly rather than assumed: a test evaluates against a source seeded with
future bars and checks the strategy's evidence contains none of them.

## 2. The clock steps through trading days, not calendar days

The market calendar already exists (`market-calendar`), so the runner steps through actual NSE
sessions. A backtest that evaluates on Sundays produces verdicts nobody could have acted on and
inflates the count of opportunities.

## 3. Fills happen at the next session's open

A verdict formed from data up to Tuesday's close could not have been acted on at Tuesday's
close — the decision did not exist until the bar did. So a `BUY` on Tuesday fills at
Wednesday's open, and an exit works the same way.

This is the second-largest source of overstated backtest returns after lookahead, and it costs
one bar's slippage in the honest direction.

## 4. The real ledger, against an in-memory database

Positions come from `Ledger` — the same class the live platform uses — pointed at an in-memory
SQLite. Not a `BacktestPortfolio` with its own averaging logic.

The predecessor had three position ledgers that disagreed. A fourth that only runs in
backtests would be the worst of them, because it would be the one deciding whether a strategy
looks good. Sharing the class means `derive_position`'s average-cost fold, the oversell guard
and the long-only clamp are literally the same code in a backtest as in the book.

## 5. Results are per strategy, and there is no combined curve

Each strategy gets its own result: trades taken, win rate, gross P&L, average holding period,
and how often a gate blocked an entry.

There is deliberately no aggregate across strategies. Four independent verdicts do not compose
into one portfolio unless something decides how to allocate between them, and that decision is
the confluence scorecard with a chart attached. Comparing strategies is something a reader does
by looking at two results side by side — it is not a number this platform computes.

## 6. Every run carries what it could not account for

The result includes a `biases` block naming, in plain terms:

- survivorship — the universe is today's members, and names that were delisted or removed are
  absent, which flatters every strategy;
- no charges — gross of brokerage, STT, stamp duty and GST;
- no slippage — fills at the open, in whatever size, with no market impact;
- a single history — one path through one market regime is not a distribution.

Attached to the result rather than written in documentation, because the number and the
caveat get copied into a conversation together or the caveat does not travel at all.
