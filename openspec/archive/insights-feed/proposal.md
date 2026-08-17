# insights-feed

## Intent

Turn a cycle's output into a small number of things actually worth a person's attention — and
keep the feed small enough that it stays worth reading.

## Why

Every part of the cycle now produces something, and none of it reaches anybody. Verdicts sit in
a table, risk decisions vanish with the response, research findings are discarded at the end of
the run. The platform can answer questions when asked and cannot tell you anything.

This is the increment the original scope named directly: *regular portfolio analysis and
rebalance/enhance insights based on relevant news and market events, researched and highlighted
automatically, so necessary actions can be taken when needed.* Everything needed for it now
exists — positions (`books-ledger-and-analytics`), risk decisions, the research tools, and the
regime read — and nothing joins them up.

The `insights` table has existed since `0001` with no writer. That is the gap.

## In scope

- **`app/insights/`** — generators over cycle state and portfolio state
- **Portfolio insights**, which are the ones with consequences:
  - a held name whose own strategy now says AVOID — the thesis that bought it has broken
  - concentration above the configured cap
  - an earnings or corporate event due on a held name
  - news or a filing on a held name
- **Opportunity insights** — a verdict risk assessed as actionable
- **Book-level insights** — regime change, book at its position limit
- **Deduplication with a suppression window**, so a daily cycle does not repeat yesterday's
  insight every morning until it is meaningless
- **`insights` node**, the last one missing from the cycle
- **`GET /insights`**, **`POST /insights/{id}/read`**, **`GET /insights/unread-count`**

## Out of scope

- **Email, push and messaging.** `project.md` has said since `0001` that insights are in-app
  only and that no channel should be added without a change specifying it. This is not that
  change. A feed nobody has read yet is a feature; an email nobody asked for is a habit that
  is hard to remove.
- **A combined "portfolio health score".** The obvious next thing to build and the exact thing
  this rebuild removed. Insights are individually traceable observations, not inputs to a
  number.
- **Acting on an insight.** An insight links to what would act — a verdict, a position — and
  never fills. `fill()` remains the one execution boundary, reached deliberately.
- **Ranking insights by importance.** Severity is a property of the *kind*, declared up front,
  not a score computed per item and compared across kinds.

## Risks

- **A noisy feed is an ignored feed**, and an ignored feed is worse than none because it looks
  like coverage. Mitigated by deduplication, a suppression window and a hard cap per cycle.
- **Insights are generated from research the model gathered**, which is not evidence. Anything
  quoting a tool result says where it came from and never presents it as a measurement the
  platform made.
