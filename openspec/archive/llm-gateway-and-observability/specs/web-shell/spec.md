# web-shell

## MODIFIED Requirements

### Requirement: Six surfaces organised by intent
The web application MUST expose exactly six top-level surfaces — Today, Ideas, Positions,
Stock, Performance and Engine — each reachable from persistent navigation.

#### Scenario: Every surface is routable
- GIVEN the web application is running
- WHEN each of `/`, `/ideas`, `/positions`, `/stock`, `/performance`, `/engine` is visited
- THEN the page renders without error
- AND the navigation marks the visited surface as active

#### Scenario: Placeholder content is labelled as such
- GIVEN a surface whose real content lands in a later change
- WHEN it is visited
- THEN it renders a labelled placeholder naming the change that will fill it
- AND it does not display fabricated trading data

#### Scenario: Engine shows LLM usage
- GIVEN the backend is reachable
- WHEN `/engine` is visited
- THEN it renders recorded LLM spend, token usage and recent calls
- AND it is no longer a placeholder

## ADDED Requirements

### Requirement: Engine surfaces cost without an external service
The Engine surface MUST render LLM spend and usage from the platform's own records, so cost
is visible with no Langfuse account configured.

#### Scenario: Usage rendered with observability unconfigured
- GIVEN no Langfuse credentials are present
- AND calls have been recorded
- WHEN `/engine` is visited
- THEN spend, token counts and recent calls are displayed

#### Scenario: Budget shown when configured
- GIVEN a daily budget is configured
- WHEN `/engine` is visited
- THEN today's spend is shown against the cap

#### Scenario: No calls yet
- GIVEN no calls have been recorded
- WHEN `/engine` is visited
- THEN it renders an explicit empty state rather than fabricated figures

#### Scenario: Backend unreachable
- GIVEN the backend is not running
- WHEN `/engine` is visited
- THEN the page still renders
- AND it displays an explicit connection-failure state
