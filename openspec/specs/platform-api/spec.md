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

### Requirement: Health reports trading-calendar coverage
`GET /health` MUST report the range of years the NSE holiday data covers and whether the
current year is among them.

#### Scenario: Current year covered
- GIVEN holiday data covering the current year
- WHEN `GET /health` is requested
- THEN the calendar section reports the covered years and `current_year_covered` true

#### Scenario: Holiday data has run out
- GIVEN holiday data whose latest year is before the current year
- WHEN `GET /health` is requested
- THEN `current_year_covered` is false
- AND overall `status` is `degraded`

#### Scenario: Stale calendar does not fail the request
- GIVEN holiday data that does not cover the current year
- WHEN `GET /health` is requested
- THEN the response status is still 200


### Requirement: Registered strategies are listable
`GET /strategies` MUST return the registered strategies with their identity and any load
failures.

#### Scenario: Strategies listed
- GIVEN the registry has loaded
- WHEN `GET /strategies` is requested
- THEN each strategy is returned with its id, name and description

#### Scenario: Load failures surfaced
- GIVEN a strategy module that failed to import
- WHEN `GET /strategies` is requested
- THEN that failure appears in the response

### Requirement: Instruments can be evaluated on demand
`POST /verdicts/evaluate` MUST evaluate named instruments and return one verdict per strategy
per instrument. Narration MUST be opt-in and MUST NOT be attempted unless requested.

#### Scenario: Evaluation returns verdicts with evidence
- GIVEN a symbol with price history
- WHEN evaluation is requested
- THEN a verdict is returned carrying stance, conviction, gates and evidence

#### Scenario: Verdicts are returned per strategy, never merged
- GIVEN more than one registered strategy
- WHEN a symbol is evaluated
- THEN one verdict per strategy is returned
- AND no combined stance or score appears in the response

#### Scenario: Evaluation does not persist by default
- GIVEN an evaluation request without a persist flag
- WHEN it completes
- THEN no verdict is written to storage

#### Scenario: Persisting is explicit
- GIVEN an evaluation request asking to persist
- WHEN it completes
- THEN the verdicts are retrievable afterwards

#### Scenario: Narration is off by default
- GIVEN an evaluation request without a narrate flag
- WHEN it completes
- THEN no language model is called
- AND every returned verdict has a null narrative

#### Scenario: Unknown strategy requested
- GIVEN a strategy id no strategy declares
- WHEN evaluation is requested for it
- THEN the response is a validation error naming the unknown id

### Requirement: Stored verdicts are listable
`GET /verdicts` MUST return stored verdicts, most recent first, filterable by ticker and
strategy.

#### Scenario: Filtered by ticker
- GIVEN stored verdicts for several tickers
- WHEN verdicts are requested for one ticker
- THEN only that ticker's verdicts are returned

#### Scenario: Newest first
- GIVEN several stored verdicts
- WHEN they are listed
- THEN they are ordered most recent first

#### Scenario: Bounded page size
- GIVEN a request for more verdicts than the permitted maximum
- WHEN it is made
- THEN the response is a validation error naming the limit

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

### Requirement: Registered tools are listable
`GET /tools` MUST return the registered tool manifests and any load failures.

#### Scenario: Tools listed with their contracts
- GIVEN the registry has loaded the seed tools
- WHEN `GET /tools` is requested
- THEN each tool is returned with its name, version, summary and input schema

#### Scenario: Load failures surfaced
- GIVEN a tool module that failed to import
- WHEN `GET /tools` is requested
- THEN that failure appears in the response
- AND a capability that vanished is distinguishable from one never written

#### Scenario: Handlers are not exposed
- GIVEN the registered tools
- WHEN `GET /tools` is requested
- THEN no handler reference or import path appears in the response

### Requirement: Narration outcomes are reported per verdict
When narration is requested, the response MUST report an outcome for each verdict, so an
absent narrative is distinguishable from one that was never requested.

#### Scenario: Successful narration reported
- GIVEN narration is requested and validation passes
- WHEN the response is returned
- THEN the outcome for that verdict is reported as successful
- AND the verdict carries prose

#### Scenario: Rejected narrative does not fail the request
- GIVEN a generated narrative containing an untraceable figure
- WHEN the response is returned
- THEN the request succeeds
- AND that verdict's outcome names the rejection

#### Scenario: Unavailable model does not cost the caller their verdicts
- GIVEN no language model answers
- WHEN narration was requested
- THEN the verdicts are still returned
- AND each outcome reports the model as unavailable

### Requirement: The root path identifies the service
`GET /` MUST answer successfully with the service identity and the paths of its real
endpoints, rather than a 404.

#### Scenario: Root answers rather than 404
- GIVEN the API is running
- WHEN `GET /` is requested
- THEN the response is 200

#### Scenario: Root names where to go next
- GIVEN a response from `GET /`
- WHEN it is read
- THEN it names the interactive documentation path
- AND lists the platform's endpoints

#### Scenario: Root does not duplicate the health report
- GIVEN a response from `GET /`
- WHEN it is read
- THEN it carries no seam status
- AND health remains the single answer to whether the platform is up

### Requirement: A cycle can be run on demand
`POST /cycles/run` MUST run the orchestrated cycle for named instruments and return one verdict
per strategy per instrument, with no combined stance anywhere in the response.

