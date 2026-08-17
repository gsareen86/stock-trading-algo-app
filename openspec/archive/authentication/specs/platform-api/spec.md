# platform-api

## ADDED Requirements

### Requirement: The API exposes login, refresh, logout and identity
The platform MUST provide endpoints to obtain a session, renew it, end it, and report who the
current session belongs to.

#### Scenario: Login returns an access token and sets a refresh cookie
- GIVEN valid credentials
- WHEN login is requested
- THEN an access token is returned
- AND the refresh token is set as an httpOnly cookie

#### Scenario: The returned token opens protected endpoints
- GIVEN an access token from login
- WHEN it is presented as a bearer credential
- THEN a protected endpoint answers

#### Scenario: Refresh without a cookie is rejected
- GIVEN no refresh cookie
- WHEN a refresh is requested
- THEN it is rejected

#### Scenario: Logout without a session is not an error
- GIVEN no active session
- WHEN logout is requested
- THEN it succeeds and reports that nothing was revoked

#### Scenario: Identity reports the authenticated user
- GIVEN an authenticated session
- WHEN identity is requested
- THEN the username is returned
