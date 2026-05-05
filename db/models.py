"""
Database layer — supports both SQLite (local dev) and Postgres (Supabase).

Backend selection
-----------------
Set the ``DB_BACKEND`` env var:
  * ``sqlite``    (default) — uses ``config.DB_PATH`` on the local filesystem.
  * ``postgres``  — uses ``SUPABASE_DB_URL`` (a libpq connection string).

Why a hand-rolled wrapper instead of SQLAlchemy?
------------------------------------------------
The codebase already has ~30 raw SQL call sites with ``?`` placeholders. A
thin wrapper keeps every existing call site working while only paying the
cost of two backend-specific tweaks:
  1. translate ``?`` → ``%s`` for psycopg
  2. expose ``cur.fetchone()/fetchall()`` rows as dict-like objects

For two non-portable SQL bits we keep small backend-aware helpers:
  * ``insert_returning_id(conn, sql, params)`` — sqlite uses ``cursor.lastrowid``;
    postgres needs ``RETURNING id``. The helper handles both.
  * ``query_df(sql, params)`` — pandas warns / breaks on raw psycopg connections,
    so for postgres we hand-roll the DataFrame from the cursor.

All UPSERTs use Postgres-compatible ``ON CONFLICT (...) DO UPDATE/NOTHING``
syntax which SQLite has supported since 3.24 (Python 3.7+ ships ≥ 3.24).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

# Load .env if present so DB_BACKEND / SUPABASE_DB_URL are picked up
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import DB_PATH

log = logging.getLogger(__name__)


BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower().strip()
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL", "").strip()

if BACKEND not in ("sqlite", "postgres"):
    raise RuntimeError(f"Unknown DB_BACKEND={BACKEND!r}; use 'sqlite' or 'postgres'")

if BACKEND == "postgres" and not SUPABASE_DB_URL:
    raise RuntimeError(
        "DB_BACKEND=postgres but SUPABASE_DB_URL is not set. "
        "Add it to your .env or the environment."
    )


# ---------- Schema (dialect-specific) ----------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    cash REAL NOT NULL,
    equity REAL NOT NULL,
    total_value REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    open_positions INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    value REAL NOT NULL,
    costs REAL NOT NULL,
    net_value REAL NOT NULL,
    strategy TEXT,
    reason TEXT,
    composite_score REAL,
    mode TEXT,
    position_id INTEGER REFERENCES positions(id)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    entry_ts TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    strategy TEXT,
    composite_score REAL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    exit_ts TEXT,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    atr_at_entry REAL,
    t1_target REAL,
    t1_taken INTEGER DEFAULT 0,
    high_water_mark REAL,
    initial_quantity INTEGER
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    strategy TEXT NOT NULL,
    technical_score REAL,
    fundamental_score REAL,
    sentiment_score REAL,
    composite_score REAL,
    price REAL,
    reason TEXT,
    taken INTEGER DEFAULT 0,
    threshold_at_time REAL,
    mode_at_time TEXT
);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT UNIQUE,
    tickers TEXT,
    sentiment REAL,
    processed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    pe_ratio REAL,
    peg_ratio REAL,
    eps REAL,
    revenue_growth REAL,
    earnings_growth REAL,
    debt_to_equity REAL,
    roe REAL,
    profit_margin REAL,
    market_cap REAL,
    dividend_yield REAL,
    sector TEXT,
    industry TEXT,
    fundamental_score REAL
);

CREATE TABLE IF NOT EXISTS bot_control (
    id INTEGER PRIMARY KEY CHECK (id=1),
    status TEXT NOT NULL DEFAULT 'STOPPED',
    mode TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT,
    max_open_positions INTEGER DEFAULT 5,
    risk_per_trade_pct REAL DEFAULT 0.04,
    stop_loss_pct REAL DEFAULT 0.05,
    take_profit_pct REAL DEFAULT 0.10,
    min_composite_score REAL DEFAULT 60
);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    strategy TEXT,
    composite_score REAL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    decided_at TEXT,
    decision_note TEXT,
    side TEXT DEFAULT 'LONG'
);

CREATE TABLE IF NOT EXISTS lt_universe (
    ticker TEXT PRIMARY KEY,
    last_filtered_at TEXT NOT NULL,
    market_cap REAL,
    sector TEXT,
    industry TEXT,
    has_fii INTEGER DEFAULT 0,
    has_dii INTEGER DEFAULT 0,
    fii_pct REAL,
    dii_pct REAL,
    fii_qoq_change REAL,
    dii_qoq_change REAL,
    promoter_holding_pct REAL,
    promoter_pledge_pct REAL,
    in_universe INTEGER DEFAULT 0,
    filter_reason TEXT,
    raw_inputs TEXT
);

CREATE TABLE IF NOT EXISTS lt_quality (
    ticker TEXT PRIMARY KEY,
    scored_at TEXT NOT NULL,
    profitability_score REAL,
    cash_quality_score REAL,
    solvency_score REAL,
    growth_score REAL,
    governance_score REAL,
    total_score REAL,
    raw_inputs TEXT
);

-- Cycle log: every run_cycle invocation writes a row at start (status=RUNNING)
-- and updates it at the end (DONE / ERROR). Lets the dashboard show what the
-- scheduler is doing cross-process AND lets long-running cycles surface
-- progress (so the 'Run Cycle Now' UI can recover even if the browser
-- disconnects mid-cycle).
CREATE TABLE IF NOT EXISTS cycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    triggered_by TEXT,
    summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON portfolio_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news(ts);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON pending_approvals(status);
CREATE INDEX IF NOT EXISTS idx_lt_universe_in_universe ON lt_universe(in_universe);
CREATE INDEX IF NOT EXISTS idx_lt_quality_total ON lt_quality(total_score);
CREATE TABLE IF NOT EXISTS positional_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER REFERENCES positions(id),
    ticker TEXT NOT NULL,
    quality_score REAL,
    conviction TEXT DEFAULT 'medium',
    expected_exit_date TEXT,
    hold_days_limit INTEGER DEFAULT 30,
    days_held INTEGER DEFAULT 0,
    sector TEXT,
    strategy_breakdown TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positional_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    strategy TEXT NOT NULL,
    score REAL,
    price REAL,
    reason TEXT,
    quality_score REAL,
    taken INTEGER DEFAULT 0,
    meta TEXT
);

CREATE INDEX IF NOT EXISTS idx_cycle_log_started ON cycle_log(started_at);
CREATE INDEX IF NOT EXISTS idx_pos_positions_ticker ON positional_positions(ticker);
CREATE INDEX IF NOT EXISTS idx_pos_signals_scanned ON positional_signals(scanned_at);
"""

