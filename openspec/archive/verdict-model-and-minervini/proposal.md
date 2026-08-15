# verdict-model-and-minervini

## Intent

Turn the platform's central design decision into enforced code: one strategy, producing one
independent verdict, where every claim traces to evidence and a failed hard gate cannot be
outweighed by a strong score.

## Why

Everything so far has been seams. This is the first change that makes a trading judgement, and
it is where the rebuild's reason for existing has to become structural rather than aspirational.

The predecessor ran four strategies and collapsed them into one confluence scorecard. Two
things went wrong there, and both are prevented here by the *shape of the types*, not by
discipline:

- **A strong score could outvote a failed gate.** Here a failed hard gate forces `AVOID` inside
  the `Verdict` constructor. There is no code path that produces a `BUY` with a failing gate,
  so no future strategy can reintroduce one by accident.
- **Nobody could say why.** Here every threshold comparison a strategy makes emits an
  `Evidence` row carrying the observed value, the threshold, the operator and a `source_ref`.
  A verdict with no evidence is not constructible.

Minervini goes first because it is the strategy core, and because the Trend Template is eight
explicit threshold tests — which makes it the best possible exercise of an evidence model. If
the model cannot express the Trend Template cleanly, it is the wrong model.

## In scope

- `app/domain/verdict.py` — `Stance`, `Evidence`, `GateResult`, `Verdict`, with invariants
  enforced at construction
- `app/strategies/` — `Strategy` protocol and a registry discovered by convention, mirroring
  the skills registry
- `app/strategies/indicators.py` — moving averages, 52-week range position, relative strength
  against a benchmark, contraction detection
- `app/strategies/minervini/` — Trend Template (all eight criteria) plus VCP contraction
  analysis, emitting evidence per criterion and deriving conviction deterministically
- Persistence over the existing `trading.verdicts` table — no migration needed
- `GET /strategies`, `POST /verdicts/evaluate`, `GET /verdicts`

## Out of scope

- **The other three strategies** — `remaining-three-strategies`. The point of this change is
  the model; three more implementations before the model has been exercised once would mean
  rewriting all of them when it shifts.
- **Narratives.** `Verdict.narrative` stays null here. `verdict-narratives` fills it, and this
  change is what proves a verdict is complete and reproducible without one.
- **Screening a universe.** This evaluates named instruments. Running the funnel over 500
  names is `screening-universe-and-gates`.
- **Position sizing and routing** — the books increment.

## A substitution worth flagging

Minervini's eighth criterion is an **IBD-style RS Rating ≥ 70** — a cross-sectional percentile
against every other stock. That requires the whole universe ranked at once, which
`screening-universe-and-gates` will have and this change does not.

Rather than fake a percentile from one stock, the criterion is implemented as **relative
strength against a benchmark index** over the same lookback, named `rs_vs_benchmark_pct` so
nothing reads it as an RS Rating. When the universe funnel lands, a true percentile replaces
it and the criterion's evidence id stays the same.

Naming it honestly matters more than matching the book: a field called `rs_rating` holding
something that is not one would be believed by every reader afterwards.

## Risks

- **A strategy is where wrong answers are expensive.** Every threshold is asserted against a
  hand-built price series with a known shape, not against generated data that happens to pass.
- **Conviction is tempting to make comparable.** It is scoped to one strategy and documented as
  incomparable; a later change that ranks across strategies on conviction would silently
  rebuild the confluence scorecard.
