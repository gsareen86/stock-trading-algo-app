# Design: gui-surfaces

## 1. Four verdicts, four columns, no fifth number

Ideas and Stock both render the same thing: one row per instrument, four verdicts across it.

The temptation at this layer is obvious and would be easy to defend — a "3 of 4 strategies say
BUY" badge, an average conviction, sorting the list by agreement. Every one of those is the
confluence scorecard, arriving as a UI affordance after being kept out of the domain for
fourteen increments.

So: strategies occupy fixed columns in a stable order, agreement is something a reader *sees*
by looking across a row, and no cell is computed from more than one verdict. A test greps the
surface components for aggregation over verdict arrays, because this is the layer where it
would look most reasonable.

Conviction is rendered inside its own strategy's column and never compared across them — it is
scoped to one strategy by definition, and putting two on the same axis would imply otherwise.

## 2. Evidence is one interaction away, not a separate page

A verdict's rows sit in a `<details>` under it: metric, observed value with its unit, the
operator and threshold it was tested against, and the `source_ref`.

Collapsed by default because fourteen rows per verdict times four strategies is not a screen
anyone reads. One click away rather than one navigation away, because "click through to see why"
is a step people skip, and the entire traceability argument depends on the why being cheap to
reach.

## 3. Server components, no client state

Every surface fetches on the server through the proxy and renders. No client-side store, no
loading spinners, no optimistic updates.

The data changes when a cycle runs — daily. Building live-updating views over daily data is
machinery that has to be maintained without ever being needed. Actions that write (`fill`,
`act`) are small client islands that post and refresh, which is the whole of the interactivity
budget.

## 4. Failure is rendered, never blank

Every fetch returns `Fetched<T>` — the existing discriminated union — and each surface renders
the failure case explicitly: not signed in, backend unreachable, or empty.

An empty book and an unreachable backend look identical on a naive screen, and confusing them
on a trading platform is how someone concludes they hold nothing. So they read differently by
construction.

## 5. Nothing is faked, including in the empty state

The placeholder component this change removes says it plainly: *plausible-looking fake numbers
on a trading screen are worse than an empty one*. That holds for empty states too — a book with
no positions says so, rather than rendering a zeroed row that looks like a real one.
