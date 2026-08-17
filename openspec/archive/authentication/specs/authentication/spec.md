# authentication

## ADDED Requirements

### Requirement: Every endpoint requires authentication unless explicitly public
The platform MUST reject unauthenticated requests to any path not on a declared public list,
and that list MUST be enforced application-wide rather than per endpoint.

#### Scenario: An endpoint added later is protected by default
- GIVEN the served route table
- WHEN each path not on the public list is requested without credentials
- THEN each is rejected

#### Scenario: Writing endpoints reject anonymous requests
- GIVEN no credentials
- WHEN a fill, a cycle run or an insight action is requested
- THEN each is rejected

#### Scenario: Health remains public
- GIVEN no credentials
- WHEN the health endpoint is requested
- THEN it answers
- AND it exposes no portfolio data

### Requirement: Access and refresh tokens are distinguishable and not interchangeable
Every token MUST declare its type, and a token of the wrong type MUST be rejected wherever a
specific type is required.

#### Scenario: A refresh token cannot authorise a request
- GIVEN a valid refresh token
- WHEN it is presented as a bearer credential
- THEN the request is rejected

#### Scenario: An access token cannot be refreshed with
- GIVEN a valid access token
- WHEN it is presented where a refresh token is expected
- THEN it is rejected

#### Scenario: Tampered, expired and unsigned tokens are rejected
- GIVEN a token that is expired, signed with another key, or unsigned
- WHEN it is presented
- THEN it is rejected

### Requirement: Logging out revokes rather than forgets
Refresh tokens MUST be checked against stored state on every use, and logging out MUST prevent
further use of the presented token.

#### Scenario: A logged-out refresh token stops working
- GIVEN a session that has logged out
- WHEN its refresh token is presented again
- THEN it is rejected

#### Scenario: A used refresh token is rotated out
- GIVEN a refresh token that has been exchanged
- WHEN the same token is presented again
- THEN it is rejected

#### Scenario: Changing a password ends existing sessions
- GIVEN an active session
- WHEN the user's password is changed
- THEN that session can no longer be refreshed

### Requirement: Credentials are stored only as a modern password hash
The platform MUST store passwords only as a memory-hard hash, MUST NOT return that hash from
any endpoint, and MUST NOT reveal whether a username exists.

#### Scenario: Stored form is a hash, not the password
- GIVEN a created user
- WHEN the stored credential is read
- THEN it is a hash and does not contain the password

#### Scenario: Unknown user and wrong password are indistinguishable
- GIVEN an unknown username and a known username with a wrong password
- WHEN each is submitted
- THEN both fail identically

#### Scenario: No endpoint returns a password hash
- GIVEN an authenticated session
- WHEN account information is requested
- THEN no password material appears in the response

### Requirement: There is no usable default signing key
The signing key MUST be configured, MUST meet a minimum length, and its absence MUST prevent
production startup.

#### Scenario: Production without a key refuses to start
- GIVEN a production configuration with no signing key
- WHEN settings are loaded
- THEN loading fails naming the missing setting

#### Scenario: Development generates a per-process key
- GIVEN a development configuration with no signing key
- WHEN settings are loaded twice
- THEN each load produces a different key

#### Scenario: A short key is refused
- GIVEN a signing key shorter than the minimum
- WHEN settings are loaded
- THEN loading fails

### Requirement: The first user is created explicitly
The platform MUST provide a command to create a user and MUST NOT create any account
automatically at startup.

#### Scenario: A user can be created from the command line
- GIVEN an empty user table
- WHEN the create-user command runs
- THEN that user can log in afterwards

#### Scenario: Duplicate usernames are refused
- GIVEN an existing username
- WHEN it is created again
- THEN the attempt is refused
