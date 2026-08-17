# platform-api

## ADDED Requirements

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
