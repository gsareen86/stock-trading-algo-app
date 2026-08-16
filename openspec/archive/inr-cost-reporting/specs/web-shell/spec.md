# web-shell

## MODIFIED Requirements

### Requirement: Engine surfaces cost without an external service
The Engine surface MUST render LLM spend and usage from the platform's own records, so cost
is visible with no Langfuse account configured. Monetary figures MUST be rendered in rupees,
and a real spend MUST NOT be rounded to a displayed zero.

#### Scenario: Usage rendered with observability unconfigured
- GIVEN no Langfuse credentials are present
- AND calls have been recorded
- WHEN `/engine` is visited
- THEN spend, token counts and recent calls are displayed

#### Scenario: Amounts shown in rupees
- GIVEN recorded paid calls
- WHEN `/engine` is visited
- THEN monetary figures are rendered with the rupee sign

#### Scenario: Sub-paisa spend is not shown as zero
- GIVEN a recorded spend smaller than one paisa but greater than zero
- WHEN `/engine` is visited
- THEN it is rendered as being below one paisa rather than as `₹0.00`

#### Scenario: Budget shown when configured
- GIVEN a daily budget is configured
- WHEN `/engine` is visited
- THEN today's spend is shown against the cap

#### Scenario: No calls yet
- GIVEN no calls have been recorded
- WHEN `/engine` is visited
- THEN it renders an explicit empty state rather than fabricated figures
