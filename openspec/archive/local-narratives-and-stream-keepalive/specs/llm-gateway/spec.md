# llm-gateway

## MODIFIED Requirements

### Requirement: Stable prompts are cached
The gateway MUST cache responses keyed by a content hash of the request, and MUST serve a
cache hit without issuing a network request. A response with no text, no tool calls and no
parsed body MUST NOT be cached.

#### Scenario: Empty answers are not cached
- GIVEN a `complete` call whose provider returned a response with empty text
- WHEN an identical call is made
- THEN a network request is issued

## ADDED Requirements

### Requirement: Local model settings reach the local server
For a rung dispatched to Ollama, the gateway MUST pass the task's configured reasoning effort
as LiteLLM's `reasoning_effort` argument, and MUST pass the configured local context window as
`num_ctx` unless it is `0`. Other providers MUST NOT receive `num_ctx`, and OpenAI-compatible
servers keep receiving reasoning effort in `extra_body`.

#### Scenario: Thinking can be turned off for an Ollama task
- GIVEN `LLM_ROUTE__NARRATIVE=ollama/gemma4:12b` and `LLM_REASONING__NARRATIVE=none`
- WHEN a narrative is requested
- THEN the call carries `reasoning_effort="none"`

#### Scenario: Ollama gets a window larger than its default
- GIVEN no context setting
- WHEN a task routed to Ollama is dispatched
- THEN the call carries a `num_ctx` greater than 4096

#### Scenario: A truncated answer is logged
- GIVEN a provider response whose finish reason is `length`
- WHEN the gateway builds the result
- THEN a warning names the model and task
