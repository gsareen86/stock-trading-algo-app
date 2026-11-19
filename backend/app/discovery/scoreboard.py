"""Signal scoreboard — what happened after each verdict a scan published.

Every completed discovery scan is persisted whole, so the platform already holds a dated record
of what each strategy said about every name. This module asks the one question that record was
never asked: **did it work?**

For each verdict it measures the forward return from the next tradable open over fixed holding
periods, against the benchmark the scan itself named, and groups the results by strategy, stance
and conviction band — the layout of a factor tear sheet (mean return by bucket, with its standard
error), applied to stances instead of factor quantiles.

Three rules carry the design:

* **Never across strategies.** Every row belongs to exactly one strategy. A BUY from Minervini
  and a BUY from Young Momentum are not pooled, because pooling them is the confluence scorecard
  measured after the fact. Comparing a strategy's BUYs with its own AVOIDs is the useful contrast,
  and it stays inside one strategy.
* **No lookahead in the entry.** A verdict formed from a scan cannot be acted on before the scan
  existed: entry is the first session open *after* the scan, or that same day's open when the
  scan finished before the market opened. The same rule the backtest runner follows.
* **New signals by default.** A name a strategy rates BUY for six weekly scans running is one
  decision, not six. Counting every repeat would multiply the sample with overlapping windows and
  make thin evidence look thick. ``signals="all"`` is available, and says what it is.

Nothing here reads or writes a verdict's stance or conviction: it measures prices after the fact.
"""

from __future__ import annotations

import logging
import math
import statistics
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Literal

from sqlalchemy import select

from app.core.clock import IST, now_utc
from app.domain.instrument import Instrument
from app.persistence.models import ScanEntry as ScanEntryRow
from app.persistence.models import ScanRun as ScanRunRow

log = logging.getLogger(__name__)

#: One trading week, about a month, about a quarter.
DEFAULT_HORIZONS: tuple[int, ...] = (5, 20, 60)
MAX_HORIZON_SESSIONS = 250
#: NSE's continuous session opens at 09:15 IST. A scan stamped before it was formed from the
#: previous session's bars, so that day's open was still available to act on.
SESSION_OPEN_IST = time(9, 15)
#: Below this many measured signals a row is flagged. Thirty is the usual floor at which a
#: standard error starts to describe the spread rather than the handful of names in it.
THIN_SAMPLE = 30
#: Default number of most recent completed scans considered.
DEFAULT_MAX_RUNS = 104
#: Conviction bands. Conviction is scoped to one strategy, so a band is only ever read inside the
#: strategy that produced it.
CONVICTION_BANDS: tuple[tuple[int, int], ...] = ((0, 39), (40, 59), (60, 74), (75, 84), (85, 100))
STANCES: tuple[str, ...] = ("BUY", "WATCH", "AVOID")
RECENT_LIMIT = 150

SignalFilter = Literal["new", "all"]
OutcomeStatus = Literal["measured", "pending", "unpriced"]

#: What this measurement cannot account for — attached to every result, as the backtest does,
#: because a number and its caveat travel together or the caveat does not travel.
BIASES: tuple[str, ...] = (
    "gross: brokerage, STT, stamp duty, exchange charges, GST and DP charges are not deducted — "
    "a small positive excess return can be zero or negative after costs",
    "fills at the next session's open in any size: no slippage, no market impact",
    "prices are split-adjusted but dividends are not added back, for the stock and for the "
    "benchmark price index alike",
    "overlapping windows: signals from consecutive scans share most of a 20- or 60-session "
    "window, so they are not independent observations — the standard error is optimistic, "
    "more so with signals='all'",
    "a name delisted or suspended after a scan has no forward bars and is reported as pending "
    "or unpriced rather than as a loss",
    "a short record is one market regime: a strategy that looks good over a few months of one "
    "kind of market has not been tested in another",
)


# ── records ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Signal:
    """One strategy's stance on one name, as published by one scan."""

    run_id: int
    strategy_id: str
    symbol: str
    stance: str
    conviction: int
    signalled_at: datetime
    benchmark: str
    #: True when the previous completed scan did not hold this strategy at this stance on this
    #: name — the first appearance of a decision rather than its repetition.
    is_new: bool
    plan_entry: float | None = None
    plan_stop: float | None = None


