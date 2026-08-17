# platform-configuration

## ADDED Requirements

### Requirement: Token lifetimes are configurable and bounded
Access and refresh token lifetimes MUST be settings, and each MUST be bounded so a
misconfiguration cannot produce an effectively permanent credential.

#### Scenario: Lifetimes have defaults
- GIVEN no explicit configuration
- WHEN settings are loaded
- THEN an access lifetime shorter than the refresh lifetime is used

#### Scenario: An out-of-range lifetime is refused
- GIVEN a refresh lifetime beyond the permitted maximum
- WHEN settings are loaded
- THEN loading fails
