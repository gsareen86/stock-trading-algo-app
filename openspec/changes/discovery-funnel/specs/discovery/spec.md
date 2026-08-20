# discovery

Answering "what is worth looking at", as distinct from "is this eligible" (`screening`) and
"what does this strategy think" (`decision-model`).

Introduced by `discovery-funnel`.

## ADDED Requirements

### Requirement: Sectors are placed by relative strength and its direction
The system MUST place each sector index into one of leading, weakening, lagging or improving,
from its relative strength against the broad-market benchmark and the direction that relative
strength is moving.

#### Scenario: A strong and strengthening sector leads
- GIVEN a sector outperforming the benchmark with rising relative strength
- WHEN sectors are placed
- THEN it is placed as leading

#### Scenario: A strong but rolling-over sector is weakening
- GIVEN a sector outperforming the benchmark with falling relative strength
- WHEN sectors are placed
- THEN it is placed as weakening, not leading

#### Scenario: A weak but turning sector is improving
- GIVEN a sector underperforming the benchmark with rising relative strength
- WHEN sectors are placed
- THEN it is placed as improving, not lagging

#### Scenario: Every placement publishes its measurements
- GIVEN a placed sector
- WHEN it is read
- THEN its relative strength, the change in that strength, the window measured and the
  benchmark compared against are all present

#### Scenario: A sector without sufficient history is unplaced
- GIVEN a sector index with too little history to measure a change in relative strength
- WHEN sectors are placed
- THEN it is reported as unplaced with that reason, not defaulted into a quadrant

#### Scenario: Placement is not a recommendation
- GIVEN a set of placed sectors
- WHEN they are read
- THEN no sector carries a stance, a conviction or a suggested action

### Requirement: Notable movement within a sector is measured, not ranked by merit
The system MUST report constituents of a sector whose price or volume behaviour crossed a
declared threshold, each with the measurement and threshold that selected it.

#### Scenario: A mover carries what made it one
- GIVEN a constituent reported as a mover
- WHEN it is read
- THEN the measurement, its threshold and the window are present

#### Scenario: Thresholds are declared, not relative to the peer set
- GIVEN a sector in which nothing crossed a threshold
- WHEN movers are requested
- THEN none are returned rather than the least-bad ones

#### Scenario: A mover is not a verdict
- GIVEN a constituent reported as a mover
- WHEN it is read
- THEN it carries no stance and no conviction

### Requirement: A scan evaluates the eligible universe and is recorded as one dated run
The system MUST be able to evaluate every eligible instrument in the universe with every
strategy, and MUST persist the result as a single run identified by when it was taken.

#### Scenario: A run is retrievable whole
- GIVEN a completed scan
- WHEN it is requested by its identifier
- THEN every verdict it produced is returned with the run's own timestamp

#### Scenario: Universe provenance is recorded on the run
- GIVEN a scan over a universe obtained from the fallback list
- WHEN the run is read
- THEN it records that the universe was the fallback, not the live index

#### Scenario: Names that could not be evaluated are recorded
- GIVEN instruments whose price history could not be fetched during a scan
- WHEN the run is read
- THEN they are listed with the reason, rather than being silently absent

#### Scenario: A later run does not overwrite an earlier one
- GIVEN a completed scan
- WHEN a second scan runs
- THEN both runs remain retrievable

#### Scenario: A scan is reproducible without a model
- GIVEN a scan run with narration disabled
- WHEN it is re-run against the same price data
- THEN it produces the same verdicts in the same order

### Requirement: A scan is ordered by a single named strategy's conviction
A scan's ordering MUST be by each instrument's highest conviction from one strategy, MUST name
that strategy alongside the figure, and MUST NOT compute any value across strategies.

#### Scenario: The ordering figure names its strategy
- GIVEN a ranked scan result
- WHEN an entry is read
- THEN the conviction it is ranked by is attributed to exactly one named strategy

#### Scenario: Every strategy's verdict remains visible
- GIVEN a ranked entry
- WHEN it is read
- THEN all four verdicts are present, not only the ranking one

#### Scenario: No cross-strategy value is computed
- GIVEN the discovery module
- WHEN it is searched for an average, sum, count or weighting over verdicts used to order them
- THEN none exists

#### Scenario: Agreement filters without scoring
- GIVEN a scan filtered to entries where at least three strategies say BUY
- WHEN the result is read
- THEN entries are selected by that count
- AND their ordering is still by a single named strategy's conviction

#### Scenario: Ties keep universe order
- GIVEN two entries with equal ranking conviction
- WHEN they are ordered
- THEN their relative order is their universe order

### Requirement: Business quality is a facet, never a universe-wide gate
The system MUST attach a business-quality assessment to scanned instruments as declared,
individually visible measurements, and MUST NOT exclude an instrument from evaluation on the
basis of it.

#### Scenario: Every strategy sees every eligible name
- GIVEN an eligible instrument failing every business-quality measure
- WHEN a scan runs
- THEN all four strategies still evaluate it

#### Scenario: Quality measures are individually visible
- GIVEN an instrument with a quality assessment
- WHEN it is read
- THEN each measure appears with its own value and threshold

#### Scenario: Quality is not summed into one number
- GIVEN a quality assessment
- WHEN it is read
- THEN no single composite quality score is present

#### Scenario: Quality thresholds are sector-aware
- GIVEN a banking instrument and a manufacturing instrument
- WHEN a leverage measure is applied
- THEN the threshold applied reflects the sector, or the measure is reported as not applicable

#### Scenario: Missing financial data is not a failed measure
- GIVEN an instrument whose financials are unavailable
- WHEN quality is assessed
- THEN each affected measure is reported as unavailable rather than as failed

#### Scenario: Filtering by quality is the reader's choice
- GIVEN a scan result
- WHEN it is requested filtered to instruments meeting a quality measure
- THEN only those are returned
- AND the unfiltered result remains available

### Requirement: A scan runs on demand and on a schedule
The system MUST support running a scan on request and on a recurring schedule, and MUST record
which of the two produced a run.

#### Scenario: A run records how it was triggered
- GIVEN a completed scan
- WHEN it is read
- THEN it records whether it was requested or scheduled

#### Scenario: A scheduled run does not displace an on-demand one
- GIVEN an on-demand scan already running
- WHEN a scheduled scan is due
- THEN the scheduled run does not start concurrently

#### Scenario: A failed scan is recorded as failed
- GIVEN a scan that cannot complete
- WHEN it ends
- THEN the run is retrievable and marked failed with its reason
- AND the previous successful run remains the latest successful one
