# platform-configuration

## ADDED Requirements

### Requirement: Money is reported in rupees at a configured rate
The platform MUST report monetary amounts to the operator in INR, and MUST obtain the
USD→INR rate from configuration rather than a network call. The rate MUST be positive.

#### Scenario: Default rate available with no configuration
- GIVEN `USD_INR_RATE` is not set
- WHEN settings are loaded
- THEN a positive default rate is in effect
- AND no network request is made to obtain it

#### Scenario: Operator overrides the rate
- GIVEN `USD_INR_RATE=90.5`
- WHEN a dollar amount is converted for reporting
- THEN it is converted at 90.5

#### Scenario: Non-positive rate rejected
- GIVEN `USD_INR_RATE=0`
- WHEN settings are loaded
- THEN loading fails with a validation error

### Requirement: A retired configuration key fails loudly
When a configuration key is renamed such that its old value would be misread under the new
meaning, the platform MUST reject the retired key at startup and name its replacement, rather
than ignoring it or reinterpreting its value.

#### Scenario: Retired budget key rejected
- GIVEN `LLM_DAILY_BUDGET_USD=5.00` is set
- WHEN settings are loaded
- THEN loading fails with an error naming `LLM_DAILY_BUDGET_INR`
- AND the value is not reinterpreted as rupees

## MODIFIED Requirements

### Requirement: Typed settings with validation
Configuration MUST be a typed settings object validated at load time, so an invalid value
fails at startup rather than at the moment it is first used. Monetary settings MUST be
denominated in INR and named accordingly.

#### Scenario: Invalid value rejected at startup
- GIVEN a setting whose value violates its declared constraint
- WHEN the application starts
- THEN startup fails with an error naming the setting

#### Scenario: Spend cap is expressed in rupees
- GIVEN `LLM_DAILY_BUDGET_INR=500`
- WHEN settings are loaded
- THEN the daily cap is five hundred rupees
- AND the equivalent cap in the provider's billing currency is derived from the configured rate

#### Scenario: Unset cap means unlimited
- GIVEN `LLM_DAILY_BUDGET_INR` is not set
- WHEN settings are loaded
- THEN no daily cap is in effect
