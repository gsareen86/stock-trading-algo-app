# portfolio-health-and-actions

## Intent

Score the portfolio's **structure**, say what to do about it, and let an insight be acted on
without retyping what it already knows.

## Why

Two gaps, and they are the same loop half-built.

`books-ledger-and-analytics` reports numbers — cost basis, concentration, realised P&L — and
leaves the reader to decide whether they add up to a problem. Nothing says "this book is
over-concentrated and under-deployed"; you have to know the thresholds yourself and apply them
by eye, every time.

`insights-feed` names problems and stops. A `thesis_broken` insight says a holding's own
strategy now rates it AVOID, and then the reader retypes the ticker, quantity and price into a
fill by hand — which is where mistakes happen, and where the platform stops being useful.

## A note on the word "score"

`insights-feed` deliberately refused a score, and this change adds one. The distinction is the
whole design, so it is stated up front rather than buried:

- **Refused, still refused:** blending strategy verdicts into a number. Conviction is scoped
  to one strategy and comparing across them is the confluence scorecard.
- **Added here:** scoring the *book's own structure* — how concentrated it is, how much capital
  is working, how many positions are open, how much is in names whose thesis has broken. These
  are measurements of the portfolio, not opinions about stocks.

A health score therefore never ranks instruments, never reads a conviction, and never appears
in a verdict. If it ever needs a `Verdict` to compute, it has become the wrong thing.

## In scope

- **`app/health/`** — component scores over portfolio structure, each with its own measurement,
  threshold and contribution, and a headline score derived from them
- **Guidance** — concrete next steps tied to the component that produced them, ordered by the
  component's weight, never by a per-step score
- **Insight actions** — an insight declares what could be done about it (`trim`, `exit`,
  `review`, `buy`), pre-filled from what it already knows
- **`POST /insights/{id}/act`** — executes a declared action through `Ledger.fill()`, the same
  one boundary
- **`GET /books/{book}/health`**

## Out of scope

- **Acting automatically.** An action is proposed and executed on request. Nothing in a cycle
  fills, and `surface_insights` staying read-only is what makes an unattended daily run safe.
- **Ranking instruments by health.** The score is a property of the book. A per-instrument
  health number that could be sorted is the scorecard, and it is refused here by name.
- **Rebalancing to a target allocation.** That needs a target, which needs a view on relative
  attractiveness across names — which is the blend. Guidance says "this is 65% of the book";
  it does not say what to buy with the proceeds.
- **Undoing an action.** A fill is a record. Correcting one is another fill, deliberately.

## Risks

- **A score invites optimising the score.** Mitigated by publishing every component with its
  own number and threshold, so the headline is never the only thing visible — and by refusing
  to rank names, which is what optimising it would otherwise mean.
- **One-click acting is one click from a mistake.** Every action states exactly what it will do
  before it does it, re-derives quantity from the ledger at execution rather than trusting a
  number the insight carried, and is refused if the position has changed underneath it.
