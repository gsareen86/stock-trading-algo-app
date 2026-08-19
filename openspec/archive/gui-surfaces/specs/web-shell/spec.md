# web-shell

## ADDED Requirements

### Requirement: Surfaces never merge verdicts
A surface MUST NOT compute a value from more than one strategy's verdict, MUST NOT present a
consensus indicator, and MUST NOT order instruments by how many strategies agree.

#### Scenario: No aggregation across verdicts exists
- GIVEN the surface components
- WHEN they are inspected
- THEN none reduces, counts or averages across a verdict collection

#### Scenario: A verdict component receives one verdict
- GIVEN the component that renders a strategy's verdict
- WHEN its interface is inspected
- THEN it accepts a single verdict rather than a collection

#### Scenario: Strategies are shown side by side
- GIVEN an instrument with a verdict from every strategy
- WHEN it is displayed
- THEN each strategy appears separately with its own stance and conviction

### Requirement: Evidence is reachable from the verdict that used it
A displayed verdict MUST make its evidence available without leaving the page, and each row
MUST show the observed value, the comparison made, and its source reference.

#### Scenario: Evidence expands in place
- GIVEN a displayed verdict
- WHEN its evidence is opened
- THEN the rows appear without navigating away

#### Scenario: Rows show the comparison, not only the value
- GIVEN an evidence row that was tested against a threshold
- WHEN it is displayed
- THEN the operator, threshold and outcome appear beside the observed value

#### Scenario: Source references are shown
- GIVEN any evidence row
- WHEN it is displayed
- THEN its source reference is visible

### Requirement: Unavailable, unauthenticated and empty are distinguishable
A surface MUST render a failed fetch, an expired session and a genuinely empty result as three
different states.

#### Scenario: An expired session offers a way back
- GIVEN a request rejected for want of authentication
- WHEN the surface renders
- THEN it says so and links to signing in

#### Scenario: A broken seam names what it tried
- GIVEN an unreachable backend
- WHEN the surface renders
- THEN it reports the failure and the address attempted

#### Scenario: An empty book says it is empty
- GIVEN a book with no positions
- WHEN it is displayed
- THEN it states that, rather than rendering zeroed rows

### Requirement: Figures carry their unit and their basis
Displayed monetary figures MUST be shown in rupees, and any profit-and-loss figure MUST be
identified as gross of charges.

#### Scenario: Portfolio figures declare charges absent
- GIVEN a surface showing profit or loss
- WHEN it renders
- THEN it states that no brokerage, transaction tax or duty is included

#### Scenario: An unavailable price is not shown as zero
- GIVEN a position with no current price
- WHEN it is displayed
- THEN its market value reads as unavailable rather than zero

### Requirement: Acting from a surface previews before it writes
An action taken from a surface MUST show what it will do before performing it, and MUST use
the platform's existing endpoints.

#### Scenario: An action is previewed first
- GIVEN an insight with an action that trades
- WHEN the action is chosen
- THEN what it would do is shown before anything is recorded

#### Scenario: A refused action is explained
- GIVEN an action the backend refuses
- WHEN it is attempted
- THEN the reason is displayed
