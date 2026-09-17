import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.config import settings
from app.database import init_db, get_db, SessionLocal, Signal, OrderLog, Instrument, SystemSetting
from app.market import get_market_status, now_ist
from app.scanner import scanner
from app.universe import refresh_instruments
from app.upstox_client import upstox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("scanner.main")

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"

# Active WebSocket connections
connected_websockets: set[WebSocket] = set()

async def broadcast_ws(payload: dict):
    if not connected_websockets:
        return
    dead = set()
    for ws in connected_websockets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    for ws in dead:
        connected_websockets.discard(ws)

# Wire scanner broadcast to WebSocket
scanner.broadcast_callback = broadcast_ws

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing NSE Semi-Algo Scanner Application...")
    init_db()

    # Restore settings from DB
    with SessionLocal() as db:
        tf_setting = db.query(SystemSetting).filter_by(key="timeframe").first()
        if tf_setting and tf_setting.value:
            scanner.timeframe = tf_setting.value
            scanner.stats["selected_timeframe"] = tf_setting.value

        u_setting = db.query(SystemSetting).filter_by(key="universe").first()
        if u_setting and u_setting.value:
            scanner.universe_name = u_setting.value
            scanner.stats["universe_name"] = u_setting.value

        token_setting = db.query(SystemSetting).filter_by(key="upstox_token").first()
        if token_setting and token_setting.value:
            upstox.set_token(token_setting.value)
        elif settings.UPSTOX_ACCESS_TOKEN:
            upstox.set_token(settings.UPSTOX_ACCESS_TOKEN)

    # Check Upstox connection
    if upstox.is_configured():
        try:
            profile = await upstox.validate_token()
            scanner.stats["upstox_connected"] = True
            logger.info("Connected to Upstox account: %s", profile.get("user_name", "Active User"))
        except Exception as e:
            scanner.stats["upstox_connected"] = False
            logger.warning("Upstox token validation on startup failed: %s", e)

    # Automatically start scanner engine
    scanner.start()

    yield

    logger.info("Shutting down scanner application...")
    scanner.stop()
    await upstox.close()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Production-ready NSE Semi-Algo Trading Scanner using Upstox API with EMA 6 / EMA 30 crossover strategy",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for frontend
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Request / Response Models
class TimeframeRequest(BaseModel):
    timeframe: str = Field(..., pattern="^(5M|10M)$")

class UniverseRequest(BaseModel):
    universe: str = Field(..., pattern="^(ALL_NSE|NIFTY500|NIFTY100|NIFTY50)$")

class UpstoxConnectRequest(BaseModel):
    access_token: str = Field(..., min_length=10)

class ManualOrderRequest(BaseModel):
    signal_id: int | None = None
    symbol: str
    instrument_key: str
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)
    order_type: str = Field(default="MARKET", pattern="^(MARKET|LIMIT)$")
    price: float = Field(default=0.0, ge=0.0)
    product: str = Field(default="I", pattern="^(I|D)$")  # I: Intraday (MIS), D: Delivery (CNC)

# ----------------- UI / HTML Route -----------------

@app.get("/")
async def serve_dashboard():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not found")
    return FileResponse(index_path)

# ----------------- Market & Scanner Endpoints -----------------

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.0.0-ema-crossover",
        "market": get_market_status(),
        "scanner_running": scanner.is_running,
        "upstox_connected": upstox.is_configured()
    }

@app.get("/api/market/status")
async def market_status():
    st = get_market_status()
    scanner.stats["market_status"] = st
    return {
        "status": st,
        "timestamp": now_ist().isoformat(),
        "timezone": "Asia/Kolkata"
    }

@app.get("/api/scanner/status")
async def get_scanner_status(db: Session = Depends(get_db)):
    market_st = get_market_status()
    scanner.stats["market_status"] = market_st
    scanner.stats["upstox_connected"] = upstox.is_configured()

    inst_count = db.query(Instrument).filter_by(is_active=True).count()
    scanner.stats["total_universe"] = inst_count

    return {
        "status": scanner.stats,
        "is_running": scanner.is_running,
        "market": market_st,
        "timestamp": now_ist().isoformat()
    }

@app.post("/api/scanner/start")
async def start_scanner():
    scanner.start()
    return {"status": "started", "is_running": True}

@app.post("/api/scanner/stop")
async def stop_scanner():
    scanner.stop()
    return {"status": "stopped", "is_running": False}

@app.post("/api/scanner/scan-now")
async def scan_now():
    if not upstox.is_configured():
        raise HTTPException(status_code=400, detail="Upstox is not connected. Please enter your access token first.")
    asyncio.create_task(scanner.run_scan_cycle())
    return {"status": "scan_initiated"}

