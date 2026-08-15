# platform-api

## ADDED Requirements

### Requirement: Usage endpoint reports spend and tokens
`GET /llm/usage` MUST report spend, token counts and call counts grouped by IST day, task and
provider.

#### Scenario: Usage with recorded calls
- GIVEN `llm_calls` contains calls across two tasks
- WHEN `GET /llm/usage` is requested
- THEN the response reports totals and a per-task and per-provider breakdown

#### Scenario: Usage with no calls
- GIVEN `llm_calls` is empty
- WHEN `GET /llm/usage` is requested
- THEN the response status is 200
- AND totals are zero rather than absent

#### Scenario: Budget reported alongside spend
- GIVEN `LLM_DAILY_BUDGET_USD` is configured
- WHEN `GET /llm/usage` is requested
- THEN the response reports today's spend, the cap, and the remaining amount

#### Scenario: Window is bounded
- GIVEN a request specifying more days than the permitted maximum
- WHEN `GET /llm/usage?days=400` is requested
- THEN the response is a 422 validation error naming the limit

### Requirement: Recent calls are listable
`GET /llm/calls` MUST return recent call records, most recent first, with a bounded page size.

#### Scenario: Recent calls returned newest first
- GIVEN several recorded calls
- WHEN `GET /llm/calls` is requested
- THEN records are returned in descending time order

#### Scenario: Failures are included
- GIVEN a recorded call with status `failed`
- WHEN `GET /llm/calls` is requested
- THEN that record appears with its status and error message

### Requirement: Observability endpoints never leak prompt content or credentials
`GET /llm/usage` and `GET /llm/calls` MUST NOT return prompt text, completion text, or
credentials.

#### Scenario: No payloads in the response
- GIVEN recorded calls whose prompts contained sensitive text
- WHEN either endpoint is requested
- THEN no prompt or completion content appears in the response
