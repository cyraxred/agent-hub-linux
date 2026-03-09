"""Tests for agent_hub.api.routes.hosts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_hub.services.proxy_service import HostConfig, HostSession, ProxyService


def _make_app(proxy: ProxyService | None = None) -> FastAPI:
    """Build a minimal FastAPI app with the hosts router and a mock provider."""
    from agent_hub.api.routes.hosts import router

    if proxy is None:
        proxy = ProxyService()

    provider = MagicMock()
    provider.proxy_service = proxy

    app = FastAPI()
    app.state.provider = provider
    app.include_router(router)
    return app


def _make_connected_session(base_url: str = "http://10.0.0.1:18080") -> HostSession:
    config = HostConfig(
        id="h1", label="Test", kind="direct", base_url=base_url
    )
    mock_session = AsyncMock()
    mock_session.closed = False
    return HostSession(
        config=config,
        http_session=mock_session,
        base_url=base_url,
    )


# ---------------------------------------------------------------------------
# Connect / disconnect / list
# ---------------------------------------------------------------------------


class TestConnectEndpoint:
    def test_connect_direct_success(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        proxy.connect = AsyncMock()
        app = _make_app(proxy)

        with TestClient(app) as client:
            resp = client.post(
                "/api/hosts/connect",
                json={
                    "id": "h1",
                    "label": "Dev Server",
                    "kind": "direct",
                    "base_url": "http://10.0.0.1:18080",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["host_id"] == "h1"
        assert data["connected"] is True
        proxy.connect.assert_awaited_once()

    def test_connect_propagates_backend_error(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        proxy.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        app = _make_app(proxy)

        with TestClient(app) as client:
            resp = client.post(
                "/api/hosts/connect",
                json={
                    "id": "h1",
                    "label": "Bad Host",
                    "kind": "direct",
                    "base_url": "http://255.255.255.255:18080",
                },
            )

        assert resp.status_code == 502

    def test_connect_ssh(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        proxy.connect = AsyncMock()
        app = _make_app(proxy)

        with TestClient(app) as client:
            resp = client.post(
                "/api/hosts/connect",
                json={
                    "id": "h-ssh",
                    "label": "SSH Server",
                    "kind": "ssh",
                    "ssh_host": "10.0.0.2",
                    "ssh_port": 22,
                    "ssh_user": "ubuntu",
                    "ssh_password": "secret",
                    "remote_port": 18080,
                },
            )

        assert resp.status_code == 200
        # Verify the HostConfig passed to connect has the right kind
        call_args = proxy.connect.await_args
        assert call_args is not None
        config: HostConfig = call_args.args[0]
        assert config.kind == "ssh"
        assert config.ssh_host == "10.0.0.2"
        assert config.ssh_password == "secret"


class TestDisconnectEndpoint:
    def test_disconnect_success(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        proxy.disconnect = AsyncMock()
        app = _make_app(proxy)

        with TestClient(app) as client:
            resp = client.post("/api/hosts/h1/disconnect")

        assert resp.status_code == 200
        assert resp.json()["disconnected"] is True
        proxy.disconnect.assert_awaited_once_with("h1")


class TestListConnectedEndpoint:
    def test_empty(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        proxy.connected_ids.return_value = []
        app = _make_app(proxy)

        with TestClient(app) as client:
            resp = client.get("/api/hosts/connected")

        assert resp.status_code == 200
        assert resp.json()["host_ids"] == []

    def test_with_hosts(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        proxy.connected_ids.return_value = ["h1", "h2"]
        app = _make_app(proxy)

        with TestClient(app) as client:
            resp = client.get("/api/hosts/connected")

        assert resp.json()["host_ids"] == ["h1", "h2"]


# ---------------------------------------------------------------------------
# HTTP proxy
# ---------------------------------------------------------------------------


class TestHttpProxy:
    def test_proxy_returns_404_if_not_connected(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        proxy.get.return_value = None
        app = _make_app(proxy)

        with TestClient(app) as client:
            resp = client.get("/api/hosts/ghost/proxy/api/health")

        assert resp.status_code == 404

    def test_proxy_forwards_get_request(self) -> None:
        """A successful GET through the proxy returns the remote response."""
        import aiohttp

        proxy = MagicMock(spec=ProxyService)
        hs = _make_connected_session()
        proxy.get.return_value = hs

        # Build a mock aiohttp response
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b'{"status":"ok"}')
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        session_mock = MagicMock()
        session_mock.request.return_value = mock_resp
        hs.http_session = session_mock

        app = _make_app(proxy)
        with TestClient(app) as client:
            resp = client.get("/api/hosts/h1/proxy/api/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        session_mock.request.assert_called_once()
        call_kwargs = session_mock.request.call_args
        assert call_kwargs.kwargs["method"] == "GET"
        assert "api/health" in call_kwargs.kwargs["url"]

    def test_proxy_forwards_post_with_body(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        hs = _make_connected_session()
        proxy.get.return_value = hs

        mock_resp = AsyncMock()
        mock_resp.status = 201
        mock_resp.read = AsyncMock(return_value=b'{"created":true}')
        mock_resp.headers = {}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        session_mock = MagicMock()
        session_mock.request.return_value = mock_resp
        hs.http_session = session_mock

        app = _make_app(proxy)
        with TestClient(app) as client:
            resp = client.post(
                "/api/hosts/h1/proxy/api/repositories",
                json={"path": "/home/user/proj"},
            )

        assert resp.status_code == 201
        call_kwargs = session_mock.request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["data"] is not None  # body was forwarded

    def test_proxy_strips_hop_by_hop_headers(self) -> None:
        """The proxy must not forward hop-by-hop headers to the remote."""
        proxy = MagicMock(spec=ProxyService)
        hs = _make_connected_session()
        proxy.get.return_value = hs

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"{}")
        mock_resp.headers = {"connection": "keep-alive", "content-type": "application/json"}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        session_mock = MagicMock()
        session_mock.request.return_value = mock_resp
        hs.http_session = session_mock

        app = _make_app(proxy)
        with TestClient(app) as client:
            resp = client.get(
                "/api/hosts/h1/proxy/api/health",
                headers={"connection": "keep-alive", "x-custom": "value"},
            )

        # Forwarded headers should not include hop-by-hop
        call_kwargs = session_mock.request.call_args.kwargs
        forwarded_headers: dict = call_kwargs["headers"]
        assert "connection" not in {k.lower() for k in forwarded_headers}
        assert "x-custom" in {k.lower() for k in forwarded_headers}

    def test_proxy_handles_aiohttp_client_error(self) -> None:
        """If the remote is unreachable, the proxy returns 502."""
        import aiohttp

        proxy = MagicMock(spec=ProxyService)
        hs = _make_connected_session()
        proxy.get.return_value = hs

        session_mock = MagicMock()
        session_mock.request.side_effect = aiohttp.ClientConnectorError(
            MagicMock(), OSError("refused")
        )
        hs.http_session = session_mock

        app = _make_app(proxy)
        with TestClient(app) as client:
            resp = client.get("/api/hosts/h1/proxy/api/health")

        assert resp.status_code == 502

    def test_proxy_passes_query_params(self) -> None:
        proxy = MagicMock(spec=ProxyService)
        hs = _make_connected_session()
        proxy.get.return_value = hs

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"[]")
        mock_resp.headers = {}
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        session_mock = MagicMock()
        session_mock.request.return_value = mock_resp
        hs.http_session = session_mock

        app = _make_app(proxy)
        with TestClient(app) as client:
            client.get("/api/hosts/h1/proxy/api/sessions?provider=claude")

        call_url: str = session_mock.request.call_args.kwargs["url"]
        assert "provider=claude" in call_url
