"""Replaying the strategies over history — as they are actually meant to be traded.

A BUY is not an instruction to buy at tomorrow's open. Every strategy that publishes a plan
says *where* to buy (a breakout pivot), *where* it is wrong (a stop) and *when* to leave (its
exit rule). The replay trades exactly that:

* **Entry** is a buy-stop at the plan's entry, live for ``order_valid_sessions``. It fills at
  the open when price gaps through it, at the entry level when the session trades through it,
  and is skipped when the open is already more than ``max_chase_pct`` above it — chasing an
  extended breakout is not the method. An order whose stop is traded through before it
  triggers is withdrawn: the setup failed. A BUY with no plan is counted and not traded.
* **Stops** are checked every session against the low, filling at the open on a gap.
* **Exits** are the strategy's own rule (`app.backtest.exits`), the buying strategy turning
  AVOID on an evaluation session (the platform's ``thesis_broken`` insight), or a maximum hold.
  A rule or thesis exit decided on a close fills at the next open.
* **Measurement** is per trade against a benchmark over the same sessions, with an explicit
  cost model, and broken down by the conviction the verdict carried.

Positions come from the **real `Ledger`**, pointed at an in-memory database — one per strategy,
because two strategies holding the same name are two positions, and a shared book would fold
them into one average cost.

Results are per strategy and there is deliberately no aggregate across them — four independent
verdicts do not compose into one portfolio unless something decides how to allocate between
them, and that decision is the confluence scorecard with a chart attached.

Symbols never interact (each position is one strategy on one name, sized independently), so a
long replay can be split across processes by symbol with ``workers > 1``.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backtest.asof import (
    LIVE_MIN_LOOKBACK_DAYS,
    AsOfFundamentalsSource,
    ReplayPriceSource,
    session_dates,
)
from app.backtest.exits import EXIT_RULES
from app.books.ledger import Ledger
from app.core.clock import IST, now_utc
from app.data.sectors import all_sector_indices
from app.domain.instrument import Instrument
from app.domain.position import Book, FillSource, Side
from app.domain.verdict import Stance
from app.persistence.base import SQLITE_SCHEMA_TRANSLATE, Base
from app.strategies.protocols import DEFAULT_BENCHMARK, StrategyContext
from app.strategies.registry import StrategyRegistry

log = logging.getLogger(__name__)

#: Bounds. A replay is many strategy evaluations; discovering its own runtime is not a thing a
#: request should do. The API applies tighter bounds of its own; the command line uses these.
MAX_SYMBOLS = 750
MAX_SESSIONS = 1_500
MAX_EVALUATIONS = 2_000_000

#: Indian equity delivery, round trip: STT 0.1% on each side, stamp duty 0.015% on the buy,
#: exchange, SEBI and GST charges of a few thousandths of a percent, and a depository charge on
#: the sell. About 0.24% on a ₹1 lakh position at zero brokerage; rounded up, and configurable.
DEFAULT_ROUND_TRIP_COST_PCT = 0.25
#: Slippage per fill, in basis points. Breakout entries fill into strength, so this is not zero.
DEFAULT_SLIPPAGE_BPS = 10.0
DEFAULT_EXCESS_BENCHMARK = "^CRSLDX"

EntryMode = Literal["plan", "next_open"]

#: Conviction bands, read only inside the strategy that produced the conviction.
CONVICTION_BANDS: tuple[tuple[int, int], ...] = ((0, 74), (75, 84), (85, 100))
#: Below this many closed trades a figure is flagged thin.
THIN_SAMPLE = 30
TRADES_IN_REPORT = 200

#: What a backtest cannot account for. Attached to every result rather than written in a
#: document, because the number and the caveat get copied into a conversation together or the
#: caveat does not travel at all.
BIASES: tuple[str, ...] = (
    "survivorship: the universe is today's members — names delisted or removed since are "
    "absent, which flatters every strategy",
    "charges and slippage are flat estimates (see cost_model), not a broker's contract note; "
    "gross figures exclude both charges and nothing else",
    "fills assume the order executes at the stated price in any size; on a session that both "
    "triggers an entry and trades through the stop, the stop is assumed hit",
    "fundamentals are visible only after their SEBI filing deadline, and providers keep a few "
    "years of quarters at most — earlier, the fundamental strategy cannot assess anything",
    "exit rules restate each plan's rule on daily bars; what they cannot test is listed in "
    "exit_rules",
    "one history: a single path through one set of market regimes is not a distribution",
)


# ── configuration and results ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    start: date
    end: date
    symbols: tuple[str, ...]
    #: Evaluate every Nth trading session. Positions are still managed on every session.
    step_sessions: int = 5
    #: A position still open after this many sessions is closed at the next open.
    max_hold_sessions: int = 120
    capital_inr: float = 10_00_000.0
    position_inr: float = 1_00_000.0
    #: ``plan``: buy-stop at the plan's entry. ``next_open``: buy the next open on any BUY,
    #: the previous behaviour, kept so the two can be compared.
    entry_mode: EntryMode = "plan"
    order_valid_sessions: int = 10
    max_chase_pct: float = 5.0
    round_trip_cost_pct: float = DEFAULT_ROUND_TRIP_COST_PCT
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS
    #: Index each trade's excess return is measured against.
    benchmark: str = DEFAULT_EXCESS_BENCHMARK
    #: Symbol -> sector, so sector-aware strategies can place a name. Without it
    #: Brahma-Vishnu-Mahesh cannot rank a name's sector and always fails that criterion.
    sectors: dict[str, str] = field(default_factory=dict)
    workers: int = 1

    def public(self) -> dict[str, Any]:
        body = asdict(self)
        body["start"] = self.start.isoformat()
        body["end"] = self.end.isoformat()
        body["symbols"] = list(self.symbols)
        body["sectors_known"] = sum(1 for s in self.symbols if self.sectors.get(s))
        del body["sectors"]
        return body


@dataclass(frozen=True, slots=True)
class TradeRecord:
    strategy_id: str
    symbol: str
    conviction: int
    signal_date: date
    entry_date: date
    entry_price: float
    stop: float | None
    exit_date: date
    exit_price: float
    exit_reason: str
    quantity: int
    sessions_held: int
    gross_pnl_inr: float
    return_pct: float
    net_return_pct: float
    r_multiple: float | None
    benchmark_return_pct: float | None
    excess_pp: float | None

    def as_dict(self) -> dict[str, Any]:
        body = asdict(self)
        for key in ("signal_date", "entry_date", "exit_date"):
            body[key] = body[key].isoformat()
        return body


@dataclass
class StrategyResult:
    """One strategy's outcome. Never combined with another's."""

    strategy_id: str
    verdicts: int = 0
    buy_signals: int = 0
    gate_blocks: int = 0
    buy_without_plan: int = 0
    orders_placed: int = 0
    orders_filled: int = 0
    orders_expired: int = 0
    orders_invalidated: int = 0
    skipped_extended: int = 0
    trades: list[TradeRecord] = field(default_factory=list)

    # Kept for the surfaces that already read them.
    @property
    def trades_opened(self) -> int:
        return self.orders_filled

    @property
    def trades_closed(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.gross_pnl_inr > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.gross_pnl_inr < 0)

    @property
    def gross_pnl(self) -> float:
        return sum(t.gross_pnl_inr for t in self.trades)

    @property
    def win_rate(self) -> float | None:
        closed = self.wins + self.losses
        return round(self.wins / closed * 100, 2) if closed else None

    @property
    def holding_days(self) -> list[int]:
        return [(t.exit_date - t.entry_date).days for t in self.trades]

    @property
    def average_hold_days(self) -> float | None:
        days = self.holding_days
        return round(sum(days) / len(days), 1) if days else None

    def merge(self, other: StrategyResult) -> None:
        for name in (
            "verdicts", "buy_signals", "gate_blocks", "buy_without_plan", "orders_placed",
            "orders_filled", "orders_expired", "orders_invalidated", "skipped_extended",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.trades.extend(other.trades)

    def as_dict(self) -> dict[str, Any]:
        recent = sorted(self.trades, key=lambda t: (t.entry_date, t.symbol), reverse=True)
        return {
            "strategy_id": self.strategy_id,
            "verdicts": self.verdicts,
            "buy_signals": self.buy_signals,
            # How often a hard gate stopped an assessment — the question a live platform
            # cannot answer, and half the reason to run this at all.
            "gate_blocks": self.gate_blocks,
            "buy_without_plan": self.buy_without_plan,
            "orders_placed": self.orders_placed,
            "orders_filled": self.orders_filled,
            "orders_expired": self.orders_expired,
            "orders_invalidated": self.orders_invalidated,
            "skipped_extended": self.skipped_extended,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_pct": self.win_rate,
            "gross_pnl": round(self.gross_pnl, 2),
            "average_hold_days": self.average_hold_days,
            "charges_included": False,
            "performance": trade_stats(self.trades),
            "by_conviction": [
                {"band": f"{low}-{high}", **trade_stats(
                    [t for t in self.trades if low <= t.conviction <= high]
                )}
                for low, high in CONVICTION_BANDS
            ],
            "exit_reasons": dict(Counter(_reason_kind(t.exit_reason) for t in self.trades)),
            "trade_log": [t.as_dict() for t in recent[:TRADES_IN_REPORT]],
        }


def _reason_kind(reason: str) -> str:
    return reason.split(":", 1)[0]


def trade_stats(trades: list[TradeRecord]) -> dict[str, Any]:
    """Distribution of one strategy's closed trades. Never called on more than one strategy."""
    n = len(trades)
    if not n:
        return {"closed": 0, "thin": True}

    def r(value: float | None, digits: int = 2) -> float | None:
        return None if value is None else round(value, digits)

    net = [t.net_return_pct for t in trades]
    gross = [t.return_pct for t in trades]
    excess = [t.excess_pp for t in trades if t.excess_pp is not None]
    net_excess = [e - _cost(t) for t, e in ((t, t.excess_pp) for t in trades) if e is not None]
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    gains = sum(x for x in net if x > 0)
    pains = -sum(x for x in net if x < 0)
    se = statistics.stdev(net_excess) / math.sqrt(len(net_excess)) if len(net_excess) > 1 else None
    return {
        "closed": n,
        "win_rate_pct": r(100.0 * sum(x > 0 for x in net) / n, 1),
        "mean_return_pct": r(statistics.fmean(gross)),
        "mean_net_return_pct": r(statistics.fmean(net)),
        "median_net_return_pct": r(statistics.median(net)),
        "best_pct": r(max(net)),
        "worst_pct": r(min(net)),
        "profit_factor": r(gains / pains) if pains > 0 else None,
        "mean_r_multiple": r(statistics.fmean(rs)) if rs else None,
        "mean_excess_pp": r(statistics.fmean(excess)) if excess else None,
        "mean_net_excess_pp": r(statistics.fmean(net_excess)) if net_excess else None,
        "net_excess_se_pp": r(se),
        "beat_benchmark_pct": (
            r(100.0 * sum(e > 0 for e in net_excess) / len(net_excess), 1) if net_excess else None
        ),
        "mean_sessions_held": r(statistics.fmean(t.sessions_held for t in trades), 1),
        "thin": n < THIN_SAMPLE,
    }


