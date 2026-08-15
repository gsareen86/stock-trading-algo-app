"""NSE trading calendar.

Extracted from the bottom of the predecessor's `data/fetcher.py`, with one behavioural change
that is the whole point of the port: **an uncovered year is refused, not assumed open.**

The old version warned that it had no holidays for the current year and then returned "not a
holiday" anyway — so every holiday in an uncovered year silently became a trading day. That
fails on a Tuesday in January, in a way nobody notices until the engine has already acted on
a closed market. Here it raises, and `/health` reports the covered range so the file's
staleness is visible before it matters.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path

from app.core.clock import IST
from app.data.protocols import CalendarNotCovered

log = logging.getLogger(__name__)

RESOURCES = Path(__file__).parent / "resources"
HOLIDAYS_FILE = RESOURCES / "nse_holidays.json"

#: NSE equity session, IST.
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)


@lru_cache(maxsize=1)
def _load_holidays(path_str: str) -> tuple[frozenset[date], tuple[int, ...]]:
    """-> (all holiday dates, covered years). Cached: the file does not change at runtime."""
    payload = json.loads(Path(path_str).read_text("utf-8"))
    by_year: dict[str, list[str]] = payload.get("holidays", {})

    dates: set[date] = set()
    years: set[int] = set()
    for year, entries in by_year.items():
        years.add(int(year))
        for entry in entries:
            dates.add(date.fromisoformat(entry))
    return frozenset(dates), tuple(sorted(years))


class NseCalendar:
    """Trading days and session hours for the NSE equity segment."""

    def __init__(self, holidays_file: Path | None = None) -> None:
        self._path = holidays_file or HOLIDAYS_FILE
        self._holidays, self._years = _load_holidays(str(self._path))

    # ── coverage ──────────────────────────────────────────────────────────────
    @property
    def covered_years(self) -> tuple[int, ...]:
        return self._years

    def covers(self, year: int) -> bool:
        """Whether the holiday data has anything to say about ``year``."""
        return year in self._years

    def _require_coverage(self, day: date) -> None:
        if not self.covers(day.year):
            raise CalendarNotCovered(day.year, self._years)

    # ── trading days ──────────────────────────────────────────────────────────
    def is_holiday(self, day: date) -> bool:
        self._require_coverage(day)
        return day in self._holidays

    def is_trading_day(self, day: date) -> bool:
        """Weekday, and not a published holiday."""
        self._require_coverage(day)
        if day.weekday() >= 5:  # Saturday, Sunday
            return False
        return day not in self._holidays

    def previous_trading_day(self, day: date) -> date:
        """The latest trading day on or before ``day`` — the "as of" anchor.

        Walks backwards a bounded number of days: an unbounded loop across a year boundary
        would run straight out of holiday coverage and raise somewhere confusing.
        """
        self._require_coverage(day)
        candidate = day
        for _ in range(15):  # longest plausible NSE closure is far under this
            if self.is_trading_day(candidate):
                return candidate
            candidate = date.fromordinal(candidate.toordinal() - 1)
            self._require_coverage(candidate)
        raise CalendarNotCovered(day.year, self._years)

    # ── session ───────────────────────────────────────────────────────────────
    def is_market_open(self, moment: datetime) -> bool:
        """Whether the NSE equity session is live at ``moment``.

        Converts to IST first: the session is an IST fact, and evaluating a UTC instant
        against IST clock times without converting would be wrong by 5h30m.
        """
        if moment.tzinfo is None:
            raise ValueError("naive datetime: attach a timezone before checking market hours")
        ist = moment.astimezone(IST)
        if not self.is_trading_day(ist.date()):
            return False
        return SESSION_OPEN <= ist.time() <= SESSION_CLOSE
