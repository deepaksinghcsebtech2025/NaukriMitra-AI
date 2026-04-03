"""Authentication endpoints: register, login, refresh, profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from core.auth import (
    authenticate_user,
    create_tokens,
    get_current_user,
    register_user,
    _jwt_decode,
    _get_secret,
)
from core.database import get_db_client

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/auth/register")
async def register(body: RegisterRequest) -> dict:
    """Create a new user account and return tokens."""
    user = await register_user(body.email, body.password, body.full_name)
    tokens = create_tokens(user["id"], user["email"], user.get("role", "user"))
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user.get("full_name", ""),
            "role": user.get("role", "user"),
        },
        **tokens,
    }


@router.post("/auth/login")
async def login(body: LoginRequest) -> dict:
    """Authenticate and return tokens."""
    user = await authenticate_user(body.email, body.password)
    tokens = create_tokens(user["id"], user["email"], user.get("role", "user"))
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user.get("full_name", ""),
            "role": user.get("role", "user"),
        },
        **tokens,
    }


@router.post("/auth/refresh")
async def refresh(body: RefreshRequest) -> dict:
    """Exchange a valid refresh token for new access + refresh tokens."""
    payload = _jwt_decode(body.refresh_token, _get_secret())
    if not payload or payload.get("type") != "refresh":
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    db = get_db_client()
    user = await db.select_one("users", {"id": payload["sub"]})
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="User not found")
    return create_tokens(user["id"], user["email"], user.get("role", "user"))


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    """Return current user profile from token."""
    return {
        "id": user.get("sub"),
        "email": user.get("email"),
        "role": user.get("role", "user"),
    }
