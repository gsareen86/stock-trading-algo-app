# llm-gateway

## ADDED Requirements

### Requirement: All LLM access goes through the gateway interface
Application code MUST invoke language models only through the `LLMGateway` protocol, and
MUST NOT import the underlying routing library directly.

#### Scenario: Feature code depends only on the protocol
- GIVEN any module outside `app/llm/`
- WHEN its imports are inspected
- THEN it imports no `litellm` symbol
- AND any LLM call it makes goes through `LLMGateway.complete`

### Requirement: Callers name a task, not a model
The gateway MUST accept a task name and resolve the provider and model from configuration.

#### Scenario: Task resolves to its configured model
- GIVEN `LLM_ROUTE__NARRATIVE=ollama/llama3.1`
- WHEN a caller invokes `complete(task="narrative", ...)`
- THEN the request is dispatched to `ollama/llama3.1`

#### Scenario: Unrouted task falls back to the default model
- GIVEN no `LLM_ROUTE__RESEARCH` is configured
- AND `LLM_DEFAULT_TASK_MODEL=anthropic/claude-sonnet-5`
- WHEN a caller invokes `complete(task="research", ...)`
- THEN the request is dispatched to `anthropic/claude-sonnet-5`

### Requirement: A failed LLM call never raises
The gateway MUST return `None` on any failure — provider error, timeout, rate limit, or
missing credentials — and MUST NOT propagate an exception to the caller.

#### Scenario: Provider returns an error
- GIVEN the configured provider responds with a server error
- WHEN `complete` is invoked
- THEN it returns `None`
- AND no exception escapes the gateway

#### Scenario: Provider is unconfigured
- GIVEN the task routes to a provider whose credentials are absent
- WHEN `complete` is invoked
- THEN it returns `None`
- AND the reason is logged once at warning level

#### Scenario: Request exceeds the timeout
- GIVEN `LLM_TIMEOUT_SECONDS` is 5
- AND the provider has not responded after 5 seconds
- WHEN `complete` is invoked
- THEN it returns `None`

### Requirement: Circuit breaker short-circuits a failing provider
After a configured number of consecutive rate-limit failures the gateway MUST stop issuing
requests for that provider for a cooldown period and return `None` immediately.

#### Scenario: Breaker opens after repeated rate limits
- GIVEN the breaker threshold is 3
- AND the provider has returned rate-limit errors on 3 consecutive calls
- WHEN `complete` is invoked again
- THEN it returns `None` without issuing a network request

#### Scenario: Breaker closes after cooldown
- GIVEN the breaker is open
- AND the cooldown period has elapsed
- WHEN `complete` is invoked
- THEN a network request is issued

### Requirement: Stable prompts are cached
The gateway MUST cache responses keyed by a content hash of the request, and MUST serve a
cache hit without issuing a network request.

#### Scenario: Identical request served from cache
- GIVEN a successful `complete` call for a given task and messages
- WHEN an identical call is made
- THEN the cached result is returned
- AND no network request is issued

#### Scenario: Failures are not cached
- GIVEN a `complete` call that returned `None` because the provider errored
- WHEN an identical call is made after the provider recovers
- THEN a network request is issued

### Requirement: Seven providers are supported without adapter code
The gateway MUST support Anthropic, Google Gemini, OpenAI, Ollama, LM Studio, llama.cpp and
AMD Lemonade, routing the OpenAI-compatible local servers by base URL.

#### Scenario: Local OpenAI-compatible server is routed by base URL
- GIVEN `LLM_ROUTE__NARRATIVE=openai/qwen3-8b`
- AND `LLM_PROVIDER_BASE_URL__OPENAI=http://localhost:8000/v1`
- WHEN `complete(task="narrative", ...)` is invoked
- THEN the request is issued against `http://localhost:8000/v1`
- AND no provider-specific adapter code is involved

### Requirement: Every call is traced when observability is configured
The gateway MUST emit a trace for each call when Langfuse credentials are present, and MUST
return the trace identifier on the result.

#### Scenario: Traced call returns its trace id
- GIVEN Langfuse credentials are configured
- WHEN `complete` succeeds
- THEN a trace is emitted recording provider, model, token counts and cost
- AND `LLMResult.trace_id` is populated

#### Scenario: Observability unconfigured degrades to off
- GIVEN no Langfuse credentials are configured
- WHEN `complete` is invoked
- THEN the call succeeds normally
- AND `LLMResult.trace_id` is `None`
- AND no error is raised
