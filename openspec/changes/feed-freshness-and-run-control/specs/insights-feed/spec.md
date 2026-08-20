# insights-feed

## ADDED Requirements

### Requirement: An insight whose precondition no longer holds is withdrawn
The system MUST withdraw a standing insight when the rule that raised it, re-evaluated against
current state, would no longer raise it — and MUST record the reason.

#### Scenario: A closed position withdraws its concentration insight
- GIVEN a standing `concentration` insight for a ticker
- WHEN a cycle runs and the book holds none of that ticker
- THEN the insight is withdrawn
- AND the reason records that the position is closed

#### Scenario: A repaired thesis withdraws its insight
- GIVEN a standing `thesis_broken` insight for a held name
- WHEN the buying strategy's verdict is no longer AVOID
- THEN the insight is withdrawn

#### Scenario: Withdrawal is not deletion
- GIVEN a withdrawn insight
- WHEN insights are queried including withdrawn ones
- THEN the row is returned with its original creation time and its withdrawal reason

#### Scenario: A withdrawn insight leaves the feed
- GIVEN a withdrawn insight
- WHEN the default feed is read
- THEN it is absent

#### Scenario: Age is never a reason to withdraw
- GIVEN a standing insight whose precondition still holds
- WHEN a cycle runs any number of days later
- THEN it is not withdrawn

#### Scenario: A cycle withdraws only what it re-evaluated
- GIVEN standing insights on several held names
- WHEN a cycle runs against a subset of those names
- THEN insights about names outside that subset are left standing
- AND only insights whose subject the cycle actually re-evaluated may be withdrawn

#### Scenario: A rule that did not run withdraws nothing
- GIVEN a standing insight raised from research findings
- WHEN a cycle runs with research disabled
- THEN that insight is not withdrawn

#### Scenario: An absent data source does not withdraw
- GIVEN a standing insight raised from a provider that is now unreachable
- WHEN a cycle runs and the provider returns nothing
- THEN the insight is left standing rather than withdrawn as no longer true

#### Scenario: Withdrawal never fills
- GIVEN any insight being withdrawn
- WHEN withdrawal completes
- THEN no trade is recorded and no position changes

### Requirement: A standing insight's measurement is refreshed in place
The system MUST update the measured figure carried by a standing insight when the observation
remains true but the figure has changed, without creating a new row or resetting its age.

#### Scenario: A drifting concentration updates its figure
- GIVEN a standing `concentration` insight recorded at 35.1%
- WHEN a later cycle measures the same holding at 29.4%, still above the cap
- THEN the same row reports 29.4%
- AND its creation time is unchanged

#### Scenario: A regime that has not changed still reports today's level
- GIVEN a standing `regime_change` insight for a constructive regime
- WHEN a later cycle reads the benchmark and the regime is still constructive
- THEN the insight reports the benchmark level from that later read

#### Scenario: A refreshed insight does not become unread again
- GIVEN a standing insight already marked read
- WHEN its measurement is refreshed
- THEN it remains read

#### Scenario: A changed label is a new insight, not a refresh
- GIVEN a standing `regime_change` insight labelled constructive
- WHEN the regime becomes hostile
- THEN a new insight is raised for the new label

## MODIFIED Requirements

### Requirement: Repeated observations are suppressed, not repeated
An insight whose dedupe key is already standing MUST NOT be written again regardless of age,
and an insight whose key was withdrawn within its kind's suppression window MUST NOT be raised
again until that window has elapsed from the withdrawal. The earlier insight MUST keep its
identity, its creation time and its read state.

#### Scenario: The same observation on a later cycle is suppressed
- GIVEN an insight already standing for a dedupe key
- WHEN a cycle produces the same key
- THEN nothing new is written
- AND the suppression is reported

#### Scenario: A standing insight is never duplicated by age
- GIVEN a standing insight older than its kind's suppression window
- WHEN the same observation is produced again
- THEN no second row is written
- AND the standing row remains the only one for that key

#### Scenario: Suppression preserves the original's identity
- GIVEN a suppressed repeat
- WHEN the feed is read
- THEN the original insight appears once, with its original creation time and read state

#### Scenario: A recurrence after withdrawal is raised again
- GIVEN an insight withdrawn longer ago than its kind's suppression window
- WHEN the same observation recurs
- THEN a new insight is written

#### Scenario: A recurrence inside the window is suppressed
- GIVEN an insight withdrawn within its kind's suppression window
- WHEN the same observation recurs
- THEN nothing new is written

### Requirement: Every insight carries the time it was last measured
An insight MUST record when its figures were last established, distinctly from when it was
first raised.

#### Scenario: A freshly raised insight measures at its creation
- GIVEN a newly written insight
- WHEN it is read
- THEN its measurement time equals its creation time

#### Scenario: A refreshed insight reports the later measurement time
- GIVEN an insight raised on one day and refreshed on a later one
- WHEN it is read
- THEN the measurement time is the later one and the creation time is the earlier one
