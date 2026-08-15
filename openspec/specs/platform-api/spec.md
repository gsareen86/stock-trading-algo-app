# platform-api

The HTTP surface the web application consumes.

Introduced by `bootstrap-platform-skeleton` (see `openspec/archive/`).

### Requirement: Health endpoint reports every external seam
`GET /health` MUST report application status, database status, and LLM provider status in a
single response.

#### Scenario: All seams healthy
- GIVEN the database is reachable and at head revision
- AND at least one LLM provider is configured
- WHEN `GET /health` is requested
- THEN the response status is 200
- AND the body reports app version, `database.connected` true, the current Alembic
  revision, and a per-provider status list

### Requirement: Degraded seams are reported, not hidden
`GET /health` MUST return a successful response describing a degraded seam rather than
failing outright, so the cause is visible to the caller.

#### Scenario: Database unreachable
- GIVEN the configured database cannot be reached
- WHEN `GET /health` is requested
- THEN the response status is 200
- AND `database.connected` is false with a reason
- AND overall `status` is `degraded`

#### Scenario: Database behind head
- GIVEN the database is reachable but its revision is older than head
- WHEN `GET /health` is requested
- THEN `database.migrations_current` is false
- AND both the current and head revisions are reported

#### Scenario: No LLM provider configured
- GIVEN no provider credentials are present
- WHEN `GET /health` is requested
- THEN the response status is 200
- AND every provider is reported as not configured
- AND overall `status` is `degraded`

### Requirement: Health reflects whether unrouted tasks can actually run
`GET /health` MUST report `status` as `degraded` when the provider backing the default task
model is unconfigured, regardless of how many other providers are configured.

#### Scenario: Only a non-default provider is configured
- GIVEN the default task model routes to a provider with no credentials
- AND one other provider is configured and routed to a single task
- WHEN `GET /health` is requested
- THEN `llm.any_configured` is true
- AND `llm.default_model_usable` is false
- AND overall `status` is `degraded`

#### Scenario: Default model's provider is configured
- GIVEN the provider backing the default task model has credentials
- WHEN `GET /health` is requested
- THEN `llm.default_model_usable` is true
- AND overall `status` is `ok`

### Requirement: Provider status distinguishes configured from reachable
`GET /health` MUST report separately whether a provider has credentials and whether it
responded to a probe.

#### Scenario: Configured but unreachable local provider
- GIVEN a local provider base URL is configured
- AND no server is listening at that URL
- WHEN `GET /health` is requested
- THEN that provider is reported `configured` true and `reachable` false

#### Scenario: Reachability probing is opt-in
- GIVEN the request is `GET /health` without a probe parameter
- WHEN the response is produced
- THEN no outbound provider request is made
- AND `reachable` is reported as `null` for every provider

### Requirement: Health check never leaks credentials
`GET /health` MUST NOT include API keys, connection strings, or other secrets in its
response.

#### Scenario: Secrets absent from response
- GIVEN provider credentials and a database URL are configured
- WHEN `GET /health` is requested
- THEN the response body contains no key material and no connection string
- AND providers are identified by name only

### Requirement: Browser origin is explicitly allowed
The API MUST accept cross-origin requests only from the configured web origin.

#### Scenario: Configured origin permitted
- GIVEN `WEB_ORIGIN=http://localhost:3000`
- WHEN the web application requests `GET /health` from that origin
- THEN the response carries the matching CORS headers

#### Scenario: Unconfigured origin rejected
- GIVEN `WEB_ORIGIN=http://localhost:3000`
- WHEN a request arrives from `http://evil.example`
- THEN the response does not carry CORS headers permitting that origin
