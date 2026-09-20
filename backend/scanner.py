import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import pandas as pd
from sqlalchemy.orm import Session
from backend.config import settings
from backend.models import ScanRun, ScanResult
from backend.database import SessionLocal, cleanup_old_scans
from backend.universe import universe_manager
from backend.upstox_client import upstox_api, UpstoxAuthExpiredException

logger = logging.getLogger("scanner.engine")

class ScannerState:
    """Holds real-time scanner state for the frontend to monitor."""
    def __init__(self):
        self.is_running: bool = False
        self.should_stop: bool = False
        self.stage: str = "Idle"
        self.stocks_scanned: int = 0
        self.total_stocks: int = 0
        self.signals_found: int = 0
        self.progress_pct: float = 0.0
        self.current_stock: str = ""
        self.error_message: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.logs: List[str] = []
        self.latest_results: List[Dict[str, Any]] = []

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        if len(self.logs) > 100:
            self.logs.pop(0)
        logger.info(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "stage": self.stage,
            "stocks_scanned": self.stocks_scanned,
            "total_stocks": self.total_stocks,
            "signals_found": self.signals_found,
            "progress_pct": round(self.progress_pct, 1),
            "current_stock": self.current_stock,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "logs": self.logs[-20:],
            "results_count": len(self.latest_results)
        }

scanner_state = ScannerState()

