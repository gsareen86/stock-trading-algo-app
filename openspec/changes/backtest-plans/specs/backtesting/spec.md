# backtesting

## MODIFIED Requirements

### Requirement: Fills happen after the deciding bar
A simulated trade MUST execute at a session strictly after the one whose data produced the
decision, and in plan mode MUST execute only when that later session reaches the plan's entry.

#### Scenario: A plan's entry fills when price trades through it
- GIVEN a BUY with a plan entry, decided at a session's close
- WHEN a later session's high reaches the entry while its open is below it
- THEN the trade executes at the entry on that later session

#### Scenario: A gap through the entry fills at the open
- GIVEN a working entry order
- WHEN a later session opens above the entry but within the chase limit
- THEN the trade executes at that session's open

#### Scenario: An extended open is not chased
- GIVEN a working entry order
- WHEN a later session opens above the entry by more than the chase limit
- THEN no trade is recorded and the skip is counted

#### Scenario: Next-open mode buys the following open
- GIVEN entry mode `next_open` and a BUY decided at a session's close
- WHEN the trade is recorded
- THEN it executes at the following session's opening price

#### Scenario: A signal on the final session cannot fill
- GIVEN a decision on the last available session
- WHEN a fill is sought
- THEN none is available and no trade is recorded

### Requirement: Replay steps through trading sessions only
The runner MUST evaluate on market sessions, and MUST NOT produce decisions for non-trading
days.

#### Scenario: The calendar decides which days are evaluated
- GIVEN a market calendar covering the window
- WHEN a replay runs
- THEN it consults the calendar for each candidate day

#### Scenario: Years the calendar does not cover use the market's own sessions
- GIVEN a calendar that does not cover a year in the window
- WHEN a replay runs
- THEN that year's sessions are the days the market index printed a bar
- AND the report names the years treated this way

#### Scenario: A window with no sessions is reported
- GIVEN a window in which the market never opens
- WHEN a replay runs
- THEN it completes and reports that there was nothing to replay

### Requirement: Every report states what it could not account for
A replay result MUST carry the biases and approximations that apply to it, including
survivorship, the cost model used, fill assumptions and the parts of exit rules not modelled.

#### Scenario: Biases accompany every result
- GIVEN any completed replay
- WHEN the report is read
- THEN survivorship, the cost and slippage estimate and the fill assumptions are stated

#### Scenario: Positions closed by the window are reported
- GIVEN a position still open on the last session
- WHEN the report is read
- THEN it is closed at the last close and the report says it was closed by the window

## ADDED Requirements

### Requirement: A strategy's fundamentals are as of their filing deadline
Replay MUST hide a quarter's reported figures until its SEBI filing deadline has passed: 45 days
after the quarter's end, 60 days for a quarter ending in March.

#### Scenario: A quarter appears on its deadline
- GIVEN a quarter ending 30 June
- WHEN the fundamental strategy is evaluated on 13 August and on 14 August
- THEN the quarter is absent on 13 August and present on 14 August

### Requirement: Positions are managed every session
Replay MUST check every open position's stop on every session, and MUST close a position at the
next open once its strategy's exit rule, its strategy turning AVOID, or the hold limit says so.

#### Scenario: A stop traded through exits at the stop
- GIVEN an open position with a stop
- WHEN a session's low reaches the stop and its open is above it
- THEN the position closes at the stop on that session

#### Scenario: A gap below the stop exits at the open
- GIVEN an open position with a stop
- WHEN a session opens below the stop
- THEN the position closes at that open

#### Scenario: The buying strategy turning AVOID exits
- GIVEN an open position opened by a strategy
- WHEN that strategy rates the name AVOID on an evaluation session
- THEN the position closes at the next open
- AND another strategy's opinion never closes it

#### Scenario: Every strategy has an exit rule
- GIVEN the registered strategies
- WHEN the replay's exit rules are listed
- THEN each strategy has one, stating its plan's rule, what is checked and what is not modelled

### Requirement: Each trade is measured against the market after costs
Replay MUST record, for each closed trade, its return gross and net of the declared round-trip
cost, its R-multiple against the plan's stop, and its excess over the configured benchmark over
the same sessions.

#### Scenario: Net return deducts the declared cost
- GIVEN a round-trip cost of 0.25%
- WHEN a trade closes
- THEN its net return is its gross return less 0.25 percentage points

#### Scenario: Excess uses the same sessions
- GIVEN a trade from session A to session B
- WHEN excess is computed
- THEN the benchmark's return from session A to session B is subtracted

### Requirement: Conviction is tested within each strategy
Replay MUST report each strategy's closed trades by conviction band, and MUST flag any figure
resting on fewer than 30 trades as thin.

#### Scenario: Bands are per strategy
- GIVEN trades from several strategies
- WHEN the report is read
- THEN each strategy's bands contain only its own trades

### Requirement: Each strategy keeps its own book
Replay MUST hold each strategy's positions in a separate ledger, so two strategies holding the
same name never share an average cost.

#### Scenario: Two strategies in one name
- GIVEN two strategies buying the same name at different prices
- WHEN both positions close
- THEN each trade's profit is measured from its own entry price

### Requirement: Instruments carry their sector
Replay MUST supply each instrument's sector when one is known, and MUST report when none is.

#### Scenario: Sector-aware strategies can place a name
- GIVEN a symbol whose sector is known from the universe or the bundled list
- WHEN a strategy evaluates it during replay
- THEN the instrument it receives carries that sector

### Requirement: Parallel replay gives the same answer
Replay MAY split symbols across processes, and MUST produce the same verdict counts and trades
as a single-process run.

#### Scenario: Two workers, same trades
- GIVEN the same configuration and data
- WHEN replayed with one worker and with two
- THEN every strategy's verdict count and trades are identical
