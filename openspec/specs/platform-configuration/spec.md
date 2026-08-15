# platform-configuration

How every setting is resolved, validated and injected. One precedence chain, no runtime-mutable config.

Introduced by `bootstrap-platform-skeleton` (see `openspec/archive/`).

### Requirement: Single configuration precedence chain
The system MUST resolve every setting through exactly one precedence chain: explicit
constructor arguments, then process environment variables, then the `.env` file, then the
field default declared in code.

#### Scenario: Environment overrides .env
- GIVEN `.env` contains `LLM_DEFAULT_TASK_MODEL=anthropic/claude-sonnet-5`
- AND the process environment sets `LLM_DEFAULT_TASK_MODEL=openai/gpt-4o`
- WHEN `Settings` is constructed
- THEN `settings.llm_default_task_model` is `openai/gpt-4o`

#### Scenario: Constructor argument overrides environment
- GIVEN the process environment sets `APP_ENV=prod`
- WHEN `Settings(app_env="test")` is constructed
- THEN `settings.app_env` is `test`
- AND the environment value is not consulted for that field

#### Scenario: Default applies when nothing is set
- GIVEN neither the environment nor `.env` defines `APP_ENV`
- WHEN `Settings` is constructed
- THEN `settings.app_env` takes its declared default of `dev`

### Requirement: No runtime-mutable configuration
The system MUST NOT read configuration values from the database at runtime.

#### Scenario: Settings resolve without a database
- GIVEN the configured database is unreachable
- WHEN `Settings` is constructed
- THEN construction succeeds
- AND every setting resolves from environment, `.env`, or defaults

### Requirement: Typed settings with validation
The system MUST reject invalid configuration at construction time rather than at first use.

#### Scenario: Malformed value fails fast
- GIVEN the environment sets `LLM_TIMEOUT_SECONDS=not-a-number`
- WHEN `Settings` is constructed
- THEN construction raises a validation error naming the offending field

#### Scenario: Unknown environment rejected
- GIVEN the environment sets `APP_ENV=production`
- WHEN `Settings` is constructed
- THEN construction raises a validation error
- AND the message lists the permitted values `dev`, `test`, `prod`

### Requirement: Per-task LLM routing is declarative
The system MUST allow the model backing any single LLM task to be overridden by
configuration alone, without changing code and without affecting other tasks.

#### Scenario: One route overridden, others unaffected
- GIVEN `LLM_DEFAULT_TASK_MODEL` is `anthropic/claude-sonnet-5`
- AND the environment sets `LLM_ROUTE__NARRATIVE=ollama/llama3.1`
- WHEN `Settings` is constructed
- THEN the model resolved for task `narrative` is `ollama/llama3.1`
- AND the model resolved for task `research` remains `anthropic/claude-sonnet-5`

### Requirement: Settings are injected, not imported
The system MUST expose settings to application code through dependency injection rather
than a module-level singleton.

#### Scenario: Test overrides settings without patching imports
- GIVEN a FastAPI test client
- WHEN the settings dependency is overridden with a test `Settings` instance
- THEN request handlers observe the test values
- AND no module-level import needs to be patched
