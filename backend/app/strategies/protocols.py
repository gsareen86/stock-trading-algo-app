"""The strategy seam.

Mirrors the tool registry deliberately: two registries with different shapes would be two
things to learn, and one pattern used twice is one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.data.fundamentals import FundamentalsSource
from app.data.protocols import PriceSource
from app.domain.instrument import Instrument
from app.domain.verdict import Verdict

#: Index the relative-strength criterion compares against. `^NSEI` is yfinance's actual Nifty
#: 50 ticker — a caret-prefixed index code, not an NSE equity symbol, so it is never suffixed.
DEFAULT_BENCHMARK = Instrument("^NSEI")

#: The broad market, 500 names rather than 50. Added by `research-data-sources` because the
#: platform had no way to read it before: NSE publishes it as `NIFTY 500` and yfinance as
#: `^CRSLDX`, and nothing here knew either name.
#:
#: It is the fairer benchmark for sector relative strength — a sector measured against fifty
#: large caps is partly being measured against a size effect. It is *not* the default, because
#: changing what every existing relative-strength criterion compares against is a change to
#: what those strategies mean, and that belongs in a change about strategies.
BROAD_BENCHMARK = Instrument("^CRSLDX")


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Collaborators handed to a strategy.

    Injected rather than imported, so a strategy is testable against a deterministic price
    source and cannot quietly acquire its own.
    """

    price_source: PriceSource
    benchmark: Instrument = DEFAULT_BENCHMARK
    #: Only the fundamental strategy needs this. Absent is a legitimate state — for the
    #: price-only strategies it is simply irrelevant, and for the fundamental one its absence
    #: is a failed gate rather than a crash.
    fundamentals_source: FundamentalsSource | None = None
    now: Callable[[], datetime] | None = None
    #: Strategy-specific overrides, keyed by strategy id.
    options: dict[str, dict] = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    """Produces one independent verdict for one instrument.

    ``evaluate`` returns a `Verdict` even when the instrument cannot be assessed — that case is
    a verdict with a failing hard gate, because "I could not assess this, and here is why" is
    information a reader wants. Returning ``None`` or raising would throw it away.
    """

    def evaluate(self, instrument: Instrument, context: StrategyContext) -> Verdict: ...


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """What a strategy package exports."""

    id: str
    name: str
    description: str
    strategy: Strategy
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("_", "").isalnum():
            raise ValueError(f"strategy id must be alphanumeric/underscore, got {self.id!r}")


@dataclass(frozen=True, slots=True)
class StrategyLoadFailure:
    module: str
    error: str