# ----------------- Timeframe & Universe Settings -----------------

@app.get("/api/settings/timeframe")
async def get_timeframe():
    return {"timeframe": scanner.timeframe}

@app.post("/api/settings/timeframe")
async def update_timeframe(req: TimeframeRequest):
    scanner.set_timeframe(req.timeframe)
    await broadcast_ws({"type": "TIMEFRAME_CHANGED", "timeframe": req.timeframe})
    return {"status": "updated", "timeframe": scanner.timeframe}

@app.get("/api/settings/universe")
async def get_universe():
    return {"universe": scanner.universe_name}

@app.post("/api/settings/universe")
async def update_universe(req: UniverseRequest):
    scanner.set_universe(req.universe)
    await broadcast_ws({"type": "UNIVERSE_CHANGED", "universe": req.universe})
    return {"status": "updated", "universe": scanner.universe_name}

# ----------------- Upstox API Auth -----------------

@app.get("/api/upstox/status")
async def upstox_status():
    token = upstox.get_token()
    masked = (token[:6] + "..." + token[-4:]) if len(token) > 10 else ""
    return {
        "configured": upstox.is_configured(),
        "masked_token": masked
    }

@app.post("/api/upstox/connect")
async def connect_upstox(req: UpstoxConnectRequest, db: Session = Depends(get_db)):
    upstox.set_token(req.access_token)
    try:
        profile = await upstox.validate_token()
        # Persist token
        setting = db.query(SystemSetting).filter_by(key="upstox_token").first()
        if setting:
            setting.value = req.access_token
        else:
            db.add(SystemSetting(key="upstox_token", value=req.access_token))
        db.commit()

        scanner.stats["upstox_connected"] = True
        return {
            "status": "connected",
            "account_name": profile.get("user_name", "Upstox User"),
            "email": profile.get("email", "")
        }
    except Exception as e:
        upstox.set_token("")
        scanner.stats["upstox_connected"] = False
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

@app.post("/api/upstox/disconnect")
async def disconnect_upstox(db: Session = Depends(get_db)):
    upstox.set_token("")
    scanner.stats["upstox_connected"] = False
    setting = db.query(SystemSetting).filter_by(key="upstox_token").first()
    if setting:
        setting.value = ""
        db.commit()
    return {"status": "disconnected"}

# ----------------- Instruments Management -----------------

@app.get("/api/instruments/count")
async def instruments_count(db: Session = Depends(get_db)):
    count = db.query(Instrument).filter_by(is_active=True).count()
    return {"count": count}

@app.post("/api/instruments/refresh")
async def refresh_universe(db: Session = Depends(get_db)):
    try:
        count = await refresh_instruments(db)
        return {"status": "success", "instruments_loaded": count}
    except Exception as e:
        logger.error("Instrument refresh failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to refresh instruments: {str(e)}")

# ----------------- Signals (Ranked by Newest Crossover First) -----------------

def format_signal_dict(sig: Signal, rank: int) -> dict:
    return {
        "rank": rank,
        "id": sig.id,
        "signal_key": sig.signal_key,
        "symbol": sig.symbol,
        "instrument_key": sig.instrument_key,
        "direction": sig.direction,
        "timeframe": sig.timeframe,
        "crossover_time": sig.crossover_time.isoformat() if sig.crossover_time else "",
        "crossover_time_str": sig.crossover_time_str,
        "crossover_price": sig.crossover_price,
        "ema6": sig.ema6,
        "ema30": sig.ema30,
        "prev_ema6": sig.prev_ema6,
        "prev_ema30": sig.prev_ema30,
        "status": sig.status,
        "created_at": sig.created_at.isoformat() if sig.created_at else ""
    }

@app.get("/api/signals/buy")
async def get_buy_signals(
    timeframe: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db)
):
    """
    Returns BUY signals ranked by most recently confirmed crossover (descending order of crossover_time).
    Newest crossover timestamp = highest priority (Rank 1).
    """
    query = db.query(Signal).filter_by(direction="BUY")
    if timeframe:
        query = query.filter_by(timeframe=timeframe.upper())
    # Strict ranking: newest confirmed crossover timestamp first
    signals = query.order_by(desc(Signal.crossover_time)).limit(limit).all()

    ranked = [format_signal_dict(sig, idx + 1) for idx, sig in enumerate(signals)]
    return {"direction": "BUY", "count": len(ranked), "signals": ranked}

