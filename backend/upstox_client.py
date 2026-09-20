import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import httpx
from backend.config import settings

import pandas as pd

logger = logging.getLogger("scanner.upstox")

class UpstoxAuthExpiredException(Exception):
    """Raised when Upstox returns HTTP 401 Unauthorized."""
    pass

class UpstoxRateLimitException(Exception):
    """Raised when Upstox rate limit is exceeded."""
    pass

class UpstoxAPIClient:
    """
    High-performance client for the official Upstox API v2.
    Features:
    - Asynchronous requests with connection pooling
    - Concurrency control via Semaphore
    - Automatic exponential backoff retry for HTTP 429 rate limits
    - Specific exception handling for 401 auth expiration
    - Graceful stock-level error handling
    - Resampling of 1-minute intraday bars into 10-minute completed candles
    """

    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        self.base_url = "https://api.upstox.com/v2"

    async def fetch_10min_candles(
        self,
        instrument_key: str,
        access_token: Optional[str] = None,
        lookback_days: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Fetches 1-minute historical candles from Upstox and resamples them into
        10-minute completed candles, strictly excluding any currently forming incomplete candle.
        """
        raw_1min = await self.fetch_raw_candles(
            instrument_key=instrument_key,
            interval="1minute",
            access_token=access_token,
            lookback_days=lookback_days
        )
        if not raw_1min or len(raw_1min) < 30:
            return []

        # Convert to DataFrame
        df = pd.DataFrame(raw_1min)
        df["dt"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("dt").reset_index(drop=True)

        # Resample into 10-minute candles grouped per trading day (starting 09:15)
        daily_groups = []
        for date, group in df.groupby(df["dt"].dt.date):
            g = group.set_index("dt")
            g_10m = g.resample("10min", origin="start", closed="left", label="left").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna().reset_index()
            daily_groups.append(g_10m)

        if not daily_groups:
            return []

        df_10m = pd.concat(daily_groups, ignore_index=True)

        # Exclude currently forming incomplete 10-minute candle
        now = datetime.now(timezone.utc)
        if not df_10m.empty:
            last_candle_time = pd.to_datetime(df_10m["dt"].iloc[-1])
            if last_candle_time.tzinfo is None:
                last_candle_time = last_candle_time.tz_localize(timezone.utc)
            # If the bar started less than 10 minutes ago, it is incomplete
            if last_candle_time + timedelta(minutes=10) > now:
                df_10m = df_10m.iloc[:-1].reset_index(drop=True)

        # Format output records
        result_candles = []
        for _, row in df_10m.iterrows():
            result_candles.append({
                "timestamp": row["dt"].strftime("%Y-%m-%d %H:%M"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"])
            })

        return result_candles

    async def fetch_raw_candles(
        self,
        instrument_key: str,
        interval: str = "1minute",
        access_token: Optional[str] = None,
        lookback_days: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Fetches historical candles from Upstox for specified interval ('1minute', '30minute', 'day').
        """
        today = datetime.now()
        from_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        # URL encode instrument_key
        safe_key = httpx.URL(f"{self.base_url}/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}")
        headers = {
            "Accept": "application/json",
            "Api-Version": "2.0"
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        max_retries = 3
        backoff = 1.0

        for attempt in range(1, max_retries + 1):
            async with self.semaphore:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.get(str(safe_key), headers=headers)

                        if resp.status_code == 200:
                            data = resp.json()
                            candles_raw = data.get("data", {}).get("candles", [])
                            # Format: [timestamp, open, high, low, close, volume, open_interest]
                            parsed_candles = []
                            for c in candles_raw:
                                if len(c) >= 5:
                                    parsed_candles.append({
                                        "timestamp": c[0],
                                        "open": float(c[1]),
                                        "high": float(c[2]),
                                        "low": float(c[3]),
                                        "close": float(c[4]),
                                        "volume": int(c[5]) if len(c) > 5 and c[5] is not None else 0
                                    })
                            return parsed_candles

                        elif resp.status_code == 401:
                            logger.error("Upstox authentication expired (HTTP 401) on %s", instrument_key)
                            raise UpstoxAuthExpiredException(
                                "Upstox authentication expired. Please reconnect your Upstox account."
                            )

                        elif resp.status_code == 429:
                            logger.warning(
                                "Upstox API rate limit reached on %s (attempt %d/%d). Retrying in %.1fs...",
                                instrument_key, attempt, max_retries, backoff
                            )
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue

                        elif resp.status_code in [400, 404]:
                            logger.warning("No data found or invalid instrument %s (HTTP %d)", instrument_key, resp.status_code)
                            return []

                        else:
                            logger.warning("Unexpected status %d from Upstox for %s: %s", resp.status_code, instrument_key, resp.text)
                            if attempt < max_retries:
                                await asyncio.sleep(backoff)
                                backoff *= 1.5
                                continue
                            return []

                except UpstoxAuthExpiredException:
                    raise
                except httpx.RequestError as e:
                    logger.warning("Network request error for %s (attempt %d/%d): %s", instrument_key, attempt, max_retries, e)
                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff *= 1.5
                    else:
                        return []
                except Exception as e:
                    logger.error("Unexpected error fetching candles for %s: %s", instrument_key, e)
                    return []

        return []

upstox_api = UpstoxAPIClient()
