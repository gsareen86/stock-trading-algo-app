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
Configuration MUST be a typed settings object validated at load time, so an invalid value
fails at startup rather than at the moment it is first used. Monetary settings MUST be
denominated in INR and named accordingly.

#### Scenario: Invalid value rejected at startup
- GIVEN a setting whose value violates its declared constraint
- WHEN the application starts
- THEN startup fails with an error naming the setting

#### Scenario: Spend cap is expressed in rupees
- GIVEN `LLM_DAILY_BUDGET_INR=500`
- WHEN settings are loaded
- THEN the daily cap is five hundred rupees
- AND the equivalent cap in the provider's billing currency is derived from the configured rate

#### Scenario: Unset cap means unlimited
- GIVEN `LLM_DAILY_BUDGET_INR` is not set
- WHEN settings are loaded
- THEN no daily cap is in effect

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

### Requirement: Money is reported in rupees at a configured rate
The platform MUST report monetary amounts to the operator in INR, and MUST obtain the
USD→INR rate from configuration rather than a network call. The rate MUST be positive.

#### Scenario: Default rate available with no configuration
- GIVEN `USD_INR_RATE` is not set
- WHEN settings are loaded
- THEN a positive default rate is in effect
- AND no network request is made to obtain it

#### Scenario: Operator overrides the rate
- GIVEN `USD_INR_RATE=90.5`
- WHEN a dollar amount is converted for reporting
- THEN it is converted at 90.5

#### Scenario: Non-positive rate rejected
- GIVEN `USD_INR_RATE=0`
- WHEN settings are loaded
- THEN loading fails with a validation error

### Requirement: A retired configuration key fails loudly
When a configuration key is renamed such that its old value would be misread under the new
meaning, the platform MUST reject the retired key at startup and name its replacement, rather
than ignoring it or reinterpreting its value.

#### Scenario: Retired budget key rejected
- GIVEN `LLM_DAILY_BUDGET_USD=5.00` is set
- WHEN settings are loaded
- THEN loading fails with an error naming `LLM_DAILY_BUDGET_INR`
- AND the value is not reinterpreted as rupees

### Requirement: Local model latency is configured separately
The platform MUST expose a separate timeout setting for local providers, so tuning for hosted
latency cannot make local providers unusable.

#### Scenario: Local timeout defaults higher than the hosted one
- GIVEN no timeout settings are configured
- WHEN settings are loaded
- THEN the local timeout is greater than the hosted timeout

#### Scenario: Non-positive timeout rejected
- GIVEN `LLM_LOCAL_TIMEOUT_SECONDS=0`
- WHEN settings are loaded
- THEN loading fails with a validation error
