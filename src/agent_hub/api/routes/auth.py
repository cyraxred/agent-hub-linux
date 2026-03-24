"""Authentication routes — PAM login, token management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthStatusResponse(BaseModel):
    authenticated: bool
    username: str | None = None


class InvalidateResponse(BaseModel):
    tokens_invalidated: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_auth_service(request: Request):  # noqa: ANN202
    return request.app.state.provider.auth_service


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(request: Request) -> AuthStatusResponse:
    """Check current authentication state."""
    auth_service = _get_auth_service(request)
    token = request.cookies.get("agent_hub_token")
    if not token:
        return AuthStatusResponse(authenticated=False)

    ip = _client_ip(request)
    username = await auth_service.validate_token(token, ip)
    return AuthStatusResponse(authenticated=username is not None, username=username)


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> JSONResponse:
    """Authenticate via PAM and issue an auth token cookie."""
    auth_service = _get_auth_service(request)
    ip = _client_ip(request)

    if auth_service.check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    if not await auth_service.authenticate_pam(body.username, body.password):
        auth_service.record_failure(ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = await auth_service.create_token(body.username, ip)

    response = JSONResponse(content={"authenticated": True, "username": body.username})
    response.set_cookie(
        key="agent_hub_token",
        value=token,
        httponly=True,
        secure=request.app.state.provider.settings.require_tls,
        samesite="strict",
        path="/",
        max_age=365 * 24 * 60 * 60,  # 1 year
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    """Clear the auth cookie."""
    response = JSONResponse(content={"authenticated": False})
    response.delete_cookie("agent_hub_token", path="/")
    return response


@router.post("/invalidate-all", response_model=InvalidateResponse)
async def invalidate_all(request: Request) -> InvalidateResponse:
    """Invalidate all issued tokens. All clients will need to re-authenticate."""
    auth_service = _get_auth_service(request)
    count = await auth_service.invalidate_all()
    return InvalidateResponse(tokens_invalidated=count)
