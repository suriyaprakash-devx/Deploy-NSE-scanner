import os
import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from backend.config import settings
from backend.models import OAuthSession

logger = logging.getLogger("scanner.auth")

# Derive a valid 32-byte urlsafe base64 key for Fernet from settings.SECRET_KEY
def _get_fernet() -> Fernet:
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

def encrypt_token(plain_token: str) -> str:
    f = _get_fernet()
    return f.encrypt(plain_token.encode()).decode()

def decrypt_token(cipher_token: str) -> str:
    f = _get_fernet()
    return f.decrypt(cipher_token.encode()).decode()

async def validate_upstox_token(token: str) -> Dict[str, Any]:
    """Validates the Upstox access token by fetching the user profile."""
    url = "https://api.upstox.com/v2/user/profile"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Api-Version": "2.0"
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                profile = data.get("data", {})
                return {
                    "valid": True,
                    "user_id": profile.get("user_id", "Unknown"),
                    "user_name": profile.get("user_name", "Upstox User"),
                    "email": profile.get("email", ""),
                    "broker": profile.get("broker", "UPSTOX")
                }
            elif resp.status_code == 401:
                return {"valid": False, "error": "Upstox authentication expired or invalid. Please provide a fresh token."}
            else:
                return {"valid": False, "error": f"Upstox API returned status {resp.status_code}: {resp.text}"}
    except Exception as e:
        logger.error("Error validating Upstox token: %s", e)
        return {"valid": False, "error": f"Connection error: {str(e)}"}

async def save_access_token(db: Session, token: str) -> Dict[str, Any]:
    """Validates and securely saves the Upstox token into the database."""
    validation = await validate_upstox_token(token)
    if not validation["valid"]:
        return validation

    # Encrypt token
    encrypted = encrypt_token(token)
    session_key = "default_session"

    # Deactivate existing sessions
    db.query(OAuthSession).filter(OAuthSession.session_id == session_key).delete()

    session_record = OAuthSession(
        session_id=session_key,
        user_id=validation.get("user_id"),
        user_name=validation.get("user_name"),
        user_email=validation.get("email"),
        access_token_encrypted=encrypted,
        is_active=True
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)

    logger.info("Saved active Upstox session for user %s", validation.get("user_id"))
    return {
        "valid": True,
        "user_id": validation.get("user_id"),
        "user_name": validation.get("user_name"),
        "email": validation.get("email")
    }

def get_active_access_token(db: Session) -> Optional[str]:
    """
    Retrieves the active Upstox access token:
    1. Checks environment variable UPSTOX_ACCESS_TOKEN first
    2. Checks database oauth_sessions table
    """
    # 1. Environment variable
    if settings.UPSTOX_ACCESS_TOKEN and len(settings.UPSTOX_ACCESS_TOKEN.strip()) > 10:
        return settings.UPSTOX_ACCESS_TOKEN.strip()

    # 2. Database session
    session_record = (
        db.query(OAuthSession)
        .filter(OAuthSession.is_active == True)
        .order_by(OAuthSession.id.desc())
        .first()
    )
    if session_record and session_record.access_token_encrypted:
        try:
            return decrypt_token(session_record.access_token_encrypted)
        except Exception as e:
            logger.error("Failed to decrypt stored token: %s", e)
            return None
    return None

def clear_session(db: Session):
    """Logs out by deactivating stored sessions."""
    db.query(OAuthSession).update({"is_active": False})
    db.commit()

# Optional OAuth 2.0 helpers
def get_oauth_authorization_url() -> Optional[str]:
    if not settings.UPSTOX_CLIENT_ID:
        return None
    return (
        f"https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code"
        f"&client_id={settings.UPSTOX_CLIENT_ID}"
        f"&redirect_uri={settings.UPSTOX_REDIRECT_URI}"
    )

async def exchange_code_for_token(code: str, db: Session) -> Dict[str, Any]:
    url = "https://api.upstox.com/v2/login/authorization/token"
    headers = {
        "Accept": "application/json",
        "Api-Version": "2.0",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "code": code,
        "client_id": settings.UPSTOX_CLIENT_ID,
        "client_secret": settings.UPSTOX_CLIENT_SECRET,
        "redirect_uri": settings.UPSTOX_REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, data=payload)
        if resp.status_code == 200:
            token_data = resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return {"valid": False, "error": "No access_token received from Upstox"}
            return await save_access_token(db, access_token)
        else:
            return {"valid": False, "error": f"Token exchange failed: {resp.text}"}
