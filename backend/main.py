import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.config import settings
from backend.database import init_db, get_db
from backend.models import ScanRun, ScanResult
from backend.auth import (
    get_active_access_token,
    save_access_token,
    validate_upstox_token,
    clear_session,
    get_oauth_authorization_url,
    exchange_code_for_token,
)
from backend.scanner import scanner_state, execute_scanner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("scanner.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables
    logger.info("Initializing database...")
    init_db()
    # Check if UPSTOX_ACCESS_TOKEN is configured in environment
    if settings.UPSTOX_ACCESS_TOKEN:
        logger.info("Environment UPSTOX_ACCESS_TOKEN detected.")
    yield
    logger.info("Application shutting down.")

app = FastAPI(
    title="Upstox Semi-Algo NSE Stock Scanner",
    description="Automated analysis tool screening NIFTY 100 & 200 for SMA 6/30 crossovers.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
allowed_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
if settings.FRONTEND_URL and settings.FRONTEND_URL not in allowed_origins:
    allowed_origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENVIRONMENT == "development" else allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Request/Response Models -----------------

class TokenSubmissionRequest(BaseModel):
    access_token: str

class AuthStatusResponse(BaseModel):
    authenticated: bool
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    email: Optional[str] = None
    token_source: Optional[str] = None  # "env", "database", or None
    error: Optional[str] = None

class ScanRunResponse(BaseModel):
    message: str
    status: str

# ----------------- Health Endpoint -----------------

@app.get("/api/health")
def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}

# ----------------- Authentication Endpoints -----------------

@app.get("/api/auth/status", response_model=AuthStatusResponse)
async def check_auth_status(db: Session = Depends(get_db)):
    """Check if the backend has a valid, active Upstox access token."""
    # Check env first
    if settings.UPSTOX_ACCESS_TOKEN and len(settings.UPSTOX_ACCESS_TOKEN.strip()) > 10:
        token = settings.UPSTOX_ACCESS_TOKEN.strip()
        val = await validate_upstox_token(token)
        if val["valid"]:
            return AuthStatusResponse(
                authenticated=True,
                user_id=val.get("user_id"),
                user_name=val.get("user_name"),
                email=val.get("email"),
                token_source="env"
            )

    token = get_active_access_token(db)
    if not token:
        return AuthStatusResponse(authenticated=False, error="No active Upstox token found.")

    val = await validate_upstox_token(token)
    if not val["valid"]:
        return AuthStatusResponse(authenticated=False, error=val.get("error", "Token expired or invalid."))

    return AuthStatusResponse(
        authenticated=True,
        user_id=val.get("user_id"),
        user_name=val.get("user_name"),
        email=val.get("email"),
        token_source="database"
    )

@app.post("/api/auth/token")
async def submit_access_token(payload: TokenSubmissionRequest, db: Session = Depends(get_db)):
    """Directly submit an Upstox access token from the dashboard."""
    token = payload.access_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Access token cannot be empty.")

    result = await save_access_token(db, token)
    if not result["valid"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.get("error", "Failed to validate Upstox token.")
        )

    return {
        "success": True,
        "message": "Upstox token validated and stored successfully.",
        "user_id": result.get("user_id"),
        "user_name": result.get("user_name")
    }

@app.get("/api/auth/login")
def login_with_upstox():
    """Starts the official Upstox OAuth 2.0 flow if client_id is set."""
    auth_url = get_oauth_authorization_url()
    if not auth_url:
        raise HTTPException(
            status_code=400,
            detail="Upstox OAuth credentials not configured. Please use the Direct Access Token input."
        )
    return RedirectResponse(url=auth_url)

@app.get("/api/auth/callback")
async def oauth_callback(code: str = Query(...), db: Session = Depends(get_db)):
    """Receives authorization code from Upstox and exchanges for token."""
    res = await exchange_code_for_token(code, db)
    if not res["valid"]:
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to exchange authorization code."))
    # Redirect back to frontend dashboard
    redirect_url = f"{settings.FRONTEND_URL}/?auth=success"
    return RedirectResponse(url=redirect_url)

@app.post("/api/auth/logout")
def logout(db: Session = Depends(get_db)):
    """Clears stored Upstox session token."""
    clear_session(db)
    return {"success": True, "message": "Logged out successfully."}

# ----------------- Scanner Endpoints -----------------

@app.post("/api/scanner/run", response_model=ScanRunResponse)
async def run_scanner(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Starts the semi-algo scanner in the background."""
    if scanner_state.is_running:
        raise HTTPException(status_code=409, detail="A scan is already running.")

    # Validate active token
    token = get_active_access_token(db)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Upstox authentication required. Please provide a valid access token."
        )

    background_tasks.add_task(execute_scanner, token)
    return ScanRunResponse(message="Scanner started successfully.", status="RUNNING")

@app.get("/api/scanner/status")
def get_scanner_status():
    """Returns real-time progress and logs of the scanner."""
    return scanner_state.to_dict()

@app.post("/api/scanner/stop")
def stop_scanner():
    """Requests scanner to stop gracefully."""
    if not scanner_state.is_running:
        return {"message": "Scanner is not currently running."}
    scanner_state.should_stop = True
    scanner_state.stage = "Stopping..."
    return {"message": "Stop signal sent to scanner."}

@app.get("/api/scanner/results")
def get_scanner_results(db: Session = Depends(get_db)):
    """
    Returns latest scan results formatted with exact required columns:
    Rank, Symbol, Company, Signal Type, Crossover Date, Close, SMA 6, SMA 30
    """
    # If in-memory state has latest results, return them
    if scanner_state.latest_results:
        return {
            "results": scanner_state.latest_results,
            "count": len(scanner_state.latest_results),
            "completed_at": scanner_state.completed_at.isoformat() if scanner_state.completed_at else None
        }

    # Otherwise fetch latest completed scan run from database
    latest_run = (
        db.query(ScanRun)
        .filter(ScanRun.status == "COMPLETED")
        .order_by(ScanRun.id.desc())
        .first()
    )

    if not latest_run:
        return {"results": [], "count": 0, "completed_at": None}

    results = (
        db.query(ScanResult)
        .filter(ScanResult.scan_id == latest_run.id)
        .order_by(ScanResult.rank.asc())
        .all()
    )

    formatted = [
        {
            "Rank": r.rank,
            "Symbol": r.symbol,
            "Company": r.company,
            "Signal Type": r.signal_type,
            "Crossover Date": r.crossover_date,
            "Close": f"{r.close:.2f}",
            "SMA 6": f"{r.sma6:.2f}",
            "SMA 30": f"{r.sma30:.2f}"
        }
        for r in results
    ]

    return {
        "results": formatted,
        "count": len(formatted),
        "completed_at": latest_run.completed_at.isoformat() if latest_run.completed_at else None
    }
