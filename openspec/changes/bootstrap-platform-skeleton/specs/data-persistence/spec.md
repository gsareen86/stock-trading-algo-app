# data-persistence

## ADDED Requirements

### Requirement: Schema is migration-owned
The system MUST define its schema through Alembic migrations, and MUST NOT create or alter
tables at application startup.

#### Scenario: Clean database migrates to head
- GIVEN an empty SQLite database
- WHEN `alembic upgrade head` runs
- THEN the `insights` and `verdicts` tables exist
- AND the recorded Alembic revision matches head

#### Scenario: Startup does not mutate schema
- GIVEN a database at a revision older than head
- WHEN the FastAPI application starts
- THEN no table is created or altered
- AND `GET /health` reports the database as out of date

### Requirement: One schema definition across dialects
The system MUST use the same SQLAlchemy model definitions for SQLite and PostgreSQL.

#### Scenario: Same models on both dialects
- GIVEN the models defined in `app/persistence/models.py`
- WHEN migrations run against SQLite and against PostgreSQL
- THEN both produce the same logical tables and columns
- AND no dialect-specific model definition exists

### Requirement: Legacy tables are dropped only when verifiably empty
The first migration MUST drop the 30 named legacy tables, and MUST abort without dropping
anything if any of them contains rows.

#### Scenario: All legacy tables empty
- GIVEN all 30 named legacy tables exist and contain 0 rows
- WHEN the first migration runs
- THEN all 30 are dropped
- AND the new tables are created

#### Scenario: A legacy table has data
- GIVEN one of the 30 named legacy tables contains at least one row
- WHEN the first migration runs
- THEN the migration raises an error naming that table
- AND the transaction is rolled back so no table is dropped

#### Scenario: Unlisted tables are never touched
- GIVEN a table exists that is not on the hard-coded legacy list
- WHEN the first migration runs
- THEN that table still exists afterwards

#### Scenario: Legacy tables already absent
- GIVEN a fresh database where none of the 30 legacy tables exist
- WHEN the first migration runs
- THEN the migration completes successfully
- AND the new tables are created

### Requirement: Row Level Security enabled with policies in the same migration
Every table the system creates on PostgreSQL MUST have RLS enabled, and MUST have its
access policies created in the same migration that creates the table.

#### Scenario: New table is RLS-protected on creation
- GIVEN the first migration runs against PostgreSQL
- WHEN it creates the `insights` table
- THEN RLS is enabled on `insights`
- AND a `service_role` full-access policy exists on `insights`

#### Scenario: Anonymous access is denied
- GIVEN the migration has been applied to PostgreSQL
- WHEN a client holding only the anon key queries `insights`
- THEN no rows are returned and no rows can be written

#### Scenario: RLS statements skipped on SQLite
- GIVEN the target database is SQLite, which has no RLS
- WHEN the first migration runs
- THEN the RLS statements are skipped
- AND the migration completes successfully

### Requirement: Backend connects with a server-side credential
The system MUST access the database using a server-side credential, and MUST NOT expose
database credentials to the browser.

#### Scenario: Browser never holds a database credential
- GIVEN the web application is served to a browser
- WHEN its client-side bundle is inspected
- THEN it contains no database connection string, service-role key, or anon key
- AND all data reaches it through the backend API
