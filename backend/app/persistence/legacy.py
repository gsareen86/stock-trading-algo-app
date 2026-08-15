"""Inventory of the predecessor's schema, and the guard for eventually retiring it.

These 30 tables live in ``public`` and are **not** touched by this platform's migrations. The
rebuild took its own ``trading`` schema instead, because they turned out to hold roughly
47,500 rows of real history — 472 trades, 206 positions, 325 signal outcomes and ~20k signals
— which later increments want for backtesting and outcome analysis.

Two things live here:

* :data:`LEGACY_TABLES` — the inventory, so "is this ours or the old app's?" is answerable in
  code rather than from memory. The data port in ``market-data-foundation`` reads from it.
* :func:`assert_all_empty` — the guard for the tracked cleanup milestone that eventually drops
  these tables. It is deliberately kept and tested now, while there is no pressure on it,
  rather than written in a hurry on the day someone decides to delete 47,500 rows.

Nothing here is wired into a migration today. That is intentional.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection

#: The legacy schema, named exhaustively. Nothing outside this list is ever dropped — no
#: ``DROP SCHEMA``, no reflection-driven loop over whatever happens to be present.
LEGACY_TABLES: tuple[str, ...] = (
    "portfolio_snapshots",
    "trades",
    "positions",
    "signals",
    "news",
    "fundamentals",
    "bot_control",
    "pending_approvals",
    "lt_universe",
    "lt_quality",
    "cycle_log",
    "positional_positions",
    "positional_signals",
    "llm_call_log",
    "pos_market_regime",
    "pos_universe",
    "pos_scans",
    "pos_positions",
    "pos_trades",
    "pos_watchlist",
    "pos_research",
    "fundamentals_pins",
    "news_impact_alerts",
    "news_sector_tags",
    "guidance_ledger",
    "signal_outcomes",
    "event_calendar",
    "surveillance_list",
    "lt_positions",
    "lt_trades",
)


def present_legacy_tables(bind: Connection) -> list[str]:
    """Which legacy tables actually exist, in the order they are listed."""
    existing = set(sa.inspect(bind).get_table_names())
    return [table for table in LEGACY_TABLES if table in existing]


def assert_all_empty(bind: Connection) -> list[str]:
    """Verify every present legacy table is empty and return them.

    Raises :class:`RuntimeError` naming every offending table *before* anything is dropped, so
    an abort leaves the schema exactly as it was.
    """
    present = present_legacy_tables(bind)

    non_empty: list[tuple[str, int]] = []
    for table in present:
        count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        if count:
            non_empty.append((table, count))

    if non_empty:
        detail = ", ".join(f"{name} ({rows} rows)" for name, rows in non_empty)
        raise RuntimeError(
            f"Refusing to drop non-empty legacy tables: {detail}. This migration only removes "
            "verifiably empty tables; export or delete the data deliberately, then re-run."
        )

    return present