def _cost(trade: TradeRecord) -> float:
    return trade.return_pct - trade.net_return_pct


@dataclass
class BacktestReport:
    config: dict[str, Any]
    sessions: int
    evaluations: int
    results: dict[str, StrategyResult] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    cost_model: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "sessions": self.sessions,
            "evaluations": self.evaluations,
            # Per strategy, side by side. There is no combined curve — see the module
            # docstring for why that is a decision rather than an omission.
            "results": {k: v.as_dict() for k, v in sorted(self.results.items())},
            "exit_rules": [
                EXIT_RULES[sid].describe() for sid in sorted(self.results) if sid in EXIT_RULES
            ],
            "cost_model": self.cost_model,
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


# ── one symbol, start to finish ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Bars:
    dates: list[date]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    position: dict[date, int]

    @classmethod
    def of(cls, series) -> _Bars | None:
        if series is None or series.is_empty:
            return None
        dates = session_dates(series)
        frame = series.frame
        return cls(
            dates=dates,
            opens=[float(x) for x in frame["open"]],
            highs=[float(x) for x in frame["high"]],
            lows=[float(x) for x in frame["low"]],
            closes=[float(x) for x in frame["close"]],
            position={d: i for i, d in enumerate(dates)},
        )

    def open_or_prior_close(self, i: int) -> float | None:
        if self.opens[i] > 0:
            return self.opens[i]
        return self.closes[i - 1] if i > 0 and self.closes[i - 1] > 0 else None


