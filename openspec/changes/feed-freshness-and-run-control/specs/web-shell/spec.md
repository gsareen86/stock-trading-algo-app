# web-shell

## ADDED Requirements

### Requirement: A cycle can be started from the application
The Today surface MUST offer a control that runs a cycle, and MUST report the run's outcome
without requiring a manual page reload to see it.

#### Scenario: Running a cycle refreshes the feed
- GIVEN the Today surface
- WHEN the run control is used and the cycle completes
- THEN the feed shows what the cycle wrote

#### Scenario: A failed run is reported as a failure
- GIVEN a backend that cannot run a cycle
- WHEN the run control is used
- THEN the failure and its reason are shown
- AND the existing feed stays on screen rather than being replaced by an empty state

#### Scenario: The control cannot be triggered twice concurrently
- GIVEN a cycle already running from this surface
- WHEN the run control is used again
- THEN the second request is not sent

### Requirement: The seam report reports the feed's own state
The seam report MUST report whether the feed could be read and how much of it is unread, and
MUST NOT display a fixed message about the feed's contents.

#### Scenario: A populated feed is reported as such
- GIVEN a feed containing insights
- WHEN the seam report is opened
- THEN it reports how many are shown and how many are unread

#### Scenario: An unreadable feed is a broken seam
- GIVEN a backend that cannot serve insights
- WHEN the seam report is opened
- THEN the feed row reports the failure, not an empty count

## MODIFIED Requirements

### Requirement: The shell proves the backend seam
The shell MUST report the state of every external seam the backend declares, and MUST
distinguish a seam that is **failing** from one that is **switched off by configuration**.

#### Scenario: A missing credential for an unused service is not a fault
- GIVEN no Langfuse credential is configured
- WHEN the seam report is opened
- THEN observability reports that tracing is off by configuration
- AND it is not rendered with the same severity as a failing seam

#### Scenario: A failing seam is reported as failing
- GIVEN a database that cannot be reached
- WHEN the seam report is opened
- THEN it is rendered as down

#### Scenario: A default model whose provider is unconfigured is degraded
- GIVEN a default model whose provider has no credential and no route
- WHEN the seam report is opened
- THEN the default model row is degraded and names the provider

#### Scenario: An unreachable backend is distinguished from a degraded one
- GIVEN a backend that cannot be reached at all
- WHEN Today is opened
- THEN the attempted URL and the transport error are shown
- AND no seam is reported as healthy