@app.get("/api/signals/sell")
async def get_sell_signals(
    timeframe: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db)
):
    """
    Returns SELL signals ranked by most recently confirmed crossover (descending order of crossover_time).
    Newest crossover timestamp = highest priority (Rank 1).
    """
    query = db.query(Signal).filter_by(direction="SELL")
    if timeframe:
        query = query.filter_by(timeframe=timeframe.upper())
    # Strict ranking: newest confirmed crossover timestamp first
    signals = query.order_by(desc(Signal.crossover_time)).limit(limit).all()

    ranked = [format_signal_dict(sig, idx + 1) for idx, sig in enumerate(signals)]
    return {"direction": "SELL", "count": len(ranked), "signals": ranked}

@app.post("/api/signals/{signal_id}/reject")
async def reject_signal(signal_id: int, db: Session = Depends(get_db)):
    """User manually rejects a signal so it is marked as rejected."""
    sig = db.query(Signal).filter_by(id=signal_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")

    sig.status = "REJECTED"
    db.commit()
    await broadcast_ws({"type": "SIGNAL_STATUS_UPDATED", "id": signal_id, "status": "REJECTED"})
    return {"status": "success", "id": signal_id, "signal_status": "REJECTED"}

# ----------------- Semi-Algo Manual Order Placement -----------------

@app.post("/api/orders/place")
async def place_manual_order(req: ManualOrderRequest, db: Session = Depends(get_db)):
    """
    Semi-algo requirement:
    Live orders can only be placed when the user manually clicks and confirms in the dashboard.
    Never automated.
    """
    if not upstox.is_configured():
        raise HTTPException(status_code=400, detail="Upstox access token is not configured.")

    try:
        res = await upstox.place_order(
            symbol=req.symbol,
            instrument_key=req.instrument_key,
            transaction_type=req.direction,
            quantity=req.quantity,
            order_type=req.order_type,
            price=req.price,
            product=req.product
        )

        order_id = res.get("order_id", "UNKNOWN")

        # Save order log in DB
        order_log = OrderLog(
            signal_id=req.signal_id,
            order_id=order_id,
            symbol=req.symbol,
            instrument_key=req.instrument_key,
            direction=req.direction,
            quantity=req.quantity,
            order_type=req.order_type,
            product=req.product,
            price=req.price,
            status="SUCCESS",
            response_message=str(res.get("data", "")),
            created_at=datetime.now(timezone.utc)
        )
        db.add(order_log)

        # Update signal status if linked
        if req.signal_id:
            sig = db.query(Signal).filter_by(id=req.signal_id).first()
            if sig:
                sig.status = "ORDER_PLACED"

        db.commit()

        await broadcast_ws({
            "type": "ORDER_PLACED",
            "symbol": req.symbol,
            "direction": req.direction,
            "order_id": order_id,
            "signal_id": req.signal_id
        })

        return {
            "status": "SUCCESS",
            "order_id": order_id,
            "message": f"Order for {req.symbol} placed successfully via Upstox."
        }
    except Exception as e:
        logger.error("Manual order execution error: %s", e)
        # Log failure
        order_log = OrderLog(
            signal_id=req.signal_id,
            symbol=req.symbol,
            instrument_key=req.instrument_key,
            direction=req.direction,
            quantity=req.quantity,
            order_type=req.order_type,
            product=req.product,
            price=req.price,
            status="FAILED",
            response_message=str(e),
            created_at=datetime.now(timezone.utc)
        )
        db.add(order_log)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Order execution failed: {str(e)}")

@app.get("/api/orders/history")
async def get_orders_history(db: Session = Depends(get_db)):
    orders = db.query(OrderLog).order_by(desc(OrderLog.id)).limit(100).all()
    return {
        "orders": [
            {
                "id": o.id,
                "order_id": o.order_id,
                "symbol": o.symbol,
                "direction": o.direction,
                "quantity": o.quantity,
                "order_type": o.order_type,
                "product": o.product,
                "price": o.price,
                "status": o.status,
                "response_message": o.response_message,
                "created_at": o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else ""
            }
            for o in orders
        ]
    }

# ----------------- WebSocket Live Stream -----------------

@app.websocket("/ws/live")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_websockets.add(ws)
    try:
        # Send initial state immediately
        await ws.send_json({
            "type": "INIT",
            "market_status": get_market_status(),
            "timeframe": scanner.timeframe,
            "universe": scanner.universe_name,
            "stats": scanner.stats,
            "upstox_connected": upstox.is_configured()
        })
        while True:
            # Keepalive / ping
            await asyncio.sleep(15)
            await ws.send_json({"type": "HEARTBEAT", "market_status": get_market_status(), "time": now_ist().isoformat()})
    except WebSocketDisconnect:
        connected_websockets.discard(ws)
    except Exception:
        connected_websockets.discard(ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
