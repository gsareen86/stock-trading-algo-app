# web-shell

## ADDED Requirements

### Requirement: Every surface indicates that it is loading
Each surface MUST render an immediate placeholder while its data is in flight, and that
placeholder MUST resemble the shape of the content that will replace it.

#### Scenario: Navigation shows a placeholder immediately
- GIVEN any surface
- WHEN it is navigated to
- THEN a placeholder renders before the backend has answered

#### Scenario: The placeholder is not an empty state
- GIVEN a surface loading its data
- WHEN the placeholder is shown
- THEN it is distinguishable from the surface's own "nothing found" rendering

#### Scenario: A failed load replaces the placeholder with the failure
- GIVEN a surface whose data cannot be fetched
- WHEN the request fails
- THEN the placeholder is replaced by the unavailable rendering, not by an empty one

### Requirement: A control that submits reports that it is working
Any control that triggers work MUST become visibly pending until that work resolves, and MUST
NOT accept a second submission while pending.

#### Scenario: A search submission is pending until answered
- GIVEN a symbol search form
- WHEN it is submitted
- THEN the control reports that it is working until results arrive

#### Scenario: A pending control refuses a second submission
- GIVEN a control already pending
- WHEN it is activated again
- THEN no second request is sent

### Requirement: Cycle progress is reported as named steps
While a cycle runs, the surface MUST show which of the cycle's steps have completed.

#### Scenario: Completed steps appear as they finish
- GIVEN a cycle running from the Today surface
- WHEN a step completes
- THEN that step is shown as complete while the run continues

#### Scenario: A long-running step shows elapsed time
- GIVEN a step that has been running beyond a short threshold
- WHEN progress is rendered
- THEN the time elapsed on that step is shown

### Requirement: Completion is shown as a fraction of counted work
The surface MUST display progress as a percentage of work units completed against a declared
denominator, MUST show the counts that percentage is derived from, and MUST NOT present it as
a proportion of time or display an estimated time remaining.

#### Scenario: The percentage is accompanied by its counts
- GIVEN a cycle evaluating instruments
- WHEN progress is rendered
- THEN the percentage is shown alongside the units counted, such as instruments evaluated of
  instruments eligible

#### Scenario: Progress is indeterminate until the denominator is known
- GIVEN a cycle that has not yet finished screening
- WHEN progress is rendered
- THEN it is shown as indeterminate
- AND no percentage figure is displayed

#### Scenario: The denominator is adopted once reported
- GIVEN a cycle whose screen has reported the eligible count
- WHEN progress is next rendered
- THEN a percentage against that count is displayed

#### Scenario: A revised denominator does not move the bar backwards
- GIVEN a displayed percentage against one phase's denominator
- WHEN a later phase reports its own smaller denominator
- THEN the displayed percentage does not decrease

#### Scenario: No time remaining is claimed
- GIVEN a cycle in progress
- WHEN its progress is rendered
- THEN no estimated completion time and no estimated remaining duration is shown

#### Scenario: A completed cycle reads as complete
- GIVEN a cycle that has emitted its terminal event
- WHEN progress is rendered
- THEN it reads as complete rather than stopping short of the full bar

#### Scenario: A dropped stream is reported, not left hanging
- GIVEN a progress stream that closes without a terminal event
- WHEN the client observes the close
- THEN the run is reported as failed
- AND the last completed step is not left displayed as if still in progress
