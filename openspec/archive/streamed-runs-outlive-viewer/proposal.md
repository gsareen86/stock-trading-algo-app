# streamed-runs-outlive-viewer

## Intent

A scan, cycle or theme run started from a streaming endpoint finishes and records its result
whether or not anyone is still watching it.

## Why

On 19-Nov a Nifty 750 scan ran for 26 minutes and was in its final step, narrating the
ranked head, when the browser pane showing it closed. The SSE helper cancelled the run on
disconnect, so every computed verdict was discarded. And because `asyncio.CancelledError`
is not an `Exception`, the scanner's failure handler never ran: the row stayed `running`,
and every later scan was refused as "already in progress" until a server restart.

A full scan takes longer than anyone will keep one tab in front of them. Tying the run to
the tab makes the long-running work the least likely to ever complete.

## In scope

- The SSE helper stops cancelling its run when the viewer disconnects, and keeps the run
  referenced until it finishes.
- A run that fails after its viewer left logs the failure, since no error event can reach anyone.
- A discovery scan that is cancelled anyway (server shutdown) records `interrupted` instead
  of staying `running`.

## Out of scope

- Re-attaching a new viewer to a run already in progress. A second scan request is still
  refused while one runs; the result is read from `GET /discovery/runs/latest` once it lands.
- Narration truncation at the local model's context limit — a separate problem.
