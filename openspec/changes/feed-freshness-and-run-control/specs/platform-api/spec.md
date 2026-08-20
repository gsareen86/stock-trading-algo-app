# platform-api

## ADDED Requirements

### Requirement: Withdrawn insights are excluded by default and retrievable on request
`GET /insights` MUST omit withdrawn insights unless they are explicitly requested, and MUST
report each withdrawn insight's reason when they are.

#### Scenario: Default listing omits withdrawn insights
- GIVEN a feed containing standing and withdrawn insights
- WHEN `GET /insights` is called with no withdrawal filter
- THEN only standing insights are returned

#### Scenario: Withdrawn insights are requestable
- GIVEN a feed containing withdrawn insights
- WHEN `GET /insights?include_withdrawn=true` is called
- THEN they are returned, each carrying its withdrawal reason and time

#### Scenario: Unread count ignores withdrawn insights
- GIVEN an unread insight that is then withdrawn
- WHEN the unread count is read
- THEN it does not count that insight

#### Scenario: A withdrawn insight cannot be acted on
- GIVEN a withdrawn insight
- WHEN an action is posted against it
- THEN the request is refused as stale
- AND no trade is recorded

### Requirement: A cycle reports what it withdrew and refreshed
A cycle that surfaces insights MUST report counts of insights written, suppressed, truncated,
refreshed and withdrawn.

#### Scenario: Counts are reported per run
- GIVEN a cycle that surfaces insights
- WHEN it completes
- THEN the response reports all five counts

#### Scenario: A cycle that surfaces nothing reports no counts
- GIVEN a cycle run with insight surfacing disabled
- WHEN it completes
- THEN no insight counts are reported at all
