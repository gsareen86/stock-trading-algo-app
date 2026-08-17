# platform-api

## ADDED Requirements

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
