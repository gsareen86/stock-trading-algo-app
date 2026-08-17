# data-persistence

## ADDED Requirements

### Requirement: Credentials and revocable tokens are stored in the platform schema
The platform MUST store users and refresh-token records in its own schema with row-level
security enabled, and MUST store a token's identifier rather than the token itself.

#### Scenario: Token rows cannot reconstruct a credential
- GIVEN a stored refresh-token record
- WHEN it is read
- THEN it contains an identifier and expiry, not a usable token

#### Scenario: New tables follow the platform's security posture
- GIVEN the authentication tables
- WHEN the migration is inspected
- THEN row-level security is enabled with a policy in the same migration
