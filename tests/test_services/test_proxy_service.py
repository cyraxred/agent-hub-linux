"""Tests for agent_hub.services.proxy_service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_hub.services.proxy_service import HostConfig, HostSession, ProxyService


def _direct_config(host_id: str = "host-1", base_url: str = "http://10.0.0.1:18080") -> HostConfig:
    return HostConfig(id=host_id, label="Test", kind="direct", base_url=base_url)


def _ssh_config(host_id: str = "host-ssh") -> HostConfig:
    return HostConfig(
        id=host_id,
        label="SSH Host",
        kind="ssh",
        ssh_host="10.0.0.2",
        ssh_port=22,
        ssh_user="ubuntu",
        ssh_password="secret",
        remote_port=18080,
    )


class TestProxyServiceDirect:
    """Tests for direct (TCP) host connections."""

    @pytest.mark.asyncio
    async def test_connect_direct_creates_session(self) -> None:
        """Connecting a direct host creates an aiohttp.ClientSession."""
        import aiohttp

        svc = ProxyService()
        with patch("aiohttp.TCPConnector") as mock_connector_cls, \
             patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_session_cls.return_value = mock_session

            config = _direct_config()
            await svc.connect(config)

        hs = svc.get("host-1")
        assert hs is not None
        assert hs.config is config
        assert hs.base_url == "http://10.0.0.1:18080"
        assert hs.ssh_conn is None

    @pytest.mark.asyncio
    async def test_connect_strips_trailing_slash(self) -> None:
        svc = ProxyService()
        with patch("aiohttp.TCPConnector"), \
             patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_session_cls.return_value = mock_session

            await svc.connect(_direct_config(base_url="http://10.0.0.1:18080/"))

        hs = svc.get("host-1")
        assert hs is not None
        assert hs.base_url == "http://10.0.0.1:18080"

    @pytest.mark.asyncio
    async def test_get_unknown_host_returns_none(self) -> None:
        svc = ProxyService()
        assert svc.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_connected_ids_empty_initially(self) -> None:
        svc = ProxyService()
        assert svc.connected_ids() == []

    @pytest.mark.asyncio
    async def test_connected_ids_after_connect(self) -> None:
        svc = ProxyService()
        with patch("aiohttp.TCPConnector"), \
             patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_session_cls.return_value = mock_session
            await svc.connect(_direct_config("h1"))
            await svc.connect(_direct_config("h2", "http://10.0.0.2:18080"))

        assert set(svc.connected_ids()) == {"h1", "h2"}

    @pytest.mark.asyncio
    async def test_disconnect_removes_session(self) -> None:
        svc = ProxyService()
        with patch("aiohttp.TCPConnector"), \
             patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.closed = False
            mock_session_cls.return_value = mock_session
            await svc.connect(_direct_config())

        await svc.disconnect("host-1")
        assert svc.get("host-1") is None
        assert svc.connected_ids() == []

    @pytest.mark.asyncio
    async def test_disconnect_unknown_host_is_noop(self) -> None:
        """Disconnecting a host that was never connected should not raise."""
        svc = ProxyService()
        await svc.disconnect("ghost")  # should not raise

    @pytest.mark.asyncio
    async def test_reconnect_closes_old_session(self) -> None:
        """Connecting to the same host ID twice closes the previous session."""
        svc = ProxyService()
        closed_sessions: list[MagicMock] = []

        with patch("aiohttp.TCPConnector"):
            with patch("aiohttp.ClientSession") as mock_session_cls:
                def make_session(*_a: object, **_kw: object) -> MagicMock:
                    s = AsyncMock()
                    s.closed = False
                    closed_sessions.append(s)
                    return s

                mock_session_cls.side_effect = make_session
                await svc.connect(_direct_config())
                await svc.connect(_direct_config())

        # The first session should have been closed
        assert closed_sessions[0].close.called

    @pytest.mark.asyncio
    async def test_shutdown_closes_all_sessions(self) -> None:
        svc = ProxyService()
        sessions: list[AsyncMock] = []

        with patch("aiohttp.TCPConnector"):
            with patch("aiohttp.ClientSession") as mock_session_cls:
                def make_session(*_a: object, **_kw: object) -> AsyncMock:
                    s = AsyncMock()
                    s.closed = False
                    sessions.append(s)
                    return s

                mock_session_cls.side_effect = make_session
                await svc.connect(_direct_config("h1"))
                await svc.connect(_direct_config("h2", "http://10.0.0.2:18080"))

        await svc.shutdown()
        assert svc.connected_ids() == []
        for s in sessions:
            assert s.close.called


class TestProxyServiceSSH:
    """Tests for SSH host connections (asyncssh mocked)."""

    @pytest.mark.asyncio
    async def test_connect_ssh_binds_local_port(self) -> None:
        """SSH connect should bind a local port via asyncssh.forward_local_port."""
        svc = ProxyService()
        mock_listener = MagicMock()
        mock_listener.get_port.return_value = 54321
        mock_ssh_conn = AsyncMock()
        mock_ssh_conn.forward_local_port = AsyncMock(return_value=mock_listener)

        with patch("asyncssh.connect", new=AsyncMock(return_value=mock_ssh_conn)), \
             patch("aiohttp.TCPConnector"), \
             patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session_cls.return_value = MagicMock(closed=False)
            await svc.connect(_ssh_config())

        hs = svc.get("host-ssh")
        assert hs is not None
        assert hs.base_url == "http://127.0.0.1:54321"
        assert hs.ssh_conn is mock_ssh_conn
        assert hs.ssh_listener is mock_listener

    @pytest.mark.asyncio
    async def test_connect_ssh_password_auth(self) -> None:
        """SSH connect with password passes it to asyncssh.connect."""
        svc = ProxyService()
        mock_listener = MagicMock()
        mock_listener.get_port.return_value = 12345
        mock_ssh_conn = AsyncMock()
        mock_ssh_conn.forward_local_port = AsyncMock(return_value=mock_listener)

        connect_kwargs_captured: dict = {}

        async def fake_connect(**kwargs: object) -> object:
            connect_kwargs_captured.update(kwargs)
            return mock_ssh_conn

        with patch("asyncssh.connect", side_effect=fake_connect), \
             patch("aiohttp.TCPConnector"), \
             patch("aiohttp.ClientSession", return_value=MagicMock(closed=False)):
            config = _ssh_config()
            config.ssh_password = "mysecret"
            await svc.connect(config)

        assert connect_kwargs_captured.get("password") == "mysecret"

    @pytest.mark.asyncio
    async def test_connect_ssh_key_auth(self) -> None:
        """SSH connect with key content imports the key and passes client_keys."""
        svc = ProxyService()
        mock_listener = MagicMock()
        mock_listener.get_port.return_value = 12345
        mock_ssh_conn = AsyncMock()
        mock_ssh_conn.forward_local_port = AsyncMock(return_value=mock_listener)

        connect_kwargs_captured: dict = {}

        async def fake_connect(**kwargs: object) -> object:
            connect_kwargs_captured.update(kwargs)
            return mock_ssh_conn

        fake_key = MagicMock()
        with patch("asyncssh.connect", side_effect=fake_connect), \
             patch("asyncssh.import_private_key", return_value=fake_key), \
             patch("aiohttp.TCPConnector"), \
             patch("aiohttp.ClientSession", return_value=MagicMock(closed=False)):
            config = _ssh_config()
            config.ssh_key = "-----BEGIN OPENSSH PRIVATE KEY-----\n..."
            config.ssh_password = ""
            await svc.connect(config)

        assert "client_keys" in connect_kwargs_captured
        assert connect_kwargs_captured["client_keys"] == [fake_key]

    @pytest.mark.asyncio
    async def test_disconnect_ssh_closes_tunnel_and_conn(self) -> None:
        """Disconnecting an SSH host closes the listener and SSH connection."""
        svc = ProxyService()
        mock_listener = MagicMock()
        mock_listener.get_port.return_value = 12345
        mock_ssh_conn = MagicMock()
        mock_ssh_conn.forward_local_port = AsyncMock(return_value=mock_listener)

        with patch("asyncssh.connect", new=AsyncMock(return_value=mock_ssh_conn)), \
             patch("aiohttp.TCPConnector"), \
             patch("aiohttp.ClientSession", return_value=AsyncMock(closed=False)):
            await svc.connect(_ssh_config())

        await svc.disconnect("host-ssh")
        mock_listener.close.assert_called_once()
        mock_ssh_conn.close.assert_called_once()
        assert svc.get("host-ssh") is None

    @pytest.mark.asyncio
    async def test_connect_ssh_failure_raises(self) -> None:
        """If asyncssh.connect raises, the error propagates and no session is stored."""
        svc = ProxyService()
        with patch("asyncssh.connect", side_effect=ConnectionRefusedError("refused")):
            with pytest.raises(ConnectionRefusedError):
                await svc.connect(_ssh_config())

        assert svc.get("host-ssh") is None
