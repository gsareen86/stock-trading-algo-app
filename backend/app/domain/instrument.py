"""Instruments and the symbol forms they wear.

An NSE symbol (`RELIANCE`) is what the platform reasons about. `RELIANCE.NS` is a yfinance
artefact. Keeping that translation inside the data source means the provider's naming never
leaks into strategy code — the same reason `PriceSeries` lowercases yfinance's column
capitalisation.
"""

from __future__ import annotations

from dataclasses import dataclass

#: yfinance suffixes: NSE and BSE respectively.
NSE_SUFFIX = ".NS"
BSE_SUFFIX = ".BO"
PROVIDER_SUFFIXES = (NSE_SUFFIX, BSE_SUFFIX)


@dataclass(frozen=True, slots=True)
class Instrument:
    """One tradable name.

    ``symbol`` is the bare NSE code, without any provider suffix.
    """

    symbol: str
    name: str | None = None
    sector: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol or not self.symbol.strip():
            raise ValueError("instrument symbol must be non-empty")
        if self.symbol != self.symbol.strip().upper():
            # Normalising silently would make `Instrument("reliance")` and
            # `Instrument("RELIANCE")` distinct dict keys that compare unequal — a bug that
            # surfaces far from its cause.
            raise ValueError(f"symbol must be upper-case and unpadded, got {self.symbol!r}")

    @property
    def yf_ticker(self) -> str:
        """Provider form. Already-suffixed symbols are left alone rather than double-suffixed."""
        return to_provider_ticker(self.symbol)


def to_provider_ticker(symbol: str) -> str:
    """`RELIANCE` → `RELIANCE.NS`; `RELIANCE.NS` → `RELIANCE.NS`."""
    cleaned = symbol.strip().upper()
    if cleaned.endswith(PROVIDER_SUFFIXES):
        return cleaned
    return f"{cleaned}{NSE_SUFFIX}"


def from_provider_ticker(ticker: str) -> str:
    """`RELIANCE.NS` → `RELIANCE`."""
    cleaned = ticker.strip().upper()
    for suffix in PROVIDER_SUFFIXES:
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)]
    return cleaned
