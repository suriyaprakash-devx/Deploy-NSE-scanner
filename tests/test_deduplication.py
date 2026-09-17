from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, Signal
from app.strategy import generate_signal_key, CrossoverSignal
from app.scanner import ScannerEngine

# In-memory SQLite for testing deduplication and ranking
engine = create_engine("sqlite:///:memory:", echo=False)
TestingSessionLocal = sessionmaker(bind=engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_unique_signal_key_format():
    key = generate_signal_key(
        date_str="2026-09-17",
        instrument_key="NSE_EQ|INE002A01018",
        timeframe="10M",
        direction="BUY",
        crossover_timestamp_str="2026-09-17T11:20:00+05:30"
    )
    expected = "2026-09-17:NSE_EQ|INE002A01018:10M:BUY:2026-09-17T11:20:00+05:30"
    assert key == expected

def test_duplicate_signal_prevention():
    db = TestingSessionLocal()
    signal_key = "2026-09-17:NSE_EQ|INE002A01018:5M:BUY:2026-09-17T11:20:00+05:30"

    sig1 = Signal(
        signal_key=signal_key,
        symbol="RELIANCE",
        instrument_key="NSE_EQ|INE002A01018",
        direction="BUY",
        timeframe="5M",
        crossover_time=datetime(2026, 9, 17, 11, 20),
        crossover_time_str="2026-09-17 11:20:00",
        crossover_price=2500.0,
        ema6=2505.0,
        ema30=2500.0,
        prev_ema6=2498.0,
        prev_ema30=2499.0,
        status="PENDING",
        created_at=datetime.now(timezone.utc)
    )
    db.add(sig1)
    db.commit()

    # Attempt inserting identical signal (e.g. from a rescan or app restart)
    sig2 = Signal(
        signal_key=signal_key,
        symbol="RELIANCE",
        instrument_key="NSE_EQ|INE002A01018",
        direction="BUY",
        timeframe="5M",
        crossover_time=datetime(2026, 9, 17, 11, 20),
        crossover_time_str="2026-09-17 11:20:00",
        crossover_price=2500.0,
        ema6=2505.0,
        ema30=2500.0,
        prev_ema6=2498.0,
        prev_ema30=2499.0,
        status="PENDING",
        created_at=datetime.now(timezone.utc)
    )
    db.add(sig2)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()
    db.close()

def test_signal_ranking_newest_first():
    """
    Prompt requirement:
    'Rank signals by most recently confirmed crossover.
    Newest crossover timestamp = highest priority.
    Example:
    1: ABC, 11:20
    2: XYZ, 11:10
    3: PQR, 11:00
    Do not rank by alphabetical order or arbitrary stock order.'
    """
    db = TestingSessionLocal()

    # Insert in mixed / non-chronological order
    signals = [
        Signal(
            signal_key="k1", symbol="PQR", instrument_key="k1", direction="BUY", timeframe="10M",
            crossover_time=datetime(2026, 9, 17, 11, 0), crossover_time_str="11:00",
            crossover_price=100.0, ema6=101, ema30=100, prev_ema6=99, prev_ema30=100, status="PENDING"
        ),
        Signal(
            signal_key="k2", symbol="ABC", instrument_key="k2", direction="BUY", timeframe="10M",
            crossover_time=datetime(2026, 9, 17, 11, 20), crossover_time_str="11:20",
            crossover_price=200.0, ema6=201, ema30=200, prev_ema6=199, prev_ema30=200, status="PENDING"
        ),
        Signal(
            signal_key="k3", symbol="XYZ", instrument_key="k3", direction="BUY", timeframe="10M",
            crossover_time=datetime(2026, 9, 17, 11, 10), crossover_time_str="11:10",
            crossover_price=150.0, ema6=151, ema30=150, prev_ema6=149, prev_ema30=150, status="PENDING"
        ),
    ]
    for s in signals:
        db.add(s)
    db.commit()

    # Query ordered by crossover_time DESC
    from sqlalchemy import desc
    ranked_signals = db.query(Signal).order_by(desc(Signal.crossover_time)).all()

    # ABC (11:20) must be Rank 1, XYZ (11:10) Rank 2, PQR (11:00) Rank 3
    assert ranked_signals[0].symbol == "ABC"
    assert ranked_signals[1].symbol == "XYZ"
    assert ranked_signals[2].symbol == "PQR"
    db.close()
