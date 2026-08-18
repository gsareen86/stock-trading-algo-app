"""Replaying the strategies over history.

Positions come from the **real `Ledger`**, pointed at an in-memory database. Not a
`BacktestPortfolio` with its own averaging logic: the predecessor had three position ledgers
that disagreed, and a fourth that only ran in backtests would be the worst of them, because it
would be the one deciding whether a strategy looks good.

Results are per strategy and there is deliberately no aggregate across them — four independent
verdicts do not compose into one portfolio unless something decides how to allocate between
them, and that decision is the confluence scorecard with a chart attached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backtest.asof import AsOfPriceSource, first_bar_after
from app.books.ledger import Ledger
from app.domain.instrument import Instrument
from app.domain.position import Book, FillSource, Side
from app.domain.verdict import Stance
from app.persistence.base import SQLITE_SCHEMA_TRANSLATE, Base
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry

log = logging.getLogger(__name__)

#: Bounds. A replay is tens of thousands of strategy evaluations; discovering its own runtime
#: is not a thing a request should do.
MAX_SYMBOLS = 50
MAX_SESSIONS = 500
MAX_EVALUATIONS = 20_000

#: What a backtest cannot account for. Attached to every result rather than written in a
#: document, because the number and the caveat get copied into a conversation together or the
#: caveat does not travel at all.
BIASES: tuple[str, ...] = (
    "survivorship: the universe is today's members — names delisted or removed since are "
    "absent, which flatters every strategy",
    "no charges: P&L is gross of brokerage, STT, stamp duty and GST",
    "no slippage or market impact: fills happen at the open in whatever size was requested",
    "one history: a single path through one market regime is not a distribution",
)


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    start: date
    end: date
    symbols: tuple[str, ...]
    #: Evaluate every Nth trading session. Daily is honest and slow; weekly is usually enough
    #: to see whether a strategy fires at all.
    step_sessions: int = 5
    #: Sessions to hold before an exit is considered, when no strategy rule closes it first.
    max_hold_sessions: int = 40
    capital_inr: float = 10_00_000.0
    position_inr: float = 1_00_000.0


@dataclass
class StrategyResult:
    """One strategy's outcome. Never combined with another's."""

    strategy_id: str
    verdicts: int = 0
    buy_signals: int = 0
    gate_blocks: int = 0
    trades_opened: int = 0
    trades_closed: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl: float = 0.0
    holding_days: list[int] = field(default_factory=list)

    @property
    def win_rate(self) -> float | None:
        closed = self.wins + self.losses
        return round(self.wins / closed * 100, 2) if closed else None

    @property
    def average_hold_days(self) -> float | None:
        if not self.holding_days:
            return None
        return round(sum(self.holding_days) / len(self.holding_days), 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "verdicts": self.verdicts,
            "buy_signals": self.buy_signals,
            # How often a hard gate stopped an assessment — the question a live platform
            # cannot answer, and half the reason to run this at all.
            "gate_blocks": self.gate_blocks,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_pct": self.win_rate,
            "gross_pnl": round(self.gross_pnl, 2),
            "average_hold_days": self.average_hold_days,
            "charges_included": False,
        }


@dataclass
class BacktestReport:
    config: dict[str, Any]
    sessions: int
    evaluations: int
    results: dict[str, StrategyResult] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "sessions": self.sessions,
            "evaluations": self.evaluations,
            # Per strategy, side by side. There is no combined curve — see the module
            # docstring for why that is a decision rather than an omission.
            "results": {k: v.as_dict() for k, v in sorted(self.results.items())},
            "biases": list(BIASES),
            "notes": self.notes,
        }


def in_memory_ledger() -> Ledger:
    """A real `Ledger` over a throwaway database.

    The same class, the same `derive_position` fold, the same oversell guard and long-only
    clamp — so a backtest cannot disagree with the book about what a position is.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True).execution_options(
        # SQLite has no schemas, so the `trading` namespace is translated away — the same
        # translation `make_engine` applies for dev, and the reason one model definition
        # serves both dialects.
        schema_translate_map=SQLITE_SCHEMA_TRANSLATE
    )
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
    return Ledger(sessionmaker(bind=engine, expire_on_commit=False, future=True))


@dataclass(frozen=True, slots=True)
class _Open:
    """A position this run opened, and what it needs to close one."""

    strategy_id: str
    ticker: str
    opened_on: date
    quantity: int


