# backtesting

## ADDED Requirements

### Requirement: A strategy under replay cannot see data after the decision date
Historical evaluation MUST supply price history truncated to the evaluation date, and that
truncation MUST happen at the data seam so strategies are unmodified and cannot bypass it.

#### Scenario: No bar after the as-of date is returned
- GIVEN a source holding history beyond the evaluation date
- WHEN history is requested for that date
- THEN no bar after it is present

#### Scenario: Truncation holds whatever lookback is requested
- GIVEN requests for short and long lookbacks
- WHEN each is served for the same evaluation date
- THEN neither contains a bar after that date

#### Scenario: The as-of session itself is included
- GIVEN an evaluation date that is a trading session
- WHEN history is requested
- THEN that session's bar is present

#### Scenario: A strategy's evidence contains no future measurement
- GIVEN a strategy evaluated at a past date against a source holding later bars
- WHEN its verdict is read
- THEN no evidence value reflects a bar after that date

### Requirement: Fills happen after the deciding bar
A simulated trade MUST execute at a session strictly after the one whose data produced the
decision.

#### Scenario: A signal fills at the next session's open
- GIVEN a decision formed from data up to a session's close
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
- GIVEN a market calendar
- WHEN a replay runs
- THEN it consults the calendar for each candidate day

#### Scenario: A window with no sessions is reported
- GIVEN a window in which the market never opens
- WHEN a replay runs
- THEN it completes and reports that there was nothing to replay

### Requirement: Replay uses the platform's own position ledger
Simulated positions MUST be derived by the same ledger the live platform uses, and the system
MUST NOT contain a separate position implementation for backtests.

#### Scenario: Backtest positions fold identically
- GIVEN a buy and a partial sell in a replay
- WHEN the position is read
- THEN quantity, average cost and realised profit match the live ledger's behaviour

#### Scenario: Ledger guards still apply
- GIVEN a sell larger than the simulated holding
- WHEN it is attempted
- THEN it is refused as it would be in the live book

### Requirement: Results are reported per strategy with no aggregate
Each strategy MUST receive its own result, and the report MUST NOT contain a combined
performance figure or curve across strategies.

#### Scenario: Every registered strategy is reported separately
- GIVEN a completed replay
- WHEN results are read
- THEN each registered strategy has its own entry

#### Scenario: No combined figure exists
- GIVEN a completed replay
- WHEN the report is inspected
- THEN it contains no aggregate equity curve or total across strategies

#### Scenario: Gate blocks are counted
- GIVEN a replay in which hard gates failed
- WHEN results are read
- THEN the count of blocked assessments is reported per strategy

### Requirement: Every report states what it could not account for
A replay result MUST carry the biases and omissions that apply to it, including survivorship,
absent charges and absent slippage.

#### Scenario: Biases accompany every result
- GIVEN any completed replay
- WHEN the report is read
- THEN survivorship, charges and slippage limitations are stated

#### Scenario: Approximations in the run itself are reported
- GIVEN a replay evaluating less often than every session
- WHEN the report is read
- THEN the effect of that spacing on holding periods is stated

### Requirement: Replay never reads the predecessor's data
Backtesting MUST NOT read, join to or import any table the platform did not create.

#### Scenario: No legacy table is referenced
- GIVEN the backtesting package
- WHEN its source is inspected
- THEN no legacy table name appears
