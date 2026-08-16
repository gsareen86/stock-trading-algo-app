# llm-gateway

## MODIFIED Requirements

### Requirement: A daily spend cap stops paid calls
The gateway MUST refuse calls to paid providers once recorded spend for the current IST day
reaches the configured cap. The cap MUST be configured in INR and compared against recorded
spend converted at the configured rate.

#### Scenario: Cap reached
- GIVEN `LLM_DAILY_BUDGET_INR=88.00` and a rate of 88 rupees to the dollar
- AND recorded spend for today is at least one dollar
- WHEN a task routed to a paid provider invokes `complete`
- THEN it returns `None` without issuing a network request
- AND the attempt is recorded with status `budget_exceeded`

#### Scenario: Local providers are exempt
- GIVEN the daily cap has been reached
- WHEN a task routed to a local provider invokes `complete`
- THEN the request is issued normally

#### Scenario: Cap unset means unlimited
- GIVEN `LLM_DAILY_BUDGET_INR` is not configured
- WHEN any task invokes `complete`
- THEN no budget check blocks the call

#### Scenario: Paid rungs are skipped but local rungs still run
- GIVEN the daily cap has been reached
- AND a task's chain is a paid primary followed by a local fallback
- WHEN `complete` is invoked
- THEN the paid rung is skipped
- AND the local fallback serves the request

## ADDED Requirements

### Requirement: The call ledger stores the provider's billing currency
Recorded call cost MUST be stored in the currency the provider bills in, unconverted, so a
row reconciles against a provider invoice. Conversion to INR MUST happen when the ledger is
read for reporting, never when it is written.

#### Scenario: Stored cost is unconverted
- GIVEN a paid call the provider prices at some dollar amount
- WHEN the call is recorded
- THEN the stored cost is that dollar amount
- AND no exchange rate has been applied to it

#### Scenario: A rate change does not rewrite history
- GIVEN recorded calls and a configured rate
- WHEN the configured rate is changed
- THEN no stored row is modified
