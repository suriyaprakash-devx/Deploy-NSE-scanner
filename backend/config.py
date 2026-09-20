import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Upstox Direct Access Token or OAuth
    UPSTOX_ACCESS_TOKEN: Optional[str] = None
    UPSTOX_CLIENT_ID: Optional[str] = None
    UPSTOX_CLIENT_SECRET: Optional[str] = None
    UPSTOX_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"

    # Database
    DATABASE_URL: Optional[str] = None
    DELETE_RESULTS_AFTER_SCAN: bool = False

    # Security & Frontend
    SECRET_KEY: str = "upstox_semi_algo_secret_encryption_key_32bytes!"
    FRONTEND_URL: str = "http://localhost:5173"
    ENVIRONMENT: str = "development"

    # Scanner Settings
    TIMEFRAME: str = "10minute"
    INTRADAY_LOOKBACK_DAYS: int = 8  # Sufficient 1-minute candles to produce 200+ 10-minute candles
    MAX_CONCURRENT_REQUESTS: int = 10
    REQUESTS_PER_SECOND_LIMIT: int = 15

    # Storage paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"

    @property
    def normalized_database_url(self) -> str:
        if not self.DATABASE_URL:
            self.DATA_DIR.mkdir(parents=True, exist_ok=True)
            sqlite_path = self.DATA_DIR / "nse_scanner.db"
            return f"sqlite:///{sqlite_path}"
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url

settings = Settings()
