# discovery

## ADDED Requirements

### Requirement: A progress stream stays connected through silent work
An SSE endpoint MUST send a keep-alive comment when nothing has been sent for 15 seconds, and
a scan's narration step MUST report progress after each verdict.

#### Scenario: Minutes-long narration keeps the stream alive
- GIVEN a streaming scan narrating with a local model that takes minutes per verdict
- WHEN no progress event is due for more than 15 seconds
- THEN a `: keepalive` comment is sent

#### Scenario: Narration is counted per verdict
- GIVEN a scan narrating N verdicts
- WHEN each verdict's narration finishes
- THEN a `narrate` progress event reports it as done out of N
