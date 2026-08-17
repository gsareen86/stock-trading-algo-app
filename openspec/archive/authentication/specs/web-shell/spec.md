# web-shell

## ADDED Requirements

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
