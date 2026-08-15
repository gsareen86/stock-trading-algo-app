# llm-observability

The platform's own LLM ledger: what every call cost, how it failed, and whether the daily budget is spent — answerable with no external observability service.

Introduced by `llm-gateway-and-observability` (see `openspec/archive/`).

### Requirement: Every call attempt is recorded locally
The system MUST write one `llm_calls` row per call attempt, regardless of outcome, without
requiring any external observability service.

#### Scenario: Successful call recorded
- GIVEN a task that completes successfully
- WHEN `complete` returns
- THEN one row exists recording task, provider, model, token counts, latency and status `ok`

#### Scenario: Failed call recorded
- GIVEN a provider that errors
- WHEN `complete` returns `None`
- THEN one row exists with status `failed`

#### Scenario: Cache hit recorded
- GIVEN a call served from the content-hash cache
- WHEN `complete` returns
- THEN one row exists with status `cached`
- AND its latency reflects the cache lookup, not the original call

#### Scenario: Recording works with no Langfuse configured
- GIVEN no Langfuse credentials are present
- WHEN a call completes
- THEN the row is still written

### Requirement: Failure modes are distinguishable
Recorded status MUST distinguish `ok`, `cached`, `failed`, `rate_limited`, `breaker_open`
and `budget_exceeded`.

#### Scenario: Rate limit distinguished from generic failure
- GIVEN a provider returning a rate-limit error
- WHEN `complete` is invoked
- THEN the recorded status is `rate_limited`, not `failed`

#### Scenario: Breaker short-circuit distinguished
- GIVEN the breaker is open for every rung in a task's chain
- WHEN `complete` is invoked
- THEN the recorded status is `breaker_open`

### Requirement: Logging can never break a call
A failure to write the call log MUST NOT change what `complete` returns or raise to the
caller.

#### Scenario: Log write fails
- GIVEN the database rejects the `llm_calls` insert
- WHEN a successful call completes
- THEN `complete` still returns its result
- AND the logging failure is warned about, not raised

### Requirement: Unpriced calls are recorded as unknown cost, not zero
Cost MUST be recorded as null when the provider reports none, and aggregates MUST report
priced and unpriced call counts separately.

#### Scenario: Local model call
- GIVEN a call served by a local provider that reports no cost
- WHEN the row is written
- THEN its cost is null, not `0.0`

#### Scenario: Aggregate distinguishes unpriced calls
- GIVEN a day containing both paid and local calls
- WHEN usage is aggregated
- THEN the reported spend covers only priced calls
- AND the count of unpriced calls is reported alongside it

### Requirement: A fallback is visible in the record
When a fallback served a request, the recorded row MUST show both the requested and serving
model.

#### Scenario: Fallback recorded
- GIVEN a task whose primary failed and whose fallback succeeded
- WHEN the rows are written
- THEN a row exists for the failed primary attempt
- AND a row exists for the successful fallback marked as a fallback

### Requirement: Spend is aggregated per IST day
Daily aggregation MUST use the Asia/Kolkata day boundary, matching the market day the
platform reasons about.

#### Scenario: Call just after IST midnight
- GIVEN a call recorded at 18:45 UTC, which is 00:15 IST the following day
- WHEN usage is grouped by day
- THEN it is attributed to the later IST day
