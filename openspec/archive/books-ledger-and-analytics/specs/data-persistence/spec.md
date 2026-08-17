# data-persistence

## ADDED Requirements

### Requirement: Platform tables never share a name with a legacy table
Every table this platform creates MUST have a name distinct from the predecessor's tables.

#### Scenario: No platform table collides
- GIVEN the platform's declared tables
- WHEN their names are compared with the legacy inventory
- THEN no name appears in both

#### Scenario: Populated legacy tables survive a migration
- GIVEN legacy tables holding rows
- WHEN migrations are run to head
- THEN those tables and their rows are unchanged
