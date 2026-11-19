# web-shell

## ADDED Requirements

### Requirement: A dropped progress connection is not reported as a failed run
When a progress stream ends without a `complete` or `error` event, or fails after it opened,
the `LiveProgressCard` MUST say the connection was lost and that the run continues on the
server. An `error` event MUST display the backend's message.

#### Scenario: Connection lost mid-scan
- GIVEN a streaming scan in progress
- WHEN the stream's connection drops before a terminal event
- THEN the card reports a lost connection and that the run continues
- AND does not report the scan as failed
