import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    desc
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings

logger = logging.getLogger("scanner.database")
Base = declarative_base()

class Instrument(Base):
    __tablename__ = "instruments"

    instrument_key = Column(String(64), primary_key=True)
    symbol = Column(String(32), index=True, nullable=False)
    name = Column(String(256), nullable=True)
    segment = Column(String(32), nullable=False)
    instrument_type = Column(String(32), nullable=False)
    lot_size = Column(Integer, default=1)
    tick_size = Column(Float, default=0.05)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_key = Column(String(128), unique=True, index=True, nullable=False)
    symbol = Column(String(32), index=True, nullable=False)
    instrument_key = Column(String(64), index=True, nullable=False)
    direction = Column(String(8), index=True, nullable=False)  # BUY or SELL
    timeframe = Column(String(8), index=True, nullable=False)  # 5M or 10M
    crossover_time = Column(DateTime, index=True, nullable=False)
    crossover_time_str = Column(String(64), nullable=False)
    crossover_price = Column(Float, nullable=False)
    ema6 = Column(Float, nullable=False)
    ema30 = Column(Float, nullable=False)
    prev_ema6 = Column(Float, nullable=False)
    prev_ema30 = Column(Float, nullable=False)
    status = Column(String(32), default="PENDING", index=True)  # PENDING, APPROVED, REJECTED, ORDER_PLACED
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_signals_direction_crossover", "direction", desc("crossover_time")),
    )

class OrderLog(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    order_id = Column(String(64), nullable=True)  # Upstox returned order_id
    symbol = Column(String(32), nullable=False)
    instrument_key = Column(String(64), nullable=False)
    direction = Column(String(8), nullable=False)
    quantity = Column(Integer, nullable=False)
    order_type = Column(String(16), nullable=False)  # MARKET / LIMIT
    product = Column(String(8), nullable=False)       # I (Intraday) / D (Delivery)
    price = Column(Float, default=0.0)
    status = Column(String(32), nullable=False)      # SUCCESS / FAILED
    response_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

def _get_sqlite_engine():
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = data_dir / "nse_scanner.db"
    return create_engine(
        f"sqlite:///{sqlite_path}",
        connect_args={"check_same_thread": False},
        echo=False
    )

def _build_engine():
    db_url = settings.normalized_database_url
    if db_url.startswith("sqlite"):
        return _get_sqlite_engine()

    try:
        pg_engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            connect_args={"connect_timeout": 3},
            echo=False
        )
        with pg_engine.connect() as conn:
            pass
        logger.info("Connected successfully to PostgreSQL database.")
        return pg_engine
    except Exception as e:
        logger.warning("Could not connect to PostgreSQL (%s). Falling back to local SQLite database.", e)
        return _get_sqlite_engine()

engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create tables if they do not exist and seed default settings."""
    global engine, SessionLocal
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.warning("Database init error with primary engine (%s). Falling back to SQLite.", e)
        engine = _get_sqlite_engine()
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        # Seed default timeframe if not present
        if not db.query(SystemSetting).filter_by(key="timeframe").first():
            db.add(SystemSetting(key="timeframe", value=settings.DEFAULT_TIMEFRAME))
        # Seed default universe if not present
        if not db.query(SystemSetting).filter_by(key="universe").first():
            db.add(SystemSetting(key="universe", value=settings.SCAN_UNIVERSE))
        db.commit()

def get_db():
    """Dependency for FastAPI route handlers."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