@dataclass
class _Order:
    conviction: int
    signal_date: date
    entry: float | None  # None: buy at the next open (``next_open`` mode)
    stop: float | None
    placed_k: int
    expires_k: int


@dataclass
class _Holding:
    conviction: int
    signal_date: date
    entry_date: date
    entry_price: float
    stop: float | None
    quantity: int
    entry_k: int
    entry_bar: int
    exit_due: str | None = None


@dataclass
class _SymbolTask:
    symbol: str
    sector: str | None
    series: Any
    fundamentals: Any = None


@dataclass
class _Shared:
    """What every symbol's replay reads: sessions, indices, configuration, strategies."""

    config: BacktestConfig
    sessions: list[date]
    index_histories: dict[str, Any]
    strategy_ids: tuple[str, ...]
    registry: StrategyRegistry | None = None


def _slip(price: float, bps: float, up: bool) -> float:
    factor = 1 + bps / 10_000.0 if up else 1 - bps / 10_000.0
    return price * factor


def _simulate_symbol(task: _SymbolTask, shared: _Shared) -> tuple[dict[str, StrategyResult], int]:
    ledgers = {sid: in_memory_ledger() for sid in shared.strategy_ids}
    try:
        return _simulate_with(task, shared, ledgers)
    finally:
        for ledger in ledgers.values():
            ledger._sessions.kw["bind"].dispose()


