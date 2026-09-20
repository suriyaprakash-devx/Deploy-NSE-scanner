import pytest
from datetime import datetime, timedelta
import pandas as pd
from backend.scanner import detect_crossover, build_ranked_dataframe

def generate_candles_bullish():
    """
    Generates a candle series where a bullish crossover occurs on the last completed candle.
    """
    base_date = datetime(2026, 1, 1)
    candles = []
    # 35 days: first 30 days low price, then last 5 days rapid surge to cross above SMA 30
    for i in range(35):
        dt = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        if i < 30:
            price = 100.0 - (i * 0.1)  # downtrend/flat
        else:
            price = 100.0 + ((i - 29) * 5.0)  # sharp surge to cross above
        candles.append({
            "timestamp": f"{dt}T09:15:00+05:30",
            "open": price - 1,
            "high": price + 2,
            "low": price - 2,
            "close": price,
            "volume": 10000
        })
    return candles

def generate_candles_bearish():
    """
    Generates a candle series where a bearish crossover occurs on the last completed candle.
    """
    base_date = datetime(2026, 1, 1)
    candles = []
    # 35 days: first 30 days high price, then last 5 days sharp decline to cross below SMA 30
    for i in range(35):
        dt = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        if i < 30:
            price = 200.0 + (i * 0.1)  # uptrend
        else:
            price = 200.0 - ((i - 29) * 8.0)  # sharp decline
        candles.append({
            "timestamp": f"{dt}T09:15:00+05:30",
            "open": price + 1,
            "high": price + 2,
            "low": price - 2,
            "close": price,
            "volume": 15000
        })
    return candles

def test_detect_bullish_crossover():
    candles = generate_candles_bullish()
    signal = detect_crossover(candles, "RELIANCE", "Reliance Industries Ltd")
    assert signal is not None
    assert signal["signal_type"] == "BULLISH"
    assert signal["symbol"] == "RELIANCE"
    assert signal["company"] == "Reliance Industries Ltd"
    assert signal["sma6"] > signal["sma30"]
    assert "crossover_date" in signal
    assert signal["close"] > 0

def test_detect_bearish_crossover():
    candles = generate_candles_bearish()
    signal = detect_crossover(candles, "TCS", "Tata Consultancy Services Ltd")
    assert signal is not None
    assert signal["signal_type"] == "BEARISH"
    assert signal["symbol"] == "TCS"
    assert signal["company"] == "Tata Consultancy Services Ltd"
    assert signal["sma6"] < signal["sma30"]
    assert "crossover_date" in signal
    assert signal["close"] > 0

def test_no_crossover_when_steady():
    # 35 identical candles: no crossover can happen
    base_date = datetime(2026, 1, 1)
    candles = [
        {
            "timestamp": f"{(base_date + timedelta(days=i)).strftime('%Y-%m-%d')}T09:15:00+05:30",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 100.0,
            "volume": 1000
        }
        for i in range(35)
    ]
    signal = detect_crossover(candles, "FLAT", "Flat Stock Ltd")
    assert signal is None

def test_insufficient_candles():
    # Only 10 candles: SMA 30 cannot be calculated
    candles = [
        {
            "timestamp": "2026-01-01T09:15:00+05:30",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 100.0,
            "volume": 1000
        }
        for _ in range(10)
    ]
    assert detect_crossover(candles, "TEST", "Test Ltd") is None

def test_ranking_and_dataframe_columns():
    signals = [
        {
            "symbol": "ABC",
            "company": "ABC Industries Ltd",
            "signal_type": "BULLISH",
            "crossover_date": "2026-09-18",
            "close": 1250.50,
            "sma6": 1240.20,
            "sma30": 1230.10
        },
        {
            "symbol": "XYZ",
            "company": "XYZ Ltd",
            "signal_type": "BEARISH",
            "crossover_date": "2026-09-19",
            "close": 845.00,
            "sma6": 850.30,
            "sma30": 855.80
        }
    ]

    df = build_ranked_dataframe(signals)
    expected_cols = ["Rank", "Symbol", "Company", "Signal Type", "Crossover Date", "Close", "SMA 6", "SMA 30"]
    assert list(df.columns) == expected_cols
    assert len(df) == 2

    # Most recent crossover date (2026-09-19) must be Rank 1
    first_row = df.iloc[0]
    assert first_row["Rank"] == 1
    assert first_row["Symbol"] == "XYZ"
    assert first_row["Crossover Date"] == "2026-09-19"
    assert first_row["Signal Type"] == "BEARISH"

    # Second row must be Rank 2
    second_row = df.iloc[1]
    assert second_row["Rank"] == 2
    assert second_row["Symbol"] == "ABC"
    assert second_row["Crossover Date"] == "2026-09-18"
    assert second_row["Signal Type"] == "BULLISH"

def test_crossover_10min_timestamps():
    """Verify that 10-minute bar timestamps are preserved in format YYYY-MM-DD HH:MM."""
    base_time = datetime(2026, 9, 20, 9, 15)
    candles = []
    for i in range(35):
        dt = (base_time + timedelta(minutes=10 * i)).strftime("%Y-%m-%d %H:%M")
        price = 100.0 + (i * 2.0 if i >= 30 else -i * 0.1)
        candles.append({
            "timestamp": dt,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": 5000
        })

    signal = detect_crossover(candles, "INTRADAY", "Intraday Test Ltd")
    assert signal is not None
    assert signal["signal_type"] == "BULLISH"
    # Verify timestamp includes hour and minute
    assert ":" in signal["crossover_date"]