#### Scenario: Cycle returns one verdict per strategy
- GIVEN four registered strategies
- WHEN a cycle is run for one symbol
- THEN four verdicts are returned

#### Scenario: No combined stance appears
- GIVEN a cycle result
- WHEN the response is read
- THEN it carries no overall stance, score or consensus field

#### Scenario: Regime, research and notes are reported
- GIVEN a completed cycle
- WHEN the response is read
- THEN it reports the regime read, research findings and run notes

#### Scenario: Unreachable MCP server does not fail the request
- GIVEN a configured MCP server that cannot be reached
- WHEN a cycle is run
- THEN the response succeeds
- AND the server is reported as unreachable

#### Scenario: Agent graph unavailable
- GIVEN the agent dependencies are not installed
- WHEN a cycle is requested
- THEN the response reports the capability as unavailable rather than as a server error

### Requirement: The platform publishes an A2A agent card
`GET /.well-known/agent-card.json` MUST return an agent card listing the platform's registered
tools, rendered from the same manifests the tool definitions use.

#### Scenario: Card lists every registered tool
- GIVEN the tool registry
- WHEN the agent card is requested
- THEN every registered tool appears in it

#### Scenario: Card does not claim capabilities the platform lacks
- GIVEN the agent card
- WHEN its capabilities are read
- THEN streaming and push notifications are declared unsupported

### Requirement: The investable universe is inspectable
`GET /universe` MUST return the current universe snapshot, how it was obtained, and any
symbols excluded from it.

#### Scenario: Snapshot reports its origin
- GIVEN a universe snapshot
- WHEN it is requested
- THEN whether it came from the live source or the bundled fallback is reported

#### Scenario: Blocklisted symbols are visible
- GIVEN symbols removed by the blocklist
- WHEN the universe is requested
- THEN those symbols are reported separately from the constituents

### Requirement: A screen can be run on demand
`POST /screen` MUST apply eligibility filters to the universe and return the eligible
instruments together with why the others were excluded.

#### Scenario: Screen reports eligible and excluded
- GIVEN a universe
- WHEN a screen is requested
- THEN the eligible instruments and a per-filter exclusion count are returned

#### Scenario: Exclusion detail can be omitted without losing the counts
- GIVEN a screen requested without exclusion detail
- WHEN the response is read
- THEN individual exclusions are absent
- AND the per-filter counts remain

#### Scenario: Surveillance freshness is reported
- GIVEN a screen result
- WHEN it is read
- THEN the surveillance list's date and staleness are present

### Requirement: Positions, trades and analytics are readable per book
The API MUST expose a book's open positions, its trade history and its portfolio analytics.

#### Scenario: Positions are returned with their marks
- GIVEN a book holding positions
- WHEN they are requested
- THEN each is returned with quantity, average cost and, where a price is available, market value

#### Scenario: Analytics declare charges absent
- GIVEN a portfolio analytics response
- WHEN it is read
- THEN it states that charges are not included

#### Scenario: An unknown book is rejected
- GIVEN a book name the platform does not define
- WHEN positions are requested for it
- THEN the response is a validation error

### Requirement: A paper fill can be recorded over the API
`POST /books/{book}/fill` MUST record a paper fill and return the resulting position.

#### Scenario: A fill updates the derived position
- GIVEN an empty book
- WHEN a buy is recorded
- THEN the returned position reflects it

#### Scenario: Overselling is a client error
- GIVEN a book holding fewer shares than a sell requests
- WHEN the fill is posted
- THEN the response is a validation error rather than a server error

### Requirement: The insight feed is readable and markable
The API MUST expose the insight feed, an unread count, the available kinds with their declared
severity, and a way to mark an insight read.

#### Scenario: Feed returns insights with severity
- GIVEN recorded insights
- WHEN the feed is requested
- THEN each is returned with its kind, severity and whether it has been read

#### Scenario: Unread count is available on its own
- GIVEN recorded insights
- WHEN the unread count is requested
- THEN the number of unread insights is returned

#### Scenario: Kinds are published with their severity
- GIVEN the insight kinds
- WHEN they are requested
- THEN each is returned with its severity and suppression window

#### Scenario: Marking an unknown insight is a not-found
- GIVEN an identifier no insight has
- WHEN it is marked read
- THEN the response is a not-found error

### Requirement: A book's health is readable
`GET /books/{book}/health` MUST return the health score with its components and guidance.

#### Scenario: Health returns components and guidance
- GIVEN a book with positions
- WHEN its health is requested
- THEN the score, every component and any guidance steps are returned

#### Scenario: Health declares charges absent
- GIVEN a health response
- WHEN it is read
- THEN it states that charges are not included

### Requirement: An insight can be acted on
`POST /insights/{id}/act` MUST execute a declared action for that insight, or explain why it
cannot.

#### Scenario: Insights list their available actions
- GIVEN insights in the feed
- WHEN they are listed
- THEN each carries the actions available for its kind

#### Scenario: An unavailable action is rejected
- GIVEN an action not declared for an insight's kind
- WHEN it is requested
- THEN the response is a validation error

#### Scenario: A stale insight is a conflict, not a server error
- GIVEN an insight whose position has since been closed
- WHEN an action against it is requested
- THEN the response reports the conflict

#### Scenario: Acting marks the insight read
- GIVEN an executed action
- WHEN the feed is read
- THEN that insight is marked read
