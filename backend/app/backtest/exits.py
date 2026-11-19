"""Each strategy's own exit rule, in a form a replay can check.

A strategy's `Plan.exit_rule` is prose written for a reader ("Exit on weekly close below 50-day
(10-week) SMA"). A replay needs a function. These are those functions — one per strategy, each
restating its plan's rule as closely as daily bars allow, and each saying plainly what it does
*not* model, so a result is never read as having tested more than it did.

Every rule is evaluated on bars up to and including the session being judged, and an exit it
signals fills at the *next* session's open: a close below an average is not known until the
close has happened.

Strategies stay unmodified. Putting a replay hook on the strategy protocol would make every
strategy carry backtest machinery; keeping the rules here keeps the coupling one-directional,
and a test asserts every registered strategy has an entry so a new strategy cannot be replayed
with no exit at all by accident.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from app.strategies.indicators import to_weekly

#: (stock bars to date, benchmark bars to date) -> reason to exit, or None to hold.
ExitCheck = Callable[[pd.DataFrame, pd.DataFrame | None], str | None]


@dataclass(frozen=True, slots=True)
class ExitRule:
    strategy_id: str
    #: The plan's own wording, quoted so a reader can compare it with what is checked.
    plan_rule: str
    #: What this function actually tests.
    checked: str
    #: Parts of the plan's rule a replay on daily bars cannot test.
    not_modelled: tuple[str, ...]
    check: ExitCheck

    def describe(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "plan_rule": self.plan_rule,
            "checked": self.checked,
            "not_modelled": list(self.not_modelled),
        }


def _is_week_end(frame: pd.DataFrame) -> bool:
    """Whether the last bar is the final session of its calendar week.

    Judged from the bars alone: a replay knows today's bar but not tomorrow's, so "last session
    of the week" means a Friday, or a Thursday when Friday is a holiday is not knowable in
    advance — the next bar tells us, one session late. Using the weekday keeps the check free of
    lookahead; a holiday Friday shifts that week's check to the following Monday's evaluation.
    """
    return bool(len(frame)) and frame.index[-1].tz_convert("Asia/Kolkata").weekday() == 4


def _close_below_sma(frame: pd.DataFrame, window: int) -> tuple[bool, float, float] | None:
    if len(frame) < window:
        return None
    close = float(frame["close"].iloc[-1])
    average = float(frame["close"].tail(window).mean())
    return close < average, close, average


def _minervini(frame: pd.DataFrame, _bench: pd.DataFrame | None) -> str | None:
    if not _is_week_end(frame):
        return None
    reading = _close_below_sma(frame, 50)
    if reading and reading[0]:
        return f"weekly close {reading[1]:.2f} below 50-day SMA {reading[2]:.2f}"
    return None


def _young_momentum(frame: pd.DataFrame, _bench: pd.DataFrame | None) -> str | None:
    if len(frame) < 20:
        return None
    ema = frame["close"].ewm(span=20, adjust=False).mean()
    close, average = float(frame["close"].iloc[-1]), float(ema.iloc[-1])
    if close < average:
        return f"close {close:.2f} below 20-day EMA {average:.2f}"
    return None


def _fun_tech(frame: pd.DataFrame, _bench: pd.DataFrame | None) -> str | None:
    reading = _close_below_sma(frame, 50)
    if reading and reading[0]:
        return f"close {reading[1]:.2f} below 50-day SMA {reading[2]:.2f}"
    return None


def _bvm(_frame: pd.DataFrame, bench: pd.DataFrame | None) -> str | None:
    if bench is None or bench.empty or not _is_week_end(bench):
        return None
    weekly = to_weekly(bench)
    if len(weekly) < 20:
        return None
    close = float(weekly["close"].iloc[-1])
    average = float(weekly["close"].tail(20).mean())
    if close < average:
        return f"Nifty weekly close {close:.2f} below 20-week SMA {average:.2f}"
    return None


EXIT_RULES: dict[str, ExitRule] = {
    rule.strategy_id: rule
    for rule in (
        ExitRule(
            strategy_id="minervini",
            plan_rule="Exit on weekly close below 50-day (10-week) SMA",
            checked="Friday close below the 50-day simple average",
            not_modelled=(),
            check=_minervini,
        ),
        ExitRule(
            strategy_id="young_momentum",
            plan_rule="Exit on failure to make higher high or close below 20-day EMA",
            checked="daily close below the 20-day exponential average",
            not_modelled=("failure to make a higher high — the plan does not define the window",),
            check=_young_momentum,
        ),
        ExitRule(
            strategy_id="fun_tech_momentum",
            plan_rule="Exit on quarterly YoY EPS deceleration or close below 50-day SMA",
            checked="daily close below the 50-day simple average",
            not_modelled=(
                "quarterly EPS deceleration — covered only indirectly, by the verdict turning "
                "AVOID once a weaker quarter is past its filing deadline",
            ),
            check=_fun_tech,
        ),
        ExitRule(
            strategy_id="brahma_vishnu_mahesh",
            plan_rule=(
                "Exit if Nifty weekly close breaks rising 20-week SMA "
                "or sector drops out of top 3 RS"
            ),
            checked="the strategy's benchmark closing a week below its 20-week simple average",
            not_modelled=(
                "sector dropping out of the top 3 — covered only indirectly, by the verdict "
                "turning AVOID on an evaluation session",
            ),
            check=_bvm,
        ),
    )
}


def rule_for(strategy_id: str) -> ExitRule | None:
    return EXIT_RULES.get(strategy_id)
