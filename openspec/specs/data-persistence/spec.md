# data-persistence

How the schema is defined, namespaced away from the predecessor's tables, and secured.

Introduced by `bootstrap-platform-skeleton` (see `openspec/archive/`).

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

### Requirement: The platform owns a dedicated namespace
The system MUST create its tables in a dedicated `trading` schema on PostgreSQL, so its
tables are distinguishable from the predecessor's by name alone.

#### Scenario: Tables created in the trading schema
- GIVEN the migration runs against PostgreSQL
- WHEN it completes
- THEN `trading.verdicts` and `trading.insights` exist
- AND no table is created in `public`

#### Scenario: Version table lives beside its tables
- GIVEN the migration runs against PostgreSQL
- WHEN it completes
- THEN the Alembic version table is in the `trading` schema, not `public`

#### Scenario: Namespace exists before Alembic writes its version table
- GIVEN a PostgreSQL database with no `trading` schema
- WHEN `alembic upgrade head` runs
- THEN the schema is created before the version table is written
- AND the migration completes without error

#### Scenario: Namespace collapses on SQLite
- GIVEN the target database is SQLite, which has no schemas
- WHEN the migration runs
- THEN the `trading` namespace is translated away
- AND the tables are created in the single available namespace

### Requirement: Migrations never modify the predecessor's data
The system's migrations MUST NOT drop, alter or write to any table it did not create.

#### Scenario: Populated legacy tables survive
- GIVEN the `public` schema holds the predecessor's 30 tables with data in them
- WHEN `alembic upgrade head` runs
- THEN every one of those tables still exists
- AND their row counts are unchanged

#### Scenario: Unrelated tables survive
- GIVEN a table exists that this platform did not create
- WHEN `alembic upgrade head` runs
- THEN that table and its rows are unchanged

#### Scenario: Downgrade removes only what the platform created
- GIVEN the migration has been applied
- WHEN `alembic downgrade base` runs
- THEN `verdicts` and `insights` are removed
- AND no legacy table is affected

### Requirement: Retiring legacy tables is guarded by an emptiness check
Any future removal of the predecessor's tables MUST verify each is empty first, and MUST
abort naming every non-empty table rather than dropping any.

#### Scenario: Guard rejects populated tables
- GIVEN legacy tables containing rows
- WHEN the emptiness guard runs
- THEN it raises an error naming each non-empty table with its row count
- AND no table is dropped

#### Scenario: Guard passes on empty tables
- GIVEN every present legacy table contains 0 rows
- WHEN the emptiness guard runs
- THEN it returns the list of tables safe to drop

#### Scenario: Guard ignores tables outside the inventory
- GIVEN a populated table that is not one of the 30 named legacy tables
- WHEN the emptiness guard runs
- THEN that table is not considered and does not cause an error

### Requirement: Row Level Security enabled with policies in the same migration
Every table the system creates on PostgreSQL MUST have RLS enabled, and MUST have its
access policies created in the same migration that creates the table.

#### Scenario: New table is RLS-protected on creation
- GIVEN the migration runs against PostgreSQL
- WHEN it creates the `insights` table
- THEN RLS is enabled on `trading.insights`
- AND a `service_role` full-access policy exists on it

#### Scenario: Anonymous roles are granted nothing
- GIVEN the migration has been applied to PostgreSQL
- WHEN the schema grants are inspected
- THEN neither `anon` nor `authenticated` holds any privilege on the `trading` schema

#### Scenario: RLS statements skipped on SQLite
- GIVEN the target database is SQLite, which has no RLS
- WHEN the migration runs
- THEN the RLS statements are skipped
- AND the migration completes successfully

#### Scenario: Migration introduces no new security advisory
- GIVEN the migration has been applied to the Supabase project
- WHEN the security advisors are read
- THEN no `rls_disabled` advisory names a table in the `trading` schema

### Requirement: Backend connects with a server-side credential
The system MUST access the database using a server-side credential, and MUST NOT expose
database credentials to the browser.

#### Scenario: Browser never holds a database credential
- GIVEN the web application is served to a browser
- WHEN its client-side bundle is inspected
- THEN it contains no database connection string, service-role key, or anon key
- AND all data reaches it through the backend API

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

### Requirement: Insights carry a dedupe key and a stored severity
The insights table MUST hold a deduplication key and the severity of the insight's kind, both
indexed for suppression lookups.

#### Scenario: Suppression lookup is indexed
- GIVEN the insights table
- WHEN it is inspected
- THEN a dedupe key and creation time are indexed together

#### Scenario: Severity is stored rather than derived at read time
- GIVEN a recorded insight
- WHEN it is read
- THEN its severity is present on the row