def _simulate_with(
    task: _SymbolTask, shared: _Shared, ledgers: dict[str, Ledger]
) -> tuple[dict[str, StrategyResult], int]:
    config = shared.config
    registry = shared.registry or StrategyRegistry.discover()
    results = {sid: StrategyResult(strategy_id=sid) for sid in shared.strategy_ids}
    bars = _Bars.of(task.series)
    if bars is None:
        return results, 0

    instrument = Instrument(task.symbol, sector=task.sector)
    histories = {**shared.index_histories, task.symbol: task.series}
    replay = ReplayPriceSource(histories)
    excess_bench = _Bars.of(shared.index_histories.get(config.benchmark))
    strategy_bench = shared.index_histories.get(DEFAULT_BENCHMARK.symbol)
    bench_dates = session_dates(strategy_bench) if strategy_bench is not None else []

    from app.data.fundamentals import StaticFundamentalsSource

    fundamentals = (
        StaticFundamentalsSource({task.symbol: task.fundamentals})
        if task.fundamentals is not None
        else None
    )
    orders: dict[str, _Order] = {}
    holdings: dict[str, _Holding] = {}
    evaluations = 0

    def close(sid: str, hold: _Holding, k: int, i: int, price: float, reason: str,
              at_open: bool) -> None:
        exit_price = _slip(price, config.slippage_bps, up=False)
        ledger = ledgers[sid]
        before = ledger.position(Book.SWING, task.symbol).realised_pnl
        ledger.fill(
            Book.SWING, task.symbol, Side.SELL, hold.quantity, exit_price,
            executed_at=_ist_stamp(bars.dates[i]), source=FillSource.BACKTEST, strategy_id=sid,
        )
        realised = ledger.position(Book.SWING, task.symbol).realised_pnl - before
        ret = (exit_price / hold.entry_price - 1) * 100
        risk = hold.entry_price - hold.stop if hold.stop is not None else None
        bench_ret = _bench_return(excess_bench, hold.entry_date, bars.dates[i], at_open)
        results[sid].trades.append(
            TradeRecord(
                strategy_id=sid,
                symbol=task.symbol,
                conviction=hold.conviction,
                signal_date=hold.signal_date,
                entry_date=hold.entry_date,
                entry_price=round(hold.entry_price, 4),
                stop=hold.stop,
                exit_date=bars.dates[i],
                exit_price=round(exit_price, 4),
                exit_reason=reason,
                quantity=hold.quantity,
                sessions_held=k - hold.entry_k,
                gross_pnl_inr=round(realised, 2),
                return_pct=round(ret, 4),
                net_return_pct=round(ret - config.round_trip_cost_pct, 4),
                r_multiple=(
                    round((exit_price - hold.entry_price) / risk, 3) if risk and risk > 0 else None
                ),
                benchmark_return_pct=None if bench_ret is None else round(bench_ret, 4),
                excess_pp=None if bench_ret is None else round(ret - bench_ret, 4),
            )
        )
        del holdings[sid]

    for k, day in enumerate(shared.sessions):
        i = bars.position.get(day)
        if i is None:
            continue  # the name did not trade this session
        o, h, low, c = bars.opens[i], bars.highs[i], bars.lows[i], bars.closes[i]
        if o <= 0:
            o = bars.open_or_prior_close(i) or c

        # 1. Open positions: exits decided yesterday fill at the open; then the stop.
        for sid, hold in list(holdings.items()):
            if hold.exit_due:
                close(sid, hold, k, i, o, hold.exit_due, at_open=True)
            elif hold.stop is not None and o <= hold.stop:
                close(sid, hold, k, i, o, "stop: gapped below", at_open=True)
            elif hold.stop is not None and low <= hold.stop:
                close(sid, hold, k, i, hold.stop, "stop: traded through", at_open=False)

        # 2. Working orders placed on an earlier session.
        for sid, order in list(orders.items()):
            if k <= order.placed_k:
                continue
            if k > order.expires_k:
                results[sid].orders_expired += 1
                del orders[sid]
                continue
            fill: float | None = None
            if order.entry is None:
                fill = o
            elif o > order.entry * (1 + config.max_chase_pct / 100.0):
                results[sid].skipped_extended += 1
                del orders[sid]
                continue
            elif o >= order.entry:
                fill = o
            elif h >= order.entry:
                fill = order.entry
            elif order.stop is not None and low <= order.stop:
                results[sid].orders_invalidated += 1
                del orders[sid]
                continue
            if fill is None:
                continue
            del orders[sid]
            price = _slip(fill, config.slippage_bps, up=True)
            quantity = int(config.position_inr // price)
            if quantity < 1:
                continue
            ledgers[sid].fill(
                Book.SWING, task.symbol, Side.BUY, quantity, price,
                executed_at=_ist_stamp(day), source=FillSource.BACKTEST, strategy_id=sid,
            )
            results[sid].orders_filled += 1
            hold = _Holding(
                conviction=order.conviction, signal_date=order.signal_date, entry_date=day,
                entry_price=price, stop=order.stop, quantity=quantity, entry_k=k, entry_bar=i,
            )
            holdings[sid] = hold
            # The entry session's own low: with no intrabar order, assume the worst.
            if hold.stop is not None and low <= hold.stop:
                close(sid, hold, k, i, min(hold.stop, o) if o < hold.stop else hold.stop,
                      "stop: entry session", at_open=False)

        # 3. After the close: each strategy's own exit rule, and the hold limit.
        if holdings:
            frame = task.series.frame.iloc[max(0, i - 299): i + 1]
            bench_frame = None
            if strategy_bench is not None and bench_dates:
                from bisect import bisect_right

                end = bisect_right(bench_dates, day)
                bench_frame = strategy_bench.frame.iloc[max(0, end - 200): end]
            for sid, hold in holdings.items():
                if hold.exit_due:
                    continue
                rule = EXIT_RULES.get(sid)
                reason = rule.check(frame, bench_frame) if rule is not None else None
                if reason:
                    hold.exit_due = f"rule: {reason}"
                elif k - hold.entry_k >= config.max_hold_sessions:
                    hold.exit_due = f"max hold: {config.max_hold_sessions} sessions"

        # 4. Evaluation sessions: what each strategy now says.
        if k % max(1, config.step_sessions) != 0:
            continue
        context = StrategyContext(
            price_source=replay.at(day),
            fundamentals_source=(
                AsOfFundamentalsSource(inner=fundamentals, as_of=day) if fundamentals else None
            ),
            now=lambda d=day: datetime.combine(d, time(15, 30), tzinfo=IST),
        )
        for sid in shared.strategy_ids:
            definition = registry.get(sid)
            if definition is None:  # pragma: no cover
                continue
            try:
                verdict = definition.strategy.evaluate(instrument, context)
            except Exception as exc:
                log.warning("%s failed on %s at %s: %s", sid, task.symbol, day, exc)
                continue
            evaluations += 1
            result = results[sid]
            result.verdicts += 1
            if not verdict.gates_passed:
                result.gate_blocks += 1

            if sid in holdings:
                if verdict.stance is Stance.AVOID and not holdings[sid].exit_due:
                    holdings[sid].exit_due = "thesis broken: own strategy now AVOID"
                continue
            if verdict.stance is not Stance.BUY:
                continue
            result.buy_signals += 1
            if sid in orders:
                continue
            plan = verdict.plan
            if config.entry_mode == "next_open":
                entry, stop = None, (plan.stop if plan else None)
            elif plan is None:
                result.buy_without_plan += 1
                continue
            else:
                entry, stop = plan.entry, plan.stop
            orders[sid] = _Order(
                conviction=verdict.conviction, signal_date=day, entry=entry, stop=stop,
                placed_k=k,
                expires_k=k + (1 if entry is None else max(1, config.order_valid_sessions)),
            )
            result.orders_placed += 1

    # Whatever is still open is marked at the last close, and said to be.
    last_i = None
    for day in reversed(shared.sessions):
        last_i = bars.position.get(day)
        if last_i is not None:
            break
    if last_i is not None:
        for sid, hold in list(holdings.items()):
            close(sid, hold, len(shared.sessions) - 1, last_i, bars.closes[last_i],
                  "end of window: closed at the last close, not by a rule", at_open=False)
    return results, evaluations


def _ist_stamp(day: date) -> datetime:
    return datetime.combine(day, time(9, 15), tzinfo=IST)


def _bench_return(bench: _Bars | None, entry: date, exit_day: date, at_open: bool) -> float | None:
    if bench is None:
        return None
    a, b = bench.position.get(entry), bench.position.get(exit_day)
    if a is None or b is None:
        return None
    start = bench.open_or_prior_close(a)
    end = bench.open_or_prior_close(b) if at_open else bench.closes[b]
    if not start or not end:
        return None
    return (end / start - 1) * 100


# ── worker processes ───────────────────────────────────────────────────────────────────────

_WORKER_SHARED: _Shared | None = None


def _init_worker(shared: _Shared) -> None:
    global _WORKER_SHARED
    _WORKER_SHARED = shared


def _run_in_worker(task: _SymbolTask) -> tuple[dict[str, StrategyResult], int]:
    assert _WORKER_SHARED is not None
    return _simulate_symbol(task, _WORKER_SHARED)


# ── the run ────────────────────────────────────────────────────────────────────────────────


def _sessions(
    calendar, start: date, end: date, traded: set[date] | frozenset[date] = frozenset()
) -> tuple[list[date], set[int]]:
    """Trading sessions in the window, and the years the calendar could not answer for.

    The bundled holiday calendar covers only the years someone has entered, and refuses the
    rest rather than assuming them open. For those years the market's own record decides: a
    session is a day the index printed a bar. That is what a session *is*, so it needs no
    holiday list — only a benchmark history.
    """
    from app.data.protocols import CalendarNotCovered

    days: list[date] = []
    uncovered: set[int] = set()
    cursor = start
    while cursor <= end:
        try:
            if calendar.is_trading_day(cursor):
                days.append(cursor)
        except CalendarNotCovered:
            uncovered.add(cursor.year)
            if cursor in traded:
                days.append(cursor)
        cursor += timedelta(days=1)
    return days, uncovered


def run(
    config: BacktestConfig,
    price_source,
    registry: StrategyRegistry,
    calendar,
    fundamentals_source=None,
    on_progress=None,
) -> BacktestReport:
    """Replay every symbol and report per strategy."""
    symbols = tuple(dict.fromkeys(s.strip().upper() for s in config.symbols))[:MAX_SYMBOLS]
    strategy_ids = tuple(registry.ids())

    report = BacktestReport(
        config=config.public(),
        sessions=0,
        evaluations=0,
        results={sid: StrategyResult(strategy_id=sid) for sid in strategy_ids},
        cost_model={
            "round_trip_cost_pct": config.round_trip_cost_pct,
            "slippage_bps_per_fill": config.slippage_bps,
            "basis": (
                "delivery equity at zero brokerage: STT 0.1% each side, stamp duty 0.015% on "
                "the buy, exchange/SEBI/GST and a depository charge on the sell"
            ),
        },
    )
    if not symbols:
        report.notes.append("nothing to replay: no trading sessions or no symbols")
        return report

    # Enough history for the longest lookback before the first session, through the last.
    today = now_utc().astimezone(IST).date()
    lookback = (today - config.start).days + LIVE_MIN_LOOKBACK_DAYS + 30
    index_symbols = {DEFAULT_BENCHMARK.symbol, config.benchmark}
    index_symbols.update(s.ticker for s in all_sector_indices())
    instruments = [Instrument(s, sector=config.sectors.get(s)) for s in symbols]

    prefetch = getattr(price_source, "prefetch", None)
    if prefetch is not None:
        try:
            prefetch(
                [*instruments, *(Instrument(s) for s in sorted(index_symbols))],
                interval="1d",
                lookback_days=lookback,
            )
        except Exception as exc:
            log.warning("backtest prefetch failed; fetching per symbol: %s", exc)

    def fetch(instrument: Instrument):
        try:
            series = price_source.history(instrument, interval="1d", lookback_days=lookback)
        except Exception as exc:  # pragma: no cover - sources are contracted not to raise
            log.warning("history failed for %s: %s", instrument.symbol, exc)
            return None
        return None if series is None or series.is_empty else series

    index_histories = {
        s: series for s in sorted(index_symbols) if (series := fetch(Instrument(s))) is not None
    }
    market = index_histories.get(DEFAULT_BENCHMARK.symbol) or index_histories.get(
        config.benchmark
    )
    traded = set(session_dates(market)) if market is not None else set()
    sessions, from_market = _sessions(calendar, config.start, config.end, traded)
    sessions = sessions[:MAX_SESSIONS]
    report.sessions = len(sessions)
    if not sessions:
        report.notes.append("nothing to replay: no trading sessions or no symbols")
        return report
    if from_market:
        report.notes.append(
            "the holiday calendar does not cover "
            + ", ".join(str(y) for y in sorted(from_market))
            + ": sessions in those years are the days the market index actually traded"
        )
    if config.benchmark not in index_histories:
        report.notes.append(f"benchmark {config.benchmark} unavailable: excess returns absent")

    per_symbol = math.ceil(len(sessions) / max(1, config.step_sessions)) * len(strategy_ids)
    if per_symbol * len(symbols) > MAX_EVALUATIONS:
        keep = max(1, MAX_EVALUATIONS // max(1, per_symbol))
        report.notes.append(
            f"evaluation bound: replaying the first {keep} of {len(symbols)} symbols"
        )
        instruments = instruments[:keep]
    if not config.sectors:
        report.notes.append(
            "no sectors supplied: brahma_vishnu_mahesh cannot rank a name's sector and fails "
            "that criterion on every evaluation"
        )

    tasks: list[_SymbolTask] = []
    unpriced: list[str] = []
    for instrument in instruments:
        series = fetch(instrument)
        if series is None:
            unpriced.append(instrument.symbol)
            continue
        quarters = None
        if fundamentals_source is not None:
            try:
                quarters = fundamentals_source.quarterly(instrument)
            except Exception as exc:  # pragma: no cover
                log.debug("fundamentals failed for %s: %s", instrument.symbol, exc)
        tasks.append(_SymbolTask(instrument.symbol, instrument.sector, series, quarters))
    if unpriced:
        report.notes.append(f"{len(unpriced)} symbol(s) had no price history: "
                            + ", ".join(unpriced[:20]))

    shared = _Shared(config=config, sessions=sessions, index_histories=index_histories,
                     strategy_ids=strategy_ids, registry=registry)

    def absorb(outcome: tuple[dict[str, StrategyResult], int], done: int) -> None:
        per_strategy, evaluations = outcome
        report.evaluations += evaluations
        for sid, result in per_strategy.items():
            report.results[sid].merge(result)
        if on_progress is not None:
            on_progress(done, len(tasks))

    if config.workers > 1 and len(tasks) > 1:
        # Workers rediscover the registry rather than receive it: strategies are found by
        # import, which every process can do, and a registry need not be picklable.
        worker_shared = replace(shared, registry=None)
        with ProcessPoolExecutor(
            max_workers=config.workers, initializer=_init_worker, initargs=(worker_shared,)
        ) as pool:
            for done, outcome in enumerate(pool.map(_run_in_worker, tasks, chunksize=1), 1):
                absorb(outcome, done)
    else:
        for done, task in enumerate(tasks, 1):
            absorb(_simulate_symbol(task, shared), done)

    ended = sum(
        1 for r in report.results.values() for t in r.trades if t.exit_reason.startswith("end")
    )
    if ended:
        report.notes.append(f"{ended} position(s) closed at the end of the window, not by a rule")
    return report


def symbols_with_sectors(instruments: Iterable[Instrument]) -> tuple[tuple[str, ...], dict]:
    """(symbols, symbol -> sector) from a universe snapshot."""
    items = list(instruments)
    return (
        tuple(i.symbol for i in items),
        {i.symbol: i.sector for i in items if i.sector},
    )
