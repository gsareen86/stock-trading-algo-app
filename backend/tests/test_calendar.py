"""The NSE trading calendar.

Most of these run against a synthetic holiday file so they stay true when the real one is
updated each January. A couple assert the bundled resource itself loads and is sane.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.core.clock import IST
from app.data.calendar import NseCalendar
from app.data.protocols import CalendarNotCovered


@pytest.fixture
def calendar(tmp_path: Path) -> NseCalendar:
    """2026 only. 2026-01-26 is a Monday; 2026-04-03 a Friday."""
    path = tmp_path / "holidays.json"
    path.write_text(json.dumps({"holidays": {"2026": ["2026-01-26", "2026-04-03", "2026-08-15"]}}))
    return NseCalendar(holidays_file=path)


class TestTradingDays:
    def test_ordinary_weekday(self) -> None:
        cal = _cal_for({"2026": []})
        assert date(2026, 8, 11).weekday() == 1  # Tuesday
        assert cal.is_trading_day(date(2026, 8, 11)) is True

    def test_saturday_and_sunday(self, calendar: NseCalendar) -> None:
        assert calendar.is_trading_day(date(2026, 8, 8)) is False  # Saturday
        assert calendar.is_trading_day(date(2026, 8, 9)) is False  # Sunday

    def test_published_holiday_on_a_weekday(self, calendar: NseCalendar) -> None:
        assert date(2026, 1, 26).weekday() < 5
        assert calendar.is_holiday(date(2026, 1, 26)) is True
        assert calendar.is_trading_day(date(2026, 1, 26)) is False


class TestCoverage:
    def test_uncovered_year_raises_rather_than_assuming_open(self, calendar: NseCalendar) -> None:
        """The predecessor warned and then said 'not a holiday' — silently wrong."""
        with pytest.raises(CalendarNotCovered, match="2027"):
            calendar.is_trading_day(date(2027, 3, 10))

    def test_coverage_is_queryable_before_asking(self, calendar: NseCalendar) -> None:
        assert calendar.covers(2026) is True
        assert calendar.covers(2027) is False

    def test_covered_years_reported(self, calendar: NseCalendar) -> None:
        assert calendar.covered_years == (2026,)

    def test_error_names_the_covered_range(self, calendar: NseCalendar) -> None:
        with pytest.raises(CalendarNotCovered) as excinfo:
            calendar.is_holiday(date(2030, 1, 1))

        assert "2030" in str(excinfo.value)
        assert "nse_holidays.json" in str(excinfo.value)


class TestSessionHours:
    def test_mid_session_open(self, calendar: NseCalendar) -> None:
        moment = datetime(2026, 8, 11, 11, 0, tzinfo=IST)
        assert calendar.is_market_open(moment) is True

    def test_before_open(self, calendar: NseCalendar) -> None:
        assert calendar.is_market_open(datetime(2026, 8, 11, 9, 0, tzinfo=IST)) is False

    def test_after_close(self, calendar: NseCalendar) -> None:
        assert calendar.is_market_open(datetime(2026, 8, 11, 15, 45, tzinfo=IST)) is False

    def test_boundaries_inclusive(self, calendar: NseCalendar) -> None:
        assert calendar.is_market_open(datetime(2026, 8, 11, 9, 15, tzinfo=IST)) is True
        assert calendar.is_market_open(datetime(2026, 8, 11, 15, 30, tzinfo=IST)) is True

    def test_holiday_during_session_hours(self, calendar: NseCalendar) -> None:
        assert calendar.is_market_open(datetime(2026, 1, 26, 11, 0, tzinfo=IST)) is False

    def test_utc_instant_converted_before_evaluation(self, calendar: NseCalendar) -> None:
        """05:30 UTC is 11:00 IST — open. Evaluating the UTC clock time would say closed."""
        assert calendar.is_market_open(datetime(2026, 8, 11, 5, 30, tzinfo=UTC)) is True

    def test_naive_datetime_rejected(self, calendar: NseCalendar) -> None:
        with pytest.raises(ValueError, match="naive"):
            calendar.is_market_open(datetime(2026, 8, 11, 11, 0))


class TestPreviousTradingDay:
    def test_on_a_trading_day_returns_itself(self, calendar: NseCalendar) -> None:
        assert calendar.previous_trading_day(date(2026, 8, 11)) == date(2026, 8, 11)

    def test_on_a_sunday_returns_friday(self, calendar: NseCalendar) -> None:
        assert calendar.previous_trading_day(date(2026, 8, 9)) == date(2026, 8, 7)

    def test_across_a_holiday_weekend(self, tmp_path: Path) -> None:
        """Monday holiday after a weekend resolves back to the Friday."""
        path = tmp_path / "h.json"
        path.write_text(json.dumps({"holidays": {"2026": ["2026-08-10"]}}))
        cal = NseCalendar(holidays_file=path)

        assert date(2026, 8, 10).weekday() == 0  # Monday
        assert cal.previous_trading_day(date(2026, 8, 10)) == date(2026, 8, 7)


class TestBundledResource:
    def test_real_file_loads(self) -> None:
        calendar = NseCalendar()

        assert calendar.covered_years
        assert all(isinstance(year, int) for year in calendar.covered_years)

    def test_real_file_covers_a_known_holiday(self) -> None:
        calendar = NseCalendar()

        assert calendar.is_holiday(date(2026, 8, 15)) is True  # Independence Day


def _cal_for(holidays: dict) -> NseCalendar:
    import tempfile

    path = Path(tempfile.mkdtemp()) / "h.json"
    path.write_text(json.dumps({"holidays": holidays}))
    return NseCalendar(holidays_file=path)
