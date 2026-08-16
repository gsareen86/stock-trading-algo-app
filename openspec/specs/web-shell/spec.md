# web-shell

The six surfaces, how they are styled, and how they consume the backend.

Introduced by `bootstrap-platform-skeleton` (see `openspec/archive/`).

### Requirement: Six surfaces organised by intent
The web application MUST expose exactly six top-level surfaces — Today, Ideas, Positions,
Stock, Performance and Engine — each reachable from persistent navigation.

#### Scenario: Every surface is routable
- GIVEN the web application is running
- WHEN each of `/`, `/ideas`, `/positions`, `/stock`, `/performance`, `/engine` is visited
- THEN the page renders without error
- AND the navigation marks the visited surface as active

#### Scenario: Placeholder content is labelled as such
- GIVEN a surface whose real content lands in a later change
- WHEN it is visited
- THEN it renders a labelled placeholder naming the change that will fill it
- AND it does not display fabricated trading data

#### Scenario: Engine shows LLM usage
- GIVEN the backend is reachable
- WHEN `/engine` is visited
- THEN it renders recorded LLM spend, token usage and recent calls
- AND it is no longer a placeholder

### Requirement: The shell proves the backend seam
The Today surface MUST fetch live status from the backend and render it, so a broken
frontend-to-backend seam is visible in the UI rather than only in logs.

#### Scenario: Backend reachable
- GIVEN the backend is running and reachable at the configured API base URL
- WHEN the Today surface is loaded
- THEN it displays the backend's reported app, database and LLM provider status

#### Scenario: Backend unreachable
- GIVEN the backend is not running
- WHEN the Today surface is loaded
- THEN the page still renders
- AND it displays an explicit connection-failure state naming the API base URL it tried

### Requirement: Insights are delivered in-app only
The system MUST deliver insights through the web application, and MUST NOT send them over
email, push notification, or messaging integrations.

#### Scenario: No outbound notification channel exists
- GIVEN the shipped application
- WHEN its configuration and dependencies are inspected
- THEN no email, push, or messaging credential is required
- AND no outbound notification is sent when an insight is produced

### Requirement: Design tokens are the single source of visual style
The web application MUST define colour, spacing and typography as shared tokens, and
surfaces MUST consume those tokens rather than hard-coded values.

#### Scenario: Surfaces use tokens
- GIVEN the six surface components
- WHEN their styles are inspected
- THEN they reference shared design tokens
- AND no surface hard-codes a hex colour

#### Scenario: Theme applies consistently
- GIVEN a token value is changed in one place
- WHEN the application is rebuilt
- THEN every surface reflects the change

### Requirement: The API base URL is configurable
The web application MUST read its backend base URL from configuration, and MUST NOT hard-code
it.

#### Scenario: Base URL comes from environment
- GIVEN `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
- WHEN the Today surface fetches backend status
- THEN the request is issued against `http://localhost:8000`

### Requirement: Engine surfaces cost without an external service
The Engine surface MUST render LLM spend and usage from the platform's own records, so cost
is visible with no Langfuse account configured. Monetary figures MUST be rendered in rupees,
and a real spend MUST NOT be rounded to a displayed zero.

#### Scenario: Usage rendered with observability unconfigured
- GIVEN no Langfuse credentials are present
- AND calls have been recorded
- WHEN `/engine` is visited
- THEN spend, token counts and recent calls are displayed

#### Scenario: Amounts shown in rupees
- GIVEN recorded paid calls
- WHEN `/engine` is visited
- THEN monetary figures are rendered with the rupee sign

#### Scenario: Sub-paisa spend is not shown as zero
- GIVEN a recorded spend smaller than one paisa but greater than zero
- WHEN `/engine` is visited
- THEN it is rendered as being below one paisa rather than as `₹0.00`

#### Scenario: Budget shown when configured
- GIVEN a daily budget is configured
- WHEN `/engine` is visited
- THEN today's spend is shown against the cap

#### Scenario: No calls yet
- GIVEN no calls have been recorded
- WHEN `/engine` is visited
- THEN it renders an explicit empty state rather than fabricated figures
