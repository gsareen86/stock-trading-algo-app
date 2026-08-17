# insights-feed

## ADDED Requirements

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
