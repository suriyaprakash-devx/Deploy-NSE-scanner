import logging
from typing import Generator
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from backend.config import settings
from backend.models import Base, ScanRun, ScanResult, OAuthSession

logger = logging.getLogger("scanner.database")

def get_engine():
    db_url = settings.normalized_database_url
    if db_url.startswith("sqlite"):
        return create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=False
        )
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        connect_args={"connect_timeout": 5},
        echo=False
    )

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all tables if they do not exist."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize database: %s", e)
        raise

def get_db() -> Generator[Session, None, None]:
    """Dependency injection for FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def cleanup_old_scans(db: Session, keep_latest: int = 1):
    """
    Cleanup policy: Keeps the latest scan(s) and purges older scan runs
    and associated temporary results to prevent database accumulation.
    """
    try:
        # Get IDs of latest scans to keep
        recent_scan_ids = [
            run.id for run in db.query(ScanRun.id)
            .filter(ScanRun.status.in_(["COMPLETED", "RUNNING"]))
            .order_by(desc(ScanRun.id))
            .limit(keep_latest)
            .all()
        ]

        if recent_scan_ids:
            # Delete runs that are not in the recent list
            deleted = db.query(ScanRun).filter(~ScanRun.id.in_(recent_scan_ids)).delete(synchronize_session=False)
            db.commit()
            if deleted > 0:
                logger.info("Cleaned up %d older scan runs from database.", deleted)
    except Exception as e:
        db.rollback()
        logger.warning("Error during scan cleanup: %s", e)
