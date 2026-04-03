"""JWT authentication: hashing, token creation, and FastAPI dependency."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status

from core.config import get_settings
from core.database import get_db_client
from core.logger import logger

# ---------------------------------------------------------------------------
# Password hashing — uses PBKDF2-SHA256 (stdlib, no extra deps)
# ---------------------------------------------------------------------------
_HASH_ITERATIONS = 260_000


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Return 'salt_hex$hash_hex' string."""
    import os

    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _HASH_ITERATIONS)
    return f"{salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Compare password against 'salt_hex$hash_hex'."""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _HASH_ITERATIONS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT — minimal implementation using HMAC-SHA256 (no PyJWT dependency)
# ---------------------------------------------------------------------------
_ACCESS_TOKEN_EXPIRE = 24 * 3600  # 24 hours
_REFRESH_TOKEN_EXPIRE = 30 * 24 * 3600  # 30 days


def _b64_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return urlsafe_b64decode(s + "=" * pad)


def _jwt_encode(payload: dict[str, Any], secret: str) -> str:
    header = _b64_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64_encode(json.dumps(payload).encode())
    sig_input = f"{header}.{body}".encode()
    sig = hmac.new(secret.encode(), sig_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64_encode(sig)}"


def _jwt_decode(token: str, secret: str) -> dict[str, Any] | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        sig_input = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(secret.encode(), sig_input, hashlib.sha256).digest()
        actual = _b64_decode(parts[2])
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64_decode(parts[1]))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _get_secret() -> str:
    """Use SUPABASE_KEY as JWT secret (always available); fallback to a default."""
    s = get_settings()
    return s.supabase_key or s.openrouter_api_key or "ultra-job-agent-dev-secret"


def create_tokens(user_id: str, email: str, role: str = "user") -> dict[str, str]:
    """Return access_token + refresh_token."""
    secret = _get_secret()
    now = int(time.time())
    access = _jwt_encode(
        {"sub": user_id, "email": email, "role": role, "iat": now, "exp": now + _ACCESS_TOKEN_EXPIRE},
        secret,
    )
    refresh = _jwt_encode(
        {"sub": user_id, "type": "refresh", "iat": now, "exp": now + _REFRESH_TOKEN_EXPIRE},
        secret,
    )
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# User CRUD helpers
# ---------------------------------------------------------------------------

async def register_user(email: str, password: str, full_name: str = "") -> dict[str, Any]:
    """Create a new user; raise HTTPException on duplicate."""
    db = get_db_client()
    existing = await db.select_one("users", {"email": email.lower().strip()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    hashed = _hash_password(password)
    user = await db.insert(
        "users",
        {
            "email": email.lower().strip(),
            "password_hash": hashed,
            "full_name": full_name,
            "role": "user",
        },
    )
    return user


async def authenticate_user(email: str, password: str) -> dict[str, Any]:
    """Validate credentials; return user dict or raise 401."""
    db = get_db_client()
    user = await db.select_one("users", {"email": email.lower().strip()})
    if not user or not _verify_password(password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disabled")
    # Update last login
    await db.update("users", user["id"], {"last_login_at": datetime.now(timezone.utc).isoformat()})
    return user


# ---------------------------------------------------------------------------
# FastAPI dependency — extract current user from Bearer token
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> dict[str, Any]:
    """Dependency: decode JWT from Authorization header, return user payload."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth[7:]
    payload = _jwt_decode(token, _get_secret())
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


async def get_optional_user(request: Request) -> Optional[dict[str, Any]]:
    """Dependency: return user payload or None (no error if missing)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    return _jwt_decode(token, _get_secret())


def require_admin(user: dict = Depends(get_current_user)):
    """Dependency: raise 403 if user is not admin."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
