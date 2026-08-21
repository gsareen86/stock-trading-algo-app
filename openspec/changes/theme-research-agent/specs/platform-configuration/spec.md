# platform-configuration

## ADDED Requirements

### Requirement: The search provider is configured and metered like every other
The search provider MUST have its own credential setting and its own request allowance, and its
absence MUST disable only search.

#### Scenario: No search key leaves everything else working
- GIVEN no search provider credential is configured
- WHEN the platform starts
- THEN it starts normally
- AND themes, chains, name matching, screening and every strategy are unaffected

#### Scenario: The allowance is a bounded setting
- GIVEN the configuration inventory
- WHEN the search request allowance is looked for
- THEN it is a documented setting with a bound

#### Scenario: Health reports whether search is configured
- GIVEN the set of configured providers
- WHEN health is requested
- THEN search is reported as configured or not, naming the setting that would configure it

#### Scenario: No search credential appears in any response
- GIVEN a configured search credential
- WHEN any endpoint is called
- THEN its value appears in no response

### Requirement: The research conversation routes to a model by task
The model used for research MUST be selected by the existing per-task routing, and MUST be
reportable without inspecting code.

#### Scenario: Research routes like any other task
- GIVEN a configured route for the research task
- WHEN a research request runs
- THEN it dispatches to that model

#### Scenario: An unrouted research task falls back to the default
- GIVEN no explicit research route
- WHEN a research request runs
- THEN it dispatches to the default model

#### Scenario: Research spend counts against the existing budget
- GIVEN a daily model budget
- WHEN research calls a paid model
- THEN that spend counts against the same budget as every other task
