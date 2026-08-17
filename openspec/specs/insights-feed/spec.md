# insights-feed

The few things from a cycle worth a person's attention — portfolio consequences first, in-app
only, and quiet enough to stay worth reading.

Introduced by `insights-feed` (see `openspec/archive/`).

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

### Requirement: Available actions are declared by insight kind
Each insight kind MUST declare which actions are available for it, and a review action MUST be
available for every kind.

#### Scenario: Kinds declare their actions
- GIVEN a broken-thesis insight
- WHEN its available actions are read
- THEN exiting is among them

#### Scenario: Review is always available
- GIVEN any insight kind
- WHEN its available actions are read
- THEN review is among them

#### Scenario: An unknown kind still offers review
- GIVEN an insight kind the platform does not define
- WHEN its available actions are read
- THEN only review is offered

### Requirement: An action re-derives quantity from the ledger
Executing an action MUST compute quantities from the current position, and MUST NOT use a
quantity recorded on the insight.

#### Scenario: Exit sells the current holding
- GIVEN an insight raised when a different quantity was held
- WHEN the exit action is executed
- THEN the quantity sold is the currently held quantity

#### Scenario: A closed position refuses the action
- GIVEN an insight for a position that has since been closed
- WHEN an action against it is attempted
- THEN it is refused with that reason

#### Scenario: Trim is refused when no longer concentrated
- GIVEN a holding no longer above the concentration target
- WHEN a trim is attempted
- THEN it is refused

#### Scenario: A missing price refuses rather than guesses
- GIVEN no current price for the instrument
- WHEN an action requiring a fill is attempted
- THEN it is refused

### Requirement: Actions execute through the single execution boundary
An action that trades MUST do so through the ledger's fill function and MUST NOT write trades
by any other path.

#### Scenario: Acting records a trade through the ledger
- GIVEN an executed exit action
- WHEN the book is read
- THEN the position reflects the fill
- AND the trade records the insight that prompted it

#### Scenario: No alternative write path exists
- GIVEN the actions module
- WHEN it is inspected
- THEN it writes no trade rows directly

### Requirement: Preview runs the same derivation without writing
Requesting a preview MUST produce the same plan as execution and MUST NOT record a trade.

#### Scenario: Preview writes nothing
- GIVEN a preview of an exit action
- WHEN it completes
- THEN no trade is recorded and the position is unchanged

#### Scenario: Preview and execution agree
- GIVEN the same insight and portfolio state
- WHEN previewed and then executed
- THEN both produce the same quantity and side

### Requirement: Reviewing an insight acts on nothing
The review action MUST mark an insight read without recording any trade.

#### Scenario: Review changes no position
- GIVEN a review action
- WHEN it completes
- THEN no trade is recorded and the position is unchanged
