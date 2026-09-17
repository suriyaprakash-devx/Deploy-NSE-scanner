import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal, Signal

@pytest.fixture(scope="module", autouse=True)
def setup_app_db():
    init_db()
    with SessionLocal() as db:
        db.query(Signal).filter(Signal.signal_key.like("test:api:%")).delete(synchronize_session=False)
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(Signal).filter(Signal.signal_key.like("test:api:%")).delete(synchronize_session=False)
        db.commit()

client = TestClient(app)

def test_market_status_endpoint():
    res = client.get("/api/market/status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert data["timezone"] == "Asia/Kolkata"

def test_scanner_status_endpoint():
    res = client.get("/api/scanner/status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "market" in data
    assert "is_running" in data

def test_timeframe_switch():
    res = client.post("/api/settings/timeframe", json={"timeframe": "10M"})
    assert res.status_code == 200
    assert res.json()["timeframe"] == "10M"

    res_get = client.get("/api/settings/timeframe")
    assert res_get.json()["timeframe"] == "10M"

    res2 = client.post("/api/settings/timeframe", json={"timeframe": "5M"})
    assert res2.status_code == 200
    assert res2.json()["timeframe"] == "5M"

    bad_res = client.post("/api/settings/timeframe", json={"timeframe": "15M"})
    assert bad_res.status_code == 422

def test_universe_switch():
    res = client.post("/api/settings/universe", json={"universe": "NIFTY500"})
    assert res.status_code == 200
    assert res.json()["universe"] == "NIFTY500"

    res2 = client.post("/api/settings/universe", json={"universe": "ALL_NSE"})
    assert res2.status_code == 200

def test_signals_endpoints_ranking():
    uid = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        s1 = Signal(
            signal_key=f"test:api:buy1_{uid}",
            symbol="RELIANCE",
            instrument_key="NSE_EQ|INE002A01018",
            direction="BUY",
            timeframe="5M",
            crossover_time=datetime(2026, 9, 17, 10, 20),
            crossover_time_str="2026-09-17 10:20:00",
            crossover_price=2500.0,
            ema6=2510.0,
            ema30=2505.0,
            prev_ema6=2502.0,
            prev_ema30=2504.0,
            status="PENDING",
            created_at=datetime.now(timezone.utc)
        )
        s2 = Signal(
            signal_key=f"test:api:buy2_{uid}",
            symbol="TCS",
            instrument_key="NSE_EQ|INE467B01029",
            direction="BUY",
            timeframe="5M",
            crossover_time=datetime(2026, 9, 17, 10, 45),  # Newer!
            crossover_time_str="2026-09-17 10:45:00",
            crossover_price=4200.0,
            ema6=4210.0,
            ema30=4205.0,
            prev_ema6=4201.0,
            prev_ema30=4203.0,
            status="PENDING",
            created_at=datetime.now(timezone.utc)
        )
        db.add_all([s1, s2])
        db.commit()

    res = client.get("/api/signals/buy?timeframe=5M")
    assert res.status_code == 200
    data = res.json()
    assert data["direction"] == "BUY"
    signals = data["signals"]
    assert len(signals) >= 2

    # Verification of ranking: Newest crossover timestamp = highest priority (Rank 1)
    tcs_sig = next(s for s in signals if s["symbol"] == "TCS")
    rel_sig = next(s for s in signals if s["symbol"] == "RELIANCE")
    assert tcs_sig["rank"] < rel_sig["rank"]

def test_reject_signal_endpoint():
    uid = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        sig = Signal(
            signal_key=f"test:api:reject_{uid}",
            symbol="INFY",
            instrument_key="NSE_EQ|INE009A01021",
            direction="BUY",
            timeframe="5M",
            crossover_time=datetime(2026, 9, 17, 11, 0),
            crossover_time_str="2026-09-17 11:00:00",
            crossover_price=1800.0,
            ema6=1805.0,
            ema30=1800.0,
            prev_ema6=1795.0,
            prev_ema30=1798.0,
            status="PENDING",
            created_at=datetime.now(timezone.utc)
        )
        db.add(sig)
        db.commit()
        sig_id = sig.id

    res = client.post(f"/api/signals/{sig_id}/reject")
    assert res.status_code == 200
    assert res.json()["signal_status"] == "REJECTED"

    with SessionLocal() as db:
        updated = db.query(Signal).filter_by(id=sig_id).first()
        assert updated.status == "REJECTED"

def test_manual_order_requires_upstox_token():
    res = client.post("/api/orders/place", json={
        "symbol": "INFY",
        "instrument_key": "NSE_EQ|INE009A01021",
        "direction": "BUY",
        "quantity": 5,
        "order_type": "MARKET",
        "price": 0.0,
        "product": "I"
    })
    assert res.status_code == 400
    assert "token" in res.json()["detail"].lower()
