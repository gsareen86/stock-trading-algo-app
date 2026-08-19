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

### Requirement: The web app never handles a token in page script
Tokens MUST be held in httpOnly cookies on the web origin and attached by a server-side proxy.
The browser page MUST NOT store a token in `localStorage`, `sessionStorage` or a variable
reachable by page script.

#### Scenario: Login stores nothing readable
- GIVEN a successful login through the web app
- WHEN page storage is inspected
- THEN no token is present

#### Scenario: Requests reach the backend through the proxy
- GIVEN a page fetching platform data
- WHEN the request is made
- THEN it goes to the application's own proxy route rather than directly to the backend

### Requirement: An expired session is refreshed once, then sent to login
The proxy MUST attempt a single refresh when the backend rejects a request, and MUST NOT retry
indefinitely.

#### Scenario: A stale access token is renewed transparently
- GIVEN an expired access token and a valid refresh token
- WHEN a page requests data
- THEN the session is renewed and the request succeeds

#### Scenario: A dead session ends at the login page
- GIVEN no valid refresh token
- WHEN a page requests data
- THEN the request is rejected once
- AND the visitor is directed to the login page

### Requirement: Surfaces never merge verdicts
A surface MUST NOT compute a value from more than one strategy's verdict, MUST NOT present a
consensus indicator, and MUST NOT order instruments by how many strategies agree.

#### Scenario: No aggregation across verdicts exists
- GIVEN the surface components
- WHEN they are inspected
- THEN none reduces, counts or averages across a verdict collection

#### Scenario: A verdict component receives one verdict
- GIVEN the component that renders a strategy's verdict
- WHEN its interface is inspected
- THEN it accepts a single verdict rather than a collection

#### Scenario: Strategies are shown side by side
- GIVEN an instrument with a verdict from every strategy
- WHEN it is displayed
- THEN each strategy appears separately with its own stance and conviction

### Requirement: Evidence is reachable from the verdict that used it
A displayed verdict MUST make its evidence available without leaving the page, and each row
MUST show the observed value, the comparison made, and its source reference.

#### Scenario: Evidence expands in place
- GIVEN a displayed verdict
- WHEN its evidence is opened
- THEN the rows appear without navigating away

#### Scenario: Rows show the comparison, not only the value
- GIVEN an evidence row that was tested against a threshold
- WHEN it is displayed
- THEN the operator, threshold and outcome appear beside the observed value

#### Scenario: Source references are shown
- GIVEN any evidence row
- WHEN it is displayed
- THEN its source reference is visible

### Requirement: Unavailable, unauthenticated and empty are distinguishable
A surface MUST render a failed fetch, an expired session and a genuinely empty result as three
different states.

#### Scenario: An expired session offers a way back
- GIVEN a request rejected for want of authentication
- WHEN the surface renders
- THEN it says so and links to signing in

#### Scenario: A broken seam names what it tried
- GIVEN an unreachable backend
- WHEN the surface renders
- THEN it reports the failure and the address attempted

#### Scenario: An empty book says it is empty
- GIVEN a book with no positions
- WHEN it is displayed
- THEN it states that, rather than rendering zeroed rows

### Requirement: Figures carry their unit and their basis
Displayed monetary figures MUST be shown in rupees, and any profit-and-loss figure MUST be
identified as gross of charges.

#### Scenario: Portfolio figures declare charges absent
- GIVEN a surface showing profit or loss
- WHEN it renders
- THEN it states that no brokerage, transaction tax or duty is included

#### Scenario: An unavailable price is not shown as zero
- GIVEN a position with no current price
- WHEN it is displayed
- THEN its market value reads as unavailable rather than zero

### Requirement: Acting from a surface previews before it writes
An action taken from a surface MUST show what it will do before performing it, and MUST use
the platform's existing endpoints.

#### Scenario: An action is previewed first
- GIVEN an insight with an action that trades
- WHEN the action is chosen
- THEN what it would do is shown before anything is recorded

#### Scenario: A refused action is explained
- GIVEN an action the backend refuses
- WHEN it is attempted
- THEN the reason is displayed
