# risk-management

## ADDED Requirements

### Requirement: Risk decides about acting and never alters a verdict
Risk assessment MUST return a decision about whether to act on a verdict, and MUST NOT change
that verdict's stance, conviction, gates or evidence.

#### Scenario: A blocked verdict is unchanged
- GIVEN a BUY verdict for a name already held
- WHEN risk assesses it
- THEN the decision is to block
- AND the verdict's stance and conviction are unchanged

#### Scenario: A non-actionable stance is not reported as blocked
- GIVEN a WATCH or AVOID verdict
- WHEN risk assesses it
- THEN it is reported as not actionable rather than blocked

### Requirement: Risk never compares one verdict to another
Risk MUST size a single verdict against portfolio state, and MUST NOT rank, sort or allocate
between verdicts.

#### Scenario: Assessment takes one verdict
- GIVEN the risk assessment interface
- WHEN it is inspected
- THEN it accepts a single verdict rather than a collection

#### Scenario: No ranking or allocation function exists
- GIVEN the risk module
- WHEN it is searched for a function that ranks, scores or allocates between verdicts
- THEN none exists

### Requirement: Portfolio gates block with a named reason
When risk declines to act, it MUST identify which constraint stopped it.

#### Scenario: Already held
- GIVEN a BUY for a name the book already holds
- WHEN adding is not permitted
- THEN the decision names the existing holding

#### Scenario: Position count reached
- GIVEN a book at its maximum number of positions
- WHEN a further BUY is assessed
- THEN the decision names the position-count constraint

#### Scenario: Capital exhausted
- GIVEN a book with no remaining capital
- WHEN a BUY is assessed
- THEN the decision names the capital constraint

#### Scenario: No price to size against
- GIVEN no current price for the instrument
- WHEN a BUY is assessed
- THEN it is blocked rather than sized against a guessed price

### Requirement: Position size respects conviction and caps
Size MUST scale with the verdict's own conviction and MUST NOT exceed the configured
per-position cap or remaining capital.

#### Scenario: Higher conviction sizes larger
- GIVEN two BUY verdicts differing only in conviction
- WHEN each is sized against the same portfolio
- THEN the higher-conviction verdict receives the larger size

#### Scenario: Per-position cap is respected
- GIVEN a target size above the per-position cap
- WHEN the verdict is sized
- THEN the resulting notional does not exceed the cap
