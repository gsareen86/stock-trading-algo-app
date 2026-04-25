"""
Paper broker: simulates order execution on Indian NSE with realistic costs + slippage.
Cost model mirrors Zerodha discount-brokerage pricing for equity intraday.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from config import (
    BROKERAGE_PCT,
    BROKERAGE_PER_ORDER,
    EXCHANGE_TXN_CHARGE,
    GST_RATE,
    SEBI_CHARGES,
    SLIPPAGE_PCT,
    STAMP_DUTY_BUY,
    STT_INTRADAY_SELL,
)


@dataclass
class ExecutionResult:
    side: str
    quantity: int
    fill_price: float
    gross: float
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    gst: float
    stamp: float
    total_costs: float
    net: float   # cash impact (negative on BUY, positive on SELL after costs)


def _brokerage(gross: float) -> float:
    """Zerodha-style: min(₹20, 0.03% of gross)."""
    pct_based = gross * BROKERAGE_PCT
    return min(BROKERAGE_PER_ORDER, pct_based)


def compute_costs(side: str, price: float, qty: int) -> Tuple[float, dict]:
    """
    Compute Indian trading cost breakdown for a single leg.
    Returns (total_cost, breakdown_dict).
    """
    gross = price * qty
    brokerage = _brokerage(gross)
    stt = gross * STT_INTRADAY_SELL if side == "SELL" else 0.0
    exchange = gross * EXCHANGE_TXN_CHARGE
    sebi = gross * SEBI_CHARGES
    # GST on brokerage + exchange + sebi
    gst = (brokerage + exchange + sebi) * GST_RATE
    stamp = gross * STAMP_DUTY_BUY if side == "BUY" else 0.0
    total = brokerage + stt + exchange + sebi + gst + stamp
    return round(total, 4), dict(
        brokerage=brokerage, stt=stt, exchange=exchange, sebi=sebi,
        gst=gst, stamp=stamp,
    )


def execute(side: str, price: float, qty: int) -> ExecutionResult:
    """
    Simulate an order fill.
    Applies slippage in the direction that hurts (buy-up, sell-down).
    """
    assert side in ("BUY", "SELL"), f"bad side {side}"
    assert qty > 0 and price > 0
    slip = price * SLIPPAGE_PCT
    fill = price + slip if side == "BUY" else price - slip
    gross = fill * qty
    total_costs, breakdown = compute_costs(side, fill, qty)

    if side == "BUY":
        net = -(gross + total_costs)    # cash out
    else:
        net = gross - total_costs        # cash in

    return ExecutionResult(
        side=side,
        quantity=qty,
        fill_price=round(fill, 2),
        gross=round(gross, 2),
        total_costs=round(total_costs, 2),
        net=round(net, 2),
        **{k: round(v, 2) for k, v in breakdown.items()},
    )


if __name__ == "__main__":
    r = execute("BUY", 2800, 10)
    print(r)
    r = execute("SELL", 2850, 10)
    print(r)
