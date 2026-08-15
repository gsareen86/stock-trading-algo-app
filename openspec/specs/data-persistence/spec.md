# Data Persistence

Status: baseline — not yet exercised through a change under `openspec/changes/`.

The dual-backend (SQLite/Postgres) database layer underlying every other capability.

## Requirements

### Requirement: Backend is selected by `DB_BACKEND`, defaulting to zero-config SQLite
The system MUST default to a local SQLite file (`db/trading_bot.db`) requiring no
configuration, and MUST switch to Postgres/Supabase only when `DB_BACKEND=postgres` and
`SUPABASE_DB_URL` are both set.

#### Scenario: DB_BACKEND set to postgres without a connection URL
- GIVEN `.env` sets `DB_BACKEND=postgres` but `SUPABASE_DB_URL` is left unset
- WHEN `db/models.py` is imported
- THEN it raises `RuntimeError("DB_BACKEND=postgres but SUPABASE_DB_URL is not set...")`
  immediately — this is a hard failure at import time, not a silent fallback to SQLite

### Requirement: Schema is defined twice, once per dialect, deliberately
The system MUST maintain two schema definitions in `db/models.py` — one using SQLite
syntax (`AUTOINCREMENT`), one using Postgres syntax (`SERIAL`/`BIGSERIAL`) — covering the
same ~29 tables. This duplication is intentional (the two dialects aren't
schema-compatible enough to share one definition) and MUST NOT be "simplified" into a
single definition without confirming both backends still initialize correctly.

#### Scenario: A table is added to one dialect's definition but not the other
- GIVEN a new table is added only to the SQLite schema block
- WHEN the app runs against a Postgres backend
- THEN that table is silently absent on Postgres — this is the specific risk the
  duplication creates, worth checking whenever `db/models.py` is edited

### Requirement: Every table uses `CREATE TABLE IF NOT EXISTS` — additive, not migrating
The system MUST initialize schema idempotently via `CREATE TABLE IF NOT EXISTS` for every
table; there is no migration framework for altering existing tables' columns. Schema
changes to an existing table require a manual `ALTER`/data-migration step, not a rerun of
`init_db()`.

#### Scenario: A column is added to a table definition after the table already exists
- GIVEN a table was already created in a prior run (e.g. `fundamentals`), and a new
  column is added to its `CREATE TABLE IF NOT EXISTS` statement in `db/models.py`
- WHEN `init_db()` runs again against the existing database file
- THEN the existing table is left as-is (the `IF NOT EXISTS` guard skips it entirely) —
  the new column does not appear without a manual `ALTER TABLE`

### Requirement: One-shot SQLite-to-Supabase migration is a separate, explicit script
The system MUST require an explicit, separate invocation
(`python -m db.migrate_sqlite_to_supabase`) to move existing SQLite data to Postgres —
switching `DB_BACKEND` alone does not migrate data, only which backend new writes go to.

#### Scenario: Switching backend without running the migration
- GIVEN an existing SQLite database with trade history, and `DB_BACKEND` is switched to
  `postgres` in `.env` without running the migration script
- WHEN the app starts against the Postgres backend
- THEN it starts with empty tables (schema created fresh) — none of the SQLite history is
  present until `python -m db.migrate_sqlite_to_supabase` is run explicitly

## Known gaps / gotchas

- No migration framework (Alembic or similar) — every schema change is either additive
  (`CREATE TABLE IF NOT EXISTS`, safe) or requires a hand-written, one-off `ALTER`
  (unsafe if forgotten on one backend).
- ~29 tables span every book's ledger, the conviction-engine scorecard, guidance ledger,
  outcome tracking, news/alerts, and universe/quality data — see
  `openspec/project.md`'s architecture map for which capability owns which tables; this
  spec does not re-enumerate them.

## Source modules

`db/models.py`, `db/migrate_sqlite_to_supabase.py`.
