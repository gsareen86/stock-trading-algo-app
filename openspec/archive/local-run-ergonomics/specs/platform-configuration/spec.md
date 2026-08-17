# platform-configuration

## ADDED Requirements

### Requirement: Local model latency is configured separately
The platform MUST expose a separate timeout setting for local providers, so tuning for hosted
latency cannot make local providers unusable.

#### Scenario: Local timeout defaults higher than the hosted one
- GIVEN no timeout settings are configured
- WHEN settings are loaded
- THEN the local timeout is greater than the hosted timeout

#### Scenario: Non-positive timeout rejected
- GIVEN `LLM_LOCAL_TIMEOUT_SECONDS=0`
- WHEN settings are loaded
- THEN loading fails with a validation error
