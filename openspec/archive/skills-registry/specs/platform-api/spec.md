# platform-api

## ADDED Requirements

### Requirement: Registered skills are listable
`GET /skills` MUST return the registered skill manifests and any load failures.

#### Scenario: Skills listed with their contracts
- GIVEN the registry has loaded the seed skills
- WHEN `GET /skills` is requested
- THEN each skill is returned with its name, version, summary and input schema

#### Scenario: Load failures surfaced
- GIVEN a skill module that failed to import
- WHEN `GET /skills` is requested
- THEN that failure appears in the response
- AND a capability that vanished is distinguishable from one never written

#### Scenario: Handlers are not exposed
- GIVEN the registered skills
- WHEN `GET /skills` is requested
- THEN no handler reference or import path appears in the response
