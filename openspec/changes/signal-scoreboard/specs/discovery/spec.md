# discovery

## ADDED Requirements

### Requirement: Published verdicts are measured forward
The system MUST measure, for each verdict in a completed scan, the return from the first
tradable session open after that scan to the close of the Nth session, for each requested
holding period.

#### Scenario: A scan after the open enters at the next session
- GIVEN a scan that finished after 09:15 IST on a trading day
- WHEN its verdicts are measured
- THEN entry is the open of the next trading session

#### Scenario: A scan before the open enters the same day
- GIVEN a scan that finished before 09:15 IST
- WHEN its verdicts are measured
- THEN entry is the open of that day's session, or the next session when the day is not one

#### Scenario: A holding period that has not elapsed is pending
- GIVEN a verdict whose Nth session has not yet closed
- WHEN it is measured
- THEN that holding period is reported pending and contributes to no statistic

#### Scenario: A name with no price history is unpriced
- GIVEN a verdict on a name for which no price history is returned
- WHEN it is measured
- THEN it is reported unpriced, not as a loss and not as zero

### Requirement: Returns are compared with the scan's benchmark
The system MUST report each measured return's excess over the benchmark the scan named, over
the same sessions.

#### Scenario: Excess uses identical sessions
- GIVEN a measured return from session A's open to session B's close
- WHEN excess is computed
- THEN the benchmark's return from session A's open to session B's close is subtracted

#### Scenario: A missing benchmark bar leaves excess absent
- GIVEN a benchmark with no bar on the entry or exit session
- WHEN excess is computed
- THEN excess is absent for that holding period while the raw return is still reported

### Requirement: A plan's stop is checked inside each window
The system MUST report whether a verdict's plan stop was traded through within each measured
holding period, and MUST report nothing when the verdict carried no stop.

#### Scenario: A low through the stop is reported
- GIVEN a BUY with a plan stop and a session low at or below it within the window
- WHEN the window is measured
- THEN the stop is reported touched

#### Scenario: No plan, no reading
- GIVEN a verdict without a plan stop
- WHEN it is measured
- THEN the stop reading is absent rather than false

### Requirement: Only a changed stance is a new signal by default
The system MUST, by default, count a verdict only when its strategy's stance on that name
differs from the immediately preceding completed scan, and MAY count every scan's verdict when
asked, saying that the windows overlap.

#### Scenario: A repeated BUY is not counted twice
- GIVEN a strategy rating a name BUY in two consecutive completed scans
- WHEN the scoreboard counts new signals
- THEN only the first scan's verdict is counted

#### Scenario: A name returning after an absence is new
- GIVEN a name absent from one completed scan and rated BUY in the next
- WHEN the scoreboard counts new signals
- THEN that BUY is counted

### Requirement: Results are never pooled across strategies
The system MUST summarise outcomes per strategy, per stance and per conviction band within that
stance, and MUST NOT compute any figure from more than one strategy's verdicts.

#### Scenario: Two strategies' BUYs stay apart
- GIVEN BUY verdicts from two different strategies
- WHEN the scoreboard is summarised
- THEN each appears only in its own strategy's rows

#### Scenario: Strategies are not ordered by results
- GIVEN several strategies with different results
- WHEN the scoreboard is returned
- THEN strategies appear in alphabetical order

### Requirement: Thin evidence is labelled
The system MUST report, for each bucket and holding period, the number of measured signals and
the standard error of the mean excess, and MUST flag a bucket with fewer than 30 measured
signals as thin.

#### Scenario: A small bucket is flagged
- GIVEN a bucket with one measured signal
- WHEN it is summarised
- THEN it is flagged thin and its standard error is absent

### Requirement: The scoreboard carries its biases
The system MUST attach to every scoreboard result its method, its known biases and that charges
are not included.

#### Scenario: Gross figures say so
- GIVEN any scoreboard result
- WHEN it is returned
- THEN it states charges are not included and lists the biases

#### Scenario: No completed scan yet
- GIVEN no completed scan exists
- WHEN the scoreboard is requested
- THEN it returns no strategies and a note saying a scan must run first
