# platform-api

## REMOVED Requirements

### Requirement: Registered skills are listable
Replaced by "Registered tools are listable" — the endpoint and its vocabulary are renamed;
the behaviour is unchanged.

## ADDED Requirements

### Requirement: Registered tools are listable
`GET /tools` MUST return the registered tool manifests and any load failures.

#### Scenario: Tools listed with their contracts
- GIVEN the registry has loaded the seed tools
- WHEN `GET /tools` is requested
- THEN each tool is returned with its name, version, summary and input schema

#### Scenario: Load failures surfaced
- GIVEN a tool module that failed to import
- WHEN `GET /tools` is requested
- THEN that failure appears in the response
- AND a capability that vanished is distinguishable from one never written

#### Scenario: Handlers are not exposed
- GIVEN the registered tools
- WHEN `GET /tools` is requested
- THEN no handler reference or import path appears in the response
