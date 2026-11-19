# platform-configuration

## ADDED Requirements

### Requirement: The local context window is configured
The platform MUST expose `LLM_LOCAL_CONTEXT_TOKENS`, the context window requested from Ollama,
defaulting above Ollama's own 4096, with `0` meaning Ollama's default.

#### Scenario: Default exceeds Ollama's
- GIVEN no context setting
- WHEN settings are loaded
- THEN the local context window is greater than 4096

#### Scenario: Negative window rejected
- GIVEN `LLM_LOCAL_CONTEXT_TOKENS=-1`
- WHEN settings are loaded
- THEN loading fails with a validation error
