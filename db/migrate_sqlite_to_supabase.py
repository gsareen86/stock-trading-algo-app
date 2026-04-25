"""
One-shot migration: copy every row from the local SQLite DB to Supabase
Postgres, preserving primary keys.

Usage
-----
1. Make sure ``.env`` has both:
     SUPABASE_DB_URL=postgresql://postgres:...@db.xxxx.supabase.co:5432/postgres
     DB_BACKEND=sqlite           # so this script reads from local SQLite
2. Run from the project root:
     python -m db.migrate_sqlite_to_supabase

The script will:
  * connect directly to SQLite (bypassing db.models which would otherwise
    route through whatever DB_BACKEND points at)
  * connect directly to Postgres using SUPABASE_DB_URL
  * create the Postgres schema if missing
  * for each table, read all rows from SQLite and INSERT into Postgres
    inside a transaction with ``ON CONFLICT (id) DO NOTHING`` so the script
    is idempotent — re-running it won't duplicate rows
  * after copying, advance each BIGSERIAL sequence past the max imported id
    so subsequent INSERTs don't collide

It does NOT delete from Postgres first. To start clean, drop+recreate via:
    python -c "import db.models as m; m.BACKEND='postgres'; m.reset_db()"
(or just truncate the tables in the Supabase SQL editor).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import DB_PATH

log = logging.getLogger(__name__)


# ----- Tables to migrate, in FK-safe order -----
# bot_control is special: it's a single-row state machine, ON CONFLICT (id) DO UPDATE
# handles re-runs.
TABLE_ORDER = [
    "bot_control",
    "portfolio_snapshots",
    "trades",
    "positions",
    "signals",
    "news",
    "fundamentals",
    "pending_approvals",
]

# Tables whose primary key is `id` BIGSERIAL — sequences need resetting.
SERIAL_TABLES = [
    "portfolio_snapshots",
    "trades",
    "positions",
    "signals",
    "news",
    "pending_approvals",
]


def _connect_sqlite():
    if not Path(DB_PATH).exists():
        raise FileNotFoundError(f"SQLite DB not found at {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _connect_pg():
    url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not url:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    import psycopg
    return psycopg.connect(url)


def _table_columns(pg, table: str) -> list[str]:
    """Return ordered list of column names for the Postgres table."""
    with pg.cursor() as cur:
        cur.execute(
            """SELECT column_name
                 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position""",
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def _migrate_table(sqlite_conn, pg, table: str) -> int:
    """Copy rows from SQLite → Postgres for a single table. Returns row count
    inserted (excludes ON CONFLICT skips)."""
    sqlite_rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
    if not sqlite_rows:
        log.info("[%s] empty, skipping", table)
        return 0

    pg_cols = _table_columns(pg, table)
    if not pg_cols:
        raise RuntimeError(
            f"Postgres has no '{table}' table — run init_db() first"
        )

    # Use the intersection of (sqlite cols, postgres cols) to be defensive
    # in case the schemas drift.
    sqlite_cols = sqlite_rows[0].keys()
    cols = [c for c in pg_cols if c in sqlite_cols]
    if not cols:
        raise RuntimeError(f"No common columns for {table}")

    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)

    if table == "bot_control":
        # Single-row table; UPDATE on conflict so the migrated values win.
        update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "id")
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {update_set}"
        )
    elif table == "fundamentals":
        # PK is `ticker`; UPDATE on conflict so reruns keep the latest data.
        update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "ticker")
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT (ticker) DO UPDATE SET {update_set}"
        )
    elif table == "news":
        # `url` has UNIQUE; ON CONFLICT DO NOTHING is fine for news.
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT (url) DO NOTHING"
        )
    else:
        # BIGSERIAL `id` PK — DO NOTHING keeps re-runs safe.
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO NOTHING"
        )

    inserted = 0
    with pg.cursor() as cur:
        for r in sqlite_rows:
            try:
                cur.execute(sql, tuple(r[c] for c in cols))
                inserted += cur.rowcount
            except Exception as e:
                log.error("[%s] row %s failed: %s", table, dict(r).get("id"), e)
                raise
    log.info("[%s] %d/%d rows inserted", table, inserted, len(sqlite_rows))
    return inserted


def _reset_sequences(pg) -> None:
    """Advance each BIGSERIAL sequence past the max imported id."""
    with pg.cursor() as cur:
        for t in SERIAL_TABLES:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)",
                (t,),
            )
    log.info("Sequences reset for: %s", ", ".join(SERIAL_TABLES))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("Source SQLite: %s", DB_PATH)
    log.info("Target: %s", os.environ.get("SUPABASE_DB_URL", "(unset)").rsplit("@", 1)[-1])

    # Lazy-import init_db with DB_BACKEND forced to postgres for the bootstrap.
    os.environ["DB_BACKEND"] = "postgres"
    # We must reload db.models if it was previously imported with sqlite.
    import importlib
    import db.models as m
    importlib.reload(m)
    log.info("Initializing Postgres schema (idempotent)")
    m.init_db()

    sqlite_conn = _connect_sqlite()
    pg = _connect_pg()
    try:
        total = 0
        for table in TABLE_ORDER:
            try:
                total += _migrate_table(sqlite_conn, pg, table)
                pg.commit()  # commit per table so partial failures still keep progress
            except Exception:
                pg.rollback()
                raise
        _reset_sequences(pg)
        pg.commit()
        log.info("DONE — %d rows migrated", total)
    finally:
        pg.close()
        sqlite_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
