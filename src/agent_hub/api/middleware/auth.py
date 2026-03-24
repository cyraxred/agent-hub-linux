"""ASGI middleware enforcing cookie-based authentication.

Works for both HTTP and WebSocket connections.  Static files are served
without authentication so the SPA can load its login page.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Paths that never require authentication.
_AUTH_BYPASS_PREFIXES = ("/api/auth/",)
_AUTH_BYPASS_EXACT = ("/api/health",)

# Only these prefixes are protected — everything else is static.
_PROTECTED_PREFIXES = ("/api/", "/ws/", "/ws")


def _requires_auth(path: str) -> bool:
    """Return True if *path* needs a valid auth token."""
    for exact in _AUTH_BYPASS_EXACT:
        if path == exact:
            return False
    for prefix in _AUTH_BYPASS_PREFIXES:
        if path.startswith(prefix):
            return False
    for prefix in _PROTECTED_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _extract_cookie(scope: Scope, name: str) -> str | None:
    """Parse a named cookie from the raw ASGI scope headers."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"cookie":
            for part in header_value.decode("latin-1").split(";"):
                part = part.strip()
                if part.startswith(f"{name}="):
                    return part[len(name) + 1 :]
    return None


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"


class AuthMiddleware:
    """Raw ASGI middleware — intercepts HTTP *and* WebSocket requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not _requires_auth(path):
            await self.app(scope, receive, send)
            return

        # Resolve auth service from app state
        app: Any = scope.get("app")
        if app is None:
            await self.app(scope, receive, send)
            return

        auth_service = app.state.provider.auth_service

        token = _extract_cookie(scope, "agent_hub_token")
        ip = _client_ip(scope)

        username: str | None = None
        if token:
            username = await auth_service.validate_token(token, ip)

        if username is None:
            if scope["type"] == "websocket":
                # Reject WebSocket upgrade
                await send({"type": "websocket.close", "code": 4401})
            else:
                response = JSONResponse(
                    {"detail": "Authentication required"}, status_code=401
                )
                await response(scope, receive, send)
            return

        # Stash username for downstream handlers
        scope["auth_username"] = username
        await self.app(scope, receive, send)