# Postgres schema. We keep ts columns as TEXT (ISO strings) to match the
# SQLite shape exactly — that way migration is row-for-row and existing code
# using `datetime.utcnow().isoformat()` strings keeps working unchanged.
# Indexes and ON CONFLICT keys are added explicitly.
_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id BIGSERIAL PRIMARY KEY,
    ts TEXT NOT NULL,
    cash DOUBLE PRECISION NOT NULL,
    equity DOUBLE PRECISION NOT NULL,
    total_value DOUBLE PRECISION NOT NULL,
    unrealized_pnl DOUBLE PRECISION NOT NULL,
    realized_pnl DOUBLE PRECISION NOT NULL,
    open_positions INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    costs DOUBLE PRECISION NOT NULL,
    net_value DOUBLE PRECISION NOT NULL,
    strategy TEXT,
    reason TEXT,
    composite_score DOUBLE PRECISION,
    mode TEXT,
    position_id BIGINT REFERENCES positions(id)
);

CREATE TABLE IF NOT EXISTS positions (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    entry_ts TEXT NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    quantity INTEGER NOT NULL,
    stop_loss DOUBLE PRECISION,
    take_profit DOUBLE PRECISION,
    strategy TEXT,
    composite_score DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'OPEN',
    exit_ts TEXT,
    exit_price DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    pnl_pct DOUBLE PRECISION,
    atr_at_entry DOUBLE PRECISION,
    t1_target DOUBLE PRECISION,
    t1_taken INTEGER DEFAULT 0,
    high_water_mark DOUBLE PRECISION,
    initial_quantity INTEGER
);

CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    strategy TEXT NOT NULL,
    technical_score DOUBLE PRECISION,
    fundamental_score DOUBLE PRECISION,
    sentiment_score DOUBLE PRECISION,
    composite_score DOUBLE PRECISION,
    price DOUBLE PRECISION,
    reason TEXT,
    taken INTEGER DEFAULT 0,
    threshold_at_time DOUBLE PRECISION,
    mode_at_time TEXT
);

CREATE TABLE IF NOT EXISTS news (
    id BIGSERIAL PRIMARY KEY,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT UNIQUE,
    tickers TEXT,
    sentiment DOUBLE PRECISION,
    processed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    pe_ratio DOUBLE PRECISION,
    peg_ratio DOUBLE PRECISION,
    eps DOUBLE PRECISION,
    revenue_growth DOUBLE PRECISION,
    earnings_growth DOUBLE PRECISION,
    debt_to_equity DOUBLE PRECISION,
    roe DOUBLE PRECISION,
    profit_margin DOUBLE PRECISION,
    market_cap DOUBLE PRECISION,
    dividend_yield DOUBLE PRECISION,
    sector TEXT,
    industry TEXT,
    fundamental_score DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS bot_control (
    id INTEGER PRIMARY KEY CHECK (id=1),
    status TEXT NOT NULL DEFAULT 'STOPPED',
    mode TEXT NOT NULL DEFAULT 'manual',
    updated_at TEXT,
    max_open_positions INTEGER DEFAULT 5,
    risk_per_trade_pct DOUBLE PRECISION DEFAULT 0.04,
    stop_loss_pct DOUBLE PRECISION DEFAULT 0.05,
    take_profit_pct DOUBLE PRECISION DEFAULT 0.10,
    min_composite_score DOUBLE PRECISION DEFAULT 60
);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id BIGSERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    stop_loss DOUBLE PRECISION,
    take_profit DOUBLE PRECISION,
    strategy TEXT,
    composite_score DOUBLE PRECISION,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    decided_at TEXT,
    decision_note TEXT,
    side TEXT DEFAULT 'LONG'
);

CREATE TABLE IF NOT EXISTS lt_universe (
    ticker TEXT PRIMARY KEY,
    last_filtered_at TEXT NOT NULL,
    market_cap DOUBLE PRECISION,
    sector TEXT,
    industry TEXT,
    has_fii INTEGER DEFAULT 0,
    has_dii INTEGER DEFAULT 0,
    fii_pct DOUBLE PRECISION,
    dii_pct DOUBLE PRECISION,
    fii_qoq_change DOUBLE PRECISION,
    dii_qoq_change DOUBLE PRECISION,
    promoter_holding_pct DOUBLE PRECISION,
    promoter_pledge_pct DOUBLE PRECISION,
    in_universe INTEGER DEFAULT 0,
    filter_reason TEXT,
    raw_inputs JSONB
);

CREATE TABLE IF NOT EXISTS lt_quality (
    ticker TEXT PRIMARY KEY,
    scored_at TEXT NOT NULL,
    profitability_score DOUBLE PRECISION,
    cash_quality_score DOUBLE PRECISION,
    solvency_score DOUBLE PRECISION,
    growth_score DOUBLE PRECISION,
    governance_score DOUBLE PRECISION,
    total_score DOUBLE PRECISION,
    raw_inputs JSONB
);

CREATE TABLE IF NOT EXISTS cycle_log (
    id BIGSERIAL PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    triggered_by TEXT,
    summary JSONB
);

CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON portfolio_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news(ts);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON pending_approvals(status);
CREATE INDEX IF NOT EXISTS idx_lt_universe_in_universe ON lt_universe(in_universe);
CREATE INDEX IF NOT EXISTS idx_lt_quality_total ON lt_quality(total_score);
CREATE TABLE IF NOT EXISTS positional_positions (
    id BIGSERIAL PRIMARY KEY,
    position_id BIGINT REFERENCES positions(id),
    ticker TEXT NOT NULL,
    quality_score DOUBLE PRECISION,
    conviction TEXT DEFAULT 'medium',
    expected_exit_date TEXT,
    hold_days_limit INTEGER DEFAULT 30,
    days_held INTEGER DEFAULT 0,
    sector TEXT,
    strategy_breakdown JSONB,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positional_signals (
    id BIGSERIAL PRIMARY KEY,
    scanned_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    strategy TEXT NOT NULL,
    score DOUBLE PRECISION,
    price DOUBLE PRECISION,
    reason TEXT,
    quality_score DOUBLE PRECISION,
    taken INTEGER DEFAULT 0,
    meta JSONB
);

CREATE INDEX IF NOT EXISTS idx_cycle_log_started ON cycle_log(started_at);
CREATE INDEX IF NOT EXISTS idx_pos_positions_ticker ON positional_positions(ticker);
CREATE INDEX IF NOT EXISTS idx_pos_signals_scanned ON positional_signals(scanned_at);
"""


# ---------- Postgres adapter ----------

def _q(sql: str) -> str:
    """Translate SQLite ``?`` placeholders to psycopg ``%s``.

    Uses a simple state machine to skip ``?`` characters that appear inside
    single-quoted string literals, preventing incorrect substitution for SQL
    like ``WHERE reason = 'Why?'``.
    """
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_string:
            in_string = True
            result.append(ch)
        elif ch == "'" and in_string:
            # Handle escaped quote ''
            if i + 1 < len(sql) and sql[i + 1] == "'":
                result.append("''")
                i += 2
                continue
            in_string = False
            result.append(ch)
        elif ch == "?" and not in_string:
            result.append("%s")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


class _PgCursorWrapper:
    """psycopg cursor wrapped to mimic sqlite3.Cursor's API surface we use:
    - ``fetchone()`` / ``fetchall()`` return dict-like rows (psycopg dict_row).
    - ``rowcount`` and ``lastrowid`` exposed as attributes.
    The wrapper makes plain dict rows look like ``sqlite3.Row`` (subscript by
    column name AND by integer index)."""

    def __init__(self, cur):
        self._cur = cur

    def __iter__(self):
        for r in self._cur:
            yield _Row(r) if isinstance(r, dict) else r

    def fetchone(self):
        r = self._cur.fetchone()
        return _Row(r) if isinstance(r, dict) else r

    def fetchall(self):
        rows = self._cur.fetchall()
        return [_Row(r) if isinstance(r, dict) else r for r in rows]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    @property
    def lastrowid(self):
        # psycopg has no lastrowid; callers should use insert_returning_id().
        # We raise rather than silently return None to surface the bug early.
        raise AttributeError(
            "lastrowid is unavailable on Postgres. Use db.models.insert_returning_id(conn, sql, params) instead."
        )

    def close(self):
        self._cur.close()


class _Row(dict):
    """Dict subclass that also supports integer indexing like sqlite3.Row."""

    def __init__(self, mapping):
        super().__init__(mapping)
        self._values_list = list(mapping.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values_list[key]
        return super().__getitem__(key)


class _PgConnWrapper:
    """psycopg connection wrapped to look like a sqlite3 connection."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(_q(sql), params or ())
        return _PgCursorWrapper(cur)

    def executemany(self, sql, seq_of_params):
        cur = self._conn.cursor()
        cur.executemany(_q(sql), seq_of_params)
        return _PgCursorWrapper(cur)

    def cursor(self):
        return _PgCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ---------- Init ----------


def _connect_pg():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(SUPABASE_DB_URL, row_factory=dict_row)


def _connect_sqlite():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_positions_atr_columns(conn) -> None:
    """Add ATR/trailing-stop + side columns to ``positions`` if missing.

    Backwards-compatible: positions opened before this migration will have
    NULL in the new columns and will fall back to the legacy fixed SL/TP path.
    """
    if BACKEND == "sqlite":
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
        ddl = {
            "atr_at_entry":     "ALTER TABLE positions ADD COLUMN atr_at_entry REAL",
            "t1_target":        "ALTER TABLE positions ADD COLUMN t1_target REAL",
            "t1_taken":         "ALTER TABLE positions ADD COLUMN t1_taken INTEGER DEFAULT 0",
            "high_water_mark":  "ALTER TABLE positions ADD COLUMN high_water_mark REAL",
            "initial_quantity": "ALTER TABLE positions ADD COLUMN initial_quantity INTEGER",
            "side":             "ALTER TABLE positions ADD COLUMN side TEXT DEFAULT 'LONG'",
        }
        for col, sql in ddl.items():
            if col not in existing:
                conn.execute(sql)
        return

    # Postgres path — IF NOT EXISTS is supported on ALTER TABLE ADD COLUMN
    # for >= 9.6 (Supabase is much newer).
    cur = conn.cursor() if hasattr(conn, "cursor") else conn
    for sql in (
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS atr_at_entry DOUBLE PRECISION",
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS t1_target DOUBLE PRECISION",
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS t1_taken INTEGER DEFAULT 0",
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS high_water_mark DOUBLE PRECISION",
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS initial_quantity INTEGER",
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS side TEXT DEFAULT 'LONG'",
    ):
        cur.execute(sql)


def _migrate_positional_columns(conn) -> None:
    """Add trade_type columns to positions and pending_approvals if missing."""
    if BACKEND == "sqlite":
        pos_cols = {r["name"] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
        if "trade_type" not in pos_cols:
            conn.execute("ALTER TABLE positions ADD COLUMN trade_type TEXT DEFAULT 'intraday'")
        appr_cols = {r["name"] for r in conn.execute("PRAGMA table_info(pending_approvals)").fetchall()}
        if "trade_type" not in appr_cols:
            conn.execute("ALTER TABLE pending_approvals ADD COLUMN trade_type TEXT DEFAULT 'intraday'")
        if "positional_enabled" not in {r["name"] for r in conn.execute("PRAGMA table_info(bot_control)").fetchall()}:
            conn.execute("ALTER TABLE bot_control ADD COLUMN positional_enabled INTEGER DEFAULT 0")
        sig_cols = {r["name"] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
        if "threshold_at_time" not in sig_cols:
            conn.execute("ALTER TABLE signals ADD COLUMN threshold_at_time REAL")
        if "mode_at_time" not in sig_cols:
            conn.execute("ALTER TABLE signals ADD COLUMN mode_at_time TEXT")
        pend_cols = {r["name"] for r in conn.execute("PRAGMA table_info(pending_approvals)").fetchall()}
        if "side" not in pend_cols:
            conn.execute("ALTER TABLE pending_approvals ADD COLUMN side TEXT DEFAULT 'LONG'")
        return

    cur = conn.cursor() if hasattr(conn, "cursor") else conn
    for sql in (
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS trade_type TEXT DEFAULT 'intraday'",
        "ALTER TABLE pending_approvals ADD COLUMN IF NOT EXISTS trade_type TEXT DEFAULT 'intraday'",
        "ALTER TABLE bot_control ADD COLUMN IF NOT EXISTS positional_enabled INTEGER DEFAULT 0",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS threshold_at_time DOUBLE PRECISION",
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS mode_at_time TEXT",
        "ALTER TABLE pending_approvals ADD COLUMN IF NOT EXISTS side TEXT DEFAULT 'LONG'",
    ):
        cur.execute(sql)


def init_db() -> None:
    """Create tables + seed bot_control row if absent."""
    if BACKEND == "sqlite":
        conn = _connect_sqlite()
        try:
            conn.executescript(_SQLITE_SCHEMA)
            _migrate_positions_atr_columns(conn)
            _migrate_positional_columns(conn)
            conn.execute(
                """INSERT INTO bot_control (id, status, mode, updated_at)
                   VALUES (1, 'STOPPED', 'manual', ?)
                   ON CONFLICT (id) DO NOTHING""",
                (datetime.utcnow().isoformat(),),
            )
            conn.commit()
        finally:
            conn.close()
    else:
        conn = _connect_pg()
        try:
            with conn.cursor() as cur:
                # psycopg can run multi-statement DDL via execute() if the
                # commands are separated by ;.
                cur.execute(_POSTGRES_SCHEMA)
                _migrate_positions_atr_columns(cur)
                _migrate_positional_columns(cur)
                cur.execute(
                    """INSERT INTO bot_control (id, status, mode, updated_at)
                       VALUES (1, 'STOPPED', 'manual', %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (datetime.utcnow().isoformat(),),
                )
            conn.commit()
        finally:
            conn.close()


@contextmanager
def get_conn():
    """Context-managed DB connection. Auto-commits on clean exit, rolls back
    on exception. Returned object exposes ``execute()``/``executemany()``/
    ``cursor()`` regardless of backend."""
    if BACKEND == "sqlite":
        conn = _connect_sqlite()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        raw = _connect_pg()
        wrapped = _PgConnWrapper(raw)
        try:
            yield wrapped
            wrapped.commit()
        except Exception:
            wrapped.rollback()
            raise
        finally:
            wrapped.close()


# ---------- Backend-aware helpers ----------


def insert_returning_id(conn, sql: str, params: Iterable[Any] = ()) -> int:
    """Run an INSERT and return the new row's id.

    SQLite: uses ``cursor.lastrowid``.
    Postgres: appends ``RETURNING id`` (if not already present) and reads the
    first column of the returned row.
    """
    if BACKEND == "sqlite":
        cur = conn.execute(sql, params)
        return int(cur.lastrowid)

    # Postgres path
    sql_lower = sql.lower()
    if " returning " not in sql_lower:
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING id produced no row")
    # _Row supports both dict access and int indexing
    return int(row["id"]) if "id" in row else int(row[0])


def query_df(sql: str, params: Iterable[Any] = ()):
    """Run a SELECT and return a pandas DataFrame.

    pandas + raw psycopg connections produces a UserWarning and may break
    in newer pandas versions, so for postgres we hand-roll the DataFrame
    from the cursor results.
    """
    import pandas as pd

    if BACKEND == "sqlite":
        conn = _connect_sqlite()
        try:
            return pd.read_sql_query(sql, conn, params=tuple(params or ()))
        finally:
            conn.close()

    # Postgres: explicit cursor → DataFrame
    raw = _connect_pg()
    try:
        with raw.cursor() as cur:
            cur.execute(_q(sql), tuple(params or ()))
            cols = [c.name for c in cur.description] if cur.description else []
            rows = cur.fetchall()
        # rows are list of dict (dict_row factory)
        return pd.DataFrame(rows, columns=cols)
    finally:
        raw.close()


def reset_db() -> None:
    """Wipes everything. Use with care."""
    if BACKEND == "sqlite":
        if Path(DB_PATH).exists():
            Path(DB_PATH).unlink()
        init_db()
        return
    # Postgres: drop+recreate
    conn = _connect_pg()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DROP TABLE IF EXISTS lt_quality, lt_universe,
                                     pending_approvals, bot_control, fundamentals,
                                     news, signals, positions, trades,
                                     portfolio_snapshots CASCADE
            """)
        conn.commit()
    finally:
        conn.close()
    init_db()


def reset_postgres_sequences() -> None:
    """After a row-preserving migration, advance each BIGSERIAL sequence past
    the max imported id, otherwise the next INSERT collides."""
    if BACKEND != "postgres":
        return
    tables_with_serial = [
        "portfolio_snapshots", "trades", "positions",
        "signals", "news", "pending_approvals",
    ]
    conn = _connect_pg()
    try:
        with conn.cursor() as cur:
            for t in tables_with_serial:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)",
                    (t,),
                )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(f"DB initialized [backend={BACKEND}]")
