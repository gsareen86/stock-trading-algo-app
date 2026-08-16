"""Instruments and the symbol forms they wear.

An NSE symbol (`RELIANCE`) is what the platform reasons about. `RELIANCE.NS` is a yfinance
artefact. Keeping that translation inside the data source means the provider's naming never
leaks into strategy code — the same reason `PriceSeries` lowercases yfinance's column
capitalisation.

Indices are a second symbol family, not a special case of the first: yfinance addresses them
by a caret-prefixed code (`^NSEI` for the Nifty 50, `^CNXIT` for the IT sector index) with no
`.NS`/`.BO` suffix at all. This was found live rather than designed for — every strategy test
before real data used a fake price source keyed by the raw symbol string, so nothing exercised
the actual translation. Against yfinance, the untranslated benchmark instrument became
`NIFTY50.NS`, which does not exist, and every relative-strength criterion built on it failed
silently rather than erroring, because that criterion's own contract is "unavailable is a
failed comparison, not an exception" (see `market-data-foundation`). The fix belongs here, at
the one seam every symbol crosses, rather than as a special case in each caller.
"""

from __future__ import annotations

from dataclasses import dataclass

#: yfinance suffixes: NSE and BSE respectively.
NSE_SUFFIX = ".NS"
BSE_SUFFIX = ".BO"
PROVIDER_SUFFIXES = (NSE_SUFFIX, BSE_SUFFIX)

#: Index tickers are already in provider form — caret-prefixed, unsuffixed — and must never
#: be treated as a bare NSE equity code needing `.NS` appended.
INDEX_PREFIX = "^"


@dataclass(frozen=True, slots=True)
class Instrument:
    """One tradable name: an NSE/BSE equity, or an index.

    ``symbol`` is the bare NSE code for an equity (no provider suffix), or the caret-prefixed
    provider code for an index — the latter has no other form to be bare *of*.
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
    def is_index(self) -> bool:
        return self.symbol.startswith(INDEX_PREFIX)

    @property
    def yf_ticker(self) -> str:
        """Provider form. Already-suffixed symbols and indices are left alone."""
        return to_provider_ticker(self.symbol)


def to_provider_ticker(symbol: str) -> str:
    """`RELIANCE` → `RELIANCE.NS`; `RELIANCE.NS` → `RELIANCE.NS`; `^NSEI` → `^NSEI`."""
    cleaned = symbol.strip().upper()
    if cleaned.startswith(INDEX_PREFIX) or cleaned.endswith(PROVIDER_SUFFIXES):
        return cleaned
    return f"{cleaned}{NSE_SUFFIX}"


def from_provider_ticker(ticker: str) -> str:
    """`RELIANCE.NS` → `RELIANCE`; `^NSEI` → `^NSEI` (indices have no suffix to strip)."""
    cleaned = ticker.strip().upper()
    if cleaned.startswith(INDEX_PREFIX):
        return cleaned
    for suffix in PROVIDER_SUFFIXES:
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)]
    return cleaned