@dataclass(frozen=True, slots=True)
class HorizonOutcome:
    sessions: int
    exit_date: date | None = None
    exit_price: float | None = None
    return_pct: float | None = None
    benchmark_return_pct: float | None = None
    excess_pp: float | None = None
    #: Whether the plan's stop was traded through within the window. None when no plan stop.
    stop_touched: bool | None = None

    @property
    def measured(self) -> bool:
        return self.return_pct is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sessions": self.sessions,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "exit_price": self.exit_price,
            "return_pct": self.return_pct,
            "benchmark_return_pct": self.benchmark_return_pct,
            "excess_pp": self.excess_pp,
            "stop_touched": self.stop_touched,
        }


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    signal: Signal
    status: OutcomeStatus
    entry_date: date | None = None
    entry_price: float | None = None
    horizons: tuple[HorizonOutcome, ...] = ()
    reason: str | None = None

    def horizon(self, sessions: int) -> HorizonOutcome | None:
        return next((h for h in self.horizons if h.sessions == sessions), None)

    def as_dict(self) -> dict[str, Any]:
        s = self.signal
        return {
            "run_id": s.run_id,
            "strategy_id": s.strategy_id,
            "symbol": s.symbol,
            "stance": s.stance,
            "conviction": s.conviction,
            "signalled_at": s.signalled_at.isoformat(),
            "is_new": s.is_new,
            "benchmark": s.benchmark,
            "plan_entry": s.plan_entry,
            "plan_stop": s.plan_stop,
            "status": self.status,
            "reason": self.reason,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "entry_price": self.entry_price,
            "horizons": {str(h.sessions): h.as_dict() for h in self.horizons},
        }


