# platform-configuration

## ADDED Requirements

### Requirement: Each external data provider is configured independently
Every external data provider MUST have its own settings, and the absence of one provider's
configuration MUST disable only the capability that provider serves.

#### Scenario: An absent financials key disables only financials
- GIVEN no financials API key is configured
- WHEN the platform starts
- THEN it starts normally
- AND price history, screening, strategies and verdicts are unaffected

#### Scenario: Provider configuration is reported by the health endpoint
- GIVEN the set of configured data providers
- WHEN health is requested
- THEN each provider is reported as configured or not, with the setting that would configure it

#### Scenario: No data provider credential is ever returned
- GIVEN configured provider credentials
- WHEN health or any other endpoint is called
- THEN no credential value appears in any response

### Requirement: Provider request rates and cache lifetimes are configurable and bounded
The request rate for each external provider and the cache lifetime for each data class MUST be
settings with documented bounds, not constants in call sites.

#### Scenario: Rate limits are settings
- GIVEN the configuration inventory
- WHEN external provider request rates are looked for
- THEN each is a documented setting with a bound

#### Scenario: Financial cache lifetime is measured in days
- GIVEN the financials cache lifetime setting
- WHEN its default is read
- THEN it is expressed in days

#### Scenario: A rate outside its bound fails at construction
- GIVEN a configured rate outside its documented bound
- WHEN settings are constructed
- THEN construction fails with the offending setting named
