"""
Risk & position-sizing rules.
All rules are read from runtime bot_control (so UI edits take effect immediately).
"""
from __future__ import annotations

import logging
from typing import Optional

from db.models import get_conn

log = logging.getLogger(__name__)


def get_runtime_params() -> dict:
    """Read current runtime params from bot_control (falls back to config defaults)."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bot_control WHERE id=1").fetchone()
    if not row:
        from config import (
            MAX_OPEN_POSITIONS,
            RISK_PER_TRADE_PCT,
            STOP_LOSS_PCT,
            TAKE_PROFIT_PCT,
            MIN_COMPOSITE_SCORE,
        )
        return dict(
            max_open_positions=MAX_OPEN_POSITIONS,
            risk_per_trade_pct=RISK_PER_TRADE_PCT,
            stop_loss_pct=STOP_LOSS_PCT,
            take_profit_pct=TAKE_PROFIT_PCT,
            min_composite_score=MIN_COMPOSITE_SCORE,
        )
    return dict(row)


def position_size(capital: float, price: float, sl_pct: Optional[float] = None,
                  risk_pct: Optional[float] = None) -> int:
    """
    Position sizing by risk:
    quantity = (capital * risk_pct) / (price * sl_pct)
    capped at 20% of capital / price (max position size).
    """
    params = get_runtime_params()
    sl_pct = sl_pct if sl_pct is not None else params["stop_loss_pct"]
    risk_pct = risk_pct if risk_pct is not None else params["risk_per_trade_pct"]

    if price <= 0 or sl_pct <= 0:
        return 0

    risk_amount = capital * risk_pct
    qty = int(risk_amount / (price * sl_pct))
    max_qty = int((capital * 0.20) / price)
    return max(0, min(qty, max_qty))


def can_open_new(open_position_count: int) -> bool:
    params = get_runtime_params()
    return open_position_count < params["max_open_positions"]
