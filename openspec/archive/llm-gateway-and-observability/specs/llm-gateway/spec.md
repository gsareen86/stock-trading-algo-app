# llm-gateway

## MODIFIED Requirements

### Requirement: Callers name a task, not a model
The gateway MUST accept a task name and resolve an ordered chain of provider/model targets
from configuration, dispatching to the first available rung.

#### Scenario: Task resolves to its configured model
- GIVEN `LLM_ROUTE__NARRATIVE=ollama/llama3.1`
- WHEN a caller invokes `complete(task="narrative", ...)`
- THEN the request is dispatched to `ollama/llama3.1`

#### Scenario: Unrouted task falls back to the default model
- GIVEN no `LLM_ROUTE__RESEARCH` is configured
- AND `LLM_DEFAULT_TASK_MODEL=anthropic/claude-sonnet-5`
- WHEN a caller invokes `complete(task="research", ...)`
- THEN the request is dispatched to `anthropic/claude-sonnet-5`

#### Scenario: Task with no fallback behaves as before
- GIVEN `LLM_ROUTE__NARRATIVE` is set and no `LLM_FALLBACK__NARRATIVE` is configured
- WHEN the primary provider fails
- THEN `complete` returns `None`

### Requirement: Circuit breaker short-circuits a failing provider
After a configured number of consecutive rate-limit failures the gateway MUST stop issuing
requests to that provider for a cooldown period.

#### Scenario: Breaker opens after repeated rate limits
- GIVEN the breaker threshold is 3
- AND the provider has returned rate-limit errors on 3 consecutive calls
- AND the task has no fallback configured
- WHEN `complete` is invoked again
- THEN it returns `None` without issuing a network request

#### Scenario: Breaker closes after cooldown
- GIVEN the breaker is open
- AND the cooldown period has elapsed
- WHEN `complete` is invoked
- THEN a network request is issued

#### Scenario: Non-rate-limit failures do not trip the breaker
- GIVEN a provider failing with a non-rate-limit error repeatedly
- WHEN `complete` is invoked more times than the breaker threshold
- THEN every call still issues a network request

## ADDED Requirements

### Requirement: The result names the model that answered
`LLMResult` MUST report the model that actually served the request, and MUST separately
report the model that was requested.

#### Scenario: No fallback occurred
- GIVEN a task whose primary provider succeeds
- WHEN `complete` returns
- THEN `LLMResult.model` and `LLMResult.requested_model` are equal
- AND `LLMResult.used_fallback` is false

#### Scenario: A fallback served the request
- GIVEN a task whose primary provider fails and whose fallback succeeds
- WHEN `complete` returns
- THEN `LLMResult.model` names the fallback model
- AND `LLMResult.requested_model` names the primary
- AND `LLMResult.used_fallback` is true

### Requirement: Tasks may declare an ordered fallback chain
The gateway MUST support a per-task fallback chain, and MUST try each rung in the configured
order until one succeeds.

#### Scenario: Primary fails, fallback answers
- GIVEN `LLM_ROUTE__NARRATIVE=ollama/llama3.1`
- AND `LLM_FALLBACK__NARRATIVE=anthropic/claude-sonnet-5`
- AND the Ollama request fails
- WHEN `complete(task="narrative", ...)` is invoked
- THEN the Anthropic model is tried
- AND its result is returned

#### Scenario: Chain order is preserved
- GIVEN `LLM_FALLBACK__NARRATIVE=openai/gpt-4o,anthropic/claude-sonnet-5`
- WHEN the primary and first fallback both fail
- THEN the Anthropic model is tried last

#### Scenario: Whole chain fails
- GIVEN every rung in a task's chain fails
- WHEN `complete` is invoked
- THEN it returns `None`
- AND no exception escapes the gateway

### Requirement: An open circuit breaker prunes the chain rather than failing the call
The gateway MUST skip rungs whose provider has an open circuit breaker, and MUST still attempt
the remaining rungs.

#### Scenario: Primary provider is breaker-open
- GIVEN the breaker is open for the primary rung's provider
- AND the task has a fallback whose provider is healthy
- WHEN `complete` is invoked
- THEN no request is issued to the primary provider
- AND the fallback serves the request

#### Scenario: Every provider in the chain is breaker-open
- GIVEN the breaker is open for every provider in the task's chain
- WHEN `complete` is invoked
- THEN it returns `None` without issuing any network request

### Requirement: A daily spend cap stops paid calls
The gateway MUST refuse calls to paid providers once recorded spend for the current IST day
reaches the configured cap.

#### Scenario: Cap reached
- GIVEN `LLM_DAILY_BUDGET_USD=1.00`
- AND recorded spend for today is at least 1.00
- WHEN a task routed to a paid provider invokes `complete`
- THEN it returns `None` without issuing a network request
- AND the attempt is recorded with status `budget_exceeded`

#### Scenario: Local providers are exempt
- GIVEN the daily cap has been reached
- WHEN a task routed to a local provider invokes `complete`
- THEN the request is issued normally

#### Scenario: Cap unset means unlimited
- GIVEN `LLM_DAILY_BUDGET_USD` is not configured
- WHEN any task invokes `complete`
- THEN no budget check blocks the call

#### Scenario: Paid rungs are skipped but local rungs still run
- GIVEN the daily cap has been reached
- AND a task's chain is a paid primary followed by a local fallback
- WHEN `complete` is invoked
- THEN the paid rung is skipped
- AND the local fallback serves the request
