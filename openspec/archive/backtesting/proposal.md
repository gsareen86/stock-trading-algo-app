# backtesting

## Intent

Run the strategies over history and find out what they would have done — without the backtest
quietly telling itself the answer.

## Why

Four strategies each publish a verdict and nobody knows whether any of them is worth following.
That question is only askable because of a decision made in `verdict-model-and-minervini`:
**verdicts are deterministic and reproducible with the LLM off.** A strategy whose output
depended on a model's mood could not be replayed at all.

The value is not a performance number. It is the three questions a live platform cannot answer:
does a strategy fire often enough to matter, does its conviction mean anything, and does a
failed gate actually precede a bad outcome.

## The bias problem, stated up front

A backtest is easy to write and easy to make lie. Three ways, and this change's position on
each:

| Bias | Where it comes from | What this does |
|---|---|---|
| **Lookahead** | strategy sees bars after the decision date | prevented structurally — see `design.md` §1 |
| **Fill timing** | buying at the close you decided on | fills at the *next* session's open |
| **Survivorship** | today's index members were not yesterday's | **cannot** be removed; reported on every result |

The first two are fixable and are fixed. The third is not, with the data this platform has, and
a backtest that stayed silent about it would be the most misleading thing in the repository.

## In scope

- **`app/backtest/`** — a point-in-time price source, a runner, per-strategy results
- **Lookahead prevention as a wrapper**, so strategies are unmodified and cannot opt out
- **The real `Ledger`**, against an in-memory database — not a parallel position simulator
- **Per-strategy results**, never a combined equity curve
- **A declared bias report** attached to every run
- **`POST /backtest/run`**

## Out of scope

- **Legacy data.** Standing decision, recorded in `project.md`: the predecessor's ~20,000
  signals and 325 outcomes are never read. They were produced by the scoring system this
  rebuild removes, so measuring the new engine against them would be measuring it against the
  old one's judgement.
- **Parameter optimisation.** Searching thresholds against one price history produces the
  parameters that fit that history. It needs walk-forward validation to mean anything, and
  that is a change with its own spec.
- **Charges and slippage.** Consistent with the ledger: P&L is gross and says so. Modelling
  slippage badly is worse than a number labelled as excluding it.
- **A combined equity curve across strategies.** Four strategies with independent verdicts do
  not have one portfolio unless you decide how to allocate between them — which is the
  confluence scorecard with a chart.

## Risks

- **A backtest is the most persuasive artefact this platform can produce**, and the easiest to
  produce wrongly. Mitigated by making lookahead structurally impossible rather than avoided by
  care, and by attaching what the run *cannot* account for to the run itself.
- **Slow.** Replaying a year over a hundred names is tens of thousands of strategy evaluations.
  Bounded by explicit limits rather than left to discover its own runtime.