# ── collecting signals from persisted scans ────────────────────────────────────────────────


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes for timezone-aware columns; storage is always UTC."""
    if moment is None:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _parse_instant(raw: Any, fallback: datetime | None) -> datetime | None:
    if isinstance(raw, str):
        try:
            return _aware(datetime.fromisoformat(raw))
        except ValueError:
            pass
    return _aware(fallback)


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def collect_signals(session_factory, *, max_runs: int = DEFAULT_MAX_RUNS) -> list[Signal]:
    """Every verdict from the most recent ``max_runs`` completed scans, oldest scan first.

    ``is_new`` compares each verdict with the immediately preceding completed scan only. A name
    that left the eligible set for a week and came back at BUY is a new decision, because nothing
    in between said BUY.
    """
    with session_factory() as session:
        runs = (
            session.execute(
                select(ScanRunRow)
                .where(ScanRunRow.outcome == "complete")
                .order_by(ScanRunRow.id.desc())
                .limit(max(1, max_runs))
            )
            .scalars()
            .all()
        )
        runs = sorted(runs, key=lambda r: r.id)
        run_ids = [r.id for r in runs]
        entries = (
            session.execute(
                select(ScanEntryRow)
                .where(ScanEntryRow.run_id.in_(run_ids))
                .order_by(ScanEntryRow.run_id, ScanEntryRow.id)
            )
            .scalars()
            .all()
            if run_ids
            else []
        )
        by_run: dict[int, list[ScanEntryRow]] = {}
        for row in entries:
            by_run.setdefault(row.run_id, []).append(row)
        run_meta = [
            (r.id, r.benchmark or "^CRSLDX", _aware(r.finished_at or r.started_at)) for r in runs
        ]
        payloads = {
            run_id: [(row.symbol, list(row.verdicts or [])) for row in by_run.get(run_id, [])]
            for run_id in run_ids
        }

    signals: list[Signal] = []
    previous: dict[tuple[str, str], str] = {}
    for run_id, benchmark, stamped in run_meta:
        current: dict[tuple[str, str], str] = {}
        for symbol, verdicts in payloads.get(run_id, []):
            for raw in verdicts:
                strategy_id = raw.get("strategy_id")
                stance = str(raw.get("stance", "")).upper()
                if not strategy_id or stance not in STANCES:
                    continue
                signalled_at = _parse_instant(raw.get("as_of"), stamped)
                if signalled_at is None:
                    continue
                key = (strategy_id, symbol)
                current[key] = stance
                plan = raw.get("plan") or {}
                signals.append(
                    Signal(
                        run_id=run_id,
                        strategy_id=strategy_id,
                        symbol=symbol,
                        stance=stance,
                        conviction=int(raw.get("conviction") or 0),
                        signalled_at=signalled_at,
                        benchmark=benchmark,
                        is_new=previous.get(key) != stance,
                        plan_entry=_float_or_none(plan.get("entry")),
                        plan_stop=_float_or_none(plan.get("stop")),
                    )
                )
        previous = current
    return signals


# ── measuring forward returns ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Bars:
    """A price series flattened to IST session dates.

    Bars are keyed by their IST calendar date rather than their UTC timestamp: a provider that
    stamps NSE sessions at midnight IST stores them at 18:30 UTC on the *previous* day, and a
    UTC date would shift every session by one. Converting to IST is correct for both midnight-UTC
    and midnight-IST stamps.
    """

    dates: list[date]
    opens: list[float]
    closes: list[float]
    lows: list[float]

    @classmethod
    def from_series(cls, series) -> _Bars | None:
        if series is None or getattr(series, "is_empty", True):
            return None
        frame = series.frame
        index = frame.index
        if index.tz is None:
            index = index.tz_localize("UTC")
        dates = [ts.date() for ts in index.tz_convert(IST)]
        return cls(
            dates=dates,
            opens=[float(x) for x in frame["open"]],
            closes=[float(x) for x in frame["close"]],
            lows=[float(x) for x in frame["low"]],
        )

    def position_of(self, day: date) -> int | None:
        i = bisect_left(self.dates, day)
        return i if i < len(self.dates) and self.dates[i] == day else None

    def open_on(self, i: int) -> float | None:
        """The session's open, or the prior close when a provider reports no usable open —
        index opens from free sources are sometimes zero or missing."""
        value = self.opens[i]
        if value > 0 and math.isfinite(value):
            return value
        if i > 0 and self.closes[i - 1] > 0:
            return self.closes[i - 1]
        return None


def entry_index(bars: _Bars, signalled_at: datetime) -> int | None:
    """Index of the first session whose open the signal could have traded."""
    local = signalled_at.astimezone(IST)
    day = local.date()
    if local.time() < SESSION_OPEN_IST:
        i = bisect_left(bars.dates, day)
    else:
        i = bisect_right(bars.dates, day)
    return i if i < len(bars.dates) else None


def _pct(after: float, before: float) -> float:
    return round((after / before - 1.0) * 100.0, 4)


def _measure_one(
    signal: Signal,
    bars: _Bars | None,
    bench: _Bars | None,
    horizons: Sequence[int],
) -> SignalOutcome:
    if bars is None:
        return SignalOutcome(signal=signal, status="unpriced", reason="no price history returned")

    start = entry_index(bars, signal.signalled_at)
    if start is None:
        return SignalOutcome(signal=signal, status="pending", reason="no session has opened since")
    entry_price = bars.open_on(start)
    if entry_price is None:
        return SignalOutcome(signal=signal, status="unpriced", reason="no usable entry price")
    entry_day = bars.dates[start]

    bench_start = bench.position_of(entry_day) if bench is not None else None
    bench_entry = (
        bench.open_on(bench_start) if bench is not None and bench_start is not None else None
    )

    results: list[HorizonOutcome] = []
    for sessions in horizons:
        end = start + sessions - 1
        if end >= len(bars.dates):
            results.append(HorizonOutcome(sessions=sessions))
            continue
        exit_price = bars.closes[end]
        exit_day = bars.dates[end]
        ret = _pct(exit_price, entry_price)

        bench_ret: float | None = None
        if bench is not None and bench_entry is not None:
            bench_end = bench.position_of(exit_day)
            if bench_end is not None and bench.closes[bench_end] > 0:
                bench_ret = _pct(bench.closes[bench_end], bench_entry)

        stop_touched: bool | None = None
        if signal.plan_stop is not None:
            stop_touched = min(bars.lows[start : end + 1]) <= signal.plan_stop

        results.append(
            HorizonOutcome(
                sessions=sessions,
                exit_date=exit_day,
                exit_price=round(exit_price, 4),
                return_pct=ret,
                benchmark_return_pct=bench_ret,
                excess_pp=round(ret - bench_ret, 4) if bench_ret is not None else None,
                stop_touched=stop_touched,
            )
        )

    status: OutcomeStatus = "measured" if any(h.measured for h in results) else "pending"
    return SignalOutcome(
        signal=signal,
        status=status,
        entry_date=entry_day,
        entry_price=round(entry_price, 4),
        horizons=tuple(results),
        reason=None if status == "measured" else "shortest horizon has not elapsed",
    )


def _history_bars(price_source, symbol: str, lookback_days: int) -> _Bars | None:
    try:
        series = price_source.history(
            Instrument(symbol), interval="1d", lookback_days=lookback_days
        )
    except Exception as exc:  # sources are contracted not to raise; a scoreboard must not either
        log.warning("scoreboard price fetch failed for %s: %s", symbol, exc)
        return None
    try:
        return _Bars.from_series(series)
    except Exception as exc:
        log.warning("scoreboard could not read bars for %s: %s", symbol, exc)
        return None


def measure_signals(
    signals: Sequence[Signal],
    price_source,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    today: date | None = None,
) -> list[SignalOutcome]:
    """Forward outcomes for each signal. One price fetch per symbol, however many signals."""
    if not signals:
        return []
    today = today or now_utc().astimezone(IST).date()
    earliest = min(s.signalled_at.astimezone(IST).date() for s in signals)
    # Enough history to reach back to the earliest scan, plus room for the entry session.
    lookback = max(400, (today - earliest).days + 30)

    symbols = sorted({s.symbol for s in signals})
    benchmarks = sorted({s.benchmark for s in signals})

    prefetch = getattr(price_source, "prefetch", None)
    if prefetch is not None:
        try:
            prefetch(
                [Instrument(sym) for sym in [*symbols, *benchmarks]],
                interval="1d",
                lookback_days=max(820, lookback),
            )
        except Exception as exc:
            log.warning("scoreboard prefetch failed; falling back to per-symbol fetches: %s", exc)

    bars = {sym: _history_bars(price_source, sym, lookback) for sym in symbols}
    bench_bars = {sym: _history_bars(price_source, sym, lookback) for sym in benchmarks}

    return [
        _measure_one(s, bars.get(s.symbol), bench_bars.get(s.benchmark), horizons) for s in signals
    ]


# ── summarising, one strategy at a time ────────────────────────────────────────────────────


def band_label(conviction: int) -> str:
    for low, high in CONVICTION_BANDS:
        if low <= conviction <= high:
            return f"{low}-{high}"
    return "out-of-range"


def horizon_stats(outcomes: Iterable[SignalOutcome], sessions: int) -> dict[str, Any]:
    """Distribution of one bucket's results at one horizon.

    Pending signals are counted and excluded — a window that has not closed is not a result.
    """
    returns: list[float] = []
    excess: list[float] = []
    stops: list[bool] = []
    pending = 0
    for outcome in outcomes:
        h = outcome.horizon(sessions)
        if h is None or not h.measured:
            pending += 1
            continue
        returns.append(h.return_pct)  # type: ignore[arg-type]
        if h.excess_pp is not None:
            excess.append(h.excess_pp)
        if h.stop_touched is not None:
            stops.append(h.stop_touched)

    n = len(returns)

    def _r(value: float | None, digits: int = 2) -> float | None:
        return None if value is None else round(value, digits)

    excess_se = (
        statistics.stdev(excess) / math.sqrt(len(excess)) if len(excess) >= 2 else None
    )
    return {
        "measured": n,
        "pending": pending,
        "mean_return_pct": _r(statistics.fmean(returns)) if returns else None,
        "median_return_pct": _r(statistics.median(returns)) if returns else None,
        "positive_pct": _r(100.0 * sum(r > 0 for r in returns) / n, 1) if n else None,
        "best_pct": _r(max(returns)) if returns else None,
        "worst_pct": _r(min(returns)) if returns else None,
        "with_benchmark": len(excess),
        "mean_excess_pp": _r(statistics.fmean(excess)) if excess else None,
        "median_excess_pp": _r(statistics.median(excess)) if excess else None,
        "excess_se_pp": _r(excess_se),
        "beat_benchmark_pct": (
            _r(100.0 * sum(e > 0 for e in excess) / len(excess), 1) if excess else None
        ),
        "with_stop": len(stops),
        "stop_touched_pct": _r(100.0 * sum(stops) / len(stops), 1) if stops else None,
        "thin": n < THIN_SAMPLE,
    }


def summarise(
    outcomes: Sequence[SignalOutcome], *, horizons: Sequence[int] = DEFAULT_HORIZONS
) -> list[dict[str, Any]]:
    """Per strategy (alphabetical), per stance, then per conviction band within that stance.

    Strategies are listed alphabetically and never ordered by their results: a scoreboard that
    sorted strategies by excess return would be a ranking of strategies, and the reader should
    compare them deliberately, row by row.
    """
    by_strategy: dict[str, list[SignalOutcome]] = {}
    for outcome in outcomes:
        if outcome.status == "unpriced":
            continue
        by_strategy.setdefault(outcome.signal.strategy_id, []).append(outcome)

    report: list[dict[str, Any]] = []
    for strategy_id in sorted(by_strategy):
        rows: list[dict[str, Any]] = []
        for stance in STANCES:
            in_stance = [o for o in by_strategy[strategy_id] if o.signal.stance == stance]
            if not in_stance:
                continue
            rows.append(_row(stance, "all", in_stance, horizons))
            bands = [
                (label, [o for o in in_stance if band_label(o.signal.conviction) == label])
                for label in (f"{low}-{high}" for low, high in CONVICTION_BANDS)
            ]
            occupied = [(label, group) for label, group in bands if group]
            # One occupied band is the stance total again; repeating it adds a row, not a fact.
            if len(occupied) > 1:
                rows.extend(_row(stance, label, group, horizons) for label, group in occupied)
        report.append({"strategy_id": strategy_id, "rows": rows})
    return report


def _row(
    stance: str, band: str, outcomes: list[SignalOutcome], horizons: Sequence[int]
) -> dict[str, Any]:
    return {
        "stance": stance,
        "band": band,
        "signals": len(outcomes),
        "horizons": {str(h): horizon_stats(outcomes, h) for h in horizons},
    }


# ── the whole report ───────────────────────────────────────────────────────────────────────


def normalise_horizons(raw: Iterable[int] | None) -> tuple[int, ...]:
    values = sorted(
        {int(h) for h in (raw or DEFAULT_HORIZONS) if 1 <= int(h) <= MAX_HORIZON_SESSIONS}
    )
    return tuple(values) or DEFAULT_HORIZONS


def build_scoreboard(
    session_factory,
    price_source,
    *,
    horizons: Iterable[int] | None = None,
    signals: SignalFilter = "new",
    strategy_id: str | None = None,
    max_runs: int = DEFAULT_MAX_RUNS,
    today: date | None = None,
) -> dict[str, Any]:
    horizon_tuple = normalise_horizons(horizons)
    collected = collect_signals(session_factory, max_runs=max_runs)
    run_ids = sorted({s.run_id for s in collected})
    first_at = min((s.signalled_at for s in collected), default=None)
    last_at = max((s.signalled_at for s in collected), default=None)

    chosen = [
        s
        for s in collected
        if (signals == "all" or s.is_new) and (strategy_id is None or s.strategy_id == strategy_id)
    ]
    outcomes = measure_signals(chosen, price_source, horizons=horizon_tuple, today=today)

    notes: list[str] = []
    if not run_ids:
        notes.append(
            "No completed discovery scan exists yet. Run one from Ideas or Engine; the scoreboard "
            "fills in as the first horizon elapses after it."
        )
    elif len(run_ids) < 4:
        notes.append(
            f"Only {len(run_ids)} completed scan(s) so far — far too few to judge any strategy. "
            "Treat every figure here as anecdote until the counts pass the thin-sample floor."
        )
    if signals == "all":
        notes.append(
            "Counting every scan's verdict, including repeats of an unchanged stance: consecutive "
            "rows overlap heavily, so sample sizes overstate the evidence."
        )

    recent = sorted(
        (o for o in outcomes if o.signal.stance == "BUY"),
        key=lambda o: (o.signal.signalled_at, o.signal.strategy_id, o.signal.symbol),
        reverse=True,
    )[:RECENT_LIMIT]

    return {
        "generated_at": now_utc().isoformat(),
        "horizons": list(horizon_tuple),
        "signal_filter": signals,
        "strategy_filter": strategy_id,
        "runs": {
            "count": len(run_ids),
            "first_signal_at": first_at.isoformat() if first_at else None,
            "last_signal_at": last_at.isoformat() if last_at else None,
        },
        "benchmarks": sorted({s.benchmark for s in chosen}),
        "totals": {
            "signals": len(outcomes),
            "measured": sum(o.status == "measured" for o in outcomes),
            "pending": sum(o.status == "pending" for o in outcomes),
            "unpriced": sum(o.status == "unpriced" for o in outcomes),
        },
        "thin_sample_floor": THIN_SAMPLE,
        "strategies": summarise(outcomes, horizons=horizon_tuple),
        "recent_buys": [o.as_dict() for o in recent],
        "method": (
            "Entry at the first session open after the scan (that day's open when the scan "
            "finished before 09:15 IST). Return to the close of the Nth session counting the "
            "entry session, against the scan's benchmark over the same sessions. Grouped by "
            "strategy, stance and conviction band; never pooled across strategies."
        ),
        "biases": list(BIASES),
        "charges_included": False,
        "notes": notes,
    }
