"""PAM authentication and token management service."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time

from agent_hub.services.metadata_store import AuthTokenRow, MetadataStore

logger = logging.getLogger(__name__)

# Rate limiting: max failures per IP before lockout.
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW = 300  # 5 minutes
_LOCKOUT_DURATION = 900  # 15 minutes


class AuthService:
    """Handles PAM authentication and auth token lifecycle."""

    def __init__(self, metadata_store: MetadataStore) -> None:
        self._store = metadata_store
        self._login_failures: dict[str, list[float]] = {}

    # ------------------------------------------------------------------
    # PAM
    # ------------------------------------------------------------------

    async def authenticate_pam(self, username: str, password: str) -> bool:
        """Validate credentials against system PAM.

        Runs in a thread executor to avoid blocking the event loop.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._pam_check, username, password)

    @staticmethod
    def _pam_check(username: str, password: str) -> bool:
        try:
            import pam  # type: ignore[import-untyped]

            p = pam.pam()
            return bool(p.authenticate(username, password, service="login"))
        except Exception:
            logger.exception("PAM authentication error")
            return False

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def check_rate_limit(self, client_ip: str) -> bool:
        """Return True if the IP is rate-limited (too many failed attempts)."""
        now = time.time()
        failures = self._login_failures.get(client_ip, [])
        # Prune entries older than lockout duration
        failures = [t for t in failures if now - t < _LOCKOUT_DURATION]
        self._login_failures[client_ip] = failures
        recent = [t for t in failures if now - t < _LOCKOUT_WINDOW]
        return len(recent) >= _LOCKOUT_THRESHOLD

    def record_failure(self, client_ip: str) -> None:
        """Record a failed login attempt for rate limiting."""
        self._login_failures.setdefault(client_ip, []).append(time.time())

    # ------------------------------------------------------------------
    # Token CRUD
    # ------------------------------------------------------------------

    async def create_token(self, username: str, client_ip: str) -> str:
        """Create a new auth token bound to the given IP."""
        token = secrets.token_urlsafe(48)
        async with self._store._session_factory() as session:
            row = AuthTokenRow(
                token=token,
                username=username,
                client_ip=client_ip,
            )
            session.add(row)
            await session.commit()
        return token

    async def validate_token(self, token: str, client_ip: str) -> str | None:
        """Validate a token and check IP binding. Returns username or None."""
        async with self._store._session_factory() as session:
            row = await session.get(AuthTokenRow, token)
            if row is None:
                return None
            if row.client_ip != client_ip:
                return None
            return row.username

    async def invalidate_all(self) -> int:
        """Delete all auth tokens. Returns count of deleted tokens."""
        from sqlalchemy import delete

        async with self._store._session_factory() as session:
            result = await session.execute(delete(AuthTokenRow))
            await session.commit()
            return result.rowcount or 0
