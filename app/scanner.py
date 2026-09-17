import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Any
import httpx
from sqlalchemy.orm import Session
from app.config import settings
from app.database import SessionLocal, Signal, SystemSetting, Instrument
from app.market import get_market_status, now_ist
from app.strategy import detect_ema_crossover, CrossoverSignal
from app.universe import get_active_universe, refresh_instruments
from app.upstox_client import upstox

logger = logging.getLogger("scanner.engine")

class ScannerEngine:
    def __init__(self):
        self.is_running = False
        self._scan_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        # Dynamic state
        self.timeframe = settings.DEFAULT_TIMEFRAME  # "5M" or "10M"
        self.universe_name = settings.SCAN_UNIVERSE   # "ALL_NSE", "NIFTY500", etc.

        # Live statistics
        self.stats = {
            "market_status": "CLOSED",
            "selected_timeframe": self.timeframe,
            "universe_name": self.universe_name,
            "last_scan_time": None,
            "last_scan_duration_sec": 0.0,
            "stocks_scanned": 0,
            "successful_scans": 0,
            "failed_scans": 0,
            "total_universe": 0,
            "signals_detected_today": 0,
            "is_running": False,
            "upstox_connected": False,
            "status_message": "Scanner initialized and ready."
        }

        # WebSocket subscribers callback
        self.broadcast_callback: Callable[[dict], Any] | None = None

    def set_timeframe(self, timeframe: str):
        """Dynamically switch between 5M and 10M."""
        tf = timeframe.upper().strip()
        if tf not in ("5M", "10M"):
            raise ValueError("Timeframe must be 5M or 10M")
        self.timeframe = tf
        self.stats["selected_timeframe"] = tf
        logger.info("Scanner timeframe changed to %s", tf)

        # Save to database
        with SessionLocal() as db:
            setting = db.query(SystemSetting).filter_by(key="timeframe").first()
            if setting:
                setting.value = tf
            else:
                db.add(SystemSetting(key="timeframe", value=tf))
            db.commit()

    def set_universe(self, universe: str):
        """Change the active scanning universe."""
        u = universe.upper().strip()
        self.universe_name = u
        self.stats["universe_name"] = u
        logger.info("Scanner universe set to %s", u)

        with SessionLocal() as db:
            setting = db.query(SystemSetting).filter_by(key="universe").first()
            if setting:
                setting.value = u
            else:
                db.add(SystemSetting(key="universe", value=u))
            db.commit()

    async def notify_subscribers(self, event_type: str, data: dict):
        if self.broadcast_callback:
            try:
                await self.broadcast_callback({"type": event_type, "data": data, "timestamp": now_ist().isoformat()})
            except Exception as e:
                logger.debug("Failed to broadcast WebSocket update: %s", e)

    async def send_telegram_alert(self, signal: CrossoverSignal):
        """Send optional Telegram alert for newly detected signal."""
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
            return

        icon = "🟢" if signal.direction == "BUY" else "🔴"
        text = (
            f"⚡ *EMA CROSSOVER SIGNAL DETECTED* ⚡\n\n"
            f"*Stock*: `{signal.symbol}`\n"
            f"*Signal*: *{signal.direction}* {icon}\n"
            f"*Timeframe*: `{signal.timeframe}`\n"
            f"*Crossover Price*: ₹{signal.crossover_price:,.2f}\n"
            f"*EMA 6*: {signal.ema6} | *EMA 30*: {signal.ema30}\n"
            f"*Prev EMA 6*: {signal.prev_ema6} | *Prev EMA 30*: {signal.prev_ema30}\n"
            f"*Candle Closed*: {signal.crossover_time_str} IST\n\n"
            f"⚠️ *Semi-Algo Notice*: Order requires manual approval on your dashboard."
        )

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
                await client.post(url, json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "Markdown"
                })
        except Exception as e:
            logger.warning("Failed to send Telegram notification: %s", e)

    def record_signal_if_new(self, sig: CrossoverSignal) -> bool:
        """
        Duplicate protection:
        Ensures the signal identifier (date + instrument + timeframe + direction + crossover candle timestamp)
        does not already exist. If new, inserts into database.
        Returns True if newly inserted, False if duplicate.
        """
        with SessionLocal() as db:
            existing = db.query(Signal).filter_by(signal_key=sig.signal_key).first()
            if existing:
                return False

            new_sig = Signal(
                signal_key=sig.signal_key,
                symbol=sig.symbol,
                instrument_key=sig.instrument_key,
                direction=sig.direction,
                timeframe=sig.timeframe,
                crossover_time=sig.crossover_time,
                crossover_time_str=sig.crossover_time_str,
                crossover_price=sig.crossover_price,
                ema6=sig.ema6,
                ema30=sig.ema30,
                prev_ema6=sig.prev_ema6,
                prev_ema30=sig.prev_ema30,
                status="PENDING",
                created_at=datetime.now(timezone.utc)
            )
            db.add(new_sig)
            try:
                db.commit()
                return True
            except Exception as e:
                db.rollback()
                logger.warning("Duplicate signal insertion prevented by DB constraint: %s", e)
                return False

    async def scan_single_stock(self, item: dict, interval_minutes: int, current_dt: datetime) -> CrossoverSignal | None:
        """Scan a single stock with full error isolation."""
        key = item["instrument_key"]
        symbol = item["symbol"]

        try:
            # Fetch candles up to current completed candle
            candles = await upstox.fetch_candles(key, interval_minutes=interval_minutes, days_back=5)
            if not candles:
                return None

            signal = detect_ema_crossover(
                symbol=symbol,
                instrument_key=key,
                raw_candles=candles,
                timeframe=self.timeframe,
                current_dt=current_dt
            )
            return signal
        except Exception as e:
            logger.debug("Error scanning stock %s (%s): %s", symbol, key, e)
            raise

    async def run_scan_cycle(self):
        """Execute one complete scan across all stocks in the active universe."""
        t_start = datetime.now()
        market_st = get_market_status()
        self.stats["market_status"] = market_st
        self.stats["upstox_connected"] = upstox.is_configured()

        # Load universe
        with SessionLocal() as db:
            universe = get_active_universe(db, self.universe_name)

        if not universe:
            # Attempt to refresh instruments if database is empty
            logger.info("No active universe in DB, refreshing from Upstox master...")
            try:
                with SessionLocal() as db:
                    await refresh_instruments(db)
                    universe = get_active_universe(db, self.universe_name)
            except Exception as e:
                logger.error("Failed to load Upstox instrument master: %s", e)
                self.stats["status_message"] = "Waiting for instrument master download..."
                return

        self.stats["total_universe"] = len(universe)
        self.stats["stocks_scanned"] = 0
        self.stats["successful_scans"] = 0
        self.stats["failed_scans"] = 0
        self.stats["status_message"] = f"Scanning {len(universe)} NSE stocks ({self.timeframe})..."

        interval_minutes = 10 if self.timeframe == "10M" else 5
        current_dt = now_ist()
        new_signals_count = 0

        # Concurrent scanning with rate limiter & error isolation
        chunk_size = 50
        for i in range(0, len(universe), chunk_size):
            if self._stop_event.is_set():
                break

            chunk = universe[i:i + chunk_size]
            tasks = []
            for item in chunk:
                tasks.append(self.scan_single_stock(item, interval_minutes, current_dt))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for item, res in zip(chunk, results):
                self.stats["stocks_scanned"] += 1
                if isinstance(res, Exception):
                    self.stats["failed_scans"] += 1
                else:
                    self.stats["successful_scans"] += 1
                    if isinstance(res, CrossoverSignal):
                        is_new = self.record_signal_if_new(res)
                        if is_new:
                            new_signals_count += 1
                            self.stats["signals_detected_today"] += 1
                            logger.info("NEW %s SIGNAL DETECTED: %s at ₹%.2f (%s)",
                                        res.direction, res.symbol, res.crossover_price, res.crossover_time_str)
                            # Broadcast real-time event
                            await self.notify_subscribers("NEW_SIGNAL", {
                                "symbol": res.symbol,
                                "direction": res.direction,
                                "timeframe": res.timeframe,
                                "price": res.crossover_price,
                                "ema6": res.ema6,
                                "ema30": res.ema30,
                                "crossover_time": res.crossover_time_str
                            })
                            # Send Telegram alert
                            asyncio.create_task(self.send_telegram_alert(res))

            # Broadcast progress periodically
            await self.notify_subscribers("SCAN_PROGRESS", {
                "stocks_scanned": self.stats["stocks_scanned"],
                "total_universe": self.stats["total_universe"],
                "successful_scans": self.stats["successful_scans"],
                "failed_scans": self.stats["failed_scans"]
            })

        t_end = datetime.now()
        duration = (t_end - t_start).total_seconds()
        self.stats["last_scan_duration_sec"] = round(duration, 2)
        self.stats["last_scan_time"] = current_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        self.stats["status_message"] = f"Scan completed in {duration:.1f}s. {new_signals_count} new signals."
        logger.info("Scan completed: %d stocks scanned in %.1fs (%d success, %d failed, %d new signals)",
                    self.stats["stocks_scanned"], duration, self.stats["successful_scans"],
                    self.stats["failed_scans"], new_signals_count)

        await self.notify_subscribers("SCAN_COMPLETED", self.stats)

    async def _runner_loop(self):
        """Continuous scanning loop with configurable interval."""
        logger.info("Scanner runner loop started.")
        while not self._stop_event.is_set():
            try:
                if upstox.is_configured():
                    await self.run_scan_cycle()
                else:
                    self.stats["status_message"] = "Awaiting Upstox Access Token connection."
            except Exception as e:
                logger.exception("Scanner cycle encountered unhandled error: %s", e)
                self.stats["status_message"] = f"Scan cycle error: {type(e).__name__}"

            # Wait before next scan cycle
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=settings.SCAN_INTERVAL_SECONDS)
                break
            except asyncio.TimeoutError:
                continue

        logger.info("Scanner runner loop stopped.")

    def start(self):
        """Start the background scanner engine."""
        if self.is_running:
            return
        self.is_running = True
        self.stats["is_running"] = True
        self._stop_event.clear()
        self._scan_task = asyncio.create_task(self._runner_loop())
        logger.info("Scanner engine started.")

    def stop(self):
        """Stop the background scanner engine."""
        if not self.is_running:
            return
        self.is_running = False
        self.stats["is_running"] = False
        self._stop_event.set()
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        logger.info("Scanner engine stopped.")

scanner = ScannerEngine()
