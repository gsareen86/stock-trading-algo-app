# insights-feed

## ADDED Requirements

### Requirement: Only consequential observations reach the feed
An insight MUST be raised only when it could change what a person does. Verdicts about
instruments the reader holds no position in and has no actionable decision for MUST NOT
generate insights.

#### Scenario: A held name whose own strategy turns AVOID is surfaced
- GIVEN a position bought on a strategy's verdict
- AND that same strategy now rates the instrument AVOID
- WHEN insights are generated
- THEN a broken-thesis insight is raised naming the strategy and the holding

#### Scenario: An unheld name turning AVOID is not surfaced
- GIVEN an AVOID verdict for an instrument with no position
- WHEN insights are generated
- THEN no insight is raised for it

#### Scenario: Another strategy's AVOID is not a broken thesis
- GIVEN a position bought on one strategy's verdict
- AND a different strategy rates the instrument AVOID
- WHEN insights are generated
- THEN no broken-thesis insight is raised

#### Scenario: A position with no recorded strategy raises nothing
- GIVEN a holding with no strategy recorded on its buys
- WHEN insights are generated
- THEN no broken-thesis insight is raised

### Requirement: Severity is a property of the kind
Each insight kind MUST declare its severity, and the system MUST NOT compute a per-item score
comparable across kinds.

#### Scenario: Every kind declares a severity
- GIVEN the set of insight kinds
- WHEN each is inspected
- THEN it carries a declared severity and suppression window

#### Scenario: No ranking function exists
- GIVEN the insight modules
- WHEN searched for a function that scores, ranks or prioritises insights
- THEN none exists

### Requirement: Repeated observations are suppressed, not repeated
An insight matching a previously raised dedupe key within that kind's suppression window MUST
NOT be written again, and the earlier insight MUST remain unchanged.

#### Scenario: The same observation on a later cycle is suppressed
- GIVEN an insight already raised for a dedupe key
- WHEN a cycle produces the same key within the window
- THEN nothing new is written
- AND the suppression is reported

#### Scenario: Suppression preserves the original
- GIVEN a suppressed repeat
- WHEN the feed is read
- THEN the original insight appears once, with its original timestamp

#### Scenario: Outside the window it may be raised again
- GIVEN an insight older than its kind's suppression window
- WHEN the same observation recurs
- THEN a new insight is written

### Requirement: Research-derived insights are quoted, not asserted
An insight built from tool output MUST name the tool, carry its source reference, and record
that the platform did not measure it.

#### Scenario: A news finding names its tool
- GIVEN a research finding on a held instrument
- WHEN an insight is raised from it
- THEN the tool and source reference are recorded
- AND the insight is marked as not measured by the platform

#### Scenario: A failed tool result raises nothing
- GIVEN a research finding recording that a tool was unavailable
- WHEN insights are generated
- THEN no insight is raised from it

### Requirement: The feed is capped per cycle
The number of insights written by one cycle MUST be bounded, filled highest severity first,
and any truncation MUST be reported.

#### Scenario: High severity is written first
- GIVEN more candidates than the cap allows
- WHEN they are recorded
- THEN higher-severity insights are written before lower-severity ones

#### Scenario: Truncation is reported
- GIVEN candidates beyond the cap
- WHEN they are recorded
- THEN the number truncated is reported

### Requirement: Insights are delivered in the application only
The platform MUST NOT send insights by email, push notification or any messaging channel.

#### Scenario: No outbound delivery exists
- GIVEN the application package
- WHEN it is searched for mail, SMS, push or webhook delivery
- THEN none exists

### Requirement: Insights never act
Generating an insight MUST NOT create a trade, alter a verdict or change a position.

#### Scenario: An opportunity insight buys nothing
- GIVEN a verdict assessed as actionable
- WHEN an insight is raised for it
- THEN no trade is recorded
- AND the insight states that recording a fill is a separate step

### Requirement: Insights can be read and marked read
The feed MUST support listing insights, filtering to unread, reporting an unread count, and
marking an insight read.

#### Scenario: Unread count reflects marking
- GIVEN an unread insight
- WHEN it is marked read
- THEN the unread count decreases

#### Scenario: Marking an unknown insight is not an error condition of the store
- GIVEN an identifier no insight has
- WHEN it is marked read
- THEN the failure is reported rather than raised
