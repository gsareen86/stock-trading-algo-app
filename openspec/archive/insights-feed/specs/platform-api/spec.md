# platform-api

## ADDED Requirements

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
