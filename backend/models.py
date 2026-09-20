from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Index, Text, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class OAuthSession(Base):
    __tablename__ = "oauth_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(64), nullable=True)
    user_name = Column(String(128), nullable=True)
    user_email = Column(String(128), nullable=True)
    access_token_encrypted = Column(Text, nullable=False)
    token_type = Column(String(32), default="Bearer")
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    stocks_scanned = Column(Integer, default=0)
    signals_found = Column(Integer, default=0)
    status = Column(String(32), default="RUNNING", nullable=False)  # RUNNING, COMPLETED, FAILED, STOPPED
    error_message = Column(Text, nullable=True)

    results = relationship("ScanResult", back_populates="scan_run", cascade="all, delete-orphan")

class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, nullable=False)
    symbol = Column(String(32), index=True, nullable=False)
    company = Column(String(256), nullable=False)
    signal_type = Column(String(16), nullable=False)  # BULLISH or BEARISH
    crossover_date = Column(String(32), nullable=False)
    close = Column(Float, nullable=False)
    sma6 = Column(Float, nullable=False)
    sma30 = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    scan_run = relationship("ScanRun", back_populates="results")

    __table_args__ = (
        Index("ix_scan_results_scan_rank", "scan_id", "rank"),
    )
