from dataclasses import dataclass
from datetime import datetime
import pandas as pd
from app.market import filter_completed_candles, parse_iso_datetime

@dataclass
class CrossoverSignal:
    signal_key: str
    symbol: str
    instrument_key: str
    direction: str  # BUY or SELL
    timeframe: str  # 5M or 10M
    crossover_time: datetime
    crossover_time_str: str
    crossover_price: float
    ema6: float
    ema30: float
    prev_ema6: float
    prev_ema30: float

def calculate_ema(prices: list[float], span: int) -> pd.Series:
    """Calculate Exponential Moving Average using pandas ewm(adjust=False)."""
    return pd.Series(prices).ewm(span=span, adjust=False).mean()

def generate_signal_key(
    date_str: str,
    instrument_key: str,
    timeframe: str,
    direction: str,
    crossover_timestamp_str: str
) -> str:
    """
    Generate unique signal identifier:
    date + instrument + timeframe + direction + crossover candle timestamp
    """
    return f"{date_str}:{instrument_key}:{timeframe.upper()}:{direction.upper()}:{crossover_timestamp_str}"

def detect_ema_crossover(
    symbol: str,
    instrument_key: str,
    raw_candles: list,
    timeframe: str = "5M",
    current_dt: datetime | None = None,
    min_candles: int = 31
) -> CrossoverSignal | None:
    """
    1. Filter candles to strictly completed candles only (excluding current forming candle).
    2. Ensure sufficient candles for EMA 30.
    3. Calculate EMA 6 and EMA 30 on candle close prices.
    4. Detect BUY: previous EMA6 <= previous EMA30 and latest EMA6 > latest EMA30.
    5. Detect SELL: previous EMA6 >= previous EMA30 and latest EMA6 < latest EMA30.
    6. Return CrossoverSignal or None.
    """
    interval_minutes = 10 if timeframe.upper() in ("10M", "10MIN", "10MINUTE") else 5
    tf_normalized = f"{interval_minutes}M"

    # Step 1: Strict completed candle filter - no look-ahead bias
    completed = filter_completed_candles(raw_candles, interval_minutes, current_dt)

    if len(completed) < min_candles:
        # Not enough completed candles to calculate reliable EMA 30
        return None

    # Step 2: Extract close prices
    close_prices = [float(c[4]) for c in completed]

    # Step 3: Compute EMA 6 and EMA 30
    ema6_series = calculate_ema(close_prices, span=6)
    ema30_series = calculate_ema(close_prices, span=30)

    # Latest two completed candles
    prev_ema6 = float(ema6_series.iloc[-2])
    prev_ema30 = float(ema30_series.iloc[-2])
    latest_ema6 = float(ema6_series.iloc[-1])
    latest_ema30 = float(ema30_series.iloc[-1])

    direction = None
    if prev_ema6 <= prev_ema30 and latest_ema6 > latest_ema30:
        direction = "BUY"
    elif prev_ema6 >= prev_ema30 and latest_ema6 < latest_ema30:
        direction = "SELL"

    if not direction:
        return None

    # Step 4: Extract crossover candle metadata
    latest_candle = completed[-1]
    raw_timestamp = latest_candle[0]
    crossover_dt = parse_iso_datetime(raw_timestamp)
    crossover_price = float(latest_candle[4])

    date_str = crossover_dt.strftime("%Y-%m-%d")
    timestamp_str = crossover_dt.isoformat()

    signal_key = generate_signal_key(
        date_str=date_str,
        instrument_key=instrument_key,
        timeframe=tf_normalized,
        direction=direction,
        crossover_timestamp_str=timestamp_str
    )

    return CrossoverSignal(
        signal_key=signal_key,
        symbol=symbol,
        instrument_key=instrument_key,
        direction=direction,
        timeframe=tf_normalized,
        crossover_time=crossover_dt,
        crossover_time_str=crossover_dt.strftime("%Y-%m-%d %H:%M:%S"),
        crossover_price=round(crossover_price, 2),
        ema6=round(latest_ema6, 2),
        ema30=round(latest_ema30, 2),
        prev_ema6=round(prev_ema6, 2),
        prev_ema30=round(prev_ema30, 2),
    )
