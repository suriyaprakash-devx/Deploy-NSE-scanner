from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from app.strategy import detect_ema_crossover, calculate_ema, generate_signal_key

IST = ZoneInfo("Asia/Kolkata")

def generate_candles_with_trend(trend: str, count: int = 50, interval_minutes: int = 5) -> list:
    """
    Generate synthetic completed candles with timestamps.
    trend: 'bullish_cross', 'bearish_cross', 'steady_bullish', 'steady_bearish'
    """
    base_time = datetime(2026, 9, 17, 9, 15, tzinfo=IST)
    candles = []

    prices = []
    if trend == 'bullish_cross':
        # 40 candles downtrend (EMA6 < EMA30), then rising so crossover happens exactly at idx 43
        prices = [100.0 - (0.1 * i) for i in range(40)]
        prices += [96.0 + (1.0 * i) for i in range(1, 5)]  # indices 40, 41, 42, 43
    elif trend == 'bearish_cross':
        # 40 candles uptrend (EMA6 > EMA30), then falling so crossover happens exactly at idx 43
        prices = [100.0 + (0.1 * i) for i in range(40)]
        prices += [104.0 - (1.0 * i) for i in range(1, 5)]  # indices 40, 41, 42, 43
    elif trend == 'steady_bullish':
        prices = [100.0 + (0.5 * i) for i in range(count)]
    else:  # steady_bearish
        prices = [200.0 - (0.5 * i) for i in range(count)]

    for i, p in enumerate(prices):
        t = base_time + timedelta(minutes=i * interval_minutes)
        candles.append([
            t.isoformat(),
            round(p - 0.2, 2),
            round(p + 0.5, 2),
            round(p - 0.5, 2),
            round(p, 2),
            1000,
            0
        ])
    return candles

def test_ema_calculation_lengths():
    prices = [100.0 + i for i in range(40)]
    ema6 = calculate_ema(prices, 6)
    ema30 = calculate_ema(prices, 30)

    assert len(ema6) == len(prices)
    assert len(ema30) == len(prices)
    # In uptrend, faster EMA6 must be greater than slower EMA30
    assert ema6.iloc[-1] > ema30.iloc[-1]

def test_detect_buy_crossover():
    # 44 candles with exact crossover at candle -1
    candles = generate_candles_with_trend('bullish_cross', count=44, interval_minutes=5)
    current_dt = datetime(2026, 9, 17, 15, 30, tzinfo=IST)

    signal = detect_ema_crossover(
        symbol="TEST_BUY",
        instrument_key="NSE_EQ|TEST123",
        raw_candles=candles,
        timeframe="5M",
        current_dt=current_dt
    )

    assert signal is not None
    assert signal.direction == "BUY"
    assert signal.symbol == "TEST_BUY"
    assert signal.timeframe == "5M"
    assert signal.prev_ema6 <= signal.prev_ema30
    assert signal.ema6 > signal.ema30
    assert "BUY" in signal.signal_key

def test_detect_sell_crossover():
    # 44 candles with exact crossover at candle -1
    candles = generate_candles_with_trend('bearish_cross', count=44, interval_minutes=5)
    current_dt = datetime(2026, 9, 17, 15, 30, tzinfo=IST)

    signal = detect_ema_crossover(
        symbol="TEST_SELL",
        instrument_key="NSE_EQ|TEST456",
        raw_candles=candles,
        timeframe="5M",
        current_dt=current_dt
    )

    assert signal is not None
    assert signal.direction == "SELL"
    assert signal.symbol == "TEST_SELL"
    assert signal.timeframe == "5M"
    assert signal.prev_ema6 >= signal.prev_ema30
    assert signal.ema6 < signal.ema30
    assert "SELL" in signal.signal_key

def test_no_crossover_when_already_crossed():
    # In a steady trend, EMA6 is already above EMA30 on BOTH previous and latest candles
    candles = generate_candles_with_trend('steady_bullish', count=50, interval_minutes=5)
    current_dt = datetime(2026, 9, 17, 15, 30, tzinfo=IST)

    signal = detect_ema_crossover(
        symbol="TEST_STEADY",
        instrument_key="NSE_EQ|TEST789",
        raw_candles=candles,
        timeframe="5M",
        current_dt=current_dt
    )
    # No new crossover on the latest candle
    assert signal is None

def test_insufficient_candles_returns_none():
    # Less than 31 candles
    candles = generate_candles_with_trend('bullish_cross', count=20, interval_minutes=5)[:20]
    current_dt = datetime(2026, 9, 17, 15, 30, tzinfo=IST)

    signal = detect_ema_crossover(
        symbol="TEST_SHORT",
        instrument_key="NSE_EQ|SHORT",
        raw_candles=candles,
        timeframe="5M",
        current_dt=current_dt
    )
    assert signal is None
