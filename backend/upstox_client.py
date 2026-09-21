import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd
from backend.config import settings

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
    - Concurrently fetches both historical (previous trading days) and live intraday (today) 1-minute bars
    - Resampling of 1-minute bars into 10-minute candles including the live current candle
    """

    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        self.base_url = "https://api.upstox.com/v2"

    async def _fetch_candle_url(
        self,
        url: str,
        headers: Dict[str, str],
        instrument_key: str,
        max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        backoff = 1.0
        for attempt in range(1, max_retries + 1):
            async with self.semaphore:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.get(url, headers=headers)

                        if resp.status_code == 200:
                            data = resp.json()
                            candles_raw = data.get("data", {}).get("candles", [])
                            parsed = []
                            for c in candles_raw:
                                if len(c) >= 5:
                                    parsed.append({
                                        "timestamp": c[0],
                                        "open": float(c[1]),
                                        "high": float(c[2]),
                                        "low": float(c[3]),
                                        "close": float(c[4]),
                                        "volume": int(c[5]) if len(c) > 5 and c[5] is not None else 0
                                    })
                            return parsed

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
                            # Intraday candles might be empty before market open (09:15) or invalid key
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

    async def fetch_10min_candles(
        self,
        instrument_key: str,
        access_token: Optional[str] = None,
        lookback_days: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Fetches both historical 1-minute candles (previous trading days) and live intraday candles (today),
        merges them chronologically, deduplicates, and resamples them into 10-minute candles
        including the live current candle.
        """
        today = datetime.now()
        from_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        headers = {
            "Accept": "application/json",
            "Api-Version": "2.0"
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        hist_url = f"{self.base_url}/historical-candle/{instrument_key}/1minute/{to_date}/{from_date}"
        intra_url = f"{self.base_url}/historical-candle/intraday/{instrument_key}/1minute"

        # Concurrently fetch historical and today's live intraday candles
        hist_task = self._fetch_candle_url(hist_url, headers, instrument_key)
        intra_task = self._fetch_candle_url(intra_url, headers, instrument_key)

        hist_candles, intra_candles = await asyncio.gather(hist_task, intra_task, return_exceptions=True)

        if isinstance(hist_candles, UpstoxAuthExpiredException) or isinstance(intra_candles, UpstoxAuthExpiredException):
            raise UpstoxAuthExpiredException("Upstox authentication expired. Please reconnect your Upstox account.")

        candles_raw = []
        if isinstance(intra_candles, list):
            candles_raw.extend(intra_candles)
        if isinstance(hist_candles, list):
            candles_raw.extend(hist_candles)

        if not candles_raw or len(candles_raw) < 30:
            return []

        # Convert to DataFrame
        df = pd.DataFrame(candles_raw)
        df["dt"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("dt").drop_duplicates(subset=["dt"]).reset_index(drop=True)

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

        # Retain the live current candle so the scanner evaluates real-time market data
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
        Fetches raw candles for historical lookback.
        """
        today = datetime.now()
        from_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        headers = {
            "Accept": "application/json",
            "Api-Version": "2.0"
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        url = f"{self.base_url}/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
        return await self._fetch_candle_url(url, headers, instrument_key)

upstox_api = UpstoxAPIClient()
