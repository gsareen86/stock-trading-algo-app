# platform-api

## MODIFIED Requirements

### Requirement: Usage endpoint reports spend and tokens
`GET /llm/usage` MUST report spend, token counts and call counts grouped by IST day, task and
provider. Spend MUST be reported in INR, and the response MUST state the conversion rate used
so any reported figure can be traced back to the stored amount.

#### Scenario: Usage with recorded calls
- GIVEN `llm_calls` contains calls across two tasks
- WHEN `GET /llm/usage` is requested
- THEN the response reports totals and a per-task and per-provider breakdown

#### Scenario: Spend is reported in rupees with its rate
- GIVEN recorded paid calls
- WHEN `GET /llm/usage` is requested
- THEN reported spend is in INR
- AND the response states the USD→INR rate applied

#### Scenario: Usage with no calls
- GIVEN `llm_calls` is empty
- WHEN `GET /llm/usage` is requested
- THEN the response status is 200
- AND totals are zero rather than absent

#### Scenario: Budget reported alongside spend
- GIVEN `LLM_DAILY_BUDGET_INR` is configured
- WHEN `GET /llm/usage` is requested
- THEN the response reports today's spend, the cap, and the remaining amount, all in INR

#### Scenario: Window is bounded
- GIVEN a request specifying more days than the permitted maximum
- WHEN `GET /llm/usage?days=400` is requested
- THEN the response is a 422 validation error naming the limit

## ADDED Requirements

### Requirement: Call records carry both stored and reported cost
`GET /llm/calls` MUST report each call's cost in INR for display, and MUST also return the
stored provider-currency amount, so the reported figure is auditable rather than opaque.

#### Scenario: Paid call carries both amounts
- GIVEN a recorded call with a provider-reported cost
- WHEN `GET /llm/calls` is requested
- THEN the record reports both the stored amount and its INR equivalent

#### Scenario: Unpriced call reports no cost in either currency
- GIVEN a recorded call from a local provider, which has no cost
- WHEN `GET /llm/calls` is requested
- THEN both cost fields are null
- AND neither is reported as zero
