"""Proxy service: manages per-host aiohttp sessions for HTTP and WebSocket proxying.

Each remote host gets one persistent ``aiohttp.ClientSession``.  For SSH hosts
the session routes through an ``asyncssh`` port-forward listener bound to a
random localhost port; for direct hosts it uses a plain TCP connector.  The
proxy layer above never needs to know which transport is in use.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class HostConfig:
    """Runtime host configuration sent by the frontend on connect."""

    id: str
    label: str
    kind: Literal["direct", "ssh"]
    # direct
    base_url: str = ""  # e.g. "http://192.168.1.10:18080"
    # ssh
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_password: str = ""   # decrypted by caller before passing here
    ssh_key: str = ""        # PEM content, decrypted by caller
    remote_port: int = 18080


@dataclass
class HostSession:
    """Live state for a connected host."""

    config: HostConfig
    http_session: object  # aiohttp.ClientSession — typed as object to avoid import at module level
    base_url: str         # resolved base URL (may differ from config for SSH hosts)
    ssh_conn: object | None = None    # asyncssh.SSHClientConnection
    ssh_listener: object | None = None  # asyncssh local port forward listener
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ProxyService:
    """Manages one :class:`aiohttp.ClientSession` per connected remote host.

    Thread-safety: all public methods are coroutines and protected by a single
    asyncio lock, so callers can ``await`` them from any task.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, HostSession] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self, config: HostConfig) -> None:
        """Establish a connection to *config* and store the session.

        If a session for the same host ID already exists it is first closed.
        """
        async with self._lock:
            await self._close_locked(config.id)
            host_session = await self._create_session(config)
            self._sessions[config.id] = host_session
            logger.info(
                "ProxyService: connected host %r (%s) at %s",
                config.label,
                config.kind,
                host_session.base_url,
            )

    async def disconnect(self, host_id: str) -> None:
        """Close and remove the session for *host_id*."""
        async with self._lock:
            await self._close_locked(host_id)
            logger.info("ProxyService: disconnected host %r", host_id)

    def get(self, host_id: str) -> HostSession | None:
        """Return the live session for *host_id*, or ``None`` if not connected."""
        return self._sessions.get(host_id)

    def connected_ids(self) -> list[str]:
        """Return a list of currently connected host IDs."""
        return list(self._sessions.keys())

    async def shutdown(self) -> None:
        """Close all sessions (called on application shutdown)."""
        async with self._lock:
            for host_id in list(self._sessions.keys()):
                await self._close_locked(host_id)
        logger.info("ProxyService: all sessions closed")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _close_locked(self, host_id: str) -> None:
        """Close a session — must be called with *self._lock* held."""
        hs = self._sessions.pop(host_id, None)
        if hs is None:
            return
        import aiohttp

        session: aiohttp.ClientSession = hs.http_session  # type: ignore[assignment]
        if not session.closed:
            await session.close()
        if hs.ssh_listener is not None:
            try:
                hs.ssh_listener.close()  # type: ignore[union-attr]
            except Exception:
                pass
        if hs.ssh_conn is not None:
            try:
                hs.ssh_conn.close()  # type: ignore[union-attr]
            except Exception:
                pass

    async def _create_session(self, config: HostConfig) -> HostSession:
        if config.kind == "ssh":
            return await self._create_ssh_session(config)
        return await self._create_direct_session(config)

    async def _create_direct_session(self, config: HostConfig) -> HostSession:
        import aiohttp

        connector = aiohttp.TCPConnector()
        session = aiohttp.ClientSession(connector=connector)
        return HostSession(
            config=config,
            http_session=session,
            base_url=config.base_url.rstrip("/"),
        )

    async def _create_ssh_session(self, config: HostConfig) -> HostSession:
        import aiohttp
        import asyncssh  # type: ignore[import-untyped]

        connect_kwargs: dict[str, object] = {
            "host": config.ssh_host,
            "port": config.ssh_port,
            "username": config.ssh_user or None,
            "known_hosts": None,  # trust-on-first-use
        }
        if config.ssh_password:
            connect_kwargs["password"] = config.ssh_password
        if config.ssh_key:
            connect_kwargs["client_keys"] = [
                asyncssh.import_private_key(config.ssh_key)
            ]

        ssh_conn = await asyncssh.connect(**connect_kwargs)

        # Bind a local port that forwards to the remote backend
        listener = await ssh_conn.forward_local_port(
            "",                  # bind on localhost
            0,                   # OS-assigned port
            "127.0.0.1",
            config.remote_port,
        )
        local_port: int = listener.get_port()
        base_url = f"http://127.0.0.1:{local_port}"

        connector = aiohttp.TCPConnector()
        session = aiohttp.ClientSession(connector=connector)

        return HostSession(
            config=config,
            http_session=session,
            base_url=base_url,
            ssh_conn=ssh_conn,
            ssh_listener=listener,
        )
