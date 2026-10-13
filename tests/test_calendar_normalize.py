from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import bar
from momentum_bot.data.coverage import missing_intervals
from momentum_bot.data.market_calendar import (
    CalendarCoverageError,
    previous_trading_day,
    session_windows,
    trading_days,
)
from momentum_bot.data.normalize import normalize


def test_dst_shifts_utc_session_boundaries() -> None:
    est = session_windows(date(2024, 3, 8))
    edt = session_windows(date(2024, 3, 11))
    assert est["premarket"].start_utc == datetime(2024, 3, 8, 9, tzinfo=timezone.utc)
    assert edt["premarket"].start_utc == datetime(2024, 3, 11, 8, tzinfo=timezone.utc)
    assert edt["afterhours"].end_utc == datetime(2024, 3, 12, 0, tzinfo=timezone.utc)
    assert est["premarket"].minutes == 330 and est["afterhours"].minutes == 240


def test_holidays_weekends_and_early_close() -> None:
    assert session_windows(date(2024, 7, 4)) == {}
    assert trading_days(date(2024, 3, 29), date(2024, 4, 1)) == [date(2024, 4, 1)]  # Good Friday + weekend
    assert previous_trading_day(date(2024, 4, 1)) == date(2024, 3, 28)
    ah = session_windows(date(2024, 11, 29))["afterhours"]
    assert ah.start_utc == datetime(2024, 11, 29, 18, tzinfo=timezone.utc)  # 13:00 EST
    assert ah.minutes == 240


def test_uncovered_year_is_an_error_not_a_guess() -> None:
    with pytest.raises(CalendarCoverageError):
        session_windows(date(2030, 1, 2))


def test_normalize_labels_sessions_and_drops_incomplete_duplicate_out_of_session() -> None:
    d = date(2024, 3, 8)
    windows = {d: session_windows(d)}
    pm = bar("sip", d, "04:00", 2.0, 2.0, 10)
    late = bar("sip", d, "19:59", 2.0, 2.0, 10)
    night = bar("sip", d, "20:00", 2.0, 2.0, 10)
    regular = bar("sip", d, "10:00", 2.0, 2.0, 10)
    as_of = late.timestamp_utc + timedelta(seconds=30)  # 19:59 bar not yet complete
    out, dropped = normalize([pm, pm, regular, late, night], windows, as_of_utc=as_of)
    assert [(sb.session, sb.bar.timestamp_utc) for sb in out] == [
        ("premarket", pm.timestamp_utc), ("regular", regular.timestamp_utc)
    ]
    assert dropped == {"duplicate": 1, "incomplete": 2}  # 20:00 is also after as_of


def test_missing_intervals_are_half_open_runs() -> None:
    w = session_windows(date(2024, 3, 8))["premarket"]
    present = [w.start_utc + timedelta(minutes=m) for m in (0, 1, 5)]
    runs = missing_intervals(w, present)
    assert runs[0] == (w.start_utc + timedelta(minutes=2), w.start_utc + timedelta(minutes=5))
    assert runs[1] == (w.start_utc + timedelta(minutes=6), w.end_utc)
