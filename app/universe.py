import gzip
import json
import logging
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.database import Instrument, SessionLocal

logger = logging.getLogger("scanner.universe")

# Common Nifty 50 benchmarks symbols for quick indexing if requested
NIFTY_50_SYMBOLS = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJFINANCE", "BAJAJFINSV", "BEL", "BPCL", "BHARTIARTL", "BRITANNIA", "CIPLA",
    "COALINDIA", "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA",
    "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM", "TITAN", "TRENT",
    "ULTRACEMCO", "WIPRO"
}

async def fetch_upstox_nse_master() -> list[dict]:
    """
    Download and decompress Upstox's official Begin-of-Day NSE instrument master.
    URL: https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz
    """
    logger.info("Downloading live NSE instrument master from Upstox...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            settings.UPSTOX_INSTRUMENT_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        response.raise_for_status()

    decompressed = gzip.decompress(response.content)
    raw_instruments = json.loads(decompressed)
    logger.info("Downloaded %d total instruments from NSE master", len(raw_instruments))

    # Filter for active NSE Equities only
    equities = []
    for item in raw_instruments:
        segment = item.get("segment")
        inst_type = item.get("instrument_type")
        symbol = item.get("trading_symbol")
        key = item.get("instrument_key")

        # NSE_EQ segment and EQ/EQUITY type
        if segment == "NSE_EQ" and inst_type in ("EQ", "EQUITY") and symbol and key:
            equities.append({
                "instrument_key": key,
                "symbol": symbol.strip().upper(),
                "name": item.get("name") or symbol,
                "segment": "NSE_EQ",
                "instrument_type": "EQ",
                "lot_size": int(item.get("lot_size") or 1),
                "tick_size": float(item.get("tick_size") or 0.05),
                "is_active": True,
            })

    logger.info("Extracted %d valid NSE Equities", len(equities))
    return equities

def sync_instruments_to_db(instruments: list[dict], db: Session) -> int:
    """Synchronize downloaded NSE instruments into the database."""
    count = 0
    now = datetime.now(timezone.utc)
    for data in instruments:
        existing = db.query(Instrument).filter_by(instrument_key=data["instrument_key"]).first()
        if existing:
            existing.symbol = data["symbol"]
            existing.name = data["name"]
            existing.lot_size = data["lot_size"]
            existing.tick_size = data["tick_size"]
            existing.is_active = True
            existing.updated_at = now
        else:
            inst = Instrument(
                instrument_key=data["instrument_key"],
                symbol=data["symbol"],
                name=data["name"],
                segment=data["segment"],
                instrument_type=data["instrument_type"],
                lot_size=data["lot_size"],
                tick_size=data["tick_size"],
                is_active=True,
                updated_at=now,
            )
            db.add(inst)
        count += 1
    db.commit()
    logger.info("Synchronized %d instruments into database", count)
    return count

async def refresh_instruments(db: Session) -> int:
    """Download fresh instrument master and update database."""
    items = await fetch_upstox_nse_master()
    return sync_instruments_to_db(items, db)

def get_active_universe(db: Session, universe_name: str = "ALL_NSE") -> list[dict]:
    """
    Retrieve active stocks for the scanner.
    If database has no instruments yet, seed with basic Nifty 50 or full master.
    """
    query = db.query(Instrument).filter_by(is_active=True)
    rows = query.all()

    if not rows:
        return []

    instruments = [
        {
            "instrument_key": r.instrument_key,
            "symbol": r.symbol,
            "name": r.name,
            "lot_size": r.lot_size,
            "tick_size": r.tick_size
        }
        for r in rows
    ]

    universe_name = universe_name.upper()
    if universe_name == "NIFTY50":
        return [i for i in instruments if i["symbol"] in NIFTY_50_SYMBOLS]
    elif universe_name in ("NIFTY500", "NIFTY100"):
        # For NIFTY 100/500, return top alphabetically or liquid subset if available
        limit = 500 if universe_name == "NIFTY500" else 100
        return instruments[:limit]

    # Default: ALL_NSE (all available NSE equities)
    return instruments
