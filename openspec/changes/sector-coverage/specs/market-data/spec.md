# market-data

## MODIFIED Requirements

### Requirement: Sector membership maps to a sector index
The system MUST map an instrument to an NSE sector index from a data file rather than code,
first by a per-symbol override when one is listed, otherwise by its industry description.

#### Scenario: Known industry maps to its index
- GIVEN an instrument whose industry is a financial-services description
- WHEN its sector index is resolved
- THEN the financial services index is returned

#### Scenario: NSE's Commodities industries map to the commodities index
- GIVEN an instrument whose industry is Chemicals or Forest Materials
- WHEN its sector index is resolved
- THEN the NIFTY COMMODITIES index is returned

#### Scenario: A listed override takes precedence
- GIVEN a symbol listed in the overrides with a sector and a reason
- WHEN its sector index is resolved
- THEN the override's index is returned whatever its industry says

#### Scenario: A short term never matches inside a longer word
- GIVEN the industry description "Utilities"
- WHEN its sector index is resolved
- THEN the energy index is returned, not the IT index

#### Scenario: Unknown industry resolves to nothing
- GIVEN an instrument with an unrecognised industry, or a conglomerate
- WHEN its sector index is resolved
- THEN no index is returned rather than a wrong one

#### Scenario: Mapping is data
- GIVEN the sector mapping file
- WHEN an industry or override is added to it
- THEN no code change is needed for it to take effect

## ADDED Requirements

### Requirement: Sector indices can be verified against provider history
The system MUST provide a command that fetches every configured sector index's history and
fails when any index returns too little to measure relative strength.

#### Scenario: An index without history fails the check
- GIVEN a configured index for which the provider returns no bars
- WHEN the verification runs
- THEN that index is reported unusable and the command exits non-zero
