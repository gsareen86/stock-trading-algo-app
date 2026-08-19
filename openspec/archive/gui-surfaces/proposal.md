# gui-surfaces

## Intent

Fill the four surfaces that are still navigation shell, and turn Today into the feed it was
always named for.

## Why

Everything the platform knows is reachable only by `curl`. Four of the six surfaces still
render the placeholder from `bootstrap-platform-skeleton` naming the change that would fill
them — and this is that change for all of them.

The gap is not cosmetic. The platform's central claim is that **every figure on screen traces
back to evidence a reader can inspect**. That claim has been true of the data and untested by a
reader, because there has been no screen. A verdict's evidence rows, a narrative's citations, an
insight's reason, a backtest's biases — all of it was built to be *looked at*.

## In scope

- **Today** — the insight feed, with actions attached to each item
- **Ideas** — every strategy's verdict on a name, side by side, never merged
- **Positions** — both books, with the health score and its guidance
- **Stock** — one name: four verdicts, their evidence, and any narrative
- **Performance** — analytics, attribution and a backtest runner
- **Evidence made visible** — a verdict's rows expandable under it, with thresholds and
  `source_ref`

## Out of scope

- **Charts.** Nothing here needs one that a table does not say better, and a chart library is a
  dependency with a rendering budget. `performance` shows figures; a curve arrives when there is
  a question a table cannot answer.
- **Editing anything but through existing endpoints.** No surface writes except via
  `POST /books/{book}/fill` and `POST /insights/{id}/act`, which already exist and already
  enforce their own rules.
- **A combined verdict view.** Ideas shows four verdicts beside each other. Any layout implying
  a merged answer — a consensus badge, an average conviction, sorting names by "how many
  strategies like this" — is the confluence scorecard as a UI affordance.
- **Real-time updates.** A daily cycle does not need a websocket.

## Risks

- **A screen is where a blended score sneaks back in**, because a combined number is a natural
  thing to render and nothing in the backend stops a template computing one. The layout keeps
  strategies in separate columns, and a test asserts no aggregation happens in the surface code.
- **A number on a trading screen is trusted.** Every figure shown carries its unit and, where
  one exists, the threshold it was tested against — the same discipline the evidence rows
  already enforce, made visible rather than assumed.
