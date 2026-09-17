import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any
import httpx
from app.config import settings
from app.market import now_ist

logger = logging.getLogger("scanner.upstox")

class AsyncTokenBucketRateLimiter:
    """Token-bucket rate limiter to enforce Upstox API request limits."""
    def __init__(self, rate: int = 20, per_seconds: float = 1.0):
        self.rate = rate
        self.per_seconds = per_seconds
        self.tokens = rate
        self.last_check = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_check
            self.last_check = now
            self.tokens += elapsed * (self.rate / self.per_seconds)
            if self.tokens > self.rate:
                self.tokens = self.rate

            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) * (self.per_seconds / self.rate)
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0

class UpstoxClient:
    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or settings.UPSTOX_ACCESS_TOKEN
        self.rate_limiter = AsyncTokenBucketRateLimiter(
            rate=settings.MAX_REQUESTS_PER_SECOND,
            per_seconds=1.0
        )
        self.semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        self._client: httpx.AsyncClient | None = None

    def set_token(self, token: str):
        self.access_token = token.strip()

    def get_token(self) -> str:
        return self.access_token or ""

    def is_configured(self) -> bool:
        return bool(self.access_token and len(self.access_token) >= 10)

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.UPSTOX_BASE_URL,
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
                headers={"Accept": "application/json"}
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    async def validate_token(self) -> dict:
        """Validate the token by fetching user profile."""
        if not self.is_configured():
            raise ValueError("Upstox access token is not configured.")

        client = await self.get_client()
        await self.rate_limiter.acquire()
        response = await client.get("/v2/user/profile", headers=self._auth_headers())
        if response.status_code != 200:
            raise PermissionError(f"Upstox authentication failed: {response.text}")
        data = response.json()
        return data.get("data", {})

    async def fetch_candles(
        self,
        instrument_key: str,
        interval_minutes: int = 5,
        days_back: int = 5
    ) -> list:
        """
        Fetch historical candle data for a given instrument.
        Attempts Upstox V3 endpoint first, with fallback to historical V3/V2.
        Returns raw list of candles [ [timestamp, open, high, low, close, volume, oi], ... ].
        """
        if not self.is_configured():
            raise ValueError("Upstox access token is missing.")

        client = await self.get_client()
        today = now_ist().date()
        from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        # Encode instrument key if necessary (e.g., NSE_EQ|INE... -> NSE_EQ%7CINE...)
        key_encoded = instrument_key.replace("|", "%7C")

        # We try endpoints in order of preference:
        # 1. V3 historical endpoint for specific minutes
        # 2. V3 intraday endpoint
        # 3. V2 historical endpoint
        urls_to_try = [
            f"/v3/historical-candle/{key_encoded}/minutes/{interval_minutes}/{to_date}/{from_date}",
            f"/v3/historical-candle/intraday/{key_encoded}/minutes/{interval_minutes}",
            f"/v2/historical-candle/{key_encoded}/1minute/{to_date}/{from_date}",
        ]

        max_retries = 3
        last_exception = None

        for attempt in range(max_retries):
            try:
                async with self.semaphore:
                    await self.rate_limiter.acquire()
                    for url in urls_to_try:
                        try:
                            resp = await client.get(url, headers=self._auth_headers())
                            if resp.status_code == 200:
                                data = resp.json()
                                candles = data.get("data", {}).get("candles", [])
                                if candles:
                                    # If 1-minute fallback was fetched, resample
                                    if "1minute" in url and interval_minutes > 1:
                                        return self._resample_1min_candles(candles, interval_minutes)
                                    return candles
                            elif resp.status_code == 429:
                                # Rate limited
                                backoff = (2 ** attempt) + random.uniform(0.2, 0.8)
                                logger.warning("Rate limited (429) on %s. Backing off %.2fs", instrument_key, backoff)
                                await asyncio.sleep(backoff)
                                break  # Retry next outer attempt
                            elif resp.status_code in (400, 404):
                                # Endpoint or instrument not available on this path, try next url
                                continue
                            elif resp.status_code == 401:
                                raise PermissionError("Upstox access token has expired or is invalid.")
                        except (httpx.RequestError, httpx.TimeoutException) as e:
                            logger.debug("Request error on %s (%s): %s", instrument_key, url, e)
                            continue
            except PermissionError:
                raise
            except Exception as e:
                last_exception = e
                backoff = (2 ** attempt) + random.uniform(0.1, 0.5)
                await asyncio.sleep(backoff)

        if last_exception:
            raise last_exception
        return []

    def _resample_1min_candles(self, raw_1m_candles: list, target_minutes: int) -> list:
        """Resample 1-minute candles into target_minutes (5M or 10M) candles."""
        if not raw_1m_candles:
            return []
        import pandas as pd
        df = pd.DataFrame(raw_1m_candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
        df["dt"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("dt")
        df.set_index("dt", inplace=True)

        resampled = df.resample(
            f"{target_minutes}min",
            origin="start",
            offset="15min" if target_minutes == 10 else "0min"
        ).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "oi": "last"
        }).dropna()

        resampled_candles = []
        for dt_idx, row in resampled.iterrows():
            resampled_candles.append([
                dt_idx.isoformat(),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                int(row["volume"]),
                int(row["oi"])
            ])
        return resampled_candles

    async def place_order(
        self,
        symbol: str,
        instrument_key: str,
        transaction_type: str,  # BUY or SELL
        quantity: int,
        order_type: str = "MARKET",  # MARKET or LIMIT
        price: float = 0.0,
        product: str = "I",          # I for Intraday (MIS), D for Delivery (CNC)
        tag: str = "EMA_SEMI_ALGO"
    ) -> dict:
        """
        Execute manual live order via Upstox API v2 /v2/order/place.
        Requires explicit user approval from the dashboard!
        """
        if not self.is_configured():
            raise ValueError("Upstox access token is not configured.")

        if transaction_type.upper() not in ("BUY", "SELL"):
            raise ValueError(f"Invalid transaction type: {transaction_type}")

        if quantity <= 0:
            raise ValueError(f"Invalid quantity: {quantity}")

        payload = {
            "quantity": int(quantity),
            "product": product.upper(),
            "validity": "DAY",
            "price": float(price) if order_type.upper() == "LIMIT" else 0.0,
            "tag": tag,
            "instrument_token": instrument_key,
            "order_type": order_type.upper(),
            "transaction_type": transaction_type.upper(),
            "disclosed_quantity": 0,
            "trigger_price": 0.0,
            "is_amo": False
        }

        logger.info("Executing user-approved order for %s: %s", symbol, payload)
        client = await self.get_client()
        await self.rate_limiter.acquire()

        response = await client.post(
            "/v2/order/place",
            headers=self._auth_headers(),
            json=payload
        )

        resp_json = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}

        if response.status_code not in (200, 201):
            error_msg = resp_json.get("message") or response.text
            logger.error("Order placement failed for %s: %s", symbol, error_msg)
            raise RuntimeError(f"Upstox order rejected: {error_msg}")

        order_id = resp_json.get("data", {}).get("order_id")
        logger.info("Order placed successfully for %s! Order ID: %s", symbol, order_id)
        return {
            "status": "SUCCESS",
            "order_id": order_id,
            "data": resp_json.get("data", {})
        }

# Global singleton client
upstox = UpstoxClient()
