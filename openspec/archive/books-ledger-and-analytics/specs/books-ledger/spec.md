# books-ledger

## ADDED Requirements

### Requirement: One ledger serves every book
The system MUST provide a single ledger implementation with the book as a parameter, and MUST
NOT provide a separate ledger type, module or table per book.

#### Scenario: Books are independent within one ledger
- GIVEN a fill recorded in one book
- WHEN another book's positions are read
- THEN that fill does not appear

#### Scenario: Adding a book requires no new ledger
- GIVEN the ledger module
- WHEN it is inspected
- THEN exactly one ledger type exists

### Requirement: A position is derived from trades, never stored independently
The system MUST compute a position by folding that symbol's trades within a book, and MUST NOT
persist quantity or average cost as independently writable values.

#### Scenario: Buy then partial sell
- GIVEN ten shares bought and four sold at a higher price
- WHEN the position is read
- THEN six remain at the original average cost
- AND the gain on the four is realised

#### Scenario: Full exit closes the position
- GIVEN a holding sold in full
- WHEN the position is read
- THEN the quantity is zero
- AND the realised profit or loss is recorded

#### Scenario: Trades out of order fold identically
- GIVEN the same trades supplied in a different order
- WHEN positions are derived
- THEN both produce the same average cost

#### Scenario: Selling more than held never creates a short
- GIVEN a sell larger than the held quantity reaches the fold
- WHEN the position is derived
- THEN the quantity is zero rather than negative

### Requirement: There is exactly one paper-execution boundary
Creating a trade MUST happen through one named function, and the platform MUST NOT contain a
broker or executor type that appears to execute.

#### Scenario: No broker type exists
- GIVEN the application package
- WHEN it is searched for a broker or executor class
- THEN none exists

#### Scenario: Overselling is refused at the boundary
- GIVEN a book holding fewer shares than a sell requests
- WHEN the fill is attempted
- THEN it is refused with the held quantity named

#### Scenario: Every fill records what caused it
- GIVEN a recorded fill
- WHEN it is read
- THEN its source is present

### Requirement: Reported profit and loss is gross and says so
Every profit-and-loss figure MUST exclude brokerage, transaction taxes and duties, and the
response MUST state that charges are not included.

#### Scenario: Charges are declared absent
- GIVEN a portfolio analytics response
- WHEN it is read
- THEN it states that charges are not included

#### Scenario: Unvalued positions do not become zero
- GIVEN an open position with no available price
- WHEN unrealised profit is computed
- THEN it is reported as unavailable rather than zero

#### Scenario: A partial portfolio total is withheld
- GIVEN several open positions and a missing price for one
- WHEN market value is computed
- THEN no total is reported

### Requirement: Analytics report activity without ranking strategies
Portfolio analytics MUST NOT produce a measure that ranks strategies against one another.

#### Scenario: Attribution reports per strategy
- GIVEN trades attributed to different strategies
- WHEN attribution is read
- THEN each strategy's activity is reported separately

#### Scenario: Win rate counts only closed positions
- GIVEN open and closed positions
- WHEN the win rate is computed
- THEN only closed positions contribute
