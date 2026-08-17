"""Portfolio analytics for one book.

**Every figure here is gross** — no brokerage, STT, stamp duty or GST, and no tax treatment.
A number labelled "P&L" that quietly omits charges is one somebody will eventually compare
against a broker statement and find wrong with no clue why, and Indian equity charges are not
negligible at swing frequencies. Field names carry `_gross` so the omission travels with the
number rather than living in a doc nobody reads next to it.

Nothing here ranks strategies against each other. Attribution reports what each *did*; it never
becomes a reason to prefer one, which would be the confluence scorecard rebuilt at the portfolio
layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.domain.position import Book, Position, Side, Trade


@dataclass
class BookAnalytics:
    """What a book looks like right now."""

    book: Book
    positions: list[Position] = field(default_factory=list)
    prices: Mapping[str, float] = field(default_factory=dict)
    realised_pnl_gross: float = 0.0
    trade_count: int = 0

    # ── exposure ──────────────────────────────────────────────────────────────
    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.is_open]

    @property
    def cost_basis(self) -> float:
        return round(sum(p.cost_basis for p in self.open_positions), 2)

    @property
    def market_value(self) -> float | None:
        """None when any open position has no price — a partial total is a misleading one."""
        values = [p.market_value(self.prices.get(p.ticker)) for p in self.open_positions]
        if any(v is None for v in values):
            return None
        return round(sum(v for v in values if v is not None), 2)

    @property
    def unrealised_pnl_gross(self) -> float | None:
        market = self.market_value
        return None if market is None else round(market - self.cost_basis, 2)

    def concentration(self) -> dict[str, float]:
        """Each holding's share of cost basis, as a percentage.

        Measured on cost rather than market value so the number does not move because a
        position appreciated — concentration is about how much was committed.
        """
        total = self.cost_basis
        if total <= 0:
            return {}
        return {
            p.ticker: round(p.cost_basis / total * 100, 2)
            for p in sorted(self.open_positions, key=lambda x: -x.cost_basis)
        }

    def largest_position_pct(self) -> float:
        weights = self.concentration()
        return max(weights.values()) if weights else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "book": self.book.value,
            "open_positions": len(self.open_positions),
            "cost_basis": self.cost_basis,
            "market_value": self.market_value,
            # Gross of every charge — see the module docstring.
            "realised_pnl_gross": round(self.realised_pnl_gross, 2),
            "unrealised_pnl_gross": self.unrealised_pnl_gross,
            "concentration_pct": self.concentration(),
            "largest_position_pct": self.largest_position_pct(),
            "trade_count": self.trade_count,
            "charges_included": False,
            "positions": [p.as_dict(self.prices.get(p.ticker)) for p in self.open_positions],
        }


def build(
    book: Book,
    positions: list[Position],
    trades: list[Trade],
    prices: Mapping[str, float] | None = None,
) -> BookAnalytics:
    return BookAnalytics(
        book=book,
        positions=positions,
        prices=dict(prices or {}),
        realised_pnl_gross=sum(p.realised_pnl for p in positions),
        trade_count=len(trades),
    )


def closed_trade_stats(positions: list[Position]) -> dict[str, Any]:
    """Outcomes of positions that have been fully exited.

    Deliberately not a "win rate" across open positions: a position still open has no outcome,
    and counting unrealised gains as wins is how a strategy looks good until it is closed.
    """
    closed = [p for p in positions if not p.is_open and p.trade_count > 0]
    wins = [p for p in closed if p.realised_pnl > 0]
    losses = [p for p in closed if p.realised_pnl < 0]
    return {
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 2) if closed else None,
        "gross_won": round(sum(p.realised_pnl for p in wins), 2),
        "gross_lost": round(sum(p.realised_pnl for p in losses), 2),
    }


def attribution(trades: list[Trade]) -> dict[str, dict[str, Any]]:
    """What each strategy's verdicts led to.

    Reports activity; it does not rank. "Which strategy performed best" is a question this
    platform deliberately cannot answer with one number — that is the confluence scorecard,
    and a portfolio view is exactly where it would look reasonable.
    """
    out: dict[str, dict[str, Any]] = {}
    for trade in trades:
        key = trade.strategy_id or "unattributed"
        bucket = out.setdefault(key, {"trades": 0, "bought": 0.0, "sold": 0.0})
        bucket["trades"] += 1
        if trade.side is Side.BUY:
            bucket["bought"] = round(bucket["bought"] + trade.value, 2)
        else:
            bucket["sold"] = round(bucket["sold"] + trade.value, 2)
    return out
