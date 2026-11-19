# discovery

## ADDED Requirements

### Requirement: A streamed run outlives its viewer
A run started through an SSE endpoint (`POST /discovery/scan/stream`, `POST /cycles/run/stream`,
`POST /themes/run/stream`) MUST continue to completion and persist its result when the stream's
client disconnects. A discovery scan that is cancelled for any other reason MUST NOT be left
recorded as `running`.

#### Scenario: Closing the page does not cancel the scan
- GIVEN a streaming discovery scan in progress
- WHEN the client disconnects before the terminal event
- THEN the scan continues and records its outcome and entries as if it had been watched

#### Scenario: A cancelled scan is recorded as interrupted
- GIVEN a discovery scan whose task is cancelled, as on server shutdown
- WHEN the cancellation reaches the scanner
- THEN its run row is marked `interrupted` with a `finished_at`
- AND a later scan is not refused on its account
