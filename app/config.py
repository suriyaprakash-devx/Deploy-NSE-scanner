import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "NSE Semi-Algo Scanner"
    ENV: str = os.getenv("ENV", "development")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Upstox API
    UPSTOX_ACCESS_TOKEN: str = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    UPSTOX_BASE_URL: str = "https://api.upstox.com"
    UPSTOX_INSTRUMENT_URL: str = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/data/nse_scanner.db")

    # Strategy settings
    DEFAULT_TIMEFRAME: str = os.getenv("DEFAULT_TIMEFRAME", "5M")  # "5M" or "10M"
    SCAN_UNIVERSE: str = os.getenv("SCAN_UNIVERSE", "ALL_NSE")     # "ALL_NSE", "NIFTY500", "NIFTY100", "NIFTY50"
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))

    # Rate limiting & worker pool
    MAX_REQUESTS_PER_SECOND: int = int(os.getenv("MAX_REQUESTS_PER_SECOND", "20"))
    MAX_CONCURRENT_REQUESTS: int = int(os.getenv("MAX_CONCURRENT_REQUESTS", "12"))
    REQUEST_TIMEOUT_SECONDS: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "8.0"))

    # Optional Telegram Alerts
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # CORS
    CORS_ORIGINS: list[str] = ["*"]

    @property
    def normalized_database_url(self) -> str:
        """Render supplies postgres://, which SQLAlchemy 2.0 requires as postgresql://"""
        url = self.DATABASE_URL.strip()
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql://", 1)
        return url

settings = Settings()
