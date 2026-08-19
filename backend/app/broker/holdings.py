"""What is actually held at the broker.

**Observed, never recorded as fills.** These do not enter `Ledger`, and that separation is the
whole point: the paper ledger is a record of what this platform's strategies would have done,
and real holdings are a record of what you did elsewhere. Merging them destroys the only
question the ledger exists to answer — "how would following these strategies have gone" — by
mixing in trades no strategy proposed.

They are also a different *kind* of fact. A ledger position is derived from a trade history the
platform recorded and can reproduce. A broker holding is a snapshot someone else computed, with
an average price whose constituent fills we never saw.

What the join is genuinely for: taking a real holding and asking the strategies what they now
think of it — which is the useful thing, and needs no merging at all.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BrokerHolding:
    """One position as the broker reports it."""

    symbol: str
    exchange: str
    quantity: int
    average_price: float
    last_price: float | None
    #: As the broker computed it. Not recomputed here — a second opinion on someone else's
    #: arithmetic would be a number that disagrees with the app the user actually trades in.
    pnl: float | None

    @property
    def value(self) -> float | None:
        return None if self.last_price is None else self.quantity * self.last_price

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "average_price": self.average_price,
            "last_price": self.last_price,
            "value": self.value,
            # Named as the broker's own figure. This platform's P&L is gross and computed
            # differently; presenting them under one label would invite comparing them.
            "pnl_reported_by_broker": self.pnl,
            "source": "zerodha",
        }


def _as_records(payload: str) -> list[dict[str, Any]]:
    """Kite MCP returns JSON as text. Anything unparseable yields nothing rather than raising."""
    text = (payload or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Kite returned text that is not JSON: %s", text[:160])
        return []

    if isinstance(parsed, dict):
        for key in ("holdings", "positions", "net", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        return []
    return parsed if isinstance(parsed, list) else []


def _number(record: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = record.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


def parse_holdings(payload: str) -> list[BrokerHolding]:
    """Read a holdings response.

    Field names are read defensively across the spellings Kite has used. A remote schema is not
    ours to depend on, and a missing field should cost one value rather than the whole list.
    """
    out: list[BrokerHolding] = []
    for record in _as_records(payload):
        if not isinstance(record, dict):
            continue
        raw_symbol = (
            record.get("tradingsymbol")
            or record.get("trading_symbol")
            or record.get("symbol")
            or ""
        )
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue

        quantity = _number(record, "quantity", "opening_quantity", "qty") or 0
        if quantity <= 0:
            continue

        out.append(
            BrokerHolding(
                symbol=symbol,
                exchange=str(record.get("exchange") or "NSE").upper(),
                quantity=int(quantity),
                average_price=_number(record, "average_price", "avg_price", "average_cost") or 0.0,
                last_price=_number(record, "last_price", "ltp", "close_price"),
                pnl=_number(record, "pnl", "unrealised", "unrealized"),
            )
        )
    return sorted(out, key=lambda h: h.symbol)


def summarise(holdings: list[BrokerHolding]) -> dict[str, Any]:
    """Totals over what the broker reports."""
    invested = sum(h.quantity * h.average_price for h in holdings)
    values = [h.value for h in holdings]
    # Withheld entirely when any price is missing — a partial total is a misleading one, the
    # same rule the paper book follows.
    market = None if any(v is None for v in values) else sum(v for v in values if v is not None)

    return {
        "count": len(holdings),
        "invested": round(invested, 2),
        "market_value": None if market is None else round(market, 2),
        "holdings": [h.as_dict() for h in holdings],
        "source": "zerodha",
        "note": (
            "Reported by your broker, not by this platform. These are not paper positions and "
            "are never mixed into the paper books."
        ),
    }
