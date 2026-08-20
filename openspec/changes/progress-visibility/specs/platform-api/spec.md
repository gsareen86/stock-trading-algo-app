# platform-api

## ADDED Requirements

### Requirement: A cycle can be run with progress streamed
The API MUST offer a streaming form of the cycle run that emits one event per graph node as
that node completes, followed by a terminal event carrying the same body the non-streaming
form returns.

#### Scenario: Each completed node emits an event
- GIVEN a cycle running with progress streamed
- WHEN a graph node completes
- THEN an event naming that node and its completion time is emitted

#### Scenario: The terminal event carries the full result
- GIVEN a cycle running with progress streamed
- WHEN the cycle completes
- THEN a terminal event carries the same payload the non-streaming endpoint returns

#### Scenario: A failed cycle terminates the stream with the failure
- GIVEN a cycle that fails partway
- WHEN the failure occurs
- THEN a terminal event carrying the failure is emitted
- AND the stream closes

#### Scenario: The non-streaming form is unchanged
- GIVEN a caller that does not ask for progress
- WHEN a cycle is run
- THEN the existing endpoint behaves exactly as before

#### Scenario: Progress events carry no model output
- GIVEN a cycle whose narration step completes
- WHEN its progress event is emitted
- THEN the event names the step and carries no prompt or generated text

### Requirement: Progress events carry counted work, not a computed percentage
A phase with countable work MUST emit its completed and total unit counts, and the stream MUST
NOT emit a percentage — the denominator is reported and the fraction is derived by the reader.

#### Scenario: A counting phase reports both numbers
- GIVEN a phase evaluating a known number of instruments
- WHEN it emits progress
- THEN the event carries units completed and units total, and names the unit

#### Scenario: A phase whose total is not yet known reports no total
- GIVEN a phase running before its denominator has been established
- WHEN it emits progress
- THEN the total is absent rather than estimated

#### Scenario: A phase with no countable work emits step completion only
- GIVEN the regime step
- WHEN it completes
- THEN it emits its completion with no unit counts

#### Scenario: No percentage crosses the wire
- GIVEN any progress event
- WHEN it is read
- THEN it carries counts and contains no percentage field

### Requirement: Streamed responses are not buffered by the web proxy
The web application's backend proxy MUST forward a streamed response as it arrives, without
buffering it to completion first.

#### Scenario: Events reach the browser before the run finishes
- GIVEN a cycle streaming progress through the proxy
- WHEN an early node completes
- THEN its event is readable by the browser before the cycle ends

#### Scenario: Authentication still applies to a streamed route
- GIVEN an unauthenticated caller
- WHEN the streaming route is requested
- THEN the request is refused before any event is emitted
