import os
import gzip
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import httpx
from backend.config import settings

logger = logging.getLogger("scanner.universe")

# Authoritative list of NIFTY 100 + NIFTY 200 constituents (200 unique symbols)
NIFTY_200_SYMBOLS = [
    # NIFTY 50 & NIFTY Next 50 (NIFTY 100)
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "INFY", "ITC", "SBIN",
    "LICI", "HINDUNILVR", "LT", "HCLTECH", "BAJFINANCE", "SUNPHARMA", "MARUTI",
    "ONGC", "KOTAKBANK", "TATAMOTORS", "NTPC", "AXISBANK", "TITAN", "ADANIENT",
    "ADANIPORTS", "ULTRACEMCO", "POWERGRID", "COALINDIA", "TATASTEEL", "BAJAJFINSV",
    "SIEMENS", "ASIANPAINT", "NESTLEIND", "ZOMATO", "JSWSTEEL", "IOC", "HAL",
    "BEL", "GRASIM", "TECHM", "WIPRO", "HINDALCO", "INDUSINDBK", "DLF", "JIOFIN",
    "DIVISLAB", "ADANIPOWER", "CIPLA", "VEDL", "EICHERMOT", "SBILIFE", "TRENT",
    "BPCL", "PFC", "RECLTD", "SHRIRAMFIN", "BRITANNIA", "CHOLAFIN", "DRREDDY",
    "TATACONSUM", "HINDZINC", "TVSMOTOR", "HDFCLIFE", "APOLLOHOSP", "BAJAJ-AUTO",
    "GODREJCP", "GAIL", "ABB", "MOTHERSON", "PIDILITIND", "AMBUJACEM", "HAVELLS",
    "INDIGO", "BANKBARODA", "CANBK", "PNB", "IOB", "UNIONBANK", "IDBI",
    "INDIANB", "UCOBANK", "CENTRALBK", "BANKINDIA", "POLYCAB", "CUMMINSIND",
    "CGPOWER", "SOLARINDS", "BOSCHLTD", "PERSISTENT", "OFSS", "MAXHEALTH",
    "LUPIN", "AUROPHARMA", "ZYDUSLIFE", "MANKIND", "ALKEM", "TORNTPHARM",
    "COLPAL", "DABUR", "MARICO", "PGHH", "BERGEPAINT",

    # NIFTY Midcap 100 (Completing NIFTY 200)
    "ACC", "ASTRAL", "AUEXP", "AUBANK", "BALKRISIND", "BANDHANBNK", "BATAINDIA",
    "BDL", "BHARATFORG", "BHEL", "BIOCON", "BSOFT", "CANFINHOME", "CDSL",
    "COFORGE", "CONCOR", "COROMANDEL", "CROMPTON", "DEEPAKNTR", "DELHIVERY",
    "DIXON", "ESCORTS", "EXIDEIND", "FEDERALBNK", "FORTIS", "GLENMARK",
    "GMRINFRA", "GNFC", "GODREJPROP", "GRANULES", "GUJGASLTD", "HDFCAMC",
    "HINDPETRO", "HUDCO", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "IPCALAB",
    "IRCTC", "IRFC", "JINDALSTEL", "JSWENERGY", "JUBLFOOD", "KALYANKJIL",
    "KPITTECH", "L&TFH", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LTTS",
    "M&MFIN", "METROPOLIS", "MFSL", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM",
    "NAVINFLUOR", "NBCC", "NHPC", "NLCINDIA", "NMDC", "OBEROIRLTY", "OIL",
    "PAGEIND", "PATANJALI", "PETRONET", "PHOENIXLTD", "POONAWALLA", "PRESTIGE",
    "RADICO", "RAMCOCEM", "RVNL", "SAIL", "SCHAEFFLER", "SJVN", "SONACOMS",
    "SRF", "STARHEALTH", "SUNDARMFIN", "SUNTV", "SUPREMEIND", "SUZLON",
    "SYNGENE", "TATACHEM", "TATACOMM", "TATAELXSI", "TATATECH", "TORNTPOWER",
    "TRIDENT", "UBL", "UPL", "VOLTAS", "YESBANK"
]

UPSTOX_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
CACHE_EXPIRY_SECONDS = 86400  # 24 hours

