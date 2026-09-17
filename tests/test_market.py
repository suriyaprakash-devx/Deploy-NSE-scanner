from datetime import datetime
from zoneinfo import ZoneInfo
from app.market import (
    get_market_status,
    is_candle_completed,
    filter_completed_candles,
    parse_iso_datetime
)

IST = ZoneInfo("Asia/Kolkata")

def test_market_status_scenarios():
    # Regular weekday during market hours: Thursday at 11:30 IST
    t_open = datetime(2026, 9, 17, 11, 30, tzinfo=IST)
    assert get_market_status(t_open) == "OPEN"

    # Pre-open at 09:05 IST
    t_pre = datetime(2026, 9, 17, 9, 5, tzinfo=IST)
    assert get_market_status(t_pre) == "PRE-OPEN"

    # Post-market at 16:00 IST
    t_post = datetime(2026, 9, 17, 16, 0, tzinfo=IST)
    assert get_market_status(t_post) == "CLOSED"

    # Weekend Saturday
    t_sat = datetime(2026, 9, 19, 11, 30, tzinfo=IST)
    assert get_market_status(t_sat) == "CLOSED"

def test_completed_candle_rule():
    """
    Prompt requirement:
    'If the latest completed 10-minute candle is 10:20-10:30, use data only through
    the 10:20-10:30 candle and never use the 10:30-10:40 candle.'
    """
    # Current time: 10:32 IST
    current_time = datetime(2026, 9, 17, 10, 32, tzinfo=IST)

    # Candle 1: starts at 10:20, completes at 10:30
    c1_start = datetime(2026, 9, 17, 10, 20, tzinfo=IST)
    assert is_candle_completed(c1_start, interval_minutes=10, current_dt=current_time) is True

    # Candle 2: starts at 10:30, completes at 10:40 (still in progress at 10:32!)
    c2_start = datetime(2026, 9, 17, 10, 30, tzinfo=IST)
    assert is_candle_completed(c2_start, interval_minutes=10, current_dt=current_time) is False

def test_filter_completed_candles_excludes_forming():
    current_time = datetime(2026, 9, 17, 10, 32, tzinfo=IST)

    raw_candles = [
        ["2026-09-17T10:00:00+05:30", 100, 105, 99, 104, 1000],
        ["2026-09-17T10:10:00+05:30", 104, 106, 103, 105, 1200],
        ["2026-09-17T10:20:00+05:30", 105, 108, 104, 107, 1500], # Completed (ended 10:30)
        ["2026-09-17T10:30:00+05:30", 107, 109, 106, 108, 500],  # In progress! (ends 10:40)
    ]

    completed = filter_completed_candles(raw_candles, interval_minutes=10, current_dt=current_time)

    # Must contain exactly 3 candles, with the forming 10:30-10:40 candle removed
    assert len(completed) == 3
    assert completed[-1][0] == "2026-09-17T10:20:00+05:30"