def detect_crossover(candles: List[Dict[str, Any]], symbol: str, company: str) -> Optional[Dict[str, Any]]:
    """
    Given completed daily candles:
    1. Verifies sufficiency of data (minimum 31 completed candles for SMA 30 + 1 prev comparison).
    2. Calculates SMA 6 and SMA 30 on Close prices.
    3. Detects confirmed crossovers:
       - Bullish: prev candle SMA6 <= SMA30, current candle SMA6 > SMA30. Signal: BULLISH
       - Bearish: prev candle SMA6 >= SMA30, current candle SMA6 < SMA30. Signal: BEARISH
    4. Identifies the most recent crossover event.
    """
    if len(candles) < 31:
        return None

    # Sort ascending by timestamp
    df = pd.DataFrame(candles)
    # Parse timestamp
    df["dt"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values(by="dt", ascending=True).reset_index(drop=True)

    # Filter out current day incomplete candle if still within market hours or incomplete
    now = datetime.now()
    if not df.empty:
        last_dt = df["dt"].iloc[-1]
        if last_dt.date() == now.date() and (now.hour < 15 or (now.hour == 15 and now.minute < 35)):
            df = df.iloc[:-1].reset_index(drop=True)

    if len(df) < 31:
        return None

    # Calculate SMA 6 and SMA 30
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["sma6"] = df["close"].rolling(window=6).mean()
    df["sma30"] = df["close"].rolling(window=30).mean()

    # Drop rows where SMA 30 is NaN
    valid_df = df.dropna(subset=["sma6", "sma30"]).reset_index(drop=True)
    if len(valid_df) < 2:
        return None

    # Search for all crossover events chronologically to find the most recent
    crossovers = []
    for i in range(1, len(valid_df)):
        prev_sma6 = valid_df["sma6"].iloc[i - 1]
        prev_sma30 = valid_df["sma30"].iloc[i - 1]
        curr_sma6 = valid_df["sma6"].iloc[i]
        curr_sma30 = valid_df["sma30"].iloc[i]
        curr_close = valid_df["close"].iloc[i]
        crossover_dt = valid_df["dt"].iloc[i]
        if crossover_dt.hour == 0 and crossover_dt.minute == 0:
            crossover_date_str = str(crossover_dt.strftime("%Y-%m-%d"))
        else:
            crossover_date_str = str(crossover_dt.strftime("%Y-%m-%d %H:%M"))

        # Bullish crossover
        if prev_sma6 <= prev_sma30 and curr_sma6 > curr_sma30:
            crossovers.append({
                "symbol": symbol,
                "company": company,
                "signal_type": "BULLISH",
                "crossover_date": crossover_date_str,
                "close": round(curr_close, 2),
                "sma6": round(curr_sma6, 2),
                "sma30": round(curr_sma30, 2),
            })
        # Bearish crossover
        elif prev_sma6 >= prev_sma30 and curr_sma6 < curr_sma30:
            crossovers.append({
                "symbol": symbol,
                "company": company,
                "signal_type": "BEARISH",
                "crossover_date": crossover_date_str,
                "close": round(curr_close, 2),
                "sma6": round(curr_sma6, 2),
                "sma30": round(curr_sma30, 2),
            })

    # Return the most recent crossover for this stock
    if crossovers:
        return crossovers[-1]
    return None

def build_ranked_dataframe(signals: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Ranks signals:
    1. Sorts by crossover_date DESC (most recent first).
    2. Assigns Rank 1, 2, 3...
    3. Returns exact columns:
       Rank, Symbol, Company, Signal Type, Crossover Date, Close, SMA 6, SMA 30
    """
    if not signals:
        return pd.DataFrame(columns=[
            "Rank", "Symbol", "Company", "Signal Type", "Crossover Date", "Close", "SMA 6", "SMA 30"
        ])

    df = pd.DataFrame(signals)
    # Sort by crossover_date DESC, secondary sort by Symbol
    df = df.sort_values(by=["crossover_date", "symbol"], ascending=[False, True]).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))

    # Rename & order exact required columns
    df = df.rename(columns={
        "symbol": "Symbol",
        "company": "Company",
        "signal_type": "Signal Type",
        "crossover_date": "Crossover Date",
        "close": "Close",
        "sma6": "SMA 6",
        "sma30": "SMA 30"
    })

    # Format numeric columns to 2 decimal places
    df["Close"] = df["Close"].apply(lambda x: f"{float(x):.2f}")
    df["SMA 6"] = df["SMA 6"].apply(lambda x: f"{float(x):.2f}")
    df["SMA 30"] = df["SMA 30"].apply(lambda x: f"{float(x):.2f}")

    return df[["Rank", "Symbol", "Company", "Signal Type", "Crossover Date", "Close", "SMA 6", "SMA 30"]]

async def execute_scanner(access_token: Optional[str] = None):
    """
    Main scanner execution loop:
    1. Verify Upstox authentication
    2. Load NIFTY 100 + NIFTY 200 universe
    3. Load Upstox instrument master
    4. Map symbols -> instrument_key
    5. Fetch historical daily candles
    6. Calculate SMA 6 and SMA 30
    7. Detect confirmed crossovers
    8. Find latest crossover per stock
    9. Rank by latest crossover date
    10. Save scan results to DB
    11. Return results
    """
    scanner_state.is_running = True
    scanner_state.should_stop = False
    scanner_state.error_message = None
    scanner_state.started_at = datetime.now(timezone.utc)
    scanner_state.completed_at = None
    scanner_state.stocks_scanned = 0
    scanner_state.signals_found = 0
    scanner_state.progress_pct = 0.0
    scanner_state.logs.clear()

    db: Session = SessionLocal()
    scan_run = ScanRun(
        started_at=datetime.now(timezone.utc),
        status="RUNNING"
    )
    db.add(scan_run)
    db.commit()
    db.refresh(scan_run)

    try:
        # Step 1: Universe & Instruments
        scanner_state.stage = "Loading stock universe & Upstox instruments..."
        scanner_state.log("Loading NIFTY 100 + NIFTY 200 universe...")
        universe = await universe_manager.get_universe()

        if not universe:
            raise RuntimeError("Failed to load stock universe or instrument mapping.")

        scanner_state.total_stocks = len(universe)
        scanner_state.log(f"Ready to scan {len(universe)} NSE equity stocks.")

        # Step 2: Scan stocks
        signals: List[Dict[str, Any]] = []

        async def process_stock(stock: Dict[str, Any]):
            if scanner_state.should_stop:
                return

            symbol = stock["symbol"]
            company = stock["company"]
            inst_key = stock["instrument_key"]
            scanner_state.current_stock = symbol

            try:
                candles = await upstox_api.fetch_10min_candles(
                    instrument_key=inst_key,
                    access_token=access_token,
                    lookback_days=settings.INTRADAY_LOOKBACK_DAYS
                )
                if candles:
                    signal = detect_crossover(candles, symbol, company)
                    if signal:
                        signals.append(signal)
                        scanner_state.signals_found = len(signals)
                        scanner_state.log(
                            f"Signal found: {symbol} - {signal['signal_type']} (Crossed on {signal['crossover_date']})"
                        )
            except UpstoxAuthExpiredException:
                scanner_state.error_message = "Upstox authentication expired. Please reconnect your Upstox account."
                scanner_state.log(scanner_state.error_message)
                scanner_state.should_stop = True
                raise
            except Exception as e:
                scanner_state.log(f"Unable to retrieve historical data for {symbol}. Skipping: {e}")
            finally:
                scanner_state.stocks_scanned += 1
                if scanner_state.total_stocks > 0:
                    scanner_state.progress_pct = (scanner_state.stocks_scanned / scanner_state.total_stocks) * 100
                if scanner_state.stocks_scanned % 25 == 0 or scanner_state.stocks_scanned == scanner_state.total_stocks:
                    scanner_state.log(f"Scanning {scanner_state.stocks_scanned} / {scanner_state.total_stocks}")

        # Run stock requests concurrently using worker tasks with rate control
        tasks = [process_stock(stock) for stock in universe]
        # Execute in gathered chunks or concurrently
        await asyncio.gather(*tasks, return_exceptions=True)

        if scanner_state.should_stop and scanner_state.error_message:
            scan_run.status = "FAILED"
            scan_run.error_message = scanner_state.error_message
            db.commit()
            return

        # Step 3: Ranking
        scanner_state.stage = "Ranking detected signals..."
        scanner_state.log("Ranking signals by most recent crossover date...")

        df_ranked = build_ranked_dataframe(signals)
        results_records = df_ranked.to_dict(orient="records")
        scanner_state.latest_results = results_records

        # Step 4: Save to Database
        scan_run.completed_at = datetime.now(timezone.utc)
        scan_run.stocks_scanned = scanner_state.stocks_scanned
        scan_run.signals_found = len(results_records)
        scan_run.status = "COMPLETED"

        for row in results_records:
            result_entry = ScanResult(
                scan_id=scan_run.id,
                rank=int(row["Rank"]),
                symbol=str(row["Symbol"]),
                company=str(row["Company"]),
                signal_type=str(row["Signal Type"]),
                crossover_date=str(row["Crossover Date"]),
                close=float(row["Close"]),
                sma6=float(row["SMA 6"]),
                sma30=float(row["SMA 30"]),
            )
            db.add(result_entry)

        db.commit()
        scanner_state.log(f"Scan complete. Found {len(results_records)} confirmed crossovers.")
        scanner_state.stage = "Completed"

        # Step 5: Database cleanup policy
        cleanup_old_scans(db, keep_latest=1)

    except UpstoxAuthExpiredException:
        scan_run.status = "FAILED"
        scan_run.error_message = "Upstox authentication expired. Please reconnect your Upstox account."
        db.commit()
    except Exception as e:
        logger.exception("Scanner execution error: %s", e)
        scanner_state.error_message = str(e)
        scanner_state.stage = "Failed"
        scan_run.status = "FAILED"
        scan_run.error_message = str(e)
        db.commit()
    finally:
        scanner_state.is_running = False
        scanner_state.completed_at = datetime.now(timezone.utc)
        db.close()