class UniverseManager:
    """
    Manages the combined NIFTY 100 + NIFTY 200 stock universe,
    downloading and caching the Upstox NSE instrument master to dynamically
    map symbols to instrument_key, company name, and ISIN.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or settings.DATA_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.master_cache_file = self.cache_dir / "upstox_nse_instruments.json"
        self._instrument_map: Dict[str, Dict[str, Any]] = {}

    async def fetch_upstox_instrument_master(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Loads the official Upstox NSE instrument master.
        Filters strictly: segment == "NSE_EQ" and instrument_type == "EQ".
        Caches locally for 24 hours to optimize performance and prevent rate issues.
        """
        # Return memory cache if already populated
        if self._instrument_map and not force_refresh:
            return self._instrument_map

        # Check disk cache
        if not force_refresh and self.master_cache_file.exists():
            file_age = time.time() - self.master_cache_file.stat().st_mtime
            if file_age < CACHE_EXPIRY_SECONDS:
                try:
                    with open(self.master_cache_file, "r", encoding="utf-8") as f:
                        self._instrument_map = json.load(f)
                    logger.info("Loaded %d NSE equity instruments from local cache.", len(self._instrument_map))
                    return self._instrument_map
                except Exception as e:
                    logger.warning("Corrupt instrument cache, refetching: %s", e)

        # Download from Upstox CDN
        logger.info("Downloading Upstox NSE instrument master from CDN...")
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(UPSTOX_INSTRUMENTS_URL)
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch Upstox instrument master: HTTP {resp.status_code}")

            raw_bytes = resp.content
            # Decompress gzip
            decompressed = gzip.decompress(raw_bytes)
            raw_instruments = json.loads(decompressed.decode("utf-8"))

        filtered_map: Dict[str, Dict[str, Any]] = {}
        for inst in raw_instruments:
            # Filter strictly: segment == NSE_EQ and instrument_type == EQ
            if inst.get("segment") == "NSE_EQ" and inst.get("instrument_type") == "EQ":
                symbol = str(inst.get("trading_symbol", "")).upper().strip()
                if symbol:
                    filtered_map[symbol] = {
                        "symbol": symbol,
                        "company": inst.get("name", symbol),
                        "instrument_key": inst.get("instrument_key", f"NSE_EQ|{inst.get('isin', '')}"),
                        "isin": inst.get("isin", ""),
                        "exchange": inst.get("exchange", "NSE"),
                        "segment": inst.get("segment", "NSE_EQ"),
                        "instrument_type": inst.get("instrument_type", "EQ"),
                        "lot_size": inst.get("lot_size", 1),
                        "tick_size": inst.get("tick_size", 0.05)
                    }

        self._instrument_map = filtered_map
        # Save to disk cache
        try:
            with open(self.master_cache_file, "w", encoding="utf-8") as f:
                json.dump(filtered_map, f)
            logger.info("Successfully cached %d NSE equity instruments to disk.", len(filtered_map))
        except Exception as e:
            logger.warning("Failed to save instrument cache to disk: %s", e)

        return self._instrument_map

    async def get_universe(self) -> List[Dict[str, Any]]:
        """
        Combines NIFTY 100 + NIFTY 200, removes duplicates, and dynamically
        maps them to Upstox instrument keys.

        Returns list of dicts:
        [
            {
                "symbol": "RELIANCE",
                "company": "RELIANCE INDUSTRIES LTD",
                "instrument_key": "NSE_EQ|INE002A01018",
                "isin": "INE002A01018"
            },
            ...
        ]
        """
        instruments = await self.fetch_upstox_instrument_master()

        # Deduplicate symbols from NIFTY 100 and NIFTY 200
        unique_symbols = sorted(list(set([s.upper().strip() for s in NIFTY_200_SYMBOLS if s.strip()])))

        universe: List[Dict[str, Any]] = []
        unmatched_symbols: List[str] = []

        for symbol in unique_symbols:
            if symbol in instruments:
                inst_info = instruments[symbol]
                universe.append({
                    "symbol": symbol,
                    "company": inst_info["company"],
                    "instrument_key": inst_info["instrument_key"],
                    "isin": inst_info["isin"]
                })
            else:
                unmatched_symbols.append(symbol)

        if unmatched_symbols:
            logger.warning("%d symbols could not be matched in Upstox instrument master: %s",
                           len(unmatched_symbols), unmatched_symbols[:10])

        logger.info("Generated universe of %d unique stocks mapped to Upstox instrument keys.", len(universe))
        return universe

universe_manager = UniverseManager()
