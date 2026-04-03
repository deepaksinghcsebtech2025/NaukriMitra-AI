"""Supabase Auth JWT verification for FastAPI routes.

Supabase Auth issues HS256 JWTs signed with the project's JWT secret.
Get it from: Dashboard → Project Settings → API → JWT Settings → JWT Secret

Token claims:
  sub   → user UUID  (this is the user_id used in RLS)
  email → user email
  role  → 'authenticated' | 'anon'
  exp   → expiry timestamp
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status

from core.config import get_settings
from core.logger import logger


# ---------------------------------------------------------------------------
# Minimal HS256 JWT decoder (stdlib only, no PyJWT dependency)
# ---------------------------------------------------------------------------

def _b64url_decode(segment: str) -> bytes:
    """Decode a base64url segment (with padding fix)."""
    padding = 4 - len(segment) % 4
    if padding != 4:
        segment += "=" * padding
    return base64.urlsafe_b64decode(segment)


def _verify_supabase_jwt(token: str, jwt_secret: str) -> dict[str, Any]:
    """Verify a Supabase Auth JWT and return its claims.

    Raises ValueError with a human-readable message on any failure.
    The jwt_secret is the raw secret string from Supabase dashboard
    (NOT base64-encoded — Supabase shows it as plain text).
    """
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise ValueError("Malformed JWT — expected 3 dot-separated parts")

    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}".encode()
    secret_bytes = jwt_secret.encode("utf-8")
    expected_sig = hmac.new(secret_bytes, signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid JWT signature")

    # Decode payload
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise ValueError("Cannot decode JWT payload")

    # Check expiry
    exp = payload.get("exp")
    if exp and int(time.time()) > int(exp):
        raise ValueError("JWT has expired")

    # Must be an authenticated user (not anonymous)
    role = payload.get("role", "")
    if role not in ("authenticated", "service_role"):
        raise ValueError(f"Unexpected JWT role: {role!r}")

    return payload


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

class UserContext:
    """Minimal user info extracted from Supabase JWT."""

    __slots__ = ("user_id", "email", "role", "raw_token")

    def __init__(self, user_id: str, email: str, role: str, raw_token: str) -> None:
        self.user_id = user_id
        self.email = email
        self.role = role
        self.raw_token = raw_token

    def __repr__(self) -> str:
        return f"UserContext(user_id={self.user_id!r}, email={self.email!r})"


def _extract_bearer(request: Request) -> Optional[str]:
    """Pull Bearer token from Authorization header or ?token= query param."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    # fallback: allow token in query string (useful for WebSocket)
    return request.query_params.get("token")


async def get_current_user(request: Request) -> UserContext:
    """FastAPI dependency — require authenticated Supabase user.

    Raises 401 if token is missing or invalid.
    """
    settings = get_settings()
    jwt_secret = settings.supabase_jwt_secret

    if not jwt_secret:
        # In development without auth configured, create a dev user stub
        if settings.environment != "production":
            logger.warning("SUPABASE_JWT_SECRET not set — using dev stub user")
            return UserContext(
                user_id="00000000-0000-0000-0000-000000000001",
                email="dev@localhost",
                role="authenticated",
                raw_token="",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured — set SUPABASE_JWT_SECRET in .env",
        )

    token = _extract_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = _verify_supabase_jwt(token, jwt_secret)
    except ValueError as exc:
        logger.warning("JWT verification failed: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT missing 'sub' claim",
        )

    return UserContext(
        user_id=user_id,
        email=claims.get("email", ""),
        role=claims.get("role", "authenticated"),
        raw_token=token,
    )


async def get_optional_user(request: Request) -> Optional[UserContext]:
    """FastAPI dependency — return user if token present, None otherwise."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    """FastAPI dependency — require service_role / admin."""
    if user.role != "service_role":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
