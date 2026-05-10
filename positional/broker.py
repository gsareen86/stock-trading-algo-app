"""
Broker API Abstraction — Positional Trading Module.

Provides a unified interface for placing delivery orders.
Currently supports:
  paper      — Paper trading (records to pos_trades, no real orders)
  sharekhan  — Stub (API integration pending — add API key to .env)
  zerodha    — Stub (API integration pending — add API key to .env)

Switch broker via POSITIONAL_BROKER in .env:
  POSITIONAL_BROKER=paper       # default (safe, paper trading)
  POSITIONAL_BROKER=sharekhan   # requires SHAREKHAN_API_KEY + SHAREKHAN_CLIENT_ID
  POSITIONAL_BROKER=zerodha     # requires ZERODHA_API_KEY + ZERODHA_ACCESS_TOKEN

All brokers return the same OrderResult namedtuple for consistent handling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success:    bool
    order_id:   str
    ticker:     str
    side:       str          # "BUY" | "SELL"
    quantity:   int
    fill_price: float
    message:    str          # status/error description


# ── Paper Broker ──────────────────────────────────────────────────────────────

class PaperBroker:
    """Paper trading — simulates order fills using last price + slippage."""

    name = "paper"

    def place_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
    ) -> OrderResult:
        from positional.risk import delivery_fill_price
        fill = delivery_fill_price(side, price)
        order_id = f"PAPER-{ticker}-{side}-{quantity}"
        log.info("[broker:paper] %s %s qty=%d fill=%.2f (simulated)",
                 side, ticker, quantity, fill)
        return OrderResult(
            success=True, order_id=order_id,
            ticker=ticker, side=side, quantity=quantity,
            fill_price=fill,
            message=f"Paper order filled @ ₹{fill:.2f}",
        )

    def get_holdings(self) -> list[dict]:
        """Return open positions from pos_positions as holdings."""
        try:
            from db.models import get_conn
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT ticker, quantity, entry_price FROM pos_positions WHERE status='OPEN'"
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


# ── Sharekhan Broker ─────────────────────────────────────────────────────────

class SharekhanBroker:
    """
    Sharekhan API integration — STUB (not yet implemented).

    To activate:
      1. Open a Sharekhan account and enable API access
      2. Obtain API key and client credentials
      3. Install the Sharekhan API SDK (if available) or use their REST API
      4. Set in .env:
           POSITIONAL_BROKER=sharekhan
           SHAREKHAN_API_KEY=your_api_key
           SHAREKHAN_CLIENT_ID=your_client_id
           SHAREKHAN_PASSWORD=your_password
      5. Replace the stub implementations below with actual API calls

    API docs: https://www.sharekhan.com/APIDocumentation
    """

    name = "sharekhan"

    def __init__(self):
        import os
        self.api_key    = os.environ.get("SHAREKHAN_API_KEY", "")
        self.client_id  = os.environ.get("SHAREKHAN_CLIENT_ID", "")
        self.password   = os.environ.get("SHAREKHAN_PASSWORD", "")
        if not self.api_key:
            log.warning("[broker:sharekhan] SHAREKHAN_API_KEY not set — using paper fallback")

    def place_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
    ) -> OrderResult:
        if not self.api_key:
            log.warning("[broker:sharekhan] API key missing — falling back to paper")
            return PaperBroker().place_order(ticker, side, quantity, price, order_type)

        # ── TODO: Implement Sharekhan API call ──────────────────────────────
        # import sharekhan  # pip install sharekhan (or requests)
        # session = sharekhan.login(self.api_key, self.client_id, self.password)
        # nse_ticker = ticker.replace(".NS", "")
        # order_id = session.place_order(
        #     exchange="NSE",
        #     tradingsymbol=nse_ticker,
        #     transaction_type=side,          # "BUY" or "SELL"
        #     quantity=quantity,
        #     order_type=order_type,          # "MARKET" or "LIMIT"
        #     price=price if order_type == "LIMIT" else 0,
        #     product="CNC",                  # Cash-and-Carry for delivery
        # )
        # ────────────────────────────────────────────────────────────────────

        log.warning("[broker:sharekhan] STUB — order not placed for %s %s x%d",
                    side, ticker, quantity)
        return OrderResult(
            success=False, order_id="",
            ticker=ticker, side=side, quantity=quantity, fill_price=price,
            message="Sharekhan broker not yet implemented. Set POSITIONAL_BROKER=paper",
        )

    def get_holdings(self) -> list[dict]:
        # TODO: session.get_holdings()
        return []


# ── Zerodha Broker ────────────────────────────────────────────────────────────

class ZerodhaBroker:
    """
    Zerodha Kite API integration — STUB (not yet implemented).

    To activate:
      1. Open a Zerodha account + subscribe to Kite Connect API (₹2000/month)
      2. Generate API key + access token (daily token refresh needed)
      3. Set in .env:
           POSITIONAL_BROKER=zerodha
           ZERODHA_API_KEY=your_api_key
           ZERODHA_ACCESS_TOKEN=your_access_token   (refresh daily)
      4. pip install kiteconnect
      5. Replace stub implementations with actual Kite calls

    Kite API docs: https://kite.trade/docs/connect/v3/
    """

    name = "zerodha"

    def __init__(self):
        import os
        self.api_key      = os.environ.get("ZERODHA_API_KEY", "")
        self.access_token = os.environ.get("ZERODHA_ACCESS_TOKEN", "")
        if not self.api_key:
            log.warning("[broker:zerodha] ZERODHA_API_KEY not set — using paper fallback")

    def place_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "MARKET",
    ) -> OrderResult:
        if not self.api_key:
            log.warning("[broker:zerodha] API key missing — falling back to paper")
            return PaperBroker().place_order(ticker, side, quantity, price, order_type)

        # ── TODO: Implement Zerodha Kite API call ───────────────────────────
        # from kiteconnect import KiteConnect
        # kite = KiteConnect(api_key=self.api_key)
        # kite.set_access_token(self.access_token)
        # nse_ticker = ticker.replace(".NS", "")
        # order_id = kite.place_order(
        #     variety=kite.VARIETY_REGULAR,
        #     exchange=kite.EXCHANGE_NSE,
        #     tradingsymbol=nse_ticker,
        #     transaction_type=kite.TRANSACTION_TYPE_BUY if side=="BUY" else kite.TRANSACTION_TYPE_SELL,
        #     quantity=quantity,
        #     product=kite.PRODUCT_CNC,      # CNC = delivery
        #     order_type=kite.ORDER_TYPE_MARKET if order_type=="MARKET" else kite.ORDER_TYPE_LIMIT,
        #     price=price if order_type=="LIMIT" else None,
        # )
        # ────────────────────────────────────────────────────────────────────

        log.warning("[broker:zerodha] STUB — order not placed for %s %s x%d",
                    side, ticker, quantity)
        return OrderResult(
            success=False, order_id="",
            ticker=ticker, side=side, quantity=quantity, fill_price=price,
            message="Zerodha broker not yet implemented. Set POSITIONAL_BROKER=paper",
        )

    def get_holdings(self) -> list[dict]:
        # TODO: kite.holdings()
        return []


# ── Factory ───────────────────────────────────────────────────────────────────

_BROKERS = {
    "paper":     PaperBroker,
    "sharekhan": SharekhanBroker,
    "zerodha":   ZerodhaBroker,
}

_instance: Optional[object] = None


def get_broker() -> PaperBroker | SharekhanBroker | ZerodhaBroker:
    """Return the configured broker instance (singleton per process)."""
    global _instance
    if _instance is not None:
        return _instance  # type: ignore[return-value]
    from config import POSITIONAL_BROKER
    cls = _BROKERS.get(POSITIONAL_BROKER.lower(), PaperBroker)
    _instance = cls()
    log.info("[broker] using broker: %s", cls.name)
    return _instance  # type: ignore[return-value]
