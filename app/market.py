from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Regular Trading Hours (IST)
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)
PRE_OPEN_START = time(9, 0)

def now_ist() -> datetime:
    """Return current datetime in Asia/Kolkata timezone."""
    return datetime.now(IST)

def get_market_status(dt: datetime | None = None) -> str:
    """
    Determine NSE market status: OPEN, CLOSED, or PRE-OPEN.
    Trading days: Monday (0) to Friday (4).
    """
    if dt is None:
        dt = now_ist()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)

    # Weekends
    if dt.weekday() >= 5:
        return "CLOSED"

    current_t = dt.time()
    if PRE_OPEN_START <= current_t < MARKET_OPEN_TIME:
        return "PRE-OPEN"
    if MARKET_OPEN_TIME <= current_t <= MARKET_CLOSE_TIME:
        return "OPEN"
    return "CLOSED"

def is_market_open(dt: datetime | None = None) -> bool:
    return get_market_status(dt) == "OPEN"

def parse_iso_datetime(dt_str: str) -> datetime:
    """Parse ISO timestamp string from Upstox (e.g. 2026-09-17T11:20:00+05:30)."""
    # Clean up standard formats
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt

def is_candle_completed(start_dt: datetime, interval_minutes: int, current_dt: datetime | None = None) -> bool:
    """
    Strict candle completion validation:
    A candle starting at start_dt with duration interval_minutes completes at start_dt + interval_minutes.
    It is completed if and only if end_dt <= current_dt, or if current_dt is past market close for that trading day.
    """
    if current_dt is None:
        current_dt = now_ist()
    elif current_dt.tzinfo is None:
        current_dt = current_dt.replace(tzinfo=IST)
    else:
        current_dt = current_dt.astimezone(IST)

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=IST)
    else:
        start_dt = start_dt.astimezone(IST)

    end_dt = start_dt + timedelta(minutes=interval_minutes)

    # If the candle belongs to a previous date, it has already completed
    if start_dt.date() < current_dt.date():
        return True

    # If it's today and current time is past market close, any candle ending by 15:30 is completed
    if current_dt.date() == start_dt.date() and current_dt.time() >= MARKET_CLOSE_TIME:
        return end_dt.time() <= MARKET_CLOSE_TIME or end_dt <= current_dt

    # During trading session or intraday: end_dt must be <= current_dt
    return end_dt <= current_dt

def filter_completed_candles(candles: list, interval_minutes: int, current_dt: datetime | None = None) -> list:
    """
    Filter raw candles list to include strictly completed candles only.
    Each candle item is [timestamp_str, open, high, low, close, volume, ...]
    Returns list of candles sorted chronologically ascending.
    """
    if not candles:
        return []

    if current_dt is None:
        current_dt = now_ist()

    # Parse and sort chronologically ascending first
    parsed = []
    for c in candles:
        try:
            ts = parse_iso_datetime(c[0])
            parsed.append((ts, c))
        except Exception:
            continue

    parsed.sort(key=lambda x: x[0])

    completed = []
    for ts, raw in parsed:
        if is_candle_completed(ts, interval_minutes, current_dt):
            completed.append(raw)

    return completed