def run(
    config: BacktestConfig,
    price_source,
    registry: StrategyRegistry,
    calendar,
    fundamentals_source=None,
) -> BacktestReport:
    """Walk trading sessions, evaluate, and act at the next open."""
    sessions = _sessions(calendar, config.start, config.end)[:MAX_SESSIONS]
    symbols = config.symbols[:MAX_SYMBOLS]
    strategy_ids = registry.ids()

    report = BacktestReport(
        config={
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
            "symbols": list(symbols),
            "step_sessions": config.step_sessions,
            "max_hold_sessions": config.max_hold_sessions,
        },
        sessions=len(sessions),
        evaluations=0,
        results={sid: StrategyResult(strategy_id=sid) for sid in strategy_ids},
    )
    if not sessions or not symbols:
        report.notes.append("nothing to replay: no trading sessions or no symbols")
        return report

    if config.step_sessions > 1:
        # Exits are evaluated on stepped sessions only, so the hold limit is a floor rather
        # than a bound — a position can be held up to step_sessions past it. Said here because
        # a reported average hold longer than the configured limit otherwise looks like a bug.
        report.notes.append(
            f"exits are checked every {config.step_sessions} sessions, so holds can run up to "
            f"{config.step_sessions} sessions past the {config.max_hold_sessions}-session limit"
        )

    ledger = in_memory_ledger()
    open_positions: dict[tuple[str, str], _Open] = {}
    # Full history once per symbol; the as-of wrapper truncates per session rather than
    # refetching, which is the difference between a minute and an afternoon.
    histories = {s: price_source.history(Instrument(s), interval="1d", lookback_days=1500)
                 for s in symbols}

    for index in range(0, len(sessions), max(1, config.step_sessions)):
        today = sessions[index]
        if report.evaluations >= MAX_EVALUATIONS:
            report.notes.append(f"stopped at the {MAX_EVALUATIONS} evaluation bound")
            break

        as_of_source = AsOfPriceSource(inner=price_source, as_of=today)
        context = StrategyContext(
            price_source=as_of_source,
            fundamentals_source=fundamentals_source,
            now=lambda t=today: datetime.combine(t, time(15, 30)),
        )

        for symbol in symbols:
            instrument = Instrument(symbol)
            series = histories.get(symbol)
            if series is None or series.is_empty:
                continue

            _close_due(
                config, ledger, report, open_positions, symbol, series, today, sessions, index
            )

            for strategy_id in strategy_ids:
                definition = registry.get(strategy_id)
                if definition is None:  # pragma: no cover
                    continue
                try:
                    verdict = definition.strategy.evaluate(instrument, context)
                except Exception as exc:
                    log.warning("%s failed on %s at %s: %s", strategy_id, symbol, today, exc)
                    continue

                report.evaluations += 1
                result = report.results[strategy_id]
                result.verdicts += 1
                if not verdict.gates_passed:
                    result.gate_blocks += 1
                if verdict.stance is not Stance.BUY:
                    continue

                result.buy_signals += 1
                if (strategy_id, symbol) in open_positions:
                    continue

                # The fill is at the *next* session's open: the decision did not exist until
                # this bar closed, so it could not have been acted on at this bar's close.
                fill = first_bar_after(series, today)
                if fill is None:
                    continue
                fill_date, fill_price = fill
                quantity = int(config.position_inr // fill_price)
                if quantity < 1:
                    continue

                ledger.fill(
                    Book.SWING,
                    symbol,
                    Side.BUY,
                    quantity,
                    fill_price,
                    executed_at=datetime.combine(fill_date, time(9, 15)),
                    source=FillSource.BACKTEST,
                    strategy_id=strategy_id,
                )
                open_positions[(strategy_id, symbol)] = _Open(
                    strategy_id, symbol, fill_date, quantity
                )
                result.trades_opened += 1

    _close_remaining(config, ledger, report, open_positions, histories, sessions)
    return report


def _sessions(calendar, start: date, end: date) -> list[date]:
    """Trading days only.

    Evaluating on a Sunday produces verdicts nobody could have acted on and inflates the count
    of opportunities.
    """
    days: list[date] = []
    cursor = start
    while cursor <= end:
        try:
            trading = calendar.is_trading_day(cursor)
        except Exception:  # pragma: no cover - calendar is contracted not to raise
            trading = cursor.weekday() < 5
        if trading:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _close_due(
    config: BacktestConfig,
    ledger: Ledger,
    report: BacktestReport,
    open_positions: dict[tuple[str, str], _Open],
    symbol: str,
    series,
    today: date,
    sessions: list[date],
    index: int,
) -> None:
    """Close anything that has been held past the hold limit."""
    for key in list(open_positions):
        strategy_id, held_symbol = key
        if held_symbol != symbol:
            continue
        position = open_positions[key]
        held_sessions = sum(1 for d in sessions[: index + 1] if d > position.opened_on)
        if held_sessions < config.max_hold_sessions:
            continue

        exit_bar = first_bar_after(series, today)
        if exit_bar is None:
            continue
        _record_exit(ledger, report, open_positions, key, exit_bar)


def _close_remaining(
    config: BacktestConfig,
    ledger: Ledger,
    report: BacktestReport,
    open_positions: dict[tuple[str, str], _Open],
    histories: dict,
    sessions: list[date],
) -> None:
    """Mark everything still open to the last session, so results are not half-counted."""
    if not sessions:
        return
    final = sessions[-1]
    for key in list(open_positions):
        _, symbol = key
        series = histories.get(symbol)
        if series is None or series.is_empty:
            open_positions.pop(key, None)
            continue
        from app.backtest.asof import last_bar_on_or_before

        last = last_bar_on_or_before(series, final)
        if last is None:
            open_positions.pop(key, None)
            continue
        _record_exit(ledger, report, open_positions, key, last)
        report.notes.append(f"{symbol} closed at the end of the window, not by a rule")


def _record_exit(
    ledger: Ledger,
    report: BacktestReport,
    open_positions: dict[tuple[str, str], _Open],
    key: tuple[str, str],
    bar: tuple[date, float],
) -> None:
    position = open_positions.pop(key)
    exit_date, exit_price = bar
    before = ledger.position(Book.SWING, position.ticker).realised_pnl

    ledger.fill(
        Book.SWING,
        position.ticker,
        Side.SELL,
        position.quantity,
        exit_price,
        executed_at=datetime.combine(exit_date, time(9, 15)),
        source=FillSource.BACKTEST,
        strategy_id=position.strategy_id,
    )

    realised = ledger.position(Book.SWING, position.ticker).realised_pnl - before
    result = report.results[position.strategy_id]
    result.trades_closed += 1
    result.gross_pnl += realised
    result.holding_days.append((exit_date - position.opened_on).days)
    if realised > 0:
        result.wins += 1
    elif realised < 0:
        result.losses += 1
