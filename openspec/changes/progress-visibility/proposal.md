# progress-visibility

## Intent

Show what the platform is doing while it does it, using the steps it actually runs.

## Why

Nothing in the web app indicates that work is happening. Every surface is a server component
with `dynamic = "force-dynamic"` that performs its fetch inline, there is **no `loading.tsx`
anywhere in the application**, and no Suspense boundary. Next.js therefore holds the previous
page fully rendered until the new payload arrives and then swaps it. Nothing is mounted that
could indicate progress, so nothing does.

Today that reads as a one-to-two second pause with no feedback. It gets worse, not better:
`discovery-funnel` introduces a scan over the whole universe, and `research-data-sources`
introduces providers that are slower and rate-limited. A person who cannot tell the difference
between "working" and "broken" will refresh, which starts a second run.

The cycle already has real steps to report. `screen → regime → research → four strategies →
risk → narrate → insights` are LangGraph nodes with genuine boundaries. That is a progress
signal the platform already produces and throws away.

## In scope

- **`loading.tsx` per route** — an immediate skeleton on every navigation, matching the shape
  of what is arriving.
- **Pending state on every control that submits** — the two search forms and the run control.
- **Streamed cycle progress** — `POST /cycles/run` gains a streaming counterpart that emits one
  event per graph node as it completes, and Today renders those steps as they arrive.
- **Elapsed time**, shown for anything that has been running long enough to wonder about.
- **A percentage-complete bar**, computed over **counted work units with a declared
  denominator** — instruments left to screen, instruments left to evaluate, verdicts left to
  narrate. Not over graph nodes, and not over elapsed time. See below.

## Percentage, honestly

A bar over the graph's *nodes* would be a lie with arithmetic on it: `regime` reads one series
in milliseconds and `narrate` runs a local 12B model over every verdict for minutes, so
"6 of 10 nodes" would sit at 60% for most of the wall clock and then finish in a rush.

What the cycle genuinely knows is **how many things it has left to do**:

| Phase | Denominator | Known from |
|---|---|---|
| screen | instruments in the universe | universe snapshot, at the start |
| strategies | eligible instruments × strategies | after `screen` completes |
| narrate | verdicts selected for narration | after the strategy fan-in |
| regime, research, risk, insights | one unit each | fixed |

So the denominator is **established progressively**, and the bar says so: until `screen`
finishes, the total is not yet known and the bar is indeterminate rather than guessed at. From
that point on the percentage is a true fraction of counted work, and it is accurate exactly
where it matters — the long phases.

This is a different claim from "58% of the time remains", and the surface must not make the
second claim. Percent-of-work is checkable; percent-of-time is a forecast the platform has no
basis for.

## Out of scope

- **Estimated time remaining.** Per-unit durations vary by two orders of magnitude between a
  cached price read and a local narration call, and the platform has no model of either. A
  countdown would be invented, and this codebase rejects invented numbers everywhere else.

- **Cancelling a run.** Worth having, needs a job record and a cancellation path through
  LangGraph, and is not what this change is about.
- **Background jobs.** The run still happens within the request. Scheduling arrives with
  `discovery-funnel`.
- **Per-strategy sub-steps.** Node granularity is what the graph actually exposes; anything
  finer would be narration of an implementation detail.

## Risks

- **A stream that dies mid-run looks like a hang.** The client treats a closed stream without a
  terminal event as a failure and says so, rather than displaying the last step forever.
- **Streaming through the Next proxy adds a hop that can buffer.** The proxy route today does
  `await response.text()` before constructing its own response, so it buffers every body to
  completion — SSE through it is impossible without changing it. A scenario covers this,
  because a buffered stream produces exactly the behaviour this change exists to remove.
- **A percentage invites being read as time remaining**, whatever the denominator. Mitigated by
  labelling the bar with its own counts ("214 of 380 evaluated") rather than the percentage
  alone, so the unit being counted is always visible next to the figure.
- **The denominator is unknown at the start of a run**, and a bar that begins at an invented
  zero-of-something is the failure mode this design exists to avoid. Indeterminate until
  `screen` reports, then counted.
